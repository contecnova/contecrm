"""El arranque documentado levanta lo mismo que el despliegue.

**No lo levantaba, y las tres listas estaban cada una más atrás que la anterior:**

    docker-compose.yml        20 procesos
    ./setup.sh arrancar       11        ← el camino documentado por defecto
    docs/manual-1-empezar.md   8        ← lo que el manual decía

Faltaban tres servicios de API enteros —`service`, `marketing` e `intelligence`,
añadidos al producto después— y **los seis workers**: `setup.sh` no mencionaba
la palabra «worker» ni una sola vez.

Quien seguía el manual levantaba un sistema que **arranca, contesta y se ve
perfecto**, sin casos, sin marketing y sin IA, y en el que **nada asíncrono
ocurre jamás**: los trabajos se encolan y no pasan nunca, sin error.

Dos cosas que este fichero hace a propósito, y la segunda es la que vale:

**Se lee el YAML, no una expresión regular.** A un repositorio de la casa la
regex le acusó de «servicios sin levantar» a `pgdata`, `browsernet` y
`environment`, que son un volumen, una red y una clave de configuración.

**Se contrastan las DOS listas contra el compose, no entre ellas.** Que el guion
y el manual coincidan no basta: **pueden coincidir las dos en olvidar el mismo
servicio**, que es exactamente lo que pasaba aquí con `intelligence`.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]

# Lo que el compose levanta y NO tiene que estar en el arranque local, **con el
# motivo al lado**. Una excepción sin motivo es un olvido con permiso.
NO_VAN_EN_LOCAL = {
    "postgres": "en local es el Postgres embebido que arranca `setup.sh`",
    "nats": "el bus en local es el de memoria; NATS solo en despliegue",
    "redis": "la caché en local es la de memoria",
    "prometheus": "observabilidad: no hace falta para trabajar",
    "tempo": "observabilidad: no hace falta para trabajar",
    "grafana": "observabilidad: no hace falta para trabajar",
    "consola": "el front se levanta aparte con `./setup.sh front`",
}


def _servicios_del_compose() -> set[str]:
    """Los servicios del compose, leyendo el YAML.

    Solo la clave `services`: con una expresión regular entran las redes, los
    volúmenes y las claves de las anclas, y el gate acusa de «sin levantar» a un
    volumen.
    """
    datos = yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))
    return set(datos.get("services") or {})


def _lista_de_setup(nombre: str) -> list[str]:
    texto = (RAIZ / "setup.sh").read_text(encoding="utf-8")
    encaje = re.search(rf"^{nombre}=\(([^)]*)\)", texto, re.M)
    assert encaje, (
        f"`setup.sh` ya no declara {nombre}. Si se ha quitado, el arranque local "
        "deja de levantar algo y nadie lo notará: el sistema arranca, contesta y "
        "lo que falta no da error."
    )
    return encaje.group(1).split()


def _como_el_compose(entrada: str) -> str:
    """`party:trabajos_worker` → `party-trabajos`, que es como se llama allí."""
    servicio, _, modulo = entrada.partition(":")
    return f"{servicio}-{modulo.removesuffix('_worker')}"


def _del_setup() -> set[str]:
    servicios = set(_lista_de_setup("SERVICIOS"))
    workers = {_como_el_compose(w) for w in _lista_de_setup("WORKERS")}
    return servicios | workers


def _del_manual() -> set[str]:
    """Lo que el manual de empezar promete que se levanta.

    Se lee del bloque de ejemplo porque es lo que la gente mira: si ahí falta
    algo, alguien dará por bueno un arranque incompleto aunque el guion lo
    levante.
    """
    texto = (RAIZ / "docs" / "manual-1-empezar.md").read_text(encoding="utf-8")
    servicios = set(re.findall(r"✓ ([a-z][a-z0-9-]*) :\d+", texto))
    workers = {
        _como_el_compose(f"{s}:{m}") for s, m in re.findall(r"✓ worker ([a-z]+)/([a-z_]+)", texto)
    }
    return servicios | workers


def _faltan(lista: set[str]) -> set[str]:
    return _servicios_del_compose() - lista - set(NO_VAN_EN_LOCAL)


def test_las_excepciones_dicen_por_que() -> None:
    """Una excepción sin motivo escrito es un olvido con permiso."""
    for nombre, motivo in NO_VAN_EN_LOCAL.items():
        assert motivo.strip(), f"«{nombre}» está exenta y no dice por qué"


def test_el_guion_de_arranque_levanta_lo_que_levanta_el_compose() -> None:
    faltan = _faltan(_del_setup())
    assert not faltan, (
        "El compose levanta esto y `./setup.sh arrancar` no:\n  "
        + "\n  ".join(sorted(faltan))
        + "\n\nQuien siga el camino documentado tendrá un sistema que arranca y "
        "contesta sin esas piezas, y si alguna es un worker, sin ejecutar nada "
        "asíncrono. Si la ausencia es deliberada, añádela a NO_VAN_EN_LOCAL con "
        "su motivo."
    )


def test_el_manual_promete_lo_que_el_compose_levanta() -> None:
    """Contra el compose y **no contra el guion**.

    Comparar el manual con el guion no serviría: pueden coincidir los dos en
    olvidar el mismo servicio, que es justo lo que pasaba —el manual decía ocho,
    el guion once, y a los dos les faltaba `intelligence`—.
    """
    faltan = _faltan(_del_manual())
    assert not faltan, (
        "El compose levanta esto y el manual de empezar no lo nombra:\n  "
        + "\n  ".join(sorted(faltan))
        + "\n\nQuien lea el manual dará por bueno un arranque al que le falta eso."
    )


def test_el_arranque_no_inventa_nada_que_no_exista() -> None:
    """Un nombre que ya no existe deja un proceso fallando en un log que nadie
    abre, y el arranque se ve igual de bien."""
    for nombre in _lista_de_setup("SERVICIOS"):
        assert (
            RAIZ / "services" / nombre / "main.py"
        ).is_file(), f"`setup.sh` arranca «{nombre}» y no existe `services/{nombre}/main.py`"
    for entrada in _lista_de_setup("WORKERS"):
        servicio, _, modulo = entrada.partition(":")
        assert (RAIZ / "services" / servicio / f"{modulo}.py").is_file(), (
            f"`setup.sh` arranca el worker «{entrada}» y no existe "
            f"`services/{servicio}/{modulo}.py`"
        )


def test_cada_servicio_tiene_puerto_propio() -> None:
    """Dos servicios en el mismo puerto: el segundo no arranca y su log lo dice
    donde nadie mira."""
    texto = (RAIZ / "setup.sh").read_text(encoding="utf-8")
    puertos: dict[str, str] = {}
    for nombre in _lista_de_setup("SERVICIOS"):
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


def test_los_workers_se_miran_por_proceso_y_no_por_puerto() -> None:
    """Un worker no escucha en ningún sitio: comprobarlo con `curl` lo daría por
    caído siempre, y por eso el compose dejó de hacerlo. El arranque local tiene
    que saberlo igual."""
    texto = (RAIZ / "setup.sh").read_text(encoding="utf-8")
    servicios = set(_lista_de_setup("SERVICIOS"))
    for entrada in _lista_de_setup("WORKERS"):
        nombre = _como_el_compose(entrada)
        assert nombre not in servicios, (
            f"«{nombre}» está declarado como servicio HTTP y es un worker: se "
            "arrancaría dos veces y la segunda moriría por el puerto ocupado."
        )
    assert "kill -0" in texto, (
        "El estado de los workers tiene que mirarse por proceso: no escuchan en "
        "ningún puerto y con `curl` saldrían caídos siempre."
    )
