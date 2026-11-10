"""Evaluación de la IA contra el modelo real.

**Lo que había, medido el 09-11-2026.** Ningún conjunto de evaluación: sólo las
métricas de los modelos predictivos. Del asistente, de las preguntas sobre los
datos, de los resúmenes, de la extracción y de los compromisos de una reunión
sólo se sabía que funcionaban *alguna vez*. «Funciona a la perfección» no se
podía afirmar ni negar.

Ahora hay un **banco de casos** por tenant (`evaluacion_de_serie` lo siembra la
primera vez) y una ejecución que los pasa **por el mismo puerto que las
funciones reales**, con el modelo que el enrutador elige para ese uso y con el
mismo tratamiento de lo que vuelve: las citas se cuentan con la misma
expresión que el asistente, el plan de una consulta se normaliza, se valida y
se agrega con las mismas funciones que la consulta real, lo extraído pasa por
el mismo filtro de cita literal y confianza, y los compromisos por el mismo
`proponer_extraidos`. Lo que se mide es lo que el usuario vería.

Cada ejecución queda guardada con su fecha, el modelo, **la versión de cada
prompt** (la huella del código del puerto que lo escribe y, si la hay, de la
plantilla del tenant), el acierto por función y caso a caso con el porqué del
fallo, el coste y la latencia. Si una función baja del umbral, se avisa por el
sistema de avisos de la casa.

**El juez.** Hay criterios que un programa no puede comprobar —«¿afirma algo
que no esté en el historial?»—. Ésos, y sólo ésos, se le preguntan a un modelo,
y el resultado lo dice (`juez: true`) al lado de cada uno. No hay ninguno en las
funciones donde se puede medir de otra forma.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
    Index,
    Integer,
    Numeric,
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

from services.intelligence.evaluacion_de_serie import CASOS, FUNCIONES

logger = get_logger(__name__)

ORIGENES_CASO = ("serie", "propio")
ESTADOS_EJECUCION = ("en_curso", "terminada", "fallida")
ORIGENES_EJECUCION = ("manual", "programada")

# Lo que se guarda de cada salida del modelo. Es para leer el porqué de un
# fallo, no un archivo: una respuesta entera de un resumen cabe de sobra.
_TOPE_SALIDA = 4000


# ── Tablas ────────────────────────────────────────────────────────────────


class CasoEvaluacionIA(Base, TimestampMixin):
    """Un caso del banco de evaluación del tenant: entrada y lo que se exige."""

    __tablename__ = "ia_evaluacion_casos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    funcion: Mapped[str] = mapped_column(
        String(40), nullable=False, info={"opciones": tuple(FUNCIONES)}
    )
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    entrada: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    criterios: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    origen: Mapped[str] = mapped_column(
        String(20), nullable=False, default="propio", info={"opciones": ORIGENES_CASO}
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_ia_evaluacion_caso"),)


class EjecucionEvaluacionIA(Base):
    """Una pasada del banco contra el modelo real, con su resultado agregado."""

    __tablename__ = "ia_evaluaciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="en_curso", info={"opciones": ESTADOS_EJECUCION}
    )
    origen: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual", info={"opciones": ORIGENES_EJECUCION}
    )
    pedida_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    empezada_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    terminada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Qué se pasa: las claves de los casos, fijadas al empezar. Un caso que se
    # desactiva a mitad no descoloca el recorrido.
    casos_previstos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    proveedor: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    # Los modelos por uso (`{"resumen": "gemini-2.5-flash", …}`): cada función
    # va con el que el enrutador le da, que puede no ser el mismo.
    modelos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # La versión de cada prompt: la huella del código que lo escribe y, si la
    # hay, de la plantilla del tenant. Comparar dos ejecuciones con versiones
    # distintas es comparar dos cosas.
    versiones_prompt: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    casos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aciertos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acierto: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    por_funcion: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    coste: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), nullable=False, default=Decimal(0), server_default=text("0")
    )
    latencia_media_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    umbral: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    bajo_umbral: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    aviso: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (Index("ix_ia_evaluaciones_tenant_fecha", "tenant_id", "empezada_at"),)


class ResultadoEvaluacionIA(Base):
    """Un caso en una ejecución: si acertó, y si no, por qué."""

    __tablename__ = "ia_evaluacion_resultados"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    ejecucion_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    caso_clave: Mapped[str] = mapped_column(String(120), nullable=False)
    caso_nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    funcion: Mapped[str] = mapped_column(String(40), nullable=False)
    acierto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    criterios: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    porque: Mapped[str] = mapped_column(Text, nullable=False, default="")
    salida: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    modelo: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    version_prompt: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    tokens_entrada: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_salida: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coste: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), nullable=False, default=Decimal(0), server_default=text("0")
    )
    latencia_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("ix_ia_evaluacion_resultados_ejecucion", "tenant_id", "ejecucion_id"),)


# ── Ajustes ───────────────────────────────────────────────────────────────


def _ajuste(clave: str, db: Any = None) -> Any:
    from services.intelligence import predictivo

    return predictivo._ajuste(clave, db)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ── El banco del tenant ───────────────────────────────────────────────────


def asegurar_banco(uow: UnidadDeTrabajo) -> int:
    """Guarda como del tenant los casos de serie que todavía no tiene.

    Por clave, y **también los desactivados**: un caso que el tenant apagó no
    vuelve a encenderse porque el producto lo traiga. Devuelve cuántos ha
    añadido.

    Y un caso de serie que el tenant **no ha tocado** (sigue en su versión 1)
    se pone al día con el del producto: si el producto corrige un criterio mal
    escrito, el tenant no se queda midiendo con el viejo. Uno que el tenant
    cambió es suyo y no se pisa; encenderlo o apagarlo no cuenta como cambio.
    """
    filas = {
        f.clave: f
        for f in uow.db.execute(
            select(CasoEvaluacionIA).where(CasoEvaluacionIA.tenant_id == uow.tenant_id)
        ).scalars()
    }
    nuevos = 0
    for caso in CASOS:
        fila = filas.get(caso["clave"])
        if fila is not None:
            if fila.origen == "serie" and int(fila.version or 1) == 1:
                if fila.entrada != caso["entrada"] or fila.criterios != caso["criterios"]:
                    fila.entrada = dict(caso["entrada"])
                    fila.criterios = list(caso["criterios"])
                fila.nombre = caso.get("nombre") or caso["clave"]
            continue
        uow.db.add(
            CasoEvaluacionIA(
                tenant_id=uow.tenant_id,
                clave=caso["clave"],
                funcion=caso["funcion"],
                nombre=caso.get("nombre") or caso["clave"],
                entrada=dict(caso["entrada"]),
                criterios=list(caso["criterios"]),
                activo=True,
                origen="serie",
            )
        )
        nuevos += 1
    uow.db.flush()
    return nuevos


def caso_a_dict(fila: CasoEvaluacionIA) -> dict[str, Any]:
    return {
        "id": str(fila.id),
        "clave": fila.clave,
        "funcion": fila.funcion,
        "funcion_nombre": FUNCIONES.get(fila.funcion, {}).get("nombre", fila.funcion),
        "nombre": fila.nombre,
        "entrada": fila.entrada,
        "criterios": fila.criterios,
        "activo": fila.activo,
        "origen": fila.origen,
        "version": fila.version,
        "con_juez": any(str(c.get("tipo")) == "juez" for c in fila.criterios or []),
    }


def casos(db: Session, tenant_id: UUID) -> dict[str, Any]:
    filas = (
        db.execute(
            select(CasoEvaluacionIA)
            .where(CasoEvaluacionIA.tenant_id == tenant_id)
            .order_by(CasoEvaluacionIA.funcion, CasoEvaluacionIA.clave)
        )
        .scalars()
        .all()
    )
    return {
        "casos": [caso_a_dict(f) for f in filas],
        # Sin banco instalado todavía se dice cuántos trae el producto: se
        # guardan al evaluar por primera vez.
        "instalado": bool(filas),
        "de_serie": len(CASOS),
        "funciones": {k: v["nombre"] for k, v in FUNCIONES.items()},
    }


def _validar_caso(funcion: str, entrada: dict[str, Any], criterios: list[Any]) -> None:
    if funcion not in FUNCIONES:
        raise ErrorValidacion(
            f"Función «{funcion}» no evaluable.",
            error_code="evaluacion.funcion",
            detalle={"validas": list(FUNCIONES)},
        )
    if not isinstance(entrada, dict) or not entrada:
        raise ErrorValidacion("El caso necesita su entrada.", error_code="evaluacion.sin_entrada")
    if not criterios:
        # Un caso sin criterios saldría siempre acertado: lo que no se puede
        # evaluar no se cumple.
        raise ErrorValidacion(
            "Un caso sin criterios no comprueba nada: saldría siempre acertado.",
            error_code="evaluacion.sin_criterios",
        )
    malos = [str(c.get("tipo")) for c in criterios if str(c.get("tipo")) not in COMPROBACIONES]
    if malos:
        raise ErrorValidacion(
            f"Criterios no reconocidos: {', '.join(malos)}.",
            error_code="evaluacion.criterio",
            detalle={"validos": sorted(COMPROBACIONES)},
        )


def crear_caso(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    funcion: str,
    nombre: str,
    entrada: dict[str, Any],
    criterios: list[Any],
) -> dict[str, Any]:
    _validar_caso(funcion, entrada, criterios)
    existe = uow.db.execute(
        select(CasoEvaluacionIA).where(
            CasoEvaluacionIA.tenant_id == uow.tenant_id, CasoEvaluacionIA.clave == clave
        )
    ).scalar_one_or_none()
    if existe is not None:
        raise Conflicto(f"Ya hay un caso «{clave}».", error_code="evaluacion.caso_repetido")
    fila = CasoEvaluacionIA(
        tenant_id=uow.tenant_id,
        clave=clave,
        funcion=funcion,
        nombre=nombre or clave,
        entrada=entrada,
        criterios=criterios,
        origen="propio",
    )
    uow.db.add(fila)
    uow.db.flush()
    return caso_a_dict(fila)


def cambiar_caso(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    activo: bool | None = None,
    nombre: str | None = None,
    entrada: dict[str, Any] | None = None,
    criterios: list[Any] | None = None,
) -> dict[str, Any]:
    fila = uow.db.execute(
        select(CasoEvaluacionIA).where(
            CasoEvaluacionIA.tenant_id == uow.tenant_id, CasoEvaluacionIA.clave == clave
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(f"No hay caso «{clave}».", error_code="evaluacion.caso_no_existe")
    if entrada is not None or criterios is not None:
        _validar_caso(
            fila.funcion,
            entrada if entrada is not None else fila.entrada,
            criterios if criterios is not None else fila.criterios,
        )
        if entrada is not None:
            fila.entrada = entrada
        if criterios is not None:
            fila.criterios = criterios
        # Cambiar lo que se exige es otro caso: la versión sube y el historial
        # lo puede decir.
        fila.version = int(fila.version or 1) + 1
    if nombre is not None:
        fila.nombre = nombre
    if activo is not None:
        fila.activo = bool(activo)
    uow.db.flush()
    return caso_a_dict(fila)


# ── Normalización y comprobaciones ────────────────────────────────────────


def _plano(texto: Any) -> str:
    from services.intelligence.consulta_natural import _plano as plano

    return " ".join(plano(str(texto or "")).split())


def _alternativas(valor: Any) -> list[str]:
    """«5|cinco» → ["5", "cinco"]: cualquiera de las dos vale."""
    return [_plano(a) for a in str(valor).split("|") if a.strip()]


def _texto_de(salida: dict[str, Any], campo: str) -> str:
    valor = salida.get(campo)
    if isinstance(valor, list):
        return " \n ".join(
            " ".join(str(v) for v in x.values()) if isinstance(x, dict) else str(x) for x in valor
        )
    return str(valor or "")


def _numero(valor: Any) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _ok(ok: bool, porque: str = "") -> dict[str, Any]:
    return {"ok": bool(ok), "porque": "" if ok else porque}


def _c_contiene(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    texto = _plano(_texto_de(s, str(c.get("campo") or "texto")))
    faltan = [v for v in c.get("valores") or [] if not any(a in texto for a in _alternativas(v))]
    return _ok(not faltan, f"No dice {', '.join('«' + str(f) + '»' for f in faltan)}.")


def _c_no_contiene(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    texto = _plano(_texto_de(s, str(c.get("campo") or "texto")))
    sobran = [v for v in c.get("valores") or [] if any(a in texto for a in _alternativas(v))]
    return _ok(not sobran, f"Dice {', '.join('«' + str(f) + '»' for f in sobran)}, y no debe.")


def _c_igual(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    esperado, real = c.get("valor"), s.get(str(c.get("campo")))
    if esperado is None:
        return _ok(real in (None, ""), f"Esperaba nada y salió «{real}».")
    return _ok(
        _plano(real) == _plano(esperado),
        f"«{c.get('campo')}» es «{real}» y debía ser «{esperado}».",
    )


def _c_en(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    real = _plano(s.get(str(c.get("campo"))))
    validos = [_plano(v) for v in c.get("valores") or []]
    return _ok(
        real in validos,
        f"«{c.get('campo')}» es «{s.get(str(c.get('campo')))}»; valían {', '.join(validos)}.",
    )


def _c_numero(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    real = _numero(s.get(str(c.get("campo") or "valor")))
    esperado = float(c.get("valor") or 0)
    tolerancia = float(c.get("tolerancia") or 0.01)
    if real is None:
        return _ok(False, f"No hay cifra (salió «{s.get(str(c.get('campo') or 'valor'))}»).")
    return _ok(
        abs(real - esperado) <= tolerancia, f"Salió {real:g} y con los datos es {esperado:g}."
    )


def _c_grupos(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    reales = {_plano(k): v for k, v in (s.get("grupos") or {}).items()}
    tolerancia = float(c.get("tolerancia") or 0.01)
    malos = []
    for grupo, esperado in (c.get("valores") or {}).items():
        real = _numero(reales.get(_plano(grupo)))
        if real is None or abs(real - float(esperado)) > tolerancia:
            malos.append(f"{grupo}: {real if real is not None else 'nada'} (es {esperado})")
    return _ok(not malos, "Grupos mal: " + "; ".join(malos) + ".")


def _c_cita(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    n = int(c.get("n") or 0)
    return _ok(n in (s.get("citas") or []), f"No cita el fragmento [{n}], que es de donde sale.")


def _c_citas_validas(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    if s.get("citas_inventadas"):
        return _ok(False, f"Cita fragmentos que no existen: {s['citas_inventadas']}.")
    return _ok(bool(s.get("citas")), "No cita ninguna fuente: el asistente no la daría por buena.")


def _c_no_sabe(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    esperado = bool(c.get("valor"))
    real = bool(s.get("sin_respuesta"))
    if esperado:
        return _ok(real, "Debía decir que no lo sabe, y el producto no lo reconoce como tal.")
    return _ok(not real, "Dice que no lo sabe y la respuesta está en el conocimiento.")


def _iguales_campo(real: Any, esperado: Any, solo_digitos: bool) -> bool:
    if solo_digitos:
        return re.sub(r"\D", "", str(real)) == re.sub(r"\D", "", str(esperado))
    if isinstance(esperado, (int, float)) and not isinstance(esperado, bool):
        n = _numero(real)
        return n is not None and abs(n - float(esperado)) < 0.005
    return _plano(real) == _plano(esperado)


def _c_campos(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    extraidos = s.get("extraidos") or {}
    digitos = set(c.get("solo_digitos") or [])
    malos = []
    for clave, esperado in (c.get("valores") or {}).items():
        if clave not in extraidos:
            porque = next(
                (d["porque"] for d in s.get("descartados") or [] if d.get("campo") == clave), ""
            )
            malos.append(f"{clave}: no extraído" + (f" ({porque})" if porque else ""))
        elif not _iguales_campo(extraidos[clave], esperado, clave in digitos):
            malos.append(f"{clave}: «{extraidos[clave]}» y es «{esperado}»")
    return _ok(not malos, "; ".join(malos) + ".")


def _c_ausentes(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    extraidos = s.get("extraidos") or {}
    sobran = [f"{k}=«{extraidos[k]}»" for k in c.get("claves") or [] if k in extraidos]
    return _ok(not sobran, f"Se ha inventado {', '.join(sobran)}: no está en el texto.")


def _elementos(s: dict[str, Any], c: dict[str, Any]) -> list[Any]:
    lista = s.get(str(c.get("campo") or "")) or []
    tipo = c.get("tipo_elemento")
    if tipo:
        lista = [e for e in lista if isinstance(e, dict) and e.get("tipo") == tipo]
    return list(lista)


def _c_cuantos(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    n = len(_elementos(s, c))
    minimo, maximo = c.get("min"), c.get("max")
    ok = (minimo is None or n >= int(minimo)) and (maximo is None or n <= int(maximo))
    rango = (
        f"entre {minimo} y {maximo}"
        if minimo is not None and maximo is not None
        else (f"al menos {minimo}" if minimo is not None else f"como mucho {maximo}")
    )
    return _ok(ok, f"{c.get('campo')}: {n}, y debían ser {rango}.")


def _c_elementos_contienen(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    elementos = [
        _plano(" ".join(str(v) for v in e.values()) if isinstance(e, dict) else e)
        for e in _elementos(s, c)
    ]
    if c.get("todas"):
        malos = [
            e[:60]
            for e in elementos
            for v in c.get("valores") or []
            if not any(a in e for a in _alternativas(v))
        ]
        return _ok(bool(elementos) and not malos, f"Sin «{c.get('valores')}»: {malos}.")
    faltan = [
        v
        for v in c.get("valores") or []
        if not any(any(a in e for a in _alternativas(v)) for e in elementos)
    ]
    return _ok(not faltan, f"Ningún elemento de «{c.get('campo')}» habla de {faltan}.")


def _c_compromiso(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    quien = _alternativas(c.get("quien") or "") if c.get("quien") else []
    que = _alternativas(c.get("texto") or "")
    cuando = str(c.get("cuando") or "")
    candidatos = []
    for e in s.get("compromisos") or []:
        texto = _plano(f"{e.get('texto') or ''} {e.get('cita') or ''}")
        if not any(a in texto for a in que):
            continue
        if quien and not any(a in _plano(e.get("quien")) for a in quien):
            candidatos.append(f"«{e.get('texto')}» con dueño «{e.get('quien')}»")
            continue
        if cuando and not str(e.get("cuando") or "").startswith(cuando):
            candidatos.append(f"«{e.get('texto')}» para «{e.get('cuando') or 'sin fecha'}»")
            continue
        return _ok(True)
    detalle = f" Salió {'; '.join(candidatos)}." if candidatos else ""
    return _ok(
        False,
        f"Falta el compromiso de {c.get('quien') or 'quien registra'} sobre «{c.get('texto')}»"
        + (f" para el {cuando}" if cuando else "")
        + "."
        + detalle,
    )


def _c_ningun_compromiso(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    que = _alternativas(c.get("texto") or "")
    sobran = [
        str(e.get("texto"))
        for e in s.get("compromisos") or []
        if any(a in _plano(f"{e.get('texto') or ''} {e.get('cita') or ''}") for a in que)
    ]
    return _ok(not sobran, f"Propone como compromiso algo que nadie prometió: {sobran}.")


def _c_citas_literales(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    malas = [str(e.get("texto")) for e in s.get("compromisos") or [] if not e.get("cita_literal")]
    return _ok(not malas, f"Citas que no están en la transcripción: {malas}.")


def _c_cuantas(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    n, pedidas = len(s.get("variantes") or []), int(s.get("pedidas") or 0)
    return _ok(n == pedidas, f"Se pidieron {pedidas} distintas y salen {n}.")


def _c_marcadores(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    perdidos = s.get("marcadores_perdidos") or []
    return _ok(not perdidos, f"Variantes que pierden un marcador: {perdidos}.")


def _c_sin_afirmaciones_nuevas(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    nuevas = s.get("afirmaciones_nuevas") or []
    return _ok(not nuevas, f"Añaden afirmaciones que la base no hace: {nuevas}.")


def _c_longitud_max(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    tope = int(c.get("valor") or 0)
    largas = [
        len(str(v)) for v in s.get(str(c.get("campo") or "variantes")) or [] if len(str(v)) > tope
    ]
    return _ok(not largas, f"Pasan de {tope} caracteres: {largas}.")


def _c_concluyente(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    return _ok(bool(s.get("concluyente")), f"Confianza {s.get('confianza')}: no concluyente.")


def _c_argumentos(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    """Cada argumento dice lo pedido. «asunto|cuerpo» vale en cualquiera de los dos:
    una nota con el dato en el cuerpo y un asunto que lo titula es una buena nota."""
    argumentos = s.get("argumentos") or {}
    malos = []
    for claves, v in (c.get("valores") or {}).items():
        texto = _plano(" ".join(str(argumentos.get(k) or "") for k in str(claves).split("|")))
        if not any(a in texto for a in _alternativas(v)):
            malos.append(", ".join(f"{k}=«{argumentos.get(k)}»" for k in str(claves).split("|")))
    return _ok(not malos, f"Argumentos que no dicen lo pedido: {malos}.")


def _c_herramientas_de_la_lista(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    ajenas = s.get("herramientas_ajenas") or []
    return _ok(not ajenas, f"Pide herramientas que el agente no tiene: {ajenas}.")


def _c_usa_herramienta(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    usadas = s.get("herramientas") or []
    return _ok(c.get("valor") in usadas, f"No usa «{c.get('valor')}» (usa {usadas}).")


def _c_plan_valido(c: dict[str, Any], s: dict[str, Any], **_: Any) -> dict[str, Any]:
    problemas = s.get("problemas") or []
    return _ok(not problemas, "Plan no ejecutable: " + " ".join(problemas))


def _c_juez(
    c: dict[str, Any],
    s: dict[str, Any],
    *,
    juez: Callable[..., dict[str, Any]] | None = None,
    entrada: Any = None,
) -> dict[str, Any]:
    if juez is None:
        return {**_ok(False, "No hay juez conectado: no se puede evaluar."), "juez": True}
    veredicto = juez(pregunta=str(c.get("pregunta") or ""), salida=s, entrada=entrada)
    ok = bool(veredicto.get("si")) == bool(c.get("esperado", True))
    return {
        **_ok(ok, f"Según el juez: {veredicto.get('porque') or 'sin motivo'}"),
        "juez": True,
        "coste": veredicto.get("coste", 0),
    }


COMPROBACIONES: dict[str, Callable[..., dict[str, Any]]] = {
    "contiene": _c_contiene,
    "no_contiene": _c_no_contiene,
    "igual": _c_igual,
    "en": _c_en,
    "numero": _c_numero,
    "grupos": _c_grupos,
    "cita": _c_cita,
    "citas_validas": _c_citas_validas,
    "no_sabe": _c_no_sabe,
    "campos": _c_campos,
    "ausentes": _c_ausentes,
    "cuantos": _c_cuantos,
    "elementos_contienen": _c_elementos_contienen,
    "compromiso": _c_compromiso,
    "ningun_compromiso": _c_ningun_compromiso,
    "citas_literales": _c_citas_literales,
    "cuantas": _c_cuantas,
    "marcadores": _c_marcadores,
    "sin_afirmaciones_nuevas": _c_sin_afirmaciones_nuevas,
    "longitud_max": _c_longitud_max,
    "concluyente": _c_concluyente,
    "argumentos": _c_argumentos,
    "herramientas_de_la_lista": _c_herramientas_de_la_lista,
    "usa_herramienta": _c_usa_herramienta,
    "plan_valido": _c_plan_valido,
    "juez": _c_juez,
}


def comprobar(
    criterios: list[dict[str, Any]],
    salida: dict[str, Any],
    *,
    entrada: Any = None,
    juez: Callable[..., dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Cada criterio con su resultado. Uno desconocido NO se da por cumplido."""
    resultado = []
    for criterio in criterios:
        tipo = str(criterio.get("tipo") or "")
        fn = COMPROBACIONES.get(tipo)
        if fn is None:
            r = _ok(False, f"Criterio «{tipo}» desconocido: no se puede evaluar.")
        else:
            try:
                r = fn(criterio, salida, juez=juez, entrada=entrada)
            except Exception as exc:  # noqa: BLE001 — un criterio roto es un fallo, no un acierto
                r = _ok(False, f"No se pudo comprobar: {type(exc).__name__}: {str(exc)[:200]}")
        resultado.append({"tipo": tipo, "juez": tipo == "juez", **r})
    return resultado


