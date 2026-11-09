"""Segregación de funciones (CRM-07.03.02.06).

SoD es la regla más vieja del control interno: quien crea un proveedor no puede
aprobar su pago. En un CRM se traduce a pares de permisos que no deben coincidir
en la misma persona —dar de alta un descuento y aprobarlo, crear un usuario y
asignarle roles, exportar el maestro de clientes y borrar la auditoría—.

Vive en `identity` porque lo que compara son **permisos efectivos**, que salen
de los roles y de sus herencias, y eso solo lo sabe este servicio.

Dos decisiones que evitan que esto sea una alarma que nadie mira:

**Detecta, no impide.** Bloquear la asignación de un rol porque crearía un
conflicto deja al administrador sin poder operar y sin entender por qué. Lo que
hace falta es la lista de quién está en conflicto y desde cuándo, para
resolverlo con criterio.

**La excepción se aprueba y caduca.** Una organización pequeña tiene conflictos
inevitables: una persona es todo el departamento. Sin excepciones, el informe
sale siempre en rojo y se deja de mirar; con excepciones eternas, el rojo
desaparece y tampoco se mira. Se aprueban, con motivo y con fecha.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.errors import ErrorValidacion
from crmcore.fechas import hoy
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, Date, DateTime, Index, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

NIVELES = ("bajo", "medio", "alto", "critico")


class ReglaSoD(Base):
    """Un par de conjuntos de permisos que no deben coincidir en una persona."""

    __tablename__ = "sod_reglas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    codigo: Mapped[str] = mapped_column(String(40), nullable=False)
    nombre: Mapped[str] = mapped_column(String(300), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Dos conjuntos: tener algo de A y algo de B a la vez es el conflicto.
    permisos_a: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    permisos_b: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    nivel: Mapped[str] = mapped_column(
        String(10), nullable=False, default="alto", info={"opciones": NIVELES}
    )
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("uq_sod_regla", "tenant_id", "codigo", unique=True),)


class ExcepcionSoD(Base):
    """Un conflicto aprobado, con motivo y con fecha de caducidad."""

    __tablename__ = "sod_excepciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    regla_codigo: Mapped[str] = mapped_column(String(40), nullable=False)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    aprobada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    caduca_at: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_sod_excepciones", "tenant_id", "regla_codigo", "usuario_id"),)


def guardar_regla(
    db: Session,
    *,
    tenant_id: UUID,
    codigo: str,
    nombre: str,
    permisos_a: list[str],
    permisos_b: list[str],
    descripcion: str = "",
    nivel: str = "alto",
    activa: bool = True,
) -> ReglaSoD:
    if nivel not in NIVELES:
        raise ErrorValidacion(
            f"El nivel admite {', '.join(NIVELES)}", error_code="sod.nivel_invalido"
        )
    if not permisos_a or not permisos_b:
        raise ErrorValidacion(
            "Una regla de segregación necesita los dos lados",
            error_code="sod.regla_incompleta",
        )
    # Un permiso en los dos lados hace que la regla se dispare con solo tenerlo,
    # que no es segregar nada: es prohibirlo. Si eso es lo que se quiere, se
    # quita el permiso del rol, no se escribe una regla que miente sobre lo que
    # comprueba.
    solapados = sorted(set(permisos_a) & set(permisos_b))
    if solapados:
        raise ErrorValidacion(
            "Un mismo permiso no puede estar en los dos lados de la regla",
            error_code="sod.lados_solapados",
            detalle={"solapados": solapados},
        )

    fila = db.execute(
        select(ReglaSoD).where(ReglaSoD.tenant_id == tenant_id, ReglaSoD.codigo == codigo)
    ).scalar_one_or_none()
    if fila is None:
        fila = ReglaSoD(tenant_id=tenant_id, codigo=codigo)
        db.add(fila)
    fila.nombre = nombre
    fila.descripcion = descripcion
    fila.permisos_a = list(permisos_a)
    fila.permisos_b = list(permisos_b)
    fila.nivel = nivel
    fila.activa = activa
    db.flush()
    logger.info("sod.regla_guardada", codigo=codigo, nivel=nivel)
    return fila


def aprobar_excepcion(
    db: Session,
    *,
    tenant_id: UUID,
    regla_codigo: str,
    usuario_id: UUID,
    motivo: str,
    caduca_at: date,
    por: UUID | None = None,
) -> ExcepcionSoD:
    """Aprueba un conflicto concreto. Exige motivo y caducidad.

    Las dos condiciones juntas. Sin motivo, dentro de un año nadie sabe por qué
    se aprobó; sin caducidad, la excepción sobrevive a la persona, al puesto y a
    la razón que la justificaba.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Aprobar un conflicto exige motivo escrito", error_code="sod.excepcion_sin_motivo"
        )
    if caduca_at <= hoy(db):
        raise ErrorValidacion(
            "La excepción tiene que caducar en el futuro",
            error_code="sod.excepcion_ya_caducada",
        )
    fila = ExcepcionSoD(
        tenant_id=tenant_id,
        regla_codigo=regla_codigo,
        usuario_id=usuario_id,
        motivo=motivo.strip(),
        aprobada_por=por,
        caduca_at=caduca_at,
    )
    db.add(fila)
    db.flush()
    logger.warning(
        "sod.excepcion_aprobada",
        regla=regla_codigo,
        usuario=str(usuario_id),
        caduca=caduca_at.isoformat(),
    )
    return fila


