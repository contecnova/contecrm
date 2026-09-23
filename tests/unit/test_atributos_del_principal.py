"""Nadie lee del principal un campo que no existe.

Había **34 usos de `principal.usuario_id`** repartidos por nueve servicios, y
ese atributo no existe: se llama `id`. Cada uno de esos endpoints reventaba con
`AttributeError` y devolvía un 500 en cuanto alguien lo llamaba — la pantalla de
estado, la de cuadros de mando y la consola de agente, entre otras.

No lo cazaba nada. Python resuelve los atributos al ejecutar, así que un nombre
mal escrito solo se nota si esa línea llega a correr, y ninguna prueba pasaba por
ahí. El gate lo mira en el código: recorre los servicios buscando accesos sobre
una variable llamada `principal` y comprueba que el nombre exista de verdad en
la clase.

Es una comprobación estática sobre un nombre de variable, con lo que eso tiene
de imperfecto: si alguien llama `p` al principal, este gate no lo ve. Vale igual,
porque el convenio del repositorio es llamarlo `principal` —lo exige la firma de
las dependencias— y porque el coste de la comprobación es cero.
"""

from __future__ import annotations

import ast
from pathlib import Path

from crmcore.authz.principal import Principal

RAIZ = Path(__file__).resolve().parents[2]
CAMPOS = {f for f in dir(Principal) if not f.startswith("_")}


def test_ningun_servicio_lee_un_campo_inexistente_del_principal() -> None:
    malos: list[str] = []
    for fichero in sorted((RAIZ / "services").rglob("*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), str(fichero))
        for nodo in ast.walk(arbol):
            if (
                isinstance(nodo, ast.Attribute)
                and isinstance(nodo.value, ast.Name)
                and nodo.value.id == "principal"
                and nodo.attr not in CAMPOS
            ):
                malos.append(f"{fichero.relative_to(RAIZ)}:{nodo.lineno}: principal.{nodo.attr}")

    assert not malos, (
        "Accesos a campos que el principal no tiene:\n  "
        + "\n  ".join(malos)
        + f"\n\nLos que hay son: {', '.join(sorted(CAMPOS))}."
        + "\n\nNo lo caza nada en ejecución hasta que esa línea corre, y entonces es un 500."
    )
