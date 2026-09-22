"""Recorridos de cliente: el lienzo, las esperas y las bifurcaciones
(CRM-02.02.02.01 a CRM-02.02.02.04, CRM-02.02.02.07, CRM-02.02.02.08,
CRM-02.02.02.09).

Un recorrido es un proceso de negocio con una diferencia: lo ejecutan miles de
personas a la vez y **cada una va por su sitio**. Eso cambia tres cosas respecto
del motor de procesos, y por eso esto vive aquí y no allí:

**El estado es por persona, no por expediente.** Un proceso tiene una instancia
por caso; un recorrido tiene una por contacto y decenas de miles vivas. Meterlas
en el motor de procesos convertiría cada envío masivo en cien mil instancias
duraderas con su compensación, que es un precio que no paga lo que aporta.

**Las decisiones miran comportamiento, no datos.** «Abrió», «hizo clic», «no
respondió en cinco días» son eventos que ocurren *fuera*, y la rama se resuelve
cuando llegan o cuando vence la espera.

**Salir es lo que más importa.** Un recorrido del que no se sale a tiempo manda
la oferta de bienvenida a quien ya compró. Por eso las salidas se declaran
arriba, valen para todos los nodos y se comprueban **antes** de cada paso.

Y dos cosas que se heredan del resto de marketing en vez de reinventarse: la
**supresión** —quien pidió no ser alcanzado no lo es, por mucho que el recorrido
lo diga— y la **fatiga**, porque tres recorridos a la vez suman tres correos el
mismo martes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
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

logger = get_logger(__name__)

# Tipos de nodo. Cerrado: un tipo libre haría que el lienzo tuviera que adivinar
# cómo dibujar algo que no conoce, y el motor cómo ejecutarlo.
TIPOS_NODO = ("accion", "espera", "decision", "prueba", "salida", "fin")
# Cómo se entra a un recorrido (CRM-02.02.02.02).
ENTRADAS = ("evento", "segmento", "api", "manual")
# Comportamientos sobre los que se bifurca (CRM-02.02.02.03).
COMPORTAMIENTOS = ("abrio", "clico", "visito", "compro", "respondio", "no_respondio")
# Por qué se sale (CRM-02.02.02.07).
MOTIVOS = ("conversion", "exclusion", "otro_recorrido", "fin", "manual", "suprimido", "caducado")


class Recorrido(Base, TimestampMixin):
    """La definición del recorrido (CRM-02.02.02.01)."""

    __tablename__ = "recorridos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # El lienzo ES la definición, como en el motor de procesos: nodos con su
    # tipo, sus salidas y sus posiciones dentro del mismo documento. Con el
    # dibujo aparte, el día que se desincronizaran el diagrama enseñaría un
    # recorrido que no es el que se ejecuta.
    nodos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    inicio: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    # Cómo se entra (CRM-02.02.02.02).
    entrada: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    evento_entrada: Mapped[str | None] = mapped_column(String(80), nullable=True)
    segmento_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # Las salidas valen para TODO el recorrido y se comprueban antes de cada
    # paso. Un recorrido del que no se sale a tiempo manda la oferta de
    # bienvenida a quien ya compró.
    salidas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Recorridos que expulsan de este al entrar en ellos. Sin esto, alguien que
    # pasa de «captación» a «cliente» recibe las dos cosas a la vez.
    excluye_si_en: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Cuántos días como mucho. Un recorrido sin tope deja gente dentro años,
    # recibiendo un paso que alguien añadió al final sin pensar en ellos.
    dias_maximos: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    # Solo se puede entrar una vez. Casi siempre es lo correcto: quien ya recorrió
    # la bienvenida no la necesita otra vez.
    reentrada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Un recorrido por cuenta y no por persona (CRM-02.02.02.09): en B2B, cuatro
    # personas de la misma empresa recibiendo la misma secuencia es cuatro veces
    # el mismo mensaje en la misma reunión.
    por_cuenta: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # borrador | publicado | pausado | archivado
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_recorrido_clave"),
        Index("ix_recorridos_estado", "tenant_id", "estado"),
    )


class EnRecorrido(Base, TimestampMixin):
    """Una persona dentro de un recorrido."""

    __tablename__ = "en_recorrido"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    recorrido_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("recorridos.id", ondelete="CASCADE"), nullable=False
    )
    # La versión con la que entró. Quien está dentro termina con la suya: cambiar
    # el recorrido bajo los pies de quien ya recibió tres correos produce saltos
    # que nadie puede explicar después.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    objeto: Mapped[str] = mapped_column(String(20), nullable=False, default="contacto")
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)

    nodo_actual: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    # activo | esperando | salido | terminado
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="activo", index=True)
    despertar_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    entro_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    salio_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_salida: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # En qué rama de una prueba A/B cayó (CRM-02.02.02.04).
    variantes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Lo que ha hecho: `{"abrio": true, "clico_at": "..."}`.
    comportamiento: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "recorrido_id", "objeto_id", name="uq_en_recorrido"),
        Index("ix_en_recorrido_pendientes", "tenant_id", "estado", "despertar_at"),
    )


class PasoRecorrido(Base):
    """Por dónde pasó cada uno. Append-only (CRM-02.02.02.08)."""

    __tablename__ = "pasos_recorrido"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    recorrido_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    en_recorrido_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("en_recorrido.id", ondelete="CASCADE"), nullable=False
    )
    nodo: Mapped[str] = mapped_column(String(80), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    # Por dónde salió del nodo. En una decisión es la rama; en una acción, vacío.
    rama: Mapped[str | None] = mapped_column(String(80), nullable=True)
    variante: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Se ejecutó, o se saltó y por qué (fatiga, supresión).
    ejecutado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    motivo_omision: Mapped[str | None] = mapped_column(String(80), nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_pasos_recorrido", "tenant_id", "recorrido_id", "nodo"),
        Index("ix_pasos_por_persona", "en_recorrido_id", "at"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


# ── Validación del lienzo (CRM-02.02.02.01) ───────────────────────────────


def validar(definicion: dict[str, Any]) -> list[str]:
    """Comprueba el recorrido antes de publicarlo.

    Se valida **antes de publicar y no al ejecutar**: un recorrido roto
    descubierto en ejecución son diez mil personas paradas a mitad de camino, y
    sacarlas de ahí cuesta más que el error.
    """
    nodos = definicion.get("nodos") or {}
    inicio = str(definicion.get("inicio") or "")
    if not nodos:
        raise ErrorValidacion(
            "Un recorrido sin nodos no lleva a nadie a ninguna parte.",
            error_code="recorrido.sin_nodos",
        )
    if inicio not in nodos:
        raise ErrorValidacion(
            f"El nodo de inicio «{inicio}» no existe.",
            error_code="recorrido.inicio_no_existe",
        )

    avisos: list[str] = []
    destinos: set[str] = set()
    for nombre, nodo in nodos.items():
        tipo = str(nodo.get("tipo") or "")
        if tipo not in TIPOS_NODO:
            raise ErrorValidacion(
                f"Tipo de nodo «{tipo}» no válido en «{nombre}».",
                error_code="recorrido.tipo_no_valido",
                detalle={"validos": list(TIPOS_NODO)},
            )
        salidas = _salidas_de(nodo)
        for destino in salidas:
            if destino and destino not in nodos:
                raise ErrorValidacion(
                    f"«{nombre}» lleva a «{destino}», que no existe.",
                    error_code="recorrido.destino_no_existe",
                )
            if destino:
                destinos.add(destino)
        if tipo == "decision" and not nodo.get("rutas"):
            raise ErrorValidacion(
                f"La decisión «{nombre}» no tiene ramas.",
                error_code="recorrido.decision_sin_ramas",
            )
        if tipo == "decision":
            comportamiento = str(nodo.get("comportamiento") or "")
            if comportamiento and comportamiento not in COMPORTAMIENTOS:
                raise ErrorValidacion(
                    f"Comportamiento «{comportamiento}» no válido.",
                    error_code="recorrido.comportamiento_no_valido",
                    detalle={"validos": list(COMPORTAMIENTOS)},
                )
            if comportamiento and not nodo.get("espera_dias"):
                # Una decisión por comportamiento sin plazo espera para siempre:
                # nadie «no ha abierto» hasta que se decide cuándo se deja de
                # esperar.
                raise ErrorValidacion(
                    f"La decisión «{nombre}» mira un comportamiento y no dice "
                    "cuánto espera. Sin plazo, nadie «no ha abierto» nunca.",
                    error_code="recorrido.decision_sin_plazo",
                )
        if tipo == "prueba":
            variantes = nodo.get("variantes") or []
            if len(variantes) < 2:
                raise ErrorValidacion(
                    f"La prueba «{nombre}» necesita al menos dos variantes.",
                    error_code="recorrido.prueba_sin_variantes",
                )
            reparto = sum(int(v.get("peso", 0)) for v in variantes)
            if reparto != 100:
                raise ErrorValidacion(
                    f"Los pesos de «{nombre}» suman {reparto} y tienen que sumar 100.",
                    error_code="recorrido.pesos_no_suman",
                )

    huerfanos = sorted(n for n in nodos if n != inicio and n not in destinos)
    if huerfanos:
        # No se rechaza: montando un lienzo es normal tener un trozo suelto a
        # mitad. Pero publicarlo con nodos a los que no llega nadie es publicar
        # algo que no se va a ejecutar, y eso hay que verlo.
        avisos.append("Hay nodos a los que no llega nadie: " + ", ".join(huerfanos))
    if not any(str(n.get("tipo")) in ("fin", "salida") for n in nodos.values()):
        avisos.append(
            "El recorrido no tiene ningún final: la gente saldrá solo por el tope "
            "de días, y eso se lee como que el recorrido no terminó."
        )
    if not definicion.get("salidas"):
        avisos.append(
            "No hay salidas declaradas. Sin ellas, quien compre seguirá "
            "recibiendo la oferta de bienvenida hasta el último paso."
        )
    return avisos


def _salidas_de(nodo: dict[str, Any]) -> list[str]:
    salidas = []
    if nodo.get("siguiente"):
        salidas.append(str(nodo["siguiente"]))
    for destino in (nodo.get("rutas") or {}).values():
        salidas.append(str(destino))
    for variante in nodo.get("variantes") or []:
        if variante.get("siguiente"):
            salidas.append(str(variante["siguiente"]))
    return salidas


def crear(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    nodos: dict[str, Any],
    inicio: str,
    descripcion: str = "",
    entrada: str = "manual",
    evento_entrada: str = "",
    segmento_id: UUID | None = None,
    salidas: list[dict[str, Any]] | None = None,
    excluye_si_en: list[str] | None = None,
    dias_maximos: int = 90,
    reentrada: bool = False,
    por_cuenta: bool = False,
) -> tuple[Recorrido, list[str]]:
    if entrada not in ENTRADAS:
        raise ErrorValidacion(
            f"Entrada «{entrada}» no válida.",
            error_code="recorrido.entrada_no_valida",
            detalle={"validas": list(ENTRADAS)},
        )
    if entrada == "evento" and not evento_entrada:
        raise ErrorValidacion(
            "Una entrada por evento necesita decir por qué evento.",
            error_code="recorrido.entrada_sin_evento",
        )
    if entrada == "segmento" and segmento_id is None:
        raise ErrorValidacion(
            "Una entrada por segmento necesita decir por cuál.",
            error_code="recorrido.entrada_sin_segmento",
        )

    definicion = {"nodos": nodos, "inicio": inicio, "salidas": salidas or []}
    avisos = validar(definicion)
    fila = Recorrido(
        tenant_id=uow.tenant_id,
        clave=clave,
        nombre=nombre,
        descripcion=descripcion,
        nodos=nodos,
        inicio=inicio,
        entrada=entrada,
        evento_entrada=evento_entrada or None,
        segmento_id=segmento_id,
        salidas=salidas or [],
        excluye_si_en=excluye_si_en or [],
        dias_maximos=dias_maximos,
        reentrada=reentrada,
        por_cuenta=por_cuenta,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def publicar(uow: UnidadDeTrabajo, recorrido_id: UUID) -> dict[str, Any]:
    """Publica el recorrido. Quien esté dentro sigue con su versión.

    Cambiar el recorrido bajo los pies de quien ya recibió tres correos produce
    saltos que nadie puede explicar después —«¿por qué a este le llegó el paso
    cinco sin el cuatro?»— y son justo los que se descubren por una queja.
    """
    fila = uow.db.get(Recorrido, recorrido_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("El recorrido no existe", error_code="recorrido.no_encontrado")
    avisos = validar({"nodos": fila.nodos, "inicio": fila.inicio, "salidas": fila.salidas})
    if fila.estado == "publicado":
        fila.version += 1
    fila.estado = "publicado"
    uow.db.flush()
    return {"recorrido": fila.clave, "version": fila.version, "avisos": avisos}


# ── Entrar (CRM-02.02.02.02) ──────────────────────────────────────────────


def entrar(
    uow: UnidadDeTrabajo,
    recorrido_id: UUID,
    *,
    objeto_id: UUID,
    objeto: str = "contacto",
    cuenta_id: UUID | None = None,
) -> dict[str, Any]:
    """Mete a alguien en el recorrido.

    Cuatro comprobaciones antes de dejar entrar, y ninguna es opcional:

    * que el recorrido esté **publicado** —entrar en un borrador es recibir un
      recorrido a medio montar—;
    * que **no esté ya dentro**, salvo que se permita reentrada: quien recorrió
      la bienvenida no la necesita otra vez;
    * que **no esté en un recorrido excluyente**: sin esto, quien pasa de
      captación a cliente recibe las dos cosas a la vez;
    * y que **no esté suprimido**, porque quien pidió no ser alcanzado no lo es
      por mucho que el recorrido lo diga.
    """
    from services.marketing.segmentos import filtrar_suprimidos

    tenant_id = uow.tenant_id
    recorrido = uow.db.get(Recorrido, recorrido_id)
    if recorrido is None or recorrido.tenant_id != tenant_id:
        raise NoEncontrado("El recorrido no existe", error_code="recorrido.no_encontrado")
    if recorrido.estado != "publicado":
        raise Conflicto(
            f"Ese recorrido está «{recorrido.estado}»: entrar en un borrador es "
            "recibir un recorrido a medio montar.",
            error_code="recorrido.no_publicado",
        )

    ya = uow.db.execute(
        select(EnRecorrido).where(
            EnRecorrido.tenant_id == tenant_id,
            EnRecorrido.recorrido_id == recorrido_id,
            EnRecorrido.objeto_id == objeto_id,
        )
    ).scalar_one_or_none()
    if ya is not None and not recorrido.reentrada:
        return {"entro": False, "motivo": "ya_estuvo", "en_recorrido_id": str(ya.id)}
    if ya is not None and ya.estado in ("activo", "esperando"):
        return {"entro": False, "motivo": "ya_dentro", "en_recorrido_id": str(ya.id)}

    if recorrido.excluye_si_en:
        otros = (
            uow.db.execute(
                select(EnRecorrido)
                .join(Recorrido, Recorrido.id == EnRecorrido.recorrido_id)
                .where(
                    EnRecorrido.tenant_id == tenant_id,
                    EnRecorrido.objeto_id == objeto_id,
                    EnRecorrido.estado.in_(("activo", "esperando")),
                    Recorrido.clave.in_([str(c) for c in recorrido.excluye_si_en]),
                )
            )
            .scalars()
            .all()
        )
        if otros:
            return {"entro": False, "motivo": "en_recorrido_excluyente"}

    permitidos, _ = filtrar_suprimidos(uow.db, tenant_id, objeto, [objeto_id])
    if objeto_id not in permitidos:
        # «Fuera» junta dos cosas distintas: quien pidió la baja y quien no tiene
        # dirección. Decir «suprimido» a los dos manda a buscar una baja que no
        # existe, cuando lo que falta es el correo. Se distinguen.
        return {
            "entro": False,
            "motivo": _por_que_no_alcanzable(uow.db, tenant_id, objeto, objeto_id),
        }

    if recorrido.por_cuenta and cuenta_id is not None:
        # En B2B, cuatro personas de la misma empresa recibiendo la misma
        # secuencia es cuatro veces el mismo mensaje en la misma reunión.
        hermano = uow.db.execute(
            select(EnRecorrido).where(
                EnRecorrido.tenant_id == tenant_id,
                EnRecorrido.recorrido_id == recorrido_id,
                EnRecorrido.cuenta_id == cuenta_id,
                EnRecorrido.estado.in_(("activo", "esperando")),
            )
        ).scalar_one_or_none()
        if hermano is not None:
            return {"entro": False, "motivo": "cuenta_ya_dentro"}

    if ya is not None:
        uow.db.delete(ya)
        uow.db.flush()

    fila = EnRecorrido(
        tenant_id=tenant_id,
        recorrido_id=recorrido_id,
        version=recorrido.version,
        objeto=objeto,
        objeto_id=objeto_id,
        cuenta_id=cuenta_id,
        nodo_actual=recorrido.inicio,
        despertar_at=_ahora(),
    )
    uow.db.add(fila)
    uow.db.flush()
    uow.emitir(
        "journey.entered",
        subject=("recorrido", fila.id),
        data={
            "recorrido": recorrido.clave,
            "en_recorrido_id": str(fila.id),
            "objeto": objeto,
            "objeto_id": str(objeto_id),
        },
    )
    return {"entro": True, "en_recorrido_id": str(fila.id), "nodo": fila.nodo_actual}


# ── Salidas (CRM-02.02.02.07) ─────────────────────────────────────────────


def _por_que_no_alcanzable(db: Session, tenant_id: UUID, objeto: str, objeto_id: UUID) -> str:
    """Si no se le puede escribir, por qué exactamente.

    Sin esta distinción, quien mira por qué no entró alguien busca una baja que
    no existe cuando lo que falta es la dirección — y al revés.
    """
    from services.marketing.modelos import PerfilMarketing

    perfil = db.execute(
        select(PerfilMarketing).where(
            PerfilMarketing.tenant_id == tenant_id,
            PerfilMarketing.objeto == objeto,
            PerfilMarketing.objeto_id == objeto_id,
        )
    ).scalar_one_or_none()
    if perfil is None or not (perfil.email or "").strip():
        return "sin_direccion"
    return "suprimido"


def _debe_salir(db: Session, recorrido: Recorrido, fila: EnRecorrido) -> tuple[bool, str]:
    """Si esta persona ya no pinta nada aquí.

    Se comprueba **antes de cada paso** y no solo al entrar: alguien que compra a
    mitad del recorrido tiene que dejar de recibir la oferta de bienvenida en el
    paso siguiente, no al final.
    """
    from crmcore.authz.abac import Condicion

    ahora = _ahora()
    if (ahora - _con_tz(fila.entro_at)).days > recorrido.dias_maximos:
        return True, "caducado"

    ambito = {"persona": dict(fila.comportamiento or {})}
    for salida in recorrido.salidas or []:
        condiciones = [
            Condicion(
                atributo=str(c.get("atributo", "")),
                operador=str(c.get("operador", "=")),
                valor=c.get("valor"),
            )
            for c in (salida.get("condiciones") or [])
            if isinstance(c, dict)
        ]
        if condiciones and all(c.evaluar(ambito) for c in condiciones):
            motivo = str(salida.get("motivo") or "conversion")
            return True, motivo if motivo in MOTIVOS else "conversion"
    return False, ""


def salir(uow: UnidadDeTrabajo, en_recorrido_id: UUID, *, motivo: str = "manual") -> dict[str, Any]:
    if motivo not in MOTIVOS:
        raise ErrorValidacion(
            f"Motivo «{motivo}» no válido.",
            error_code="recorrido.motivo_no_valido",
            detalle={"validos": list(MOTIVOS)},
        )
    fila = uow.db.get(EnRecorrido, en_recorrido_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("No está en ese recorrido", error_code="recorrido.no_esta")
    if fila.estado in ("salido", "terminado"):
        raise Conflicto("Ya salió de ese recorrido", error_code="recorrido.ya_salio")

    fila.estado = "salido"
    fila.motivo_salida = motivo
    fila.salio_at = _ahora()
    fila.despertar_at = None
    uow.db.flush()
    uow.emitir(
        "journey.exited",
        subject=("recorrido", fila.id),
        data={
            "en_recorrido_id": str(fila.id),
            "recorrido_id": str(fila.recorrido_id),
            "objeto_id": str(fila.objeto_id),
            "motivo": motivo,
        },
    )
    return {"en_recorrido_id": str(fila.id), "motivo": motivo}


# ── Comportamiento (CRM-02.02.02.03) ──────────────────────────────────────


def anotar_comportamiento(
    uow: UnidadDeTrabajo, *, objeto_id: UUID, que: str, cuando: datetime | None = None
) -> dict[str, Any]:
    """Anota que alguien abrió, hizo clic, visitó o compró.

    Se anota en **todos los recorridos donde esté** a la vez: el mismo clic
    resuelve la rama de los tres, y anotarlo en uno solo dejaría a los otros dos
    esperando un comportamiento que ya ocurrió.
    """
    if que not in COMPORTAMIENTOS:
        raise ErrorValidacion(
            f"Comportamiento «{que}» no válido.",
            error_code="recorrido.comportamiento_no_valido",
            detalle={"validos": list(COMPORTAMIENTOS)},
        )
    momento = _con_tz(cuando) or _ahora()
    filas = (
        uow.db.execute(
            select(EnRecorrido).where(
                EnRecorrido.tenant_id == uow.tenant_id,
                EnRecorrido.objeto_id == objeto_id,
                EnRecorrido.estado.in_(("activo", "esperando")),
            )
        )
        .scalars()
        .all()
    )
    for fila in filas:
        fila.comportamiento = {
            **(fila.comportamiento or {}),
            que: True,
            f"{que}_at": momento.isoformat(),
        }
        # Un comportamiento que resuelve una espera la despierta ya: esperar al
        # plazo cuando la respuesta ya está es hacer esperar cinco días a quien
        # contestó en cinco minutos.
        if fila.estado == "esperando":
            fila.despertar_at = _ahora()
    uow.db.flush()
    return {"anotado_en": len(filas), "que": que}


# ── Ejecutar (CRM-02.02.02.04) ────────────────────────────────────────────


def _variante(
    fila: EnRecorrido, nodo_nombre: str, variantes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Reparte a una variante de forma estable.

    **Por el identificador de la persona y no al azar**: con `random`, reintentar
    un paso movería a alguien de la rama A a la B y su historial diría dos cosas
    distintas. Con el identificador, el mismo contacto cae siempre en la misma.
    """
    ya = (fila.variantes or {}).get(nodo_nombre)
    if ya:
        for variante in variantes:
            if str(variante.get("clave")) == ya:
                return variante
    semilla = int(str(fila.objeto_id).replace("-", "")[:8], 16) % 100
    acumulado = 0
    for variante in variantes:
        acumulado += int(variante.get("peso", 0))
        if semilla < acumulado:
            return variante
    return variantes[-1]


