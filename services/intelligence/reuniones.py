"""Transcribir una llamada o una reunión, resumirla y proponer sus compromisos
(CRM-01.02.01.05, CRM-01.02.01.06).

**Lo que había, medido el 09-11-2026.** `POST /transcripciones` recibía el texto
ya transcrito, no resumía nada y no guardaba nada: devolvía lo mismo que se le
mandaba con una advertencia. Los compromisos se «proponían» a partir de una
lista que tecleaba quien llamaba. Era la forma de una transcripción sin
ninguna de sus partes.

Ahora, de punta a punta:

1. **El audio**, subido o por enlace. El subido se guarda como adjunto del
   registro —una actividad, una cuenta— en el servicio dueño, por su API y con
   la identidad de quien lo sube: es un documento más del registro.
2. **La transcripción**, con el proveedor que el tenant tenga configurado. Es
   un **perfil sobre el conector de la casa** (`integration`): URL,
   autenticación y forma de la petición y de la respuesta son configuración.
   Aquí hay plantillas para dos proveedores típicos y ni una línea por casa.
3. **El resumen y los compromisos**, con el modelo de la casa por el puerto. Lo
   extraído pasa por las reglas de siempre (`transcripcion.proponer_extraidos`):
   sin dueño no se propone, y de una transcripción poco fiable no se extrae.
4. **Se guarda** ligado al registro, y cada compromiso queda como propuesta.
5. **Una persona confirma** cada compromiso —puede corregirlo— y entonces se
   crea la tarea en `party`, por su API, con su identidad, colgada del mismo
   registro que la reunión.

Los cruces con otros servicios pasan por `_http`, que las pruebas sustituyen
por un doble: lo que se prueba es qué se pide y qué se hace con lo que vuelve.
"""

from __future__ import annotations

import base64
import math
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import (
    Conflicto,
    CrmError,
    ErrorDependencia,
    ErrorValidacion,
    NoEncontrado,
    Prohibido,
)
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, Float, Index, Integer, String, Text, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from services.intelligence import transcripcion as trs

logger = get_logger(__name__)

ORIGENES = ("audio", "enlace", "texto")
ESTADOS = ("resumida", "sin_resumen")
# Lo que se convierte en tarea al confirmarlo. Un riesgo o una objeción se
# anotan, pero no son algo que alguien tenga que HACER en una fecha.
SE_HACEN_TAREA = ("compromiso", "proximo_paso")

# ── Plantillas de proveedor ───────────────────────────────────────────────
#
# Son DATOS: una conexión y una operación del conector de la casa. Instalar una
# las da de alta en `integration` por su API; cambiar de proveedor es instalar
# otra o editar la conexión, nunca tocar este módulo. La respuesta se mapea a
# `texto`, `confianza` y `segundos`; si el proveedor devuelve varios trozos, se
# juntan.
PLANTILLAS: dict[str, dict[str, Any]] = {
    "deepgram": {
        "nombre": "Deepgram (descarga el audio de un enlace)",
        "envio": "enlace",
        "conexion": {
            "url_base": "https://api.deepgram.com",
            "auth_tipo": "api_key",
            "auth_cabecera": "Authorization",
            "auth_prefijo": "Token ",
        },
        "operacion": {
            "metodo": "POST",
            "ruta": "/v1/listen",
            "query": {
                "language": "{{idioma}}",
                "punctuate": "true",
                "smart_format": "true",
                "diarize": "true",
            },
            "cuerpo": {"url": "{{audio_url}}"},
            "mapeo": {
                "texto": "results.channels.0.alternatives.0.transcript",
                "confianza": "results.channels.0.alternatives.0.confidence",
                "segundos": "metadata.duration",
            },
        },
    },
    "google_stt": {
        "nombre": "Google Speech-to-Text (el audio va en la petición)",
        "envio": "contenido",
        "conexion": {
            "url_base": "https://speech.googleapis.com",
            "auth_tipo": "api_key",
            "auth_cabecera": "x-goog-api-key",
            "auth_prefijo": "",
        },
        "operacion": {
            "metodo": "POST",
            "ruta": "/v1/speech:recognize",
            "cuerpo": {
                "config": {
                    "languageCode": "{{idioma_region}}",
                    "enableAutomaticPunctuation": True,
                },
                "audio": {"content": "{{audio_base64}}"},
            },
            "ruta_resultados": "results",
            "mapeo": {
                "texto": "alternatives.0.transcript",
                "confianza": "alternatives.0.confidence",
            },
        },
    },
}


