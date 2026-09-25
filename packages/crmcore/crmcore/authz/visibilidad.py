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

    # Una credencial de MÁQUINA no es una persona: no posee registros, no está en
    # ningún equipo y nadie le ha compartido nada, así que el filtro de
    # compartición la dejaba viendo CERO filas. Una integración con permiso de
    # lectura que no lee nada no es una integración — y lo peor es que no falla:
    # devuelve una lista vacía, que es una respuesta legítima. Así estaba el
    # almacén analítico, cargando cero filas sin un solo error.
    #
    # La compartición responde a «¿a qué personas se les ha dado acceso?», y esa
    # pregunta no tiene sentido para algo que representa al TENANT entero. Así
    # que para un principal de servicio no se aplica.
    #
    # Lo que SÍ se le sigue aplicando, y va justo arriba, es el ABAC: las
    # políticas de dato —«esta unidad de negocio no ve las oportunidades de la
    # otra»— son del dato, no de la persona, y una integración que las esquivara
    # sería la puerta de atrás de todas ellas.
    #
    # Y lo que la acota es lo que se le dio al crearla: su tenant, su rol de
    # solo lectura y sus alcances. Nada de esto le abre otro tenant.
    if getattr(principal, "tipo", "") == "servicio":
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

    salida: set[UUID] = set()
    for resolver in _RESOLUTORES.get("subordinados", []):
        salida |= set(resolver(db, principal))
    return salida


def equipos_de(db: Session, principal: Any, objeto: str) -> set[UUID]:
    """Registros en cuyos equipos está este usuario.

    Igual que arriba: lo resuelve el servicio que tiene la tabla de equipos, y
    se registra al arrancar. Sin resolutor, la vía no aplica.
    """
    salida: set[UUID] = set()
    for resolver in _RESOLUTORES.get("equipos", []):
        # Cada resolutor devuelve {} para los objetos que no son suyos: el de
        # `party` sabe de cuentas y el de `sales` de oportunidades.
        salida |= set(resolver(db, principal, objeto))
    return salida


# Resolutores que cada servicio registra para las vías que sabe calcular. Es el
# mismo patrón que los componentes de la página de estado, y por la misma razón:
# la jerarquía de mando y los equipos de cuenta viven en tablas de servicios
# concretos, y el núcleo no puede leerlas.
#
# Es una lista por clave y no uno solo, y esa diferencia importa: `party` resuelve
# «equipos» para cuentas y `sales` para oportunidades. Con un único resolutor por
# clave, el último en importarse **borraba al anterior en silencio** —la vía por
# equipo de cuenta dejaba de aplicar sin que nada fallara, que es exactamente el
# tipo de error que enseña de menos y no se nota—. En producción cada servicio va
# en su proceso y no se cruzaban; en cualquier proceso que cargue dos, sí.
_RESOLUTORES: dict[str, list[Any]] = {}


def registrar_resolutor(clave: str, fn: Any) -> None:
    """Declara cómo se resuelve una vía en este servicio.

    `clave` es `subordinados` o `equipos`. Se **añade**, no se sustituye: dos
    servicios pueden resolver la misma vía para objetos distintos, y cada uno
    devuelve vacío para lo que no es suyo.

    Registrar dos veces la misma función no duplica nada: el módulo que la
    registra puede importarse más de una vez.
    """
    registrados = _RESOLUTORES.setdefault(clave, [])
    if fn not in registrados:
        registrados.append(fn)


def resolutores_registrados() -> list[str]:
    return sorted(_RESOLUTORES)
