#!/usr/bin/env python3
"""Las cifras de «lo nuestro» en docs/COMPARATIVA-SALESFORCE.md, recontadas.

    python scripts/medir_comparativa.py            # cifras en texto
    python scripts/medir_comparativa.py --json     # lo mismo, en JSON
    python scripts/medir_comparativa.py --api      # además, la API viva (importa los 14 servicios)

**Por qué existe.** La comparativa se reescribe cada pocas semanas y cada cifra
tiene que poder volver a contarse igual. Todo lo que cuenta este guion sale del
repositorio, sin pila ni base de datos; cada número lleva al lado qué recorre,
para que «cero» no pueda significar «no miré» (cuenta los ficheros leídos).

Qué cuenta y cómo:

- **Capacidades**: entradas con `id` y `estado` en `docs/catalogo/catalogo.yaml`.
- **Con pantalla**: la misma regla que `tests/unit/test_cada_capacidad_tiene_pantalla.py`
  (se importa de ahí, no se copia): hechas, sin `svc: docs` ni
  `sin_pantalla_porque`, cuyo identificador nombra un fichero del front que no
  es de pruebas, quitando los párrafos de «lo que esta pantalla NO declara».
- **Con prueba que las nombre**: el identificador, en su forma `CRM-00.01.02.03`
  o `crm_00_01_02_03`, aparece en un fichero de pruebas: `tests/**/*.py` o un
  `*.test.ts(x)` / `frontend/src/pruebas/**` del front. Un sitio del código que
  la cite NO cuenta aquí (el gate de trazabilidad sí lo admite).
- **Vistas**: campo `visto` del catálogo; «en el navegador» si el texto lo dice
  (`EN EL NAVEGADOR`, `en el navegador`, `VISTO EN`), «auditada» si dice
  `AUDITADO`. Fecha: la primera `AAAA-MM-DD` de cada tramo separado por `||`.
- **API sellada**: `docs/contrato-publicado.json` (método + ruta por servicio).
  Con `--api`, además, las operaciones que publican hoy los servicios
  (`scripts/sellar_contrato.operaciones`, que lee `app.openapi()`).
"""

from __future__ import annotations

import collections
import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
FRONT = RAIZ / "frontend" / "src"
RE_ID = re.compile(r"CRM-(\d\d)\.(\d\d)\.(\d\d)\.(\d\d)")
RE_ID_PRUEBA = re.compile(r"crm_(\d\d)_(\d\d)_(\d\d)_(\d\d)", re.IGNORECASE)
RE_FECHA = re.compile(r"(20\d\d-\d\d-\d\d)")


def _capacidades() -> list[dict]:
    catalogo = yaml.safe_load((RAIZ / "docs/catalogo/catalogo.yaml").read_text(encoding="utf-8"))
    return [
        {**cap, "_modulo": modulo.get("nombre", "")}
        for modulo in catalogo["modulos"]
        for seccion in modulo["secciones"]
        for funcion in seccion["funciones"]
        for cap in funcion["capacidades"]
    ]


def _gate_de_pantallas():
    ruta = RAIZ / "tests/unit/test_cada_capacidad_tiene_pantalla.py"
    spec = importlib.util.spec_from_file_location("gate_pantallas", ruta)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ficheros_de_prueba() -> list[Path]:
    py = list((RAIZ / "tests").rglob("*.py"))
    front = [p for p in FRONT.rglob("*.ts*") if "/pruebas/" in str(p) or ".test." in p.name]
    return py + front


def _ids_en_pruebas(ficheros: list[Path]) -> set[str]:
    ids: set[str] = set()
    for p in ficheros:
        texto = p.read_text(encoding="utf-8", errors="ignore")
        ids.update("CRM-{}.{}.{}.{}".format(*m) for m in RE_ID.findall(texto))
        ids.update("CRM-{}.{}.{}.{}".format(*m) for m in RE_ID_PRUEBA.findall(texto))
    return ids