class TranscripcionReunion(Base, TimestampMixin):
    """Una llamada o reunión transcrita, con su resumen y sus compromisos."""

    __tablename__ = "transcripciones_reunion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # De qué registro es: casi siempre una actividad (la llamada, la reunión).
    objeto: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    origen: Mapped[str] = mapped_column(String(20), nullable=False, info={"opciones": ORIGENES})
    adjunto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    enlace: Mapped[str] = mapped_column(Text, nullable=False, default="")
    base_para_grabar: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="es")
    texto: Mapped[str] = mapped_column(
        Text, nullable=False, default="", info={"anonimizar_en_copias": True}
    )
    # La confianza que dio el proveedor. Nula si no la da (o si el texto lo
    # pegó una persona): «sin medir» no es «fiable al 100 %».
    confianza: Mapped[float | None] = mapped_column(Float, nullable=True)
    fiable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    segundos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proveedor: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    resumen: Mapped[str] = mapped_column(
        Text, nullable=False, default="", info={"anonimizar_en_copias": True}
    )
    # Cada uno con su estado: propuesta, confirmada o descartada, y la tarea
    # creada. Se guarda lo que propuso el modelo y lo que quedó.
    compromisos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    descartados: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="resumida", info={"opciones": ESTADOS}
    )
    aviso: Mapped[str] = mapped_column(Text, nullable=False, default="")
    creada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_transcripciones_reunion_objeto", "tenant_id", "objeto", "objeto_id"),
    )


# ── Puertos sustituibles ──────────────────────────────────────────────────

_resumidor: Callable[..., dict[str, Any]] | None = None
_http: Callable[..., dict[str, Any]] | None = None


def registrar_resumidor(fn: Callable[..., dict[str, Any]] | None) -> None:
    global _resumidor
    _resumidor = fn


def _registrar_http(fn: Callable[..., dict[str, Any]] | None) -> None:
    """Sólo para las pruebas: sustituye las llamadas a otros servicios por un doble."""
    global _http
    _http = fn


def _identidad(principal: Any) -> dict[str, Any]:
    from services.intelligence.predictivo import identidad_de

    return identidad_de(principal)


