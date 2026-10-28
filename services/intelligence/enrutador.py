"""Qué modelo atiende a quién, dónde y con qué límite
(CRM-05.02.02.10, CRM-05.02.02.09).

La primera pregunta de cualquier comité de compras sobre IA en un CRM no es qué
sabe hacer: es **dónde se procesan mis datos y quién los usa después**. Y la
respuesta no puede ser «depende del proveedor que tengamos configurado esta
semana».

De ahí las decisiones de este módulo:

**El modelo se elige por tenant, no por instalación.** Una empresa exige que todo
se quede en la UE, otra tiene su propio modelo en su infraestructura y una tercera
solo quiere el más barato. Los tres son el mismo producto con configuración
distinta, y con un modelo fijo en el código el primero se pierde.

**La región es una condición, no una preferencia.** Si un tenant declara que sus
datos no salen de la UE y el modelo elegido está fuera, **no se llama**. Llamar
igual y anotarlo en una traza es contarle después a alguien que sus datos ya
salieron.

**El opt-out de entrenamiento se guarda y se manda en cada llamada.** No basta con
haberlo firmado en un contrato: tiene que viajar con la petición, porque la
garantía que se le da al cliente es técnica y no comercial. Y si el proveedor
configurado no lo admite, **se dice y no se llama**.

**Sin presupuesto no hay llamada.** Un modelo sin tope es una factura que llega a
final de mes y que nadie autorizó; y el tope se comprueba **antes**, porque
comprobarlo después es descubrir que ya se gastó.

El proveedor se declara con su dirección y su formato: aquí no hay código por
casa. Lo que cambia entre dos despliegues es la configuración.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.events.dominio import AI_BUDGET_EXHAUSTED
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from crmcore.regiones import REGIONES as REGIONES_DE_DATOS
from crmcore.regiones import REGIONES_DE_PROVEEDOR
from sqlalchemy import (
    Boolean,
    Date,
    Index,
    Integer,
    Numeric,
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

from services.intelligence.dialectos import DIALECTOS, exigir_dialecto

logger = get_logger(__name__)

CENTIMO = Decimal("0.0001")

# Para qué sirve cada modelo. No es decorativo: el que redacta y el que extrae
# datos estructurados no son el mismo, y elegir por «el mejor» acaba usando el
# caro para todo.
USOS = (
    "redaccion",
    "resumen",
    "extraccion",
    "traduccion",
    "consulta",
    "embeddings",
    "clasificacion",
)

# Dónde se procesa. Dos listas y no una, porque no es la misma pregunta:
# `REGIONES` es dónde puede quedarse el dato de un tenant —la misma que firma su
# residencia, de `crmcore`—, y `REGIONES_DE_PROVEEDOR` es ésa más «otra», que es
# lo que se dice de un proveedor del que no consta dónde está. Admitir «otra»
# como región de un tenant era prometer que el dato no sale de un sitio que no
# se sabe cuál es.
REGIONES = REGIONES_DE_DATOS


class ProveedorIA(Base, TimestampMixin, SoftDeleteMixin):
    """Un sitio al que se le pueden mandar peticiones de IA (CRM-05.02.02.10).

    **Cada tenant declara los suyos**, y `tenant_id` no admite nulos: un catálogo
    común con tenant nulo quedaría fuera de la RLS, que es la garantía que
    sostiene todo el aislamiento. Lo que distingue el modelo del cliente del que
    contrata el proveedor del CRM es `propio`, y no la ausencia de tenant.
    """

    __tablename__ = "proveedores_ia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # El modelo del propio cliente, en su infraestructura. Gana siempre que
    # exista: es su casa, y sus datos no se mueven de ella.
    propio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # La dirección y el formato del protocolo. Sin código por casa: lo que cambia
    # entre dos proveedores es esto.
    base_url: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    formato: Mapped[str] = mapped_column(
        String(40), nullable=False, default="openai_chat", info={"opciones": DIALECTOS}
    )
    region: Mapped[str] = mapped_column(
        String(20), nullable=False, default="otra", info={"opciones": REGIONES_DE_PROVEEDOR}
    )
    # Si el proveedor admite pedir que no se entrene con lo enviado. Cuando no,
    # un tenant con opt-out **no puede usarlo**, y eso se comprueba antes de
    # llamar, no después.
    admite_opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Coste declarado por millón de tokens. Declarado y no medido: lo cobra el
    # proveedor y aquí solo se usa para poder avisar antes de gastarlo.
    coste_entrada_millon: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    coste_salida_millon: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    modelos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_proveedor_ia"),
        Index("ix_proveedores_ia", "activo", "region"),
    )


class PoliticaIA(Base, TimestampMixin):
    """Lo que un tenant admite y lo que no (CRM-05.02.02.09, .10)."""

    __tablename__ = "politicas_ia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Dónde pueden procesarse sus datos. Vacío = sin restricción declarada, que
    # **no** es lo mismo que «en cualquier sitio»: se anota y se puede exigir.
    regiones_admitidas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Exigir que el proveedor garantice no entrenar con lo enviado. Encendido por
    # defecto: es lo que un cliente asume sin preguntarlo, y descubrir que no era
    # así se descubre tarde y mal.
    exigir_opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Preferencias por uso: {uso: clave_proveedor}. El que redacta y el que
    # extrae no tienen por qué ser el mismo.
    preferencias: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    presupuesto_mes: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Interruptor por tenant (CRM-05.02.03.04). Apagarlo corta toda la IA de ese
    # cliente sin tocar nada más.
    ia_activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    motivo_apagado: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_politica_ia"),
        Index("ix_politicas_ia", "tenant_id"),
    )


class GastoIA(Base):
    """Lo gastado por tenant y día, para poder cortar antes de la factura."""

    __tablename__ = "gasto_ia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    dia: Mapped[date] = mapped_column(Date, nullable=False)
    proveedor: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    tokens_entrada: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_salida: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coste: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    llamadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("tenant_id", "dia", "proveedor", name="uq_gasto_ia_dia"),
        Index("ix_gasto_ia", "tenant_id", "dia"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hoy(db: Any = None) -> date:
    """El día de hoy **donde está el cliente**, si hay sesión con la que saberlo.

    Sin sesión cae a UTC, que es lo que hacía antes: no empeora nada y deja
    claro dónde falta el dato. Quien la tenga a mano está obligado a pasarla —
    hay un gate que lo mira—, porque entre medianoche y las dos de la mañana en
    Madrid la respuesta sin sesión es **la de ayer**.
    """
    from crmcore.fechas import hoy as _hoy_del_cliente

    return _hoy_del_cliente(db)


def registrar_proveedor(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    base_url: str,
    region: str,
    nombre: str = "",
    formato: str = "openai_chat",
    admite_opt_out: bool = False,
    modelos: list[dict[str, Any]] | None = None,
    coste_entrada_millon: Decimal = Decimal(0),
    coste_salida_millon: Decimal = Decimal(0),
    config: dict[str, Any] | None = None,
    solo_este_tenant: bool = False,
) -> tuple[ProveedorIA, list[str]]:
    """Declara un proveedor de IA."""
    if region not in REGIONES_DE_PROVEEDOR:
        raise ErrorValidacion(
            f"Región «{region}» no reconocida.",
            error_code="ia.region_no_valida",
            detalle={"validas": list(REGIONES_DE_PROVEEDOR)},
        )
    # El formato se comprueba igual que la región, y no lo hacía nadie: era
    # texto libre, así que «openai» o «Anthropic» se guardaban perfectamente y
    # la llamada salía en el dialecto equivocado meses después.
    exigir_dialecto(formato)
    if not base_url.strip():
        raise ErrorValidacion(
            "Un proveedor sin dirección no se puede llamar.", error_code="ia.sin_url"
        )
    avisos: list[str] = []
    if not admite_opt_out:
        avisos.append(
            "Este proveedor no garantiza el opt-out de entrenamiento: los tenants "
            "que lo exijan no podrán usarlo, y es lo que casi todos exigen."
        )
    if coste_entrada_millon == 0 and coste_salida_millon == 0:
        avisos.append(
            "Sin coste declarado no se puede avisar antes de gastar: el presupuesto "
            "no cortará nada."
        )
    fila = ProveedorIA(
        tenant_id=uow.tenant_id,
        propio=solo_este_tenant,
        clave=clave.strip(),
        nombre=nombre.strip() or clave.strip(),
        base_url=base_url.strip(),
        formato=formato,
        region=region,
        admite_opt_out=admite_opt_out,
        modelos=list(modelos or []),
        coste_entrada_millon=coste_entrada_millon,
        coste_salida_millon=coste_salida_millon,
        config=dict(config or {}),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def politica(db: Session, tenant_id: UUID) -> PoliticaIA | None:
    return db.execute(
        select(PoliticaIA).where(PoliticaIA.tenant_id == tenant_id)
    ).scalar_one_or_none()


def fijar_politica(
    uow: UnidadDeTrabajo,
    *,
    regiones_admitidas: list[str] | None = None,
    exigir_opt_out: bool = True,
    preferencias: dict[str, str] | None = None,
    presupuesto_mes: Decimal | None = None,
) -> PoliticaIA:
    """Declara qué admite este tenant."""
    for region in regiones_admitidas or []:
        if region not in REGIONES:
            raise ErrorValidacion(
                f"Región «{region}» no reconocida.",
                error_code="ia.region_no_valida",
                detalle={"validas": list(REGIONES)},
            )
    fila = politica(uow.db, uow.tenant_id)
    if fila is None:
        fila = PoliticaIA(tenant_id=uow.tenant_id)
        uow.db.add(fila)
    fila.regiones_admitidas = list(regiones_admitidas or [])
    fila.exigir_opt_out = exigir_opt_out
    fila.preferencias = dict(preferencias or {})
    fila.presupuesto_mes = presupuesto_mes
    uow.db.flush()
    return fila


def apagar(uow: UnidadDeTrabajo, *, motivo: str) -> PoliticaIA:
    """Corta toda la IA de este tenant (CRM-05.02.03.04).

    Sin borrar configuración: lo que se quiere el día que algo va mal es parar
    ahora y decidir después.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Apagar la IA exige motivo: alguien preguntará por qué dejó de " "funcionar.",
            error_code="ia.motivo_obligatorio",
        )
    fila = politica(uow.db, uow.tenant_id) or PoliticaIA(tenant_id=uow.tenant_id)
    fila.ia_activa = False
    fila.motivo_apagado = motivo.strip()
    if fila.id is None:
        uow.db.add(fila)
    uow.db.flush()
    return fila


