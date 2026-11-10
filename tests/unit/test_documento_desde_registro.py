"""El documento generado desde la ficha del registro (CRM-06.01.01.06).

Medido el 10-11-2026: los datos se escribían a mano, salía texto y guardarlo
dependía de contecmind. Estas pruebas fijan las tres cosas que lo cierran: los
datos salen del registro y se dice qué falta, sale un PDF de verdad que queda
como adjunto, y un corpus caído no tumba lo que ya está guardado.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import ErrorDependencia
from crmcore.i18n import Localizacion

from services.integration import documento_registro as dr

CUENTA = uuid4()
OPORTUNIDAD = uuid4()


def _plantilla(cuerpo: str, **extra: Any) -> Any:
    return SimpleNamespace(cuerpo=cuerpo, mapeo=extra.get("mapeo", {}))


def test_cada_marcador_sale_del_registro_y_lo_que_falta_se_dice() -> None:
    contexto = {
        "registro": {"nombre": "Banco de pruebas", "importe": "45000.00", "moneda": "EUR"},
        "contacto": {"nombre_completo": "Ana Ruiz"},
        "cuenta": {"nombre": "Ficosa"},
    }
    plantilla = _plantilla(
        "{{contacto}} · {{cliente}} · {{importe}} · {{oportunidad}} · {{plazo}}",
        mapeo={"cliente": "cuenta.nombre", "oportunidad": "registro.nombre"},
    )
    salida = {
        r["marcador"]: r
        for r in dr.resolver(
            plantilla,
            contexto,
            a_mano={"oportunidad": "Escrito a mano"},
            loc=Localizacion(idioma="es"),
            fuentes={},
        )
    }
    # El registro entero toma su nombre; el mapeo manda; el importe lleva su
    # moneda al lado y sale como importe; lo escrito a mano gana.
    assert salida["contacto"]["valor"] == "Ana Ruiz"
    assert salida["cliente"]["valor"] == "Ficosa"
    assert salida["importe"]["valor"] == "45.000,00 €"
    assert salida["oportunidad"] == {
        "marcador": "oportunidad",
        "valor": "Escrito a mano",
        "origen": "a_mano",
        "campo": "",
    }
    assert salida["plazo"]["origen"] == "falta"


def _doble(respuestas: dict[str, dict[str, Any]], llamadas: list[dict[str, Any]]) -> Any:
    def http(**kw: Any) -> dict[str, Any]:
        llamadas.append(kw)
        for prefijo, respuesta in respuestas.items():
            if kw["ruta"].startswith(prefijo):
                return respuesta
        return {"estado": 404, "datos": {"detail": "no"}}

    return http


@pytest.fixture
def principal(tenant_id: UUID) -> Any:
    return SimpleNamespace(
        id=uuid4(), tenant_id=tenant_id, permisos=frozenset(), roles=frozenset(), tipo="usuario"
    )


@pytest.mark.db
def test_genera_el_pdf_lo_guarda_como_adjunto_y_un_corpus_caido_no_lo_tumba(
    db: Any, contexto_tenant: UUID, principal: Any
) -> None:
    from crmcore.documental.plantillas import DocumentoGenerado, guardar_plantilla

    guardar_plantilla(
        db,
        tenant_id=contexto_tenant,
        clave="oferta",
        nombre="Oferta",
        cuerpo="Estimado/a {{contacto}}:\n\nOferta para {{oportunidad}} por {{importe}}.",
    )
    adjunto = uuid4()
    llamadas: list[dict[str, Any]] = []
    dr._registrar_http(
        _doble(
            {
                f"/api/v1/opportunities/{OPORTUNIDAD}/lineas": {
                    "estado": 200,
                    "datos": [{"descripcion": "Banco", "cantidad": "1", "total": "45000.00"}],
                },
                f"/api/v1/opportunities/{OPORTUNIDAD}": {
                    "estado": 200,
                    "datos": {
                        "id": str(OPORTUNIDAD),
                        "nombre": "Banco de pruebas",
                        "importe": "45000.00",
                        "moneda": "EUR",
                        "cuenta_id": str(CUENTA),
                    },
                },
                f"/api/v1/accounts/{CUENTA}": {
                    "estado": 200,
                    "datos": {"id": str(CUENTA), "nombre": "Ficosa"},
                },
                "/api/v1/contacts?cuenta_id=": {
                    "estado": 200,
                    "datos": {"items": [{"nombre_completo": "Ana Ruiz"}]},
                },
                "/api/v1/adjuntos/oportunidad": {
                    "estado": 201,
                    "datos": {"id": str(adjunto), "nombre": "oferta.pdf"},
                },
                "/api/v1/documentos/": {
                    "estado": 503,
                    "datos": {"detail": "El gestor documental no responde"},
                },
            },
            llamadas,
        )
    )
    try:
        salida = dr.generar(
            db, principal, clave="oferta", objeto="oportunidad", objeto_id=OPORTUNIDAD
        )
    finally:
        dr._registrar_http(None)

    subida = next(c for c in llamadas if c["ruta"] == "/api/v1/adjuntos/oportunidad")
    nombre, contenido, tipo = subida["fichero"]
    assert contenido.startswith(b"%PDF") and tipo == "application/pdf"
    assert nombre.endswith(".pdf")
    assert "Ana Ruiz" in salida["texto"] and "45.000,00 €" in salida["texto"]
    assert salida["adjunto"]["id"] == str(adjunto)
    assert salida["corpus"] == {
        "archivado": False,
        "documento_id": "",
        "motivo": "El gestor documental no responde",
    }
    constancia = db.query(DocumentoGenerado).filter_by(plantilla_clave="oferta").one()
    assert (constancia.adjunto_id, constancia.formato) == (adjunto, "pdf")


@pytest.mark.db
def test_si_no_se_puede_guardar_el_adjunto_no_queda_como_generado(
    db: Any, contexto_tenant: UUID, principal: Any
) -> None:
    from crmcore.documental.plantillas import guardar_plantilla

    guardar_plantilla(db, tenant_id=contexto_tenant, clave="carta", cuerpo="Hola {{nombre}}")
    dr._registrar_http(
        _doble(
            {
                f"/api/v1/accounts/{CUENTA}": {
                    "estado": 200,
                    "datos": {"id": str(CUENTA), "nombre": "Ficosa"},
                },
                "/api/v1/adjuntos/cuenta": {"estado": 413, "datos": {"detail": "Sin espacio"}},
            },
            [],
        )
    )
    try:
        with pytest.raises(ErrorDependencia) as fallo:
            dr.generar(db, principal, clave="carta", objeto="cuenta", objeto_id=CUENTA)
    finally:
        dr._registrar_http(None)
    assert fallo.value.error_code == "documento.adjunto_no_guardado"
