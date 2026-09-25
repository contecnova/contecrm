"""Modelo semántico y métricas certificadas (CRM-05.01.03.03).

El problema que resuelve esto no es técnico: es que **«ingresos» significa cinco
cosas distintas** en la misma empresa. El de ventas cuenta lo firmado, el de
finanzas lo facturado, el de dirección lo cobrado, y los tres llevan su cifra a la
misma reunión. Nadie miente; nadie está usando la misma definición.

Una métrica certificada es una definición **escrita, con dueño y con versión**.
De ahí las decisiones:

**La definición es un plan, no SQL.** Igual que en el motor de informes (RT-4):
así la misma métrica se puede calcular contra el almacén analítico o contra
contecintelligence sin reescribirla, y nadie mete una subconsulta a mano que solo
funciona en un sitio.

**Certificar es un acto con dueño y fecha.** Una métrica sin dueño no se puede
corregir: cuando alguien detecta que está mal, no hay a quién preguntar y acaba
creándose otra al lado, que es como se llega a cinco definiciones de ingresos.

**Cambiar una métrica certificada crea una versión nueva.** Los informes de hace
tres meses se hicieron con la definición de entonces; reescribirla en sitio haría
que un número publicado cambiara solo, y quien lo miró no se enteraría.

**Lo no certificado se marca como no certificado, y se sirve igual.** Prohibir las
métricas en borrador haría que la gente las calculara en una hoja aparte, que es
justo lo que se quiere evitar; lo que no puede pasar es que se confundan con las
buenas.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
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

logger = get_logger(__name__)

# Identificador admitido para claves y campos. El mismo criterio que en el motor
# de informes: lo que va a acabar nombrando una columna se valida aquí, no allí.
IDENTIFICADOR = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

# Agregaciones que sabe expresar el plan. Cerrada: una agregación nueva necesita
# que el ejecutor sepa traducirla, y aceptarla sin eso daría una métrica que
# falla al usarse, no al definirse.
AGREGACIONES = ("suma", "cuenta", "cuenta_distinta", "media", "minimo", "maximo", "ratio")

# Cuántas filas como mucho trae una métrica agrupada. Es un tope de cordura, no
# una preferencia: una métrica agrupada por una dimensión de alta cardinalidad
# —el identificador de cliente, por ejemplo— devolvería una fila por cliente y
# eso no es una métrica, es una exportación.
TOPE_FILAS_METRICA = 5_000

# Estados de una métrica.
#
#   borrador     se está afinando; se sirve marcada
#   certificada  revisada, con dueño y versión
#   obsoleta     ya no se usa; se conserva para poder leer informes viejos
ESTADOS = ("borrador", "certificada", "obsoleta")


class Metrica(Base, TimestampMixin, SoftDeleteMixin):
    """Una definición de negocio, versionada (CRM-05.01.03.03)."""

    __tablename__ = "metricas_semanticas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    # La definición **en palabras**, para quien la lee en un panel. No es
    # decorativa: es lo único que distingue «ingresos firmados» de «ingresos
    # cobrados» para quien no va a mirar el plan.
    definicion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    objeto: Mapped[str] = mapped_column(String(60), nullable=False)
    agregacion: Mapped[str] = mapped_column(
        String(20), nullable=False, default="suma", info={"opciones": AGREGACIONES}
    )
    campo: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Con `ratio`: numerador y denominador, los dos como claves de métrica.
    numerador: Mapped[str | None] = mapped_column(String(80), nullable=True)
    denominador: Mapped[str | None] = mapped_column(String(80), nullable=True)
    filtros: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    dimensiones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    unidad: Mapped[str] = mapped_column(String(20), nullable=False, default="")

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")
    # Quién responde de ella. Sin dueño, cuando alguien detecta que está mal no
    # hay a quién preguntar y acaba creándose otra al lado.
    dueno_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    certificada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    certificada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_version: Mapped[str] = mapped_column(Text, nullable=False, default="")
    vigente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", "version", name="uq_metrica_version"),
        Index("ix_metricas_vigentes", "tenant_id", "vigente", "estado"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _vigente(db: Session, tenant_id: UUID, clave: str) -> Metrica | None:
    return (
        db.execute(
            select(Metrica)
            .where(
                Metrica.tenant_id == tenant_id,
                Metrica.clave == clave,
                Metrica.vigente.is_(True),
            )
            .order_by(Metrica.version.desc())
        )
        .scalars()
        .first()
    )


def definir(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    objeto: str,
    definicion: str = "",
    agregacion: str = "suma",
    campo: str | None = None,
    numerador: str | None = None,
    denominador: str | None = None,
    filtros: list[dict[str, Any]] | None = None,
    dimensiones: list[str] | None = None,
    unidad: str = "",
    dueno_id: UUID | None = None,
) -> tuple[Metrica, list[str]]:
    """Define una métrica **en borrador**.

    Nace sin certificar a propósito: certificar es un acto, y una métrica que
    nace certificada no la ha revisado nadie.
    """
    if not IDENTIFICADOR.match(clave):
        raise ErrorValidacion(
            "La clave de una métrica es un identificador en minúsculas: acaba "
            "nombrando una columna en el plan.",
            error_code="semantico.clave_no_valida",
        )
    if agregacion not in AGREGACIONES:
        raise ErrorValidacion(
            f"Agregación «{agregacion}» no soportada.",
            error_code="semantico.agregacion_no_valida",
            detalle={"validas": list(AGREGACIONES)},
        )
    if agregacion == "ratio" and not (numerador and denominador):
        raise ErrorValidacion(
            "Un ratio necesita numerador y denominador, y los dos tienen que ser "
            "métricas: si no, nadie puede saber qué divide a qué.",
            error_code="semantico.ratio_incompleto",
        )
    if agregacion not in ("cuenta", "ratio") and not campo:
        raise ErrorValidacion(
            f"«{agregacion}» necesita saber sobre qué campo se calcula.",
            error_code="semantico.sin_campo",
        )
    if campo and not IDENTIFICADOR.match(campo):
        raise ErrorValidacion(
            "El campo tiene que ser un identificador válido.",
            error_code="semantico.campo_no_valido",
        )
    if _vigente(uow.db, uow.tenant_id, clave) is not None:
        raise Conflicto(
            "Ya hay una métrica vigente con esa clave. Para cambiarla se crea una "
            "versión nueva, que es lo que impide que un número publicado cambie solo.",
            error_code="semantico.clave_ocupada",
        )

    avisos: list[str] = []
    if not definicion.strip():
        avisos.append(
            "Sin definición en palabras: quien la lea en un panel no podrá "
            "distinguirla de otra parecida, que es el problema que esto resuelve."
        )
    if dueno_id is None:
        avisos.append(
            "Sin dueño: cuando alguien detecte que está mal no habrá a quién "
            "preguntar, y acabará creándose otra al lado."
        )

    fila = Metrica(
        tenant_id=uow.tenant_id,
        clave=clave,
        version=1,
        nombre=nombre.strip(),
        definicion=definicion.strip(),
        objeto=objeto.strip(),
        agregacion=agregacion,
        campo=campo,
        numerador=numerador,
        denominador=denominador,
        filtros=list(filtros or []),
        dimensiones=list(dimensiones or []),
        unidad=unidad,
        dueno_id=dueno_id,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def certificar(
    uow: UnidadDeTrabajo, *, clave: str, por: UUID | None = None, dueno_id: UUID | None = None
) -> Metrica:
    """Certifica la versión vigente. **Exige dueño y definición escrita.**"""
    fila = _vigente(uow.db, uow.tenant_id, clave)
    if fila is None:
        raise NoEncontrado("No hay métrica con esa clave", error_code="semantico.no_encontrada")
    if dueno_id is not None:
        fila.dueno_id = dueno_id
    if fila.dueno_id is None:
        raise ErrorValidacion(
            "Certificar exige un dueño: una métrica que nadie responde no se puede "
            "corregir cuando falle.",
            error_code="semantico.sin_dueno",
        )
    if not fila.definicion.strip():
        raise ErrorValidacion(
            "Certificar exige la definición en palabras: es lo único que distingue "
            "«ingresos firmados» de «ingresos cobrados» para quien lee el panel.",
            error_code="semantico.sin_definicion",
        )
    fila.estado = "certificada"
    fila.certificada_por = por
    fila.certificada_at = _ahora()
    uow.db.flush()
    registrar(
        uow.db,
        accion="metrica.certificada",
        objeto="metrica",
        objeto_id=fila.id,
        datos={"clave": fila.clave, "version": fila.version},
        tenant_id=uow.tenant_id,
    )
    return fila


def nueva_version(uow: UnidadDeTrabajo, *, clave: str, motivo: str, **cambios: Any) -> Metrica:
    """Crea una versión nueva y deja la anterior como no vigente.

    **Con motivo obligatorio.** Un número publicado que cambia sin explicación
    hace que se desconfíe de todos los demás, y quien lo miró hace tres meses
    tiene derecho a saber que la definición cambió — y a seguir leyendo su informe
    con la de entonces.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Cambiar una métrica exige decir por qué: quien leyó el número de hace "
            "tres meses tiene que poder entender la diferencia.",
            error_code="semantico.motivo_obligatorio",
        )
    anterior = _vigente(uow.db, uow.tenant_id, clave)
    if anterior is None:
        raise NoEncontrado("No hay métrica con esa clave", error_code="semantico.no_encontrada")

    nueva = Metrica(
        tenant_id=uow.tenant_id,
        clave=anterior.clave,
        version=anterior.version + 1,
        nombre=cambios.get("nombre", anterior.nombre),
        definicion=cambios.get("definicion", anterior.definicion),
        objeto=cambios.get("objeto", anterior.objeto),
        agregacion=cambios.get("agregacion", anterior.agregacion),
        campo=cambios.get("campo", anterior.campo),
        numerador=cambios.get("numerador", anterior.numerador),
        denominador=cambios.get("denominador", anterior.denominador),
        filtros=list(cambios.get("filtros", anterior.filtros) or []),
        dimensiones=list(cambios.get("dimensiones", anterior.dimensiones) or []),
        unidad=cambios.get("unidad", anterior.unidad),
        dueno_id=cambios.get("dueno_id", anterior.dueno_id),
        # La versión nueva nace **en borrador** aunque la anterior estuviera
        # certificada: certificar es revisar, y lo que ha cambiado no lo ha
        # revisado nadie todavía.
        estado="borrador",
        motivo_version=motivo.strip(),
    )
    anterior.vigente = False
    uow.db.add(nueva)
    uow.db.flush()
    registrar(
        uow.db,
        accion="metrica.nueva_version",
        objeto="metrica",
        objeto_id=nueva.id,
        datos={"clave": clave, "desde": anterior.version, "hasta": nueva.version, "motivo": motivo},
        tenant_id=uow.tenant_id,
    )
    return nueva


