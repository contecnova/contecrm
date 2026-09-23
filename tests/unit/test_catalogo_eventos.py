"""El catálogo de eventos describe el sistema entero, no lo que uno haya importado.

Los eventos de negocio se declaraban en `services/<servicio>/eventos.py`, cada
uno en su productor. Leído en el código parecía correcto; en ejecución no lo
era, porque **ningún proceso importa los ocho módulos**. El servicio de eventos
—que valida a qué se puede suscribir un webhook y publica el AsyncAPI a los
integradores— veía quince tipos de los ciento uno que el sistema emite: dar de
alta un webhook sobre `opportunity.stage.changed` contestaba «hay tipos de
evento que no existen», y el documento entregado a quien integra describía el
quince por ciento del producto.

No se notaba porque el gate que existía comprobaba los eventos de la fase 0 del
Anexo B, que son justo los de plataforma —los que sí estaban en el núcleo—.

Aquí se comprueban las dos mitades del contrato:

  * lo que el código **emite** está declarado, y
  * lo declarado se ve **desde cualquier proceso**, sin importar servicios.
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Llamadas que publican un evento. `emitir` es la del UoW; las otras dos son
# los atajos que usan algunos módulos.
PUBLICADORAS = {"emitir", "emitir_evento", "publicar"}

# Nombres literales que no son tipos de evento aunque lo parezcan: van a otros
# parámetros de la misma llamada.
NO_SON_EVENTOS = {"application/json"}


def _emitidos() -> dict[str, set[str]]:
    """Tipos de evento con nombre literal que el código publica, y dónde."""
    encontrados: dict[str, set[str]] = {}
    for fichero in list((RAIZ / "services").rglob("*.py")) + list(
        (RAIZ / "packages").rglob("*.py")
    ):
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"), str(fichero))
        except SyntaxError:  # pragma: no cover - no debería haberlos
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call):
                continue
            nombre = (
                nodo.func.attr
                if isinstance(nodo.func, ast.Attribute)
                else getattr(nodo.func, "id", "")
            )
            if nombre not in PUBLICADORAS:
                continue
            candidatos = list(nodo.args) + [
                k.value for k in nodo.keywords if k.arg in ("tipo", "asunto", "evento")
            ]
            for arg in candidatos:
                if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                    continue
                valor = arg.value
                if "." not in valor or " " in valor or valor in NO_SON_EVENTOS:
                    continue
                encontrados.setdefault(valor, set()).add(
                    str(fichero.relative_to(RAIZ)) + f":{arg.lineno}"
                )
    return encontrados


def test_todo_lo_que_se_emite_esta_declarado() -> None:
    from crmcore.events.catalogo import obtener

    sin_declarar = {
        tipo: sorted(sitios) for tipo, sitios in _emitidos().items() if obtener(tipo) is None
    }
    assert not sin_declarar, (
        "Eventos que el código emite y el catálogo no declara. Un integrador no "
        "puede suscribirse a ellos y el AsyncAPI no los describe:\n  "
        + "\n  ".join(f"{t} → {', '.join(s)}" for t, s in sorted(sin_declarar.items()))
    )


def test_el_catalogo_completo_se_ve_sin_importar_servicios() -> None:
    """Importar solo el núcleo tiene que bastar para ver todo el catálogo.

    Es la comprobación que faltaba: el registro estaba bien escrito y quien lo
    consultaba veía una porción, porque el resto vivía en módulos que ese
    proceso no importa.

    Se mide en un **proceso aparte** y no recargando el módulo aquí. Recargarlo
    vacía el registro global, y entonces esta prueba dejaba sin eventos a las
    que vinieran después —el gate de contratos entre servicios empezó a decir
    que siete eventos no tenían productor, que es exactamente la clase de fallo
    que esta prueba existe para no tener—. Y de paso el subproceso prueba lo
    que se quería probar: que un proceso que solo importa `crmcore` los ve.
    """
    import subprocess
    import sys

    salida = subprocess.run(
        [
            sys.executable,
            "-c",
            "from crmcore.events.catalogo import todos; print(len(todos()))",
        ],
        capture_output=True,
        text=True,
        cwd=RAIZ,
        check=True,
    )
    total = int(salida.stdout.strip())
    # 111 al escribir esto (10 de plataforma, 86 de los servicios y 15 que se
    # emitían sin declarar en ninguna parte). El suelo va por debajo para que
    # retirar un evento a propósito no rompa el gate, y lo bastante cerca para
    # que volver a repartirlos por los servicios sí.
    assert total >= 105, (
        f"Desde el núcleo solo se ven {total} tipos de evento. Si han vuelto a "
        "declararse dentro de los servicios, el servicio de eventos no los verá "
        "y los webhooks sobre ellos volverán a rechazarse."
    )
