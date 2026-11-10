"""Lógica de leads y oportunidades."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore import vocabulario
from crmcore.audit.chain import registrar, registrar_cambios
from crmcore.authz.decision import exigir
from crmcore.datos.estados import aplicar as aplicar_estado
from crmcore.datos.estados import (
    camino_propio,
    con_significado,
    maquina_efectiva,
    registrar_caminos,
    significa,
)
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy
from crmcore.logging import get_logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.sales import estados as _estados  # noqa: F401 — declara las máquinas
from services.sales.enrutamiento import enrutar
from services.sales.modelos import (
    CambioEtapa,
    Etapa,
    Lead,
    LineaOportunidad,
    Oportunidad,
    Pipeline,
)
from services.sales.origen import registrar_alta
from services.sales.plan_conjunto import anotar_resultado

logger = get_logger(__name__)


# ── Leads ─────────────────────────────────────────────────────────────────


def crear_lead(
    uow: UnidadDeTrabajo,
    *,
    forzar: bool = False,
    comprobar_duplicados: bool = True,
    **datos: Any,
) -> Lead:
    """Da de alta un lead y le pone el reloj del SLA de primera respuesta.

    El SLA se fija **al entrar**, no al asignarlo: el cliente que rellenó el
    formulario está esperando desde que lo envió, no desde que alguien de dentro
    se hizo cargo. Contarlo desde la asignación permitiría cumplir el SLA
    siempre, sin más que asignar tarde.

    **Antes de crear, mira si ya existe** como lead o como contacto
    (CRM-01.01.03.03). Con un duplicado concluyente responde 409 con los
    candidatos, como cuentas y contactos; `forzar=True` lo crea igual y la
    decisión queda en la auditoría. `comprobar_duplicados=False` es para quien
    ya ha mirado —la captura automática, que decide por su cuenta qué hacer—.
    """
    from crmcore.runtime import settings as rt

    tenant_id = uow.tenant_id
    if tenant_id is None:
        raise ErrorValidacion("Falta el tenant", error_code="sales.sin_tenant")

    encontrados = None
    if comprobar_duplicados:
        from crmcore.authz.principal import principal_actual

        from services.sales import dedupe_leads

        encontrados = dedupe_leads.buscar(
            uow.db, tenant_id, datos, principal_id=principal_actual().id
        )
        if encontrados.concluyentes and not forzar:
            raise Conflicto(
                "Ya existe un lead o un contacto que parece el mismo",
                error_code="sales.lead_duplicado",
                detalle={
                    **encontrados.a_dict(),
                    # Se dice cómo continuar: sin esto, quien recibe el 409 no
                    # sabe si tiene que abrir el que hay o insistir.
                    "como_continuar": "usa el registro existente, o repite con forzar=true",
                },
            )

    horas = int(rt.efectivo("lead_sla_primera_respuesta_horas", uow.db) or 4)
    ahora = datetime.now(timezone.utc)

    lead = Lead(
        tenant_id=tenant_id,
        sla_primera_respuesta_at=ahora + timedelta(hours=horas),
        asignado_at=ahora if datos.get("owner_id") else None,
        **datos,
    )
    uow.db.add(lead)
    uow.db.flush()

    # Trazabilidad de origen (CRM-01.01.03.06). Antes del enrutamiento, porque
    # una regla puede repartir por campaña y necesita el origen ya resuelto.
    registrar_alta(uow.db, lead, tenant_id=tenant_id)

    from services.sales.indexacion import indexar_lead

    indexar_lead(uow.db, lead)

    # Enrutamiento automático (CRM-01.01.03.04). Solo si nadie lo trae asignado:
    # una asignación explícita —un comercial que da de alta su propio contacto—
    # manda sobre las reglas, porque quien lo escribe sabe algo que las reglas
    # no saben.
    registro = None
    if lead.owner_id is None and bool(rt.efectivo("lead_enrutar_al_crear", uow.db)):
        registro = enrutar(uow.db, lead, tenant_id=tenant_id)

    if encontrados is not None and encontrados.concluyentes and forzar:
        # Crear a sabiendas de que se parece a otro es una decisión, y queda
        # escrita: quién, cuándo y contra qué candidatos.
        registrar(
            uow.db,
            accion="lead.creado_forzado",
            objeto="lead",
            objeto_id=lead.id,
            datos={"candidatos_descartados": [c.a_dict() for c in encontrados.candidatos]},
        )

    uow.emitir(
        "lead.created",
        subject=("lead", lead.id),
        data={
            "lead_id": str(lead.id),
            "origen": lead.origen or "",
            # Ver `account.created`: sin los campos propios aquí, un flujo no
            # puede condicionar por ellos (CRM-00.04.03.05).
            "campos": dict(lead.campos or {}),
        },
    )
    if registro is not None and registro.asignado_a is not None:
        uow.emitir(
            "lead.assigned",
            subject=("lead", lead.id),
            data={
                "lead_id": str(lead.id),
                "asignado_a": str(registro.asignado_a),
                "regla": registro.regla_nombre or "",
            },
            # La asignación de un lead concreto a un dueño concreto es el hecho:
            # si el consumidor lo recibe dos veces, es la misma asignación.
            dedup_key=f"lead.assigned:{lead.id}:{registro.asignado_a}",
        )
    return lead


def registrar_primera_respuesta(db: Session, lead_id: UUID, *, por: UUID | None = None) -> Lead:
    """Anota que alguien ha respondido al lead y evalúa el SLA.

    Idempotente: si ya había respuesta anotada, no la pisa. La primera es la que
    cuenta, y sobrescribirla con una posterior maquillaría el incumplimiento.
    """
    lead = _lead(db, lead_id)
    if lead.primera_respuesta_at is not None:
        return lead

    ahora = datetime.now(timezone.utc)
    lead.primera_respuesta_at = ahora
    lead.sla_incumplido = bool(
        lead.sla_primera_respuesta_at and ahora > lead.sla_primera_respuesta_at
    )
    if significa("lead", lead.estado, "nuevo", db):
        aplicar_estado(db, lead, objeto="lead", nuevo="contactado", por=por)
    if lead.sla_incumplido:
        logger.warning(
            "sales.sla_incumplido",
            lead=str(lead_id),
            vencia=lead.sla_primera_respuesta_at.isoformat()
            if lead.sla_primera_respuesta_at
            else "",
        )
    return lead


def descartar_lead(uow: UnidadDeTrabajo, lead_id: UUID, *, motivo: str, nota: str = "") -> Lead:
    """Descarta un lead con motivo normalizado y fecha de reciclaje.

    El motivo es de una lista cerrada porque lo que se quiere es **contar**:
    «sin presupuesto» y «no es nuestro perfil» llevan a acciones distintas, y en
    texto libre no se pueden agrupar ni comparar entre periodos.
    """
    from crmcore.runtime import settings as rt

    lead = _lead(uow.db, lead_id)
    if significa("lead", lead.estado, "convertido", uow.db):
        raise Conflicto(
            "Un lead ya convertido no se puede descartar",
            error_code="sales.lead_ya_convertido",
        )
    admitidos = vocabulario.valores(uow.db, "motivos_descarte")
    if motivo not in admitidos:
        raise ErrorValidacion(
            f"«{motivo}» no es un motivo de descarte reconocido",
            error_code="sales.motivo_descarte_invalido",
            detalle={"admitidos": sorted(admitidos)},
        )

    dias = int(rt.efectivo("lead_dias_reciclaje", uow.db) or 180)
    aplicar_estado(uow.db, lead, objeto="lead", nuevo="descartado", motivo=motivo)
    lead.motivo_descarte = motivo
    lead.nota_descarte = nota or None
    # Un «ahora no» no es un no para siempre: se programa la vuelta a la cola.
    lead.reciclar_at = (hoy(uow.db) + timedelta(days=dias)) if dias > 0 else None

    registrar(
        uow.db,
        accion="lead.descartado",
        objeto="lead",
        objeto_id=lead_id,
        # Explícito y no del contexto: esto lo llaman también tareas de fondo
        # (el reciclaje automático), que no tienen petición ni contexto.
        tenant_id=lead.tenant_id,
        datos={
            "motivo": motivo,
            "reciclar_at": lead.reciclar_at.isoformat() if lead.reciclar_at else None,
        },
    )
    return lead


# Con los que se estrena el producto. **No son un límite**: la empresa los
# cambia desde su pantalla y a partir de ahí manda su lista — ver
# `crmcore.vocabulario`. Escritos como constante, los nueve que trae eran los
# nueve que iba a tener siempre, y la pantalla los enseñaba sin dejar tocarlos.
MOTIVOS_DESCARTE: frozenset[str] = frozenset(
    {
        "sin_presupuesto",
        "sin_autoridad",
        "sin_necesidad",
        "fuera_de_perfil",
        "competencia",
        "datos_incorrectos",
        "duplicado",
        "no_responde",
        "momento_inadecuado",
    }
)


def convertir_lead(
    uow: UnidadDeTrabajo,
    lead_id: UUID,
    *,
    cuenta_id: UUID,
    contacto_id: UUID | None = None,
    crear_oportunidad: bool = True,
    nombre_oportunidad: str | None = None,
    importe: Decimal | None = None,
    pipeline_id: UUID | None = None,
    fecha_cierre: date | None = None,
) -> tuple[Lead, Oportunidad | None]:
    """Convierte un lead en cuenta, contacto y oportunidad (CRM-01.01.03.01).

    La cuenta y el contacto los crea el servicio `party` **antes** de llamar
    aquí, y se pasan por identificador. No se crean desde este servicio aunque
    sería más cómodo: el maestro de clientes es de `party`, y escribir en su
    esquema desde ventas rompería la propiedad exclusiva de datos — que además
    los permisos de base de datos impiden.

    El lead **se conserva** apuntando a lo que generó. Es lo que hace posible
    responder a «¿de dónde salió este cliente?».
    """
    lead = _lead(uow.db, lead_id)
    if significa("lead", lead.estado, "convertido", uow.db):
        raise Conflicto(
            "Ese lead ya se convirtió",
            error_code="sales.lead_ya_convertido",
            detalle={
                "cuenta_id": str(lead.cuenta_id) if lead.cuenta_id else None,
                "oportunidad_id": str(lead.oportunidad_id) if lead.oportunidad_id else None,
            },
        )

    oportunidad: Oportunidad | None = None
    if crear_oportunidad:
        oportunidad = crear_oportunidad_nueva(
            uow,
            nombre=nombre_oportunidad or (lead.empresa or "Oportunidad"),
            cuenta_id=cuenta_id,
            contacto_id=contacto_id,
            importe=importe or Decimal(0),
            pipeline_id=pipeline_id,
            fecha_cierre=fecha_cierre,
            owner_id=lead.owner_id,
            lead_id=lead.id,
        )

    # Pasa por la máquina: convertir un lead ya convertido crearía una segunda
    # cuenta del mismo cliente, y convertir uno descartado se salta la
    # cualificación que mide el equipo.
    aplicar_estado(uow.db, lead, objeto="lead", nuevo="convertido")
    lead.convertido_at = datetime.now(timezone.utc)
    lead.cuenta_id = cuenta_id
    lead.contacto_id = contacto_id
    lead.oportunidad_id = oportunidad.id if oportunidad else None

    registrar(
        uow.db,
        accion="lead.convertido",
        objeto="lead",
        objeto_id=lead_id,
        tenant_id=lead.tenant_id,
        datos={
            "cuenta_id": str(cuenta_id),
            "contacto_id": str(contacto_id) if contacto_id else None,
            "oportunidad_id": str(oportunidad.id) if oportunidad else None,
        },
    )
    uow.emitir(
        "lead.converted",
        subject=("lead", lead_id),
        data={
            "lead_id": str(lead_id),
            "cuenta_id": str(cuenta_id),
            "contacto_id": str(contacto_id) if contacto_id else "",
            "oportunidad_id": str(oportunidad.id) if oportunidad else "",
        },
    )
    return lead, oportunidad


def exigir_lead(db: Session, lead_id: UUID) -> Lead:
    """El lead, o 404. Pública para que las rutas de subrecursos comprueben el
    padre antes de devolver su contenido."""
    return _lead(db, lead_id)


# Los significados que tienen su propio camino, con lo que ese camino hace y
# esta acción no: cerrar (lección, bloqueo, eventos de cierre), convertir (crea
# cuenta y oportunidad) y descartar (motivo normalizado y reciclaje).
_CON_SU_CAMINO = {
    "oportunidad": {
        "ganado": "se cierra moviéndola a la etapa de ganada",
        "perdido": "se cierra moviéndola a la etapa de perdida, con su motivo",
    },
    "lead": {
        "convertido": "se convierte con «Convertir»",
        "descartado": "se descarta con «Descartar», con su motivo",
    },
    "presupuesto": {
        "en_aprobacion": "se manda con «Enviar», que mira la matriz de descuentos",
        "enviado": "se manda con «Enviar», que mira la matriz de descuentos",
        "aprobado": "lo aprueba quien le toca, desde Aprobaciones",
        "aceptado": "se acepta con «Aceptar», que crea el pedido",
        "sustituido": "se sustituye haciendo una versión nueva",
        "caducado": "caduca solo al pasar su validez",
    },
    "contrato": {
        "renovado": "se renueva desde la revisión de renovaciones, que crea el contrato nuevo",
    },
}
# Publicados con la máquina: el desplegable de la ficha no los ofrece.
for _objeto, _caminos in _CON_SU_CAMINO.items():
    registrar_caminos(_objeto, _caminos)


def cambiar_estado(
    uow: UnidadDeTrabajo, objeto: str, fila: Any, *, estado: str, motivo: str = ""
) -> Any:
    """Mueve el registro a otro estado de los que ha configurado la empresa.

    Es lo que hace alcanzables los estados propios —«En pausa», «Visitado»—:
    sin esto se podían declarar y no había forma de llegar a ellos. La máquina
    de la empresa decide si la transición vale y si pide motivo.
    """
    # Entre dos estados que significan lo mismo —«Enviado» y «En negociación»—
    # no hay nada que rehacer: lo que hace la acción ya se hizo al llegar.
    camino = camino_propio(objeto, fila.estado, estado, uow.db)
    if camino:
        raise Conflicto(
            f"Pasar a «{estado}» no se hace aquí: {camino}",
            error_code="estados.con_su_camino",
        )
    aplicar_estado(uow.db, fila, objeto=objeto, nuevo=estado, motivo=motivo)
    uow.db.flush()
    return fila


def _lead(db: Session, lead_id: UUID) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None or lead.deleted_at is not None:
        raise NoEncontrado("El lead no existe", error_code="sales.lead_no_encontrado")
    # Punto único de decisión (CRM-00.05.02.18). Va en el cargador y no en cada
    # endpoint a propósito: el endpoint que se olvide de llamarlo es el agujero,
    # y aquí pasan TODOS —la ficha, la edición, el borrado y lo que venga—.
    # Si una política lo niega, esto corta con 403 y la explicación dentro.
    exigir(db, objeto="lead", accion="read", registro=lead)
    return lead


# ── Pipelines y etapas ────────────────────────────────────────────────────


def pipeline_por_defecto(db: Session, tenant_id: UUID) -> Pipeline:
    """El pipeline marcado por defecto, o el primero activo."""
    pipeline = db.execute(
        select(Pipeline).where(
            Pipeline.tenant_id == tenant_id,
            Pipeline.por_defecto.is_(True),
            Pipeline.activo.is_(True),
        )
    ).scalar_one_or_none()
    if pipeline is None:
        pipeline = db.execute(
            select(Pipeline)
            .where(Pipeline.tenant_id == tenant_id, Pipeline.activo.is_(True))
            .order_by(Pipeline.created_at)
            .limit(1)
        ).scalar_one_or_none()
    if pipeline is None:
        raise NoEncontrado(
            "No hay ningún pipeline configurado. Crea uno antes de dar de alta " "oportunidades.",
            error_code="sales.sin_pipeline",
        )
    return pipeline


def primera_etapa(db: Session, pipeline_id: UUID) -> Etapa:
    etapa = db.execute(
        select(Etapa)
        .where(Etapa.pipeline_id == pipeline_id, Etapa.terminal.is_(False))
        .order_by(Etapa.orden)
        .limit(1)
    ).scalar_one_or_none()
    if etapa is None:
        raise NoEncontrado(
            "El pipeline no tiene etapas configuradas", error_code="sales.sin_etapas"
        )
    return etapa


# ── Oportunidades ─────────────────────────────────────────────────────────


def _dueno_por_defecto(db: Session) -> UUID | None:
    """Quien da de alta la oportunidad, si es una persona y el ajuste lo dice.

    Medido el 09-11-2026: 160 de las 162 ganadas del tenant de la plataforma no
    tenían dueño —nadie lo ponía al crearlas, y una cerrada queda bloqueada—,
    así que la compensación externa las mandaba sin reparto. Un proceso, un
    agente o la revisión periódica no son dueños de nada: esas se quedan sin él,
    como antes, y se reparten con las reglas de siempre.
    """
    from crmcore.authz.principal import principal_actual
    from crmcore.runtime import settings as rt

    from services.sales.ajustes import ajustes

    activo = rt.efectivo("oportunidad_dueno_quien_crea", db)
    if activo is None:
        activo = ajustes().oportunidad_dueno_quien_crea
    if not activo:
        return None
    quien = principal_actual()
    return quien.id if quien.tipo == "usuario" and quien.id is not None else None


def crear_oportunidad_nueva(
    uow: UnidadDeTrabajo,
    *,
    nombre: str,
    cuenta_id: UUID | None = None,
    pipeline_id: UUID | None = None,
    etapa_id: UUID | None = None,
    importe: Decimal = Decimal(0),
    **datos: Any,
) -> Oportunidad:
    """Crea una oportunidad en la primera etapa del pipeline que corresponda."""
    tenant_id = uow.tenant_id
    if tenant_id is None:
        raise ErrorValidacion("Falta el tenant", error_code="sales.sin_tenant")

    pipeline = (
        uow.db.get(Pipeline, pipeline_id)
        if pipeline_id
        else pipeline_por_defecto(uow.db, tenant_id)
    )
    if pipeline is None:
        raise NoEncontrado("El pipeline no existe", error_code="sales.pipeline_no_encontrado")

    etapa = uow.db.get(Etapa, etapa_id) if etapa_id else primera_etapa(uow.db, pipeline.id)
    if etapa is None or etapa.pipeline_id != pipeline.id:
        raise ErrorValidacion(
            "La etapa no pertenece a ese pipeline", error_code="sales.etapa_de_otro_pipeline"
        )

    if datos.get("owner_id") is None:
        datos["owner_id"] = _dueno_por_defecto(uow.db)
    oportunidad = Oportunidad(
        tenant_id=tenant_id,
        nombre=nombre.strip(),
        cuenta_id=cuenta_id,
        pipeline_id=pipeline.id,
        etapa_id=etapa.id,
        importe=importe,
        probabilidad=etapa.probabilidad,
        codigo=_siguiente_codigo(uow.db, tenant_id),
        **datos,
    )
    uow.db.add(oportunidad)
    uow.db.flush()

    uow.db.add(
        CambioEtapa(
            tenant_id=tenant_id,
            oportunidad_id=oportunidad.id,
            etapa_desde_id=None,
            etapa_hasta_id=etapa.id,
            importe_en_cambio=oportunidad.importe,
            fecha_cierre_en_cambio=oportunidad.fecha_cierre,
            por=oportunidad.created_by,
        )
    )
    # Volcado para que el apunte sea visible en la misma transacción y para que
    # `created_at` —que lo pone el servidor— quede asignado: sin él, dos cambios
    # seguidos comparten fecha y el historial deja de poder ordenarse.
    uow.db.flush()
    uow.emitir(
        "opportunity.created",
        subject=("oportunidad", oportunidad.id),
        data={
            "oportunidad_id": str(oportunidad.id),
            "cuenta_id": str(cuenta_id) if cuenta_id else "",
            "importe": str(oportunidad.importe),
            "moneda": oportunidad.moneda,
            # Ver `account.created` (CRM-00.04.03.05).
            "campos": dict(oportunidad.campos or {}),
        },
    )
    from services.sales.indexacion import indexar_oportunidad

    indexar_oportunidad(uow.db, oportunidad)
    # Lo que las lecciones del mismo cliente tienen que decir, desde el primer
    # día (CRM-03.01.01.17). Sin lecciones no hay aviso.
    from services.sales.consejos import avisar_en

    avisar_en(uow, oportunidad, "creacion")
    return oportunidad


def _siguiente_codigo(db: Session, tenant_id: UUID) -> str:
    """Código legible correlativo: `OPP-2026-00123` (CRM-00.04.01.11).

    **Antes se contaba, y contar falla de tres maneras que pasan todas**: si se
    borra una oportunidad la siguiente repite número; si dos altas entran a la
    vez piden el mismo y la restricción única convierte el alta en un error que
    el usuario no entiende; y si alguien carga histórico con códigos propios,
    el recuento no tiene nada que ver con el último emitido.

    Ahora lo lleva el contador común (`crmcore.numeracion`), bajo cerrojo de
    fila, con el patrón como configuración del tenant. Si el tenant no ha
    declarado numeración para `oportunidad` se cae al patrón de siempre, que es
    el prefijo de sus ajustes: estrenar el CRM no puede exigir configurar una
    numeración antes de poder crear la primera oportunidad.
    """
    from crmcore import numeracion

    from services.sales.ajustes import ajustes

    codigo = numeracion.siguiente(db, tenant_id, objeto="oportunidad")
    if codigo is not None:
        return codigo

    # Primera vez: se declara con el patrón de siempre y se emite. Así el
    # contador queda creado y a partir de aquí ya no se cuenta nunca más.
    anio = hoy(db).year
    prefijo = f"{ajustes().codigo_prefijo}-{anio}-"
    ya_hay = (
        db.execute(
            select(func.count(Oportunidad.id)).where(
                Oportunidad.tenant_id == tenant_id,
                Oportunidad.codigo.like(f"{prefijo}%"),
            )
        ).scalar_one()
        or 0
    )
    numeracion.declarar(
        db,
        tenant_id,
        objeto="oportunidad",
        # El prefijo sigue saliendo de los ajustes del tenant, que es donde
        # estaba y donde la gente lo busca.
        patron=f"{ajustes().codigo_prefijo}-{{anio}}-{{secuencia}}",
        relleno=5,
        reinicio="anual",
        # Arranca donde estaba: si hay 123 de este año, el siguiente es el 124.
        # Empezar en cero repetiría todos los códigos ya emitidos.
        empezar_en=ya_hay,
    )
    emitido = numeracion.siguiente(db, tenant_id, objeto="oportunidad")
    assert emitido is not None  # se acaba de declarar
    return emitido


def cambiar_etapa(
    uow: UnidadDeTrabajo,
    oportunidad_id: UUID,
    *,
    etapa_id: UUID,
    motivo: str = "",
    forzar: bool = False,
) -> Oportunidad:
    """Mueve una oportunidad de etapa comprobando los criterios de salida.

    Los criterios son lo que hace que la previsión signifique algo: sin ellos,
    una oportunidad llega a «negociación» sin importe ni fecha, y el pipeline
    suma números que nadie se cree.

    `forzar` existe para la carga de datos históricos, que nunca los cumplen, y
    deja constancia de que se saltó la comprobación.
    """
    from crmcore.runtime import settings as rt

    oportunidad = _oportunidad(uow.db, oportunidad_id)
    _exigir_editable(uow.db, oportunidad)

    destino = uow.db.get(Etapa, etapa_id)
    if destino is None or destino.pipeline_id != oportunidad.pipeline_id:
        raise ErrorValidacion(
            "La etapa no pertenece al pipeline de la oportunidad",
            error_code="sales.etapa_de_otro_pipeline",
        )
    if destino.id == oportunidad.etapa_id:
        return oportunidad

    origen = uow.db.get(Etapa, oportunidad.etapa_id)
    if origen is not None and bool(rt.efectivo("exigir_criterios_salida", uow.db)) and not forzar:
        faltan = criterios_incumplidos(oportunidad, origen)
        if faltan:
            raise ErrorValidacion(
                # Cuáles, en el propio mensaje: es lo único que ve quien pulsa
                # la etapa en la ficha, y «faltan datos» sin decir cuáles le
                # obliga a abrir el detalle técnico (visto el 10-11-2026).
                f"No se puede salir de «{origen.nombre}»: falta "
                + ", ".join(c.replace("_", " ") for c in faltan),
                error_code="sales.criterios_salida_incumplidos",
                errores=[
                    {
                        "campo": c,
                        "motivo": "criterio_de_salida",
                        "mensaje": f"«{c}» es obligatorio para avanzar",
                    }
                    for c in faltan
                ],
            )

    dias = (datetime.now(timezone.utc) - oportunidad.etapa_desde).days
    anterior = oportunidad.etapa_id

    oportunidad.etapa_id = destino.id
    oportunidad.etapa_desde = datetime.now(timezone.utc)
    # La probabilidad sigue a la etapa salvo que alguien la haya fijado a mano
    # (CRM-03.01.01.04). Antes se deducía comparando con la probabilidad de la
    # etapa de origen, y esa heurística fallaba por los dos lados: un ajuste
    # manual que coincidiera con la etapa se perdía al avanzar, y uno que no
    # coincidiera se arrastraba para siempre por todas las etapas siguientes.
    # Ahora es una bandera explícita, que es lo que era desde el principio.
    if not oportunidad.probabilidad_manual:
        oportunidad.probabilidad = destino.probabilidad

    uow.db.add(
        CambioEtapa(
            tenant_id=oportunidad.tenant_id,
            oportunidad_id=oportunidad.id,
            etapa_desde_id=anterior,
            etapa_hasta_id=destino.id,
            dias_en_etapa=dias,
            importe_en_cambio=oportunidad.importe,
            fecha_cierre_en_cambio=oportunidad.fecha_cierre,
            motivo=motivo or ("carga forzada" if forzar else None),
            por=oportunidad.updated_by,
        )
    )
    uow.db.flush()
    uow.emitir(
        "opportunity.stage.changed",
        subject=("oportunidad", oportunidad.id),
        data={
            "oportunidad_id": str(oportunidad.id),
            "etapa_desde": origen.clave if origen else "",
            "etapa_hasta": destino.clave,
            "probabilidad": oportunidad.probabilidad,
        },
    )

    if destino.terminal:
        _cerrar(uow, oportunidad, ganada=destino.ganada, motivo=motivo)
    else:
        # Al entrar en una etapa, lo que se perdió en ella (CRM-03.01.01.17).
        from services.sales.consejos import avisar_en

        avisar_en(uow, oportunidad, "etapa", clave=str(destino.id), etapa=destino.nombre)
    return oportunidad


def criterios_incumplidos(oportunidad: Oportunidad, etapa: Etapa) -> list[str]:
    """Campos obligatorios de la etapa que la oportunidad no tiene.

    Mira primero los campos propios del modelo y luego los personalizados del
    tenant, para que un criterio pueda apuntar a cualquiera de los dos.
    """
    faltan: list[str] = []
    for criterio in etapa.criterios_salida or []:
        campo = criterio if isinstance(criterio, str) else str(criterio.get("campo", ""))
        if not campo:
            continue
        valor = getattr(oportunidad, campo, None)
        if valor is None:
            valor = (oportunidad.campos or {}).get(campo)
        if valor in (None, "", 0, Decimal(0), [], {}):
            faltan.append(campo)
    return faltan


def _cerrar(uow: UnidadDeTrabajo, oportunidad: Oportunidad, *, ganada: bool, motivo: str) -> None:
    """Marca la oportunidad como cerrada y la bloquea si así está configurado."""
    from crmcore.runtime import settings as rt

    aplicar_estado(
        uow.db,
        oportunidad,
        objeto="oportunidad",
        nuevo="ganada" if ganada else "perdida",
        motivo=motivo,
    )
    oportunidad.fecha_cierre_real = hoy(uow.db)
    oportunidad.probabilidad = 100 if ganada else 0
    if bool(rt.efectivo("bloquear_al_cerrar", uow.db)):
        oportunidad.bloqueada = True

    if not ganada:
        admitidos = vocabulario.valores(uow.db, "motivos_perdida")
        if bool(rt.efectivo("exigir_motivo_perdida", uow.db)) and not (
            oportunidad.motivo_perdida or motivo
        ):
            raise ErrorValidacion(
                "Para cerrar como perdida hace falta un motivo normalizado",
                error_code="sales.motivo_perdida_requerido",
                detalle={"admitidos": sorted(admitidos)},
            )
        # Y se comprueba que sea uno de los de la lista. No se comprobaba: la
        # lista se enseñaba en el mensaje de error y luego entraba cualquier
        # texto, así que el informe de motivos de pérdida —para el que existe
        # el campo— salía con tantas categorías como formas de escribirlas.
        elegido = oportunidad.motivo_perdida or motivo
        if elegido and elegido not in admitidos:
            raise ErrorValidacion(
                f"«{elegido}» no es un motivo de pérdida reconocido",
                error_code="sales.motivo_perdida_invalido",
                detalle={"admitidos": sorted(admitidos)},
            )
        if not oportunidad.motivo_perdida:
            oportunidad.motivo_perdida = motivo

    # Lo que se dijo en las revisiones se compara con lo que pasó, y «lo que
    # pasó» sólo se sabe aquí. Sin esta línea la columna `resultado` se quedaba
    # siempre vacía y la calibración contestaba «no hay suficientes para
    # concluir» para siempre, con el archivo lleno de revisiones.
    anotar_resultado(uow, oportunidad.id, ganada=ganada)

    # La lección: pendiente desde ya, y obligatoria si se ha perdido. Sin ella,
    # lo que enseñó esta oportunidad se queda en la cabeza de quien la llevaba.
    from services.sales import lecciones

    lecciones.al_cerrar(uow, oportunidad, ganada=ganada)

    uow.emitir(
        "opportunity.won" if ganada else "opportunity.lost",
        subject=("oportunidad", oportunidad.id),
        data={
            "oportunidad_id": str(oportunidad.id),
            "cuenta_id": str(oportunidad.cuenta_id) if oportunidad.cuenta_id else "",
            "importe": str(oportunidad.importe),
            "moneda": oportunidad.moneda,
            **({} if ganada else {"motivo": oportunidad.motivo_perdida or ""}),
        },
    )
    registrar(
        uow.db,
        accion="oportunidad.ganada" if ganada else "oportunidad.perdida",
        objeto="oportunidad",
        objeto_id=oportunidad.id,
        tenant_id=oportunidad.tenant_id,
        datos={"importe": str(oportunidad.importe), "motivo": oportunidad.motivo_perdida},
    )


# Los de fábrica, como los de descarte: el punto de partida de cada empresa, no
# su techo.
MOTIVOS_PERDIDA: frozenset[str] = frozenset(
    {
        "precio",
        "producto",
        "plazo",
        "competencia",
        "sin_presupuesto",
        "sin_decision",
        "proyecto_cancelado",
        "solucion_interna",
        "sin_respuesta",
    }
)

vocabulario.registrar(
    "motivos_perdida",
    MOTIVOS_PERDIDA,
    etiqueta="Motivos de pérdida",
    descripcion=(
        "Por qué se pierde una oportunidad. Se exige al cerrarla como perdida "
        "si el ajuste correspondiente está activo, y es lo que agrupa el "
        "informe de pérdidas."
    ),
)

vocabulario.registrar(
    "motivos_descarte",
    MOTIVOS_DESCARTE,
    etiqueta="Motivos de descarte",
    descripcion="Por qué se descarta un lead sin llegar a convertirlo.",
)


def reabrir(
    uow: UnidadDeTrabajo, oportunidad_id: UUID, *, etapa_id: UUID, motivo: str
) -> Oportunidad:
    """Reabre una oportunidad cerrada (CRM-03.01.01.14).

    Es un acto **explícito y auditado**, y emite su propio evento: quien haya
    consumido el cierre —la previsión del trimestre, el cálculo de comisiones,
    el pedido que se creó— tiene que poder deshacerlo. Sin ese evento, reabrir
    deja el resto del sistema con datos de un cierre que ya no existe.
    """
    oportunidad = _oportunidad(uow.db, oportunidad_id)
    if significa("oportunidad", oportunidad.estado, "abierto", uow.db):
        raise Conflicto("Esa oportunidad ya está abierta", error_code="sales.ya_abierta")
    if not motivo.strip():
        raise ErrorValidacion(
            "Reabrir exige un motivo escrito", error_code="sales.reapertura_sin_motivo"
        )

    etapa = uow.db.get(Etapa, etapa_id)
    if etapa is None or etapa.pipeline_id != oportunidad.pipeline_id or etapa.terminal:
        raise ErrorValidacion(
            "Hay que reabrir en una etapa no terminal del mismo pipeline",
            error_code="sales.etapa_reapertura_invalida",
        )

    estado_previo = oportunidad.estado
    # Al estado inicial de esta empresa, que siempre es uno abierto.
    inicial = maquina_efectiva("oportunidad", uow.db).inicial
    aplicar_estado(uow.db, oportunidad, objeto="oportunidad", nuevo=inicial, motivo=motivo)
    oportunidad.bloqueada = False
    oportunidad.etapa_id = etapa.id
    oportunidad.etapa_desde = datetime.now(timezone.utc)
    oportunidad.probabilidad = etapa.probabilidad
    oportunidad.fecha_cierre_real = None
    oportunidad.reaperturas += 1

    registrar(
        uow.db,
        accion="oportunidad.reabierta",
        objeto="oportunidad",
        objeto_id=oportunidad_id,
        tenant_id=oportunidad.tenant_id,
        datos={"estado_previo": estado_previo, "reaperturas": oportunidad.reaperturas},
        motivo=motivo,
    )
    uow.emitir(
        "opportunity.reopened",
        subject=("oportunidad", oportunidad_id),
        data={
            "oportunidad_id": str(oportunidad_id),
            "estado_previo": estado_previo,
            "motivo": motivo,
        },
    )
    return oportunidad


def exigir_oportunidad(db: Session, oportunidad_id: UUID) -> Oportunidad:
    """La oportunidad, o 404. Misma razón que `exigir_lead`."""
    return _oportunidad(db, oportunidad_id)


def _oportunidad(db: Session, oportunidad_id: UUID) -> Oportunidad:
    oportunidad = db.get(Oportunidad, oportunidad_id)
    if oportunidad is None or oportunidad.deleted_at is not None:
        raise NoEncontrado("La oportunidad no existe", error_code="sales.oportunidad_no_encontrada")
    # Punto único de decisión (CRM-00.05.02.18). Va en el cargador y no en cada
    # endpoint a propósito: el endpoint que se olvide de llamarlo es el agujero,
    # y aquí pasan TODOS —la ficha, la edición, el borrado y lo que venga—.
    # Si una política lo niega, esto corta con 403 y la explicación dentro.
    exigir(db, objeto="oportunidad", accion="read", registro=oportunidad)
    return oportunidad


def _exigir_editable(db: Session, oportunidad: Oportunidad) -> None:
    """Una oportunidad cerrada y bloqueada no se edita: hay que reabrirla.

    Sus números ya están en un informe que alguien ha mirado y en una comisión
    que quizá ya se ha pagado. Editarla en silencio cambia el pasado.
    """
    if oportunidad.bloqueada:
        raise Conflicto(
            "La oportunidad está cerrada y bloqueada. Reábrela si hay que cambiarla.",
            error_code="sales.oportunidad_bloqueada",
            detalle={"estado": oportunidad.estado},
        )


def actualizar_oportunidad(
    uow: UnidadDeTrabajo, oportunidad_id: UUID, cambios: dict[str, Any]
) -> Oportunidad:
    oportunidad = _oportunidad(uow.db, oportunidad_id)
    _exigir_editable(uow.db, oportunidad)
    anterior = oportunidad.a_dict()
    importe_antes = oportunidad.importe
    fecha_antes = oportunidad.fecha_cierre

    # Fijar la probabilidad a mano la marca como manual (CRM-03.01.01.04): si no,
    # el siguiente cambio de etapa la pisaría y el comercial dejaría de
    # ajustarla a la tercera vez, convirtiendo el dato en decorativo.
    if "probabilidad" in cambios and cambios["probabilidad"] != oportunidad.probabilidad:
        oportunidad.probabilidad_manual = True

    for campo, valor in cambios.items():
        if hasattr(oportunidad, campo):
            setattr(oportunidad, campo, valor)

    # Deslizamiento (CRM-03.01.01.13). Se anota aquí y no en quien llame: un
    # historial que dependa de que alguien se acuerde tiene huecos justo donde
    # importa, y el hueco típico es el cambio de fecha sin cambio de etapa, que
    # es precisamente el deslizamiento que explica el trimestre.
    from services.sales.forecast import anotar_cambio_de_prevision

    anotar_cambio_de_prevision(
        uow.db,
        oportunidad,
        importe_antes=importe_antes,
        fecha_antes=fecha_antes,
        motivo=str(cambios.get("motivo_cambio") or ""),
    )

    registrar_cambios(
        uow.db,
        objeto="oportunidad",
        objeto_id=oportunidad.id,
        anterior=anterior,
        nuevo=oportunidad.a_dict(),
        # Se pasa explícito: este camino lo recorren también el ejecutor de
        # trabajos y los consumidores de eventos, que no tienen contexto
        # ambiental, y sin esto el historial se escribía con tenant nulo.
        tenant_id=uow.tenant_id,
    )
    return oportunidad


# ── Líneas ────────────────────────────────────────────────────────────────


def duplicar_oportunidad(
    uow: UnidadDeTrabajo, oportunidad_id: UUID, *, nombre: str | None = None
) -> Oportunidad:
    """Copia una oportunidad **con sus líneas** (CRM-07.01.01.07).

    Lo que se copia es lo que se ofertó —cuenta, contacto, embudo, moneda,
    fecha prevista, campos propios y cada línea con su precio y su coste
    pactados—. Lo que **no** se copia es lo que dice cómo le fue a la original:
    la copia empieza en la primera etapa, abierta y sin historial de etapas,
    porque una venta nueva no ha pasado por donde pasó la otra. Con el estado
    copiado, la previsión contaría dos veces lo que se cerró una.

    Pasa por `crear_oportunidad_nueva`, como cualquier alta: numeración,
    eventos y reglas de la etapa son los de siempre.
    """
    original = _oportunidad(uow.db, oportunidad_id)
    copia = crear_oportunidad_nueva(
        uow,
        nombre=(nombre or "").strip() or f"{original.nombre} (copia)",
        descripcion=original.descripcion,
        cuenta_id=original.cuenta_id,
        contacto_id=original.contacto_id,
        pipeline_id=original.pipeline_id,
        importe=original.importe or Decimal(0),
        moneda=original.moneda,
        fecha_cierre=original.fecha_cierre,
        owner_id=original.owner_id,
        campos=dict(original.campos or {}),
    )
    lineas = (
        uow.db.execute(
            select(LineaOportunidad)
            .where(LineaOportunidad.oportunidad_id == original.id)
            .order_by(LineaOportunidad.orden)
        )
        .scalars()
        .all()
    )
    copiables = [
        c.key
        for c in LineaOportunidad.__table__.columns
        if c.key not in ("id", "oportunidad_id", "created_at", "updated_at")
    ]
    for linea in lineas:
        uow.db.add(
            LineaOportunidad(**{k: getattr(linea, k) for k in copiables}, oportunidad_id=copia.id)
        )
    uow.db.flush()
    if lineas:
        recalcular_total(uow.db, copia, anotar=False)
    registrar(
        uow.db,
        accion="oportunidad.duplicada",
        objeto="oportunidad",
        objeto_id=copia.id,
        datos={"de": str(original.id), "lineas": len(lineas)},
    )
    return copia


def recalcular_total(db: Session, oportunidad: Oportunidad, *, anotar: bool = True) -> Decimal:
    """Suma las líneas y actualiza el importe de la oportunidad.

    El importe de la cabecera se mantiene calculado en vez de dejar que difiera:
    una oportunidad cuyo importe no coincide con sus líneas produce un pipeline
    que no cuadra con lo que se ha ofertado, y nadie sabe cuál de los dos creer.

    Y el cambio queda en el historial de importe (CRM-03.01.01.13), como cuando
    se edita a mano. Añadir la primera línea a una oportunidad de 60.000 € la
    dejaba en 11.000 € sin rastro: «lo que se ha movido» seguía diciendo 60.000
    (visto el 10-11-2026). `anotar=False` sólo para una copia recién hecha, que
    no se ha movido: nace así.
    """
    antes = oportunidad.importe
    total = db.execute(
        select(func.coalesce(func.sum(LineaOportunidad.total), 0)).where(
            LineaOportunidad.oportunidad_id == oportunidad.id
        )
    ).scalar_one()
    oportunidad.importe = Decimal(total)
    if anotar and antes is not None and Decimal(antes) != oportunidad.importe:
        from services.sales.forecast import anotar_cambio_de_prevision

        anotar_cambio_de_prevision(
            db,
            oportunidad,
            importe_antes=Decimal(antes),
            fecha_antes=oportunidad.fecha_cierre,
            motivo="Cambian las líneas",
        )
    return oportunidad.importe


def calcular_linea(cantidad: Decimal, precio: Decimal, descuento_pct: Decimal) -> Decimal:
    """Total de una línea, redondeado a dos decimales.

    El redondeo se hace **aquí y una sola vez**: redondear en cada paso acumula
    diferencias que acaban en un total que no cuadra con la factura.
    """
    from decimal import ROUND_HALF_UP

    bruto = (cantidad or Decimal(0)) * (precio or Decimal(0))
    neto = bruto * (Decimal(100) - (descuento_pct or Decimal(0))) / Decimal(100)
    return neto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ── Pipeline y estancamiento ──────────────────────────────────────────────


def resumen_pipeline(
    db: Session, tenant_id: UUID, *, pipeline_id: UUID | None = None
) -> dict[str, Any]:
    """Importe y número de oportunidades por etapa, con el ponderado.

    El ponderado va **además** del bruto, no en su lugar: el bruto dice cuánto
    hay sobre la mesa y el ponderado cuánto se espera cerrar, y confundirlos es
    el origen de la mitad de las discusiones sobre una previsión.
    """
    consulta = (
        select(
            Etapa.id,
            Etapa.nombre,
            Etapa.orden,
            Etapa.probabilidad,
            func.count(Oportunidad.id),
            func.coalesce(func.sum(Oportunidad.importe), 0),
        )
        .join(Oportunidad, Oportunidad.etapa_id == Etapa.id, isouter=True)
        .where(Etapa.tenant_id == tenant_id)
        .group_by(Etapa.id, Etapa.nombre, Etapa.orden, Etapa.probabilidad)
        .order_by(Etapa.orden)
    )
    if pipeline_id:
        consulta = consulta.where(Etapa.pipeline_id == pipeline_id)

    etapas: list[dict[str, Any]] = []
    total_bruto = Decimal(0)
    total_ponderado = Decimal(0)
    for _eid, nombre, orden, prob, cuantas, importe in db.execute(consulta).all():
        importe = Decimal(importe or 0)
        ponderado = (importe * Decimal(prob) / Decimal(100)).quantize(Decimal("0.01"))
        total_bruto += importe
        total_ponderado += ponderado
        etapas.append(
            {
                "etapa": nombre,
                "orden": orden,
                "probabilidad": prob,
                "oportunidades": int(cuantas or 0),
                "importe": str(importe),
                "importe_ponderado": str(ponderado),
            }
        )
    return {
        "etapas": etapas,
        "total": str(total_bruto),
        "total_ponderado": str(total_ponderado),
    }


def oportunidades_estancadas(db: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    """Oportunidades que llevan demasiado en su etapa (CRM-03.01.01.12).

    El umbral es **por etapa**, con un valor de reserva configurable: estar tres
    semanas en «negociación» puede ser normal y en «primer contacto» no lo es.
    """
    from crmcore.runtime import settings as rt

    defecto = int(rt.efectivo("dias_estancamiento_defecto", db) or 30)
    ahora = datetime.now(timezone.utc)

    filas = db.execute(
        select(Oportunidad, Etapa.nombre, Etapa.dias_estancamiento)
        .join(Etapa, Etapa.id == Oportunidad.etapa_id)
        .where(
            Oportunidad.tenant_id == tenant_id,
            Oportunidad.estado.in_(con_significado("oportunidad", "abierto", db)),
            Oportunidad.deleted_at.is_(None),
        )
    ).all()

    estancadas = []
    for oportunidad, etapa_nombre, dias_etapa in filas:
        limite = int(dias_etapa or defecto)
        dias = (ahora - oportunidad.etapa_desde).days
        if dias >= limite:
            estancadas.append(
                {
                    "id": str(oportunidad.id),
                    "codigo": oportunidad.codigo,
                    "nombre": oportunidad.nombre,
                    "etapa": etapa_nombre,
                    "dias_en_etapa": dias,
                    "limite": limite,
                    "importe": str(oportunidad.importe),
                    "owner_id": str(oportunidad.owner_id) if oportunidad.owner_id else None,
                }
            )
    return sorted(estancadas, key=lambda e: -e["dias_en_etapa"])