def plan_de(
    db: Session,
    tenant_id: UUID,
    *,
    clave: str,
    dimensiones: list[str] | None = None,
    filtros: list[dict[str, Any]] | None = None,
    version: int | None = None,
) -> dict[str, Any]:
    """El plan de cálculo de una métrica (CRM-05.01.03.03).

    **Plan y no SQL**, por lo mismo que en el motor de informes: así la misma
    definición se calcula contra el almacén analítico o contra
    contecintelligence sin reescribirla.

    Se puede pedir una **versión concreta**: es lo que permite reproducir un
    informe de hace tres meses con la definición que tenía entonces, en vez de
    recalcularlo con otra y decir que es el mismo número.
    """
    consulta = select(Metrica).where(Metrica.tenant_id == tenant_id, Metrica.clave == clave)
    if version is not None:
        consulta = consulta.where(Metrica.version == version)
    else:
        consulta = consulta.where(Metrica.vigente.is_(True))
    fila = db.execute(consulta.order_by(Metrica.version.desc())).scalars().first()
    if fila is None:
        raise NoEncontrado("No hay métrica con esa clave", error_code="semantico.no_encontrada")

    pedidas = [d for d in (dimensiones or [])]
    desconocidas = sorted(set(pedidas) - set(fila.dimensiones or []))
    if desconocidas:
        raise ErrorValidacion(
            f"Esta métrica no está definida por {desconocidas}: agrupar por una "
            "dimensión que no forma parte de su definición da un número que no es "
            "esa métrica.",
            error_code="semantico.dimension_no_declarada",
            detalle={"declaradas": fila.dimensiones},
        )

    plan: dict[str, Any] = {
        "metrica": fila.clave,
        "version": fila.version,
        "objeto": fila.objeto,
        "agregacion": fila.agregacion,
        "campo": fila.campo,
        "agrupar_por": pedidas,
        "filtros": [*(fila.filtros or []), *(filtros or [])],
        "unidad": fila.unidad,
        # Lo que hay que enseñar junto al número. Sin esto, una métrica en
        # borrador se lee igual que una certificada.
        "certificada": fila.estado == "certificada",
        "definicion": fila.definicion,
        "dueno_id": str(fila.dueno_id) if fila.dueno_id else None,
        "aviso": (
            ""
            if fila.estado == "certificada"
            else "Métrica sin certificar: el número es correcto según su definición, "
            "pero esa definición no la ha revisado nadie."
        ),
    }
    if fila.agregacion == "ratio":
        plan["numerador"] = plan_de(db, tenant_id, clave=str(fila.numerador))
        plan["denominador"] = plan_de(db, tenant_id, clave=str(fila.denominador))
    return plan


