#!/usr/bin/env python3
"""¿Se ven los datos de todos, o están copiados en todos? (diagnóstico)

    python scripts/de_quien_son_las_filas.py

Son dos problemas distintos y se arreglan en sitios opuestos, así que lo
primero es saber cuál de los dos es:

  * **Fuga de visibilidad** — las filas son de UN tenant y la sesión las está
    enseñando todas. Se arregla en la sesión; los datos están bien.
  * **Copia** — las mismas filas existen de verdad en varios tenants, cada una
    con su `tenant_id`. Se arregla borrando; la sesión está bien.

Se distinguen mirando dónde están las filas, no qué enseña la pantalla: la
pantalla miente igual en los dos casos.

Y hay un tercer caso que se confunde con la copia y no lo es: **datos legítimos
de varias empresas**. Dos tenants sembrados a propósito tienen cuentas los dos,
y eso no es un fallo. Por eso no basta con contar tenants por tabla: se compara
si los NOMBRES coinciden. Dos tenants con cuentas distintas son dos clientes;
dos tenants con las mismas veinte cuentas son una copia.

No escribe nada. Lee.
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict

import psycopg

# Las columnas por las que se reconoce una fila entre tenants. Se prueban en
# orden y se usa la primera que la tabla tenga: un nombre repetido en dos
# tenants es la señal; un identificador NO lo es, porque una copia de verdad
# genera identificadores nuevos y pareceria que no hay copia.
COLUMNAS_NOMBRE = ("nombre", "titulo", "asunto", "codigo", "clave", "email", "razon_social")

# Cuántas filas se miran por tabla para comparar nombres. No hace falta más:
# si veinte nombres coinciden entre dos tenants, es una copia.
MUESTRA = 50


def main() -> int:
    uri = os.environ.get("DATABASE_URL", "")
    if not uri:
        print("Falta DATABASE_URL. Sale del `.env` del proyecto.", file=sys.stderr)
        return 2
    # SQLAlchemy mete el driver en el esquema de la URI y psycopg no lo entiende.
    uri = uri.replace("postgresql+psycopg://", "postgresql://")

    try:
        conexion = psycopg.connect(uri, connect_timeout=5)
    except Exception as exc:  # noqa: BLE001 — el motivo es lo que hay que leer
        print(f"No se ha podido conectar: {exc}", file=sys.stderr)
        print("¿Está levantada la pila? `docker compose up -d`", file=sys.stderr)
        return 1

    with conexion, conexion.cursor() as cur:
        cur.execute(
            """
            SELECT c.table_schema, c.table_name
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_schema = c.table_schema AND t.table_name = c.table_name
            WHERE c.column_name = 'tenant_id'
              AND t.table_type = 'BASE TABLE'
              AND c.table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY 1, 2
            """
        )
        tablas = cur.fetchall()
        print(f"{len(tablas)} tablas con `tenant_id`.\n")

        por_tenant: dict[str, int] = defaultdict(int)
        compartidas: list[tuple[str, str, int, int]] = []
        copiadas: list[tuple[str, str, list[str], int]] = []
        revisadas = 0
        con_filas = 0

        for esquema, tabla in tablas:
            revisadas += 1
            cur.execute(
                f'SELECT tenant_id, count(*) FROM "{esquema}"."{tabla}" GROUP BY 1'  # noqa: S608
            )
            reparto = cur.fetchall()
            if not reparto:
                continue
            con_filas += 1
            for tenant, cuantas in reparto:
                por_tenant[str(tenant)] += cuantas
            if len(reparto) < 2:
                continue
            compartidas.append((esquema, tabla, len(reparto), sum(c for _, c in reparto)))

            columna = _columna_de_nombre(cur, esquema, tabla)
            if columna is None:
                continue
            nombres_por_tenant: dict[str, set[str]] = {}
            for tenant, _ in reparto:
                cur.execute(
                    f'SELECT DISTINCT "{columna}"::text FROM "{esquema}"."{tabla}" '  # noqa: S608
                    f"WHERE tenant_id = %s LIMIT {MUESTRA}",
                    (tenant,),
                )
                nombres_por_tenant[str(tenant)] = {f[0] for f in cur.fetchall() if f[0]}
            repetidos = _repetidos(nombres_por_tenant)
            if repetidos:
                copiadas.append((esquema, tabla, sorted(repetidos)[:5], len(repetidos)))

    print("── Filas por tenant ────────────────────────────────────────")
    for tenant, cuantas in sorted(por_tenant.items(), key=lambda x: -x[1]):
        print(f"  {tenant}  {cuantas:>8} filas")
    print(f"\n  {revisadas} tablas recorridas, {con_filas} con filas.")

    print("\n── Tablas con filas de MÁS DE UN tenant ────────────────────")
    if not compartidas:
        print("  Ninguna. Cada tabla tiene filas de un solo tenant.")
    else:
        for esquema, tabla, cuantos, total in sorted(compartidas, key=lambda x: -x[3])[:40]:
            print(f"  {esquema}.{tabla:<38} {cuantos} tenants, {total} filas")
        if len(compartidas) > 40:
            print(f"  … y {len(compartidas) - 40} más")

    print("\n── ¿Son las MISMAS filas? ──────────────────────────────────")
    if not copiadas:
        print("  No. Cada tenant tiene las suyas: esto NO es una copia.")
        print("  Si en pantalla se ven todas, el problema es de visibilidad.")
    else:
        print("  Sí: estos nombres existen en más de un tenant.")
        for esquema, tabla, muestra, cuantos in sorted(copiadas, key=lambda x: -x[3])[:40]:
            print(f"  {esquema}.{tabla:<38} {cuantos} repetidos · {', '.join(muestra)}")
    return 0


def _columna_de_nombre(cur: psycopg.Cursor, esquema: str, tabla: str) -> str | None:
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = ANY(%s)
        """,
        (esquema, tabla, list(COLUMNAS_NOMBRE)),
    )
    encontradas = {f[0] for f in cur.fetchall()}
    for candidata in COLUMNAS_NOMBRE:
        if candidata in encontradas:
            return candidata
    return None


def _repetidos(nombres_por_tenant: dict[str, set[str]]) -> set[str]:
    """Los nombres que aparecen en dos tenants o más."""
    cuantas_veces: dict[str, int] = defaultdict(int)
    for nombres in nombres_por_tenant.values():
        for nombre in nombres:
            cuantas_veces[nombre] += 1
    return {n for n, veces in cuantas_veces.items() if veces > 1}


if __name__ == "__main__":
    raise SystemExit(main())
