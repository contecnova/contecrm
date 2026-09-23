"""Change Data Capture hacia el lago del cliente (CRM-00.02.02.06).

Un cliente grande quiere sus datos del CRM en su propio lago para cruzarlos con
los del ERP, con los de producción y con lo que tenga. Lo que pide suena simple —
«mándanos los cambios»— y tiene tres formas de salir mal:

**El volcado completo cada noche.** Funciona con cien mil filas y deja de
funcionar con diez millones, justo cuando el cliente ya depende de ello.

**Mandar el cambio sin decir qué cambió.** Un flujo que solo dice «esta fila es
ahora así» obliga al otro lado a comparar contra lo que tenía, y si se perdió un
mensaje, ya no puede.

**Y mandarlo todo.** Un lago con los datos personales del CRM entero es otra copia
que proteger, en un sitio con otras reglas y otros permisos.

Las decisiones:

**Se manda el hecho, no la foto.** Qué se creó, qué cambió y de qué a qué. Con la
foto sola, el que recibe no puede reconstruir nada si se le escapó un mensaje; con
el hecho, sí.

**Se declara qué sale, campo a campo.** Y lo que es dato personal se dice en el
propio flujo, porque el lago del cliente no tiene por qué saberlo y su equipo de
datos no lo va a adivinar.

**El borrado viaja como borrado.** Un CDC que omite las bajas deja un lago que
crece para siempre con clientes que ya ejercieron su derecho de supresión — y el
incumplimiento pasa a estar en casa del cliente sin que él lo sepa.

**Y la marca de progreso solo avanza sobre lo confirmado.** Si avanzara al mandar,
un corte dejaría un hueco que nadie detecta hasta que cuadran cifras a fin de mes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué tipos de cambio se emiten. El borrado está dentro a propósito: un CDC que
# lo omite deja un lago que crece para siempre con datos que ya deberían haber
# desaparecido.
CAMBIOS = ("alta", "modificacion", "baja", "anonimizacion")

# Qué se manda de cada campo personal. No es una opción de configuración: es lo
# que decide si el cliente acaba con una segunda base de datos personales sin
# saberlo.
TRATO_PERSONAL = ("tal_cual", "seudonimizado", "omitido")


def declarar_flujo(
    *,
    objeto: str,
    campos: list[dict[str, Any]],
    destino: str,
    trato_por_defecto: str = "omitido",
) -> dict[str, Any]:
    """Declara qué sale del CRM hacia el lago, campo a campo.

    **Por defecto, lo personal no sale.** Es lo contrario de lo cómodo —mandarlo
    todo y que el cliente filtre— y es lo correcto: lo que sale ya no vuelve, y
    una vez está en su lago está bajo sus reglas, sus permisos y sus copias.

    Y lo que sale marcado como personal **viaja marcado**. El equipo de datos del
    cliente no va a adivinar cuál de esas cuarenta columnas es un correo, y sin
    saberlo lo tratará como cualquier otra.
    """
    if trato_por_defecto not in TRATO_PERSONAL:
        raise ErrorValidacion(
            f"Trato desconocido para el dato personal: «{trato_por_defecto}»",
            error_code="cdc.trato_invalido",
            detalle={"admitidos": list(TRATO_PERSONAL)},
        )

    salen: list[dict[str, Any]] = []
    fuera: list[dict[str, str]] = []
    for campo in campos:
        personal = str(campo.get("sensibilidad") or "") in ("personal", "especial")
        trato = str(campo.get("trato") or (trato_por_defecto if personal else "tal_cual"))
        if trato not in TRATO_PERSONAL:
            raise ErrorValidacion(
                f"Trato desconocido en «{campo.get('clave')}»: «{trato}»",
                error_code="cdc.trato_invalido",
            )
        if trato == "omitido":
            fuera.append(
                {
                    "campo": str(campo.get("clave")),
                    "porque": (
                        "es dato personal y no se ha pedido expresamente que salga"
                        if personal
                        else "declarado como omitido"
                    ),
                }
            )
            continue
        salen.append(
            {
                "clave": campo.get("clave"),
                "personal": personal,
                "trato": trato,
            }
        )

    return {
        "objeto": objeto,
        "destino": destino,
        "campos_que_salen": salen,
        # Lo que se queda, con el motivo. Sin esta lista, el cliente pide un campo
        # y nadie sabe si es que no existe o que se decidió no mandarlo.
        "campos_que_no_salen": fuera,
        "personales_que_salen": [c["clave"] for c in salen if c["personal"]],
        "aviso": (
            ""
            if not any(c["personal"] and c["trato"] == "tal_cual" for c in salen)
            else "Salen datos personales sin seudonimizar. Una vez están en el lago "
            "del cliente están bajo sus reglas y sus permisos, y eso hay que "
            "declararlo en el registro de tratamiento como transferencia."
        ),
    }


def componer_cambio(
    *,
    objeto: str,
    registro_id: UUID,
    tipo: str,
    antes: dict[str, Any] | None,
    despues: dict[str, Any] | None,
    campos_permitidos: list[str],
    secuencia: int,
) -> dict[str, Any]:
    """Compone un mensaje de cambio con **el hecho y no la foto**.

    Qué cambió y de qué a qué. Un flujo que solo manda «esta fila es ahora así»
    obliga al otro lado a comparar contra lo que tenía, y si se le escapó un
    mensaje ya no puede: se queda con una foto que no sabe de cuándo es.

    El **borrado viaja como borrado**, con su identificador y sin datos. Omitirlo
    deja un lago que crece para siempre con gente que ya ejerció su derecho de
    supresión — y el incumplimiento pasa a estar en casa del cliente sin que lo
    sepa.
    """
    if tipo not in CAMBIOS:
        raise ErrorValidacion(
            f"Tipo de cambio desconocido: «{tipo}»",
            error_code="cdc.tipo_invalido",
            detalle={"admitidos": list(CAMBIOS)},
        )

    permitidos = set(campos_permitidos)
    limpio_antes = {k: v for k, v in (antes or {}).items() if k in permitidos}
    limpio_despues = {k: v for k, v in (despues or {}).items() if k in permitidos}
    cambiados = sorted(k for k in permitidos if limpio_antes.get(k) != limpio_despues.get(k))

    mensaje: dict[str, Any] = {
        "objeto": objeto,
        "registro_id": str(registro_id),
        "tipo": tipo,
        # La secuencia es lo que permite al otro lado saber que le falta algo. Sin
        # ella, un mensaje perdido no se nota: simplemente hay un dato viejo.
        "secuencia": secuencia,
        "momento": datetime.now(timezone.utc).isoformat(),
    }
    if tipo in ("baja", "anonimizacion"):
        # Sin datos: en una baja, lo que hay que propagar es que ya no está, y
        # mandar la fila entera una última vez sería dejarla ahí para siempre.
        mensaje["campos_cambiados"] = []
        mensaje["sin_datos"] = True
        mensaje["que_hacer_en_el_destino"] = (
            "Borrar o anonimizar también allí. Si esto se ignora, el lago conserva "
            "datos de alguien que pidió que desaparecieran."
        )
        return mensaje

    mensaje["campos_cambiados"] = cambiados
    mensaje["antes"] = {k: limpio_antes.get(k) for k in cambiados}
    mensaje["despues"] = {k: limpio_despues.get(k) for k in cambiados}
    return mensaje


def avanzar_marca(
    *, marca_actual: int, confirmados: list[int], fallidos: list[int]
) -> dict[str, Any]:
    """Hasta dónde se puede dar por entregado.

    **Solo hasta el primer fallo.** Avanzar hasta el último confirmado dejaría el
    hueco de los que fallaron en medio, y ese hueco no se detecta: el lago
    simplemente tiene un dato viejo, y se descubre cuando alguien cuadra cifras a
    fin de mes y no le salen.
    """
    if not confirmados and not fallidos:
        return {
            "marca": marca_actual,
            "avanza": False,
            "porque": "No se ha confirmado nada todavía.",
        }
    tope_fallo = min(fallidos) if fallidos else None
    candidatos = [s for s in sorted(confirmados) if tope_fallo is None or s < tope_fallo]
    nueva = max(candidatos) if candidatos else marca_actual
    return {
        "marca": nueva,
        "avanza": nueva > marca_actual,
        "parada_en": tope_fallo,
        "porque": (
            f"Hay un fallo en la secuencia {tope_fallo}: la marca se queda antes. "
            "Avanzar hasta el último confirmado dejaría un hueco que no se detecta —"
            " el lago tendría un dato viejo y se descubriría cuadrando cifras."
            if tope_fallo is not None
            else "Todo lo mandado se ha confirmado."
        ),
    }
