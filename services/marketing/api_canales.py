"""API de canales, consentimiento, landings y entregabilidad
(CRM-02.03.02, CRM-02.03.01.02, CRM-02.03.01.03, CRM-02.03.01.06)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from services.marketing import canales as can

router = APIRouter(prefix="/canales-marketing", tags=["canales"])
router_landings = APIRouter(prefix="/landings", tags=["canales"])
router_dominios = APIRouter(prefix="/dominios-envio", tags=["canales"])


class CrearCanal(BaseModel):
    clave: str = Field(..., min_length=1, max_length=60)
    nombre: str = Field(..., min_length=1, max_length=200)
    tipo: str = Field(..., description="email · sms · whatsapp · push · rcs")
    conexion_id: UUID | None = Field(
        None, description="La conexión declarativa. No hay código por proveedor"
    )
    remitente: str | None = None
    silencio_desde: int = Field(
        21, ge=0, le=23, description="Un SMS a las once de la noche despierta a alguien"
    )
    silencio_hasta: int = Field(9, ge=0, le=23)
    coste_mensaje: str | None = None


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Configurar un canal",
    description=(
        "Sobre el transporte declarativo que ya existe. Twilio, MessageBird o el "
        "agregador del cliente son la misma cosa con otra dirección y otra "
        "credencial: **un módulo por casa convierte cada implantación en una "
        "versión del producto**."
    ),
)
def crear_canal(datos: CrearCanal, db: DbDep, principal: AutenticadoDep) -> Any:
    if datos.tipo not in can.CANALES:
        from crmcore.errors import ErrorValidacion

        raise ErrorValidacion(
            f"Canal «{datos.tipo}» no válido.",
            error_code="canal.no_valido",
            detalle={"validos": list(can.CANALES)},
        )
    fila = can.Canal(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {
        "id": str(fila.id),
        "clave": fila.clave,
        "como_se_da_de_baja": can.BAJAS_POR_CANAL.get(fila.tipo, ""),
    }


@router.get(
    "",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Canales configurados",
)
def listar_canales(db: DbDep, principal: AutenticadoDep) -> Any:
    from sqlalchemy import select as _select

    filas = (
        db.execute(
            _select(can.Canal)
            .where(can.Canal.tenant_id == principal.tenant_id)
            .order_by(can.Canal.clave)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "clave": f.clave,
            "nombre": f.nombre,
            "tipo": f.tipo,
            "activo": f.activo,
            "como_se_da_de_baja": can.BAJAS_POR_CANAL.get(f.tipo, ""),
        }
        for f in filas
    ]


class FijarConsentimiento(BaseModel):
    canal: str
    destino: str = Field(..., min_length=3)
    acepta: bool
    origen: str = "formulario"
    prueba: str = Field(
        "", description="De dónde salió. Sin ella, «¿quién autorizó esto?» no tiene respuesta"
    )


@router.post(
    "/consentimiento",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Anotar que alguien acepta un canal",
    description=(
        "El consentimiento es **por canal**: quien aceptó el correo no ha aceptado "
        "el SMS, y mandarle uno «porque ya nos dio permiso» es exactamente lo que "
        "sanciona un regulador."
    ),
)
def consentimiento(datos: FijarConsentimiento, request: Request, uow: UowDep) -> Any:
    fila = can.fijar_consentimiento(
        uow, ip=request.client.host if request.client else "", **datos.model_dump()
    )
    return {"id": str(fila.id), "acepta": fila.acepta}


class Entrante(BaseModel):
    canal: str
    destino: str = Field(..., min_length=3)
    texto: str = ""


@router.post(
    "/entrante",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Procesar un mensaje que llega del destinatario",
    description=(
        "Dos cosas a la vez: si es una **baja** se aplica —y basta la primera "
        "palabra, sin acentos ni mayúsculas, porque exigir una exacta deja sin "
        "efecto una baja que la persona sí pidió—, y en cualquier caso **abre la "
        "ventana de 24 horas** de WhatsApp: el que escribe autoriza a contestarle."
    ),
)
def entrante(datos: Entrante, uow: UowDep) -> Any:
    return can.procesar_entrante(uow, **datos.model_dump())


@router.get(
    "/comprobar",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="¿Se puede mandar esto, ahora, a esta persona?",
    description=(
        "Cinco comprobaciones en una llamada: canal activo, consentimiento **de "
        "ese canal**, hora de silencio, ventana de WhatsApp y plantilla aprobada. "
        "Repartidas por el código, la que se olvida es siempre la del "
        "consentimiento.\n\n"
        "Una plantilla no aprobada **no da error**: el proveedor la descarta y el "
        "mensaje no llega nunca, que es peor porque nadie se entera."
    ),
)
def comprobar(
    db: DbDep,
    principal: AutenticadoDep,
    canal: str = Query(...),
    destino: str = Query(...),
    plantilla: str = Query(""),
) -> Any:
    return can.comprobar_envio(
        db, principal.tenant_id, canal_clave=canal, destino=destino, plantilla=plantilla
    )


@router.get(
    "/mejor-hora",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="A qué hora abre esta persona",
    description=(
        "**Con pocos datos no se recomienda nada.** Con tres aperturas, la hora "
        "que salga es la de esos tres correos y no un hábito; mandar a esa hora "
        "«porque el sistema lo dice» es superstición con una cifra al lado.\n\n"
        "Sin datos devuelve `null` y quien llama usa su hora por defecto: no saber "
        "es un resultado válido."
    ),
)
def mejor_hora(
    db: DbDep,
    principal: AutenticadoDep,
    objeto_id: UUID = Query(...),
    minimo: int = Query(10, ge=3, le=1000),
) -> Any:
    return can.mejor_hora(db, principal.tenant_id, objeto_id, minimo=minimo)


class Personalizar(BaseModel):
    texto: str
    datos: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/personalizar",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Sustituir tokens y resolver condicionales",
    description=(
        "Los tokens admiten valor por defecto (`{{nombre|cliente}}`), que es la "
        "diferencia entre «Hola cliente» y «Hola », que es lo que se manda cuando "
        "el dato falta y nadie lo previó.\n\n"
        "Los condicionales son solo «si existe». Darle a una plantilla un lenguaje "
        "con condiciones convierte cada campaña en código sin revisar."
    ),
)
def personalizar(datos: Personalizar) -> Any:
    return can.personalizar(datos.texto, datos.datos)


class Revisar(BaseModel):
    asunto: str = ""
    cuerpo: str = ""
    dominio: str = ""


@router.post(
    "/revisar",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Qué conviene mirar antes de enviar",
    description=(
        "Es una **ayuda, no un veredicto**: nunca bloquea. Un sistema que bloquea "
        "por una palabra acaba con la gente escribiendo «gr4tis», que es peor para "
        "el filtro y para quien lee."
    ),
)
def revisar(datos: Revisar, db: DbDep, principal: AutenticadoDep) -> Any:
    listo = True
    if datos.dominio:
        try:
            listo = bool(can.estado_dominio(db, principal.tenant_id, datos.dominio)["listo"])
        except Exception:  # noqa: BLE001 — un dominio sin configurar no rompe la revisión
            listo = False
    return can.revisar_antes_de_mandar(datos.asunto, datos.cuerpo, dominio_listo=listo)


class CrearDominio(BaseModel):
    dominio: str = Field(..., min_length=3, max_length=253)
    uso: str = Field("promocional", description="promocional · transaccional")
    spf: bool = False
    dkim: bool = False
    dmarc: str | None = Field(None, description="none · quarantine · reject")
    bimi: bool = False
    ip_dedicada: str | None = None


@router_dominios.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Declarar un dominio de envío",
)
def crear_dominio(datos: CrearDominio, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = can.DominioEnvio(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id), "dominio": fila.dominio}


@router_dominios.get(
    "",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Dominios de envío configurados",
)
def listar_dominios(db: DbDep, principal: AutenticadoDep) -> Any:
    from sqlalchemy import select as _select

    filas = (
        db.execute(
            _select(can.DominioEnvio)
            .where(can.DominioEnvio.tenant_id == principal.tenant_id)
            .order_by(can.DominioEnvio.dominio)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "dominio": f.dominio,
            "uso": f.uso,
            "spf": f.spf,
            "dkim": f.dkim,
            "dmarc": f.dmarc,
        }
        for f in filas
    ]


@router_landings.get(
    "",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Landings del tenant",
)
def listar_landings(db: DbDep, principal: AutenticadoDep) -> Any:
    from sqlalchemy import select as _select

    filas = (
        db.execute(
            _select(can.Landing)
            .where(can.Landing.tenant_id == principal.tenant_id)
            .order_by(can.Landing.clave)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "clave": f.clave,
            "titulo": f.titulo,
            "visitas": f.visitas,
            "envios": f.envios,
            "activa": f.activa,
        }
        for f in filas
    ]


@router_dominios.get(
    "/{dominio}",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Si el dominio está listo para mandar, y qué le falta",
    description=(
        "**Un dominio sin SPF, sin DKIM o sin DMARC no rebota: llega a basura.** Y "
        "eso no aparece en ningún informe de rebotes — aparece como una campaña "
        "que nadie abrió, que es el diagnóstico equivocado.\n\n"
        "Si está en calentamiento dice el tope de hoy: una IP nueva que manda cien "
        "mil el primer día se quema, y quemarla cuesta semanas."
    ),
)
def dominio(dominio: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return can.estado_dominio(db, principal.tenant_id, dominio)


class CrearLanding(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    titulo: str = Field(..., min_length=1, max_length=300)
    campos: list[dict[str, Any]] = Field(default_factory=list)
    pide_consentimiento: list[str] = Field(
        default_factory=list,
        description=(
            "Qué canales pide. Sin declararlo, recoger un teléfono NO autoriza a "
            "mandar SMS: recoger no es consentir"
        ),
    )
    canal_captura: str | None = None


@router_landings.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Crear una landing con su formulario",
)
def crear_landing(datos: CrearLanding, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = can.Landing(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id), "clave": fila.clave}


class EnvioLanding(BaseModel):
    datos: dict[str, Any]
    consentimientos: dict[str, bool] = Field(default_factory=dict)


@router_landings.post(
    "/{clave}/enviar",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Recoger un envío de formulario",
    description=(
        "**Recoger un teléfono no autoriza a mandar SMS.** El consentimiento se "
        "pide aparte y por canal, y si la landing no lo declaraba se ignora y se "
        "dice: dar por consentido lo que solo se ha escrito en una casilla es "
        "justo la práctica que sanciona un regulador."
    ),
)
def enviar_landing(clave: str, datos: EnvioLanding, request: Request, uow: UowDep) -> Any:
    return can.registrar_envio_landing(
        uow,
        clave,
        datos=datos.datos,
        consentimientos=datos.consentimientos,
        ip=request.client.host if request.client else "",
    )


@router_landings.get(
    "/{clave}/prerelleno",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Qué se le puede pre-rellenar a quien ya conocemos",
    description=(
        "Solo los campos que **la landing pide**, no la ficha entera: "
        "pre-rellenar con datos que no estaba pidiendo le enseña a quien lo abre "
        "—o a quien recibió el enlace reenviado— lo que sabemos de otra persona."
    ),
)
def prerelleno(clave: str, db: DbDep, principal: AutenticadoDep, destino: str = Query(...)) -> Any:
    return can.prerelleno(db, principal.tenant_id, clave, destino)


ROUTERS_CANALES = [router, router_landings, router_dominios]
