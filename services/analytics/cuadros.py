"""Componentes, filtros, alertas y embebido de los cuadros de mando
(CRM-05.01.02.02, CRM-05.01.02.03, CRM-05.01.02.04, CRM-05.01.02.05,
CRM-05.01.02.06).

Un cuadro de mando es una colección de componentes que apuntan a informes. Lo que
decide si sirve no es el dibujo: es que **lo que enseña se pueda creer y se pueda
seguir hasta el registro**.

Cuatro decisiones:

**El catálogo de tipos es cerrado y cada tipo declara qué necesita.** Un KPI
necesita una métrica; un embudo, una serie ordenada; un mapa, un campo geográfico.
Sin esa declaración, un componente mal configurado se descubre al abrirlo delante
de alguien, y lo que se ve es un hueco sin explicación.

**Un filtro global es del cuadro, no de cada componente.** Si cada uno llevara el
suyo, cambiar el trimestre exigiría tocar ocho sitios y siempre quedaría uno sin
cambiar — y nadie se daría cuenta, porque un número plausible no se cuestiona.

**El drill-down llega hasta el registro, no hasta otra agregación.** Un cuadro del
que no se puede bajar al detalle obliga a rehacer la consulta a mano en otra
pantalla, y ahí ya no coinciden los números.

**Una alerta que se dispara siempre deja de leerse.** Por eso hay histéresis y
silencio mínimo: sin ellos, un indicador que baila alrededor del umbral manda
cuarenta avisos en una tarde y al día siguiente la regla está desactivada.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Qué necesita cada tipo de componente para poder pintarse (CRM-05.01.02.02).
# Cerrado a propósito: un tipo libre haría que el front tuviera que adivinar cómo
# dibujar algo que no conoce, y lo que dibujaría es un hueco.
TIPOS_COMPONENTE: dict[str, dict[str, Any]] = {
    "kpi": {
        "necesita": ("metrica",),
        "descripcion": "Una cifra grande con su comparación contra el periodo anterior",
    },
    "tabla": {"necesita": (), "descripcion": "Las filas tal cual, con su orden"},
    "grafico": {
        "necesita": ("dimension", "metrica"),
        "descripcion": "Barras, líneas o áreas: una dimensión contra una o más métricas",
    },
    "embudo": {
        "necesita": ("dimension", "metrica", "orden"),
        # El embudo exige ORDEN porque sus etapas no se ordenan solas: alfabético
        # daría «Cierre, Negociación, Propuesta» y el embudo saldría al revés.
        "descripcion": "Etapas en orden con su caída entre una y la siguiente",
    },
    "mapa": {
        "necesita": ("geografico", "metrica"),
        "descripcion": "Una métrica sobre un campo geográfico",
    },
    "gauge": {
        "necesita": ("metrica", "objetivo"),
        # Un gauge sin objetivo es un KPI con una aguja: la aguja solo significa
        # algo contra una meta.
        "descripcion": "Una métrica contra su objetivo",
    },
    "texto": {"necesita": (), "descripcion": "Una nota fija, para explicar el resto"},
}

# Cómo se compara un valor con su umbral.
COMPARACIONES = ("mayor", "mayor_igual", "menor", "menor_igual", "igual", "cambia_mas_de")


class SuscripcionCuadro(Base, TimestampMixin):
    """Quién quiere que le llegue un cuadro, y cada cuánto (CRM-05.01.02.05)."""

    __tablename__ = "suscripciones_cuadro"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # El cuadro de mando que se está embebiendo.
    cuadro_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, info={"referencia": "cuadro_mando"}
    )
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # diaria | semanal | mensual
    periodicidad: Mapped[str] = mapped_column(String(20), nullable=False, default="semanal")
    hora: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    proxima_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "cuadro_id", "usuario_id", name="uq_suscripcion_cuadro"),
    )


class AlertaUmbral(Base, TimestampMixin):
    """Avisar cuando una métrica cruza una línea (CRM-05.01.02.05)."""

    __tablename__ = "alertas_umbral"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    informe_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Qué se mira del resultado: una métrica del informe, o el número de filas.
    metrica: Mapped[str] = mapped_column(String(80), nullable=False, default="filas")
    comparacion: Mapped[str] = mapped_column(
        String(20), nullable=False, default="mayor", info={"opciones": COMPARACIONES}
    )
    umbral: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    # Margen para volver al verde. Sin él, un indicador que baila alrededor del
    # umbral manda cuarenta avisos en una tarde y al día siguiente la regla está
    # desactivada — que es la forma más común de perder una alerta buena.
    histeresis: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    # Tiempo mínimo entre dos avisos de la misma alerta.
    silencio_horas: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    destinatarios: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # verde | disparada
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="verde")
    ultimo_valor: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ultimo_aviso_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comprobada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "nombre", name="uq_alerta_nombre"),
        Index("ix_alertas_activas", "tenant_id", "activa", "estado"),
    )


class EnlaceEmbebido(Base, TimestampMixin, SoftDeleteMixin):
    """Un cuadro embebido fuera del CRM (CRM-05.01.02.06).

    Se guarda el **hash** del secreto y no el secreto: quien lea esta tabla —una
    copia de seguridad, un volcado de soporte— no puede firmar enlaces a los
    cuadros de nadie.
    """

    __tablename__ = "enlaces_embebidos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuadro_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, info={"referencia": "cuadro_mando"}
    )
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    hash_secreto: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Dominios desde los que se puede incrustar. Vacío **no** significa
    # «cualquiera»: significa que no se sirve, porque un cuadro embebible desde
    # cualquier sitio es un cuadro público.
    dominios: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Los datos se sirven con el ámbito de ESTE usuario, no del que mira. El
    # embebido no autentica a quien está delante de la pantalla ajena, así que se
    # fija a quién representa y se dice.
    actua_como_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    minutos_validez: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ultimo_uso_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    usos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_embebidos_cuadro", "tenant_id", "cuadro_id", "activo"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


# ── Componentes (CRM-05.01.02.02) ─────────────────────────────────────────


def catalogo_componentes() -> list[dict[str, Any]]:
    """Los tipos que el front sabe pintar, con lo que necesita cada uno.

    Se publica para que la pantalla de montaje ofrezca lo que existe en vez de
    una lista escrita a mano en el front: dos listas que tienen que coincidir
    acaban no coincidiendo, y la que se queda corta es siempre la del front.
    """
    return [
        {"tipo": tipo, "necesita": list(d["necesita"]), "descripcion": d["descripcion"]}
        for tipo, d in TIPOS_COMPONENTE.items()
    ]


def validar_componente(componente: dict[str, Any]) -> list[str]:
    """Comprueba que un componente tiene lo que su tipo necesita.

    Se valida al guardarlo y no al pintarlo: un componente mal configurado que
    solo falla al abrirse se descubre delante de alguien, y lo que se ve es un
    hueco sin explicación.
    """
    tipo = str(componente.get("tipo") or "")
    if tipo not in TIPOS_COMPONENTE:
        raise ErrorValidacion(
            f"Tipo de componente «{tipo}» no válido.",
            error_code="cuadro.tipo_no_valido",
            detalle={"validos": sorted(TIPOS_COMPONENTE)},
        )
    if not componente.get("informe") and tipo != "texto":
        raise ErrorValidacion(
            f"Un componente de tipo «{tipo}» necesita un informe del que sacar los datos.",
            error_code="cuadro.componente_sin_informe",
        )

    faltan = [pieza for pieza in TIPOS_COMPONENTE[tipo]["necesita"] if not componente.get(pieza)]
    if faltan:
        raise ErrorValidacion(
            f"Un «{tipo}» necesita {', '.join(faltan)}.",
            error_code="cuadro.componente_incompleto",
            detalle={"faltan": faltan, "tipo": tipo},
        )

    avisos: list[str] = []
    if tipo == "kpi" and not componente.get("comparar_con"):
        avisos.append("El KPI no compara con nada: una cifra sola no dice si va bien o mal.")
    if tipo == "tabla" and not componente.get("limite"):
        avisos.append(
            "La tabla no tiene límite: si el informe devuelve miles de filas, el "
            "cuadro tardará en abrirse."
        )
    return avisos


def validar_componentes(componentes: list[dict[str, Any]]) -> list[str]:
    avisos: list[str] = []
    for i, componente in enumerate(componentes):
        for aviso in validar_componente(componente):
            avisos.append(f"componente {i + 1}: {aviso}")
    return avisos


# ── Filtros globales y drill-down (CRM-05.01.02.03) ───────────────────────


def aplicar_filtros_globales(
    componentes: list[dict[str, Any]], filtros: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Pasa los filtros del cuadro a cada componente.

    El filtro es **del cuadro**, no de cada componente: si cada uno llevara el
    suyo, cambiar el trimestre exigiría tocar ocho sitios y siempre quedaría uno
    sin cambiar — y nadie se daría cuenta, porque un número plausible no se
    cuestiona.

    Un componente puede **declararse inmune** (`ignora_filtros`). Hace falta para
    los que enseñan el contexto —«total del año pasado»— que dejarían de decir lo
    que dicen si el filtro del trimestre les llegara. Se declara, no se adivina.
    """
    salida: list[dict[str, Any]] = []
    for componente in componentes:
        copia = dict(componente)
        if componente.get("ignora_filtros"):
            copia["filtros_aplicados"] = []
        else:
            copia["filtros_aplicados"] = [dict(f) for f in filtros]
        salida.append(copia)
    return salida


