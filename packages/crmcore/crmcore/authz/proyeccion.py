"""Qué campos ve cada quien, y cómo (CRM-00.05.02.03, CRM-00.05.03.03).

El permiso por objeto dice si alguien puede leer cuentas. Este dice **qué
columnas** de una cuenta ve, y en qué estado: en claro, enmascaradas o no
verlas. Sin esto, dar acceso de lectura a un maestro de clientes es darlo todo —
el teléfono personal del contacto, la facturación, el identificador fiscal—, y
la única alternativa práctica acaba siendo no dar acceso, que es peor.

**La política se deriva de la sensibilidad, no de una lista de campos.** Cada
columna declara la suya en el modelo (`info={"sensibilidad": "personal"}`), y la
configuración dice qué ve cada rol de cada nivel. Una lista campo a campo
tendría que mantenerse a mano y se quedaría desfasada al primer campo nuevo —que
entraría **visible para todos** sin que nadie lo decidiera. Con la sensibilidad,
un campo nuevo sin declarar entra en el nivel por defecto, y el nivel por
defecto no es «público».

**Las excepciones viven en el esquema del servicio dueño del dato**, como la
papelera o la retención: una tabla central no la podría consultar el servicio
que serializa, porque los permisos de base de datos se lo impiden.

Y un límite dicho por delante: esto filtra **la salida**. No impide que un campo
oculto se use en un filtro de búsqueda, ni que se deduzca de un agregado. Cerrar
eso exige reescribir las consultas, y está pendiente.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Index, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base, TimestampMixin
from crmcore.errors import ErrorValidacion
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Campos retenidos durante esta petición. Va en un contextvar porque quien los
# retiene es el endpoint y quien los anuncia es el middleware, y entre los dos no
# hay forma de pasarse un valor sin ensuciar todas las firmas.
# El valor por defecto es `None` y no un conjunto vacío: un mutable por defecto
# en un `ContextVar` lo comparten TODAS las peticiones, y basta que alguien lo
# modifique en el sitio —`.get().add(x)`— para que una respuesta anuncie los
# campos que retuvo otra. Se reemplaza siempre con `.set()`, nunca se muta.
_retenidos: ContextVar[frozenset[str] | None] = ContextVar("campos_retenidos", default=None)


def anotar_retenidos(campos: Iterable[str]) -> None:
    """Apunta que estos campos se han retenido en esta respuesta."""
    _retenidos.set((_retenidos.get() or frozenset()) | frozenset(campos))


def retenidos() -> tuple[str, ...]:
    """Los campos retenidos, para anunciarlos en la respuesta."""
    return tuple(sorted(_retenidos.get() or frozenset()))


def limpiar_retenidos() -> None:
    _retenidos.set(None)


# De menos a más sensible. El orden es lo que permite decir «este rol ve hasta
# confidencial» en vez de enumerar niveles.
SENSIBILIDADES: tuple[str, ...] = (
    "publico",
    "interno",
    "confidencial",
    "personal",
    "especial",
)

# Qué se hace con un campo.
NIVELES = {
    "claro": "Se ve el valor",
    "enmascarado": "Se ven los últimos caracteres; el resto, puntos",
    "oculto": "No se devuelve, y se dice que no se ha devuelto",
}

# Nivel por defecto de una columna que no declara sensibilidad. **`interno` y no
# `publico`**: un campo nuevo que nadie clasificó no puede entrar como visible
# para cualquiera. Equivocarse hacia la discreción se corrige con una línea de
# configuración; al revés se corrige con una notificación de brecha.
SENSIBILIDAD_POR_DEFECTO = "interno"


class PoliticaCampo(Base, TimestampMixin):
    """Excepción explícita para un campo concreto.

    Manda sobre la política por sensibilidad, en los dos sentidos: puede ocultar
    algo que por su nivel se vería, y puede abrir algo que por su nivel se
    ocultaría. Existe porque la clasificación por niveles acierta en el 95 % y
    el 5 % restante son decisiones que un cliente concreto necesita tomar.
    """

    __tablename__ = "politicas_campo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    objeto: Mapped[str] = mapped_column(String(60), nullable=False)
    campo: Mapped[str] = mapped_column(String(80), nullable=False)
    # `*` vale para cualquier rol. Es la forma de decir «este campo no lo ve
    # nadie salvo quien tenga una excepción propia».
    rol: Mapped[str] = mapped_column(String(60), nullable=False, default="*")
    nivel: Mapped[str] = mapped_column(String(20), nullable=False, default="oculto")

    __table_args__ = (
        UniqueConstraint("tenant_id", "objeto", "campo", "rol", name="uq_politica_campo"),
        Index("ix_politicas_campo", "tenant_id", "objeto"),
    )


@dataclass(frozen=True, slots=True)
class Proyeccion:
    """El resultado: los datos ya filtrados y qué se quitó."""

    datos: dict[str, Any]
    ocultos: tuple[str, ...]
    enmascarados: tuple[str, ...]


def sensibilidad_de(modelo: type, campo: str) -> str:
    """La sensibilidad declarada de una columna, o la de por defecto.

    Se lee del `info` de la columna y no de una tabla aparte para que viva
    **junto a la definición del campo**: así, quien añade una columna sensible
    ve en la línea de al lado que sus vecinas la declaran, y la tabla aparte no
    se queda sin la entrada nueva.
    """
    columnas = getattr(modelo, "__table__", None)
    if columnas is None or campo not in columnas.columns:
        return SENSIBILIDAD_POR_DEFECTO
    valor = columnas.columns[campo].info.get("sensibilidad")
    if valor not in SENSIBILIDADES:
        return SENSIBILIDAD_POR_DEFECTO
    return str(valor)


def _politica_por_rol(db: Session | None) -> dict[str, dict[str, str]]:
    """Qué nivel de sensibilidad ve cada rol, de la configuración.

    Ejemplo: `{"comercial": {"ve_hasta": "confidencial", "enmascara": "personal"}}`
    significa que un comercial ve en claro hasta lo confidencial, ve los datos
    personales enmascarados, y lo especial no lo ve.
    """
    from crmcore.runtime import settings as rt

    crudo = rt.efectivo("politica_sensibilidad", db)
    if isinstance(crudo, dict) and crudo:
        return {str(k): dict(v) for k, v in crudo.items() if isinstance(v, dict)}
    return {}


def nivel_para(
    sensibilidad: str, roles: frozenset[str], politica: dict[str, dict[str, str]]
) -> str:
    """Qué se hace con un campo de esa sensibilidad para esos roles.

    Con varios roles gana **el más permisivo**, igual que con los permisos: los
    roles suman, y que añadir un rol quitara visibilidad sería incomprensible
    para quien lo administra.

    Un rol que la política no menciona no ve nada por encima de `interno`. Es
    deliberado: un rol nuevo sin configurar no puede nacer viendo los datos
    personales de todos los clientes.
    """
    if sensibilidad not in SENSIBILIDADES:
        sensibilidad = SENSIBILIDAD_POR_DEFECTO
    orden = SENSIBILIDADES.index(sensibilidad)

    mejor = "oculto"
    for rol in roles or {"*"}:
        regla = politica.get(rol) or politica.get("*") or {}
        ve_hasta = str(regla.get("ve_hasta", "interno"))
        enmascara = str(regla.get("enmascara", "personal"))
        tope_claro = SENSIBILIDADES.index(ve_hasta) if ve_hasta in SENSIBILIDADES else 1
        tope_masc = SENSIBILIDADES.index(enmascara) if enmascara in SENSIBILIDADES else 3

        if orden <= tope_claro:
            return "claro"  # no hay nada mejor que esto
        if orden <= tope_masc and mejor == "oculto":
            mejor = "enmascarado"
    return mejor


def _excepciones(
    db: Session | None, tenant_id: UUID | None, objeto: str
) -> dict[tuple[str, str], str]:
    """Excepciones declaradas para este objeto: `{(campo, rol): nivel}`."""
    if db is None or tenant_id is None:
        return {}
    filas = (
        db.execute(
            select(PoliticaCampo).where(
                PoliticaCampo.tenant_id == tenant_id, PoliticaCampo.objeto == objeto
            )
        )
        .scalars()
        .all()
    )
    return {(f.campo, f.rol): f.nivel for f in filas}


def proyectar(
    datos: dict[str, Any],
    *,
    objeto: str,
    modelo: type,
    roles: frozenset[str],
    es_admin: bool = False,
    tenant_id: UUID | None = None,
    db: Session | None = None,
) -> Proyeccion:
    """Filtra y enmascara un registro ya serializado.

    Se trabaja sobre el **diccionario** y no sobre el objeto ORM a propósito: el
    objeto se sigue necesitando entero para las reglas de negocio, y vaciarle
    campos para serializarlo sería sabotear la lógica que viene después.

    Un administrador de plataforma **no queda exento**. Su acceso a datos de un
    tenant ya está auditado con motivo, y eximirle aquí convertiría ese
    privilegio en «ve todo siempre», que es justo lo que la auditoría intenta
    acotar. Lo que se le da es un rol con la política más amplia, no una puerta
    aparte.
    """
    from crmcore.config import get_settings
    from crmcore.security.cifrado import enmascarar

    if not bool(get_settings().masking_enabled):
        return Proyeccion(datos=dict(datos), ocultos=(), enmascarados=())

    politica = _politica_por_rol(db)
    excepciones = _excepciones(db, tenant_id, objeto)
    roles_efectivos = frozenset(roles) | ({"admin"} if es_admin else frozenset())

    salida: dict[str, Any] = {}
    ocultos: list[str] = []
    enmascarados: list[str] = []

    for campo, valor in datos.items():
        nivel = _nivel_del_campo(campo, modelo, roles_efectivos, politica, excepciones)
        if nivel == "claro" or valor is None:
            # Un campo vacío no se enmascara: «····» donde no hay nada hace
            # creer que hay algo escondido, y eso es peor que un hueco.
            salida[campo] = valor
        elif nivel == "enmascarado":
            salida[campo] = enmascarar(str(valor))
            enmascarados.append(campo)
        else:
            ocultos.append(campo)

    return Proyeccion(
        datos=salida, ocultos=tuple(sorted(ocultos)), enmascarados=tuple(sorted(enmascarados))
    )


def _nivel_del_campo(
    campo: str,
    modelo: type,
    roles: frozenset[str],
    politica: dict[str, dict[str, str]],
    excepciones: dict[tuple[str, str], str],
) -> str:
    """Nivel efectivo: la excepción si la hay, y si no, el que toca por sensibilidad."""
    for rol in [*sorted(roles), "*"]:
        nivel = excepciones.get((campo, rol))
        if nivel in NIVELES:
            return nivel
    return nivel_para(sensibilidad_de(modelo, campo), roles, politica)


def fijar_politica_campo(
    db: Session,
    *,
    tenant_id: UUID,
    objeto: str,
    campo: str,
    nivel: str,
    rol: str = "*",
) -> PoliticaCampo:
    """Declara una excepción para un campo."""
    if nivel not in NIVELES:
        raise ErrorValidacion(
            f"Nivel desconocido: «{nivel}»",
            error_code="proyeccion.nivel_desconocido",
            detalle={"admitidos": sorted(NIVELES)},
        )
    fila = db.execute(
        select(PoliticaCampo).where(
            PoliticaCampo.tenant_id == tenant_id,
            PoliticaCampo.objeto == objeto,
            PoliticaCampo.campo == campo,
            PoliticaCampo.rol == rol,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = PoliticaCampo(tenant_id=tenant_id, objeto=objeto, campo=campo, rol=rol)
        db.add(fila)
    fila.nivel = nivel
    db.flush()
    logger.info("proyeccion.excepcion_fijada", objeto=objeto, campo=campo, rol=rol, nivel=nivel)
    return fila
