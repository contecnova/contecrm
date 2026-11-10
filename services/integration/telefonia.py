"""Telefonía conectada al CRM: screen pop, transferencia con contexto e IVR
(CRM-04.02.01.05).

Lo que se le pide a una integración de telefonía es que **cuando suene el teléfono
ya esté la ficha abierta**. Suena a comodidad y no lo es: son quince segundos por
llamada buscando quién llama, multiplicados por doscientas llamadas al día, y sobre
todo es el cliente contando otra vez lo mismo.

Las decisiones:

**Se identifica por el número y se dice con qué confianza.** Un número que
coincide con tres fichas no es una ficha: es una lista, y abrir la primera «porque
suele ser esa» hace que el agente salude por el nombre equivocado — que es peor
que no saludar por ninguno.

**La transferencia lleva el contexto o no es una transferencia.** Pasar la llamada
sin lo que ya se ha hablado obliga al cliente a empezar de cero, y esa es
literalmente la queja número uno de cualquier servicio de atención.

**El IVR aporta lo que el cliente ya tecleó.** Si marcó su número de pedido, ese
dato llega con la llamada: volver a pedírselo al descolgar es la forma más rápida
de que alguien se enfade antes de que empiece la conversación.

**Y la llamada se registra pase lo que pase.** Una llamada perdida o que nadie
cogió es información —y de la buena—: las que no constan son justo las que se
pierden en la cola.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.errors import Conflicto, CrmError, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Eventos que manda una centralita. Cerrada porque de cada uno sale una acción
# distinta en la pantalla, y uno desconocido que se ignore en silencio deja al
# agente esperando algo que no va a pasar.
EVENTOS = ("entrante", "contestada", "colgada", "perdida", "transferida", "en_cola", "saliente")

# Estados con los que puede terminar una llamada. `perdida` y `abandonada` van
# separadas: una la colgó el que llamaba antes de que nadie la cogiera y la otra
# nunca llegó a sonar, y confundirlas oculta un problema de enrutado.
RESULTADOS = ("contestada", "perdida", "abandonada", "desviada", "buzon")


# Longitud mínima para intentar identificar por número. Con menos, media base
# encaja: un «600» coincide con miles de fichas.
def _telefono_minimo_digitos() -> int:
    """Antes `_telefono_minimo_digitos() = 7`.

    Era una constante de módulo. Sale del `.env`, que es donde una instalación
    puede afinarla sin tocar código.
    """
    from crmcore.config import get_settings

    return get_settings().telefono_minimo_digitos


_SOLO_DIGITOS = re.compile(r"\D+")


def _normalizar(numero: str) -> str:
    """Deja solo dígitos y se queda con la cola significativa.

    Se compara por el final a propósito: el mismo teléfono aparece como
    `+34600...`, `0034600...` y `600...` según quién lo escribiera, y comparar
    literalmente hace que el screen pop no salte justo con los clientes de toda la
    vida, que son los que están mal escritos.
    """
    limpio = _SOLO_DIGITOS.sub("", numero or "")
    return limpio[-9:] if len(limpio) > 9 else limpio


def identificar(*, numero: str, candidatos: list[dict[str, Any]]) -> dict[str, Any]:
    """Quién llama, **y con qué confianza**.

    Tres respuestas distintas y ninguna se redondea: **una ficha**, **varias** y
    **ninguna**. Abrir la primera de tres «porque suele ser esa» hace que el
    agente salude por el nombre equivocado, que es peor que no saludar por
    ninguno.

    Y con un número corto no se intenta: con menos de siete dígitos media base
    encaja.
    """
    clave = _normalizar(numero)
    if len(clave) < _telefono_minimo_digitos():
        return {
            "identificado": False,
            "motivo": "numero_corto",
            "que_hacer": (
                "El número es demasiado corto para buscar: con menos de "
                f"{_telefono_minimo_digitos()} dígitos media base encaja. Se abre la pantalla en "
                "blanco y se pregunta."
            ),
        }

    encajan = [
        c
        for c in candidatos
        if any(_normalizar(str(t)) == clave for t in (c.get("telefonos") or []))
    ]
    if not encajan:
        return {
            "identificado": False,
            "motivo": "desconocido",
            "numero": clave,
            "que_hacer": (
                "No hay ninguna ficha con ese número. No es basura: puede ser un "
                "contacto que falta por dar de alta, y conviene ofrecerlo al colgar."
            ),
        }
    if len(encajan) > 1:
        return {
            "identificado": False,
            "motivo": "ambiguo",
            "candidatos": [
                {"id": str(c.get("id")), "nombre": c.get("nombre"), "cuenta": c.get("cuenta")}
                for c in encajan
            ],
            "que_hacer": (
                f"{len(encajan)} fichas comparten ese número —suele ser una centralita "
                "de empresa—. Se enseñan las tres y elige el agente: abrir la primera "
                "hace que salude por el nombre equivocado."
            ),
        }
    ficha = encajan[0]
    return {
        "identificado": True,
        "contacto_id": str(ficha.get("id")),
        "nombre": ficha.get("nombre"),
        "cuenta": ficha.get("cuenta"),
    }


def pantalla_al_sonar(
    *,
    identificacion: dict[str, Any],
    datos_del_ivr: dict[str, Any] | None = None,
    ultimo_caso: dict[str, Any] | None = None,
    ultima_interaccion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Qué se le pone delante al agente antes de descolgar.

    Lo que el cliente **ya tecleó en el IVR viaja con la llamada**. Si marcó su
    número de pedido, volver a pedírselo al descolgar es la forma más rápida de
    que se enfade antes de empezar.

    Y lo que se enseña es **lo último que le pasó**, no su ficha entera: un agente
    tiene cuatro segundos mientras suena, y un panel con veinte campos no se lee
    en cuatro segundos.
    """
    ivr = dict(datos_del_ivr or {})
    return {
        "abrir_ficha": bool(identificacion.get("identificado")),
        "contacto_id": identificacion.get("contacto_id"),
        "lo_que_ya_dijo_en_el_ivr": ivr,
        "ultimo_caso": ultimo_caso,
        "ultima_interaccion": ultima_interaccion,
        "no_volver_a_preguntar": sorted(ivr),
        "porque": (
            "Lo que tecleó en el IVR llega con la llamada: volver a pedírselo es la "
            "forma más rápida de que se enfade antes de empezar."
            if ivr
            else "El IVR no ha recogido nada, así que hay que preguntarlo."
        ),
        "que_se_enseña": (
            "Lo último que le pasó, no la ficha entera: un agente tiene cuatro segundos "
            "mientras suena, y un panel de veinte campos no se lee en cuatro segundos."
        ),
    }