# ── Cada función, por su puerto ───────────────────────────────────────────
#
# Cada ejecutor llama al puerto que la función real tiene registrado, con el
# modelo que el enrutador elige para su uso, y trata lo que vuelve con las
# mismas funciones que ella. Devuelve la salida normalizada y lo que gastó.


def _huella(*partes: Any) -> str:
    crudo = "\n".join(str(p) for p in partes)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:12]


def _fuente(fn: Any) -> str:
    try:
        return inspect.getsource(fn)
    except (OSError, TypeError):
        return getattr(fn, "__qualname__", repr(fn))


def _puerto(funcion: str) -> Any:
    """El puerto que la función real usa. `None` si no hay ninguno conectado."""
    from services.intelligence import (
        acciones_asistente,
        agentes,
        conversacion,
        extraccion,
        generacion,
        rag,
        reuniones,
        variantes_copy,
    )

    return {
        "asistente": lambda: rag._respondedor,
        "consulta_datos": lambda: rag._traductor,
        "resumen_caso": lambda: generacion._generador,
        "resumen_conversacion": lambda: conversacion._resumidor,
        "extraccion": lambda: extraccion._extractor,
        "compromisos_reunion": lambda: reuniones._resumidor,
        "variantes_copy": lambda: variantes_copy._redactor,
        "clasificacion": lambda: conversacion._clasificador,
        "acciones_asistente": lambda: acciones_asistente._proponedor,
        "plan_agente": lambda: agentes._planificador,
    }[funcion]()


