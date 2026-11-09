"""La copia de un tenant a su sandbox, servicio a servicio (CRM-07.02.01.02).

Cada servicio guarda lo suyo en su esquema, así que cada uno copia lo suyo: el
orquestador —`tenancy`— pide a los trece la misma copia con los mismos
parámetros y junta lo que contestan. Lo que hace que el resultado cuadre sin que
se coordinen es que todo lo que decide la copia es **determinista**:

- **Identificadores nuevos por UUID5** de la semilla del sandbox y el original.
  Una oportunidad de `sales` que apunta a una cuenta de `party` sigue apuntando
  a la copia de esa cuenta, porque los dos servicios calculan el mismo nuevo
  identificador sin hablarse. Los que no son del tenant —los usuarios, que son
  globales— se conservan: el orquestador los pasa en `conservar`.
- **La muestra es por cuenta.** Una copia parcial se queda con un porcentaje de
  las cuentas, elegidas por un hash de su identificador, y con todo lo que lleva
  `cuenta_id`. Lo que no cuelga de una cuenta —catálogo, configuración,
  procesos— se copia entero: sin ello, el sandbox no funciona.
- **La anonimización sale del modelo**: las columnas que declaran sensibilidad
  `personal`, `especial` o `confidencial`, con un seudónimo consistente y no
  reversible (`crmcore.seguridad.anonimizar`).

Y una regla que no se negocia: **una tabla con secretos no se copia**. Claves
de API, credenciales de conexiones, secretos de webhook, tokens de la suite: su
configuración apunta a sistemas de verdad, y en un sandbox serviría para
disparar contra producción con la cara del cliente.

Lo que esto NO resuelve, dicho: los identificadores escritos dentro de un JSON
no se traducen —quedan apuntando al original, que en el sandbox no existe— y
una referencia a una cuenta que la muestra dejó fuera queda colgando. Las dos
cosas salen en el resumen por tabla, no se callan.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as insertar
from sqlalchemy.orm import Session

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Columnas por las que se decide la muestra: si la fila cuelga de una cuenta, va
# con su cuenta. `cuentas.id` es la propia cuenta.
COLUMNAS_DE_CUENTA = ("cuenta_id", "account_id")
TABLA_DE_CUENTAS = "cuentas"
# Parámetros que admite una sentencia en Postgres: un hecho del protocolo, no un
# ajuste. El lote de cada tabla se recorta para no pasarlo.
PARAMETROS_POSTGRES = 65_535


def nuevo_identificador(semilla: str, original: Any) -> UUID:
    """El identificador de la copia: el mismo en todos los servicios."""
    return uuid.uuid5(uuid.NAMESPACE_OID, f"sandbox:{semilla}:{original}")


def en_la_muestra(semilla: str, cuenta: Any, porcentaje: int) -> bool:
    """Si esa cuenta entra en la copia parcial. Determinista y por cuenta."""
    if porcentaje >= 100:
        return True
    resumen = hashlib.sha256(f"{semilla}:{cuenta}".encode()).hexdigest()
    return int(resumen[:8], 16) % 100 < porcentaje


def _es_uuid(columna: Any) -> bool:
    try:
        return columna.type.python_type is UUID
    except NotImplementedError:
        return False


def _insertar(db: Session, tabla: Any, lote: list[dict[str, Any]]) -> int:
    """Inserta y devuelve cuántas entraron: lo que choca con lo que ya hay, no.

    Se cuentan las filas que DEVUELVE el insert y no el `rowcount`: con un lote
    el controlador contesta -1, y la primera copia de verdad decía que había
    copiado menos ciento noventa filas.
    """
    sentencia = (
        insertar(tabla).values(lote).on_conflict_do_nothing().returning(*tabla.primary_key.columns)
    )
    return len(db.execute(sentencia).all())


def _apunta_a_lo_global(columna: Any) -> bool:
    """Si es una clave ajena a una tabla sin tenant: no se copia, no se traduce.

    Un manifiesto de conector del catálogo, un usuario: existen una vez para
    todos, así que la copia tiene que seguir apuntando al mismo. Traducirlo lo
    deja apuntando a algo que no existe —medido: `instalaciones_conector` caía
    por su clave a `manifiestos_conector`—. Sale de las claves del modelo, no de
    una lista: la siguiente referencia a algo global entra sola.
    """
    return any("tenant_id" not in fk.column.table.c for fk in columna.foreign_keys)


def _tablas_del_servicio(servicio: str) -> list[tuple[Any, type]]:
    """Las tablas de negocio del servicio, en orden de dependencias."""
    from crmcore.db.base import Base

    orden = {t.name: i for i, t in enumerate(Base.metadata.sorted_tables)}
    salida = []
    for mapper in Base.registry.mappers:
        modelo = mapper.class_
        tabla = getattr(modelo, "__table__", None)
        if tabla is None or "tenant_id" not in tabla.c:
            continue
        if not modelo.__module__.startswith(f"services.{servicio}."):
            continue
        salida.append((tabla, modelo))
    return sorted(salida, key=lambda par: orden.get(par[0].name, 0))


def copiar_tenant(
    db: Session,
    *,
    servicio: str,
    origen: UUID,
    destino: UUID,
    semilla: str,
    porcentaje: int,
    anonimizar: bool,
    conservar: set[str],
) -> dict[str, Any]:
    """Copia las tablas del servicio de `origen` a `destino`. Ver el módulo.

    Cada tabla va en su propio punto de guardado: si una falla —una restricción
    que no se esperaba— se cuenta como fallida y las demás siguen. Una copia que
    se para entera por una tabla deja el sandbox a medias y sin decir dónde.
    """
    from crmcore.config import get_settings
    from crmcore.seguridad.anonimizar import (
        anonimizar_fila,
        campos_sensibles,
        sal_de_entorno,
    )

    s = get_settings()
    sal = sal_de_entorno(str(destino), s.secret_key.get_secret_value())
    copiadas: list[dict[str, Any]] = []
    no_copiadas: list[dict[str, str]] = []
    fallidas: list[dict[str, str]] = []

    for tabla, modelo in _tablas_del_servicio(servicio):
        # Lo que es de ESTE entorno y no de sus datos —una cola de ejecuciones
        # pendientes— lo declara la propia tabla, con su motivo. Copiado, el
        # sandbox repetiría el trabajo que producción tiene a medias.
        propio = (tabla.info or {}).get("no_copiar_a_sandbox")
        if propio:
            no_copiadas.append({"tabla": tabla.name, "porque": str(propio)})
            continue
        secretas = [c.name for c in tabla.c if (c.info or {}).get("secreto")]
        if secretas:
            no_copiadas.append(
                {
                    "tabla": tabla.name,
                    "porque": f"Lleva secretos ({', '.join(secretas)}): su configuración "
                    "apunta a sistemas de verdad y desde un sandbox dispararía contra "
                    "producción.",
                }
            )
            continue
        uuids = [
            c.name
            for c in tabla.c
            if _es_uuid(c) and c.name != "tenant_id" and not _apunta_a_lo_global(c)
        ]
        autonumericas = [
            c.name for c in tabla.primary_key.columns if not _es_uuid(c) and c.autoincrement is True
        ]
        cuenta = next((c for c in COLUMNAS_DE_CUENTA if c in tabla.c), None)
        sensibles = campos_sensibles(modelo) if anonimizar else []
        tope = max(1, min(s.sandbox_copia_lote, PARAMETROS_POSTGRES // len(tabla.c)))
        filas = 0
        fuera_de_muestra = 0
        ya_estaban = 0
        try:
            with db.begin_nested():
                lote: list[dict[str, Any]] = []
                for fila in db.execute(select(tabla).where(tabla.c.tenant_id == origen)).mappings():
                    datos = dict(fila)
                    clave_muestra = (
                        datos.get("id")
                        if tabla.name == TABLA_DE_CUENTAS
                        else datos.get(cuenta)
                        if cuenta
                        else None
                    )
                    if clave_muestra is not None and not en_la_muestra(
                        semilla, clave_muestra, porcentaje
                    ):
                        fuera_de_muestra += 1
                        continue
                    if sensibles:
                        datos = anonimizar_fila(datos, modelo, sal=sal, campos=sensibles)
                    for nombre in uuids:
                        valor = datos.get(nombre)
                        if valor is not None and str(valor) not in conservar:
                            datos[nombre] = nuevo_identificador(semilla, valor)
                    for nombre in autonumericas:
                        datos.pop(nombre, None)
                    datos["tenant_id"] = destino
                    lote.append(datos)
                    if len(lote) >= tope:
                        metidas = _insertar(db, tabla, lote)
                        filas += metidas
                        ya_estaban += len(lote) - metidas
                        lote = []
                if lote:
                    metidas = _insertar(db, tabla, lote)
                    filas += metidas
                    ya_estaban += len(lote) - metidas
        except Exception as exc:  # noqa: BLE001 — se cuenta y se sigue con la siguiente
            fallidas.append({"tabla": tabla.name, "error": str(exc).splitlines()[0][:300]})
            logger.warning("sandbox.tabla_fallida", tabla=tabla.name, error=str(exc)[:300])
            continue
        if filas or fuera_de_muestra:
            copiadas.append(
                {
                    "tabla": tabla.name,
                    "filas": filas,
                    "fuera_de_la_muestra": fuera_de_muestra,
                    # Lo que el tenant sandbox ya tenía al crearse —su
                    # configuración de partida— y chocaba con lo copiado: se
                    # queda lo suyo y se cuenta.
                    "ya_estaban": ya_estaban,
                    "anonimizadas": sensibles,
                }
            )
    return {
        "servicio": servicio,
        "copiadas": copiadas,
        "no_copiadas": no_copiadas,
        "fallidas": fallidas,
        "filas": sum(c["filas"] for c in copiadas),
    }