def elegir(
    db: Session,
    tenant_id: UUID,
    *,
    uso: str,
    preferido: str = "",
) -> dict[str, Any]:
    """Qué proveedor atiende esta petición, **y por qué** (CRM-05.02.02.10).

    El orden de las comprobaciones es deliberado: **interruptor, opt-out,
    región, presupuesto**. El interruptor primero porque tiene que cortar aunque
    todo lo demás esté bien; y la región y el opt-out antes que el presupuesto
    porque son condiciones del contrato, no cuestión de dinero.

    Cuando no se puede llamar se dice **cuál de las condiciones lo impide**. Un
    «no disponible» a secas manda a revisar la conexión cuando lo que pasa es que
    el cliente no admite esa región.
    """
    if uso not in USOS:
        raise ErrorValidacion(
            f"Uso «{uso}» no reconocido.",
            error_code="ia.uso_no_valido",
            detalle={"validos": list(USOS)},
        )
    ficha = politica(db, tenant_id)
    if ficha is not None and not ficha.ia_activa:
        return {
            "elegido": None,
            "puede_llamar": False,
            "porque": "La IA está apagada para este tenant: " + (ficha.motivo_apagado or ""),
            "motivo_codigo": "apagada",
        }

    candidatos = (
        db.execute(
            select(ProveedorIA).where(
                ProveedorIA.tenant_id == tenant_id, ProveedorIA.activo.is_(True)
            )
        )
        .scalars()
        .all()
    )
    if not candidatos:
        return {
            "elegido": None,
            "puede_llamar": False,
            "porque": "No hay ningún proveedor de IA declarado.",
            "motivo_codigo": "sin_proveedor",
        }

    # El modelo del propio cliente gana siempre que exista: es su casa.
    candidatos.sort(key=lambda p: (not p.propio, p.clave))
    clave_preferida = preferido or (ficha.preferencias or {}).get(uso, "") if ficha else preferido
    if clave_preferida:
        candidatos.sort(key=lambda p: p.clave != clave_preferida)

    descartados: list[dict[str, str]] = []
    exigir_opt_out = ficha.exigir_opt_out if ficha else True
    regiones = [str(r) for r in (ficha.regiones_admitidas or [])] if ficha else []

    for proveedor in candidatos:
        if proveedor.modelos and uso not in {
            str(m.get("uso")) for m in proveedor.modelos if m.get("uso")
        }:
            descartados.append(
                {"proveedor": proveedor.clave, "porque": f"no declara ningún modelo para «{uso}»"}
            )
            continue
        if exigir_opt_out and not proveedor.admite_opt_out:
            descartados.append(
                {
                    "proveedor": proveedor.clave,
                    "porque": (
                        "no garantiza que no se entrene con lo enviado, y este tenant " "lo exige"
                    ),
                }
            )
            continue
        if regiones and proveedor.region not in regiones:
            descartados.append(
                {
                    "proveedor": proveedor.clave,
                    "porque": (
                        f"procesa en «{proveedor.region}» y este tenant solo admite "
                        f"{', '.join(regiones)}"
                    ),
                }
            )
            continue

        modelo = next(
            (m for m in (proveedor.modelos or []) if str(m.get("uso")) == uso),
            None,
        )
        return {
            "elegido": proveedor.clave,
            "proveedor_id": str(proveedor.id),
            "modelo": str((modelo or {}).get("nombre") or ""),
            "region": proveedor.region,
            "propio_del_tenant": proveedor.propio,
            "opt_out": proveedor.admite_opt_out,
            "puede_llamar": True,
            "descartados": descartados,
            "porque": (
                f"Modelo del propio cliente en {proveedor.region}."
                if proveedor.propio
                else f"ProveedorIA «{proveedor.clave}» en {proveedor.region}, "
                + ("con opt-out garantizado." if proveedor.admite_opt_out else "sin opt-out.")
            ),
        }

    return {
        "elegido": None,
        "puede_llamar": False,
        # Se dice exactamente qué condición lo impide: «no disponible» a secas
        # manda a revisar la conexión cuando el problema es el contrato.
        "porque": "Ningún proveedor cumple lo que este tenant exige.",
        "motivo_codigo": "sin_candidato",
        "descartados": descartados,
    }


