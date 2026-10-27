"""Lo que la consola ofrece, ¿contesta? (CRM-07.04.03).

La consola no escribe una pantalla por recurso: declara en `recursos.ts` de
dónde se lista cada cosa y dibuja las pestañas a partir de eso. Ya hay un gate
que comprueba que esas rutas **existan** en el contrato del servicio, y un
barrido que comprueba que los listados de cada servicio no revienten.

Falta lo de en medio, que es lo que ve el usuario: **abrir la pestaña**. Una
ruta puede existir y contestar bien al barrido genérico y aun así dar 403 —el
permiso que exige no es el que el módulo supone—, 422 —pide un parámetro que la
pestaña no manda— o 404 —el servicio dueño declarado no es el que la publica—.
Las tres se ven igual desde dentro: una pestaña con su rótulo y un error.

Es el mismo agujero que la bandeja de casos leyendo campos que nadie manda,
una capa más arriba: cada mitad está bien y lo que falla es la unión.

Los módulos que recorre, por su identificador de catálogo: CRM-07.04.03.01,
CRM-07.04.03.02, CRM-07.04.03.03, CRM-07.04.03.04, CRM-07.04.03.05,
CRM-07.04.03.06, CRM-07.04.03.07, CRM-07.04.03.08, CRM-07.04.03.09,
CRM-07.04.03.10, CRM-07.04.03.11, CRM-07.04.03.12, CRM-07.04.03.14,
CRM-07.04.03.15, CRM-07.04.03.16, CRM-07.04.03.21, CRM-07.04.03.22,
CRM-07.04.03.28 y CRM-07.04.03.31.

Medido el 26-10-2026: **110 pestañas en trece servicios, todas contestan**, en
quince segundos. Que no saliera ningún roto no es motivo para no tenerlo: lo
barato es mantenerlo, y lo caro es la pestaña que se rompe el día que alguien
cambia un permiso.

**Lo que NO hace.** No mira que el dato sea el correcto; eso es de cada prueba
de dominio. Se abre la pestaña como la abre la consola al entrar —sin filtros,
con permisos de administrador— y se exige que conteste. Un error aquí es una
pantalla con su título y un mensaje rojo para alguien.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db

RAIZ = Path(__file__).resolve().parents[2]
MODULOS = RAIZ / "frontend/src/lib/recursos.ts"

# Una entrada de `recursos.ts` es un objeto sin objetos dentro, igual que lee el
# gate de rutas. Se leen con expresión regular y no importando el módulo porque
# es TypeScript; a cambio, el recuento mínimo de abajo hace que un cambio de
# formato que deje de encontrar entradas se note.
ENTRADA = re.compile(r"\{[^{}]*?\}", re.S)


def _pestanas() -> dict[str, list[tuple[str, str]]]:
    """Servicio → [(nombre de la pestaña, ruta que lista)].

    Se dejan fuera las que la propia declaración marca como especiales, con su
    motivo escrito allí: las que **exigen un término** de búsqueda —pedidas sin
    él contestan 422 a propósito— y las que son **sólo de plataforma**, que
    desde el tenant dan 403 por diseño.

    Las de **periodo** no se dejan fuera: se abren con un rango, que es como las
    abre quien entra. Saltárselas sería no mirar justo los informes, que son los
    que más fácilmente se rompen al cambiar un cálculo.
    """
    salida: dict[str, list[tuple[str, str]]] = {}
    for bloque in ENTRADA.findall(MODULOS.read_text(encoding="utf-8")):
        servicio = re.search(r'servicio:\s*"([^"]+)"', bloque)
        listar = re.search(r'listar:\s*"([^"]+)"', bloque)
        nombre = re.search(r'nombre:\s*"([^"]+)"', bloque)
        if not (servicio and listar):
            continue
        if "exige_termino" in bloque or "solo_plataforma" in bloque:
            continue
        # Las que llevan un identificador dentro se piden desde una ficha, no
        # desde el menú: sin un registro de verdad delante no se pueden abrir.
        if "${" in listar.group(1) or "{" in listar.group(1):
            continue
        ruta = listar.group(1)
        # Un informe de periodo exige `desde` y `hasta`: sin ellos contesta 422
        # a propósito. Se le da un rango, que es lo que hace la pantalla.
        if re.search(r"periodo:\s*true", bloque):
            ruta = f"{ruta}?desde=2020-01-01&hasta=2030-12-31"
        salida.setdefault(servicio.group(1), []).append(
            (nombre.group(1) if nombre else listar.group(1), ruta)
        )
    return salida


def test_el_recorrido_mira_de_verdad() -> None:
    """Sin esto, un cambio de formato en `recursos.ts` dejaría el barrido sin
    pestañas que abrir y pasaría en verde — que es el verde de no mirar."""
    todas = _pestanas()
    cuantas = sum(len(v) for v in todas.values())
    assert cuantas >= 100, f"sólo se ven {cuantas} pestañas: {sorted(todas)}"
    assert "party" in todas and "tenancy" in todas, sorted(todas)


def _cabeceras(tenant_id: UUID) -> dict[str, str]:
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


@pytest.mark.parametrize("servicio", sorted(_pestanas()))
def test_las_pestanas_de_la_consola_abren(
    servicio: str, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una por una, como las abre quien entra en el módulo."""
    import importlib
    import os

    from crmcore.config import get_settings
    from starlette.testclient import TestClient

    pestanas = _pestanas()[servicio]
    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    cabeceras = _cabeceras(tenant_id)
    rotas: list[str] = []
    abiertas = 0
    try:
        with TestClient(importlib.import_module(f"services.{servicio}.main").app) as cli:
            for nombre, ruta in pestanas:
                respuesta = cli.get(ruta, headers=cabeceras)
                abiertas += 1
                if respuesta.status_code != 200:
                    rotas.append(
                        f"«{nombre}» ({ruta}) → {respuesta.status_code}: " f"{respuesta.text[:160]}"
                    )
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()

    assert abiertas == len(pestanas), f"se han abierto {abiertas} de {len(pestanas)}"
    assert not rotas, (
        f"Pestañas de «{servicio}» que la consola ofrece y no contestan. Cada "
        "una es una pantalla con su rótulo y un error para alguien:\n  " + "\n  ".join(rotas)
    )
