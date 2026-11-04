"""`arrancar` sobre una pila ya levantada tiene que levantarla de verdad.

**Medido el 04-11-2026, y costó dos diagnósticos.** `./setup.sh arrancar` con
los servicios ya corriendo lanzaba catorce uvicorn que morían en el acto —el
puerto estaba cogido—, escribía los ficheros de pid con esos procesos muertos y
decía «✓» de los catorce, porque quien contestaba era la pila vieja. El efecto
es de los que no avisan: cambias el código, reinicias, y sigue corriendo lo de
la víspera. De regalo, `parar` después tampoco paraba nada, porque iba por esos
ficheros de pid.

Había un guardia escrito para exactamente este caso debajo del lanzamiento, y
**miraba demasiado pronto**: `kill -0` a los 0,6 s, cuando uvicorn todavía está
importando la aplicación y tarda segundos en morir por el puerto ocupado.

Esto ejercita la función del `setup.sh` **de verdad**, con un proceso que
escucha: no mira si el fichero contiene una línea. Y comprueba las dos mitades,
porque una sola se cumpliría matando lo que no es nuestro.
"""

from __future__ import annotations

import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SETUP = RAIZ / "setup.sh"


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _escuchando(puerto: int, marca: str) -> int:
    """Un proceso que ocupa el puerto y lleva `marca` en su línea de orden.

    **Huérfano a propósito.** Lanzado como hijo de pytest, al matarlo se queda
    zombi hasta que alguien lo recoge, y `kill -0` sobre un zombi **dice que
    sigue vivo**: `matar_de_verdad` concluía que no había podido pararlo y la
    prueba acusaba a la función de un fallo del arnés. Se suelta con `nohup` y
    `&` para que lo recoja init, que es la situación real — el servicio que hay
    que parar lo lanzó un `arrancar` de hace horas.
    """
    guion = (
        "import socket,time\n"
        "s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        f"s.bind(('127.0.0.1',{puerto})); s.listen()\n"
        "time.sleep(60)\n"
        f"# {marca}\n"
    )
    lanzado = subprocess.run(
        ["bash", "-c", f"nohup {sys.executable} -c {shlex.quote(guion)} >/dev/null 2>&1 & echo $!"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    pid = int(lanzado.stdout.strip())
    for _ in range(50):
        with socket.socket() as c:
            if c.connect_ex(("127.0.0.1", puerto)) == 0:
                return pid
        time.sleep(0.1)
    subprocess.run(["kill", "-9", str(pid)], check=False)
    raise AssertionError("el proceso de prueba no ha llegado a escuchar")


def _llamar_a_liberar(servicio: str, puerto: int) -> str:
    """Ejecuta `liberar_puerto_propio` del setup.sh, y nada más de él.

    Se extraen las dos funciones que hacen falta en vez de ejecutar el script:
    correrlo entero levantaría la pila.
    """
    orden = (
        f"cd {RAIZ} && "
        "eval \"$(sed -n '/^matar_de_verdad()/,/^}/p' setup.sh)\" && "
        "eval \"$(sed -n '/^liberar_puerto_propio()/,/^}/p' setup.sh)\" && "
        'info() { echo "INFO $*"; }; aviso() { echo "AVISO $*"; }; '
        f"liberar_puerto_propio {servicio} {puerto}"
    )
    salida = subprocess.run(["bash", "-c", orden], capture_output=True, text=True, timeout=60)
    return salida.stdout + salida.stderr


def _sigue_ocupado(puerto: int) -> bool:
    with socket.socket() as c:
        return c.connect_ex(("127.0.0.1", puerto)) == 0


def test_lo_nuestro_se_para_antes_de_volver_a_lanzar() -> None:
    puerto = _puerto_libre()
    # La marca es la que distingue a un servicio nuestro: `services.<nombre>.`
    pid = _escuchando(puerto, "services.identity.main:app")
    try:
        salida = _llamar_a_liberar("identity", puerto)
        assert "INFO" in salida, salida
        assert not _sigue_ocupado(puerto), (
            "el puerto sigue ocupado: `arrancar` volvería a lanzar encima y el "
            "proceso nuevo moriría sin que nadie lo dijera"
        )
    finally:
        subprocess.run(["kill", "-9", str(pid)], check=False)


def test_lo_que_no_es_nuestro_no_se_toca() -> None:
    """La otra mitad. Sin ella, «liberar el puerto» sería matar al vecino.

    En esta máquina conviven varias soluciones de la casa, y un Postgres o un
    MinIO de otro producto en un puerto nuestro mal configurado no se arregla
    matándolo a traición.
    """
    puerto = _puerto_libre()
    pid = _escuchando(puerto, "una-cosa-de-otro-producto")
    try:
        salida = _llamar_a_liberar("identity", puerto)
        assert "AVISO" in salida, salida
        assert _sigue_ocupado(puerto), "se ha matado un proceso que no era nuestro"
    finally:
        subprocess.run(["kill", "-9", str(pid)], check=False)