def enlace_al_detalle(
    componente: dict[str, Any], punto: dict[str, Any], filtros: list[dict[str, Any]]
) -> dict[str, Any]:
    """A qué lista de registros lleva pulsar un punto del gráfico.

    Baja **hasta el registro**, no hasta otra agregación. Un cuadro del que no se
    puede bajar al detalle obliga a rehacer la consulta a mano en otra pantalla, y
    ahí ya no coinciden los números — y entonces se deja de creer al cuadro.

    Los filtros que se llevan son los del cuadro **más el del punto pulsado**: sin
    lo segundo, pulsar en la barra de marzo llevaría a la lista del año entero.
    """
    informe = str(componente.get("informe") or "")
    if not informe:
        raise ErrorValidacion(
            "Ese componente no sale de un informe, así que no hay detalle al que bajar.",
            error_code="cuadro.sin_detalle",
        )
    del_punto = [
        {"campo": str(k), "operador": "=", "valor": v}
        for k, v in (punto or {}).items()
        if not str(k).startswith("_")
    ]
    return {
        "informe": informe,
        "filtros": [*(filtros or []), *del_punto],
        # Se dice de dónde sale cada filtro: quien mire la lista tiene que poder
        # saber por qué está viendo esas filas y no otras.
        "origen_filtros": {
            "del_cuadro": len(filtros or []),
            "del_punto": len(del_punto),
        },
    }


