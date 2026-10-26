"""Auditoría de los contratos de API (CRM-00.02.01), por las respuestas reales.

Cinco capacidades sin ninguna prueba que las nombre, y las cinco son promesas
que se le hacen a **quien integra desde fuera**. Lo que tienen en común es que
romperlas no se nota desde dentro: el producto sigue funcionando y lo que se
rompe es el cliente de otro.

  · **el versionado explícito** (CRM-00.02.01.05): toda ruta cuelga de la
    versión mayor, para que un cambio rompedor pueda convivir con lo anterior
    en vez de obligar a todos a migrar el mismo día;
  · **los avisos de retirada** (CRM-00.02.01.07): cuando hay fecha anunciada,
    va en **toda** respuesta. Es el único canal que el integrador ya está
    leyendo — una circular por correo la lee quien sigue en la empresa;
  · **la paginación por cursor** (CRM-00.02.01.10): estable, que es lo que
    distingue un cursor de un número de página. Con desplazamiento, una fila
    nueva mientras se pagina hace que otra se salte sin que nadie se entere;
  · y **los errores normalizados** (CRM-00.02.01.14): con código estable y con
    el identificador de la petición dentro, que es lo que permite que alguien
    abra una incidencia que se pueda buscar.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(db: Any) -> Iterator[Any]:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.party.main").app) as cli:
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


# ── CRM-00.02.01.05 · Versionado explícito ────────────────────────────────


def test_toda_ruta_cuelga_de_la_version_mayor_crm_00_02_01_05(cliente: Any) -> None:
    """Con la versión en la URI, un cambio rompedor puede convivir con lo
    anterior: los dos caminos existen a la vez y cada integrador migra cuando
    puede. Sin ella, el día del cambio es el día de todos."""
    from crmcore.config import get_settings

    prefijo = get_settings().api_prefix
    assert prefijo.startswith("/api/v"), prefijo

    contrato = cliente.get(f"{prefijo}/openapi.json").json()
    de_negocio = [
        r for r in contrato["paths"] if not r.startswith(("/health", "/metrics", "/docs"))
    ]
    assert len(de_negocio) >= 30, f"sólo se ven {len(de_negocio)} rutas"
    fuera = sorted(r for r in de_negocio if not r.startswith(prefijo))
    assert not fuera, f"rutas sin versión en el camino: {fuera}"


# ── CRM-00.02.01.07 · Avisos de retirada ──────────────────────────────────


def test_sin_fecha_anunciada_no_se_avisa_de_nada_crm_00_02_01_07(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Una cabecera de retirada permanente es ruido, y el ruido se filtra: el
    día que sí haya fecha, el integrador ya habrá dejado de mirarla."""
    r = cliente.get("/api/v1/accounts", headers=cabeceras)
    assert "sunset" not in {k.lower() for k in r.headers}, dict(r.headers)


