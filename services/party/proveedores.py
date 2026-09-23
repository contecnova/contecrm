"""El proveedor como parte: homologación, documentos, riesgo y evaluación
(CRM-09.01.01.01 a .06, .10).

Un CRM que solo mira al cliente cuenta media historia. En muchos negocios **quien
da el servicio es un proveedor**, y lo que se le promete al cliente depende de lo
que sostenga él: si no está homologado, si su seguro venció el mes pasado o si es
el único que puede servir esa zona, eso decide lo que se puede vender y no se
puede decidir en el momento de firmar.

La primera decisión es la que evita la mitad de los problemas:

**Un proveedor es una cuenta con rol, no un maestro aparte.** Ya existe el modelo
de partes, con su deduplicación, su jerarquía, sus direcciones y sus permisos. Un
maestro de proveedores en paralelo duplicaría las cuatro cosas, y la misma empresa
que es cliente de una división y proveedor de otra estaría dos veces —con el
riesgo de que se le apliquen condiciones de la ficha equivocada—.

Y las demás:

**Lo que caduca bloquea solo.** Un certificado vencido que hay que mirar a mano no
se mira: se descubre cuando el cliente pregunta. Aquí se avisa antes y se bloquea
al vencer, sin que nadie tenga que acordarse.

**La homologación es por categoría, no global.** «Proveedor homologado» no
significa nada: homologado ¿para qué? Uno puede valer para material de oficina y
no para trabajos en altura, y tratarlo igual es como se contrata a quien no debe.

**El riesgo se mide por dependencia, no por opinión.** Lo que hace daño no es un
proveedor malo: es un proveedor bueno del que se depende y que no tiene
alternativa declarada.

**Y la evaluación va con hechos.** Una encuesta anual mide la relación con el
comercial. El plazo cumplido y las incidencias miden el servicio, y son números
que ya están.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from crmcore.authz.decision import exigir
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Date,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

if TYPE_CHECKING:  # pragma: no cover — solo para el tipo
    from services.party.modelos import Cuenta

logger = get_logger(__name__)

ROL_PROVEEDOR = "proveedor"

# Estados de la homologación. `caducada` está aparte de `rechazada` a propósito:
# una caducada volvía a valer con papel nuevo y una rechazada no, y mezclarlas
# hace que alguien vuelva a intentarlo con quien ya se descartó.
ESTADOS_HOMOLOGACION = (
    "pendiente",
    "en_revision",
    "homologado",
    "caducada",
    "rechazada",
    "suspendido",
)

# Con cuánta antelación se avisa de lo que va a vencer. Es configurable por
# requisito; esto es el valor por defecto y existe porque avisar el mismo día es
# no avisar: renovar un seguro lleva semanas.
DIAS_PREAVISO = 30

# Funciones que hacen falta de un proveedor. Cerrada porque la pregunta real es
# «¿a quién llamo cuando esto falla a las once de la noche?», y con texto libre
# cada ficha contesta a otra cosa.
FUNCIONES_CONTACTO = ("comercial", "tecnico", "facturacion", "escalado", "calidad")


def _hoy() -> date:
    return datetime.now(timezone.utc).date()


class Homologacion(Base, TimestampMixin):
    """Si un proveedor vale para una categoría concreta, y hasta cuándo."""

    __tablename__ = "homologaciones_proveedor"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Para qué está homologado. «Proveedor homologado» a secas no significa nada:
    # uno puede valer para material de oficina y no para trabajos en altura.
    categoria: Mapped[str] = mapped_column(String(80), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    # Requisitos exigidos a esta categoría, con si están cubiertos.
    requisitos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    valida_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revisada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "cuenta_id", "categoria", name="uq_homologacion"),
        Index("ix_homologaciones_vigencia", "tenant_id", "valida_hasta"),
    )


class DocumentoProveedor(Base, TimestampMixin):
    """Un papel obligatorio con su vigencia: seguro, certificado, solvencia."""

    __tablename__ = "documentos_proveedor"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Referencia al documento en el gestor documental. No se guarda el fichero
    # aquí: ya hay un sitio para eso, y tener dos deja uno sin cifrar.
    referencia: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    valido_desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    valido_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    dias_preaviso: Mapped[int] = mapped_column(Integer, nullable=False, default=DIAS_PREAVISO)
    # Si su caducidad bloquea. No todo bloquea: el certificado de calidad es
    # deseable y el seguro de responsabilidad civil no lo es.
    bloquea_al_vencer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "cuenta_id", "clave", name="uq_documento_proveedor"),
        Index("ix_documentos_proveedor_vencen", "tenant_id", "valido_hasta"),
    )


class ContactoProveedor(Base, TimestampMixin):
    """A quién se llama, y para qué."""

    __tablename__ = "contactos_proveedor"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    funcion: Mapped[str] = mapped_column(String(20), nullable=False)
    nombre: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", info={"sensibilidad": "personal"}
    )
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, default="", info={"sensibilidad": "personal"}
    )
    telefono: Mapped[str] = mapped_column(
        String(40), nullable=False, default="", info={"sensibilidad": "personal"}
    )
    # Fuera del horario, para el escalado. Es el dato que nadie tiene cuando hace
    # falta, a las once de la noche.
    fuera_de_horario: Mapped[str] = mapped_column(
        String(40), nullable=False, default="", info={"sensibilidad": "personal"}
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "cuenta_id", "funcion", "email", name="uq_contacto_prov"),
    )


# ── El proveedor es una cuenta (CRM-09.01.01.01) ──────────────────────────


def marcar_como_proveedor(uow: UnidadDeTrabajo, *, cuenta_id: UUID) -> dict[str, Any]:
    """Añade el rol de proveedor a una cuenta que ya existe.

    **Se añade, no se sustituye.** La misma empresa puede ser cliente de una
    división y proveedor de otra, y quitarle el rol de cliente para ponerle el de
    proveedor le aplicaría las condiciones de la ficha equivocada.
    """
    # Importado aquí y no arriba: `modelos` importa este módulo para registrar
    # sus tablas, y al revés sería un ciclo.
    from services.party.modelos import Cuenta

    cuenta = uow.db.get(Cuenta, cuenta_id)
    if cuenta is None or cuenta.tenant_id != uow.tenant_id:
        raise NoEncontrado("Esa cuenta no existe", error_code="proveedor.cuenta_no_existe")
    # Marcar a una cuenta como proveedor es escribir en ella: pasa por el mismo
    # punto de decisión que cualquier otra escritura, o sería una puerta lateral
    # para modificar cuentas que uno no puede tocar.
    exigir(uow.db, objeto="cuenta", accion="write", registro=cuenta, tenant_id=uow.tenant_id)
    roles = list(cuenta.roles or [])
    if ROL_PROVEEDOR not in roles:
        roles.append(ROL_PROVEEDOR)
        cuenta.roles = roles
        uow.db.flush()
    return {
        "cuenta_id": str(cuenta_id),
        "roles": roles,
        "porque": (
            "Los roles se suman. La misma empresa puede ser cliente de una división y "
            "proveedor de otra, y sustituir el rol le aplicaría las condiciones de la "
            "ficha equivocada."
        ),
    }


def exigir_proveedor(db: Session, tenant_id: UUID, cuenta_id: UUID) -> "Cuenta":
    """Comprueba que esa cuenta es realmente un proveedor de este tenant."""
    from services.party.modelos import Cuenta

    cuenta = db.get(Cuenta, cuenta_id)
    if cuenta is None or cuenta.tenant_id != tenant_id:
        raise NoEncontrado("Esa cuenta no existe", error_code="proveedor.cuenta_no_existe")
    # Las reglas de visibilidad de una cuenta valen también cuando se la mira
    # como proveedor: sin esto, preguntar por sus papeles sería una forma de leer
    # cuentas que no te tocan.
    exigir(db, objeto="cuenta", accion="read", registro=cuenta, tenant_id=tenant_id)
    if ROL_PROVEEDOR not in (cuenta.roles or []):
        raise ErrorValidacion(
            f"«{cuenta.nombre}» no tiene el rol de proveedor. Tratarla como tal sin "
            "declararlo hace que no aparezca en ninguna lista de proveedores y que "
            "nadie revise sus papeles.",
            error_code="proveedor.sin_rol",
        )
    return cuenta


# ── Homologación (CRM-09.01.01.02) ────────────────────────────────────────


def homologar(
    uow: UnidadDeTrabajo,
    *,
    cuenta_id: UUID,
    categoria: str,
    requisitos: list[dict[str, Any]],
    valida_hasta: date | None,
    revisada_por: UUID,
) -> Homologacion:
    """Homologa a un proveedor **para una categoría**, con fecha de fin.

    Dos cosas que no se negocian:

    **Sin todos los requisitos cubiertos no se homologa.** Homologar «con
    salvedades» es homologar: nadie vuelve a mirar la salvedad, y el día que pasa
    algo la salvedad era justo eso.

    **Sin fecha de fin tampoco.** Una homologación eterna es una que nadie revisa:
    a los cinco años nadie sabe si aquella empresa sigue teniendo los medios que
    tenía cuando se la aprobó.
    """
    exigir_proveedor(uow.db, uow.tenant_id, cuenta_id)
    faltan = [r.get("clave") for r in requisitos if not r.get("cubierto")]
    if faltan:
        raise ErrorValidacion(
            f"Faltan requisitos de la categoría «{categoria}»: {', '.join(str(f) for f in faltan)}. "
            "Homologar «con salvedades» es homologar: nadie vuelve a mirar la "
            "salvedad, y el día que pasa algo la salvedad era justo eso.",
            error_code="proveedor.requisitos_incompletos",
            detalle={"faltan": faltan},
        )
    if valida_hasta is None:
        raise ErrorValidacion(
            "Una homologación sin fecha de fin es una que nadie revisa: a los cinco "
            "años nadie sabe si esa empresa sigue teniendo los medios que tenía.",
            error_code="proveedor.homologacion_sin_fin",
        )
    if valida_hasta <= _hoy():
        raise ErrorValidacion(
            "La fecha de fin ya ha pasado", error_code="proveedor.homologacion_caducada"
        )

    fila = uow.db.execute(
        select(Homologacion).where(
            Homologacion.tenant_id == uow.tenant_id,
            Homologacion.cuenta_id == cuenta_id,
            Homologacion.categoria == categoria,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = Homologacion(tenant_id=uow.tenant_id, cuenta_id=cuenta_id, categoria=categoria)
        uow.db.add(fila)
    if fila.estado == "rechazada":
        raise Conflicto(
            f"«{categoria}» está rechazada para este proveedor. Rechazada no es "
            "caducada: volver a homologarlo sin revisar el motivo es repetir la "
            "decisión que alguien tomó por algo.",
            error_code="proveedor.estaba_rechazada",
            detalle={"motivo": fila.motivo},
        )

    fila.requisitos = requisitos
    fila.valida_hasta = valida_hasta
    fila.estado = "homologado"
    fila.revisada_por = revisada_por
    fila.motivo = ""
    uow.db.flush()
    return fila


def esta_homologado(
    db: Session, tenant_id: UUID, *, cuenta_id: UUID, categoria: str, hoy: date | None = None
) -> dict[str, Any]:
    """Si se le puede encargar algo de esa categoría, hoy.

    La respuesta distingue **«no está homologado» de «se le caducó»**: la primera
    exige empezar el proceso y la segunda solo papel nuevo, y confundirlas hace
    que se descarte a un proveedor que valdría mañana.
    """
    momento = hoy or _hoy()
    fila = db.execute(
        select(Homologacion).where(
            Homologacion.tenant_id == tenant_id,
            Homologacion.cuenta_id == cuenta_id,
            Homologacion.categoria == categoria,
        )
    ).scalar_one_or_none()
    if fila is None:
        return {
            "puede": False,
            "motivo": "sin_homologar",
            "que_hacer": (
                f"No está homologado para «{categoria}». Homologado para otra cosa no "
                "vale: uno puede servir material de oficina y no hacer trabajos en "
                "altura."
            ),
        }
    if fila.estado == "rechazada":
        return {"puede": False, "motivo": "rechazada", "que_hacer": fila.motivo}
    if fila.estado == "suspendido":
        return {"puede": False, "motivo": "suspendido", "que_hacer": fila.motivo}
    if fila.valida_hasta and fila.valida_hasta < momento:
        return {
            "puede": False,
            "motivo": "caducada",
            "vencio_el": fila.valida_hasta.isoformat(),
            "que_hacer": (
                "Se le caducó la homologación. No hay que empezar de cero: hace falta "
                "papel nuevo, y eso son días, no semanas."
            ),
        }
    if fila.estado != "homologado":
        return {"puede": False, "motivo": fila.estado, "que_hacer": "Está en trámite."}
    return {
        "puede": True,
        "valida_hasta": fila.valida_hasta.isoformat() if fila.valida_hasta else None,
    }


# ── Documentos con vigencia (CRM-09.01.01.03) ─────────────────────────────


def registrar_documento(
    uow: UnidadDeTrabajo,
    *,
    cuenta_id: UUID,
    clave: str,
    nombre: str,
    referencia: str,
    valido_hasta: date | None,
    valido_desde: date | None = None,
    dias_preaviso: int = DIAS_PREAVISO,
    bloquea_al_vencer: bool = True,
) -> DocumentoProveedor:
    """Registra un papel obligatorio con su vigencia.

    **El fichero no se guarda aquí**: se referencia en el gestor documental, que
    ya existe y ya cifra. Tener dos sitios donde viven documentos deja uno de los
    dos sin cifrar, y será justo el que nadie recuerda.

    Y un documento **sin fecha de fin** se admite solo si de verdad no caduca: si
    caduca y no consta, no se puede avisar de nada y el aviso es el noventa por
    ciento del valor de esto.
    """
    exigir_proveedor(uow.db, uow.tenant_id, cuenta_id)
    if not referencia.strip():
        raise ErrorValidacion(
            "Un documento sin referencia al gestor documental es una fila que dice que "
            "el papel existe sin que nadie pueda verlo.",
            error_code="proveedor.documento_sin_referencia",
        )
    fila = uow.db.execute(
        select(DocumentoProveedor).where(
            DocumentoProveedor.tenant_id == uow.tenant_id,
            DocumentoProveedor.cuenta_id == cuenta_id,
            DocumentoProveedor.clave == clave,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = DocumentoProveedor(tenant_id=uow.tenant_id, cuenta_id=cuenta_id, clave=clave)
        uow.db.add(fila)
    fila.nombre = nombre
    fila.referencia = referencia.strip()
    fila.valido_desde = valido_desde
    fila.valido_hasta = valido_hasta
    fila.dias_preaviso = max(0, dias_preaviso)
    fila.bloquea_al_vencer = bloquea_al_vencer
    uow.db.flush()
    return fila


def estado_documental(
    db: Session, tenant_id: UUID, *, cuenta_id: UUID, hoy: date | None = None
) -> dict[str, Any]:
    """Qué papeles le faltan, cuáles vencen pronto y cuáles ya vencieron.

    **Lo vencido que bloquea, bloquea solo.** Un certificado caducado que hay que
    mirar a mano no se mira: se descubre el día que el cliente pregunta quién hizo
    el trabajo y con qué seguro.

    Y se avisa **antes**, con el plazo de cada documento: renovar un seguro lleva
    semanas, así que avisar el mismo día que vence es no avisar.
    """
    momento = hoy or _hoy()
    filas = list(
        db.execute(
            select(DocumentoProveedor).where(
                DocumentoProveedor.tenant_id == tenant_id,
                DocumentoProveedor.cuenta_id == cuenta_id,
            )
        )
        .scalars()
        .all()
    )

    vencidos: list[dict[str, Any]] = []
    por_vencer: list[dict[str, Any]] = []
    sin_caducidad: list[str] = []

    for fila in filas:
        if fila.valido_hasta is None:
            sin_caducidad.append(fila.clave)
            continue
        dias = (fila.valido_hasta - momento).days
        entrada = {
            "clave": fila.clave,
            "nombre": fila.nombre,
            "vence": fila.valido_hasta.isoformat(),
            "dias": dias,
            "bloquea": fila.bloquea_al_vencer,
        }
        if dias < 0:
            vencidos.append(entrada)
        elif dias <= fila.dias_preaviso:
            por_vencer.append(entrada)

    bloqueantes = [v for v in vencidos if v["bloquea"]]
    return {
        "documentos": len(filas),
        "vencidos": vencidos,
        "por_vencer": sorted(por_vencer, key=lambda d: d["dias"]),
        "sin_fecha_de_caducidad": sin_caducidad,
        "bloqueado": bool(bloqueantes),
        "porque": (
            f"{len(bloqueantes)} documentos vencidos de los que bloquean."
            if bloqueantes
            else "Ningún documento vencido de los que bloquean."
        ),
        "medible": bool(filas),
        "aviso": (
            "No consta ningún documento de este proveedor. Eso no es que esté todo en "
            "regla: es que no se ha pedido nada."
            if not filas
            else ""
        ),
    }


def documentos_que_vencen(
    db: Session, tenant_id: UUID, *, dias: int = DIAS_PREAVISO, hoy: date | None = None
) -> dict[str, Any]:
    """La lista de trabajo: qué hay que renovar y de quién.

    Ordenada por lo que vence antes, y con lo que **ya venció** primero: eso no es
    un aviso, es un problema que está pasando ahora.
    """
    momento = hoy or _hoy()
    limite = momento + timedelta(days=dias)
    filas = list(
        db.execute(
            select(DocumentoProveedor).where(
                DocumentoProveedor.tenant_id == tenant_id,
                DocumentoProveedor.valido_hasta.is_not(None),
                DocumentoProveedor.valido_hasta <= limite,
            )
        )
        .scalars()
        .all()
    )
    return {
        "ya_vencidos": [
            {"cuenta_id": str(f.cuenta_id), "clave": f.clave, "vencio": f.valido_hasta.isoformat()}
            for f in filas
            if f.valido_hasta and f.valido_hasta < momento
        ],
        "por_vencer": [
            {
                "cuenta_id": str(f.cuenta_id),
                "clave": f.clave,
                "vence": f.valido_hasta.isoformat(),
                "dias": (f.valido_hasta - momento).days,
            }
            for f in sorted(filas, key=lambda x: x.valido_hasta or momento)
            if f.valido_hasta and f.valido_hasta >= momento
        ],
    }


# ── Riesgo (CRM-09.01.01.04) ──────────────────────────────────────────────


def riesgo_de_dependencia(
    *,
    proveedores: list[dict[str, Any]],
    umbral_concentracion: float = 40.0,
) -> dict[str, Any]:
    """Dónde duele si un proveedor falla mañana.

    Lo que hace daño **no es un proveedor malo**: un proveedor malo se cambia. Lo
    que hace daño es un proveedor bueno del que se depende, del que sale el 60 %
    de lo que se sirve y que no tiene alternativa homologada — porque el día que
    tiene un incendio no hay nada que decidir, solo que contar.

    Por eso lo que se mide es la **concentración** y la **alternativa**, no la
    opinión que se tenga de cada uno.
    """
    total = sum(float(p.get("volumen") or 0) for p in proveedores)
    if total <= 0:
        return {
            "medible": False,
            "porque": (
                "No hay volumen registrado por proveedor. Sin eso no se puede hablar de "
                "concentración: se puede opinar, que no es lo mismo."
            ),
        }

    filas = []
    for p in proveedores:
        pct = float(p.get("volumen") or 0) / total * 100
        alternativas = list(p.get("alternativas_homologadas") or [])
        filas.append(
            {
                "cuenta_id": str(p.get("id")),
                "nombre": p.get("nombre"),
                "pct_del_volumen": round(pct, 1),
                "alternativas_homologadas": len(alternativas),
                "critico": pct >= umbral_concentracion and not alternativas,
            }
        )

    criticos = [f for f in filas if f["critico"]]
    return {
        "medible": True,
        "proveedores": sorted(filas, key=lambda f: -f["pct_del_volumen"]),
        "criticos": criticos,
        "que_significa": (
            "Ningún proveedor concentra volumen sin alternativa."
            if not criticos
            else f"{len(criticos)} proveedores concentran más del {umbral_concentracion} % "
            "y no tienen alternativa homologada. El día que uno falle no habrá nada que "
            "decidir: solo que contar."
        ),
        "que_hacer": (
            ""
            if not criticos
            else "Homologar una alternativa cuesta semanas y se hace antes, no el día "
            "del incendio."
        ),
    }


# ── Evaluación con hechos (CRM-09.01.01.05) ───────────────────────────────


def evaluar(
    *,
    entregas: list[dict[str, Any]],
    incidencias: list[dict[str, Any]],
    encuesta: int | None = None,
) -> dict[str, Any]:
    """Cómo va este proveedor, **con hechos**.

    Una encuesta anual mide la relación con el comercial del proveedor, que es una
    cosa legítima y no es el servicio. El plazo cumplido y las incidencias sí lo
    miden, y son números que ya están en el sistema: no hay que pedirle a nadie
    que rellene nada.

    Y si no hay entregas **no se puntúa**: un proveedor al que no se le ha
    encargado nada no es un buen proveedor, es uno del que no se sabe.
    """
    if not entregas:
        return {
            "medible": False,
            "porque": (
                "No consta ninguna entrega. Un proveedor al que no se le ha encargado "
                "nada no es bueno ni malo: no se sabe."
            ),
            "encuesta": encuesta,
        }

    a_tiempo = [e for e in entregas if e.get("en_plazo")]
    graves = [i for i in incidencias if str(i.get("gravedad")) in ("alta", "critica")]
    pct_plazo = len(a_tiempo) / len(entregas) * 100

    return {
        "medible": True,
        "entregas": len(entregas),
        "pct_en_plazo": round(pct_plazo, 1),
        "incidencias": len(incidencias),
        "incidencias_graves": len(graves),
        "incidencias_por_entrega": round(len(incidencias) / len(entregas), 2),
        "encuesta": encuesta,
        "que_significa": (
            f"{round(pct_plazo, 1)} % en plazo sobre {len(entregas)} entregas."
            + (
                f" Y {len(graves)} incidencias graves, que pesan más que el porcentaje: "
                "una sola puede costar un cliente."
                if graves
                else ""
            )
        ),
        "aviso": (
            ""
            if encuesta is None
            else "La encuesta mide la relación con su comercial, que es otra cosa. Lo "
            "que mide el servicio es el plazo y las incidencias."
        ),
    }


# ── Contactos por función (CRM-09.01.01.06) ───────────────────────────────


def registrar_contacto(
    uow: UnidadDeTrabajo,
    *,
    cuenta_id: UUID,
    funcion: str,
    nombre: str,
    email: str,
    telefono: str = "",
    fuera_de_horario: str = "",
) -> ContactoProveedor:
    """Registra a quién se llama y para qué."""
    exigir_proveedor(uow.db, uow.tenant_id, cuenta_id)
    if funcion not in FUNCIONES_CONTACTO:
        raise ErrorValidacion(
            f"Función «{funcion}» desconocida",
            error_code="proveedor.funcion_invalida",
            detalle={"admitidas": list(FUNCIONES_CONTACTO)},
        )
    correo = email.strip().lower()
    fila = uow.db.execute(
        select(ContactoProveedor).where(
            ContactoProveedor.tenant_id == uow.tenant_id,
            ContactoProveedor.cuenta_id == cuenta_id,
            ContactoProveedor.funcion == funcion,
            ContactoProveedor.email == correo,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = ContactoProveedor(
            tenant_id=uow.tenant_id, cuenta_id=cuenta_id, funcion=funcion, email=correo
        )
        uow.db.add(fila)
    fila.nombre = nombre
    fila.telefono = telefono
    fila.fuera_de_horario = fuera_de_horario
    uow.db.flush()
    return fila


def a_quien_llamo(
    db: Session, tenant_id: UUID, *, cuenta_id: UUID, funcion: str = "escalado"
) -> dict[str, Any]:
    """A quién se llama cuando esto falla.

    Y si **no hay nadie para escalar se dice**, en vez de devolver el comercial:
    dar el teléfono del comercial a las once de la noche no es una respuesta, es
    perder media hora antes de descubrir que no hay nadie.
    """
    filas = list(
        db.execute(
            select(ContactoProveedor).where(
                ContactoProveedor.tenant_id == tenant_id,
                ContactoProveedor.cuenta_id == cuenta_id,
            )
        )
        .scalars()
        .all()
    )
    de_la_funcion = [f for f in filas if f.funcion == funcion]
    if not de_la_funcion:
        return {
            "hay": False,
            "funcion": funcion,
            "porque": (
                f"No consta ningún contacto de «{funcion}» para este proveedor. No se "
                "devuelve el comercial en su lugar: su teléfono a las once de la noche "
                "no es una respuesta, es media hora perdida."
            ),
            "funciones_que_si_hay": sorted({f.funcion for f in filas}),
        }
    return {
        "hay": True,
        "contactos": [
            {
                "nombre": f.nombre,
                "email": f.email,
                "telefono": f.telefono,
                "fuera_de_horario": f.fuera_de_horario,
            }
            for f in de_la_funcion
        ],
        "sin_telefono_fuera_de_horario": [
            f.nombre for f in de_la_funcion if funcion == "escalado" and not f.fuera_de_horario
        ],
    }


# ── Baja del proveedor (CRM-09.01.01.10) ──────────────────────────────────


def puede_darse_de_baja(
    *, compromisos_abiertos: list[dict[str, Any]], alternativas_homologadas: int
) -> dict[str, Any]:
    """Si se puede dar de baja a un proveedor, y qué pasa con lo comprometido.

    **No se da de baja lo que tiene trabajo comprometido con clientes.** Quitarlo
    del maestro no cancela lo que ya se vendió: lo que hace es que el día de la
    entrega nadie sepa quién tenía que ir.

    Y si es el único homologado para algo, la baja **deja un hueco**, no un
    problema del futuro: hay que decirlo antes, porque homologar a otro lleva
    semanas.
    """
    if compromisos_abiertos:
        return {
            "puede": False,
            "compromisos": len(compromisos_abiertos),
            "porque": (
                f"Tiene {len(compromisos_abiertos)} compromisos abiertos con clientes. "
                "Darlo de baja no los cancela: hace que el día de la entrega nadie sepa "
                "quién tenía que ir."
            ),
            "que_hacer": "Reasignarlos o cerrarlos antes de la baja.",
        }
    return {
        "puede": True,
        "deja_hueco": alternativas_homologadas == 0,
        "aviso": (
            ""
            if alternativas_homologadas
            else "Es el único homologado para lo suyo. La baja deja un hueco desde el "
            "primer día, y homologar a otro lleva semanas: conviene tenerlo antes."
        ),
    }