# ── Alertas por umbral (CRM-05.01.02.05) ──────────────────────────────────


def _cruza(valor: Decimal, comparacion: str, umbral: Decimal, anterior: Decimal | None) -> bool:
    if comparacion == "mayor":
        return valor > umbral
    if comparacion == "mayor_igual":
        return valor >= umbral
    if comparacion == "menor":
        return valor < umbral
    if comparacion == "menor_igual":
        return valor <= umbral
    if comparacion == "igual":
        return valor == umbral
    if comparacion == "cambia_mas_de":
        # Anomalía por salto: sin valor anterior no hay salto que medir, y decir
        # que sí lo hay dispararía la alerta la primera vez siempre.
        if anterior is None:
            return False
        return abs(valor - anterior) > umbral
    return False


def _vuelve_al_verde(
    valor: Decimal, comparacion: str, umbral: Decimal, histeresis: Decimal
) -> bool:
    """Si ya se puede dar por resuelta, con su margen.

    El margen es lo que evita el baile: una alerta que se apaga en el mismo punto
    en que se enciende manda un aviso por cada oscilación.
    """
    if comparacion in ("mayor", "mayor_igual"):
        return valor < umbral - histeresis
    if comparacion in ("menor", "menor_igual"):
        return valor > umbral + histeresis
    if comparacion == "igual":
        return valor != umbral
    return True


def crear_alerta(
    uow: UnidadDeTrabajo,
    *,
    nombre: str,
    informe_id: UUID,
    metrica: str = "filas",
    comparacion: str = "mayor",
    umbral: Decimal = Decimal(0),
    histeresis: Decimal = Decimal(0),
    silencio_horas: int = 12,
    destinatarios: list[str] | None = None,
) -> AlertaUmbral:
    if comparacion not in COMPARACIONES:
        raise ErrorValidacion(
            f"Comparación «{comparacion}» no válida.",
            error_code="alerta.comparacion_no_valida",
            detalle={"validas": list(COMPARACIONES)},
        )
    if not destinatarios:
        raise ErrorValidacion(
            "Una alerta sin destinatarios no avisa a nadie.",
            error_code="alerta.sin_destinatarios",
        )
    fila = AlertaUmbral(
        tenant_id=uow.tenant_id,
        nombre=nombre,
        informe_id=informe_id,
        metrica=metrica,
        comparacion=comparacion,
        umbral=umbral,
        histeresis=histeresis,
        silencio_horas=silencio_horas,
        destinatarios=list(destinatarios),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _valor_de(salida: dict[str, Any], metrica: str) -> Decimal | None:
    if metrica == "filas":
        return Decimal(salida.get("cuantas", 0))
    total = Decimal(0)
    visto = False
    for fila in salida.get("filas") or []:
        valor = fila.get(metrica)
        if isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool):
            total += Decimal(str(valor))
            visto = True
    return total if visto else None