def test_con_fecha_anunciada_va_en_toda_respuesta_crm_00_02_01_07(
    db: Any, cabeceras: dict[str, str], contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """**En toda respuesta**, no en una nota del manual: es el único canal que
    el integrador ya está leyendo. Una circular por correo la lee quien sigue
    en la empresa el día que se manda."""
    import importlib
    import os

    from crmcore.config import get_settings

    monkeypatch.setenv("API_SUNSET_DATE", "Sat, 31 Oct 2026 23:59:59 GMT")
    monkeypatch.setenv("OUTBOX_ENABLED", "false")
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.party.main")
        with TestClient(modulo.app) as cli:
            r = cli.get("/api/v1/accounts", headers=cabeceras)
            cab = {k.lower(): v for k, v in r.headers.items()}
            assert cab.get("sunset") == "Sat, 31 Oct 2026 23:59:59 GMT", cab
            # Y `Deprecation`, que es la que un cliente mira para avisar a quien
            # lo mantiene: `Sunset` sola dice cuándo, no que ya esté en
            # retirada.
            assert cab.get("deprecation") == "true", cab
    finally:
        os.environ.pop("API_SUNSET_DATE", None)
        get_settings.cache_clear()


# ── CRM-00.02.01.10 · Paginación por cursor ───────────────────────────────


@pytest.fixture
def cinco_cuentas(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> list[Any]:
    from services.party.modelos import Cuenta

    filas = [
        Cuenta(tenant_id=tenant_id, nombre=f"Cuenta {i:02d}", clave_canonica=f"cuenta-{i:02d}")
        for i in range(5)
    ]
    db.add_all(filas)
    db.flush()
    return filas


def test_el_cursor_no_se_salta_ni_repite_filas_crm_00_02_01_10(
    cliente: Any, cabeceras: dict[str, str], cinco_cuentas: Any
) -> None:
    """**Esto es lo que distingue un cursor de un número de página.** Con
    desplazamiento, una fila nueva mientras alguien pagina empuja a las demás y
    una se salta — sin error, sin aviso, y el que exporta se lleva 4.999 de
    5.000 sin saberlo.

    Aquí se inserta una fila **entre página y página**, que es el caso real.
    """
    from services.party.modelos import Cuenta

    primera = cliente.get("/api/v1/accounts?limite=2", headers=cabeceras).json()
    assert len(primera["items"]) == 2, primera
    assert primera["siguiente"], "sin cursor no hay segunda página"

    # Entra una cuenta nueva mientras se pagina.
    from sqlalchemy.orm import object_session

    sesion = object_session(cinco_cuentas[0])
    sesion.add(
        Cuenta(
            tenant_id=cinco_cuentas[0].tenant_id,
            nombre="Cuenta intercalada",
            clave_canonica="cuenta-intercalada",
        )
    )
    sesion.flush()

    vistos = [c["id"] for c in primera["items"]]
    cursor = primera["siguiente"]
    for _ in range(6):
        if not cursor:
            break
        pagina = cliente.get(f"/api/v1/accounts?limite=2&cursor={cursor}", headers=cabeceras).json()
        vistos += [c["id"] for c in pagina["items"]]
        cursor = pagina.get("siguiente")

    assert len(vistos) == len(set(vistos)), "el cursor ha repetido filas"
    # Las cinco de antes tienen que estar todas: la que entró después puede
    # salir o no —depende de dónde caiga en el orden— y eso es correcto.
    de_antes = {str(c.id) for c in cinco_cuentas}
    assert de_antes <= set(vistos), f"se han saltado {sorted(de_antes - set(vistos))}"


def test_la_pagina_dice_si_hay_mas_crm_00_02_01_10(
    cliente: Any, cabeceras: dict[str, str], cinco_cuentas: Any
) -> None:
    """Sin eso, quien integra tiene que pedir una página de más para descubrir
    que estaba vacía — y con un listado grande eso es una consulta de más en
    cada recorrido."""
    pagina = cliente.get("/api/v1/accounts?limite=2", headers=cabeceras).json()
    for campo in ("items", "siguiente", "hay_mas"):
        assert campo in pagina, f"falta «{campo}»: {sorted(pagina)}"
    assert pagina["hay_mas"] is True

    entera = cliente.get("/api/v1/accounts?limite=50", headers=cabeceras).json()
    assert entera["hay_mas"] is False
    assert entera["siguiente"] is None


def test_un_cursor_inventado_se_rechaza_crm_00_02_01_10(
    cliente: Any, cabeceras: dict[str, str], cinco_cuentas: Any
) -> None:
    """Y no devuelve la primera página como si nada: quien pagina con un cursor
    roto se llevaría las mismas filas una y otra vez sin enterarse."""
    r = cliente.get("/api/v1/accounts?limite=2&cursor=esto-no-es-un-cursor", headers=cabeceras)
    assert r.status_code == 422, r.text


# ── CRM-00.02.01.14 · Errores normalizados ────────────────────────────────


def test_un_error_es_problem_details_con_codigo_estable_crm_00_02_01_14(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """El código es lo que un cliente puede mirar para decidir qué hacer; el
    texto es para quien lo lee. Mirar el texto ata al integrador al idioma y a
    la redacción, y las dos cambian."""
    r = cliente.get("/api/v1/accounts/no-es-un-uuid", headers=cabeceras)
    assert r.status_code == 422, r.text
    cuerpo = r.json()
    for campo in ("type", "title", "status", "detail", "error_code"):
        assert campo in cuerpo, f"falta «{campo}»: {sorted(cuerpo)}"
    assert cuerpo["status"] == 422
    # El tipo de contenido también es parte del contrato: un cliente que mire
    # `application/problem+json` tiene que reconocerlo.
    assert "problem+json" in r.headers.get("content-type", ""), r.headers.get("content-type")


def test_el_error_lleva_el_identificador_de_la_peticion_crm_00_02_01_14(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Es lo que convierte «me da error» en una incidencia que se puede buscar.
    Y va **dentro del cuerpo** además de en la cabecera, porque lo que el
    usuario copia y pega es lo que ve en pantalla."""
    r = cliente.get("/api/v1/accounts/no-es-un-uuid", headers=cabeceras)
    cuerpo = r.json()
    assert cuerpo.get("request_id"), sorted(cuerpo)
    assert r.headers.get("x-request-id") == cuerpo["request_id"], (
        "el identificador del cuerpo y el de la cabecera no coinciden: quien "
        "busque por uno no encontrará lo del otro"
    )


def test_un_404_no_confirma_que_el_registro_exista_crm_00_02_01_14(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Un 403 confirma que ese identificador existe. Enumerando, alguien con
    una cuenta en el mismo sistema puede averiguar cuántos clientes tiene
    otro."""
    r = cliente.get(f"/api/v1/accounts/{uuid4()}", headers=cabeceras)
    assert r.status_code == 404, r.text


# ── CRM-00.02.01.06 · Compatibilidad hacia atrás ──────────────────────────


def test_nada_de_lo_publicado_ha_desaparecido_crm_00_02_01_06() -> None:
    """**La promesa que más duele romper**, porque no se rompe con un error:
    se rompe en silencio, y quien se entera es el cliente de otro, en
    producción, el día del despliegue.

    Dentro de la misma versión mayor, lo que un integrador usa hoy tiene que
    seguir estando mañana. El sello guarda las operaciones publicadas —método y
    camino— y esto comprueba que ninguna se haya ido.

    Añadir no rompe nada y por eso no se vigila. Quitar sí, y no se bloquea del
    todo: se bloquea quitar **sin decirlo**. Para retirar algo hay dos caminos y
    los dos son explícitos — anunciar la retirada con `API_SUNSET_DATE` y subir
    la versión mayor, o volver a sellar dejando constancia en el commit.
    """
    import json
    import subprocess
    import sys
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[2]
    sello = raiz / "docs/contrato-publicado.json"
    assert sello.exists(), "no hay sello del contrato publicado"

    # Que el sello mire de verdad: uno vacío —o roto— haría pasar esto en verde
    # sin comparar nada, que es el verde de no mirar.
    guardado = json.loads(sello.read_text(encoding="utf-8"))
    assert len(guardado) >= 10, f"el sello sólo cubre {len(guardado)} servicios"
    assert sum(len(v) for v in guardado.values()) >= 1000, "el sello está casi vacío"

    salida = subprocess.run(
        [sys.executable, "scripts/sellar_contrato.py"],
        cwd=raiz,
        capture_output=True,
        text=True,
    )
    assert salida.returncode == 0, salida.stdout + salida.stderr