def anotar_gasto(
    uow: UnidadDeTrabajo,
    *,
    proveedor: str,
    tokens_entrada: int,
    tokens_salida: int,
    coste: Decimal | None = None,
    dia: date | None = None,
) -> GastoIA:
    """Suma lo gastado hoy."""
    cuando = dia or _hoy(uow.db)
    fila = uow.db.execute(
        select(GastoIA).where(
            GastoIA.tenant_id == uow.tenant_id,
            GastoIA.dia == cuando,
            GastoIA.proveedor == proveedor,
        )
    ).scalar_one_or_none()
    if fila is None:
        # Los valores se ponen aquí y no se dejan al `default` de la columna: ese
        # solo se aplica al hacer el INSERT, y hasta entonces son `None` — sumarle
        # tokens reventaría antes de llegar a la base.
        fila = GastoIA(
            tenant_id=uow.tenant_id,
            dia=cuando,
            proveedor=proveedor,
            tokens_entrada=0,
            tokens_salida=0,
            coste=Decimal(0),
            llamadas=0,
        )
        uow.db.add(fila)
    fila.tokens_entrada += max(0, int(tokens_entrada))
    fila.tokens_salida += max(0, int(tokens_salida))
    fila.coste = Decimal(fila.coste) + Decimal(coste or 0)
    fila.llamadas += 1
    uow.db.flush()

    # ── Y si con esto se ha agotado el mes, se dice ───────────────────────
    #
    # `ai.budget.exhausted` estaba DECLARADO en el contrato publicado desde el
    # principio y no lo emitía nadie: quien se suscribiera no recibía nada, y la
    # descripción del propio evento dice para qué sirve — «lo escucha quien
    # avisa, porque el usuario sólo ve que la función dejó de estar».
    #
    # Se emite AQUÍ, al cruzar el tope, y no en `exigir_presupuesto`, que es
    # donde se nota. Ése lanza, y lo que se escriba justo antes se deshace con
    # la transacción: el aviso se perdería exactamente en el momento en que
    # hace falta.
    #
    # Una vez por mes: la clave de deduplicación lleva el mes, así que las
    # llamadas siguientes —que también cruzan el tope— no repiten el aviso.
    estado = presupuesto(uow.db, uow.tenant_id, hoy=cuando)
    if estado["agotado"]:
        uow.emitir(
            AI_BUDGET_EXHAUSTED,
            subject=("tenant", uow.tenant_id),
            data={"tenant": str(uow.tenant_id), "gastado": estado["gastado"]},
            dedup_key=f"ia:presupuesto:{uow.tenant_id}:{estado['mes_desde']}",
        )
    return fila


