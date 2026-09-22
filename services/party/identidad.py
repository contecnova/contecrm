"""Resolución de identidad entre canales (CRM-01.01.05.02).

La misma persona llega como `ana@empresa.com` en el correo, como `+34600…` en el
móvil, como una cookie en la web y como `AC-9912` en el ERP. Sin resolverlo, el
CRM tiene cuatro fichas de una persona y ninguna sabe lo que hicieron las otras —
que es exactamente lo que hace que las interacciones entrantes se queden sin
atribuir (`CRM-01.02.01.04`).

Resolver identidades es peligroso por lo que se rompe cuando se hace mal: **unir
dos personas distintas es peor que no unirlas**. Alguien ve el historial de otro
cliente, y eso no se deshace. De ahí las cuatro decisiones:

**Hay señales fuertes y señales débiles, y no valen igual.** Un NIF o un
identificador de ERP identifican; un teléfono fijo compartido por una oficina, no.
Cada señal declara su peso, y por debajo del umbral **se propone, no se une**.

**Unir siempre es reversible y deja rastro.** Se guarda qué señales lo
justificaron y quién lo aprobó. Sin eso, deshacer una unión equivocada es
adivinar qué era de quién.

**La confianza se declara con la señal, no se deduce del parecido.** Un nombre
parecido no une nada: «García» hay miles, y unir por nombre es cómo se acaban
mezclando dos clientes con el mismo apellido.

**Lo automático tiene un listón más alto que lo manual.** Una persona que une dos
fichas está mirando las dos; un proceso nocturno no mira nada.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from crmcore.runtime import settings as rt
from sqlalchemy import (
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

logger = get_logger(__name__)

# Tipos de señal y cuánto pesan, de 0 a 100. Los pesos por defecto son eso —por
# defecto— y se pueden ajustar por tenant: en una empresa donde cada empleado
# tiene móvil de empresa, el teléfono identifica; en otra donde comparten
# centralita, no.
#
# El criterio: **pesa lo que no comparten dos personas distintas**.
PESOS: dict[str, int] = {
    "nif": 95,
    "id_erp": 95,
    "email": 80,
    # Un móvil identifica bastante; un fijo de oficina lo comparte media planta,
    # y por eso el peso es medio y no alto.
    "telefono": 55,
    "cookie": 40,
    "id_app": 70,
    # El nombre NO une: «García» hay miles. Se guarda como señal para poder
    # explicar una propuesta, con peso casi nulo.
    "nombre": 5,
}

# Umbrales por defecto. Lo automático pide más que lo manual porque una persona
# que une dos fichas está mirando las dos, y un proceso nocturno no mira nada.
UMBRAL_AUTOMATICO = 150
UMBRAL_PROPUESTA = 80

RE_NO_DIGITOS = re.compile(r"\D")


class Senal(Base, TimestampMixin):
    """Un identificador observado de alguien (CRM-01.01.05.02).

    Se guarda **con huella y no en claro** cuando es un dato de contacto: una
    tabla de identidades es un índice de todos los correos y teléfonos del CRM, y
    no hace falta leerla para cruzarla.
    """

    __tablename__ = "senales_identidad"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    # Huella normalizada del valor: minúsculas, sin espacios, sin prefijos.
    huella: Mapped[str] = mapped_column(String(64), nullable=False)
    # Últimos caracteres, para poder enseñar de qué señal se habla sin exponerla
    # entera. «Termina en 4321» es suficiente para que una persona la reconozca.
    pista: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    contacto_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    origen: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    peso: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vista_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    veces: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("tenant_id", "tipo", "huella", "contacto_id", name="uq_senal_identidad"),
        Index("ix_senales_huella", "tenant_id", "tipo", "huella"),
    )


class Union(Base, TimestampMixin):
    """Dos identidades declaradas la misma persona.

    Reversible a propósito: unir mal es peor que no unir, y deshacerlo sin saber
    qué señales lo justificaron es adivinar qué era de quién.
    """

    __tablename__ = "uniones_identidad"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    principal_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    secundario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    puntuacion: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Qué lo justificó: [{tipo, pista, peso}]. Es lo que permite revisar la
    # decisión y lo que se enseña al deshacerla.
    senales: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # automatica | manual | propuesta
    modo: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    aprobada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    deshecha_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_deshacer: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "principal_id", "secundario_id", name="uq_union_identidad"),
        Index("ix_uniones_identidad", "tenant_id", "principal_id", "deshecha_at"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def normalizar(tipo: str, valor: str) -> tuple[str, str]:
    """Normaliza una señal y devuelve (huella, pista).

    La normalización es donde se gana o se pierde todo: `Ana@Empresa.com ` y
    `ana@empresa.com` son la misma persona, y `+34 600 11 22 33` y `600112233`
    también. Sin normalizar, el cruce no encuentra nada y parece que no hay
    duplicados.
    """
    crudo = (valor or "").strip()
    if tipo == "email":
        limpio = crudo.lower()
        pista = limpio.split("@")[0][:3] + "…@" + limpio.split("@")[-1] if "@" in limpio else ""
    elif tipo == "telefono":
        limpio = RE_NO_DIGITOS.sub("", crudo)
        # Se comparan los últimos nueve dígitos: es lo que hace que el mismo
        # número con y sin prefijo de país case, sin inventarse el país.
        limpio = limpio[-9:] if len(limpio) > 9 else limpio
        pista = "…" + limpio[-4:] if len(limpio) >= 4 else limpio
    elif tipo == "nif":
        limpio = re.sub(r"[^A-Z0-9]", "", crudo.upper())
        pista = "…" + limpio[-4:] if len(limpio) >= 4 else limpio
    else:
        limpio = crudo.lower()
        pista = limpio[:6] + "…" if len(limpio) > 6 else limpio
    return hashlib.sha256(f"{tipo}:{limpio}".encode()).hexdigest(), pista


def observar(
    uow: UnidadDeTrabajo,
    *,
    tipo: str,
    valor: str,
    contacto_id: UUID | None = None,
    cuenta_id: UUID | None = None,
    origen: str = "",
    peso: int | None = None,
) -> Senal:
    """Anota que se ha visto esta señal, opcionalmente atada a un contacto."""
    if tipo not in PESOS:
        raise ErrorValidacion(
            f"Tipo de señal «{tipo}» no reconocido.",
            error_code="identidad.tipo_no_valido",
            detalle={"validos": sorted(PESOS)},
        )
    if not (valor or "").strip():
        raise ErrorValidacion(
            "Una señal vacía no identifica a nadie.", error_code="identidad.valor_vacio"
        )
    huella, pista = normalizar(tipo, valor)
    fila = uow.db.execute(
        select(Senal).where(
            Senal.tenant_id == uow.tenant_id,
            Senal.tipo == tipo,
            Senal.huella == huella,
            Senal.contacto_id == contacto_id,
        )
    ).scalar_one_or_none()
    if fila is not None:
        fila.veces += 1
        fila.vista_at = _ahora()
        if cuenta_id and not fila.cuenta_id:
            fila.cuenta_id = cuenta_id
        uow.db.flush()
        return fila

    fila = Senal(
        tenant_id=uow.tenant_id,
        tipo=tipo,
        huella=huella,
        pista=pista,
        contacto_id=contacto_id,
        cuenta_id=cuenta_id,
        origen=origen,
        peso=int(peso if peso is not None else PESOS[tipo]),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def resolver(
    db: Session,
    tenant_id: UUID,
    *,
    senales: list[dict[str, str]],
    umbral: int | None = None,
) -> dict[str, Any]:
    """A quién corresponden estas señales, **y con qué confianza**
    (CRM-01.01.05.02).

    Devuelve los candidatos con su puntuación y con **qué señales coincidieron**,
    no un identificador a secas: una resolución sin explicación no se puede
    revisar, y aquí equivocarse significa enseñarle a alguien el historial de otro.

    Por debajo del umbral **no resuelve**: propone. Decir «es este» con un
    teléfono de centralita compartida es cómo se mezclan dos clientes.
    """
    minimo = int(
        umbral if umbral is not None else (rt.efectivo("identidad_umbral", db) or UMBRAL_PROPUESTA)
    )
    coincidencias: dict[str, dict[str, Any]] = {}
    sin_reconocer: list[str] = []

    for cruda in senales:
        tipo = str(cruda.get("tipo") or "")
        valor = str(cruda.get("valor") or "")
        if tipo not in PESOS or not valor.strip():
            sin_reconocer.append(tipo or "(sin tipo)")
            continue
        huella, pista = normalizar(tipo, valor)
        filas = (
            db.execute(
                select(Senal).where(
                    Senal.tenant_id == tenant_id,
                    Senal.tipo == tipo,
                    Senal.huella == huella,
                    Senal.contacto_id.is_not(None),
                )
            )
            .scalars()
            .all()
        )
        # Una señal que apunta a varios contactos **pesa menos**, no más: un
        # teléfono que comparten cinco personas no identifica a ninguna. Sin esto,
        # la centralita de una empresa uniría a toda su plantilla.
        compartida = len(filas) > 1
        for fila in filas:
            clave = str(fila.contacto_id)
            entrada = coincidencias.setdefault(
                clave,
                {"contacto_id": clave, "puntuacion": 0, "senales": [], "cuenta_id": None},
            )
            peso = fila.peso // len(filas) if compartida else fila.peso
            entrada["puntuacion"] += peso
            entrada["senales"].append(
                {"tipo": tipo, "pista": pista, "peso": peso, "compartida": compartida}
            )
            if fila.cuenta_id and not entrada["cuenta_id"]:
                entrada["cuenta_id"] = str(fila.cuenta_id)

    candidatos = sorted(coincidencias.values(), key=lambda c: -c["puntuacion"])
    mejor = candidatos[0] if candidatos else None
    segundo = candidatos[1] if len(candidatos) > 1 else None
    # Dos candidatos empatados o casi es peor que ninguno: elegir uno es jugársela
    # a cara o cruz con el historial de un cliente.
    ambiguo = bool(mejor and segundo and (mejor["puntuacion"] - segundo["puntuacion"]) < 20)

    resuelto = bool(mejor and mejor["puntuacion"] >= minimo and not ambiguo)
    return {
        "resuelto": resuelto,
        "contacto_id": mejor["contacto_id"] if resuelto else None,
        "cuenta_id": mejor.get("cuenta_id") if resuelto else None,
        "puntuacion": mejor["puntuacion"] if mejor else 0,
        "umbral": minimo,
        "candidatos": candidatos[:5],
        "ambiguo": ambiguo,
        "senales_no_reconocidas": sin_reconocer,
        "porque": (
            "Resuelto: las señales coinciden por encima del umbral."
            if resuelto
            else (
                "Hay dos candidatos casi empatados: elegir uno sería enseñarle a "
                "alguien el historial de otro."
                if ambiguo
                else (
                    f"La mejor coincidencia suma {mejor['puntuacion']} y el umbral es "
                    f"{minimo}: se propone, no se afirma."
                    if mejor
                    else "Ninguna señal coincide con nadie conocido."
                )
            )
        ),
    }


def proponer_uniones(
    db: Session, tenant_id: UUID, *, umbral: int | None = None, limite: int = 50
) -> dict[str, Any]:
    """Pares de contactos que parecen la misma persona.

    **Propone**: unir automáticamente dos personas distintas enseña a una el
    historial de la otra, y eso no se deshace aunque se deshaga la unión. Las
    propuestas se revisan.
    """
    minimo = int(
        umbral if umbral is not None else (rt.efectivo("identidad_umbral", db) or UMBRAL_PROPUESTA)
    )
    filas = (
        db.execute(
            select(Senal).where(Senal.tenant_id == tenant_id, Senal.contacto_id.is_not(None))
        )
        .scalars()
        .all()
    )
    por_huella: dict[tuple[str, str], list[Senal]] = {}
    for fila in filas:
        por_huella.setdefault((fila.tipo, fila.huella), []).append(fila)

    pares: dict[tuple[str, str], dict[str, Any]] = {}
    for (tipo, _), grupo in por_huella.items():
        contactos = sorted({str(f.contacto_id) for f in grupo})
        if len(contactos) < 2:
            continue
        peso = PESOS.get(tipo, 0)
        # Una señal que comparten muchos no une: reparte su peso. Con cinco
        # contactos en el mismo fijo, ese fijo no dice casi nada.
        peso = peso // max(1, len(contactos) - 1)
        for i, uno in enumerate(contactos):
            for otro in contactos[i + 1 :]:
                entrada = pares.setdefault(
                    (uno, otro), {"a": uno, "b": otro, "puntuacion": 0, "senales": []}
                )
                entrada["puntuacion"] += peso
                entrada["senales"].append({"tipo": tipo, "peso": peso, "pista": grupo[0].pista})

    ya_unidos = {
        (str(u.principal_id), str(u.secundario_id))
        for u in db.execute(
            select(Union).where(Union.tenant_id == tenant_id, Union.deshecha_at.is_(None))
        ).scalars()
    }
    propuestas = [
        p
        for clave, p in pares.items()
        if p["puntuacion"] >= minimo
        and clave not in ya_unidos
        and (clave[1], clave[0]) not in ya_unidos
    ]
    propuestas.sort(key=lambda p: -p["puntuacion"])
    return {
        "umbral": minimo,
        "propuestas": propuestas[:limite],
        "cuantas": len(propuestas),
        # Las que además pasan el listón automático: se señalan, pero **tampoco se
        # unen solas**. Es una lista de revisión rápida, no una cola de ejecución.
        "muy_probables": len([p for p in propuestas if p["puntuacion"] >= UMBRAL_AUTOMATICO]),
        "medible": bool(filas),
    }


def unir(
    uow: UnidadDeTrabajo,
    *,
    principal_id: UUID,
    secundario_id: UUID,
    senales: list[dict[str, Any]] | None = None,
    puntuacion: int = 0,
    modo: str = "manual",
    por: UUID | None = None,
) -> Union:
    """Declara que dos contactos son la misma persona.

    **No borra el secundario.** Marcarlo como el mismo y conservarlo es lo que
    permite deshacerlo: fundirlos de verdad haría que un error fuera definitivo, y
    los errores aquí se descubren semanas después, cuando alguien ve en su ficha
    una conversación que no tuvo.
    """
    if principal_id == secundario_id:
        raise ErrorValidacion(
            "Un contacto no se une consigo mismo.", error_code="identidad.union_de_si_mismo"
        )
    if modo == "automatica" and puntuacion < UMBRAL_AUTOMATICO:
        raise Conflicto(
            "Una unión automática necesita una puntuación mucho más alta que una "
            "manual: quien une a mano está mirando las dos fichas, y un proceso "
            "nocturno no mira nada.",
            error_code="identidad.puntuacion_insuficiente",
            detalle={"puntuacion": puntuacion, "umbral_automatico": UMBRAL_AUTOMATICO},
        )
    ya = uow.db.execute(
        select(Union).where(
            Union.tenant_id == uow.tenant_id,
            Union.principal_id == principal_id,
            Union.secundario_id == secundario_id,
        )
    ).scalar_one_or_none()
    if ya is not None and ya.deshecha_at is None:
        return ya

    fila = ya or Union(
        tenant_id=uow.tenant_id, principal_id=principal_id, secundario_id=secundario_id
    )
    fila.puntuacion = puntuacion
    fila.senales = list(senales or [])
    fila.modo = modo
    fila.aprobada_por = por
    fila.deshecha_at = None
    fila.motivo_deshacer = ""
    if ya is None:
        uow.db.add(fila)
    uow.db.flush()
    registrar(
        uow.db,
        accion="identidad.union",
        objeto="contacto",
        objeto_id=principal_id,
        datos={
            "secundario": str(secundario_id),
            "modo": modo,
            "puntuacion": puntuacion,
            "senales": fila.senales,
        },
        tenant_id=uow.tenant_id,
    )
    uow.emitir(
        "identity.linked",
        subject=("contacto", principal_id),
        data={
            "principal_id": str(principal_id),
            "secundario_id": str(secundario_id),
            "modo": modo,
        },
    )
    return fila


def deshacer(
    uow: UnidadDeTrabajo, *, principal_id: UUID, secundario_id: UUID, motivo: str
) -> Union:
    """Deshace una unión, con motivo.

    El motivo importa más de lo que parece: si una regla une mal dos veces al
    mismo par, el texto de por qué se deshizo es lo único que lo explica.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Deshacer una unión exige motivo: si la regla vuelve a proponerla, eso "
            "es lo único que explica por qué estaba mal.",
            error_code="identidad.motivo_obligatorio",
        )
    fila = uow.db.execute(
        select(Union).where(
            Union.tenant_id == uow.tenant_id,
            Union.principal_id == principal_id,
            Union.secundario_id == secundario_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Esa unión no existe", error_code="identidad.union_no_encontrada")
    fila.deshecha_at = _ahora()
    fila.motivo_deshacer = motivo.strip()
    uow.db.flush()
    registrar(
        uow.db,
        accion="identidad.union_deshecha",
        objeto="contacto",
        objeto_id=principal_id,
        datos={"secundario": str(secundario_id), "motivo": motivo},
        tenant_id=uow.tenant_id,
    )
    return fila


def identidades_de(db: Session, tenant_id: UUID, contacto_id: UUID) -> dict[str, Any]:
    """Todas las señales y uniones vivas de un contacto.

    Las señales salen **con su pista, no con su valor**: para saber de cuál se
    habla basta con «termina en 4321», y una pantalla que enseña todos los correos
    y teléfonos del CRM junta es una exportación esperando a pasar.
    """
    senales = (
        db.execute(
            select(Senal).where(Senal.tenant_id == tenant_id, Senal.contacto_id == contacto_id)
        )
        .scalars()
        .all()
    )
    uniones = (
        db.execute(
            select(Union).where(
                Union.tenant_id == tenant_id,
                Union.principal_id == contacto_id,
                Union.deshecha_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    return {
        "contacto_id": str(contacto_id),
        "senales": [
            {
                "tipo": s.tipo,
                "pista": s.pista,
                "origen": s.origen,
                "veces": s.veces,
                "vista_at": s.vista_at.isoformat(),
            }
            for s in senales
        ],
        "unidos": [
            {
                "contacto_id": str(u.secundario_id),
                "modo": u.modo,
                "puntuacion": u.puntuacion,
                "senales": u.senales,
            }
            for u in uniones
        ],
        "canales": sorted({s.tipo for s in senales}),
        # Un contacto con una sola señal no se puede cruzar con nada: es el que
        # va a seguir apareciendo sin atribuir.
        "cruzable": len({s.tipo for s in senales}) > 1,
    }
