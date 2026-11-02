"""Vistas de lista: el filtro con nombre de un listado (CRM-07.04.03.07).

Es lo que en Salesforce es «Todas las cuentas», «Mis oportunidades abiertas» o
«Casos que vencen hoy»: un recorte con nombre que alguien crea una vez y abre
cada día. El producto tenía filtros, orden y elección de columnas, y **ninguna
forma de guardarlos**: cada mañana había que volver a montarlos.

**Quién puede qué, y por qué:**

- Crear una vista **para uno mismo** es `vista:read`, que tiene todo el mundo.
  Guardar un recorte propio es el equivalente a ordenar una columna: si
  dependiera de un permiso de administración, el noventa por ciento de la
  gente no podría usar lo que más se usa.
- Crear o tocar una vista **de todo el tenant** es `vista:compartir`. Una
  vista que ve todo el mundo es configuración del tenant y la decide quien
  puede configurarlo — y, sobre todo, es la que sale por defecto a quien entra
  por primera vez.
- La vista de otra persona **no se ve ni se toca**. Es un recorte suyo, y
  listarlas todas convertiría el desplegable en el inventario de lo que mira
  cada uno.

Los recortes se guardan **tal y como los manda el front** —el mismo objeto de
filtros que ya viaja en la URL del listado— y no traducidos a una gramática
propia: una segunda gramática para decir lo mismo acaba discrepando de la
primera, y entonces una vista guardada deja de dar lo que daba al crearla.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import Conflicto, NoEncontrado
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from services.metadata.modelos import VistaDeLista


def listar(db: Session, tenant_id: UUID, usuario_id: UUID, recurso: str) -> list[VistaDeLista]:
    """Las vistas que esta persona puede abrir en este listado.

    Las del tenant y las suyas, nunca las de otro. Ordenadas con las
    compartidas primero y por nombre dentro de cada grupo: el desplegable tiene
    que salir siempre igual, o la de arriba cambia de sitio entre visitas.
    """
    filas = (
        db.execute(
            select(VistaDeLista)
            .where(
                VistaDeLista.tenant_id == tenant_id,
                VistaDeLista.recurso == recurso,
                VistaDeLista.deleted_at.is_(None),
                or_(
                    VistaDeLista.propietario_id.is_(None),
                    VistaDeLista.propietario_id == usuario_id,
                ),
            )
            .order_by(VistaDeLista.propietario_id.is_(None).desc(), VistaDeLista.nombre)
        )
        .scalars()
        .all()
    )
    return list(filas)


def _suya_o_404(db: Session, tenant_id: UUID, usuario_id: UUID, vista_id: UUID) -> VistaDeLista:
    """La vista, si esta persona puede tocarla. Si no, 404 y no 403.

    404 y no 403 a propósito: un 403 sobre un identificador confirma que esa
    vista existe, y el nombre de la vista de otro ya dice algo —«Cuentas en
    riesgo de fuga» cuenta lo que esa persona está mirando.
    """
    vista = db.get(VistaDeLista, vista_id)
    if (
        vista is None
        or vista.deleted_at is not None
        or vista.tenant_id != tenant_id
        or (vista.propietario_id is not None and vista.propietario_id != usuario_id)
    ):
        raise NoEncontrado("No existe esa vista de lista", error_code="metadata.vista_no_existe")
    return vista


def crear(
    db: Session,
    *,
    tenant_id: UUID,
    usuario_id: UUID,
    recurso: str,
    nombre: str,
    filtros: dict[str, Any],
    columnas: list[str],
    orden: dict[str, Any] | None,
    compartida: bool,
    es_defecto: bool,
) -> VistaDeLista:
    propietario = None if compartida else usuario_id
    if db.execute(
        select(VistaDeLista.id).where(
            VistaDeLista.tenant_id == tenant_id,
            VistaDeLista.recurso == recurso,
            VistaDeLista.nombre == nombre,
            VistaDeLista.propietario_id.is_(None)
            if propietario is None
            else VistaDeLista.propietario_id == propietario,
            VistaDeLista.deleted_at.is_(None),
        )
    ).first():
        raise Conflicto(
            f"Ya tienes una vista llamada «{nombre}» en este listado",
            error_code="metadata.vista_duplicada",
        )
    vista = VistaDeLista(
        tenant_id=tenant_id,
        recurso=recurso,
        nombre=nombre,
        filtros=filtros,
        columnas=columnas,
        orden=orden,
        propietario_id=propietario,
        es_defecto=es_defecto,
    )
    db.add(vista)
    db.flush()
    if es_defecto:
        _solo_una_por_defecto(db, vista)
    return vista


def actualizar(
    db: Session,
    vista: VistaDeLista,
    cambios: dict[str, Any],
) -> VistaDeLista:
    for campo in ("nombre", "filtros", "columnas", "orden", "es_defecto"):
        if campo in cambios and cambios[campo] is not None:
            setattr(vista, campo, cambios[campo])
    db.flush()
    if vista.es_defecto:
        _solo_una_por_defecto(db, vista)
    return vista


def _solo_una_por_defecto(db: Session, vista: VistaDeLista) -> None:
    """Marcar una como la de entrada desmarca la anterior.

    Dos por defecto no es un estado válido: el listado abriría con la que
    saliera primero, y eso cambia entre consultas. Se resuelve al escribir y no
    al leer, porque al leer habría que elegir y esa elección sería silenciosa.
    """
    otras = (
        db.execute(
            select(VistaDeLista).where(
                VistaDeLista.tenant_id == vista.tenant_id,
                VistaDeLista.recurso == vista.recurso,
                VistaDeLista.id != vista.id,
                VistaDeLista.es_defecto.is_(True),
                VistaDeLista.deleted_at.is_(None),
                VistaDeLista.propietario_id.is_(None)
                if vista.propietario_id is None
                else VistaDeLista.propietario_id == vista.propietario_id,
            )
        )
        .scalars()
        .all()
    )
    for otra in otras:
        otra.es_defecto = False
    db.flush()
