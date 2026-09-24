"""Modelo canónico de intercambio y sincronización bidireccional
(CRM-00.03.04.09, CRM-00.03.04.08).

Con dos sistemas conectados hace falta un mapeo. Con seis hacen falta quince, y
ahí es donde las integraciones dejan de mantenerse: cada conector traduce a su
manera, nadie sabe qué campo es el bueno, y cambiar el nombre de un campo obliga a
tocar cinco sitios.

**El modelo canónico es el idioma común.** Cada sistema externo traduce solo a él
y desde él, y el número de traducciones pasa de N×(N−1) a 2N. Es lo único que hace
que añadir el sexto sistema cueste lo mismo que el segundo.

**Y es del tenant, no del código.** Cada empresa llama a las cosas a su manera y
tiene campos que nadie más tiene. Un modelo canónico fijo en el código obliga a
meter lo propio en un `extra` que nadie mapea, que es exactamente donde acaba el
dato que importa.

La sincronización bidireccional añade el problema de verdad: **los dos lados
cambian a la vez**. Las tres decisiones que lo gobiernan aquí:

**La política de conflicto se declara, por campo si hace falta.** «Gana el
último» no vale para todo: el correo electrónico que corrigió el comercial no
puede perder contra una carga masiva del ERP de las 3:00. Las cuatro políticas
—gana el nuestro, gana el suyo, gana el más reciente, paralo y que lo mire
alguien— cubren los casos reales, y ninguna es el valor por defecto sensato para
todos los campos a la vez.

**Sin marca de tiempo comparable no se decide por tiempo.** Muchos sistemas no la
dan, o la dan en su zona horaria sin decirlo. Aplicar «gana el más reciente» sobre
una fecha que no se puede comparar es echarlo a suertes y presentarlo como una
regla.

**Un eco no es un cambio.** Lo que acabamos de escribir allí nos vuelve como
novedad suya, y sin detectarlo los dos sistemas se rebotan el mismo dato para
siempre. Se guarda la huella de lo último escrito en cada dirección, y lo que
vuelve igual se ignora — diciéndolo.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
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

# Qué se hace cuando los dos lados han cambiado el mismo campo.
#
#   nuestro     manda el CRM
#   externo     manda el otro sistema
#   reciente    manda el que se modificó después (exige fecha comparable en los dos)
#   manual      no se decide: se para y lo mira una persona
POLITICAS = ("nuestro", "externo", "reciente", "manual")

# Direcciones de sincronización de un campo.
#
#   ambas        va y viene
#   hacia_fuera  solo lo mandamos
#   hacia_dentro solo lo recibimos
#   ninguna      se mapea para poder leerlo, pero no se sincroniza
DIRECCIONES = ("ambas", "hacia_fuera", "hacia_dentro", "ninguna")


class ObjetoCanonico(Base, TimestampMixin):
    """Un objeto del idioma común: cuenta, contacto, pedido… (CRM-00.03.04.09).

    Lo define el tenant. Un modelo canónico fijo en el código obliga a meter lo
    propio de cada empresa en un `extra` que nadie mapea, y ahí es donde acaba el
    dato que de verdad importa.
    """

    __tablename__ = "objetos_canonicos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Cada campo: {clave, tipo, obligatorio, descripcion}. La clave canónica es la
    # que usan todos los adaptadores; cambiarla es un cambio de contrato y por eso
    # se guarda como dato y no se deduce de nadie.
    campos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Qué campos identifican al objeto entre sistemas. Sin clave de negocio, dos
    # sistemas sin identificador compartido no se pueden casar y cada carga crea
    # duplicados.
    claves_negocio: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_objeto_canonico"),)


class Adaptador(Base, TimestampMixin):
    """Cómo traduce un sistema externo a un objeto canónico (CRM-00.03.04.09)."""

    __tablename__ = "adaptadores_canonicos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("objetos_canonicos.id", ondelete="CASCADE"), nullable=False
    )
    sistema: Mapped[str] = mapped_column(String(80), nullable=False)
    # Mapeo: {campo_canonico: campo_externo}. Solo nombres; las transformaciones
    # las hace el motor de normalización que ya existe, en vez de tener aquí un
    # segundo lenguaje de expresiones que se comporte distinto.
    mapeo: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Política por defecto y excepciones por campo. La excepción por campo es lo
    # que evita la discusión de siempre: el teléfono lo manda el ERP y el correo
    # lo manda el CRM.
    politica: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    politica_por_campo: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    direccion: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ambas", info={"opciones": DIRECCIONES}
    )
    direccion_por_campo: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Campo del sistema externo que dice cuándo se modificó allí. Sin él, «gana el
    # más reciente» no se puede aplicar, y se dice en vez de inventarse un orden.
    campo_modificado: Mapped[str | None] = mapped_column(String(120), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "objeto_id", "sistema", name="uq_adaptador_sistema"),
        Index("ix_adaptadores", "tenant_id", "sistema", "activo"),
    )


class Vinculo(Base, TimestampMixin):
    """Qué registro nuestro es qué registro suyo, y qué se escribió por última vez.

    Las huellas son lo que corta el eco: lo que acabamos de escribir allí nos
    vuelve como novedad suya, y sin detectarlo los dos sistemas se rebotan el
    mismo dato para siempre — cada rebote con su llamada de API y su registro de
    auditoría.
    """

    __tablename__ = "vinculos_sincronizacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(80), nullable=False)
    sistema: Mapped[str] = mapped_column(String(80), nullable=False)
    registro_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    id_externo: Mapped[str] = mapped_column(String(200), nullable=False)

    huella_nuestra: Mapped[str | None] = mapped_column(String(64), nullable=True)
    huella_suya: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ultima_salida_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultima_entrada_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Si hay un conflicto sin resolver, el vínculo queda parado. Seguir
    # sincronizando lo demás mientras un campo está en disputa haría que el
    # registro quedara mitad de uno y mitad de otro.
    en_conflicto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "sistema", "objeto", "id_externo", name="uq_vinculo_externo"),
        Index("ix_vinculos_registro", "tenant_id", "objeto", "registro_id"),
    )


class ConflictoSincronizacion(Base, TimestampMixin):
    """Un campo que cambió en los dos lados y no se decidió solo."""

    __tablename__ = "conflictos_sincronizacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    vinculo_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("vinculos_sincronizacion.id", ondelete="CASCADE"),
        nullable=False,
    )
    campo: Mapped[str] = mapped_column(String(120), nullable=False)
    valor_nuestro: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    valor_suyo: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    politica: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    porque: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resuelto_con: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resuelto_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    resuelto_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (Index("ix_conflictos_sync", "tenant_id", "vinculo_id", "resuelto_at"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def huella(datos: Any) -> str:
    """Huella estable de un diccionario de valores."""
    return hashlib.sha256(
        json.dumps(datos, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


def _objeto(db: Session, tenant_id: UUID, clave: str) -> ObjetoCanonico:
    fila = db.execute(
        select(ObjetoCanonico).where(
            ObjetoCanonico.tenant_id == tenant_id, ObjetoCanonico.clave == clave
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            f"No hay objeto canónico «{clave}»", error_code="canonico.objeto_no_encontrado"
        )
    return fila


# ── Modelo canónico y adaptadores (CRM-00.03.04.09) ───────────────────────


def definir_objeto(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    campos: list[dict[str, Any]],
    nombre: str = "",
    descripcion: str = "",
    claves_negocio: list[str] | None = None,
) -> tuple[ObjetoCanonico, list[str]]:
    """Define un objeto del idioma común."""
    if not campos:
        raise ErrorValidacion(
            "Un objeto canónico sin campos no traduce nada.",
            error_code="canonico.sin_campos",
        )
    claves = {str(c.get("clave") or "") for c in campos}
    if "" in claves:
        raise ErrorValidacion(
            "Todos los campos canónicos necesitan clave.", error_code="canonico.campo_sin_clave"
        )
    avisos: list[str] = []
    negocio = list(claves_negocio or [])
    faltan = [c for c in negocio if c not in claves]
    if faltan:
        raise ErrorValidacion(
            f"Las claves de negocio {faltan} no están entre los campos del objeto.",
            error_code="canonico.clave_negocio_desconocida",
        )
    if not negocio:
        avisos.append(
            "Sin claves de negocio: dos sistemas que no compartan identificador no "
            "se podrán casar, y cada carga creará duplicados."
        )

    fila = ObjetoCanonico(
        tenant_id=uow.tenant_id,
        clave=clave.strip(),
        nombre=nombre.strip() or clave.strip(),
        descripcion=descripcion,
        campos=list(campos),
        claves_negocio=negocio,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def registrar_adaptador(
    uow: UnidadDeTrabajo,
    *,
    objeto: str,
    sistema: str,
    mapeo: dict[str, str],
    politica: str = "manual",
    politica_por_campo: dict[str, str] | None = None,
    direccion: str = "ambas",
    direccion_por_campo: dict[str, str] | None = None,
    campo_modificado: str | None = None,
) -> tuple[Adaptador, list[str]]:
    """Declara cómo traduce un sistema externo.

    Se comprueba que lo mapeado existe en el objeto canónico: un campo mal
    escrito no falla, **deja de sincronizarse en silencio**, y eso se descubre
    meses después con los datos ya divergidos.
    """
    ficha = _objeto(uow.db, uow.tenant_id, objeto)
    validos = {str(c.get("clave")) for c in (ficha.campos or [])}
    desconocidos = sorted(set(mapeo) - validos)
    if desconocidos:
        raise ErrorValidacion(
            f"El mapeo nombra campos que no existen en «{objeto}»: {desconocidos}.",
            error_code="canonico.campo_desconocido",
            detalle={"validos": sorted(validos)},
        )
    if politica not in POLITICAS:
        raise ErrorValidacion(
            f"Política «{politica}» no válida.",
            error_code="canonico.politica_no_valida",
            detalle={"validas": list(POLITICAS)},
        )
    if direccion not in DIRECCIONES:
        raise ErrorValidacion(
            f"Dirección «{direccion}» no válida.",
            error_code="canonico.direccion_no_valida",
            detalle={"validas": list(DIRECCIONES)},
        )
    for campo, pol in (politica_por_campo or {}).items():
        if pol not in POLITICAS:
            raise ErrorValidacion(
                f"Política «{pol}» no válida para el campo «{campo}».",
                error_code="canonico.politica_no_valida",
                detalle={"validas": list(POLITICAS)},
            )

    avisos: list[str] = []
    sin_mapear = sorted(validos - set(mapeo))
    if sin_mapear:
        avisos.append(
            f"Campos canónicos sin mapear en {sistema}: {', '.join(sin_mapear)}. No "
            "viajarán en ninguna dirección."
        )
    politicas_usadas = {politica, *(politica_por_campo or {}).values()}
    if "reciente" in politicas_usadas and not campo_modificado:
        avisos.append(
            "La política «reciente» necesita un campo de última modificación del "
            "sistema externo. Sin él, los conflictos se pararán para revisión en vez "
            "de decidirse por fecha."
        )

    fila = Adaptador(
        tenant_id=uow.tenant_id,
        objeto_id=ficha.id,
        sistema=sistema.strip(),
        mapeo=dict(mapeo),
        politica=politica,
        politica_por_campo=dict(politica_por_campo or {}),
        direccion=direccion,
        direccion_por_campo=dict(direccion_por_campo or {}),
        campo_modificado=campo_modificado,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def a_canonico(
    db: Session, tenant_id: UUID, *, objeto: str, sistema: str, externo: dict[str, Any]
) -> dict[str, Any]:
    """Traduce un registro del sistema externo al idioma común.

    Lo que el sistema manda y no está mapeado **se devuelve aparte**, no se tira:
    es la lista con la que se descubre que el cliente añadió un campo nuevo en su
    ERP y nadie se enteró.
    """
    adaptador = _adaptador(db, tenant_id, objeto, sistema)
    canonico: dict[str, Any] = {}
    for campo, campo_externo in (adaptador.mapeo or {}).items():
        if campo_externo in externo:
            canonico[campo] = externo[campo_externo]
    usados = set((adaptador.mapeo or {}).values())
    return {
        "objeto": objeto,
        "sistema": sistema,
        "datos": canonico,
        "sin_mapear": {k: v for k, v in externo.items() if k not in usados},
        "faltan_obligatorios": _faltan_obligatorios(db, tenant_id, objeto, canonico),
    }


def desde_canonico(
    db: Session, tenant_id: UUID, *, objeto: str, sistema: str, datos: dict[str, Any]
) -> dict[str, Any]:
    """Traduce del idioma común al del sistema externo."""
    adaptador = _adaptador(db, tenant_id, objeto, sistema)
    salida: dict[str, Any] = {}
    no_viajan: list[str] = []
    for campo, valor in datos.items():
        destino = (adaptador.mapeo or {}).get(campo)
        if destino is None:
            no_viajan.append(campo)
            continue
        direccion = (adaptador.direccion_por_campo or {}).get(campo, adaptador.direccion)
        if direccion in ("hacia_dentro", "ninguna"):
            no_viajan.append(campo)
            continue
        salida[destino] = valor
    return {"datos": salida, "no_viajan": sorted(no_viajan)}


def _adaptador(db: Session, tenant_id: UUID, objeto: str, sistema: str) -> Adaptador:
    ficha = _objeto(db, tenant_id, objeto)
    fila = db.execute(
        select(Adaptador).where(
            Adaptador.tenant_id == tenant_id,
            Adaptador.objeto_id == ficha.id,
            Adaptador.sistema == sistema,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            f"No hay adaptador de «{sistema}» para «{objeto}»",
            error_code="canonico.adaptador_no_encontrado",
        )
    return fila


def _faltan_obligatorios(
    db: Session, tenant_id: UUID, objeto: str, datos: dict[str, Any]
) -> list[str]:
    ficha = _objeto(db, tenant_id, objeto)
    return [
        str(c.get("clave"))
        for c in (ficha.campos or [])
        if c.get("obligatorio") and datos.get(str(c.get("clave"))) in (None, "")
    ]


# ── Sincronización bidireccional (CRM-00.03.04.08) ────────────────────────


def emparejar(
    uow: UnidadDeTrabajo,
    *,
    objeto: str,
    sistema: str,
    registro_id: UUID,
    id_externo: str,
) -> Vinculo:
    """Declara que este registro nuestro es aquel registro suyo."""
    fila = uow.db.execute(
        select(Vinculo).where(
            Vinculo.tenant_id == uow.tenant_id,
            Vinculo.sistema == sistema,
            Vinculo.objeto == objeto,
            Vinculo.id_externo == id_externo,
        )
    ).scalar_one_or_none()
    if fila is not None:
        if fila.registro_id != registro_id:
            raise Conflicto(
                "Ese registro externo ya está emparejado con otro registro nuestro. "
                "Reasignarlo en silencio haría que dos fichas se pisaran los datos.",
                error_code="canonico.vinculo_ocupado",
                detalle={"registro_id": str(fila.registro_id)},
            )
        return fila
    fila = Vinculo(
        tenant_id=uow.tenant_id,
        objeto=objeto,
        sistema=sistema,
        registro_id=registro_id,
        id_externo=id_externo,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _politica_de(adaptador: Adaptador, campo: str) -> str:
    return str((adaptador.politica_por_campo or {}).get(campo, adaptador.politica))


def conciliar(
    uow: UnidadDeTrabajo,
    *,
    objeto: str,
    sistema: str,
    id_externo: str,
    nuestro: dict[str, Any],
    suyo: dict[str, Any],
    modificado_nuestro: datetime | None = None,
    modificado_suyo: datetime | None = None,
) -> dict[str, Any]:
    """Decide campo a campo qué valor gana (CRM-00.03.04.08).

    Devuelve **lo que hay que escribir en cada lado** y los conflictos que no se
    han podido decidir. No escribe: quien llama es el dueño de cada sistema y
    sabe cómo hacerlo. Escribir desde aquí obligaría a este módulo a conocer seis
    APIs y el esquema de cuatro servicios.

    Un campo que solo cambió en un lado **no es un conflicto**: se propaga. El
    conflicto es que cambien los dos, y solo entonces manda la política.
    """
    adaptador = _adaptador(uow.db, uow.tenant_id, objeto, sistema)
    vinculo = uow.db.execute(
        select(Vinculo).where(
            Vinculo.tenant_id == uow.tenant_id,
            Vinculo.sistema == sistema,
            Vinculo.objeto == objeto,
            Vinculo.id_externo == id_externo,
        )
    ).scalar_one_or_none()
    if vinculo is None:
        raise NoEncontrado(
            "No hay vínculo para ese registro externo",
            error_code="canonico.vinculo_no_encontrado",
        )

    # Eco: lo que nos llega es exactamente lo que acabamos de escribir allí. Sin
    # esta comprobación, los dos sistemas se rebotan el mismo dato para siempre.
    if vinculo.huella_nuestra and huella(suyo) == vinculo.huella_nuestra:
        vinculo.ultima_entrada_at = _ahora()
        return {
            "eco": True,
            "escribir_fuera": {},
            "escribir_dentro": {},
            "conflictos": [],
            "porque": "Lo recibido es igual a lo último que escribimos allí: es un eco.",
        }

    escribir_fuera: dict[str, Any] = {}
    escribir_dentro: dict[str, Any] = {}
    conflictos: list[dict[str, Any]] = []

    campos = set(nuestro) | set(suyo)
    for campo in sorted(campos):
        direccion = (adaptador.direccion_por_campo or {}).get(campo, adaptador.direccion)
        if direccion == "ninguna":
            continue
        valor_nuestro = nuestro.get(campo)
        valor_suyo = suyo.get(campo)
        if valor_nuestro == valor_suyo:
            continue

        # Solo uno de los dos tiene valor: no hay conflicto, hay un hueco.
        if valor_nuestro in (None, "") and valor_suyo not in (None, ""):
            if direccion in ("ambas", "hacia_dentro"):
                escribir_dentro[campo] = valor_suyo
            continue
        if valor_suyo in (None, "") and valor_nuestro not in (None, ""):
            if direccion in ("ambas", "hacia_fuera"):
                escribir_fuera[campo] = valor_nuestro
            continue

        politica = _politica_de(adaptador, campo)
        if politica == "nuestro":
            if direccion in ("ambas", "hacia_fuera"):
                escribir_fuera[campo] = valor_nuestro
            continue
        if politica == "externo":
            if direccion in ("ambas", "hacia_dentro"):
                escribir_dentro[campo] = valor_suyo
            continue
        if politica == "reciente":
            if modificado_nuestro is None or modificado_suyo is None:
                # Sin fechas comparables, «gana el más reciente» sería echarlo a
                # suertes y presentarlo como una regla. Se para.
                conflictos.append(
                    {
                        "campo": campo,
                        "nuestro": valor_nuestro,
                        "suyo": valor_suyo,
                        "politica": politica,
                        "porque": (
                            "La política es «gana el más reciente» pero falta la fecha "
                            "de modificación de "
                            + (
                                "los dos lados"
                                if modificado_nuestro is None and modificado_suyo is None
                                else (
                                    "nuestro lado"
                                    if modificado_nuestro is None
                                    else "el sistema externo"
                                )
                            )
                        ),
                    }
                )
                continue
            if modificado_nuestro >= modificado_suyo:
                if direccion in ("ambas", "hacia_fuera"):
                    escribir_fuera[campo] = valor_nuestro
            elif direccion in ("ambas", "hacia_dentro"):
                escribir_dentro[campo] = valor_suyo
            continue

        conflictos.append(
            {
                "campo": campo,
                "nuestro": valor_nuestro,
                "suyo": valor_suyo,
                "politica": "manual",
                "porque": "Los dos lados han cambiado y la política es decidirlo a mano.",
            }
        )

    for dato in conflictos:
        ya = uow.db.execute(
            select(ConflictoSincronizacion).where(
                ConflictoSincronizacion.tenant_id == uow.tenant_id,
                ConflictoSincronizacion.vinculo_id == vinculo.id,
                ConflictoSincronizacion.campo == dato["campo"],
                ConflictoSincronizacion.resuelto_at.is_(None),
            )
        ).scalar_one_or_none()
        if ya is not None:
            # No se duplica: se cuenta. Un conflicto que se repite cien veces es
            # un conflicto, no cien.
            ya.intentos += 1
            ya.valor_suyo = {"valor": dato["suyo"]}
            ya.valor_nuestro = {"valor": dato["nuestro"]}
            continue
        uow.db.add(
            ConflictoSincronizacion(
                tenant_id=uow.tenant_id,
                vinculo_id=vinculo.id,
                campo=dato["campo"],
                valor_nuestro={"valor": dato["nuestro"]},
                valor_suyo={"valor": dato["suyo"]},
                politica=dato["politica"],
                porque=dato["porque"],
            )
        )

    # Con un conflicto abierto el vínculo queda parado: seguir sincronizando lo
    # demás dejaría el registro mitad de uno y mitad de otro, que es peor que
    # tenerlo parado y visible.
    vinculo.en_conflicto = bool(conflictos)
    vinculo.huella_suya = huella(suyo)
    vinculo.ultima_entrada_at = _ahora()
    if escribir_fuera:
        vinculo.huella_nuestra = huella({**suyo, **escribir_fuera})
        vinculo.ultima_salida_at = _ahora()
    uow.db.flush()

    return {
        "eco": False,
        "vinculo_id": str(vinculo.id),
        "escribir_fuera": escribir_fuera,
        "escribir_dentro": escribir_dentro,
        "conflictos": conflictos,
        "en_conflicto": bool(conflictos),
        "porque": (
            "Hay campos cambiados en los dos lados que la política no decide sola."
            if conflictos
            else ""
        ),
    }


def resolver_conflicto(
    uow: UnidadDeTrabajo,
    conflicto_id: UUID,
    *,
    gana: str,
    por: UUID | None = None,
) -> dict[str, Any]:
    """Cierra un conflicto eligiendo un lado, y dice qué hay que escribir."""
    if gana not in ("nuestro", "externo"):
        raise ErrorValidacion(
            "Resolver un conflicto es elegir un lado: «nuestro» o «externo».",
            error_code="canonico.eleccion_no_valida",
        )
    fila = uow.db.get(ConflictoSincronizacion, conflicto_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("El conflicto no existe", error_code="canonico.conflicto_no_encontrado")
    if fila.resuelto_at is not None:
        raise Conflicto(
            "Ese conflicto ya está resuelto",
            error_code="canonico.ya_resuelto",
            detalle={"resuelto_con": fila.resuelto_con},
        )
    fila.resuelto_con = gana
    fila.resuelto_por = por
    fila.resuelto_at = _ahora()
    # `flush` antes de contar: la sesión no tiene autoflush, así que sin esto el
    # recuento de pendientes iría contra la base sin este cambio y seguiría
    # contando como pendiente el que se acaba de resolver.
    uow.db.flush()

    vinculo = uow.db.get(Vinculo, fila.vinculo_id)
    pendientes = (
        uow.db.execute(
            select(func.count())
            .select_from(ConflictoSincronizacion)
            .where(
                ConflictoSincronizacion.tenant_id == uow.tenant_id,
                ConflictoSincronizacion.vinculo_id == fila.vinculo_id,
                ConflictoSincronizacion.resuelto_at.is_(None),
            )
        )
    ).scalar_one()
    if vinculo is not None:
        vinculo.en_conflicto = int(pendientes) > 0
    uow.db.flush()
    valor = (fila.valor_nuestro if gana == "nuestro" else fila.valor_suyo).get("valor")
    return {
        "conflicto_id": str(fila.id),
        "campo": fila.campo,
        "gana": gana,
        "valor": valor,
        # A quién hay que escribírselo: si gana el nuestro, hay que empujarlo
        # fuera; si gana el suyo, hay que traerlo dentro.
        "escribir_en": "externo" if gana == "nuestro" else "nuestro",
        "quedan_conflictos": int(pendientes),
    }


def pendientes(db: Session, tenant_id: UUID, *, sistema: str = "") -> dict[str, Any]:
    """Conflictos sin resolver, con cuántas veces ha vuelto cada uno.

    El número de intentos es el dato útil: un conflicto que se repite cada hora
    significa que alguien está escribiendo en los dos lados a la vez, y eso se
    arregla cambiando la política, no resolviendo el conflicto cien veces.
    """
    consulta = (
        select(ConflictoSincronizacion, Vinculo)
        .join(Vinculo, Vinculo.id == ConflictoSincronizacion.vinculo_id)
        .where(
            ConflictoSincronizacion.tenant_id == tenant_id,
            ConflictoSincronizacion.resuelto_at.is_(None),
        )
    )
    if sistema:
        consulta = consulta.where(Vinculo.sistema == sistema)
    filas = db.execute(consulta.order_by(ConflictoSincronizacion.intentos.desc())).all()
    return {
        "conflictos": [
            {
                "conflicto_id": str(c.id),
                "sistema": v.sistema,
                "objeto": v.objeto,
                "registro_id": str(v.registro_id),
                "id_externo": v.id_externo,
                "campo": c.campo,
                "nuestro": c.valor_nuestro.get("valor"),
                "suyo": c.valor_suyo.get("valor"),
                "intentos": c.intentos,
                "porque": c.porque,
            }
            for c, v in filas
        ],
        "cuantos": len(filas),
        "reincidentes": len([1 for c, _ in filas if c.intentos > 3]),
    }