def _plantilla_caso(uow: UnidadDeTrabajo) -> dict[str, Any]:
    """La plantilla «resumen_caso» que usaría el tenant, **sin guardarla**.

    La vigente del tenant si la tiene; si no, la de serie, que es la que se le
    guardaría la primera vez. Evaluar no da de alta nada en las plantillas.
    """
    from services.intelligence import generacion
    from services.intelligence.plantillas_de_serie import de_serie

    vigente = generacion._vigente(uow.db, uow.tenant_id, "resumen_caso")
    if vigente is not None:
        return {
            "sistema": vigente.sistema,
            "cuerpo": vigente.cuerpo,
            "version": f"v{vigente.version}",
            "idioma": vigente.idioma_defecto,
        }
    base = de_serie("resumen_caso") or {}
    return {
        "sistema": base.get("sistema", ""),
        "cuerpo": base.get("cuerpo", ""),
        "version": "serie",
        "idioma": "",
    }


def version_prompt(uow: UnidadDeTrabajo, funcion: str) -> str:
    """La versión del prompt de una función: huella del puerto (+ plantilla)."""
    puerto = _puerto(funcion)
    if funcion == "resumen_caso":
        p = _plantilla_caso(uow)
        return _huella(_fuente(puerto), p["sistema"], p["cuerpo"])
    return _huella(_fuente(puerto))


