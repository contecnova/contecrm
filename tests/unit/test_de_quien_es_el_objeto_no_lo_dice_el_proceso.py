"""De quién es un objeto no lo decide quién esté cargado (`CRM-06.02.01.04`).

Medido el 06-10-2026. `modelo_del_objeto` contesta con el registro **del
proceso**, y dos sitios lo usaban para preguntar otra cosa: «¿es mío?». Con un
servicio por proceso las dos preguntas dan lo mismo y por eso aguantó; con los
catorce dentro —la suite, o un despliegue de una sola pieza— el registro es la
unión de todos y la respuesta es que sí a todo.

Lo que costaba: la cola del móvil de `party` recibía una operación sobre una
`oportunidad`, que es de `sales`, y en vez de devolverla a la cola planificaba
aplicarla contra sus propios registros. Y el cuadre del rastro comparaba lo
vivo de otro servicio contra los hechos de este, que da diferencia en cada
campo y acusa de escritura a mano a quien no la hizo.

Lo que lo escondía: la prueba que lo cubría **pasaba por orden de carga**. Si
nadie había importado `sales` todavía, `oportunidad` no estaba en el registro y
salía verde sin haber recorrido la rama. Detrás de `test_ventas_por_http` caía.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest


def _cargar_los_dos() -> None:
    """A propósito: es la situación que se mide, no un efecto de otra prueba."""
    import services.party.main  # noqa: F401
    import services.sales.api  # noqa: F401


def test_el_dueno_sale_de_donde_esta_escrito_el_modelo() -> None:
    from crmcore.metamodelo import servicio_del_objeto

    _cargar_los_dos()
    assert servicio_del_objeto("oportunidad") == "sales"
    assert servicio_del_objeto("contacto") == "party"


def test_un_objeto_del_nucleo_es_de_quien_pregunte() -> None:
    """La papelera o el rastro de eventos los monta cada servicio con sus
    propias filas; tratarlos como ajenos dejaría a todos sin ellos."""
    from crmcore.metamodelo import es_de_este_servicio, servicio_del_objeto

    _cargar_los_dos()
    assert servicio_del_objeto("entrada_papelera") == ""
    assert es_de_este_servicio("entrada_papelera", "party")
    assert es_de_este_servicio("entrada_papelera", "sales")


def test_cargado_no_es_lo_mismo_que_propio() -> None:
    """Es la confusión entera, en una línea."""
    from crmcore.metamodelo import es_de_este_servicio, modelo_del_objeto

    _cargar_los_dos()
    assert modelo_del_objeto("oportunidad") is not None
    assert not es_de_este_servicio("oportunidad", "party")
    assert es_de_este_servicio("oportunidad", "sales")


def test_un_objeto_que_nadie_guarda_no_es_de_nadie() -> None:
    from crmcore.metamodelo import es_de_este_servicio

    assert not es_de_este_servicio("lo_que_no_existe", "party")


@pytest.mark.db
def test_el_cuadre_del_rastro_no_compara_lo_de_otro(db: Any, tenant_id: UUID) -> None:
    """Comparar lo vivo de `sales` contra los hechos de `party` da diferencia en
    cada campo, y eso en esta ruta significa «alguien escribió a mano»."""
    from crmcore.errors import NoEncontrado
    from crmcore.http.rastro_router import crear_router_rastro

    _cargar_los_dos()

    class _P:
        tenant_id_ = tenant_id

        def __init__(self) -> None:
            self.tenant_id = tenant_id
            self.id = uuid4()

    router = crear_router_rastro("party")
    fn = next(r.endpoint for r in router.routes if getattr(r, "path", "").endswith("/cuadra"))

    with pytest.raises(NoEncontrado) as fallo:
        fn("oportunidad", uuid4(), db, _P())
    assert fallo.value.error_code == "rastro.objeto_de_otro_servicio"
