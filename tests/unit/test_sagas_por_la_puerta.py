"""Las sagas con compensación, EJERCITADAS por HTTP (CRM-00.03.02).

El servicio anuncia en su propia descripción «sagas con compensación» y el
módulo que las resuelve **no lo alcanzaba ninguna ruta**. Cinco funciones
públicas, enteras y probadas por dentro, y ni un camino desde fuera: no se podía
arrancar una saga, ni marcar un paso, ni fallarlo, ni mirar qué pasaría al
publicar una versión nueva. El motor de procesos contestaba exactamente lo que
contestaría si las sagas no existieran.

La sonda solo delataba tres de las cinco. `iniciar` y `fallar` se llaman igual
que funciones de otros módulos, y contar por nombre no distingue una de otra:
basta con que alguien llame a cualquier `iniciar` para que esta parezca viva.

Aquí se ejercita la puerta, no el módulo —eso ya lo cubre
`test_entornos_y_sagas.py`—: que la ruta existe, que el permiso se exige, que el
tenant se respeta y que lo que no se puede deshacer llega hasta la ficha.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(db: Any) -> Any:
    """Pide `db` a propósito: la sesión de la prueba tiene que estar montada
    ANTES de importar la aplicación, porque el servicio abre la suya y, sin
    compartir conexión, escribiría fuera de la transacción de la prueba."""
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.orchestrator.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


def _cabeceras(tenant_id: UUID, permisos: str = "*:*") -> dict[str, str]:
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
            H_PERMISOS: permisos,
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    return _cabeceras(tenant_id)


PASOS = [
    {"nombre": "reservar_stock", "servicio": "sales", "compensacion": {"accion": "liberar"}},
    {"nombre": "cobrar", "servicio": "billing", "compensacion": {"accion": "devolver"}},
    {"nombre": "avisar_cliente", "servicio": "identity"},
]


def _arrancar(
    cliente: Any,
    cabeceras: dict[str, str],
    pasos: Any = None,
    clave: str = "alta_de_cliente",
) -> dict[str, Any]:
    r = cliente.post(
        "/api/v1/sagas",
        json={"clave": clave, "pasos": pasos if pasos is not None else PASOS},
        headers=cabeceras,
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


# ── Arrancar (CRM-00.03.02.12) ────────────────────────────────────────────


def test_se_puede_arrancar_una_saga_desde_fuera(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Era lo que no se podía: el módulo estaba entero y sin puerta."""
    salida = _arrancar(cliente, cabeceras)
    assert salida["pasos"] == 3
    UUID(salida["saga_id"])


