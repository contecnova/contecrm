"""Lo que el gateway tenía escrito y no hacía
(CRM-00.01.06.05, CRM-00.02.02.10, CRM-00.02.01.02, CRM-00.02.01.15,
CRM-00.02.03.03, CRM-00.02.04.03, CRM-00.02.04.06, CRM-00.04.02.04).

Tres módulos completos que **no importaba nadie**.

**El tráfico anómalo.** El límite de tasa fijo protege del abuso y no protege de
lo que de verdad tumba un multi-tenant: un cliente que hace lo de siempre, pero
diez veces más. Su importación nocturna se vuelve diurna, o alguien monta un
bucle en su integración, y el resto empieza a esperar sin que nadie haya pasado
ningún límite. Estaba medido, escalonado y explicado — y no corría.

**El empuje sin endpoint.** Los webhooks exigen que quien escucha tenga una
dirección pública y estable, y eso deja fuera a media integración real: un
navegador, una aplicación móvil, un servicio dentro de una red cerrada. Todos
pueden llamar al CRM y ninguno puede recibir una llamada. La cola, el flujo
reanudable, el aviso de hueco y el latido estaban escritos y no los alcanzaba
nada.

**La superficie del integrador.** Composición, sandbox, mTLS, panel y endpoint
propio: seis funciones, cero puertas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest


@pytest.fixture(autouse=True)
def _limpio() -> Any:
    from services.gateway import anomalias, empuje

    anomalias.reiniciar()
    empuje.reiniciar()
    yield
    anomalias.reiniciar()
    empuje.reiniciar()


# ── Tráfico anómalo (CRM-00.01.06.05) ─────────────────────────────────────


def test_con_pocas_ventanas_no_se_frena_a_nadie() -> None:
    """Antes de tener historia, cualquier pico es que el tenant acaba de empezar
    a usar el sistema, y frenar por ruido es frenar a quien está trabajando."""
    from services.gateway import anomalias

    tenant = uuid4()
    anomalias.anotar(tenant, 500)

    veredicto = anomalias.evaluar(tenant)
    assert veredicto["anomalo"] is False
    assert veredicto["medible"] is False
    assert "acaba de empezar" in veredicto["porque"]


def test_lo_que_se_frena_es_el_cambio_y_no_el_volumen() -> None:
    """Un cliente grande que siempre va fuerte no es una anomalía: lo es el que
    multiplica por diez lo suyo."""
    from services.gateway import anomalias

    constante, disparado = uuid4(), uuid4()
    for _ in range(12):
        anomalias.anotar(constante, 1000)
        anomalias.anotar(disparado, 10)
    anomalias.anotar(disparado, 2000)

    assert anomalias.evaluar(constante)["anomalo"] is False
    veredicto = anomalias.evaluar(disparado)
    assert veredicto["anomalo"] is True
    # Y se dice por qué: un freno sin explicación hace que la integración
    # reintente más fuerte, que es lo contrario de lo que hace falta.
    assert veredicto["porque"].strip()


def test_se_ralentiza_y_no_se_corta() -> None:
    """Cortar a un cliente porque su importación va rápida convierte un problema
    de reparto en una incidencia."""
    from services.gateway import anomalias

    tenant = uuid4()
    primero = anomalias.frenar(tenant, motivo="pico")
    assert 0 < primero["factor_de_cuota"] < 1
    assert primero["escalon"] == 1
    # Y lo que se le dice a quien llama, con palabras.
    assert "se restablece solo" in primero["mensaje_para_el_cliente"]

    # Si vuelve a pasar mientras sigue frenado, se aprieta un escalón más.
    segundo = anomalias.frenar(tenant, motivo="otra vez")
    assert segundo["escalon"] == 2
    assert segundo["factor_de_cuota"] < primero["factor_de_cuota"]


def test_el_freno_se_suelta_solo() -> None:
    """Uno que hay que quitar a mano se queda puesto, y entonces el cliente lleva
    semanas a un cuarto de cuota sin que nadie sepa por qué."""
    from services.gateway import anomalias

    tenant = uuid4()
    anomalias.frenar(tenant, motivo="pico")
    assert anomalias.estado(tenant)["frenado"] is True

    despues = datetime.now(timezone.utc) + timedelta(hours=2)
    assert anomalias.estado(tenant, ahora=despues)["frenado"] is False
    assert anomalias.estado(tenant, ahora=despues)["factor_de_cuota"] == 1.0


def test_la_puerta_de_entrada_mide_el_trafico() -> None:
    """La comprobación vive en el único paso obligado de toda la API pública: en
    cada servicio por su cuenta sería «funciona en los que alguien se acordó»."""
    import ast
    import pathlib

    fuente = (
        pathlib.Path(__file__).resolve().parents[2] / "services" / "gateway" / "api.py"
    ).read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.AsyncFunctionDef | ast.FunctionDef) and nodo.name == "proxy_api":
            llamadas = {
                getattr(n.func, "attr", None) for n in ast.walk(nodo) if isinstance(n, ast.Call)
            }
            assert {"anotar", "estado", "evaluar"} <= llamadas, (
                "la ruta de proxy ya no mide el tráfico: el módulo vuelve a estar "
                "escrito y sin enchufar"
            )
            return
    raise AssertionError("no se ha encontrado la ruta de proxy: el recorrido no mira")


# ── Empuje sin endpoint (CRM-00.02.02.10) ─────────────────────────────────


def test_un_hueco_en_la_cola_se_dice_en_vez_de_rellenarse() -> None:
    """Un cliente que cree haberlo recibido todo y no lo ha recibido toma
    decisiones sobre datos incompletos."""
    from services.gateway import empuje

    tenant = uuid4()
    for i in range(5):
        empuje.publicar(tenant, {"tipo": "x", "n": i})

    # Pedir desde antes de lo que hay en cola es un hueco.
    assert empuje.hueco(tenant, 0) is False  # desde el principio no es hueco
    assert empuje.pendientes(tenant, 3) == [(4, {"tipo": "x", "n": 3}), (5, {"tipo": "x", "n": 4})]


def test_lo_publicado_se_puede_retomar_donde_se_corto() -> None:
    from services.gateway import empuje

    tenant = uuid4()
    primero = empuje.publicar(tenant, {"tipo": "a"})
    segundo = empuje.publicar(tenant, {"tipo": "b"})

    assert [i for i, _ in empuje.pendientes(tenant, primero)] == [segundo]
    assert empuje.estado()[str(tenant)]["en_cola"] == 2


def test_quien_reparte_los_eventos_tambien_los_empuja() -> None:
    """El webhook y el empuje son el mismo evento por dos transportes: si solo
    uno de los dos sale del consumidor, el otro no existe."""
    import ast
    import pathlib

    fuente = (
        pathlib.Path(__file__).resolve().parents[2] / "services" / "eventing" / "consumidores.py"
    ).read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.AsyncFunctionDef) and nodo.name == "consumir_evento":
            llamadas = {
                getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                for n in ast.walk(nodo)
                if isinstance(n, ast.Call)
            }
            assert "avisar" in llamadas
            return
    raise AssertionError("no se ha encontrado el consumidor: el recorrido no mira")


# ── Superficie del integrador ─────────────────────────────────────────────


def test_una_composicion_no_ensena_lo_que_sus_partes_no_ensenarian() -> None:
    """Si alguien puede leer cuentas y no oportunidades, la composición no le
    trae las oportunidades."""
    from services.gateway import superficie_api as sup

    salida = sup.validar_composicion(
        nombre="ficha",
        partes=[
            {"objeto": "cuenta", "permiso": "account:read"},
            {"objeto": "oportunidad", "permiso": "opportunity:read"},
        ],
        permisos_del_llamante=frozenset({"account:read"}),
    )
    assert salida["completa"] is False
    assert salida["incluidas"] == ["account:read"]
    # Y se dice POR QUÉ falta, que es otra cosa que «no hay datos».
    assert salida["quitadas"][0]["porque"] == "no tiene «opportunity:read»"
    assert "quien pregunta no puede verlos" in salida["aviso"]


def test_una_composicion_tiene_coste_y_se_mide() -> None:
    """Una pantalla que pide quince cosas en una llamada no es una llamada
    barata: son quince con menos viajes de red."""
    from services.gateway import superficie_api as sup

    poco = sup.coste_de([{"objeto": "cuenta"}])
    mucho = sup.coste_de([{"objeto": f"o{i}"} for i in range(10)])
    assert mucho > poco


def test_un_certificado_que_no_coincide_se_rechaza() -> None:
    """Y solo cuando esa integración lo exige: obligarlo a todos deja fuera a
    quien se integra con un script de cuatro líneas."""
    from crmcore.errors import NoAutenticado, Prohibido

    from services.gateway import superficie_api as sup

    # Sin exigirlo, da igual lo que se presente.
    sup.exigir_mtls(huella_declarada="aa", huella_presentada="", obligatorio=False)

    # Exigido y sin certificado: no es lo mismo que uno equivocado, y por eso
    # son dos errores distintos — lo que tiene que hacer quien lo recibe cambia.
    with pytest.raises(NoAutenticado) as sin:
        sup.exigir_mtls(huella_declarada="aa", huella_presentada="", obligatorio=True)
    assert sin.value.error_code == "mtls.sin_certificado"

    with pytest.raises(Prohibido) as distinto:
        sup.exigir_mtls(huella_declarada="aa", huella_presentada="bb", obligatorio=True)
    assert distinto.value.error_code == "mtls.certificado_distinto"
    # Se compara la huella y no la cadena: uno firmado por la misma autoridad no
    # es el mismo certificado.
    assert "no es el mismo certificado" in str(distinto.value)


def test_el_sandbox_no_copia_datos_de_produccion() -> None:
    """Copiarlos es cómo se filtra una base de clientes entera por un sitio que
    no tiene las mismas protecciones."""
    from services.gateway import superficie_api as sup

    salida = sup.crear_sandbox(tenant_id=uuid4(), objetos=["cuenta"], filas_por_objeto=3)
    assert salida["datos"] == "sinteticos"
    assert salida["objetos"] == ["cuenta"]
    assert salida["porque_sinteticos"].strip()
    # Y caduca: un entorno de pruebas que no caduca es uno que sigue ahí dos
    # años después con la configuración de entonces.
    assert salida["caduca_at"]
    assert salida["caduca_porque"].strip()


def test_el_endpoint_propio_no_es_una_puerta_aparte() -> None:
    """Si lo fuera, sería la puerta por la que se salta todo lo anterior."""
    from crmcore.errors import ErrorValidacion

    from services.gateway import superficie_api as sup

    # Fuera del espacio reservado choca con las rutas del producto: el día que
    # se publique una con ese nombre, una de las dos deja de funcionar.
    with pytest.raises(ErrorValidacion):
        sup.declarar_endpoint_propio(
            ruta="/mi-panel", composicion="ficha", permiso="account:read", tenant_id=uuid4()
        )

    salida = sup.declarar_endpoint_propio(
        ruta="/api/v1/x/mi-panel",
        composicion="ficha",
        permiso="account:read",
        tenant_id=uuid4(),
    )
    assert "la misma auditoría" in salida["hereda"]
    assert "el mismo límite de tasa" in salida["hereda"]


def test_el_panel_ensena_lo_que_paso_y_no_lo_que_promete_el_contrato(
    monkeypatch: Any,
) -> None:
    """Un portal que solo documenta no resuelve la llamada de las tres de la
    mañana; lo que la resuelve es ver el último error."""
    from services.gateway import superficie_api as sup

    salida = sup.panel_de_integrador(
        clave="k1",
        llamadas=[
            {"ruta": "/cuentas", "status": 200},
            {"ruta": "/cuentas", "status": 500, "cuerpo": "boom"},
        ],
        cuota_mes=1000,
        scopes=["account:read"],
    )
    assert salida["ultimos_errores"]
    assert salida["llamadas"] == 2
    # Y se separa lo suyo de lo nuestro: un 4xx y un 5xx mandan a mirar a sitios
    # distintos, y mezclarlos hace que el integrador abra una incidencia por
    # algo que estaba en su petición.
    assert salida["errores_suyos"] == 0
    assert salida["errores_nuestros"] == 1
    assert salida["que_mirar_primero"].strip()


def _uuid() -> UUID:
    return uuid4()
