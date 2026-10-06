"""Los últimos módulos del núcleo que no importaba nadie
(CRM-00.02.01.13, CRM-00.05.01.09, CRM-00.02.04.05, CRM-00.02.01.03).

**Peticiones compuestas.** Un cliente que crea una cuenta, le añade un contacto y
le abre una oportunidad hacía tres llamadas y tres viajes de red. Desde un móvil
con mala cobertura, eso son tres ocasiones de quedarse a medias — y quedarse a
medias deja una cuenta sin contacto que alguien tendrá que limpiar a mano. El
módulo resolvía el tope, las referencias y la validación previa, y no lo
importaba nadie.

**Acceso contextual.** El ABAC decide por atributos del usuario y del registro;
esto añade los del momento —desde dónde, con qué, a qué hora—, que son los que
cambian entre una sesión legítima y la misma credencial usada por otro. Se
comprueba en cada petición y no al entrar, porque el caso que se cubre es
exactamente la credencial que sigue viva.

**Caché de respuestas.** Cachear es fácil; invalidar es el problema. Una caché
que solo caduca por tiempo sirve una respuesta vieja durante todo el plazo, y el
usuario que acaba de cambiar algo ve su propio cambio desaparecer — la queja más
difícil de reproducir que hay, porque a los cinco minutos ya no pasa.

**Transporte gRPC.** `GRPC_ACTIVO` existía, estaba documentado y no lo leía
nadie: encenderlo no encendía nada. Un ajuste que no hace nada es peor que no
tenerlo, porque quien lo pone cree que ya está.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[2]


# ── Acceso contextual (CRM-00.05.01.09) ───────────────────────────────────


def test_una_senal_que_no_llega_no_bloquea() -> None:
    """Una IP que no llega porque hay un proxy mal configurado delante dejaría
    fuera a toda la plantilla, y eso es una caída con otro nombre."""
    from crmcore.authz import contexto as ctx

    regla = ctx.ReglaContextual(nombre="solo oficina", redes=("10.0.0.0/8",))
    # Sin IP, la regla que depende de ella no aplica.
    ctx.exigir([regla], ctx.Contexto(ip=""))


def test_desde_fuera_de_la_red_declarada_no_se_entra() -> None:
    from crmcore.authz import contexto as ctx
    from crmcore.errors import Prohibido

    regla = ctx.ReglaContextual(nombre="solo oficina", redes=("10.0.0.0/8",))
    ctx.exigir([regla], ctx.Contexto(ip="10.1.2.3"))

    with pytest.raises(Prohibido):
        ctx.exigir([regla], ctx.Contexto(ip="200.1.2.3"))


def test_una_lista_vacia_no_bloquea_a_todo_el_mundo() -> None:
    """Es la forma más rápida de dejar fuera a todos el día que alguien crea una
    regla sin rellenarla."""
    from crmcore.authz import contexto as ctx

    ctx.exigir(
        [ctx.ReglaContextual(nombre="vacía")],
        ctx.Contexto(ip="200.1.2.3", pais="BR", momento=datetime.now(timezone.utc)),
    )


def test_la_puerta_comprueba_el_contexto_en_cada_peticion() -> None:
    """Comprobarlo solo al entrar deja la sesión abierta cuando las condiciones
    dejan de cumplirse, que es exactamente el caso que se quiere cubrir."""
    fuente = (RAIZ / "services" / "gateway" / "api.py").read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.AsyncFunctionDef) and nodo.name == "proxy_api":
            llamadas = {
                getattr(n.func, "attr", None) for n in ast.walk(nodo) if isinstance(n, ast.Call)
            }
            assert "reglas_contextuales" in llamadas
            assert "exigir" in llamadas
            return
    raise AssertionError("no se ha encontrado la ruta de proxy: el recorrido no mira")


# ── Peticiones compuestas (CRM-00.02.01.13) ───────────────────────────────


def test_una_referencia_hacia_delante_se_rechaza_antes_de_ejecutar_nada() -> None:
    """Descubierta a mitad deja la transacción abortada y al cliente con un error
    que no dice cuál de sus operaciones estaba mal."""
    from crmcore.errors import ErrorValidacion
    from crmcore.http import compuesto

    with pytest.raises(ErrorValidacion) as fallo:
        compuesto.validar(
            [
                {"metodo": "POST", "ruta": "/a", "cuerpo": {"ref": "$2.id"}},
                {"metodo": "POST", "ruta": "/b"},
            ]
        )
    assert fallo.value.error_code == "compuesto.referencia_adelantada"


def test_una_peticion_compuesta_vacia_no_hace_nada_y_se_dice() -> None:
    from crmcore.errors import ErrorValidacion
    from crmcore.http import compuesto

    with pytest.raises(ErrorValidacion) as fallo:
        compuesto.validar([])
    assert fallo.value.error_code == "compuesto.vacia"


def test_un_campo_que_no_vino_se_deja_visible_y_no_vacio() -> None:
    """Poner `None` crearía la fila con el campo vacío y nadie lo notaría hasta
    semanas después; dejarlo visible hace que falle la validación del recurso,
    que es donde tiene que fallar."""
    from crmcore.http import compuesto

    resuelto = compuesto.resolver({"cuenta_id": "$1.id", "otro": "$1.no_existe"}, [{"id": "abc"}])
    assert resuelto["cuenta_id"] == "abc"
    assert resuelto["otro"] == "$1.no_existe"


def test_la_sesion_compartida_hace_que_sea_una_transaccion(db: Any) -> None:
    """Si cada sub-petición abriera la suya, «todo o nada» serían tres
    escrituras independientes con otro nombre."""
    from crmcore.http.deps import _sesion_compartida, compartir_sesion, soltar_sesion

    assert _sesion_compartida.get() is None
    testigo = compartir_sesion(db)
    try:
        assert _sesion_compartida.get() is db
    finally:
        soltar_sesion(testigo)
    # Y se suelta: sin restaurar, la siguiente petición de la misma tarea
    # seguiría escribiendo en una sesión ya cerrada.
    assert _sesion_compartida.get() is None


def test_toda_aplicacion_con_base_sirve_peticiones_compuestas() -> None:
    """Montarlo en cada `main.py` sería «funciona en los que alguien se acordó»."""
    import importlib

    faltan = []
    for servicio in ("sales", "party", "service", "marketing", "tenancy", "identity"):
        app = importlib.import_module(f"services.{servicio}.main").app
        if f"/api/v1/{servicio}/compuesto" not in app.openapi()["paths"]:
            faltan.append(servicio)
    assert not faltan, f"sin peticiones compuestas: {faltan}"


# ── Caché de respuestas (CRM-00.02.04.05) ─────────────────────────────────


def test_subir_la_generacion_invalida_sin_tocar_ninguna_entrada() -> None:
    """Las viejas siguen ahí hasta que caduquen, pero ya no las encuentra
    nadie."""
    from crmcore.cache.respuestas import Politica, clave, invalidar_por_evento

    tenant = uuid4()
    politica = Politica(nombre="listado", ttl_s=60, invalida_con=("account.updated",))
    antes = clave(politica, tenant_id=tenant, usuario_id=None, partes={"pagina": 1})

    invalidar_por_evento("account.updated", tenant)
    despues = clave(politica, tenant_id=tenant, usuario_id=None, partes={"pagina": 1})

    assert antes != despues


def test_una_politica_que_solo_caduca_por_tiempo_se_ve() -> None:
    """Una caché que se creyó invalidada por evento y solo caduca es la que sirve
    datos viejos sin que nadie lo sepa."""
    from crmcore.cache.respuestas import Politica, politicas_sin_invalidacion

    salida = politicas_sin_invalidacion(
        [
            Politica(nombre="con", ttl_s=60, invalida_con=("x",)),
            Politica(nombre="sin", ttl_s=60),
        ]
    )
    assert salida == ["sin"]


def test_el_servicio_invalida_con_cada_evento_que_recibe() -> None:
    """Sin esto la generación no sube jamás y la invalidación por evento no
    existe, aunque el módulo esté entero."""
    fuente = (RAIZ / "packages" / "crmcore" / "crmcore" / "service.py").read_text(encoding="utf-8")
    # Hubo DOS copias de este recorrido: la del módulo de la caché, que no
    # llamaba nadie, y una suelta aquí que leía `type` y no `tipo`. Se quedó la
    # del módulo, y esto apunta a ella.
    assert '("*", consumir_invalidacion,' in fuente
    assert "_invalidar_cache" not in fuente, "ha vuelto la copia suelta"

    cache = (RAIZ / "packages" / "crmcore" / "crmcore" / "cache" / "respuestas.py").read_text(
        encoding="utf-8"
    )
    arbol = ast.parse(cache)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.AsyncFunctionDef) and nodo.name == "consumir_invalidacion":
            llamadas = {
                getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                for n in ast.walk(nodo)
                if isinstance(n, ast.Call)
            }
            assert "invalidar_por_evento" in llamadas
            return
    raise AssertionError("no se ha encontrado el consumidor de invalidación")


# ── Transporte gRPC (CRM-00.02.01.03) ─────────────────────────────────────


def test_el_ajuste_de_grpc_ya_no_es_decorativo() -> None:
    """Existía, estaba documentado y no lo leía nadie: encenderlo no encendía
    nada, que es peor que no tenerlo."""
    fuente = (RAIZ / "packages" / "crmcore" / "crmcore" / "service.py").read_text(encoding="utf-8")
    assert "grpc_activo" in fuente
    assert "_manejadores_rpc" in fuente


def test_el_contrato_exige_los_cinco_metodos() -> None:
    """Publicar un método que contesta «no implementado» es peor que no
    publicarlo: el que integra lo descubre en su despliegue."""
    from crmcore.rpc.servidor import METODOS
    from crmcore.service import _manejadores_rpc

    class _App:
        pass

    manejadores = _manejadores_rpc(_App())
    assert set(METODOS) <= set(manejadores)


def test_un_objeto_que_no_es_de_este_servicio_se_dice() -> None:
    """Adivinar aquí significa servir «contacto» a quien pidió «contactos»."""
    from crmcore.errors import NoEncontrado
    from crmcore.http.listados import ruta_de_objeto

    import services.sales.api  # noqa: F401 — registra los recursos

    assert ruta_de_objeto("oportunidad").endswith("/opportunities")
    with pytest.raises(NoEncontrado):
        ruta_de_objeto("lo_que_sea")


def _uuid() -> UUID:
    return uuid4()