def excepciones(
    db: Session, tenant_id: UUID, *, regla_codigo: str = "", incluir_caducadas: bool = False
) -> list[dict[str, Any]]:
    """Qué conflictos se han aprobado, para quién, por qué y hasta cuándo.

    **Faltaba, y es lo que convierte esto en un control.** Aprobar una excepción
    a la segregación de funciones exige motivo escrito y fecha de caducidad —el
    código lo obliga—, y **no había forma de leer ninguno de los dos**: la prueba
    de auditoría se generaba y se archivaba donde nadie podía recuperarla.

    Quien revisa un informe de segregación tiene que poder contestar «¿y éstos
    por qué están permitidos?», y esa respuesta estaba guardada en una tabla sin
    puerta.

    Por defecto sólo las vigentes: una lista con las de hace tres años obliga a
    filtrar a mano justo cuando se está revisando.
    """
    from crmcore.fechas import hoy

    consulta = select(ExcepcionSoD).where(ExcepcionSoD.tenant_id == tenant_id)
    if regla_codigo:
        consulta = consulta.where(ExcepcionSoD.regla_codigo == regla_codigo)
    if not incluir_caducadas:
        consulta = consulta.where(ExcepcionSoD.caduca_at >= hoy(db))

    filas = db.execute(consulta.order_by(ExcepcionSoD.caduca_at)).scalars().all()
    return [
        {
            "id": str(f.id),
            "regla_codigo": f.regla_codigo,
            "usuario_id": str(f.usuario_id),
            # El motivo va dentro: sin él, la lista dice que hay excepciones y no
            # por qué, que es justo lo que hay que revisar.
            "motivo": f.motivo,
            "aprobada_por": str(f.aprobada_por) if f.aprobada_por else None,
            "caduca_at": f.caduca_at.isoformat(),
            "vigente": f.caduca_at >= hoy(db),
            "created_at": f.created_at.isoformat(),
        }
        for f in filas
    ]


