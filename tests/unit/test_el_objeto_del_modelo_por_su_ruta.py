"""La pantalla de un objeto del modelo pide cinco cosas: aquí se piden de verdad.

El objeto, su `describe`, sus límites, sus tipos de registro y la trazabilidad
de quién puso cada campo. La pantalla declara la forma de las cinco y ninguna
prueba de servidor las recorría — el circuito abierto de siempre: las dos
mitades existen, el tipo cuadra sobre el papel, y si el servidor deja de mandar
un campo el panel se queda en blanco sin que nadie se entere.

**Y una trampa concreta que esto fija.** Las rutas hijas de un objeto se
dirigen por su NOMBRE (`/objetos/{nombre}/describe`) mientras que el objeto en
sí se abre por su IDENTIFICADOR (`/objetos/{objeto_id}`). La pantalla abre por
identificador —que es lo que lleva la fila del listado—, lee el nombre y con él
pide lo demás. Si alguien unificara las rutas, o cambiara cuál usa cada una,
esta prueba lo dice: lo contrario es un panel en 404 que sólo se ve abriendo la
pantalla.
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db

# Las rutas **con su hueco escrito**, y se rellenan al pedirlas. No es estilo:
# el gate que destapó este agujero busca la ruta literal en los ficheros de
# prueba y normaliza `{algo}` a un hueco, así que una ruta con el nombre real
# dentro —`/objetos/encargo_taller/describe`— no casa con la que escribe la
# pantalla, y ésta sigue contando como «declara una forma que nadie pide»
# aunque esta prueba la recorra entera. Pasó aquí y pasó en la de Plataforma.
OBJETO = "/api/v1/metadata/objetos/{nombre}"
DESCRIBE = "/api/v1/metadata/objetos/{nombre}/describe"
LIMITES = "/api/v1/metadata/objetos/{nombre}/limites"
TRAZABILIDAD = "/api/v1/metadata/objetos/{nombre}/trazabilidad"
TIPOS = "/api/v1/metadata/objetos/{nombre}/tipos"
CAMPOS = "/api/v1/metadata/objetos/{nombre}/campos"


@pytest.fixture
def cliente(db: Any) -> Any:
    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.metadata.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def un_objeto(cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID) -> dict[str, Any]:
    """Un objeto con un campo, creado por su propia API."""
    r = cliente.post(
        "/api/v1/metadata/objetos",
        json={
            "nombre": "encargo_taller",
            "etiqueta": "Encargo de taller",
            "etiqueta_plural": "Encargos de taller",
            "descripcion": "Lo que se manda a reparar fuera.",
        },
        headers=cabeceras,
    )
    assert r.status_code in (200, 201), r.text[:400]
    objeto = r.json()
    cliente.post(
        CAMPOS.format(nombre="encargo_taller"),
        json={
            "nombre": "matricula",
            "etiqueta": "Matrícula",
            "tipo": "texto",
            "obligatorio": True,
        },
        headers=cabeceras,
    )
    return objeto


def test_el_objeto_se_abre_por_su_identificador(
    cliente: Any, cabeceras: dict[str, str], un_objeto: dict[str, Any]
) -> None:
    """Es lo que lleva la fila del listado, y de ahí sale el nombre."""
    r = cliente.get(OBJETO.format(nombre=un_objeto["id"]), headers=cabeceras)
    assert r.status_code == 200, r.text[:300]
    cuerpo = r.json()
    for campo in ("id", "nombre", "etiqueta", "etiqueta_plural", "descripcion", "origen", "icono"):
        assert campo in cuerpo, f"la pantalla lee «{campo}» y la ruta no lo manda"
    # El nombre es la llave de todo lo demás: sin él, los cuatro paneles de
    # abajo no se pueden ni pedir.
    assert cuerpo["nombre"] == "encargo_taller"


def test_el_describe_trae_campos_reglas_y_layouts(
    cliente: Any, cabeceras: dict[str, str], un_objeto: dict[str, Any]
) -> None:
    r = cliente.get(DESCRIBE.format(nombre="encargo_taller"), headers=cabeceras)
    assert r.status_code == 200, r.text[:300]
    cuerpo = r.json()
    for clave in ("objeto", "campos", "reglas", "layouts"):
        assert clave in cuerpo, f"la pantalla lee «{clave}» y la ruta no lo manda"
    assert cuerpo["campos"], "se ha añadido un campo y el describe no lo trae"
    campo = cuerpo["campos"][0]
    for clave in (
        "nombre",
        "etiqueta",
        "tipo",
        "obligatorio",
        "unico",
        "sensibilidad",
        "deprecado",
    ):
        assert clave in campo, f"la pantalla lee «{clave}» de cada campo y no viene"


def test_los_limites_dicen_cuanto_queda_y_que_pasa_al_llegar(
    cliente: Any, cabeceras: dict[str, str], un_objeto: dict[str, Any]
) -> None:
    """Un tope que sólo se explica cuando se alcanza se explica tarde."""
    r = cliente.get(LIMITES.format(nombre="encargo_taller"), headers=cabeceras)
    assert r.status_code == 200, r.text[:300]
    cuerpo = r.json()
    for clave in ("campos", "tope", "pct", "en_aviso", "al_llegar"):
        assert clave in cuerpo, f"la pantalla lee «{clave}» y la ruta no lo manda"
    assert cuerpo["al_llegar"], "el tope no dice qué pasa al llegar"


def test_la_trazabilidad_contesta_si_el_campo_se_puede_quitar(
    cliente: Any, cabeceras: dict[str, str], un_objeto: dict[str, Any]
) -> None:
    """Es la pregunta de verdad delante de un modelo de datos, y sin ella la
    respuesta es siempre «no lo sé» — que es como se acaba con trescientos
    campos de los que nadie recuerda la mitad."""
    r = cliente.get(TRAZABILIDAD.format(nombre="encargo_taller"), headers=cabeceras)
    assert r.status_code == 200, r.text[:300]
    cuerpo = r.json()
    for clave in ("objeto", "campos", "sin_usar", "publicaciones"):
        assert clave in cuerpo, f"la pantalla lee «{clave}» y la ruta no lo manda"
    campo = cuerpo["campos"][0]
    for clave in ("campo", "tipo", "escrituras", "materializado", "se_puede_retirar"):
        assert clave in campo, f"la pantalla lee «{clave}» de cada campo y no viene"
    # Recién creado y sin escribir: sale como candidato, y eso es correcto —
    # pero se distingue de «deprecado», que es otra cosa.
    assert campo["escrituras"] == 0
    assert "matricula" in cuerpo["sin_usar"]


def test_los_tipos_de_registro_salen_como_lista(
    cliente: Any, cabeceras: dict[str, str], un_objeto: dict[str, Any]
) -> None:
    r = cliente.get(TIPOS.format(nombre="encargo_taller"), headers=cabeceras)
    assert r.status_code == 200, r.text[:300]
    assert isinstance(r.json(), list)