def test_lo_irreversible_que_no_va_al_final_se_avisa(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Un correo al cliente en mitad de la saga deja un aviso de algo que, al
    compensarse, no ha pasado. El aviso tiene que llegar hasta quien la arranca,
    no quedarse dentro del módulo."""
    salida = _arrancar(
        cliente,
        cabeceras,
        pasos=[
            {"nombre": "avisar_cliente", "servicio": "identity"},
            {"nombre": "cobrar", "servicio": "billing", "compensacion": {"accion": "devolver"}},
        ],
    )
    assert salida["irreversibles_antes_del_final"] == [1]
    assert salida["aviso"].strip()


def test_una_saga_sin_pasos_se_rechaza_por_la_ruta(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Y con su código: «error interno» no deja arreglar nada."""
    r = cliente.post("/api/v1/sagas", json={"clave": "vacia", "pasos": []}, headers=cabeceras)
    assert r.status_code == 422, r.text
    assert r.json()["error_code"] == "saga.sin_pasos"


# ── Avanzar y compensar ───────────────────────────────────────────────────


def test_un_paso_que_sale_bien_se_anota(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Sin esta llamada los pasos se quedan pendientes para siempre y la
    compensación no sabría hasta dónde deshacer."""
    saga_id = _arrancar(cliente, cabeceras)["saga_id"]
    r = cliente.post(
        f"/api/v1/sagas/{saga_id}/hecho", json={"orden": 1, "datos": {}}, headers=cabeceras
    )
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "hecho"


def test_al_fallar_se_deshace_hacia_atras_y_solo_lo_hecho(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Compensar un paso que no llegó a ejecutarse es deshacer algo que no pasó:
    una devolución de un cobro que nunca se hizo sale del banco igual."""
    saga_id = _arrancar(cliente, cabeceras)["saga_id"]
    cliente.post(
        f"/api/v1/sagas/{saga_id}/hecho", json={"orden": 1}, headers=cabeceras
    ).raise_for_status()

    r = cliente.post(
        f"/api/v1/sagas/{saga_id}/fallo",
        json={"orden": 2, "error": "la pasarela ha rechazado el cobro"},
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    # El 1 estaba hecho y se deshace; el 3 ni se tocó, así que no se compensa.
    assert salida["compensados"] == [1]
    assert salida["estado"] == "compensada"


def test_lo_que_no_se_puede_deshacer_deja_la_saga_atascada_a_proposito(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Decir «compensada» cuando se mandó un correo que no vuelve es lo que hace
    que nadie se fíe de esa palabra."""
    saga_id = _arrancar(
        cliente,
        cabeceras,
        pasos=[
            {"nombre": "avisar_cliente", "servicio": "identity"},
            {"nombre": "cobrar", "servicio": "billing", "compensacion": {"accion": "devolver"}},
        ],
    )["saga_id"]
    cliente.post(
        f"/api/v1/sagas/{saga_id}/hecho", json={"orden": 1}, headers=cabeceras
    ).raise_for_status()

    salida = cliente.post(
        f"/api/v1/sagas/{saga_id}/fallo",
        json={"orden": 2, "error": "sin saldo"},
        headers=cabeceras,
    ).json()
    assert salida["estado"] == "atascada"
    assert salida["limpia"] is False
    assert [s["orden"] for s in salida["sin_compensar"]] == [1]


# ── La ficha ──────────────────────────────────────────────────────────────


def test_la_ficha_dice_que_quedo_sin_deshacer(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Eso es trabajo manual pendiente, y una ficha que no lo destaca lo deja sin
    reclamar: habría que recorrer los pasos uno a uno para encontrarlo."""
    saga_id = _arrancar(
        cliente,
        cabeceras,
        pasos=[
            {"nombre": "avisar_cliente", "servicio": "identity"},
            {"nombre": "cobrar", "servicio": "billing", "compensacion": {"accion": "devolver"}},
        ],
    )["saga_id"]
    cliente.post(f"/api/v1/sagas/{saga_id}/hecho", json={"orden": 1}, headers=cabeceras)
    cliente.post(
        f"/api/v1/sagas/{saga_id}/fallo", json={"orden": 2, "error": "sin saldo"}, headers=cabeceras
    )

    r = cliente.get(f"/api/v1/sagas/{saga_id}", headers=cabeceras)
    assert r.status_code == 200, r.text
    ficha = r.json()
    assert ficha["estado"] == "atascada"
    assert ficha["sin_deshacer"] == [1]
    assert [p["orden"] for p in ficha["pasos"]] == [1, 2]


def test_sin_listado_no_se_llega_a_ninguna_ficha(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Y sin ficha no se llega a lo que hay que arreglar a mano. El gate de
    acciones alcanzables lo cazó: las rutas `/hecho` y `/fallo` cuelgan de una
    colección, y una colección sin listado deja la acción fuera de toda
    pantalla."""
    _arrancar(cliente, cabeceras)
    _arrancar(cliente, cabeceras, pasos=[{"nombre": "uno", "compensacion": {"a": 1}}], clave="otra")

    r = cliente.get("/api/v1/sagas?clave=alta_de_cliente", headers=cabeceras)
    assert r.status_code == 200, r.text
    datos = r.json()["items"]
    assert len(datos) == 1
    assert datos[0]["clave"] == "alta_de_cliente"
    assert datos[0]["estado"] == "en_curso"


def test_las_atascadas_se_pueden_pedir_solas(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Es la consulta que importa: son las que dejaron trabajo sin deshacer y
    están esperando a que alguien decida."""
    _arrancar(cliente, cabeceras)
    saga_id = _arrancar(
        cliente,
        cabeceras,
        pasos=[
            {"nombre": "avisar_cliente"},
            {"nombre": "cobrar", "compensacion": {"accion": "devolver"}},
        ],
    )["saga_id"]
    cliente.post(f"/api/v1/sagas/{saga_id}/hecho", json={"orden": 1}, headers=cabeceras)
    cliente.post(
        f"/api/v1/sagas/{saga_id}/fallo", json={"orden": 2, "error": "sin saldo"}, headers=cabeceras
    )

    datos = cliente.get("/api/v1/sagas?estado=atascada", headers=cabeceras).json()["items"]
    assert [d["id"] for d in datos] == [saga_id]


def test_la_saga_de_otro_tenant_no_existe(cliente: Any, tenant_id: UUID) -> None:
    """Contestar «prohibido» ya confirmaría que ese identificador es de alguien."""
    saga_id = _arrancar(cliente, _cabeceras(tenant_id))["saga_id"]

    r = cliente.get(f"/api/v1/sagas/{saga_id}", headers=_cabeceras(uuid4()))
    assert r.status_code == 404, r.text
    assert r.json()["error_code"] == "saga.no_encontrada"


def test_la_ficha_no_se_fia_solo_del_filtro_de_la_sesion() -> None:
    """**Medido**: una sesión abierta con otro tenant ni siquiera ve la fila, así
    que por HTTP este guardia no se puede observar — la prueba de arriba pasa
    igual con él que sin él. Eso no lo hace sobrante: lo hace invisible, que es
    peor. El día que alguien abra una sesión sin contexto de tenant —un worker,
    una tarea de mantenimiento, una reparación a mano— el filtro no filtra y
    esto es lo único que queda. Se ejercita aquí, donde sí se ve.
    """
    from crmcore.errors import NoEncontrado

    from services.orchestrator.api import ver_saga
    from services.orchestrator.sagas import Saga

    ajena = Saga(tenant_id=uuid4(), clave="de_otro")

    class _Db:
        def get(self, modelo: Any, _id: Any) -> Any:
            return ajena

    class _Principal:
        tenant_id = uuid4()

    with pytest.raises(NoEncontrado) as fallo:
        ver_saga(uuid4(), _Db(), _Principal())
    assert fallo.value.error_code == "saga.no_encontrada"


# ── Migración y plantillas ────────────────────────────────────────────────


def test_simular_la_migracion_no_ejecuta_nada(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Publicar una versión nueva sin mirar qué hay en vuelo es cambiarle los
    pasos a procesos que ya están a mitad."""
    _arrancar(cliente, cabeceras)

    r = cliente.post(
        "/api/v1/sagas/migracion/simular",
        json={
            "clave": "alta_de_cliente",
            "version_nueva": 2,
            "pasos_nuevos": ["cobrar", "avisar_cliente"],
        },
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["en_vuelo"] == 1
    # El paso pendiente es «reservar_stock», que la versión nueva no tiene.
    assert salida["se_pueden_migrar_todas"] is False
    assert salida["aviso"].strip()

    # Y no ha tocado nada: la saga sigue en curso con su versión.
    sigue = cliente.post(
        "/api/v1/sagas/migracion/simular",
        json={"clave": "alta_de_cliente", "version_nueva": 2, "pasos_nuevos": []},
        headers=cabeceras,
    ).json()
    assert sigue["en_vuelo"] == 1
    assert sigue["por_version"] == {"1": 1}


def test_clonar_una_plantilla_que_no_existe_se_dice(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Y no se crea una vacía con ese nombre: un proceso vacío que parece
    instalado es peor que no tenerlo."""
    r = cliente.post(
        "/api/v1/sagas/plantillas/clonar",
        json={"clave": "no_existe", "nombre_destino": "El mío"},
        headers=cabeceras,
    )
    assert r.status_code == 404, r.text
    assert r.json()["error_code"] == "flujo.plantilla_no_existe"


def test_una_plantilla_se_clona_con_lo_que_no_resuelve(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    """Una que promete el proceso entero y deja fuera la aprobación hace que el
    cliente lo descubra en producción, con el proceso ya en marcha."""
    from services.orchestrator.sagas import PlantillaFlujo

    db.add(
        PlantillaFlujo(
            clave="alta_industrial",
            sector="industria",
            nombre="Alta de cliente industrial",
            definicion={"pasos": ["validar", "firmar"]},
            no_resuelve=["la aprobación de riesgos"],
        )
    )
    db.commit()

    r = cliente.post(
        "/api/v1/sagas/plantillas/clonar",
        json={"clave": "alta_industrial", "nombre_destino": "Mi alta"},
        headers=cabeceras,
    )
    assert r.status_code == 201, r.text
    salida = r.json()
    assert salida["nombre"] == "Mi alta"
    assert salida["es_copia_independiente"] is True
    assert salida["no_resuelve"] == ["la aprobación de riesgos"]


# ── Permisos y encaminamiento ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("metodo", "ruta", "cuerpo"),
    [
        ("post", "/api/v1/sagas", {"clave": "x", "pasos": PASOS}),
        ("post", f"/api/v1/sagas/{uuid4()}/hecho", {"orden": 1}),
        ("post", f"/api/v1/sagas/{uuid4()}/fallo", {"orden": 1, "error": "x"}),
        ("post", "/api/v1/sagas/migracion/simular", {"clave": "x", "version_nueva": 2}),
        ("post", "/api/v1/sagas/plantillas/clonar", {"clave": "x", "nombre_destino": "y"}),
        ("get", f"/api/v1/sagas/{uuid4()}", None),
    ],
)
def test_ninguna_ruta_de_sagas_queda_sin_permiso(
    cliente: Any, tenant_id: UUID, metodo: str, ruta: str, cuerpo: Any
) -> None:
    """Una saga mueve dinero y stock en varios servicios. La que se quedara sin
    permiso sería la que nadie mira, porque las otras cinco sí lo piden."""
    cabeceras = _cabeceras(tenant_id, permisos="cuenta:read")
    extra = {} if cuerpo is None else {"json": cuerpo}
    r = getattr(cliente, metodo)(ruta, headers=cabeceras, **extra)
    assert r.status_code == 403, f"{metodo} {ruta} → {r.status_code}: {r.text}"


def test_la_puerta_de_entrada_sabe_a_quien_mandar_las_sagas() -> None:
    """Sin esto la ruta existe en el servicio y **no se alcanza desde fuera**: el
    gateway devuelve 404 y el módulo sigue tan incomunicado como antes."""
    from services.gateway.rutas import servicio_de

    assert servicio_de("/api/v1/sagas") == "orchestrator"
    assert servicio_de(f"/api/v1/sagas/{uuid4()}/fallo") == "orchestrator"
