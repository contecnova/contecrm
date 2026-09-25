#!/usr/bin/env python3
"""Genera `.env.example` a partir de los `Settings` reales.

Escribirlo a mano garantiza que se quede desfasado: alguien añade un ajuste, no
actualiza el fichero, y al mes siguiente el `.env.example` describe un sistema
que ya no existe. Aquí se genera del código, con el comentario que acompaña a
cada campo en su mixin, así que la explicación de un ajuste vive **junto al
ajuste** y llega sola a la documentación.

    python scripts/gen_env_example.py            # escribe .env.example
    python scripts/gen_env_example.py --check    # falla si está desfasado (gate)

El modo `--check` es lo que engancha el gate de pre-commit: si añades un campo y
no regeneras, el commit te lo dice.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MIXINS = RAIZ / "packages/crmcore/crmcore/config_parts"
SALIDA = RAIZ / ".env.example"

# Orden en que aparecen las secciones. Fijo y no alfabético: el orden en que se
# configura un despliegue tiene sentido (identidad del servicio, base de datos,
# tenancy…) y el alfabético lo destruye.
#
# Es un orden PREFERENTE, no una lista blanca. Lo era, y el resultado fue que
# cuatro grupos enteros —almacén, servicios de la casa, explotación y corpus
# documental— no salían en `.env.example`: el módulo existía, el ajuste
# funcionaba, y el fichero que se supone que documenta la configuración no lo
# mencionaba. El gate comparaba el fichero con lo generado, así que estaba en
# verde omitiendo lo mismo que el generador. Ahora lo que no esté aquí se añade
# al final en vez de desaparecer.
ORDEN = ["_app", "_db", "_tenancy", "_bus", "_auth", "_limits", "_obs", "_security"]

TITULOS = {
    "_app": "Identidad del servicio y red",
    "_db": "Base de datos y aislamiento en el motor",
    "_tenancy": "Multi-tenancy, cuotas y residencia",
    "_bus": "Bus de eventos, outbox y webhooks",
    "_auth": "Identidad: tokens, sesiones, MFA y federación",
    "_limits": "Límites, resiliencia y topes de proceso",
    "_obs": "Observabilidad: logs, métricas, trazas y auditoría",
    "_security": "Protección del dato: cifrado, secretos y cabeceras",
    "_almacen": "Almacén de ficheros y adjuntos",
    "_servicio": "Servicios de la casa y arranque",
    "_intelligence": "Explotación delegada en contecintelligence (RT-4)",
    "_documental": "Corpus documental delegado en contecmind (RT-5)",
    "_chat": "Chat interno: el flujo en vivo",
    "_salud": "Salud de cuenta: pesos, umbrales y bandas",
}


def _modulos() -> list[str]:
    """Todos los grupos de configuración, en el orden preferente y sin perder ninguno."""
    presentes = sorted(r.stem for r in MIXINS.glob("_*.py") if r.stem != "__init__")
    return [m for m in ORDEN if m in presentes] + [m for m in presentes if m not in ORDEN]


def _comentarios_previos(lineas: list[str], linea_campo: int) -> list[str]:
    """Comentarios inmediatamente encima de la definición de un campo."""
    comentarios: list[str] = []
    i = linea_campo - 2  # 0-based, y la línea anterior a la del campo
    while i >= 0:
        texto = lineas[i].strip()
        if texto.startswith("#"):
            comentarios.insert(0, texto.lstrip("#").strip())
            i -= 1
        elif not texto:
            break
        else:
            break
    # Las cabeceras de bloque (`── Pool ──`) no describen el campo concreto: se
    # quitan para que el comentario que quede sea el suyo.
    return [c for c in comentarios if not c.startswith("──")]


# Tipos que no pueden contener un secreto. Sin esta lista, `dms_token_ttl_s`
# —un entero de segundos— salía como `CAMBIAME` solo porque su nombre lleva
# «token» dentro, y quien copiara el fichero se encontraba el servicio negándose
# a arrancar por un número mal puesto.
TIPOS_NO_SECRETOS = {"int", "float", "bool"}


def _tipo_de(nodo: ast.AnnAssign) -> str:
    anotacion = nodo.annotation
    if isinstance(anotacion, ast.Name):
        return anotacion.id
    if isinstance(anotacion, ast.Subscript) and isinstance(anotacion.value, ast.Name):
        return anotacion.value.id
    return ""


# Tipos para los que una línea `CLAVE=` es un valor legítimo: la cadena vacía.
# Para todo lo demás —un entero, un booleano, un diccionario— la cadena vacía NO
# es un valor, es un error de arranque: pydantic intenta parsearla y falla, y el
# servicio no levanta.
#
# Esto pasó de verdad: un `.env` recién copiado del ejemplo no arrancaba, y el
# mensaje —«error parsing value for field ...»— no dejaba claro que el problema
# era el fichero de ejemplo y no la configuración de quien lo copió.
TIPOS_QUE_ADMITEN_VACIO = {"str", "SecretStr"}

# Tipos que pydantic-settings considera **complejos**: no los lee como texto,
# les aplica `json.loads`. Por eso un `DMS_SCOPES=documents:read` —que parece lo
# natural— revienta el arranque con «error parsing value for field», y por eso
# aquí se escriben en JSON: `DMS_SCOPES=["documents:read"]`.
TIPOS_COMPLEJOS = {"list", "tuple", "set", "frozenset", "dict", "List", "Tuple", "Dict"}


def _es_complejo(nodo: ast.AnnAssign) -> bool:
    """¿Lo va a leer pydantic-settings como JSON en vez de como texto?"""
    nombres = {n.id for n in ast.walk(nodo.annotation) if isinstance(n, ast.Name)}
    return bool(nombres & TIPOS_COMPLEJOS)


def _admite_vacio(nodo: ast.AnnAssign) -> bool:
    if _es_complejo(nodo):
        # Ni siquiera un `Optional[list[str]]`: la cadena vacía no es JSON.
        return False
    # Solo el texto admite la cadena vacía. Un `int | None` tampoco: pydantic
    # recibe `""`, no `None`, e intenta convertirlo a entero.
    nombres = {n.id for n in ast.walk(nodo.annotation) if isinstance(n, ast.Name)}
    return bool(nombres & TIPOS_QUE_ADMITEN_VACIO)


def _formatear(valor: object) -> str:
    """Cómo se escribe un valor en el fichero, según cómo lo vaya a leer pydantic."""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    # Una lista, una tupla o un diccionario se escriben en JSON, que es como
    # los lee pydantic-settings. Ni el `repr` de Python —`('documents:read',)`—
    # ni la lista separada por comas son valores válidos: las dos formas
    # rompen el arranque con «error parsing value for field».
    if isinstance(valor, (list, tuple, set, frozenset, dict)):
        return json.dumps(
            sorted(valor) if isinstance(valor, (set, frozenset)) else valor,
            ensure_ascii=False,
        )
    return "" if valor is None else str(valor)


def _alias_de(nodo: ast.AnnAssign) -> str:
    """El `alias=` del `Field(...)`, si lo tiene. Es el nombre real del ajuste."""
    if not isinstance(nodo.value, ast.Call):
        return ""
    for clave in nodo.value.keywords:
        if clave.arg == "alias" and isinstance(clave.value, ast.Constant):
            return str(clave.value.value)
    return ""


def _valor_ejemplo(nodo: ast.AnnAssign, nombre: str) -> str:
    """Valor de ejemplo. Nunca un secreto real, ni siquiera de desarrollo."""
    es_secreto = any(p in nombre for p in ("secret", "password", "key", "token"))
    if es_secreto and _tipo_de(nodo) not in TIPOS_NO_SECRETOS:
        if "url" in nombre:
            return ""
        return "CAMBIAME"
    if nodo.value is None:
        return ""
    try:
        if isinstance(nodo.value, ast.Call):  # Field(default, ...)
            interno = None
            if nodo.value.args:
                interno = nodo.value.args[0]
            else:
                for kw in nodo.value.keywords:
                    if kw.arg == "default":
                        interno = kw.value
            if interno is None:
                return ""
            return _formatear(ast.literal_eval(interno))
        return _formatear(ast.literal_eval(nodo.value))
    except (ValueError, TypeError, SyntaxError):
        return ""


def generar() -> str:
    partes: list[str] = [
        "# ═══════════════════════════════════════════════════════════════════",
        "#  contecrm — configuración",
        "# ═══════════════════════════════════════════════════════════════════",
        "#",
        "# GENERADO por `python scripts/gen_env_example.py`. No se edita a mano:",
        "# la explicación de cada ajuste vive junto a su campo en",
        "# `packages/crmcore/crmcore/config_parts/*.py`, y de ahí sale esto. Si",
        "# editas aquí, el siguiente `--check` lo revierte.",
        "#",
        "# Copia este fichero a `.env` y cambia lo que marque CAMBIAME. `.env`",
        "# NUNCA se commitea: está en .gitignore.",
        "#",
        "# Todo ajuste es una variable de entorno. Los que además se pueden",
        "# cambiar en caliente por tenant, sin reiniciar, están en",
        "# `crmcore/runtime/keys.py` y se editan desde la consola de",
        "# administración: ahí el valor de aquí es solo el punto de partida.",
        "",
    ]

    for modulo in _modulos():
        ruta = MIXINS / f"{modulo}.py"
        if not ruta.exists():
            continue
        fuente = ruta.read_text(encoding="utf-8")
        lineas = fuente.splitlines()
        arbol = ast.parse(fuente)

        partes.append("")
        partes.append(
            f"# ── {TITULOS.get(modulo, modulo)} "
            + "─" * max(0, 60 - len(TITULOS.get(modulo, modulo)))
        )
        partes.append("")

        for clase in [n for n in arbol.body if isinstance(n, ast.ClassDef)]:
            for nodo in clase.body:
                if not isinstance(nodo, ast.AnnAssign) or not isinstance(nodo.target, ast.Name):
                    continue
                nombre = nodo.target.id
                if nombre.startswith("_") or nombre == "model_config":
                    continue
                # El alias manda sobre el nombre del campo: un ajuste declarado
                # como `x_bruto` con `alias="x"` se lee del entorno como `X`, y
                # escribir aquí `X_BRUTO` documentaría una variable que nadie
                # lee —y dejaría la de verdad sin documentar—.
                nombre = _alias_de(nodo) or nombre
                for comentario in _comentarios_previos(lineas, nodo.lineno):
                    # Una línea de comentario vacía se escribe `#` a secas. Con
                    # el espacio, el gancho `trailing-whitespace` la recortaba
                    # al commitear y acto seguido el gate `env-example` decía
                    # que el fichero estaba desfasado: dos gates peleándose por
                    # el mismo fichero y ningún commit posible.
                    partes.append(f"# {comentario}" if comentario else "#")
                valor = _valor_ejemplo(nodo, nombre)
                if valor == "" and not _admite_vacio(nodo):
                    # Sin valor no es lo mismo que valor vacío. Comentada, el
                    # servicio usa su valor por defecto —que es el bueno— y
                    # quien quiera cambiarla solo tiene que quitar la almohadilla.
                    partes.append("# (sin valor: usa el de por defecto)")
                    partes.append(f"# {nombre.upper()}=")
                else:
                    partes.append(f"{nombre.upper()}={valor}")
                partes.append("")

    return "\n".join(partes).rstrip() + "\n"


def main() -> int:
    contenido = generar()
    if "--check" in sys.argv:
        actual = SALIDA.read_text(encoding="utf-8") if SALIDA.exists() else ""
        if actual != contenido:
            print(
                "`.env.example` está desfasado respecto de los Settings.\n"
                "Regenéralo:  python scripts/gen_env_example.py",
                file=sys.stderr,
            )
            return 1
        print(".env.example al día")
        return 0
    SALIDA.write_text(contenido, encoding="utf-8")
    print(f"Escrito {SALIDA.relative_to(RAIZ)} ({contenido.count(chr(10))} líneas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
