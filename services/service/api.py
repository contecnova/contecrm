"""API HTTP del servicio de atención (CRM-04.01.01, CRM-04.01.02)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from crmcore.datos.estados import maquina_efectiva, presentar
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import aplicar_filtros_de_la_url, ruta_de_vocabulario
from crmcore.http.pagination import CONTAR_TOTAL_DESCRIPCION, PaginaDeListado, paginar_consulta
from crmcore.http.parametros import admite_parametros_abiertos
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, not_, or_, select

# Se importa al arrancar, y no sólo al llamar: declara el vocabulario
# `resultados_llamada`, y un vocabulario que no se ha registrado al montar la app
# no tiene ruta (`crmcore.service` sólo monta las de los que ya existen).
from services.service import marcador as _marcador  # noqa: F401
from services.service import servicio as svc
from services.service.ajustes import ajustes
from services.service.estados import terminales
from services.service.modelos import (
    VOCABULARIO_PRIORIDAD,
    Caso,
    CategoriaCaso,
    DefinicionSLA,
    EventoCaso,
)

router_casos = APIRouter(prefix="/casos", tags=["casos"])
router_taxonomia = APIRouter(prefix="/categorias-caso", tags=["casos"])
router_sla = APIRouter(prefix="/sla", tags=["SLA"])


# ── Taxonomía (CRM-04.01.01.02) ───────────────────────────────────────────


class CrearCategoria(BaseModel):
    clave: str = Field(max_length=80)
    nombre: str = Field(max_length=200)
    padre_id: UUID | None = None
    linea: str = Field("general", max_length=60)
    orden: int = 100
    seleccionable: bool = True
    prioridad_sugerida: str | None = None


@router_taxonomia.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Árbol de clasificación de casos",
    description=(
        "Es un árbol y no dos campos fijos porque cada línea de servicio "
        "clasifica a su profundidad: soporte de software llega a tres niveles y "
        "mantenimiento de instalaciones a cinco. Con dos campos, el tercer nivel "
        "acaba concatenado dentro del segundo y los informes dejan de agrupar."
    ),
)
def arbol(db: DbDep, principal: AutenticadoDep, linea: str = Query("", max_length=60)) -> Any:
    return svc.arbol_de_categorias(db, principal.tenant_id, linea)


@router_taxonomia.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Añadir un nodo al árbol",
)
def crear_categoria(datos: CrearCategoria, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = CategoriaCaso(tenant_id=principal.tenant_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id), "clave": fila.clave, "nombre": fila.nombre}


# ── SLA (CRM-04.01.02.02) ─────────────────────────────────────────────────


class CrearSLA(BaseModel):
    clave: str = Field(max_length=60)
    nombre: str = Field(max_length=200)
    prioridad: str | None = None
    tier_cliente: str | None = None
    cuenta_id: UUID | None = None
    horas_primera_respuesta: float | None = None
    horas_resolucion: float | None = None
    horas_actualizacion: float | None = None
    calendario: str = Field("", max_length=60)
    aviso_pct: int = Field(80, ge=10, le=100)


@router_sla.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Publicar una definición de SLA",
    description=(
        "Cada publicación es una **versión nueva**: cambiar el SLA no reescribe "
        "el pasado. Un contrato renegociado no puede convertir en incumplidos "
        "casos que se atendieron a tiempo con las reglas de entonces, ni al "
        "revés — y esa es la trampa del SLA guardado como una fila que se edita."
    ),
)
def crear_sla(datos: CrearSLA, uow: UowDep, principal: AutenticadoDep) -> Any:
    from sqlalchemy import func as _func

    svc.exigir_calendario(uow.db, principal.tenant_id, datos.calendario or "")

    ultima = uow.db.execute(
        select(_func.max(DefinicionSLA.version)).where(
            DefinicionSLA.tenant_id == principal.tenant_id,
            DefinicionSLA.clave == datos.clave,
        )
    ).scalar_one()
    fila = DefinicionSLA(
        tenant_id=principal.tenant_id, version=int(ultima or 0) + 1, **datos.model_dump()
    )
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id), "clave": fila.clave, "version": fila.version}


@router_sla.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Definiciones de SLA vigentes",
)
def listar_sla(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(DefinicionSLA)
            .where(DefinicionSLA.tenant_id == principal.tenant_id)
            .order_by(DefinicionSLA.clave, DefinicionSLA.version.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "clave": f.clave,
            "version": f.version,
            "nombre": f.nombre,
            "prioridad": f.prioridad,
            "tier_cliente": f.tier_cliente,
            "horas_primera_respuesta": float(f.horas_primera_respuesta or 0) or None,
            "horas_resolucion": float(f.horas_resolucion or 0) or None,
            "calendario": f.calendario,
            "activa": f.activa,
        }
        for f in filas
    ]


@router_sla.get(
    "/en-riesgo",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Casos que van a incumplir si nadie hace nada",
    description=(
        "Avisar **cuando ya se ha incumplido** no sirve de nada: el "
        "incumplimiento ya está. Lo único que cambia algo es avisar antes.\n\n"
        "Se ordena por lo que **queda**, no por prioridad: un caso crítico con "
        "seis horas por delante puede esperar a uno medio que vence en diez "
        "minutos. Y lo ya incumplido se marca aparte, para que la lista no se "
        "llene de cosas sin remedio y deje de mirarse."
    ),
)
def en_riesgo(
    db: DbDep,
    principal: AutenticadoDep,
    umbral_pct: int | None = Query(
        None, ge=1, le=100, description="Sin valor, el del tenant (`sla_riesgo_umbral_pct`)"
    ),
) -> Any:
    if umbral_pct is None:
        from crmcore.runtime import settings as rt

        umbral_pct = int(
            rt.efectivo("sla_riesgo_umbral_pct", db, default=ajustes().sla_riesgo_umbral_pct)
        )
    return svc.en_riesgo(db, principal.tenant_id, umbral_pct=umbral_pct)


@router_sla.get(
    "/cumplimiento",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Cumplimiento de SLA del periodo",
    description=(
        "La primera respuesta y la resolución se cuentan **aparte**: un "
        "porcentaje único esconde que se contesta rápido y se resuelve tarde, "
        "que es el patrón más común y el que más queja genera.\n\n"
        "Sin casos con compromiso no se dice 100 %: sería un verde que nadie se "
        "ha ganado."
    ),
)
def cumplimiento(
    db: DbDep,
    principal: AutenticadoDep,
    desde: date = Query(...),
    hasta: date = Query(...),
) -> Any:
    return svc.cumplimiento(db, principal.tenant_id, desde=desde, hasta=hasta)


# ── Casos ─────────────────────────────────────────────────────────────────


class AbrirCaso(BaseModel):
    asunto: str = Field(max_length=300)
    descripcion: str | None = None
    tipo: str = Field("incidencia", max_length=40)
    categoria_id: UUID | None = None
    # De la lista de la empresa (vocabulario `prioridades_caso`): el formulario
    # la ofrece como desplegable y el servicio la valida al abrir.
    prioridad: str | None = Field(
        None,
        max_length=120,
        json_schema_extra={"x-vocabulario": ruta_de_vocabulario(VOCABULARIO_PRIORIDAD)},
    )
    severidad: str | None = None
    origen: str = Field("manual", max_length=30)
    cuenta_id: UUID | None = None
    contacto_id: UUID | None = None
    producto_id: UUID | None = None
    activo_id: UUID | None = None
    contrato_id: UUID | None = None
    pedido_id: UUID | None = None
    padre_id: UUID | None = None
    owner_id: UUID | None = None
    equipo: str | None = None
    tier_cliente: str = ""
    campos: dict[str, Any] = Field(default_factory=dict)


@router_casos.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Abrir un caso",
    description=(
        "**Severidad y prioridad son dos campos.** La severidad es del problema "
        "—qué está roto y cuánto— y la prioridad es de la respuesta —en qué "
        "orden se atiende—. Fundirlas hace imposible decir «esto es grave pero "
        "puede esperar» y «esto es menor pero es para el cliente que renueva el "
        "viernes», y en cuanto se funden alguien marca todo como crítico.\n\n"
        "Solo las **hojas** del árbol clasifican: dejar elegir un nodo intermedio "
        "convierte «software» en un cajón donde acaba la mitad de los casos."
    ),
)
def abrir(datos: AbrirCaso, uow: UowDep, principal: AutenticadoDep) -> Any:
    cuerpo = datos.model_dump(exclude_none=True)
    tier = cuerpo.pop("tier_cliente", "")
    asunto = cuerpo.pop("asunto")
    caso = svc.abrir_caso(uow, asunto=asunto, tier_cliente=tier, **cuerpo)
    return {
        "id": str(caso.id),
        "codigo": caso.codigo,
        "prioridad": caso.prioridad,
        "sla": caso.sla_clave,
        "vence_primera_respuesta_at": (
            caso.vence_primera_respuesta_at.isoformat() if caso.vence_primera_respuesta_at else None
        ),
        "vence_resolucion_at": (
            caso.vence_resolucion_at.isoformat() if caso.vence_resolucion_at else None
        ),
        # Se dice cuando no hay SLA: un caso sin compromiso no es un caso
        # cumplido, y si no se dice aquí nadie lo mira hasta el informe de fin de
        # mes, donde sale como «sin datos».
        "aviso": ""
        if caso.sla_clave
        else "No hay ninguna definición de SLA que aplique a este caso",
    }


@router_casos.get(
    "",
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Buscar casos",
    description=(
        # Que antes devolviera una lista pelada con tope de 50 —y que por eso
        # «casos abiertos» dijera 50 habiendo 153— es historia del código.
        "Los casos de soporte, por páginas. Se puede filtrar por estado, " "prioridad y cuenta."
    ),
)
def listar(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query("", max_length=30),
    prioridad: str = Query("", max_length=20),
    cuenta_id: UUID | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    contar: bool = Query(False, description=CONTAR_TOTAL_DESCRIPCION),
) -> Any:
    consulta = select(Caso).where(Caso.tenant_id == principal.tenant_id, Caso.deleted_at.is_(None))
    if estado:
        consulta = consulta.where(Caso.estado == estado)
    if prioridad:
        consulta = consulta.where(Caso.prioridad == prioridad)
    if cuenta_id:
        consulta = consulta.where(Caso.cuenta_id == cuenta_id)
    # Los filtros comunes, con sus rangos. Aquí hacen falta de verdad: la
    # bandeja separa lo que YA incumplió de lo que va a incumplir, y eso es
    # `vence_at__hasta=<ahora>` y `vence_at__desde=<ahora>&__hasta=<ahora+N>`.
    # Sin ellos, la pantalla se traía una página y contaba sobre ella: decía
    # «3 incumplidos» cuando había cincuenta.
    consulta = aplicar_filtros_de_la_url(
        request, Caso, consulta, principal=principal, db=db, objeto="caso"
    )
    maquina = maquina_efectiva("caso", db)
    return paginar_consulta(
        db,
        Caso,
        consulta,
        limite=limite,
        cursor=cursor,
        fila_a_dict=lambda f: {
            "id": str(f.id),
            "codigo": f.codigo,
            "asunto": f.asunto,
            "estado": f.estado,
            **presentar(maquina, f.estado),
            "prioridad": f.prioridad,
            "severidad": f.severidad,
            "vence_resolucion_at": (
                f.vence_resolucion_at.isoformat() if f.vence_resolucion_at else None
            ),
            "incumplio_resolucion": f.incumplio_resolucion,
        },
        contar=contar,
    )


@router_casos.get(
    "/bandeja",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="La bandeja repartida por urgencia de SLA",
    description=(
        "Los casos abiertos en tres montones: **incumplidos**, **en riesgo** y "
        "el resto, con el total de cada uno.\n\n"
        "El reparto se hace aquí y no en la pantalla por dos motivos. El "
        "primero es que el corte entre «en riesgo» y «el resto» es un ajuste "
        "del tenant (`sla_riesgo_horas`), no una constante: cuatro horas de "
        "antelación en un soporte con SLA de cuatro horas pone la bandeja "
        "entera en rojo, y en uno de cinco días avisa cuando ya no da tiempo. "
        "El segundo es que los totales tienen que ser de TODO, no de la página "
        "que se haya traído: una bandeja que dice «3 incumplidos» habiendo "
        "cincuenta se mira una vez."
    ),
)
def bandeja(
    db: DbDep,
    principal: AutenticadoDep,
    por_monton: int = Query(25, ge=1, le=100, description="Cuántos se devuelven de cada montón"),
) -> Any:
    from datetime import datetime, timezone

    from crmcore.runtime import settings as rt
    from sqlalchemy import func

    horas = float(rt.efectivo("sla_riesgo_horas", db) or ajustes().sla_riesgo_horas)
    ahora = datetime.now(timezone.utc)
    corte = ahora + timedelta(hours=horas)

    # Abiertos: lo cerrado y lo resuelto no es trabajo pendiente, y meterlo
    # aquí hace que la bandeja crezca para siempre y deje de abrirse.
    base = select(Caso).where(
        Caso.tenant_id == principal.tenant_id,
        Caso.deleted_at.is_(None),
        Caso.estado.not_in(terminales(db)),
    )

    # Lo que YA incumplió. Incluye lo marcado por el motor de SLA aunque su
    # fecha se haya movido después: el incumplimiento ya ocurrió. Con la PAUSA
    # como en el informe (`servicio._incumplio_resolucion`): mientras el caso
    # espera al cliente el reloj está parado, y solo cuenta si el plazo ya había
    # pasado cuando se paró. Antes se miraba la fecha de hoy y la bandeja cargaba
    # al equipo la espera del cliente (auditoría 13-11-2026, FUN-B-27).
    incumplido = or_(
        Caso.incumplio_resolucion.is_(True),
        and_(
            Caso.vence_resolucion_at.is_not(None),
            func.coalesce(Caso.pausado_desde, ahora) > Caso.vence_resolucion_at,
        ),
    )
    # Lo que va a incumplir si nadie lo toca. Es el único montón que se puede
    # salvar, y por eso va separado del anterior: son dos trabajos distintos
    # —uno se atiende, el otro se explica—. Un caso en pausa no corre riesgo:
    # su reloj está parado.
    en_riesgo = and_(
        Caso.incumplio_resolucion.is_(False),
        Caso.pausado_desde.is_(None),
        Caso.vence_resolucion_at.is_not(None),
        Caso.vence_resolucion_at >= ahora,
        Caso.vence_resolucion_at < corte,
    )
    montones = {
        "incumplidos": base.where(incumplido),
        "en_riesgo": base.where(en_riesgo),
        # Lo demás, incluido lo que no tiene SLA. «Sin plazo» no es «urgente»
        # ni «tranquilo»: es un caso que nadie ha clasificado, y esconderlo lo
        # deja sin atender para siempre. Se define como «ni lo uno ni lo otro»
        # para que ningún caso se quede fuera ni salga en dos montones.
        "resto": base.where(not_(incumplido), not_(en_riesgo)),
    }

    def _fila(c: Caso) -> dict[str, Any]:
        return {
            "id": str(c.id),
            "codigo": c.codigo,
            "asunto": c.asunto,
            "estado": c.estado,
            "prioridad": c.prioridad,
            "severidad": c.severidad,
            "cuenta_id": str(c.cuenta_id) if c.cuenta_id else None,
            "equipo": c.equipo,
            "vence_resolucion_at": (
                c.vence_resolucion_at.isoformat() if c.vence_resolucion_at else None
            ),
            "incumplio_resolucion": c.incumplio_resolucion,
        }

    salida: dict[str, Any] = {"riesgo_horas": horas, "ahora": ahora.isoformat()}
    for nombre, consulta in montones.items():
        # El total va aparte de las filas: devolver sólo las primeras y dejar
        # que la pantalla las cuente es exactamente el error que esto viene a
        # arreglar.
        total = db.execute(select(func.count()).select_from(consulta.subquery())).scalar_one()
        filas = (
            db.execute(
                consulta.order_by(Caso.vence_resolucion_at.asc().nulls_last(), Caso.id).limit(
                    por_monton
                )
            )
            .scalars()
            .all()
        )
        salida[nombre] = {"total": int(total), "casos": [_fila(c) for c in filas]}
    return salida


@router_casos.get(
    "/{caso_id}",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Ficha del caso",
)
def leer(caso_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    caso = svc.exigir_caso(db, caso_id)
    eventos = (
        db.execute(
            select(EventoCaso)
            .where(EventoCaso.caso_id == caso.id, EventoCaso.tenant_id == principal.tenant_id)
            .order_by(EventoCaso.created_at)
        )
        .scalars()
        .all()
    )
    return {
        "id": str(caso.id),
        "codigo": caso.codigo,
        "asunto": caso.asunto,
        "descripcion": caso.descripcion,
        "estado": caso.estado,
        **presentar(maquina_efectiva("caso", db), caso.estado),
        "prioridad": caso.prioridad,
        "severidad": caso.severidad,
        # La cola en la que está: la ficha la quita de los destinos al derivar
        # (CRM-04.01.01.08), porque derivar a donde ya está no mueve nada.
        "equipo": caso.equipo,
        "clasificacion": svc.ruta_de_categoria(db, principal.tenant_id, caso.categoria_id)
        if caso.categoria_id
        else [],
        "campos": dict(caso.campos or {}),
        # ── Con QUÉ tiene que ver este caso (CRM-04.01.01.03) ─────────────
        #
        # Estaban guardados y esta ruta no los devolvía. El listado de la
        # bandeja sí manda `cuenta_id`, así que el dato llegaba a una pantalla
        # y no a la otra: **abrir el caso perdía de qué cliente era**, que es
        # lo primero que se mira al atenderlo.
        #
        # Van los seis y no sólo la cuenta: un caso sobre un activo instalado
        # se atiende distinto que uno sobre un pedido, y sin el activo hay que
        # preguntárselo al cliente, que ya lo dijo al abrirlo.
        "relacionado_con": {
            "cuenta_id": str(caso.cuenta_id) if caso.cuenta_id else None,
            "contacto_id": str(caso.contacto_id) if caso.contacto_id else None,
            "producto_id": str(caso.producto_id) if caso.producto_id else None,
            "activo_id": str(caso.activo_id) if caso.activo_id else None,
            "contrato_id": str(caso.contrato_id) if caso.contrato_id else None,
            "pedido_id": str(caso.pedido_id) if caso.pedido_id else None,
        },
        # ── Cómo se cerró, y cuántas veces se ha reabierto ────────────────
        #
        # (CRM-04.01.01.09, CRM-04.01.01.10.) El motivo tipificado agrupa para
        # el informe y la resolución explica para la persona: con uno solo, o
        # no se puede contar o no se puede entender.
        #
        # `validacion_cliente` es la mitad que casi nunca se publica: un caso
        # cerrado por el agente y pendiente de que el cliente lo dé por bueno
        # **no está cerrado**, y en una lista se ve igual que uno que sí.
        #
        # Y `reaperturas` con el cierre, no aparte: un caso cerrado tres veces
        # no es un caso resuelto, y el número al lado del motivo es lo que
        # hace que se lea la primera vez.
        "cierre": {
            "motivo": caso.motivo_cierre,
            "resolucion": caso.resolucion,
            "validacion_cliente": caso.validacion_cliente,
            "reaperturas": caso.reaperturas,
            "cerrado_at": caso.cerrado_at.isoformat() if caso.cerrado_at else None,
            "resuelto_at": caso.resuelto_at.isoformat() if caso.resuelto_at else None,
        },
        "sla": {
            "clave": caso.sla_clave,
            "version": caso.sla_version,
            "vence_primera_respuesta_at": (
                caso.vence_primera_respuesta_at.isoformat()
                if caso.vence_primera_respuesta_at
                else None
            ),
            "vence_resolucion_at": (
                caso.vence_resolucion_at.isoformat() if caso.vence_resolucion_at else None
            ),
            "primera_respuesta_at": (
                caso.primera_respuesta_at.isoformat() if caso.primera_respuesta_at else None
            ),
            "pausa_acumulada_s": caso.pausa_acumulada_s,
            # Parado AHORA, y desde cuándo: sin esto la ficha enseñaba los
            # vencimientos como si corrieran mientras se espera al cliente.
            "pausado_desde": caso.pausado_desde.isoformat() if caso.pausado_desde else None,
            "incumplio_primera_respuesta": caso.incumplio_primera_respuesta,
            "incumplio_resolucion": caso.incumplio_resolucion,
        },
        "relaciones": svc.arbol_de_caso(db, principal.tenant_id, caso.id),
        "historial": [
            {"tipo": e.tipo, "detalle": e.detalle, "at": e.created_at.isoformat()} for e in eventos
        ],
    }


class CambiarEstado(BaseModel):
    estado: str = Field(max_length=30)
    motivo: str = ""


@router_casos.put(
    "/{caso_id}/estado",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Mover el caso de estado",
    description=(
        "Entrar en «esperando cliente» **para el reloj** y salir lo reanuda "
        "desplazando el vencimiento por el tiempo parado. Si no se desplazara, "
        "parar el reloj sería decorativo: el caso se marcaría incumplido por una "
        "espera que era del cliente.\n\n"
        "La pausa se **acumula**: un caso que entra y sale cuatro veces perdería "
        "tres de las cuatro esperas si solo se guardara la última."
    ),
)
def cambiar_estado(
    caso_id: UUID, datos: CambiarEstado, uow: UowDep, principal: AutenticadoDep
) -> Any:
    caso = svc.cambiar_estado(uow, caso_id, estado=datos.estado, motivo=datos.motivo)
    return {"id": str(caso.id), "estado": caso.estado, "pausa_s": caso.pausa_acumulada_s}


@router_casos.post(
    "/{caso_id}/estado",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Mover el caso de estado (desde la ficha)",
    description=(
        "Lo mismo que el `PUT`: es la forma en que la cabecera de cualquier "
        "ficha mueve un registro de estado. Sin ella, el desplegable del caso "
        "no tenía a quién llamar, y una ruta genérica se habría saltado el "
        "reloj del SLA."
    ),
)
def cambiar_estado_desde_la_ficha(
    caso_id: UUID, datos: CambiarEstado, uow: UowDep, principal: AutenticadoDep
) -> Any:
    return cambiar_estado(caso_id, datos, uow, principal)


@router_casos.post(
    "/{caso_id}/primera-respuesta",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Marcar la primera respuesta",
    description=(
        "Solo la primera cuenta: registrar cada respuesta como «primera» haría "
        "que el indicador midiera la última, que es el número que siempre sale "
        "bien."
    ),
)
def primera_respuesta(caso_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    caso = svc.registrar_primera_respuesta(uow, caso_id, por=principal.id)
    return {
        "id": str(caso.id),
        "primera_respuesta_at": (
            caso.primera_respuesta_at.isoformat() if caso.primera_respuesta_at else None
        ),
        "a_tiempo": not caso.incumplio_primera_respuesta,
    }


class CerrarCaso(BaseModel):
    # De la lista de la empresa (vocabulario `motivos_cierre_caso`): el
    # formulario la ofrece como desplegable y la ruta la valida.
    motivo: str = Field(
        min_length=1,
        max_length=80,
        json_schema_extra={"x-vocabulario": ruta_de_vocabulario(svc.VOCABULARIO_MOTIVOS_CIERRE)},
    )
    resolucion: str = ""
    # Si el cliente tiene que darlo por bueno desde el portal: hasta entonces
    # el caso consta cerrado PENDIENTE de su conformidad.
    exige_validacion: bool = False


@router_casos.post(
    "/{caso_id}/cerrar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Cerrar el caso con un motivo tipificado",
    description=(
        "El motivo es **obligatorio**. Sin él, el informe de cierres dice "
        "cuántos se cerraron y no por qué, que es la única parte útil: "
        "«resuelto», «no era un problema» y «el cliente no contestó» llevan a "
        "tres decisiones distintas."
    ),
)
def cerrar(caso_id: UUID, datos: CerrarCaso, uow: UowDep, principal: AutenticadoDep) -> Any:
    svc.exigir_motivo_de_cierre(uow.db, datos.motivo)
    caso = svc.cerrar_caso(
        uow,
        caso_id,
        motivo=datos.motivo,
        resolucion=datos.resolucion,
        exige_validacion=datos.exige_validacion,
    )
    return {
        "id": str(caso.id),
        "estado": caso.estado,
        "incumplio_resolucion": caso.incumplio_resolucion,
        "validacion_cliente": caso.validacion_cliente,
    }


class ResponderCaso(BaseModel):
    mensaje: str = Field(min_length=1, max_length=20_000, description="Lo que se le contesta")
    para: str = Field(
        "",
        max_length=320,
        description="A quién. Vacío: el correo del contacto del caso",
    )
    asunto: str = Field(
        "",
        max_length=300,
        description="Vacío: «Re: <asunto del caso> [<código>]»",
    )


@router_casos.post(
    "/{caso_id}/responder",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Responder al cliente por correo",
    description=(
        "Sale **de verdad**, por el canal de la casa: el correo transaccional, con "
        "la plantilla de la empresa (`respuesta_caso_plantilla`) o la de serie. "
        "Consta salga o no —el envío con su estado, la actividad en el caso y el "
        "evento en su historial—, y si sale cuenta como primera respuesta.\n\n"
        "`enviado: false` con su `motivo` no es un error de la petición: la "
        "respuesta queda apuntada como no enviada, y se dice por qué."
    ),
)
def responder(caso_id: UUID, datos: ResponderCaso, uow: UowDep, principal: AutenticadoDep) -> Any:
    return svc.responder_caso(
        uow,
        caso_id,
        mensaje=datos.mensaje,
        para=datos.para,
        asunto=datos.asunto,
        principal_id=principal.id,
    )


class ReabrirCaso(BaseModel):
    motivo: str = Field(min_length=1, max_length=1000)


@router_casos.post(
    "/{caso_id}/reabrir",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Reabrir un caso cerrado",
    description=(
        "Dentro de la ventana configurada. Pasada, **no se reabre**: se abre uno "
        "nuevo enlazado. Reabrir un caso de hace ocho meses falsea todos los "
        "indicadores del periodo en que se cerró —tiempo de resolución, "
        "cumplimiento, casos cerrados— y esos números ya están en un informe que "
        "alguien miró."
    ),
)
def reabrir(caso_id: UUID, datos: ReabrirCaso, uow: UowDep, principal: AutenticadoDep) -> Any:
    caso = svc.reabrir_caso(uow, caso_id, motivo=datos.motivo)
    return {"id": str(caso.id), "estado": caso.estado, "reaperturas": caso.reaperturas}


class Enlace(BaseModel):
    maestro_id: UUID


@router_casos.post(
    "/{caso_id}/maestro",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Colgar el caso de una incidencia masiva",
    description=(
        "Cien casos que son la misma caída se cuelgan de uno: se investiga una "
        "vez y se cierran juntos. Cerrarlos uno a uno no solo es trabajo, es que "
        "la respuesta que recibe cada cliente acaba siendo distinta."
    ),
)
def enlazar(caso_id: UUID, datos: Enlace, uow: UowDep, principal: AutenticadoDep) -> Any:
    caso = svc.enlazar_a_maestro(uow, caso_id, datos.maestro_id)
    return {"id": str(caso.id), "maestro_id": str(caso.maestro_id)}


@router_casos.post(
    "/{caso_id}/cerrar-masiva",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Cerrar el maestro y todos los casos colgados",
)
def cerrar_masiva(caso_id: UUID, datos: CerrarCaso, uow: UowDep, principal: AutenticadoDep) -> Any:
    svc.exigir_motivo_de_cierre(uow.db, datos.motivo)
    return svc.cerrar_masiva(uow, caso_id, motivo=datos.motivo, resolucion=datos.resolucion)


class Duplicado(BaseModel):
    original_id: UUID


@router_casos.post(
    "/{caso_id}/duplicado",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Marcar como duplicado de otro",
    description=(
        "No se borra: el cliente que lo abrió tiene derecho a ver su caso y su "
        "respuesta. Borrarlo hace que su referencia deje de existir, y quien "
        "pregunta por ella recibe un «no existe» que suena a que nadie le "
        "atendió."
    ),
)
def duplicado(caso_id: UUID, datos: Duplicado, uow: UowDep, principal: AutenticadoDep) -> Any:
    caso = svc.marcar_duplicado(uow, caso_id, datos.original_id)
    return {"id": str(caso.id), "duplicado_de": str(caso.duplicado_de_id)}


from crmcore.http.listados import montar_ficha  # noqa: E402

from services.service.api_conocimiento import ROUTERS_CONOCIMIENTO  # noqa: E402
from services.service.api_omnicanal import (  # noqa: E402
    ROUTERS_OMNICANAL,
    ROUTERS_SIN_PREFIJO,
)
from services.service.api_operacion import ROUTERS_OPERACION  # noqa: E402

# ── Marcador integrado (CRM-03.03.01.05) ──────────────────────────────────

router_marcador = APIRouter(prefix="/marcador", tags=["marcador"])


def _identidad(principal: Any) -> dict[str, Any]:
    """Con quién se pregunta a party y a la telefonía: con quien pulsa."""
    return {
        "tenant_id": principal.tenant_id,
        "principal_id": principal.id,
        "permisos": sorted(principal.permisos),
        "roles": sorted(principal.roles),
        "tipo": "usuario",
    }


class LlamadaIn(BaseModel):
    # Opcionales desde el 09-11-2026: se llama también desde la ficha de una
    # cuenta, que no tiene contacto.
    contacto_id: UUID | None = None
    cuenta_id: UUID | None = None
    numero: str
    consiente_grabacion: bool = False
    # Ya no decide: la política de grabación es el ajuste
    # `marcador_grabar_por_politica` del tenant. Se admite para no romper a
    # quien la mandaba, y se ignora.
    grabar_por_politica: bool = False
    # Ya no hace falta: la exclusión se pregunta a party. Si alguien la declara
    # igualmente, se respeta —nunca se llama de más—.
    en_lista_de_exclusion: bool = False


class ColgarIn(BaseModel):
    # La llamada que guardó la telefonía. Con ella, la nota va a su actividad y
    # se aplican las obligaciones del resultado.
    llamada_id: UUID | None = None
    contacto_id: UUID | None = None
    duracion_s: int = 0
    resultado: str
    nota: str = ""
    grabacion_ref: str = ""
    proxima_fecha: date | None = None


@router_marcador.post(
    "/llamar",
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Llamar: comprobar lo que hay que comprobar y pedir a la centralita que marque",
    description=(
        "Llamar a alguien que pidió no ser llamado no es un descuido: es una "
        "sanción y una conversación desagradable. Se pregunta a party —el «no "
        "contactar» de la ficha y su último consentimiento por teléfono— antes de "
        "que suene.\n\n"
        "La grabación la decide la política del tenant (ajuste "
        "`marcador_grabar_por_politica`) y el consentimiento de la persona: si no "
        "consiente, **la llamada se hace igual sin grabar**.\n\n"
        "Si todo cuadra, la telefonía conectada (`POST /telefonia/llamar`) origina "
        "la llamada y la guarda; al colgar se registra sola como actividad."
    ),
)
def marcar(cuerpo: LlamadaIn, principal: AutenticadoDep) -> Any:
    from crmcore.errors import ErrorValidacion

    from services.service import marcador

    if cuerpo.contacto_id is None and cuerpo.cuenta_id is None:
        raise ErrorValidacion(
            "Di a quién se llama: un contacto o una cuenta. Una llamada sin ficha no "
            "se puede registrar en ningún sitio.",
            error_code="marcador.sin_destino",
        )
    return marcador.llamar(
        identidad=_identidad(principal),
        numero=cuerpo.numero,
        contacto_id=cuerpo.contacto_id,
        cuenta_id=cuerpo.cuenta_id,
        consiente_grabacion=cuerpo.consiente_grabacion,
        excluido_declarado=cuerpo.en_lista_de_exclusion,
    )


@router_marcador.post(
    "/colgar",
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Anotar la llamada al colgar y hacer lo que el resultado obliga",
    description=(
        "La actividad la crea **sola** la telefonía al colgar, con lo que el "
        "sistema sabe: a quién, cuánto y cómo terminó. Aquí se anota lo que sólo "
        "sabe la persona: cómo fue comercialmente y qué se dijo. «Contestada, 3 "
        "minutos» no es información comercial, y rellenar la nota con una frase "
        "genérica es peor que dejarla vacía.\n\n"
        "Con `llamada_id`, se aplican las obligaciones del resultado: quien pide "
        "que no le llamen queda marcado como «no contactar» en su ficha, y un "
        "«reprogramar» crea la siguiente llamada con su fecha."
    ),
)
def colgar(cuerpo: ColgarIn, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.errors import ErrorValidacion

    from services.service import marcador

    # Los resultados del vocabulario del tenant, no la tupla de fábrica.
    admitidos = marcador.resultados_validos(db)
    if cuerpo.llamada_id is not None:
        return marcador.colgar(
            identidad=_identidad(principal),
            llamada_id=cuerpo.llamada_id,
            resultado=cuerpo.resultado,
            nota=cuerpo.nota,
            proxima_fecha=cuerpo.proxima_fecha,
            admitidos=admitidos,
        )
    if cuerpo.contacto_id is None:
        raise ErrorValidacion(
            "Hace falta la llamada (o, para sólo comprobar el registro, el contacto).",
            error_code="marcador.sin_llamada",
        )
    return marcador.registrar_al_colgar(
        contacto_id=cuerpo.contacto_id,
        duracion_s=cuerpo.duracion_s,
        resultado=cuerpo.resultado,
        nota=cuerpo.nota,
        grabacion_ref=cuerpo.grabacion_ref,
        proxima_fecha=cuerpo.proxima_fecha,
        admitidos=admitidos,
    )


class PoliticaGrabacionIn(BaseModel):
    grabar: bool
    avisar: bool
    dias_conservacion: int = Field(0, ge=0, le=3_650)


@router_marcador.post(
    "/politica-grabacion",
    dependencies=[Depends(exige_permiso("service:read"))],
    summary="Comprobar que la política de grabación se sostiene",
    description=(
        "**Grabar sin avisar no es una opción que se pueda ofrecer**, ni siquiera "
        "como ajuste: no es una preferencia del cliente, es un requisito legal.\n\n"
        "Y una grabación sin plazo de borrado es un archivo de voz que crece para "
        "siempre — con la voz de gente que no sabe que sigue ahí. Se comprueba al "
        "configurar, que es cuando todavía no hay nada grabado."
    ),
)
def politica_grabacion(cuerpo: PoliticaGrabacionIn, principal: AutenticadoDep) -> Any:
    from services.service import marcador

    return marcador.politica_de_grabacion(
        grabar=cuerpo.grabar,
        avisar=cuerpo.avisar,
        dias_conservacion=cuerpo.dias_conservacion,
    )


class RitmoIn(BaseModel):
    agentes_libres: int = Field(0, ge=0)
    llamadas_lanzadas: int = Field(0, ge=0)
    abandonadas: int = Field(0, ge=0)
    contestadas: int = Field(0, ge=0)


@router_marcador.post(
    "/ritmo",
    dependencies=[Depends(exige_permiso("service:read"))],
    summary="Cuántas llamadas se pueden lanzar a la vez sin pasarse",
    description=(
        "El marcado automático marca a más gente de la que hay para atender **a "
        "propósito** —porque muchos no cogen— y ahí está el riesgo: las que sí "
        "cogen y no tienen agente libre suenan y se cuelgan.\n\n"
        "Eso es el **abandono**, está regulado, y además es lo que hace que el "
        "número acabe marcado como spam en el teléfono de todo el mundo — que no "
        "se arregla pagando una multa."
    ),
)
def ritmo(cuerpo: RitmoIn, principal: AutenticadoDep) -> Any:
    from services.service import marcador

    return marcador.ritmo_de_marcado(
        agentes_libres=cuerpo.agentes_libres,
        llamadas_lanzadas=cuerpo.llamadas_lanzadas,
        abandonadas=cuerpo.abandonadas,
        contestadas=cuerpo.contestadas,
    )


# Adjuntos, comentarios y documentos de lo de servicio.
#
# No los tenía, y es donde más falta hacen: un caso de soporte sin poder colgar
# la foto de la pieza rota o el registro del equipo obliga a mandarlo por correo
# aparte, y entonces la mitad de lo que explica el caso no está en el caso. Los
# comentarios internos son lo mismo: se acababan escribiendo en la descripción,
# donde los lee el cliente si se le enseña.
from crmcore.http.adjuntos_router import crear_router_adjuntos  # noqa: E402
from crmcore.http.busqueda_router import crear_router_busqueda  # noqa: E402
from crmcore.http.comentarios_router import crear_router_comentarios  # noqa: E402
from crmcore.http.documental_router import crear_router_documental  # noqa: E402

from services.service.indexacion import OBJETOS as _OBJETOS_BUSCABLES  # noqa: E402

# Lo que el buscador de arriba pregunta a este servicio: los casos.
router_busqueda = crear_router_busqueda(_OBJETOS_BUSCABLES, "/service/buscar")

router_adjuntos = crear_router_adjuntos({"caso", "orden_trabajo"})
router_comentarios = crear_router_comentarios({"caso", "orden_trabajo"})
router_documental = crear_router_documental({"caso"})

ROUTERS = [
    router_casos,
    router_taxonomia,
    router_sla,
    router_marcador,
    router_adjuntos,
    router_comentarios,
    router_documental,
    router_busqueda,
    *ROUTERS_OPERACION,
    *ROUTERS_OMNICANAL,
    *ROUTERS_CONOCIMIENTO,
]

__all__ = ["ROUTERS", "ROUTERS_SIN_PREFIJO"]


# ── Lo que a la ficha le faltaba: corregir y borrar ───────────────────────
# Estos tres ya se podían abrir —tienen su lectura escrita a mano, con sus
# reglas de visibilidad— y no se podían ni corregir ni borrar desde ninguna
# pantalla. Un contacto con el correo mal escrito se quedaba así para siempre.
montar_ficha(
    router_casos,
    modelo=Caso,
    objeto="caso",
    permiso_leer="case:read",
    permiso_escribir="case:write",
    nombre="Casos",
    parametro="caso_id",
    con_lectura=False,
)


# Esta ruta acepta además los filtros comunes, cuyos nombres son columnas del
# modelo y cambian con él: no se pueden declarar. Los valida
# `aplicar_filtros_de_la_url`, que rechaza lo que no es columna o lo que este
# principal no ve en claro.
admite_parametros_abiertos(
    listar, "llama a `aplicar_filtros_de_la_url`, que valida los filtros por columna"
)

# ── Corregir lo dado de alta ──────────────────────────────────────────────
# Se podía crear y no había forma de cambiarlo: una errata, un plazo mal
# puesto o retirarlo obligaban a crear otro al lado. Medido el 05-11-2026: de
# las pestañas que admiten alta, treinta no admitían ningún cambio, y de ellas
# éstas eran un hueco y no una decisión. Se monta al final del módulo para que
# `/{id}` quede detrás de las rutas con nombre propio de la misma colección.
montar_ficha(
    router_taxonomia,
    modelo=CategoriaCaso,
    objeto="categoria_caso",
    permiso_leer="case:read",
    permiso_escribir="case:write",
    nombre="Categorías de caso",
)
