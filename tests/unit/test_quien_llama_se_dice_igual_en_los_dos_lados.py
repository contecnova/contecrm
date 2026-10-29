"""Quién hace una llamada se escribe igual en los dos lados (CRM-00.05.02.04).

**Medido el 29-10-2026.** Había tres palabras para la misma idea, en tres
ficheros, y no coincidían:

  * `http.interno` firmaba las llamadas del agente autónomo como «maquina»,
  * `authz.visibilidad` preguntaba por «servicio» para saltarse la
    compartición entre personas,
  * `http.reverificacion` preguntaba por «servicio» o «automatizacion».

«maquina» no casaba con ninguna. Y lo que pasa cuando no casan **no falla**: el
agente llamaba como si fuera una persona, la compartición le aplicaba su filtro,
esa persona no posee ningún registro, y `GET /accounts` le devolvía cero filas
con un 200. El modelo concluía «no hay cuentas» sobre un tenant con sesenta y
cinco, y lo decía con seguridad porque la respuesta era legítima.

Es el mismo agujero que ya se había tapado para las credenciales de
integración, con otra palabra.

Lo que vigila este gate no es que el código esté bonito: es que **no vuelva a
haber una palabra escrita en un sitio que nadie mire en el otro**.
"""

from __future__ import annotations

import re
from pathlib import Path

from crmcore.vocabularios import NO_SON_PERSONAS, TIPOS_DE_PRINCIPAL, es_persona

RAIZ = Path(__file__).resolve().parents[2]

# La cabecera por la que viaja. Se busca por su nombre, no por el de la
# constante, porque lo que cruza el cable es el texto.
CABECERA = "x-crm-tipo"


def test_el_vocabulario_separa_personas_de_lo_que_no_lo_es() -> None:
    assert NO_SON_PERSONAS <= set(TIPOS_DE_PRINCIPAL)
    assert "usuario" in TIPOS_DE_PRINCIPAL and "usuario" not in NO_SON_PERSONAS
    assert es_persona("usuario") is True
    assert es_persona(None) is True, "sin tipo se asume persona: filtra de más, no de menos"
    for tipo in NO_SON_PERSONAS:
        assert es_persona(tipo) is False


def test_lo_que_se_firma_como_agente_esta_en_el_vocabulario() -> None:
    """El valor que escribe el emisor tiene que ser uno de los que se miran.

    Esto es exactamente lo que fallaba: «maquina» se escribía y no estaba.
    """
    from crmcore.http.interno import TIPO_DEL_AGENTE

    assert TIPO_DEL_AGENTE in TIPOS_DE_PRINCIPAL
    assert TIPO_DEL_AGENTE in NO_SON_PERSONAS, (
        "El agente autónomo no es una persona: si se le aplica la compartición "
        "entre usuarios, lee cero filas y no falla."
    )


def test_nadie_compara_el_tipo_de_principal_con_una_cadena_suelta() -> None:
    """Cada comparación suelta es una palabra más que puede no coincidir.

    Se recorre el código de producción buscando comparaciones del atributo
    `tipo` de un principal contra un literal. La forma correcta es preguntarle
    al vocabulario.
    """
    # `tipo == "algo"` o `tipo in ("algo", …)`, sobre `principal` o sobre lo que
    # salga de `getattr(..., "tipo", ...)`.
    sospechoso = re.compile(
        r'(?:principal\.tipo|getattr\(\s*principal\s*,\s*"tipo"[^)]*\))\s*(?:==|in)\s*[("\']'
    )
    culpables: list[str] = []
    recorridos = 0
    for carpeta in ("packages/crmcore/crmcore", "services"):
        for fichero in sorted((RAIZ / carpeta).rglob("*.py")):
            recorridos += 1
            for n, linea in enumerate(fichero.read_text(encoding="utf-8").splitlines(), 1):
                if sospechoso.search(linea):
                    culpables.append(f"{fichero.relative_to(RAIZ)}:{n}: {linea.strip()[:90]}")
    # Que diga cuántos ha mirado: una sonda que no recorre nada parece verde.
    assert recorridos > 300, f"solo se han recorrido {recorridos} ficheros"
    assert not culpables, (
        "Comparan el tipo de principal con una cadena en vez de preguntar al "
        "vocabulario (`crmcore.vocabularios.es_persona`):\n  " + "\n  ".join(culpables)
    )


def test_quien_escribe_la_cabecera_usa_un_valor_del_vocabulario() -> None:
    """Un literal nuevo escrito en `x-crm-tipo` vuelve a abrir el agujero."""
    escrituras: list[str] = []
    for carpeta in ("packages/crmcore/crmcore", "services"):
        for fichero in sorted((RAIZ / carpeta).rglob("*.py")):
            texto = fichero.read_text(encoding="utf-8")
            if CABECERA not in texto and "H_TIPO" not in texto:
                continue
            for n, linea in enumerate(texto.splitlines(), 1):
                hallado = re.search(r'H_TIPO:\s*"([a-z_]+)"', linea)
                if hallado:
                    escrituras.append(f"{fichero.relative_to(RAIZ)}:{n}:{hallado.group(1)}")
    for escritura in escrituras:
        valor = escritura.rsplit(":", 1)[-1]
        assert valor in TIPOS_DE_PRINCIPAL, (
            f"«{valor}» se escribe en {CABECERA} y no está en el vocabulario, "
            f"así que no lo mira nadie ({escritura})"
        )
