"""Trazabilidad de origen de los leads (CRM-01.01.03.06).

Lo que estas pruebas defienden es una sola idea: **el primer toque no se pisa
nunca**. Es el dato que explica qué campaña descubrió al cliente, y el que
desaparece en cuanto el sistema guarda un solo origen — porque la última visita
antes de convertir casi siempre es «buscó nuestro nombre», y entonces todo el
mérito se lo lleva la marca.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest

from services.sales import origen as org
from services.sales.modelos import Lead


def _lead(db: Any, tenant_id: UUID, **extra: Any) -> Lead:
    extra.setdefault("estado", "nuevo")
    lead = Lead(tenant_id=tenant_id, **extra)
    db.add(lead)
    db.flush()
    return lead


# ── Normalización de parámetros ───────────────────────────────────────────


def test_admite_los_parametros_con_prefijo_y_sin_el() -> None:
    """Rechazar la forma sin prefijo sería perder el dato entero por un detalle
    de cómo lo manda el formulario del cliente."""
    con = org.normalizar({"utm_source": "google", "utm_medium": "cpc"})
    sin = org.normalizar({"source": "google", "medium": "cpc"})
    assert con == sin == {"fuente": "google", "medio": "cpc"}


def test_lo_que_no_reconoce_no_lo_tira() -> None:
    """Ahí van los identificadores de clic de cualquier red, incluidas las que
    no existían cuando se escribió esto."""
    campos = org.normalizar({"utm_source": "x", "gclid": "abc", "red_nueva_id": "999"})
    assert campos["fuente"] == "x"
    assert campos["identificadores_clic"] == {"gclid": "abc", "red_nueva_id": "999"}


def test_los_valores_vacios_no_ensucian_el_toque() -> None:
    assert org.normalizar({"utm_source": "", "utm_medium": None, "utm_campaign": "obra"}) == {
        "campana": "obra"
    }


# ── Toques ────────────────────────────────────────────────────────────────


def test_un_toque_necesita_lead_o_visitante(db: Any, tenant_id: UUID) -> None:
    with pytest.raises(ValueError):
        org.registrar_toque(db, tenant_id=tenant_id, utm_source="google")


def test_los_toques_anonimos_se_adoptan_al_identificarse(db: Any, tenant_id: UUID) -> None:
    """Es el único momento en que el recorrido anterior se puede recuperar: un
    minuto después ya se perdió, porque nadie vuelve a mirar los huérfanos."""
    org.registrar_toque(
        db,
        tenant_id=tenant_id,
        visitante_id="v-1",
        utm_source="google",
        utm_medium="cpc",
        utm_campaign="obra-2026",
    )
    org.registrar_toque(db, tenant_id=tenant_id, visitante_id="v-1", utm_source="newsletter")

    lead = _lead(db, tenant_id, utm={"visitante_id": "v-1", "utm_source": "directo"})
    org.registrar_alta(db, lead, tenant_id=tenant_id)
    db.flush()

    recorrido = org.recorrido(db, tenant_id=tenant_id, lead_id=lead.id)
    assert [t["fuente"] for t in recorrido] == ["google", "newsletter", "directo"]


def test_el_primer_toque_es_el_que_descubrio_al_cliente(db: Any, tenant_id: UUID) -> None:
    org.registrar_toque(
        db, tenant_id=tenant_id, visitante_id="v-2", utm_source="google", utm_campaign="obra-2026"
    )
    lead = _lead(db, tenant_id, utm={"visitante_id": "v-2", "utm_source": "marca"})
    org.registrar_alta(db, lead, tenant_id=tenant_id)

    assert lead.primer_toque["campana"] == "obra-2026"
    assert lead.ultimo_toque["fuente"] == "marca"
    # Y el `origen` del lead sale del PRIMERO: es una pregunta sobre de dónde
    # salió, no sobre lo último que hizo.
    assert lead.origen == "google"


def test_el_primer_toque_no_se_reescribe_nunca(db: Any, tenant_id: UUID) -> None:
    lead = _lead(db, tenant_id, utm={"visitante_id": "v-3", "utm_source": "primera"})
    org.registrar_alta(db, lead, tenant_id=tenant_id)
    primero = dict(lead.primer_toque)

    org.registrar_toque(db, tenant_id=tenant_id, lead_id=lead.id, utm_source="posterior")
    org.fijar_primer_y_ultimo(db, lead, tenant_id=tenant_id)

    assert lead.primer_toque == primero
    assert lead.ultimo_toque["fuente"] == "posterior"


def test_el_alta_no_duplica_el_toque_que_ya_mando_el_cliente(db: Any, tenant_id: UUID) -> None:
    """Sería el mismo hecho contado dos veces, y la campaña aparecería con el
    doble de leads de los que trajo."""
    org.registrar_toque(
        db,
        tenant_id=tenant_id,
        visitante_id="v-4",
        utm_source="google",
        utm_medium="cpc",
        utm_campaign="obra",
    )
    lead = _lead(
        db,
        tenant_id,
        utm={
            "visitante_id": "v-4",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "obra",
        },
    )

    assert org.registrar_alta(db, lead, tenant_id=tenant_id) == 1


def test_fuera_de_la_ventana_los_toques_no_se_adoptan(db: Any, tenant_id: UUID) -> None:
    viejo = datetime.now(timezone.utc) - timedelta(days=400)
    org.registrar_toque(
        db, tenant_id=tenant_id, visitante_id="v-5", ocurrio_at=viejo, utm_source="prehistoria"
    )
    lead = _lead(db, tenant_id, utm={"visitante_id": "v-5", "utm_source": "hoy"})
    org.registrar_alta(db, lead, tenant_id=tenant_id)

    fuentes = [t["fuente"] for t in org.recorrido(db, tenant_id=tenant_id, lead_id=lead.id)]
    assert fuentes == ["hoy"]


def test_un_lead_sin_ningun_dato_de_origen_no_revienta(db: Any, tenant_id: UUID) -> None:
    """Un lead dado de alta a mano por un comercial no trae utm, y eso es normal."""
    lead = _lead(db, tenant_id, empresa="Alta manual")
    assert org.registrar_alta(db, lead, tenant_id=tenant_id) == 0
    assert lead.primer_toque == {}


def test_el_recorrido_va_del_mas_antiguo_al_mas_reciente(db: Any, tenant_id: UUID) -> None:
    lead = _lead(db, tenant_id)
    ahora = datetime.now(timezone.utc)
    for fuente in ("tercera", "primera", "segunda"):
        org.registrar_toque(
            db,
            tenant_id=tenant_id,
            lead_id=lead.id,
            utm_source=fuente,
            ocurrio_at=ahora
            + timedelta(minutes={"primera": 0, "segunda": 1, "tercera": 2}[fuente]),
        )
    assert [t["fuente"] for t in org.recorrido(db, tenant_id=tenant_id, lead_id=lead.id)] == [
        "primera",
        "segunda",
        "tercera",
    ]


def test_por_campana_cuenta_primer_y_ultimo_toque_por_separado(db: Any, tenant_id: UUID) -> None:
    """Es lo que hace visible que la marca se lleva los cierres y otra campaña
    trajo a la gente."""
    for _ in range(3):
        org.registrar_toque(
            db, tenant_id=tenant_id, visitante_id="v", utm_campaign="descubrimiento"
        )
        lead = _lead(db, tenant_id, utm={"visitante_id": "v", "utm_campaign": "marca"})
        org.registrar_alta(db, lead, tenant_id=tenant_id)
        db.flush()

    filas = {f["campana"]: f for f in org.por_campana(db, tenant_id=tenant_id)}
    assert filas["descubrimiento"]["primer_toque"] == 3
    assert filas["descubrimiento"]["ultimo_toque"] == 0
    assert filas["marca"]["ultimo_toque"] == 3
    assert filas["marca"]["primer_toque"] == 0


def test_crear_un_lead_deja_su_origen_resuelto(db: Any, tenant_id: UUID) -> None:
    """La integración: `crear_lead` registra el origen ANTES de enrutar, porque
    una regla puede repartir por campaña."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.sales import servicio as svc

    org.registrar_toque(db, tenant_id=tenant_id, visitante_id="v-6", utm_campaign="feria")
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)

    lead = svc.crear_lead(uow, empresa="Acme", utm={"visitante_id": "v-6"})

    assert lead.primer_toque["campana"] == "feria"
