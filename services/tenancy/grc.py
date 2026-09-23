"""GRC — gobierno, riesgo y cumplimiento (CRM-07.03.02.*).

El GRC clásico son riesgos, controles y evaluaciones periódicas, y eso ya lo
sabe hacer la casa: hay 740 líneas en contecmind y 786 en contecweb. Lo que
cambia aquí son dos cosas, y las dos vienen de que este producto tiene un
catálogo funcional con identificadores estables.

**Cada control se ancla a capacidades del catálogo por su identificador.** Un
GRC donde los controles se escriben a mano describe un sistema imaginado, no el
que hay, y a los dos trimestres describe uno que ya no existe. Con el anclaje,
la cobertura es medible —«de las 631 capacidades, cuáles tienen control»— y
crece sola con el producto. Se comprueba al guardar: un control sobre
`CRM-99.99.99.99` no se guarda.

**El informe va en los dos sentidos.** El que todo el mundo hace es «qué
capacidades no tienen control». El que nadie hace es el de vuelta: **qué
controles apuntan a capacidades que ya no existen**, que es como se detecta que
un control lleva un año cubriendo algo que se quitó.

Y una tercera, sobre las evidencias: **las pone el sistema, no una persona**.
El audit trail, los certificados de destrucción y los gates locales ya generan
la prueba; adjuntarla a mano es como un GRC se queda desactualizado el segundo
trimestre.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Escalas de 1 a 5. Cerradas a propósito: una escala abierta hace que dos
# riesgos evaluados por dos personas no se puedan comparar, que es justo lo
# único que un mapa de riesgos tiene que permitir.
ESCALA = (1, 2, 3, 4, 5)
TRATAMIENTOS = ("mitigar", "aceptar", "transferir", "evitar")
ESTADOS_RIESGO = ("abierto", "en_tratamiento", "cerrado")
TIPOS_CONTROL = ("preventivo", "detectivo", "correctivo")
FRECUENCIAS = ("continuo", "diario", "semanal", "mensual", "trimestral", "semestral", "anual")
RESULTADOS = ("efectivo", "parcial", "inefectivo", "no_aplica")


class Riesgo(Base):
    """Un riesgo del registro, con su tratamiento y su residual (CRM-07.03.02.01).

    Se guarda el residual aparte del inherente porque la diferencia entre los
    dos **es** el valor del control. Un registro que solo anota el inherente no
    puede responder si el tratamiento sirvió de algo.
    """

    __tablename__ = "grc_riesgos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    codigo: Mapped[str] = mapped_column(String(40), nullable=False)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    categoria: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    probabilidad: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    impacto: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    propietario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    tratamiento: Mapped[str] = mapped_column(String(20), nullable=False, default="mitigar")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="abierto")
    residual_probabilidad: Mapped[int | None] = mapped_column(Integer, nullable=True)
    residual_impacto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("uq_grc_riesgo", "tenant_id", "codigo", unique=True),)

    @property
    def inherente(self) -> int:
        return self.probabilidad * self.impacto

    @property
    def residual(self) -> int | None:
        if self.residual_probabilidad is None or self.residual_impacto is None:
            return None
        return self.residual_probabilidad * self.residual_impacto


class Control(Base):
    """Un control, anclado a lo que de verdad hace el producto (CRM-07.03.02.02).

    `capacidades` es la lista de identificadores del catálogo que este control
    cubre, y es lo que convierte el GRC en algo medible sobre el sistema real en
    vez de sobre uno descrito en un documento.
    """

    __tablename__ = "grc_controles"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    codigo: Mapped[str] = mapped_column(String(40), nullable=False)
    nombre: Mapped[str] = mapped_column(String(300), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="preventivo")
    automatico: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    frecuencia: Mapped[str] = mapped_column(String(20), nullable=False, default="trimestral")
    responsable_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Identificadores del catálogo funcional que este control cubre.
    capacidades: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    # Riesgos que mitiga, por su código.
    riesgos: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    # Obligaciones normativas: [{"marco": "ISO 27001", "referencia": "A.9.2.3"}].
    marcos: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    # De dónde sale la prueba sola: `audit_trail`, `certificados_destruccion`,
    # `gates`, `politicas_abac`… Vacío = la aporta una persona.
    fuente_evidencia: Mapped[str] = mapped_column(String(60), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("uq_grc_control", "tenant_id", "codigo", unique=True),)


class EvaluacionControl(Base):
    """Qué dio el control la última vez que se miró, y con qué prueba.

    CRM-07.03.02.03: la evaluación periódica, con resultado, evidencia y plan
    de acción.
    """

    __tablename__ = "grc_evaluaciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    control_codigo: Mapped[str] = mapped_column(String(40), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    resultado: Mapped[str] = mapped_column(String(20), nullable=False)
    evidencia: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    observaciones: Mapped[str] = mapped_column(Text, nullable=False, default="")
    plan_accion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Cuándo toca la siguiente. Se calcula de la frecuencia del control: dejarlo
    # a mano es cómo un control «trimestral» pasa dieciocho meses sin mirarse.
    proxima_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    evaluado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_grc_evaluaciones", "tenant_id", "control_codigo", "fecha"),)


# ── Riesgos ───────────────────────────────────────────────────────────────


def guardar_riesgo(
    db: Session,
    *,
    tenant_id: UUID,
    codigo: str,
    titulo: str,
    descripcion: str = "",
    categoria: str = "",
    probabilidad: int = 3,
    impacto: int = 3,
    propietario_id: UUID | None = None,
    tratamiento: str = "mitigar",
    estado: str = "abierto",
    residual_probabilidad: int | None = None,
    residual_impacto: int | None = None,
    revision_at: date | None = None,
) -> Riesgo:
    _en(probabilidad, ESCALA, "probabilidad")
    _en(impacto, ESCALA, "impacto")
    _en(tratamiento, TRATAMIENTOS, "tratamiento")
    _en(estado, ESTADOS_RIESGO, "estado")
    for valor, nombre in (
        (residual_probabilidad, "residual_probabilidad"),
        (residual_impacto, "residual_impacto"),
    ):
        if valor is not None:
            _en(valor, ESCALA, nombre)
    if not (codigo or "").strip():
        raise ErrorValidacion("El riesgo necesita un código", error_code="grc.riesgo_sin_codigo")
    # Un riesgo que se acepta sin decir cuál queda después no se ha evaluado: se
    # ha archivado. Es la trampa más común de un registro de riesgos.
    if tratamiento == "aceptar" and (residual_probabilidad is None or residual_impacto is None):
        raise ErrorValidacion(
            "Aceptar un riesgo exige declarar el residual: aceptar sin decir cuánto "
            "queda no es una decisión, es archivarlo",
            error_code="grc.aceptar_sin_residual",
        )

    fila = db.execute(
        select(Riesgo).where(Riesgo.tenant_id == tenant_id, Riesgo.codigo == codigo)
    ).scalar_one_or_none()
    if fila is None:
        fila = Riesgo(tenant_id=tenant_id, codigo=codigo)
        db.add(fila)
    fila.titulo = titulo
    fila.descripcion = descripcion
    fila.categoria = categoria
    fila.probabilidad = probabilidad
    fila.impacto = impacto
    fila.propietario_id = propietario_id
    fila.tratamiento = tratamiento
    fila.estado = estado
    fila.residual_probabilidad = residual_probabilidad
    fila.residual_impacto = residual_impacto
    fila.revision_at = revision_at
    db.flush()
    logger.info("grc.riesgo_guardado", codigo=codigo, inherente=fila.inherente)
    return fila


# ── Controles ─────────────────────────────────────────────────────────────


def guardar_control(
    db: Session,
    *,
    tenant_id: UUID,
    codigo: str,
    nombre: str,
    descripcion: str = "",
    tipo: str = "preventivo",
    automatico: bool = False,
    frecuencia: str = "trimestral",
    responsable_id: UUID | None = None,
    activo: bool = True,
    capacidades: list[str] | None = None,
    riesgos: list[str] | None = None,
    marcos: list[dict[str, str]] | None = None,
    fuente_evidencia: str = "",
) -> Control:
    """Crea o actualiza un control, comprobando a qué se ancla.

    Las capacidades se validan contra el catálogo: sin esto, un control sobre
    `CRM-99.99.99.99` se guardaría tan tranquilo y el informe de cobertura
    contaría un control que no cubre nada. Y los riesgos, contra el registro:
    un control que dice mitigar un riesgo que no existe es un control huérfano
    presentado como tratamiento.
    """
    from crmcore.catalogo import capacidades as catalogo
    from crmcore.catalogo import disponible

    _en(tipo, TIPOS_CONTROL, "tipo")
    _en(frecuencia, FRECUENCIAS, "frecuencia")
    if not (codigo or "").strip():
        raise ErrorValidacion("El control necesita un código", error_code="grc.control_sin_codigo")

    capacidades = list(capacidades or [])
    if capacidades and disponible():
        conocidas = catalogo()
        desconocidas = sorted(c for c in capacidades if c not in conocidas)
        if desconocidas:
            raise ErrorValidacion(
                "Ese control se ancla a capacidades que no existen en el catálogo",
                error_code="grc.capacidad_desconocida",
                detalle={"desconocidas": desconocidas},
            )

    riesgos = list(riesgos or [])
    if riesgos:
        existentes = set(
            db.execute(select(Riesgo.codigo).where(Riesgo.tenant_id == tenant_id)).scalars().all()
        )
        faltan = sorted(set(riesgos) - existentes)
        if faltan:
            raise ErrorValidacion(
                "Ese control dice mitigar riesgos que no están en el registro",
                error_code="grc.riesgo_desconocido",
                detalle={"desconocidos": faltan},
            )

    fila = db.execute(
        select(Control).where(Control.tenant_id == tenant_id, Control.codigo == codigo)
    ).scalar_one_or_none()
    if fila is None:
        fila = Control(tenant_id=tenant_id, codigo=codigo)
        db.add(fila)
    fila.nombre = nombre
    fila.descripcion = descripcion
    fila.tipo = tipo
    fila.automatico = automatico
    fila.frecuencia = frecuencia
    fila.responsable_id = responsable_id
    fila.activo = activo
    fila.capacidades = capacidades
    fila.riesgos = riesgos
    fila.marcos = list(marcos or [])
    fila.fuente_evidencia = fuente_evidencia
    db.flush()
    logger.info("grc.control_guardado", codigo=codigo, capacidades=len(capacidades))
    return fila


# Días entre evaluaciones según la frecuencia declarada. Se calcula y no se pide
# a mano porque una fecha de próxima revisión escrita por una persona es la
# primera que se queda sin poner.
DIAS_FRECUENCIA = {
    "continuo": 1,
    "diario": 1,
    "semanal": 7,
    "mensual": 30,
    "trimestral": 91,
    "semestral": 182,
    "anual": 365,
}


def evaluar_control(
    db: Session,
    *,
    tenant_id: UUID,
    control_codigo: str,
    resultado: str,
    fecha: date | None = None,
    observaciones: str = "",
    plan_accion: str = "",
    evidencia: dict[str, Any] | None = None,
    por: UUID | None = None,
) -> EvaluacionControl:
    """Anota una evaluación y calcula cuándo toca la siguiente.

    Un resultado distinto de «efectivo» **exige plan de acción**. Sin esa
    obligación, el registro se llena de controles «parciales» que nadie
    arregla, y el GRC pasa de herramienta a archivo.
    """
    from datetime import timedelta

    _en(resultado, RESULTADOS, "resultado")
    control = db.execute(
        select(Control).where(Control.tenant_id == tenant_id, Control.codigo == control_codigo)
    ).scalar_one_or_none()
    if control is None:
        raise NoEncontrado("Ese control no existe", error_code="grc.control_no_existe")
    if resultado in ("parcial", "inefectivo") and not plan_accion.strip():
        raise Conflicto(
            "Un control que no es efectivo necesita plan de acción",
            error_code="grc.sin_plan_de_accion",
        )

    cuando = fecha or datetime.now(timezone.utc).date()
    fila = EvaluacionControl(
        tenant_id=tenant_id,
        control_codigo=control_codigo,
        fecha=cuando,
        resultado=resultado,
        evidencia=evidencia or _evidencia_automatica(db, tenant_id, control),
        observaciones=observaciones,
        plan_accion=plan_accion,
        proxima_at=cuando + timedelta(days=DIAS_FRECUENCIA.get(control.frecuencia, 91)),
        evaluado_por=por,
    )
    db.add(fila)
    db.flush()
    logger.info("grc.control_evaluado", control=control_codigo, resultado=resultado)
    return fila


def _evidencia_automatica(db: Session, tenant_id: UUID, control: Control) -> dict[str, Any]:
    """La prueba que el propio sistema ya genera (CRM-07.03.02.08).

    Adjuntar la evidencia a mano es como un GRC se queda desactualizado el
    segundo trimestre: la persona que la sacaba cambia de puesto y nadie más
    sabe de dónde salía. Aquí el control declara su fuente y el sistema la lee.

    Una fuente que no se sabe leer se dice en la propia evidencia, en vez de
    devolver un diccionario vacío que parecería «no hay nada que probar».
    """
    fuente = control.fuente_evidencia
    if not fuente:
        return {}
    try:
        if fuente == "audit_trail":
            # `ApunteAuditoria`, no `EntradaAuditoria`: ese nombre no existe.
            # El `except` de abajo convertía el `ImportError` en un control
            # que informaba de un error de evidencia — nunca en una cifra—,
            # así que este control no se pudo evaluar jamás.
            from crmcore.audit.modelos import ApunteAuditoria

            cuantas = db.execute(
                select(func.count())
                .select_from(ApunteAuditoria)
                .where(ApunteAuditoria.tenant_id == tenant_id)
            ).scalar_one()
            return {"fuente": fuente, "entradas_de_auditoria": int(cuantas)}
        if fuente == "politicas_abac":
            from crmcore.authz.politicas import PoliticaAbac

            activas = db.execute(
                select(func.count())
                .select_from(PoliticaAbac)
                .where(PoliticaAbac.tenant_id == tenant_id, PoliticaAbac.activa.is_(True))
            ).scalar_one()
            return {"fuente": fuente, "politicas_activas": int(activas)}
        if fuente == "certificados_destruccion":
            from services.tenancy.baja import CertificadoDestruccion

            cuantos = db.execute(
                select(func.count())
                .select_from(CertificadoDestruccion)
                .where(CertificadoDestruccion.tenant_id == tenant_id)
            ).scalar_one()
            return {"fuente": fuente, "certificados": int(cuantos)}
    except Exception as exc:  # noqa: BLE001 — la evidencia que falla se dice
        return {"fuente": fuente, "error": str(exc)[:200]}
    return {"fuente": fuente, "error": "fuente no reconocida"}


def _en(valor: Any, admitidos: tuple[Any, ...], campo: str) -> None:
    if valor not in admitidos:
        raise ErrorValidacion(
            f"«{campo}» admite {', '.join(str(a) for a in admitidos)}, no «{valor}»",
            error_code=f"grc.{campo}_invalido",
        )


# ── Cobertura sobre el catálogo (CRM-07.03.02.05) ─────────────────────────


def cobertura(db: Session, tenant_id: UUID, *, solo_hechas: bool = False) -> dict[str, Any]:
    """Qué del producto tiene control y qué no, medido sobre el catálogo.

    Los dos sentidos, y el segundo es el que importa:

      * **Qué capacidades no tienen control.** Es la lista de trabajo.
      * **Qué controles apuntan a capacidades que ya no existen.** Es como se
        detecta que un control lleva un año cubriendo algo que se quitó del
        producto — y ningún GRC lo mira, porque hay que ir a buscarlo.

    Con `solo_hechas` se mide únicamente sobre lo entregado, que es lo que un
    auditor puede comprobar hoy. Sin ello se mide sobre el catálogo entero, que
    es lo que dice cuánto queda por cubrir cuando eso se entregue.
    """
    from crmcore.catalogo import capacidades as catalogo
    from crmcore.catalogo import disponible

    if not disponible():
        # Se dice, en vez de devolver ceros: una cobertura del 0 % y una
        # cobertura que no se ha podido medir se leen igual y significan cosas
        # opuestas.
        return {
            "medible": False,
            "motivo": "El catálogo funcional no está disponible en este despliegue",
        }

    todas = catalogo()
    universo = {
        cid: cap for cid, cap in todas.items() if not solo_hechas or cap["estado"] == "hecho"
    }

    controles = (
        db.execute(select(Control).where(Control.tenant_id == tenant_id, Control.activo.is_(True)))
        .scalars()
        .all()
    )
    por_capacidad: dict[str, list[str]] = {}
    huerfanos: list[dict[str, Any]] = []
    for control in controles:
        fuera = [c for c in (control.capacidades or []) if c not in todas]
        if fuera:
            huerfanos.append({"control": control.codigo, "capacidades": sorted(fuera)})
        for cid in control.capacidades or []:
            if cid in universo:
                por_capacidad.setdefault(cid, []).append(control.codigo)

    sin_control = sorted(cid for cid in universo if cid not in por_capacidad)
    # Agrupado por sección: una lista de cuatrocientos identificadores no la
    # lee nadie, y por sección se ve de un vistazo qué área está descubierta.
    por_seccion: dict[str, dict[str, int]] = {}
    for cid, cap in universo.items():
        fila = por_seccion.setdefault(cap["seccion"], {"total": 0, "con_control": 0})
        fila["total"] += 1
        if cid in por_capacidad:
            fila["con_control"] += 1

    return {
        "medible": True,
        "alcance": "solo capacidades hechas" if solo_hechas else "catálogo completo",
        "capacidades": len(universo),
        "con_control": len(por_capacidad),
        "sin_control": len(sin_control),
        # Dos decimales y no uno: con setecientas capacidades en el catálogo, un
        # control cubre el 0,14 %, y redondeando a un decimal la cobertura sobre
        # lo entregado y la cobertura sobre todo salen iguales — con lo que la
        # distinción que este informe existe para enseñar no se ve.
        "pct": round(len(por_capacidad) / len(universo) * 100, 2) if universo else 0.0,
        "por_seccion": {
            nombre: {
                **datos,
                "pct": round(datos["con_control"] / datos["total"] * 100, 2),
            }
            for nombre, datos in sorted(por_seccion.items())
        },
        "capacidades_sin_control": sin_control,
        # El informe al revés.
        "controles_sobre_capacidades_inexistentes": huerfanos,
    }


def por_marco(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Del marco normativo a las capacidades del producto (CRM-07.03.02.07).

    Un auditor pregunta por ISO 27001 A.9 y esto contesta qué controles
    responden, qué capacidades del producto los sostienen y cuándo se evaluaron
    por última vez. El recorrido de vuelta —de una capacidad a sus
    obligaciones— sale del mismo dato y lo devuelve `obligaciones_de`.
    """
    from crmcore.catalogo import descripcion

    controles = db.execute(select(Control).where(Control.tenant_id == tenant_id)).scalars().all()
    ultimas = _ultimas_evaluaciones(db, tenant_id)

    salida: dict[str, dict[str, Any]] = {}
    for control in controles:
        for marco in control.marcos or []:
            if not isinstance(marco, dict):
                continue
            clave = str(marco.get("marco", "")).strip()
            referencia = str(marco.get("referencia", "")).strip()
            if not clave:
                continue
            nodo = salida.setdefault(clave, {"referencias": {}})
            entrada = nodo["referencias"].setdefault(referencia, {"controles": []})
            ultima = ultimas.get(control.codigo)
            entrada["controles"].append(
                {
                    "codigo": control.codigo,
                    "nombre": control.nombre,
                    "activo": control.activo,
                    "capacidades": [
                        {"id": cid, "titulo": descripcion(cid)}
                        for cid in (control.capacidades or [])
                    ],
                    "ultima_evaluacion": ultima,
                }
            )
    return salida