def transferir(
    *,
    a: str,
    resumen: str,
    contacto_id: UUID | None,
    caso_id: UUID | None,
    lo_ya_hablado: list[str],
) -> dict[str, Any]:
    """Prepara una transferencia **con el contexto dentro**.

    Pasar la llamada sin lo que ya se ha hablado obliga al cliente a empezar de
    cero, y esa es literalmente la queja número uno de cualquier servicio de
    atención. Por eso el resumen es obligatorio: una transferencia sin resumen es
    la que se hace por quitarse la llamada de encima.
    """
    if not resumen.strip():
        raise ErrorValidacion(
            "Una transferencia sin resumen obliga al cliente a empezar de cero, y esa es "
            "la queja número uno de cualquier servicio de atención.",
            error_code="cti.transferencia_sin_contexto",
        )
    return {
        "a": a,
        "resumen": resumen.strip(),
        "contacto_id": str(contacto_id) if contacto_id else None,
        "caso_id": str(caso_id) if caso_id else None,
        "lo_ya_hablado": lo_ya_hablado,
        "el_cliente_no_repite": True,
        "porque": (
            "Lo que ya contó viaja con la llamada. Quien la recibe empieza sabiendo, no "
            "preguntando."
        ),
    }


def registrar_llamada(
    *,
    evento: str,
    resultado: str,
    numero: str,
    duracion_s: int,
    contacto_id: UUID | None,
    espera_s: int = 0,
    grabacion_ref: str = "",
) -> dict[str, Any]:
    """Deja constancia de la llamada, **haya hablado alguien o no**.

    Las perdidas y las abandonadas son las que más dicen: una llamada que nadie
    cogió es un cliente que lo intentó, y si no consta, el panel enseña un servicio
    impecable construido con las llamadas que sí se atendieron.

    Se distinguen además **perdida** (sonó y nadie la cogió) de **abandonada** (la
    colgaron en la cola antes de sonar): confundirlas oculta un problema de
    enrutado detrás de uno de plantilla.
    """
    if evento not in EVENTOS:
        raise ErrorValidacion(
            f"Evento de telefonía «{evento}» desconocido",
            error_code="cti.evento_invalido",
            detalle={"admitidos": list(EVENTOS)},
        )
    if resultado not in RESULTADOS:
        raise ErrorValidacion(
            f"Resultado «{resultado}» desconocido",
            error_code="cti.resultado_invalido",
            detalle={"admitidos": list(RESULTADOS)},
        )
    return {
        "evento": evento,
        "resultado": resultado,
        "numero": _normalizar(numero),
        "duracion_s": duracion_s,
        "espera_s": espera_s,
        "contacto_id": str(contacto_id) if contacto_id else None,
        "sin_atender": resultado in ("perdida", "abandonada"),
        "grabacion": grabacion_ref,
        "registrada_at": datetime.now(timezone.utc).isoformat(),
        "porque_se_registra_igual": (
            "Una llamada que nadie cogió es un cliente que lo intentó. Si no consta, el "
            "panel enseña un servicio impecable construido solo con las que se "
            "atendieron."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# La telefonía de verdad (09-11-2026)
#
# Hasta aquí, funciones puras: identificaban contra una lista que traía quien
# llamaba, componían la transferencia sin mandarla y «registraban» devolviendo un
# diccionario que no se guardaba en ninguna parte. Medido en el recorrido del
# 09-11-2026: ninguna llamada había quedado registrada nunca.
#
# Lo que sigue es la mitad que compromete:
#
# * **el perfil de telefonía es una conexión de integración**, con dos
#   operaciones declaradas —originar y transferir— y la traducción del aviso
#   que manda la centralita. Cambiar de proveedor es declarar otras dos
#   operaciones y otro mapeo, no escribir otro módulo;
# * **cada llamada se guarda**, con su historial de eventos, lo que recogió el
#   IVR, sus transferencias y el enlace a la grabación;
# * **el llamante se identifica contra los contactos y cuentas de verdad**,
#   preguntando a `party` por HTTP con la identidad de quien manda el aviso;
# * **y al colgar se registra sola como actividad en `party`**, con su duración
#   y su resultado, se haya cogido o no.
# ══════════════════════════════════════════════════════════════════════════

CLASE_PERFIL = "telefonia"
SENTIDOS = ("entrante", "saliente")
# Lo que el aviso de la centralita tiene que traer, ya traducido. Sin el
# identificador no se sabe a qué llamada pertenece cada aviso, y la misma
# llamada aparece tres veces.
CAMPOS_AVISO = (
    "id_externo",
    "evento",
    "numero",
    "sentido",
    "duracion_s",
    "espera_s",
    "resultado",
    "grabacion",
    "ivr",
    "agente",
    "destino",
)
OBLIGATORIOS_AVISO = ("id_externo", "evento")
# Los eventos con los que una llamada termina.
FINALES = ("colgada", "perdida")
# Mientras está en uno de estos, la llamada «suena» o está en curso.
VIVOS = ("entrante", "en_cola", "contestada", "transferida", "saliente")


class LlamadaTelefonica(Base, TimestampMixin):
    """Una llamada, entrante o saliente, tal como la contó la centralita."""

    __tablename__ = "llamadas_telefonicas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    conexion_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # El identificador que le da la centralita. Hace idempotente la ingesta: la
    # centralita reenvía el mismo aviso si no le contestamos a tiempo.
    id_externo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sentido: Mapped[str] = mapped_column(
        String(10), nullable=False, default="entrante", info={"opciones": SENTIDOS}
    )
    numero: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="",
        info={"anonimizar_en_copias": True, "sensibilidad": "personal"},
    )
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="entrante", info={"opciones": EVENTOS}
    )
    resultado: Mapped[str | None] = mapped_column(
        String(20), nullable=True, info={"opciones": RESULTADOS}
    )
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Quién la atiende o quién la hizo.
    usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    agente: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Lo que salió de identificar: una ficha, varias o ninguna, con el porqué.
    identificacion: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Lo último que le pasó a quien llama: su último caso y su última actividad.
    contexto: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    ivr: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    transferencias: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    eventos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    grabacion_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    duracion_s: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    espera_s: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inicio_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contestada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fin_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # La actividad que quedó en `party`. Vacía y con `registro_error` si no se
    # pudo crear: se dice, no se da por registrada.
    actividad_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    registro_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Lo que anota la persona al colgar (marcador): cómo fue, comercialmente.
    resultado_comercial: Mapped[str | None] = mapped_column(String(40), nullable=True)
    nota: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "id_externo", name="uq_llamada_id_externo"),
        Index("ix_llamadas_tenant_estado", "tenant_id", "estado", "created_at"),
    )


