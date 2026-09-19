#!/usr/bin/env python3
"""Mide qué aguanta esta instalación. No lo inventa (CRM-08.01.01.05).

    python scripts/medir_volumetria.py --cuentas 50000

Existe porque **una volumetría declarada sin medir es una cifra inventada**
(CRM-08.01.01.03), y de las que se descubren en la peor conversación posible:
la que empieza con «nos dijisteis que aguantaba un millón de registros».

Lo que mide, y por qué esos tres:

  * **Alta de registros por segundo** — es el suelo de cualquier importación.
  * **Búsqueda con el índice cargado** — es lo que primero se degrada al crecer,
    y lo que más se nota, porque se usa a todas horas.
  * **Listado paginado con filtro** — la pantalla más usada del CRM.

Lo que **no** mide, y hay que decirlo: nada de concurrencia real, ni red, ni el
coste del gateway. Corre contra un Postgres embebido en esta máquina, así que
los números son un **suelo comparable entre versiones**, no una promesa de
capacidad en producción. Sirven para responder «¿esto ha empeorado?», que es la
pregunta que se puede contestar honestamente sin un entorno de carga.
"""

from __future__ import annotations

import json
import shutil
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "packages" / "crmcore"))

SALIDA = RAIZ / "docs" / "volumetria.json"


def _arg(nombre: str, por_defecto: int) -> int:
    if nombre in sys.argv:
        i = sys.argv.index(nombre)
        if i + 1 < len(sys.argv):
            return int(sys.argv[i + 1])
    return por_defecto