def obligaciones_de(db: Session, tenant_id: UUID, capacidad_id: str) -> dict[str, Any]:
    """De una capacidad del producto a las obligaciones que responde.

    Es el recorrido de vuelta, y es el que convierte el GRC en algo útil para
    quien construye: antes de tocar una capacidad se puede ver a qué
    obligaciones está respondiendo.
    """
    from crmcore.catalogo import capacidades as catalogo

    controles = [
        c
        for c in db.execute(select(Control).where(Control.tenant_id == tenant_id)).scalars().all()
        if capacidad_id in (c.capacidades or [])
    ]
    return {
        "capacidad": catalogo().get(capacidad_id, {"id": capacidad_id}),
        "controles": [
            {
                "codigo": c.codigo,
                "nombre": c.nombre,
                "activo": c.activo,
                "marcos": c.marcos,
                "riesgos": c.riesgos,
            }
            for c in controles
        ],
        "sin_control": not controles,
    }


def _ultimas_evaluaciones(db: Session, tenant_id: UUID) -> dict[str, dict[str, Any]]:
    filas = (
        db.execute(
            select(EvaluacionControl)
            .where(EvaluacionControl.tenant_id == tenant_id)
            .order_by(EvaluacionControl.fecha.desc())
        )
        .scalars()
        .all()
    )
    ultimas: dict[str, dict[str, Any]] = {}
    for fila in filas:
        ultimas.setdefault(
            fila.control_codigo,
            {
                "fecha": fila.fecha.isoformat(),
                "resultado": fila.resultado,
                "proxima_at": fila.proxima_at.isoformat() if fila.proxima_at else None,
            },
        )
    return ultimas


