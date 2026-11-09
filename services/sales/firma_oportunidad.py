"""Enviar a firma desde la oportunidad, y que la firma mueva la etapa
(CRM-03.03.02.07).

El sobre vive en `integration` y se crea por HTTP: este servicio no escribe su
esquema. Lo que sí es de aquí es **la oportunidad**: con qué presupuesto se
firma, en qué estado está la firma y a qué etapa la lleva.

**La etapa la decide quien gobierna el embudo**, no el código. Un sobre
completado dice que está firmado, no que el negocio esté ganado —puede faltar
el pedido, el pago o una aprobación—, así que sólo se mueve si el embudo lo
tiene configurado (`firma_etapa_por_embudo`). Si no, se marca la firma y nada
más, que es lo que se hacía.

Y la etapa se mueve **por el camino de siempre** (`cambiar_etapa`): con sus
criterios de salida y su historial. Si los criterios no se cumplen no se fuerza:
se anota por qué no se movió y la ficha lo dice.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoDisponible, NoEncontrado
from crmcore.logging import get_logger
from sqlalchemy import select

logger = get_logger(__name__)

# El evento del motor de firma trae el estado en inglés (`signature.envelope.
# completed`); la ficha lo enseña con los estados del sobre, que son los que
# se ven en «Pendiente de firma». Dos nombres para lo mismo en dos pantallas
# es lo que hace que nadie se fíe de ninguna.
ESTADO_DEL_EVENTO = {
    "created": "borrador",
    "sent": "enviado",
    "viewed": "en_curso",
    "signed": "en_curso",
    "completed": "completado",
    "rejected": "rechazado",
    "declined": "rechazado",
    "expired": "caducado",
    "cancelled": "cancelado",
}


def _espera(db: Any) -> float:
    from crmcore.runtime import settings as rt

    from services.sales.ajustes import ajustes

    valor = rt.efectivo("firma_espera_s", db)
    return float(valor if valor is not None else ajustes().firma_espera_s)


def _etapa_tras_firma(db: Any, oportunidad: Any) -> Any:
    """La etapa a la que lleva una firma completada en el embudo de esta
    oportunidad, o `None` si su embudo no lo tiene configurado."""
    from crmcore.runtime import settings as rt

    from services.sales.ajustes import ajustes
    from services.sales.modelos import Etapa, Pipeline

    mapa = rt.efectivo("firma_etapa_por_embudo", db)
    if mapa is None:
        mapa = ajustes().firma_etapa_por_embudo
    if not isinstance(mapa, dict) or not mapa:
        return None
    embudo = db.get(Pipeline, oportunidad.pipeline_id)
    clave = mapa.get(embudo.clave) if embudo is not None else None
    if not clave:
        return None
    return db.execute(
        select(Etapa).where(Etapa.pipeline_id == oportunidad.pipeline_id, Etapa.clave == clave)
    ).scalar_one_or_none()


def aplicar_estado(
    uow: UnidadDeTrabajo,
    oportunidad: Any,
    *,
    estado: str,
    sobre_id: str = "",
    referencia: str = "",
    motivo: str = "",
) -> dict[str, Any]:
    """Escribe el estado de la firma en la oportunidad y, si se completó y el
    embudo lo dice, la lleva a su etapa.

    Lo llaman el consumidor del evento y la consulta de la ficha: los dos
    caminos tienen que dejar lo mismo. Idempotente: la etapa se mueve una vez
    por sobre, aunque el evento llegue dos veces o la ficha se recargue.
    """
    from services.sales import servicio as svc

    estado = ESTADO_DEL_EVENTO.get(estado, estado)
    campos = dict(oportunidad.campos or {})
    campos["firma_estado"] = estado
    if sobre_id:
        campos["firma_sobre_id"] = sobre_id
    if referencia:
        campos["firma_referencia"] = referencia
    if motivo:
        campos["firma_motivo"] = motivo
    movida = None
    if estado == "completado" and campos.get("firma_etapa_aplicada") != (sobre_id or "-"):
        destino = _etapa_tras_firma(uow.db, oportunidad)
        if destino is not None:
            campos["firma_etapa_aplicada"] = sobre_id or "-"
            oportunidad.campos = campos
            uow.db.flush()
            try:
                svc.cambiar_etapa(
                    uow, oportunidad.id, etapa_id=destino.id, motivo="Firma completada"
                )
                movida = destino.nombre
                campos.pop("firma_etapa_error", None)
            except (ErrorValidacion, Conflicto) as exc:
                # No se fuerza: los criterios de salida son lo que hace que la
                # previsión signifique algo. Se deja escrito por qué no se movió.
                campos["firma_etapa_error"] = str(exc)[:500]
                logger.info("sales.firma_no_mueve_etapa", oportunidad=str(oportunidad.id))
    oportunidad.campos = campos
    uow.db.flush()
    return {"estado": estado, "etapa_movida_a": movida}


def _presupuesto(
    db: Any, tenant_id: UUID, oportunidad_id: UUID, presupuesto_id: UUID | None
) -> Any:
    """El presupuesto que se firma: el pedido, o el último vivo de la
    oportunidad. Un sustituido no se firma: obliga a lo que ya no se ofrece."""
    from crmcore.datos.estados import significa

    from services.sales.presupuestos import Presupuesto

    if presupuesto_id is not None:
        fila = db.get(Presupuesto, presupuesto_id)
        if fila is None or fila.tenant_id != tenant_id or fila.oportunidad_id != oportunidad_id:
            raise NoEncontrado(
                "Ese presupuesto no es de esta oportunidad", error_code="firma.presupuesto_ajeno"
            )
        return fila
    filas = (
        db.execute(
            select(Presupuesto)
            .where(
                Presupuesto.tenant_id == tenant_id,
                Presupuesto.oportunidad_id == oportunidad_id,
                Presupuesto.deleted_at.is_(None),
            )
            .order_by(Presupuesto.created_at.desc())
        )
        .scalars()
        .all()
    )
    for fila in filas:
        if not any(
            significa("presupuesto", fila.estado, muerto, db)
            for muerto in ("sustituido", "rechazado", "caducado")
        ):
            return fila
    return None


def enviar_a_firma(
    uow: UnidadDeTrabajo,
    oportunidad_id: UUID,
    *,
    principal_id: Any,
    firmantes: list[dict[str, Any]],
    presupuesto_id: UUID | None = None,
    contrato_id: UUID | None = None,
    asunto: str = "",
    mensaje: str = "",
    enviar: bool = True,
) -> dict[str, Any]:
    """Crea el sobre en `integration` con el origen ya puesto y, si se pide,
    lo manda. La oportunidad queda apuntando al sobre."""
    from crmcore.http.interno import invocar

    from services.sales import servicio as svc
    from services.sales.presupuestos import Contrato

    tenant_id = uow.tenant_id
    oportunidad = svc._oportunidad(uow.db, oportunidad_id)
    if not firmantes:
        raise ErrorValidacion(
            "Un sobre sin firmantes no lo firma nadie.", error_code="firma.sin_firmantes"
        )

    documento = ""
    titulo = oportunidad.nombre
    if contrato_id is not None:
        contrato = uow.db.get(Contrato, contrato_id)
        if contrato is None or contrato.tenant_id != tenant_id:
            raise NoEncontrado("Ese contrato no existe", error_code="firma.contrato_no_existe")
        documento = f"contrato:{contrato.id}"
        titulo = contrato.titulo or contrato.numero
    else:
        presupuesto = _presupuesto(uow.db, tenant_id, oportunidad.id, presupuesto_id)
        if presupuesto is None:
            raise ErrorValidacion(
                "Esta oportunidad no tiene un presupuesto vivo que firmar.",
                error_code="firma.sin_presupuesto",
            )
        documento = f"presupuesto:{presupuesto.id}"
        titulo = f"{presupuesto.numero} v{presupuesto.version}"

    cuerpo = {
        "documento_id": documento,
        "firmantes": firmantes,
        "objeto_origen": "oportunidad",
        "objeto_origen_id": str(oportunidad.id),
        "cuenta_id": str(oportunidad.cuenta_id) if oportunidad.cuenta_id else None,
        "asunto": asunto or titulo,
        "mensaje": mensaje,
        "contexto": {"importe": str(oportunidad.importe), "moneda": oportunidad.moneda},
    }
    espera = _espera(uow.db)
    # Sin respuesta de integración, `NoDisponible` sube tal cual: es un 503 y
    # no un «no hay sobre».
    creado = invocar(
        metodo="POST",
        ruta="/api/v1/firma/sobres",
        cuerpo=cuerpo,
        tenant_id=tenant_id,
        principal_id=principal_id,
        permisos=["firma:write"],
        timeout_s=espera,
    )
    if not creado.get("ok"):
        _reenviar_error(creado)
    sobre = creado.get("datos") or {}
    sobre_id = str(sobre.get("id") or "")
    estado = str(sobre.get("estado") or "borrador")
    enviado_error = None
    if enviar and sobre_id:
        mandado = invocar(
            metodo="POST",
            ruta=f"/api/v1/firma/sobres/{sobre_id}/enviar",
            tenant_id=tenant_id,
            principal_id=principal_id,
            permisos=["firma:write"],
            timeout_s=espera,
        )
        if mandado.get("ok"):
            estado = str((mandado.get("datos") or {}).get("estado") or "enviado")
        else:
            # El sobre existe y se queda en borrador: no se da por mandado lo
            # que el proveedor no aceptó. Se dice por qué.
            enviado_error = _mensaje(mandado)
    aplicar_estado(
        uow,
        oportunidad,
        estado=estado,
        sobre_id=sobre_id,
        referencia=str(sobre.get("referencia") or ""),
    )
    return {
        "sobre_id": sobre_id,
        "referencia": sobre.get("referencia"),
        "estado": estado,
        "documento_id": documento,
        "error_al_enviar": enviado_error,
    }


def _mensaje(respuesta: dict[str, Any]) -> str:
    datos = respuesta.get("datos") or {}
    if isinstance(datos, dict):
        return str(datos.get("detail") or datos.get("mensaje") or datos.get("title") or datos)[:500]
    return str(datos)[:500]


def _reenviar_error(respuesta: dict[str, Any]) -> None:
    """El error de integración, con su código, para que la ficha diga lo mismo
    que diría la pantalla de firma."""
    datos = respuesta.get("datos") or {}
    codigo = str(datos.get("error_code") or "firma.no_creado") if isinstance(datos, dict) else ""
    if int(respuesta.get("estado") or 0) == 409:
        raise Conflicto(_mensaje(respuesta), error_code=codigo or "firma.no_creado")
    raise ErrorValidacion(_mensaje(respuesta), error_code=codigo or "firma.no_creado")


def estado_de_la_firma(
    uow: UnidadDeTrabajo, oportunidad_id: UUID, *, principal_id: Any
) -> dict[str, Any]:
    """Lo que dice el sobre AHORA, y lo que eso hace en la oportunidad.

    El evento del motor de firma es el camino normal; esto es el otro: sin bus
    —o con el evento perdido— la ficha pregunta al sobre al abrirse y aplica lo
    mismo que habría aplicado el consumidor. Si integración no contesta se
    enseña lo último guardado y se dice.
    """
    from crmcore.http.interno import invocar

    from services.sales import servicio as svc

    oportunidad = svc._oportunidad(uow.db, oportunidad_id)
    campos = dict(oportunidad.campos or {})
    sobre_id = str(campos.get("firma_sobre_id") or "")
    salida: dict[str, Any] = {
        "sobre_id": sobre_id or None,
        "estado": campos.get("firma_estado"),
        "referencia": campos.get("firma_referencia"),
        "motivo": campos.get("firma_motivo"),
        "etapa_error": campos.get("firma_etapa_error"),
        "etapa_tras_firma": None,
        "consultado": False,
    }
    destino = _etapa_tras_firma(uow.db, oportunidad)
    salida["etapa_tras_firma"] = destino.nombre if destino is not None else None
    if not sobre_id:
        return salida
    try:
        r = invocar(
            metodo="GET",
            ruta=f"/api/v1/firma/sobres/{sobre_id}/evidencia",
            tenant_id=uow.tenant_id,
            principal_id=principal_id,
            permisos=["firma:read"],
            timeout_s=_espera(uow.db),
        )
    except NoDisponible:
        return salida
    datos = r.get("datos") if r.get("ok") else None
    if not isinstance(datos, dict) or not datos.get("estado"):
        return salida
    salida["consultado"] = True
    estado = str(datos["estado"])
    if estado != campos.get("firma_estado") or (
        estado == "completado" and campos.get("firma_etapa_aplicada") != sobre_id
    ):
        aplicado = aplicar_estado(uow, oportunidad, estado=estado, sobre_id=sobre_id)
        salida["etapa_movida_a"] = aplicado["etapa_movida_a"]
    campos = dict(oportunidad.campos or {})
    salida["estado"] = campos.get("firma_estado")
    salida["etapa_error"] = campos.get("firma_etapa_error")
    return salida