def _citas(texto: str) -> set[int]:
    from services.intelligence.rag import RE_CITA

    return {
        int(n)
        for grupo in RE_CITA.findall(texto)
        for n in re.split(r"[,;\s]+", grupo)
        if n.isdigit()
    }


def _ex_asistente(llamar: Callable[..., dict[str, Any]], e: dict[str, Any], uow: Any) -> dict:
    numerados = [
        {
            "n": i + 1,
            "fuente": str(f.get("fuente") or ""),
            "id": str(f.get("id") or ""),
            "texto": f.get("texto"),
        }
        for i, f in enumerate(e.get("fragmentos") or [])
    ]
    r = llamar(pregunta=str(e.get("pregunta") or ""), fragmentos=numerados)
    texto = str(r.get("texto") or "")
    citados = _citas(texto)
    validos = {f["n"] for f in numerados}
    return {
        **r,
        "texto": texto,
        # Lo mismo que decide `rag.responder`: o lo dice el puerto, o no hay texto.
        "sin_respuesta": bool(r.get("sin_respuesta")) or not texto.strip(),
        "citas": sorted(citados & validos),
        "citas_inventadas": sorted(citados - validos),
    }


def _comparar(real: Any, operador: str, valor: Any) -> bool:
    if operador == "vacio":
        return real in (None, "")
    if operador == "no_vacio":
        return real not in (None, "")
    if operador == "en":
        lista = valor if isinstance(valor, list) else str(valor).split(",")
        return _plano(real) in {_plano(v) for v in lista}
    a, b = _numero(real), _numero(valor)
    if a is None or b is None:
        a, b = _plano(real), _plano(valor)  # type: ignore[assignment]
    if operador == "=":
        return a == b
    if operador == "!=":
        return a != b
    if real in (None, ""):
        return False
    return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}.get(operador, False)  # type: ignore[operator]