def _ajuste(clave: str, db: Session | None) -> Any:
    from services.integration.ajustes import valor

    return valor(clave, db)


# ── El perfil ─────────────────────────────────────────────────────────────


def validar_aviso(webhook: dict[str, Any]) -> list[str]:
    """Qué le falta a la traducción del aviso de la centralita."""
    mapeo = dict(webhook.get("mapeo") or {})
    problemas = [
        f"falta «{c}» en el mapeo: sin él no se sabe "
        + ("a qué llamada pertenece cada aviso" if c == "id_externo" else "qué ha pasado")
        for c in OBLIGATORIOS_AVISO
        if c not in mapeo
    ]
    sobrantes = sorted(set(mapeo) - set(CAMPOS_AVISO))
    if sobrantes:
        problemas.append(
            f"campos que no se usan: {', '.join(sobrantes)} (los que se leen son "
            f"{', '.join(CAMPOS_AVISO)})"
        )
    return problemas


def declarar_perfil(
    db: Session, tenant_id: UUID, *, conexion_id: UUID, webhook: dict[str, Any]
) -> Any:
    """Marca una conexión como la telefonía del tenant, con la traducción del aviso.

    Es una `Conexion` como cualquier otra —la misma bóveda de credenciales, el
    mismo conector—: originar y transferir son operaciones declaradas en ella.
    """
    from services.integration import conector
    from services.integration.modelos import Conexion

    fila = db.get(Conexion, conexion_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("La conexión no existe", error_code="telefonia.conexion_no_encontrada")
    clase = dict(fila.config or {}).get("clase")
    if clase and clase != CLASE_PERFIL:
        raise Conflicto(
            f"La conexión «{fila.nombre}» ya es de otra clase ({clase}).",
            error_code="telefonia.conexion_de_otra_clase",
        )
    problemas = validar_aviso(webhook)
    if problemas:
        raise ErrorValidacion(
            "La traducción del aviso de la centralita no se sostiene: " + "; ".join(problemas),
            error_code="telefonia.aviso_invalido",
            detalle={"problemas": problemas},
        )
    conector.exigir_funciones_conocidas(webhook)
    fila.config = {
        **dict(fila.config or {}),
        "clase": CLASE_PERFIL,
        "telefonia": {"webhook": webhook},
    }
    db.flush()
    return fila


def perfil(db: Session, tenant_id: UUID) -> Any:
    """La conexión de telefonía del tenant. Una, o se dice qué pasa."""
    from services.integration.modelos import Conexion

    candidatos = [
        c
        for c in db.execute(
            select(Conexion).where(Conexion.tenant_id == tenant_id, Conexion.activa.is_(True))
        )
        .scalars()
        .all()
        if dict(c.config or {}).get("clase") == CLASE_PERFIL
    ]
    if not candidatos:
        raise ErrorValidacion(
            "Este tenant no tiene telefonía conectada. Se conecta en Telefonía › "
            "Perfil, sobre una conexión de Integraciones.",
            error_code="telefonia.sin_perfil",
        )
    if len(candidatos) > 1:
        raise ErrorValidacion(
            "Hay más de una conexión marcada como telefonía y no se sabe por cuál llamar.",
            error_code="telefonia.perfil_ambiguo",
            detalle={"perfiles": sorted(c.nombre for c in candidatos)},
        )
    return candidatos[0]


def estado_del_perfil(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Qué está conectado y qué falta, para enseñarlo antes de la primera llamada."""
    from services.integration.operar import operacion_declarada

    try:
        conexion = perfil(db, tenant_id)
    except ErrorValidacion as exc:
        return {"conectado": False, "porque": exc.mensaje, "error_code": exc.error_code}
    op_originar = str(_ajuste("telefonia_op_originar", db))
    op_transferir = str(_ajuste("telefonia_op_transferir", db))
    webhook = dict(dict(dict(conexion.config or {}).get("telefonia") or {}).get("webhook") or {})
    operaciones = {
        op_originar: operacion_declarada(db, conexion.id, op_originar),
        op_transferir: operacion_declarada(db, conexion.id, op_transferir),
    }
    falta = [f"la operación «{k}»" for k, v in operaciones.items() if not v]
    falta += validar_aviso(webhook)
    return {
        "conectado": True,
        "conexion_id": str(conexion.id),
        "nombre": conexion.nombre,
        "sistema": conexion.sistema,
        "operaciones": operaciones,
        "webhook": webhook,
        "falta": falta,
        "sondeo_s": int(_ajuste("telefonia_sondeo_s", db)),
    }


# ── Traducir el aviso de la centralita ────────────────────────────────────


def _entero(valor: Any) -> int:
    try:
        return max(0, int(float(valor)))
    except (TypeError, ValueError):
        return 0


def traducir_aviso(webhook: dict[str, Any], crudo: dict[str, Any]) -> dict[str, Any]:
    """Del aviso de la centralita a los campos de aquí, con el conector de siempre.

    El mapeo admite alternativas, marcadores de vacío y `transformar` —el `mapa`
    es lo que traduce «ANSWERED» a «contestada»—: es lo mismo que lee un ERP.
    """
    from services.integration import conector

    rechazos: list[dict[str, Any]] = []
    registros = conector.mapear([crudo], webhook, rechazos=rechazos)
    if not registros:
        raise ErrorValidacion(
            "El aviso de la centralita no trae nada que se pueda leer con el mapeo " "declarado.",
            error_code="telefonia.aviso_ilegible",
            detalle={"rechazos": rechazos[:3]},
        )
    r = registros[0]
    faltan = [c for c in OBLIGATORIOS_AVISO if not str(r.get(c) or "").strip()]
    if faltan:
        raise ErrorValidacion(
            f"El aviso llega sin {', '.join(faltan)}.",
            error_code="telefonia.aviso_incompleto",
            detalle={"faltan": faltan},
        )
    evento = str(r.get("evento")).strip().lower()
    if evento not in EVENTOS:
        raise ErrorValidacion(
            f"Evento de telefonía «{evento}» desconocido: tradúcelo en el mapeo del perfil.",
            error_code="cti.evento_invalido",
            detalle={"admitidos": list(EVENTOS)},
        )
    resultado = str(r.get("resultado") or "").strip().lower() or None
    if resultado and resultado not in RESULTADOS:
        resultado = None
    sentido = str(r.get("sentido") or "").strip().lower()
    if sentido not in SENTIDOS:
        sentido = "saliente" if evento == "saliente" else "entrante"
    ivr = r.get("ivr")
    return {
        "id_externo": str(r.get("id_externo")).strip()[:200],
        "evento": evento,
        "numero": str(r.get("numero") or "").strip()[:40],
        "sentido": sentido,
        "duracion_s": _entero(r.get("duracion_s")),
        "espera_s": _entero(r.get("espera_s")),
        "resultado": resultado,
        "grabacion": str(r.get("grabacion") or "").strip(),
        "ivr": dict(ivr) if isinstance(ivr, dict) else {},
        "agente": str(r.get("agente") or "").strip()[:200],
        "destino": str(r.get("destino") or "").strip()[:200],
    }


# ── Los puertos hacia party, sustituibles en las pruebas ─────────────────

Invocador = Callable[..., dict[str, Any]]


def _invocar(**kw: Any) -> dict[str, Any]:
    from crmcore.http.interno import invocar

    return invocar(**kw)


def variantes_del_numero(numero: str) -> list[str]:
    """Las formas en que puede estar guardado el mismo número.

    `party` lo guarda normalizado (E.164) desde que normaliza al escribir, y las
    fichas viejas pueden tenerlo como se tecleó. Se pregunta por las dos.
    """
    from crmcore.normalizacion import normalizar_telefono

    digitos = _SOLO_DIGITOS.sub("", numero or "")
    formas = {normalizar_telefono(numero), digitos, f"+{digitos}" if digitos else ""}
    if len(digitos) > 9:
        formas.add(digitos[-9:])
    return sorted(f for f in formas if f and "," not in f)


def identificar_en_party(
    invocar: Invocador, *, identidad: dict[str, Any], numero: str
) -> dict[str, Any]:
    """Quién llama, preguntando a `party` por los contactos y cuentas con ese número.

    Con la identidad de quien manda el aviso: si no puede ver una ficha, la
    ficha emergente no se la enseña. Se usa la misma decisión de siempre
    (`identificar`): una ficha, varias o ninguna, sin redondear.
    """
    if len(_normalizar(numero)) < _telefono_minimo_digitos():
        return identificar(numero=numero, candidatos=[])
    formas = ",".join(variantes_del_numero(numero))
    candidatos: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for campo in ("telefono", "movil"):
        r = invocar(
            metodo="GET",
            ruta="/api/v1/contacts",
            parametros={f"{campo}__en": formas, "limite": 20},
            **identidad,
        )
        if not r.get("ok"):
            continue
        for c in (r.get("datos") or {}).get("items") or []:
            if str(c.get("id")) in vistos:
                continue
            vistos.add(str(c.get("id")))
            candidatos.append(
                {
                    "id": c.get("id"),
                    "nombre": c.get("nombre_completo") or c.get("nombre"),
                    "tipo": "contacto",
                    "telefonos": [numero],
                }
            )
    r = invocar(
        metodo="GET",
        ruta="/api/v1/accounts",
        parametros={"telefono__en": formas, "limite": 20},
        **identidad,
    )
    if r.get("ok"):
        for c in (r.get("datos") or {}).get("items") or []:
            candidatos.append(
                {
                    "id": c.get("id"),
                    "nombre": c.get("nombre"),
                    "tipo": "cuenta",
                    "cuenta": c.get("nombre"),
                    "telefonos": [numero],
                }
            )
    salida = identificar(numero=numero, candidatos=candidatos)
    if salida.get("identificado"):
        salida["tipo"] = candidatos[0]["tipo"] if len(candidatos) == 1 else None
    return salida


def contexto_en_party(
    invocar: Invocador, *, identidad: dict[str, Any], contacto_id: str | None, cuenta_id: str | None
) -> dict[str, Any]:
    """Lo último que le pasó: su última actividad y su último caso.

    Lo último y no la ficha entera: un agente tiene cuatro segundos mientras
    suena. Si no se puede leer, no se inventa: se queda vacío.
    """
    contexto: dict[str, Any] = {}
    filtro = {"contacto_id": contacto_id} if contacto_id else {"cuenta_id": cuenta_id}
    if not (contacto_id or cuenta_id):
        return contexto
    r = invocar(
        metodo="GET",
        ruta="/api/v1/activities",
        parametros={**filtro, "limite": 1},
        **identidad,
    )
    if r.get("ok"):
        items = (r.get("datos") or {}).get("items") or []
        if items:
            a = items[0]
            contexto["ultima_interaccion"] = {
                "id": a.get("id"),
                "tipo": a.get("tipo"),
                "asunto": a.get("asunto"),
                "cuando": a.get("fin_at") or a.get("inicio_at") or a.get("created_at"),
            }
    r = invocar(
        metodo="GET",
        ruta="/api/v1/casos",
        parametros={**filtro, "limite": 1},
        **identidad,
    )
    if r.get("ok"):
        datos = r.get("datos")
        items = (datos or {}).get("items") if isinstance(datos, dict) else datos
        if items:
            c = items[0]
            contexto["ultimo_caso"] = {
                "id": c.get("id"),
                "asunto": c.get("asunto") or c.get("titulo"),
                "estado": c.get("estado"),
            }
    return contexto


def registrar_en_party(
    invocar: Invocador, *, identidad: dict[str, Any], llamada: LlamadaTelefonica
) -> str:
    """Crea la actividad de la llamada en `party` y la deja completada.

    Devuelve su id. Si `party` no la acepta se lanza: quien llama lo apunta en
    la llamada (`registro_error`) en vez de darla por registrada.
    """
    quien = (llamada.identificacion or {}).get("nombre") or llamada.numero or "número oculto"
    asunto = (
        f"Llamada {'entrante de' if llamada.sentido == 'entrante' else 'a'} {quien}"
        f" — {llamada.resultado or llamada.estado}"
    )[:300]
    objeto, objeto_id = (
        ("contacto", llamada.contacto_id)
        if llamada.contacto_id
        else (("cuenta", llamada.cuenta_id) if llamada.cuenta_id else (None, None))
    )
    cuerpo = {
        "tipo": "llamada",
        "asunto": asunto,
        "objeto": objeto,
        "objeto_id": str(objeto_id) if objeto_id else None,
        "contacto_id": str(llamada.contacto_id) if llamada.contacto_id else None,
        "cuenta_id": str(llamada.cuenta_id) if llamada.cuenta_id else None,
        "asignada_a": str(llamada.usuario_id) if llamada.usuario_id else None,
        "inicio_at": (llamada.inicio_at or llamada.created_at or _ahora_utc()).isoformat(),
        "fin_at": (llamada.fin_at or _ahora_utc()).isoformat(),
        "detalles": {
            "llamada_id": str(llamada.id),
            "sentido": llamada.sentido,
            "numero": llamada.numero,
            "duracion_s": llamada.duracion_s,
            "espera_s": llamada.espera_s,
            "resultado": llamada.resultado,
            "grabacion": llamada.grabacion_url or "",
            "ivr": llamada.ivr or {},
            "transferencias": llamada.transferencias or [],
        },
    }
    r = invocar(
        metodo="POST",
        ruta="/api/v1/activities",
        cuerpo=cuerpo,
        **identidad,
    )
    if not r.get("ok"):
        datos = r.get("datos") or {}
        raise ErrorValidacion(
            f"party no ha aceptado la actividad (HTTP {r.get('estado')}): "
            f"{datos.get('mensaje') or datos.get('detail') or datos}"[:500],
            error_code="telefonia.actividad_rechazada",
        )
    actividad_id = str((r.get("datos") or {}).get("id"))
    invocar(
        metodo="POST",
        ruta=f"/api/v1/activities/{actividad_id}/completar",
        cuerpo={"resultado": llamada.resultado or llamada.estado},
        **identidad,
    )
    return actividad_id


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── Ingerir un aviso ──────────────────────────────────────────────────────


def _uuid_o_none(valor: Any) -> UUID | None:
    try:
        return UUID(str(valor)) if valor else None
    except (TypeError, ValueError):
        return None


def ingerir(
    db: Session,
    tenant_id: UUID,
    *,
    conexion: Any,
    aviso: dict[str, Any],
    identidad: dict[str, Any],
    invocar: Invocador | None = None,
) -> LlamadaTelefonica:
    """Aplica un aviso ya traducido a su llamada. Idempotente por `id_externo`.

    * **entrante**: se crea la llamada, se identifica al llamante y se guarda lo
      último que le pasó, que es lo que pinta la ficha emergente;
    * **contestada / transferida / en cola**: se avanza el estado;
    * **colgada o perdida**: se cierra con su duración y su resultado, y se
      registra como actividad en `party` —una sola vez aunque el aviso se
      repita—.
    """
    invocar = invocar or _invocar
    ahora = _ahora_utc()
    llamada = db.execute(
        select(LlamadaTelefonica).where(
            LlamadaTelefonica.tenant_id == tenant_id,
            LlamadaTelefonica.id_externo == aviso["id_externo"],
        )
    ).scalar_one_or_none()
    nueva = llamada is None
    if llamada is None:
        llamada = LlamadaTelefonica(
            tenant_id=tenant_id,
            conexion_id=conexion.id if conexion is not None else None,
            id_externo=aviso["id_externo"],
            sentido=aviso["sentido"],
            numero=aviso["numero"],
            estado=aviso["evento"],
            inicio_at=ahora,
            identificacion={},
            contexto={},
            ivr={},
            transferencias=[],
            eventos=[],
        )
        db.add(llamada)

    evento = aviso["evento"]
    llamada.eventos = [
        *(llamada.eventos or []),
        {"evento": evento, "at": ahora.isoformat(), "resultado": aviso.get("resultado")},
    ]
    if aviso.get("numero") and not llamada.numero:
        llamada.numero = aviso["numero"]
    if aviso.get("ivr"):
        # Lo que el cliente tecleó viaja con la llamada y se acumula: si el IVR
        # manda el pedido en un aviso y el motivo en otro, se quedan los dos.
        llamada.ivr = {**(llamada.ivr or {}), **aviso["ivr"]}
    if aviso.get("agente"):
        llamada.agente = aviso["agente"]
        llamada.usuario_id = _uuid_o_none(aviso["agente"]) or llamada.usuario_id
    if aviso.get("grabacion"):
        llamada.grabacion_url = aviso["grabacion"]
    if aviso.get("espera_s"):
        llamada.espera_s = aviso["espera_s"]

    if llamada.sentido == "entrante" and not llamada.identificacion and llamada.numero:
        try:
            ident = identificar_en_party(invocar, identidad=identidad, numero=llamada.numero)
        except CrmError as exc:
            ident = {"identificado": False, "motivo": "sin_respuesta", "que_hacer": exc.mensaje}
        llamada.identificacion = ident
        if ident.get("identificado"):
            if ident.get("tipo") == "cuenta":
                llamada.cuenta_id = _uuid_o_none(ident.get("contacto_id"))
            else:
                llamada.contacto_id = _uuid_o_none(ident.get("contacto_id"))
            try:
                llamada.contexto = contexto_en_party(
                    invocar,
                    identidad=identidad,
                    contacto_id=str(llamada.contacto_id) if llamada.contacto_id else None,
                    cuenta_id=str(llamada.cuenta_id) if llamada.cuenta_id else None,
                )
            except CrmError:
                llamada.contexto = {}
        # El número que llamó es una señal de identidad para party
        # (CRM-01.01.05.02), con el contacto si se le reconoció. Si party no
        # contesta, la llamada sigue y la señal la manda el relevo.
        from services.integration import senales_identidad as sen

        db.flush()
        sen.anotar_y_enviar(
            db,
            tenant_id,
            identidad=identidad,
            invocar=invocar,
            tipo="telefono",
            valor=llamada.numero,
            origen="telefonia",
            referencia=str(llamada.id),
            contacto_id=llamada.contacto_id,
        )

    if evento == "contestada" and llamada.contestada_at is None:
        llamada.contestada_at = ahora
    if evento == "transferida" and aviso.get("destino"):
        llamada.transferencias = [
            *(llamada.transferencias or []),
            {"a": aviso["destino"], "at": ahora.isoformat(), "origen": "centralita"},
        ]

    if evento in FINALES:
        if llamada.estado not in FINALES:
            llamada.fin_at = ahora
        llamada.estado = evento
        if aviso.get("duracion_s"):
            llamada.duracion_s = aviso["duracion_s"]
        elif llamada.contestada_at and not llamada.duracion_s:
            llamada.duracion_s = int((ahora - llamada.contestada_at).total_seconds())
        llamada.resultado = aviso.get("resultado") or _resultado_por_historia(llamada, evento)
        db.flush()
        if llamada.actividad_id is None:
            try:
                llamada.actividad_id = _uuid_o_none(
                    registrar_en_party(invocar, identidad=identidad, llamada=llamada)
                )
                llamada.registro_error = None
            except CrmError as exc:
                llamada.registro_error = exc.mensaje[:1000]
    elif llamada.estado not in FINALES:
        llamada.estado = evento
    db.flush()
    logger.info(
        "telefonia.aviso",
        evento=evento,
        nueva=nueva,
        identificada=bool((llamada.identificacion or {}).get("identificado")),
    )
    return llamada


def _resultado_por_historia(llamada: LlamadaTelefonica, evento: str) -> str:
    """Cómo terminó, cuando la centralita no lo dice.

    Contestada si alguien la cogió. Si no: **perdida** si llegó a sonar y
    **abandonada** si se colgó en la cola. Confundirlas oculta un problema de
    enrutado detrás de uno de plantilla.
    """
    # Una llamada que duró algo o que se pasó a otra persona la cogió alguien,
    # aunque la centralita no mandara el «contestada».
    if llamada.contestada_at is not None or llamada.duracion_s > 0 or llamada.transferencias:
        return "contestada"
    if any((e or {}).get("evento") == "en_cola" for e in llamada.eventos or []) and not any(
        (e or {}).get("evento") == "entrante" for e in llamada.eventos or []
    ):
        return "abandonada"
    return "perdida"


# ── Originar y transferir ─────────────────────────────────────────────────


def originar(
    db: Session,
    tenant_id: UUID,
    *,
    usuario_id: UUID,
    numero: str,
    contacto_id: UUID | None,
    cuenta_id: UUID | None,
    grabar: bool,
    agente: str = "",
) -> LlamadaTelefonica:
    """Click-to-call: pide a la centralita que marque y guarda la llamada.

    La llamada se guarda ANTES de pedirla, con su identificador nuestro como
    referencia: si la centralita contesta tarde o el aviso llega antes que la
    respuesta, se casan por esa referencia y no aparecen dos llamadas.
    """
    from services.integration import operar

    if len(_normalizar(numero)) < _telefono_minimo_digitos():
        raise ErrorValidacion(
            f"El número es demasiado corto para marcar (mínimo {_telefono_minimo_digitos()} dígitos).",
            error_code="telefonia.numero_corto",
        )
    conexion = perfil(db, tenant_id)
    llamada = LlamadaTelefonica(
        tenant_id=tenant_id,
        conexion_id=conexion.id,
        sentido="saliente",
        numero=numero.strip()[:40],
        estado="saliente",
        contacto_id=contacto_id,
        cuenta_id=cuenta_id,
        usuario_id=usuario_id,
        agente=agente,
        inicio_at=_ahora_utc(),
        identificacion={"identificado": bool(contacto_id or cuenta_id), "origen": "ficha"},
        contexto={},
        ivr={},
        transferencias=[],
        eventos=[{"evento": "saliente", "at": _ahora_utc().isoformat(), "origen": "crm"}],
    )
    db.add(llamada)
    db.flush()
    try:
        respuesta = operar.ejecutar(
            db,
            conexion=conexion,
            clave=str(_ajuste("telefonia_op_originar", db)),
            parametros={
                "numero": numero.strip(),
                "referencia": str(llamada.id),
                "agente": agente or str(usuario_id),
                "usuario_id": str(usuario_id),
                "grabar": "true" if grabar else "false",
            },
            timeout_s=float(_ajuste("telefonia_espera_s", db)),
            codigo_error="telefonia.operacion_no_declarada",
        )
    except CrmError as exc:
        llamada.estado = "colgada"
        llamada.resultado = "abandonada"
        llamada.fin_at = _ahora_utc()
        llamada.error = f"{exc.error_code}: {exc.mensaje}"[:1000]
        db.flush()
        return llamada
    registro = operar.primer_registro(respuesta)
    externo = str(registro.get("id_externo") or registro.get("id") or "").strip()
    if externo:
        otra = db.execute(
            select(LlamadaTelefonica).where(
                LlamadaTelefonica.tenant_id == tenant_id,
                LlamadaTelefonica.id_externo == externo,
                LlamadaTelefonica.id != llamada.id,
            )
        ).scalar_one_or_none()
        if otra is None:
            llamada.id_externo = externo[:200]
    db.flush()
    return llamada


def transferir_llamada(
    db: Session,
    tenant_id: UUID,
    *,
    llamada_id: UUID,
    a: str,
    resumen: str,
    lo_ya_hablado: list[str],
    por: UUID,
) -> LlamadaTelefonica:
    """Pasa la llamada a otra persona o cola, con el contexto dentro.

    El resumen es obligatorio (`transferir`) y viaja a la centralita como
    parámetro y a la llamada guardada: quien la recibe abre la misma ficha
    emergente y lee lo que ya se habló.
    """
    from services.integration import operar

    llamada = db.get(LlamadaTelefonica, llamada_id)
    if llamada is None or llamada.tenant_id != tenant_id:
        raise NoEncontrado("La llamada no existe", error_code="telefonia.llamada_no_encontrada")
    if llamada.estado in FINALES:
        raise Conflicto(
            "La llamada ya ha terminado: no hay nada que transferir.",
            error_code="telefonia.llamada_terminada",
        )
    paquete = transferir(
        a=a,
        resumen=resumen,
        contacto_id=llamada.contacto_id,
        caso_id=_uuid_o_none(((llamada.contexto or {}).get("ultimo_caso") or {}).get("id")),
        lo_ya_hablado=lo_ya_hablado,
    )
    conexion = perfil(db, tenant_id)
    operar.ejecutar(
        db,
        conexion=conexion,
        clave=str(_ajuste("telefonia_op_transferir", db)),
        parametros={
            "id_externo": llamada.id_externo or "",
            "referencia": str(llamada.id),
            "a": a,
            "resumen": paquete["resumen"],
            "ivr": llamada.ivr or {},
        },
        timeout_s=float(_ajuste("telefonia_espera_s", db)),
        codigo_error="telefonia.operacion_no_declarada",
    )
    llamada.transferencias = [
        *(llamada.transferencias or []),
        {
            "a": a,
            "resumen": paquete["resumen"],
            "lo_ya_hablado": lo_ya_hablado,
            "por": str(por),
            "at": _ahora_utc().isoformat(),
            "origen": "crm",
        },
    ]
    llamada.estado = "transferida"
    llamada.usuario_id = _uuid_o_none(a) or llamada.usuario_id
    db.flush()
    return llamada


def anotar_resultado(
    db: Session,
    tenant_id: UUID,
    *,
    llamada_id: UUID,
    resultado_comercial: str,
    nota: str,
    invocar: Invocador,
    identidad: dict[str, Any],
) -> LlamadaTelefonica:
    """Lo que solo sabe la persona: cómo fue y qué se habló. Va a su actividad."""
    llamada = db.get(LlamadaTelefonica, llamada_id)
    if llamada is None or llamada.tenant_id != tenant_id:
        raise NoEncontrado("La llamada no existe", error_code="telefonia.llamada_no_encontrada")
    llamada.resultado_comercial = resultado_comercial[:40]
    llamada.nota = nota.strip()
    if llamada.actividad_id is not None:
        r = invocar(
            metodo="PATCH",
            ruta=f"/api/v1/activities/{llamada.actividad_id}",
            cuerpo={"cuerpo": llamada.nota or None},
            **identidad,
        )
        if not r.get("ok"):
            llamada.registro_error = (
                f"La nota no se guardó en la actividad (HTTP {r.get('estado')})"
            )
    if resultado_comercial == str(_ajuste("telefonia_resultado_numero_erroneo", db)):
        marcar_telefono_erroneo(db, llamada, invocar=invocar, identidad=identidad)
    db.flush()
    return llamada


def marcar_telefono_erroneo(
    db: Session, llamada: LlamadaTelefonica, *, invocar: Invocador, identidad: dict[str, Any]
) -> dict[str, Any]:
    """«Número erróneo» marca el teléfono de la ficha del contacto en party.

    Por la edición del contacto, que admite `estado_telefono`, y con la
    identidad de quien cierra la llamada: si no puede editar la ficha, no se
    edita, y se dice. El resultado queda en la historia de la llamada, para que
    la pantalla pueda decir si se marcó o qué falta.
    """
    if llamada.contacto_id is None:
        hecho = {
            "marcado": False,
            "porque": "La llamada no está ligada a un contacto: márcalo a mano en su ficha.",
        }
    else:
        estado = str(_ajuste("telefonia_estado_telefono_erroneo", db))
        try:
            r = invocar(
                metodo="PATCH",
                ruta=f"/api/v1/contacts/{llamada.contacto_id}",
                cuerpo={"estado_telefono": estado},
                **identidad,
            )
        except CrmError as exc:
            r = {"ok": False, "estado": 0, "datos": {"mensaje": exc.mensaje}}
        if r.get("ok"):
            hecho = {"marcado": True, "estado_telefono": estado}
        else:
            datos = r.get("datos") or {}
            hecho = {
                "marcado": False,
                "porque": (
                    f"party no ha marcado el teléfono (HTTP {r.get('estado')}): "
                    f"{datos.get('mensaje') or datos.get('detail') or ''}"
                )[:500],
            }
    llamada.eventos = [
        *(llamada.eventos or []),
        {"evento": "telefono_erroneo", "at": _ahora_utc().isoformat(), **hecho},
    ]
    return hecho


def telefono_marcado(llamada: LlamadaTelefonica) -> dict[str, Any] | None:
    """Lo último que pasó al marcar el teléfono como erróneo, si se intentó."""
    for e in reversed(llamada.eventos or []):
        if (e or {}).get("evento") == "telefono_erroneo":
            return {k: v for k, v in e.items() if k not in ("evento",)}
    return None


def sonando(db: Session, tenant_id: UUID, *, usuario_id: UUID) -> list[LlamadaTelefonica]:
    """Las entrantes vivas que le tocan a esta persona o a nadie todavía.

    Con tope de vida: una llamada cuyo colgado se perdió no puede quedarse en la
    pantalla del agente para siempre.
    """
    desde = _ahora_utc() - timedelta(seconds=int(_ajuste("telefonia_ficha_emergente_s", db)))
    return list(
        db.execute(
            select(LlamadaTelefonica)
            .where(
                LlamadaTelefonica.tenant_id == tenant_id,
                LlamadaTelefonica.sentido == "entrante",
                LlamadaTelefonica.estado.in_(("entrante", "en_cola", "contestada", "transferida")),
                LlamadaTelefonica.updated_at >= desde,
                or_(
                    LlamadaTelefonica.usuario_id == usuario_id,
                    LlamadaTelefonica.usuario_id.is_(None),
                ),
            )
            .order_by(LlamadaTelefonica.created_at.desc())
            .limit(5)
        )
        .scalars()
        .all()
    )


def a_dict(llamada: LlamadaTelefonica) -> dict[str, Any]:
    """La llamada, con lo que la pantalla al sonar tiene que enseñar."""
    pantalla = pantalla_al_sonar(
        identificacion=llamada.identificacion or {},
        datos_del_ivr=llamada.ivr or {},
        ultimo_caso=(llamada.contexto or {}).get("ultimo_caso"),
        ultima_interaccion=(llamada.contexto or {}).get("ultima_interaccion"),
    )
    return {
        "id": str(llamada.id),
        "id_externo": llamada.id_externo,
        "sentido": llamada.sentido,
        "numero": llamada.numero,
        "estado": llamada.estado,
        "resultado": llamada.resultado,
        "contacto_id": str(llamada.contacto_id) if llamada.contacto_id else None,
        "cuenta_id": str(llamada.cuenta_id) if llamada.cuenta_id else None,
        "usuario_id": str(llamada.usuario_id) if llamada.usuario_id else None,
        "agente": llamada.agente,
        "identificacion": llamada.identificacion or {},
        "contexto": llamada.contexto or {},
        "ivr": llamada.ivr or {},
        "transferencias": llamada.transferencias or [],
        "eventos": llamada.eventos or [],
        "grabacion_url": llamada.grabacion_url,
        "duracion_s": llamada.duracion_s,
        "espera_s": llamada.espera_s,
        "inicio_at": llamada.inicio_at.isoformat() if llamada.inicio_at else None,
        "fin_at": llamada.fin_at.isoformat() if llamada.fin_at else None,
        "actividad_id": str(llamada.actividad_id) if llamada.actividad_id else None,
        "registro_error": llamada.registro_error,
        "resultado_comercial": llamada.resultado_comercial,
        "nota": llamada.nota,
        "error": llamada.error,
        # Si «número erróneo» marcó el teléfono de la ficha, o por qué no.
        "telefono_marcado": telefono_marcado(llamada),
        "pantalla": pantalla,
    }
