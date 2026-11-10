"""Restos de la primera tanda: claves de API, recordar el equipo y consumo.

- `GET /claves-api` devuelve desde dónde se admite cada clave
  (`ips_permitidas`): se guardaba y no salía, así que no se podía revisar si una
  clave estaba restringida o abierta a internet entero.
- El secreto del alta va marcado `x-una-vez` en el contrato: es lo que lee la
  pantalla para enseñarlo una vez, con el aviso de copiarlo.
- Recordar el equipo lee el plazo **del tenant**, como los demás ajustes del
  login: en la entrada el contexto no lleva tenant y se leía sólo el global.
- Un medidor de consumo que falla no arrastra a los demás, y el que cuenta una
  tabla que en este módulo no existe no sale como «no legible».
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from tests.unit.test_reverificacion_y_mfa_adaptativa import (  # noqa: F401
    _cabeceras,
    cliente_identidad,
)

# ── Claves de API ─────────────────────────────────────────────────────────


@pytest.mark.db
def test_la_lista_de_claves_dice_desde_donde_se_admite_cada_una(
    cliente_identidad: Any,  # noqa: F811
    tenant_id: UUID,
    db: Any,
) -> None:
    cli, cab = cliente_identidad, _cabeceras(tenant_id)
    alta = cli.post(
        "/api/v1/claves-api",
        headers=cab,
        json={
            "nombre": "ERP con IP",
            "scopes": ["account:read"],
            "ips_permitidas": ["10.0.0.0/24"],
        },
    )
    assert alta.status_code == 201, alta.text
    assert alta.json()["secreto"], "el alta tiene que devolver el secreto, una vez"
    lista = cli.get("/api/v1/claves-api?revocada_at__vacio=true", headers=cab)
    assert lista.status_code == 200, lista.text
    fila = next(f for f in lista.json()["items"] if f["id"] == alta.json()["id"])
    assert fila["ips_permitidas"] == ["10.0.0.0/24"]
    # Y el secreto no vuelve a salir por ninguna parte.
    assert "secreto" not in fila


def test_el_secreto_del_alta_va_marcado_para_ensenarse_una_vez() -> None:
    """La pantalla de alta lee la marca del contrato: sin ella tiraba la
    respuesta y el secreto, que no se puede volver a pedir, no lo veía nadie."""
    from services.identity.esquemas import ClaveApiCreada

    esquema = ClaveApiCreada.model_json_schema()
    marcados = [n for n, p in esquema["properties"].items() if p.get("x-una-vez")]
    assert marcados == ["secreto"]


# ── Recordar el equipo ────────────────────────────────────────────────────


def test_recordar_el_equipo_lee_el_plazo_del_tenant(monkeypatch: Any) -> None:
    """En la entrada el contexto no lleva tenant: sin ponerlo, `efectivo`
    saltaba el ámbito de la empresa y leía sólo el global."""
    from crmcore.errors import Prohibido
    from crmcore.runtime import settings as rt
    from crmcore.tenancy.context import contexto_actual

    from services.identity import factores

    leidos: list[Any] = []

    def _efectivo(clave: str, *a: Any, **k: Any) -> Any:
        leidos.append((clave, contexto_actual().tenant_id))
        return 0

    monkeypatch.setattr(rt, "efectivo", _efectivo)
    tenant = uuid4()
    with pytest.raises(Prohibido):
        factores.recordar_dispositivo(None, uuid4(), tenant, huella="h")  # type: ignore[arg-type]
    assert leidos == [("dispositivo_confianza_dias", tenant)]


# ── Consumo ───────────────────────────────────────────────────────────────


@pytest.mark.db
def test_un_medidor_que_falla_no_arrastra_a_los_siguientes(db: Any, tenant_id: UUID) -> None:
    """Medido el 09-11-2026: el primero que fallaba dejaba la transacción
    abortada y los siguientes caían todos; tres de cuatro «no legibles»."""
    from crmcore.consumo import limpiar_medidores, medido_aqui, registrar_medidor
    from sqlalchemy import text

    def _sin_tabla(d: Any, _t: Any) -> tuple[int, str]:
        d.execute(text("SELECT count(*) FROM tabla_que_aqui_no_existe"))
        return 0, "cuota_registros"

    def _sql_roto(d: Any, _t: Any) -> tuple[int, str]:
        d.execute(text("SELECT 1/0"))
        return 0, "cuota_registros"

    def _sano(d: Any, _t: Any) -> tuple[int, str]:
        return int(d.execute(text("SELECT 7")).scalar_one()), "cuota_registros"

    limpiar_medidores()
    registrar_medidor("a_sin_tabla", _sin_tabla)
    registrar_medidor("b_roto", _sql_roto)
    registrar_medidor("c_sano", _sano)
    try:
        filas = {f["metrica"]: f for f in medido_aqui(db, tenant_id)}
    finally:
        limpiar_medidores()

    # Lo que en este módulo no se guarda no es una métrica rota: no sale.
    assert "a_sin_tabla" not in filas
    # Lo que de verdad falla se dice, con su motivo…
    assert filas["b_roto"]["legible"] is False
    assert "no se ha podido medir" in filas["b_roto"]["porque"]
    # …y no se lleva por delante a los que vienen detrás.
    assert filas["c_sano"]["legible"] is True and filas["c_sano"]["consumido"] == 7


@pytest.mark.db
def test_el_consumo_del_tenant_junta_los_modulos_y_dice_el_que_no_contesta(
    db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    """La ficha del tenant medía sólo las tablas de tenancy: «0 registros» con
    miles de cuentas en party. Ahora pregunta a cada módulo, y el que no contesta
    sale como no leído, nunca como cero."""
    from crmcore.authz.principal import Principal
    from crmcore.consumo import limpiar_medidores

    from services.tenancy import api

    monkeypatch.setattr(
        api,
        "_consumo_de_los_demas",
        lambda _t, _p: {
            "party": [
                {
                    "metrica": "registros",
                    "legible": True,
                    "consumido": 1200,
                    "limite": 0,
                    "pct": None,
                    "en_aviso": False,
                    "periodo": "2026-11",
                }
            ],
            "sales": "El módulo no responde: su consumo no se ha podido leer",
        },
    )
    limpiar_medidores()
    principal = Principal(id=uuid4(), tipo="usuario", tenant_id=tenant_id)
    filas = api.consumo(tenant_id, db, principal)
    por_modulo = {(f.metrica, f.modulo): f for f in filas}
    assert por_modulo[("registros", "party")].consumido == 1200
    caido = por_modulo[("*", "sales")]
    assert caido.medido is False and "no responde" in caido.porque