def coste_estimado(
    db: Session, *, proveedor: str, tokens_entrada: int, tokens_salida: int
) -> Decimal:
    """Lo que costaría, según el coste declarado del proveedor."""
    fila = db.execute(select(ProveedorIA).where(ProveedorIA.clave == proveedor)).scalars().first()
    if fila is None:
        return Decimal(0)
    entrada = Decimal(tokens_entrada) / Decimal(1_000_000) * Decimal(fila.coste_entrada_millon)
    salida = Decimal(tokens_salida) / Decimal(1_000_000) * Decimal(fila.coste_salida_millon)
    return (entrada + salida).quantize(CENTIMO, rounding=ROUND_HALF_UP)


def presupuesto(db: Session, tenant_id: UUID, *, hoy: date | None = None) -> dict[str, Any]:
    """Cuánto se lleva gastado este mes y cuánto queda.

    Se comprueba **antes** de llamar: comprobarlo después es descubrir que ya se
    gastó, y la factura llega igual.
    """
    cuando = hoy or _hoy(db)
    desde = cuando.replace(day=1)
    gastado = (
        db.execute(
            select(func.coalesce(func.sum(GastoIA.coste), 0)).where(
                GastoIA.tenant_id == tenant_id, GastoIA.dia >= desde
            )
        )
    ).scalar_one()
    ficha = politica(db, tenant_id)
    # `is not None` y no la verdad del valor: con `if ficha.presupuesto_mes`, un
    # tope de **cero** —que es como un administrador para el gasto de IA sin
    # desconectar nada— se leía como «no hay tope» y dejaba la IA corriendo sin
    # límite. Justo lo contrario de lo que acababa de pedir.
    tope = Decimal(ficha.presupuesto_mes) if ficha and ficha.presupuesto_mes is not None else None
    return {
        "mes_desde": str(desde),
        "gastado": str(Decimal(gastado or 0)),
        "presupuesto": str(tope) if tope is not None else None,
        "queda": str(tope - Decimal(gastado or 0)) if tope is not None else None,
        "agotado": bool(tope is not None and Decimal(gastado or 0) >= tope),
        # Sin presupuesto declarado no se dice que quede mucho: se dice que no hay
        # tope, que es lo que alguien tiene que decidir.
        "con_tope": tope is not None,
    }


