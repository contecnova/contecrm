"""El tenant de demostración (CRM-07.04.05.03).

El front estándar es con lo que se enseña la solución, y enseñarla sobre una
base vacía no enseña nada: lo que hay que ver es cómo se relacionan los
registros, no que existan. Por eso estas pruebas defienden la **coherencia** de
los datos de muestra, no su cantidad.

Y defienden lo otro, que importa más: que sembrar **no se pueda hacer en
producción**. Meter datos de ejemplo en la base de un cliente no se deshace con
un `DELETE` — los eventos ya se han publicado, la auditoría ya lo ha registrado
y los webhooks ya han salido.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[2]


def _modulo() -> Any:
    especificacion = importlib.util.spec_from_file_location(
        "sembrar_demo", RAIZ / "scripts" / "sembrar_demo.py"
    )
    assert especificacion and especificacion.loader
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


def test_los_datos_de_muestra_son_coherentes_entre_si() -> None:
    """Un tenant de muestra con registros sueltos no sirve para enseñar el
    sistema, porque justo lo que hay que enseñar es cómo se relacionan."""
    demo = _modulo()

    empresas = {c["nombre"] for c in demo.CUENTAS_DEMO}

    huerfanos = [c[0] for c in demo.CONTACTOS_DEMO if c[0] not in empresas]
    assert not huerfanos, f"Contactos de empresas que no se siembran: {huerfanos}"

    sueltas = [o[0] for o in demo.OPORTUNIDADES_DEMO if o[0] not in empresas]
    assert not sueltas, f"Oportunidades de cuentas que no se siembran: {sueltas}"

    # Los leads son de empresas que NO son clientes todavía: si coincidieran con
    # una cuenta existente, la demo enseñaría un duplicado y no un lead.
    ya_clientes = [ld[0] for ld in demo.LEADS_DEMO if ld[0] in empresas]
    assert not ya_clientes, f"Leads de empresas que ya son cuentas: {ya_clientes}"


def test_hay_algo_vencido_para_que_se_vea_el_aviso() -> None:
    """Enseñar solo actividades al día esconde justo la mitad del sistema que se
    nota: los avisos y los vencimientos."""
    fuente = (RAIZ / "scripts" / "sembrar_demo.py").read_text("utf-8")
    assert "-3" in fuente and "vencida" in fuente


def test_sembrar_se_niega_en_produccion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Es la condición sin la cual todo lo demás da igual."""
    from crmcore.config import limpiar_cache_settings

    demo = _modulo()
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("SERVICE_NAME", "tenancy")
    monkeypatch.setattr(demo.sys, "argv", ["sembrar_demo.py"])
    limpiar_cache_settings()
    try:
        assert demo.main() == 2
    finally:
        limpiar_cache_settings()


def test_cada_parte_se_ejecuta_donde_tiene_permisos() -> None:
    """En un despliegue real un proceso NO llega a todos los esquemas, y eso es
    el aislamiento funcionando. Cada parte se puede ejecutar por separado."""
    fuente = (RAIZ / "scripts" / "sembrar_demo.py").read_text("utf-8")
    for parte in ("tenant", "usuario", "party", "sales"):
        assert f'"{parte}"' in fuente, f"falta la parte «{parte}»"
    # Y cada una fija su `SERVICE_NAME` y vacía las cachés: sin eso seguiría
    # apuntando al esquema de la anterior.
    assert fuente.count("reset_engine()") >= 3
