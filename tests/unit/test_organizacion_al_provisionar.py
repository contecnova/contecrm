"""Un tenant nuevo nace con su organización en contecintelligence (`CRM-05.01.04.02`).

La tabla existía, la ruta para asignarla a mano existía, y **no la rellenaba
nadie**. Todo tenant nuevo nacía sin correspondencia, y la primera pregunta que
alguien hiciera contra la explotación del dato se encontraba «este tenant no
tiene organización asignada». Un paso manual que hay que recordar es un paso que
se olvida — y esta noche eso ya ha pasado cinco veces en este repositorio.

La decisión que había que tomar y aquí se comprueba: **la organización lleva el
`slug`, no el nombre comercial.** El `slug` es inmutable por diseño —`EditarTenant`
no lo admite— y eso es justo lo que hace falta al otro lado, donde
contecintelligence solo acepta nombrar organizaciones que tenga mapeadas y donde
no podemos renombrar nada. El `nombre` se corrige con una ruta que existe para
eso, y cada corrección dejaría la correspondencia apuntando a algo que allí ya no
se llama así.

Y de ahí sale la otra mitad: **el renombrado no se propaga porque no hay nada que
propagar.**
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


def _mensaje(tenant_id: UUID, *, slug: str = "acme", tipo: str = "tenant.provisioned") -> Any:
    """El sobre tal como lo emite `tenancy`, con sus mismos campos."""
    return SimpleNamespace(
        tipo=tipo,
        tenant_id=str(tenant_id),
        data={"tenant_id": str(tenant_id), "slug": slug, "plan": "estandar", "region": "eu"},
    )


def _organizacion(db: Any, tenant_id: UUID) -> Any:
    from sqlalchemy import select

    from services.analytics.modelos import OrganizacionExterna

    # SE EXPIRA ANTES DE LEER. El consumidor escribe en SU propia unidad de
    # trabajo, y sin esto la sesión de la prueba devuelve el objeto que ya tenía
    # en memoria en vez de lo que hay en la base: la comprobación de que una
    # reentrega no pisa lo anterior pasaba **con la avería puesta**, porque
    # estaba mirando su propia copia.
    db.expire_all()
    return db.execute(
        select(OrganizacionExterna).where(OrganizacionExterna.tenant_id == tenant_id)
    ).scalar_one_or_none()


async def test_al_provisionar_se_crea_la_correspondencia(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Esta es la avería: antes no la creaba nadie."""
    from services.analytics.fuente import consumir_tenant_provisionado

    assert _organizacion(db, tenant_id) is None

    await consumir_tenant_provisionado(_mensaje(tenant_id, slug="acme"))

    fila = _organizacion(db, tenant_id)
    assert fila is not None, "el tenant ha nacido sin organización: la explotación no funcionará"
    assert fila.organizacion == "acme"
    # Pendiente y no activa: que exista la correspondencia no significa que al
    # otro lado la conozcan. Darla por activa sin verificarla haría que el
    # primer fallo apareciera como «no hay datos» en vez de «falta darla de alta».
    assert fila.estado == "pendiente"


async def test_lleva_el_slug_y_no_el_nombre_comercial(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El nombre comercial se corrige; el `slug` no se puede cambiar.

    Si la organización llevara el nombre, cada errata corregida dejaría la
    correspondencia apuntando a algo que al otro lado ya no se llama así, y allí
    no podemos renombrar nada.
    """
    from services.analytics.fuente import consumir_tenant_provisionado

    sobre = _mensaje(tenant_id, slug="acme-industrial")
    # El nombre comercial viaja en el evento de `tenancy` en otros casos; aquí
    # se pone a propósito para comprobar que NO es el que se usa.
    sobre.data["nombre"] = "ACME Industrial, S.A."

    await consumir_tenant_provisionado(sobre)

    assert _organizacion(db, tenant_id).organizacion == "acme-industrial"


async def test_una_segunda_entrega_no_pisa_lo_que_ya_estaba(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La entrega es al menos una vez.

    Una reentrega no puede devolver a «pendiente» una organización que lleva
    meses verificada: el panel diría que hay algo por hacer y no lo hay, y quien
    lo mire dos veces deja de mirarlo.
    """
    from services.analytics.fuente import consumir_tenant_provisionado

    await consumir_tenant_provisionado(_mensaje(tenant_id, slug="acme"))
    fila = _organizacion(db, tenant_id)
    fila.estado = "activa"
    fila.organizacion = "acme"
    db.flush()

    await consumir_tenant_provisionado(_mensaje(tenant_id, slug="acme"))

    fila = _organizacion(db, tenant_id)
    assert fila.estado == "activa", "una reentrega ha devuelto la organización a pendiente"


async def test_un_evento_sin_slug_no_inventa_un_nombre(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Inventarlo —del identificador, por ejemplo— crearía allí una organización
    que no existe y que nadie sabría de dónde salió."""
    from services.analytics.fuente import consumir_tenant_provisionado

    sobre = _mensaje(tenant_id)
    sobre.data["slug"] = ""

    await consumir_tenant_provisionado(sobre)

    assert _organizacion(db, tenant_id) is None


async def test_otro_evento_no_crea_nada(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """El consumidor mira el tipo: suscrito a uno, no se dispara con otro."""
    from services.analytics.fuente import consumir_tenant_provisionado

    await consumir_tenant_provisionado(_mensaje(tenant_id, tipo="tenant.suspendido"))

    assert _organizacion(db, tenant_id) is None


async def test_la_correspondencia_es_de_su_tenant_y_no_de_otro(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Dos tenants provisionados no pueden acabar compartiendo organización: al
    otro lado eso son los datos de una empresa en el informe de otra."""
    from services.analytics.fuente import consumir_tenant_provisionado

    otro = uuid4()
    await consumir_tenant_provisionado(_mensaje(tenant_id, slug="acme"))
    await consumir_tenant_provisionado(_mensaje(otro, slug="beta"))

    assert _organizacion(db, tenant_id).organizacion == "acme"
    assert _organizacion(db, otro).organizacion == "beta"


def test_el_servicio_esta_suscrito_al_alta_de_tenant() -> None:
    """Lo que faltaba no era el consumidor: era que alguien lo enchufara.

    Si se quita esta línea, los tenants nuevos vuelven a nacer sin organización
    y **nada falla**: los que ya la tienen siguen funcionando, y el problema
    aparece meses después con un cliente nuevo delante.
    """
    import inspect

    from services.analytics import main

    fuente = inspect.getsource(main)
    assert "consumir_tenant_provisionado" in fuente and "TENANT_PROVISIONADO" in fuente, (
        "analytics ya no consume el alta de tenant: los nuevos nacerán sin "
        "organización en contecintelligence y nadie lo notará"
    )


def test_el_slug_sigue_sin_poderse_cambiar() -> None:
    """De esto depende la decisión entera.

    Si algún día `EditarTenant` admitiera `slug`, la organización dejaría de ser
    estable y habría que decidir otra vez: o se propaga el cambio —y al otro
    lado no podemos renombrar— o la correspondencia se rompe en silencio.
    """
    from services.tenancy.api import EditarTenant

    assert "slug" not in EditarTenant.model_fields, (
        "el slug ha pasado a ser editable: la organización de contecintelligence "
        "se apoya en que no lo sea. Hay que decidir de nuevo antes de permitirlo."
    )
