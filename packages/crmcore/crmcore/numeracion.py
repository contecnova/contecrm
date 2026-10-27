"""El código que la gente dice por teléfono (CRM-00.04.01.11).

    from crmcore import numeracion

    codigo = numeracion.siguiente(db, tenant_id, objeto="oportunidad")
    # 'OPP-2026-00123'

Un identificador opaco es lo correcto para la máquina —no se adivina, no se
enumera, no se agota— y **no sirve para lo que la gente hace con él**: decirlo
por teléfono, escribirlo en un correo, buscarlo en una hoja de cálculo que le
mandó el cliente. Por eso al lado del identificador va un código de negocio:
corto, legible y correlativo.

**Por qué no se cuenta.** Lo que había contaba las filas del año y sumaba uno.
Eso falla de tres maneras y las tres pasan: si se borra un registro el
siguiente repite número; si dos altas entran a la vez piden el mismo y la
restricción única convierte el alta en un error; y si alguien carga histórico
con códigos propios, el recuento no tiene nada que ver con el último emitido.
Aquí hay un contador de verdad, con su fila, y se pide **bajo cerrojo**.

**Por qué el patrón es configuración.** `OPP-2026-00123` es una convención, no
una ley: hay clientes que numeran por delegación, otros sin año y otros que
arrastran el formato del sistema que venían usando — y el código tiene que
seguir siendo el mismo para que sus referencias de veinte años no se queden
huérfanas. El patrón, el relleno y cuándo se reinicia se declaran por objeto.

**El reinicio es parte del patrón, no un capricho.** Si el patrón lleva el año
y el contador no se reinicia, el primero de enero sale `OPP-2027-00124`, que no
es lo que nadie espera. Y al revés: si se reinicia y el patrón NO lleva el año,
el 1 de enero se repite el `00001` del año pasado. Las dos cosas se comprueban
al guardar la numeración, no al emitir: descubrirlo al emitir significa
descubrirlo con un registro a medio crear.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Integer, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base, TimestampMixin
from crmcore.errors import ErrorValidacion
from crmcore.fechas import hoy
from crmcore.ids import nuevo_id

# Cuándo vuelve el contador a uno.
REINICIOS = ("nunca", "anual", "mensual")

# Las piezas que admite un patrón. Lista cerrada: un patrón con un hueco que no
# se sabe rellenar produciría códigos con `{loquesea}` dentro, y eso acaba
# impreso en una oferta.
PIEZAS = ("objeto", "anio", "anio_corto", "mes", "secuencia")


class NumeracionObjeto(Base, TimestampMixin):
    """Cómo se numera un objeto en este tenant, y por dónde va."""

    __tablename__ = "numeracion_objetos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(80), nullable=False)
    # Por ejemplo `OPP-{anio}-{secuencia}`. Las piezas, en `PIEZAS`.
    patron: Mapped[str] = mapped_column(String(120), nullable=False)
    # Con cuántos dígitos se escribe la secuencia: `5` da `00123`. El relleno
    # es lo que hace que los códigos ordenen bien como texto, que es como los
    # ordena cualquier hoja de cálculo a la que acaben llegando.
    relleno: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    reinicio: Mapped[str] = mapped_column(String(10), nullable=False, default="anual")
    # El periodo cuyo contador está vivo: `2026`, `2026-03` o `` si no reinicia.
    periodo: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    # El ÚLTIMO emitido, no el siguiente: así un contador recién creado vale 0
    # y no hay que decidir si el primero es el 0 o el 1 en dos sitios.
    ultimo: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "objeto", name="uq_numeracion_objeto"),)


def _periodo_de(reinicio: str, dia: date) -> str:
    if reinicio == "anual":
        return f"{dia.year:04d}"
    if reinicio == "mensual":
        return f"{dia.year:04d}-{dia.month:02d}"
    return ""


def comprobar(patron: str, reinicio: str) -> list[str]:
    """Qué tiene de malo este patrón, antes de guardarlo.

    Se comprueba al guardar y no al emitir: un patrón roto descubierto al
    emitir se descubre con un registro a medio crear y delante de quien no lo
    escribió.
    """
    import re

    problemas: list[str] = []
    if reinicio not in REINICIOS:
        problemas.append(f"«{reinicio}» no es un reinicio válido; usa {', '.join(REINICIOS)}")
    piezas = re.findall(r"\{([a-z_]+)\}", patron)
    for pieza in piezas:
        if pieza not in PIEZAS:
            problemas.append(f"«{{{pieza}}}» no existe; las piezas son {', '.join(PIEZAS)}")
    if "secuencia" not in piezas:
        # Sin secuencia no hay número: el patrón daría el mismo código a todos
        # los registros, y la restricción única los rechazaría del segundo en
        # adelante. El síntoma sería «no se puede crear», no «falta el número».
        problemas.append("el patrón tiene que llevar {secuencia}: sin ella todos serían iguales")
    lleva_anio = "anio" in piezas or "anio_corto" in piezas
    lleva_mes = "mes" in piezas
    if reinicio == "anual" and not lleva_anio:
        problemas.append(
            "se reinicia cada año y el patrón no lleva el año: el 1 de enero se "
            "repetirían los códigos del año anterior"
        )
    if reinicio == "mensual" and not (lleva_anio and lleva_mes):
        problemas.append(
            "se reinicia cada mes y el patrón no lleva año y mes: los códigos se repetirían"
        )
    if reinicio == "nunca" and (lleva_anio or lleva_mes):
        problemas.append(
            "el patrón lleva la fecha y el contador no se reinicia: el 1 de enero "
            "saldría el año nuevo con el número viejo, que no es lo que nadie espera"
        )
    return problemas


def declarar(
    db: Session,
    tenant_id: UUID,
    *,
    objeto: str,
    patron: str,
    relleno: int = 5,
    reinicio: str = "anual",
    empezar_en: int | None = None,
) -> NumeracionObjeto:
    """Declara o cambia cómo se numera un objeto.

    `empezar_en` existe para el único caso que lo pide de verdad: llegar de
    otro sistema con el último código emitido. Sin él, el primer registro del
    CRM repetiría un código que el cliente ya tiene impreso en un albarán.
    """
    problemas = comprobar(patron, reinicio)
    if problemas:
        raise ErrorValidacion(
            "La numeración no es válida: " + "; ".join(problemas),
            error_code="numeracion.patron_invalido",
            detalle={"problemas": problemas},
        )
    fila = db.execute(
        select(NumeracionObjeto).where(
            NumeracionObjeto.tenant_id == tenant_id, NumeracionObjeto.objeto == objeto
        )
    ).scalar_one_or_none()
    periodo = _periodo_de(reinicio, hoy(db))
    if fila is None:
        fila = NumeracionObjeto(
            tenant_id=tenant_id,
            objeto=objeto,
            patron=patron,
            relleno=relleno,
            reinicio=reinicio,
            periodo=periodo,
            ultimo=max(0, empezar_en or 0),
        )
        db.add(fila)
        db.flush()
        return fila
    fila.patron = patron
    fila.relleno = relleno
    # Cambiar el reinicio cambia el periodo vivo, y con él el contador. No se
    # toca `ultimo` salvo que lo pidan: bajarlo solo repetiría códigos.
    if fila.reinicio != reinicio:
        fila.reinicio = reinicio
        fila.periodo = periodo
    if empezar_en is not None:
        fila.ultimo = max(0, empezar_en)
    db.flush()
    return fila


def siguiente(db: Session, tenant_id: UUID, *, objeto: str) -> str | None:
    """El siguiente código de este objeto, o `None` si no se numera.

    `None` y no una excepción: un objeto sin numeración declarada no es un
    error, es lo normal. Que reventara obligaría a declarar numeración para
    todo antes de poder dar de alta nada.

    **Bajo cerrojo de fila.** Dos altas simultáneas piden el mismo contador; sin
    el cerrojo se llevan el mismo número y la restricción única convierte una
    de las dos altas en un error que el usuario no entiende.
    """
    consulta = select(NumeracionObjeto).where(
        NumeracionObjeto.tenant_id == tenant_id,
        NumeracionObjeto.objeto == objeto,
        NumeracionObjeto.activa.is_(True),
    )
    # SQLite —el de las pruebas rápidas— no sabe de `FOR UPDATE`; en Postgres,
    # que es donde hay concurrencia de verdad, sí.
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        consulta = consulta.with_for_update()
    fila = db.execute(consulta).scalar_one_or_none()
    if fila is None:
        return None

    dia = hoy(db)
    periodo = _periodo_de(fila.reinicio, dia)
    if periodo != fila.periodo:
        fila.periodo = periodo
        fila.ultimo = 0
    fila.ultimo += 1
    db.flush()
    return formatear(fila, dia)


def formatear(fila: NumeracionObjeto, dia: date) -> str:
    """El código, con las piezas puestas."""
    valores: dict[str, Any] = {
        "objeto": fila.objeto,
        "anio": f"{dia.year:04d}",
        "anio_corto": f"{dia.year % 100:02d}",
        "mes": f"{dia.month:02d}",
        "secuencia": f"{fila.ultimo:0{max(1, fila.relleno)}d}",
    }
    salida = fila.patron
    for pieza, valor in valores.items():
        salida = salida.replace(f"{{{pieza}}}", valor)
    return salida
