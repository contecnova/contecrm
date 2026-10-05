"""Operaciones masivas sobre cualquier recurso (CRM-00.02.01.11).

Crear, actualizar, insertar-o-actualizar y borrar muchos registros en una
llamada, con **informe de resultados parciales**: en un lote de diez mil, que
noventa estén mal no es razón para no escribir los 9.910 buenos, pero sí para
decir exactamente cuáles fallaron y por qué.

Es una fábrica: cada servicio declara qué sabe hacer con su recurso y monta el
router. Lo que `crmcore` aporta es lo que es idéntico en todos y no conviene
copiar cinco veces — los topes, el aislamiento entre elementos, el informe, y la
bifurcación a trabajo asíncrono cuando el lote es grande.

**Cada elemento va en su punto de guardado.** Sin eso, la fila 4.000 que viola
una restricción aborta la transacción entera de Postgres y las 3.999 anteriores
—correctas y ya escritas— se pierden: el informe diría «3.999 creados» y en la
base no habría ninguno. Un `SAVEPOINT` por elemento cuesta, y es exactamente lo
que se paga por que el informe no mienta.

**Dos caminos según el tamaño, y el cliente no elige por capricho.** Hasta
`bulk_max_items` se ejecuta en la propia petición y se responde con el informe.
Por encima se rechaza con un 413 que dice cómo pedirlo en diferido: un lote de
cincuenta mil en una petición síncrona acaba siempre igual, con el proxy
cortando a los treinta segundos y el cliente sin saber qué se escribió.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from crmcore.datos.masivas import Informe
from crmcore.datos.trabajos import Tanda, Trabajo, encolar, registrar_ejecutor
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import CuerpoDemasiadoGrande, ErrorValidacion
from crmcore.http.deps import AutenticadoDep, UowDep
from crmcore.logging import get_logger

logger = get_logger(__name__)

OPERACIONES = ("crear", "actualizar", "upsert", "borrar")


@dataclass(frozen=True)
class RecursoMasivo:
    """Lo que un servicio declara para que su recurso admita lotes.

    Las funciones son las del propio servicio, no una reimplementación: un alta
    masiva tiene que pasar por la misma validación, la misma normalización y los
    mismos eventos que un alta de una en una. Un camino masivo que escribe
    directamente en la tabla es cómo se cuelan en el maestro los registros que
    ninguna pantalla habría dejado guardar.
    """

    recurso: str
    objeto: str
    permisos: dict[str, str]
    # Reciben la unidad de trabajo y no la sesión: un alta masiva tiene que
    # emitir los mismos eventos de dominio que un alta suelta, y son los eventos
    # los que disparan la indexación, las automatizaciones y los webhooks. Con
    # una sesión pelada, importar diez mil cuentas las dejaría fuera del buscador
    # y sin una sola regla ejecutada, y el fallo no daría la cara hasta que
    # alguien buscara una.
    crear: Callable[[UnidadDeTrabajo, dict[str, Any]], UUID] | None = None
    actualizar: Callable[[UnidadDeTrabajo, UUID, dict[str, Any]], None] | None = None
    borrar: Callable[[UnidadDeTrabajo, UUID], None] | None = None
    # Resuelve el identificador de un elemento ya existente a partir de sus
    # datos: es lo que distingue un `upsert` de un `crear`. Sin esta función el
    # servicio no ofrece `upsert`, y se dice en el error en vez de hacer un alta
    # y llamarlo actualización.
    buscar: Callable[[Session, dict[str, Any]], UUID | None] | None = None

    @property
    def tipo_trabajo(self) -> str:
        return f"{self.recurso}.masivo"

    def admite(self, operacion: str) -> bool:
        if operacion == "crear":
            return self.crear is not None
        if operacion == "actualizar":
            return self.actualizar is not None
        if operacion == "borrar":
            return self.borrar is not None
        if operacion == "upsert":
            return self.buscar is not None and self.crear is not None
        return False

    def permiso_de(self, operacion: str) -> str:
        # `upsert` exige el permiso de crear: es el más fuerte de los dos que
        # puede acabar ejecutando, y conceder el de actualizar no debería
        # permitir dar de alta por la puerta de atrás.
        clave = "crear" if operacion == "upsert" else operacion
        return self.permisos[clave]


class PeticionMasiva(BaseModel):
    operacion: str = Field(description="crear | actualizar | upsert | borrar")
    elementos: list[dict[str, Any]] = Field(default_factory=list)
    # URL de aviso, solo en el camino diferido. Va validada contra el guard de
    # salidas antes de guardarse.
    callback_url: str = ""


# ── Ejecución de un lote ──────────────────────────────────────────────────


def _id_de(elemento: dict[str, Any], fila: int) -> UUID:
    bruto = elemento.get("id")
    if not bruto:
        raise ErrorValidacion(f"Falta «id» en la fila {fila}", error_code="masivo.sin_id")
    try:
        return UUID(str(bruto))
    except ValueError as exc:
        raise ErrorValidacion(
            f"«id» no es un identificador válido en la fila {fila}",
            error_code="masivo.id_invalido",
        ) from exc


def aplicar(
    uow: UnidadDeTrabajo,
    recurso: RecursoMasivo,
    operacion: str,
    elementos: list[dict[str, Any]],
    *,
    informe: Informe,
    desplazamiento: int = 0,
) -> None:
    """Ejecuta los elementos uno a uno sobre el informe dado.

    `desplazamiento` es el índice del primer elemento dentro del lote completo.
    Importa porque el informe de un trabajo reanudado se construye a trozos y
    quien lee «fila 7» está mirando su hoja de cálculo, no la tanda tercera.
    """
    db = uow.db
    for i, elemento in enumerate(elementos):
        fila = desplazamiento + i + 1
        campos = {k: v for k, v in elemento.items() if k != "id"}
        # Cuántos eventos había antes de tocar este elemento. Si el elemento
        # falla y su punto de guardado se deshace, los eventos que hubiera
        # emitido tienen que irse con él: dejarlos publicaría un «cuenta creada»
        # de una cuenta que no existe, y el consumidor que la busque no la
        # encontrará nunca.
        eventos_antes = len(uow._pendientes)
        # Un punto de guardado por elemento: ver la cabecera del módulo.
        punto = db.begin_nested()
        try:
            if operacion == "crear":
                assert recurso.crear is not None
                recurso.crear(uow, elemento)
                informe.creados += 1
            elif operacion == "actualizar":
                assert recurso.actualizar is not None
                recurso.actualizar(uow, _id_de(elemento, fila), campos)
                informe.actualizados += 1
            elif operacion == "borrar":
                assert recurso.borrar is not None
                recurso.borrar(uow, _id_de(elemento, fila))
                informe.borrados += 1
            elif operacion == "upsert":
                assert recurso.buscar is not None and recurso.crear is not None
                existente = recurso.buscar(db, elemento)
                if existente is None:
                    recurso.crear(uow, elemento)
                    informe.creados += 1
                else:
                    if recurso.actualizar is None:
                        raise ErrorValidacion(
                            f"«{recurso.objeto}» ya existe y este recurso no admite actualizarlo",
                            error_code="masivo.upsert_sin_actualizar",
                        )
                    recurso.actualizar(uow, existente, campos)
                    informe.actualizados += 1
            punto.commit()
        except Exception as exc:  # noqa: BLE001 — un elemento malo no tumba el lote
            punto.rollback()
            del uow._pendientes[eventos_antes:]
            codigo = getattr(exc, "error_code", "") or type(exc).__name__
            informe.anotar_error(fila, str(exc)[:300], {"codigo": codigo})
        informe.total += 1


def _ejecutor_masivo(recurso: RecursoMasivo) -> Any:
    """Construye el ejecutor del trabajo diferido para este recurso."""

    def ejecutar(db: Session, trabajo: Trabajo, tope: int) -> Tanda:
        elementos: list[dict[str, Any]] = trabajo.entrada.get("elementos", [])
        operacion: str = trabajo.entrada.get("operacion", "")
        trozo = elementos[trabajo.cursor : trabajo.cursor + tope]
        if not trozo:
            return Tanda(avanzados=0, total=len(elementos))

        informe = Informe()
        uow = UnidadDeTrabajo(db=db, tenant_id=trabajo.tenant_id)
        aplicar(
            uow,
            recurso,
            operacion,
            trozo,
            informe=informe,
            desplazamiento=trabajo.cursor,
        )
        # Los eventos se vuelcan aquí y los confirma el commit de la tanda, en la
        # misma transacción que el cursor. Es la misma garantía del outbox
        # llevada al trabajo largo: o avanza el cursor y salen los eventos, o no
        # avanza ninguno de los dos.
        uow.volcar()
        return Tanda(
            avanzados=len(trozo),
            ok=informe.creados + informe.actualizados + informe.borrados,
            fallidos=informe.fallidos,
            errores=informe.errores,
            total=len(elementos),
            resultado={
                # Acumulado, no de la tanda: quien mira la ficha quiere el total
                # del trabajo, y sumar las tandas a mano no es cosa suya.
                "creados": trabajo.resultado.get("creados", 0) + informe.creados,
                "actualizados": trabajo.resultado.get("actualizados", 0) + informe.actualizados,
                "borrados": trabajo.resultado.get("borrados", 0) + informe.borrados,
            },
        )

    return ejecutar


# ── Router ────────────────────────────────────────────────────────────────


def registrar_recursos(recursos: tuple[RecursoMasivo, ...] | list[RecursoMasivo]) -> None:
    """Declara los ejecutores diferidos de estos recursos.

    Va aparte de montar el router, y esa separación tiene una razón concreta:
    **el worker es otro proceso y no monta routers**. Registrar dentro de la
    fábrica dejaba al worker sin un solo ejecutor, con los trabajos encolados
    para siempre y una ficha que decía «encolado» sin que nada estuviera roto a
    la vista. Se descubrió al escribir el worker, antes de que llegara a correr.

    Llamarla es lo que hace el módulo `masivo.py` de cada servicio, que importan
    tanto la API como el worker.
    """
    for recurso in recursos:
        registrar_ejecutor(recurso.tipo_trabajo, _ejecutor_masivo(recurso))


def crear_router_masivo(recurso: RecursoMasivo) -> APIRouter:
    """Monta `POST /<recurso>/masivo`."""
    from crmcore.datos.trabajos import ejecutor_de

    if ejecutor_de(recurso.tipo_trabajo) is None:
        # Al arrancar y no al primer 202: un servicio que expone el camino
        # diferido sin ejecutor aceptaría trabajos que nadie va a ejecutar.
        raise RuntimeError(
            f"«{recurso.recurso}» monta el router masivo sin haber registrado su "
            f"ejecutor. Llama a registrar_recursos() al declarar el recurso."
        )

    router = APIRouter(tags=["masivo"])

    @router.post(
        f"/{recurso.recurso}/masivo",
        summary=f"Operación masiva sobre {recurso.recurso}",
        status_code=status.HTTP_207_MULTI_STATUS,
    )
    def masivo(
        principal: AutenticadoDep,
        uow: UowDep,
        respuesta: Response,
        peticion: PeticionMasiva = Body(...),
        modo: str = Query("sincrono", pattern="^(sincrono|asincrono)$"),
    ) -> Any:
        from crmcore.config import get_settings
        from crmcore.runtime import settings as rt

        operacion = peticion.operacion
        if operacion not in OPERACIONES:
            raise ErrorValidacion(
                f"Operación desconocida: «{operacion}»",
                error_code="masivo.operacion_invalida",
                detalle={"admitidas": list(OPERACIONES)},
            )
        if not recurso.admite(operacion):
            raise ErrorValidacion(
                f"«{recurso.recurso}» no admite la operación «{operacion}»",
                error_code="masivo.operacion_no_soportada",
                detalle={"admitidas": [o for o in OPERACIONES if recurso.admite(o)]},
            )
        # El permiso se comprueba aquí y no como dependencia del router porque
        # depende de la operación que traiga el cuerpo: una sola dependencia
        # obligaría a exigir el permiso más fuerte para todas, y quien solo puede
        # actualizar no podría actualizar en lote.
        principal.exigir(recurso.permiso_de(operacion))
        # Y el borrado en bloque exige reverificarse. Va aquí dentro y no como
        # dependencia del router por lo mismo que el permiso: depende de la
        # operación que traiga el cuerpo, y pedirla para todas obligaría a
        # teclear el segundo factor para actualizar cien direcciones.
        if operacion == "borrar":
            from crmcore.http.reverificacion import comprobar as exigir_reverificacion

            exigir_reverificacion(principal, "borrado_masivo", db=uow.db)
        if not peticion.elementos:
            raise ErrorValidacion("No hay elementos que procesar", error_code="masivo.lote_vacio")

        db = uow.db
        cfg = get_settings()
        tope_sincrono = int(rt.efectivo("bulk_max_items", db) or cfg.bulk_max_items)
        tope_diferido = int(rt.efectivo("trabajo_max_items", db) or cfg.trabajo_max_items)
        cuantos = len(peticion.elementos)

        if modo == "asincrono":
            if cuantos > tope_diferido:
                raise CuerpoDemasiadoGrande(
                    f"Un trabajo admite como mucho {tope_diferido} elementos",
                    error_code="masivo.lote_excesivo",
                    detalle={"maximo": tope_diferido, "recibidos": cuantos},
                )
            trabajo = encolar(
                db,
                tenant_id=principal.tenant_id,
                tipo=recurso.tipo_trabajo,
                entrada={"operacion": operacion, "elementos": peticion.elementos},
                total=cuantos,
                callback_url=peticion.callback_url,
                pedido_por=principal.id,
            )
            respuesta.status_code = status.HTTP_202_ACCEPTED
            # `Location` apunta a donde se sondea. Es lo que convierte el 202 en
            # una respuesta accionable en vez de un «vale» sin continuación.
            #
            # Es la ruta **pública**, con el prefijo de la API y el nombre del
            # servicio, porque quien la sigue está fuera y entra por el gateway.
            # Devolver `/trabajos/{id}` a secas mandaba a una ruta que el
            # gateway no sabe enrutar —trabajos los tienen varios servicios— y
            # el cliente que hacía lo que la cabecera decía recibía un 404.
            respuesta.headers["Location"] = (
                f"{cfg.api_prefix}/{cfg.service_name}/trabajos/{trabajo.id}"
            )
            from crmcore.datos.trabajos import a_dict as ficha

            return ficha(trabajo)

        if cuantos > tope_sincrono:
            raise CuerpoDemasiadoGrande(
                f"En una sola petición caben {tope_sincrono} elementos. "
                f"Para más, repite la llamada con ?modo=asincrono",
                error_code="masivo.lote_excesivo",
                detalle={
                    "maximo": tope_sincrono,
                    "recibidos": cuantos,
                    "alternativa": f"POST /{recurso.recurso}/masivo?modo=asincrono",
                },
            )

        informe = Informe()
        aplicar(uow, recurso, operacion, peticion.elementos, informe=informe)
        # No hay commit aquí: lo hace la dependencia al cerrar, después de volcar
        # los eventos. Hacerlo antes dejaría fuera de la transacción los eventos
        # del propio lote.
        logger.info(
            "masivo.ejecutado",
            recurso=recurso.recurso,
            operacion=operacion,
            total=informe.total,
            fallidos=informe.fallidos,
        )
        # 207 incluso cuando todo va bien: el cliente que lee el informe lo lee
        # siempre igual, y no tiene que tratar dos formas distintas de éxito.
        return informe.a_dict()

    return router
