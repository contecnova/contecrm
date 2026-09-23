"""Cola de excepciones de calidad y enriquecimiento programado
(CRM-01.01.04.08, CRM-01.01.04.09, CRM-01.01.01.08).

Medir la calidad del dato es fácil y no sirve de nada por sí solo: el informe que
dice «el 38 % de las cuentas no tiene sector» lo mira todo el mundo la primera
semana y nadie la segunda. Lo que arregla el dato es que **alguien concreto tenga
una cola con su nombre**.

Las decisiones:

**Una excepción sin responsable no es una excepción, es una estadística.** Se
asigna, y si no hay a quién asignarla se dice — porque una cola sin dueño crece
hasta que nadie la abre.

**Cerrar exige decir qué se hizo.** Corregido, no era un error, o no se puede
arreglar y por qué. Un botón de «cerrar» a secas convierte la cola en un
vertedero: se vacía y el dato sigue mal.

**«No era un error» es una respuesta legítima y se aprende de ella.** Si la misma
regla genera cien excepciones que cien personas descartan, la rota es la regla.

**El enriquecimiento no pisa lo que escribió una persona.** Un proveedor de datos
sabe de muchas empresas y no conoce a ninguna; quien acaba de hablar con el
cliente sí. Rellena huecos.

**Y enriquecer cuesta dinero por llamada.** Un botón de «enriquecer todo» sobre
cuarenta mil cuentas es una factura que nadie aprobó: se dice cuánto va a costar
antes, no después.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import DateTime, Index, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Qué tipos de excepción se abren. Cerrada: cada una se arregla de una forma
# distinta y se asigna a gente distinta, y con texto libre la cola deja de poder
# repartirse.
TIPOS = (
    "falta_obligatorio",
    "formato_invalido",
    "posible_duplicado",
    "fuentes_en_desacuerdo",
    "dato_obsoleto",
    "sin_propietario",
)

# Cómo se cierra. «Hecho» a secas no está: cerrar sin decir qué se hizo convierte
# la cola en un vertedero que se vacía mientras el dato sigue mal.
CIERRES = (
    "corregido",
    "no_era_un_error",
    "no_se_puede_arreglar",
    "ya_no_aplica",
)

# A partir de cuántos «no era un error» sobre la misma regla se sospecha de la
# regla. Es bajo a propósito: si cinco personas distintas dicen que no es un
# error, probablemente no lo es.
DESCARTES_PARA_SOSPECHAR = 5


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class ExcepcionCalidad(Base, TimestampMixin):
    """Algo que está mal en una ficha y que alguien tiene que mirar."""

    __tablename__ = "excepciones_calidad"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(40), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    campo: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    # Qué regla la abrió. Sin esto no se puede saber que una regla está generando
    # ruido, y una regla que genera ruido vacía la cola de credibilidad.
    regla: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    detalle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 1 = hay que mirarlo hoy; 3 = cuando se pueda. Tres niveles y no cinco:
    # con cinco, todo acaba en el del medio.
    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    asignada_a: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    # abierta | asignada | cerrada
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="abierta")
    cierre: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    nota_de_cierre: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cerrada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cerrada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    datos: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_excepciones_cola", "tenant_id", "estado", "prioridad"),
        Index("ix_excepciones_registro", "tenant_id", "objeto", "objeto_id"),
        Index("ix_excepciones_regla", "tenant_id", "regla"),
    )


def abrir(
    uow: UnidadDeTrabajo,
    *,
    objeto: str,
    objeto_id: UUID,
    tipo: str,
    regla: str,
    detalle: str,
    campo: str = "",
    prioridad: int = 2,
    asignada_a: UUID | None = None,
    datos: dict[str, Any] | None = None,
) -> ExcepcionCalidad:
    """Abre una excepción, **sin duplicarla**.

    La misma regla sobre el mismo campo de la misma ficha es una excepción, no
    diez. Sin esto, el proceso nocturno abre otra cada noche y a la semana hay
    tres mil que son siete.
    """
    if tipo not in TIPOS:
        raise ErrorValidacion(
            f"Tipo de excepción «{tipo}» desconocido",
            error_code="calidad.tipo_invalido",
            detalle={"admitidos": list(TIPOS)},
        )
    if not regla.strip():
        raise ErrorValidacion(
            "Una excepción sin regla no se puede evaluar después: es lo que permite "
            "descubrir que una regla está generando ruido.",
            error_code="calidad.sin_regla",
        )

    existente = uow.db.execute(
        select(ExcepcionCalidad).where(
            ExcepcionCalidad.tenant_id == uow.tenant_id,
            ExcepcionCalidad.objeto == objeto,
            ExcepcionCalidad.objeto_id == objeto_id,
            ExcepcionCalidad.regla == regla,
            ExcepcionCalidad.campo == campo,
            ExcepcionCalidad.estado != "cerrada",
        )
    ).scalar_one_or_none()
    if existente is not None:
        existente.detalle = detalle
        existente.datos = dict(datos or {})
        uow.db.flush()
        return existente

    fila = ExcepcionCalidad(
        tenant_id=uow.tenant_id,
        objeto=objeto,
        objeto_id=objeto_id,
        tipo=tipo,
        campo=campo,
        regla=regla.strip(),
        detalle=detalle,
        prioridad=max(1, min(3, prioridad)),
        asignada_a=asignada_a,
        estado="asignada" if asignada_a else "abierta",
        datos=dict(datos or {}),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def asignar(uow: UnidadDeTrabajo, *, excepcion_id: UUID, a: UUID) -> ExcepcionCalidad:
    """Le pone nombre a una excepción.

    Una cola sin dueño crece hasta que nadie la abre: «el 38 % de las cuentas no
    tiene sector» se mira la primera semana y no la segunda.
    """
    fila = uow.db.get(ExcepcionCalidad, excepcion_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Esa excepción no existe", error_code="calidad.no_encontrada")
    if fila.estado == "cerrada":
        raise ErrorValidacion(
            "Esa excepción ya está cerrada: reasignarla la resucitaría sin que conste " "por qué.",
            error_code="calidad.ya_cerrada",
        )
    fila.asignada_a = a
    fila.estado = "asignada"
    uow.db.flush()
    return fila


def cerrar(
    uow: UnidadDeTrabajo, *, excepcion_id: UUID, cierre: str, nota: str, por: UUID
) -> dict[str, Any]:
    """Cierra una excepción diciendo **qué se hizo**.

    Un botón de «cerrar» a secas convierte la cola en un vertedero: se vacía y el
    dato sigue mal. Y «no se puede arreglar» exige nota, porque es la respuesta
    que hay que poder revisar dentro de seis meses — a veces lo que no se podía
    entonces sí se puede ahora.
    """
    if cierre not in CIERRES:
        raise ErrorValidacion(
            f"Cierre «{cierre}» desconocido",
            error_code="calidad.cierre_invalido",
            detalle={"admitidos": list(CIERRES)},
        )
    fila = uow.db.get(ExcepcionCalidad, excepcion_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Esa excepción no existe", error_code="calidad.no_encontrada")
    if cierre in ("no_se_puede_arreglar", "no_era_un_error") and not nota.strip():
        raise ErrorValidacion(
            f"Cerrar como «{cierre}» exige decir por qué. Sin el motivo, dentro de seis "
            "meses nadie sabrá si aquello sigue sin poder arreglarse o si la regla "
            "estaba mal.",
            error_code="calidad.cierre_sin_motivo",
        )

    fila.estado = "cerrada"
    fila.cierre = cierre
    fila.nota_de_cierre = nota.strip()
    fila.cerrada_at = _ahora()
    fila.cerrada_por = por
    uow.db.flush()
    return {"excepcion_id": str(fila.id), "cierre": cierre, "regla": fila.regla}


def cola(
    db: Session,
    tenant_id: UUID,
    *,
    de: UUID | None = None,
    sin_asignar: bool = False,
    limite: int = 50,
) -> dict[str, Any]:
    """La cola de trabajo, ordenada por lo que hay que mirar antes.

    Se dice aparte **cuántas no tiene nadie**: son las que nunca se van a hacer,
    y si no se cuentan el panel enseña una cola pequeña y sana que en realidad es
    una cola pequeña vigilada y otra grande abandonada.
    """
    condiciones = [
        ExcepcionCalidad.tenant_id == tenant_id,
        ExcepcionCalidad.estado != "cerrada",
    ]
    if de is not None:
        condiciones.append(ExcepcionCalidad.asignada_a == de)
    if sin_asignar:
        condiciones.append(ExcepcionCalidad.asignada_a.is_(None))

    filas = list(
        db.execute(
            select(ExcepcionCalidad)
            .where(*condiciones)
            .order_by(ExcepcionCalidad.prioridad, ExcepcionCalidad.created_at)
            .limit(limite)
        )
        .scalars()
        .all()
    )
    huerfanas = len(
        list(
            db.execute(
                select(ExcepcionCalidad).where(
                    ExcepcionCalidad.tenant_id == tenant_id,
                    ExcepcionCalidad.estado == "abierta",
                    ExcepcionCalidad.asignada_a.is_(None),
                )
            )
            .scalars()
            .all()
        )
    )

    return {
        "excepciones": [
            {
                "id": str(f.id),
                "objeto": f.objeto,
                "objeto_id": str(f.objeto_id),
                "tipo": f.tipo,
                "campo": f.campo,
                "regla": f.regla,
                "detalle": f.detalle,
                "prioridad": f.prioridad,
                "asignada_a": str(f.asignada_a) if f.asignada_a else None,
            }
            for f in filas
        ],
        "sin_asignar": huerfanas,
        "aviso": (
            ""
            if not huerfanas
            else f"{huerfanas} excepciones no tienen a nadie asignado. Son las que no "
            "se van a hacer: una cola sin dueño crece hasta que nadie la abre."
        ),
    }


def reglas_sospechosas(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Qué reglas están generando ruido en vez de trabajo.

    Si la misma regla produce cien excepciones que cien personas descartan como
    «no era un error», la rota es la regla. Sin esta vista, lo que se rompe es la
    credibilidad de la cola entera: en cuanto la mitad de lo que hay dentro no es
    un problema, se deja de abrir.
    """
    filas = list(
        db.execute(
            select(ExcepcionCalidad).where(
                ExcepcionCalidad.tenant_id == tenant_id,
                ExcepcionCalidad.estado == "cerrada",
            )
        )
        .scalars()
        .all()
    )
    por_regla: dict[str, dict[str, int]] = {}
    for fila in filas:
        datos = por_regla.setdefault(fila.regla, {"cerradas": 0, "descartadas": 0})
        datos["cerradas"] += 1
        if fila.cierre == "no_era_un_error":
            datos["descartadas"] += 1

    sospechosas = [
        {
            "regla": regla,
            "cerradas": d["cerradas"],
            "descartadas": d["descartadas"],
            "pct_descartadas": round(d["descartadas"] / d["cerradas"] * 100, 1),
        }
        for regla, d in por_regla.items()
        if d["descartadas"] >= DESCARTES_PARA_SOSPECHAR and d["descartadas"] / d["cerradas"] > 0.5
    ]

    return {
        "medible": bool(filas),
        "reglas": sorted(sospechosas, key=lambda r: -r["pct_descartadas"]),
        "que_significa": (
            "No se ha cerrado ninguna excepción todavía: no se puede decir si las "
            "reglas son buenas o si nadie está mirando la cola."
            if not filas
            else "Estas reglas producen más ruido que trabajo. La rota es la regla, no "
            "el dato: en cuanto la mitad de la cola no es un problema, se deja de abrir."
            if sospechosas
            else "Ninguna regla está generando ruido llamativo."
        ),
    }


