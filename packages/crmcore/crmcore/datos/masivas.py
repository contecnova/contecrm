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

from crmcore.db.al_margen import al_margen
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
    # Los borrados se cuentan aparte y no como «actualizados». Parece un detalle
    # y no lo es: un informe que dice «500 actualizados» tras un borrado masivo
    # es la clase de frase que hace que nadie compruebe qué pasó de verdad.
    borrados: int = 0
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
        if len(self.errores) < _masivas_errores_devueltos():
            self.errores.append({"fila": fila, "motivo": motivo, **(detalle or {})})

    def a_dict(self) -> dict[str, Any]:
        d = {
            "total": self.total,
            "creados": self.creados,
            "actualizados": self.actualizados,
            "borrados": self.borrados,
            "omitidos": self.omitidos,
            "fallidos": self.fallidos,
            "errores": self.errores,
        }
        if self.fallidos > len(self.errores):
            d["errores_no_mostrados"] = self.fallidos - len(self.errores)
        if self.previsualizacion:
            d["previsualizacion"] = self.previsualizacion
        return d


def _masivas_errores_devueltos() -> int:
    """Tope del núcleo, antes `_masivas_errores_devueltos() = 200`.

    Era una constante de módulo. Sale del `.env`, no de los ajustes en
    caliente: es un tope operativo del despliegue y «por cliente» no
    significaría nada.
    """
    from crmcore.config import get_settings

    return get_settings().masivas_errores_devueltos


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
    # El modelo, solo para poder hacer `ANALYZE` sobre su tabla al terminar. Es
    # opcional porque no todo plan escribe en una sola tabla; sin él, la carga
    # funciona igual pero las consultas van lentas hasta que pase autovacuum.
    modelo: type | None = None
    # Tenant para el que se importa. Hace falta para resolver los campos propios
    # del esquema publicado (CRM-00.04.03.08); sin él, esas columnas se tratan
    # como desconocidas y el importador pierde en silencio justo los campos que
    # el cliente añadió porque le importaban.
    tenant_id: Any = None


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

    # Campos propios del tenant en la importación (CRM-00.04.03.08): el plan
    # declara qué columnas conoce, y las que no son de serie se validan contra el
    # esquema publicado. Ignorarlas dejaría fuera precisamente los campos que el
    # cliente añadió porque le importaban, y el importador que «funciona» sería
    # el que pierde la mitad del fichero.
    if plan.objeto and plan.tenant_id is not None and filas:
        from crmcore import metamodelo

        propios = {
            str(c.get("nombre")) for c in metamodelo.campos_de(db, plan.tenant_id, plan.objeto)
        }
        if propios:
            for fila in filas:
                sueltos = {k: fila.pop(k) for k in list(fila) if k in propios}
                if sueltos:
                    fila.setdefault("campos", {}).update(sueltos)

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

        # Un SAVEPOINT por fila. Antes era un `try` con `db.rollback()` dentro,
        # y ese `rollback` no deshace la fila mala: deshace **la transacción
        # entera**. El comentario de abajo decía «una fila mala no arrastra a
        # las 9.999 buenas» y el código hacía justo lo contrario — una carga de
        # diez mil filas con un fallo en la cinco mil perdía las 4.999
        # anteriores, y el informe seguía contándolas como creadas.
        punto = db.begin_nested()
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
            punto.commit()
        except Exception as exc:  # noqa: BLE001 — una fila mala no tumba la carga
            # `rollback()` SIEMPRE, no sólo si «sigue activo»: cuando el fallo
            # es de la base, SQLAlchemy desactiva el savepoint y aun así exige
            # deshacerlo antes de seguir. Con el `if`, la sesión se quedaba
            # envenenada y moría la instrucción SIGUIENTE, que no tiene nada
            # que ver. Ver `crmcore.db.al_margen`, donde está contado entero.
            punto.rollback()
            # El recuento también se deshace: lo subía antes de saber si la
            # fila entraba, y una carga con fallos decía haber creado más de
            # las que había.
            if existente is not None:
                informe.actualizados -= 1
            else:
                informe.creados -= 1
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
        if plan.modelo is not None:
            _actualizar_estadisticas(db, plan.modelo)
    return informe


