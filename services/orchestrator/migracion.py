"""Migrar instancias en vuelo a otra versión del proceso (CRM-00.03.02.13).

Publicar una versión nueva no toca lo que ya corre: cada instancia termina con
la versión con la que nació, y eso es lo correcto por defecto. Pero un proceso
de alta de cliente puede durar semanas, y cuando la versión nueva corrige un
error —una tarea asignada a un rol que ya no existe, un plazo mal puesto—
esperar a que las doscientas instancias viejas terminen con el error no es una
opción. Esto las mueve.

**Sólo las que se pueden mover sin inventar nada.** Una instancia está parada en
un paso; se migra si ese paso existe en la versión destino y es del mismo tipo.
Si no, no hay dónde ponerla: elegirle otro paso sería decidir por el negocio
qué le toca hacer, y eso es exactamente lo que el histórico tiene que poder
explicar después. Las que no se pueden se quedan como estaban y se dice por qué.

Tres casos más que se quedan, cada uno con su motivo:

  * **Una tarea humana pendiente cuyas respuestas cambian.** La tarea ya está
    en la bandeja de alguien con sus opciones; si la versión nueva no tiene la
    ruta de una de ellas, contestar con esa opción terminaría el proceso sin
    pasar por ningún final.
  * **Pasos ya hechos que tenían compensación y en la versión nueva no.** Si
    después falla algo, la compensación se busca en la definición de la
    instancia: migrarla dejaría sin deshacer lo que la versión vieja sabía
    deshacer, en silencio.
  * **Las que un worker tiene tomadas ahora mismo**, o las que están
    compensando: moverlas a mitad de un paso es cambiarle el guion a un actor
    mientras habla.

**Simular primero.** La simulación es la misma función con `aplicar=False`, así
que lo que enseña es exactamente lo que hará: un simulador que decide distinto
que la ejecución es peor que no tenerlo.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.errors import Conflicto, NoEncontrado
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.orchestrator.modelos import DefinicionProceso, InstanciaProceso, PasoEjecutado

# En vuelo = puede seguir avanzando. «compensando» también lo está, pero se
# trata aparte: se lista y no se migra.
EN_VUELO = ("ejecutando", "esperando", "esperando_humano", "compensando")


def _motivo(
    db: Session,
    instancia: InstanciaProceso,
    pasos_origen: dict[str, Any],
    pasos_destino: dict[str, Any],
    ahora: datetime,
) -> str:
    """Por qué NO se puede migrar esta instancia. Cadena vacía si se puede."""
    if instancia.estado == "compensando":
        return "está deshaciendo pasos: se termina de compensar con su versión"
    if instancia.tomada_hasta is not None and instancia.tomada_hasta > ahora:
        return "un worker la está avanzando ahora mismo: vuelve a intentarlo en unos minutos"

    actual = instancia.paso_actual or ""
    origen = pasos_origen.get(actual) or {}
    destino = pasos_destino.get(actual)
    if destino is None:
        return f"está en «{actual}», que no existe en la versión destino"
    if destino.get("tipo") != origen.get("tipo"):
        return (
            f"está en «{actual}», que en la versión destino es de tipo "
            f"«{destino.get('tipo')}» y no «{origen.get('tipo')}»"
        )

    if instancia.estado == "esperando_humano":
        # Las opciones de la tarea ya creada son las rutas de la versión vieja.
        faltan = sorted(set(origen.get("rutas") or {}) - set(destino.get("rutas") or {}))
        if faltan:
            return (
                f"tiene una tarea pendiente en «{actual}» con respuestas que la versión "
                f"destino ya no admite ({', '.join(faltan)})"
            )

    hechos = (
        db.execute(
            select(PasoEjecutado.paso).where(
                PasoEjecutado.instancia_id == instancia.id,
                PasoEjecutado.resultado == "ok",
            )
        )
        .scalars()
        .all()
    )
    sin_deshacer = sorted(
        {
            paso
            for paso in hechos
            if (pasos_origen.get(paso) or {}).get("compensacion")
            and not (pasos_destino.get(paso) or {}).get("compensacion")
        }
    )
    if sin_deshacer:
        return (
            "ya hizo pasos que su versión sabe deshacer y la destino no "
            f"({', '.join(sin_deshacer)}): si después fallara, se quedarían sin deshacer"
        )
    return ""


def migrar(
    db: Session,
    tenant_id: UUID,
    *,
    clave: str,
    version: int,
    aplicar: bool,
    motivo: str = "",
) -> dict[str, Any]:
    """Simula (`aplicar=False`) o hace la migración a `clave` v`version`."""
    destino = db.execute(
        select(DefinicionProceso).where(
            DefinicionProceso.tenant_id == tenant_id,
            DefinicionProceso.clave == clave,
            DefinicionProceso.version == version,
        )
    ).scalar_one_or_none()
    if destino is None:
        raise NoEncontrado("Esa versión no existe", error_code="proceso.version_no_existe")
    if destino.estado != "publicada":
        # A un borrador no: nadie la ha dado por buena. A una archivada
        # tampoco: se archivó para que no arrancara nada más con ella, y meterle
        # instancias es lo contrario.
        raise Conflicto(
            f"Sólo se migra a una versión publicada, y la v{version} está «{destino.estado}»",
            error_code="proceso.migracion_a_no_publicada",
        )

    instancias = (
        db.execute(
            select(InstanciaProceso)
            .where(
                InstanciaProceso.tenant_id == tenant_id,
                InstanciaProceso.clave == clave,
                InstanciaProceso.version != version,
                InstanciaProceso.estado.in_(EN_VUELO),
            )
            .order_by(InstanciaProceso.created_at)
        )
        .scalars()
        .all()
    )

    pasos_destino = (destino.definicion or {}).get("pasos") or {}
    definiciones: dict[UUID, dict[str, Any]] = {}
    ahora = datetime.now(timezone.utc)
    migrables: list[dict[str, Any]] = []
    se_quedan: list[dict[str, Any]] = []
    for instancia in instancias:
        if instancia.definicion_id not in definiciones:
            origen = db.get(DefinicionProceso, instancia.definicion_id)
            definiciones[instancia.definicion_id] = (
                ((origen.definicion or {}).get("pasos") or {}) if origen else {}
            )
        porque = _motivo(db, instancia, definiciones[instancia.definicion_id], pasos_destino, ahora)
        fila = {
            "instancia_id": str(instancia.id),
            "version": instancia.version,
            "estado": instancia.estado,
            "paso_actual": instancia.paso_actual,
        }
        if porque:
            se_quedan.append({**fila, "motivo": porque})
        else:
            migrables.append(fila)

    if aplicar:
        for fila in migrables:
            instancia = db.get(InstanciaProceso, UUID(fila["instancia_id"]))
            anterior = instancia.version
            instancia.definicion_id = destino.id
            instancia.version = destino.version
            # Cada instancia con su apunte: es en SU historia donde alguien
            # buscará por qué siguió un camino que su versión no tenía.
            registrar(
                db,
                accion="proceso.instancia_migrada",
                objeto="instancia_proceso",
                objeto_id=instancia.id,
                datos={"clave": clave, "desde": anterior, "hasta": destino.version},
                motivo=motivo or None,
                tenant_id=tenant_id,
            )
        registrar(
            db,
            accion="proceso.migracion_de_instancias",
            objeto="definicion_proceso",
            objeto_id=destino.id,
            datos={
                "clave": clave,
                "hasta": destino.version,
                "migradas": len(migrables),
                "se_quedan": [
                    {"instancia_id": f["instancia_id"], "motivo": f["motivo"]} for f in se_quedan
                ],
            },
            motivo=motivo or None,
            tenant_id=tenant_id,
        )
        db.flush()

    return {
        "clave": clave,
        "version_destino": destino.version,
        "aplicada": aplicar,
        "en_vuelo": len(instancias),
        "migrables": migrables,
        "se_quedan": se_quedan,
        "que_significa": (
            (
                f"{len(migrables)} instancia(s) siguen ya con la v{destino.version}."
                if aplicar
                else f"{len(migrables)} instancia(s) pasarían a la v{destino.version}."
            )
            + (
                f" {len(se_quedan)} se quedan con su versión, cada una con su motivo: "
                "terminan como empezaron."
                if se_quedan
                else ""
            )
            if instancias
            else "No hay instancias en vuelo de otras versiones: no hay nada que migrar."
        ),
    }
