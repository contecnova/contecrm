"""El árbol de carpetas del corpus, visto desde el CRM (RT-5).

Lo que se defiende aquí es lo que se rompe en silencio si nadie lo mira:

  * **El área se resuelve por su NOMBRE.** Fijar su identificador en la
    configuración habría funcionado en el primer tenant y habría mandado los
    documentos de los otros dos a un área que no es la suya — o a ninguna.
  * **La carpeta de un registro se resuelve una vez.** Volver a resolverla por
    su nombre crearía una segunda carpeta al lado el día que alguien renombre la
    primera, con los documentos repartidos entre las dos.
  * **Colocar el documento no puede impedir enlazarlo.** El enlace es del CRM y
    vale por sí solo; que no se pueda registrar un contrato en una cuenta porque
    el corpus está en mantenimiento sería la dependencia que este diseño evita.

Se prueba contra un transporte HTTP simulado y no contra dobles del cliente: lo
que ha fallado cinco veces en esta integración ha sido el CONTRATO —ruta,
autenticación, número de pasos, nombres de campo— y un doble del cliente fija la
suposición, no lo que el otro lado publica. Que las rutas de aquí son las que
contecmind declara lo comprueba aparte `test_contratos_vecinos.py`.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest
from crmcore.documental import cliente
from crmcore.errors import NoDisponible


@pytest.fixture
def dms_activo() -> Any:
    from crmcore.config import limpiar_cache_settings

    previo = dict(os.environ)
    os.environ.update(
        DMS_ENABLED="true",
        DMS_BASE_URL="https://dms.ejemplo.test",
        DMS_CLIENT_ID="crm",
        DMS_CLIENT_SECRET="x",
        DMS_AREA_NOMBRE="",
    )
    limpiar_cache_settings()
    yield
    os.environ.clear()
    os.environ.update(previo)
    limpiar_cache_settings()


class _Gestor:
    """Un contecmind de mentira, con su árbol y sus llamadas contadas."""

    def __init__(self, areas: list[dict[str, Any]]) -> None:
        self.areas = areas
        self.carpetas: list[dict[str, Any]] = []
        self.llamadas: list[tuple[str, str]] = []
        self.movidos: list[tuple[str, str | None]] = []
        self._siguiente = 0

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        ruta = peticion.url.path
        self.llamadas.append((peticion.method, ruta))
        if ruta == "/api/v1/areas":
            return httpx.Response(200, json={"items": self.areas})
        if ruta == "/api/v1/folders" and peticion.method == "GET":
            padre = peticion.url.params.get("parent_id")
            hijas = [c for c in self.carpetas if c["parent_id"] == (padre or None)]
            return httpx.Response(200, json={"items": hijas})
        if ruta == "/api/v1/folders" and peticion.method == "POST":
            import json as _json

            datos = _json.loads(peticion.content)
            self._siguiente += 1
            carpeta = {
                "id": f"c{self._siguiente}",
                "name": datos["name"],
                "parent_id": datos.get("parent_id"),
                "area_id": datos["area_id"],
            }
            self.carpetas.append(carpeta)
            return httpx.Response(200, json=carpeta)
        if ruta.endswith("/move"):
            import json as _json

            documento = ruta.split("/")[-2]
            self.movidos.append((documento, _json.loads(peticion.content).get("folder_id")))
            return httpx.Response(204)
        return httpx.Response(404, json={"detail": "no"})


@pytest.fixture
def gestor(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _montar(areas: list[dict[str, Any]]) -> _Gestor:
        g = _Gestor(areas)
        import contextlib

        @contextlib.contextmanager
        def _fabrica(**_: Any) -> Any:
            with httpx.Client(transport=httpx.MockTransport(g)) as cli:
                yield cli

        monkeypatch.setattr("crmcore.red.cliente_seguro", _fabrica)
        return g

    return _montar


# ── El área ───────────────────────────────────────────────────────────────


def test_con_una_sola_area_no_hay_nada_que_configurar(dms_activo: Any, gestor: Any) -> None:
    g = gestor([{"id": "a1", "name": "Corpus"}])
    assert cliente.carpetas(token_usuario="t") == []
    assert ("GET", "/api/v1/areas") in g.llamadas


def test_con_varias_areas_y_ninguna_elegida_se_dice_cuales_hay(
    dms_activo: Any, gestor: Any
) -> None:
    """Repartir los documentos en la que tocara sería peor que no guardarlos."""
    gestor([{"id": "a1", "name": "Corpus"}, {"id": "a2", "name": "Calidad"}])
    with pytest.raises(NoDisponible) as exc:
        cliente.carpetas(token_usuario="t")
    assert exc.value.error_code == "documental.area_ambigua"
    assert set(exc.value.detalle["visibles"]) == {"Corpus", "Calidad"}


def test_el_area_elegida_se_busca_por_nombre(dms_activo: Any, gestor: Any) -> None:
    """Por nombre y no por identificador: el id de un área es de UN tenant."""
    from crmcore.config import limpiar_cache_settings

    os.environ["DMS_AREA_NOMBRE"] = "calidad"  # y sin distinguir mayúsculas
    limpiar_cache_settings()
    g = gestor([{"id": "a1", "name": "Corpus"}, {"id": "a2", "name": "Calidad"}])
    cliente.carpetas(token_usuario="t")
    pedida = [ll for ll in g.llamadas if ll[1] == "/api/v1/folders"]
    assert pedida, "no se llegó a pedir el árbol"


def test_un_area_elegida_que_el_usuario_no_ve_se_dice_con_su_nombre(
    dms_activo: Any, gestor: Any
) -> None:
    from crmcore.config import limpiar_cache_settings

    os.environ["DMS_AREA_NOMBRE"] = "Confidencial"
    limpiar_cache_settings()
    gestor([{"id": "a1", "name": "Corpus"}])
    with pytest.raises(NoDisponible) as exc:
        cliente.carpetas(token_usuario="t")
    assert exc.value.error_code == "documental.area_no_encontrada"


# ── La carpeta de un registro ─────────────────────────────────────────────


def test_la_carpeta_de_un_registro_se_crea_tramo_a_tramo(dms_activo: Any, gestor: Any) -> None:
    g = gestor([{"id": "a1", "name": "Corpus"}])
    carpeta = cliente.carpeta_de_registro(objeto="cuenta", etiqueta="ACME", token_usuario="t")
    assert carpeta
    assert [c["name"] for c in g.carpetas] == ["cuenta", "ACME"]
    # La segunda cuelga de la primera y no de la raíz.
    assert g.carpetas[1]["parent_id"] == g.carpetas[0]["id"]


def test_la_segunda_vez_no_crea_otra_carpeta(dms_activo: Any, gestor: Any) -> None:
    """Es lo que evita acabar con «ACME» y «ACME» colgando del mismo sitio."""
    g = gestor([{"id": "a1", "name": "Corpus"}])
    primera = cliente.carpeta_de_registro(objeto="cuenta", etiqueta="ACME", token_usuario="t")
    segunda = cliente.carpeta_de_registro(objeto="cuenta", etiqueta="ACME", token_usuario="t")
    assert primera == segunda
    assert len(g.carpetas) == 2


def test_una_carpeta_que_solo_difiere_en_mayusculas_es_la_misma(
    dms_activo: Any, gestor: Any
) -> None:
    """Para quien la mira son la misma; crear la segunda reparte los documentos."""
    g = gestor([{"id": "a1", "name": "Corpus"}])
    cliente.carpeta_de_registro(objeto="cuenta", etiqueta="ACME", token_usuario="t")
    cliente.carpeta_de_registro(objeto="cuenta", etiqueta="acme", token_usuario="t")
    assert len(g.carpetas) == 2


def test_sin_crear_devuelve_nada_y_no_toca_el_gestor(dms_activo: Any, gestor: Any) -> None:
    g = gestor([{"id": "a1", "name": "Corpus"}])
    assert (
        cliente.carpeta_de_registro(
            objeto="cuenta", etiqueta="ACME", token_usuario="t", crear=False
        )
        is None
    )
    assert not g.carpetas


def test_la_plantilla_de_la_jerarquia_es_configuracion(dms_activo: Any, gestor: Any) -> None:
    """Unos quieren `Clientes/ACME` y otros `2026/Clientes/ACME`."""
    from crmcore.config import limpiar_cache_settings

    os.environ["DMS_CARPETA_PLANTILLA"] = "2026/Clientes/{registro}"
    limpiar_cache_settings()
    g = gestor([{"id": "a1", "name": "Corpus"}])
    cliente.carpeta_de_registro(objeto="cuenta", etiqueta="ACME", token_usuario="t")
    assert [c["name"] for c in g.carpetas] == ["2026", "Clientes", "ACME"]


# ── Las citas de un análisis ──────────────────────────────────────────────


def test_las_citas_se_agrupan_por_documento() -> None:
    """Son de FRAGMENTO: sin agrupar, el mismo documento sale cuatro veces."""
    citas = [
        {"document_id": "d1", "document_title": "Contrato", "relevance": 0.4, "chunk_id": "c1"},
        {"document_id": "d1", "document_title": "Contrato", "relevance": 0.9, "chunk_id": "c2"},
        {"document_id": "d2", "document_title": "Anexo", "relevance": 0.6, "chunk_id": "c3"},
    ]
    salida = cliente.documentos_citados(citas)
    assert [d["documento_id"] for d in salida] == ["d1", "d2"]
    # Se queda la relevancia MAYOR del documento, no la última ni la media.
    assert salida[0]["relevancia"] == 0.9
    assert salida[0]["fragmentos"] == 2


def test_una_cita_huerfana_se_marca_y_no_se_esconde() -> None:
    """Esconderla haría parecer el resumen menos fundado de lo que dijo ser."""
    salida = cliente.documentos_citados(
        [{"document_id": "d1", "relevance": 0.5, "is_orphan": True}]
    )
    assert salida[0]["huerfano"] is True


def test_una_cita_sin_documento_no_inventa_una_fila() -> None:
    assert cliente.documentos_citados([{"chunk_id": "c1", "relevance": 0.5}]) == []


# ── Pedir un análisis que no existe ───────────────────────────────────────


def test_solo_se_puede_pedir_resumen_o_conceptos(dms_activo: Any, gestor: Any) -> None:
    from crmcore.errors import ErrorValidacion

    gestor([{"id": "a1", "name": "Corpus"}])
    with pytest.raises(ErrorValidacion):
        cliente.analizar_rama("c1", token_usuario="t", que="loquesea")
