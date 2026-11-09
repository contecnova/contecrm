"""El acuerdo de servicio del proveedor frente al que prometemos
(CRM-09.01.01.08).

Cuando quien da el servicio es un proveedor, el compromiso que se le firma al
cliente **no puede ser mejor que el que sostiene el proveedor**. Parece obvio y se
incumple constantemente: comercial promete cuatro horas de respuesta porque es lo
que pide el pliego, y el proveedor que va a ir tiene contratadas ocho.

Nadie miente. Simplemente **nadie compara los dos documentos**, porque están en
sitios distintos y los firma gente distinta. Eso es lo que hace esto: compararlos
antes de firmar y decir exactamente por cuánto no cuadra.

Y una segunda cosa, menos evidente: **los tiempos se suman**. Si el proveedor
responde en cuatro horas y hacen falta dos más para coordinar y desplazar, lo que
se le puede prometer al cliente son seis. Prometer las cuatro del proveedor es
prometer un tiempo que solo existiría si nosotros no hiciéramos nada.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Date, Numeric, String, Text, UniqueConstraint, or_, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Qué se compara. Cerrada porque cada métrica se mide distinto, y la que falta en
# la lista es la que nadie compara.
METRICAS = ("respuesta_h", "resolucion_h", "disponibilidad_pct", "cobertura_horaria")


def _horas_propias(horas: float | None, db: Session | None = None) -> float:
    """Lo que tardamos nosotros en medio: coordinar, abrir el parte, desplazar.

    No es un colchón inventado, es tiempo real que hay que sumar. Era una
    constante de una hora; ahora es el ajuste `sla_proveedor_horas_propias`,
    que cada empresa fija desde Admin."""
    if horas is not None:
        return float(horas)
    if db is not None:
        from crmcore.runtime import settings as rt

        valor = rt.efectivo("sla_proveedor_horas_propias", db)
        if valor is not None:
            return float(valor)
    from services.service.ajustes import ajustes

    return float(ajustes().sla_proveedor_horas_propias)


class AcuerdoProveedor(Base, TimestampMixin):
    """Lo que sostiene por contrato un proveedor de servicio (CRM-09.01.01.08).

    El proveedor vive en `integration` (`proveedores_servicio`, el mismo al que
    se le mandan los encargos) y allí sólo consta su plazo. Lo demás que firma
    —respuesta, disponibilidad, cobertura— se guarda aquí, junto a los
    derechos que prometemos al cliente, que es con lo que se compara. Se ata
    por la CLAVE del proveedor y no por su id: es la que se lee en pantalla y
    la que usan las reglas de reparto de encargos.
    """

    __tablename__ = "acuerdos_proveedor"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    proveedor_clave: Mapped[str] = mapped_column(String(60), nullable=False)
    respuesta_h: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    # Vacío: vale el plazo que consta del proveedor en `integration`.
    resolucion_h: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    disponibilidad_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    cobertura_horaria: Mapped[str | None] = mapped_column(String(40), nullable=True)
    vigente_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    notas: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "proveedor_clave", name="uq_acuerdo_proveedor"),
    )


def _h(valor: Any) -> str:
    """Un número de horas para leerlo: «24», no «24.0»."""
    return f"{float(valor):g}"


def comparar(
    *,
    prometido_al_cliente: dict[str, Any],
    del_proveedor: dict[str, Any],
    horas_propias: float | None = None,
) -> dict[str, Any]:
    """Compara lo que se le promete al cliente con lo que sostiene el proveedor.

    Devuelve **todos** los incumplimientos, no el primero: quien está revisando un
    pliego necesita ver las tres cosas que no cuadran de una vez, porque con ellas
    negocia una sola conversación en vez de tres.

    Y lo que no consta **no se da por bueno**: un proveedor que no declara su
    tiempo de resolución no es que lo tenga bien, es que no lo ha dicho — y
    firmarlo así es firmar sin saber.
    """
    horas_propias = _horas_propias(horas_propias)
    problemas: list[dict[str, Any]] = []
    sin_declarar: list[str] = []

    for metrica in METRICAS:
        prometido = prometido_al_cliente.get(metrica)
        if prometido is None:
            continue
        soportado = del_proveedor.get(metrica)
        if soportado is None:
            sin_declarar.append(metrica)
            continue

        if metrica.endswith("_h"):
            # Tiempos: el nuestro tiene que ser MAYOR que el suyo más lo que
            # tardamos en medio. Prometer su mismo tiempo es prometer uno que
            # solo existiría si nosotros no hiciéramos nada.
            necesario = float(soportado) + horas_propias
            if float(prometido) < necesario:
                problemas.append(
                    {
                        "metrica": metrica,
                        "prometido": prometido,
                        "del_proveedor": soportado,
                        "hace_falta_al_menos": necesario,
                        "porque": (
                            f"Se prometen {_h(prometido)} h y el proveedor sostiene "
                            f"{_h(soportado)} h; sumando {_h(horas_propias)} h de coordinación "
                            f"y desplazamiento hacen falta {_h(necesario)} h. La diferencia no "
                            "la absorbe nadie: la paga el incumplimiento."
                        ),
                    }
                )
        elif metrica == "disponibilidad_pct":
            if float(prometido) > float(soportado):
                problemas.append(
                    {
                        "metrica": metrica,
                        "prometido": prometido,
                        "del_proveedor": soportado,
                        "porque": (
                            f"Se promete un {prometido} % sobre una infraestructura que "
                            f"garantiza un {soportado} %. La diferencia es optimismo "
                            "contractual."
                        ),
                    }
                )
        elif str(prometido) != str(soportado) and str(soportado) != "24x7":
            problemas.append(
                {
                    "metrica": metrica,
                    "prometido": prometido,
                    "del_proveedor": soportado,
                    "porque": (
                        f"Se promete cobertura «{prometido}» y el proveedor cubre "
                        f"«{soportado}». Lo que pase fuera de su horario lo cubre quien "
                        "lo firmó, que somos nosotros."
                    ),
                }
            )

    return {
        "se_sostiene": not problemas and not sin_declarar,
        "problemas": problemas,
        "sin_declarar_por_el_proveedor": sin_declarar,
        "veredicto": (
            "Lo que se le promete al cliente lo sostiene el proveedor con margen."
            if not problemas and not sin_declarar
            else "Hay compromisos que el proveedor no sostiene. Nadie miente: es que "
            "los dos documentos están en sitios distintos y los firma gente distinta."
        ),
        "aviso": (
            ""
            if not sin_declarar
            else f"El proveedor no declara {', '.join(sin_declarar)}. Eso no es que lo "
            "tenga bien: es que no lo ha dicho, y firmarlo así es firmar sin saber."
        ),
    }


def maximo_que_se_puede_prometer(
    *, del_proveedor: dict[str, Any], horas_propias: float | None = None
) -> dict[str, Any]:
    """Lo mejor que se puede firmar con este proveedor detrás.

    Sirve para la conversación al revés: en vez de comprobar un pliego ya escrito,
    decirle al comercial qué puede ofrecer **antes** de escribirlo. Es más barato
    que descubrirlo en la revisión legal, y mucho más que descubrirlo en la
    primera incidencia.
    """
    if not del_proveedor:
        raise ErrorValidacion(
            "No consta el acuerdo del proveedor. Sin él no se puede decir qué se puede "
            "prometer: se puede adivinar, que es lo que se hace ahora y lo que este "
            "módulo existe para evitar.",
            error_code="sla.proveedor_sin_acuerdo",
        )
    horas_propias = _horas_propias(horas_propias)
    salida: dict[str, Any] = {}
    for metrica, valor in del_proveedor.items():
        if metrica.endswith("_h"):
            salida[metrica] = float(valor) + horas_propias
        else:
            salida[metrica] = valor
    return {
        "maximo": salida,
        "horas_propias_incluidas": horas_propias,
        "porque": (
            "A lo que sostiene el proveedor se le suma lo que tardamos nosotros en "
            "coordinar y desplazar. Prometer su mismo tiempo es prometer uno que solo "
            "existiría si nosotros no hiciéramos nada."
        ),
    }


# ── Lo guardado frente a lo prometido ──────────────────────────────────────


CAMPOS_ACUERDO = ("respuesta_h", "resolucion_h", "disponibilidad_pct", "cobertura_horaria")


def _num(v: Any) -> float | None:
    return None if v is None else float(v)


def acuerdo_como_dict(fila: AcuerdoProveedor) -> dict[str, Any]:
    return {
        "id": str(fila.id),
        "proveedor_clave": fila.proveedor_clave,
        "respuesta_h": _num(fila.respuesta_h),
        "resolucion_h": _num(fila.resolucion_h),
        "disponibilidad_pct": _num(fila.disponibilidad_pct),
        "cobertura_horaria": fila.cobertura_horaria,
        "vigente_hasta": str(fila.vigente_hasta) if fila.vigente_hasta else None,
        "notas": fila.notas,
    }


def acuerdos(db: Session, tenant_id: UUID) -> list[AcuerdoProveedor]:
    return list(
        db.execute(
            select(AcuerdoProveedor)
            .where(AcuerdoProveedor.tenant_id == tenant_id)
            .order_by(AcuerdoProveedor.proveedor_clave)
        )
        .scalars()
        .all()
    )


def guardar_acuerdo(
    db: Session, tenant_id: UUID, proveedor_clave: str, datos: dict[str, Any]
) -> AcuerdoProveedor:
    """Alta o cambio del acuerdo de un proveedor. Se cambia sólo lo enviado."""
    clave = proveedor_clave.strip()
    if not clave:
        raise ErrorValidacion("Falta el proveedor.", error_code="sla.proveedor_sin_clave")
    fila = db.execute(
        select(AcuerdoProveedor).where(
            AcuerdoProveedor.tenant_id == tenant_id,
            AcuerdoProveedor.proveedor_clave == clave,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = AcuerdoProveedor(tenant_id=tenant_id, proveedor_clave=clave, notas="")
        db.add(fila)
    for campo, valor in datos.items():
        if campo in (*CAMPOS_ACUERDO, "vigente_hasta", "notas"):
            setattr(fila, campo, valor if campo != "notas" else (valor or ""))
    db.flush()
    return fila


def borrar_acuerdo(db: Session, tenant_id: UUID, proveedor_clave: str) -> None:
    fila = db.execute(
        select(AcuerdoProveedor).where(
            AcuerdoProveedor.tenant_id == tenant_id,
            AcuerdoProveedor.proveedor_clave == proveedor_clave,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Ese proveedor no tiene acuerdo.", error_code="sla.acuerdo_no_existe")
    db.delete(fila)
    db.flush()


def del_proveedor(
    acuerdo: AcuerdoProveedor | None, en_integracion: dict[str, Any] | None
) -> dict[str, Any]:
    """Lo que sostiene el proveedor: su acuerdo, y su plazo de `integration`
    para la resolución si el acuerdo no la declara."""
    salida: dict[str, Any] = {}
    if acuerdo is not None:
        for campo in CAMPOS_ACUERDO:
            valor = getattr(acuerdo, campo)
            if valor is not None:
                salida[campo] = _num(valor) if campo != "cobertura_horaria" else valor
    plazo = (en_integracion or {}).get("plazo_horas")
    if "resolucion_h" not in salida and plazo is not None:
        salida["resolucion_h"] = float(plazo)
    return salida


def _sla_vigente(db: Session, tenant_id: UUID, clave: str) -> Any:
    from services.service.modelos import DefinicionSLA

    return (
        db.execute(
            select(DefinicionSLA)
            .where(
                DefinicionSLA.tenant_id == tenant_id,
                DefinicionSLA.clave == clave,
                DefinicionSLA.activa.is_(True),
            )
            .order_by(DefinicionSLA.version.desc())
        )
        .scalars()
        .first()
    )


def revisar(
    db: Session,
    tenant_id: UUID,
    *,
    proveedores: dict[str, dict[str, Any]] | None,
    horas_propias: float | None = None,
) -> dict[str, Any]:
    """Cada derecho que prometemos con un proveedor detrás, contra lo que
    ese proveedor sostiene.

    `proveedores` es lo que `integration` dice que hay, por clave; `None` si no
    contestó, que **no es lo mismo que «no hay ninguno»**: entonces se compara
    con los acuerdos guardados y se dice que el plazo de allí no se pudo leer.
    """
    from services.service.entitlements import Entitlement

    horas = _horas_propias(horas_propias, db)
    dia = hoy(db)
    derechos = (
        db.execute(
            select(Entitlement)
            .where(
                Entitlement.tenant_id == tenant_id,
                Entitlement.deleted_at.is_(None),
                Entitlement.activo.is_(True),
                Entitlement.proveedor_clave.isnot(None),
                or_(Entitlement.vigente_hasta.is_(None), Entitlement.vigente_hasta >= dia),
            )
            .order_by(Entitlement.clave)
        )
        .scalars()
        .all()
    )
    por_clave = {a.proveedor_clave: a for a in acuerdos(db, tenant_id)}
    filas: list[dict[str, Any]] = []
    for d in derechos:
        clave = str(d.proveedor_clave)
        en_integracion = (proveedores or {}).get(clave)
        acuerdo = por_clave.get(clave)
        sostiene = del_proveedor(acuerdo, en_integracion)
        sla = _sla_vigente(db, tenant_id, d.sla_clave) if d.sla_clave else None
        prometido: dict[str, Any] = {}
        if sla is not None:
            if sla.horas_primera_respuesta is not None:
                prometido["respuesta_h"] = float(sla.horas_primera_respuesta)
            if sla.horas_resolucion is not None:
                prometido["resolucion_h"] = float(sla.horas_resolucion)
        if not prometido:
            veredicto = "sin_compromiso"
            comparacion = None
        elif not sostiene:
            veredicto = "sin_acuerdo"
            comparacion = None
        else:
            comparacion = comparar(
                prometido_al_cliente=prometido, del_proveedor=sostiene, horas_propias=horas
            )
            veredicto = "se_sostiene" if comparacion["se_sostiene"] else "no_se_sostiene"
        filas.append(
            {
                "entitlement_id": str(d.id),
                "entitlement": d.nombre,
                "entitlement_clave": d.clave,
                "cuenta_id": str(d.cuenta_id) if d.cuenta_id else None,
                "sla_clave": d.sla_clave,
                "proveedor_clave": clave,
                "proveedor": (en_integracion or {}).get("nombre") or clave,
                # Sólo se puede afirmar que no existe si integración contestó.
                "proveedor_existe": (None if proveedores is None else en_integracion is not None),
                "prometido": prometido,
                "del_proveedor": sostiene,
                "veredicto": veredicto,
                "problemas": (comparacion or {}).get("problemas", []),
                "sin_declarar": (comparacion or {}).get("sin_declarar_por_el_proveedor", []),
                "aviso": (comparacion or {}).get("aviso", ""),
            }
        )
    no_cumplen = [f for f in filas if f["veredicto"] in ("no_se_sostiene", "sin_acuerdo")]
    return {
        "revisados": len(filas),
        "no_se_sostienen": len([f for f in filas if f["veredicto"] == "no_se_sostiene"]),
        "sin_acuerdo": len([f for f in filas if f["veredicto"] == "sin_acuerdo"]),
        "sin_compromiso": len([f for f in filas if f["veredicto"] == "sin_compromiso"]),
        "horas_propias": horas,
        "integracion_respondio": proveedores is not None,
        "proveedores": [
            {"clave": c, "nombre": p.get("nombre") or c, "plazo_horas": p.get("plazo_horas")}
            for c, p in sorted((proveedores or {}).items())
        ],
        "filas": filas,
        "hay_avisos": bool(no_cumplen),
    }
