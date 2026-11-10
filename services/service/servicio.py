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
from crmcore.errors import Conflicto, ErrorValidacion, NoDisponible, NoEncontrado
from crmcore.fechas import hoy
from crmcore.logging import get_logger
from crmcore.vocabularios import SEVERIDADES as SEVERIDADES_QUE_CRUZAN
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.service.modelos import Caso, CategoriaCaso, DefinicionSLA, EventoCaso

logger = get_logger(__name__)

# Qué estados paran el reloj y cuáles son terminales ya no es una lista: es el
# significado de cada estado en la máquina del caso (`estados.py`), que la
# empresa configura. Quién para el reloj es una decisión de negocio que cambia
# por cliente —hay contratos donde «esperando repuesto» lo para y otros donde
# no—, y por eso no podía ser una constante.

# La prioridad es de aquí y no sale: en qué orden se atiende es decisión del
# servicio. La severidad sí viaja —la manda la telemetría en el comando que abre
# un caso—, así que se escribe una vez en `crmcore.vocabularios`.
from crmcore.datos.estados import (  # noqa: E402
    comprobar,
    con_significado,
    estado_de,
    maquina_efectiva,
    significa,
)

from services.service.estados import EN_PAUSA, terminales  # noqa: E402
from services.service.modelos import PRIORIDADES, VOCABULARIO_PRIORIDAD  # noqa: E402

SEVERIDADES = SEVERIDADES_QUE_CRUZAN

# La empresa decide sus prioridades (Gestor de objetos › Vocabularios). «media»
# es fija: es la que toma un caso que no dice ninguna —el alta, el canal de
# entrada—, y retirarla dejaría esos casos sin una prioridad válida.
from crmcore import vocabulario  # noqa: E402

vocabulario.registrar(
    VOCABULARIO_PRIORIDAD,
    PRIORIDADES,
    etiqueta="Prioridades de un caso",
    descripcion=(
        "En qué orden se atiende un caso. Es una escala: el orden de la lista es "
        "el de la urgencia, y el escalado sube un caso al siguiente. «Media» es "
        "la de un caso que no dice ninguna y no se puede retirar."
    ),
    fijos=("media",),
    en_orden=True,
    etiquetas={"baja": "Baja", "media": "Media", "alta": "Alta", "critica": "Crítica"},
)

# Por qué se cierra un caso (CRM-04.01.01.09). Era texto libre: «resuelto»,
# «Resuelto» y «solucionado» contaban como tres motivos y el informe de cierres
# —para el que existe el campo— tenía tantas filas como formas de escribirlo.
# Medido el 10-11-2026 cerrando un caso desde la ficha. Los dos fijos los
# escribe el código: marcar un duplicado y resolver un problema cierran solos.
VOCABULARIO_MOTIVOS_CIERRE = "motivos_cierre_caso"
MOTIVOS_CIERRE = (
    "resuelto",
    "solucion_temporal",
    "no_era_un_problema",
    "sin_respuesta_del_cliente",
    "fuera_de_alcance",
    "duplicado",
    "resuelto_por_problema",
)
vocabulario.registrar(
    VOCABULARIO_MOTIVOS_CIERRE,
    MOTIVOS_CIERRE,
    etiqueta="Motivos de cierre de un caso",
    descripcion=(
        "Por qué se cerró un caso. Se elige al cerrarlo y es lo que agrupa el "
        "informe de cierres. «Duplicado» y «resuelto por problema» los pone el "
        "propio sistema y no se pueden retirar."
    ),
    fijos=("duplicado", "resuelto_por_problema"),
    en_orden=True,
    etiquetas={
        "resuelto": "Resuelto",
        "solucion_temporal": "Solución temporal",
        "no_era_un_problema": "No era un problema",
        "sin_respuesta_del_cliente": "Sin respuesta del cliente",
        "fuera_de_alcance": "Fuera de alcance",
        "duplicado": "Duplicado",
        "resuelto_por_problema": "Resuelto por un problema",
    },
)


