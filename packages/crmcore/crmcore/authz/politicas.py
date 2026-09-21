"""Políticas ABAC guardadas, versionadas y aplicadas (CRM-00.05.02.17 a .21).

El motor de `abac.py` estaba entero y **no lo llamaba nadie**: las políticas
vivían en una lista de Python, las tres de ejemplo desactivadas, y el único
sitio que las evaluaba era el explicador de permisos. O sea, el sistema sabía
explicar una decisión que no tomaba. Esto es la otra mitad.

Tres cosas que decide este módulo y conviene entender:

**Las políticas viven en el esquema de CADA servicio.** La decisión se toma
donde está el dato —`party` decide sobre una cuenta— y ningún servicio lee el
esquema de otro. Se escriben desde administración y se replican por evento,
igual que los ajustes en caliente, la clave BYOK del tenant y el mapeo del
gestor documental. Un servicio que no replicara seguiría decidiendo con las
políticas de ayer, que en permisos es la peor divergencia posible.

**Restringen, nunca amplían.** Se evalúan DESPUÉS del RBAC. Un usuario sin
`account:read` no lee cuentas por permisiva que sea la política, así que «¿qué
puede hacer como máximo?» se sigue respondiendo mirando solo los roles.

**Una política habla de registros o de campos, no de las dos cosas.** Con
`alcance="registro"`, no cumplirla esconde el registro entero. Con
`alcance="campos"`, no cumplirla esconde solo los campos que nombra y el
registro se sigue viendo. Mezclarlo en una sola política haría imposible
explicar por qué algo no se ve, que es justo lo que este subsistema existe para
poder responder.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.authz.abac import Condicion, Politica
from crmcore.db.base import Base
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

POLITICA_CAMBIADA = "seguridad.politica_abac_cambiada"

# Qué esconde una política cuando no se cumple.
#
#   registro  — el registro no existe para quien pregunta.
#   campos    — el registro se ve, algunos campos no.
#   bloqueado — el registro se ve EXISTIR, sin detalle (CRM-00.05.02.09).
#
# El tercero no es un matiz. Esconder del todo hace que los recuentos mientan:
# la ficha de una cuenta dice «5 oportunidades» y el listado enseña 3, y quien
# lo ve concluye que el sistema ha perdido dos. Con el registro bloqueado el
# recuento cuadra, se ve que existe algo que no se puede abrir, y quien lo
# necesita sabe a quién pedírselo — que es información distinta de «no hay
# nada».
ALCANCES = ("registro", "campos", "bloqueado")
COMBINACIONES = ("todas", "alguna")


class PoliticaAbac(Base):
    """Una política de acceso por atributos, tal como se guarda.

    Las condiciones se guardan como datos —una lista de `{atributo, operador,
    valor}`— y no como expresión: una cadena que hubiera que interpretar sería
    ejecutar entrada del tenant dentro del motor de permisos, y además no se
    podría explicar condición a condición, que es lo que hace útil al
    explicador.
    """

    __tablename__ = "politicas_abac"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    objeto: Mapped[str] = mapped_column(String(60), nullable=False)
    # Lista de acciones: read, write, delete, export… o `*`.
    acciones: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    condiciones: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    combinacion: Mapped[str] = mapped_column(String(10), nullable=False, default="todas")
    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    alcance: Mapped[str] = mapped_column(String(10), nullable=False, default="registro")
    # Solo con `alcance="campos"`: qué campos deja de ver o de escribir quien no
    # cumple la condición.
    campos: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    descripcion: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Sube en cada cambio. Es lo que permite decir «con qué política se decidió
    # aquello» meses después, cuando alguien reclama.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    creada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("uq_politica_abac_nombre", "tenant_id", "nombre", unique=True),)


class VersionPoliticaAbac(Base):
    """Foto de una política cada vez que cambia. Append-only.

    Sin el histórico, «esta política deniega desde hace dos semanas» no se puede
    contestar: la tabla viva solo enseña el estado de hoy. Y una política de
    acceso es exactamente el tipo de cosa por la que alguien pregunta después,
    no antes.
    """

    __tablename__ = "versiones_politica_abac"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    politica_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    contenido: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cambiada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_versiones_politica", "tenant_id", "politica_id", "version"),)


# ── Lectura ───────────────────────────────────────────────────────────────

# Caché por tenant. Las políticas se leen en CADA decisión —una ficha, un
# listado, una escritura— y sin caché serían una consulta por petición para algo
# que cambia una vez al mes.
_cache: dict[UUID, list[Politica]] = {}

# Alcance y campos de cada política, por nombre. Va aparte porque `Politica` es
# del motor y no debe saber nada de cómo se guarda. Se llena y se vacía a la vez
# que `_cache`.
_alcances: dict[UUID, dict[str, tuple[str, tuple[Any, ...]]]] = {}


def invalidar(tenant_id: UUID | None = None) -> None:
    """Vacía la caché. Sin argumento, la de todos los tenants.

    Las DOS: `_cache` y `_alcances` se llenan juntas y tienen que vaciarse
    juntas. Vaciar solo la primera dejaba el alcance de una política borrada
    apuntando a campos que ya no controla nadie.
    """
    if tenant_id is None:
        _cache.clear()
        _alcances.clear()
    else:
        _cache.pop(tenant_id, None)
        _alcances.pop(tenant_id, None)


def _a_politica(fila: PoliticaAbac) -> Politica:
    return Politica(
        nombre=fila.nombre,
        objeto=fila.objeto,
        acciones=frozenset(str(a) for a in (fila.acciones or [])),
        condiciones=tuple(
            Condicion(
                atributo=str(c.get("atributo", "")),
                operador=str(c.get("operador", "=")),
                valor=c.get("valor"),
            )
            for c in (fila.condiciones or [])
            if isinstance(c, dict)
        ),
        combinacion=fila.combinacion,
        prioridad=fila.prioridad,
        activa=fila.activa,
        descripcion=fila.descripcion,
    )


def cargar(db: Session, tenant_id: UUID, *, alcance: str = "registro") -> list[Politica]:
    """Las políticas ACTIVAS del tenant para ese alcance.

    Solo las activas: una política guardada y desactivada existe para poder
    editarla y probarla con el simulador sin que decida nada. Que se pueda
    escribir sin que aplique es lo que hace que alguien se atreva a escribirla.
    """
    todas = _cache.get(tenant_id)
    if todas is None:
        filas = (
            db.execute(
                select(PoliticaAbac).where(
                    PoliticaAbac.tenant_id == tenant_id,
                    PoliticaAbac.activa.is_(True),
                )
            )
            .scalars()
            .all()
        )
        # Se guarda el alcance junto a la política traducida: `Politica` es del
        # motor y no lo lleva, y volver a la base para saberlo anularía la caché.
        _cache[tenant_id] = [_a_politica(f) for f in filas]
        _alcances[tenant_id] = {f.nombre: (f.alcance, tuple(f.campos or [])) for f in filas}
        todas = _cache[tenant_id]
    return [
        p
        for p in todas
        if _alcances.get(tenant_id, {}).get(p.nombre, ("registro", ()))[0] == alcance
    ]


def campos_de(tenant_id: UUID, nombre: str) -> tuple[str, ...]:
    """Campos que nombra una política de alcance `campos`."""
    return tuple(str(c) for c in _alcances.get(tenant_id, {}).get(nombre, ("", ()))[1])


def campos_gobernados(db: Session, tenant_id: UUID, objeto: str) -> set[str]:
    """Todos los campos que ALGUNA política activa controla para ese objeto.

    Es la respuesta conservadora cuando evaluar falla: no se sabe cuáles había
    que esconder, así que se esconden todos los que están bajo política. Es
    acotado —no esconde el registro entero— y no enseña nada que una política
    pudiera estar negando.
    """
    filas = (
        db.execute(
            select(PoliticaAbac).where(
                PoliticaAbac.tenant_id == tenant_id,
                PoliticaAbac.activa.is_(True),
                PoliticaAbac.alcance == "campos",
                PoliticaAbac.objeto.in_([objeto, "*"]),
            )
        )
        .scalars()
        .all()
    )
    return {str(c) for f in filas for c in (f.campos or [])}


# ── Escritura ─────────────────────────────────────────────────────────────


def guardar(
    db: Session,
    *,
    tenant_id: UUID,
    nombre: str,
    objeto: str,
    acciones: list[str],
    condiciones: list[dict[str, Any]],
    combinacion: str = "todas",
    prioridad: int = 100,
    alcance: str = "registro",
    campos: list[str] | None = None,
    activa: bool = False,
    descripcion: str = "",
    por: UUID | None = None,
) -> PoliticaAbac:
    """Crea o actualiza una política, sube su versión y la replica.

    Se valida la gramática ANTES de guardar: una política con un operador que no
    existe se evalúa como denegar —en seguridad, ante la duda, no— y eso
    convertiría un error de escritura en un corte de acceso silencioso para
    quien la activara.
    """
    from crmcore.authz.abac import OPERADORES

    nombre = (nombre or "").strip()
    if not nombre:
        raise ErrorValidacion("La política necesita un nombre", error_code="politica.sin_nombre")
    if alcance not in ALCANCES:
        raise ErrorValidacion(
            f"El alcance es «registro» o «campos», no «{alcance}»",
            error_code="politica.alcance_invalido",
        )
    if combinacion not in COMBINACIONES:
        raise ErrorValidacion(
            f"La combinación es «todas» o «alguna», no «{combinacion}»",
            error_code="politica.combinacion_invalida",
        )
    if not acciones:
        raise ErrorValidacion(
            "Una política sin acciones no aplica a nada", error_code="politica.sin_acciones"
        )
    for condicion in condiciones:
        operador = str(condicion.get("operador", ""))
        if operador not in OPERADORES:
            raise ErrorValidacion(
                f"Operador desconocido: «{operador}»",
                error_code="politica.operador_desconocido",
                detalle={"admitidos": sorted(OPERADORES)},
            )
        if not str(condicion.get("atributo", "")).strip():
            raise ErrorValidacion(
                "Cada condición necesita un atributo", error_code="politica.condicion_sin_atributo"
            )
    if alcance == "campos" and not campos:
        raise ErrorValidacion(
            "Una política de campos tiene que decir qué campos",
            error_code="politica.campos_vacios",
        )
    if alcance == "bloqueado" and not campos:
        raise ErrorValidacion(
            "Una política de bloqueo tiene que decir qué campos SÍ se ven: un "
            "registro bloqueado del que no se ve nada es un registro escondido "
            "con otro nombre",
            error_code="politica.bloqueo_sin_campos",
        )

    fila = db.execute(
        select(PoliticaAbac).where(
            PoliticaAbac.tenant_id == tenant_id, PoliticaAbac.nombre == nombre
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = PoliticaAbac(tenant_id=tenant_id, nombre=nombre, creada_por=por, version=0)
        db.add(fila)

    fila.objeto = objeto
    fila.acciones = list(acciones)
    fila.condiciones = list(condiciones)
    fila.combinacion = combinacion
    fila.prioridad = prioridad
    fila.alcance = alcance
    fila.campos = list(campos or [])
    fila.activa = activa
    fila.descripcion = descripcion
    fila.version += 1
    db.flush()

    db.add(
        VersionPoliticaAbac(
            tenant_id=tenant_id,
            politica_id=fila.id,
            version=fila.version,
            contenido=a_dict(fila),
            cambiada_por=por,
        )
    )
    db.flush()
    _propagar(db, fila)
    invalidar(tenant_id)
    logger.info(
        "abac.politica_guardada",
        politica=nombre,
        objeto=objeto,
        version=fila.version,
        activa=activa,
    )
    return fila


def borrar(db: Session, *, tenant_id: UUID, nombre: str, por: UUID | None = None) -> None:
    """Quita una política. Su histórico se queda.

    Borrar también las versiones dejaría sin respuesta a quien pregunte por qué
    no veía algo el mes pasado, que es cuando se pregunta.
    """
    fila = db.execute(
        select(PoliticaAbac).where(
            PoliticaAbac.tenant_id == tenant_id, PoliticaAbac.nombre == nombre
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Esa política no existe", error_code="politica.no_existe")
    db.add(
        VersionPoliticaAbac(
            tenant_id=tenant_id,
            politica_id=fila.id,
            version=fila.version + 1,
            contenido={"borrada": True, "nombre": nombre},
            cambiada_por=por,
        )
    )
    db.delete(fila)
    db.flush()
    _propagar(db, fila, borrada=True)
    invalidar(tenant_id)
    logger.info("abac.politica_borrada", politica=nombre)


def a_dict(fila: PoliticaAbac) -> dict[str, Any]:
    return {
        "id": str(fila.id),
        "nombre": fila.nombre,
        "objeto": fila.objeto,
        "acciones": list(fila.acciones or []),
        "condiciones": list(fila.condiciones or []),
        "combinacion": fila.combinacion,
        "prioridad": fila.prioridad,
        "alcance": fila.alcance,
        "campos": list(fila.campos or []),
        "activa": fila.activa,
        "descripcion": fila.descripcion,
        "version": fila.version,
    }


# ── Réplica a los demás servicios ─────────────────────────────────────────


def declarar_evento() -> None:
    from crmcore.events.catalogo import TipoEvento, obtener, registrar

    if obtener(POLITICA_CAMBIADA) is not None:
        return
    registrar(
        TipoEvento(
            tipo=POLITICA_CAMBIADA,
            version=1,
            productor="core",
            descripcion=(
                "Una política ABAC ha cambiado. La consumen TODOS los servicios "
                "para replicarla en su esquema: la decisión se toma donde está el dato"
            ),
            campos=("tenant_id", "politica", "borrada"),
        )
    )


def _propagar(db: Session, fila: PoliticaAbac, *, borrada: bool = False) -> None:
    from crmcore.bus.outbox import encolar

    declarar_evento()
    contenido = {"nombre": fila.nombre} if borrada else a_dict(fila)
    encolar(
        db,
        tenant_id=fila.tenant_id,
        tipo=POLITICA_CAMBIADA,
        subject_tipo="politica_abac",
        subject_id=fila.nombre,
        data={"tenant_id": str(fila.tenant_id), "politica": contenido, "borrada": borrada},
        # El hecho es «esta política quedó en esta versión». Reintentar la
        # publicación no puede aplicar dos veces una versión distinta.
        dedup_key=f"abac:{fila.tenant_id}:{fila.nombre}:{fila.version}"[:64],
    )


async def consumir_politica(mensaje: Any) -> None:
    """Aplica en ESTE servicio la política cambiada en otro.

    Lo registra `crear_servicio` en todos. Un servicio que no lo consumiera
    seguiría decidiendo con las políticas de ayer: en permisos, esa es la
    divergencia más cara, porque no falla nada — simplemente alguien ve lo que
    ya no debería.
    """
    from crmcore.db.uow import unidad_de_trabajo

    if isinstance(mensaje, dict):
        datos = mensaje.get("data") if isinstance(mensaje.get("data"), dict) else mensaje
    else:
        datos = getattr(mensaje, "data", None) or {}
    try:
        tenant_id = UUID(str(datos.get("tenant_id")))
    except (TypeError, ValueError):
        logger.error("abac.politica_sin_tenant", datos=str(datos)[:200])
        return
    contenido = datos.get("politica") or {}
    nombre = str(contenido.get("nombre") or "")
    if not nombre:
        return

    with unidad_de_trabajo(sistema=True) as uow:
        fila = uow.db.execute(
            select(PoliticaAbac).where(
                PoliticaAbac.tenant_id == tenant_id, PoliticaAbac.nombre == nombre
            )
        ).scalar_one_or_none()
        if datos.get("borrada"):
            if fila is not None:
                uow.db.delete(fila)
        else:
            if fila is None:
                fila = PoliticaAbac(tenant_id=tenant_id, nombre=nombre)
                uow.db.add(fila)
            # Se escribe el contenido tal cual y NO se llama a `guardar`: llamarlo
            # reemitiría el evento al aplicarlo y el bus entraría en un bucle que
            # crece con el número de servicios. Es lo mismo que pasa con los
            # ajustes en caliente.
            fila.objeto = str(contenido.get("objeto") or "*")
            fila.acciones = list(contenido.get("acciones") or [])
            fila.condiciones = list(contenido.get("condiciones") or [])
            fila.combinacion = str(contenido.get("combinacion") or "todas")
            fila.prioridad = int(contenido.get("prioridad") or 100)
            fila.alcance = str(contenido.get("alcance") or "registro")
            fila.campos = list(contenido.get("campos") or [])
            fila.activa = bool(contenido.get("activa"))
            fila.descripcion = str(contenido.get("descripcion") or "")
            fila.version = int(contenido.get("version") or 1)
    invalidar(tenant_id)
    logger.info("abac.politica_replicada", politica=nombre, tenant=str(tenant_id))


# ── Dimensiones de restricción (CRM-00.05.02.08) ──────────────────────────

# Las cuatro por las que se restringe el acceso en una organización con más de
# una unidad: unidad de negocio, marca, país y canal. Se declaran aquí, con el
# atributo del registro y el del usuario que tienen que coincidir, en vez de
# dejar que cada tenant las escriba a mano.
#
# No es por comodidad: escritas a mano, la mitad acaba comparando el campo
# equivocado —`pais` del registro contra `pais` del usuario cuando el del
# usuario es el de su oficina, no el de su cartera— y el resultado es una
# política que restringe de más o de menos sin que nadie sepa cuál.
DIMENSIONES: dict[str, tuple[str, str]] = {
    "unidad_de_negocio": ("registro.business_unit_id", "@usuario.business_unit_id"),
    "marca": ("registro.marca", "@usuario.marca"),
    "pais": ("registro.pais", "@usuario.pais"),
    "canal": ("registro.canal", "@usuario.canal"),
}


def politica_por_dimension(
    dimension: str,
    *,
    objeto: str,
    acciones: list[str] | None = None,
    alcance: str = "registro",
    campos: list[str] | None = None,
) -> dict[str, Any]:
    """Construye la política de una dimensión, lista para guardar.

    Devuelve el diccionario y no la guarda: quien administra decide si la activa
    y con qué alcance —esconder el registro o dejarlo bloqueado— y eso es una
    decisión de negocio, no algo que se pueda dar por hecho.
    """
    if dimension not in DIMENSIONES:
        raise ErrorValidacion(
            f"«{dimension}» no es una dimensión de restricción",
            error_code="politica.dimension_desconocida",
            detalle={"admitidas": sorted(DIMENSIONES)},
        )
    atributo, valor = DIMENSIONES[dimension]
    return {
        "nombre": f"{dimension}_{objeto}",
        "objeto": objeto,
        "acciones": acciones or ["read", "write"],
        "condiciones": [{"atributo": atributo, "operador": "=", "valor": valor}],
        "alcance": alcance,
        "campos": campos or [],
        "descripcion": (
            f"Cada quien ve los {objeto} de su {dimension.replace('_', ' ')}. "
            "Un registro sin ese atributo NO lo ve nadie: en una restricción, el "
            "dato que falta no puede abrir la puerta."
        ),
    }