def ejecutar(
    db: Session,
    tenant_id: UUID,
    *,
    clave: str,
    dimensiones: list[str] | None = None,
    filtros: list[dict[str, Any]] | None = None,
    version: int | None = None,
    usuario_id: UUID | None = None,
    roles: frozenset[str] = frozenset(),
    es_admin: bool = False,
) -> dict[str, Any]:
    """Calcula la métrica y devuelve el número, con lo que hay que leer al lado.

    Existía `plan` y no existía ESTO. O sea que una métrica se podía definir,
    versionar y certificar, y no se podía ver cuánto vale: la pantalla enseñaba
    su definición y nada más. Una métrica que no se puede mirar no es una
    métrica, es una ficha.

    El número **nunca va solo**: lleva su unidad, si está certificada y el aviso
    cuando no lo está. Un número sin eso se copia a una presentación y allí ya
    parece oficial.

    Las de tipo `ratio` se calculan de sus dos mitades, y **se dice el
    denominador**: un porcentaje sobre cero es infinito, no cien.
    """
    plan = plan_de(
        db, tenant_id, clave=clave, dimensiones=dimensiones, filtros=filtros, version=version
    )
    if plan["agregacion"] == "ratio":
        arriba = _valor_de(db, tenant_id, plan["numerador"], usuario_id, roles, es_admin)
        abajo = _valor_de(db, tenant_id, plan["denominador"], usuario_id, roles, es_admin)
        total = None if not abajo.get("valor") else arriba["valor"] / abajo["valor"]
        return {
            **_cabecera(plan),
            "valor": total,
            "numerador": arriba.get("valor"),
            "denominador": abajo.get("valor"),
            # Se dice por qué no hay número, en vez de devolver cero: un ratio
            # sobre cero no es cero, es que no se puede calcular.
            "sin_valor": None if total is not None else "el denominador es cero",
            "filas": [],
        }

    salida = _valor_de(db, tenant_id, plan, usuario_id, roles, es_admin)
    return {**_cabecera(plan), **salida, **_aviso_de_truncado(db, tenant_id, plan)}