def vencidos(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Lo que no cuadra hoy: sin evaluar, fuera de plazo y sin tratamiento.

    Un GRC sin esta vista es un archivo. Lo que hace que se use es que alguien
    pueda abrir una pantalla y ver exactamente qué le falta.
    """
    hoy = datetime.now(timezone.utc).date()
    controles = (
        db.execute(select(Control).where(Control.tenant_id == tenant_id, Control.activo.is_(True)))
        .scalars()
        .all()
    )
    ultimas = _ultimas_evaluaciones(db, tenant_id)

    nunca = [c.codigo for c in controles if c.codigo not in ultimas]
    fuera_de_plazo = [
        {"control": c.codigo, "vencio": ultimas[c.codigo]["proxima_at"]}
        for c in controles
        if c.codigo in ultimas
        and ultimas[c.codigo]["proxima_at"]
        and date.fromisoformat(ultimas[c.codigo]["proxima_at"]) < hoy
    ]
    no_efectivos = [
        {"control": codigo, "resultado": datos["resultado"]}
        for codigo, datos in ultimas.items()
        if datos["resultado"] in ("parcial", "inefectivo")
    ]
    riesgos_sin_tratar = [
        r.codigo
        for r in db.execute(
            select(Riesgo).where(
                Riesgo.tenant_id == tenant_id,
                Riesgo.estado == "abierto",
                Riesgo.tratamiento == "mitigar",
            )
        )
        .scalars()
        .all()
        if not _tiene_control(db, tenant_id, r.codigo)
    ]
    return {
        "controles_nunca_evaluados": sorted(nunca),
        "controles_fuera_de_plazo": fuera_de_plazo,
        "controles_no_efectivos": no_efectivos,
        # Un riesgo que se decide mitigar y no tiene ningún control es una
        # decisión sin ejecución: el caso que más veces sale en una auditoría.
        "riesgos_a_mitigar_sin_control": sorted(riesgos_sin_tratar),
    }


def _tiene_control(db: Session, tenant_id: UUID, riesgo_codigo: str) -> bool:
    for control in (
        db.execute(select(Control).where(Control.tenant_id == tenant_id, Control.activo.is_(True)))
        .scalars()
        .all()
    ):
        if riesgo_codigo in (control.riesgos or []):
            return True
    return False


# ── Aportación al informe de cumplimiento (CRM-07.03.01.07) ───────────────
#
# Los apartados los aporta quien es dueño del dato, no el núcleo. Si el núcleo
# los importara, pasaría a depender de este servicio y se acabó el despliegue
# independiente: el gate de arquitectura lo caza, y con razón.


def _apartado_cobertura(db: Any, tenant_id: UUID) -> dict[str, Any]:
    return cobertura(db, tenant_id, solo_hechas=True)


def _apartado_certificados(db: Any, tenant_id: UUID) -> dict[str, Any]:
    from sqlalchemy import func as _func
    from sqlalchemy import select as _select

    from services.tenancy.baja import CertificadoDestruccion

    cuantos = int(
        db.execute(
            _select(_func.count())
            .select_from(CertificadoDestruccion)
            .where(CertificadoDestruccion.tenant_id == tenant_id)
        ).scalar_one()
        or 0
    )
    return {"emitidos": cuantos}


def registrar_apartados() -> None:
    """Aporta al informe lo que este servicio sabe y el núcleo no."""
    from crmcore.cumplimiento import registrar_apartado

    registrar_apartado("cobertura_de_controles", _apartado_cobertura)
    registrar_apartado("certificados_de_destruccion", _apartado_certificados)


registrar_apartados()


# ── Panel de GRC (CRM-07.03.02.10) ────────────────────────────────────────

# A partir de aquí, un riesgo se considera alto. Sobre 25 —probabilidad por
# impacto, los dos de 1 a 5—, 12 es la mitad larga: lo que un comité mira. Va
# como constante del módulo y no como ajuste porque mover el umbral cambiaría
# qué sale en el panel sin cambiar ningún riesgo, y eso es maquillar el informe;
# quien quiera menos ruido tiene que bajar el impacto o la probabilidad de un
# riesgo concreto, que es una decisión que deja rastro.
UMBRAL_RIESGO_ALTO = 12


def panel(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Todo lo que no cuadra, en un sitio y **ordenado por lo que urge**.

    Las piezas ya estaban —cobertura, vencimientos, riesgos sin control— y cada
    una en su pantalla. El problema de tenerlas separadas es el de siempre: hay
    que abrir cuatro sitios para saber si se está bien, así que no se abre
    ninguno.

    Dos decisiones:

    **Se ordena por urgencia, no por fecha.** Una lista por fecha entierra lo
    grave debajo de lo viejo. Aquí lo primero es lo que tiene consecuencia —un
    riesgo alto sin control, un control fuera de plazo— y lo último, lo que
    conviene mirar.

    **Se dice qué NO se ha podido medir.** Un panel en verde porque no hay nada
    declarado es el que más tranquiliza y el que peor informa: sin controles, sin
    riesgos y sin evaluaciones, esto no dice que se cumpla — dice que no hay
    nada con lo que comprobarlo.
    """
    datos_vencidos = vencidos(db, tenant_id)
    datos_cobertura = cobertura(db, tenant_id, solo_hechas=True)

    riesgos = (
        db.execute(select(Riesgo).where(Riesgo.tenant_id == tenant_id, Riesgo.estado == "abierto"))
        .scalars()
        .all()
    )
    controles = (
        db.execute(select(Control).where(Control.tenant_id == tenant_id, Control.activo.is_(True)))
        .scalars()
        .all()
    )
    ultimas = _ultimas_evaluaciones(db, tenant_id)

    # Un riesgo alto sin control es la fila que un auditor mira primero, así que
    # es la que va arriba.
    # La severidad no es un campo: es probabilidad × impacto, que es como se
    # calcula de verdad. Buscar un campo «severidad» habría dejado esta lista
    # vacía para siempre sin un solo error — la clase de fallo que hace que un
    # panel de riesgos enseñe todo en verde.
    altos_sin_control = [
        r.codigo
        for r in riesgos
        if r.inherente >= UMBRAL_RIESGO_ALTO
        and r.codigo in datos_vencidos["riesgos_a_mitigar_sin_control"]
    ]

    urgente: list[dict[str, Any]] = []
    for codigo in sorted(altos_sin_control):
        urgente.append(
            {
                "que": f"Riesgo {codigo} de severidad alta sin ningún control",
                "inherente": next((r.inherente for r in riesgos if r.codigo == codigo), None),
                "por_que_urge": "Se decidió mitigarlo y no hay nada ejecutándolo",
                "orden": 1,
            }
        )
    for fila in datos_vencidos["controles_no_efectivos"]:
        urgente.append(
            {
                "que": f"Control {fila['control']} evaluado como «{fila['resultado']}»",
                "por_que_urge": "Está declarado y no protege: peor que no tenerlo, porque consta",
                "orden": 2,
            }
        )
    for fila in datos_vencidos["controles_fuera_de_plazo"]:
        urgente.append(
            {
                "que": f"Control {fila['control']} sin evaluar desde su plazo ({fila['vencio']})",
                "por_que_urge": "Nadie sabe si sigue funcionando",
                "orden": 3,
            }
        )
    for codigo in datos_vencidos["controles_nunca_evaluados"]:
        urgente.append(
            {
                "que": f"Control {codigo} nunca evaluado",
                "por_que_urge": "Declarado y sin comprobar ni una vez",
                "orden": 4,
            }
        )

    hay_con_que_medir = bool(controles) and bool(ultimas)
    return {
        "generado_at": datetime.now(timezone.utc).isoformat(),
        "riesgos_abiertos": len(riesgos),
        "controles_activos": len(controles),
        "controles_evaluados": len(ultimas),
        "cobertura_pct": datos_cobertura.get("cobertura_pct"),
        "lo_que_urge": sorted(urgente, key=lambda f: f["orden"]),
        "detalle": datos_vencidos,
        # La diferencia entre «se cumple» y «no hay nada con lo que comprobarlo»,
        # que es la que decide si este panel sirve o tranquiliza en falso.
        "medible": hay_con_que_medir,
        "porque": (
            "Hay controles declarados y evaluaciones con las que comprobarlo."
            if hay_con_que_medir
            else "No hay controles declarados o ninguno se ha evaluado: este panel "
            "no dice que se cumpla, dice que no hay nada con lo que comprobarlo."
        ),
        "todo_en_orden": hay_con_que_medir and not urgente,
    }