def exigir_motivo_de_cierre(db: Session, motivo: str) -> None:
    """Que el motivo sea uno de la lista de la empresa.

    Se exige en el cierre que se ELIGE —la acción de la ficha y el cierre de
    una incidencia masiva—, no en el que se deriva de mover el estado, donde el
    motivo es el comentario de la transición.
    """
    admitidos = vocabulario.valores(db, VOCABULARIO_MOTIVOS_CIERRE)
    if motivo not in admitidos:
        raise ErrorValidacion(
            f"«{motivo}» no es un motivo de cierre de la lista.",
            error_code="service.motivo_cierre_no_valido",
            detalle={"admitidos": sorted(admitidos)},
        )


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
    en_fecha = en_fecha or hoy(db)
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
    """El calendario del SLA, o el de la empresa por defecto si ése no existe.

    Una clave que no casa con ningún calendario —el SLA dice «laborable» y la
    empresa tiene «iberia»— hacía contar en horas de RELOJ: un SLA de ocho
    horas laborables vencía a la una de la madrugada. Medido el 10-11-2026 con
    los tres SLA del tenant de demostración. El calendario por defecto de la
    empresa se parece mucho más a lo pactado que el reloj, y se avisa.
    """
    base = select(CalendarioLaboral).where(CalendarioLaboral.tenant_id == tenant_id)
    if clave:
        hallado = db.execute(
            base.where(CalendarioLaboral.clave == clave).limit(1)
        ).scalar_one_or_none()
        if hallado is not None:
            return hallado
        logger.warning(
            "service.sla_calendario_inexistente", tenant=str(tenant_id), calendario=clave
        )
    return db.execute(
        base.where(CalendarioLaboral.por_defecto.is_(True)).limit(1)
    ).scalar_one_or_none()


