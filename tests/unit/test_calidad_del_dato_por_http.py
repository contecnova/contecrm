"""Calidad del dato en `party`, EJERCITADA por HTTP
(CRM-01.01.04.08, CRM-01.01.04.09, CRM-01.01.04.11, CRM-09.01.01.05,
CRM-01.01.02.09).

Un **circuito abierto** y cinco decisiones sin puerta.

El circuito: el linaje —de dónde viene cada valor— se podía **consultar** y no
se podía **escribir**. `anotar_linaje` no la llamaba nadie, así que la tabla
estaba siempre vacía: «¿por qué pone esto aquí?» contestaba nada, y «qué valores
llevan demasiado sin confirmarse» contestaba que ninguno. Las dos respuestas son
exactamente las que saldrían si todo estuviera al día.

Y un falso positivo que salió al enchufar el normalizador de razón social: la
clave canónica **quita la forma jurídica** —y tiene que quitarla, para que
«García SL» y «García, S.L.» se reconozcan—, así que «García SL» y «García SA»
salían como duplicado concluyente. Son dos entidades jurídicas, con dos NIF y dos
contabilidades, y fusionarlas es caro de deshacer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(monkeypatch: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    # Los barridos periódicos del servicio abren su propia transacción contra la
    # misma base que la prueba y, al deshacerla, se llevan el savepoint del
    # caso: el síntoma es un «savepoint no existe» que no tiene nada que ver con
    # lo que se está probando.
    async def _no_correr(self: Any) -> None:
        return None

    from crmcore.tareas import RelevoDeTareas

    monkeypatch.setattr(RelevoDeTareas, "correr", _no_correr)

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.party.main")
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


# ── El linaje se podía leer y no escribir ─────────────────────────────────


def test_sin_poder_apuntar_el_linaje_la_consulta_contesta_vacio(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    """Es la mitad que faltaba, y su ausencia no daba ningún error: contestaba lo
    mismo que si todo estuviera al día."""
    objeto_id = uuid4()
    antes = cliente.get(f"/api/v1/calidad-dato/linaje/cuenta/{objeto_id}", headers=cabeceras)
    assert antes.status_code == 200, antes.text
    assert not antes.json()["campos"]

    puesto = cliente.post(
        "/api/v1/calidad-dato/linaje",
        headers=cabeceras,
        json={
            "objeto": "cuenta",
            "objeto_id": str(objeto_id),
            "campo": "telefono",
            "fuente": "erp",
            "valor": "+34600000000",
            "confianza": 80,
        },
    )
    assert puesto.status_code == 200, puesto.text

    despues = cliente.get(f"/api/v1/calidad-dato/linaje/cuenta/{objeto_id}", headers=cabeceras)
    assert despues.status_code == 200, despues.text
    assert "telefono" in despues.json()["campos"]


def test_confirmar_no_es_cambiar(cliente: Any, cabeceras: dict[str, str], db: Any) -> None:
    """Mover las dos fechas haría que el dato pareciera recién actualizado cuando
    lo único que ha pasado es que alguien lo miró."""
    objeto_id = uuid4()
    cambiado = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    puesto = cliente.post(
        "/api/v1/calidad-dato/linaje",
        headers=cabeceras,
        json={
            "objeto": "cuenta",
            "objeto_id": str(objeto_id),
            "campo": "cargo",
            "fuente": "formulario",
            "valor": "Director",
            "cambiado_at": cambiado,
        },
    )
    assert puesto.status_code == 200, puesto.text
    assert puesto.json()["cambiado_at"][:10] == cambiado[:10]

    confirmado = cliente.post(
        "/api/v1/calidad-dato/linaje/confirmar",
        headers=cabeceras,
        json={
            "objeto": "cuenta",
            "objeto_id": str(objeto_id),
            "campo": "cargo",
            "fuente": "formulario",
        },
    )
    assert confirmado.status_code == 200, confirmado.text

    linaje = cliente.get(
        f"/api/v1/calidad-dato/linaje/cuenta/{objeto_id}", headers=cabeceras
    ).json()
    fuente = linaje["campos"]["cargo"][0]
    # Se comparan INSTANTES, no los diez primeros caracteres de su forma de
    # texto. Lo que se guarda es un instante y lo que se devuelve va en la zona
    # del cliente, así que recortar la cadena compara dos días distintos: medido
    # el 07-10-2026 a las 01:24, con 400 días hacia atrás, uno daba 2025-09-01 y
    # el otro 2025-09-02. Lo que esta prueba dice —que confirmar no mueve la
    # fecha del cambio— es cierto en los dos, y no tiene nada que ver con la
    # hora a la que se ejecute.
    assert datetime.fromisoformat(fuente["cambio_el_valor"]) == datetime.fromisoformat(cambiado)
    # ...y la del último mensaje es de ahora, no de hace 400 días.
    distancia = abs(datetime.fromisoformat(fuente["ultimo_mensaje"]) - datetime.now(timezone.utc))
    assert distancia < timedelta(minutes=5), fuente["ultimo_mensaje"]


def test_un_plazo_de_cero_dias_deja_todo_obsoleto(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Lo que produce es una cola de excepciones con todo dentro, que nadie mira."""
    r = cliente.post(
        "/api/v1/calidad-dato/caducidad/comprobar",
        headers=cabeceras,
        json={"dias_por_campo": {"telefono": 0, "nif": 36500, "cargo": 180}},
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["valido"] is False
    assert [p["campo"] for p in salida["problemas"]] == ["telefono"]
    # Y un plazo de cien años es «no caduca» sin escribirlo: se señala.
    assert salida["practicamente_eternos"] == ["nif"]


# ── Enriquecimiento (CRM-01.01.04.11) ─────────────────────────────────────


def test_nunca_consultado_no_es_hace_mucho(cliente: Any, cabeceras: dict[str, str]) -> None:
    """La decisión que se toma con cada uno es distinta."""
    nunca = cliente.get("/api/v1/calidad-dato/enriquecimiento/caducidad", headers=cabeceras)
    assert nunca.status_code == 200, nunca.text
    assert nunca.json()["nunca_consultado"] is True

    hace_poco = cliente.get(
        "/api/v1/calidad-dato/enriquecimiento/caducidad"
        f"?ultimo_at={(datetime.now(timezone.utc) - timedelta(days=5)).strftime('%Y-%m-%dT%H:%M:%S')}&dias=180",
        headers=cabeceras,
    )
    assert hace_poco.status_code == 200, hace_poco.text
    assert hace_poco.json()["nunca_consultado"] is False
    assert hace_poco.json()["toca"] is False


# ── Proveedores (CRM-09.01.01.05) ─────────────────────────────────────────


def _proveedor(db: Any, tenant_id: UUID, nombre: str) -> Any:
    from services.party.modelos import Cuenta
    from services.party.normalizacion import clave_canonica_empresa

    cuenta = Cuenta(
        tenant_id=tenant_id,
        nombre=nombre,
        clave_canonica=clave_canonica_empresa(nombre),
        roles=["proveedor"],
    )
    db.add(cuenta)
    db.flush()
    return cuenta


def test_no_se_da_de_baja_lo_que_tiene_trabajo_comprometido(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Quitarlo del maestro no cancela lo que ya se vendió: hace que el día de la
    entrega nadie sepa quién tenía que ir."""
    proveedor = _proveedor(db, tenant_id, "Montajes del Norte SL")

    con_trabajo = cliente.post(
        f"/api/v1/proveedores/{proveedor.id}/puede-darse-de-baja",
        headers=cabeceras,
        json={
            "compromisos_abiertos": [{"referencia": "OP-1"}, {"referencia": "OP-2"}],
            "alternativas_homologadas": 3,
        },
    )
    assert con_trabajo.status_code == 200, con_trabajo.text
    assert con_trabajo.json()["puede"] is False
    assert con_trabajo.json()["que_hacer"]

    unico = cliente.post(
        f"/api/v1/proveedores/{proveedor.id}/puede-darse-de-baja",
        headers=cabeceras,
        json={"compromisos_abiertos": [], "alternativas_homologadas": 0},
    )
    assert unico.status_code == 200, unico.text
    assert unico.json()["puede"] is True
    # Se puede, y deja un hueco desde el primer día. Las dos cosas.
    assert unico.json()["deja_hueco"] is True
    assert "semanas" in unico.json()["aviso"]


# ── El complemento de correo (CRM-01.01.02.09) ────────────────────────────


def test_el_panel_del_correo_dice_tambien_a_quien_no_conoce(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Esa es la lista de contactos que faltan por dar de alta, y es lo que hace
    que el complemento sirva para algo más que consultar."""
    from services.party.modelos import Contacto

    db.add(
        Contacto(
            tenant_id=tenant_id,
            nombre="Marta",
            apellidos="Ruiz",
            nombre_completo="Marta Ruiz",
            email="marta@cliente.example",
            clave_canonica="marta ruiz",
        )
    )
    db.flush()

    r = cliente.get(
        "/api/v1/contacts/contexto-de-correo"
        "?direccion=marta@cliente.example&direccion=nadie@otra.example",
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert [c["email"] for c in salida["conocidos"]] == ["marta@cliente.example"]
    assert salida["desconocidos"] == ["nadie@otra.example"]


# ── El falso positivo que salió al enchufar la razón social ───────────────


def test_dos_formas_juridicas_distintas_no_son_un_duplicado_concluyente(
    db: Any, tenant_id: UUID
) -> None:
    """La clave canónica quita la forma jurídica, así que «García SL» y «García
    SA» salían idénticas. Son dos entidades, con dos NIF y dos contabilidades."""
    from services.party import duplicados

    _proveedor(db, tenant_id, "Hijos de García SA")

    candidatos = duplicados.buscar_cuentas_duplicadas(
        db, tenant_id=tenant_id, nombre="Hijos de García, S.L."
    )
    assert candidatos, "la criba por clave canónica tiene que traerlo igualmente"
    uno = candidatos[0]
    assert uno.concluyente is False
    assert "forma_juridica_distinta" in uno.senales


def test_la_misma_forma_juridica_escrita_de_dos_maneras_si_es_duplicado(
    db: Any, tenant_id: UUID
) -> None:
    """Y esto es lo que no se puede romper al arreglar lo anterior."""
    from services.party import duplicados

    _proveedor(db, tenant_id, "Hijos de García S.L.")

    candidatos = duplicados.buscar_cuentas_duplicadas(
        db, tenant_id=tenant_id, nombre="Hijos de García, SL"
    )
    assert candidatos
    assert "forma_juridica_distinta" not in candidatos[0].senales
    assert candidatos[0].concluyente is True


def test_rutas_literales_no_quedan_tapadas() -> None:
    """Una ruta literal declarada DESPUÉS de una con parámetro no se alcanza.

    FastAPI casa en orden de declaración: con `/contacts/{contacto_id}` arriba,
    `/contacts/contexto-de-correo` encaja en ella y la respuesta es «no es un
    UUID» — un 422 que manda a mirar el cliente, donde está todo bien.

    Ha mordido **tres veces hoy**: la exportación de los listados, las dos rutas
    literales de sugerencias y el panel del correo. Las tres se arreglaron
    adelantando la ruta, y las tres después de depurarlo. Esto lo caza antes.
    """
    import importlib
    import re

    def _caminos(app: Any) -> list[tuple[str, str]]:
        """Las rutas, aplanadas y **en orden de declaración**.

        El orden es el dato: es lo único que decide cuál casa primero. Por eso
        no vale `openapi()["paths"]`, que viene ordenado de otra forma.
        """
        salida: list[tuple[str, str]] = []

        def _apuntar(ruta: Any) -> None:
            camino = getattr(ruta, "path", None)
            if not camino:
                return
            # El MÉTODO forma parte de la comparación: `DELETE /x/{id}` no tapa
            # a `POST /x/validar`, y sin esta distinción el guardián señalaría
            # cuarenta rutas que funcionan perfectamente — y entonces se apaga.
            for metodo in sorted(getattr(ruta, "methods", None) or {"GET"}):
                salida.append((metodo, camino))

        for ruta in app.routes:
            if getattr(ruta, "path", None):
                _apuntar(ruta)
                continue
            interno = getattr(ruta, "original_router", None)
            for sub in getattr(interno, "routes", []):
                _apuntar(sub)
        return salida

    tapadas: list[str] = []
    miradas = 0
    for servicio in (
        "sales",
        "party",
        "service",
        "marketing",
        "metadata",
        "tenancy",
        "identity",
        "analytics",
        "automation",
        "integration",
        "intelligence",
        "eventing",
        "orchestrator",
    ):
        modulo = importlib.import_module(f"services.{servicio}.main")
        vistas: list[tuple[str, str]] = []
        for metodo, camino in _caminos(modulo.app):
            miradas += 1
            for metodo_anterior, anterior in vistas:
                if metodo_anterior != metodo or "{" not in anterior or anterior == camino:
                    continue
                patron = re.sub(r"\{[^}]+\}", "[^/]+", anterior)
                if re.fullmatch(patron, camino):
                    tapadas.append(f"{servicio}: «{metodo} {camino}» la tapa «{anterior}»")
            vistas.append((metodo, camino))

    # Que diga cuántas ha mirado: un recorrido que no mira sale verde, y en este
    # repositorio ya pasó — un cero que significaba «no se ha mirado».
    assert miradas > 1_000, f"solo se han mirado {miradas} rutas: el recorrido no mira"
    assert not tapadas, (
        "Estas rutas no se alcanzan nunca: las casa antes una con parámetro "
        "declarada más arriba.\n  " + "\n  ".join(sorted(set(tapadas)))
    )
