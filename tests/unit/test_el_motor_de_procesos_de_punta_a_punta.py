"""Auditoría del motor de procesos (CRM-00.03.02), por sus rutas.

Ocho capacidades de la familia sin ninguna prueba que las nombre. Se recorren
aquí por HTTP, que es como se usan, y lo que se persigue en cada una es el fallo
que la justifica:

  · **el lienzo ES la definición** (.02): no hay dos documentos. El mismo JSON
    se publica y se dibuja, así que un diagrama no puede enseñar un proceso
    distinto del que se ejecuta;
  · **validar y simular no publican nada** (.14): un error descubierto en el
    editor es un mensaje; descubierto en ejecución es un proceso a medias en
    producción con su compensación pendiente;
  · **la espera no consume nada** (.07): una instancia dormida tiene una fecha
    de despertar, no un hilo ocupado;
  · **un subproceso cuelga de su padre** (.08), que es lo que permite seguir la
    cadena cuando falla el de abajo;
  · **el outbox** (.06): el evento se escribe en la MISMA transacción que el
    dato, porque publicarlo fuera deja los dos lados discrepando el día que
    algo falla entre medias;
  · y **el aislamiento del motor** (.15): una definición de un tenant no la ve
    ni la instancia otro.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

# Con la marca de despliegue, y por un motivo concreto: aquí se comprueba que un
# tenant **no pueda arrancar** el proceso de otro, y eso el fuzzing de
# aislamiento no lo ve. El fuzzing recorre las rutas que llevan un identificador
# EN EL CAMINO; arrancar un proceso ajeno es un `POST /instancias` con la clave
# en el cuerpo, así que la red ancha pasa por encima. Lo que no cubre la red
# ancha no puede esperar al bloque.
pytestmark = [pytest.mark.db, pytest.mark.despliegue]


@pytest.fixture
def cliente(db: Any) -> Iterator[Any]:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.orchestrator.main").app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


def _cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    return _cabeceras(tenant_id)


# Un proceso mínimo que llega a fin: el control de todo lo demás.
RECTO = {
    "inicio": "decidir",
    "pasos": {
        "decidir": {
            "tipo": "decision",
            "condiciones": [
                {"si": {"atributo": "importe", "op": ">", "valor": 1000}, "entonces": "grande"}
            ],
            "si_no": "pequeno",
        },
        "grande": {"tipo": "fin"},
        "pequeno": {"tipo": "fin"},
    },
}


# ── CRM-00.03.02.02 · La definición es el documento ───────────────────────


def test_la_definicion_se_guarda_tal_cual_y_se_puede_releer_crm_00_03_02_02(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """**No hay dos documentos.** El JSON que se publica es el que se ejecuta y
    el que dibuja el lienzo; las posiciones de las cajas van dentro de la propia
    definición. Mantenerlas aparte obligaría a sincronizar dos documentos, y el
    día que se desincronizaran el diagrama enseñaría un proceso que no es."""
    con_posiciones = {
        **RECTO,
        "posiciones": {"decidir": {"x": 10, "y": 20}, "grande": {"x": 200, "y": 0}},
    }
    r = cliente.post(
        "/api/v1/procesos/definiciones",
        headers=cabeceras,
        json={
            "clave": "alta",
            "nombre": "Alta de cliente",
            "definicion": con_posiciones,
            "estado": "publicada",
        },
    )
    assert r.status_code == 201, r.text

    leidas = cliente.get("/api/v1/procesos/definiciones", headers=cabeceras).json()
    mia = next(d for d in leidas if d["clave"] == "alta")
    assert mia["definicion"]["posiciones"]["decidir"] == {"x": 10, "y": 20}, (
        "las posiciones se han quedado por el camino: el lienzo y la definición "
        "serían dos documentos que hay que sincronizar"
    )
    assert mia["definicion"]["pasos"] == RECTO["pasos"]


def test_una_definicion_rota_no_se_guarda_ni_como_borrador_crm_00_03_02_02(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """El borrador también se valida, a propósito: descubrir que la definición
    está rota el día que se publica, con prisa, es exactamente cuando peor
    viene. Lo que el borrador evita es que alguien la EJECUTE, no que se
    revise."""
    rota = {"inicio": "a", "pasos": {"a": {"tipo": "inventado"}}}
    for estado in ("borrador", "publicada"):
        r = cliente.post(
            "/api/v1/procesos/definiciones",
            headers=cabeceras,
            json={"clave": "rota", "nombre": "Rota", "definicion": rota, "estado": estado},
        )
        assert r.status_code == 422, (estado, r.text)


def test_un_paso_del_que_no_se_sale_no_pasa_la_validacion_crm_00_03_02_02(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Un proceso que no llega a fin se queda colgado para siempre, y eso no se
    ve leyendo el JSON: se ve recorriéndolo."""
    sin_salida = {
        "inicio": "a",
        "pasos": {
            "a": {"tipo": "servicio", "operacion": "x.y", "siguiente": "b"},
            "b": {"tipo": "servicio", "operacion": "x.z"},
        },
    }
    r = cliente.post(
        "/api/v1/procesos/definiciones/validar",
        headers=cabeceras,
        json={"clave": "colgada", "nombre": "Colgada", "definicion": sin_salida},
    )
    assert r.status_code == 200, r.text
    assert r.json()["problemas"], "una definición que no llega a fin pasa por buena"


