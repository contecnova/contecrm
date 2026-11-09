"""Normalización de direcciones (CRM-01.01.04.04).

Medido el 09-11-2026: la capacidad constaba hecha y **ninguna dirección se
normalizaba**. «c/ mayor  3», «C/ Mayor, 3» y «Calle Mayor 3» eran tres
direcciones distintas para el cruce de duplicados, para el mapa y para el
reparto por territorio; y un código postal «8001» que perdió el cero en una
hoja de cálculo no caía en ningún territorio de Barcelona.

Lo que se hace, y lo que no:

- **Forma, no contenido.** Espacios, mayúsculas, la abreviatura de vía de la
  primera palabra, el código postal con sus dígitos y el país en ISO-2. No se
  inventa nada: no se deduce la provincia ni se corrige una calle que no existe
  —eso es validar contra un callejero, y es otra capacidad—.
- **Las abreviaturas y los dígitos del código postal son ajustes.** Cada país y
  cada empresa abrevia distinto; una lista escrita aquí sería la de quien la
  escribió.
- **Al guardar y en lote.** Lo que entra desde hoy se normaliza al darlo de
  alta; lo que ya estaba se recorre con un barrido que primero dice qué cambiaría
  y sólo escribe si se le pide. Cada cambio queda en la auditoría con el antes:
  una normalización que se equivoca tiene que poder deshacerse a mano.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.runtime import settings as rt
from sqlalchemy import select
from sqlalchemy.orm import Session

_RE_ESPACIOS = re.compile(r"\s+")
_RE_ESPACIO_ANTES_DE_COMA = re.compile(r"\s+,")
_CAMPOS = ("linea1", "linea2", "codigo_postal", "ciudad", "provincia", "pais")

# Partículas que no se capitalizan dentro de un nombre de lugar: «Sant Cugat
# del Vallès», no «Sant Cugat Del Vallès».
_MENORES = frozenset({"de", "del", "la", "las", "los", "el", "y", "i", "d'", "l'", "en"})


def _abreviaturas(db: Session | None) -> dict[str, str]:
    from services.party.ajustes import ajustes

    valor = rt.efectivo("direcciones_abreviaturas", db)
    if not isinstance(valor, dict):
        valor = ajustes().direcciones_abreviaturas
    return {str(k).lower(): str(v) for k, v in (valor or {}).items()}


def _digitos_cp(db: Session | None) -> dict[str, int]:
    from services.party.ajustes import ajustes

    valor = rt.efectivo("direcciones_cp_digitos", db)
    if not isinstance(valor, dict):
        valor = ajustes().direcciones_cp_digitos
    salida: dict[str, int] = {}
    for k, v in (valor or {}).items():
        try:
            salida[str(k).upper()] = int(v)
        except (TypeError, ValueError):
            continue
    return salida


def _limpio(texto: str | None) -> str:
    return _RE_ESPACIO_ANTES_DE_COMA.sub(",", _RE_ESPACIOS.sub(" ", (texto or "").strip()))


def _lugar(texto: str | None) -> str:
    """«SANT CUGAT DEL VALLES» → «Sant Cugat del Valles». Sin tocar acentos."""
    limpio = _limpio(texto)
    if not limpio:
        return ""
    palabras = limpio.lower().split(" ")
    salida = []
    for i, palabra in enumerate(palabras):
        if i > 0 and palabra in _MENORES:
            salida.append(palabra)
        else:
            salida.append("-".join(p[:1].upper() + p[1:] for p in palabra.split("-")))
    return " ".join(salida)


def normalizar_direccion(datos: dict[str, Any], db: Session | None = None) -> dict[str, Any]:
    """La misma dirección, en su forma normalizada. No toca lo que no reconoce."""
    salida = dict(datos)
    linea1 = _limpio(datos.get("linea1"))
    if linea1:
        primera, _, resto = linea1.partition(" ")
        # «C/Mayor» sin espacio: la abreviatura va pegada a la calle.
        abreviaturas = _abreviaturas(db)
        larga = abreviaturas.get(primera.lower())
        if larga is None and "/" in primera:
            cabeza, _, cola = primera.partition("/")
            larga = abreviaturas.get(f"{cabeza.lower()}/")
            if larga is not None:
                resto = f"{cola} {resto}".strip()
        if larga is not None:
            linea1 = f"{larga} {resto}".strip()
        # La primera letra de la vía en mayúscula; el resto, como venga: un
        # nombre propio en minúsculas no se arregla sin saber cuál es.
        linea1 = linea1[:1].upper() + linea1[1:]
        salida["linea1"] = linea1
    if "linea2" in datos:
        salida["linea2"] = _limpio(datos.get("linea2")) or None

    pais = re.sub(r"[^A-Za-z]", "", str(datos.get("pais") or "")).upper()[:2]
    if pais:
        salida["pais"] = pais
    pais = pais or "ES"

    cp = _limpio(datos.get("codigo_postal")).upper()
    if cp:
        digitos = _digitos_cp(db).get(pais)
        solo = re.sub(r"\D", "", cp)
        if digitos and solo and solo == cp.replace(" ", "") and len(solo) < digitos:
            cp = solo.zfill(digitos)
        elif digitos and solo == cp.replace(" ", ""):
            cp = solo
        salida["codigo_postal"] = cp
    for campo in ("ciudad", "provincia"):
        if campo in datos:
            salida[campo] = _lugar(datos.get(campo)) or None
    return salida


def diferencias(antes: dict[str, Any], despues: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        c: {"antes": antes.get(c), "despues": despues.get(c)}
        for c in _CAMPOS
        if c in despues and (antes.get(c) or None) != (despues.get(c) or None)
    }


def barrido(
    uow: UnidadDeTrabajo,
    *,
    aplicar: bool = False,
    limite: int = 500,
    objeto: str | None = None,
    objeto_id: UUID | None = None,
) -> dict[str, Any]:
    """Recorre las direcciones guardadas y dice —o aplica— lo que cambiaría.

    Primero se mira y después se escribe: una regla de abreviaturas mal puesta
    cambiaría miles de direcciones de golpe, y verlo antes cuesta un clic.
    """
    from services.party.modelos import Direccion

    consulta = select(Direccion).where(Direccion.tenant_id == uow.tenant_id)
    if objeto:
        consulta = consulta.where(Direccion.objeto == objeto)
    if objeto_id:
        consulta = consulta.where(Direccion.objeto_id == objeto_id)
    filas = list(uow.db.execute(consulta.order_by(Direccion.created_at).limit(limite)).scalars())
    cambios: list[dict[str, Any]] = []
    for fila in filas:
        antes = {c: getattr(fila, c) for c in _CAMPOS}
        despues = normalizar_direccion(antes, uow.db)
        dif = diferencias(antes, despues)
        if not dif:
            continue
        cambios.append(
            {
                "direccion_id": str(fila.id),
                "objeto": fila.objeto,
                "objeto_id": str(fila.objeto_id),
                "cambios": dif,
            }
        )
        if aplicar:
            for campo, par in dif.items():
                setattr(fila, campo, par["despues"])
            registrar(
                uow.db,
                accion="direccion.normalizada",
                objeto=fila.objeto,
                objeto_id=fila.objeto_id,
                datos={"direccion_id": str(fila.id), "cambios": dif},
                tenant_id=uow.tenant_id,
            )
    if aplicar:
        uow.db.flush()
    return {
        "revisadas": len(filas),
        "a_cambiar": len(cambios),
        "aplicado": aplicar,
        "cambios": cambios[:200],
        "recortado": len(cambios) > 200,
    }


def _al_guardar(session: Session, _contexto: Any, _instancias: Any) -> None:
    """Normaliza la dirección nueva o corregida, venga por donde venga.

    Por cualquier vía y no por una ruta: el alta de la ficha, la importación, la
    corrección genérica y la sincronización sin conexión escriben direcciones, y
    enganchar sólo una dejaba sin normalizar justo la importación.
    """
    from sqlalchemy import inspect as inspeccionar

    from services.party.modelos import Direccion

    for obj in list(session.new) + list(session.dirty):
        if not isinstance(obj, Direccion):
            continue
        if obj in session.dirty:
            estado = inspeccionar(obj)
            if not any(estado.attrs[c].history.has_changes() for c in _CAMPOS):  # type: ignore[index]
                continue
        antes = {c: getattr(obj, c) for c in _CAMPOS}
        despues = normalizar_direccion(antes, session)
        for campo, par in diferencias(antes, despues).items():
            if campo == "linea1" and not par["despues"]:
                continue
            setattr(obj, campo, par["despues"])


_ENGANCHADO = False


def enganchar() -> None:
    """Registra la normalización al guardar. Idempotente."""
    global _ENGANCHADO
    if _ENGANCHADO:
        return
    from sqlalchemy import event

    event.listen(Session, "before_flush", _al_guardar)
    _ENGANCHADO = True
