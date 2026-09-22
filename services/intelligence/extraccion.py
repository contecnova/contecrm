"""Extracción estructurada desde correos, PDFs y transcripciones
(CRM-05.02.02.05).

Sacar campos de un texto es lo que más tiempo ahorra de todo lo que hace la IA en
un CRM —nadie quiere teclear el NIF de un correo— y lo que más daño hace si se
aplica solo: un importe mal leído entra en una oportunidad, sale en el forecast y
llega a una reunión.

Por eso:

**Se propone, no se escribe.** Cada campo extraído es una propuesta con su
confianza y su cita: el trozo de texto de donde salió. Quien lo acepte estará
mirando las dos cosas.

**Lo que ya tiene valor no se pisa.** Si el campo ya está relleno y lo extraído no
coincide, se marca como **conflicto** y decide una persona: el dato que ya estaba
lo puso alguien, y una máquina no tiene autoridad para corregirlo en silencio.

**Sin cita no hay propuesta.** Un valor sin el fragmento del que salió no se puede
comprobar, y comprobarlo es más rápido que buscarlo a mano — que es todo el ahorro
que esto promete.

**El esquema manda.** Se extrae hacia los campos que el metamodelo declara, con su
tipo: si el destino es una fecha y el modelo devuelve «el martes», la propuesta se
marca como no convertible en vez de guardar basura con buena cara.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from uuid import UUID

from crmcore.db.base import Base
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.intelligence import enrutador, guardias, uso

logger = get_logger(__name__)

# Tipos a los que se sabe convertir. Cerrada: un tipo que no se sabe convertir
# guardaría el texto tal cual, y un «el martes» dentro de una columna de fecha es
# basura con buena cara.
TIPOS = ("texto", "numero", "fecha", "booleano", "lista")

# Confianza mínima para proponer. Por debajo, la propuesta cuesta más revisarla
# que escribir el dato a mano, que es cuando la gente deja de usar la función.
CONFIANZA_MINIMA = 0.5

_extractor: Callable[..., dict[str, Any]] | None = None


def registrar_extractor(fn: Callable[..., dict[str, Any]]) -> None:
    global _extractor
    _extractor = fn


class CampoExtraido(Base):
    """Un valor propuesto para un campo del CRM, con su prueba."""

    __tablename__ = "campos_extraidos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    campo: Mapped[str] = mapped_column(String(80), nullable=False)
    valor: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="texto")
    confianza: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    # El trozo de texto del que salió. Sin esto no se puede comprobar, y
    # comprobarlo es más rápido que buscarlo a mano — que es el ahorro que esto
    # promete.
    cita: Mapped[str] = mapped_column(Text, nullable=False, default="")
    origen: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    origen_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # pendiente | aceptado | rechazado | conflicto
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    valor_actual: Mapped[str | None] = mapped_column(Text, nullable=True)
    convertible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    llamada_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    decidido_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_campos_extraidos", "tenant_id", "estado", "created_at"),
        Index("ix_campos_extraidos_objeto", "tenant_id", "objeto", "objeto_id"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def convertir(valor: Any, tipo: str) -> tuple[Any, bool]:
    """Convierte al tipo del campo destino. Devuelve (valor, se_pudo).

    No se fuerza nada: si el destino es una fecha y llega «el martes», se dice que
    no se pudo. Guardar el texto tal cual daría una columna de fechas con frases
    dentro, y eso rompe el primer informe que lo agrupe.
    """
    crudo = str(valor).strip() if valor is not None else ""
    if not crudo:
        return None, False
    if tipo == "texto":
        return crudo, True
    if tipo == "numero":
        try:
            return Decimal(crudo.replace(".", "").replace(",", ".")), True
        except (InvalidOperation, ValueError):
            return None, False
    if tipo == "fecha":
        for patron in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(crudo, patron).date(), True
            except ValueError:
                continue
        return None, False
    if tipo == "booleano":
        bajo = crudo.lower()
        if bajo in ("sí", "si", "true", "1", "verdadero"):
            return True, True
        if bajo in ("no", "false", "0", "falso"):
            return False, True
        return None, False
    if tipo == "lista":
        return [t.strip() for t in re.split(r"[;,]", crudo) if t.strip()], True
    return None, False


def extraer(
    uow: UnidadDeTrabajo,
    *,
    texto: str,
    campos: list[dict[str, Any]],
    objeto: str,
    objeto_id: UUID | None = None,
    valores_actuales: dict[str, Any] | None = None,
    origen: str = "",
    origen_id: str = "",
    principal: Any = None,
) -> dict[str, Any]:
    """Saca campos de un texto y los deja **propuestos** (CRM-05.02.02.05).

    `campos` declara qué se busca y de qué tipo: `[{clave, tipo, descripcion}]`.
    Se pide por esquema y no en abierto porque «saca lo que veas» devuelve cosas
    distintas cada vez y nadie puede construir encima.

    Lo que ya tiene valor **no se pisa**: si lo extraído no coincide con lo que
    había, la propuesta queda en **conflicto** y decide una persona. El dato que ya
    estaba lo puso alguien, y una máquina no tiene autoridad para corregirlo en
    silencio.
    """
    if not texto.strip():
        raise ErrorValidacion("No hay texto del que extraer.", error_code="extraccion.texto_vacio")
    if not campos:
        raise ErrorValidacion(
            "Hay que decir qué campos se buscan: «saca lo que veas» devuelve cosas "
            "distintas cada vez y nadie puede construir encima.",
            error_code="extraccion.sin_campos",
        )
    malos = sorted({str(c.get("tipo") or "texto") for c in campos} - set(TIPOS))
    if malos:
        raise ErrorValidacion(
            f"Tipos no soportados: {malos}.",
            error_code="extraccion.tipo_no_valido",
            detalle={"validos": list(TIPOS)},
        )

    filtrado = guardias.filtrar_contexto(
        uow.db,
        uow.tenant_id,
        fragmentos=[{"texto": texto, "permiso": "account:read", "fuente": origen or "texto"}],
        principal=principal,
    )
    if not filtrado["fragmentos"]:
        guardias.anotar_bloqueo(
            uow,
            motivo="permiso",
            tarea="extraccion",
            usuario_id=getattr(principal, "id", None),
        )
        return {"extraidos": [], "porque": "No puedes leer ese texto.", "bloqueado": True}

    elegido = enrutador.exigir_disponible(uow.db, uow.tenant_id, uso="extraccion")
    if _extractor is None:
        raise Conflicto(
            "No hay extractor conectado en este despliegue.",
            error_code="extraccion.sin_extractor",
        )

    inicio = _ahora()
    respuesta = _extractor(
        proveedor=elegido["elegido"],
        modelo=elegido.get("modelo", ""),
        texto=str(filtrado["fragmentos"][0]["texto"]),
        campos=campos,
        opt_out=bool(elegido.get("opt_out")),
    )

    llamada = uso.anotar(
        uow,
        tarea="extraccion",
        proveedor=str(elegido.get("elegido") or ""),
        modelo=str(respuesta.get("modelo") or elegido.get("modelo") or ""),
        region=str(elegido.get("region") or ""),
        usuario_id=getattr(principal, "id", None),
        objeto=objeto,
        objeto_id=objeto_id,
        prompt=texto[:2000],
        fuentes=[{"fuente": origen, "id": origen_id}] if origen else [],
        tokens_entrada=int(respuesta.get("tokens_entrada") or 0),
        tokens_salida=int(respuesta.get("tokens_salida") or 0),
        coste=enrutador.coste_estimado(
            uow.db,
            proveedor=str(elegido.get("elegido") or ""),
            tokens_entrada=int(respuesta.get("tokens_entrada") or 0),
            tokens_salida=int(respuesta.get("tokens_salida") or 0),
        ),
        duracion_ms=int((_ahora() - inicio).total_seconds() * 1000),
        opt_out=bool(elegido.get("opt_out")),
    )
    enrutador.anotar_gasto(
        uow,
        proveedor=str(elegido.get("elegido") or ""),
        tokens_entrada=llamada.tokens_entrada,
        tokens_salida=llamada.tokens_salida,
        coste=llamada.coste,
    )

    tipos = {str(c.get("clave")): str(c.get("tipo") or "texto") for c in campos}
    actuales = dict(valores_actuales or {})
    propuestos: list[dict[str, Any]] = []
    descartados: list[dict[str, Any]] = []

    for cruda in respuesta.get("campos") or []:
        clave = str(cruda.get("clave") or "")
        if clave not in tipos:
            descartados.append({"campo": clave, "porque": "no estaba entre los campos pedidos"})
            continue
        cita = str(cruda.get("cita") or "").strip()
        if not cita:
            # Sin cita no se puede comprobar, y comprobar es más rápido que
            # buscarlo a mano — que es todo el ahorro que esto promete.
            descartados.append(
                {"campo": clave, "porque": "sin cita del texto: no se podría comprobar"}
            )
            continue
        if cita not in texto:
            descartados.append(
                {
                    "campo": clave,
                    "porque": "la cita no aparece en el texto: la referencia es inventada",
                }
            )
            continue
        try:
            confianza = Decimal(str(cruda.get("confianza", 0)))
        except (InvalidOperation, ValueError):
            confianza = Decimal(0)
        if confianza < Decimal(str(CONFIANZA_MINIMA)):
            descartados.append(
                {
                    "campo": clave,
                    "porque": (
                        f"confianza {confianza}: revisarlo costaría más que escribirlo " "a mano"
                    ),
                }
            )
            continue

        tipo = tipos[clave]
        convertido, se_pudo = convertir(cruda.get("valor"), tipo)
        actual = actuales.get(clave)
        estado = "pendiente"
        if actual not in (None, "") and str(actual) != str(convertido):
            # No se pisa: el dato que ya estaba lo puso alguien.
            estado = "conflicto"

        fila = CampoExtraido(
            tenant_id=uow.tenant_id,
            objeto=objeto,
            objeto_id=objeto_id,
            campo=clave,
            valor=str(cruda.get("valor") or ""),
            tipo=tipo,
            confianza=confianza,
            cita=cita,
            origen=origen,
            origen_id=origen_id,
            estado=estado,
            valor_actual=str(actual) if actual not in (None, "") else None,
            convertible=se_pudo,
            llamada_id=llamada.id,
        )
        uow.db.add(fila)
        uow.db.flush()
        propuestos.append(
            {
                "id": str(fila.id),
                "campo": clave,
                "valor": fila.valor,
                "tipo": tipo,
                "confianza": float(confianza),
                "cita": cita,
                "estado": estado,
                "valor_actual": fila.valor_actual,
                # Un «el martes» en un campo de fecha se marca en vez de guardarse
                # con buena cara.
                "convertible": se_pudo,
            }
        )

    return {
        "extraidos": propuestos,
        "descartados": descartados,
        "llamada_id": str(llamada.id),
        "conflictos": len([p for p in propuestos if p["estado"] == "conflicto"]),
        "no_convertibles": len([p for p in propuestos if not p["convertible"]]),
        # Nada de esto está escrito en el CRM todavía, y se dice.
        "aplicado": False,
        "aviso": "Son propuestas: no se ha modificado ningún campo del CRM.",
    }


def decidir(
    uow: UnidadDeTrabajo,
    campo_id: UUID,
    *,
    aceptar: bool,
    por: UUID | None = None,
) -> dict[str, Any]:
    """Acepta o rechaza una propuesta. Aceptar **pide** el cambio, no lo escribe.

    El campo lo escribe el servicio dueño del objeto, por comando, con sus reglas
    de validación: escribir desde aquí saltaría el metamodelo y las reglas de
    negocio de ese servicio, que aplican a todo el mundo menos —de repente— a la
    IA.
    """
    fila = uow.db.get(CampoExtraido, campo_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Esa propuesta no existe", error_code="extraccion.no_encontrada")
    if fila.estado in ("aceptado", "rechazado"):
        raise Conflicto(
            "Esa propuesta ya está decidida",
            error_code="extraccion.ya_decidida",
            detalle={"estado": fila.estado},
        )
    if aceptar and not fila.convertible:
        raise ErrorValidacion(
            f"El valor «{fila.valor}» no se puede convertir a {fila.tipo}: aceptarlo "
            "guardaría basura en un campo con tipo.",
            error_code="extraccion.no_convertible",
        )

    fila.estado = "aceptado" if aceptar else "rechazado"
    fila.decidido_por = por
    uow.db.flush()

    pedido = False
    if aceptar and fila.objeto_id:
        from crmcore.bus.comandos import Comando
        from crmcore.bus.comandos import emitir as emitir_comando

        convertido, _ = convertir(fila.valor, fila.tipo)
        emitir_comando(
            uow,
            Comando(
                accion="actualizar",
                objeto=fila.objeto,
                tenant_id=uow.tenant_id,
                registro_id=fila.objeto_id,
                datos={"campos": {fila.campo: convertido}},
                origen="ia_extraccion",
                origen_id=str(fila.id),
            ),
        )
        pedido = True

    return {
        "id": str(fila.id),
        "estado": fila.estado,
        # «Pedido» y no «escrito»: lo aplica el servicio dueño con sus reglas, y
        # puede rechazarlo.
        "cambio_pedido": pedido,
        "porque": (
            "Se ha pedido el cambio al servicio dueño del objeto, que aplica sus " "reglas."
            if pedido
            else ""
        ),
    }


def pendientes(
    db: Session, tenant_id: UUID, *, objeto: str = "", limite: int = 100
) -> dict[str, Any]:
    """Lo extraído que espera decisión, con los conflictos delante.

    Los conflictos primero porque son los únicos donde equivocarse borra un dato
    que ya existía: el resto, como mucho, deja un campo vacío.
    """
    consulta = select(CampoExtraido).where(
        CampoExtraido.tenant_id == tenant_id,
        CampoExtraido.estado.in_(("pendiente", "conflicto")),
    )
    if objeto:
        consulta = consulta.where(CampoExtraido.objeto == objeto)
    filas = (
        db.execute(consulta.order_by(CampoExtraido.created_at.desc()).limit(limite)).scalars().all()
    )
    ordenadas = sorted(filas, key=lambda f: f.estado != "conflicto")
    return {
        "campos": [
            {
                "id": str(f.id),
                "objeto": f.objeto,
                "objeto_id": str(f.objeto_id) if f.objeto_id else None,
                "campo": f.campo,
                "valor": f.valor,
                "valor_actual": f.valor_actual,
                "confianza": float(f.confianza),
                "cita": f.cita,
                "estado": f.estado,
                "convertible": f.convertible,
            }
            for f in ordenadas
        ],
        "conflictos": len([f for f in filas if f.estado == "conflicto"]),
        "no_convertibles": len([f for f in filas if not f.convertible]),
        "cuantos": len(filas),
    }
