"""API de lo que sale de verdad: audiencias sincronizadas, envíos programados por
destinatario, la vista previa del correo y por dónde sale cada clase
(CRM-02.01.01.09, CRM-02.02.02.05, CRM-02.03.01.02, CRM-02.03.01.06,
CRM-02.03.01.07), más la ficha y el lienzo del recorrido (CRM-02.02.02.01,
CRM-02.02.02.04).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import NoDisponible
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.marketing import audiencias_sync as aud
from services.marketing import envios as env
from services.marketing import recorridos as rec
from services.marketing import vista_correo as vis

router_audiencias = APIRouter(prefix="/audiencias-publicitarias", tags=["publicidad y audiencias"])
router_envios = APIRouter(prefix="/envios-programados", tags=["envíos"])
router_campana_envio = APIRouter(prefix="/campanas", tags=["campañas"])
router_correo_vista = APIRouter(prefix="/correo", tags=["correo"])
router_recorrido_lienzo = APIRouter(prefix="/recorridos", tags=["recorridos"])
router_momento_real = APIRouter(prefix="/momento", tags=["hora y canal"])


# ── Audiencias (CRM-02.01.01.09) ──────────────────────────────────────────


class CrearAudiencia(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    segmento_id: UUID
    conexion_id: UUID = Field(
        ...,
        description=(
            "La conexión de integraciones que habla con la plataforma. Declara las "
            "operaciones de crear, añadir y quitar: el proveedor es configuración"
        ),
    )
    finalidad: str = ""


@router_audiencias.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("marketing:write"))],
    summary="Dar de alta una audiencia sincronizada con una plataforma",
)
def crear_audiencia(datos: CrearAudiencia, uow: UowDep) -> Any:
    fila = aud.crear(uow, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado}


@router_audiencias.get(
    "/{audiencia_id}",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="La audiencia, su estado y el historial de sincronizaciones",
)
def ver_audiencia(audiencia_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return aud.ficha(db, principal.tenant_id, audiencia_id)


@router_audiencias.post(
    "/{audiencia_id}/sincronizar",
    dependencies=[Depends(exige_permiso("marketing:write"))],
    summary="Dejar la audiencia de fuera igual que el segmento",
    description=(
        "**Primero las bajas**: quien se dio de baja o perdió el consentimiento deja "
        "de ver anuncios antes de que se añada a nadie. Después se crea la "
        "audiencia si hace falta y se mandan las altas, troceadas. Por debajo del "
        "mínimo no se sube nadie. Cada vuelta queda en el historial."
    ),
)
def sincronizar(audiencia_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    return aud.sincronizar(uow, audiencia_id, principal_id=principal.id)


@router_audiencias.delete(
    "/{audiencia_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("marketing:write"))],
    summary="Retirar la audiencia",
)
def borrar_audiencia(audiencia_id: UUID, uow: UowDep) -> None:
    from datetime import datetime, timezone

    fila = aud._audiencia(uow.db, uow.tenant_id, audiencia_id)
    fila.deleted_at = datetime.now(timezone.utc)
    fila.estado = "pausada"


montar_listado(
    router_audiencias,
    modelo=aud.AudienciaPublicitaria,
    objeto="audiencia_publicitaria",
    permiso="marketing:read",
    nombre="Audiencias publicitarias",
)


# ── Envíos programados (CRM-02.02.02.05, CRM-02.03.01.07) ─────────────────


class ProgramarCampana(BaseModel):
    plantilla: str = Field(..., min_length=1)
    idioma: str = "es"
    inmediato: bool = Field(
        False, description="Sin esperar a la mejor hora: sale en el próximo despacho"
    )


@router_campana_envio.post(
    "/{campana_id}/programar-envio",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Programar el envío de la campaña, cada miembro a su hora y por su canal",
    description=(
        "Cada miembro se programa a **su** mejor hora y por **su** canal, sacados de "
        "su historial real; sin historial suficiente, a la hora y por el canal por "
        "defecto, que son ajustes. Devuelve cuántos van a la hora general: si son "
        "casi todos, la personalización no está haciendo nada."
    ),
)
def programar_campana(
    campana_id: UUID, datos: ProgramarCampana, uow: UowDep, principal: AutenticadoDep
) -> Any:
    # Quien lo programa queda en cada envío: es con quien sale solo a su hora.
    return env.programar_campana(uow, campana_id, **datos.model_dump(), por=env.foto(principal))


@router_envios.get(
    "",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Los envíos de una campaña o de un recorrido, con su hora, su canal y por qué",
)
def envios(
    db: DbDep,
    principal: AutenticadoDep,
    origen: str = Query(..., description="campana · recorrido"),
    origen_id: UUID = Query(...),
    limite: int = Query(200, ge=1, le=1000),
) -> Any:
    return env.listado(db, principal.tenant_id, origen=origen, origen_id=origen_id, limite=limite)


class Despachar(BaseModel):
    origen: str = ""
    origen_id: UUID | None = None
    forzar: bool = Field(
        False, description="Mandar ya lo programado de ese origen aunque no sea su hora"
    )


@router_envios.post(
    "/despachar",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Mandar lo que ya toca, cada clase por su dominio y su servidor",
)
def despachar(datos: Despachar, uow: UowDep, principal: AutenticadoDep) -> Any:
    return env.despachar(
        uow,
        principal_id=principal.id,
        origen=datos.origen,
        origen_id=datos.origen_id,
        forzar=datos.forzar,
    )


class Suceso(BaseModel):
    que: str = Field(..., description="abierto · clic · respondido")


@router_envios.post(
    "/{envio_id}/suceso",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Anotar que abrió, hizo clic o respondió",
    description=(
        "Alimenta el historial con el que se elige su próxima hora y su canal, y "
        "resuelve las ramas de los recorridos donde esté."
    ),
)
def suceso(envio_id: UUID, datos: Suceso, uow: UowDep) -> Any:
    return env.anotar_suceso(uow, envio_id, que=datos.que)


@router_momento_real.get(
    "/destinatario/{objeto_id}",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="La hora y el canal que se elegirían hoy para esta persona, y por qué",
)
def momento_de(objeto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from sqlalchemy import select

    from services.marketing.modelos import PerfilMarketing

    perfil = db.execute(
        select(PerfilMarketing).where(
            PerfilMarketing.tenant_id == principal.tenant_id,
            PerfilMarketing.objeto_id == objeto_id,
        )
    ).scalar_one_or_none()
    return env.elegir(db, principal.tenant_id, objeto_id, perfil=perfil)


# ── Vista previa, spam y salida (CRM-02.03.01.02, .06, .07) ───────────────


@router_correo_vista.get(
    "/plantillas/{clave}/vista-previa",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="El correo montado con los datos de un contacto real, en varios clientes",
    description=(
        "Los datos salen de `party` (contacto y cuenta) y las recomendaciones del "
        "historial de la cuenta en `sales`. Se monta en cada cliente configurado "
        "—ancho, imágenes bloqueadas, modo oscuro— y se puntúa el spam con reglas "
        "que dicen qué han visto y cuánto suman."
    ),
)
def vista_previa(
    clave: str,
    db: DbDep,
    principal: AutenticadoDep,
    contacto_id: UUID | None = Query(None),
    idioma: str = Query("es"),
) -> Any:
    return vis.vista_previa(
        db,
        principal.tenant_id,
        plantilla=clave,
        idioma=idioma,
        contacto_id=contacto_id,
        principal_id=principal.id,
    )


@router_correo_vista.get(
    "/salida",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Por qué dominio, remitente y servidor sale cada clase de correo",
)
def salida(db: DbDep, principal: AutenticadoDep) -> Any:
    return vis.separacion(db, principal.tenant_id)


# ── El recorrido entero y su lienzo (CRM-02.02.02.01) ─────────────────────


@router_recorrido_lienzo.get(
    "/{recorrido_id}/lienzo",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="El recorrido con su lienzo, quién hay dentro y qué tipos de nodo admite",
    # En `/lienzo` y no en `/{id}`: la ficha genérica del registro ya contesta
    # ahí, y la de la casa gana el orden de rutas.
)
def ver_recorrido(recorrido_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return rec.ficha(db, principal.tenant_id, recorrido_id)


class Lienzo(BaseModel):
    nodos: dict[str, Any]
    inicio: str = Field(..., min_length=1)
    salidas: list[dict[str, Any]] | None = None
    por_cuenta: bool | None = None
    nombre: str | None = None


@router_recorrido_lienzo.put(
    "/{recorrido_id}/lienzo",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Guardar lo dibujado en el lienzo",
    description=(
        "Se valida igual que al crear. Si estaba publicado vuelve a borrador: "
        "publicar es un paso aparte, con su versión."
    ),
)
def guardar_lienzo(recorrido_id: UUID, datos: Lienzo, uow: UowDep) -> Any:
    return rec.actualizar_lienzo(uow, recorrido_id, **datos.model_dump())


@router_recorrido_lienzo.get(
    "/{recorrido_id}/inscritos",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Quién está o estuvo en el recorrido",
)
def inscritos(recorrido_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return rec.inscritos(db, principal.tenant_id, recorrido_id)


def convertidos_de_ventas(tenant_id: UUID, principal_id: Any) -> set[UUID] | None:
    """Los leads convertidos, de `sales`. `None` si no contesta: no es «ninguno»."""
    from crmcore.http.interno import invocar

    salida: set[UUID] = set()
    cursor = ""
    for _ in range(50):
        try:
            r = invocar(
                metodo="GET",
                ruta="/api/v1/leads",
                parametros={"estado": "convertido", "limite": 200, "cursor": cursor},
                tenant_id=tenant_id,
                principal_id=principal_id,
                permisos=["lead:read", "lead:admin"],
                timeout_s=15.0,
            )
        except NoDisponible:
            return None
        if not r.get("ok"):
            return None
        datos = r.get("datos") or {}
        for fila in vis._filas(datos):
            try:
                salida.add(UUID(str(fila.get("id"))))
            except ValueError:
                continue
        cursor = str((datos or {}).get("siguiente") or (datos or {}).get("cursor") or "")
        if not cursor:
            break
    return salida


ROUTERS_ENVIOS = [
    router_audiencias,
    router_envios,
    router_campana_envio,
    router_correo_vista,
    router_recorrido_lienzo,
    router_momento_real,
]
