"""Jerarquía de empresas: matriz–filial, franquicia y holding (CRM-00.01.03.07).

Hasta el 09-11-2026 la jerarquía era una columna —`tenant_padre_id`— que se
podía poner en el alta y no servía para nada más: no decía qué relación era, no
se veía el árbol y la matriz no podía ver nada de sus hijas.

Lo que hay ahora, y las dos reglas que lo sostienen:

**Lo que la matriz ve lo autoriza la HIJA, explícitamente, y sólo ella.** Ni la
matriz ni la plataforma pueden concederlo en su nombre: una filial puede tener
obligaciones de confidencialidad frente a su matriz —un franquiciado no tiene
por qué enseñar su embudo al franquiciador— y un permiso que da quien lo va a
usar no es un permiso. Vacío es no compartir nada, que es lo de fábrica.

**Sólo agregados, nunca filas.** Lo que se puede compartir es el consumo y unos
indicadores (cifras sumadas que se configuran). La llamada a la hija se firma
con su identidad, sin más permiso que el que pide cada indicador, a rutas que
devuelven números; de la respuesta se coge el campo numérico y nada más. El
aislamiento entre empresas no se toca: ninguna fila de la hija sale de su
servicio.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.tenancy.modelos import Tenant

logger = get_logger(__name__)

RELACIONES = ("matriz_filial", "franquicia", "holding")
COMPARTIBLE = ("consumo", "indicadores")


def _todos(db: Session) -> dict[UUID, Tenant]:
    return {t.id: t for t in db.execute(select(Tenant)).scalars().all()}


def _ancestros(tenants: dict[UUID, Tenant], tenant_id: UUID) -> list[Tenant]:
    """De la empresa hacia arriba, sin ella. Corta si hay un ciclo."""
    salida: list[Tenant] = []
    vistos = {tenant_id}
    actual = tenants.get(tenant_id)
    while actual is not None and actual.tenant_padre_id and actual.tenant_padre_id not in vistos:
        vistos.add(actual.tenant_padre_id)
        actual = tenants.get(actual.tenant_padre_id)
        if actual is not None:
            salida.append(actual)
    return salida


def _descendientes(tenants: dict[UUID, Tenant], tenant_id: UUID) -> list[Tenant]:
    hijos: dict[UUID, list[Tenant]] = {}
    for t in tenants.values():
        if t.tenant_padre_id:
            hijos.setdefault(t.tenant_padre_id, []).append(t)
    salida: list[Tenant] = []
    pendientes = [tenant_id]
    vistos = {tenant_id}
    while pendientes:
        for h in sorted(hijos.get(pendientes.pop(0), []), key=lambda x: x.nombre):
            if h.id in vistos:
                continue
            vistos.add(h.id)
            salida.append(h)
            pendientes.append(h.id)
    return salida


def _nodo(t: Tenant, *, nivel: int) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "slug": t.slug,
        "nombre": t.nombre,
        "estado": t.estado,
        "padre_id": str(t.tenant_padre_id) if t.tenant_padre_id else None,
        "relacion": t.relacion_padre,
        "comparte": list(t.comparte_con_padre or []),
        "nivel": nivel,
    }


def arbol(db: Session, tenant_id: UUID, *, es_plataforma: bool) -> dict[str, Any]:
    """El árbol visto desde una empresa.

    Para la plataforma, el árbol entero desde la raíz. Para la propia empresa,
    su línea hacia arriba (matriz, matriz de la matriz) y todo lo que cuelga de
    ella; NO sus hermanas: que dos filiales compartan matriz no les da derecho
    a saber la una de la otra.
    """
    tenants = _todos(db)
    if tenant_id not in tenants:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")
    arriba = _ancestros(tenants, tenant_id)
    if es_plataforma:
        raiz = arriba[-1].id if arriba else tenant_id
        nodos = [tenants[raiz], *_descendientes(tenants, raiz)]
    else:
        nodos = [*reversed(arriba), tenants[tenant_id], *_descendientes(tenants, tenant_id)]
    niveles: dict[UUID, int] = {}
    salida = []
    for t in nodos:
        nivel = niveles.get(t.tenant_padre_id, -1) + 1 if t.tenant_padre_id else 0
        niveles[t.id] = nivel
        salida.append(_nodo(t, nivel=nivel))
    return {"tenant_id": str(tenant_id), "relaciones": list(RELACIONES), "nodos": salida}


def colgar(
    db: Session,
    tenant_id: UUID,
    *,
    padre_id: UUID | None,
    relacion: str | None,
) -> dict[str, Any]:
    """Pone (o quita) el padre de una empresa y la relación que los une.

    Al cambiar de padre se BORRA lo que la hija compartía: lo autorizó para
    aquella matriz, no para la que venga.
    """
    from crmcore.audit.chain import registrar

    tenants = _todos(db)
    hija = tenants.get(tenant_id)
    if hija is None:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")
    if padre_id is not None:
        if padre_id == tenant_id:
            raise ErrorValidacion(
                "Una empresa no puede colgar de sí misma", error_code="jerarquia.ciclo"
            )
        if padre_id not in tenants:
            raise NoEncontrado(
                "El tenant padre indicado no existe", error_code="tenant.padre_no_encontrado"
            )
        if tenant_id in {t.id for t in _ancestros(tenants, padre_id)}:
            raise Conflicto(
                "Esa empresa cuelga ya de esta: el árbol quedaría en círculo",
                error_code="jerarquia.ciclo",
            )
        if relacion not in RELACIONES:
            raise ErrorValidacion(
                f"La relación tiene que ser una de: {', '.join(RELACIONES)}",
                error_code="jerarquia.relacion_no_valida",
            )
    antes = {"padre": str(hija.tenant_padre_id or ""), "relacion": hija.relacion_padre}
    if hija.tenant_padre_id != padre_id:
        hija.comparte_con_padre = []
        hija.comparte_actualizado_at = datetime.now(timezone.utc)
    hija.tenant_padre_id = padre_id
    hija.relacion_padre = relacion if padre_id else None
    registrar(
        db,
        accion="tenant.jerarquia_cambiada",
        objeto="tenant",
        objeto_id=str(tenant_id),
        datos={"antes": antes, "padre": str(padre_id or ""), "relacion": hija.relacion_padre},
        tenant_id=tenant_id,
    )
    db.flush()
    return _nodo(hija, nivel=0)


def compartir(db: Session, tenant_id: UUID, *, que: list[str], por: UUID | None) -> dict[str, Any]:
    """La hija decide qué deja ver a su padre. Sólo la hija llama aquí."""
    from crmcore.audit.chain import registrar

    hija = db.get(Tenant, tenant_id)
    if hija is None:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")
    malos = [q for q in que if q not in COMPARTIBLE]
    if malos:
        raise ErrorValidacion(
            f"Sólo se puede compartir: {', '.join(COMPARTIBLE)}",
            error_code="jerarquia.no_compartible",
        )
    if que and not hija.tenant_padre_id:
        raise Conflicto(
            "Esta empresa no cuelga de ninguna: no hay con quién compartir",
            error_code="jerarquia.sin_padre",
        )
    antes = list(hija.comparte_con_padre or [])
    hija.comparte_con_padre = sorted(set(que))
    hija.comparte_actualizado_at = datetime.now(timezone.utc)
    hija.comparte_actualizado_por = por
    registrar(
        db,
        accion="tenant.comparticion_con_padre",
        objeto="tenant",
        objeto_id=str(tenant_id),
        datos={
            "antes": antes,
            "ahora": hija.comparte_con_padre,
            "padre": str(hija.tenant_padre_id),
        },
        tenant_id=tenant_id,
    )
    db.flush()
    return {"comparte": hija.comparte_con_padre, "padre_id": str(hija.tenant_padre_id or "")}


def _numero(valor: Any) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def indicadores_de(hija_id: UUID, indicadores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cada indicador configurado, leído en la hija. Sólo el número.

    La llamada va firmada con la identidad de la hija y sólo el permiso que pide
    ese indicador; de la respuesta se coge el campo y se descarta el resto. Un
    indicador que no se puede leer se dice, no vale cero.
    """
    from crmcore.http.interno import invocar

    from services.tenancy.facturacion import identidad_de_lectura

    salida = []
    for ind in indicadores:
        nombre = str(ind.get("nombre") or ind.get("ruta") or "")
        ruta = str(ind.get("ruta") or "")
        campo = str(ind.get("campo") or "")
        if not ruta.startswith("/api/v1/") or not campo:
            salida.append({"nombre": nombre, "valor": None, "porque": "mal configurado"})
            continue
        try:
            r = invocar(
                metodo="GET",
                ruta=ruta,
                tenant_id=hija_id,
                principal_id=identidad_de_lectura(),
                permisos=[str(ind["permiso"])] if ind.get("permiso") else [],
                roles=[str(r) for r in (ind.get("roles") or [])],
            )
        except Exception as exc:  # noqa: BLE001 — se dice en su fila
            salida.append({"nombre": nombre, "valor": None, "porque": str(exc)[:120]})
            continue
        datos = r.get("datos") if r.get("ok") else None
        valor = _numero(datos.get(campo)) if isinstance(datos, dict) else None
        salida.append(
            {
                "nombre": nombre,
                "valor": valor,
                "porque": "" if valor is not None else f"no se ha podido leer ({r.get('estado')})",
            }
        )
    return salida