def comprobar_alertas(uow: UnidadDeTrabajo, tenant_id: UUID) -> dict[str, Any]:
    """Ejecuta los informes de las alertas activas y avisa de lo que cruza.

    **Una alerta que se dispara siempre deja de leerse.** Por eso hay histéresis
    —un margen para volver al verde— y silencio mínimo entre avisos: sin ellos, un
    indicador que baila alrededor del umbral manda cuarenta correos en una tarde y
    al día siguiente la regla está desactivada.

    Cuando el informe **no se puede ejecutar**, la alerta no se da por verde: se
    cuenta aparte. Dar por bueno lo que no se ha podido medir es la forma más
    silenciosa de perder una alerta.
    """
    from services.analytics.informes import ejecutar

    ahora = _ahora()
    alertas = (
        uow.db.execute(
            select(AlertaUmbral).where(
                AlertaUmbral.tenant_id == tenant_id, AlertaUmbral.activa.is_(True)
            )
        )
        .scalars()
        .all()
    )
    disparadas: list[dict[str, Any]] = []
    resueltas: list[str] = []
    silenciadas: list[str] = []
    no_medibles: list[dict[str, Any]] = []

    for alerta in alertas:
        try:
            salida = ejecutar(uow, alerta.informe_id, es_admin=True, origen="programada")
        except Exception as exc:  # noqa: BLE001 — el motor analítico es externo
            no_medibles.append({"alerta": alerta.nombre, "error": str(exc)[:200]})
            continue

        valor = _valor_de(salida, alerta.metrica)
        if valor is None:
            no_medibles.append(
                {
                    "alerta": alerta.nombre,
                    "error": f"El informe no devuelve la métrica «{alerta.metrica}».",
                }
            )
            continue

        anterior = Decimal(alerta.ultimo_valor) if alerta.ultimo_valor is not None else None
        alerta.comprobada_at = ahora
        cruza = _cruza(valor, alerta.comparacion, Decimal(alerta.umbral), anterior)
        alerta.ultimo_valor = valor

        if cruza and alerta.estado == "verde":
            ultimo = _con_tz(alerta.ultimo_aviso_at)
            if ultimo and (ahora - ultimo) < timedelta(hours=alerta.silencio_horas):
                silenciadas.append(alerta.nombre)
                continue
            alerta.estado = "disparada"
            alerta.ultimo_aviso_at = ahora
            disparadas.append({"alerta": alerta.nombre, "valor": str(valor)})
            uow.emitir(
                "dashboard.alert.fired",
                subject=("alerta", alerta.id),
                data={
                    "alerta_id": str(alerta.id),
                    "nombre": alerta.nombre,
                    "valor": str(valor),
                    "umbral": str(alerta.umbral),
                    "destinatarios": list(alerta.destinatarios or []),
                },
            )
        elif alerta.estado == "disparada" and _vuelve_al_verde(
            valor, alerta.comparacion, Decimal(alerta.umbral), Decimal(alerta.histeresis)
        ):
            alerta.estado = "verde"
            resueltas.append(alerta.nombre)
            uow.emitir(
                "dashboard.alert.cleared",
                subject=("alerta", alerta.id),
                data={
                    "alerta_id": str(alerta.id),
                    "nombre": alerta.nombre,
                    "valor": str(valor),
                },
            )

    uow.db.flush()
    return {
        "revisadas": len(alertas),
        "disparadas": disparadas,
        "resueltas": resueltas,
        "silenciadas": silenciadas,
        # Lo que no se ha podido medir sale aparte y NO cuenta como verde: dar
        # por bueno lo que no se ha medido es la forma más silenciosa de perder
        # una alerta.
        "no_medibles": no_medibles,
        "medible": bool(alertas),
    }


# ── Embebido (CRM-05.01.02.06) ────────────────────────────────────────────