def _aviso_de_truncado(db: Session, tenant_id: UUID, plan: dict[str, Any]) -> dict[str, Any]:
    """Si el objeto se lee incompleto, se dice JUNTO AL NÚMERO.

    No en un rincón ni en un registro: pegado a la cifra. `casos_abiertos`
    contestaba 50 habiendo 153 —porque su listado no pagina y la explotación solo
    ve la primera página— con su unidad y su cara de cifra buena. Un número así
    es peor que un error: nadie lo comprueba.
    """
    from services.analytics.fuente import objeto_truncado

    if not objeto_truncado(db, tenant_id, str(plan.get("objeto") or "")):
        return {}
    return {
        "incompleta": True,
        "aviso_datos": (
            "Este objeto se lee por páginas y su listado no las ofrece, así que "
            "la cifra cuenta solo las primeras filas. No es el total."
        ),
    }


def _cabecera(plan: dict[str, Any]) -> dict[str, Any]:
    """Lo que acompaña al número y no se puede separar de él."""
    return {
        "metrica": plan["metrica"],
        "version": plan["version"],
        "unidad": plan.get("unidad") or "",
        "certificada": plan.get("certificada", False),
        "aviso": plan.get("aviso") or "",
        "definicion": plan.get("definicion") or "",
        "agrupado_por": list(plan.get("agrupar_por") or []),
    }


