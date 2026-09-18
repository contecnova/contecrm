"""Operaciones masivas: transferencia de propiedad e importación (CRM-07.01.01.07, .08).

Las dos comparten la misma idea, que es lo que las hace seguras: **primero se
valida todo y se enseña qué va a pasar, y solo después se ejecuta**. Una
importación que empieza a escribir y falla a la mitad deja un maestro de clientes
en un estado que nadie sabe describir, y deshacerlo a mano cuesta días.

Y las dos devuelven un **informe de resultados parciales** en vez de un
todo-o-nada: en un fichero de diez mil filas, que noventa estén mal no es razón
para no cargar las 9.910 buenas — pero sí para decir exactamente cuáles fallaron
y por qué.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from crmcore.logging import get_logger

logger = get_logger(__name__)


# ── Informe común ─────────────────────────────────────────────────────────


@dataclass
class Informe:
    """Resultado de una operación masiva, fila a fila.

    `errores` lleva el número de fila **del fichero original**, no el índice
    interno: quien tiene que corregirlo está mirando su hoja de cálculo, y
    decirle «fila 7 del lote 3» no le sirve de nada.
    """

    total: int = 0
    creados: int = 0
    actualizados: int = 0
    omitidos: int = 0
    fallidos: int = 0
    errores: list[dict[str, Any]] = field(default_factory=list)
    # Solo en simulación: qué habría pasado con cada fila.
    previsualizacion: list[dict[str, Any]] = field(default_factory=list)

    def anotar_error(self, fila: int, motivo: str, detalle: dict[str, Any] | None = None) -> None:
        self.fallidos += 1
        # Se recorta la lista de errores: un fichero con cien mil filas todas
        # mal produciría una respuesta imposible de leer y de transportar. El
        # recuento total sigue siendo exacto.
        if len(self.errores) < MAX_ERRORES_DEVUELTOS:
            self.errores.append({"fila": fila, "motivo": motivo, **(detalle or {})})

    def a_dict(self) -> dict[str, Any]:
        d = {
            "total": self.total,
            "creados": self.creados,
            "actualizados": self.actualizados,
            "omitidos": self.omitidos,
            "fallidos": self.fallidos,
            "errores": self.errores,
        }
        if self.fallidos > len(self.errores):
            d["errores_no_mostrados"] = self.fallidos - len(self.errores)
        if self.previsualizacion:
            d["previsualizacion"] = self.previsualizacion
        return d


MAX_ERRORES_DEVUELTOS = 200


# ── Transferencia de propiedad ────────────────────────────────────────────


def transferir_propiedad(
    db: Session,
    *,
    tenant_id: UUID,
    modelos: list[type],
    de_usuario: UUID,
    a_usuario: UUID,
    motivo: str,
    simular: bool = False,
) -> dict[str, int]:
    """Cambia el propietario de todos los registros de una persona a otra.

    Es la operación que hace falta cuando alguien deja la empresa, y conviene
    que sea una sola: hacerlo objeto por objeto garantiza que alguno se olvide y
    que sus cuentas queden sin dueño, invisibles para las reglas de visibilidad
    por propietario.

    `simular=True` cuenta sin tocar nada. Quien la ejecuta necesita ver **cuánto**
    va a mover antes de moverlo: mil cuentas y tres oportunidades es una cosa, y
    al revés es otra.
    """
    from crmcore.audit.chain import registrar

    resumen: dict[str, int] = {}
    for modelo in modelos:
        if not hasattr(modelo, "owner_id"):
            continue
        condiciones = [modelo.owner_id == de_usuario, modelo.tenant_id == tenant_id]
        if hasattr(modelo, "deleted_at"):
            condiciones.append(modelo.deleted_at.is_(None))

        if simular:
            from sqlalchemy import func as _f

            cuantos = db.execute(
                select(_f.count()).select_from(modelo).where(*condiciones)
            ).scalar_one()
        else:
            resultado = db.execute(
                update(modelo)
                .where(*condiciones)
                .values(owner_id=a_usuario)
                .execution_options(synchronize_session=False)
            )
            cuantos = int(resultado.rowcount or 0)
        if cuantos:
            resumen[modelo.__tablename__] = int(cuantos)

    if not simular and resumen:
        registrar(
            db,
            accion="datos.transferencia_propiedad",
            objeto="usuario",
            objeto_id=de_usuario,
            datos={"a": str(a_usuario), "movidos": resumen},
            motivo=motivo,
            tenant_id=tenant_id,
        )
        logger.info(
            "datos.propiedad_transferida",
            de=str(de_usuario),
            a=str(a_usuario),
            total=sum(resumen.values()),
        )
    return resumen


# ── Importación ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PlanImportacion:
    """Cómo se importa un objeto concreto.

    `validar` comprueba una fila y devuelve los errores; `crear` y `actualizar`
    hacen el trabajo. Los aporta el servicio dueño del objeto: el núcleo sabe
    orquestar la carga, no qué es una cuenta válida.
    """

    objeto: str
    validar: Callable[[dict[str, Any]], list[str]]
    buscar_existente: Callable[[Session, dict[str, Any]], Any | None]
    crear: Callable[[Session, dict[str, Any]], Any]
    actualizar: Callable[[Session, Any, dict[str, Any]], Any]
    # Columnas obligatorias del fichero. Se comprueban **antes** de procesar
    # nada: un fichero al que le falta una columna entera es un error del
    # fichero, no de sus filas, y decirlo cien mil veces no ayuda.
    columnas_obligatorias: tuple[str, ...] = ()


def importar(
    db: Session,
    filas: list[dict[str, Any]],
    plan: PlanImportacion,
    *,
    simular: bool = True,
    actualizar_existentes: bool = False,
    tope: int | None = None,
) -> Informe:
    """Importa filas según el plan del objeto.

    **`simular=True` por defecto**, y es deliberado: la operación destructiva
    tiene que pedirse a propósito. Quien llama por error a este endpoint con un
    fichero de prueba recibe un informe, no un maestro de clientes contaminado.
    """
    from crmcore.config import get_settings
    from crmcore.errors import ErrorValidacion

    informe = Informe(total=len(filas))
    tope = tope or get_settings().bulk_max_items
    if len(filas) > tope:
        raise ErrorValidacion(
            f"El lote tiene {len(filas)} filas y el máximo es {tope}. Pártelo o usa "
            "la importación asíncrona.",
            error_code="importacion.lote_demasiado_grande",
            detalle={"maximo": tope, "recibido": len(filas)},
        )

    if plan.columnas_obligatorias and filas:
        faltan = [c for c in plan.columnas_obligatorias if c not in filas[0]]
        if faltan:
            raise ErrorValidacion(
                "Al fichero le faltan columnas obligatorias",
                error_code="importacion.columnas_faltan",
                detalle={"faltan": faltan, "recibidas": sorted(filas[0])},
            )

    for indice, fila in enumerate(filas, start=1):
        errores = plan.validar(fila)
        if errores:
            informe.anotar_error(indice, "validacion", {"errores": errores})
            continue

        existente = plan.buscar_existente(db, fila)
        if existente is not None and not actualizar_existentes:
            informe.omitidos += 1
            if simular:
                informe.previsualizacion.append(
                    {"fila": indice, "accion": "omitir", "motivo": "ya existe"}
                )
            continue

        accion = "actualizar" if existente is not None else "crear"
        if simular:
            informe.previsualizacion.append({"fila": indice, "accion": accion})
            if accion == "crear":
                informe.creados += 1
            else:
                informe.actualizados += 1
            continue

        try:
            if existente is not None:
                plan.actualizar(db, existente, fila)
                informe.actualizados += 1
            else:
                plan.crear(db, fila)
                informe.creados += 1
            # Un volcado por fila: así una fila mala falla sola y no arrastra a
            # las 9.999 buenas del lote.
            db.flush()
        except Exception as exc:  # noqa: BLE001 — una fila mala no tumba la carga
            db.rollback()
            informe.anotar_error(indice, "error", {"detalle": str(exc)[:300]})

    if not simular:
        from crmcore.audit.chain import registrar

        registrar(
            db,
            accion="datos.importacion",
            objeto=plan.objeto,
            datos=informe.a_dict() | {"errores": len(informe.errores)},
        )
        logger.info(
            "datos.importados",
            objeto=plan.objeto,
            creados=informe.creados,
            actualizados=informe.actualizados,
            fallidos=informe.fallidos,
        )
    return informe


def exportar(
    db: Session,
    consulta: Any,
    *,
    columnas: list[str],
    limite: int,
    enmascarar: Callable[[str, Any], Any] | None = None,
) -> list[dict[str, Any]]:
    """Exporta el resultado de una consulta a filas planas.

    `enmascarar` permite aplicar la política de enmascaramiento por rol
    (CRM-00.05.03.03): una exportación no puede sacar en claro lo que la API no
    enseña, porque sería la vía más fácil de saltarse la protección.
    """
    filas = db.execute(consulta.limit(limite)).scalars().all()
    salida: list[dict[str, Any]] = []
    for fila in filas:
        registro: dict[str, Any] = {}
        for columna in columnas:
            valor = getattr(fila, columna, None)
            registro[columna] = enmascarar(columna, valor) if enmascarar else valor
        salida.append(registro)
    return salida
