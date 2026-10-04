"""Un ajuste que no lee nadie es una promesa en la pantalla de configuración.

El 30-09-2026 había **diez** de 172 así: declarados, con su rango, exportados al
`.env.example`, documentados en el manual de referencia… y sin una sola línea de
código que los consultara. El cliente los cambiaba y no pasaba nada.

Y no eran menores:

    webhook_firma_ventana_s   la ventana anti-reenvío de los webhooks
    cb_umbral_fallos          cuándo abre el cortacircuitos
    cb_reposo_s               cuánto se queda abierto
    degradacion_umbral_pool   cuándo se difiere lo no crítico
    sso_margen_reloj_s        el desfase de reloj admitido con el IdP
    composite_max_ops         el tope de una petición compuesta
    webhook_max_payload_kb    el tamaño máximo que se entrega
    inbox_retencion_dias      cuánto se guarda la bandeja de entrada
    request_timeout_s         cuándo se corta una petición desbocada
    health_check_timeout_s    cuándo se rinde el readiness
    salud_recalculo_horas     cada cuánto se recalcula la salud

Cinco de ellos tenían además **una constante haciendo su trabajo** con otro
valor, así que la pantalla decía una cosa y el sistema aplicaba otra.

Esto lo impide para el siguiente.

**Cuenta el acceso por nombre COMPUESTO**, que es donde la primera medición se
equivocó: `getattr(s, f"rpo_minutos_{tier}")` nunca contiene la cadena
`rpo_minutos_estandar`, así que un grep literal daba 23 sin lector cuando eran
10. Acusar a trece de decorativos sin serlo habría costado un día de trabajo
inútil.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Suelo de ajustes encontrados. Sin esto, un cambio en cómo se declaran dejaría
# la lista vacía y la prueba pasaría en verde sin haber mirado nada. Medido el
# 30-09-2026: 174.
SUELO_DE_AJUSTES = 150

# Ajustes que a propósito no los lee el código de aquí, **con su motivo**. Una
# exención sin motivo es un olvido con permiso.
NO_LOS_LEE_NADIE_A_PROPOSITO: dict[str, str] = {}


def _declarados() -> dict[str, str]:
    """Nombre -> fichero donde se declara."""
    salida: dict[str, str] = {}
    for fichero in (RAIZ / "packages/crmcore/crmcore/config_parts").glob("*.py"):
        for m in re.finditer(
            r"^\s{4}([a-z_][a-z0-9_]*)\s*:\s*[^=]+=\s*Field\(",
            fichero.read_text(encoding="utf-8"),
            re.M,
        ):
            salida[m.group(1)] = fichero.name
    return salida


@lru_cache(maxsize=1)
def _corpus() -> str:
    """Todo el código de producción, leído UNA vez.

    La primera versión lanzaba un `grep` por ajuste: 174 procesos y 35 segundos
    para una comprobación que mira texto. Un guardián no puede ser el coste.
    """
    trozos = []
    for carpeta in ("packages", "services", "scripts"):
        for fichero in (RAIZ / carpeta).rglob("*"):
            if fichero.suffix not in (".py", ".sh") or "__pycache__" in str(fichero):
                continue
            if "config_parts" in str(fichero):
                continue  # la declaración no cuenta como lectura
            trozos.append(fichero.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(trozos)


def _aparece(patron: str) -> bool:
    """Si el patrón sale en algún sitio que no sea la propia declaración."""
    return re.search(patron, _corpus()) is not None


def test_todo_ajuste_declarado_lo_lee_alguien() -> None:
    declarados = _declarados()

    assert len(declarados) >= SUELO_DE_AJUSTES, (
        f"solo se han encontrado {len(declarados)} ajustes declarados, menos del "
        f"suelo de {SUELO_DE_AJUSTES}. La lectura se ha quedado corta y su "
        "resultado no significa nada."
    )

    decorativos: list[str] = []
    for nombre, fichero in sorted(declarados.items()):
        if nombre in NO_LOS_LEE_NADIE_A_PROPOSITO:
            continue
        if _aparece(nombre):
            continue
        # Por nombre compuesto: `getattr(s, f"rpo_minutos_{tier}")`. Se prueban
        # todos los prefijos partidos por `_`.
        trozos = nombre.split("_")
        if any(_aparece(rf'f"{"_".join(trozos[:i])}_\{{') for i in range(1, len(trozos))):
            continue
        decorativos.append(f"{nombre}  ({fichero})")

    assert not decorativos, (
        f"{len(decorativos)} ajustes están declarados, documentados y exportados "
        "al `.env.example`, y **no los lee nadie**. Quien los cambie en la "
        "pantalla de configuración no cambiará nada, y eso es peor que no "
        "ofrecerlos: promete un control que no existe.\n  "
        + "\n  ".join(decorativos)
        + "\n\nO se enchufan, o se quitan, o entran en "
        "NO_LOS_LEE_NADIE_A_PROPOSITO con su motivo escrito."
    )


def test_las_exenciones_dicen_por_que() -> None:
    for nombre, motivo in NO_LOS_LEE_NADIE_A_PROPOSITO.items():
        assert motivo.strip(), f"«{nombre}» está exento y no dice por qué"
