"""El panel de consumo suma por HTTP, y lo que no se lee no vale cero.

Las cuotas van **por módulo** —cada servicio guarda lo suyo en su esquema y
cuenta lo suyo—, así que la suma se compone preguntando a cada uno, con la misma
mecánica que la página de estado.

**Y la regla que decide si el panel sirve para algo: un servicio que no contesta
sale como «no se ha podido leer», nunca como cero.** Un cero es una afirmación
falsa —«no has gastado nada»— y un cliente que ve ceros llega al tope sin haber
visto subir el número nunca. Eso convierte una cuota en una encerrona.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest


@pytest.fixture(autouse=True)
def _sin_medidores() -> Any:
    from crmcore.consumo import limpiar_medidores

    limpiar_medidores()
    yield
    limpiar_medidores()


# ── Lo que publica cada módulo ────────────────────────────────────────────


@pytest.mark.db
def test_un_modulo_publica_lo_que_mide_con_su_tope_al_lado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El tope va dentro: un consumo sin su límite no dice si son muchos o pocos."""
    from crmcore.consumo import medido_aqui, registrar_medidor
    from crmcore.runtime import settings as rt

    rt.fijar(db, "cuota_correos_mes", 100, ambito="tenant", ambito_id=str(tenant_id))
    db.commit()
    registrar_medidor("email", lambda _db, _t: (30, "cuota_correos_mes"))

    fila = medido_aqui(db, tenant_id)[0]
    assert fila["consumido"] == 30
    assert fila["limite"] == 100
    assert fila["pct"] == 30.0
    assert fila["sin_limite"] is False
    assert fila["ajuste"] == "cuota_correos_mes"


@pytest.mark.db
def test_sin_tope_se_dice_sin_limite_y_no_un_porcentaje_inventado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.consumo import medido_aqui, registrar_medidor

    registrar_medidor("email", lambda _db, _t: (30, "cuota_correos_mes"))

    fila = medido_aqui(db, tenant_id)[0]
    assert fila["sin_limite"] is True
    assert fila["pct"] is None, "un porcentaje sobre un límite que no existe no significa nada"


@pytest.mark.db
def test_un_medidor_roto_no_tumba_a_los_demas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una métrica rota no puede dejar sin panel a las otras cinco. Y se dice en
    su fila, que es distinto de desaparecer."""
    from crmcore.consumo import medido_aqui, registrar_medidor

    def _rota(_db: Any, _t: UUID) -> tuple[int, str]:
        raise RuntimeError("la tabla no está")

    registrar_medidor("rota", _rota)
    registrar_medidor("sana", lambda _db, _t: (7, "cuota_registros"))

    filas = {f["metrica"]: f for f in medido_aqui(db, tenant_id)}
    assert filas["rota"]["legible"] is False
    assert "no se ha podido medir" in filas["rota"]["porque"]
    assert filas["sana"]["consumido"] == 7


# ── La suma del gateway ───────────────────────────────────────────────────


def _gateway_con(respuestas: dict[str, Any]) -> Any:
    """Un gateway con destinos falsos que contestan lo que se le diga.

    `respuestas[servicio]` puede ser un dict —lo que publica ese módulo— o una
    excepción, para el caso que importa: el servicio que no contesta.
    """
    from crmcore import rutas_de_api as rutas

    from services.gateway import api

    def responder(peticion: httpx.Request) -> httpx.Response:
        nombre = peticion.url.host
        valor = respuestas[nombre]
        if isinstance(valor, Exception):
            raise valor
        return httpx.Response(200, json=valor)

    api._cliente = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    api._destinos = {
        nombre: rutas.Destino(servicio=nombre, url_base=f"http://{nombre}") for nombre in respuestas
    }
    return api


async def _pedir_consumo() -> dict[str, Any]:
    from crmcore.authz.principal import Principal

    from services.gateway import api

    principal = Principal(id=uuid4(), tipo="usuario", tenant_id=uuid4())
    return await api.consumo_del_tenant(None, principal)  # type: ignore[arg-type]


async def test_suma_lo_de_cada_modulo_y_dice_de_donde_sale() -> None:
    api = _gateway_con(
        {
            "party": {"metricas": [_m("registros", 40, 100)]},
            "sales": {"metricas": [_m("registros", 25, 100)]},
        }
    )
    assert api is not None

    salida = await _pedir_consumo()
    registros = salida["metricas"][0]
    assert registros["consumido"] == 65
    # Con el desglose: un total sin decir de dónde sale no se puede cuadrar con
    # lo que el cliente ve en cada pantalla.
    assert registros["por_modulo"] == {"party": 40, "sales": 25}
    assert salida["completo"] is True


async def test_un_servicio_que_no_contesta_NO_vale_cero() -> None:
    """La regla que decide si este panel sirve para algo.

    Un cero es una afirmación falsa: dice «no has gastado nada». Y un cliente que
    ve ceros llega al tope sin haber visto subir el número nunca.
    """
    _gateway_con(
        {
            "party": {"metricas": [_m("registros", 40, 100)]},
            "sales": httpx.ConnectError("sales no responde"),
        }
    )

    salida = await _pedir_consumo()

    assert salida["completo"] is False, "un total al que le falta un módulo no es un total"
    assert salida["no_leidos"] == ["sales"]
    # Y lo que sí se leyó se enseña: no leer un módulo no puede dejar sin panel.
    assert salida["metricas"][0]["consumido"] == 40
    assert "sales" not in salida["metricas"][0]["por_modulo"]


async def test_una_metrica_rota_de_un_modulo_sano_tambien_se_dice() -> None:
    """El módulo contesta, pero una de sus métricas no se pudo medir. Sumar el
    resto y callar ésa daría un total que parece completo."""
    _gateway_con(
        {
            "party": {
                "metricas": [
                    _m("registros", 40, 100),
                    {"metrica": "almacenamiento_mb", "legible": False, "porque": "no va"},
                ]
            }
        }
    )

    salida = await _pedir_consumo()
    assert salida["completo"] is False
    assert salida["no_leidos"] == ["party/almacenamiento_mb"]


async def test_los_topes_no_se_suman() -> None:
    """Sumar topes daría un límite que no existe en ninguna parte.

    Las cuotas son por módulo: 100 en `party` y 100 en `sales` no son 200, son
    dos topes distintos, y cada uno corta por su lado.
    """
    _gateway_con(
        {
            "party": {"metricas": [_m("registros", 40, 100)]},
            "sales": {"metricas": [_m("registros", 25, 50)]},
        }
    )

    registros = (await _pedir_consumo())["metricas"][0]
    assert "limite" not in registros
    assert registros["topes_por_modulo"] == {"party": 100, "sales": 50}


def _m(metrica: str, consumido: int, limite: int) -> dict[str, Any]:
    return {
        "metrica": metrica,
        "legible": True,
        "consumido": consumido,
        "limite": limite,
        "sin_limite": limite <= 0,
        "pct": round(consumido / limite * 100, 1),
        "ajuste": f"cuota_{metrica}",
    }