def crear_embebido(
    uow: UnidadDeTrabajo,
    *,
    cuadro_id: UUID,
    actua_como_id: UUID,
    dominios: list[str],
    nombre: str = "",
    minutos_validez: int = 10,
) -> tuple[EnlaceEmbebido, str]:
    """Habilita un cuadro para incrustarlo fuera, y devuelve su secreto una vez.

    **Sin dominios no se crea.** Vacío no significa «desde cualquier sitio»:
    significa que no se sirve, porque un cuadro embebible desde cualquier parte es
    un cuadro público, y lo normal es que el cuadro traiga cifras de negocio.

    El enlace **actúa como una persona concreta** y se dice cuál. El embebido no
    autentica a quien está delante de la pantalla ajena, así que fijar a quién
    representa es lo que impide que un cuadro incrustado enseñe más de lo que ve
    quien lo montó.
    """
    if not dominios:
        raise ErrorValidacion(
            "Hace falta decir desde qué dominios se puede incrustar: un cuadro "
            "embebible desde cualquier sitio es un cuadro público.",
            error_code="cuadro.embebido_sin_dominios",
        )
    secreto = secrets.token_urlsafe(32)
    fila = EnlaceEmbebido(
        tenant_id=uow.tenant_id,
        cuadro_id=cuadro_id,
        nombre=nombre,
        hash_secreto=_hash(secreto),
        dominios=[d.strip().lower() for d in dominios if d.strip()],
        actua_como_id=actua_como_id,
        minutos_validez=minutos_validez,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, secreto


def resolver_embebido(
    db: Session, tenant_id: UUID, secreto: str, *, origen: str = ""
) -> EnlaceEmbebido:
    """Comprueba el secreto y el dominio desde el que se incrusta.

    Un secreto inexistente, desactivado o de otro dominio dan **el mismo error**:
    distinguirlos le diría a quien prueba si ese cuadro existe y desde dónde se
    sirve.
    """
    invalido = NoAutenticado(
        "Ese cuadro no se puede mostrar aquí.",
        error_code="cuadro.embebido_invalido",
    )
    fila = db.execute(
        select(EnlaceEmbebido).where(
            EnlaceEmbebido.tenant_id == tenant_id,
            EnlaceEmbebido.hash_secreto == _hash(secreto),
        )
    ).scalar_one_or_none()
    if fila is None or not fila.activo:
        raise invalido

    if origen:
        dominio = origen.replace("https://", "").replace("http://", "").split("/")[0].lower()
        permitidos = [str(d) for d in (fila.dominios or [])]
        # Coincidencia exacta o de subdominio, nunca «contiene»: con `contiene`,
        # `micrm.com.ataque.net` pasaría por `micrm.com`.
        if not any(dominio == d or dominio.endswith("." + d) for d in permitidos):
            logger.warning(
                "cuadro.embebido_origen_rechazado", origen=dominio, cuadro=str(fila.cuadro_id)
            )
            raise invalido

    fila.usos += 1
    fila.ultimo_uso_at = _ahora()
    db.flush()
    return fila


def revocar_embebido(uow: UnidadDeTrabajo, enlace_id: UUID) -> dict[str, Any]:
    """Desactiva un enlace embebido. No se borra: su uso queda en el histórico."""
    fila = uow.db.get(EnlaceEmbebido, enlace_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Ese enlace no existe", error_code="cuadro.embebido_no_encontrado")
    if not fila.activo:
        raise Conflicto("Ese enlace ya estaba revocado", error_code="cuadro.embebido_revocado")
    fila.activo = False
    uow.db.flush()
    return {"enlace_id": str(fila.id), "usos": fila.usos}


# ── Suscripción (CRM-05.01.02.05) ─────────────────────────────────────────


def suscribirse(
    uow: UnidadDeTrabajo,
    *,
    cuadro_id: UUID,
    usuario_id: UUID,
    periodicidad: str = "semanal",
    hora: int = 8,
) -> SuscripcionCuadro:
    """Pide que el cuadro llegue solo.

    Uno se suscribe **a sí mismo**: suscribir a otro convierte un cuadro en correo
    no deseado que el receptor no sabe cómo parar, y lo que hace es marcarlo como
    basura — y con él, todo lo que mande el CRM.
    """
    ya = uow.db.execute(
        select(SuscripcionCuadro).where(
            SuscripcionCuadro.tenant_id == uow.tenant_id,
            SuscripcionCuadro.cuadro_id == cuadro_id,
            SuscripcionCuadro.usuario_id == usuario_id,
        )
    ).scalar_one_or_none()
    if ya is not None:
        ya.activa = True
        ya.periodicidad = periodicidad
        ya.hora = hora
        uow.db.flush()
        return ya
    fila = SuscripcionCuadro(
        tenant_id=uow.tenant_id,
        cuadro_id=cuadro_id,
        usuario_id=usuario_id,
        periodicidad=periodicidad,
        hora=hora,
        proxima_at=_ahora() + timedelta(days=1),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila
