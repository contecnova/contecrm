"""Motor de informes (CRM-05.01.01) y cuadros de mando (CRM-05.01.02.01).

**Aquí no se ejecuta SQL contra el dato.** La restricción RT-4 dice que la
explotación la resuelve contecintelligence, y la de arquitectura dice que ningún
servicio lee el esquema de otro. Lo que vive aquí es lo que no puede vivir allí:

  * la **definición** del informe, que es del tenant y tiene que sobrevivir a un
    cambio de motor analítico,
  * el **sobre de seguridad**: qué campos puede usar quien lo pide y qué filas
    puede ver, resuelto antes de que la consulta salga,
  * el **plan**: la consulta compilada como estructura de datos, nunca como
    SQL —escribir SQL aquí sería un segundo motor de explotación (RT-4), y
    además obligaría a interpolar nombres de campo—,
  * la **programación y la distribución**, que son del CRM porque van a los
    usuarios del CRM,
  * y el **histórico** de instantáneas, que es la única forma de contestar «¿cómo
    íbamos en marzo?» cuando el dato operativo ya cambió.

Quién ejecuta el plan se **registra** (`registrar_ejecutor`), no se importa. Es la
misma inversión que usa el núcleo con los apartados de cumplimiento, y por lo
mismo: si este módulo importara al ejecutor, el motor de informes quedaría atado a
un producto concreto y cambiarlo sería reescribirlo.

Tres decisiones que gobiernan el módulo:

**La seguridad se resuelve al compilar, no al pintar.** Un informe que trae la
facturación y la esconde en la pantalla ya ha sacado la facturación de la base: la
respuesta de la API la ve cualquiera que abra las herramientas del navegador.

**Un informe guarda lo que pidió, no lo que devolvió.** Los resultados no se
guardan salvo como instantánea explícita: una tabla de resultados cacheada se
queda desfasada en silencio y se lee como si fuera de hoy.

**Un informe programado que falla avisa.** Un informe que deja de llegar no se
echa de menos —la gente supone que no había nada que contar—, y eso convierte un
fallo en un punto ciego de semanas.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Date,
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

TIPOS = ("tabular", "agrupado", "matricial", "union")
# Funciones de resumen admitidas. Lista cerrada: una definición es dato del
# tenant y no puede convertirse en SQL arbitrario. Es la misma razón por la que
# las condiciones de ABAC tienen operadores cerrados.
AGREGADOS = ("suma", "media", "minimo", "maximo", "cuenta", "cuenta_distinta")
# Operadores admitidos en un filtro. Lista cerrada por lo mismo que los
# agregados, y **sin su traducción a SQL**: el plan que sale de aquí es una
# estructura de datos, no una consulta. Quien la ejecuta la traduce a su
# lenguaje, que es lo que dice RT-4 y lo que evita que este módulo se convierta
# en un segundo motor de explotación.
OPERADORES = (
    "=",
    "!=",
    ">",
    ">=",
    "<",
    "<=",
    "contiene",
    "empieza",
    "en",
    "vacio",
    "no_vacio",
)
# Un identificador de campo válido. Se comprueba aunque el plan no sea SQL:
# quien lo ejecute lo usará como nombre de columna, y un nombre con comillas o
# punto y coma es una inyección esperando a que el de abajo no la filtre.
IDENTIFICADOR = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
PERIODOS = ("dia", "semana", "mes", "trimestre", "anio")
FORMATOS = ("csv", "excel", "pdf", "json")

# Tope de filas por ejecución. Es un ajuste con valor de partida, no un límite
# duro escondido: un informe que devuelve medio millón de filas tumba el
# navegador de quien lo abrió y no lo lee nadie, pero el tope correcto depende
# del cliente.
TOPE_FILAS_DEFECTO = 50_000


class Informe(Base, TimestampMixin):
    """La definición de un informe (CRM-05.01.01.01, CRM-05.01.01.02).

    Los cuatro tipos —tabular, agrupado, matricial y de unión— son el mismo
    objeto con distintas piezas rellenas, no cuatro modelos. Con un modelo por
    tipo, convertir un tabular en agrupado obligaría a rehacerlo desde cero, que
    es exactamente lo que alguien hace después de pasar media hora montándolo.
    """

    __tablename__ = "informes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    objeto: Mapped[str] = mapped_column(String(40), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="tabular")

    # Columnas que se enseñan tal cual.
    columnas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Por qué se agrupa, y con qué periodo si es una fecha.
    agrupaciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Qué se calcula: `{"campo": "importe", "agregado": "suma", "como": "total"}`.
    metricas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Campos calculados (CRM-05.01.01.04): expresiones sobre columnas ya
    # proyectadas, no SQL libre.
    calculados: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    filtros: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Filtros que el usuario rellena al ejecutarlo (CRM-05.01.01.03).
    filtros_ejecucion: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    orden: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Para el matricial: qué va en las columnas.
    pivote: Mapped[str | None] = mapped_column(String(80), nullable=True)
    limite: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Quién lo ve. Vacío = quien tenga permiso de informes.
    roles: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    propietario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Un informe que enseña los datos de quien lo abre y no los de todos
    # (CRM-05.01.02.04 usa lo mismo). Es lo que evita tener un informe por
    # comercial.
    solo_mios: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_informe_clave"),
        Index("ix_informes_objeto", "tenant_id", "objeto", "activo"),
    )


class ProgramacionInforme(Base, TimestampMixin):
    """Cuándo se manda y a quién (CRM-05.01.01.06)."""

    __tablename__ = "programaciones_informe"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    informe_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("informes.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # diaria | semanal | mensual
    periodicidad: Mapped[str] = mapped_column(String(20), nullable=False, default="semanal")
    hora: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    dia_semana: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dia_mes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    formato: Mapped[str] = mapped_column(String(10), nullable=False, default="csv")
    destinatarios: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Destino externo: un webhook, un SFTP declarado como conexión. Va como
    # identificador opaco porque quien lo resuelve es `integration`.
    destino_externo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # No mandar si no hay filas. Apagado por defecto a propósito: un informe que
    # deja de llegar no se echa de menos, y el silencio se lee como «no pasa
    # nada» en vez de como «no se ejecutó».
    omitir_si_vacio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    proxima_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    ultima_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallos_seguidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_programaciones_pendientes", "tenant_id", "activa", "proxima_at"),)


class EjecucionInforme(Base):
    """Cada vez que se corrió, con lo que costó. Append-only."""

    __tablename__ = "ejecuciones_informe"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    informe_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # interactiva | programada | api
    origen: Mapped[str] = mapped_column(String(20), nullable=False, default="interactiva")
    usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    filas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duracion_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    formato: Mapped[str] = mapped_column(String(10), nullable=False, default="json")
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Qué campos se le quitaron a quien lo pidió. Es la prueba de que el informe
    # no enseñó más de lo permitido, y lo que permite auditar sin repetirlo.
    campos_retirados: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_ejecuciones_informe", "tenant_id", "informe_id", "created_at"),)


class InstantaneaInforme(Base):
    """Lo que decía el informe un día concreto (CRM-05.01.01.05).

    Es la única forma de contestar «¿cómo íbamos en marzo?». El dato operativo ya
    cambió —una oportunidad cerrada se recategoriza, un importe se corrige— y
    recalcular marzo con los datos de hoy da un número que nunca existió.
    """

    __tablename__ = "instantaneas_informe"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    informe_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    tomada_el: Mapped[date] = mapped_column(Date, nullable=False)
    filas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Los resúmenes, no las filas. Guardar el detalle entero convertiría la tabla
    # en una copia del CRM que crece sin fin y que nadie purga.
    resumen: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "informe_id", "tomada_el", name="uq_instantanea_dia"),
        Index("ix_instantaneas_informe", "tenant_id", "informe_id", "tomada_el"),
    )


class CuadroMando(Base, TimestampMixin):
    """Un tablero con sus componentes (CRM-05.01.02.01)."""

    __tablename__ = "cuadros_mando"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Componentes: cada uno apunta a un informe y dice cómo se pinta. El «cómo»
    # va aquí y no en el informe porque el mismo informe se enseña como tabla en
    # un sitio y como gráfico en otro, y duplicar la definición para cambiar el
    # dibujo es cómo se acaba con dos informes que dicen cosas distintas.
    componentes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    roles: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    equipos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    propietario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # El cuadro por defecto de un rol. Solo uno por rol: dos «por defecto» hacen
    # que cuál se abre dependa del orden de la consulta.
    por_defecto_para: Mapped[str | None] = mapped_column(String(60), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_cuadro_clave"),
        Index("ix_cuadros_defecto", "tenant_id", "por_defecto_para", "activo"),
    )


# ── El ejecutor se registra, no se importa ────────────────────────────────

_EJECUTOR: Callable[..., dict[str, Any]] | None = None


def registrar_ejecutor(fn: Callable[..., dict[str, Any]]) -> None:
    """Declara quién ejecuta los planes.

    Se registra y no se importa: si este módulo importara al ejecutor, el motor
    de informes quedaría atado a un producto concreto —hoy contecintelligence— y
    cambiarlo sería reescribirlo. Es la misma inversión que usa el núcleo con los
    apartados de cumplimiento.
    """
    global _EJECUTOR
    _EJECUTOR = fn


def hay_ejecutor() -> bool:
    return _EJECUTOR is not None


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


# ── Validación de la definición ───────────────────────────────────────────


def validar(definicion: dict[str, Any]) -> list[str]:
    """Comprueba la definición antes de guardarla. Lanza lo grave, avisa lo demás.

    Se separa a propósito, como en los módulos verticales: rechazar por un aviso
    deja a alguien sin poder guardar un borrador a medias, y aceptar en silencio
    lo grave produce un informe que falla al ejecutarse delante del cliente.
    """
    avisos: list[str] = []
    tipo = str(definicion.get("tipo") or "tabular")
    if tipo not in TIPOS:
        raise ErrorValidacion(
            f"Tipo de informe «{tipo}» no válido.",
            error_code="informe.tipo_no_valido",
            detalle={"validos": list(TIPOS)},
        )
    if not str(definicion.get("objeto") or ""):
        raise ErrorValidacion(
            "Un informe sin objeto no sabe de qué informar.",
            error_code="informe.sin_objeto",
        )

    metricas = definicion.get("metricas") or []
    for metrica in metricas:
        agregado = str(metrica.get("agregado") or "")
        if agregado not in AGREGADOS:
            raise ErrorValidacion(
                f"Agregado «{agregado}» no válido.",
                error_code="informe.agregado_no_valido",
                detalle={"validos": list(AGREGADOS)},
            )
        if agregado != "cuenta" and not str(metrica.get("campo") or ""):
            raise ErrorValidacion(
                f"«{agregado}» necesita un campo sobre el que calcularse.",
                error_code="informe.metrica_sin_campo",
            )

    agrupaciones = definicion.get("agrupaciones") or []
    for grupo in agrupaciones:
        periodo = grupo.get("periodo")
        if periodo and periodo not in PERIODOS:
            raise ErrorValidacion(
                f"Periodo «{periodo}» no válido.",
                error_code="informe.periodo_no_valido",
                detalle={"validos": list(PERIODOS)},
            )

    for filtro in (definicion.get("filtros") or []) + (definicion.get("filtros_ejecucion") or []):
        operador = str(filtro.get("operador") or "=")
        if operador not in OPERADORES:
            raise ErrorValidacion(
                f"Operador «{operador}» no válido.",
                error_code="informe.operador_no_valido",
                detalle={"validos": list(OPERADORES)},
            )
        campo = str(filtro.get("campo") or "")
        if campo and not IDENTIFICADOR.match(campo):
            raise ErrorValidacion(
                f"«{campo}» no es un nombre de campo válido.",
                error_code="informe.campo_no_valido",
            )

    if tipo == "agrupado" and not agrupaciones:
        raise ErrorValidacion(
            "Un informe agrupado sin agrupaciones es un informe tabular con otro nombre.",
            error_code="informe.agrupado_sin_agrupaciones",
        )
    if tipo == "matricial" and not definicion.get("pivote"):
        raise ErrorValidacion(
            "Un informe matricial necesita saber qué va en las columnas.",
            error_code="informe.matricial_sin_pivote",
        )
    if tipo in ("agrupado", "matricial") and not metricas:
        avisos.append(
            "Agrupa pero no calcula nada: saldrán los grupos y ninguna cifra. "
            "Casi siempre falta una métrica."
        )
    if not definicion.get("columnas") and not metricas:
        avisos.append("El informe no enseña ninguna columna ni calcula nada: saldrá vacío.")
    if definicion.get("limite") and int(definicion["limite"]) > TOPE_FILAS_DEFECTO:
        avisos.append(
            f"El límite pedido pasa de {TOPE_FILAS_DEFECTO} filas; se recortará al "
            "tope configurado del tenant."
        )
    return avisos


# ── Compilar: la seguridad se resuelve aquí (CRM-05.01.01.08) ─────────────


def _campos_usados(informe: Informe, filtros_extra: list[dict[str, Any]]) -> list[str]:
    usados: list[str] = list(informe.columnas or [])
    usados += [str(g.get("campo")) for g in (informe.agrupaciones or []) if g.get("campo")]
    usados += [str(m.get("campo")) for m in (informe.metricas or []) if m.get("campo")]
    usados += [str(f.get("campo")) for f in (informe.filtros or []) if f.get("campo")]
    usados += [str(f.get("campo")) for f in filtros_extra if f.get("campo")]
    usados += [str(o.get("campo")) for o in (informe.orden or []) if o.get("campo")]
    if informe.pivote:
        usados.append(informe.pivote)
    return list(dict.fromkeys(u for u in usados if u))


def compilar(
    db: Session,
    tenant_id: UUID,
    informe: Informe,
    *,
    roles: frozenset[str] = frozenset(),
    es_admin: bool = False,
    usuario_id: UUID | None = None,
    filtros_extra: list[dict[str, Any]] | None = None,
    tope: int | None = None,
) -> dict[str, Any]:
    """Convierte la definición en un **plan de consulta portable**.

    El plan es una estructura de datos, no SQL. Lo era en la primera versión de
    este módulo y estaba mal por dos motivos, los dos reales:

    **Escribir SQL aquí es un segundo motor de explotación**, que es justo lo que
    RT-4 dice que no se haga. El gate que lo vigila lo cazó.

    **Y los identificadores se interpolaban.** Los valores iban como parámetros,
    pero el nombre de un campo se metía en el texto: un campo llamado
    `importe"; DROP TABLE x; --` se habría salido de sus comillas. Ahora los
    nombres van como nombres, se comprueban contra un patrón estricto, y quien
    ejecute el plan los resuelve contra su propio modelo.

    **La seguridad se resuelve aquí, no al pintar.** Un informe que trae la
    facturación y la esconde en la pantalla ya la ha sacado de la base: la
    respuesta de la API la ve cualquiera que abra las herramientas del navegador.

    Un campo que quien lo pide no puede usar **se quita del informe y se dice
    cuál**, en vez de fallar. Fallar deja a media plantilla sin poder abrir los
    informes de la empresa; quitarlo en silencio hace que dos personas vean
    cifras distintas del mismo informe y ninguna sepa por qué.
    """
    from crmcore import metamodelo

    filtros_extra = list(filtros_extra or [])
    vista = metamodelo.nombre_de_vista(informe.objeto, tenant_id)

    retirados: list[str] = []
    permitidos: set[str] = set()
    for campo in _campos_usados(informe, filtros_extra):
        if not IDENTIFICADOR.match(campo):
            raise ErrorValidacion(
                f"«{campo}» no es un nombre de campo válido.",
                error_code="informe.campo_no_valido",
            )
        if _campo_usable(db, tenant_id, informe.objeto, campo, roles, es_admin):
            permitidos.add(campo)
        else:
            retirados.append(campo)

    columnas = [c for c in (informe.columnas or []) if c in permitidos]
    agrupaciones = [
        {"campo": str(g["campo"]), "periodo": g.get("periodo")}
        for g in (informe.agrupaciones or [])
        if g.get("campo") in permitidos
    ]
    metricas = [
        {
            "campo": m.get("campo"),
            "agregado": str(m["agregado"]),
            "como": str(m.get("como") or f"{m['agregado']}_{m.get('campo') or 'filas'}"),
        }
        for m in (informe.metricas or [])
        if m.get("agregado") == "cuenta" or m.get("campo") in permitidos
    ]
    orden = [
        {"campo": str(o["campo"]), "descendente": bool(o.get("descendente"))}
        for o in (informe.orden or [])
        if o.get("campo") in permitidos
    ]
    calculados = [_calculado(c, permitidos) for c in (informe.calculados or [])]

    filtros: list[dict[str, Any]] = []
    for filtro in [*(informe.filtros or []), *filtros_extra]:
        campo = str(filtro.get("campo") or "")
        if campo not in permitidos:
            continue
        operador = str(filtro.get("operador") or "=")
        if operador not in OPERADORES:
            raise ErrorValidacion(
                f"Operador «{operador}» no válido.",
                error_code="informe.operador_no_valido",
                detalle={"validos": list(OPERADORES)},
            )
        filtros.append({"campo": campo, "operador": operador, "valor": filtro.get("valor")})

    if informe.solo_mios and usuario_id is not None:
        # El filtro por dueño lo pone el SERVIDOR, no el que llama. Si viniera
        # del cliente, bastaría quitarlo de la petición para ver los datos de
        # todos, que es exactamente lo que el informe quería impedir.
        filtros.append(
            {"campo": "propietario_id", "operador": "=", "valor": str(usuario_id), "impuesto": True}
        )

    limite = min(int(informe.limite or TOPE_FILAS_DEFECTO), tope or TOPE_FILAS_DEFECTO)
    return {
        "vista": vista,
        "objeto": informe.objeto,
        "tipo": informe.tipo,
        "columnas": columnas,
        "agrupaciones": agrupaciones,
        "metricas": metricas,
        "calculados": calculados,
        "filtros": filtros,
        "orden": orden,
        "pivote": informe.pivote if informe.pivote in permitidos else None,
        # Se pide una fila de más que el tope: es lo que permite decir «hay más»
        # sin contar la tabla entera, que en un informe grande cuesta más que el
        # propio informe.
        "limite": limite,
        "pedir": limite + 1,
        # Lo que se quitó por permisos, dicho por su nombre. Sin esto, quien mira
        # el informe no sabe que le falta una columna.
        "campos_retirados": retirados,
        "acotado_al_usuario": bool(informe.solo_mios and usuario_id is not None),
    }


def _campo_usable(
    db: Session, tenant_id: UUID, objeto: str, campo: str, roles: frozenset[str], es_admin: bool
) -> bool:
    """Si quien pide el informe puede usar ese campo.

    Se apoya en la sensibilidad declarada en el metamodelo. Los campos estándar
    no viven aquí —su modelo ORM está en el servicio dueño, que este no puede
    leer—, así que se dejan pasar **y el plan lo dice**, para que quien lo
    ejecute aplique su política: suponer que son libres abriría un agujero, y
    suponer que son secretos dejaría todos los informes vacíos.
    """
    from crmcore import metamodelo

    if es_admin:
        return True
    for definicion in metamodelo.campos_de(db, tenant_id, objeto):
        if str(definicion.get("clave")) == campo:
            return str(definicion.get("sensibilidad") or "interno") not in ("personal", "especial")
    return True


def _calculado(calculado: dict[str, Any], permitidos: set[str]) -> dict[str, Any]:
    """Un campo calculado es una operación entre dos columnas, no una expresión.

    Se limita a propósito: un campo calculado que aceptara una expresión libre
    sería SQL arbitrario escrito por un usuario final sobre la base de
    producción, y la comodidad de poder escribir un `CASE WHEN` no compensa eso.

    `proteger_division` va en el plan para que quien lo ejecute sepa que tiene
    que guardarse del cero: en SQL, dividir por cero revienta la consulta entera,
    y en un informe eso es una pantalla en blanco en vez de una fila rara.
    """
    izquierda = str(calculado.get("izquierda") or "")
    derecha = str(calculado.get("derecha") or "")
    operacion = str(calculado.get("operacion") or "")
    alias = str(calculado.get("como") or "calculado")
    if operacion not in ("+", "-", "*", "/"):
        raise ErrorValidacion(
            f"Operación «{operacion}» no válida en un campo calculado.",
            error_code="informe.operacion_no_valida",
            detalle={"validas": ["+", "-", "*", "/"]},
        )
    if izquierda not in permitidos or derecha not in permitidos:
        raise Prohibido(
            "Ese campo calculado usa una columna que no se puede usar",
            error_code="informe.calculado_no_usable",
        )
    return {
        "izquierda": izquierda,
        "operacion": operacion,
        "derecha": derecha,
        "como": alias,
        "proteger_division": operacion == "/",
    }


# ── Ejecutar (CRM-05.01.01.09) ────────────────────────────────────────────


def ejecutar(
    uow: UnidadDeTrabajo,
    informe_id: UUID,
    *,
    roles: frozenset[str] = frozenset(),
    es_admin: bool = False,
    usuario_id: UUID | None = None,
    filtros: list[dict[str, Any]] | None = None,
    origen: str = "interactiva",
    formato: str = "json",
) -> dict[str, Any]:
    """Compila y manda a ejecutar el plan.

    Si no hay ejecutor registrado **se dice**, en vez de devolver una tabla
    vacía: un informe vacío se lee como «no hay datos» y manda a buscar el
    problema al sitio equivocado.
    """
    tenant_id = uow.tenant_id
    informe = _informe(uow.db, tenant_id, informe_id)
    if not informe.activo:
        raise Conflicto("Ese informe está desactivado", error_code="informe.desactivado")
    if informe.roles and not es_admin and not (set(informe.roles) & set(roles)):
        # 404 y no 403, como en el resto del producto: un 403 confirma que ese
        # informe existe y de qué va su nombre.
        raise NoEncontrado("El informe no existe", error_code="informe.no_encontrado")

    plan = compilar(
        uow.db,
        tenant_id,
        informe,
        roles=roles,
        es_admin=es_admin,
        usuario_id=usuario_id,
        filtros_extra=filtros,
    )

    empezado = _ahora()
    if _EJECUTOR is None:
        uow.db.add(
            EjecucionInforme(
                tenant_id=tenant_id,
                informe_id=informe.id,
                origen=origen,
                usuario_id=usuario_id,
                ok=False,
                error="No hay ejecutor analítico registrado",
                formato=formato,
                campos_retirados=plan["campos_retirados"],
            )
        )
        uow.db.flush()
        raise Conflicto(
            "No hay ningún motor analítico conectado, así que este informe no se "
            "puede ejecutar. No es que no haya datos.",
            error_code="informe.sin_ejecutor",
        )

    try:
        salida = _EJECUTOR(plan=plan, tenant_id=tenant_id)
        filas = list(salida.get("filas") or [])
        error = None
        ok = True
    except Exception as exc:  # el motor analítico es externo: su fallo es un dato
        filas, error, ok = [], str(exc)[:1000], False

    truncado = len(filas) > plan["limite"]
    if truncado:
        filas = filas[: plan["limite"]]

    uow.db.add(
        EjecucionInforme(
            tenant_id=tenant_id,
            informe_id=informe.id,
            origen=origen,
            usuario_id=usuario_id,
            filas=len(filas),
            duracion_ms=int((_ahora() - empezado).total_seconds() * 1000),
            truncado=truncado,
            formato=formato,
            ok=ok,
            error=error,
            campos_retirados=plan["campos_retirados"],
        )
    )
    uow.db.flush()

    if not ok:
        raise Conflicto(
            f"El motor analítico no pudo resolver el informe: {error}",
            error_code="informe.fallo_ejecutor",
        )

    return {
        "informe": informe.clave,
        "nombre": informe.nombre,
        "filas": filas,
        "cuantas": len(filas),
        # Se dice si se cortó, en vez de devolver las primeras y callar: un
        # informe truncado en silencio se lee como el total, y con eso se toman
        # decisiones.
        "truncado": truncado,
        "limite": plan["limite"],
        "campos_retirados": plan["campos_retirados"],
        "acotado_al_usuario": plan["acotado_al_usuario"],
    }


def _informe(db: Session, tenant_id: UUID, informe_id: UUID) -> Informe:
    fila = db.execute(
        select(Informe).where(Informe.id == informe_id, Informe.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("El informe no existe", error_code="informe.no_encontrado")
    return fila


# ── Exportar (CRM-05.01.01.07) ────────────────────────────────────────────


def exportar(
    filas: list[dict[str, Any]], *, formato: str = "csv", nombre: str = "informe"
) -> dict[str, Any]:
    """Convierte las filas al formato pedido.

    CSV se genera aquí porque es texto y no necesita nada. **Excel y PDF no**: se
    devuelve el encargo para el generador documental, que ya existe y es común a
    toda la suite. Meter una librería de PDF en el servicio de explotación
    obligaría a desplegarlo para cambiar una tipografía, y acabaría habiendo dos
    maquetaciones distintas del mismo dato.
    """
    if formato not in FORMATOS:
        raise ErrorValidacion(
            f"Formato «{formato}» no válido.",
            error_code="informe.formato_no_valido",
            detalle={"validos": list(FORMATOS)},
        )
    if formato == "json":
        return {"formato": "json", "filas": filas}
    if formato == "csv":
        if not filas:
            return {"formato": "csv", "contenido": "", "filas": 0, "vacio": True}
        buffer = io.StringIO()
        escritor = csv.DictWriter(buffer, fieldnames=list(filas[0].keys()))
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({k: _texto(v) for k, v in fila.items()})
        return {
            "formato": "csv",
            "contenido": buffer.getvalue(),
            "filas": len(filas),
            "vacio": False,
        }
    return {
        "formato": formato,
        "encargo": {
            "plantilla": f"informe/{formato}",
            "nombre": nombre,
            "columnas": list(filas[0].keys()) if filas else [],
            "filas": filas,
        },
        "filas": len(filas),
        "vacio": not filas,
    }


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    return str(valor)


# ── Programación y distribución (CRM-05.01.01.06) ─────────────────────────


def _siguiente_ejecucion(programacion: ProgramacionInforme, desde: datetime) -> datetime:
    base = desde.replace(hour=programacion.hora, minute=0, second=0, microsecond=0)
    if programacion.periodicidad == "diaria":
        return base if base > desde else base + timedelta(days=1)
    if programacion.periodicidad == "semanal":
        objetivo = programacion.dia_semana if programacion.dia_semana is not None else 0
        dias = (objetivo - base.weekday()) % 7
        candidato = base + timedelta(days=dias)
        return candidato if candidato > desde else candidato + timedelta(days=7)
    dia = programacion.dia_mes or 1
    mes, anio = base.month, base.year
    candidato = base.replace(day=min(dia, 28))
    if candidato <= desde:
        mes, anio = (mes % 12 + 1, anio + (1 if mes == 12 else 0))
        candidato = candidato.replace(year=anio, month=mes)
    return candidato


def programar(
    uow: UnidadDeTrabajo,
    informe_id: UUID,
    *,
    periodicidad: str = "semanal",
    hora: int = 7,
    dia_semana: int | None = None,
    dia_mes: int | None = None,
    formato: str = "csv",
    destinatarios: list[str] | None = None,
    destino_externo: str = "",
    omitir_si_vacio: bool = False,
    nombre: str = "",
) -> ProgramacionInforme:
    """Programa el envío. Exige al menos un destino."""
    if periodicidad not in ("diaria", "semanal", "mensual"):
        raise ErrorValidacion(
            f"Periodicidad «{periodicidad}» no válida.",
            error_code="informe.periodicidad_no_valida",
        )
    if not destinatarios and not destino_externo:
        raise ErrorValidacion(
            "Una programación sin destino no manda el informe a ninguna parte.",
            error_code="informe.programacion_sin_destino",
        )
    _informe(uow.db, uow.tenant_id, informe_id)
    fila = ProgramacionInforme(
        tenant_id=uow.tenant_id,
        informe_id=informe_id,
        nombre=nombre,
        periodicidad=periodicidad,
        hora=hora,
        dia_semana=dia_semana,
        dia_mes=dia_mes,
        formato=formato,
        destinatarios=list(destinatarios or []),
        destino_externo=destino_externo or None,
        omitir_si_vacio=omitir_si_vacio,
    )
    fila.proxima_at = _siguiente_ejecucion(fila, _ahora())
    uow.db.add(fila)
    uow.db.flush()
    return fila


def correr_programadas(
    uow: UnidadDeTrabajo, tenant_id: UUID, *, tope_fallos: int = 3
) -> dict[str, Any]:
    """Ejecuta lo que toca y lo manda.

    **Un informe programado que falla avisa**, y a los `tope_fallos` seguidos se
    desactiva y se dice. Un informe que deja de llegar no se echa de menos —la
    gente supone que no había nada que contar— y eso convierte un fallo en un
    punto ciego de semanas; pero seguir intentándolo cada día contra un informe
    roto llena la bandeja de todo el mundo con el mismo error.
    """
    ahora = _ahora()
    pendientes = (
        uow.db.execute(
            select(ProgramacionInforme).where(
                ProgramacionInforme.tenant_id == tenant_id,
                ProgramacionInforme.activa.is_(True),
                ProgramacionInforme.proxima_at.isnot(None),
                ProgramacionInforme.proxima_at <= ahora,
            )
        )
        .scalars()
        .all()
    )
    mandados: list[dict[str, Any]] = []
    fallados: list[dict[str, Any]] = []
    desactivadas: list[str] = []

    for programacion in pendientes:
        try:
            salida = ejecutar(
                uow,
                programacion.informe_id,
                es_admin=True,
                origen="programada",
                formato=programacion.formato,
            )
            paquete = exportar(salida["filas"], formato=programacion.formato)
            programacion.ultimo_error = None
            programacion.fallos_seguidos = 0
            if paquete.get("vacio") and programacion.omitir_si_vacio:
                mandados.append({"programacion": str(programacion.id), "omitido_por_vacio": True})
            else:
                uow.emitir(
                    "report.delivered",
                    subject=("informe", programacion.informe_id),
                    data={
                        "informe_id": str(programacion.informe_id),
                        "programacion_id": str(programacion.id),
                        "formato": programacion.formato,
                        "filas": salida["cuantas"],
                        "destinatarios": list(programacion.destinatarios or []),
                        "destino_externo": programacion.destino_externo or "",
                    },
                )
                mandados.append({"programacion": str(programacion.id), "filas": salida["cuantas"]})
        except Exception as exc:
            programacion.ultimo_error = str(exc)[:1000]
            programacion.fallos_seguidos += 1
            fallados.append(
                {"programacion": str(programacion.id), "error": programacion.ultimo_error}
            )
            uow.emitir(
                "report.failed",
                subject=("informe", programacion.informe_id),
                data={
                    "informe_id": str(programacion.informe_id),
                    "programacion_id": str(programacion.id),
                    "error": programacion.ultimo_error,
                    "fallos_seguidos": programacion.fallos_seguidos,
                },
            )
            if programacion.fallos_seguidos >= tope_fallos:
                programacion.activa = False
                desactivadas.append(str(programacion.id))
        finally:
            programacion.ultima_at = ahora
            programacion.proxima_at = _siguiente_ejecucion(programacion, ahora)

    uow.db.flush()
    return {
        "revisadas": len(pendientes),
        "mandados": mandados,
        "fallados": fallados,
        "desactivadas": desactivadas,
        "medible": bool(pendientes),
    }


# ── Instantáneas (CRM-05.01.01.05) ────────────────────────────────────────


def tomar_instantanea(
    uow: UnidadDeTrabajo, informe_id: UUID, *, el_dia: date | None = None
) -> dict[str, Any]:
    """Guarda lo que dice el informe hoy, para poder compararlo mañana.

    Se guardan **los resúmenes, no las filas**: guardar el detalle entero
    convertiría la tabla en una copia del CRM que crece sin fin y que nadie purga.

    Dos veces el mismo día **no crea dos instantáneas**: se actualiza la del día.
    Con dos, la serie tendría dos puntos para la misma fecha y cualquier gráfico
    de tendencia saldría con un pico que no ocurrió.
    """
    tenant_id = uow.tenant_id
    dia = el_dia or date.today()
    salida = ejecutar(uow, informe_id, es_admin=True, origen="programada")

    resumen: dict[str, Any] = {"filas": salida["cuantas"]}
    numericas: dict[str, Decimal] = {}
    for fila in salida["filas"]:
        for clave, valor in fila.items():
            if isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool):
                numericas[clave] = numericas.get(clave, Decimal(0)) + Decimal(str(valor))
    resumen["totales"] = {k: str(v) for k, v in numericas.items()}

    existente = uow.db.execute(
        select(InstantaneaInforme).where(
            InstantaneaInforme.tenant_id == tenant_id,
            InstantaneaInforme.informe_id == informe_id,
            InstantaneaInforme.tomada_el == dia,
        )
    ).scalar_one_or_none()
    if existente is not None:
        existente.filas = salida["cuantas"]
        existente.resumen = resumen
        uow.db.flush()
        return {"instantanea_id": str(existente.id), "dia": str(dia), "sustituida": True}

    fila = InstantaneaInforme(
        tenant_id=tenant_id,
        informe_id=informe_id,
        tomada_el=dia,
        filas=salida["cuantas"],
        resumen=resumen,
    )
    uow.db.add(fila)
    uow.db.flush()
    return {"instantanea_id": str(fila.id), "dia": str(dia), "sustituida": False}


def tendencia(
    db: Session, tenant_id: UUID, informe_id: UUID, *, desde: date | None = None
) -> dict[str, Any]:
    """La serie histórica del informe.

    Con menos de dos puntos **no se dice que hay tendencia**: una sola
    instantánea es una foto, y llamarla tendencia hace que alguien saque una
    conclusión de un punto.
    """
    consulta = select(InstantaneaInforme).where(
        InstantaneaInforme.tenant_id == tenant_id, InstantaneaInforme.informe_id == informe_id
    )
    if desde:
        consulta = consulta.where(InstantaneaInforme.tomada_el >= desde)
    filas = db.execute(consulta.order_by(InstantaneaInforme.tomada_el)).scalars().all()
    return {
        "puntos": [
            {"dia": str(f.tomada_el), "filas": f.filas, "totales": f.resumen.get("totales", {})}
            for f in filas
        ],
        "cuantos": len(filas),
        "hay_tendencia": len(filas) >= 2,
        "aviso": ""
        if len(filas) >= 2
        else "Con una sola instantánea no hay tendencia: es una foto.",
    }


# ── Cuadros de mando (CRM-05.01.02.01) ────────────────────────────────────


def crear_cuadro(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    componentes: list[dict[str, Any]] | None = None,
    roles: list[str] | None = None,
    equipos: list[str] | None = None,
    propietario_id: UUID | None = None,
    por_defecto_para: str = "",
    descripcion: str = "",
) -> CuadroMando:
    """Crea un cuadro de mando.

    Solo puede haber **un cuadro por defecto por rol**: con dos, cuál se abre
    dependería del orden de la consulta, y eso cambia al restaurar una copia.
    """
    tenant_id = uow.tenant_id
    if por_defecto_para:
        ya = uow.db.execute(
            select(CuadroMando).where(
                CuadroMando.tenant_id == tenant_id,
                CuadroMando.por_defecto_para == por_defecto_para,
                CuadroMando.activo.is_(True),
            )
        ).scalar_one_or_none()
        if ya is not None:
            raise Conflicto(
                f"El rol «{por_defecto_para}» ya tiene un cuadro por defecto: " f"«{ya.clave}».",
                error_code="cuadro.defecto_duplicado",
            )

    fila = CuadroMando(
        tenant_id=tenant_id,
        clave=clave,
        nombre=nombre,
        descripcion=descripcion,
        componentes=list(componentes or []),
        roles=list(roles or []),
        equipos=list(equipos or []),
        propietario_id=propietario_id,
        por_defecto_para=por_defecto_para or None,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def cuadros_de(
    db: Session,
    tenant_id: UUID,
    *,
    roles: frozenset[str] = frozenset(),
    usuario_id: UUID | None = None,
    equipos: frozenset[str] = frozenset(),
    es_admin: bool = False,
) -> list[dict[str, Any]]:
    """Los cuadros que puede abrir esta persona.

    Un cuadro sin roles ni equipos es **de todos**: exigir declarar el público de
    cada uno haría que el primero que alguien crea no lo vea nadie, y la
    conclusión sería que los cuadros no funcionan.
    """
    filas = (
        db.execute(
            select(CuadroMando)
            .where(CuadroMando.tenant_id == tenant_id, CuadroMando.activo.is_(True))
            .order_by(CuadroMando.nombre)
        )
        .scalars()
        .all()
    )
    salida = []
    for fila in filas:
        suyo = fila.propietario_id is not None and fila.propietario_id == usuario_id
        publico = not fila.roles and not fila.equipos
        por_rol = bool(set(fila.roles or []) & set(roles))
        por_equipo = bool(set(fila.equipos or []) & set(equipos))
        if not (es_admin or suyo or publico or por_rol or por_equipo):
            continue
        salida.append(
            {
                "id": str(fila.id),
                "clave": fila.clave,
                "nombre": fila.nombre,
                "descripcion": fila.descripcion,
                "componentes": list(fila.componentes or []),
                "por_defecto": fila.por_defecto_para in roles if fila.por_defecto_para else False,
                "propio": suyo,
            }
        )
    return salida