def ejecutar_plan(
    plan: dict[str, Any], ficha: dict[str, Any], filas: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """El plan sobre unas filas, con la gramática del listado real.

    Como el listado: lo que filtra por defecto se aplica salvo que el plan
    filtre ese campo; un `=` vacío lo quita. Y el agregado es el mismo
    `consulta_natural.agregar` que usa la consulta de verdad.
    """
    from services.intelligence.consulta_natural import agregar

    filtros = [f for f in plan.get("filtros") or [] if isinstance(f, dict)]
    tocados = {str(f.get("campo")) for f in filtros}
    for campo, valor in (ficha.get("filtra_por_defecto") or {}).items():
        if campo not in tocados:
            filtros.append({"campo": campo, "operador": "=", "valor": valor})
    activos = [
        f
        for f in filtros
        if not (str(f.get("operador") or "=") == "=" and f.get("valor") in ("", None))
    ]
    quedan = [
        fila
        for fila in filas
        if all(
            _comparar(fila.get(str(f.get("campo"))), str(f.get("operador") or "="), f.get("valor"))
            for f in activos
        )
    ]
    return agregar(quedan, plan)


def _ex_consulta(llamar: Callable[..., dict[str, Any]], e: dict[str, Any], uow: Any) -> dict:
    from services.intelligence.consulta_natural import normalizar, validar_plan

    modelo_datos = dict(e.get("modelo_datos") or {})
    r = llamar(pregunta=str(e.get("pregunta") or ""), modelo_datos=modelo_datos)
    plan = normalizar(dict(r.get("plan") or {}))
    objeto = str(plan.get("objeto") or "")
    ficha = next((o for o in modelo_datos.get("objetos") or [] if o.get("clave") == objeto), None)
    salida: dict[str, Any] = {
        **r,
        "plan": plan,
        "objeto": objeto,
        "interpretacion": r.get("interpretacion") or "",
    }
    if ficha is None:
        return {**salida, "problemas": [f"«{objeto}» no es ningún objeto que se pueda preguntar."]}
    campos = [str(c.get("nombre")) for c in ficha.get("campos") or []]
    problemas = validar_plan(plan, campos)
    if problemas:
        return {**salida, "problemas": problemas}
    agregados = ejecutar_plan(plan, ficha, list((e.get("filas") or {}).get(objeto) or []))
    funcion = str((plan.get("agregado") or {}).get("funcion") or "cuenta")
    if plan.get("agrupar_por"):
        valor = None
    elif agregados:
        valor = agregados[0]["valor"]
    else:
        valor = 0 if funcion == "cuenta" else None
    return {
        **salida,
        "problemas": [],
        "agregados": agregados,
        "valor": valor,
        "grupos": {str(g["grupo"]): g["valor"] for g in agregados if g.get("grupo") is not None},
    }


def _ex_resumen_caso(llamar: Callable[..., dict[str, Any]], e: dict[str, Any], uow: Any) -> dict:
    from crmcore.config import get_settings
    from crmcore.runtime import settings as rt

    p = _plantilla_caso(uow)
    prompt = (
        p["cuerpo"]
        .replace("{{asunto}}", str(e.get("asunto") or ""))
        .replace("{{ asunto }}", str(e.get("asunto") or ""))
    )
    # El idioma, como en `generacion.generar`: el de la plantilla o el del tenant.
    idioma = p["idioma"] or str(rt.efectivo("idioma", uow.db) or get_settings().idioma_defecto)
    r = llamar(
        sistema=p["sistema"], prompt=prompt, contexto=str(e.get("contexto") or ""), idioma=idioma
    )
    return {**r, "texto": str(r.get("texto") or "")}


def _ex_resumen_conversacion(
    llamar: Callable[..., dict[str, Any]], e: dict[str, Any], uow: Any
) -> dict:
    r = llamar(mensajes=list(e.get("mensajes") or []))
    return {**r, "texto": str(r.get("texto") or ""), "pendientes": list(r.get("pendientes") or [])}


def _ex_extraccion(llamar: Callable[..., dict[str, Any]], e: dict[str, Any], uow: Any) -> dict:
    """Con el mismo filtro que `extraccion.extraer`: pedido, citado, literal y confiado."""
    from services.intelligence.extraccion import _ia_confianza_extraccion, convertir

    texto = str(e.get("texto") or "")
    campos = list(e.get("campos") or [])
    r = llamar(texto=texto, campos=campos)
    tipos = {str(c.get("clave")): str(c.get("tipo") or "texto") for c in campos}
    minima = float(_ia_confianza_extraccion(uow.db))
    extraidos: dict[str, Any] = {}
    descartados: list[dict[str, str]] = []
    for crudo in r.get("campos") or []:
        if not isinstance(crudo, dict):
            continue
        clave = str(crudo.get("clave") or "")
        cita = str(crudo.get("cita") or "").strip()
        if clave not in tipos:
            descartados.append({"campo": clave, "porque": "no estaba entre los pedidos"})
        elif not cita:
            descartados.append({"campo": clave, "porque": "sin cita"})
        elif cita not in texto:
            descartados.append({"campo": clave, "porque": "la cita no aparece en el texto"})
        elif (_numero(crudo.get("confianza")) or 0) < minima:
            descartados.append({"campo": clave, "porque": f"confianza {crudo.get('confianza')}"})
        else:
            valor, se_pudo = convertir(crudo.get("valor"), tipos[clave])
            if not se_pudo:
                descartados.append(
                    {"campo": clave, "porque": f"«{crudo.get('valor')}» no se convierte"}
                )
                continue
            extraidos[clave] = (
                valor.isoformat()
                if hasattr(valor, "isoformat")
                else (float(valor) if isinstance(valor, Decimal) else valor)
            )
    return {**r, "extraidos": extraidos, "descartados": descartados}


def _ex_compromisos(llamar: Callable[..., dict[str, Any]], e: dict[str, Any], uow: Any) -> dict:
    """Con el mismo tratamiento que `reuniones.procesar`."""
    from services.intelligence import transcripcion as trs
    from services.intelligence.reuniones import SE_HACEN_TAREA, _normalizado

    texto = str(e.get("texto") or "")
    r = llamar(texto=texto, idioma=str(e.get("idioma") or "es"), tipos=list(trs.EXTRAIBLES))
    elementos = [x for x in r.get("elementos") or [] if isinstance(x, dict)]
    propuestas = trs.proponer_extraidos(elementos=elementos, confianza_transcripcion=1.0)
    normal = _normalizado(texto)
    todas = [
        {
            **p,
            "cita_literal": bool(p.get("cita")) and _normalizado(str(p.get("cita"))) in normal,
        }
        for p in propuestas.get("propuestas") or []
    ]
    return {
        **r,
        "resumen": str(r.get("resumen") or ""),
        "elementos": todas,
        "compromisos": [p for p in todas if p.get("tipo") in SE_HACEN_TAREA],
        "descartados": list(propuestas.get("descartados") or []),
    }


def _ex_variantes(llamar: Callable[..., dict[str, Any]], e: dict[str, Any], uow: Any) -> dict:
    """Con el mismo filtro que `variantes_copy.generar`: distintas y sin la base."""
    from services.intelligence import variantes as var
    from services.intelligence.variantes_copy import _marcadores_perdidos

    base = str(e.get("base") or "")
    cuantas = int(e.get("cuantas") or 3)
    r = llamar(
        base=base,
        objetivo=str(e.get("objetivo") or ""),
        canal=str(e.get("canal") or "email"),
        cuantas=cuantas,
        idioma=str(e.get("idioma") or "es"),
    )
    vistos = {base.strip().lower()}
    unicas: list[str] = []
    for t in (str(x).strip() for x in r.get("variantes") or []):
        if t and t.lower() not in vistos:
            vistos.add(t.lower())
            unicas.append(t)
    unicas = unicas[:cuantas]
    de_la_base = {_plano(a["texto"]) for a in var.marcar_afirmaciones(base)["afirmaciones"]}
    nuevas = [
        a["texto"]
        for t in unicas
        for a in var.marcar_afirmaciones(t)["afirmaciones"]
        if _plano(a["texto"]) not in de_la_base
    ]
    perdidos = [m["texto"] for t in unicas for m in _marcadores_perdidos(base, t)]
    return {
        **r,
        "variantes": unicas,
        "pedidas": cuantas,
        "afirmaciones_nuevas": nuevas,
        "marcadores_perdidos": perdidos,
    }


def _ex_clasificacion(llamar: Callable[..., dict[str, Any]], e: dict[str, Any], uow: Any) -> dict:
    """Con el mismo saneado que `conversacion.clasificar`."""
    from services.intelligence.conversacion import INTENCIONES, SENTIMIENTOS

    r = llamar(
        texto=str(e.get("texto") or ""),
        sentimientos=list(SENTIMIENTOS),
        intenciones=list(INTENCIONES),
    )
    sentimiento = str(r.get("sentimiento") or "neutro")
    intencion = str(r.get("intencion") or "otro")
    confianza = max(0.0, min(1.0, _numero(r.get("confianza")) or 0.0))
    return {
        **r,
        "sentimiento": sentimiento if sentimiento in SENTIMIENTOS else "neutro",
        "intencion": intencion if intencion in INTENCIONES else "otro",
        "confianza": confianza,
        # El umbral por defecto de `clasificar`.
        "concluyente": confianza >= _umbral_de_clasificar(),
    }


def _umbral_de_clasificar() -> float:
    """El umbral de confianza con el que `conversacion.clasificar` concluye.

    Se lee de su firma y no se copia: si alguien lo cambia allí, la evaluación
    mide con el mismo número que el producto.
    """
    from services.intelligence.conversacion import clasificar

    return float(inspect.signature(clasificar).parameters["umbral_confianza"].default)


def _ex_acciones(llamar: Callable[..., dict[str, Any]], e: dict[str, Any], uow: Any) -> dict:
    """Con el mismo filtro que `acciones_asistente.proponer`: de la lista y limpia."""
    from services.intelligence.acciones_asistente import ACCIONES, limpiar

    claves = [k for k in e.get("acciones") or list(ACCIONES) if k in ACCIONES]
    ofrecidas = [
        {"clave": k, "nombre": ACCIONES[k]["nombre"], "campos": ACCIONES[k]["campos"]}
        for k in claves
    ]
    r = llamar(
        pregunta=str(e.get("pregunta") or ""),
        respuesta=str(e.get("respuesta") or ""),
        acciones=ofrecidas,
    )
    clave = str(r.get("accion") or "")
    if clave not in claves:
        return {**r, "accion": None, "argumentos": {}, "faltan": [], "pedida": clave or None}
    argumentos, faltan = limpiar(clave, dict(r.get("argumentos") or {}))
    return {**r, "accion": clave, "argumentos": argumentos, "faltan": faltan}


def _ex_plan_agente(llamar: Callable[..., dict[str, Any]], e: dict[str, Any], uow: Any) -> dict:
    herramientas = list(e.get("herramientas") or [])
    r = llamar(
        objetivo=str(e.get("objetivo") or ""),
        contexto=dict(e.get("contexto") or {}),
        herramientas=herramientas,
    )
    nombres = {str(h.get("nombre")) for h in herramientas}
    usadas = [str(p.get("herramienta") or "") for p in r.get("pasos") or [] if isinstance(p, dict)]
    return {
        **r,
        "pasos": list(r.get("pasos") or []),
        "herramientas": usadas,
        "herramientas_ajenas": sorted({u for u in usadas if u not in nombres}),
    }


EJECUTORES: dict[str, Callable[..., dict[str, Any]]] = {
    "asistente": _ex_asistente,
    "consulta_datos": _ex_consulta,
    "resumen_caso": _ex_resumen_caso,
    "resumen_conversacion": _ex_resumen_conversacion,
    "extraccion": _ex_extraccion,
    "compromisos_reunion": _ex_compromisos,
    "variantes_copy": _ex_variantes,
    "clasificacion": _ex_clasificacion,
    "acciones_asistente": _ex_acciones,
    "plan_agente": _ex_plan_agente,
}


# ── El juez ───────────────────────────────────────────────────────────────

_SISTEMA_JUEZ = (
    "Eres un evaluador estricto de la salida de un asistente de CRM. Se te da la "
    "entrada original como contexto y el texto que produjo el asistente. Contesta "
    "a la pregunta sobre ese texto. Juzga los HECHOS —datos, cifras, fechas, "
    "nombres, estados y lo que queda pendiente—, no la redacción ni los rótulos "
    "con que el asistente ordena el texto. La PRIMERA línea es solo «SI» o «NO»; "
    "la segunda, en una frase, por qué. Si un hecho no está en la entrada, NO."
)


def _juez_para(uow: UnidadDeTrabajo, ejecucion_id: UUID | None) -> Callable[..., dict[str, Any]]:
    """El juez: un modelo al que se le pregunta lo que un programa no sabe medir."""
    import json

    from services.intelligence import enrutador, generacion

    def _juzgar(*, pregunta: str, salida: dict[str, Any], entrada: Any) -> dict[str, Any]:
        if generacion._generador is None:
            return {"si": False, "porque": "no hay puerto conectado para el juez"}
        elegido = enrutador.exigir_disponible(uow.db, uow.tenant_id, uso="clasificacion")
        texto = str(salida.get("texto") or salida.get("resumen") or "")
        r = generacion._generador(
            proveedor=elegido["elegido"],
            modelo=elegido.get("modelo", ""),
            sistema=_SISTEMA_JUEZ,
            prompt=f"Pregunta: {pregunta}\n\nTexto del asistente:\n{texto}",
            contexto=json.dumps(entrada, ensure_ascii=False)[:8000],
            idioma="es",
            opt_out=bool(elegido.get("opt_out")),
        )
        coste = _anotar(uow, elegido, r, ejecucion_id, latencia_ms=0)
        lineas = [x.strip() for x in str(r.get("texto") or "").strip().splitlines() if x.strip()]
        primera = _plano(lineas[0] if lineas else "")
        return {
            "si": primera.startswith("si"),
            "porque": " ".join(lineas[1:])[:400] or (lineas[0] if lineas else ""),
            "coste": float(coste),
        }

    return _juzgar


# ── Ejecutar ──────────────────────────────────────────────────────────────


def _anotar(
    uow: UnidadDeTrabajo,
    elegido: dict[str, Any],
    r: dict[str, Any],
    ejecucion_id: UUID | None,
    *,
    latencia_ms: int,
) -> Decimal:
    """Cada llamada de la evaluación se apunta como cualquier otra: cuesta dinero."""
    from services.intelligence import enrutador, uso

    proveedor = str(elegido.get("elegido") or "")
    entrada, salida = int(r.get("tokens_entrada") or 0), int(r.get("tokens_salida") or 0)
    coste = enrutador.coste_estimado(
        uow.db, proveedor=proveedor, tokens_entrada=entrada, tokens_salida=salida
    )
    llamada = uso.anotar(
        uow,
        tarea="evaluacion",
        proveedor=proveedor,
        modelo=str(r.get("modelo") or elegido.get("modelo") or ""),
        region=str(elegido.get("region") or ""),
        objeto="evaluacion_ia",
        objeto_id=ejecucion_id,
        tokens_entrada=entrada,
        tokens_salida=salida,
        coste=coste,
        duracion_ms=latencia_ms,
        resultado="pendiente",
        opt_out=bool(elegido.get("opt_out")),
    )
    enrutador.anotar_gasto(
        uow,
        proveedor=proveedor,
        tokens_entrada=llamada.tokens_entrada,
        tokens_salida=llamada.tokens_salida,
        coste=llamada.coste,
    )
    return Decimal(coste or 0)


def _recortar(valor: Any) -> Any:
    """La salida, con los textos largos recortados, para guardarla."""
    import json

    limpio = {
        k: v
        for k, v in (valor or {}).items()
        if k not in ("tokens_entrada", "tokens_salida", "llamadas", "avisos")
    }
    crudo = json.dumps(limpio, ensure_ascii=False, default=str)
    if len(crudo) <= _TOPE_SALIDA:
        return json.loads(crudo)
    return {"recortada": True, "inicio": crudo[:_TOPE_SALIDA]}


def evaluar_caso(
    uow: UnidadDeTrabajo,
    caso: CasoEvaluacionIA | dict[str, Any],
    *,
    ejecucion_id: UUID | None = None,
    juez: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Pasa un caso por el puerto real de su función y lo comprueba.

    Un fallo del proveedor es un fallo del caso, con su motivo: si el modelo no
    contesta, la función tampoco le habría contestado al usuario.
    """
    from services.intelligence import enrutador

    d = caso_a_dict(caso) if isinstance(caso, CasoEvaluacionIA) else dict(caso)
    funcion = str(d["funcion"])
    base = {
        "caso_clave": d["clave"],
        "caso_nombre": d.get("nombre") or d["clave"],
        "funcion": funcion,
        "modelo": "",
        "version_prompt": "",
        "tokens_entrada": 0,
        "tokens_salida": 0,
        "coste": Decimal(0),
        "latencia_ms": 0,
        "salida": {},
        "error": "",
    }
    puerto = _puerto(funcion)
    if puerto is None:
        return {
            **base,
            "acierto": False,
            "criterios": [],
            "porque": "No hay puerto de IA conectado para esta función.",
            "error": "sin_puerto",
        }
    base["version_prompt"] = version_prompt(uow, funcion)
    try:
        elegido = enrutador.exigir_disponible(uow.db, uow.tenant_id, uso=FUNCIONES[funcion]["uso"])
    except Exception as exc:  # noqa: BLE001 — se dice por qué no se pudo
        return {
            **base,
            "acierto": False,
            "criterios": [],
            "porque": f"No hay modelo disponible: {exc}",
            "error": type(exc).__name__,
        }

    def _llamar(**kw: Any) -> dict[str, Any]:
        return puerto(
            proveedor=elegido["elegido"],
            modelo=elegido.get("modelo", ""),
            opt_out=bool(elegido.get("opt_out")),
            **kw,
        )

    inicio = _ahora()
    try:
        salida = EJECUTORES[funcion](_llamar, dict(d.get("entrada") or {}), uow)
    except Exception as exc:  # noqa: BLE001 — un caso que revienta es un caso fallado
        latencia = int((_ahora() - inicio).total_seconds() * 1000)
        mensaje = str(getattr(exc, "mensaje", "") or exc)[:300]
        detalle = getattr(exc, "detalle", None)
        if isinstance(detalle, dict) and detalle.get("dijo"):
            mensaje += f" — {str(detalle['dijo'])[:200]}"
        return {
            **base,
            "modelo": str(elegido.get("modelo") or ""),
            "latencia_ms": latencia,
            "acierto": False,
            "criterios": [],
            "porque": f"La llamada falló: {mensaje}",
            "error": type(exc).__name__,
        }
    latencia = int((_ahora() - inicio).total_seconds() * 1000)
    coste = _anotar(uow, elegido, salida, ejecucion_id, latencia_ms=latencia)
    criterios = comprobar(
        list(d.get("criterios") or []), salida, entrada=d.get("entrada"), juez=juez
    )
    coste += sum((Decimal(str(c.pop("coste", 0) or 0)) for c in criterios), Decimal(0))
    fallados = [c for c in criterios if not c["ok"]]
    return {
        **base,
        "modelo": str(salida.get("modelo") or elegido.get("modelo") or ""),
        "tokens_entrada": int(salida.get("tokens_entrada") or 0),
        "tokens_salida": int(salida.get("tokens_salida") or 0),
        "coste": coste,
        "latencia_ms": latencia,
        "salida": _recortar(salida),
        "criterios": criterios,
        # Sin criterios no hay acierto: lo que no se puede evaluar no se cumple.
        "acierto": bool(criterios) and not fallados,
        "porque": " ".join(("[juez] " if c["juez"] else "") + c["porque"] for c in fallados)
        or ("" if criterios else "El caso no tiene criterios."),
    }


def _asegurar_puertos() -> None:
    """El worker es otro proceso y no pasa por el arranque de la API."""
    from services.intelligence import rag

    if rag._respondedor is None:
        from services.intelligence.puerto import conectar

        conectar()


def en_curso(db: Session, tenant_id: UUID) -> EjecucionEvaluacionIA | None:
    return (
        db.execute(
            select(EjecucionEvaluacionIA)
            .where(
                EjecucionEvaluacionIA.tenant_id == tenant_id,
                EjecucionEvaluacionIA.estado == "en_curso",
            )
            .order_by(EjecucionEvaluacionIA.empezada_at.desc())
        )
        .scalars()
        .first()
    )


def preparar(
    uow: UnidadDeTrabajo,
    *,
    origen: str = "manual",
    pedida_por: UUID | None = None,
    funciones: list[str] | None = None,
) -> EjecucionEvaluacionIA:
    """Abre una ejecución con los casos fijados. No llama a ningún modelo."""
    from services.intelligence import enrutador

    abierta = en_curso(uow.db, uow.tenant_id)
    if abierta is not None:
        # Una caducada (el worker murió a mitad) no bloquea para siempre.
        limite = timedelta(hours=int(_ajuste("ia_evaluacion_caducidad_horas", uow.db)))
        if (
            _ahora()
            - abierta.empezada_at.replace(tzinfo=abierta.empezada_at.tzinfo or timezone.utc)
            < limite
        ):
            raise Conflicto(
                "Ya hay una evaluación en curso: espera a que termine.",
                error_code="evaluacion.en_curso",
                detalle={"ejecucion_id": str(abierta.id)},
            )
        abierta.estado = "fallida"
        abierta.error = "Caducada: no terminó en el plazo."
        abierta.terminada_at = _ahora()
    malas = sorted(set(funciones or []) - set(FUNCIONES))
    if malas:
        raise ErrorValidacion(
            f"Funciones no evaluables: {', '.join(malas)}.",
            error_code="evaluacion.funcion",
            detalle={"validas": list(FUNCIONES)},
        )
    asegurar_banco(uow)
    consulta = select(CasoEvaluacionIA).where(
        CasoEvaluacionIA.tenant_id == uow.tenant_id, CasoEvaluacionIA.activo.is_(True)
    )
    if funciones:
        consulta = consulta.where(CasoEvaluacionIA.funcion.in_(funciones))
    claves = [
        c.clave
        for c in uow.db.execute(
            consulta.order_by(CasoEvaluacionIA.funcion, CasoEvaluacionIA.clave)
        ).scalars()
    ]
    if not claves:
        raise ErrorValidacion(
            "No hay ningún caso activo que evaluar.", error_code="evaluacion.sin_casos"
        )
    usos = sorted({FUNCIONES[f]["uso"] for f in FUNCIONES})
    modelos: dict[str, str] = {}
    proveedor = ""
    for u in usos:
        eleccion = enrutador.elegir(uow.db, uow.tenant_id, uso=u)
        if eleccion.get("puede_llamar"):
            modelos[u] = str(eleccion.get("modelo") or "")
            proveedor = proveedor or str(eleccion.get("elegido") or "")
    _asegurar_puertos()
    fila = EjecucionEvaluacionIA(
        tenant_id=uow.tenant_id,
        origen=origen,
        pedida_por=pedida_por,
        casos_previstos=claves,
        proveedor=proveedor,
        modelos=modelos,
        versiones_prompt={f: version_prompt(uow, f) for f in FUNCIONES},
        umbral=float(_ajuste("ia_evaluacion_umbral", uow.db)),
        empezada_at=_ahora(),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def avanzar(uow: UnidadDeTrabajo, ejecucion: EjecucionEvaluacionIA, cuantos: int) -> int:
    """Evalúa los siguientes `cuantos` casos pendientes. Devuelve cuántos ha hecho."""
    hechos = set(
        uow.db.execute(
            select(ResultadoEvaluacionIA.caso_clave).where(
                ResultadoEvaluacionIA.tenant_id == uow.tenant_id,
                ResultadoEvaluacionIA.ejecucion_id == ejecucion.id,
            )
        ).scalars()
    )
    pendientes = [c for c in ejecucion.casos_previstos or [] if c not in hechos][: max(1, cuantos)]
    if not pendientes:
        return 0
    filas = {
        c.clave: c
        for c in uow.db.execute(
            select(CasoEvaluacionIA).where(
                CasoEvaluacionIA.tenant_id == uow.tenant_id,
                CasoEvaluacionIA.clave.in_(pendientes),
            )
        ).scalars()
    }
    _asegurar_puertos()
    juez = _juez_para(uow, ejecucion.id)
    for clave in pendientes:
        caso = filas.get(clave)
        if caso is None:
            r = {
                "caso_clave": clave,
                "caso_nombre": clave,
                "funcion": "",
                "acierto": False,
                "criterios": [],
                "porque": "El caso ya no existe en el banco.",
                "error": "caso_borrado",
            }
        else:
            r = evaluar_caso(uow, caso, ejecucion_id=ejecucion.id, juez=juez)
        uow.db.add(
            ResultadoEvaluacionIA(
                tenant_id=uow.tenant_id,
                ejecucion_id=ejecucion.id,
                caso_clave=r["caso_clave"],
                caso_nombre=str(r.get("caso_nombre") or "")[:200],
                funcion=str(r.get("funcion") or ""),
                acierto=bool(r["acierto"]),
                criterios=list(r.get("criterios") or []),
                porque=str(r.get("porque") or ""),
                salida=dict(r.get("salida") or {}),
                modelo=str(r.get("modelo") or "")[:120],
                version_prompt=str(r.get("version_prompt") or ""),
                tokens_entrada=int(r.get("tokens_entrada") or 0),
                tokens_salida=int(r.get("tokens_salida") or 0),
                coste=Decimal(str(r.get("coste") or 0)),
                latencia_ms=int(r.get("latencia_ms") or 0),
                error=str(r.get("error") or ""),
            )
        )
        uow.db.flush()
    return len(pendientes)


def cerrar(uow: UnidadDeTrabajo, ejecucion: EjecucionEvaluacionIA) -> dict[str, Any]:
    """Agrega los resultados, guarda el acierto por función y avisa si baja."""
    resultados = (
        uow.db.execute(
            select(ResultadoEvaluacionIA).where(
                ResultadoEvaluacionIA.tenant_id == uow.tenant_id,
                ResultadoEvaluacionIA.ejecucion_id == ejecucion.id,
            )
        )
        .scalars()
        .all()
    )
    por_funcion: dict[str, dict[str, Any]] = {}
    for r in resultados:
        f = por_funcion.setdefault(
            r.funcion,
            {"casos": 0, "aciertos": 0, "coste": Decimal(0), "latencias": [], "con_juez": 0},
        )
        f["casos"] += 1
        f["aciertos"] += int(bool(r.acierto))
        f["coste"] += Decimal(r.coste or 0)
        f["latencias"].append(int(r.latencia_ms or 0))
        f["con_juez"] += int(any(c.get("juez") for c in r.criterios or []))
    umbral = float(
        ejecucion.umbral
        if ejecucion.umbral is not None
        else _ajuste("ia_evaluacion_umbral", uow.db)
    )
    resumen: dict[str, Any] = {}
    bajo: list[dict[str, Any]] = []
    for funcion, f in sorted(por_funcion.items()):
        acierto = round(f["aciertos"] / f["casos"], 4) if f["casos"] else None
        resumen[funcion] = {
            "nombre": FUNCIONES.get(funcion, {}).get("nombre", funcion),
            "casos": f["casos"],
            "aciertos": f["aciertos"],
            "acierto": acierto,
            "coste": float(f["coste"]),
            "latencia_media_ms": int(sum(f["latencias"]) / len(f["latencias"]))
            if f["latencias"]
            else 0,
            "casos_con_juez": f["con_juez"],
        }
        if acierto is not None and acierto < umbral:
            bajo.append({"funcion": funcion, "acierto": acierto, "casos": f["casos"]})
    total = len(resultados)
    aciertos = sum(1 for r in resultados if r.acierto)
    latencias = [int(r.latencia_ms or 0) for r in resultados]
    ejecucion.casos = total
    ejecucion.aciertos = aciertos
    ejecucion.acierto = round(aciertos / total, 4) if total else None
    ejecucion.por_funcion = resumen
    ejecucion.coste = sum((Decimal(r.coste or 0) for r in resultados), Decimal(0))
    ejecucion.latencia_media_ms = int(sum(latencias) / len(latencias)) if latencias else 0
    ejecucion.bajo_umbral = bajo
    ejecucion.estado = "terminada"
    ejecucion.terminada_at = _ahora()
    if bajo:
        ejecucion.aviso = _avisar(uow, ejecucion, bajo, umbral)
    uow.db.flush()
    logger.info(
        "evaluacion_ia.terminada",
        ejecucion=str(ejecucion.id),
        acierto=float(ejecucion.acierto or 0),
        bajo_umbral=len(bajo),
    )
    return ejecucion_a_dict(ejecucion)


def _avisar(
    uow: UnidadDeTrabajo,
    ejecucion: EjecucionEvaluacionIA,
    bajo: list[dict[str, Any]],
    umbral: float,
) -> str:
    """Por el sistema de avisos de la casa: el evento que el servicio de
    identidad convierte en notificación para quien se le diga.

    A quién: quien pidió la evaluación y la lista de `ia_evaluacion_avisar_a`.
    Una programada sin nadie en esa lista deja el evento en el bus y el aviso
    escrito en la ejecución —se ve en la pantalla—, y no se le inventa un
    destinatario.
    """
    partes = [
        f"{FUNCIONES.get(b['funcion'], {}).get('nombre', b['funcion'])}: "
        f"{round(float(b['acierto']) * 100)} % en {b['casos']} casos"
        for b in bajo
    ]
    texto = (
        f"La evaluación de la IA ha bajado del {round(umbral * 100)} % en "
        f"{len(bajo)} función(es): " + "; ".join(partes) + "."
    )
    destinatarios: list[str] = []
    if ejecucion.pedida_por:
        destinatarios.append(str(ejecucion.pedida_por))
    for crudo in str(_ajuste("ia_evaluacion_avisar_a", uow.db) or "").split(","):
        crudo = crudo.strip()
        if not crudo:
            continue
        try:
            destinatarios.append(str(UUID(crudo)))
        except ValueError:
            logger.warning("evaluacion_ia.destinatario_invalido", valor=crudo[:60])
    uow.emitir(
        "automatizacion.aviso",
        subject=("evaluacion_ia", ejecucion.id),
        data={
            "titulo": "La IA ha bajado del umbral de acierto",
            "cuerpo": texto,
            "objeto_tipo": "evaluacion_ia",
            "objeto_id": str(ejecucion.id),
            "menciones": list(dict.fromkeys(destinatarios)),
        },
        dedup_key=f"evaluacion_ia:{uow.tenant_id}:{ejecucion.id}",
    )
    return texto


def evaluar(
    uow: UnidadDeTrabajo,
    *,
    origen: str = "manual",
    pedida_por: UUID | None = None,
    funciones: list[str] | None = None,
) -> dict[str, Any]:
    """Todo de una vez, en esta unidad de trabajo. Para pruebas y para la consola."""
    ejecucion = preparar(uow, origen=origen, pedida_por=pedida_por, funciones=funciones)
    while avanzar(uow, ejecucion, 50):
        pass
    return cerrar(uow, ejecucion)


# ── Lo que se enseña ──────────────────────────────────────────────────────


def ejecucion_a_dict(fila: EjecucionEvaluacionIA) -> dict[str, Any]:
    return {
        "id": str(fila.id),
        "estado": fila.estado,
        "origen": fila.origen,
        "empezada_at": fila.empezada_at.isoformat() if fila.empezada_at else None,
        "terminada_at": fila.terminada_at.isoformat() if fila.terminada_at else None,
        "proveedor": fila.proveedor,
        "modelos": fila.modelos or {},
        "versiones_prompt": fila.versiones_prompt or {},
        "previstos": len(fila.casos_previstos or []),
        "casos": fila.casos,
        "aciertos": fila.aciertos,
        "acierto": float(fila.acierto) if fila.acierto is not None else None,
        "por_funcion": fila.por_funcion or {},
        "coste": float(fila.coste or 0),
        "latencia_media_ms": fila.latencia_media_ms,
        "umbral": float(fila.umbral) if fila.umbral is not None else None,
        "bajo_umbral": fila.bajo_umbral or [],
        "aviso": fila.aviso,
        "error": fila.error,
    }


def resultado_a_dict(fila: ResultadoEvaluacionIA) -> dict[str, Any]:
    return {
        "caso_clave": fila.caso_clave,
        "caso_nombre": fila.caso_nombre,
        "funcion": fila.funcion,
        "acierto": fila.acierto,
        "criterios": fila.criterios or [],
        "porque": fila.porque,
        "salida": fila.salida or {},
        "modelo": fila.modelo,
        "version_prompt": fila.version_prompt,
        "coste": float(fila.coste or 0),
        "latencia_ms": fila.latencia_ms,
        "error": fila.error,
    }


def ejecuciones(db: Session, tenant_id: UUID, *, limite: int) -> list[dict[str, Any]]:
    filas = (
        db.execute(
            select(EjecucionEvaluacionIA)
            .where(EjecucionEvaluacionIA.tenant_id == tenant_id)
            .order_by(EjecucionEvaluacionIA.empezada_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return [ejecucion_a_dict(f) for f in filas]


def detalle(db: Session, tenant_id: UUID, ejecucion_id: UUID) -> dict[str, Any]:
    fila = db.execute(
        select(EjecucionEvaluacionIA).where(
            EjecucionEvaluacionIA.tenant_id == tenant_id, EjecucionEvaluacionIA.id == ejecucion_id
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("No hay esa evaluación.", error_code="evaluacion.no_existe")
    resultados = (
        db.execute(
            select(ResultadoEvaluacionIA)
            .where(
                ResultadoEvaluacionIA.tenant_id == tenant_id,
                ResultadoEvaluacionIA.ejecucion_id == ejecucion_id,
            )
            .order_by(
                ResultadoEvaluacionIA.acierto,
                ResultadoEvaluacionIA.funcion,
                ResultadoEvaluacionIA.caso_clave,
            )
        )
        .scalars()
        .all()
    )
    return {
        **ejecucion_a_dict(fila),
        "hechos": len(resultados),
        "resultados": [resultado_a_dict(r) for r in resultados],
    }


def panel(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Lo que pinta la pantalla: acierto por función, última, tendencia y fallos."""
    historial = ejecuciones(db, tenant_id, limite=int(_ajuste("ia_evaluacion_historial", db)))
    terminadas = [e for e in historial if e["estado"] == "terminada"]
    ultima = terminadas[0] if terminadas else None
    corriendo = next((e for e in historial if e["estado"] == "en_curso"), None)
    if corriendo is not None:
        # Cuántos lleva, para que el botón diga por dónde va desde que se abre.
        corriendo["hechos"] = int(
            db.execute(
                select(func.count())
                .select_from(ResultadoEvaluacionIA)
                .where(
                    ResultadoEvaluacionIA.tenant_id == tenant_id,
                    ResultadoEvaluacionIA.ejecucion_id == UUID(corriendo["id"]),
                )
            ).scalar_one()
        )
    tendencia = [
        {
            "fecha": e["empezada_at"],
            "acierto": e["acierto"],
            **{f: (v or {}).get("acierto") for f, v in (e["por_funcion"] or {}).items()},
        }
        for e in reversed(terminadas)
    ]
    funciones = []
    for clave, ficha in FUNCIONES.items():
        actual = (ultima or {}).get("por_funcion", {}).get(clave)
        previa = next(
            (e["por_funcion"].get(clave) for e in terminadas[1:] if e["por_funcion"].get(clave)),
            None,
        )
        funciones.append(
            {
                "funcion": clave,
                "nombre": ficha["nombre"],
                "uso": ficha["uso"],
                "casos": (actual or {}).get("casos", 0),
                "aciertos": (actual or {}).get("aciertos", 0),
                "acierto": (actual or {}).get("acierto"),
                "acierto_anterior": (previa or {}).get("acierto"),
                "coste": (actual or {}).get("coste", 0),
                "latencia_media_ms": (actual or {}).get("latencia_media_ms", 0),
                "casos_con_juez": (actual or {}).get("casos_con_juez", 0),
                "version_prompt": ((ultima or {}).get("versiones_prompt") or {}).get(clave, ""),
            }
        )
    fallos: list[dict[str, Any]] = []
    if ultima:
        fallos = [
            r for r in detalle(db, tenant_id, UUID(ultima["id"]))["resultados"] if not r["acierto"]
        ]
    cada = int(_ajuste("ia_evaluacion_cada_horas", db))
    proxima = None
    if cada > 0 and historial:
        base = datetime.fromisoformat(historial[0]["empezada_at"])
        proxima = (base + timedelta(hours=cada)).isoformat()
    return {
        "umbral": float(_ajuste("ia_evaluacion_umbral", db)),
        "cada_horas": cada,
        "proxima_at": proxima,
        "ultima": ultima,
        "en_curso": corriendo,
        "funciones": funciones,
        "tendencia": tendencia,
        "fallos": fallos,
        "banco": casos(db, tenant_id)["de_serie"] if not historial else None,
    }


# ── Programada ────────────────────────────────────────────────────────────


def tenants_con_banco() -> list[Any]:
    """De SU propia tabla: los tenants que ya tienen el banco instalado.

    Uno que nunca ha evaluado no lo quiere programado por su cuenta: el banco
    se instala la primera vez que alguien pulsa «Evaluar ahora».
    """
    from crmcore.db.session import sesion

    with sesion(sistema=True) as db:
        return [t for (t,) in db.execute(select(CasoEvaluacionIA.tenant_id).distinct()).all()]


def lanzar(
    uow: UnidadDeTrabajo,
    *,
    origen: str,
    pedida_por: UUID | None,
    funciones: list[str] | None = None,
) -> dict[str, Any]:
    """Abre la ejecución; la recorre la tarea `intelligence.evaluacion_avance`.

    **No va por la cola de trabajos, y es a propósito.** El estado ya vive en
    estas tablas caso a caso: lo hecho tiene su fila de resultado y lo
    pendiente es lo que falta de `casos_previstos`. Si el proceso muere a
    mitad, la vuelta siguiente sigue por el primero sin resultado, sin repetir
    ni saltarse ninguno — que es lo que la cola habría aportado. Y la fila de la
    ejecución se bloquea con `SKIP LOCKED` mientras se avanza, así que dos
    réplicas no evalúan el mismo caso dos veces.

    Medido el 10-11-2026 en la pila local: con la cola, un worker de una
    versión anterior que seguía vivo tomaba el trabajo y lo daba por fallido
    («el tipo ya no tiene ejecutor») antes que el bueno lo viera.
    """
    ejecucion = preparar(uow, origen=origen, pedida_por=pedida_por, funciones=funciones)
    return {
        "ejecucion_id": str(ejecucion.id),
        "casos": len(ejecucion.casos_previstos or []),
    }


def tenants_con_evaluacion_en_curso() -> list[Any]:
    from crmcore.db.session import sesion

    with sesion(sistema=True) as db:
        return [
            t
            for (t,) in db.execute(
                select(EjecucionEvaluacionIA.tenant_id)
                .where(EjecucionEvaluacionIA.estado == "en_curso")
                .distinct()
            ).all()
        ]


def avanzar_en_curso(tenant_id: Any) -> dict[str, Any]:
    """Una tanda de la ejecución en curso del tenant; la cierra si no queda nada."""
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    tid = tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id))
    with con_contexto(tenant_id=tid, origen="barrido"), unidad_de_trabajo(tid) as uow:
        ejecucion = (
            uow.db.execute(
                select(EjecucionEvaluacionIA)
                .where(
                    EjecucionEvaluacionIA.tenant_id == tid,
                    EjecucionEvaluacionIA.estado == "en_curso",
                )
                .order_by(EjecucionEvaluacionIA.empezada_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .first()
        )
        if ejecucion is None:
            return {"avanzados": 0}
        hechos = avanzar(uow, ejecucion, int(_ajuste("ia_evaluacion_casos_por_tanda", uow.db)))
        if hechos == 0:
            r = cerrar(uow, ejecucion)
            return {"avanzados": 0, "cerrada": r["id"], "acierto": r["acierto"]}
        return {"avanzados": hechos}


def evaluar_si_toca(tenant_id: Any) -> dict[str, Any]:
    """Encola la evaluación del tenant si ha pasado `ia_evaluacion_cada_horas`."""
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    tid = tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id))
    with con_contexto(tenant_id=tid, origen="barrido"), unidad_de_trabajo(tid) as uow:
        cada = int(_ajuste("ia_evaluacion_cada_horas", uow.db))
        if cada <= 0:
            return {"evaluada": False, "porque": "programación apagada (0 horas)"}
        ultima = uow.db.execute(
            select(EjecucionEvaluacionIA.empezada_at)
            .where(EjecucionEvaluacionIA.tenant_id == tid)
            .order_by(EjecucionEvaluacionIA.empezada_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if ultima is not None and _ahora() - ultima < timedelta(hours=cada):
            return {"evaluada": False, "porque": "no toca todavía"}
        r = lanzar(uow, origen="programada", pedida_por=None)
    return {"evaluada": True, **r}
