"""Ninguna ruta se rompe ante quien llega sin autenticar.

Esto existe por una avería concreta: **las tres rutas de SSO contestaban 500** —
`iniciar`, la vuelta de OIDC y el punto de retorno de SAML— porque pedían la
sesión por una dependencia que la abre con el tenant del principal, y el
proveedor de identidad llega anónimo, que es como llega siempre. O sea que el SSO
no funcionaba de punta a punta, y no lo notaba nadie: cada pieza estaba probada
por su lado y **nunca se llamó a la ruta**.

Qué se considera correcto y qué no:

- **401 o 403**: no has entrado, o no te toca.
- **422**: falta el cuerpo, que es lo que se manda aquí a propósito.
- **404**: el identificador inventado no existe.
- **503**: el servicio dice que algo de lo que depende no está. Eso es la ruta
  contestando, no rompiéndose — `/health/ready` con la base caída tiene que
  decir 503, y decirlo es su trabajo.
- **500 es que la ruta se rompe antes de poder contestar.** Da igual quién
  llame: una ruta que revienta con la petición más tonta del mundo está rota.

Se llaman **todas** las operaciones que publica cada servicio, no una muestra, y
se comprueba cuántas se han recorrido: un barrido que no mira parece verde, y ya
pasó aquí — la primera versión de otra prueba de este repositorio dejaba 709 de
1.878 rutas sin tocar, y el número parecía razonable porque nadie tenía delante
el real.

Lo que esto **no** detecta, dicho para que nadie se confíe: desde que `get_uow`
tiene la guarda que convierte «anónimo sin tenant» en 401, una ruta rota de esa
forma contesta 401 y desde fuera parece correcta. Para esa avería lo que vale es
llamar a la ruta con su credencial de verdad, como hace
`test_saml_no_se_reenvia.py`.
"""

from __future__ import annotations

import importlib
import os
import re
from typing import Any

import pytest

pytestmark = pytest.mark.db

SERVICIOS = (
    "gateway",
    "identity",
    "tenancy",
    "party",
    "sales",
    "marketing",
    "service",
    "metadata",
    "automation",
    "integration",
    "analytics",
    "intelligence",
    "orchestrator",
    "eventing",
)

# Un identificador con la forma correcta y que no existe. Con uno mal formado
# saldría 422 por validación y no se llegaría a ejecutar nada.
UUID_INVENTADO = "00000000-0000-0000-0000-000000000001"

# Suelo del recorrido. No es el número exacto a propósito —crece con el
# producto— pero salta si el barrido se queda corto porque cambie FastAPI o la
# forma de montar los routers. Medido el 29-09-2026: 1.898.
SUELO_DE_OPERACIONES = 1_700

# Lo que SÍ puede contestar a un desconocido, una por una y con su motivo: salud,
# contrato y catálogos de tipos. Nada de esto depende de un tenant.
ABIERTAS_A_PROPOSITO = (
    "/health",
    "/health/live",
    "/health/ready",
    "/metrics",
    # El producto es headless: la superficie ES el contrato, y la consola se
    # construye de ella. Publica qué operaciones hay, no datos de nadie.
    "/api/v1/superficie",
    "/api/v1/eventos/asyncapi.json",
    "/api/v1/eventos/catalogo",
    "/api/v1/servicios",
    # Salir sin haber entrado no puede ser un error: es lo que hace el navegador
    # con una sesión ya caducada.
    "/api/v1/sesion/salir",
    # Catálogos de TIPOS que trae el producto, iguales para todos los tenants:
    # qué clases de relación existen, qué estrategias de reparto hay, sobre qué
    # objetos se puede buscar, por qué canales se avisa.
    "/api/v1/metadata/relaciones/tipos",
    "/api/v1/lead-routing/estrategias",
    "/api/v1/party/buscar/objetos",
    "/api/v1/sales/buscar/objetos",
    "/api/v1/notificaciones/canales",
)