def exigir_calendario(db: Session, tenant_id: UUID, clave: str) -> None:
    """Al publicar un SLA, que su calendario exista: lo que no exista se descubre
    cuando ya hay casos con vencimientos mal calculados."""
    if not clave:
        return
    claves = [
        c
        for (c,) in db.execute(
            select(CalendarioLaboral.clave).where(CalendarioLaboral.tenant_id == tenant_id)
        ).all()
    ]
    if clave not in claves:
        raise ErrorValidacion(
            f"No hay ningún calendario laboral «{clave}».",
            error_code="service.calendario_inexistente",
            detalle={"calendarios": sorted(claves)},
        )


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
    """Código legible correlativo: `CAS-2026-00123`.

    **Se contaba, y contar repetía números.** El recuento no ve los casos
    borrados —el guardián de borrados los quita de toda consulta—, así que
    borrar un caso hacía que el siguiente pidiera el código del borrado y la
    restricción única tumbaba el alta con un 409: medido el 09-11-2026, tras
    borrar un caso de prueba nadie podía abrir ninguno. Ahora lo lleva el
    contador común (`crmcore.numeracion`), bajo cerrojo, como la oportunidad;
    la primera vez se declara arrancando por el mayor código ya emitido este
    año, borrados incluidos.
    """
    from crmcore import numeracion
    from crmcore.datos.guard_borrados import con_borrados

    codigo = numeracion.siguiente(db, tenant_id, objeto="caso")
    if codigo is not None:
        return codigo
    anio = hoy(db).year
    prefijo = f"CAS-{anio}-"
    with con_borrados(db):
        codigos = (
            db.execute(
                select(Caso.codigo).where(
                    Caso.tenant_id == tenant_id, Caso.codigo.like(f"{prefijo}%")
                )
            )
            .scalars()
            .all()
        )
    ya = max(
        (int(c[len(prefijo) :]) for c in codigos if c and c[len(prefijo) :].isdigit()), default=0
    )
    numeracion.declarar(
        db,
        tenant_id,
        objeto="caso",
        patron="CAS-{anio}-{secuencia}",
        relleno=5,
        reinicio="anual",
        empezar_en=ya,
    )
    emitido = numeracion.siguiente(db, tenant_id, objeto="caso")
    assert emitido is not None  # se acaba de declarar
    return emitido


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
    validas = vocabulario.valores(uow.db, VOCABULARIO_PRIORIDAD)
    if prioridad not in validas:
        raise ErrorValidacion(
            f"Prioridad «{prioridad}» no válida.",
            error_code="service.prioridad_no_valida",
            detalle={"validas": sorted(validas)},
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
    # El reparto, AL ABRIR (CRM-04.01.01.05). Las reglas, la capacidad y la
    # explicación estaban escritas y sólo se ejecutaban si alguien llamaba a
    # `POST /colas/asignar/{caso}` a mano: ningún caso se repartía solo, todos
    # se quedaban en la entrada sin dueño. Medido el 10-11-2026. Sólo cuando
    # quien abre no ha dicho ya de quién es ni a qué cola va.
    if caso.owner_id is None and not caso.equipo:
        from services.service.operacion import asignar

        asignar(uow, caso)
    from services.service.indexacion import indexar_caso

    indexar_caso(uow.db, caso)
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


def responder_caso(
    uow: UnidadDeTrabajo,
    caso_id: UUID,
    *,
    mensaje: str,
    para: str = "",
    asunto: str = "",
    principal_id: Any = None,
) -> dict[str, Any]:
    """Contesta al cliente por correo, y deja escrito que se hizo.

    Hasta el 10-11-2026 «responder» en la ficha del caso era **apuntar** un
    correo: quedaba una actividad de tipo correo y al cliente no le llegaba
    nada. Ahora sale de verdad, por el canal de la casa —el correo
    transaccional de marketing, con la plantilla de la empresa
    (`respuesta_caso_plantilla`)—, y consta tres veces: el envío con su estado
    en marketing, la actividad colgada del caso en clientes y el evento en el
    historial del caso. Si sale, cuenta como primera respuesta para el SLA.

    **Lo que no sale también consta.** Sin remitente, sin servidor o con el
    buzón rechazándolo, se apunta igual —con «no ha salido» y el motivo— y se
    devuelve `enviado: false`: una respuesta que se cree mandada y no lo está es
    la peor de las tres posibilidades.

    El destinatario es el que se escriba o, si no, el correo del contacto del
    caso. Se pregunta a clientes con la identidad de quien responde y sólo con
    lo que hace falta para leerlo.
    """
    from crmcore.http.interno import invocar
    from crmcore.runtime import settings as rt

    from services.service.ajustes import ajustes

    caso = exigir_caso(uow.db, caso_id)
    texto = mensaje.strip()
    if not texto:
        raise ErrorValidacion(
            "Una respuesta sin texto no dice nada al cliente",
            error_code="service.respuesta_vacia",
        )
    espera = float(
        rt.efectivo("respuesta_caso_espera_s", uow.db) or ajustes().respuesta_caso_espera_s
    )

    def llamar(metodo: str, ruta: str, permisos: list[str], cuerpo: Any = None) -> dict[str, Any]:
        return invocar(
            metodo=metodo,
            ruta=ruta,
            cuerpo=cuerpo,
            tenant_id=uow.tenant_id,
            principal_id=principal_id,
            permisos=permisos,
            timeout_s=espera,
        )

    destino = para.strip()
    if not destino and caso.contacto_id is not None:
        contacto = llamar("GET", f"/api/v1/contacts/{caso.contacto_id}", ["contact:read"])
        if contacto.get("ok"):
            destino = str((contacto.get("datos") or {}).get("email") or "").strip()
    if not destino:
        raise ErrorValidacion(
            "No hay a quién mandarla: el caso no tiene un contacto con correo. "
            "Escribe la dirección en «Para».",
            error_code="service.respuesta_sin_destinatario",
            errores=[{"campo": "para", "motivo": "Hace falta una dirección"}],
        )

    titulo = asunto.strip() or f"Re: {caso.asunto} [{caso.codigo}]"
    plantilla = str(
        rt.efectivo("respuesta_caso_plantilla", uow.db) or ajustes().respuesta_caso_plantilla
    )
    try:
        mandado = llamar(
            "POST",
            "/api/v1/correo/enviar",
            ["activity:write"],
            {
                "para": destino,
                "objeto": "caso",
                "objeto_id": str(caso.id),
                "asunto": titulo,
                "mensaje": texto,
                "plantilla": plantilla,
                "datos": {"caso": {"codigo": caso.codigo, "asunto": caso.asunto}},
            },
        )
    except NoDisponible as exc:
        mandado = {"ok": False, "datos": {"mensaje": exc.mensaje}}
    resultado = mandado.get("datos") if isinstance(mandado.get("datos"), dict) else {}
    enviado = bool(mandado.get("ok") and resultado.get("enviado"))
    motivo = (
        ""
        if enviado
        else str(
            resultado.get("motivo")
            or resultado.get("detail")
            or resultado.get("mensaje")
            or "no contesta"
        )[:500]
    )

    # La actividad, en la ficha del caso: es lo que ve quien lo abre después.
    actividad = llamar(
        "POST",
        "/api/v1/activities",
        ["activity:write"],
        {
            "tipo": "email",
            # Lo que no salió se ve en la propia lista de lo apuntado, sin
            # abrir nada: no puede leerse igual que lo que sí llegó.
            "asunto": (titulo if enviado else f"No ha salido: {titulo}")[:300],
            "cuerpo": texto,
            "objeto": "caso",
            "objeto_id": str(caso.id),
            **({"cuenta_id": str(caso.cuenta_id)} if caso.cuenta_id else {}),
            **({"contacto_id": str(caso.contacto_id)} if caso.contacto_id else {}),
            "detalles": {
                "para": destino,
                "enviado": enviado,
                "motivo": motivo,
                "envio_id": resultado.get("envio_id") or "",
            },
        },
    )
    actividad_id = (
        str((actividad.get("datos") or {}).get("id") or "") if actividad.get("ok") else ""
    )

    _anotar(
        uow.db,
        caso,
        "respuesta",
        para=destino,
        asunto=titulo,
        enviado=enviado,
        motivo=motivo,
        envio_id=resultado.get("envio_id") or "",
        actividad_id=actividad_id,
        por=str(principal_id) if principal_id else None,
    )
    if enviado:
        registrar_primera_respuesta(uow, caso.id, por=principal_id)
    uow.db.flush()
    return {
        "enviado": enviado,
        "motivo": motivo,
        "para": destino,
        "asunto": titulo,
        "envio_id": resultado.get("envio_id") or None,
        "plantilla": resultado.get("plantilla"),
        "plantilla_de_serie": bool(resultado.get("plantilla_de_serie")),
        "actividad_id": actividad_id or None,
    }


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
    maquina = maquina_efectiva("caso", uow.db)
    validos = sorted(maquina.estados - maquina.inactivos) if maquina else []
    if estado not in validos:
        raise ErrorValidacion(
            f"«{estado}» no es un estado de caso",
            error_code="caso.estado_desconocido",
            detalle={"validos": validos},
        )
    if estado == caso.estado:
        return caso
    # Las transiciones y el motivo, como los configure la empresa.
    comprobar("caso", desde=caso.estado, hasta=estado, motivo=motivo, db=uow.db)

    # Cerrar y reabrir tienen su camino: cerrar fija la resolución y el
    # incumplimiento, reabrir mira la ventana y cuenta la reapertura. Desde el
    # desplegable de estado se pasa por ellos; si no, cambiar el estado a mano
    # era la forma de reabrir fuera de plazo sin que constara.
    estaba_cerrado = significa("caso", caso.estado, "cerrado", uow.db)
    va_a_cerrado = significa("caso", estado, "cerrado", uow.db)
    if va_a_cerrado and not estaba_cerrado:
        cerrar_caso(uow, caso.id, motivo=motivo)
        caso.estado = estado  # el cerrado que se eligió, si la empresa tiene varios
        return caso
    if estaba_cerrado and not va_a_cerrado:
        reabrir_caso(uow, caso.id, motivo=motivo)
        if estado == caso.estado:
            return caso

    ahora = _ahora()
    pausa = con_significado("caso", EN_PAUSA, uow.db)
    estaba_en_pausa = caso.estado in pausa
    entra_en_pausa = estado in pausa

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
    if significa("caso", estado, "resuelto", uow.db) and caso.resuelto_at is None:
        caso.resuelto_at = ahora
        vence = _con_tz(caso.vence_resolucion_at)
        if vence is not None and ahora > vence:
            caso.incumplio_resolucion = True
    _anotar(uow.db, caso, "estado", desde=anterior, hasta=estado, motivo=motivo or None)
    from services.service.indexacion import indexar_caso

    # El resultado lleva el estado: sin esto, el buscador decía «nuevo» de un
    # caso cerrado hace un mes.
    indexar_caso(uow.db, caso)
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
    if significa("caso", caso.estado, "cerrado", uow.db):
        raise Conflicto("El caso ya está cerrado", error_code="service.caso_ya_cerrado")

    ahora = _ahora()
    if caso.resuelto_at is None:
        caso.resuelto_at = ahora
        vence = _con_tz(caso.vence_resolucion_at)
        if vence is not None and ahora > vence:
            caso.incumplio_resolucion = True
    caso.estado = estado_de("caso", "cerrado", uow.db)
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
    from services.service.indexacion import indexar_caso

    indexar_caso(uow.db, caso)
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
    if not significa("caso", caso.estado, "cerrado", uow.db):
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

    caso.estado = estado_de("caso", "en_curso", uow.db)
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
    from services.service.indexacion import indexar_caso

    indexar_caso(uow.db, caso)
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
                Caso.estado.not_in(con_significado("caso", "cerrado", uow.db)),
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
    if not significa("caso", maestro.estado, "cerrado", uow.db):
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
    caso.estado = estado_de("caso", "cerrado", uow.db)
    caso.cerrado_at = _ahora()
    caso.motivo_cierre = "duplicado"
    _anotar(uow.db, caso, "duplicado", original=str(original.id))
    return caso


def arbol_de_caso(db: Session, tenant_id: UUID, caso_id: UUID) -> dict[str, Any]:
    """De qué cuelga el caso y qué cuelga de él (CRM-04.01.01.04, CRM-04.01.01.11).

    Las tres relaciones en los DOS sentidos y con el asunto de cada uno. Antes
    salía sólo hacia abajo y sin nombre: el caso colgado de una incidencia
    masiva no decía de cuál —el agente que lo abría no sabía que había una
    causa común investigándose—, el original no listaba sus duplicados y el
    padre era «cuelga de otro caso», sin decir cuál. Medido el 10-11-2026
    recorriendo la ficha.
    """
    caso = exigir_caso(db, caso_id)

    def _de(columna: Any) -> list[dict[str, Any]]:
        filas = (
            db.execute(
                select(Caso)
                .where(Caso.tenant_id == tenant_id, columna == caso.id, Caso.deleted_at.is_(None))
                .order_by(Caso.created_at)
            )
            .scalars()
            .all()
        )
        return [{"id": str(h.id), "asunto": h.asunto, "estado": h.estado} for h in filas]

    arriba = {
        clave: valor
        for clave, valor in (
            ("padre", caso.padre_id),
            ("maestro", caso.maestro_id),
            ("duplicado_de", caso.duplicado_de_id),
        )
        if valor
    }
    asuntos: dict[UUID, str] = {}
    if arriba:
        asuntos = dict(
            db.execute(
                select(Caso.id, Caso.asunto).where(
                    Caso.tenant_id == tenant_id, Caso.id.in_(list(arriba.values()))
                )
            ).all()
        )
    return {
        "caso": str(caso.id),
        "padre": str(caso.padre_id) if caso.padre_id else None,
        "maestro": str(caso.maestro_id) if caso.maestro_id else None,
        "duplicado_de": str(caso.duplicado_de_id) if caso.duplicado_de_id else None,
        # El asunto de los de arriba, por identificador. Uno que ya no está no
        # aparece: la pantalla lo dice en vez de inventarle un nombre.
        "asuntos": {str(k): v for k, v in asuntos.items()},
        "hijos": _de(Caso.padre_id),
        "colgados_del_maestro": _de(Caso.maestro_id),
        "duplicados": _de(Caso.duplicado_de_id),
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
                Caso.estado.not_in(terminales(db)),
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

    # Primero lo que AÚN se puede salvar, por lo que le queda; detrás lo ya
    # incumplido, lo más reciente antes. Ordenado sólo por minutos, lo vencido
    # hace dos años salía el primero y los que vencían en una hora quedaban al
    # final de 180 filas (medido el 10-11-2026 en Casos › SLA).
    salida.sort(
        key=lambda c: (
            c["ya_incumplido"],
            -c["minutos_restantes"] if c["ya_incumplido"] else c["minutos_restantes"],
        )
    )
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