def agregado(
    db: Session,
    tenant_id: UUID,
    *,
    consumo_de: Any = None,
    indicadores_de_hija: Any = None,
) -> dict[str, Any]:
    """Lo que la matriz ve de cada empresa que cuelga de ella.

    De cada descendiente, sólo lo que ESA empresa ha compartido. Lo no
    compartido sale como tal —«no compartido»—, no como cero ni oculto: la
    matriz tiene que saber que hay una filial que no le enseña su consumo, no
    creer que no consume.

    `consumo_de` e `indicadores_de_hija` se inyectan en las pruebas; en el
    producto son las llamadas por HTTP.
    """
    from crmcore.runtime import settings as rt

    from services.tenancy.facturacion import consumo_compuesto

    consumo_de = consumo_de or (lambda tid: consumo_compuesto(tid, principal_id=None))
    indicadores_de_hija = indicadores_de_hija or indicadores_de
    configurados = list(rt.efectivo("jerarquia_indicadores", db) or [])

    tenants = _todos(db)
    if tenant_id not in tenants:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")
    hijas = []
    totales_consumo: dict[str, dict[str, Any]] = {}
    totales_ind: dict[str, float] = {}
    for h in _descendientes(tenants, tenant_id):
        comparte = set(h.comparte_con_padre or [])
        fila: dict[str, Any] = {
            "id": str(h.id),
            "nombre": h.nombre,
            "relacion": h.relacion_padre,
            "comparte": sorted(comparte),
            "consumo": None,
            "indicadores": None,
        }
        if "consumo" in comparte:
            medido = consumo_de(h.id)
            fila["consumo"] = medido
            for f in medido.get("filas") or []:
                acum = totales_consumo.setdefault(
                    f["metrica"], {"metrica": f["metrica"], "cantidad": 0, "unidad": f["unidad"]}
                )
                acum["cantidad"] += int(f.get("cantidad") or 0)
        if "indicadores" in comparte:
            leidos = indicadores_de_hija(h.id, configurados)
            fila["indicadores"] = leidos
            for i in leidos:
                if i.get("valor") is not None:
                    totales_ind[i["nombre"]] = totales_ind.get(i["nombre"], 0.0) + float(i["valor"])
        hijas.append(fila)
    return {
        "tenant_id": str(tenant_id),
        "hijas": hijas,
        "totales": {
            "consumo": sorted(totales_consumo.values(), key=lambda x: x["metrica"]),
            "indicadores": [{"nombre": k, "valor": v} for k, v in sorted(totales_ind.items())],
        },
        "no_comparten": [h["nombre"] for h in hijas if not h["comparte"]],
    }


def exigir_propia(principal: Any, tenant_id: UUID) -> None:
    """Sólo la propia empresa decide qué comparte. Ni la plataforma."""
    if principal.tenant_id != tenant_id:
        raise Prohibido(
            "Lo que una empresa comparte con su matriz lo decide ella misma",
            error_code="jerarquia.solo_la_propia",
        )
