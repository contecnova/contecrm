"""Campos calculados, agregados y lo que un listado enseña de más
(CRM-00.04.01.04, CRM-00.05.03.03).

Dos módulos de `crmcore` que **no importaba nadie** —`datos.formulas` y
`datos.rollups`— y, al enchufarlos, un agujero de enmascaramiento que llevaba
abierto desde el principio.

El tipo de campo «fórmula» se podía declarar desde el primer día: aparecía en la
lista de tipos, se guardaba y **nadie lo evaluaba ni lo validaba**. El campo
existía, la persona escribía su fórmula y el registro no enseñaba ningún valor.
Sin error. Lo mismo con los agregados sobre los hijos: «cuántas cosas hay
abiertas con este cliente» es la pregunta que se hace al abrir una cuenta, y no
la calculaba nada.

Y el agujero: tres listados escritos a mano —leads, cuentas y contactos—
serializaban con su esquema de salida **sin pasar por la proyección**, mientras
su ficha sí pasaba. Un rol que no puede ver datos personales los veía en el
listado y no en la ficha de la misma fila. No daba ningún error: enseñaba el
teléfono.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db

RAIZ = pathlib.Path(__file__).resolve().parents[2]


# ── Fórmulas (CRM-00.04.01.04) ────────────────────────────────────────────


def test_una_formula_rota_se_rechaza_al_guardarla() -> None:
    """Y no al leer el primer registro: una fórmula rota descubierta al leer es
    una ficha que no se puede abrir, y quien la escribió ya no está delante."""
    from crmcore.datos.formulas import validar

    assert not validar("importe * 1.21")
    assert validar("importe.__class__")
    assert validar("ejecutar(importe)")
    # Y el tope de partes: una fórmula de mil nodos es una forma de agotar el
    # proceso desde la configuración del tenant.
    assert validar(" + ".join(["1"] * 400))


def test_una_formula_que_revienta_no_tumba_la_ficha() -> None:
    """La alternativa —propagar el error— convierte una fórmula mal escrita en
    un objeto inaccesible."""
    from crmcore.datos.formulas import evaluar

    assert evaluar("importe / 0", {"importe": 10}) is None
    assert evaluar("no_existe * 2", {}) is None
    # Y no solo la división por cero: cualquier cosa que reviente. Multiplicar
    # dos textos es el fallo más común cuando el dato llega de un formulario y
    # el número vino como cadena.
    assert evaluar("a * b", {"a": "uno", "b": "dos"}) is None
    assert evaluar("importe * 2", {"importe": 10}) == 20


def test_el_campo_calculado_sale_al_leer(db: Any, tenant_id: UUID) -> None:
    """Es lo que no pasaba: el tipo existía y no lo evaluaba nadie."""
    from crmcore.http.deps import proyectar_para
    from crmcore.metamodelo import EsquemaTenant

    from services.party.modelos import Cuenta

    db.add(
        EsquemaTenant(
            tenant_id=tenant_id,
            objeto="cuenta",
            campos=[
                {"nombre": "base", "tipo": "numero", "activo": True},
                {
                    "nombre": "con_iva",
                    "tipo": "formula",
                    "activo": True,
                    "restricciones": {"formula": "redondear(base * 1.21, 2)"},
                },
            ],
        )
    )
    cuenta = Cuenta(
        tenant_id=tenant_id, nombre="Obras SL", clave_canonica="obras", campos={"base": 100}
    )
    db.add(cuenta)
    db.flush()

    proyecta = proyectar_para(_principal(tenant_id), db, objeto="cuenta", modelo=Cuenta)
    salida = proyecta(cuenta)

    assert salida["campos"]["con_iva"] == 121.0
    # Y el guardado sigue ahí: lo calculado no sustituye a lo que se escribió.
    assert salida["campos"]["base"] == 100


def test_lo_calculado_pisa_lo_que_hubiera_guardado(db: Any, tenant_id: UUID) -> None:
    """Un campo calculado no se escribe, se calcula: un valor viejo guardado con
    ese nombre sería el que se enseñara, y nadie sabría de dónde salió."""
    from crmcore.http.deps import proyectar_para
    from crmcore.metamodelo import EsquemaTenant

    from services.party.modelos import Cuenta

    db.add(
        EsquemaTenant(
            tenant_id=tenant_id,
            objeto="cuenta",
            campos=[
                {"nombre": "base", "tipo": "numero", "activo": True},
                {
                    "nombre": "doble",
                    "tipo": "formula",
                    "activo": True,
                    "restricciones": {"formula": "base * 2"},
                },
            ],
        )
    )
    cuenta = Cuenta(
        tenant_id=tenant_id,
        nombre="Obras SL",
        clave_canonica="obras",
        campos={"base": 10, "doble": 999},
    )
    db.add(cuenta)
    db.flush()

    proyecta = proyectar_para(_principal(tenant_id), db, objeto="cuenta", modelo=Cuenta)
    assert proyecta(cuenta)["campos"]["doble"] == 20


# ── Agregados sobre los hijos (CRM-00.04.01.04) ───────────────────────────


def test_el_maximo_de_un_conjunto_vacio_no_es_cero(db: Any, tenant_id: UUID) -> None:
    """Devolver cero haría que un listado ordenado por «última actividad» pusiera
    arriba a quien no tiene ninguna."""
    from crmcore.datos import rollups

    from services.party.modelos import Cuenta

    cuenta = Cuenta(tenant_id=tenant_id, nombre="Sin nada", clave_canonica="sin nada")
    db.add(cuenta)
    db.flush()

    valores = rollups.calcular(db, rollups.declarados("cuenta"), [cuenta.id])[cuenta.id]
    # «Ninguna actividad» cuenta cero...
    assert valores["actividades_abiertas"] == 0
    # ...y el máximo de un conjunto vacío no existe, no es cero.
    assert valores["ultima_actividad_at"] is None


def test_los_agregados_de_una_cuenta_se_calculan(db: Any, tenant_id: UUID) -> None:
    from crmcore.datos import rollups

    from services.party.modelos import Actividad, Cuenta

    cuenta = Cuenta(tenant_id=tenant_id, nombre="Con cosas", clave_canonica="con cosas")
    db.add(cuenta)
    db.flush()
    for estado in ("pendiente", "en_curso", "completada"):
        db.add(
            Actividad(
                tenant_id=tenant_id,
                cuenta_id=cuenta.id,
                tipo="llamada",
                asunto=f"x {estado}",
                estado=estado,
            )
        )
    db.flush()

    valores = rollups.calcular(db, rollups.declarados("cuenta"), [cuenta.id])[cuenta.id]
    # Solo las abiertas: una completada no es trabajo pendiente con el cliente.
    assert valores["actividades_abiertas"] == 2
    assert valores["ultima_actividad_at"] is not None


def test_un_rollup_roto_no_tumba_el_listado(db: Any, tenant_id: UUID) -> None:
    """El listado es lo que la gente usa todo el día: propagar el fallo lo
    convertiría en una pantalla que no se puede abrir."""
    from crmcore.datos import rollups

    from services.party.modelos import Actividad, Cuenta

    cuenta = Cuenta(tenant_id=tenant_id, nombre="X", clave_canonica="x")
    db.add(cuenta)
    db.flush()

    roto = rollups.Rollup(
        nombre="imposible",
        modelo_hijo=Actividad,
        campo_padre="cuenta_id",
        funcion="suma",
        campo="asunto",  # sumar texto: lo rechaza Postgres
    )
    valores = rollups.calcular(db, [roto], [cuenta.id])
    assert valores[cuenta.id] == {}


# ── Lo que un listado enseña de más (CRM-00.05.03.03) ─────────────────────


def test_ningun_listado_serializa_saltandose_la_proyeccion() -> None:
    """Tres listados lo hacían, y la consecuencia era que un rol que no puede ver
    datos personales los veía en el listado y no en la ficha de la misma fila.

    Se mira con AST: una función que construye una página y la serializa tiene
    que pasar por `proyectar_para`. Buscar el texto no vale —una mención en un
    comentario no es una llamada— y ya dio un falso rojo en este repositorio.
    """
    sospechosas: list[str] = []
    miradas = 0
    for fichero in (RAIZ / "services").rglob("*.py"):
        if "__pycache__" in str(fichero):
            continue
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            llamadas = {
                getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                for n in ast.walk(nodo)
                if isinstance(n, ast.Call)
            }
            if "construir_pagina" not in llamadas:
                continue
            miradas += 1
            if "proyectar_para" not in llamadas:
                sospechosas.append(f"{fichero.relative_to(RAIZ)}::{nodo.name}")

    # Que diga cuántas ha mirado: si el recorrido se rompe, «ninguna sospechosa»
    # significa «no se ha mirado», que es lo contrario de lo que parece.
    assert miradas >= 4, f"solo se han mirado {miradas} listados: el recorrido no mira"
    assert not sospechosas, (
        "Estos listados serializan sin pasar por la proyección, así que pueden "
        "enseñar lo que su ficha tapa:\n  " + "\n  ".join(sospechosas)
    )


def test_el_listado_tapa_lo_mismo_que_la_ficha(db: Any, tenant_id: UUID) -> None:
    """Comprobado sobre los datos, no sobre el código: con una política que
    enmascara lo personal, el teléfono sale igual de tapado en los dos."""
    from crmcore.http.deps import proyectar_para
    from crmcore.http.listados import proyectar_con_esquema

    from services.party.esquemas import CuentaOut
    from services.party.modelos import Cuenta

    cuenta = Cuenta(
        tenant_id=tenant_id,
        nombre="Obras SL",
        clave_canonica="obras",
        telefono="+34600111222",
    )
    db.add(cuenta)
    db.flush()

    principal = _principal(tenant_id)
    ficha = proyectar_para(principal, db, objeto="cuenta", modelo=Cuenta)
    listado = proyectar_con_esquema(ficha, CuentaOut)

    en_ficha = ficha(cuenta).get("telefono")
    en_listado = listado(cuenta).get("telefono")
    assert en_ficha == en_listado


def test_lo_tapado_se_anuncia_aparte_de_lo_retenido(db: Any, tenant_id: UUID) -> None:
    """Un valor enmascarado **parece un dato** y hay que decir que no lo es.

    Hasta el 29-10-2026 sólo se anunciaban los campos ocultos. El enmascarado
    salía sin avisar, y quien lee la respuesta no puede notarlo: «··0111222»
    ocupa el sitio de un teléfono y tiene su forma. Se descubrió con el agente
    autónomo, que preguntó por tres cuentas y contestó que se llamaban
    «··············tora», «··cosa» y «·············elta» — con seguridad.

    Las dos listas van **separadas** porque son dos cosas distintas: lo
    retenido no viene y se ve el hueco; lo tapado viene y engaña.
    """
    from crmcore.authz.proyeccion import enmascarados, limpiar_retenidos, retenidos
    from crmcore.http.deps import proyectar_para

    from services.party.modelos import Cuenta

    cuenta = Cuenta(
        tenant_id=tenant_id,
        nombre="Obras SL",
        clave_canonica="obras-anuncio",
        telefono="+34600111222",
    )
    db.add(cuenta)
    db.flush()

    limpiar_retenidos()
    proyectado = proyectar_para(_principal(tenant_id), db, objeto="cuenta", modelo=Cuenta)(cuenta)

    tapados = enmascarados()
    # Lo que se comprueba no es una lista concreta —depende de la política del
    # tenant— sino que lo que SALE tapado esté anunciado y lo que sale en claro
    # no. Sin esto, la prueba pasaría con la lista siempre vacía.
    for campo, valor in proyectado.items():
        if isinstance(valor, str) and "·" in valor:
            assert campo in tapados, f"«{campo}» sale tapado y no se anuncia"
    for campo in tapados:
        assert "·" in str(proyectado.get(campo)), (
            f"«{campo}» se anuncia como tapado y no lo está: un aviso que sobra " "se deja de leer"
        )
    assert set(tapados).isdisjoint(retenidos()), (
        "Un campo no puede estar a la vez tapado y retenido: son dos cosas "
        "distintas y se cuentan aparte"
    )
    limpiar_retenidos()


def _principal(tenant_id: UUID) -> Any:
    from crmcore.authz.principal import Principal

    return Principal(
        id=uuid4(),
        tenant_id=tenant_id,
        permisos=frozenset({"*:*"}),
        roles=frozenset({"comercial"}),
    )
