#!/usr/bin/env python3
"""Copia de seguridad y, sobre todo, su verificación (CRM-00.06.02.01).

    python scripts/respaldar.py copiar --destino /var/backups/contecrm
    python scripts/respaldar.py verificar /var/backups/contecrm/2026-09-19T03-00
    python scripts/respaldar.py listar --destino /var/backups/contecrm

**Una copia que no se ha restaurado nunca no es una copia: es un fichero.** El
90 % del valor de esto está en `verificar`, que la restaura de verdad sobre una
base efímera y comprueba que las tablas están y tienen filas. Es lo que convierte
el RTO de una promesa en un número medido (CRM-08.02.01.02).

Qué se copia y por qué:

  * **La base entera**, en formato personalizado de `pg_dump`: comprimido, y
    permite restaurar una sola tabla sin releer el fichero completo.
  * **El manifiesto**, con el SHA-256 y el tamaño de cada pieza. Sin él, «la
    copia está» y «la copia está entera» son la misma frase.

Lo que **no** copia, y hay que decirlo: la clave de cifrado. Va en el gestor de
secretos, no aquí — una copia de la base junto a la clave que la descifra es un
solo fichero que lo entrega todo. El precio es que restaurar exige tener las dos
cosas, y eso es exactamente lo que se quiere.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _herramienta(nombre: str) -> str:
    """Ruta de `pg_dump` o `pg_restore`.

    Se busca primero en el PATH —en un servidor están instaladas— y si no, en
    las que trae `pgserver` dentro del entorno. Sin esta caída, el script solo
    funciona en máquinas con el cliente de Postgres instalado, que no son las de
    desarrollo: y una copia que solo se sabe hacer en producción es una copia que
    nadie ha probado.

    **La versión importa**: `pg_restore` no lee volcados de una versión mayor
    que la suya. Usar las dos del mismo sitio evita el caso en que la copia se
    hace con la del servidor y se intenta restaurar con una más vieja.
    """
    import shutil

    encontrada = shutil.which(nombre)
    if encontrada:
        return encontrada
    try:
        import pgserver

        candidata = Path(pgserver.__file__).parent / "pginstall" / "bin" / nombre
        if candidata.exists():
            return str(candidata)
    except ImportError:
        pass
    print(
        f"No se encuentra «{nombre}». Instala el cliente de PostgreSQL, o "
        "ejecuta esto dentro del entorno del proyecto.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")


def _sha256(fichero: Path) -> str:
    resumen = hashlib.sha256()
    # Por trozos: un volcado de varios GB no cabe en memoria, y leerlo entero
    # para calcular un hash es la forma más tonta de quedarse sin RAM.
    with fichero.open("rb") as f:
        for trozo in iter(lambda: f.read(1024 * 1024), b""):
            resumen.update(trozo)
    return resumen.hexdigest()


def _url() -> str:
    url = os.environ.get("DATABASE_ADMIN_URL") or os.environ.get("DATABASE_URL", "")
    if not url:
        print(
            "Falta DATABASE_URL (o DATABASE_ADMIN_URL). Sin ella no hay nada que copiar.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    # `pg_dump` no entiende el prefijo de SQLAlchemy.
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def copiar(destino: Path) -> int:
    """Vuelca la base y escribe el manifiesto."""
    carpeta = destino / _ahora()
    carpeta.mkdir(parents=True, exist_ok=True)
    volcado = carpeta / "contecrm.dump"

    inicio = time.monotonic()
    proceso = subprocess.run(
        [
            _herramienta("pg_dump"),
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(volcado),
            _url(),
        ],
        capture_output=True,
        text=True,
    )
    if proceso.returncode != 0:
        print(f"pg_dump falló:\n{proceso.stderr[-2000:]}", file=sys.stderr)
        return 1
    duracion = time.monotonic() - inicio

    manifiesto = {
        "creada_at": datetime.now(timezone.utc).isoformat(),
        "duracion_s": round(duracion, 1),
        "piezas": {volcado.name: {"bytes": volcado.stat().st_size, "sha256": _sha256(volcado)}},
        # Se anota que la clave NO está aquí. Es la nota que evita la sorpresa
        # de restaurar y encontrarse los campos cifrados ilegibles.
        "clave_de_cifrado_incluida": False,
        "aviso": (
            "Esta copia NO contiene ENCRYPTION_KEY. Sin ella, los campos "
            "cifrados no se recuperan. Guárdala en el gestor de secretos."
        ),
    }
    (carpeta / "manifiesto.json").write_text(
        json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Copia en {carpeta} ({volcado.stat().st_size / 1e6:.1f} MB, {duracion:.1f} s)")
    print("Verifícala antes de confiar en ella:")
    print(f"  python scripts/respaldar.py verificar {carpeta}")
    return 0


def verificar(carpeta: Path) -> int:
    """Restaura la copia en una base efímera y comprueba que sirve.

    Mide el tiempo, que es el RTO real de esta copia y de esta máquina. Un RTO
    escrito en un contrato sin haberlo medido nunca es una cifra inventada.
    """
    manifiesto_json = carpeta / "manifiesto.json"
    if not manifiesto_json.exists():
        print(f"No hay manifiesto en {carpeta}", file=sys.stderr)
        return 1
    manifiesto = json.loads(manifiesto_json.read_text(encoding="utf-8"))

    # 1. Integridad: lo guardado es lo que se escribió.
    for nombre, datos in manifiesto["piezas"].items():
        pieza = carpeta / nombre
        if not pieza.exists():
            print(f"✗ falta la pieza «{nombre}»", file=sys.stderr)
            return 1
        if _sha256(pieza) != datos["sha256"]:
            print(f"✗ «{nombre}» no coincide con el manifiesto: está corrupta", file=sys.stderr)
            return 1
    print("✓ integridad: las piezas coinciden con el manifiesto")

    # 2. Restauración de verdad, sobre un Postgres efímero. Es lo único que
    #    demuestra que la copia sirve; comprobar el hash solo demuestra que el
    #    fichero no se ha estropeado.
    import shutil
    import tempfile

    import pgserver

    directorio = Path(tempfile.mkdtemp(prefix="restaurar-"))
    inicio = time.monotonic()
    servidor = pgserver.get_server(directorio / "pgdata")
    try:
        uri = servidor.get_uri()
        restaurar = subprocess.run(
            [
                _herramienta("pg_restore"),
                "--no-owner",
                "--no-privileges",
                # NO se pone `--exit-on-error`: por defecto `pg_restore` sigue
                # tras un error, y eso es lo que se quiere — un volcado hecho
                # con otro rol da errores de permisos que no impiden que los
                # datos entren. Lo que decide si la copia sirve es la
                # comprobación de contenido de más abajo, no el código de salida.
                "--dbname",
                uri,
                str(carpeta / "contecrm.dump"),
            ],
            capture_output=True,
            text=True,
        )
        duracion = time.monotonic() - inicio
        # El código de salida se INFORMA pero no decide. Aceptarlo a ciegas fue
        # un fallo real de este script: con una opción mal escrita, `pg_restore`
        # salía con 1 sin restaurar nada y la verificación lo daba por bueno.
        if restaurar.returncode != 0:
            print(
                f"  aviso: pg_restore terminó con código {restaurar.returncode}; "
                "se comprueba el contenido igualmente"
            )
            for linea in restaurar.stderr.strip().splitlines()[:5]:
                print(f"    {linea}")

        # 3. Comprobación de contenido: que haya tablas y que tengan filas. Una
        #    restauración que devuelve cero errores sobre un volcado vacío
        #    también "funciona".
        import sqlalchemy as sa

        motor = sa.create_engine(uri.replace("postgresql://", "postgresql+psycopg://", 1))
        with motor.connect() as conexion:
            # `pg_tables` y no `pg_stat_user_tables`: las estadísticas están
            # vacías hasta que pasa el recolector, así que una base recién
            # restaurada parece no tener nada. Se descubrió aquí, y es
            # exactamente el tipo de comprobación que da un falso negativo y
            # hace desconfiar de una copia que estaba bien.
            tablas = conexion.execute(
                sa.text(
                    "SELECT schemaname, tablename FROM pg_tables "
                    "WHERE schemaname NOT IN ('pg_catalog','information_schema') "
                    "ORDER BY schemaname, tablename"
                )
            ).all()
            # Y se cuentan filas de verdad en unas cuantas: una restauración que
            # crea las tablas vacías también "funciona", y es el caso que hay
            # que cazar.
            conteos = []
            for esquema, tabla in tablas[:10]:
                filas = conexion.execute(
                    sa.text(f'SELECT count(*) FROM "{esquema}"."{tabla}"')
                ).scalar_one()
                conteos.append((esquema, tabla, filas))
        motor.dispose()

        if not tablas:
            print("✗ la copia se restaura pero no tiene ninguna tabla", file=sys.stderr)
            return 1
        if not any(filas for _e, _t, filas in conteos):
            print(
                "✗ la copia tiene tablas pero todas están vacías: revisa qué se volcó",
                file=sys.stderr,
            )
            return 1

        print(f"✓ restaurada en {duracion:.1f} s · {len(tablas)} tablas")
        for esquema, tabla, filas in sorted(conteos, key=lambda c: -c[2])[:5]:
            print(f"    {esquema}.{tabla}: {filas} filas")
        print()
        print(f"RTO medido en esta máquina: {duracion:.1f} s")
        print("Es el tiempo de restaurar los datos. El RTO del servicio añade")
        print("levantar los contenedores y comprobar la salud.")
        return 0
    finally:
        servidor.cleanup()
        shutil.rmtree(directorio, ignore_errors=True)


def listar(destino: Path) -> int:
    """Qué copias hay y cuál es la más reciente."""
    if not destino.exists():
        print(f"No hay copias en {destino}")
        return 0
    carpetas = sorted((p for p in destino.iterdir() if p.is_dir()), reverse=True)
    if not carpetas:
        print(f"No hay copias en {destino}")
        return 0

    ahora = datetime.now(timezone.utc)
    for i, carpeta in enumerate(carpetas):
        manifiesto = carpeta / "manifiesto.json"
        if not manifiesto.exists():
            print(f"  {carpeta.name}  (sin manifiesto)")
            continue
        datos = json.loads(manifiesto.read_text(encoding="utf-8"))
        creada = datetime.fromisoformat(datos["creada_at"])
        antiguedad = (ahora - creada).total_seconds() / 60
        tamano = sum(p["bytes"] for p in datos["piezas"].values()) / 1e6
        marca = " ← la más reciente" if i == 0 else ""
        print(f"  {carpeta.name}  {tamano:7.1f} MB  hace {antiguedad:5.0f} min{marca}")

    ultima = json.loads((carpetas[0] / "manifiesto.json").read_text(encoding="utf-8"))
    rpo = (ahora - datetime.fromisoformat(ultima["creada_at"])).total_seconds() / 60
    print()
    print(f"RPO actual: {rpo:.0f} minutos de datos en riesgo si la base se pierde ahora.")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    orden = sys.argv[1]
    destino = Path(
        sys.argv[sys.argv.index("--destino") + 1]
        if "--destino" in sys.argv
        else os.environ.get("BACKUP_DESTINO", "./copias")
    )

    if orden == "copiar":
        return copiar(destino)
    if orden == "verificar":
        objetivo = [a for a in sys.argv[2:] if not a.startswith("-")]
        if not objetivo:
            print("Indica qué copia verificar", file=sys.stderr)
            return 2
        return verificar(Path(objetivo[0]))
    if orden == "listar":
        return listar(destino)

    print(f"Orden desconocida: «{orden}». Usa copiar, verificar o listar.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
