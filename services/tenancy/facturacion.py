"""El consumo, exportable a facturación (CRM-00.01.06.07).

El consumo medido existía —cada servicio cuenta lo suyo y el panel lo suma— y
no salía de la pantalla: para cobrar por uso había que copiar los números a
mano a la herramienta de facturación cada mes. Medido el 09-11-2026.

Aquí se toma un **corte**: el consumo de un tenant en un periodo, fila a fila
—periodo, módulo, métrica, cantidad, unidad, tope—, en una forma neutra que
cualquier sistema de cobro entiende (JSON o CSV), y se manda al sistema de
facturación del cliente como un webhook de la casa: firmado con HMAC y por el
guard de SSRF. Nada de un conector por proveedor de facturación.

Tres decisiones:

**Se compone preguntando a cada servicio**, igual que el panel del gateway, y
con la misma regla: el que no contesta NO es un cero. Un corte al que le falta
un módulo se guarda con `completo = false` y la lista de los que faltan; mandar
a cobrar un cero que no se ha medido es cobrar de menos sin que nadie lo sepa.

**El corte de un periodo es el último que se tomó dentro de él.** La medición
es del estado actual (filas que hay, correos de este mes), así que el consumo
de octubre sólo se puede tomar en octubre. La tarea periódica rehace el corte
del periodo en curso en cada vuelta y, cuando el periodo cierra, manda el
último. Lo que pueda faltar del final del mes es, como mucho, un intervalo de
la tarea, y eso se dice en el manual.

**El estado del envío se guarda y se ve**: pendiente, enviado (con el código
que contestó), fallido (con el porqué y los intentos) o sin destino. Un envío
que falla en silencio es una factura que no sale y nadie lo sabe hasta que el
cliente pregunta por qué no le han cobrado.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Las columnas del formato neutro, en este orden. Es el contrato con el sistema
# de facturación: cambiarlas rompe al receptor, así que van en un sitio.
COLUMNAS = ("periodo", "tenant", "modulo", "metrica", "cantidad", "unidad", "tope")
ESTADOS_ENVIO = ("pendiente", "enviado", "fallido", "sin_destino", "abierto")


class CorteConsumo(Base):
    """El consumo de un tenant en un periodo, tal como se manda a cobrar."""

    __tablename__ = "cortes_consumo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    periodo: Mapped[str] = mapped_column(String(20), nullable=False)
    # `manual` (bajo demanda) o `programado` (la tarea).
    origen: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    filas: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Lo que no se pudo leer: un corte incompleto se dice, no se rellena.
    completo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    no_leidos: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # `abierto` mientras su periodo está en curso (la tarea lo rehace), y
    # luego pendiente | enviado | fallido | sin_destino.
    estado_envio: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultimo_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    respuesta_codigo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enviado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pedido_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    tomado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_cortes_consumo_periodo", "tenant_id", "periodo", "origen"),)


# ── Medir ─────────────────────────────────────────────────────────────────


def unidad_de(metrica: str) -> str:
    """La unidad, de cómo se llama la métrica. Sin sufijo, se cuentan unidades.

    Va por el nombre porque es donde ya la declara quien registra el medidor
    (`almacenamiento_mb`): una tabla aparte de unidades se desincronizaría con
    el primer medidor nuevo.
    """
    for sufijo, unidad in (("_mb", "MB"), ("_gb", "GB"), ("_kb", "KB"), ("_s", "s")):
        if metrica.endswith(sufijo):
            return unidad
    return "unidades"


def identidad_de_lectura() -> UUID:
    """Quién firma las lecturas de consumo que no pide una persona.

    Sin identidad, la ruta de destino contesta 401 —una firma sin usuario es
    un anónimo—. Medido el 09-11-2026 en la pila: el corte periódico y lo que
    la matriz ve de sus hijas salían con los trece módulos «sin leer». Es fija
    y derivada, no una cuenta: no tiene permisos (la llamada va sin ninguno) y
    en el rastro se reconoce como la lectura de consumo del tenant.
    """
    import uuid

    return uuid.uuid5(uuid.NAMESPACE_OID, "contecrm:tenancy:lectura-de-consumo")


def consumo_compuesto(tenant_id: UUID, *, principal_id: UUID | None) -> dict[str, Any]:
    """El consumo de un tenant en todos los módulos, preguntando a cada uno.

    Firma la llamada con la identidad de ESE tenant y sin permisos: la ruta
    `/estado/consumo` sólo pide sesión y devuelve cifras, y no se puede hacer
    nada más con esa firma. El que no contesta va a `no_leidos`.
    """
    import httpx
    from crmcore.config import get_settings
    from crmcore.http.interno import cabeceras_de
    from crmcore.rutas_de_api import cargar_destinos

    s = get_settings()
    destinos = cargar_destinos(s.rutas_servicios)
    cabeceras = cabeceras_de(
        tenant_id=tenant_id, principal_id=principal_id or identidad_de_lectura(), permisos=[]
    )
    filas: list[dict[str, Any]] = []
    no_leidos: list[str] = []
    for nombre in sorted(destinos):
        if nombre == "gateway":
            continue
        try:
            r = httpx.get(
                f"{destinos[nombre].url_base}/api/v1/estado/consumo",
                headers=cabeceras,
                timeout=float(s.http_interno_timeout_s),
            )
            if r.status_code != 200:
                raise RuntimeError(f"respondió {r.status_code}")
            metricas = r.json().get("metricas") or []
        except Exception as exc:  # noqa: BLE001 — un servicio caído es un dato, no un error
            logger.warning("facturacion.modulo_no_leido", servicio=nombre, error=str(exc)[:200])
            no_leidos.append(nombre)
            continue
        for m in metricas:
            if not m.get("legible", True):
                no_leidos.append(f"{nombre}/{m.get('metrica')}")
                continue
            filas.append(
                {
                    "periodo": str(m.get("periodo") or ""),
                    "modulo": nombre,
                    "metrica": str(m["metrica"]),
                    "cantidad": int(m.get("consumido") or 0),
                    "unidad": unidad_de(str(m["metrica"])),
                    # Sin tope es `None`, no cero: cero se leería como «no
                    # tiene derecho a nada».
                    "tope": None if m.get("sin_limite") else int(m.get("limite") or 0),
                }
            )
    return {"filas": filas, "no_leidos": sorted(set(no_leidos))}


# ── Cortes ────────────────────────────────────────────────────────────────


def tomar_corte(
    db: Session,
    tenant_id: UUID,
    *,
    origen: str = "manual",
    pedido_por: UUID | None = None,
    medido: dict[str, Any] | None = None,
) -> CorteConsumo:
    """Toma el corte del periodo en curso y lo guarda.

    `medido` es para las pruebas y para la tarea, que ya lo trae; sin él se
    compone preguntando a los módulos.
    """
    from crmcore.cuotas import periodo_actual

    from services.tenancy.modelos import Tenant

    datos = medido if medido is not None else consumo_compuesto(tenant_id, principal_id=pedido_por)
    periodo = periodo_actual(db)
    tenant = db.get(Tenant, tenant_id)
    slug = tenant.slug if tenant else str(tenant_id)
    filas = [
        {**f, "periodo": f.get("periodo") or periodo, "tenant": slug}
        for f in datos.get("filas") or []
    ]
    corte = CorteConsumo(
        tenant_id=tenant_id,
        periodo=periodo,
        origen=origen,
        filas=filas,
        completo=not datos.get("no_leidos"),
        no_leidos=list(datos.get("no_leidos") or []),
        estado_envio="abierto" if origen == "programado" else "pendiente",
        pedido_por=pedido_por,
    )
    db.add(corte)
    db.flush()
    return corte


def corte(db: Session, tenant_id: UUID, corte_id: UUID) -> CorteConsumo:
    fila = db.get(CorteConsumo, corte_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("Ese corte no existe", error_code="facturacion.corte_no_existe")
    return fila


def listar(db: Session, tenant_id: UUID, *, limite: int = 50) -> list[dict[str, Any]]:
    filas = (
        db.execute(
            select(CorteConsumo)
            .where(CorteConsumo.tenant_id == tenant_id)
            .order_by(CorteConsumo.tomado_at.desc(), CorteConsumo.id.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return [a_dict(f) for f in filas]


def a_dict(f: CorteConsumo) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "periodo": f.periodo,
        "origen": f.origen,
        "filas": len(f.filas or []),
        "completo": f.completo,
        "no_leidos": list(f.no_leidos or []),
        "estado_envio": f.estado_envio,
        "intentos": f.intentos,
        "ultimo_error": f.ultimo_error,
        "respuesta_codigo": f.respuesta_codigo,
        "enviado_at": f.enviado_at.isoformat() if f.enviado_at else None,
        "tomado_at": f.tomado_at.isoformat() if f.tomado_at else None,
    }


def como_csv(filas: list[dict[str, Any]]) -> str:
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=list(COLUMNAS), extrasaction="ignore")
    escritor.writeheader()
    for f in filas:
        escritor.writerow({c: ("" if f.get(c) is None else f.get(c)) for c in COLUMNAS})
    return salida.getvalue()


def como_json(c: CorteConsumo) -> dict[str, Any]:
    """El corte en JSON neutro: la cabecera y las filas, con las mismas columnas."""
    return {
        "periodo": c.periodo,
        "tomado_at": c.tomado_at.isoformat() if c.tomado_at else None,
        "completo": c.completo,
        "no_leidos": list(c.no_leidos or []),
        "columnas": list(COLUMNAS),
        "filas": [{k: f.get(k) for k in COLUMNAS} for f in c.filas or []],
    }


# ── Enviar ────────────────────────────────────────────────────────────────


def enviar(db: Session, c: CorteConsumo) -> dict[str, Any]:
    """Manda el corte al sistema de facturación configurado y anota cómo fue.

    Por el mismo camino que un webhook de la casa: `cliente_seguro` (guard de
    SSRF, que la URL la escribe el tenant) y la firma HMAC, para que el
    receptor sepa que viene de aquí y no es uno viejo reenviado.
    """
    from crmcore.audit.chain import registrar
    from crmcore.config import get_settings
    from crmcore.red import cliente_seguro
    from crmcore.runtime import settings as rt
    from crmcore.security.firma import cabeceras_firmadas

    url = str(rt.efectivo("facturacion_destino_url", db) or "").strip()
    if not url:
        c.estado_envio = "sin_destino"
        c.ultimo_error = "No hay sistema de facturación configurado (facturacion_destino_url)"
        db.flush()
        return a_dict(c)

    formato = str(rt.efectivo("facturacion_formato_envio", db) or "json")
    if formato == "csv":
        cuerpo = como_csv(c.filas or []).encode()
        tipo = "text/csv; charset=utf-8"
    else:
        cuerpo = json.dumps(como_json(c), ensure_ascii=False).encode()
        tipo = "application/json"
    s = get_settings()
    extra = rt.efectivo("facturacion_destino_cabeceras", db) or {}
    cabeceras = {
        "content-type": tipo,
        **{str(k): str(v) for k, v in dict(extra).items()},
        **cabeceras_firmadas(cuerpo, s.secret_key.get_secret_value()),
        # Para que el receptor deduplique: el mismo corte reenviado es el mismo.
        "x-crm-corte": str(c.id),
    }
    c.intentos += 1
    try:
        with cliente_seguro(timeout=float(s.http_externo_timeout_s)) as cli:
            r = cli.post(url, content=cuerpo, headers=cabeceras)
        c.respuesta_codigo = r.status_code
        if 200 <= r.status_code < 300:
            c.estado_envio = "enviado"
            c.enviado_at = datetime.now(timezone.utc)
            c.ultimo_error = ""
        else:
            c.estado_envio = "fallido"
            c.ultimo_error = f"HTTP {r.status_code}: {r.text[:300]}"
    except Exception as exc:  # noqa: BLE001 — el fallo se guarda en el corte
        c.estado_envio = "fallido"
        c.ultimo_error = f"{type(exc).__name__}: {exc}"[:500]
    registrar(
        db,
        accion="consumo.corte_enviado" if c.estado_envio == "enviado" else "consumo.corte_fallido",
        objeto="corte_consumo",
        objeto_id=str(c.id),
        datos={"periodo": c.periodo, "codigo": c.respuesta_codigo, "intentos": c.intentos},
        tenant_id=c.tenant_id,
    )
    db.flush()
    return a_dict(c)


def descargar(c: CorteConsumo, formato: str) -> tuple[str, str]:
    """(contenido, tipo) del corte en el formato pedido."""
    if formato == "csv":
        return como_csv(c.filas or []), "text/csv; charset=utf-8"
    if formato == "json":
        return json.dumps(como_json(c), ensure_ascii=False, indent=2), "application/json"
    raise ErrorValidacion(
        "Formato no admitido: json o csv", error_code="facturacion.formato_no_admitido"
    )


# ── La tarea periódica ────────────────────────────────────────────────────


def barrer(db: Session, tenant_id: UUID, *, medido: dict[str, Any] | None = None) -> dict[str, Any]:
    """Una vuelta de la tarea para un tenant.

    Rehace el corte abierto del periodo en curso y manda los de periodos ya
    cerrados que sigan sin mandar (o fallidos con intentos por gastar). Si la
    exportación periódica está apagada para este tenant, no hace nada.
    """
    from crmcore.cuotas import periodo_actual
    from crmcore.runtime import settings as rt

    if not rt.efectivo("facturacion_exportar_periodicamente", db):
        return {"tomados": 0, "enviados": 0, "apagado": True}
    periodo = periodo_actual(db)
    # El corte abierto de este periodo se sustituye: el que vale es el último.
    for viejo in db.execute(
        select(CorteConsumo).where(
            CorteConsumo.tenant_id == tenant_id,
            CorteConsumo.origen == "programado",
            CorteConsumo.periodo == periodo,
            CorteConsumo.estado_envio == "abierto",
        )
    ).scalars():
        db.delete(viejo)
    db.flush()
    tomar_corte(db, tenant_id, origen="programado", medido=medido)

    maximo = int(rt.efectivo("facturacion_max_intentos", db) or 1)
    enviados = 0
    for c in db.execute(
        select(CorteConsumo).where(
            CorteConsumo.tenant_id == tenant_id,
            CorteConsumo.origen == "programado",
            CorteConsumo.periodo < periodo,
            CorteConsumo.estado_envio.in_(("abierto", "fallido")),
            CorteConsumo.intentos < maximo,
        )
    ).scalars():
        c.estado_envio = "pendiente"
        if enviar(db, c)["estado_envio"] == "enviado":
            enviados += 1
    return {"tomados": 1, "enviados": enviados, "apagado": False}
