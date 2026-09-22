"""Redacción, resumen y traducción con plantillas versionadas
(CRM-05.02.02.01, CRM-05.02.02.02, CRM-05.02.02.06).

Lo que distingue una funcionalidad de IA que aguanta en producción de una demo es
aburrido: **la plantilla del prompt es un objeto versionado, no una cadena en el
código**. Cuando dentro de tres meses los resúmenes empiecen a salir raros, la
pregunta será «¿qué cambió?», y sin versión no hay respuesta.

Cuatro decisiones más, todas por lo mismo — que esto se usa con clientes delante:

**Nada se escribe solo en el CRM.** Lo generado se **propone**: un borrador que
alguien lee, corrige y manda. Un correo enviado automáticamente con un dato
inventado no se puede retirar, y el modelo inventa; poco, pero inventa.

**El idioma se decide, no se adivina.** Contestar en castellano a un cliente
francés porque la ficha estaba en castellano es el error más frecuente y el más
caro de los baratos.

**Lo que no se puede generar se dice.** Sin contexto suficiente —una cuenta sin
actividad, un caso sin mensajes— el modelo redacta igual, y lo que sale es
plausible y vacío. Aquí se devuelve que no había con qué, que es la verdad.

**Se guarda de qué se generó.** Cada propuesta lleva sus fuentes y su llamada
registrada (`CRM-05.02.02.08`): sin eso, «¿de dónde ha salido esto?» no tiene
respuesta.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.intelligence import enrutador, guardias, uso

logger = get_logger(__name__)

# Qué se puede pedir. Cada una tiene su uso de modelo y su forma de fallar: el
# que resume no es el que traduce, y elegir «el mejor» para todo sale caro.
TAREAS = ("redaccion", "reescritura", "resumen", "traduccion")

# Marcadores `{{clave}}` de la plantilla.
RE_MARCADOR = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")

# Mínimo de contexto para que un resumen signifique algo. Por debajo, el modelo
# redacta igual y lo que sale es plausible y vacío — que es peor que no responder.
MINIMO_CONTEXTO = 120

# El puerto hacia el modelo. Se inyecta desde fuera —lo registra el arranque del
# servicio— para que este módulo no sepa de HTTP ni de ningún proveedor, y para
# que en pruebas se pueda comprobar lo que importa: qué se manda y qué se hace
# con lo que vuelve.
_generador: Callable[..., dict[str, Any]] | None = None


def registrar_generador(fn: Callable[..., dict[str, Any]]) -> None:
    """Declara quién habla de verdad con el modelo."""
    global _generador
    _generador = fn


def generador_registrado() -> bool:
    return _generador is not None


class PlantillaPrompt(Base, TimestampMixin):
    """Un prompt con versión (CRM-05.02.02.01).

    Versionada porque el día que los resúmenes salgan raros, la primera pregunta
    es qué cambió — y una cadena en el código no lo dice.
    """

    __tablename__ = "plantillas_ia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tarea: Mapped[str] = mapped_column(String(30), nullable=False, default="redaccion")
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Instrucciones fijas del sistema y cuerpo con marcadores. Separadas porque
    # lo primero es política de la empresa —tono, qué no decir— y lo segundo es
    # la petición concreta.
    sistema: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Qué marcadores exige. Se calculan al guardar: una plantilla que espera
    # `{{cliente}}` y recibe `{{cuenta}}` genera un texto con un hueco que nadie
    # ve hasta que se manda.
    marcadores: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    idioma_defecto: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    vigente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    motivo_version: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", "version", name="uq_plantilla_ia"),
        Index("ix_plantillas_ia", "tenant_id", "vigente", "tarea"),
    )


class Propuesta(Base, TimestampMixin):
    """Lo generado, **antes** de que nadie lo use.

    Que sea una tabla y no un valor en el registro es la decisión importante: lo
    generado no es un dato del CRM hasta que una persona lo acepta.
    """

    __tablename__ = "propuestas_ia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tarea: Mapped[str] = mapped_column(String(30), nullable=False)
    objeto: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    objeto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    texto: Mapped[str] = mapped_column(Text, nullable=False, default="")
    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    plantilla: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    version_plantilla: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llamada_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    fuentes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # pendiente | aceptada | descartada | editada
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    # Lo que quedó después de que una persona lo tocara. Guardarlo es lo que
    # permite saber si el modelo acierta o si siempre hay que reescribirlo.
    texto_final: Mapped[str | None] = mapped_column(Text, nullable=True)
    decidida_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    decidida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_propuestas_ia", "tenant_id", "estado", "created_at"),
        Index("ix_propuestas_objeto", "tenant_id", "objeto", "objeto_id"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _vigente(db: Session, tenant_id: UUID, clave: str) -> PlantillaPrompt | None:
    return (
        db.execute(
            select(PlantillaPrompt)
            .where(
                PlantillaPrompt.tenant_id == tenant_id,
                PlantillaPrompt.clave == clave,
                PlantillaPrompt.vigente.is_(True),
            )
            .order_by(PlantillaPrompt.version.desc())
        )
        .scalars()
        .first()
    )


def guardar_plantilla(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    cuerpo: str,
    tarea: str = "redaccion",
    sistema: str = "",
    nombre: str = "",
    idioma_defecto: str = "",
    motivo_version: str = "",
) -> tuple[PlantillaPrompt, list[str]]:
    """Guarda una plantilla. Cambiarla **crea versión nueva**."""
    if tarea not in TAREAS:
        raise ErrorValidacion(
            f"Tarea «{tarea}» no reconocida.",
            error_code="generacion.tarea_no_valida",
            detalle={"validas": list(TAREAS)},
        )
    if not cuerpo.strip():
        raise ErrorValidacion(
            "Una plantilla sin cuerpo no pide nada.", error_code="generacion.cuerpo_vacio"
        )
    marcadores = sorted(set(RE_MARCADOR.findall(cuerpo)))
    avisos: list[str] = []
    if not sistema.strip():
        avisos.append(
            "Sin instrucciones de sistema: el tono y lo que no se puede decir "
            "quedan a lo que el modelo crea, y eso cambia con cada versión del modelo."
        )
    if not marcadores:
        avisos.append(
            "La plantilla no tiene marcadores: va a generar lo mismo para todos los " "clientes."
        )

    anterior = _vigente(uow.db, uow.tenant_id, clave)
    if anterior is not None and not motivo_version.strip():
        raise ErrorValidacion(
            "Cambiar una plantilla exige decir qué cambia: el día que los textos "
            "salgan raros, esto es lo único que explicará por qué.",
            error_code="generacion.motivo_obligatorio",
        )

    fila = PlantillaPrompt(
        tenant_id=uow.tenant_id,
        clave=clave.strip(),
        version=(anterior.version + 1) if anterior else 1,
        tarea=tarea,
        nombre=nombre.strip() or clave.strip(),
        sistema=sistema,
        cuerpo=cuerpo,
        marcadores=marcadores,
        idioma_defecto=idioma_defecto,
        motivo_version=motivo_version.strip(),
    )
    if anterior is not None:
        anterior.vigente = False
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def _render(plantilla: PlantillaPrompt, datos: dict[str, Any]) -> tuple[str, list[str]]:
    faltan = [m for m in (plantilla.marcadores or []) if datos.get(m) in (None, "")]
    texto = plantilla.cuerpo
    for clave, valor in datos.items():
        texto = texto.replace("{{" + clave + "}}", str(valor))
        texto = texto.replace("{{ " + clave + " }}", str(valor))
    return texto, faltan


def generar(
    uow: UnidadDeTrabajo,
    *,
    plantilla: str,
    datos: dict[str, Any] | None = None,
    contexto: list[dict[str, Any]] | None = None,
    objeto: str = "",
    objeto_id: UUID | None = None,
    idioma: str = "",
    principal: Any = None,
) -> dict[str, Any]:
    """Genera un borrador y lo deja **propuesto**, nunca aplicado
    (CRM-05.02.02.01,
    CRM-05.02.02.02 y CRM-05.02.02.06).

    El orden es el mismo siempre y no es casual: **plantilla, guardarraíles,
    enrutador, llamada, registro**. Los guardarraíles van antes que el enrutador
    porque filtrar después de elegir proveedor ya habría decidido a dónde iban a
    salir los datos.

    Sin contexto suficiente **no se llama al modelo**: redactaría igual, y lo que
    sale es plausible y vacío. Cuesta dinero y engaña, que es la peor combinación.
    """
    ficha = _vigente(uow.db, uow.tenant_id, plantilla)
    if ficha is None:
        raise NoEncontrado(
            f"No hay plantilla «{plantilla}»", error_code="generacion.plantilla_no_encontrada"
        )

    cuerpo, faltan = _render(ficha, dict(datos or {}))
    if faltan:
        raise ErrorValidacion(
            f"Faltan datos que la plantilla espera: {', '.join(faltan)}. Generar con "
            "huecos produce un texto que alguien manda sin verlos.",
            error_code="generacion.faltan_marcadores",
            detalle={"faltan": faltan},
        )

    filtrado = guardias.filtrar_contexto(
        uow.db, uow.tenant_id, fragmentos=list(contexto or []), principal=principal
    )
    texto_contexto = "\n\n".join(str(f.get("texto") or "") for f in filtrado["fragmentos"])
    if ficha.tarea in ("resumen", "reescritura") and len(texto_contexto) < MINIMO_CONTEXTO:
        guardias.anotar_bloqueo(
            uow,
            motivo="sin_contexto",
            tarea=ficha.tarea,
            usuario_id=getattr(principal, "id", None),
            detalle={"caracteres": len(texto_contexto)},
        )
        return {
            "generado": False,
            "porque": (
                "No hay contexto suficiente para resumir: con esto el modelo "
                "redactaría algo plausible y vacío."
            ),
            "caracteres_contexto": len(texto_contexto),
            "quitados_por_permisos": filtrado["quitados"],
        }

    elegido = enrutador.exigir_disponible(uow.db, uow.tenant_id, uso=_uso_de(ficha.tarea))
    idioma_final = idioma or ficha.idioma_defecto
    if not idioma_final:
        # Adivinarlo es cómo se contesta en castellano a un cliente francés.
        return {
            "generado": False,
            "porque": (
                "No se ha declarado el idioma de la respuesta ni la plantilla trae "
                "uno por defecto: adivinarlo es cómo se contesta en castellano a un "
                "cliente francés."
            ),
        }

    if _generador is None:
        raise Conflicto(
            "No hay ningún generador conectado: este despliegue no puede llamar a " "un modelo.",
            error_code="generacion.sin_generador",
        )

    inicio = _ahora()
    try:
        respuesta = _generador(
            proveedor=elegido["elegido"],
            modelo=elegido.get("modelo", ""),
            sistema=ficha.sistema,
            prompt=cuerpo,
            contexto=texto_contexto,
            idioma=idioma_final,
            opt_out=bool(elegido.get("opt_out")),
        )
    except Exception as error:  # el puerto decide qué excepciones lanza
        uso.anotar(
            uow,
            tarea=ficha.tarea,
            proveedor=str(elegido.get("elegido") or ""),
            modelo=str(elegido.get("modelo") or ""),
            region=str(elegido.get("region") or ""),
            usuario_id=getattr(principal, "id", None),
            objeto=objeto,
            objeto_id=objeto_id,
            plantilla=ficha.clave,
            version_plantilla=ficha.version,
            prompt=cuerpo,
            resultado="error",
            error=str(error)[:300],
            opt_out=bool(elegido.get("opt_out")),
            duracion_ms=int((_ahora() - inicio).total_seconds() * 1000),
        )
        raise

    tokens_entrada = int(respuesta.get("tokens_entrada") or 0)
    tokens_salida = int(respuesta.get("tokens_salida") or 0)
    llamada = uso.anotar(
        uow,
        tarea=ficha.tarea,
        proveedor=str(elegido.get("elegido") or ""),
        modelo=str(respuesta.get("modelo") or elegido.get("modelo") or ""),
        region=str(elegido.get("region") or ""),
        usuario_id=getattr(principal, "id", None),
        objeto=objeto,
        objeto_id=objeto_id,
        plantilla=ficha.clave,
        version_plantilla=ficha.version,
        prompt=cuerpo,
        fuentes=[
            {"fuente": str(f.get("fuente") or ""), "id": str(f.get("id") or "")}
            for f in filtrado["fragmentos"]
        ],
        tokens_entrada=tokens_entrada,
        tokens_salida=tokens_salida,
        coste=enrutador.coste_estimado(
            uow.db,
            proveedor=str(elegido.get("elegido") or ""),
            tokens_entrada=tokens_entrada,
            tokens_salida=tokens_salida,
        ),
        duracion_ms=int((_ahora() - inicio).total_seconds() * 1000),
        # `pendiente`: se ha generado, pero nadie ha dicho todavía si le sirve.
        # Marcarla aceptada aquí haría que la tasa de descarte no midiera nada.
        resultado="sin_respuesta" if not respuesta.get("texto") else "pendiente",
        opt_out=bool(elegido.get("opt_out")),
    )
    enrutador.anotar_gasto(
        uow,
        proveedor=str(elegido.get("elegido") or ""),
        tokens_entrada=tokens_entrada,
        tokens_salida=tokens_salida,
        coste=llamada.coste,
    )

    propuesta = Propuesta(
        tenant_id=uow.tenant_id,
        tarea=ficha.tarea,
        objeto=objeto,
        objeto_id=objeto_id,
        texto=str(respuesta.get("texto") or ""),
        idioma=idioma_final,
        plantilla=ficha.clave,
        version_plantilla=ficha.version,
        llamada_id=llamada.id,
        fuentes=llamada.fuentes,
    )
    uow.db.add(propuesta)
    uow.db.flush()

    return {
        "generado": True,
        "propuesta_id": str(propuesta.id),
        "texto": propuesta.texto,
        "idioma": idioma_final,
        "modelo": llamada.modelo,
        "region": llamada.region,
        "plantilla": f"{ficha.clave} v{ficha.version}",
        "fuentes": llamada.fuentes,
        "coste": str(llamada.coste),
        # Lo que se dejó fuera por permisos viaja con la respuesta: quien la lea
        # tiene que saber que está incompleta y por qué.
        "contexto_incompleto": not filtrado["completo"],
        "quitados_por_permisos": filtrado["quitados"],
        # Y lo más importante: esto **no** está aplicado en ninguna parte.
        "aplicado": False,
        "aviso": ("Es un borrador: no se ha escrito en el CRM ni se ha enviado a nadie."),
    }


def _uso_de(tarea: str) -> str:
    return {
        "redaccion": "redaccion",
        "reescritura": "redaccion",
        "resumen": "resumen",
        "traduccion": "traduccion",
    }.get(tarea, "redaccion")


def decidir(
    uow: UnidadDeTrabajo,
    propuesta_id: UUID,
    *,
    estado: str,
    texto_final: str = "",
    por: UUID | None = None,
) -> Propuesta:
    """Anota qué hizo la persona con el borrador.

    Es lo que convierte esto en medible: sin saber cuántas propuestas se tiran, se
    sabe lo que cuesta la IA y no lo que vale. Y el texto final, cuando se edita,
    dice si el modelo acierta o si siempre hay que reescribirlo entero.
    """
    if estado not in ("aceptada", "descartada", "editada"):
        raise ErrorValidacion(
            "Una propuesta se acepta, se descarta o se edita.",
            error_code="generacion.estado_no_valido",
        )
    fila = uow.db.get(Propuesta, propuesta_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Esa propuesta no existe", error_code="generacion.no_encontrada")
    fila.estado = estado
    fila.decidida_por = por
    fila.decidida_at = _ahora()
    if estado == "editada":
        if not texto_final.strip():
            raise ErrorValidacion(
                "Marcar como editada exige el texto que quedó: sin él no se puede "
                "saber cuánto había que corregir.",
                error_code="generacion.texto_final_obligatorio",
            )
        fila.texto_final = texto_final
    if estado == "descartada":
        # Lo descartado no se conserva: es un texto sobre un cliente que nadie ha
        # validado, y esos textos acaban leyéndose como si fueran datos.
        fila.texto = ""
    uow.db.flush()
    if fila.llamada_id:
        uso.marcar_resultado(
            uow,
            fila.llamada_id,
            resultado="descartada" if estado == "descartada" else "aceptada",
        )
    return fila


def calidad(db: Session, tenant_id: UUID, *, dias: int = 30) -> dict[str, Any]:
    """Cuánto de lo generado se usa tal cual, cuánto se corrige y cuánto se tira.

    Las tres juntas: una tarea con el 90 % de aceptación y otra con el 20 % no
    merecen la misma inversión, y con una media global las dos parecen iguales.
    """
    from datetime import timedelta

    desde = _ahora() - timedelta(days=dias)
    filas = (
        db.execute(
            select(Propuesta).where(Propuesta.tenant_id == tenant_id, Propuesta.created_at >= desde)
        )
        .scalars()
        .all()
    )
    por_tarea: dict[str, dict[str, int]] = {}
    for fila in filas:
        entrada = por_tarea.setdefault(
            fila.tarea,
            {"total": 0, "aceptadas": 0, "editadas": 0, "descartadas": 0, "pendientes": 0},
        )
        entrada["total"] += 1
        entrada[
            {
                "aceptada": "aceptadas",
                "editada": "editadas",
                "descartada": "descartadas",
                "pendiente": "pendientes",
            }[fila.estado]
        ] += 1
    juzgadas = len([f for f in filas if f.estado != "pendiente"])
    return {
        "dias": dias,
        "propuestas": len(filas),
        "por_tarea": por_tarea,
        "sin_juzgar": len(filas) - juzgadas,
        "medible": bool(juzgadas),
        "aviso": (
            ""
            if juzgadas
            else "Nadie ha marcado qué hizo con los borradores: no se puede saber si " "esto sirve."
        ),
    }