def medir(con_api: bool = False) -> dict:
    caps = _capacidades()
    hechas = [c for c in caps if c.get("estado") == "hecho"]
    por_estado = collections.Counter(c.get("estado") for c in caps)
    por_crit = collections.Counter(c.get("c") for c in hechas)

    # Pantalla: la regla del gate, importada.
    gate = _gate_de_pantallas()
    exigibles = gate._capacidades_hechas()
    sin_pantalla = gate._sin_pantalla()
    excluidas = [c for c in hechas if c.get("sin_pantalla_porque")]
    de_docs = [c for c in hechas if c.get("svc") == "docs"]

    ficheros = _ficheros_de_prueba()
    en_pruebas = _ids_en_pruebas(ficheros)
    con_prueba = [c for c in hechas if c["id"] in en_pruebas]

    con_visto = [c for c in hechas if c.get("visto")]
    navegador = [
        c
        for c in con_visto
        if re.search(r"en el navegador|VISTO EN|visto en el navegador", c["visto"], re.IGNORECASE)
    ]
    auditadas = [c for c in con_visto if "AUDITADO" in c["visto"]]
    ultima_fecha: collections.Counter[str] = collections.Counter()
    desde_05_11 = 0
    for c in con_visto:
        fechas = []
        for tramo in str(c["visto"]).split("||"):
            m = RE_FECHA.search(tramo)
            if m:
                fechas.append(m.group(1))
        if fechas:
            f = max(fechas)
            ultima_fecha[f[:7]] += 1
            if f >= "2026-11-05":
                desde_05_11 += 1

    por_modulo: dict[str, dict] = {}
    for c in hechas:
        mod_id = c["id"][4:6]
        d = por_modulo.setdefault(
            mod_id, {"nombre": c["_modulo"], "hechas": 0, "con_prueba": 0, "visto": 0}
        )
        d["hechas"] += 1
        d["con_prueba"] += c["id"] in en_pruebas
        d["visto"] += bool(c.get("visto"))

    sello = json.loads((RAIZ / "docs/contrato-publicado.json").read_text())
    salida = {
        "capacidades": len(caps),
        "por_estado": dict(por_estado),
        "no_hechas": [(c["id"], c["t"]) for c in caps if c.get("estado") != "hecho"],
        "hechas_por_criticidad": dict(por_crit),
        "pantalla": {
            "exigibles": len(exigibles),
            "con_pantalla": len(exigibles) - len(sin_pantalla),
            "sin_pantalla": list(sin_pantalla),
            "excluidas_con_motivo": len(excluidas),
            "de_docs": len(de_docs),
        },
        "pruebas": {
            "ficheros_recorridos": len(ficheros),
            "hechas_con_prueba_que_las_nombra": len(con_prueba),
        },
        "visto": {
            "con_visto": len(con_visto),
            "en_el_navegador": len(navegador),
            "auditadas": len(auditadas),
            "ultima_fecha_desde_05_11": desde_05_11,
            "ultima_fecha_por_mes": dict(sorted(ultima_fecha.items())),
        },
        "por_modulo": por_modulo,
        "api_sellada": {
            "total": sum(len(v) for v in sello.values()),
            "servicios": len(sello),
        },
        "front": {
            "rutas_app": len(
                re.findall(r'path="', (FRONT / "App.tsx").read_text(encoding="utf-8"))
            ),
            "paginas": len(
                [p for p in (FRONT / "paginas").glob("*.tsx") if ".test." not in p.name]
            ),
        },
    }
    if con_api:
        from scripts.sellar_contrato import operaciones

        hoy = operaciones()
        salida["api_viva"] = {
            "total": sum(len(v) for v in hoy.values()),
            "por_servicio": {k: len(v) for k, v in hoy.items()},
        }
    return salida


def main() -> int:
    datos = medir(con_api="--api" in sys.argv)
    if "--json" in sys.argv:
        print(json.dumps(datos, ensure_ascii=False, indent=1))
        return 0
    p, v, pr = datos["pantalla"], datos["visto"], datos["pruebas"]
    print(f"Capacidades: {datos['capacidades']} {datos['por_estado']}")
    print(f"  hechas por criticidad: {datos['hechas_por_criticidad']}")
    print(f"  no hechas: {datos['no_hechas']}")
    print(
        f"Pantalla: {p['con_pantalla']} de {p['exigibles']} exigibles "
        f"(+{p['excluidas_con_motivo']} sin pantalla con motivo, {p['de_docs']} de docs); "
        f"sin pantalla: {p['sin_pantalla']}"
    )
    print(
        f"Prueba que las nombra: {pr['hechas_con_prueba_que_las_nombra']} "
        f"({pr['ficheros_recorridos']} ficheros de prueba leídos)"
    )
    print(
        f"Visto: {v['con_visto']} con visto, {v['en_el_navegador']} en el navegador, "
        f"{v['auditadas']} auditadas, {v['ultima_fecha_desde_05_11']} con fecha >= 05-11; "
        f"por mes: {v['ultima_fecha_por_mes']}"
    )
    print(f"API sellada: {datos['api_sellada']}")
    if "api_viva" in datos:
        print(f"API viva: {datos['api_viva']['total']} {datos['api_viva']['por_servicio']}")
    print(f"Front: {datos['front']}")
    for m, d in sorted(datos["por_modulo"].items()):
        print(
            f"  {m} {d['nombre'][:40]:40} hechas {d['hechas']:4} prueba {d['con_prueba']:4} visto {d['visto']:4}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
