"""El índice de conocimiento con pgvector (CRM-04.03.01.04, CRM-05.02.02.03).

Las sugerencias de casos parecidos y la respuesta con citación filtraban
resultados que «llegaban ya buscados», y nada buscaba. Aquí se comprueba el
índice que faltaba, con un incrustador de mentira determinista —palabras a
dimensiones— para que «parecido» signifique algo comprobable:

- lo más parecido sale primero, y lo de otro tenant no sale;
- lo que no ha cambiado no se vuelve a calcular (ni a pagar);
- vectores de otro modelo no se comparan;
- lo que quien pregunta no puede ver no sale de la búsqueda;
- y la sugerencia del caso busca sola cuando no le dan resultados.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz.principal import Principal
from crmcore.db.uow import UnidadDeTrabajo

from services.intelligence import indice
from tests.unit.test_ia_generativa import _proveedor, uow  # noqa: F401

pytestmark = pytest.mark.db

DIM = 32


def _vector(texto: str) -> list[float]:
    v = [0.0] * DIM
    for palabra in texto.lower().split():
        v[int(hashlib.md5(palabra.encode()).hexdigest(), 16) % DIM] += 1.0
    norma = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norma for x in v]


@pytest.fixture
def llamadas() -> Any:
    hechas: list[list[str]] = []

    def _incrustar(**kw: Any) -> list[list[float]]:
        hechas.append(list(kw["textos"]))
        return [_vector(t) for t in kw["textos"]]

    indice.registrar_incrustador(_incrustar)
    return hechas


def _con_embeddings(uow: UnidadDeTrabajo, clave: str = "vectores") -> None:  # noqa: F811
    _proveedor(
        uow,
        clave=clave,
        modelos=[{"uso": "embeddings", "clave": f"{clave}-1", "nombre": "Vectores"}],
    )


def test_lo_mas_parecido_sale_primero_y_no_se_paga_dos_veces(
    uow: UnidadDeTrabajo,  # noqa: F811
    llamadas: list[Any],
) -> None:
    _con_embeddings(uow)
    indice.indexar(
        uow,
        fuente="articulo",
        referencia="a1",
        titulo="Impresora no imprime",
        texto="reiniciar la impresora y revisar el toner",
    )
    indice.indexar(
        uow,
        fuente="articulo",
        referencia="a2",
        titulo="Factura duplicada",
        texto="anular la factura repetida y emitir abono",
    )
    resultados = indice.buscar(
        uow.db, uow.tenant_id, texto="la impresora no imprime nada", fuentes=("articulo",)
    )
    assert [r["referencia"] for r in resultados][0] == "a1"
    assert resultados[0]["parecido"] > resultados[1]["parecido"]
    antes = len(llamadas)
    salida = indice.indexar(
        uow,
        fuente="articulo",
        referencia="a1",
        titulo="Impresora no imprime",
        texto="reiniciar la impresora y revisar el toner",
    )
    assert salida["indexado"] is False and len(llamadas) == antes


def test_lo_de_otro_tenant_y_lo_de_otro_modelo_no_se_compara(
    db: Any,
    tenant_id: UUID,
    llamadas: list[Any],
) -> None:
    propio = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    _con_embeddings(propio)
    indice.indexar(
        propio, fuente="articulo", referencia="a1", titulo="Toner", texto="cambiar toner"
    )
    otro = uuid4()
    ajeno = UnidadDeTrabajo(db=db, tenant_id=otro)
    _con_embeddings(ajeno)
    indice.indexar(ajeno, fuente="articulo", referencia="b1", titulo="Toner", texto="cambiar toner")
    vistos = {r["referencia"] for r in indice.buscar(db, tenant_id, texto="cambiar toner")}
    assert vistos == {"a1"}
    # Un fragmento calculado con otro modelo no entra en la comparación.
    fila = db.query(indice.FragmentoIndice).filter_by(tenant_id=tenant_id).one()
    fila.modelo = "otro/modelo"
    db.flush()
    assert indice.buscar(db, tenant_id, texto="cambiar toner") == []


def test_la_busqueda_por_api_no_ensena_lo_que_no_se_puede_ver(
    uow: UnidadDeTrabajo,  # noqa: F811
    llamadas: list[Any],
) -> None:
    from services.intelligence.api_indice import BuscarIn, buscar

    _con_embeddings(uow)
    indice.indexar(uow, fuente="articulo", referencia="a1", titulo="Toner", texto="cambiar toner")
    indice.indexar(
        uow,
        fuente="caso_resuelto",
        referencia="c1",
        titulo="Toner",
        texto="cambiar toner. Resolución: se cambió",
    )

    def _quien(*p: str) -> Principal:
        return Principal(id=uuid4(), tenant_id=uow.tenant_id, permisos=frozenset(p))

    solo_casos = buscar(BuscarIn(texto="cambiar toner"), uow.db, _quien("case:read"))
    assert {r["referencia"] for r in solo_casos["items"]} == {"c1"}
    nada = buscar(BuscarIn(texto="cambiar toner"), uow.db, _quien("ia:usar"))
    assert nada["items"] == []


def test_la_sugerencia_del_caso_busca_sola_en_el_indice(
    uow: UnidadDeTrabajo,  # noqa: F811
    llamadas: list[Any],
    monkeypatch: Any,
) -> None:
    from services.intelligence import caso_semantico as sem
    from services.intelligence.api_modelos import SugerirIn, sugerir

    monkeypatch.setattr(sem, "_ia_parecido_caso", lambda: 0.1)
    _con_embeddings(uow)
    indice.indexar(
        uow,
        fuente="caso_resuelto",
        referencia="c-viejo",
        titulo="La impresora no imprime",
        texto="no imprime. Resolución: reiniciar la cola de impresión",
    )
    caso = uuid4()
    salida = sugerir(
        caso,
        SugerirIn(caso={"asunto": "La impresora no imprime", "descripcion": "nada sale"}),
        uow.db,
        Principal(id=uuid4(), tenant_id=uow.tenant_id, permisos=frozenset({"case:read"})),
    )
    assert salida["buscado_en_el_indice"] is True
    assert [s.get("referencia") for s in salida["sugerencias"]] == ["c-viejo"]
    # Y con comodín también: comparando el texto literal, quien tenía `*:*` no
    # «tenía» `case:read` y se le descartaba todo (medido con el índice de verdad).
    admin = sugerir(
        caso,
        SugerirIn(caso={"asunto": "La impresora no imprime", "descripcion": "nada sale"}),
        uow.db,
        Principal(id=uuid4(), tenant_id=uow.tenant_id, permisos=frozenset({"*:*"})),
    )
    assert [s.get("referencia") for s in admin["sugerencias"]] == ["c-viejo"]


def test_lo_que_se_publica_entra_solo(
    db: Any,
    tenant_id: UUID,
    llamadas: list[Any],
    monkeypatch: Any,
) -> None:
    from types import SimpleNamespace

    import crmcore.http.interno as interno

    _con_embeddings(UnidadDeTrabajo(db=db, tenant_id=tenant_id))
    db.commit()
    articulo = str(uuid4())

    def _invocar(**kw: Any) -> dict[str, Any]:
        assert kw["ruta"] == f"/api/v1/conocimiento/{articulo}"
        return {"estado": 200, "datos": {"titulo": "Toner", "cuerpo": "cambiar el toner"}}

    monkeypatch.setattr(interno, "invocar", _invocar)
    indice._al_evento(
        SimpleNamespace(tenant_id=str(tenant_id), data={"articulo_id": articulo}),
        "articulo",
        "articulo_id",
    )
    fila = (
        db.query(indice.FragmentoIndice).filter_by(tenant_id=tenant_id, referencia=articulo).one()
    )
    assert fila.permiso == "knowledge:read" and "cambiar el toner" in fila.texto