def _llamar(
    principal: Any,
    *,
    metodo: str,
    ruta: str,
    cuerpo: dict[str, Any] | None = None,
    fichero: tuple[str, bytes, str] | None = None,
    formulario: dict[str, str] | None = None,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """Llama a otro servicio con la identidad de quien pide. `{estado, datos}`.

    JSON por `crmcore.http.interno.invocar`; un fichero, por multipart con las
    mismas cabeceras firmadas (el `invocar` sólo sabe de JSON).
    """
    if _http is not None:
        return _http(
            metodo=metodo, ruta=ruta, cuerpo=cuerpo, fichero=fichero, formulario=formulario
        )
    if fichero is None:
        from crmcore.http.interno import invocar

        return invocar(
            metodo=metodo, ruta=ruta, cuerpo=cuerpo, timeout_s=timeout_s, **_identidad(principal)
        )

    import httpx
    from crmcore.http.interno import cabeceras_de, direccion_de
    from crmcore.rutas_de_api import servicio_de

    servicio = servicio_de(ruta.lstrip("/")) or ""
    base = direccion_de(servicio)
    if not base:
        raise ErrorDependencia(
            f"No hay dirección para «{ruta}»", error_code="reunion.servicio_sin_direccion"
        )
    ident = _identidad(principal)
    cabeceras = cabeceras_de(
        tenant_id=ident["tenant_id"],
        principal_id=ident["principal_id"],
        permisos=ident["permisos"],
        roles=ident["roles"],
        tipo=ident["tipo"],
    )
    try:
        r = httpx.request(
            metodo,
            f"{base}{ruta}",
            files={"fichero": fichero},
            data=formulario or {},
            headers=cabeceras,
            timeout=timeout_s,
        )
    except httpx.HTTPError as exc:
        raise ErrorDependencia(
            f"El servicio «{servicio}» no responde", error_code="reunion.servicio_no_responde"
        ) from exc
    try:
        datos: Any = r.json()
    except ValueError:
        datos = {"texto": r.text[:500]}
    return {"estado": r.status_code, "datos": datos}


def _exigir_ok(r: dict[str, Any], que: str) -> Any:
    estado = int(r.get("estado") or 0)
    datos = r.get("datos")
    if 200 <= estado < 300:
        return datos
    detalle = datos if isinstance(datos, dict) else {}
    mensaje = str(detalle.get("detail") or detalle.get("mensaje") or f"{que}: HTTP {estado}")
    codigo = str(detalle.get("error_code") or "reunion.dependencia")
    if estado == 403:
        raise Prohibido(mensaje, error_code=codigo)
    if estado == 404:
        raise NoEncontrado(mensaje, error_code=codigo)
    if estado in (400, 422):
        raise ErrorValidacion(mensaje, error_code=codigo, detalle={"que": que})
    raise ErrorDependencia(mensaje, error_code=codigo, detalle={"que": que, "codigo_http": estado})


def _ajuste(db: Any, clave: str) -> Any:
    from crmcore.runtime import settings as rt

    from services.intelligence.ajustes import ajustes

    valor = rt.efectivo(clave, db) if db is not None else None
    return getattr(ajustes(), clave) if valor in (None, "") else valor


# ── El proveedor de transcripción ─────────────────────────────────────────


def proveedor(db: Any) -> dict[str, Any]:
    """Qué proveedor transcribe en este tenant, o por qué no hay ninguno."""
    conexion = str(_ajuste(db, "ia_transcripcion_conexion") or "")
    return {
        "configurado": bool(conexion),
        "conexion_id": conexion,
        "operacion": str(_ajuste(db, "ia_transcripcion_operacion") or ""),
        "envio": str(_ajuste(db, "ia_transcripcion_envio") or "enlace"),
        "max_mb": int(_ajuste(db, "ia_transcripcion_max_mb")),
        "plantillas": [
            {"clave": k, "nombre": v["nombre"], "envio": v["envio"]} for k, v in PLANTILLAS.items()
        ],
        "porque": (
            ""
            if conexion
            else "No hay proveedor de transcripción configurado. Se instala una "
            "plantilla (o se declara una conexión en Integraciones) y se le pone "
            "su credencial en la ficha de la conexión."
        ),
    }


def instalar_plantilla(
    uow: UnidadDeTrabajo, *, clave: str, principal: Any, url_base: str = ""
) -> dict[str, Any]:
    """Da de alta la conexión y su operación en `integration` y la deja en uso.

    `url_base` permite apuntar la misma forma de petición a otra dirección —un
    proveedor compatible, un proxy de la empresa o un doble para probar—.
    """
    from crmcore.runtime import settings as rt

    plantilla = PLANTILLAS.get(clave)
    if plantilla is None:
        raise ErrorValidacion(
            f"No hay plantilla «{clave}»",
            error_code="reunion.plantilla_desconocida",
            detalle={"hay": sorted(PLANTILLAS)},
        )
    config = dict(plantilla["conexion"])
    if url_base.strip():
        config["url_base"] = url_base.strip()
    conexion = _exigir_ok(
        _llamar(
            principal,
            metodo="POST",
            ruta="/api/v1/integraciones/conexiones",
            cuerpo={
                "nombre": f"Transcripción · {plantilla['nombre']}"[:200],
                "sistema": clave,
                "descripcion": "Transcripción de llamadas y reuniones (CRM-01.02.01.05)",
                "config": config,
            },
        ),
        "dar de alta la conexión",
    )
    conexion_id = str((conexion or {}).get("id") or "")
    operacion = str(_ajuste(uow.db, "ia_transcripcion_operacion") or "transcribir")
    _exigir_ok(
        _llamar(
            principal,
            metodo="POST",
            ruta=f"/api/v1/integraciones/conexiones/{conexion_id}/operaciones",
            cuerpo={
                "clave": operacion,
                "nombre": "Transcribir audio",
                "definicion": plantilla["operacion"],
            },
        ),
        "declarar la operación",
    )
    for k, v in (
        ("ia_transcripcion_conexion", conexion_id),
        ("ia_transcripcion_envio", plantilla["envio"]),
    ):
        rt.fijar(
            uow.db,
            k,
            v,
            ambito="tenant",
            ambito_id=str(uow.tenant_id),
            por=getattr(principal, "id", None),
            motivo=f"Plantilla de transcripción «{clave}»",
        )
    return {
        **proveedor(uow.db),
        "conexion_id": conexion_id,
        "configurado": True,
        "envio": plantilla["envio"],
        "falta": "Poner la credencial del proveedor en la ficha de la conexión.",
    }


def _region(idioma: str) -> str:
    """`es` → `es-ES`: hay proveedores que piden la variante regional."""
    if "-" in idioma:
        return idioma
    return f"{idioma}-{idioma.upper()}" if idioma else "es-ES"


def transcribir_audio(
    db: Any,
    *,
    principal: Any,
    idioma: str,
    audio: bytes | None = None,
    audio_url: str = "",
) -> dict[str, Any]:
    """Manda el audio al proveedor configurado y junta lo que devuelve."""
    conf = proveedor(db)
    if not conf["configurado"]:
        raise Conflicto(conf["porque"], error_code="reunion.sin_proveedor")
    parametros: dict[str, Any] = {"idioma": idioma, "idioma_region": _region(idioma)}
    if conf["envio"] == "contenido":
        if audio is None:
            raise ErrorValidacion(
                "Este proveedor recibe el audio dentro de la petición: hay que subir "
                "el fichero, un enlace no le sirve.",
                error_code="reunion.necesita_fichero",
            )
        parametros["audio_base64"] = base64.b64encode(audio).decode()
    else:
        if not audio_url:
            raise ErrorValidacion("Falta el enlace al audio.", error_code="reunion.sin_enlace")
        parametros["audio_url"] = audio_url
    datos = _exigir_ok(
        _llamar(
            principal,
            metodo="POST",
            ruta=(
                f"/api/v1/integraciones/conexiones/{conf['conexion_id']}"
                f"/operaciones/{conf['operacion']}/invocar"
            ),
            cuerpo={"parametros": parametros},
        ),
        "transcribir",
    )
    registros = [r for r in (datos or {}).get("registros") or [] if isinstance(r, dict)]
    trozos = [str(r.get("texto") or "").strip() for r in registros]
    texto = " ".join(t for t in trozos if t)
    confianzas = []
    for r in registros:
        try:
            if r.get("confianza") is not None:
                confianzas.append(float(r["confianza"]))
        except (TypeError, ValueError):
            pass
    segundos = None
    for r in registros:
        try:
            if r.get("segundos") is not None:
                segundos = int(math.ceil(float(r["segundos"])))
        except (TypeError, ValueError):
            pass
    if not texto:
        raise ErrorDependencia(
            "El proveedor no ha devuelto texto. Puede ser un audio sin voz, un "
            "formato que no admite o un mapeo de la respuesta que no casa.",
            error_code="reunion.transcripcion_vacia",
            detalle={"registros": len(registros)},
        )
    return {
        "texto": texto,
        "confianza": round(sum(confianzas) / len(confianzas), 3) if confianzas else None,
        "segundos": segundos,
        "proveedor": f"{conf['conexion_id']}/{conf['operacion']}",
    }


def _subir_audio(
    principal: Any, *, objeto: str, objeto_id: UUID, nombre: str, datos: bytes, mime: str
) -> str:
    """Guarda el audio como adjunto del registro, en el servicio dueño."""
    salida = _exigir_ok(
        _llamar(
            principal,
            metodo="POST",
            ruta=f"/api/v1/adjuntos/{objeto}",
            fichero=(nombre or "grabacion", datos, mime or "application/octet-stream"),
            formulario={
                "objeto_id": str(objeto_id),
                "descripcion": "Grabación transcrita (CRM-01.02.01.05)",
            },
        ),
        "guardar el audio",
    )
    return str((salida or {}).get("id") or "")


def _enlace_firmado(principal: Any, *, objeto: str, adjunto_id: str) -> str:
    """Un enlace que caduca pronto, para que el proveedor descargue el audio."""
    from crmcore.config import get_settings

    salida = _exigir_ok(
        _llamar(principal, metodo="POST", ruta=f"/api/v1/adjuntos/{objeto}/{adjunto_id}/enlace"),
        "firmar el enlace del audio",
    )
    token = str((salida or {}).get("token") or "")
    base = str(get_settings().public_base_url or "").rstrip("/")
    return f"{base}/api/v1/adjuntos/{objeto}/enlace/{token}"


# ── Resumen y compromisos ─────────────────────────────────────────────────


def _resumir(
    uow: UnidadDeTrabajo, *, texto: str, idioma: str, principal: Any, objeto_id: UUID
) -> dict[str, Any]:
    """El resumen y lo extraído, con el modelo de la casa."""
    from services.intelligence import enrutador, uso

    if _resumidor is None:
        raise ErrorDependencia(
            "No hay puerto de IA conectado: mejor sin resumen que con uno inventado.",
            error_code="reunion.sin_puerto",
        )
    elegido = enrutador.exigir_disponible(uow.db, uow.tenant_id, uso="resumen")
    tope = int(_ajuste(uow.db, "ia_transcripcion_caracteres_modelo"))
    recortada = len(texto) > tope
    inicio = datetime.now(timezone.utc)
    try:
        salida = _resumidor(
            proveedor=elegido["elegido"],
            modelo=elegido.get("modelo", ""),
            texto=texto[:tope],
            idioma=idioma,
            tipos=list(trs.EXTRAIBLES),
            opt_out=bool(elegido.get("opt_out")),
        )
    except CrmError as exc:
        uso.anotar(
            uow,
            tarea="resumen_reunion",
            proveedor=str(elegido.get("elegido") or ""),
            modelo=str(elegido.get("modelo") or ""),
            objeto="transcripcion",
            objeto_id=objeto_id,
            resultado="error",
            error=str(exc)[:200],
            opt_out=bool(elegido.get("opt_out")),
        )
        raise
    uso.anotar(
        uow,
        tarea="resumen_reunion",
        proveedor=str(elegido.get("elegido") or ""),
        modelo=str(salida.get("modelo") or elegido.get("modelo") or ""),
        region=str(elegido.get("region") or ""),
        usuario_id=getattr(principal, "id", None),
        objeto="transcripcion",
        objeto_id=objeto_id,
        tokens_entrada=int(salida.get("tokens_entrada") or 0),
        tokens_salida=int(salida.get("tokens_salida") or 0),
        coste=enrutador.coste_estimado(
            uow.db,
            proveedor=str(elegido.get("elegido") or ""),
            tokens_entrada=int(salida.get("tokens_entrada") or 0),
            tokens_salida=int(salida.get("tokens_salida") or 0),
        ),
        duracion_ms=int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000),
        resultado="pendiente",
        opt_out=bool(elegido.get("opt_out")),
    )
    return {**salida, "recortada": recortada}