def _actualizar_estadisticas(db: Session, modelo: type) -> None:
    """`ANALYZE` sobre la tabla recién cargada.

    **No es cosmético.** Tras una importación grande, el planificador sigue
    creyendo que la tabla está como estaba y descarta los índices: se midió una
    búsqueda pasando de 2,8 ms a 81 ms sobre los mismos 20.000 documentos, solo
    por estadísticas viejas. Autovacuum acabaría haciéndolo, pero puede tardar
    minutos — los mismos minutos en los que quien acaba de importar concluye que
    el sistema no aguanta su volumen.

    Un fallo aquí no puede tumbar la importación: los datos ya están dentro, y
    lo único que se pierde es que las consultas vayan lentas un rato.
    """
    from sqlalchemy import text as _text

    tabla = getattr(modelo, "__tablename__", "")
    if not tabla:
        return
    # Al margen de verdad: un `ANALYZE` que falla deja la sesión envenenada, y
    # esto corre al final de la importación —justo antes del volcado—, así que
    # una estadística se llevaría por delante las filas ya cargadas.
    with al_margen(db, "datos.analyze_fallido", tabla=tabla):
        db.execute(_text(f'ANALYZE "{tabla}"'))


def exportar(
    db: Session,
    consulta: Any,
    *,
    columnas: list[str],
    limite: int,
    enmascarar: Callable[[str, Any], Any] | None = None,
    proyectar: Callable[[Any], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Exporta el resultado de una consulta a filas planas.

    `enmascarar` permite aplicar la política de enmascaramiento por rol
    (CRM-00.05.03.03): una exportación no puede sacar en claro lo que la API no
    enseña, porque sería la vía más fácil de saltarse la protección.

    `proyectar` es la forma **completa** de lo mismo y la que usa la ruta de
    exportación: la proyección del producto resuelve la sensibilidad por rol,
    las excepciones y las políticas ABAC que dependen de la propia fila —«el
    margen de las oportunidades de otra unidad»—, y eso no cabe en una función
    que solo ve el nombre del campo y su valor. Lo que la proyección quita no
    aparece en el fichero: una columna que la pantalla no enseña y el CSV sí es
    la vía más fácil de saltarse la protección, y además la más silenciosa.
    """
    filas = db.execute(consulta.limit(limite)).scalars().all()
    salida: list[dict[str, Any]] = []
    for fila in filas:
        if proyectar is not None:
            visto = proyectar(fila)
            propios_visibles = visto.get("campos") if isinstance(visto.get("campos"), dict) else {}
            salida.append(
                {
                    columna: (
                        visto[columna]
                        if columna in visto
                        else (propios_visibles or {}).get(columna)
                    )
                    for columna in columnas
                    # Lo que la proyección no devolvió no se exporta vacío: se
                    # omite. Una columna en blanco se lee como «no hay dato»
                    # cuando lo que pasa es que esa persona no puede verlo.
                    if columna in visto or columna in (propios_visibles or {})
                }
            )
            continue
        registro: dict[str, Any] = {}
        for columna in columnas:
            # Campos propios del tenant (CRM-00.04.03.08). Se piden por su
            # nombre, igual que los de serie: quien exporta no tiene por qué
            # saber cuáles vienen con el producto y cuáles añadió su consultor,
            # y obligarle a distinguirlos sería trasladarle una decisión de
            # implementación nuestra.
            propios = getattr(fila, "campos", None)
            if columna not in ("campos",) and isinstance(propios, dict) and columna in propios:
                valor = propios[columna]
            else:
                valor = getattr(fila, columna, None)
            registro[columna] = enmascarar(columna, valor) if enmascarar else valor
        salida.append(registro)
    return salida


def columnas_exportables(
    db: Session, tenant_id: Any, objeto: str, columnas_base: list[str]
) -> list[str]:
    """Las columnas de serie más los campos propios del tenant.

    Es lo que hace que una exportación traiga lo que el cliente ve en su ficha y
    no lo que traía el producto de fábrica. Sin esto, la exportación es
    incompleta de una forma que solo nota quien conoce el dato — y lo nota
    demasiado tarde, cuando ya ha mandado el fichero.
    """
    from crmcore import metamodelo

    propios = [
        str(c.get("nombre"))
        for c in metamodelo.campos_de(db, tenant_id, objeto)
        if c.get("activo", True)
    ]
    # Sin duplicar y en orden estable: una exportación cuyas columnas cambian de
    # orden entre dos descargas rompe cualquier hoja de cálculo que la consuma.
    vistos = set(columnas_base)
    return [*columnas_base, *[c for c in propios if c not in vistos]]
