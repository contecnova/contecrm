"""La correspondencia tenant → organización de contecintelligence (CRM-05.01.04.01).

Es una tabla de PLATAFORMA en un servicio con RLS por tenant, y esa combinación
tiene una trampa que solo se ve ejecutándola: cada fila habla de OTRO tenant, así
que con la sesión del que llama la política no deja ni escribirla ni leerla.

Con el enlace levantado de verdad (24-09-2026) salieron las dos caras:

  * `PUT` daba **500**. Postgres contesta `new row violates row-level security
    policy` al insertar la fila de otro tenant, y salía como error interno: desde
    fuera parecía una avería del servicio, no una ruta que nunca había
    funcionado para nadie que no fuera el tenant de quien llamaba.
  * `GET` era peor, porque no fallaba: devolvía **solo la fila del propio
    tenant**. Una consola de plataforma con tres clientes enseñaba uno y no
    decía que faltaban dos.

Lo que se fija aquí es que las dos rutas usan sesión de sistema.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from services.analytics.api import AsignarOrganizacion, asignar_organizacion, listar_organizaciones


@pytest.fixture
def otros_tenants() -> list[UUID]:
    """Tres tenants que NO son el de la prueba: el caso que rompía."""
    return [uuid4(), uuid4(), uuid4()]


def test_se_asigna_la_organizacion_de_un_tenant_que_no_es_el_que_llama(
    db: Any, otros_tenants: list[UUID]
) -> None:
    """Es el caso normal, no uno raro: quien asigna es plataforma, nunca el tenant."""
    ajeno = otros_tenants[0]
    salida = asignar_organizacion(
        AsignarOrganizacion(tenant_id=ajeno, organizacion="cliente-uno"), _=None
    )
    assert salida.tenant_id == ajeno
    assert salida.organizacion == "cliente-uno"
    assert salida.estado == "pendiente"


def test_el_listado_de_plataforma_trae_TODOS_los_tenants(
    db: Any, otros_tenants: list[UUID]
) -> None:
    """Un listado incompleto aquí no se nota, y esa es exactamente la avería.

    Sin sesión de sistema devolvía las filas del tenant de quien llama —cero, en
    una tabla de plataforma— sin error y sin decir que había más.
    """
    for i, tenant in enumerate(otros_tenants):
        asignar_organizacion(
            AsignarOrganizacion(tenant_id=tenant, organizacion=f"cliente-{i}"), _=None
        )

    vistas = {o.tenant_id for o in listar_organizaciones(_=None)}
    assert set(otros_tenants) <= vistas, "la consola de plataforma tiene que verlos todos"


def test_reasignar_cambia_la_organizacion_y_vuelve_a_pendiente(
    db: Any, otros_tenants: list[UUID]
) -> None:
    """Cambiarla deja las preguntas guardadas apuntando a otros datos.

    Se permite —hace falta al migrar— pero el estado vuelve a `pendiente` para
    que nadie dé por verificado un enlace que ya no es el mismo.
    """
    ajeno = otros_tenants[0]
    asignar_organizacion(AsignarOrganizacion(tenant_id=ajeno, organizacion="antes"), _=None)
    despues = asignar_organizacion(
        AsignarOrganizacion(tenant_id=ajeno, organizacion="despues"), _=None
    )
    assert despues.organizacion == "despues"
    assert despues.estado == "pendiente"