def medir(n_cuentas: int) -> dict[str, object]:
    import os

    import pgserver
    import sqlalchemy as sa

    directorio = Path(tempfile.mkdtemp(prefix="volumetria-"))
    servidor = pgserver.get_server(directorio / "pgdata")
    uri = servidor.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)

    os.environ.update(
        DATABASE_URL=uri,
        DB_SCHEMA="party",
        SERVICE_NAME="party",
        ENV="dev",
        BUS_BACKEND="memoria",
        SECRET_KEY="clave-de-medicion-que-no-vale-para-nada-mas",
    )
    from crmcore.config import limpiar_cache_settings
    from crmcore.db.base import Base
    from crmcore.db.session import get_engine, nueva_sesion, reset_engine

    limpiar_cache_settings()
    reset_engine()

    # Se importan TODOS los modelos que la sesión va a tocar, incluidos los
    # comunes: la jerarquía de ajustes consulta `ajustes_runtime` en la primera
    # búsqueda, y sin su tabla la medición muere con un «relation does not
    # exist» a mitad, después de haber insertado veinte mil filas.
    import crmcore.audit.modelos  # noqa: F401
    import crmcore.bus.modelos  # noqa: F401
    import crmcore.busqueda  # noqa: F401
    import crmcore.runtime.settings  # noqa: F401
    from crmcore.busqueda import buscar, indexar

    import services.party.modelos  # noqa: F401
    from services.party.modelos import Cuenta
    from services.party.normalizacion import clave_canonica_empresa

    motor = get_engine()
    with motor.connect() as conexion:
        conexion.execute(sa.text('CREATE SCHEMA IF NOT EXISTS "party"'))
        conexion.commit()
    Base.metadata.create_all(motor)

    tenant = uuid4()
    otros = [uuid4() for _ in range(4)]
    db = nueva_sesion(sistema=True)
    medidas: dict[str, object] = {}

    try:
        # ── Alta ──────────────────────────────────────────────────────────
        # Por lotes, que es como entra el volumen de verdad: una importación,
        # una sincronización con el ERP. Medir insercion a inserción con commit
        # mediría la latencia del disco, no la capacidad del sistema.
        inicio = time.monotonic()
        lote = 1_000
        for comienzo in range(0, n_cuentas, lote):
            filas = []
            for i in range(comienzo, min(comienzo + lote, n_cuentas)):
                # Un cuarto de las cuentas es de otros tenants: sin eso, el
                # índice tendría un solo tenant y la medida no diría nada sobre
                # el coste de filtrar, que es el que importa aquí.
                propietario = tenant if i % 4 else otros[i % 4]
                nombre = f"Empresa {i} Servicios Integrales"
                filas.append(
                    {
                        "id": uuid4(),
                        "tenant_id": propietario,
                        "nombre": nombre,
                        "clave_canonica": clave_canonica_empresa(nombre),
                        "estado": "activa" if i % 3 else "prospecto",
                    }
                )
            db.execute(sa.insert(Cuenta), filas)
            db.commit()
        alta_s = time.monotonic() - inicio
        medidas["altas_por_segundo"] = round(n_cuentas / alta_s)
        medidas["alta_total_s"] = round(alta_s, 1)

        # ── Indexado ──────────────────────────────────────────────────────
        indexadas = min(n_cuentas, 20_000)
        cuentas = db.execute(sa.select(Cuenta).limit(indexadas)).scalars().all()
        inicio = time.monotonic()
        for cuenta in cuentas:
            indexar(
                db,
                tenant_id=cuenta.tenant_id,
                objeto="cuenta",
                registro_id=cuenta.id,
                titulo=cuenta.nombre,
                cuerpo=cuenta.clave_canonica,
            )
        db.commit()
        indexado_s = time.monotonic() - inicio

        # ANALYZE tras la carga. **No es cosmético**: sin estadísticas frescas,
        # el planificador cree que la tabla está vacía y descarta el índice GIN,
        # con lo que la primera búsqueda tras una importación tarda treinta veces
        # más. Se midió aquí: 81 ms frente a 2,6 ms sobre los mismos 20.000
        # documentos. Autovacuum acabaría haciéndolo, pero puede tardar minutos —
        # los mismos minutos en los que alguien concluye que la búsqueda no sirve.
        db.execute(sa.text("ANALYZE indice_busqueda"))
        db.commit()
        medidas["indexadas_por_segundo"] = round(indexadas / indexado_s)
        medidas["documentos_indexados"] = indexadas

        # ── Búsqueda ──────────────────────────────────────────────────────
        tiempos = []
        for i in range(30):
            arranque = time.monotonic()
            buscar(db, tenant_id=tenant, texto=f"empresa {i * 137}", limite=20)
            tiempos.append((time.monotonic() - arranque) * 1000)
        medidas["busqueda_ms_mediana"] = round(statistics.median(tiempos), 1)
        medidas["busqueda_ms_p95"] = round(sorted(tiempos)[int(len(tiempos) * 0.95) - 1], 1)

        # ── Listado ───────────────────────────────────────────────────────
        tiempos = []
        for _ in range(30):
            arranque = time.monotonic()
            db.execute(
                sa.select(Cuenta)
                .where(Cuenta.tenant_id == tenant, Cuenta.estado == "activa")
                .order_by(Cuenta.created_at.desc())
                .limit(50)
            ).scalars().all()
            tiempos.append((time.monotonic() - arranque) * 1000)
        medidas["listado_ms_mediana"] = round(statistics.median(tiempos), 1)
        medidas["listado_ms_p95"] = round(sorted(tiempos)[int(len(tiempos) * 0.95) - 1], 1)

        # ── Tamaño ────────────────────────────────────────────────────────
        tamano = db.execute(
            sa.text("SELECT pg_size_pretty(pg_database_size(current_database()))")
        ).scalar_one()
        medidas["tamano_base"] = tamano
    finally:
        db.close()
        reset_engine()
        servidor.cleanup()
        shutil.rmtree(directorio, ignore_errors=True)

    return medidas


def main() -> int:
    import platform

    n = _arg("--cuentas", 20_000)
    print(f"Midiendo con {n} cuentas. Tarda unos minutos.\n")
    medidas = medir(n)

    informe = {
        "medido_at": datetime.now(timezone.utc).isoformat(),
        "cuentas": n,
        "maquina": {
            "sistema": platform.system(),
            "procesador": platform.machine(),
            "python": platform.python_version(),
        },
        "aviso": (
            "Medido contra un Postgres embebido en una sola máquina, sin red ni "
            "concurrencia. Son un SUELO comparable entre versiones, no una "
            "promesa de capacidad en producción."
        ),
        "medidas": medidas,
    }
    SALIDA.write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{'alta de cuentas':28s} {medidas['altas_por_segundo']:>8} /s")
    print(f"{'indexado':28s} {medidas['indexadas_por_segundo']:>8} /s")
    print(
        f"{'búsqueda (mediana / p95)':28s} {medidas['busqueda_ms_mediana']:>8} / {medidas['busqueda_ms_p95']} ms"
    )
    print(
        f"{'listado (mediana / p95)':28s} {medidas['listado_ms_mediana']:>8} / {medidas['listado_ms_p95']} ms"
    )
    print(f"{'tamaño de la base':28s} {medidas['tamano_base']:>8}")
    print(f"\nEscrito {SALIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
