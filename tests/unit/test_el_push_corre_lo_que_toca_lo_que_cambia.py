"""Un push de tres minutos deja de correrse (`QUALITY_GATES`).

Medido el 11-10-2026: el nivel del push costaba **2 min 47 s** con la máquina a
media carga, y la nota del propio fichero decía que debía costar unos 37. De los
167 segundos, 117 eran el recorrido de aislamiento — que construye las catorce
aplicaciones y recorre sus rutas **aunque el commit sólo toque un manual**.

Lo que pasa cuando un push tarda tres minutos no es que se espere: es que se
empuja con `--no-verify`, y entonces no hay red. Así que esto no quita ninguna
comprobación —el nivel completo las corre todas y es el que cierra cada bloque—
sino que cambia **cuándo** corre cada una.

Las dos reglas, y las dos son conservadoras a propósito:

  · un gate se omite sólo si **nada de lo que cambió** está dentro de lo que
    mira;
  · y el recorrido de aislamiento se acota a unos servicios sólo si **todo** lo
    que cambió vive dentro de `services/<x>/`. Un cambio en `packages/` lo
    heredan los catorce, y acotarlo dejaría trece sin mirar — de lo que
    comprueba que ningún cliente ve lo de otro no se puede dejar trece sin
    mirar.

Si no se sabe qué cambió —sin rama remota, recién clonado, `git` que falla— no
se omite nada. Una optimización que se equivoca callando es peor que no tenerla.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[2]


def _preflight() -> Any:
    spec = importlib.util.spec_from_file_location("preflight_push_", RAIZ / "scripts/preflight.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    try:
        spec.loader.exec_module(modulo)
    finally:
        sys.modules.pop(spec.name, None)
    return modulo


def _gate(nombre: str) -> Any:
    return next(g for g in _preflight().GATES if g.nombre == nombre)


# ── Qué gate aporta algo ──────────────────────────────────────────────────


def test_un_gate_sin_alcance_declarado_corre_siempre() -> None:
    """Lo no declarado no se omite: omitir por defecto convertiría cada gate
    nuevo en uno que no corre hasta que alguien se acuerde."""
    pf = _preflight()
    assert pf._aporta_algo(_gate("ruff"), ["docs/manual-1-empezar.md"])


@pytest.mark.parametrize(
    ("gate", "cambios", "corre"),
    [
        ("aislamiento", ["services/sales/api.py"], True),
        ("aislamiento", ["packages/crmcore/crmcore/consumo.py"], True),
        ("aislamiento", ["docs/manual-2-perfiles.md"], False),
        ("aislamiento", ["tests/unit/test_algo.py"], False),
        ("front", ["frontend/src/App.tsx"], True),
        ("front", ["services/sales/api.py"], False),
        ("migraciones", ["alembic/versions/sales/x.py"], True),
        ("migraciones", ["docs/procesos.md"], False),
    ],
)
def test_cada_gate_mira_lo_suyo(gate: str, cambios: list[str], corre: bool) -> None:
    assert _preflight()._aporta_algo(_gate(gate), cambios) is corre


def test_sin_saber_que_cambio_no_se_omite_nada() -> None:
    """Sin rama remota, recién clonado o con `git` roto: se corre todo."""
    pf = _preflight()
    for nombre in ("aislamiento", "front", "migraciones"):
        assert pf._aporta_algo(_gate(nombre), None) is True


def test_un_cambio_mixto_cuenta_para_los_dos() -> None:
    """Tocar el front y un servicio en el mismo push corre los dos."""
    pf = _preflight()
    cambios = ["frontend/src/App.tsx", "services/sales/api.py"]
    assert pf._aporta_algo(_gate("front"), cambios)
    assert pf._aporta_algo(_gate("aislamiento"), cambios)


# ── El acotado por servicio ───────────────────────────────────────────────


def test_un_solo_servicio_se_acota_a_el() -> None:
    pf = _preflight()
    acotado = pf._acotar_a_los_servicios_que_cambiaron(
        _gate("aislamiento"), ["services/sales/api.py", "docs/manual-5-arquitectura.md"]
    )
    assert acotado.comando[-2:] == ["-k", "sales"]


def test_dos_servicios_se_acota_a_los_dos() -> None:
    pf = _preflight()
    acotado = pf._acotar_a_los_servicios_que_cambiaron(
        _gate("aislamiento"), ["services/sales/api.py", "services/party/api.py"]
    )
    assert acotado.comando[-1] == "party or sales"


def test_un_cambio_del_nucleo_no_se_acota_nunca() -> None:
    """**Es la regla que no se puede aflojar.** `packages/` lo heredan los
    catorce servicios: acotar a uno dejaría trece sin comprobar que no dejan ver
    lo de otro cliente."""
    pf = _preflight()
    original = _gate("aislamiento")
    for cambios in (
        ["packages/crmcore/crmcore/consumo.py"],
        ["services/sales/api.py", "packages/crmcore/crmcore/http/deps.py"],
    ):
        assert (
            pf._acotar_a_los_servicios_que_cambiaron(original, cambios).comando == original.comando
        ), cambios


def test_sin_saber_que_cambio_tampoco_se_acota() -> None:
    pf = _preflight()
    original = _gate("aislamiento")
    assert pf._acotar_a_los_servicios_que_cambiaron(original, None).comando == original.comando


def test_muchos_servicios_a_la_vez_no_se_acota() -> None:
    """Pasado un punto, acotar no ahorra y sí añade una expresión larga que
    puede casar de más por parecido de nombre."""
    pf = _preflight()
    original = _gate("aislamiento")
    muchos = [
        f"services/{s}/api.py"
        for s in ("sales", "party", "service", "marketing", "identity", "tenancy", "analytics")
    ]
    assert pf._acotar_a_los_servicios_que_cambiaron(original, muchos).comando == original.comando


def test_solo_el_gate_que_lo_declara_se_acota() -> None:
    """Acotar uno que no esté parametrizado por servicio le pasaría un `-k` que
    no significa nada y dejaría de correr casi todo."""
    pf = _preflight()
    for nombre in ("atributos", "acciones", "contrato-headless", "migraciones"):
        original = _gate(nombre)
        assert not original.por_servicio, f"{nombre} se declara por servicio sin estarlo"
        acotado = pf._acotar_a_los_servicios_que_cambiaron(original, ["services/sales/api.py"])
        assert acotado.comando == original.comando


# ── Lo que no puede pasar ─────────────────────────────────────────────────


def test_el_nivel_completo_no_omite_nada() -> None:
    """Es el que cierra cada bloque y el que tiene que poder decir «pasó
    entero». Si omitiera, ese apunte dejaría de significar nada."""
    fuente = (RAIZ / "scripts/preflight.py").read_text(encoding="utf-8")
    cuerpo = fuente.split("def main(")[1]
    assert '"tests" in tiers and "suite" not in tiers' in cuerpo


def test_lo_omitido_se_dice_y_dice_dónde_se_corre() -> None:
    """Un gate que no corre en silencio da una falsa sensación de cobertura,
    que es peor que no tener el gate."""
    fuente = (RAIZ / "scripts/preflight.py").read_text(encoding="utf-8")
    assert "Fuera de alcance de este push" in fuente
    assert "--todo" in fuente.split("Fuera de alcance de este push")[1][:400]