def exigir_presupuesto(db: Session, tenant_id: UUID) -> None:
    """Corta si el mes ya se ha gastado."""
    estado = presupuesto(db, tenant_id)
    if estado["agotado"]:
        raise Conflicto(
            "Se ha agotado el presupuesto de IA de este mes",
            error_code="ia.presupuesto_agotado",
            detalle=estado,
        )


def exigir_disponible(db: Session, tenant_id: UUID, *, uso: str) -> dict[str, Any]:
    """Comprueba todo y devuelve el proveedor elegido, o falla explicando cuál.

    Es la puerta por la que pasa **todo** lo de este servicio: si cada módulo
    comprobara por su cuenta, el día que se añada una condición habría seis sitios
    donde ponerla y solo cinco la tendrían.
    """
    eleccion = elegir(db, tenant_id, uso=uso)
    if not eleccion["puede_llamar"]:
        codigo = str(eleccion.get("motivo_codigo") or "sin_candidato")
        if codigo == "apagada":
            raise Prohibido(eleccion["porque"], error_code="ia.apagada", detalle=eleccion)
        raise NoEncontrado(eleccion["porque"], error_code="ia.sin_proveedor", detalle=eleccion)
    exigir_presupuesto(db, tenant_id)
    return eleccion


# ── Modo sin salida de datos (CRM-00.01.05.04) ────────────────────────────


