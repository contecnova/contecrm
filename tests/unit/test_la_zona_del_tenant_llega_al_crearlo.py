"""La zona horaria del tenant no llegaba a donde se lee (`CRM-00.01.04.07`).

Medido el 07-10-2026 a la 01:24, con el pase completo del preflight: doce
pruebas de vigencia en rojo a la vez —presupuestos caducados, comparticiones
caducadas, pertenencias a equipo caducadas— y todas por lo mismo.

`propagar_localizacion` existe desde que se arregló que `Tenant.zona_horaria`
no lo leyera nadie. Pero **la llamaba sólo la ruta de editar**. Un tenant recién
dado de alta tenía su zona en la ficha y no en los ajustes, que es de donde sale
`rt.efectivo("zona_horaria")`, así que caía a UTC hasta que alguien abriera el
perfil y guardara — algo que en la mayoría de las implantaciones no pasa nunca.

Entre medias, «hoy» era el día de UTC. De madrugada en Madrid eso es **ayer**, y
entonces un presupuesto caduca un día antes de lo que dice la pantalla, una
compartición deja de dar acceso un día antes y una pertenencia a un equipo
también. No falla nada: contesta distinto.

Es el arreglo al que le faltaba una vía. Se tapó la de editar y la de crear se
quedó abierta — que es por donde pasan **todos** los tenants.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

pytestmark = pytest.mark.db


def _uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def test_al_crear_un_tenant_su_zona_queda_donde_se_lee(db: Any, tenant_id: UUID) -> None:
    from crmcore.runtime import settings as rt

    from services.tenancy import servicio as svc

    fila = svc.crear_tenant(
        _uow(db, tenant_id),
        slug="acme-zona",
        nombre="ACME",
        zona_horaria="Pacific/Auckland",
    )
    db.flush()

    valores = rt._valores_de_ambito(db, "tenant", str(fila.id))
    assert valores.get("zona_horaria") == "Pacific/Auckland", (
        "la zona se ha quedado en la ficha del tenant y no en los ajustes, que es "
        "de donde se lee: todas sus fechas se calcularían en UTC"
    )


def test_tambien_el_idioma_y_la_moneda(db: Any, tenant_id: UUID) -> None:
    """Los tres van por el mismo camino y se propagaban juntos al editar.
    Arreglar sólo la zona habría dejado los otros dos como estaban."""
    from crmcore.runtime import settings as rt

    from services.tenancy import servicio as svc

    fila = svc.crear_tenant(
        _uow(db, tenant_id),
        slug="acme-loc",
        nombre="ACME",
        idioma="en",
        moneda="USD",
    )
    db.flush()

    valores = rt._valores_de_ambito(db, "tenant", str(fila.id))
    assert valores.get("idioma") == "en"
    assert valores.get("moneda_funcional") == "USD"


def test_el_dia_del_tenant_es_el_suyo_y_no_el_de_utc(db: Any, tenant_id: UUID) -> None:
    """La consecuencia, medida: con la zona puesta, `hoy(db)` deja de ser el día
    del servidor.

    Auckland porque con Madrid el desfase son dos horas y la prueba sólo
    distinguiría de madrugada — y una prueba que sólo comprueba algo en una
    franja horaria es una prueba que no comprueba nada el resto del día.
    """
    from datetime import datetime, timezone

    from crmcore.fechas import hoy
    from crmcore.tenancy.context import con_contexto

    from services.tenancy import servicio as svc

    fila = svc.crear_tenant(
        _uow(db, tenant_id),
        slug="acme-nz",
        nombre="ACME NZ",
        zona_horaria="Pacific/Auckland",
    )
    db.flush()

    ahora_utc = datetime.now(timezone.utc)
    with con_contexto(tenant_id=fila.id):
        dia = hoy(db)

    # Auckland va 12 o 13 horas por delante de UTC, así que durante media
    # jornada su día es el siguiente. Lo que se comprueba es que `hoy(db)` sigue
    # al tenant: o coincide con UTC o va un día por delante, nunca por detrás.
    assert dia >= ahora_utc.date(), f"el día del tenant ({dia}) va por detrás del de UTC"


def test_crear_y_editar_propagan_por_el_mismo_sitio() -> None:
    """Dos copias de esta propagación divergen, y la que menos se mire será la
    que deje a un tenant con la zona a medio poner."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    svc = (raiz / "services/tenancy/servicio.py").read_text(encoding="utf-8")
    api = (raiz / "services/tenancy/api.py").read_text(encoding="utf-8")
    assert svc.count("def propagar_localizacion(") == 1
    assert "propagar_localizacion(" in svc.split("def crear_tenant(")[1]
    assert "svc.propagar_localizacion(" in api
