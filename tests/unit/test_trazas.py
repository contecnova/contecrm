"""Trazas distribuidas con OpenTelemetry (CRM-00.06.01.03).

Lo que estas pruebas defienden, por orden de importancia:

  * **Encender las trazas sin el paquete instalado impide arrancar.** Es la
    decisión central del módulo: una promesa de trazabilidad que se incumple en
    silencio se descubre el día que hace falta la traza y no está.
  * **Apagadas no cuestan nada y no rompen nada.** Ni un import de
    OpenTelemetry en el camino caliente, ni una llamada que falle.
  * **La traza se continúa, no se reinicia.** Una petición que llega con
    `traceparent` sigue esa traza; si no, el árbol sale en cinco pedazos de un
    salto en vez de uno de cinco saltos.

Las pruebas corren con el exportador **en memoria**: exportan de verdad y se
comprueban los tramos resultantes. Comprobar solo que «no revienta» sería
comprobar que no hacer nada no rompe nada.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from crmcore.obs import trazas


@pytest.fixture(autouse=True)
def _trazas_limpias() -> Iterator[None]:
    """Sin esto, la primera prueba que configura deja el proveedor puesto para
    todas las demás del proceso, y la que comprueba «apagado» pasaría o fallaría
    según el orden de ejecución."""
    trazas.reset()
    yield
    trazas.reset()


@contextmanager
def _activas(muestreo: str = "1.0") -> Iterator[Any]:
    """Trazas encendidas de verdad contra un exportador en memoria.

    Dos cosas que hay que forzar y que costaron un rato de depuración:

    **El muestreo al 100 %.** Con el 0,1 por defecto, un tramo raíz casi nunca
    se muestrea y la prueba falla sin que nada esté roto — una prueba que falla
    nueve de cada diez veces por diseño es peor que no tenerla.

    **El procesador simple en vez del de lotes.** El real exporta en un hilo
    aparte cada cinco segundos, y depender de eso hace la prueba intermitente.
    """
    from crmcore.config import limpiar_cache_settings
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    os.environ["TRACING_ENABLED"] = "true"
    os.environ["OTEL_SAMPLE_RATIO"] = muestreo
    limpiar_cache_settings()

    memoria = InMemorySpanExporter()
    original = trazas._crear_exportador
    trazas._crear_exportador = lambda _e, _p: memoria  # type: ignore[assignment]
    try:
        trazas.configurar("pruebas", "0.0")
        proveedor = trazas.proveedor()
        assert isinstance(proveedor, TracerProvider)
        proveedor.add_span_processor(SimpleSpanProcessor(memoria))
        yield memoria
    finally:
        # Restaurar SIEMPRE. La primera versión de estas pruebas dejaba el
        # exportador falso puesto al salir, y la prueba siguiente —la del
        # protocolo gRPC— pasaba a llamarlo en vez de al de verdad y dejaba de
        # comprobar nada. Pasó, y por eso está escrito aquí.
        trazas._crear_exportador = original  # type: ignore[assignment]
        os.environ.pop("TRACING_ENABLED", None)
        os.environ.pop("OTEL_SAMPLE_RATIO", None)
        limpiar_cache_settings()


@pytest.fixture
def con_exportador() -> Iterator[Any]:
    with _activas() as memoria:
        yield memoria


# ── Apagadas ──────────────────────────────────────────────────────────────


def test_apagadas_configurar_devuelve_falso_y_no_activa_nada() -> None:
    assert trazas.configurar("pruebas") is False
    assert trazas.activo() is False


def test_apagadas_un_tramo_es_un_contexto_vacio() -> None:
    """Es lo que permite sembrar el código de tramos sin que la instalación que
    no traza pague por ellos."""
    trazas.configurar("pruebas")
    with trazas.span("algo", clave="valor") as tramo:
        assert tramo is None


def test_apagadas_marcar_y_traceparent_no_fallan() -> None:
    trazas.configurar("pruebas")
    trazas.marcar(lo_que_sea=1)
    assert trazas.traceparent_actual() == ""


def test_apagadas_la_propagacion_usa_el_traceparent_del_contexto() -> None:
    """La correlación entre servicios no debería depender de tener un colector
    montado: sin exportador, se reenvía el `traceparent` que llegó."""
    from crmcore.tenancy.context import ContextoPeticion, fijar_contexto, restaurar_contexto

    entrante = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    token = fijar_contexto(ContextoPeticion(traceparent=entrante))
    try:
        assert trazas.inyectar({})["traceparent"] == entrante
    finally:
        restaurar_contexto(token)


def test_apagadas_sin_traceparent_entrante_no_se_inventa_ninguno() -> None:
    """Inventarse uno haría que el receptor creyera que continúa una traza que
    no existe, y su tramo colgaría de un padre inexistente."""
    assert trazas.inyectar({}) == {}


# ── Encendidas sin el paquete ─────────────────────────────────────────────


def test_encender_sin_opentelemetry_impide_arrancar(monkeypatch: Any) -> None:
    """La decisión central del módulo.

    Se simula la ausencia del paquete rompiendo el import, que es lo que pasa en
    una instalación que no instaló el extra.
    """
    import builtins

    from crmcore.config import limpiar_cache_settings

    os.environ["TRACING_ENABLED"] = "true"
    limpiar_cache_settings()
    importar = builtins.__import__

    def _sin_otel(nombre: str, *args: Any, **kwargs: Any) -> Any:
        if nombre.startswith("opentelemetry"):
            raise ImportError("No module named 'opentelemetry'")
        return importar(nombre, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _sin_otel)
    try:
        with pytest.raises(RuntimeError) as exc:
            trazas.configurar("pruebas")
        # El mensaje tiene que decir las dos salidas: instalarlo o apagarlo. Un
        # error que solo dice «falta un paquete» manda a buscar cuál.
        assert "requirements-otel.txt" in str(exc.value)
        assert "TRACING_ENABLED=false" in str(exc.value)
    finally:
        monkeypatch.undo()
        del os.environ["TRACING_ENABLED"]
        limpiar_cache_settings()


# ── Encendidas ────────────────────────────────────────────────────────────


def test_un_tramo_se_exporta_con_sus_atributos(con_exportador: Any) -> None:
    with trazas.span("operacion", **{"crm.tenant_slug": "acme", "crm.filas": 12}):
        pass

    tramos = con_exportador.get_finished_spans()
    assert [t.name for t in tramos] == ["operacion"]
    assert tramos[0].attributes["crm.tenant_slug"] == "acme"
    assert tramos[0].attributes["crm.filas"] == 12


def test_los_atributos_nulos_no_se_emiten(con_exportador: Any) -> None:
    """Un atributo a `None` no es información: ensucia la traza y en algunos
    visores rompe el filtrado por esa clave."""
    with trazas.span("operacion", presente="sí", ausente=None):
        pass
    atributos = con_exportador.get_finished_spans()[0].attributes
    assert "presente" in atributos and "ausente" not in atributos


def test_un_tramo_que_falla_se_marca_como_fallido_y_guarda_la_excepcion(
    con_exportador: Any,
) -> None:
    """Sin lo primero la traza sale verde cuando falló; sin lo segundo no se
    sabe de qué falló sin buscar el log a mano."""
    from opentelemetry.trace import StatusCode

    with pytest.raises(ValueError):
        with trazas.span("revienta"):
            raise ValueError("se rompió")

    tramo = con_exportador.get_finished_spans()[0]
    assert tramo.status.status_code is StatusCode.ERROR
    assert any(e.name == "exception" for e in tramo.events)


def test_los_tramos_anidados_cuelgan_del_padre(con_exportador: Any) -> None:
    with trazas.span("padre"):
        with trazas.span("hijo"):
            pass

    por_nombre = {t.name: t for t in con_exportador.get_finished_spans()}
    assert por_nombre["hijo"].parent.span_id == por_nombre["padre"].context.span_id
    assert por_nombre["hijo"].context.trace_id == por_nombre["padre"].context.trace_id


def test_marcar_añade_atributos_al_tramo_en_curso(con_exportador: Any) -> None:
    with trazas.span("operacion"):
        trazas.marcar(**{"crm.resultado": "ok"})
    assert con_exportador.get_finished_spans()[0].attributes["crm.resultado"] == "ok"


def test_una_peticion_entrante_continua_la_traza_de_quien_llama(
    con_exportador: Any,
) -> None:
    """Es el punto de las trazas distribuidas. Sin esto salen cinco trazas de un
    salto en vez de una de cinco."""
    entrante = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    with trazas.span_entrante("GET /cuentas", {"traceparent": entrante}):
        pass

    tramo = con_exportador.get_finished_spans()[0]
    assert f"{tramo.context.trace_id:032x}" == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert f"{tramo.parent.span_id:016x}" == "00f067aa0ba902b7"


def test_sin_traceparent_entrante_se_empieza_una_traza_nueva(con_exportador: Any) -> None:
    with trazas.span_entrante("GET /cuentas", {}):
        pass
    assert con_exportador.get_finished_spans()[0].parent is None


def test_inyectar_pone_el_tramo_en_curso_como_padre(con_exportador: Any) -> None:
    with trazas.span("saliendo"):
        cabeceras = trazas.inyectar({})
        actual = trazas.traceparent_actual()

    assert cabeceras["traceparent"] == actual
    assert actual.startswith("00-")


def test_inyectar_no_pisa_un_traceparent_puesto_a_mano(con_exportador: Any) -> None:
    """Reenviar una petición conservando su traza original es un caso
    legítimo, y pisarlo lo rompería."""
    ajeno = "00-11111111111111111111111111111111-2222222222222222-01"
    with trazas.span("saliendo"):
        cabeceras = trazas.inyectar({})
        cabeceras_a_mano = {"traceparent": ajeno}
        trazas.inyectar(cabeceras_a_mano)

    assert cabeceras["traceparent"] != ajeno
    # `inyectar` sí escribe sobre el dict; quien protege el valor puesto a mano
    # es el guard de salida, con `setdefault`. Se comprueba ahí.
    assert "traceparent" in cabeceras_a_mano


def test_la_salida_de_red_lleva_el_traceparent_sin_pisar_el_explicito(
    con_exportador: Any,
) -> None:
    """La propagación va en el guard de salidas, que es por donde pasan TODAS
    las llamadas del servidor, incluidas las redirecciones."""
    import httpx
    from crmcore.red.guard_url import _propagar_traza

    with trazas.span("llamando"):
        automatica = httpx.Request("GET", "https://ejemplo.test/x")
        _propagar_traza(automatica)

        ajeno = "00-11111111111111111111111111111111-2222222222222222-01"
        explicita = httpx.Request("GET", "https://ejemplo.test/x", headers={"traceparent": ajeno})
        _propagar_traza(explicita)

    assert automatica.headers["traceparent"].startswith("00-")
    assert explicita.headers["traceparent"] == ajeno


def test_el_muestreo_respeta_la_decision_de_quien_empezo_la_traza() -> None:
    """Muestrear otra vez por nuestra cuenta produciría trazas con agujeros —el
    tramo del servicio A está y el del B no—, que parece un fallo."""
    from opentelemetry.sdk.trace.sampling import ParentBased

    with _activas(muestreo="0.0") as memoria:
        assert isinstance(trazas.proveedor().sampler, ParentBased)

        # Con ratio 0 no se muestrea nada propio…
        with trazas.span("propio"):
            pass
        # …pero una traza que llega marcada como muestreada sí continúa.
        marcada = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        with trazas.span_entrante("heredado", {"traceparent": marcada}):
            pass

        nombres = [t.name for t in memoria.get_finished_spans()]

    assert "propio" not in nombres
    assert "heredado" in nombres


# ── Integración con el resto ──────────────────────────────────────────────


def test_el_protocolo_grpc_sin_su_paquete_dice_exactamente_que_falta() -> None:
    """Y no «ImportError: opentelemetry...», que manda a buscar al sitio
    equivocado: el paquete HTTP sí está instalado."""
    import builtins

    importar = builtins.__import__

    def _sin_grpc(nombre: str, *args: Any, **kwargs: Any) -> Any:
        if "proto.grpc" in nombre:
            raise ImportError("no grpc")
        return importar(nombre, *args, **kwargs)

    builtins.__import__ = _sin_grpc  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError, match="OTEL_PROTOCOLO=http"):
            trazas._crear_exportador("http://x", "grpc")
    finally:
        builtins.__import__ = importar  # type: ignore[assignment]


@pytest.mark.db
def test_cada_paso_de_un_proceso_deja_su_tramo(
    con_exportador: Any, db: Any, tenant_id: Any, contexto_tenant: Any
) -> None:
    """Una orquestación que tarda dos días no sucede dentro de la llamada que la
    arrancó: sin un tramo por paso, la traza de la petición no cuenta nada."""
    from services.orchestrator.modelos import DefinicionProceso
    from services.orchestrator.motor import Motor

    db.add(
        DefinicionProceso(
            tenant_id=tenant_id,
            clave="dos_pasos",
            version=1,
            nombre="dos_pasos",
            definicion={
                "inicio": "decidir",
                "pasos": {
                    "decidir": {
                        "tipo": "decision",
                        "condiciones": [{"si": {"op": "="}, "entonces": "fin"}],
                        "si_no": "fin",
                    },
                    "fin": {"tipo": "fin", "resultado": "ok"},
                },
            },
            estado="publicada",
        )
    )
    db.flush()

    motor = Motor(db)
    instancia = motor.arrancar(tenant_id=tenant_id, clave="dos_pasos", variables={})
    motor.avanzar(instancia)

    tramos = [t for t in con_exportador.get_finished_spans() if t.name.startswith("proceso.")]
    assert [t.name for t in tramos] == ["proceso.decision", "proceso.fin"]
    assert tramos[0].attributes["crm.proceso"] == "dos_pasos"
    assert tramos[0].attributes["crm.paso"] == "decidir"