def _normalizado(texto: str) -> str:
    return " ".join(str(texto or "").lower().split())


def procesar(
    uow: UnidadDeTrabajo,
    *,
    principal: Any,
    objeto: str,
    objeto_id: UUID,
    base_para_grabar: str,
    participantes_avisados: bool,
    participantes_externos: bool = True,
    idioma: str = "es",
    audio: bytes | None = None,
    nombre_fichero: str = "",
    mime: str = "",
    enlace: str = "",
    texto: str = "",
    guardar_audio: bool = True,
) -> dict[str, Any]:
    """Transcribe (si hace falta), resume, extrae y guarda. Nada se crea solo."""
    # Primero el permiso para grabar: antes de mandar NADA a ningún sitio.
    trs.exigir_permiso_para_grabar(
        base=base_para_grabar,
        participantes_avisados=participantes_avisados,
        participantes_externos=participantes_externos,
    )
    fuentes = sum(1 for x in (audio, enlace.strip(), texto.strip()) if x)
    if fuentes != 1:
        raise ErrorValidacion(
            "Se transcribe una cosa: un fichero de audio, un enlace a la grabación o el "
            "texto ya transcrito.",
            error_code="reunion.una_fuente",
        )

    adjunto_id = ""
    if audio is not None:
        max_mb = int(_ajuste(uow.db, "ia_transcripcion_max_mb"))
        if len(audio) > max_mb * 1024 * 1024:
            raise ErrorValidacion(
                f"El audio pasa de {max_mb} MB.",
                error_code="reunion.audio_grande",
                detalle={"max_mb": max_mb},
            )
        conf = proveedor(uow.db)
        if not conf["configurado"]:
            raise Conflicto(conf["porque"], error_code="reunion.sin_proveedor")
        # Con envío por enlace hay que guardarlo: el proveedor lo descarga.
        if guardar_audio or conf["envio"] == "enlace":
            adjunto_id = _subir_audio(
                principal,
                objeto=objeto,
                objeto_id=objeto_id,
                nombre=nombre_fichero,
                datos=audio,
                mime=mime,
            )
        url = (
            _enlace_firmado(principal, objeto=objeto, adjunto_id=adjunto_id)
            if conf["envio"] == "enlace"
            else ""
        )
        transcrito = transcribir_audio(
            uow.db, principal=principal, idioma=idioma, audio=audio, audio_url=url
        )
        origen = "audio"
    elif enlace.strip():
        if not enlace.strip().lower().startswith(("https://", "http://")):
            raise ErrorValidacion("El enlace no es una URL.", error_code="reunion.enlace_invalido")
        transcrito = transcribir_audio(
            uow.db, principal=principal, idioma=idioma, audio_url=enlace.strip()
        )
        origen = "enlace"
    else:
        transcrito = {"texto": texto.strip(), "confianza": None, "segundos": None, "proveedor": ""}
        origen = "texto"

    confianza = transcrito["confianza"]
    # Sin medida de confianza (texto pegado por una persona, o un proveedor que
    # no la da) se trata como fiable y se dice que no se midió.
    fiable = confianza is None or confianza >= trs._ia_confianza_transcripcion()

    fila = TranscripcionReunion(
        tenant_id=uow.tenant_id,
        objeto=objeto,
        objeto_id=objeto_id,
        origen=origen,
        adjunto_id=UUID(adjunto_id) if adjunto_id else None,
        enlace=enlace.strip() if origen == "enlace" else "",
        base_para_grabar=base_para_grabar,
        idioma=idioma[:10],
        texto=transcrito["texto"],
        confianza=confianza,
        fiable=fiable,
        segundos=transcrito["segundos"],
        proveedor=str(transcrito.get("proveedor") or "")[:200],
        creada_por=getattr(principal, "id", None),
    )
    uow.db.add(fila)
    uow.db.flush()

    avisos: list[str] = []
    if confianza is None and origen != "texto":
        avisos.append("El proveedor no da confianza: no se ha podido medir.")
    try:
        salida = _resumir(
            uow, texto=fila.texto, idioma=idioma, principal=principal, objeto_id=fila.id
        )
    except CrmError as exc:
        # La transcripción ya está pagada: se guarda aunque no haya resumen.
        fila.estado = "sin_resumen"
        fila.aviso = f"No se ha podido resumir: {exc.mensaje}"[:2000]
        uow.db.flush()
        return a_dict(fila)

    if salida.get("recortada"):
        avisos.append(
            "La transcripción es más larga que lo que se manda al modelo: el resumen es del principio."
        )
    elementos = [e for e in salida.get("elementos") or [] if isinstance(e, dict)]
    propuestas = trs.proponer_extraidos(
        elementos=elementos, confianza_transcripcion=confianza if confianza is not None else 1.0
    )
    texto_normal = _normalizado(fila.texto)
    compromisos = []
    for n, p in enumerate(propuestas.get("propuestas") or []):
        cita = str(p.get("cita") or "")
        compromisos.append(
            {
                **p,
                "n": n,
                # La cita tiene que estar en lo transcrito. Si no está, el modelo
                # la ha parafraseado (o inventado) y se dice.
                "cita_literal": bool(cita) and _normalizado(cita) in texto_normal,
                "se_hace_tarea": p.get("tipo") in SE_HACEN_TAREA,
                "tarea_id": None,
            }
        )
    fila.resumen = str(salida.get("resumen") or "")
    fila.compromisos = compromisos
    fila.descartados = list(propuestas.get("descartados") or [])
    if not propuestas.get("propuestas") and propuestas.get("porque"):
        avisos.append(str(propuestas["porque"]))
    fila.aviso = " ".join(avisos)[:2000]
    uow.db.flush()
    registrar(
        uow.db,
        accion="reunion.transcrita",
        objeto=objeto,
        objeto_id=objeto_id,
        datos={"transcripcion_id": str(fila.id), "origen": origen, "compromisos": len(compromisos)},
        tenant_id=uow.tenant_id,
    )
    return a_dict(fila)