def exigir_sin_salida(
    db: Session, tenant_id: UUID, *, uso: str, region_del_tenant: str = "ue"
) -> dict[str, Any]:
    """Elige proveedor **sin que el dato salga de la región** del tenant.

    Es el modo que piden los clientes que no pueden mandar nada fuera: sector
    público, sanidad, banca. Lo que hacen casi todos los productos es ofrecer una
    casilla «no usar IA» — que no es lo mismo: el cliente quiere la función, no
    quiere la salida.

    Tres condiciones, y las tres tienen que cumplirse:

    **El proveedor está en la región del tenant**, no en «una región europea».
    Un modelo alojado en otro país de la UE sigue siendo una transferencia dentro
    del EEE, que es legal, pero no es lo que se pidió cuando se pidió esto.

    **Garantiza que no entrena con lo que se le manda.** Un modelo en la región
    que aprende de los datos los saca de otra forma: no por la red, por el peso.

    **O es del propio cliente.** Un modelo suyo, en su infraestructura, es la
    única forma de que esto no dependa de la promesa de nadie — y por eso se
    prefiere cuando está.
    """
    eleccion = elegir(db, tenant_id, uso=uso)
    if not eleccion["puede_llamar"]:
        return {
            **eleccion,
            "sin_salida": False,
            "porque_sin_salida": "No hay ningún proveedor disponible, ni dentro ni fuera.",
        }

    candidatos = (
        db.execute(
            select(ProveedorIA).where(
                ProveedorIA.tenant_id == tenant_id,
                ProveedorIA.activo.is_(True),
                ProveedorIA.region == region_del_tenant,
            )
        )
        .scalars()
        .all()
    )
    propios = [p for p in candidatos if p.propio]
    con_opt_out = [p for p in candidatos if p.admite_opt_out]

    # El del cliente primero: es la única opción que no depende de la promesa de
    # nadie. Después, el que garantiza por escrito que no entrena.
    elegido = (propios or con_opt_out or [None])[0]
    if elegido is None:
        return {
            "puede_llamar": False,
            "sin_salida": False,
            "porque_sin_salida": (
                f"No hay ningún modelo en «{region_del_tenant}» que garantice que no "
                "entrena con lo que se le manda. Este tenant ha pedido que el dato no "
                "salga, así que no se llama a ninguno: usar el de fuera «porque es "
                "mejor» sería incumplir lo que se le prometió."
            ),
            "descartados": [
                {"proveedor": p.clave, "region": p.region, "opt_out": p.admite_opt_out}
                for p in db.execute(
                    select(ProveedorIA).where(
                        ProveedorIA.tenant_id == tenant_id, ProveedorIA.activo.is_(True)
                    )
                ).scalars()
            ],
        }

    return {
        "puede_llamar": True,
        "sin_salida": True,
        "elegido": elegido.clave,
        "modelo": str(
            next((m.get("nombre") for m in (elegido.modelos or []) if m.get("uso") == uso), "")
        ),
        "region": elegido.region,
        "propio_del_tenant": elegido.propio,
        "opt_out": elegido.admite_opt_out,
        "porque_sin_salida": (
            "Modelo del propio cliente en su infraestructura: el dato no sale de "
            "donde ya estaba."
            if elegido.propio
            else f"Modelo alojado en «{elegido.region}», la misma región del tenant, "
            "y con garantía escrita de que no entrena con lo que recibe."
        ),
    }
