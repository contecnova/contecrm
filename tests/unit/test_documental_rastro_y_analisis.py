"""La constancia que no se dejaba y el análisis que no se podía pedir
(CRM-06.01.01.05, CRM-06.01.01.06).

**«¿A quién le mandamos la cláusula mala?»** es la pregunta que se hace cuando
una cláusula de una plantilla resulta estar mal, y el producto tenía la respuesta
montada: una tabla con qué se generó, de qué plantilla y de qué versión, y una
consulta que la lee. Lo que no tenía era **quien escribiera en la tabla**:
`anotar_generado` no la llamaba nadie, así que estaba siempre vacía y la consulta
contestaba «a nadie» con toda tranquilidad. Un registro vacío no da error:
contesta lo mismo que si de verdad no se hubiera mandado a nadie.

Y la función que compone el documento decía **en su primera línea** que dejaba
constancia. No la dejaba.

**El análisis de una rama** del corpus —resumir una carpeta entera, o sacar sus
conceptos— estaba escrito, con su plazo propio en minutos porque pasa por el
modelo de lenguaje, y con una nota que dice que solo se llama desde un trabajo de
fondo. No había trabajo de fondo. Ni ruta. Era una capacidad que no se podía
pedir de ninguna forma.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


# ── La constancia de lo generado (CRM-06.01.01.06) ────────────────────────


@pytest.fixture
def plantilla(db: Any, tenant_id: UUID) -> Any:
    from crmcore.documental.plantillas import guardar_plantilla

    return guardar_plantilla(
        db,
        tenant_id=tenant_id,
        clave="contrato-marco",
        cuerpo="Estimado {{cliente}}: adjuntamos el contrato. CLÁUSULA DE PENALIZACIÓN.",
        tipo="contrato",
        nombre="Contrato marco",
        clausulas_bloqueadas=["CLÁUSULA DE PENALIZACIÓN"],
    )


def test_generar_deja_constancia_de_con_que_se_hizo(
    db: Any, tenant_id: UUID, plantilla: Any
) -> None:
    """Lo decía en su primera línea y no lo hacía."""
    from crmcore.documental.plantillas import generar, quien_recibio

    salida = generar(
        db,
        tenant_id=tenant_id,
        clave="contrato-marco",
        datos={"cliente": "Acme"},
        objeto="cuenta",
        objeto_id=uuid4(),
        por=uuid4(),
    )
    assert "Acme" in salida["texto"]

    rastro = quien_recibio(db, tenant_id, clave="contrato-marco", version=salida["version"])
    assert (
        rastro["cuantos"] == 1
    ), "generar no ha dejado constancia: la pregunta sigue sin respuesta"


def test_la_pregunta_que_esto_existe_para_contestar(
    db: Any, tenant_id: UUID, plantilla: Any
) -> None:
    """«Esta cláusula está mal, ¿a quién se la mandamos?». Sin la constancia, la
    respuesta es «a nadie» y nadie sabe que es mentira."""
    from crmcore.documental.plantillas import generar, quien_recibio

    uno, dos = uuid4(), uuid4()
    for cuenta in (uno, dos):
        generar(
            db,
            tenant_id=tenant_id,
            clave="contrato-marco",
            datos={"cliente": "X"},
            objeto="cuenta",
            objeto_id=cuenta,
            por=uuid4(),
        )

    rastro = quien_recibio(db, tenant_id, clave="contrato-marco", version=plantilla.version)
    assert rastro["cuantos"] == 2
    objetos = {str(d["objeto_id"]) for d in rastro["documentos"]}
    assert objetos == {str(uno), str(dos)}


def test_la_constancia_lleva_la_version_con_la_que_se_hizo(
    db: Any, tenant_id: UUID, plantilla: Any
) -> None:
    """Es lo que hace que la pregunta tenga sentido: la cláusula mala está en UNA
    versión, y lo que hay que saber es quién recibió ésa."""
    from crmcore.documental.plantillas import generar, guardar_plantilla, quien_recibio

    primera = generar(db, tenant_id=tenant_id, clave="contrato-marco", datos={"cliente": "Antigua"})
    guardar_plantilla(
        db,
        tenant_id=tenant_id,
        clave="contrato-marco",
        cuerpo="Hola {{cliente}}. CLÁUSULA DE PENALIZACIÓN.",
        tipo="contrato",
        nombre="Contrato marco",
        clausulas_bloqueadas=["CLÁUSULA DE PENALIZACIÓN"],
    )
    segunda = generar(db, tenant_id=tenant_id, clave="contrato-marco", datos={"cliente": "Nueva"})

    assert segunda["version"] > primera["version"]
    assert (
        quien_recibio(db, tenant_id, clave="contrato-marco", version=primera["version"])["cuantos"]
        == 1
    )
    assert (
        quien_recibio(db, tenant_id, clave="contrato-marco", version=segunda["version"])["cuantos"]
        == 1
    )


def test_un_documento_que_no_se_archiva_tambien_se_apunta(
    db: Any, tenant_id: UUID, plantilla: Any
) -> None:
    """Hay documentos que se generan y acaban en un correo sin pasar por el
    gestor. Son exactamente los que después nadie puede rastrear, así que la
    constancia va al generar y no al archivar."""
    from crmcore.documental.plantillas import generar, quien_recibio

    generar(db, tenant_id=tenant_id, clave="contrato-marco", datos={"cliente": "Sin archivar"})
    assert (
        quien_recibio(db, tenant_id, clave="contrato-marco", version=plantilla.version)["cuantos"]
        == 1
    )


def test_lo_que_no_se_llega_a_generar_no_se_apunta(
    db: Any, tenant_id: UUID, plantilla: Any
) -> None:
    """Apuntar un intento fallido haría creer que alguien recibió algo que no
    salió."""
    from crmcore.documental.plantillas import generar, quien_recibio
    from crmcore.errors import Conflicto

    with pytest.raises(Conflicto):
        generar(db, tenant_id=tenant_id, clave="contrato-marco", datos={})

    assert (
        quien_recibio(db, tenant_id, clave="contrato-marco", version=plantilla.version)["cuantos"]
        == 0
    )


# ── El análisis de una rama (CRM-06.01.01.05) ─────────────────────────────


def test_el_analisis_tiene_ejecutor_registrado() -> None:
    """Registrarlo solo dentro de la ruta lo dejaría en el proceso web: el worker
    —que es quien lo ejecuta— no lo tendría, y el trabajo quedaría encolado para
    siempre sin nadie que lo coja."""
    import crmcore.http.documental_router  # noqa: F401 — es el que lo importa
    from crmcore.datos.trabajos import ejecutor_de

    assert ejecutor_de("documental.analizar_rama") is not None


def test_el_analisis_se_encola_y_no_se_ejecuta_en_la_peticion(db: Any, tenant_id: UUID) -> None:
    """Pasa por el modelo de lenguaje y el de embeddings tarda minutos en cargar
    en frío: hacerlo dentro de la petición da un 504 con el trabajo hecho y
    tirado — y funcionaría en pruebas, con el modelo caliente, para fallar el
    lunes por la mañana."""
    from crmcore.documental.trabajos_analisis import TIPO, encolar_analisis

    trabajo = encolar_analisis(
        db,
        tenant_id=tenant_id,
        carpetas=["carpeta-1", "carpeta-2"],
        token_usuario="tok",
        que="resumen",
    )
    assert trabajo.tipo == TIPO
    assert trabajo.estado == "encolado"
    assert trabajo.total == 2


def test_una_rama_por_tanda(db: Any, tenant_id: UUID, monkeypatch: Any) -> None:
    """Cada análisis puede tardar minutos. Una tanda que se come veinte es un
    commit de media hora que, si el worker se cae, se repite entero."""
    from crmcore.datos.trabajos import ejecutor_de
    from crmcore.documental import cliente
    from crmcore.documental.trabajos_analisis import TIPO, encolar_analisis

    llamadas: list[str] = []

    def _falso(carpeta_id: str, **kwargs: Any) -> dict[str, Any]:
        llamadas.append(carpeta_id)
        return {"texto": f"resumen de {carpeta_id}", "citations": []}

    monkeypatch.setattr(cliente, "analizar_rama", _falso)

    trabajo = encolar_analisis(
        db, tenant_id=tenant_id, carpetas=["a", "b", "c"], token_usuario="tok"
    )
    tanda = ejecutor_de(TIPO)(db, trabajo, 50)  # type: ignore[misc]

    assert tanda.avanzados == 1, "se ha comido más de una rama en la misma tanda"
    assert llamadas == ["a"]
    assert tanda.total == 3


def test_las_citas_vuelven_agrupadas_por_documento(
    db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    """Las del gestor son de FRAGMENTO: varias salen del mismo fichero. Pintarlas
    tal cual da una lista con el mismo documento cuatro veces, que parece un
    fallo y no lo es."""
    from crmcore.datos.trabajos import ejecutor_de
    from crmcore.documental import cliente
    from crmcore.documental.trabajos_analisis import TIPO, encolar_analisis

    def _falso(carpeta_id: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "texto": "resumen",
            "citations": [
                {"document_id": "doc-1", "relevance": 0.9, "fragment": "uno"},
                {"document_id": "doc-1", "relevance": 0.5, "fragment": "dos"},
                {"document_id": "doc-2", "relevance": 0.7, "fragment": "tres"},
            ],
        }

    monkeypatch.setattr(cliente, "analizar_rama", _falso)

    trabajo = encolar_analisis(db, tenant_id=tenant_id, carpetas=["a"], token_usuario="tok")
    tanda = ejecutor_de(TIPO)(db, trabajo, 10)  # type: ignore[misc]

    documentos = tanda.resultado["analisis"][0]["documentos"]
    assert len(documentos) == 2, f"las citas no se han agrupado: {documentos}"
    # Y por relevancia, que es lo único comparable entre resultados.
    assert documentos[0]["documento_id"] == "doc-1"
    # Y con cuántos fragmentos salieron de él, que es lo que explica la lista.
    assert documentos[0]["fragmentos"] == 2


def test_una_rama_que_falla_no_para_las_demas(db: Any, tenant_id: UUID, monkeypatch: Any) -> None:
    """Un corpus grande tiene carpetas con permisos raros y ficheros rotos."""
    from crmcore.datos.trabajos import ejecutor_de
    from crmcore.documental import cliente
    from crmcore.documental.trabajos_analisis import TIPO, encolar_analisis

    def _falso(carpeta_id: str, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("el gestor no contesta")

    monkeypatch.setattr(cliente, "analizar_rama", _falso)

    trabajo = encolar_analisis(db, tenant_id=tenant_id, carpetas=["a"], token_usuario="tok")
    tanda = ejecutor_de(TIPO)(db, trabajo, 10)  # type: ignore[misc]

    # Se consume igual: si no, el trabajo se quedaría reintentando la misma rama
    # eternamente.
    assert tanda.avanzados == 1
    assert tanda.fallidos == 1
    assert "no contesta" in tanda.errores[0]["motivo"]


def test_un_trabajo_sin_ramas_lo_dice(db: Any, tenant_id: UUID) -> None:
    """Devolver «hecho» sobre cero ramas deja a quien lo pidió esperando un
    resumen que no va a llegar."""
    from crmcore.datos.trabajos import Trabajo, ejecutor_de
    from crmcore.documental.trabajos_analisis import TIPO

    trabajo = Trabajo(tenant_id=tenant_id, tipo=TIPO, estado="encolado", entrada={})
    db.add(trabajo)
    db.flush()

    tanda = ejecutor_de(TIPO)(db, trabajo, 10)  # type: ignore[misc]
    assert tanda.avanzados == 0
    assert "ninguna rama" in tanda.resultado["motivo"]
