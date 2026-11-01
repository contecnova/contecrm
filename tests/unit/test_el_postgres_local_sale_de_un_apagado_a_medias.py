"""Un `postmaster.pid` huérfano no deja la máquina sin base de datos.

PostgreSQL borra su `postmaster.pid` al cerrar. Si matan al proceso a mitad del
cierre —la terminal cerrada, un `./setup.sh parar` interrumpido, un reinicio—
el fichero se queda con la última línea en `stopping`, y `pgserver` revienta con
un `AssertionError` pelado. Medido el 01-11-2026 en esta máquina: un fichero del
30-10 cuyo PID (718) ya lo había reciclado `distnoted`, y con él **ni `arrancar`
ni `parar` funcionaban** —`parar` pasa por el mismo sitio—, sólo borrarlo a mano.

Lo que se prueba aquí es la rama **peligrosa**, no la cómoda: borrar ese fichero
con un Postgres vivo detrás deja dos servidores sobre el mismo directorio de
datos, que es corrupción. Un PID se reutiliza, así que «no es mi PID» no basta:
hay que mirar qué programa es y de qué directorio.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import psutil
import pytest

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def modulo(tmp_path, monkeypatch):
    """`postgres_local` con su directorio de datos en un sitio de usar y tirar."""
    especificacion = importlib.util.spec_from_file_location(
        "postgres_local_bajo_prueba", RAIZ / "scripts" / "postgres_local.py"
    )
    assert especificacion and especificacion.loader
    m = importlib.util.module_from_spec(especificacion)
    sys.modules[especificacion.name] = m
    especificacion.loader.exec_module(m)
    monkeypatch.setattr(m, "PGDATA", tmp_path)
    return m


def _pidfile(carpeta: Path, pid: int, estado: str = "stopping") -> Path:
    """El formato real: PID, directorio, arranque, puerto, socket, … , estado."""
    f = carpeta / "postmaster.pid"
    f.write_text(
        f"{pid}\n{carpeta}\n1793087163\n5432\n{carpeta}\n\n116893523  48496640\n{estado}\n",
        encoding="utf-8",
    )
    (carpeta / ".s.PGSQL.5432").touch()
    (carpeta / ".s.PGSQL.5432.lock").write_text(f"{pid}\n", encoding="utf-8")
    return f


def test_sin_fichero_no_hace_nada(modulo, tmp_path):
    assert modulo._restos_de_un_apagado_a_medias() == ""


def test_un_pid_que_ya_no_existe_se_limpia(modulo, tmp_path, monkeypatch):
    pidfile = _pidfile(tmp_path, 999999)
    monkeypatch.setattr(
        psutil, "Process", lambda _pid: (_ for _ in ()).throw(psutil.NoSuchProcess(_pid))
    )
    aviso = modulo._restos_de_un_apagado_a_medias()
    assert "stopping" in aviso
    assert not pidfile.exists()
    # El socket y su cerrojo llevan el mismo PID muerto y bloquean igual.
    assert not (tmp_path / ".s.PGSQL.5432").exists()
    assert not (tmp_path / ".s.PGSQL.5432.lock").exists()


def test_un_pid_reciclado_por_otro_programa_se_limpia(modulo, tmp_path, monkeypatch):
    """El caso que de verdad pasó: el PID vive, pero es `distnoted`."""
    pidfile = _pidfile(tmp_path, 718)

    class Otro:
        def __init__(self, _pid: int) -> None: ...
        def name(self) -> str:
            return "distnoted"

        def cwd(self) -> str:
            return "/"

    monkeypatch.setattr(psutil, "Process", Otro)
    assert "718" in modulo._restos_de_un_apagado_a_medias()
    assert not pidfile.exists()


def test_con_un_postgres_VIVO_no_se_toca_nada(modulo, tmp_path, monkeypatch):
    """La rama cara: borrar aquí son dos servidores sobre el mismo directorio."""
    pidfile = _pidfile(tmp_path, 40050, estado="ready")
    carpeta = str(tmp_path)

    class Postgres:
        def __init__(self, _pid: int) -> None: ...
        def name(self) -> str:
            return "postgres"

        def cwd(self) -> str:
            return carpeta

    monkeypatch.setattr(psutil, "Process", Postgres)
    assert modulo._restos_de_un_apagado_a_medias() == ""
    assert pidfile.exists()
    assert (tmp_path / ".s.PGSQL.5432").exists()


def test_un_postgres_de_OTRO_directorio_no_protege_a_este(modulo, tmp_path, monkeypatch):
    """Mismo PID, mismo programa, otros datos: el fichero sigue siendo huérfano."""
    pidfile = _pidfile(tmp_path, 40050)

    class PostgresAjeno:
        def __init__(self, _pid: int) -> None: ...
        def name(self) -> str:
            return "postgres"

        def cwd(self) -> str:
            return "/otro/sitio/pgdata"

    monkeypatch.setattr(psutil, "Process", PostgresAjeno)
    assert modulo._restos_de_un_apagado_a_medias() != ""
    assert not pidfile.exists()


def test_un_fichero_ilegible_no_puede_estar_protegiendo_a_nadie(modulo, tmp_path):
    pidfile = tmp_path / "postmaster.pid"
    pidfile.write_text("no es un numero\n", encoding="utf-8")
    assert "ilegible" in modulo._restos_de_un_apagado_a_medias()
    assert not pidfile.exists()
