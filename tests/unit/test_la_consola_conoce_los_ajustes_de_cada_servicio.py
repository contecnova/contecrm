"""La consola de ajustes conoce las claves que declara cada servicio.

Medido el 10-11-2026 en vivo: la consola (en `tenancy`) sólo conocía las claves
del núcleo. Las 166 que declaran los `ajustes.py` de los servicios no salían y
fijarlas daba «clave desconocida»: sólo se cambiaban por `.env`.

Ahora cada servicio publica las suyas y la consola las agrega. Lo que se prueba
es cada mitad: que el dueño publique las suyas con SU valor por defecto, y que
la consola, al recibirlas, las valide y las resuelva igual que las del núcleo
sin pisar ninguna del núcleo.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from crmcore.errors import ErrorValidacion
from crmcore.runtime import keys
from crmcore.runtime import settings as rt


def test_cada_servicio_publica_las_suyas_con_su_valor_por_defecto() -> None:
    from crmcore.http.ajustes_catalogo_router import crear_router_catalogo_ajustes
    from crmcore.http.interno import cabeceras_firmadas
    from crmcore.http.problems import registrar_manejadores
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import services.party.ajustes  # noqa: F401 — registra las claves de party

    app = FastAPI()
    registrar_manejadores(app)
    app.include_router(crear_router_catalogo_ajustes("party"), prefix="/api/v1")
    cliente = TestClient(app)

    # Sin la firma de la casa no se entra: es una ruta entre servicios.
    assert cliente.get("/api/v1/interno/ajustes/catalogo").status_code == 401

    r = cliente.get("/api/v1/interno/ajustes/catalogo", headers=cabeceras_firmadas())
    assert r.status_code == 200, r.text
    publicadas = {c["clave"]: c for c in r.json()["claves"]}
    assert publicadas["proveedor_dias_preaviso"]["por_defecto"] == rt.efectivo(
        "proveedor_dias_preaviso"
    )
    assert publicadas["proveedor_dias_preaviso"]["tipo"] == "int"
    # Las del núcleo no: la consola ya las conoce por sí misma.
    assert "oidc_cache_ttl_s" not in publicadas


@pytest.fixture
def remotos(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    from services.tenancy import ajustes_remotos

    monkeypatch.setattr(ajustes_remotos, "_traido_en", None)
    monkeypatch.setattr(ajustes_remotos, "_sin_respuesta", [])
    yield ajustes_remotos
    keys.CLAVES.pop("zz_umbral_de_un_servicio", None)
    ajustes_remotos._por_defecto.pop("zz_umbral_de_un_servicio", None)


def test_la_consola_valida_y_resuelve_la_de_otro_servicio(
    remotos: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    nucleo = keys.CLAVES["oidc_cache_ttl_s"]
    catalogos = {
        "party": [
            {
                "clave": "zz_umbral_de_un_servicio",
                "tipo": "int",
                "descripcion": "Umbral de prueba",
                "minimo_ambito": "tenant",
                "minimo": 1,
                "maximo": 10,
                "campo_settings": "zz_umbral_de_un_servicio",
                "por_defecto": 7,
            },
            # Un servicio que publicara una del núcleo no la puede pisar.
            {"clave": "oidc_cache_ttl_s", "tipo": "str", "campo_settings": "x"},
        ]
    }
    monkeypatch.setattr(remotos, "_preguntar_a_todos", lambda: (catalogos, ["sales"]))

    # El que no contestó se dice, no se calla.
    assert remotos.asegurar() == ["sales"]

    assert keys.CLAVES["zz_umbral_de_un_servicio"].servicio == "party"
    assert keys.validar("zz_umbral_de_un_servicio", "5") == 5
    with pytest.raises(ErrorValidacion):
        keys.validar("zz_umbral_de_un_servicio", 11)
    assert not keys.ambito_permitido("zz_umbral_de_un_servicio", "usuario")
    # El valor por defecto es el del dueño, no `None`.
    assert rt.efectivo("zz_umbral_de_un_servicio") == 7
    assert keys.CLAVES["oidc_cache_ttl_s"] is nucleo


def test_cada_servicio_registra_sus_ajustes_al_arrancar() -> None:
    """La consola sólo ve lo que el servicio tiene registrado cuando le pregunta.

    Un `ajustes.py` que sólo se importa dentro de una función registra sus
    claves tarde o nunca: medido el 10-11-2026, `integration` publicaba cero de
    sus 27. Su `main.py` tiene que importarlo arriba.
    """
    import ast
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[2] / "services"
    mirados, sin_importar = 0, []
    for ajustes in sorted(raiz.glob("*/ajustes.py")):
        servicio = ajustes.parent.name
        mirados += 1
        arbol = ast.parse((ajustes.parent / "main.py").read_text(encoding="utf-8"))
        importa = any(
            (
                isinstance(n, ast.ImportFrom)
                and n.module == f"services.{servicio}"
                and any(a.name == "ajustes" for a in n.names)
            )
            or (
                isinstance(n, ast.Import)
                and any(a.name == f"services.{servicio}.ajustes" for a in n.names)
            )
            for n in arbol.body
        )
        if not importa:
            sin_importar.append(servicio)
    assert mirados >= 7, f"Sólo se han mirado {mirados} servicios con ajustes"
    assert not sin_importar, f"No registran sus ajustes al arrancar: {sin_importar}"