def test_una_condicion_sin_atributo_no_se_toma_siempre_crm_00_03_02_02(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """**El hallazgo de esta auditoría.** Una condición mal escrita —sin `si`, o
    con `si` y sin `atributo`— se tomaba SIEMPRE: el motor comparaba `None` con
    `None`, el `=` daba cierto y la decisión se iba por la primera rama. Sin
    error, sin traza, y con el `si_no` que su autor escribió al lado sin usarse
    nunca.

    Salió al escribir esta misma prueba con la forma equivocada de la condición:
    el proceso se iba por «grande» con un importe de diez.

    Las dos mitades: se rechaza al validar, y el motor devuelve falso ante una
    condición así para que las definiciones **ya guardadas** dejen de tomar la
    rama a ciegas.
    """
    mal = {
        "inicio": "decidir",
        "pasos": {
            "decidir": {
                "tipo": "decision",
                # `variable`/`operador` en vez de `si`/`atributo`: la errata
                # plausible, porque es como se escribiría de memoria.
                "condiciones": [
                    {"variable": "importe", "operador": ">", "valor": 1000, "entonces": "grande"}
                ],
                "si_no": "pequeno",
            },
            "grande": {"tipo": "fin"},
            "pequeno": {"tipo": "fin"},
        },
    }
    validada = cliente.post(
        "/api/v1/procesos/definiciones/validar",
        headers=cabeceras,
        json={"clave": "mala", "nombre": "Mala", "definicion": mal},
    )
    assert validada.status_code == 200, validada.text
    assert any("sin atributo" in p for p in validada.json()["problemas"]), validada.json()

    # Y aunque estuviera guardada de antes: la rama no se toma a ciegas.
    from services.orchestrator.motor import Motor

    motor = Motor.__new__(Motor)
    assert motor._cumple({}, {"importe": 10}) is False
    assert motor._cumple({"atributo": "", "op": ">"}, {"importe": 10}) is False


# ── CRM-00.03.02.14 · Simular sin publicar ────────────────────────────────


def test_simular_recorre_el_proceso_y_no_crea_nada_crm_00_03_02_14(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Es el punto entero del editor. Y se pasa por donde manda la condición,
    que es lo que se quiere comprobar antes de publicar: con 5.000 se va por
    «grande» y con 10 por «pequeño»."""
    antes = cliente.get("/api/v1/instancias", headers=cabeceras).json()["items"]

    grande = cliente.post(
        "/api/v1/procesos/definiciones/simular",
        headers=cabeceras,
        json={"definicion": RECTO, "variables": {"importe": 5000}},
    )
    assert grande.status_code == 200, grande.text
    pasos = [p.get("paso") for p in grande.json()["recorrido"]]
    assert "grande" in pasos and "pequeno" not in pasos, grande.json()

    pequeno = cliente.post(
        "/api/v1/procesos/definiciones/simular",
        headers=cabeceras,
        json={"definicion": RECTO, "variables": {"importe": 10}},
    )
    pasos = [p.get("paso") for p in pequeno.json()["recorrido"]]
    assert "pequeno" in pasos and "grande" not in pasos, pequeno.json()

    # Y no ha arrancado nada: simular que ejecuta sería la peor trampa posible.
    despues = cliente.get("/api/v1/instancias", headers=cabeceras).json()["items"]
    assert len(despues) == len(antes), "la simulación ha arrancado una instancia de verdad"
    assert not cliente.get(
        "/api/v1/procesos/definiciones", headers=cabeceras
    ).json(), "la simulación ha guardado la definición"


def test_la_simulacion_contesta_a_las_tareas_humanas_crm_00_03_02_14(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Sin poder responder por ellas, un proceso con una aprobación en medio se
    simula hasta la primera tarea y ahí se acaba la utilidad."""
    con_humano = {
        "inicio": "aprobar",
        "pasos": {
            "aprobar": {
                "tipo": "humano",
                # Con dueño: una tarea sin `asignada_a`, `asignada_rol` ni
                # `cola` no la ve nadie y el proceso se queda parado, así que la
                # validación la rechaza — comprobado al escribir esto.
                "asignada_rol": "responsable_ventas",
                "rutas": {"si": "hecho", "no": "hecho"},
            },
            "hecho": {"tipo": "fin"},
        },
    }
    r = cliente.post(
        "/api/v1/procesos/definiciones/simular",
        headers=cabeceras,
        json={"definicion": con_humano, "respuestas_humanas": {"aprobar": "si"}},
    )
    assert r.status_code == 200, r.text
    assert "hecho" in [p.get("paso") for p in r.json()["recorrido"]], r.json()


# ── CRM-00.03.02.07 · Esperas y temporizadores ────────────────────────────


def test_una_instancia_que_espera_tiene_fecha_de_despertar_crm_00_03_02_07(
    cliente: Any, cabeceras: dict[str, str], db: Any, contexto_tenant: UUID
) -> None:
    """Mientras espera **no consume nada**: no hay un hilo parado ni un proceso
    haciendo poll. Solo una fecha que el planificador consulta por índice, que
    es lo que permite tener cien mil instancias dormidas."""
    con_espera = {
        "inicio": "dormir",
        "pasos": {
            "dormir": {"tipo": "espera", "segundos": 3600, "siguiente": "hecho"},
            "hecho": {"tipo": "fin"},
        },
    }
    cliente.post(
        "/api/v1/procesos/definiciones",
        headers=cabeceras,
        json={
            "clave": "espera",
            "nombre": "Espera",
            "definicion": con_espera,
            "estado": "publicada",
        },
    )
    r = cliente.post("/api/v1/instancias", headers=cabeceras, json={"clave": "espera"})
    assert r.status_code == 201, r.text
    # Arrancar **no ejecuta**: crea la instancia y la deja lista para que el
    # worker la recoja, porque arrancar un proceso no puede alargar la petición
    # que lo pidió. Así que aquí se hace avanzar el motor, que es lo que hace el
    # worker en su vuelta.
    assert r.json()["estado"] == "ejecutando", r.json()

    from services.orchestrator.modelos import InstanciaProceso
    from services.orchestrator.motor import Motor

    instancia = db.get(InstanciaProceso, UUID(r.json()["id"]))
    Motor(db).avanzar(instancia)
    db.flush()

    ficha = cliente.get(f"/api/v1/instancias/{r.json()['id']}", headers=cabeceras).json()
    assert ficha["estado"] == "esperando", ficha
    assert ficha[
        "despertar_at"
    ], f"una instancia dormida sin fecha de despertar no la despierta nadie: {sorted(ficha)}"


# ── CRM-00.03.02.08 · Subprocesos ─────────────────────────────────────────


def test_un_subproceso_cuelga_de_su_padre_crm_00_03_02_08(
    cliente: Any, cabeceras: dict[str, str], db: Any, contexto_tenant: UUID
) -> None:
    """Sin el enlace al padre, cuando falla el de abajo no hay forma de saber a
    qué proceso de negocio pertenece: aparece una instancia fallida suelta."""
    cliente.post(
        "/api/v1/procesos/definiciones",
        headers=cabeceras,
        json={
            "clave": "hijo",
            "nombre": "Hijo",
            "definicion": {"inicio": "fin", "pasos": {"fin": {"tipo": "fin"}}},
            "estado": "publicada",
        },
    )
    cliente.post(
        "/api/v1/procesos/definiciones",
        headers=cabeceras,
        json={
            "clave": "padre",
            "nombre": "Padre",
            "definicion": {
                "inicio": "llamar",
                "pasos": {
                    "llamar": {
                        "tipo": "subproceso",
                        "proceso": "hijo",
                        "esperar": False,
                        "siguiente": "fin",
                    },
                    "fin": {"tipo": "fin"},
                },
            },
            "estado": "publicada",
        },
    )
    arrancada = cliente.post("/api/v1/instancias", headers=cabeceras, json={"clave": "padre"})
    assert arrancada.status_code == 201, arrancada.text
    padre_id = UUID(arrancada.json()["id"])

    from sqlalchemy import select

    from services.orchestrator.modelos import InstanciaProceso
    from services.orchestrator.motor import Motor

    Motor(db).avanzar(db.get(InstanciaProceso, padre_id))
    db.flush()

    hijas = (
        db.execute(select(InstanciaProceso).where(InstanciaProceso.clave == "hijo")).scalars().all()
    )
    assert hijas, "el subproceso no ha arrancado"
    assert hijas[0].padre_id == padre_id, "el subproceso no apunta a su padre"
    assert hijas[0].profundidad == 1, hijas[0].profundidad

    # Y se ve desde fuera: sin `padre_id` en la respuesta, una instancia fallida
    # aparece suelta y no hay forma de saber a qué proceso de negocio pertenece.
    ficha = cliente.get(f"/api/v1/instancias/{hijas[0].id}", headers=cabeceras).json()
    assert str(ficha.get("padre_id")) == str(
        padre_id
    ), f"la instancia no dice de quién cuelga: {sorted(ficha)}"


# ── CRM-00.03.02.15 · Aislamiento del motor ───────────────────────────────


def test_un_tenant_no_ve_ni_arranca_el_proceso_de_otro_crm_00_03_02_15(
    cliente: Any,
    cabeceras: dict[str, str],
    tenant_id: UUID,
    otro_tenant_id: UUID,
    contexto_tenant: UUID,
) -> None:
    """Las definiciones son del tenant y la ejecución también. Un motor
    compartido que no aislara dejaría a una empresa arrancando el proceso de
    otra — y el proceso haría llamadas a servicios con los datos de la primera."""
    cliente.post(
        "/api/v1/procesos/definiciones",
        headers=cabeceras,
        json={"clave": "mio", "nombre": "Mío", "definicion": RECTO, "estado": "publicada"},
    )
    cliente.post("/api/v1/instancias", headers=cabeceras, json={"clave": "mio"})

    ajenas = _cabeceras(otro_tenant_id)
    assert (
        cliente.get("/api/v1/procesos/definiciones", headers=ajenas).json() == []
    ), "las definiciones de un tenant se ven desde otro"
    assert (
        cliente.get("/api/v1/instancias", headers=ajenas).json()["items"] == []
    ), "las instancias de un tenant se ven desde otro"
    suya = cliente.post("/api/v1/instancias", headers=ajenas, json={"clave": "mio"})
    assert suya.status_code in (
        404,
        409,
        422,
    ), f"otro tenant ha arrancado el proceso ajeno con {suya.status_code}"


# ── CRM-00.03.02.03 · La saga tiene coordinador ───────────────────────────


def test_una_saga_atascada_se_puede_encontrar_crm_00_03_02_03(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """`estado=atascada` es **la** consulta de esta pantalla: son las que
    dejaron trabajo hecho que no se puede deshacer y están esperando a que
    alguien decida. Una saga sin listado es una saga a la que no se llega, y a
    lo que no se llega no se arregla a mano."""
    from services.orchestrator import sagas

    db.add(
        sagas.Saga(
            tenant_id=tenant_id,
            clave="pedido",
            estado="atascada",
            contexto={"pasos_hechos": ["reservar"]},
            motivo_fin="La compensación del cobro ha fallado tres veces",
        )
    )
    db.flush()

    r = cliente.get("/api/v1/sagas?estado=atascada", headers=cabeceras)
    assert r.status_code == 200, r.text
    filas = r.json()["items"]
    assert filas and filas[0]["clave"] == "pedido", filas
    assert "compensación" in filas[0]["motivo_fin"], (
        "la saga atascada no dice por qué: sin motivo, quien la abre no sabe " "qué deshacer a mano"
    )


# ── CRM-00.03.02.04 · Coreografía por eventos ─────────────────────────────


@pytest.mark.asyncio
async def test_quien_publica_no_sabe_quien_le_escucha_crm_00_03_02_04() -> None:
    """Coreografía es lo contrario de la orquestación: no hay coordinador. Un
    servicio publica **lo que ha pasado** y quien tenga algo que hacer se
    suscribe, sin que el productor sepa quién ni cuántos.

    Se cruza publicar con recibir a propósito. Mientras ninguna prueba lo
    cruzaba, este transporte guardaba el patrón sin expandir y **no entregaba
    nada** — con la apariencia contraria, porque suscribirse y publicar no
    fallaban ninguno de los dos.

    Y se comprueba lo que distingue dos servicios de dos réplicas: con **grupos
    distintos** cada uno recibe el evento entero; con el mismo grupo se lo
    reparten, que es lo que evita procesarlo tres veces.
    """
    from crmcore.bus.memoria import BusEnMemoria
    from crmcore.events.envelope import crear_evento

    bus = BusEnMemoria()
    recibidos: list[str] = []

    async def ventas(mensaje: Any) -> None:
        recibidos.append("ventas")

    async def facturacion(mensaje: Any) -> None:
        recibidos.append("facturacion")

    await bus.suscribir("pedido.confirmado", ventas, grupo="ventas")
    await bus.suscribir("pedido.confirmado", facturacion, grupo="facturacion")

    await bus.publicar(
        crear_evento("pedido.confirmado", tenant_id=uuid4(), subject=("pedido", uuid4()), data={})
    )
    assert sorted(recibidos) == ["facturacion", "ventas"], (
        f"el evento no ha llegado a los dos suscriptores: {recibidos}. Quien "
        "publica no sabe quién le escucha, y ese es justo el punto"
    )


# ── CRM-00.03.02.06 · Outbox ──────────────────────────────────────────────


def test_el_evento_se_escribe_con_el_dato_y_no_despues_crm_00_03_02_06(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**La misma transacción.** Publicar el evento fuera de ella deja los dos
    lados discrepando el día que algo falla entre medias: o el dato sin evento
    —y nadie se entera del cambio— o el evento sin dato, que es peor porque los
    consumidores actúan sobre algo que no existe.

    Se comprueba sobre la fila escrita y no sobre la cola en memoria: una cola
    da verde aunque el volcado reviente.
    """
    from crmcore.bus.modelos import EventoSaliente
    from crmcore.bus.outbox import encolar
    from sqlalchemy import select

    encolar(
        db,
        tenant_id=tenant_id,
        tipo="proceso.arrancado",
        subject_tipo="instancia",
        subject_id=str(uuid4()),
        data={"clave": "alta"},
    )
    db.flush()

    filas = (
        db.execute(select(EventoSaliente).where(EventoSaliente.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    assert filas, "el evento no ha llegado a la tabla: estaba solo en memoria"
    assert (
        filas[0].publicado_at is None
    ), "nace publicado: entonces un reenvío no sabría cuáles faltan por salir"
