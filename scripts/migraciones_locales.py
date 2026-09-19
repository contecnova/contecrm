#!/usr/bin/env python3
"""Genera y prueba migraciones contra un Postgres efímero, sin Docker.

    python scripts/migraciones_locales.py generar party sales
    python scripts/migraciones_locales.py comprobar          # todos los servicios

Existe porque `--autogenerate` necesita una base **con las migraciones anteriores
ya aplicadas** para comparar, y montarla a mano —arrancar Docker, crear los
esquemas, aplicar, generar, tirar— son cinco pasos que se hacen mal a la tercera
vez. Aquí se usa el mismo Postgres embebido que la suite de pruebas
(`pgserver`), así que funciona en cualquier máquina y no deja nada encendido.

`comprobar` es lo que hay que ejecutar antes de empujar un cambio de modelo:
aplica todas las migraciones desde cero y avisa si el autogenerado detecta
diferencias, es decir, si alguien tocó un modelo y se le olvidó la migración.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVICIOS = sorted(p.name for p in (RAIZ / "alembic" / "versions").iterdir() if p.is_dir())
PY = str(RAIZ / ".venv" / "bin" / "python")


def _servidor(directorio: Path) -> tuple[str, object]:
    import pgserver

    servidor = pgserver.get_server(directorio / "pgdata")
    uri = servidor.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    return uri, servidor


def _preparar(uri: str, servicios: list[str]) -> dict[str, str]:
    import sqlalchemy as sa

    motor = sa.create_engine(uri)
    with motor.connect() as conexion:
        for servicio in servicios:
            conexion.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{servicio}"'))
        conexion.commit()
    motor.dispose()
    return dict(
        os.environ,
        DATABASE_URL=uri,
        ENV="dev",
        BUS_BACKEND="memoria",
        SECRET_KEY="clave-solo-para-generar-migraciones-en-local",
    )


def _alembic(entorno: dict[str, str], servicio: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, "scripts/migrar.py", servicio, *args],
        cwd=RAIZ,
        env=entorno,
        capture_output=True,
        text=True,
    )


def generar(servicios: list[str], mensaje: str) -> int:
    directorio = Path(tempfile.mkdtemp(prefix="migr-"))
    uri, servidor = _servidor(directorio)
    entorno = _preparar(uri, servicios)
    peor = 0
    try:
        for servicio in servicios:
            arriba = _alembic(entorno, servicio, "upgrade", "head")
            if arriba.returncode:
                print(f"{servicio}: fallo al aplicar\n{arriba.stderr[-2000:]}", file=sys.stderr)
                peor = 1
                continue
            nueva = _alembic(entorno, servicio, "revision", "-m", mensaje)
            estado = "ok" if nueva.returncode == 0 else "FALLA"
            print(f"{servicio}: {estado}")
            if nueva.returncode:
                print(nueva.stderr[-2000:], file=sys.stderr)
                peor = 1
    finally:
        servidor.cleanup()  # type: ignore[attr-defined]
        shutil.rmtree(directorio, ignore_errors=True)
    return peor


def comprobar(servicios: list[str]) -> int:
    """Aplica todo desde cero y avisa si falta alguna migración.

    Detecta el olvido más caro con los modelos: tocar una columna y no generar
    la migración. En local todo funciona —las pruebas crean las tablas desde los
    modelos—, y el fallo aparece al desplegar, donde las tablas vienen de las
    migraciones.
    """
    directorio = Path(tempfile.mkdtemp(prefix="migr-"))
    uri, servidor = _servidor(directorio)
    entorno = _preparar(uri, servicios)
    peor = 0
    try:
        for servicio in servicios:
            arriba = _alembic(entorno, servicio, "upgrade", "head")
            if arriba.returncode:
                print(f"✗ {servicio}: las migraciones no aplican\n{arriba.stderr[-2000:]}")
                peor = 1
                continue
            # Se genera una revisión de prueba: si sale con contenido, hay
            # cambios sin migrar. Se borra siempre, haya salido lo que haya.
            nueva = _alembic(entorno, servicio, "revision", "-m", "comprobacion")
            creada = _ultima(servicio)
            if nueva.returncode or creada is None:
                print(f"✗ {servicio}: no se pudo comprobar\n{nueva.stderr[-1500:]}")
                peor = 1
                continue
            cuerpo = creada.read_text(encoding="utf-8")
            creada.unlink()
            vacia = cuerpo.count("pass") >= 2
            print(
                f"{'✓' if vacia else '✗'} {servicio}: "
                + ("al día" if vacia else "HAY CAMBIOS DE MODELO SIN MIGRAR")
            )
            if not vacia:
                peor = 1
    finally:
        servidor.cleanup()  # type: ignore[attr-defined]
        shutil.rmtree(directorio, ignore_errors=True)
    return peor


def _ultima(servicio: str) -> Path | None:
    carpeta = RAIZ / "alembic" / "versions" / servicio
    ficheros = sorted(carpeta.glob("*.py"), key=lambda f: f.stat().st_mtime)
    return ficheros[-1] if ficheros else None


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("generar", "comprobar"):
        print(__doc__, file=sys.stderr)
        return 2
    orden = sys.argv[1]
    # Se quita `-m` Y su valor antes de leer los servicios: si no, el mensaje de
    # la revisión se interpreta como el nombre de un servicio y la orden falla
    # con «servicio desconocido: indice de busqueda», que no dice nada.
    resto = sys.argv[2:]
    mensaje = "cambios"
    if "-m" in resto:
        i = resto.index("-m")
        mensaje = resto[i + 1] if i + 1 < len(resto) else mensaje
        resto = resto[:i] + resto[i + 2 :]
    pedidos = [a for a in resto if not a.startswith("-")]
    servicios = pedidos or SERVICIOS
    desconocidos = [s for s in servicios if s not in SERVICIOS]
    if desconocidos:
        print(f"Servicios desconocidos: {desconocidos}", file=sys.stderr)
        return 2

    if orden == "generar":
        return generar(servicios, mensaje)
    return comprobar(servicios)


if __name__ == "__main__":
    raise SystemExit(main())
