"""Plantillas de flujo por sector y caso de uso (CRM-00.03.05.15).

Un proceso de ejemplo que se **copia** al tenant como borrador y desde ahí es
suyo: lo abre en el Editor de procesos, lo ajusta y lo publica. Antes la tabla
existía sin semilla y «clonar» devolvía un JSON que nadie guardaba, así que la
capacidad constaba como hecha sin que se pudiera usar.

Las decisiones:

**Se copia, no se hereda.** Si heredara, mejorar la plantilla cambiaría los
procesos que ya están corriendo en veinte clientes — incluido uno que la ajustó
hace seis meses y no espera que le cambie nada. La copia es un borrador con
clave propia: nadie la ejecuta hasta que alguien la publica.

**Las de serie viven en el código y se cargan en la tabla.** La tabla es de la
instalación (no lleva `tenant_id`, ver `test_contratos_arquitectura`), y lo que
la llena es esta lista: así una mejora de una plantilla llega con el despliegue
y se carga con «Cargar las de serie», que es idempotente —versión nueva si el
contenido cambió, nada si no—.

**Cada plantilla valida con el validador del motor** y sus pasos «servicio»
llaman a rutas que existen en el contrato. Una plantilla que no se puede
publicar tal cual enseña al cliente que el producto no se fía de sí mismo; la
prueba `test_las_plantillas_de_serie_validan_y_llaman_a_rutas_que_existen_crm_00_03_05_15` lo vigila.

**Y dice lo que NO resuelve.** Una que promete el proceso entero y deja fuera la
aprobación hace que el cliente lo descubra en producción.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, Index, Integer, String, UniqueConstraint, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)


class PlantillaFlujo(Base, TimestampMixin):
    """Un proceso de ejemplo por sector, para copiar (CRM-00.03.05.15)."""

    __tablename__ = "plantillas_flujo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    sector: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    caso_de_uso: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    definicion: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Lo que la plantilla NO resuelve. Una que promete el proceso entero y deja
    # fuera la aprobación hace que el cliente lo descubra en producción.
    no_resuelve: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("clave", "version", name="uq_plantilla_flujo"),
        Index("ix_plantillas_flujo", "sector", "activa"),
    )


# ── Las de serie ──────────────────────────────────────────────────────────
#
# Los umbrales que llevan dentro (el 10 % y el 25 % de descuento, los 100.000 €
# de facturación, los 500 € de una devolución) son DATO de la plantilla, no
# ajustes del producto: la copia es del tenant y los cambia en el editor, que
# es justo para lo que se copia. Los roles son los de serie del producto
# (`crmcore.authz.rbac`); donde el de verdad no existe de serie —riesgos,
# compras— la tarea cae en `admin` y la plantilla lo dice en `no_resuelve`.

_DESCUENTO: dict[str, Any] = {
    "inicio": "decidir",
    "pasos": {
        "decidir": {
            "tipo": "decision",
            "condiciones": [
                {
                    "si": {"atributo": "descuento", "op": ">", "valor": 25},
                    "entonces": "aprobacion_direccion",
                },
                {
                    "si": {"atributo": "descuento", "op": ">", "valor": 10},
                    "entonces": "aprobacion_jefe",
                },
            ],
            "si_no": "anotar_aprobado",
        },
        "aprobacion_jefe": {
            "tipo": "humano",
            "titulo": "Aprobar un descuento del @descuento % en el presupuesto @numero",
            "asignada_rol": "responsable_ventas",
            "vence_en_horas": 24,
            "rutas": {"aprobar": "anotar_aprobado", "rechazar": "avisar_rechazo"},
        },
        "aprobacion_direccion": {
            "tipo": "humano",
            "titulo": "Descuento excepcional del @descuento % en el presupuesto @numero",
            "asignada_rol": "admin",
            "vence_en_horas": 48,
            "rutas": {"aprobar": "anotar_aprobado", "rechazar": "avisar_rechazo"},
        },
        "anotar_aprobado": {
            "tipo": "servicio",
            "operacion": "PATCH /api/v1/presupuestos/@presupuesto_id",
            "entrada": {"motivo_aprobacion": "Descuento aprobado en el proceso de descuentos"},
            "salida": "presupuesto",
            "siguiente": "fin_aprobado",
        },
        "avisar_rechazo": {
            "tipo": "servicio",
            "operacion": "POST /api/v1/activities",
            "entrada": {
                "tipo": "tarea",
                "asunto": "Descuento rechazado: revisa el presupuesto antes de enviarlo",
                "objeto": "presupuesto",
                "objeto_id": "@presupuesto_id",
                "asignada_a": "@comercial_id",
                "prioridad": "alta",
            },
            "siguiente": "fin_rechazado",
        },
        "fin_aprobado": {"tipo": "fin", "resultado": "aprobado"},
        "fin_rechazado": {"tipo": "fin", "resultado": "rechazado"},
    },
}

_ALTA_CLIENTE: dict[str, Any] = {
    "inicio": "clasificar",
    "pasos": {
        "clasificar": {
            "tipo": "decision",
            "condiciones": [
                {
                    "si": {"atributo": "facturacion_prevista", "op": ">=", "valor": 100000},
                    "entonces": "revision_riesgo",
                }
            ],
            "si_no": "activar",
        },
        "revision_riesgo": {
            "tipo": "humano",
            "titulo": "Revisar el riesgo de un cliente nuevo de @facturacion_prevista €",
            "asignada_rol": "admin",
            "vence_en_horas": 72,
            "rutas": {
                "aprobar": "activar",
                "pedir_garantias": "pedir_garantias",
                "rechazar": "bloquear",
            },
        },
        "pedir_garantias": {
            "tipo": "servicio",
            "operacion": "POST /api/v1/activities",
            "entrada": {
                "tipo": "tarea",
                "asunto": "Pedir garantías al cliente antes de darlo de alta",
                "objeto": "cuenta",
                "objeto_id": "@cuenta_id",
                "cuenta_id": "@cuenta_id",
                "prioridad": "alta",
            },
            "siguiente": "fin_pendiente",
        },
        "activar": {
            "tipo": "servicio",
            "operacion": "PATCH /api/v1/accounts/@cuenta_id",
            "entrada": {"estado": "activa", "ciclo_vida": "cliente"},
            # Si algo falla después, la cuenta no se queda activa a medias.
            "compensacion": {
                "operacion": "PATCH /api/v1/accounts/@cuenta_id",
                "entrada": {"estado": "inactiva"},
            },
            "siguiente": "bienvenida",
        },
        "bienvenida": {
            "tipo": "servicio",
            "operacion": "POST /api/v1/activities",
            "entrada": {
                "tipo": "llamada",
                "asunto": "Llamada de bienvenida al cliente nuevo",
                "objeto": "cuenta",
                "objeto_id": "@cuenta_id",
                "cuenta_id": "@cuenta_id",
            },
            "siguiente": "fin_alta",
        },
        "bloquear": {
            "tipo": "servicio",
            "operacion": "PATCH /api/v1/accounts/@cuenta_id",
            "entrada": {"estado": "bloqueada"},
            "siguiente": "fin_rechazado",
        },
        "fin_alta": {"tipo": "fin", "resultado": "alta"},
        "fin_pendiente": {"tipo": "fin", "resultado": "pendiente_de_garantias"},
        "fin_rechazado": {"tipo": "fin", "resultado": "rechazado"},
    },
}

_DEVOLUCION: dict[str, Any] = {
    "inicio": "decidir",
    "pasos": {
        "decidir": {
            "tipo": "decision",
            "condiciones": [
                {
                    "si": {"atributo": "importe", "op": ">", "valor": 500},
                    "entonces": "aprobar_devolucion",
                }
            ],
            "si_no": "autorizar",
        },
        "aprobar_devolucion": {
            "tipo": "humano",
            "titulo": "Aprobar una devolución de @importe €",
            "asignada_rol": "responsable_soporte",
            "vence_en_horas": 24,
            "rutas": {"aprobar": "autorizar", "rechazar": "rechazar"},
        },
        "autorizar": {
            "tipo": "servicio",
            "operacion": "POST /api/v1/devoluciones/@devolucion_id/autorizar",
            "entrada": {},
            "siguiente": "revisar_mercancia",
        },
        "revisar_mercancia": {
            "tipo": "humano",
            "titulo": "Recibir e inspeccionar la mercancía devuelta",
            "descripcion": "Anota en el comentario qué se ha visto al inspeccionarla.",
            "asignada_rol": "agente_soporte",
            "vence_en_horas": 120,
            "rutas": {"conforme": "recibir", "no_conforme": "rechazar"},
        },
        "recibir": {
            "tipo": "servicio",
            "operacion": "POST /api/v1/devoluciones/@devolucion_id/recibir",
            "entrada": {},
            "siguiente": "inspeccionar",
        },
        "inspeccionar": {
            "tipo": "servicio",
            "operacion": "POST /api/v1/devoluciones/@devolucion_id/inspeccionar",
            "entrada": {"inspeccion": "Conforme en la revisión del proceso de devoluciones"},
            "siguiente": "abonar",
        },
        "abonar": {
            "tipo": "servicio",
            "operacion": "POST /api/v1/devoluciones/@devolucion_id/resolver",
            "entrada": {
                "tipo": "abono",
                "importe": "@importe",
                "nota": "Abono decidido en el proceso; lo confirma quien factura",
            },
            "siguiente": "fin_abonada",
        },
        "rechazar": {
            "tipo": "servicio",
            "operacion": "POST /api/v1/devoluciones/@devolucion_id/rechazar",
            "entrada": {"motivo": "Rechazada en el proceso de devolución y abono"},
            "siguiente": "fin_rechazada",
        },
        "fin_abonada": {"tipo": "fin", "resultado": "abono_solicitado"},
        "fin_rechazada": {"tipo": "fin", "resultado": "rechazada"},
    },
}

_PROVEEDOR: dict[str, Any] = {
    "inicio": "pedir_papeles",
    "pasos": {
        "pedir_papeles": {
            "tipo": "servicio",
            "operacion": "POST /api/v1/activities",
            "entrada": {
                "tipo": "tarea",
                "asunto": "Pedir al proveedor sus certificados y datos bancarios",
                "objeto": "proveedor",
                "objeto_id": "@cuenta_id",
                "cuenta_id": "@cuenta_id",
            },
            "siguiente": "revisar_papeles",
        },
        "revisar_papeles": {
            "tipo": "humano",
            "titulo": "Revisar la documentación del proveedor nuevo",
            "asignada_rol": "admin",
            "vence_en_horas": 120,
            "rutas": {
                "completa": "homologar",
                "incompleta": "esperar_documentos",
                "rechazar": "bloquear",
            },
        },
        # Tres días y se vuelve a revisar: una documentación incompleta no
        # cierra el alta, la deja esperando.
        "esperar_documentos": {
            "tipo": "espera",
            "segundos": 259200,
            "siguiente": "revisar_papeles",
        },
        "homologar": {
            "tipo": "servicio",
            "operacion": "POST /api/v1/proveedores/@cuenta_id/homologacion",
            "entrada": {"categoria": "@categoria", "requisitos": []},
            "siguiente": "activar",
        },
        "activar": {
            "tipo": "servicio",
            "operacion": "PATCH /api/v1/proveedores/@cuenta_id",
            "entrada": {"estado": "activa"},
            "siguiente": "fin_homologado",
        },
        "bloquear": {
            "tipo": "servicio",
            "operacion": "PATCH /api/v1/proveedores/@cuenta_id",
            "entrada": {"estado": "bloqueada"},
            "siguiente": "fin_rechazado",
        },
        "fin_homologado": {"tipo": "fin", "resultado": "homologado"},
        "fin_rechazado": {"tipo": "fin", "resultado": "rechazado"},
    },
}

_CASO_URGENTE: dict[str, Any] = {
    "inicio": "subir_prioridad",
    "pasos": {
        "subir_prioridad": {
            "tipo": "servicio",
            "operacion": "PATCH /api/v1/casos/@caso_id",
            "entrada": {"prioridad": "critica"},
            "siguiente": "avisar_responsable",
        },
        "avisar_responsable": {
            "tipo": "servicio",
            "operacion": "POST /api/v1/activities",
            "entrada": {
                "tipo": "tarea",
                "asunto": "Caso urgente escalado: contestar al cliente hoy",
                "objeto": "caso",
                "objeto_id": "@caso_id",
                "asignada_a": "@responsable_id",
                "prioridad": "urgente",
            },
            "siguiente": "confirmar_que_alguien_lo_lleva",
        },
        "confirmar_que_alguien_lo_lleva": {
            "tipo": "humano",
            "titulo": "Confirmar que el caso urgente tiene a alguien trabajando",
            "asignada_rol": "responsable_soporte",
            "vence_en_horas": 2,
            "rutas": {"atendido": "fin_atendido", "pasar_a_otro_equipo": "reasignar"},
        },
        "reasignar": {
            "tipo": "servicio",
            "operacion": "PATCH /api/v1/casos/@caso_id",
            "entrada": {"equipo": "@equipo_de_escalado"},
            "siguiente": "fin_reasignado",
        },
        "fin_atendido": {"tipo": "fin", "resultado": "atendido"},
        "fin_reasignado": {"tipo": "fin", "resultado": "reasignado"},
    },
}

PLANTILLAS_DE_SERIE: tuple[dict[str, Any], ...] = (
    {
        "clave": "aprobacion_descuento_comercial",
        "sector": "comercial",
        "caso_de_uso": "Aprobar descuentos por tramos",
        "nombre": "Aprobación de descuento comercial",
        "definicion": _DESCUENTO,
        "no_resuelve": [
            "Necesita al arrancar «presupuesto_id», «numero», «descuento» (en %) y "
            "«comercial_id»: quien lo lance tiene que pasarlos.",
            "Los tramos (10 % y 25 %) son de ejemplo: ajústalos a vuestra política.",
            "Por encima del 25 % decide «admin»: cámbialo por vuestro rol de dirección.",
        ],
    },
    {
        "clave": "alta_cliente_revision_riesgo",
        "sector": "general",
        "caso_de_uso": "Alta de cliente nuevo con revisión de riesgo",
        "nombre": "Alta de cliente con revisión de riesgo",
        "definicion": _ALTA_CLIENTE,
        "no_resuelve": [
            "Necesita «cuenta_id» y «facturacion_prevista» al arrancar.",
            "No hay rol de riesgos de serie: la revisión cae en «admin».",
            "No consulta solvencia en un tercero: la revisión es humana.",
        ],
    },
    {
        "clave": "devolucion_y_abono",
        "sector": "postventa",
        "caso_de_uso": "Devolución de material y abono",
        "nombre": "Devolución y abono",
        "definicion": _DEVOLUCION,
        "no_resuelve": [
            "Necesita «devolucion_id» e «importe» al arrancar.",
            "El abono queda SOLICITADO: lo emite y lo confirma quien factura, no el CRM.",
            "La recepción se anota entera; si llega menos de lo autorizado, corrígelo "
            "en la devolución antes de responder la tarea.",
        ],
    },
    {
        "clave": "onboarding_proveedor",
        "sector": "compras",
        "caso_de_uso": "Alta y homologación de proveedor",
        "nombre": "Onboarding de proveedor",
        "definicion": _PROVEEDOR,
        "no_resuelve": [
            "Necesita «cuenta_id» (el proveedor) y «categoria» al arrancar.",
            "No hay rol de compras de serie: la revisión cae en «admin».",
            "Los requisitos de homologación salen vacíos: añade los vuestros.",
        ],
    },
    {
        "clave": "escalado_caso_urgente",
        "sector": "soporte",
        "caso_de_uso": "Escalar un caso urgente",
        "nombre": "Escalado de caso urgente",
        "definicion": _CASO_URGENTE,
        "no_resuelve": [
            "Necesita «caso_id», «responsable_id» y «equipo_de_escalado» al arrancar.",
            "No avisa al cliente: eso lo decide quien atiende el caso.",
        ],
    },
)


# ── Listar, cargar y copiar ───────────────────────────────────────────────


def listar(db: Session) -> list[PlantillaFlujo]:
    """La última versión activa de cada plantilla, por sector y nombre."""
    filas = (
        db.execute(
            select(PlantillaFlujo)
            .where(PlantillaFlujo.activa.is_(True))
            .order_by(PlantillaFlujo.clave, PlantillaFlujo.version.desc())
        )
        .scalars()
        .all()
    )
    vistas: dict[str, PlantillaFlujo] = {}
    for fila in filas:
        vistas.setdefault(fila.clave, fila)
    return sorted(vistas.values(), key=lambda p: (p.sector, p.nombre))


def cargar_de_serie(db: Session) -> dict[str, Any]:
    """Carga las de serie. Idempotente: dos veces es lo mismo que una.

    Una plantilla que ya está con el mismo contenido no se toca; una cuyo
    contenido cambió entra como **versión nueva** —las copias ya hechas no se
    enteran, que es lo que se quiere—. Nunca se sobrescribe una versión: la
    copia de un cliente dice de qué versión salió, y esa versión tiene que
    seguir siendo la que copió.
    """
    creadas: list[str] = []
    iguales: list[str] = []
    for semilla in PLANTILLAS_DE_SERIE:
        ultima = (
            db.execute(
                select(PlantillaFlujo)
                .where(PlantillaFlujo.clave == semilla["clave"])
                .order_by(PlantillaFlujo.version.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        campos = {k: semilla[k] for k in ("sector", "caso_de_uso", "nombre", "definicion")}
        if ultima is not None and all(getattr(ultima, k) == v for k, v in campos.items()):
            if list(ultima.no_resuelve or []) == list(semilla["no_resuelve"]) and ultima.activa:
                iguales.append(semilla["clave"])
                continue
        db.add(
            PlantillaFlujo(
                clave=semilla["clave"],
                version=(ultima.version + 1) if ultima else 1,
                no_resuelve=list(semilla["no_resuelve"]),
                activa=True,
                **campos,
            )
        )
        creadas.append(semilla["clave"])
    db.flush()
    return {
        "cargadas": creadas,
        "ya_estaban": iguales,
        "que_significa": (
            "Las plantillas de serie están en la biblioteca. Copiar una crea un "
            "BORRADOR tuyo; las que ya copiaste no cambian."
        ),
    }


def copiar(
    db: Session,
    tenant_id: UUID,
    *,
    clave_plantilla: str,
    clave: str,
    nombre: str,
    operaciones_con_nombre: frozenset[str] | set[str] | None = None,
) -> tuple[Any, PlantillaFlujo]:
    """Copia una plantilla como BORRADOR de definición del tenant.

    Con **clave nueva**: si usara la de una definición que ya existe, la copia
    sería «la versión siguiente» de otro proceso y un disparador de aquél
    acabaría arrancando ésta en cuanto alguien la publicara.
    """
    from services.orchestrator import motor as mtr
    from services.orchestrator.modelos import DefinicionProceso

    plantilla = next((p for p in listar(db) if p.clave == clave_plantilla), None)
    if plantilla is None:
        raise NoEncontrado(
            f"No hay plantilla de flujo activa con la clave «{clave_plantilla}»",
            error_code="flujo.plantilla_no_existe",
        )
    clave = clave.strip()
    nombre = nombre.strip()
    if not clave or not nombre:
        raise ErrorValidacion(
            "La copia necesita clave y nombre propios: si se queda con los de la "
            "plantilla, nadie sabe después cuál es el suyo y cuál el de fábrica.",
            error_code="flujo.clon_sin_nombre",
        )
    existente = db.execute(
        select(DefinicionProceso.id)
        .where(DefinicionProceso.tenant_id == tenant_id, DefinicionProceso.clave == clave)
        .limit(1)
    ).first()
    if existente is not None:
        raise Conflicto(
            f"Ya hay un proceso con la clave «{clave}». La copia necesita una clave "
            "nueva: con la de otro sería su versión siguiente y heredaría sus disparadores.",
            error_code="flujo.clave_ocupada",
        )

    # Se valida antes de guardar, igual que cualquier borrador: una plantilla
    # que no pasa su propia validación no se entrega como si estuviera bien.
    problemas = mtr.validar_definicion(
        plantilla.definicion, operaciones_con_nombre=operaciones_con_nombre
    )
    if problemas:
        raise ErrorValidacion(
            "La plantilla no es válida en esta instalación",
            error_code="flujo.plantilla_invalida",
            errores=[{"campo": "definicion", "motivo": p} for p in problemas],
        )

    definicion = DefinicionProceso(
        tenant_id=tenant_id,
        clave=clave,
        version=1,
        nombre=nombre,
        descripcion=f"Copiado de la plantilla «{plantilla.nombre}» (v{plantilla.version})",
        definicion=dict(plantilla.definicion),
        disparadores=[],
        estado="borrador",
    )
    db.add(definicion)
    db.flush()
    registrar(
        db,
        accion="proceso.copiado_de_plantilla",
        objeto="definicion_proceso",
        objeto_id=definicion.id,
        datos={
            "clave": clave,
            "plantilla": plantilla.clave,
            "version_plantilla": plantilla.version,
        },
        tenant_id=tenant_id,
    )
    return definicion, plantilla
