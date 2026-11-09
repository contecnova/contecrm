"""Cuatro piezas del motor de procesos que constaban hechas y no lo estaban.

· **los pasos «servicio» llaman al CRM** con los permisos de quien lanzó el
  proceso. `construir_invocadores()` devolvía `{}` y todo paso «servicio»
  fallaba con «No hay invocador registrado»: un proceso podía decidir y pedir
  aprobaciones, y no podía HACER nada;
· **la orden de lanzar un proceso desde una automatización** la emitía
  `automation` y no la escuchaba nadie;
· **migrar instancias en vuelo** (CRM-00.03.02.13): sólo había una simulación
  que miraba la tabla de sagas y contestaba cero para cualquier proceso;
· **las plantillas de flujo** (CRM-00.03.05.15): la tabla estaba vacía y
  «clonar» devolvía un JSON que nadie guardaba.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

from services.orchestrator import motor as mtr

RAIZ = Path(__file__).resolve().parents[2]


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


def _cabeceras(
    tenant_id: UUID,
    *,
    usuario: UUID | None = None,
    permisos: str = "*:*",
    roles: str = "admin",
    scopes: str = "",
) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_SCOPES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(usuario or uuid4()),
            H_PERMISOS: permisos,
            H_ROLES: roles,
            H_SCOPES: scopes,
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    return _cabeceras(tenant_id)


def _publicar(
    cliente: Any, cabeceras: dict[str, str], clave: str, definicion: dict[str, Any]
) -> dict[str, Any]:
    r = cliente.post(
        "/api/v1/procesos/definiciones",
        headers=cabeceras,
        json={"clave": clave, "nombre": clave, "definicion": definicion, "estado": "publicada"},
    )
    assert r.status_code == 201, r.text
    return r.json()


class _ApiFalsa:
    """Lo que contestaría la API del CRM, y con qué se le llamó."""

    def __init__(self, respuestas: list[dict[str, Any]] | None = None) -> None:
        self.llamadas: list[dict[str, Any]] = []
        self.respuestas = respuestas or []

    def __call__(self, **kw: Any) -> dict[str, Any]:
        self.llamadas.append(kw)
        if self.respuestas:
            return self.respuestas.pop(0)
        return {"estado": 201, "ok": True, "datos": {"id": "op-1", "nombre": "creada"}}


CREAR_OPORTUNIDAD = {
    "inicio": "crear",
    "pasos": {
        "crear": {
            "tipo": "servicio",
            "operacion": "POST /api/v1/opportunities",
            "entrada": {"nombre": "@nombre", "cuenta_id": "@cuenta_id"},
            "salida": "oportunidad",
            "siguiente": "anotar",
        },
        "anotar": {
            "tipo": "servicio",
            "operacion": "PATCH /api/v1/opportunities/@oportunidad.id",
            "entrada": {"descripcion": "Creada por un proceso"},
            "siguiente": "fin",
        },
        "fin": {"tipo": "fin"},
    },
}


# ── Pasos «servicio»: validar al publicar ─────────────────────────────────


def test_una_operacion_con_forma_de_ruta_que_existe_valida() -> None:
    assert mtr.validar_definicion(CREAR_OPORTUNIDAD, operaciones_con_nombre=frozenset()) == []


@pytest.mark.parametrize(
    ("operacion", "se_dice"),
    [
        # El ejemplo que traía el editor: con nombre y sin invocador.
        ("sales.crear_oportunidad", "no es una operación"),
        ("POST /api/v1/no-existe-esto", "ninguna parte del CRM atiende"),
        ("CREAR /api/v1/opportunities", "no es una operación"),
        ("POST opportunities", "no es una operación"),
    ],
)
def test_una_operacion_que_no_se_puede_ejecutar_se_dice_al_publicar(
    operacion: str, se_dice: str
) -> None:
    """Descubierto al publicar es un mensaje; en ejecución, un proceso a medias."""
    definicion = {
        "inicio": "a",
        "pasos": {
            "a": {"tipo": "servicio", "operacion": operacion, "siguiente": "fin"},
            "fin": {"tipo": "fin"},
        },
    }
    problemas = mtr.validar_definicion(definicion, operaciones_con_nombre=frozenset())
    assert any(se_dice in p for p in problemas), problemas


def test_un_invocador_registrado_sigue_valiendo() -> None:
    """Los invocadores con nombre se mantienen para lo que la API no cubre."""
    definicion = {
        "inicio": "a",
        "pasos": {
            "a": {"tipo": "servicio", "operacion": "erp.enviar", "siguiente": "fin"},
            "fin": {"tipo": "fin"},
        },
    }
    assert mtr.validar_definicion(definicion, operaciones_con_nombre={"erp.enviar"}) == []


def test_una_compensacion_que_no_se_puede_ejecutar_tambien_se_dice() -> None:
    """Se descubriría justo el día que hace falta deshacer."""
    definicion = {
        "inicio": "a",
        "pasos": {
            "a": {
                "tipo": "servicio",
                "operacion": "POST /api/v1/opportunities",
                "compensacion": {"operacion": "anular_oportunidad"},
                "siguiente": "fin",
            },
            "fin": {"tipo": "fin"},
        },
    }
    problemas = mtr.validar_definicion(definicion, operaciones_con_nombre=frozenset())
    assert any("compensación" in p for p in problemas), problemas


@pytest.mark.db
def test_la_api_no_deja_publicar_un_paso_sin_invocador(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """La validación del editor y la de publicar son la misma, con los
    invocadores de verdad (hoy, ninguno)."""
    definicion = {
        "inicio": "a",
        "pasos": {
            "a": {"tipo": "servicio", "operacion": "sales.crear_oportunidad", "siguiente": "b"},
            "b": {"tipo": "fin"},
        },
    }
    validada = cliente.post(
        "/api/v1/procesos/definiciones/validar",
        headers=cabeceras,
        json={"clave": "x", "nombre": "x", "definicion": definicion},
    ).json()
    assert validada["valida"] is False and validada["problemas"], validada
    r = cliente.post(
        "/api/v1/procesos/definiciones",
        headers=cabeceras,
        json={"clave": "x", "nombre": "x", "definicion": definicion, "estado": "publicada"},
    )
    assert r.status_code == 422, r.text


# ── Pasos «servicio»: quién lanza y con qué permisos se ejecuta ───────────


@pytest.mark.db
def test_arrancar_guarda_quien_lanza_y_con_que_permisos(
    cliente: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.orchestrator.modelos import InstanciaProceso

    persona = uuid4()
    cab = _cabeceras(tenant_id, usuario=persona, permisos="oportunidad:write,proceso:write")
    _publicar(cliente, cab, "crear_op", CREAR_OPORTUNIDAD)
    r = cliente.post("/api/v1/instancias", headers=cab, json={"clave": "crear_op"})
    assert r.status_code == 201, r.text
    assert r.json()["lanzada_por"] == str(persona)
    assert "permisos_de_lanzamiento" not in r.json(), "los permisos de otro no se enseñan"

    fila = db.get(InstanciaProceso, UUID(r.json()["id"]))
    assert fila.lanzada_por == persona
    assert fila.permisos_de_lanzamiento == {
        "tipo": "usuario",
        "permisos": ["oportunidad:write", "proceso:write"],
        "roles": ["admin"],
    }


def test_con_ambitos_oauth_no_se_guardan_permisos() -> None:
    """Una aplicación de terceros con `cuenta:read` escribiría a través del
    proceso con los permisos de quien la autorizó."""
    from services.orchestrator.api import identidad_de

    principal = SimpleNamespace(
        id=uuid4(), tipo="usuario", permisos={"*:*"}, roles={"admin"}, scopes={"cuenta:read"}
    )
    assert identidad_de(principal) == (None, None)


@pytest.mark.db
def test_un_paso_servicio_llama_a_la_api_con_la_identidad_de_quien_lo_lanzo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.orchestrator.modelos import DefinicionProceso

    db.add(
        DefinicionProceso(
            tenant_id=tenant_id,
            clave="crear_op",
            version=1,
            nombre="x",
            definicion=CREAR_OPORTUNIDAD,
            estado="publicada",
        )
    )
    db.flush()
    persona = uuid4()
    api = _ApiFalsa()
    motor = mtr.Motor(db, llamar_api=api)
    instancia = motor.arrancar(
        tenant_id=tenant_id,
        clave="crear_op",
        variables={"nombre": "Renovación", "cuenta_id": "c-1"},
        lanzada_por=persona,
        permisos_de_lanzamiento={
            "tipo": "usuario",
            "permisos": ["oportunidad:write"],
            "roles": ["comercial"],
        },
    )
    motor.avanzar(instancia)

    assert instancia.estado == "completada", instancia.error
    primera, segunda = api.llamadas
    assert (primera["metodo"], primera["ruta"]) == ("POST", "/api/v1/opportunities")
    assert primera["cuerpo"] == {"nombre": "Renovación", "cuenta_id": "c-1"}
    assert primera["principal_id"] == persona
    assert primera["permisos"] == ["oportunidad:write"]
    assert primera["roles"] == ["comercial"]
    # Como la persona, no como agente: si no, la compartición no le aplicaría.
    assert primera["tipo"] == "usuario"
    assert primera["idempotencia"].startswith(f"{instancia.id}:crear:")
    # La salida del primero alimenta la ruta del segundo.
    assert segunda["ruta"] == "/api/v1/opportunities/op-1"
    assert instancia.variables["oportunidad"] == {"id": "op-1", "nombre": "creada"}


def _instancia(
    db: Any, tenant_id: UUID, definicion: dict[str, Any], **kw: Any
) -> tuple[mtr.Motor, Any, _ApiFalsa]:
    from services.orchestrator.modelos import DefinicionProceso

    clave = f"p_{uuid4().hex[:8]}"
    db.add(
        DefinicionProceso(
            tenant_id=tenant_id,
            clave=clave,
            version=1,
            nombre="x",
            definicion=definicion,
            estado="publicada",
        )
    )
    db.flush()
    api = _ApiFalsa(kw.pop("respuestas", None))
    motor = mtr.Motor(db, llamar_api=api)
    instancia = motor.arrancar(tenant_id=tenant_id, clave=clave, **kw)
    return motor, instancia, api


_IDENTIDAD = {"tipo": "usuario", "permisos": ["oportunidad:write"], "roles": []}


@pytest.mark.db
def test_un_4xx_del_destino_es_un_fallo_del_paso_con_su_mensaje(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    motor, instancia, _api = _instancia(
        db,
        tenant_id,
        CREAR_OPORTUNIDAD,
        variables={"nombre": ""},
        lanzada_por=uuid4(),
        permisos_de_lanzamiento=_IDENTIDAD,
        respuestas=[
            {
                "estado": 422,
                "ok": False,
                "datos": {
                    "detail": "Falta el nombre de la oportunidad",
                    "error_code": "validacion.campo",
                },
            }
        ],
    )
    motor.avanzar(instancia)
    # Sin reintentos ni `al_fallar` ni nada que compensar: el proceso falla y
    # dice POR QUÉ con las palabras del destino.
    assert instancia.estado in ("compensada", "fallida"), instancia.estado
    assert "422" in instancia.error and "Falta el nombre" in instancia.error, instancia.error


@pytest.mark.db
def test_sin_identidad_el_paso_falla_diciendolo_y_no_llama(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Ni se inventan permisos ni se llama como «la casa»."""
    motor, instancia, api = _instancia(db, tenant_id, CREAR_OPORTUNIDAD, variables={})
    motor.avanzar(instancia)
    assert api.llamadas == []
    assert "No se sabe con qué permisos actuar" in (instancia.error or ""), instancia.error


