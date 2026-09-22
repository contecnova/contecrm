"""API del gobierno único de la suite (CRM-00.01.07)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.tenancy import suite, suite_conector

router_suite = APIRouter(prefix="/suite", tags=["suite"])


# ── Conexión de herramientas (CRM-00.01.07.08) ────────────────────────────


class ConectarHerramienta(BaseModel):
    nombre: str = Field(max_length=60, description="contecmind, contecintelligence, …")
    base_url: str = Field(max_length=500)
    credenciales: dict[str, str] = Field(default_factory=dict)
    tipo: str = Field(
        "generico",
        description=(
            "`generico` es el suelo y funciona con cualquier herramienta "
            "declarando rutas y mapeos. Los conectores nativos van encima, solo "
            "para lo que el genérico no alcanza"
        ),
    )
    mapeo_roles: dict[str, Any] = Field(default_factory=dict)
    mapeo_campos: dict[str, Any] = Field(default_factory=dict)
    objetos: list[str] = Field(default_factory=list)
    identificador_externo: str = Field("", max_length=200)


@router_suite.post(
    "/herramientas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Conectar una herramienta de la suite",
    description=(
        "La dirección pasa por el guard de salidas, igual que un webhook o un "
        "IdP: aquí se mandan datos de personas y una credencial de "
        "administración, y una dirección apuntando a la red interna convertiría "
        "el empuje en una forma de hablar con lo que no se alcanza desde fuera."
    ),
)
def conectar(datos: ConectarHerramienta, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = suite.conectar(
        uow.db,
        principal.tenant_id,
        nombre=datos.nombre,
        base_url=datos.base_url,
        credenciales=datos.credenciales,
        tipo=datos.tipo,
        mapeo_roles=datos.mapeo_roles,
        mapeo_campos=datos.mapeo_campos,
        objetos=datos.objetos or None,
        identificador_externo=datos.identificador_externo,
    )
    return {"id": str(fila.id), "nombre": fila.nombre, "tipo": fila.tipo}


@router_suite.get(
    "/panel",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Cómo está la suite para este tenant",
    description=(
        "Las bajas sin aplicar salen **aparte** porque son lo único que hay que "
        "mirar con prisa: una baja que no llegó es un acceso que sigue abierto "
        "en otra herramienta, y eso no lo ve nadie hasta una auditoría.\n\n"
        "Si no hay ninguna herramienta conectada se dice: un «todo bien» "
        "silencioso haría creer que el cliente está en la suite cuando solo está "
        "en el CRM."
    ),
)
def panel(db: DbDep, principal: AutenticadoDep) -> Any:
    return suite.panel(db, principal.tenant_id)


# ── Identidad y organización (CRM-00.01.07.01, .05) ───────────────────────


@router_suite.get(
    "/identidad",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Los datos del tenant tal como los ve toda la suite",
    description=(
        "Un único identificador y unos únicos datos. Dos herramientas con dos "
        "nombres distintos para el mismo cliente es como empieza el trabajo "
        "manual de conciliar, y ya no para."
    ),
)
def identidad(db: DbDep, principal: AutenticadoDep) -> Any:
    return {
        "tenant": suite.identidad_de_tenant(db, principal.tenant_id),
        "organizacion": suite.organizacion_de_tenant(db, principal.tenant_id),
    }


# ── Provisionar (CRM-00.01.07.02, .03) ────────────────────────────────────


@router_suite.post(
    "/provisionar/tenant",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Dar de alta este tenant en las herramientas conectadas",
    description=(
        "No da la cascada por buena: cada herramienta tiene su fila de estado y "
        "se dice cuál ha fallado. Un alta «correcta» que dejó dos de tres "
        "herramientas sin el cliente es peor que una que falla, porque se "
        "descubre el día que alguien intenta abrir un documento."
    ),
)
def provisionar_tenant(uow: UowDep, principal: AutenticadoDep) -> Any:
    return suite.provisionar_tenant(uow.db, principal.tenant_id)


class UsuarioSuite(BaseModel):
    id: UUID
    email: str
    nombre: str = ""
    roles: list[str] = Field(default_factory=list)
    unidad: str | None = None
    activa: bool = True
    operacion: str = Field("alta", description="alta | actualizacion | baja")


@router_suite.post(
    "/provisionar/usuario",
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Alta, cambio o baja de un usuario en toda la suite",
    description=(
        "**La baja tiene prioridad sobre todo lo demás.** Un alta que tarda es "
        "una molestia: la persona llama y alguien lo mira. Una baja que tarda es "
        "una puerta abierta que no ve nadie.\n\n"
        "Un usuario cuyo rol no esté mapeado en una herramienta **no se crea** "
        "allí: una cuenta sin rol no sirve para nada y además hay que acordarse "
        "de darla de baja."
    ),
)
def provisionar_usuario(datos: UsuarioSuite, uow: UowDep, principal: AutenticadoDep) -> Any:
    return suite.provisionar_usuario(
        uow.db,
        principal.tenant_id,
        {
            "id": str(datos.id),
            "email": datos.email,
            "nombre": datos.nombre,
            "roles": datos.roles,
            "unidad": datos.unidad,
            "activa": datos.activa,
        },
        operacion=datos.operacion,
    )


@router_suite.post(
    "/provisionar/organizacion",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Replicar áreas y departamentos a las herramientas",
    description=(
        "Se define una vez aquí. Definirla en tres sitios garantiza que a los "
        "tres meses son tres árboles distintos, y entonces los permisos que "
        "cuelgan de ellos dejan de coincidir sin que nadie lo haya cambiado a "
        "propósito."
    ),
)
def provisionar_organizacion(uow: UowDep, principal: AutenticadoDep) -> Any:
    return suite.provisionar_organizacion(uow.db, principal.tenant_id)


# ── Simulación y aplicación (CRM-00.01.07.10, .11) ────────────────────────


@router_suite.get(
    "/simular",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Qué se crearía, cambiaría o desactivaría",
    description=(
        "El error caro aquí no es el técnico: es desactivar a media plantilla en "
        "el gestor documental por un mapeo de roles mal escrito, y enterarse "
        "cuando llaman."
    ),
)
def simular(
    db: DbDep, principal: AutenticadoDep, herramienta: str = Query("", max_length=60)
) -> Any:
    return suite.simular(db, principal.tenant_id, herramienta=herramienta or None)


@router_suite.post(
    "/aplicar",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Aplicar la cola pendiente",
    description=(
        "Con la baja primero y por lotes con tope: una cola de diez mil no puede "
        "ejecutarse dentro de una petición HTTP, y sin tope el primer tenant "
        "grande que reconcilie deja el servicio sin hilos."
    ),
)
def aplicar(
    uow: UowDep,
    principal: AutenticadoDep,
    herramienta: str = Query("", max_length=60),
    tope: int = Query(100, ge=1, le=500),
) -> Any:
    return suite_conector.aplicar_pendientes(
        uow.db, principal.tenant_id, herramienta=herramienta or None, tope=tope
    )


@router_suite.get(
    "/cuarentena",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Lo que no se ha podido aplicar y necesita una persona",
    description=(
        "Reintentar para siempre esconde el problema en un log que nadie mira; "
        "rendirse a la primera convierte un fallo de red en trabajo manual. Lo "
        "que agota los intentos se aparta **y se enseña**, con lo que se mandó "
        "dentro: sin eso, quien lo mira tiene que adivinar si el problema es el "
        "dato o la herramienta."
    ),
)
def cuarentena(db: DbDep, principal: AutenticadoDep) -> Any:
    return suite.cuarentena(db, principal.tenant_id)


@router_suite.post(
    "/cuarentena/{sincronizacion_id}/reintentar",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Volver a intentar algo apartado",
)
def reintentar(sincronizacion_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = suite.reintentar(uow.db, principal.tenant_id, sincronizacion_id)
    return {"id": str(fila.id), "estado": fila.estado}


# ── Reconciliación (CRM-00.01.07.07) ──────────────────────────────────────


@router_suite.get(
    "/reconciliar/{herramienta}",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Qué hay allí que no coincide con lo de aquí",
    description=(
        "Tres divergencias, y las tres importan por motivos distintos: lo que "
        "**falta allí** es un empuje que no llegó y se reencola; lo que **sobra "
        "allí** suele ser una baja que no se aplicó, y es literalmente un acceso "
        "abierto; lo que **difiere** lo cambió alguien en la otra herramienta y "
        "**no se pisa sin decirlo**.\n\n"
        "Cuando el conector no sabe leer el estado remoto se dice: «no se ha "
        "podido comprobar» y «está todo bien» son cosas distintas, y "
        "confundirlas es por lo que nadie se fía de los paneles de "
        "sincronización."
    ),
)
def reconciliar(herramienta: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return suite_conector.reconciliar_con_remoto(db, principal.tenant_id, herramienta)


class Reparar(BaseModel):
    objeto_ids: list[str]
    forzar: bool = Field(
        False,
        description=(
            "Necesario para lo divergente: repararlo es pisar el trabajo de "
            "alguien en la otra herramienta, y hacerlo sin decirlo es cómo se "
            "pierde la confianza en el empuje automático"
        ),
    )


@router_suite.post(
    "/reconciliar/{herramienta}/reparar",
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Reencolar lo divergente",
)
def reparar(herramienta: str, datos: Reparar, uow: UowDep, principal: AutenticadoDep) -> Any:
    return suite.reparar(
        uow.db,
        principal.tenant_id,
        herramienta,
        objeto_ids=datos.objeto_ids,
        forzar=datos.forzar,
    )


# ── Auditoría transversal (CRM-00.01.07.12) ───────────────────────────────


@router_suite.get(
    "/historial",
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Quién cambió qué y en qué herramienta acabó aplicándose",
    description=(
        "Sin esto, contestar «¿por qué este usuario sigue entrando en el gestor "
        "documental?» obliga a mirar tres registros de auditoría distintos y a "
        "cruzarlos de memoria."
    ),
)
def historial(
    db: DbDep,
    principal: AutenticadoDep,
    objeto_id: str = Query("", max_length=80),
    limite: int = Query(200, ge=1, le=1000),
) -> Any:
    return suite.historial(db, principal.tenant_id, objeto_id=objeto_id or None, limite=limite)


ROUTERS_SUITE = [router_suite]