def a_dict(fila: TranscripcionReunion) -> dict[str, Any]:
    return {
        "id": str(fila.id),
        "objeto": fila.objeto,
        "objeto_id": str(fila.objeto_id),
        "origen": fila.origen,
        "adjunto_id": str(fila.adjunto_id) if fila.adjunto_id else None,
        "enlace": fila.enlace,
        "base_para_grabar": fila.base_para_grabar,
        "idioma": fila.idioma,
        "texto": fila.texto,
        "confianza": fila.confianza,
        "fiable": fila.fiable,
        "segundos": fila.segundos,
        "minutos": int(math.ceil(fila.segundos / 60)) if fila.segundos else None,
        "proveedor": fila.proveedor,
        "resumen": fila.resumen,
        "compromisos": list(fila.compromisos or []),
        "descartados": list(fila.descartados or []),
        "estado": fila.estado,
        "aviso": fila.aviso,
        "que_no_es": (
            "Esto no es un acta. El modelo confunde nombres, se pierde con dos personas "
            "hablando a la vez y traduce mal las cifras: lo importante se comprueba "
            "antes de citarlo."
        ),
        "created_at": fila.created_at.isoformat() if fila.created_at else None,
    }


def listar(db: Any, tenant_id: UUID, *, objeto: str, objeto_id: UUID) -> list[dict[str, Any]]:
    filas = (
        db.execute(
            select(TranscripcionReunion)
            .where(
                TranscripcionReunion.tenant_id == tenant_id,
                TranscripcionReunion.objeto == objeto,
                TranscripcionReunion.objeto_id == objeto_id,
            )
            .order_by(TranscripcionReunion.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [a_dict(f) for f in filas]


def decidir_compromiso(
    uow: UnidadDeTrabajo,
    *,
    transcripcion_id: UUID,
    n: int,
    principal: Any,
    confirmar: bool,
    asunto: str = "",
    vence_at: str = "",
) -> dict[str, Any]:
    """Una persona confirma —o descarta— un compromiso. Al confirmar, la tarea."""
    fila = uow.db.execute(
        select(TranscripcionReunion).where(
            TranscripcionReunion.id == transcripcion_id,
            TranscripcionReunion.tenant_id == uow.tenant_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Esa transcripción no existe", error_code="reunion.no_encontrada")
    compromisos = [dict(c) for c in fila.compromisos or []]
    elegido = next((c for c in compromisos if int(c.get("n", -1)) == n), None)
    if elegido is None:
        raise NoEncontrado(
            "Ese compromiso no existe", error_code="reunion.compromiso_no_encontrado"
        )
    if elegido.get("estado") != "propuesta":
        raise Conflicto(
            f"Ese compromiso ya está {elegido.get('estado')}.",
            error_code="reunion.ya_decidido",
        )
    ahora = datetime.now(timezone.utc).isoformat()
    elegido["decidida_por"] = str(getattr(principal, "id", "") or "")
    elegido["decidida_at"] = ahora
    if not confirmar:
        elegido["estado"] = "descartada"
    else:
        final_asunto = (asunto or str(elegido.get("texto") or "")).strip()[:300]
        elegido["hubo_correccion"] = (
            bool(asunto.strip()) and asunto.strip() != str(elegido.get("texto") or "").strip()
        )
        elegido["final"] = {"asunto": final_asunto, "vence_at": vence_at or None}
        if elegido.get("se_hace_tarea"):
            elegido["tarea_id"] = _crear_tarea(
                fila, elegido, principal=principal, asunto=final_asunto, vence_at=vence_at
            )
        elegido["estado"] = "confirmada"
    fila.compromisos = [elegido if int(c.get("n", -1)) == n else c for c in compromisos]
    uow.db.flush()
    registrar(
        uow.db,
        accion="reunion.compromiso_decidido",
        objeto=fila.objeto,
        objeto_id=fila.objeto_id,
        datos={
            "transcripcion_id": str(fila.id),
            "n": n,
            "estado": elegido["estado"],
            "tarea_id": elegido.get("tarea_id"),
        },
        tenant_id=uow.tenant_id,
    )
    return a_dict(fila)


def _crear_tarea(
    fila: TranscripcionReunion,
    compromiso: dict[str, Any],
    *,
    principal: Any,
    asunto: str,
    vence_at: str,
) -> str:
    """Crea la tarea en `party`, colgada del mismo registro que la reunión."""
    cuerpo: dict[str, Any] = {
        "tipo": "tarea",
        "asunto": asunto,
        "cuerpo": (
            f"{compromiso.get('texto') or ''}\n\nQuién: {compromiso.get('quien') or '—'}"
            + (f"\nCita: «{compromiso.get('cita')}»" if compromiso.get("cita") else "")
        ),
        "detalles": {
            "origen": "transcripcion",
            "transcripcion_id": str(fila.id),
            "compromiso": int(compromiso.get("n", 0)),
            f"{fila.objeto}_id": str(fila.objeto_id),
        },
    }
    if vence_at:
        cuerpo["vence_at"] = vence_at
    if fila.objeto == "actividad":
        # La tarea cuelga de lo mismo que la reunión: la cuenta, el contacto, la
        # oportunidad. Una tarea colgada de una actividad no la ve nadie.
        madre = _llamar(principal, metodo="GET", ruta=f"/api/v1/activities/{fila.objeto_id}")
        datos = madre.get("datos") if int(madre.get("estado") or 0) == 200 else None
        if isinstance(datos, dict):
            for campo in ("objeto", "objeto_id", "cuenta_id", "contacto_id"):
                if datos.get(campo):
                    cuerpo[campo] = datos[campo]
    else:
        cuerpo["objeto"] = fila.objeto
        cuerpo["objeto_id"] = str(fila.objeto_id)
    creada = _exigir_ok(
        _llamar(principal, metodo="POST", ruta="/api/v1/activities", cuerpo=cuerpo),
        "crear la tarea",
    )
    return str((creada or {}).get("id") or "")


def dictar(
    db: Any, *, principal: Any, audio: bytes, idioma: str, nombre: str, mime: str
) -> dict[str, Any]:
    """Audio a texto para el asistente de voz, cuando el navegador no reconoce.

    No se guarda nada: es una pregunta dicha en voz alta, no una grabación. Si
    el proveedor sólo sabe descargar de un enlace, se rechaza en vez de guardar
    el audio como documento: guardar la voz de alguien para hacerle una
    pregunta al asistente no es lo que esa persona ha pedido.
    """
    max_mb = int(_ajuste(db, "ia_transcripcion_max_mb"))
    if len(audio) > max_mb * 1024 * 1024:
        raise ErrorValidacion(f"El audio pasa de {max_mb} MB.", error_code="reunion.audio_grande")
    conf = proveedor(db)
    if not conf["configurado"]:
        raise Conflicto(conf["porque"], error_code="reunion.sin_proveedor")
    if conf["envio"] != "contenido":
        raise Conflicto(
            "El proveedor configurado descarga el audio de un enlace, y para dictar "
            "habría que guardar la voz como documento. Se dicta con el reconocimiento "
            "del navegador, o se configura un proveedor que reciba el audio.",
            error_code="voz.proveedor_por_enlace",
        )
    salida = transcribir_audio(db, principal=principal, idioma=idioma, audio=audio)
    return {"texto": salida["texto"], "confianza": salida["confianza"], "guardado": False}
