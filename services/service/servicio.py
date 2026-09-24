"""Lógica de casos y relojes de SLA (CRM-04.01.01, CRM-04.01.02).

Lo que gobierna este módulo, y de lo que sale todo lo demás: **un SLA que no se
puede explicar no se puede exigir**. De ahí que los vencimientos se guarden
calculados, que las pausas se acumulen, y que incumplir la primera respuesta se
distinga de incumplir la resolución.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.datos.calendario import CalendarioLaboral, sumar_horas_laborables
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.logging import get_logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.service.modelos import Caso, CategoriaCaso, DefinicionSLA, EventoCaso

logger = get_logger(__name__)

# Estados en los que el reloj de resolución **no** corre. Es una lista y no un
# booleano en el estado porque quién para el reloj es una decisión de negocio que
# cambia por cliente: hay contratos donde «esperando repuesto» para el reloj y
# otros donde no.
ESTADOS_PAUSA = ("esperando_cliente",)
ESTADOS_TERMINALES = ("resuelto", "cerrado")

PRIORIDADES = ("baja", "media", "alta", "critica")
SEVERIDADES = ("baja", "media", "alta", "critica")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


# ── Taxonomía (CRM-04.01.01.02) ───────────────────────────────────────────


def categoria(db: Session, tenant_id: UUID, categoria_id: UUID) -> CategoriaCaso:
    fila = db.execute(
        select(CategoriaCaso).where(
            CategoriaCaso.id == categoria_id, CategoriaCaso.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("La categoría no existe", error_code="service.categoria_no_encontrada")
    return fila


def ruta_de_categoria(db: Session, tenant_id: UUID, categoria_id: UUID) -> list[str]:
    """El camino desde la raíz hasta la hoja.

    Se devuelve la ruta y no solo la hoja porque los informes agrupan por nivel:
    «cuántos casos de software» no se puede contestar si solo se guarda
    «error de instalación» sin saber de qué cuelga.
    """
    ruta: list[str] = []
    actual: UUID | None = categoria_id
    vistos: set[UUID] = set()
    while actual is not None and actual not in vistos:
        vistos.add(actual)
        fila = db.get(CategoriaCaso, actual)
        if fila is None or fila.tenant_id != tenant_id:
            break
        ruta.append(fila.nombre)
        actual = fila.padre_id
    return list(reversed(ruta))


def arbol_de_categorias(db: Session, tenant_id: UUID, linea: str = "") -> list[dict[str, Any]]:
    consulta = select(CategoriaCaso).where(
        CategoriaCaso.tenant_id == tenant_id, CategoriaCaso.activa.is_(True)
    )
    if linea:
        consulta = consulta.where(CategoriaCaso.linea == linea)
    filas = db.execute(consulta.order_by(CategoriaCaso.orden, CategoriaCaso.nombre)).scalars().all()
    # El nombre de la categoría padre, no solo su identificador: en la pantalla,
    # «padre: 01a0cfbd-…» no dice de qué cuelga esta categoría, y saberlo es lo
    # único para lo que sirve la columna.
    nombres = {f.id: f.nombre for f in filas}
    return [
        {
            "id": str(f.id),
            "padre_id": str(f.padre_id) if f.padre_id else None,
            "padre": nombres.get(f.padre_id, "") if f.padre_id else "",
            "linea": f.linea,
            "clave": f.clave,
            "nombre": f.nombre,
            "seleccionable": f.seleccionable,
            "prioridad_sugerida": f.prioridad_sugerida,
        }
        for f in filas
    ]


def _exigir_hoja(db: Session, tenant_id: UUID, categoria_id: UUID) -> CategoriaCaso:
    """Solo las hojas clasifican.

    Dejar elegir un nodo intermedio convierte «software» en un cajón donde acaba
    la mitad de los casos, y entonces la taxonomía no sirve para lo único que
    sirve: agrupar.
    """
    fila = categoria(db, tenant_id, categoria_id)
    if not fila.seleccionable:
        raise ErrorValidacion(
            f"«{fila.nombre}» es un nivel intermedio y no se puede elegir. "
            "Clasifica en una de sus hojas.",
            error_code="service.categoria_no_seleccionable",
        )
    hijas = db.execute(
        select(func.count())
        .select_from(CategoriaCaso)
        .where(CategoriaCaso.padre_id == fila.id, CategoriaCaso.activa.is_(True))
    ).scalar_one()
    if hijas:
        raise ErrorValidacion(
            f"«{fila.nombre}» tiene subcategorías: clasifica en una de ellas.",
            error_code="service.categoria_no_es_hoja",
        )
    return fila


# ── SLA aplicable (CRM-04.01.02.02) ───────────────────────────────────────


def sla_aplicable(
    db: Session,
    tenant_id: UUID,
    *,
    prioridad: str,
    tier_cliente: str = "",
    cuenta_id: UUID | None = None,
    en_fecha: date | None = None,
) -> DefinicionSLA | None:
    """La definición que le toca a este caso, la más específica.

    Gana lo más concreto: un SLA nominal para una cuenta manda sobre el del tier,
    y el del tier sobre el general. Al revés —o cogiendo el primero que
    encaje— un cliente con contrato especial recibiría el trato estándar, que es
    justo el que se paga por no tener.
    """
    en_fecha = en_fecha or date.today()
    filas = (
        db.execute(
            select(DefinicionSLA).where(
                DefinicionSLA.tenant_id == tenant_id,
                DefinicionSLA.activa.is_(True),
                DefinicionSLA.vigente_desde <= en_fecha,
            )
        )
        .scalars()
        .all()
    )
    candidatas = [
        f
        for f in filas
        if (f.vigente_hasta is None or f.vigente_hasta >= en_fecha)
        and (f.prioridad is None or f.prioridad == prioridad)
        and (f.tier_cliente is None or f.tier_cliente == tier_cliente)
        and (f.cuenta_id is None or f.cuenta_id == cuenta_id)
    ]
    if not candidatas:
        return None

    def _especificidad(f: DefinicionSLA) -> tuple[int, int]:
        puntos = (
            (100 if f.cuenta_id is not None else 0)
            + (10 if f.tier_cliente is not None else 0)
            + (1 if f.prioridad is not None else 0)
        )
        # Ante dos igual de específicas gana la versión más alta: es la que
        # alguien publicó después, y publicar una versión nueva es la forma de
        # decir «a partir de ahora, esta».
        return (puntos, f.version)

    return max(candidatas, key=_especificidad)


def _calendario(db: Session, tenant_id: UUID, clave: str) -> CalendarioLaboral | None:
    consulta = select(CalendarioLaboral).where(CalendarioLaboral.tenant_id == tenant_id)
    if clave:
        consulta = consulta.where(CalendarioLaboral.clave == clave)
    else:
        consulta = consulta.where(CalendarioLaboral.por_defecto.is_(True))
    return db.execute(consulta.limit(1)).scalar_one_or_none()


def _vencimiento(
    db: Session, tenant_id: UUID, desde: datetime, horas: Any, calendario_clave: str
) -> datetime | None:
    """Cuándo vence un plazo de horas **laborables**.

    Si no hay calendario, se cuenta en horas de reloj y **se avisa**: no es lo
    mismo, y dejar que parezca lo mismo es cómo un SLA de «4 horas» acaba
    venciendo un domingo de madrugada sin que nadie lo entienda.
    """
    if horas is None:
        return None
    horas_f = float(horas if not isinstance(horas, Decimal) else horas)
    calendario = _calendario(db, tenant_id, calendario_clave)
    if calendario is None:
        logger.warning(
            "service.sla_sin_calendario",
            tenant=str(tenant_id),
            calendario=calendario_clave or "(por defecto)",
        )
        return desde + timedelta(hours=horas_f)
    return sumar_horas_laborables(db, calendario, desde, horas_f)


def aplicar_sla(db: Session, caso: Caso, *, tier_cliente: str = "") -> DefinicionSLA | None:
    """Fija los vencimientos del caso según el SLA que le toque.

    Los vencimientos se **guardan calculados**. Recalcularlos al consultar haría
    que cambiar la definición del SLA reescribiera el pasado: un contrato
    renegociado convertiría en incumplidos casos que se atendieron a tiempo con
    las reglas de entonces.
    """
    definicion = sla_aplicable(
        db,
        caso.tenant_id,
        prioridad=caso.prioridad,
        tier_cliente=tier_cliente,
        cuenta_id=caso.cuenta_id,
    )
    if definicion is None:
        caso.sla_clave = None
        caso.sla_version = None
        caso.vence_primera_respuesta_at = None
        caso.vence_resolucion_at = None
        return None

    desde = _con_tz(caso.created_at) or _ahora()
    caso.sla_clave = definicion.clave
    caso.sla_version = definicion.version
    caso.vence_primera_respuesta_at = _vencimiento(
        db, caso.tenant_id, desde, definicion.horas_primera_respuesta, definicion.calendario
    )
    caso.vence_resolucion_at = _vencimiento(
        db, caso.tenant_id, desde, definicion.horas_resolucion, definicion.calendario
    )
    return definicion


# ── Alta y ciclo de vida ──────────────────────────────────────────────────


def _siguiente_codigo(db: Session, tenant_id: UUID) -> str:
    anio = date.today().year
    cuantos = int(
        db.execute(
            select(func.count()).select_from(Caso).where(Caso.tenant_id == tenant_id)
        ).scalar_one()
        or 0
    )
    return f"CAS-{anio}-{cuantos + 1:05d}"


def _anotar(db: Session, caso: Caso, tipo: str, **detalle: Any) -> EventoCaso:
    fila = EventoCaso(
        tenant_id=caso.tenant_id,
        caso_id=caso.id,
        tipo=tipo,
        detalle=detalle,
        por=caso.updated_by or caso.created_by,
    )
    db.add(fila)
    return fila


def abrir_caso(
    uow: UnidadDeTrabajo,
    *,
    asunto: str,
    tier_cliente: str = "",
    **datos: Any,
) -> Caso:
    """Da de alta un caso y le pone su reloj."""
    tenant_id = uow.tenant_id
    if tenant_id is None:
        raise ErrorValidacion("Falta el tenant", error_code="service.sin_tenant")

    categoria_id = datos.get("categoria_id")
    sugerida = None
    if categoria_id:
        hoja = _exigir_hoja(uow.db, tenant_id, categoria_id)
        sugerida = hoja.prioridad_sugerida
        datos.setdefault("linea", hoja.linea)

    prioridad = str(datos.pop("prioridad", "") or sugerida or "media")
    if prioridad not in PRIORIDADES:
        raise ErrorValidacion(
            f"Prioridad «{prioridad}» no válida.",
            error_code="service.prioridad_no_valida",
            detalle={"validas": list(PRIORIDADES)},
        )
    severidad = str(datos.pop("severidad", "") or "media")
    if severidad not in SEVERIDADES:
        raise ErrorValidacion(
            f"Severidad «{severidad}» no válida.",
            error_code="service.severidad_no_valida",
            detalle={"validas": list(SEVERIDADES)},
        )

    if "campos" in datos:
        from crmcore import metamodelo

        datos["campos"] = metamodelo.validar_y_anotar(uow.db, tenant_id, "caso", datos["campos"])

    caso = Caso(
        tenant_id=tenant_id,
        asunto=asunto.strip(),
        codigo=_siguiente_codigo(uow.db, tenant_id),
        prioridad=prioridad,
        severidad=severidad,
        **datos,
    )
    uow.db.add(caso)
    uow.db.flush()

    aplicar_sla(uow.db, caso, tier_cliente=tier_cliente)
    _anotar(uow.db, caso, "abierto", prioridad=prioridad, severidad=severidad)
    registrar(
        uow.db,
        accion="caso.abierto",
        objeto="caso",
        objeto_id=caso.id,
        datos={"codigo": caso.codigo, "prioridad": prioridad, "sla": caso.sla_clave},
        tenant_id=tenant_id,
    )
    uow.emitir(
        "case.created",
        subject=("caso", caso.id),
        data={
            "caso_id": str(caso.id),
            "codigo": caso.codigo or "",
            "prioridad": prioridad,
            "cuenta_id": str(caso.cuenta_id) if caso.cuenta_id else "",
            "campos": dict(caso.campos or {}),
        },
    )
    return caso


def exigir_caso(db: Session, caso_id: UUID) -> Caso:
    caso = db.get(Caso, caso_id)
    if caso is None or caso.deleted_at is not None:
        raise NoEncontrado("El caso no existe", error_code="service.caso_no_encontrado")
    return caso


def registrar_primera_respuesta(
    uow: UnidadDeTrabajo, caso_id: UUID, *, por: UUID | None = None
) -> Caso:
    """Marca la primera respuesta y decide si se cumplió el plazo.

    Solo la primera cuenta: registrar cada respuesta como «primera» haría que el
    indicador midiera la última, que es el número que siempre sale bien.
    """
    caso = exigir_caso(uow.db, caso_id)
    if caso.primera_respuesta_at is not None:
        return caso

    ahora = _ahora()
    caso.primera_respuesta_at = ahora
    vence = _con_tz(caso.vence_primera_respuesta_at)
    if vence is not None and ahora > vence:
        caso.incumplio_primera_respuesta = True
    _anotar(
        uow.db,
        caso,
        "primera_respuesta",
        a_tiempo=not caso.incumplio_primera_respuesta,
        por=str(por) if por else None,
    )
    uow.emitir(
        "case.first_response",
        subject=("caso", caso.id),
        data={
            "caso_id": str(caso.id),
            "a_tiempo": not caso.incumplio_primera_respuesta,
        },
    )
    return caso


def cambiar_estado(uow: UnidadDeTrabajo, caso_id: UUID, *, estado: str, motivo: str = "") -> Caso:
    """Mueve el caso de estado y para o reanuda el reloj.

    La pausa se **acumula** en vez de guardarse solo el último tramo: un caso que
    entra y sale de «esperando cliente» cuatro veces perdería tres de las cuatro
    esperas, y el tiempo de resolución saldría peor de lo que fue — lo que acaba
    en una discusión con el cliente que no se puede ganar sin el dato.
    """
    caso = exigir_caso(uow.db, caso_id)
    if estado == caso.estado:
        return caso

    ahora = _ahora()
    estaba_en_pausa = caso.estado in ESTADOS_PAUSA
    entra_en_pausa = estado in ESTADOS_PAUSA

    if estaba_en_pausa and not entra_en_pausa and caso.pausado_desde is not None:
        parado = int((ahora - _con_tz(caso.pausado_desde)).total_seconds())
        caso.pausa_acumulada_s += max(0, parado)
        caso.pausado_desde = None
        # El vencimiento se **desplaza** por el tiempo parado. Si no, parar el
        # reloj sería decorativo: el caso se marcaría incumplido por una espera
        # que era del cliente.
        if caso.vence_resolucion_at is not None:
            caso.vence_resolucion_at = _con_tz(caso.vence_resolucion_at) + timedelta(seconds=parado)
    elif entra_en_pausa and not estaba_en_pausa:
        caso.pausado_desde = ahora

    anterior = caso.estado
    caso.estado = estado
    if estado == "resuelto" and caso.resuelto_at is None:
        caso.resuelto_at = ahora
        vence = _con_tz(caso.vence_resolucion_at)
        if vence is not None and ahora > vence:
            caso.incumplio_resolucion = True
    _anotar(uow.db, caso, "estado", desde=anterior, hasta=estado, motivo=motivo or None)
    return caso


def cerrar_caso(
    uow: UnidadDeTrabajo,
    caso_id: UUID,
    *,
    motivo: str,
    resolucion: str = "",
    exige_validacion: bool = False,
) -> Caso:
    """Cierra el caso con un motivo tipificado (CRM-04.01.01.09).

    El motivo es **obligatorio**. Sin él, el informe de cierres dice cuántos se
    cerraron y no por qué, que es la única parte útil: «resuelto», «no era un
    problema» y «el cliente no contestó» llevan a tres decisiones distintas.
    """
    if not (motivo or "").strip():
        raise ErrorValidacion(
            "Cerrar un caso exige un motivo tipificado.",
            error_code="service.cierre_sin_motivo",
        )
    caso = exigir_caso(uow.db, caso_id)
    if caso.estado == "cerrado":
        raise Conflicto("El caso ya está cerrado", error_code="service.caso_ya_cerrado")

    ahora = _ahora()
    if caso.resuelto_at is None:
        caso.resuelto_at = ahora
        vence = _con_tz(caso.vence_resolucion_at)
        if vence is not None and ahora > vence:
            caso.incumplio_resolucion = True
    caso.estado = "cerrado"
    caso.cerrado_at = ahora
    caso.motivo_cierre = motivo
    caso.resolucion = resolucion or caso.resolucion
    caso.validacion_cliente = "pendiente" if exige_validacion else None

    _anotar(uow.db, caso, "cerrado", motivo=motivo, validacion=caso.validacion_cliente)
    registrar(
        uow.db,
        accion="caso.cerrado",
        objeto="caso",
        objeto_id=caso.id,
        datos={
            "motivo": motivo,
            "incumplio_resolucion": caso.incumplio_resolucion,
            "horas_abierto": round(
                (ahora - (_con_tz(caso.created_at) or ahora)).total_seconds() / 3600, 2
            ),
        },
        tenant_id=caso.tenant_id,
    )
    uow.emitir(
        "case.closed",
        subject=("caso", caso.id),
        data={
            "caso_id": str(caso.id),
            "motivo": motivo,
            "incumplio_resolucion": caso.incumplio_resolucion,
            "cuenta_id": str(caso.cuenta_id) if caso.cuenta_id else "",
        },
    )
    return caso


def reabrir_caso(
    uow: UnidadDeTrabajo, caso_id: UUID, *, motivo: str, ventana_dias: int | None = None
) -> Caso:
    """Reabre un caso cerrado dentro de la ventana configurada
    (CRM-04.01.01.10).

    Pasada la ventana **no se reabre**: se abre uno nuevo enlazado. Reabrir un
    caso de hace ocho meses falsea todos los indicadores del periodo en que se
    cerró —tiempo de resolución, cumplimiento de SLA, casos cerrados— y esos
    números ya están en un informe que alguien miró.
    """
    if not (motivo or "").strip():
        raise ErrorValidacion(
            "Reabrir exige un motivo escrito.", error_code="service.reapertura_sin_motivo"
        )
    caso = exigir_caso(uow.db, caso_id)
    if caso.estado != "cerrado":
        raise Conflicto("El caso no está cerrado", error_code="service.caso_no_cerrado")

    from crmcore.runtime import settings as rt

    dias = (
        ventana_dias
        if ventana_dias is not None
        else int(rt.efectivo("caso_reapertura_dias", uow.db) or 0)
    )
    cerrado = _con_tz(caso.cerrado_at) or _ahora()
    if dias > 0 and (_ahora() - cerrado) > timedelta(days=dias):
        raise Conflicto(
            f"Han pasado más de {dias} días desde el cierre. Abre un caso nuevo "
            "enlazado a este: reabrirlo falsearía los indicadores del periodo en "
            "que se cerró.",
            error_code="service.fuera_de_ventana_de_reapertura",
            detalle={"ventana_dias": dias, "cerrado_at": cerrado.isoformat()},
        )

    caso.estado = "en_curso"
    caso.cerrado_at = None
    caso.resuelto_at = None
    caso.reaperturas += 1
    caso.validacion_cliente = None
    _anotar(uow.db, caso, "reabierto", motivo=motivo, reaperturas=caso.reaperturas)
    registrar(
        uow.db,
        accion="caso.reabierto",
        objeto="caso",
        objeto_id=caso.id,
        datos={"motivo": motivo, "reaperturas": caso.reaperturas},
        tenant_id=caso.tenant_id,
    )
    return caso


# ── Jerarquía e incidencias masivas (CRM-04.01.01.04, .11) ────────────────


def enlazar_a_maestro(uow: UnidadDeTrabajo, caso_id: UUID, maestro_id: UUID) -> Caso:
    """Cuelga un caso de un maestro de incidencia masiva.

    Cien casos que son la misma caída se cuelgan de uno: se investiga una vez y
    se cierran juntos. Cerrarlos uno a uno no solo es trabajo, es que la
    respuesta que recibe cada cliente acaba siendo distinta.
    """
    caso = exigir_caso(uow.db, caso_id)
    maestro = exigir_caso(uow.db, maestro_id)
    if maestro.id == caso.id:
        raise ErrorValidacion(
            "Un caso no puede ser su propio maestro.", error_code="service.maestro_de_si_mismo"
        )
    if maestro.maestro_id is not None:
        # Un maestro que cuelga de otro maestro deja una cadena que nadie sabe
        # cerrar: se aplana a propósito.
        raise ErrorValidacion(
            "Ese caso ya cuelga de otro maestro. Enlaza directamente al maestro raíz.",
            error_code="service.maestro_encadenado",
            detalle={"maestro_raiz": str(maestro.maestro_id)},
        )
    caso.maestro_id = maestro.id
    _anotar(uow.db, caso, "enlazado_a_maestro", maestro=str(maestro.id))
    return caso


def cerrar_masiva(
    uow: UnidadDeTrabajo, maestro_id: UUID, *, motivo: str, resolucion: str = ""
) -> dict[str, Any]:
    """Cierra el maestro y todos los casos colgados de él."""
    maestro = exigir_caso(uow.db, maestro_id)
    hijos = (
        uow.db.execute(
            select(Caso).where(
                Caso.tenant_id == maestro.tenant_id,
                Caso.maestro_id == maestro.id,
                Caso.estado != "cerrado",
                Caso.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    cerrados = []
    for hijo in hijos:
        cerrar_caso(uow, hijo.id, motivo=motivo, resolucion=resolucion)
        cerrados.append(str(hijo.id))
    if maestro.estado != "cerrado":
        cerrar_caso(uow, maestro.id, motivo=motivo, resolucion=resolucion)
    return {"maestro": str(maestro.id), "cerrados": cerrados, "cuantos": len(cerrados)}


def marcar_duplicado(uow: UnidadDeTrabajo, caso_id: UUID, original_id: UUID) -> Caso:
    """Marca un caso como duplicado de otro, sin borrarlo.

    No se borra porque el cliente que lo abrió tiene derecho a ver su caso y su
    respuesta. Borrarlo hace que su referencia deje de existir, y entonces quien
    pregunta por ella recibe un «no existe» que suena a que nadie le atendió.
    """
    caso = exigir_caso(uow.db, caso_id)
    original = exigir_caso(uow.db, original_id)
    if original.id == caso.id:
        raise ErrorValidacion(
            "Un caso no puede ser duplicado de sí mismo.",
            error_code="service.duplicado_de_si_mismo",
        )
    caso.duplicado_de_id = original.id
    caso.estado = "cerrado"
    caso.cerrado_at = _ahora()
    caso.motivo_cierre = "duplicado"
    _anotar(uow.db, caso, "duplicado", original=str(original.id))
    return caso


def arbol_de_caso(db: Session, tenant_id: UUID, caso_id: UUID) -> dict[str, Any]:
    caso = exigir_caso(db, caso_id)
    hijos = (
        db.execute(
            select(Caso).where(
                Caso.tenant_id == tenant_id, Caso.padre_id == caso.id, Caso.deleted_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    colgados = (
        db.execute(
            select(Caso).where(
                Caso.tenant_id == tenant_id, Caso.maestro_id == caso.id, Caso.deleted_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    return {
        "caso": str(caso.id),
        "padre": str(caso.padre_id) if caso.padre_id else None,
        "hijos": [{"id": str(h.id), "asunto": h.asunto, "estado": h.estado} for h in hijos],
        "colgados_del_maestro": [
            {"id": str(h.id), "asunto": h.asunto, "estado": h.estado} for h in colgados
        ],
        "duplicado_de": str(caso.duplicado_de_id) if caso.duplicado_de_id else None,
    }


# ── Riesgo de incumplimiento (CRM-04.01.02.05) ────────────────────────────


def en_riesgo(db: Session, tenant_id: UUID, *, umbral_pct: int = 80) -> list[dict[str, Any]]:
    """Casos que van a incumplir si nadie hace nada.

    Avisar **cuando ya se ha incumplido** no sirve para nada: el incumplimiento
    ya está. Lo único que cambia algo es avisar antes, y por eso el umbral es
    parte del SLA y no una constante.

    Se ordena por lo que **queda**, no por prioridad: un caso crítico con seis
    horas por delante puede esperar a uno medio que vence en diez minutos.
    """
    ahora = _ahora()
    abiertos = (
        db.execute(
            select(Caso).where(
                Caso.tenant_id == tenant_id,
                Caso.estado.not_in(ESTADOS_TERMINALES),
                Caso.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )

    salida: list[dict[str, Any]] = []
    for caso in abiertos:
        for reloj, vence_at, cumplido in (
            ("primera_respuesta", caso.vence_primera_respuesta_at, caso.primera_respuesta_at),
            ("resolucion", caso.vence_resolucion_at, caso.resuelto_at),
        ):
            vence = _con_tz(vence_at)
            if vence is None or cumplido is not None:
                continue
            inicio = _con_tz(caso.created_at) or ahora
            total = (vence - inicio).total_seconds()
            if total <= 0:
                continue
            consumido = (ahora - inicio).total_seconds()
            pct = round(100 * consumido / total, 1)
            if pct < umbral_pct:
                continue
            salida.append(
                {
                    "caso_id": str(caso.id),
                    "codigo": caso.codigo,
                    "asunto": caso.asunto,
                    "prioridad": caso.prioridad,
                    "reloj": reloj,
                    "vence_at": vence.isoformat(),
                    "minutos_restantes": int((vence - ahora).total_seconds() // 60),
                    "consumido_pct": pct,
                    # Se distingue lo que aún se puede salvar de lo ya perdido:
                    # mezclarlos hace que la lista de «en riesgo» se llene de
                    # cosas que ya no tienen remedio y deje de mirarse.
                    "ya_incumplido": ahora > vence,
                }
            )

    salida.sort(key=lambda c: c["minutos_restantes"])
    return salida


def cumplimiento(db: Session, tenant_id: UUID, *, desde: date, hasta: date) -> dict[str, Any]:
    """Cumplimiento de SLA del periodo.

    Se cuentan aparte la primera respuesta y la resolución porque son dos
    compromisos distintos, y un porcentaje único esconde que se contesta rápido y
    se resuelve tarde — que es el patrón más común y el que más queja genera.
    """
    casos = (
        db.execute(
            select(Caso).where(
                Caso.tenant_id == tenant_id,
                Caso.created_at
                >= datetime.combine(desde, datetime.min.time(), tzinfo=timezone.utc),
                Caso.created_at
                <= datetime.combine(hasta, datetime.max.time(), tzinfo=timezone.utc),
                Caso.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    con_pr = [c for c in casos if c.vence_primera_respuesta_at is not None]
    con_res = [c for c in casos if c.vence_resolucion_at is not None]

    def _pct(total: list[Caso], incumplidos: int) -> float | None:
        # Sin casos no se dice 100 %: sería un verde que nadie se ha ganado.
        return round(100 * (len(total) - incumplidos) / len(total), 1) if total else None

    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "casos": len(casos),
        "sin_sla": len([c for c in casos if c.sla_clave is None]),
        "primera_respuesta": {
            "con_compromiso": len(con_pr),
            "incumplidos": len([c for c in con_pr if c.incumplio_primera_respuesta]),
            "cumplimiento_pct": _pct(
                con_pr, len([c for c in con_pr if c.incumplio_primera_respuesta])
            ),
        },
        "resolucion": {
            "con_compromiso": len(con_res),
            "incumplidos": len([c for c in con_res if c.incumplio_resolucion]),
            "cumplimiento_pct": _pct(con_res, len([c for c in con_res if c.incumplio_resolucion])),
        },
        "medible": bool(con_pr or con_res),
    }
