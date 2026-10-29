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


def _que_significa_vacio(db: Any, tenant_id: Any) -> str:
    """Por qué está vacío: no hay cambios, o este servicio no los anota.

    Son dos cosas muy distintas y con la lista vacía se ven igual. El rastro
    campo a campo lo escribe quien pasa por `registrar_cambios`, y **no todos
    los servicios lo hacen**: en los que no, esta ruta contestaría vacío para
    siempre y quien la mira concluiría que el registro no se ha tocado.

    Se distingue **midiendo**, no con una lista de servicios escrita aquí: si
    este servicio no tiene ningún cambio de campo de ningún registro de este
    tenant, lo que falta es el apunte, no el cambio. Una lista a mano se
    quedaría vieja el día que un sexto servicio empiece a anotarlos.
    """
    from sqlalchemy import exists, select

    from crmcore.audit.modelos import CambioCampo

    alguno = db.execute(select(exists().where(CambioCampo.tenant_id == tenant_id))).scalar()
    if alguno:
        return (
            "No consta ningún cambio de campo en este registro. Eso no es que no "
            "se haya tocado: es que no se ha tocado por una vía que lo anote."
        )
    return (
        "Este servicio no ha anotado ningún cambio de campo de ningún registro, "
        "así que el vacío no dice nada de ESTE: dice que aquí no se lleva ese "
        "histórico. Lo escribe quien edita pasando por el registro de cambios."
    )


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
        "/campos/{objeto}/{objeto_id}",
        dependencies=[Depends(exige_permiso("admin:read"))],
        summary="Qué cambió campo a campo, con quién y desde dónde",
        description=(
            "**Se escribía y no lo leía nadie.** Cada edición anota el campo, "
            "el valor anterior, el nuevo, quién lo hizo y **desde dónde** —la "
            "pantalla, la API o una automatización—, y ninguna ruta lo "
            "devolvía. La pregunta que esto contesta es la primera de "
            "cualquier discusión sobre un registro: «esto antes no decía "
            "esto».\n\n"
            "El **origen** es la mitad que casi nunca se guarda y la que "
            "resuelve la discusión: no es lo mismo que lo cambiara una persona "
            "que que lo pisara una sincronización todas las noches, y sin "
            "saberlo se culpa a quien pasaba por ahí.\n\n"
            "Va por servicio, como el resto del rastro: el histórico vive en "
            "el esquema del que guarda ese objeto, y ninguno lee el de otro."
        ),
    )
    def historial_de_campos(
        objeto: str,
        objeto_id: str,
        db: DbDep,
        principal: AutenticadoDep,
        campo: str | None = Query(None, description="Sólo este campo"),
        limite: int = Query(200, ge=1, le=1000),
    ) -> Any:
        from sqlalchemy import select

        from crmcore.audit.modelos import CambioCampo

        consulta = (
            select(CambioCampo)
            .where(
                CambioCampo.tenant_id == principal.tenant_id,
                CambioCampo.objeto == objeto,
                CambioCampo.objeto_id == str(objeto_id),
            )
            .order_by(CambioCampo.created_at.desc())
            .limit(limite)
        )
        if campo:
            consulta = consulta.where(CambioCampo.campo == campo)
        filas = db.execute(consulta).scalars().all()
        return {
            "objeto": objeto,
            "objeto_id": str(objeto_id),
            "cambios": [
                {
                    "campo": f.campo,
                    "valor_anterior": f.valor_anterior,
                    "valor_nuevo": f.valor_nuevo,
                    "actor_id": str(f.actor_id) if f.actor_id else None,
                    # Desde dónde se hizo. Es lo que separa «lo cambió alguien»
                    # de «lo pisa la sincronización todas las noches».
                    "origen": f.origen,
                    "cuando": f.created_at.isoformat() if f.created_at else None,
                }
                for f in filas
            ],
            "cuantos": len(filas),
            "que_significa": _que_significa_vacio(db, principal.tenant_id)
            if not filas
            else "Cada línea dice qué cambió, quién y desde dónde.",
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