def _valor_de(
    db: Session,
    tenant_id: UUID,
    plan: dict[str, Any],
    usuario_id: UUID | None,
    roles: frozenset[str],
    es_admin: bool,
) -> dict[str, Any]:
    """Manda el plan al mismo ejecutor que usan los informes.

    Al mismo, y no a uno propio: dos motores dando la misma cifra es cómo se
    acaba con dos números distintos para «cuántas oportunidades hay», y entonces
    la discusión es cuál de los dos está bien.
    """
    from services.analytics import informes as inf

    if not inf.hay_ejecutor():
        raise Conflicto(
            "No hay ningún motor analítico conectado, así que esta métrica no se "
            "puede calcular. No es que valga cero.",
            error_code="semantico.sin_ejecutor",
        )

    agrupar = list(plan.get("agrupar_por") or [])
    portable = {
        "vista": inf.entidad_de(db, str(plan["objeto"]), tenant_id),
        "objeto": plan["objeto"],
        "tipo": "agrupado" if agrupar else "tabular",
        "columnas": [],
        "agrupaciones": [{"campo": c} for c in agrupar],
        "metricas": [
            {
                "agregado": str(plan["agregacion"]),
                "campo": str(plan.get("campo") or ""),
                "como": "valor",
            }
        ],
        "filtros": list(plan.get("filtros") or []),
        "orden": [],
        "limite": TOPE_FILAS_METRICA,
        "_usuario_id": str(usuario_id) if usuario_id else "",
        "_roles": sorted(roles),
        "_es_admin": bool(es_admin),
    }
    filas = list(inf.ejecutar_plan_portable(portable, tenant_id=tenant_id))
    if agrupar:
        return {"valor": None, "filas": filas}
    # Sin agrupar, el resultado es una fila con un número. Vacío significa que no
    # hay datos que cumplan el filtro, que no es lo mismo que cero: se dice.
    if not filas:
        return {"valor": None, "filas": [], "sin_valor": "no hay datos que cumplan el filtro"}
    primera = filas[0]
    valor = primera[-1] if isinstance(primera, (list, tuple)) else primera
    return {"valor": valor, "filas": []}


def una(db: Session, tenant_id: UUID, clave: str) -> dict[str, Any]:
    """Una métrica por su clave, en su versión vigente.

    Faltaba, y sin ella la pantalla no podía tener FICHA: el front deriva la
    ficha de que exista un `GET` por identificador, y de la ficha cuelgan las
    acciones. O sea que certificar una métrica o sacarle una versión nueva
    existían en la API y no se podían hacer desde ninguna parte.
    """
    from crmcore.errors import NoEncontrado

    fila = db.execute(
        select(Metrica).where(
            Metrica.tenant_id == tenant_id, Metrica.clave == clave, Metrica.vigente.is_(True)
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Esa métrica no existe", error_code="metrica.no_encontrada")
    return {
        "id": str(fila.id),
        "clave": fila.clave,
        "nombre": fila.nombre,
        "version": fila.version,
        "definicion": fila.definicion,
        "objeto": fila.objeto,
        "agregacion": fila.agregacion,
        "dimensiones": fila.dimensiones,
        "unidad": fila.unidad,
        "estado": fila.estado,
        "certificada": fila.estado == "certificada",
        "dueno_id": str(fila.dueno_id) if fila.dueno_id else None,
    }


def catalogo(db: Session, tenant_id: UUID, *, solo_certificadas: bool = False) -> dict[str, Any]:
    """El diccionario de métricas, con su estado y su dueño.

    Es el documento que evita la reunión de las cinco definiciones de ingresos, y
    por eso las no certificadas **también salen**: esconderlas hace que se
    calculen en una hoja aparte, que es peor.
    """
    consulta = select(Metrica).where(Metrica.tenant_id == tenant_id, Metrica.vigente.is_(True))
    if solo_certificadas:
        consulta = consulta.where(Metrica.estado == "certificada")
    filas = db.execute(consulta.order_by(Metrica.clave)).scalars().all()
    return {
        "metricas": [
            {
                "clave": f.clave,
                "nombre": f.nombre,
                "version": f.version,
                "definicion": f.definicion,
                "objeto": f.objeto,
                "agregacion": f.agregacion,
                "dimensiones": f.dimensiones,
                "unidad": f.unidad,
                "estado": f.estado,
                "certificada": f.estado == "certificada",
                "dueno_id": str(f.dueno_id) if f.dueno_id else None,
                "sin_dueno": f.dueno_id is None,
            }
            for f in filas
        ],
        "certificadas": len([f for f in filas if f.estado == "certificada"]),
        "en_borrador": len([f for f in filas if f.estado == "borrador"]),
        # Las que nadie responde: es la lista con la que se empieza a ordenar esto.
        "sin_dueno": [f.clave for f in filas if f.dueno_id is None],
    }
