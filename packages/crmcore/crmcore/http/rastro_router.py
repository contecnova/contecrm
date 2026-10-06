"""El rastro completo de un agregado, servido por servicio (CRM-00.05.04.06).

La pregunta que resuelve es una sola y llega siempre tarde: **«¿cómo estaba esto
el 3 de marzo?»**. El historial de campos dice qué cambió; no dice cómo era el
conjunto, y reconstruirlo a mano encadenando cambios sale mal en cuanto hay una
fusión o un borrado por medio.

Estaba entero y apagado. La tabla de hechos se creaba en dos servicios,
`declarar_agregado` no la llamaba nadie —así que `anotar` rechazaba cualquier
hecho por «agregado no declarado»— y la tabla estaba **siempre vacía**. Un rastro
vacío no da error: contesta que no hay nada, que es exactamente lo que contestaría
si todo fuera bien y nadie hubiera tocado ese registro.

Va por servicio, como la papelera: los hechos de cada agregado viven en el esquema
del servicio que lo guarda, y la comparación con el estado vivo necesita leer su
tabla.

**La más importante de las tres rutas es la que compara.** Una reconstrucción que
no cuadra con el estado vivo significa que alguien escribió en la tabla sin pasar
por aquí —un script de corrección, una migración, un arreglo a mano un viernes— y
a partir de ahí el rastro deja de ser una prueba sin que nadie se entere.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from crmcore.datos import event_sourcing as es
from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso


def crear_router_rastro(servicio: str) -> APIRouter:
    router = APIRouter(prefix=f"/{servicio}/rastro", tags=["rastro de agregados"])

    @router.get(
        "",
        dependencies=[Depends(exige_permiso("admin:read"))],
        summary="Qué objetos tienen el rastro completo encendido, y por qué",
        description=(
            "**Opcional y por agregado.** Guardar todos los hechos de todos los "
            "objetos multiplica la escritura y el almacenamiento por algo que "
            "nadie va a consultar de la mayoría. Se enciende donde importa y se "
            "dice dónde está encendido — que es la mitad que casi nunca se "
            "publica, y sin ella nadie sabe de qué objetos puede preguntar.\n\n"
            "Cada uno lleva **el motivo por el que se encendió**: dentro de dos "
            "años alguien mirará por qué esta tabla ocupa lo que ocupa, y «porque "
            "sí» no es una respuesta que permita apagarlo con tranquilidad."
        ),
    )
    def declarados(principal: AutenticadoDep) -> Any:
        declarados = es.agregados_declarados()
        return {
            "servicio": servicio,
            "agregados": declarados,
            "porque": (
                "Ninguno tiene el rastro completo encendido en este servicio. No es "
                "que falte: encenderlo para todo multiplica la escritura por algo "
                "que casi nunca se consulta."
                if not declarados
                else "Cada uno con el motivo por el que se encendió."
            ),
        }

    @router.get(
        "/{objeto}/{objeto_id}",
        dependencies=[Depends(exige_permiso("admin:read"))],
        summary="Cómo estaba este agregado en un momento dado",
        description=(
            "Sin `hasta`, cómo está ahora según el rastro. Con `hasta`, cómo "
            "estaba ese día — que es la pregunta real.\n\n"
            "**Los hechos compensados se aplican y se anulan, no se saltan.** "
            "Saltarlos daría el estado que habría habido si nadie se hubiera "
            "equivocado, que no es lo que pasó y no sirve para explicar nada.\n\n"
            "Esto **no sustituye la tabla viva**: reconstruir para pintar una "
            "ficha haría lento lo que se usa mil veces al día para servir lo que "
            "se pregunta una vez al año."
        ),
    )
    def reconstruir(
        objeto: str,
        objeto_id: UUID,
        db: DbDep,
        principal: AutenticadoDep,
        hasta: datetime | None = Query(None),
    ) -> Any:
        _exigir_declarado(objeto)
        return es.reconstruir(
            db, principal.tenant_id, objeto=objeto, objeto_id=objeto_id, hasta=hasta
        )

    @router.get(
        "/{objeto}/{objeto_id}/cuadra",
        dependencies=[Depends(exige_permiso("admin:read"))],
        summary="Si la reconstrucción cuadra con la tabla viva",
        description=(
            "Es la comprobación que casi nadie hace y la única que detecta lo que "
            "de verdad pasa: **alguien escribió en la tabla sin pasar por aquí**. "
            "Un script de corrección, una migración, un arreglo a mano un "
            "viernes. A partir de ahí el rastro deja de ser una prueba y nadie se "
            "entera, porque sigue contestando con la misma seguridad.\n\n"
            "Se comparan solo los campos que el rastro conoce: exigirle que "
            "explique columnas en las que nunca se anotó nada daría una "
            "diferencia en cada fila y haría ilegible la única señal que "
            "importa."
        ),
    )
    def cuadra(objeto: str, objeto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.metamodelo import es_de_este_servicio, modelo_del_objeto

        _exigir_declarado(objeto)
        # Por el DUEÑO: ver `es_de_este_servicio`. Comparar lo vivo de otro
        # servicio contra el rastro de este da diferencias en cada campo.
        modelo = modelo_del_objeto(objeto) if es_de_este_servicio(objeto, servicio) else None
        if modelo is None:
            raise NoEncontrado(
                f"«{objeto}» no lo guarda «{servicio}», así que aquí no hay tabla viva "
                "con la que comparar. La comparación la hace el servicio dueño.",
                error_code="rastro.objeto_de_otro_servicio",
            )
        fila = db.get(modelo, objeto_id)
        if fila is None or getattr(fila, "tenant_id", None) != principal.tenant_id:
            raise NoEncontrado(
                "Ese registro no existe en la tabla viva. Si el rastro tiene hechos "
                "suyos, lo que falta es la fila: alguien la borró sin pasar por aquí.",
                error_code="rastro.registro_no_encontrado",
            )
        estado_vivo = fila.a_dict() if hasattr(fila, "a_dict") else {}
        reconstruido = es.reconstruir(db, principal.tenant_id, objeto=objeto, objeto_id=objeto_id)[
            "estado"
        ]
        return es.cuadra_con_lo_vivo(
            db,
            principal.tenant_id,
            objeto=objeto,
            objeto_id=objeto_id,
            estado_vivo=estado_vivo,
            # Solo lo que el rastro conoce. Comparar contra todas las columnas
            # del modelo marcaría como diferencia cada campo en el que nunca se
            # anotó nada, y la señal de verdad —alguien escribió por fuera— se
            # perdería entre cuarenta diferencias que no significan nada.
            campos=sorted(reconstruido),
        )

    def _exigir_declarado(objeto: str) -> None:
        declarados = es.agregados_declarados()
        if objeto not in declarados:
            raise NoEncontrado(
                f"«{objeto}» no tiene el rastro completo encendido, así que no hay "
                "nada que reconstruir. Un rastro vacío contestaría lo mismo que si "
                "todo fuera bien, y eso es peor que decirlo.",
                error_code="rastro.agregado_no_declarado",
                detalle={"declarados": sorted(declarados)},
            )

    return router