def violaciones(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Quién tiene hoy permisos incompatibles, y con qué regla.

    Se calcula en vivo sobre los **permisos efectivos** y no se guarda: una
    tabla de violaciones se queda vieja en cuanto alguien cambia de rol, y una
    lista de conflictos vieja es peor que ninguna, porque se actúa sobre ella.
    """
    from services.identity import servicio as svc
    from services.identity.modelos import Membresia

    reglas = (
        db.execute(
            select(ReglaSoD).where(ReglaSoD.tenant_id == tenant_id, ReglaSoD.activa.is_(True))
        )
        .scalars()
        .all()
    )
    if not reglas:
        return {"reglas": 0, "violaciones": [], "excepciones_vigentes": 0}

    dia = hoy(db)
    exentos: dict[str, set[UUID]] = {}
    vigentes = 0
    for excepcion in (
        db.execute(select(ExcepcionSoD).where(ExcepcionSoD.tenant_id == tenant_id)).scalars().all()
    ):
        if excepcion.caduca_at >= dia:
            exentos.setdefault(excepcion.regla_codigo, set()).add(excepcion.usuario_id)
            vigentes += 1

    salida: list[dict[str, Any]] = []
    for membresia in (
        db.execute(select(Membresia).where(Membresia.tenant_id == tenant_id)).scalars().all()
    ):
        permisos = svc.permisos_efectivos(db, membresia.usuario_id, tenant_id)
        for regla in reglas:
            lado_a = sorted(p for p in regla.permisos_a if _concede(permisos, p))
            lado_b = sorted(p for p in regla.permisos_b if _concede(permisos, p))
            if not lado_a or not lado_b:
                continue
            salida.append(
                {
                    "usuario_id": str(membresia.usuario_id),
                    "regla": regla.codigo,
                    "nombre": regla.nombre,
                    "nivel": regla.nivel,
                    "por_el_lado_a": lado_a,
                    "por_el_lado_b": lado_b,
                    # La excepción no esconde el conflicto: lo marca. Esconderlo
                    # haría que una excepción caducada pasara de «aprobado» a
                    # «no existe» sin que nadie lo viera.
                    "exceptuado": membresia.usuario_id in exentos.get(regla.codigo, set()),
                }
            )

    orden = {n: i for i, n in enumerate(reversed(NIVELES))}
    salida.sort(key=lambda v: (v["exceptuado"], orden.get(v["nivel"], 9), v["regla"]))
    return {
        "reglas": len(reglas),
        "violaciones": salida,
        "sin_exceptuar": sum(1 for v in salida if not v["exceptuado"]),
        "excepciones_vigentes": vigentes,
    }


# Las reglas que trae el producto: conflictos típicos de un CRM, escritos con
# los permisos que de verdad exigen sus rutas. Se cargan a petición —no al dar
# de alta el tenant— porque cada empresa decide cuáles aplica; y se traen hechas
# porque una matriz de segregación que empieza vacía no la rellena nadie.
REGLAS_DE_SERIE: tuple[dict[str, Any], ...] = (
    {
        "codigo": "SOD-COM",
        "nombre": "Calcular comisiones y aprobarlas",
        "descripcion": "Quien calcula una liquidación no puede ser quien la aprueba.",
        "permisos_a": ["commission:write"],
        "permisos_b": ["commission:approve"],
        "nivel": "alto",
    },
    {
        "codigo": "SOD-USR",
        "nombre": "Dar de alta usuarios y asignarles roles",
        "descripcion": "Quien crea una cuenta no puede darle además los permisos.",
        "permisos_a": ["user:write"],
        "permisos_b": ["role:write"],
        "nivel": "critico",
    },
    {
        "codigo": "SOD-RET",
        "nombre": "Configurar la retención y purgar",
        "descripcion": "Quien decide cuánto se guarda no puede ejecutar el borrado definitivo.",
        "permisos_a": ["retencion:configurar"],
        "permisos_b": ["retencion:purgar"],
        "nivel": "alto",
    },
    {
        "codigo": "SOD-EXP",
        "nombre": "Exportar la empresa y purgar cuentas",
        "descripcion": "Llevarse los datos y borrar su rastro no puede estar en una mano.",
        "permisos_a": ["tenant:exportar"],
        "permisos_b": ["account:purge"],
        "nivel": "critico",
    },
    {
        "codigo": "SOD-IDP",
        "nombre": "Claves de API y configuración de la identidad",
        "descripcion": "Quien emite credenciales de máquina no configura cómo se entra.",
        "permisos_a": ["apikey:write"],
        "permisos_b": ["idp:configurar"],
        "nivel": "alto",
    },
    {
        "codigo": "SOD-AUD",
        "nombre": "Auditar y restaurar datos",
        "descripcion": "Quien revisa lo que pasó no puede cambiar lo que hay.",
        "permisos_a": ["analitica:auditar"],
        "permisos_b": ["datos:restaurar"],
        "nivel": "medio",
    },
    {
        "codigo": "SOD-INT",
        "nombre": "Credenciales de integración y roles",
        "descripcion": "Quien guarda los secretos de una integración no reparte permisos.",
        "permisos_a": ["integracion:credenciales"],
        "permisos_b": ["role:write"],
        "nivel": "alto",
    },
)


def cargar_de_serie(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Añade las reglas de serie que este tenant no tenga. Se puede repetir."""
    tiene = set(
        db.execute(select(ReglaSoD.codigo).where(ReglaSoD.tenant_id == tenant_id)).scalars()
    )
    nuevas = 0
    for regla in REGLAS_DE_SERIE:
        if regla["codigo"] in tiene:
            continue
        db.add(ReglaSoD(tenant_id=tenant_id, activa=True, **regla))
        nuevas += 1
    db.flush()
    return {"anadidas": nuevas, "ya_estaban": len(REGLAS_DE_SERIE) - nuevas}


def _roles_con_permisos(db: Session, tenant_id: UUID) -> dict[str, frozenset[str]]:
    from crmcore.authz.rbac import ROLES_BASE

    from services.identity import servicio as svc
    from services.identity.modelos import RolTenant

    nombres = set(ROLES_BASE) | set(
        db.execute(select(RolTenant.nombre).where(RolTenant.tenant_id == tenant_id)).scalars()
    )
    return {n: svc.permisos_de_rol(db, n, tenant_id) for n in sorted(nombres)}


def matriz(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Cada regla contra cada rol: qué rol da un lado, el otro, o los dos.

    Un rol que da **los dos lados** es el conflicto que se arregla en el rol y
    no persona a persona: cualquiera que lo tenga está en conflicto. Es lo
    primero que se mira, y por eso va marcado aparte.
    """
    roles = _roles_con_permisos(db, tenant_id)
    reglas = list(
        db.execute(
            select(ReglaSoD).where(ReglaSoD.tenant_id == tenant_id, ReglaSoD.activa.is_(True))
        ).scalars()
    )
    vivas = violaciones(db, tenant_id)["violaciones"] if reglas else []
    por_regla: dict[str, int] = {}
    for v in vivas:
        if not v["exceptuado"]:
            por_regla[v["regla"]] = por_regla.get(v["regla"], 0) + 1
    filas = []
    for regla in reglas:
        celdas = {}
        for nombre, permisos in roles.items():
            a = any(_concede(permisos, x) for x in regla.permisos_a)
            b = any(_concede(permisos, x) for x in regla.permisos_b)
            celdas[nombre] = "ambos" if a and b else "a" if a else "b" if b else ""
        filas.append(
            {
                "regla": regla.codigo,
                "nombre": regla.nombre,
                "nivel": regla.nivel,
                "celdas": celdas,
                "roles_en_conflicto": sorted(r for r, c in celdas.items() if c == "ambos"),
                "personas_en_conflicto": por_regla.get(regla.codigo, 0),
            }
        )
    return {"roles": sorted(roles), "reglas": filas}


def simular(
    db: Session, tenant_id: UUID, usuario_id: UUID, roles_nuevos: list[str]
) -> dict[str, Any]:
    """Qué conflictos aparecerían si esta persona recibe estos roles.

    Es la parte preventiva: se mira ANTES de asignar. Sigue sin impedir nada
    —la decisión es de quien administra—, pero ya no se descubre después.
    """
    from services.identity import servicio as svc

    actuales = svc.permisos_efectivos(db, usuario_id, tenant_id)
    con_nuevos = set(actuales)
    for rol in roles_nuevos:
        con_nuevos |= svc.permisos_de_rol(db, rol, tenant_id)
    nuevos: list[dict[str, Any]] = []
    for regla in db.execute(
        select(ReglaSoD).where(ReglaSoD.tenant_id == tenant_id, ReglaSoD.activa.is_(True))
    ).scalars():

        def choca(permisos: set[str] | frozenset[str], regla: ReglaSoD = regla) -> bool:
            return any(_concede(permisos, x) for x in regla.permisos_a) and any(
                _concede(permisos, x) for x in regla.permisos_b
            )

        if choca(con_nuevos) and not choca(actuales):
            nuevos.append({"regla": regla.codigo, "nombre": regla.nombre, "nivel": regla.nivel})
    return {"conflictos_nuevos": nuevos, "limpio": not nuevos}


def _concede(permisos: frozenset[str] | set[str], permiso: str) -> bool:
    """Si el conjunto concede el permiso, expandiendo comodines.

    Se expande porque un rol con `*:*` los tiene todos, y una regla de SoD que
    no lo viera daría por limpio justo al usuario más peligroso.
    """
    if "*:*" in permisos or permiso in permisos:
        return True
    objeto, _, accion = permiso.partition(":")
    return f"{objeto}:*" in permisos or f"*:{accion}" in permisos
