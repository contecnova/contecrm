"""RT-1 — Frontless: todo existe como servicio con contrato antes que como UI.

Cubre CRM-00.02.01.01 (todo lo que hace la UI es posible por API),
CRM-00.02.01.04 (OpenAPI generado del código) y CRM-00.02.03.01 (cero lógica de
negocio en la capa de presentación).

El catálogo lo pide en su primera restricción transversal, y la forma de que no
se quede en una declaración es comprobarlo:

  * Todo servicio publica su **OpenAPI** y ahí está todo lo que sabe hacer.
  * Ninguna ruta se queda **sin documentar**: un endpoint sin descripción es uno
    que solo sabe usar quien lo escribió.
  * Toda operación de escritura declara **qué devuelve**, para que un cliente
    headless no tenga que adivinar la forma de la respuesta.
  * El **catálogo mínimo de recursos** del Anexo A está cubierto por rutas
    reales para lo que la fase actual dice tener hecho.

Lo que esta prueba NO puede comprobar —y conviene decirlo— es que no exista una
funcionalidad **solo** en una interfaz: aquí todavía no hay interfaz. Cuando la
haya, el gate que hace falta es el que compara las llamadas que hace la UI con
las rutas públicas, y está anotado en el manual técnico como pendiente de la
fase 1.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SERVICIOS = sorted(
    p.name
    for p in (RAIZ / "services").iterdir()
    if p.is_dir() and not p.name.startswith("_") and (p / "main.py").exists()
)

# Rutas que no forman parte del contrato funcional.
INFRAESTRUCTURA = {"/health", "/health/live", "/health/ready", "/metrics"}


def _app(servicio: str) -> Any:
    """Carga la aplicación de un servicio sin levantar nada."""
    import os

    os.environ["SERVICE_NAME"] = servicio
    os.environ["BUS_BACKEND"] = "memoria"
    modulo = importlib.import_module(f"services.{servicio}.main")
    return modulo.app


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_cada_servicio_publica_su_contrato(servicio: str) -> None:
    """El OpenAPI existe, se genera del código y no está vacío."""
    esquema = _app(servicio).openapi()
    assert esquema["openapi"].startswith("3."), "se espera OpenAPI 3.x"
    funcionales = [r for r in esquema["paths"] if r not in INFRAESTRUCTURA]
    if servicio == "gateway":
        # El gateway es un proxy: su contrato es el de los servicios de detrás,
        # y su única ruta propia es el registro de servicios.
        assert "/api/v1/servicios" in esquema["paths"]
        return
    assert funcionales, f"«{servicio}» no publica ninguna ruta funcional"


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_toda_ruta_esta_documentada(servicio: str) -> None:
    """Resumen obligatorio en cada operación.

    Un endpoint sin descripción obliga a leer el código para usarlo, que es
    exactamente lo que un contrato debería evitar.
    """
    esquema = _app(servicio).openapi()
    sin_resumen: list[str] = []
    for ruta, metodos in esquema["paths"].items():
        if ruta in INFRAESTRUCTURA:
            continue
        for metodo, operacion in metodos.items():
            if metodo not in ("get", "post", "put", "patch", "delete"):
                continue
            if not (operacion.get("summary") or "").strip():
                sin_resumen.append(f"{metodo.upper()} {ruta}")
    assert not sin_resumen, f"Rutas sin resumen en «{servicio}»: {sin_resumen}"


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_los_errores_estan_declarados_en_el_contrato(servicio: str) -> None:
    """Toda operación declara al menos una respuesta de error.

    FastAPI documenta el 422 de validación solo; lo que se comprueba aquí es que
    ninguna operación declare únicamente el camino feliz, porque un cliente que
    no sabe qué errores esperar no puede tratarlos.
    """
    esquema = _app(servicio).openapi()
    solo_felices: list[str] = []
    for ruta, metodos in esquema["paths"].items():
        if ruta in INFRAESTRUCTURA:
            continue
        for metodo, operacion in metodos.items():
            if metodo not in ("post", "put", "patch", "delete"):
                continue
            codigos = set(operacion.get("responses", {}))
            if not any(c.startswith(("4", "5")) for c in codigos):
                solo_felices.append(f"{metodo.upper()} {ruta} → {sorted(codigos)}")
    assert (
        not solo_felices
    ), f"Operaciones de escritura sin errores declarados en «{servicio}»: {solo_felices}"


def test_el_anexo_a_esta_cubierto_para_lo_que_dice_estar_hecho() -> None:
    """Los recursos del Anexo A de la fase 0 tienen rutas reales.

    El Anexo A es la lista con la que se verifica que el sistema es headless de
    verdad. Aquí solo se exige lo de plataforma, que es lo que cubre la fase 0;
    los de ventas, servicio y marketing llegan con sus fases.
    """
    import yaml

    catalogo = yaml.safe_load(
        (RAIZ / "docs" / "catalogo" / "catalogo.yaml").read_text(encoding="utf-8")
    )
    # Correspondencia entre el nombre del recurso en el Anexo A y la ruta real.
    # Se declara porque el anexo usa nombres en inglés (es la convención de la
    # industria para un catálogo de API) y las rutas están en castellano.
    equivalencias = {
        "tenants": "/api/v1/tenants",
        "users": "/api/v1/usuarios",
        "roles": "/api/v1/roles",
        "metadata/objects": "/api/v1/metadata/objetos",
        "workflows": "/api/v1/procesos/definiciones",
        "workflow-instances": "/api/v1/instancias",
        "webhooks": "/api/v1/webhooks",
        "events": "/api/v1/eventos/catalogo",
        "feature-flags": "/api/v1/flags/{clave}",
        "quotas-usage": "/api/v1/tenants/{tenant_id}/consumo",
    }
    todas_las_rutas: set[str] = set()
    for servicio in SERVICIOS:
        todas_las_rutas |= set(_app(servicio).openapi()["paths"])

    faltan = [recurso for recurso, ruta in equivalencias.items() if ruta not in todas_las_rutas]
    assert not faltan, "Recursos del Anexo A previstos para la fase 0 sin ruta:\n  " + "\n  ".join(
        f"{r} → {equivalencias[r]}" for r in faltan
    )
    # Y que el anexo siga ahí completo, para que nadie lo recorte al implementarlo.
    assert len(catalogo["anexo_a_recursos"]["plataforma"]) >= 19


# Un tipo de objeto real de cada servicio, para las rutas que lo llevan dentro.
# Un objeto real de cada servicio que monta adjuntos, comentarios o documentos.
# Tiene que ser real: `{objeto_tipo}` es lo que decide el destino en esas rutas,
# y con un valor inventado el gateway no encuentra a nadie y el gate daría por
# rota una ruta que funciona.
_OBJETOS_DE = {"party": "cuenta", "sales": "oportunidad", "service": "caso"}
_OBJETO_POR_DEFECTO = "x"

# Rutas que el gateway NO reenvía: las sirve él juntando la de todos los
# servicios. Preguntarlas a uno solo daría una respuesta parcial presentada
# como completa, que es peor que no tenerlas.
# Rutas que cada servicio publica para sí mismo y que el gateway NO enruta,
# sino que **compone** preguntando a todos. Llegar a la de un servicio suelto no
# serviría de nada: media página de estado, o la mitad de un contrato que tiene
# los dos lados en servicios distintos.
_AGREGADAS_EN_EL_GATEWAY = {
    "/api/v1/estado",
    "/api/v1/estado/contratos",
    # El presupuesto de error lo compone el gateway (CRM-00.06.01.04): cada
    # servicio publica su consumo y solo el gateway sabe el tier contratado,
    # porque lo pregunta a `tenancy`.
    "/api/v1/estado/slo",
    # Si la instalación necesita la interfaz de referencia (CRM-00.02.03.02):
    # cada servicio se mide a sí mismo y el gateway junta los hallazgos, porque
    # «la UI es opcional» solo es verdad si lo es en todos.
    "/api/v1/estado/ui-referencia",
    # La presión de cada servicio se compone en el gateway: la de uno solo no
    # dice nada, porque lo que se aplaza depende del que esté peor (CRM-08.01.01.06).
    "/api/v1/estado/presion",
    # Las cuotas van POR MÓDULO, así que el consumo de uno solo es un trozo: el
    # gateway pregunta a todos y suma, diciendo cuáles no ha podido leer. Llegar
    # al de un servicio suelto daría un número que parece el total y no lo es.
    "/api/v1/estado/consumo",
    # Entrar en modo solo lectura **tiene que llegar a los catorce**: el modo
    # vive en memoria de cada proceso, así que ponerlo en uno dejaría los otros
    # trece escribiendo, y un modo degradado a medias deja un estado que nadie
    # sabe reconstruir después. El gateway lo reparte y dice a cuáles no ha
    # llegado — un servicio mudo sigue escribiendo, y eso hay que saberlo ahora.
    "/api/v1/estado/solo-lectura",
    "/api/v1/superficie",
}


def test_toda_ruta_publicada_es_alcanzable_por_el_gateway() -> None:
    """Una ruta que el gateway no sabe enrutar no existe para nadie de fuera.

    Este gate nació de un fallo real: las carpetas del expediente se publican en
    `/api/v1/adjuntos/carpetas/{objeto_tipo}`, y el gateway resolvía los adjuntos
    por el segmento siguiente al recurso dando por hecho que era un tipo de
    objeto. Buscaba uno llamado «carpetas», no lo encontraba y respondía 404. La
    funcionalidad estaba escrita, probada y documentada, y era inalcanzable.

    Comprobarlo ruta a ruta —y no manteniendo a mano una lista de prefijos— es
    lo que hace que el próximo recurso nuevo no repita el fallo: el día que
    alguien publique `/api/v1/loquesea` sin declararlo, esta prueba lo dice.
    """
    from services.gateway.rutas import servicio_de

    inalcanzables: list[str] = []

    # Quién publica cada ruta. Hace falta porque las fábricas transversales
    # —adjuntos, comentarios, documentos— montan la MISMA ruta en varios
    # servicios, y una que no lleva `{objeto_tipo}` no habla de ningún registro:
    # el estado del gestor, una búsqueda en el corpus, el árbol de carpetas. El
    # gateway manda a un dueño fijo y da igual cuál, porque esas preguntan al
    # gestor y no a la base del servicio.
    #
    # Se DEDUCE de las rutas y no se mantiene una lista. La había, y cada ruta
    # nueva sin registro quedaba en rojo hasta que alguien se acordaba de
    # apuntarla ahí — o sea que el gate pedía mantenimiento para no dar falsos
    # positivos, que es como los gates acaban desactivados.
    publicantes: dict[str, set[str]] = {}
    for servicio in SERVICIOS:
        if servicio == "gateway":
            continue
        for ruta in _app(servicio).openapi()["paths"]:
            publicantes.setdefault(ruta, set()).add(servicio)

    for servicio in SERVICIOS:
        if servicio == "gateway":
            continue
        for ruta in _app(servicio).openapi()["paths"]:
            if ruta in INFRAESTRUCTURA or not ruta.startswith("/api/"):
                continue
            if ruta in _AGREGADAS_EN_EL_GATEWAY:
                continue
            # Los parámetros se sustituyen por un valor cualquiera, salvo
            # `{objeto_tipo}`: ese SÍ decide el destino en los recursos que
            # cuelgan del registro —adjuntos, comentarios, documentos—, así que
            # se pone uno real del servicio. Poner «x» habría dado por rota una
            # ruta que funciona, que es la forma de que un gate deje de mirarse.
            concreta = "/".join(
                _OBJETOS_DE.get(servicio, _OBJETO_POR_DEFECTO)
                if p == "{objeto_tipo}"
                else "x"
                if p.startswith("{")
                else p
                for p in ruta.split("/")
            )
            destino = servicio_de(concreta)
            duenos = publicantes.get(ruta, set())
            if "{objeto_tipo}" not in ruta and len(duenos) > 1 and destino in duenos:
                # No es de ningún registro y la publican varios: basta con que
                # llegue a alguno de ellos.
                continue
            if destino != servicio:
                inalcanzables.append(f"{servicio}: {ruta} → {destino or 'ningún servicio'}")

    assert not inalcanzables, (
        "Rutas publicadas que el gateway no enruta a su servicio:\n  "
        + "\n  ".join(sorted(inalcanzables))
    )
