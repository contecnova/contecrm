"""Aplicar la compartición en un listado (CRM-00.05.02.04).

Las reglas existían, se explicaban y se podían consultar para un registro
concreto. Lo que no pasaba es lo único que el usuario nota: **`GET /accounts`
seguía enseñándolo todo**.

Esta función es el puente, y se usa igual en todos los listados:

    consulta = aplicar_visibilidad(consulta, Cuenta, db=db, principal=p, objeto="cuenta")

Tres decisiones:

**Filtra en SQL, no fila a fila.** Comprobar registro a registro rompe la
paginación —pides veinte y recibes siete— y hace una consulta por fila. Con un
`WHERE` la paginación por cursor sigue siendo estable y el coste es una
subconsulta.

**Quien puede administrar el objeto no se filtra.** Un administrador que ve
media lista no puede administrar nada, y la alternativa —darle una compartición
sobre todo— convierte la auditoría en ruido. Se decide por permiso explícito, no
por rol, para que un tenant pueda montar su propia jerarquía.

**Si algo falla, se filtra.** Un error resolviendo la visibilidad devuelve una
consulta que no encuentra nada, no una sin filtrar. Ante la duda, en visibilidad,
no se enseña.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Select, false
from sqlalchemy.orm import Session

from crmcore.logging import get_logger

logger = get_logger(__name__)


def aplicar_visibilidad(
    consulta: Select,
    modelo: type,
    *,
    db: Session,
    principal: Any,
    objeto: str,
    permiso_ver_todo: str = "",
) -> Select:
    """Añade a la consulta el filtro de compartición y el de las políticas ABAC.

    Los dos, y en este orden, porque no son lo mismo y se comportan al revés:

      * La **compartición** dice a quién se le ha dado acceso. Cuando una vía no
        se puede traducir, comparte de más: no aplicarla deja de enseñar algo
        que sí se podía ver.
      * El **ABAC** dice a quién se le quita. Cuando una condición no se puede
        traducir, deniega: no aplicarla enseñaría lo que no se debe.

    Y el ABAC se aplica **también al administrador del objeto**. La
    compartición no —quien administra tiene que ver el maestro entero o no puede
    administrar nada—, pero una política de «esta unidad de negocio no ve las
    oportunidades de la otra» dejaría de servir para nada si el administrador
    fuera la excepción: es exactamente a quien se le pone.
    """
    from crmcore.authz.comparticion import filtro_visibilidad
    from crmcore.authz.decision import filtro as filtro_abac

    if principal is None or principal.id is None or principal.tenant_id is None:
        # Sin identidad no hay compartición que aplicar, y tampoco hay nada que
        # enseñar: quien llame sin autenticar no debería haber llegado aquí.
        return consulta.where(false())

    try:
        politica = filtro_abac(db, modelo, objeto=objeto, tenant_id=principal.tenant_id)
    except Exception as exc:  # noqa: BLE001 — ante la duda, no se enseña
        logger.error("abac.fallo_al_filtrar", objeto=objeto, error=str(exc)[:300])
        return consulta.where(false())
    if politica is not None:
        consulta = consulta.where(politica)

    if principal.es_admin_plataforma or principal.tiene(permiso_ver_todo or f"{objeto}:admin"):
        return consulta

    try:
        filtro = filtro_visibilidad(
            db,
            modelo,
            tenant_id=principal.tenant_id,
            usuario_id=principal.id,
            objeto=objeto,
            subordinados=subordinados_de(db, principal),
            equipos=equipos_de(db, principal, objeto),
            roles=principal.roles,
            business_unit_id=principal.business_unit_id,
        )
    except Exception as exc:  # noqa: BLE001 — ante la duda, no se enseña
        logger.error("visibilidad.fallo_al_resolver", objeto=objeto, error=str(exc)[:300])
        return consulta.where(false())

    return consulta if filtro is None else consulta.where(filtro)


def subordinados_de(db: Session, principal: Any) -> set[UUID]:
    """Quién depende de este usuario, directa o indirectamente.

    La jerarquía de mando es `superior_id` en la membresía del tenant, y la
    resuelve quien tenga esa tabla. En los servicios que no la tienen —`party`,
    `sales`— el conjunto llega vacío y la vía por jerarquía no aplica.

    Es una limitación real y se dice: hasta que la membresía se replique o se
    consulte, un responsable **no** ve por jerarquía los registros de su equipo
    en esos servicios. Ve los suyos, los de su equipo de cuenta y lo que le
    compartan. El hueco está anotado en el manual y no escondido aquí.
    """
    from crmcore.authz.comparticion import ReglaComparticion  # noqa: F401 — ancla el módulo

    resolver = _RESOLUTORES.get("subordinados")
    return resolver(db, principal) if resolver else set()


def equipos_de(db: Session, principal: Any, objeto: str) -> set[UUID]:
    """Registros en cuyos equipos está este usuario.

    Igual que arriba: lo resuelve el servicio que tiene la tabla de equipos, y
    se registra al arrancar. Sin resolutor, la vía no aplica.
    """
    resolver = _RESOLUTORES.get("equipos")
    return resolver(db, principal, objeto) if resolver else set()


# Resolutores que cada servicio registra para las vías que sabe calcular. Es el
# mismo patrón que los componentes de la página de estado, y por la misma razón:
# la jerarquía de mando y los equipos de cuenta viven en tablas de servicios
# concretos, y el núcleo no puede leerlas.
_RESOLUTORES: dict[str, Any] = {}


def registrar_resolutor(clave: str, fn: Any) -> None:
    """Declara cómo se resuelve una vía en este servicio.

    `clave` es `subordinados` o `equipos`. Registrar el de un servicio en otro
    no tiene sentido y no se impide aquí: cada uno registra el suyo al
    importarse, y un servicio que no lo haga sencillamente no aplica esa vía.
    """
    _RESOLUTORES[clave] = fn


def resolutores_registrados() -> list[str]:
    return sorted(_RESOLUTORES)
