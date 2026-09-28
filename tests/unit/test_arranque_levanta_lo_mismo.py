"""El arranque documentado levanta lo mismo que el despliegue.

**No lo levantaba.** `docker compose` arrancaba veinte procesos y
`./setup.sh arrancar` —el camino documentado por defecto— once. Faltaban tres
servicios de API enteros —`service`, `marketing`, `intelligence`, añadidos al
producto después y que nadie puso en la lista— y **los seis workers**:
`setup.sh` no mencionaba la palabra «worker» ni una sola vez.

Lo que eso significaba para quien seguía el manual: un sistema que **arranca,
contesta y se ve perfecto**, sin casos, sin marketing, sin IA, y en el que
**nada asíncrono ocurre jamás** — los trabajos se encolan y no pasan nunca, sin
error.

Ya se había cazado una vez por el lado de Docker; el aviso sigue escrito en el
`docker-compose.yml`. Nadie miró el lado nativo. Por eso esto es una prueba y no
un repaso: las dos listas se separan solas cada vez que alguien añade un
servicio, y separarse **no rompe nada** — que es exactamente por lo que no se
corrige nunca.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Lo que el compose arranca y NO es un servicio del producto.
INFRAESTRUCTURA = {
    "postgres",
    "nats",
    "redis",
    "prometheus",
    "tempo",
    "grafana",
    # El front, que en nativo lo levanta `./setup.sh front` aparte.
    "consola",
}

# Claves del bloque YAML de anclas que el barrido ve como si fueran servicios.
NO_SON_SERVICIOS = {
    "build",
    "image",
    "restart",
    "profiles",
    "environment",
    "healthcheck",
    "command",
    "ports",
    "volumes",
    "depends_on",
}


def _del_compose() -> set[str]:
    texto = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
    nombres = set(re.findall(r"^  ([a-z][a-z0-9-]*):", texto, re.M))
    return nombres - INFRAESTRUCTURA - NO_SON_SERVICIOS


def _workers_declarados() -> list[str]:
    """Las entradas tal como están escritas: `servicio:modulo`."""
    texto = (RAIZ / "setup.sh").read_text(encoding="utf-8")
    encaje = re.search(r"^WORKERS=\(([^)]*)\)", texto, re.M)
    assert encaje, "setup.sh ya no declara WORKERS"
    return encaje.group(1).split()


def _del_setup() -> tuple[set[str], set[str]]:
    texto = (RAIZ / "setup.sh").read_text(encoding="utf-8")
    servicios = re.search(r"^SERVICIOS=\(([^)]*)\)", texto, re.M)
    workers = re.search(r"^WORKERS=\(([^)]*)\)", texto, re.M)
    assert servicios, "setup.sh ya no declara SERVICIOS: esta prueba no está mirando nada"
    assert workers, (
        "setup.sh ya no declara WORKERS. Si se han quitado, el arranque nativo "
        "vuelve a no ejecutar nada asíncrono y nadie lo notará: el sistema "
        "arranca, contesta y los trabajos se encolan para siempre."
    )

    # En el compose los workers se llaman `servicio-modulo` y sin el sufijo
    # `_worker` —`party-trabajos`, no `party-trabajos_worker`—, mientras aquí se
    # declaran con el nombre real del módulo, que es lo que hay que ejecutar. Se
    # normalizan los dos lados para poder compararlos.
    def _como_el_compose(entrada: str) -> str:
        servicio, _, modulo = entrada.partition(":")
        return f"{servicio}-{modulo.removesuffix('_worker')}"

    return set(servicios.group(1).split()), {_como_el_compose(w) for w in workers.group(1).split()}


def test_el_arranque_nativo_levanta_los_mismos_servicios_que_el_compose() -> None:
    compose = _del_compose()
    servicios, workers = _del_setup()
    # El gateway se llama igual en los dos sitios; `orchestrator-worker` es worker.
    faltan = compose - servicios - workers

    assert not faltan, (
        "El compose arranca esto y `./setup.sh arrancar` no:\n  "
        + "\n  ".join(sorted(faltan))
        + "\n\nQuien siga el camino documentado tendrá un sistema que arranca y "
        "contesta sin esas piezas. Si la ausencia es deliberada, dilo en "
        "`setup.sh` con su motivo y añádelo a la excepción de esta prueba."
    )


def test_el_arranque_nativo_no_inventa_servicios_que_no_existen() -> None:
    """Al revés también: un nombre en `setup.sh` que ya no existe deja un
    `uvicorn` fallando en un log que nadie abre."""
    servicios, workers = _del_setup()
    for nombre in servicios:
        assert (
            RAIZ / "services" / nombre / "main.py"
        ).is_file(), f"`setup.sh` arranca «{nombre}» y no existe `services/{nombre}/main.py`"
    # Los workers se comprueban con su nombre REAL —`servicio:modulo`—, no con
    # el normalizado al estilo del compose: lo que se ejecuta es el módulo.
    for entrada in _workers_declarados():
        servicio, _, modulo = entrada.partition(":")
        assert (RAIZ / "services" / servicio / f"{modulo}.py").is_file(), (
            f"`setup.sh` arranca el worker «{entrada}» y no existe "
            f"`services/{servicio}/{modulo}.py`"
        )


def test_cada_servicio_del_arranque_nativo_tiene_puerto_propio() -> None:
    """Dos servicios en el mismo puerto: el segundo no arranca y su log lo dice
    donde nadie mira."""
    texto = (RAIZ / "setup.sh").read_text(encoding="utf-8")
    servicios, _ = _del_setup()
    puertos: dict[str, str] = {}
    for nombre in servicios:
        if nombre == "gateway":
            continue
        encaje = re.search(rf"^\s*{re.escape(nombre)}\)\s*echo\s+(\d+)\s*;;", texto, re.M)
        assert encaje, (
            f"«{nombre}» está en SERVICIOS y no tiene puerto en `puerto_de`: "
            "arrancaría en el 0 y no respondería, sin que nada lo diga."
        )
        puerto = encaje.group(1)
        assert (
            puerto not in puertos
        ), f"«{nombre}» y «{puertos[puerto]}» comparten el puerto {puerto}"
        puertos[puerto] = nombre


def test_los_workers_no_esperan_un_puerto() -> None:
    """Un worker no escucha en ningún sitio, y comprobarlo con `curl` lo daría
    por caído siempre. El compose ya lo aprendió —su comentario sigue ahí— y el
    arranque nativo tiene que saberlo igual: se mira por proceso."""
    texto = (RAIZ / "setup.sh").read_text(encoding="utf-8")
    servicios, workers = _del_setup()
    for w in workers:
        # Un worker no puede estar además en la lista de servicios HTTP: se
        # arrancaría dos veces y la segunda moriría por el puerto ocupado.
        assert w not in servicios, f"«{w}» está declarado como servicio HTTP y es un worker"
    assert "kill -0" in texto, (
        "El estado de los workers tiene que mirarse por proceso: no escuchan en "
        "ningún puerto y con `curl` saldrían caídos siempre."
    )