# ── Enriquecimiento (CRM-01.01.04.09, CRM-01.01.01.08) ────────────────────


def planificar_enriquecimiento(
    *,
    candidatas: list[dict[str, Any]],
    coste_por_consulta: float,
    presupuesto: float | None = None,
    campos: list[str] | None = None,
) -> dict[str, Any]:
    """Qué se va a enriquecer, **cuánto va a costar y por qué esas**.

    Un botón de «enriquecer todo» sobre cuarenta mil cuentas es una factura que
    nadie aprobó. Se dice antes, no después.

    Y se priorizan las que **importan**: enriquecer cuentas inactivas de hace
    cinco años gasta el presupuesto en fichas que nadie va a abrir. Primero las
    vivas a las que les falta algo.
    """
    utiles = [
        c
        for c in candidatas
        if c.get("activa", True) and (c.get("faltan") or (campos and not c.get("completa")))
    ]
    descartadas = len(candidatas) - len(utiles)
    utiles.sort(key=lambda c: (-int(c.get("valor") or 0), -len(list(c.get("faltan") or []))))

    caben = len(utiles)
    if presupuesto is not None and coste_por_consulta > 0:
        caben = min(caben, int(presupuesto // coste_por_consulta))

    return {
        "se_consultan": caben,
        "coste_estimado": round(caben * coste_por_consulta, 2),
        "descartadas_por_inactivas_o_completas": descartadas,
        "no_caben_en_el_presupuesto": len(utiles) - caben,
        "orden": [str(c.get("id")) for c in utiles[:caben]],
        "porque_ese_orden": (
            "Primero las cuentas vivas con más valor y más huecos. Enriquecer fichas "
            "inactivas de hace cinco años gasta el presupuesto en algo que nadie va a "
            "abrir."
        ),
        "se_ejecuta_ya": False,
        "que_hacer": "Revisar el coste y confirmar. Una factura no se aprueba sola.",
    }


def aplicar_enriquecimiento(
    *,
    actuales: dict[str, Any],
    del_proveedor: dict[str, Any],
    escritos_a_mano: list[str] | None = None,
) -> dict[str, Any]:
    """Aplica lo que trae el proveedor **sin pisar lo que escribió una persona**.

    Un proveedor de datos sabe de muchas empresas y no conoce a ninguna; quien
    acaba de hablar con el cliente sí. Rellena huecos, no corrige a la gente.

    Lo que el proveedor dice distinto de lo que hay **no se descarta**: se
    devuelve como discrepancia para la cola de calidad. Puede que el dato del CRM
    esté viejo, y esa es justo la conversación que interesa tener.
    """
    manuales = set(escritos_a_mano or [])
    aplicados: dict[str, Any] = {}
    discrepancias: list[dict[str, Any]] = []
    respetados: list[str] = []

    for campo, valor in del_proveedor.items():
        if valor in (None, ""):
            continue
        actual = actuales.get(campo)
        if actual in (None, ""):
            aplicados[campo] = valor
            continue
        if campo in manuales:
            respetados.append(campo)
            if str(actual) != str(valor):
                discrepancias.append(
                    {
                        "campo": campo,
                        "en_el_crm": actual,
                        "dice_el_proveedor": valor,
                        "porque_no_se_pisa": (
                            "Lo escribió una persona. Puede que el CRM esté viejo, y por "
                            "eso se abre como excepción en vez de cambiarlo a su espalda."
                        ),
                    }
                )
            continue
        if str(actual) != str(valor):
            discrepancias.append(
                {
                    "campo": campo,
                    "en_el_crm": actual,
                    "dice_el_proveedor": valor,
                    "porque_no_se_pisa": (
                        "Ya había valor. El enriquecimiento rellena huecos; cambiar lo "
                        "que hay es una decisión y se toma mirándola."
                    ),
                }
            )

    return {
        "aplicados": aplicados,
        "campos_manuales_respetados": sorted(respetados),
        "discrepancias": discrepancias,
        "abrir_excepciones": bool(discrepancias),
        "porque": (
            "Se rellenan los huecos y se deja constancia de lo que no cuadra. Pisar lo "
            "que hay convierte al proveedor en la verdad, y el proveedor no ha hablado "
            "con el cliente."
        ),
    }


def caducidad_del_enriquecimiento(
    *, ultimo_at: datetime | None, dias: int = 180, ahora: datetime | None = None
) -> dict[str, Any]:
    """Cuándo toca volver a consultar a la fuente externa.

    Y si **nunca** se ha consultado se dice así, no «hace mucho»: no es lo mismo
    un dato que se comprobó hace un año que uno que no se ha comprobado jamás.
    """
    momento = ahora or _ahora()
    if ultimo_at is None:
        return {
            "toca": True,
            "nunca_consultado": True,
            "porque": (
                "Esta ficha no se ha enriquecido nunca. No es «hace mucho»: es que no "
                "se ha hecho, y son cosas distintas."
            ),
        }
    ultimo = ultimo_at if ultimo_at.tzinfo else ultimo_at.replace(tzinfo=timezone.utc)
    pasado = momento - ultimo
    return {
        "toca": pasado >= timedelta(days=dias),
        "nunca_consultado": False,
        "dias_desde_la_ultima": pasado.days,
        "porque": (
            f"Han pasado {pasado.days} días y el plazo son {dias}."
            if pasado >= timedelta(days=dias)
            else f"Se consultó hace {pasado.days} días; el plazo son {dias}."
        ),
    }
