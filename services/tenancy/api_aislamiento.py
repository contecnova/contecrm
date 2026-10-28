"""API de aislamiento, residencia y migración de tenants
(CRM-00.01.01.02 a .06, CRM-00.01.03.09, .10, CRM-00.01.05.01 a .03).

Casi todo lo de aquí sirve para contestar dos preguntas que se hacen con un
cliente delante: **¿dónde están mis datos?** y **¿quién los toca?**. Por eso
ninguna respuesta se queda en el sí: dicen qué no se ha podido comprobar, que es
la parte que decide si la respuesta vale.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.tenancy import aislamiento as ais
from services.tenancy import residencia as res
from services.tenancy.aislamiento import AislamientoTenant, MigracionAislamiento
from services.tenancy.residencia import ResidenciaDato, Subprocesador, TransferenciaInternacional

router_aislamiento = APIRouter(prefix="/aislamiento", tags=["aislamiento y residencia"])
router_residencia = APIRouter(prefix="/residencia", tags=["aislamiento y residencia"])


class DeclararAislamiento(BaseModel):
    tenant_id: UUID
    modalidad: str = Field(
        "",
        description=(
            "compartido · esquema · base · cluster · cliente. Vacío: la que "
            "corresponde al tier contratado, que es lo que el cliente ha pagado"
        ),
    )
    tier: str = Field(
        "",
        description=(
            "El plan contratado. Con él, la modalidad sale de lo contratado y no "
            "de lo que alguien teclee: aprovisionar con la plantilla de siempre a "
            "un cliente que paga por base dedicada es el fallo que este módulo "
            "existe para cazar"
        ),
    )
    instancia: str = ""
    base: str = ""
    esquema: str = ""
    pool_computo: str = "comun"
    infraestructura_del_cliente: bool = False
    notas: str = ""


class PlanificarMigracion(BaseModel):
    tenant_id: UUID
    hacia: str
    ventana_minutos: int = Field(10, ge=1, le=1440)


class Verificar(BaseModel):
    recuento_origen: dict[str, int] = Field(default_factory=dict)
    recuento_destino: dict[str, int] = Field(default_factory=dict)


class Cerrar(BaseModel):
    nueva_base: str = ""
    nuevo_esquema: str = ""


class Revertir(BaseModel):
    motivo: str = Field(..., min_length=3)


@router_aislamiento.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Declarar el aislamiento de un tenant",
    description=(
        "Las cuatro modalidades son legítimas y cada una tiene su coste. Lo que no "
        "es legítimo es **cobrar una y dar otra**, y por eso declarar no basta: "
        "hay que comprobarlo."
    ),
)
def declarar(cuerpo: DeclararAislamiento, uow: UowDep) -> Any:
    datos = cuerpo.model_dump()
    tier = str(datos.pop("tier", "") or "")
    if not datos.get("modalidad"):
        if not tier:
            raise ErrorValidacion(
                "Hay que decir la modalidad, o el tier del que sacarla. Sin "
                "ninguna de las dos se aprovisionaría con la de siempre, que es "
                "justo cómo un cliente que paga por base dedicada acaba en la "
                "compartida.",
                error_code="aislamiento.sin_modalidad",
            )
        # De lo CONTRATADO, no de lo que alguien teclee. `modalidad_de_tier` no
        # se inventa nada para un tier desconocido: cae a la compartida, que es
        # la más conservadora.
        datos["modalidad"] = ais.modalidad_de_tier(tier)
    fila = ais.declarar(uow, **datos)
    return {
        "tenant_id": str(fila.tenant_id),
        "modalidad": fila.modalidad,
        "pool_computo": fila.pool_computo,
        "siguiente_paso": "Comprobarlo: una declaración que nadie contrasta es una promesa.",
    }


@router_aislamiento.post(
    "/{tenant_id}/comprobar",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Comprobar que el tenant está donde se declaró (CRM-00.01.01.02, .03)",
    description=(
        "Lo que pasa siempre: se vende una base dedicada, alguien aprovisiona con "
        "la plantilla de siempre y el tenant acaba en el pool. Funcionar funciona "
        "igual, y se descubre el día de la auditoría.\n\n"
        "Comprueba además que **el aislamiento de abajo sigue puesto**: quitar RLS "
        "«porque ya está aislado» deja la protección dependiendo de que el "
        "aprovisionamiento no falle nunca."
    ),
)
def comprobar(tenant_id: UUID, uow: UowDep) -> Any:
    return ais.comprobar(uow, tenant_id=tenant_id)


@router_aislamiento.get(
    "/garantias",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Qué impide ahora mismo que una empresa vea a otra",
    description=(
        "**Se mide, no se declara.** El manual promete tres capas y cada una tapa "
        "el hueco de la anterior; esto dice si están puestas *en esta "
        "instalación*, que no es lo mismo.\n\n"
        "La línea que más importa es la del **rol de conexión**: un SUPERUSER o un "
        "rol con `BYPASSRLS` ignora las políticas aunque estén en FORCE, así que "
        "contar tablas protegidas puede dar verde sobre una red desarmada. Pasó, y "
        "medido: 623 tablas con RLS, FORCE y política, y el servicio conectando "
        "como `postgres`. De las tres capas quedaba una.\n\n"
        "Lo que no se puede medir desde aquí —la suite que intenta entrar en lo "
        "ajeno, que corre en el gate de pre-push— se dice que es un gate y dónde "
        "corre, en vez de pintar un visto bueno que nadie ha comprobado hoy."
    ),
)
def garantias(db: DbDep) -> Any:
    return ais.garantias(db)


@router_aislamiento.get(
    "/sin-comprobar",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Tenants cuyo aislamiento nadie ha contrastado",
    description=(
        "Una comprobación de hace ocho meses no dice nada de hoy: entre medias ha "
        "habido despliegues, restauraciones y un cambio de plantilla."
    ),
)
def sin_comprobar(db: DbDep, _: AutenticadoDep, dias: int = Query(30, ge=1, le=365)) -> Any:
    return ais.sin_comprobar(db, dias=dias)


@router_aislamiento.post(
    "/migraciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Planificar un cambio de modalidad (CRM-00.01.01.04, CRM-00.01.03.10)",
    description=(
        "Se planifica antes de tocar nada porque lo que hay que poder enseñar al "
        "cliente es **la ventana**: cuánto tiempo va a poder leer y no escribir. "
        "Prometer «sin corte» es prometer lo que no se puede.\n\n"
        "Bajar de aislamiento mueve los datos a un sitio donde conviven con los de "
        "otros clientes, y la respuesta lo dice: no es un cambio de configuración, "
        "es un cambio de lo que se prometió."
    ),
)
def planificar(cuerpo: PlanificarMigracion, uow: UowDep) -> Any:
    return ais.planificar_migracion(
        uow,
        tenant_id=cuerpo.tenant_id,
        hacia=cuerpo.hacia,
        ventana_minutos=cuerpo.ventana_minutos,
    )


@router_aislamiento.post(
    "/migraciones/{migracion_id}/ventana",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Abrir la ventana de solo lectura",
)
def abrir_ventana(migracion_id: UUID, uow: UowDep) -> Any:
    return ais.abrir_ventana(uow, migracion_id=migracion_id)


@router_aislamiento.post(
    "/migraciones/{migracion_id}/verificar",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Comparar lo que había con lo que hay, tabla a tabla",
    description=(
        "Sin esto, «migrado» significa «el script terminó sin error», que no es lo "
        "mismo: una tabla que falló al copiarse y se saltó en silencio deja un "
        "tenant con la mitad de sus datos y la migración marcada como buena."
    ),
)
def verificar(migracion_id: UUID, cuerpo: Verificar, uow: UowDep) -> Any:
    return ais.verificar(
        uow,
        migracion_id=migracion_id,
        recuento_origen=cuerpo.recuento_origen,
        recuento_destino=cuerpo.recuento_destino,
    )


@router_aislamiento.post(
    "/migraciones/{migracion_id}/cerrar",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Cerrar la migración, solo si la verificación cuadró",
    description=(
        "Devuelve los minutos de solo lectura **reales** junto a los prometidos: "
        "guardar solo lo prometido haría que la siguiente estimación se hiciera "
        "sobre un número inventado."
    ),
)
def cerrar(migracion_id: UUID, cuerpo: Cerrar, uow: UowDep) -> Any:
    return ais.cerrar(
        uow,
        migracion_id=migracion_id,
        nueva_base=cuerpo.nueva_base,
        nuevo_esquema=cuerpo.nuevo_esquema,
    )


@router_aislamiento.post(
    "/migraciones/{migracion_id}/revertir",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Deshacer una migración que no cuadró",
)
def revertir(migracion_id: UUID, cuerpo: Revertir, uow: UowDep) -> Any:
    fila = ais.revertir(uow, migracion_id=migracion_id, motivo=cuerpo.motivo)
    return {"migracion_id": str(fila.id), "estado": fila.estado, "motivo": fila.motivo_fin}


# ── Residencia y subprocesadores ──────────────────────────────────────────


class FijarResidencia(BaseModel):
    tenant_id: UUID
    tipo_dato: str = Field(
        ..., description="transaccional · analitico · copias · registros · ia · adjuntos"
    )
    region: str
    proveedor: str = ""
    notas: str = ""


class DeclararSubprocesador(BaseModel):
    tenant_id: UUID
    clave: str
    nombre: str
    trata: list[str] = Field(default_factory=list)
    finalidad: str
    region: str = "ue"
    garantia: str = "sin_garantia"
    referencia_garantia: str = ""


class AnotarTransferencia(BaseModel):
    tenant_id: UUID
    tipo_dato: str = "transaccional"
    hacia_region: str
    desde_region: str = "ue"
    subprocesador: str = ""
    motivo: str = ""


@router_aislamiento.get(
    "/{tenant_id}",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Qué se declaró para este tenant, y si alguien lo ha contrastado",
    description=(
        "Existía la acción de comprobar y no existía forma de **abrir** el "
        "registro: la acción no tenía pantalla desde la que llamarse y el "
        "listado enlazaba a una ficha que respondía 404. Residencia ya lo "
        "publicaba; aislamiento no.\n\n"
        "Un tenant sin declarar sale como hueco, no como «compartido por "
        "defecto»: el defecto silencioso es justo cómo un cliente que paga por "
        "base dedicada acaba en la compartida."
    ),
)
def ficha_de_aislamiento(tenant_id: UUID, db: DbDep, _: AutenticadoDep) -> Any:
    return ais.ficha(db, tenant_id=tenant_id)


@router_residencia.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Declarar dónde vive un tipo de dato (CRM-00.01.05.01, .02)",
)
def fijar_residencia(cuerpo: FijarResidencia, uow: UowDep) -> Any:
    fila = res.fijar_residencia(uow, **cuerpo.model_dump())
    return {"tipo_dato": fila.tipo_dato, "region": fila.region, "proveedor": fila.proveedor}


@router_residencia.get(
    "/{tenant_id}",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Dónde está cada tipo de dato, y qué no está declarado",
    description=(
        "Lo no declarado sale como **hueco**, no como «europeo por defecto». El "
        "defecto silencioso es exactamente cómo se incumple una promesa de "
        "residencia sin enterarse: lo transaccional se queda donde se dijo y los "
        "registros se van a otro continente porque nadie preguntó."
    ),
)
def mapa(tenant_id: UUID, db: DbDep, _: AutenticadoDep, region_contratada: str = Query("")) -> Any:
    return res.mapa(db, tenant_id, region_contratada=region_contratada)


@router_residencia.post(
    "/subprocesadores",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Declarar un subprocesador (CRM-00.01.05.03)",
    description=(
        "Exige **qué trata y para qué**: una lista de nombres no sirve para "
        "contestar a un cliente que pregunta por el artículo 28, que es "
        "exactamente para lo que se pide esta lista."
    ),
)
def declarar_subprocesador(cuerpo: DeclararSubprocesador, uow: UowDep) -> Any:
    fila = res.declarar_subprocesador(uow, **cuerpo.model_dump())
    return {
        "clave": fila.clave,
        "region": fila.region,
        "garantia": fila.garantia,
        "comunicado": fila.comunicado_at is not None,
    }


@router_residencia.post(
    "/subprocesadores/{tenant_id}/{clave}/comunicado",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Marcar que se le ha comunicado al cliente",
    description=(
        "Un subprocesador nuevo del que el cliente no se ha enterado es un "
        "incumplimiento del contrato, no un detalle administrativo."
    ),
)
def comunicar(tenant_id: UUID, clave: str, uow: UowDep) -> Any:
    fila = res.comunicar_subprocesador(uow, tenant_id=tenant_id, clave=clave)
    return {"clave": fila.clave, "comunicado_at": fila.comunicado_at.isoformat()}


@router_residencia.post(
    "/transferencias",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Anotar una salida de datos fuera de su región",
    description=(
        "**No bloquea.** Bloquear desde aquí sería fingir un control que no "
        "existe: el dato sale por el conector, por el correo o por el modelo de "
        "IA, y esta tabla no está en medio de ninguno de los tres. Lo que sí se "
        "puede es que conste y que se vea cuál no tiene garantía."
    ),
)
def anotar_transferencia(cuerpo: AnotarTransferencia, uow: UowDep) -> Any:
    return res.anotar_transferencia(uow, **cuerpo.model_dump())


@router_residencia.get(
    "/transferencias/{tenant_id}",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Qué ha salido, hacia dónde y con qué amparo",
    description=(
        "Lo que consta es lo que se ha anotado: las salidas que no pasan por un "
        "punto que anote no aparecen aquí, y la respuesta lo dice."
    ),
)
def informe_transferencias(
    tenant_id: UUID, db: DbDep, _: AutenticadoDep, dias: int = Query(90, ge=1, le=730)
) -> Any:
    return res.informe_de_transferencias(db, tenant_id, dias=dias)


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router_aislamiento,
    modelo=AislamientoTenant,
    objeto="aislamiento",
    permiso="tenant:read",
    nombre="Declaraciones de aislamiento",
    # Sin ficha: hay **una declaración por tenant**, así que abrirla por
    # identificador no añade nada que el listado no enseñe ya, y el listado de
    # un solo elemento es el sitio donde se mira.
    ficha=False,
)
montar_listado(
    router_residencia,
    modelo=ResidenciaDato,
    objeto="residencia",
    permiso="tenant:read",
    nombre="Residencia del dato",
)


# ── Listados de las sub-colecciones ───────────────────────────────────────
# Mismo agujero que en las colecciones raíz: se podían crear y no se podían
# leer. Un sobre de firma, un subprocesador o una transferencia internacional
# que no se pueden listar no existen para quien tiene que auditarlos.

montar_listado(
    router_aislamiento,
    modelo=MigracionAislamiento,
    objeto="migracion_aislamiento",
    permiso="tenant:read",
    ruta="/migraciones",
    nombre="Migraciones de aislamiento",
)
montar_listado(
    router_residencia,
    modelo=Subprocesador,
    objeto="subprocesador",
    permiso="tenant:read",
    ruta="/subprocesadores",
    nombre="Subprocesadores",
)
montar_listado(
    router_residencia,
    modelo=TransferenciaInternacional,
    objeto="transferencia_internacional",
    permiso="tenant:read",
    ruta="/transferencias",
    nombre="Transferencias internacionales",
)


ROUTERS_AISLAMIENTO = [router_aislamiento, router_residencia]