def avanzar(uow: UnidadDeTrabajo, tenant_id: UUID, *, limite: int = 500) -> dict[str, Any]:
    """Mueve a la gente por sus recorridos.

    Antes de cada paso se comprueba la **salida** y la **supresión**. Las dos van
    aquí y no al entrar porque las dos cambian con el tiempo: alguien compra a
    mitad, alguien se da de baja a mitad, y los dos tienen que dejar de recibir
    en el paso siguiente y no al final.
    """
    from services.marketing.campanas import comprobar_fatiga
    from services.marketing.segmentos import filtrar_suprimidos

    ahora = _ahora()
    pendientes = (
        uow.db.execute(
            select(EnRecorrido)
            .where(
                EnRecorrido.tenant_id == tenant_id,
                EnRecorrido.estado.in_(("activo", "esperando")),
                EnRecorrido.despertar_at.isnot(None),
                EnRecorrido.despertar_at <= ahora,
            )
            .limit(limite)
        )
        .scalars()
        .all()
    )
    movidos: list[dict[str, Any]] = []
    salidos: list[dict[str, Any]] = []
    omitidos: list[dict[str, Any]] = []

    for fila in pendientes:
        recorrido = uow.db.get(Recorrido, fila.recorrido_id)
        if recorrido is None:
            continue

        fuera, motivo = _debe_salir(uow.db, recorrido, fila)
        if fuera:
            salir(uow, fila.id, motivo=motivo)
            salidos.append({"objeto_id": str(fila.objeto_id), "motivo": motivo})
            continue

        nodo = (recorrido.nodos or {}).get(fila.nodo_actual)
        if nodo is None:
            fila.estado = "terminado"
            fila.despertar_at = None
            continue

        tipo = str(nodo.get("tipo"))
        rama: str | None = None
        variante: str | None = None
        ejecutado = True
        omision: str | None = None
        siguiente: str | None = nodo.get("siguiente")

        if tipo == "accion":
            permitidos, _ = filtrar_suprimidos(uow.db, tenant_id, fila.objeto, [fila.objeto_id])
            if fila.objeto_id not in permitidos:
                # No se para el recorrido: se salta el envío y se sigue. Pararlo
                # dejaría a la persona atascada en un nodo para siempre, y volver
                # a meterla después sería imposible sin tocar la base a mano.
                ejecutado = False
                omision = _por_que_no_alcanzable(uow.db, tenant_id, fila.objeto, fila.objeto_id)
            else:
                fatiga = comprobar_fatiga(uow.db, tenant_id, fila.objeto_id)
                if not fatiga.get("permitido", True):
                    ejecutado = False
                    omision = "fatiga"
            if ejecutado:
                uow.emitir(
                    "journey.action.due",
                    subject=("recorrido", fila.id),
                    data={
                        "en_recorrido_id": str(fila.id),
                        "recorrido": recorrido.clave,
                        "nodo": fila.nodo_actual,
                        "accion": str(nodo.get("accion") or ""),
                        "plantilla": str(nodo.get("plantilla") or ""),
                        "objeto_id": str(fila.objeto_id),
                    },
                )

        elif tipo == "espera":
            fila.estado = "esperando"
            fila.despertar_at = ahora + timedelta(days=int(nodo.get("dias", 1)))
            uow.db.add(
                PasoRecorrido(
                    tenant_id=tenant_id,
                    recorrido_id=recorrido.id,
                    en_recorrido_id=fila.id,
                    nodo=fila.nodo_actual,
                    tipo=tipo,
                )
            )
            uow.db.flush()
            movidos.append({"objeto_id": str(fila.objeto_id), "nodo": fila.nodo_actual})
            continue

        elif tipo == "decision":
            comportamiento = str(nodo.get("comportamiento") or "")
            rutas = nodo.get("rutas") or {}
            if comportamiento:
                hecho = bool((fila.comportamiento or {}).get(comportamiento))
                plazo = _con_tz(fila.despertar_at) or ahora
                if not hecho and (ahora - plazo).days < 0:
                    continue
                rama = "si" if hecho else "no"
            else:
                rama = "si"
            siguiente = rutas.get(rama) or rutas.get("no")

        elif tipo == "prueba":
            elegida = _variante(fila, fila.nodo_actual, list(nodo.get("variantes") or []))
            variante = str(elegida.get("clave"))
            fila.variantes = {**(fila.variantes or {}), fila.nodo_actual: variante}
            siguiente = elegida.get("siguiente")

        elif tipo in ("fin", "salida"):
            uow.db.add(
                PasoRecorrido(
                    tenant_id=tenant_id,
                    recorrido_id=recorrido.id,
                    en_recorrido_id=fila.id,
                    nodo=fila.nodo_actual,
                    tipo=tipo,
                )
            )
            fila.estado = "terminado"
            fila.motivo_salida = "fin"
            fila.salio_at = ahora
            fila.despertar_at = None
            uow.db.flush()
            salidos.append({"objeto_id": str(fila.objeto_id), "motivo": "fin"})
            continue

        uow.db.add(
            PasoRecorrido(
                tenant_id=tenant_id,
                recorrido_id=recorrido.id,
                en_recorrido_id=fila.id,
                nodo=fila.nodo_actual,
                tipo=tipo,
                rama=rama,
                variante=variante,
                ejecutado=ejecutado,
                motivo_omision=omision,
            )
        )
        if not ejecutado:
            omitidos.append(
                {"objeto_id": str(fila.objeto_id), "nodo": fila.nodo_actual, "motivo": omision}
            )

        if siguiente:
            fila.nodo_actual = siguiente
            fila.estado = "activo"
            fila.despertar_at = ahora
        else:
            fila.estado = "terminado"
            fila.motivo_salida = "fin"
            fila.salio_at = ahora
            fila.despertar_at = None
        movidos.append({"objeto_id": str(fila.objeto_id), "nodo": fila.nodo_actual})

    uow.db.flush()
    return {
        "pendientes": len(pendientes),
        "movidos": movidos,
        "salidos": salidos,
        # Lo que se saltó por supresión o fatiga sale aparte: contarlo como
        # enviado inflaría el embudo con correos que nadie recibió.
        "omitidos": omitidos,
        "medible": bool(pendientes),
    }