@pytest.mark.db
def test_una_ruta_con_un_tramo_vacio_no_se_llama(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """`/opportunities/` contestaría otra cosa y el paso «funcionaría» sobre lo
    que no era."""
    definicion = {
        "inicio": "anotar",
        "pasos": {
            "anotar": {
                "tipo": "servicio",
                "operacion": "PATCH /api/v1/opportunities/@oportunidad_id",
                "siguiente": "fin",
            },
            "fin": {"tipo": "fin"},
        },
    }
    motor, instancia, api = _instancia(
        db, tenant_id, definicion, lanzada_por=uuid4(), permisos_de_lanzamiento=_IDENTIDAD
    )
    motor.avanzar(instancia)
    assert api.llamadas == []
    assert "oportunidad_id" in (instancia.error or ""), instancia.error


@pytest.mark.db
def test_la_compensacion_tambien_va_por_la_api(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    definicion = {
        "inicio": "crear",
        "pasos": {
            "crear": {
                "tipo": "servicio",
                "operacion": "POST /api/v1/opportunities",
                "salida": "oportunidad",
                "compensacion": {
                    "operacion": "PATCH /api/v1/opportunities/@oportunidad.id",
                    "entrada": {"estado": "perdida"},
                },
                "siguiente": "rompe",
            },
            "rompe": {"tipo": "servicio", "operacion": "POST /api/v1/leads", "siguiente": "fin"},
            "fin": {"tipo": "fin"},
        },
    }
    motor, instancia, api = _instancia(
        db,
        tenant_id,
        definicion,
        lanzada_por=uuid4(),
        permisos_de_lanzamiento=_IDENTIDAD,
        respuestas=[
            {"estado": 201, "ok": True, "datos": {"id": "op-9"}},
            {"estado": 500, "ok": False, "datos": {"detail": "caído"}},
            {"estado": 200, "ok": True, "datos": {}},
        ],
    )
    motor.avanzar(instancia)
    assert instancia.estado == "compensada", (instancia.estado, instancia.error)
    ultima = api.llamadas[-1]
    assert (ultima["metodo"], ultima["ruta"]) == ("PATCH", "/api/v1/opportunities/op-9")
    assert ultima["cuerpo"] == {"estado": "perdida"}


@pytest.mark.db
def test_un_subproceso_actua_con_la_identidad_del_padre(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.orchestrator.modelos import DefinicionProceso, InstanciaProceso

    db.add(
        DefinicionProceso(
            tenant_id=tenant_id,
            clave="hija",
            version=1,
            nombre="hija",
            definicion={"inicio": "fin", "pasos": {"fin": {"tipo": "fin"}}},
            estado="publicada",
        )
    )
    persona = uuid4()
    motor, padre, _api = _instancia(
        db,
        tenant_id,
        {
            "inicio": "llamar",
            "pasos": {
                "llamar": {"tipo": "subproceso", "proceso": "hija", "siguiente": "fin"},
                "fin": {"tipo": "fin"},
            },
        },
        lanzada_por=persona,
        permisos_de_lanzamiento=_IDENTIDAD,
    )
    motor.avanzar(padre)
    db.flush()
    hija = db.query(InstanciaProceso).filter_by(padre_id=padre.id).one()
    assert hija.lanzada_por == persona
    assert hija.permisos_de_lanzamiento == _IDENTIDAD


# ── La orden de lanzar un proceso desde una automatización ────────────────


def _comando(tenant_id: UUID, datos: dict[str, Any]) -> Any:
    """El sobre tal como llega del bus: el mismo `Comando` que emite automation."""
    from crmcore.bus.comandos import Comando
    from crmcore.events.envelope import Evento, crear_evento

    comando = Comando(
        accion="lanzar",
        objeto="proceso",
        tenant_id=tenant_id,
        datos=datos,
        origen="automatizacion",
        origen_id="regla-7",
    )
    evento = crear_evento(
        comando.asunto, tenant_id=tenant_id, subject=("proceso", tenant_id), data=comando.a_data()
    )
    return Evento.desde_dict(evento.a_dict())


@pytest.mark.db
def test_el_comando_de_lanzar_arranca_la_instancia_sin_inventar_permisos(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.orchestrator.lanzar_desde_automatizacion import consumir
    from services.orchestrator.modelos import InstanciaProceso

    _publicar(cliente, cabeceras, "crear_op", CREAR_OPORTUNIDAD)
    asyncio.run(
        consumir(_comando(tenant_id, {"definicion": "crear_op", "entrada": {"nombre": "X"}}))
    )
    fila = db.query(InstanciaProceso).filter_by(tenant_id=tenant_id, clave="crear_op").one()
    assert fila.variables == {"nombre": "X"}
    assert (fila.origen_tipo, fila.origen_id) == ("automatizacion", "regla-7")
    # Sin `lanzado_por` en el comando, sin identidad: el paso dirá que no sabe
    # con qué permisos actuar.
    assert fila.lanzada_por is None and fila.permisos_de_lanzamiento is None


@pytest.mark.db
def test_el_comando_con_quien_activo_la_regla_arranca_con_sus_permisos(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.orchestrator.lanzar_desde_automatizacion import consumir
    from services.orchestrator.modelos import InstanciaProceso

    _publicar(cliente, cabeceras, "crear_op", CREAR_OPORTUNIDAD)
    persona = uuid4()
    asyncio.run(
        consumir(
            _comando(
                tenant_id,
                {
                    "definicion": "crear_op",
                    "entrada": {},
                    "lanzado_por": {
                        "principal_id": str(persona),
                        "permisos": ["oportunidad:write"],
                        "roles": ["comercial"],
                    },
                },
            )
        )
    )
    fila = db.query(InstanciaProceso).filter_by(tenant_id=tenant_id, clave="crear_op").one()
    assert fila.lanzada_por == persona
    assert fila.permisos_de_lanzamiento == {
        "tipo": "usuario",
        "permisos": ["oportunidad:write"],
        "roles": ["comercial"],
    }


@pytest.mark.db
def test_un_comando_de_un_proceso_que_no_existe_no_se_reintenta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """No se arregla en el siguiente reintento: se registra y se descarta."""
    from services.orchestrator.lanzar_desde_automatizacion import consumir
    from services.orchestrator.modelos import InstanciaProceso

    asyncio.run(consumir(_comando(tenant_id, {"definicion": "no_existe", "entrada": {}})))
    assert db.query(InstanciaProceso).filter_by(tenant_id=tenant_id).count() == 0


def test_el_servicio_escucha_la_orden_de_lanzar() -> None:
    """Sin la suscripción, todo lo de arriba existe y no lo llama nadie."""
    import importlib
    import inspect

    fuente = inspect.getsource(importlib.import_module("services.orchestrator.main"))
    assert '"comando.proceso.lanzar"' in fuente


# ── Migrar instancias en vuelo (CRM-00.03.02.13) ──────────────────────────

V1 = {
    "inicio": "revisar",
    "pasos": {
        "revisar": {
            "tipo": "humano",
            "asignada_rol": "responsable_ventas",
            "rutas": {"si": "fin", "no": "fin", "pedir_mas": "fin"},
        },
        "dormir": {"tipo": "espera", "segundos": 60, "siguiente": "fin"},
        "viejo": {"tipo": "espera", "segundos": 60, "siguiente": "fin"},
        "fin": {"tipo": "fin"},
    },
}
V2 = {
    "inicio": "revisar",
    "pasos": {
        "revisar": {
            "tipo": "humano",
            "asignada_rol": "responsable_ventas",
            "rutas": {"si": "nuevo", "no": "fin", "pedir_mas": "fin"},
        },
        "dormir": {"tipo": "espera", "segundos": 60, "siguiente": "nuevo"},
        "nuevo": {"tipo": "fin", "resultado": "por_la_v2"},
        "fin": {"tipo": "fin"},
    },
}


@pytest.fixture
def en_vuelo(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> dict[str, Any]:
    from services.orchestrator.modelos import DefinicionProceso, InstanciaProceso

    filas = {}
    for version, definicion, estado in ((1, V1, "publicada"), (2, V2, "publicada")):
        fila = DefinicionProceso(
            tenant_id=tenant_id,
            clave="mig",
            version=version,
            nombre="mig",
            definicion=definicion,
            estado=estado,
        )
        db.add(fila)
        db.flush()
        filas[version] = fila

    def instancia(paso: str, estado: str = "esperando") -> Any:
        fila = InstanciaProceso(
            tenant_id=tenant_id,
            definicion_id=filas[1].id,
            clave="mig",
            version=1,
            estado=estado,
            paso_actual=paso,
            variables={},
            despertar_at=datetime.now(timezone.utc),
        )
        db.add(fila)
        db.flush()
        return fila

    return {
        "movible": instancia("dormir"),
        "sin_sitio": instancia("viejo"),
        "humana": instancia("revisar", "esperando_humano"),
        "v1": filas[1],
        "v2": filas[2],
    }


@pytest.mark.db
def test_simular_dice_cuales_se_mueven_y_por_que_no_las_demas_crm_00_03_02_13(
    cliente: Any, cabeceras: dict[str, str], en_vuelo: dict[str, Any]
) -> None:
    r = cliente.post("/api/v1/procesos/definiciones/mig/2/migracion/simular", headers=cabeceras)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["aplicada"] is False and plan["en_vuelo"] == 3
    movibles = {m["instancia_id"] for m in plan["migrables"]}
    assert movibles == {str(en_vuelo["movible"].id), str(en_vuelo["humana"].id)}, plan
    (queda,) = plan["se_quedan"]
    assert queda["instancia_id"] == str(en_vuelo["sin_sitio"].id)
    assert "no existe en la versión destino" in queda["motivo"]
    # Y no ha movido nada.
    assert en_vuelo["movible"].version == 1


@pytest.mark.db
def test_una_tarea_pendiente_cuyas_respuestas_desaparecen_no_se_mueve(
    cliente: Any, cabeceras: dict[str, str], db: Any, en_vuelo: dict[str, Any]
) -> None:
    """Contestar con la opción que ya no existe terminaría el proceso sin pasar
    por ningún final (CRM-00.03.02.13)."""
    v2 = en_vuelo["v2"]
    v2.definicion = {
        **V2,
        "pasos": {
            **V2["pasos"],
            "revisar": {**V2["pasos"]["revisar"], "rutas": {"si": "nuevo", "no": "fin"}},
        },
    }
    db.flush()
    plan = cliente.post(
        "/api/v1/procesos/definiciones/mig/2/migracion/simular", headers=cabeceras
    ).json()
    motivos = {q["instancia_id"]: q["motivo"] for q in plan["se_quedan"]}
    assert "pedir_mas" in motivos[str(en_vuelo["humana"].id)], plan


@pytest.mark.db
def test_un_paso_hecho_que_perderia_su_compensacion_no_se_mueve(
    db: Any, tenant_id: UUID, en_vuelo: dict[str, Any]
) -> None:
    from services.orchestrator import migracion
    from services.orchestrator.modelos import PasoEjecutado

    en_vuelo["v1"].definicion = {
        **V1,
        "pasos": {**V1["pasos"], "viejo": {**V1["pasos"]["viejo"], "compensacion": {"x": 1}}},
    }
    db.add(
        PasoEjecutado(
            tenant_id=tenant_id,
            instancia_id=en_vuelo["movible"].id,
            paso="viejo",
            tipo="espera",
            resultado="ok",
        )
    )
    db.flush()
    plan = migracion.migrar(db, tenant_id, clave="mig", version=2, aplicar=False)
    motivos = {q["instancia_id"]: q["motivo"] for q in plan["se_quedan"]}
    assert "deshacer" in motivos[str(en_vuelo["movible"].id)], plan


@pytest.mark.db
def test_migrar_mueve_las_migrables_y_siguen_por_la_version_nueva_crm_00_03_02_13(
    cliente: Any, cabeceras: dict[str, str], db: Any, en_vuelo: dict[str, Any]
) -> None:
    r = cliente.post(
        "/api/v1/procesos/definiciones/mig/2/migracion",
        headers=cabeceras,
        json={"motivo": "la v1 terminaba sin avisar"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["aplicada"] is True and len(r.json()["migrables"]) == 2

    movida = en_vuelo["movible"]
    db.refresh(movida)
    assert (movida.version, movida.definicion_id) == (2, en_vuelo["v2"].id)
    sin_sitio = en_vuelo["sin_sitio"]
    db.refresh(sin_sitio)
    assert sin_sitio.version == 1, "la que no tenía sitio se ha movido igual"

    # Y sigue por los caminos de la v2: «dormir» ahora lleva a «nuevo».
    mtr.Motor(db).avanzar(movida)
    assert movida.estado == "completada"
    assert movida.variables.get("resultado") == "por_la_v2", movida.variables


@pytest.mark.db
def test_no_se_migra_a_un_borrador(
    cliente: Any, cabeceras: dict[str, str], db: Any, en_vuelo: dict[str, Any]
) -> None:
    en_vuelo["v2"].estado = "borrador"
    db.flush()
    r = cliente.post("/api/v1/procesos/definiciones/mig/2/migracion", headers=cabeceras, json={})
    assert r.status_code == 409, r.text


@pytest.mark.db
def test_migrar_pide_permiso_de_administrador(
    cliente: Any, tenant_id: UUID, en_vuelo: dict[str, Any]
) -> None:
    cab = _cabeceras(tenant_id, permisos="proceso:read,proceso:write")
    r = cliente.post("/api/v1/procesos/definiciones/mig/2/migracion", headers=cab, json={})
    assert r.status_code == 403, r.text
    # Simular sí: no cambia nada.
    r = cliente.post("/api/v1/procesos/definiciones/mig/2/migracion/simular", headers=cab)
    assert r.status_code == 200, r.text


# ── Plantillas de flujo (CRM-00.03.05.15) ─────────────────────────────────


def _rutas_del_contrato() -> list[tuple[str, re.Pattern[str]]]:
    sello = json.loads((RAIZ / "docs/contrato-publicado.json").read_text(encoding="utf-8"))
    rutas = []
    for operaciones in sello.values():
        for op in operaciones:
            metodo, _, ruta = op.partition(" ")
            rutas.append((metodo, re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", ruta) + "$")))
    return rutas


def test_las_plantillas_de_serie_validan_y_llaman_a_rutas_que_existen_crm_00_03_05_15() -> None:
    """Una plantilla que no se puede publicar tal cual enseña al cliente que el
    producto no se fía de sí mismo. Y la ruta tiene que existir con ESE método:
    `servicio_de` sólo mira el prefijo."""
    from services.orchestrator.plantillas import PLANTILLAS_DE_SERIE

    assert len(PLANTILLAS_DE_SERIE) >= 5
    contrato = _rutas_del_contrato()
    recorridas = 0
    for plantilla in PLANTILLAS_DE_SERIE:
        problemas = mtr.validar_definicion(
            plantilla["definicion"], operaciones_con_nombre=frozenset()
        )
        assert problemas == [], (plantilla["clave"], problemas)
        assert plantilla["no_resuelve"], f"{plantilla['clave']} no dice lo que no resuelve"
        for nombre, paso in plantilla["definicion"]["pasos"].items():
            for operacion in (
                paso.get("operacion"),
                (paso.get("compensacion") or {}).get("operacion"),
            ):
                if not operacion:
                    continue
                metodo, ruta = mtr.operacion_http(operacion) or ("", "")
                concreta = re.sub(r"@[\w.]+", "x", ruta)
                assert any(
                    m == metodo and patron.match(concreta) for m, patron in contrato
                ), f"{plantilla['clave']}.{nombre}: {operacion} no está en el contrato"
                recorridas += 1
    # Que la comprobación mire de verdad.
    assert recorridas >= 15, recorridas


@pytest.mark.db
def test_cargar_las_de_serie_es_idempotente_y_se_listan(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    from services.orchestrator.plantillas import PLANTILLAS_DE_SERIE

    primera = cliente.post("/api/v1/procesos/plantillas/cargar", headers=cabeceras)
    assert primera.status_code == 200, primera.text
    segunda = cliente.post("/api/v1/procesos/plantillas/cargar", headers=cabeceras).json()
    assert segunda["cargadas"] == [], "cargar dos veces ha duplicado plantillas"

    listadas = cliente.get("/api/v1/procesos/plantillas", headers=cabeceras).json()
    claves = {p["clave"] for p in listadas}
    assert {p["clave"] for p in PLANTILLAS_DE_SERIE} <= claves
    assert all(p["no_resuelve"] for p in listadas if p["clave"] in claves)


@pytest.mark.db
def test_copiar_crea_un_borrador_propio_con_clave_nueva_crm_00_03_05_15(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    cliente.post("/api/v1/procesos/plantillas/cargar", headers=cabeceras)
    r = cliente.post(
        "/api/v1/procesos/plantillas/escalado_caso_urgente/copiar",
        headers=cabeceras,
        json={"clave": "mi_escalado", "nombre": "Mi escalado"},
    )
    assert r.status_code == 201, r.text
    copia = r.json()
    assert copia["definicion"]["estado"] == "borrador"
    assert copia["definicion"]["clave"] == "mi_escalado"
    assert copia["no_resuelve"]

    # Está entre las definiciones del tenant, que es lo que abre el editor.
    guardadas = cliente.get("/api/v1/procesos/definiciones", headers=cabeceras).json()
    assert any(d["clave"] == "mi_escalado" and d["estado"] == "borrador" for d in guardadas)

    # Y como borrador NO se puede arrancar: nadie la ejecuta hasta publicarla.
    r = cliente.post("/api/v1/instancias", headers=cabeceras, json={"clave": "mi_escalado"})
    assert r.status_code == 404, r.text

    # La clave ya está cogida: otra copia con ella sería su versión siguiente.
    r = cliente.post(
        "/api/v1/procesos/plantillas/escalado_caso_urgente/copiar",
        headers=cabeceras,
        json={"clave": "mi_escalado", "nombre": "Otra"},
    )
    assert r.status_code == 409, r.text


@pytest.mark.db
def test_copiar_una_plantilla_que_no_existe_se_dice(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    r = cliente.post(
        "/api/v1/procesos/plantillas/no_existe/copiar",
        headers=cabeceras,
        json={"clave": "x", "nombre": "x"},
    )
    assert r.status_code == 404, r.text
    assert r.json()["error_code"] == "flujo.plantilla_no_existe"


@pytest.mark.db
@pytest.mark.parametrize(
    ("metodo", "ruta", "permisos"),
    [
        ("post", "/api/v1/procesos/plantillas/cargar", "proceso:read,proceso:write"),
        ("post", "/api/v1/procesos/plantillas/x/copiar", "proceso:read"),
        ("get", "/api/v1/procesos/plantillas", "cuenta:read"),
    ],
)
def test_las_rutas_de_plantillas_piden_permiso(
    cliente: Any, tenant_id: UUID, metodo: str, ruta: str, permisos: str
) -> None:
    cab = _cabeceras(tenant_id, permisos=permisos)
    extra = {"json": {"clave": "x", "nombre": "x"}} if metodo == "post" else {}
    r = getattr(cliente, metodo)(ruta, headers=cab, **extra)
    assert r.status_code == 403, f"{metodo} {ruta} → {r.status_code}"
