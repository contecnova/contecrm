"""Recuperar registros concretos de una exportación (CRM-00.06.02.03).

La papelera cubre el borrado de un usuario. La restauración de clúster cubre el
desastre. Entre las dos hay un hueco enorme, y es donde caen casi todos los
casos reales: una importación que machacó trescientas cuentas, una
automatización mal escrita que vació un campo, alguien que fusionó lo que no
tocaba. Nada de eso es un desastre y ninguno lo arregla la papelera.

Restaurar el clúster entero para recuperar trescientas filas significa tirar
todo el trabajo hecho desde el punto de restauración. Es la razón por la que en
la práctica **no se restaura**: se arregla a mano, mal, durante días.

Tres decisiones:

**Se restaura desde una exportación verificada**, que es lo único de lo que se
sabe con certeza que se puede leer. Una copia que no se ha releído no prueba
nada.

**Se previsualiza antes**. Quien restaura casi nunca sabe exactamente qué va a
sobrescribir, y descubrirlo después es cambiar un problema por otro.

**Nunca se restaura en silencio sobre lo actual**: lo que cambió después del
punto de restauración se dice, y se decide qué hacer con ello.

**Un registro que ya no está se vuelve a crear.** Saltárselo dejaría fuera el
caso más común de todos —alguien borró lo que no tocaba—, que es justamente
para lo que existe esto.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from crmcore.errors import Conflicto, NoEncontrado
from crmcore.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Diferencia:
    """Qué pasaría con un registro concreto si se restaurase."""

    id: str
    estado: str  # ausente | igual | distinto
    campos_distintos: list[str]
    modificado_despues: bool = False


def leer_exportacion(uri_o_clave: str, tabla: str) -> dict[str, dict[str, Any]]:
    """Las filas de una tabla dentro de una exportación, por identificador.

    Se lee del almacén y se indexa por `id`: restaurar registros concretos es
    una búsqueda por identificador, y recorrer el fichero por cada uno haría que
    restaurar trescientos costara trescientas pasadas.
    """
    from crmcore.almacen import get_almacen

    crudo = get_almacen().leer(f"{uri_o_clave}/{tabla}.jsonl")
    filas: dict[str, dict[str, Any]] = {}
    for linea in crudo.decode("utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            fila = json.loads(linea)
        except json.JSONDecodeError:
            # Una línea corrupta no invalida el resto: se salta y se cuenta.
            # Abortar por una línea dejaría sin restaurar las otras doscientas
            # noventa y nueve, que están perfectamente.
            logger.warning("restaurar.linea_ilegible", tabla=tabla)
            continue
        if "id" in fila:
            filas[str(fila["id"])] = fila
    return filas


def previsualizar(
    db: Session,
    modelo: type,
    *,
    origen: dict[str, dict[str, Any]],
    ids: list[str],
    desde: datetime | None = None,
) -> list[Diferencia]:
    """Qué cambiaría, antes de cambiar nada.

    Marca aparte lo **modificado después** del punto de restauración: eso es
    trabajo que alguien hizo a sabiendas, y sobrescribirlo sin avisar cambia un
    problema por otro peor — porque el primero se conocía y el segundo no.
    """
    salida: list[Diferencia] = []
    for identificador in ids:
        guardado = origen.get(identificador)
        if guardado is None:
            continue
        actual = db.get(modelo, UUID(identificador))
        if actual is None:
            salida.append(Diferencia(id=identificador, estado="ausente", campos_distintos=[]))
            continue

        vivo = actual.a_dict(json_seguro=True) if hasattr(actual, "a_dict") else {}
        distintos = sorted(
            campo
            for campo, valor in guardado.items()
            # `updated_at` y compañía cambian siempre: sacarlos como diferencia
            # llenaría el informe de ruido y escondería las de verdad.
            if campo not in ("updated_at", "version", "updated_by", "updated_origen")
            and vivo.get(campo) != valor
        )
        modificado = bool(
            desde and getattr(actual, "updated_at", None) and actual.updated_at > desde
        )
        salida.append(
            Diferencia(
                id=identificador,
                estado="igual" if not distintos else "distinto",
                campos_distintos=distintos,
                modificado_despues=modificado,
            )
        )
    return salida


def restaurar(
    db: Session,
    modelo: type,
    *,
    origen: dict[str, dict[str, Any]],
    ids: list[str],
    tenant_id: UUID,
    objeto: str,
    por: UUID | None = None,
    forzar_modificados: bool = False,
    desde: datetime | None = None,
) -> dict[str, Any]:
    """Devuelve registros concretos a como estaban, dejando rastro.

    Lo modificado después **no se toca** salvo que se diga explícitamente
    (`forzar_modificados`). Es una decisión y tiene que escribirse: pisar el
    trabajo de alguien sin que nadie lo haya pedido es la forma más rápida de que
    una recuperación se convierta en una incidencia mayor que la original.
    """
    from crmcore.audit import registrar

    diferencias = {d.id: d for d in previsualizar(db, modelo, origen=origen, ids=ids, desde=desde)}
    restaurados: list[str] = []
    recreados: list[str] = []
    saltados: list[dict[str, str]] = []

    for identificador in ids:
        guardado = origen.get(identificador)
        if guardado is None:
            saltados.append({"id": identificador, "motivo": "no está en la exportación"})
            continue
        diferencia = diferencias.get(identificador)
        if diferencia and diferencia.modificado_despues and not forzar_modificados:
            saltados.append(
                {"id": identificador, "motivo": "modificado después del punto de restauración"}
            )
            continue

        fila = db.get(modelo, UUID(identificador))
        if fila is None:
            # El registro ya no está: se vuelve a crear con lo que decía la
            # exportación. Saltarlo sería dejar fuera **el caso más común** —una
            # importación o una automatización que borró lo que no tocaba—, que
            # es precisamente para lo que existe esta recuperación.
            #
            # El tenant se comprueba sobre lo exportado, porque aquí no hay fila
            # viva con la que contrastar: recrear en otro tenant sería escribir
            # datos de un cliente en la base de otro, con un rastro de auditoría
            # que diría que fue una recuperación legítima.
            if str(guardado.get("tenant_id", "")) != str(tenant_id):
                raise Conflicto(
                    "Ese registro no es de este tenant", error_code="restaurar.otro_tenant"
                )
            columnas = {c.name for c in modelo.__table__.columns}
            fila = modelo(**{k: v for k, v in guardado.items() if k in columnas})
            db.add(fila)
            recreados.append(identificador)
            restaurados.append(identificador)
            continue
        if str(getattr(fila, "tenant_id", "")) != str(tenant_id):
            # Restaurar sobre otro tenant sería la peor fuga posible: datos de
            # un cliente escritos en la base de otro, con rastro de auditoría
            # que dice que fue una recuperación legítima.
            raise Conflicto("Ese registro no es de este tenant", error_code="restaurar.otro_tenant")

        for campo, valor in guardado.items():
            if campo in ("id", "tenant_id", "created_at"):
                continue
            if hasattr(fila, campo):
                setattr(fila, campo, valor)
        restaurados.append(identificador)

    db.flush()
    registrar(
        db,
        accion="datos.restaurados",
        objeto=objeto,
        datos={
            "restaurados": len(restaurados),
            # Recrear un registro borrado y sobrescribir uno vivo son dos cosas
            # distintas, y quien lea la auditoría meses después necesita saber
            # cuál fue: una devolvió algo que no estaba y la otra pisó algo que sí.
            "recreados": len(recreados),
            "saltados": len(saltados),
            "forzando_modificados": forzar_modificados,
            "ids": restaurados[:50],
        },
        motivo="Restauración selectiva",
        tenant_id=tenant_id,
    )
    logger.warning(
        "datos.restaurados",
        objeto=objeto,
        restaurados=len(restaurados),
        recreados=len(recreados),
        saltados=len(saltados),
        por=str(por),
    )
    if not restaurados and saltados:
        raise NoEncontrado(
            "No se ha restaurado nada: revisa el detalle de lo que se ha saltado",
            error_code="restaurar.nada_restaurado",
            detalle={"saltados": saltados[:20]},
        )
    return {"restaurados": restaurados, "recreados": recreados, "saltados": saltados}