# ── Analítica por nodo (CRM-02.02.02.08) ──────────────────────────────────


def embudo(db: Session, tenant_id: UUID, recorrido_id: UUID) -> dict[str, Any]:
    """Cuánta gente pasó por cada nodo y dónde se cae.

    Se cuenta **gente distinta por nodo**, no pasos: un bucle haría que un nodo
    tuviera más pasos que personas en el recorrido y el embudo saldría al revés.

    Y la caída se dice **entre nodos consecutivos del camino**, no contra el
    total: contra el total, un nodo al que solo llega una rama parece un desastre
    cuando está funcionando.
    """
    recorrido = db.execute(
        select(Recorrido).where(Recorrido.id == recorrido_id, Recorrido.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if recorrido is None:
        raise NoEncontrado("El recorrido no existe", error_code="recorrido.no_encontrado")

    conteos = dict(
        db.execute(
            select(PasoRecorrido.nodo, func.count(func.distinct(PasoRecorrido.en_recorrido_id)))
            .where(
                PasoRecorrido.tenant_id == tenant_id,
                PasoRecorrido.recorrido_id == recorrido_id,
            )
            .group_by(PasoRecorrido.nodo)
        ).all()
    )
    omitidos = dict(
        db.execute(
            select(PasoRecorrido.nodo, func.count())
            .where(
                PasoRecorrido.tenant_id == tenant_id,
                PasoRecorrido.recorrido_id == recorrido_id,
                PasoRecorrido.ejecutado.is_(False),
            )
            .group_by(PasoRecorrido.nodo)
        ).all()
    )
    dentro = int(
        db.execute(
            select(func.count())
            .select_from(EnRecorrido)
            .where(
                EnRecorrido.tenant_id == tenant_id,
                EnRecorrido.recorrido_id == recorrido_id,
                EnRecorrido.estado.in_(("activo", "esperando")),
            )
        ).scalar_one()
        or 0
    )
    salidas = dict(
        db.execute(
            select(EnRecorrido.motivo_salida, func.count())
            .where(
                EnRecorrido.tenant_id == tenant_id,
                EnRecorrido.recorrido_id == recorrido_id,
                EnRecorrido.motivo_salida.isnot(None),
            )
            .group_by(EnRecorrido.motivo_salida)
        ).all()
    )

    # El camino principal, siguiendo las primeras salidas desde el inicio. Es una
    # aproximación y se dice: un recorrido con ramas no tiene un solo camino, y
    # fingir que sí daría un embudo que no describe a nadie.
    camino: list[str] = []
    actual: str | None = recorrido.inicio
    visto: set[str] = set()
    while actual and actual not in visto:
        visto.add(actual)
        camino.append(actual)
        nodo = (recorrido.nodos or {}).get(actual) or {}
        salidas_nodo = _salidas_de(nodo)
        actual = salidas_nodo[0] if salidas_nodo else None

    nodos = []
    anterior: int | None = None
    for nombre in camino:
        cuantos = int(conteos.get(nombre, 0))
        nodos.append(
            {
                "nodo": nombre,
                "tipo": str(((recorrido.nodos or {}).get(nombre) or {}).get("tipo") or ""),
                "personas": cuantos,
                "omitidos": int(omitidos.get(nombre, 0)),
                "caida_pct": (
                    round(100 * (anterior - cuantos) / anterior, 1)
                    if anterior and anterior > 0
                    else None
                ),
            }
        )
        anterior = cuantos

    total = sum(salidas.values()) + dentro
    return {
        "recorrido": recorrido.clave,
        "camino_principal": camino,
        "nodos": nodos,
        "dentro_ahora": dentro,
        "salidas_por_motivo": {str(k): int(v) for k, v in salidas.items()},
        "conversion_pct": (
            round(100 * int(salidas.get("conversion", 0)) / total, 1) if total else None
        ),
        # Con un recorrido de ramas, el camino principal es una aproximación y se
        # dice: fingir que hay un solo camino daría un embudo que no describe a
        # nadie.
        "tiene_ramas": any(len(_salidas_de(n)) > 1 for n in (recorrido.nodos or {}).values()),
        "medible": total > 0,
    }


def resultado_prueba(
    db: Session, tenant_id: UUID, recorrido_id: UUID, nodo: str, *, minimo: int = 100
) -> dict[str, Any]:
    """Qué variante gana en una prueba A/B (CRM-02.02.02.04).

    **Con pocos datos no se declara ganador.** Con treinta personas por rama, la
    diferencia que se ve es ruido, y elegir por ella es peor que no probar: se
    consolida una variante peor con la confianza de haberla medido.
    """
    filas = db.execute(
        select(PasoRecorrido.variante, func.count())
        .where(
            PasoRecorrido.tenant_id == tenant_id,
            PasoRecorrido.recorrido_id == recorrido_id,
            PasoRecorrido.nodo == nodo,
            PasoRecorrido.variante.isnot(None),
        )
        .group_by(PasoRecorrido.variante)
    ).all()
    por_variante = {str(k): int(v) for k, v in filas}
    conversiones: dict[str, int] = {}
    for variante in por_variante:
        conversiones[variante] = int(
            db.execute(
                select(func.count())
                .select_from(EnRecorrido)
                .join(PasoRecorrido, PasoRecorrido.en_recorrido_id == EnRecorrido.id)
                .where(
                    EnRecorrido.tenant_id == tenant_id,
                    EnRecorrido.motivo_salida == "conversion",
                    PasoRecorrido.nodo == nodo,
                    PasoRecorrido.variante == variante,
                )
            ).scalar_one()
            or 0
        )

    suficiente = all(v >= minimo for v in por_variante.values()) and len(por_variante) >= 2
    tasas = {
        k: round(100 * conversiones.get(k, 0) / v, 2) if v else 0.0 for k, v in por_variante.items()
    }
    ganadora = max(tasas, key=lambda k: tasas[k]) if tasas and suficiente else None
    return {
        "nodo": nodo,
        "variantes": [
            {"clave": k, "personas": v, "conversiones": conversiones.get(k, 0), "tasa": tasas[k]}
            for k, v in sorted(por_variante.items())
        ],
        "ganadora": ganadora,
        "concluyente": suficiente,
        "aviso": ""
        if suficiente
        else (
            f"Hacen falta al menos {minimo} personas por variante. Con menos, la "
            "diferencia que se ve es ruido, y elegir por ella consolida una "
            "variante peor con la confianza de haberla medido."
        ),
    }