@pytest.fixture(scope="module")
def barrido(_esquema: str) -> Any:
    """Una sola pasada por las 1.898 operaciones, compartida por las tres pruebas.

    Se hace **una vez** y no una por comprobación: cada pasada son casi mil
    novecientas llamadas, y repetirla duplicaba el coste sin mirar nada nuevo.
    Los guardianes no pueden ser el coste.

    El limitador de peticiones va apagado: con él puesto, 656 de las 1.898
    contestaban 429 y el barrido **no las miraba** — habría dicho «ninguna rota»
    sin haber llamado a un tercio.

    Y depende de `_esquema` a propósito: es quien deja `DATABASE_URL` apuntando
    al Postgres de las pruebas. Sin él las aplicaciones buscaban la base en
    `127.0.0.1:5432`, no la encontraban, y el barrido contaba como rotas treinta
    rutas que estaban perfectamente.
    """
    from crmcore.config import get_settings
    from starlette.testclient import TestClient

    mp = pytest.MonkeyPatch()
    mp.setenv("RATE_LIMIT_ENABLED", "false")
    mp.setenv("OUTBOX_ENABLED", "false")
    get_settings.cache_clear()

    recorridas = 0
    rotas: list[str] = []
    abiertas: list[str] = []
    try:
        for nombre in SERVICIOS:
            os.environ["SERVICE_NAME"] = nombre
            app = importlib.import_module(f"services.{nombre}.main").app
            esquema = app.openapi()
            # `raise_server_exceptions=False` para que un fallo del servidor
            # llegue como 500 y se pueda contar, en vez de abortar el barrido en
            # la primera.
            with TestClient(app, raise_server_exceptions=False) as cliente:
                for camino, operaciones in esquema.get("paths", {}).items():
                    concreto = re.sub(r"\{[^}]+\}", UUID_INVENTADO, camino)
                    for metodo in operaciones:
                        verbo = metodo.upper()
                        if verbo not in ("GET", "POST", "PATCH", "PUT", "DELETE"):
                            continue
                        recorridas += 1
                        salida = cliente.request(
                            verbo, concreto, json=None if verbo == "GET" else {}
                        )
                        # Solo el 500. Un 502/503/504 es una indisponibilidad
                        # declarada —«esto de lo que dependo no está»— y decirlo
                        # es lo que se espera de la ruta.
                        if salida.status_code == 500:
                            if "does not exist" in salida.text:
                                # Una tabla que falta es el banco de pruebas, no
                                # el producto: se dice, no se disfraza de verde.
                                rotas.append(
                                    f"{nombre} {verbo} {camino}: falta una tabla "
                                    "(¿el esquema de pruebas está sin migrar?)"
                                )
                            else:
                                rotas.append(
                                    f"{nombre} {verbo} {camino} -> 500 {salida.text[:160]}"
                                )
                        elif (
                            salida.status_code in (200, 201, 204)
                            and camino not in ABIERTAS_A_PROPOSITO
                        ):
                            abiertas.append(
                                f"{nombre} {verbo} {camino} -> {salida.status_code} "
                                f"({len(salida.content)} bytes)"
                            )
        yield recorridas, rotas, abiertas
    finally:
        mp.undo()
        get_settings.cache_clear()


def test_el_barrido_ha_mirado_todo_el_producto(barrido: Any) -> None:
    """Primero, que el barrido valga algo. Sin esto, las otras dos no dicen nada."""
    recorridas, _, _ = barrido
    assert recorridas >= SUELO_DE_OPERACIONES, (
        f"solo se han recorrido {recorridas} operaciones, menos del suelo de "
        f"{SUELO_DE_OPERACIONES}. El barrido se ha quedado corto y su resultado "
        "no significa nada: mira cómo se enumeran las rutas antes de creértelo."
    )


def test_ninguna_ruta_revienta_ante_quien_no_ha_entrado(barrido: Any) -> None:
    recorridas, rotas, _ = barrido
    assert not rotas, (
        f"{len(rotas)} de {recorridas} operaciones se rompen ante una petición "
        "sin autenticar. Un 401, un 403 o un 503 estaría bien; un 500 es que la "
        "ruta no llega ni a contestar:\n  " + "\n  ".join(rotas[:20])
    )


def test_lo_que_contesta_sin_autenticar_no_lleva_dato_de_nadie(barrido: Any) -> None:
    """Que no reviente no basta: no puede **contestar** con datos.

    Una ruta nueva que conteste a un desconocido hace fallar esto, y entonces hay
    que decidir si entra en `ABIERTAS_A_PROPOSITO` con su motivo escrito o si le
    falta el permiso — que es justo la decisión que no se debe tomar sin querer.
    """
    _, _, abiertas = barrido
    assert not abiertas, (
        f"{len(abiertas)} operaciones contestan a quien no ha entrado y no están "
        "en la lista de las que pueden hacerlo. O les falta el permiso, o hay que "
        "añadirlas a la lista diciendo por qué:\n  " + "\n  ".join(abiertas[:20])
    )
