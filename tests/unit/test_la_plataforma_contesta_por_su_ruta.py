"""Las nueve preguntas de «Plataforma y cumplimiento», pedidas de verdad.

La pantalla declara la forma de nueve respuestas —el audit trail, las anomalías
de exportación, el registro de tratamiento, la matriz de permisos, la papelera,
el RPO real, la ventana de retención, las particiones que faltan y el estado de
la bóveda— y **ninguna prueba de servidor las pedía**. Eso es el circuito
abierto de siempre: las dos mitades existen, el tipo cuadra sobre el papel y
nadie ha recorrido lo que las une. Si el servidor deja de mandar un campo —o
nunca lo mandó— el panel se queda en blanco y no se entera nadie.

Lo cazó el gate `test_ninguna_pantalla_pide_una_forma_a_una_ruta_que_nadie_toca`
en el nivel completo, al día siguiente de escribir la pantalla.

**Por servicio, y con el recorrido contado.** Siete de estas rutas las publica
cada uno de los catorce servicios con su propio prefijo: comprobarlas en uno
solo daría verde con trece sin mirar, que es exactamente lo que este gate
existe para impedir.
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db

# Los que montan los routers de plataforma. No son los catorce: `gateway` no
# tiene modelos propios y se deja fuera a propósito, dicho aquí para que no
# parezca un olvido.
SERVICIOS = (
    "party",
    "sales",
    "service",
    "marketing",
    "identity",
    "analytics",
    "automation",
    "integration",
    "intelligence",
    "metadata",
    "orchestrator",
    "tenancy",
    "eventing",
)


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


def _cliente(servicio: str, db: Any) -> Any:
    from crmcore.config import get_settings, limpiar_cache_settings
    from starlette.testclient import TestClient

    os.environ["SERVICE_NAME"] = servicio
    os.environ["OUTBOX_ENABLED"] = "false"
    limpiar_cache_settings()
    get_settings.cache_clear()
    return TestClient(importlib.import_module(f"services.{servicio}.main").app)


@pytest.fixture(autouse=True)
def _devolver_el_servicio():
    from crmcore.config import get_settings, limpiar_cache_settings

    previo = os.environ.get("SERVICE_NAME")
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop("SERVICE_NAME", None)
        else:
            os.environ["SERVICE_NAME"] = previo
        limpiar_cache_settings()
        get_settings.cache_clear()


# Ruta por servicio → campos que la pantalla lee de la respuesta. Que falte uno
# es exactamente el fallo que esto existe para cazar.
#
# **Las rutas van escritas enteras, con `{servicio}` dentro**, y no compuestas
# con una f-string. No es estilo: el gate que destapó este agujero
# —`test_ninguna_pantalla_pide_una_forma_a_una_ruta_que_nadie_toca`— busca la
# ruta literal en los ficheros de prueba. Compuesta a trozos no la encuentra, y
# entonces la pantalla sigue contando como «declara una forma que nadie pide»
# aunque esta prueba la recorra. Pasó aquí mismo, en el primer intento.
POR_SERVICIO: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    (
        "/api/v1/{servicio}/cumplimiento/rat",
        ("completo", "actividades", "objetos_sin_tratamiento_declarado"),
        False,
    ),
    (
        "/api/v1/{servicio}/cumplimiento/matriz-permisos",
        ("exigidos_sin_ningun_rol", "concedidos_que_ninguna_ruta_exige", "alcance_de_los_roles"),
        False,
    ),
    ("/api/v1/{servicio}/restauracion/objetos", ("objetos",), False),
    (
        "/api/v1/{servicio}/restauracion/rpo",
        ("medible", "dentro", "rpo_comprometido_min", "porque"),
        False,
    ),
    (
        "/api/v1/{servicio}/restauracion/ventana",
        ("se_puede", "retencion_dias", "pedidos_dias", "porque"),
        False,
    ),
    ("/api/v1/{servicio}/tokenizacion", ("hay_boveda", "tipos", "que_significa"), False),
    ("/api/v1/{servicio}/papelera", (), True),
    # Ésta exige `ultima_existente` —cuál es la última partición que ya hay—, y
    # el panel lo pregunta. Se manda el primero de este mes, que es con lo que
    # se abre.
    (
        "/api/v1/{servicio}/volumen/particiones-a-crear?ultima_existente=2026-10-01",
        ("urgente", "ya_falta_la_de_este_mes", "faltan", "porque"),
        False,
    ),
)


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_las_preguntas_de_servicio_contestan_con_lo_que_la_pantalla_lee(
    servicio: str, db: Any, tenant_id: UUID
) -> None:
    cliente = _cliente(servicio, db)
    cabeceras = _cabeceras(tenant_id)
    vistas = 0
    for plantilla, campos, es_lista in POR_SERVICIO:
        ruta = plantilla.format(servicio=servicio)
        respuesta = cliente.get(ruta, headers=cabeceras)
        if respuesta.status_code == 404:
            # Un servicio que no monta ese router no es un fallo: se cuenta
            # como no vista y el recuento de abajo impide que «no vista» pase
            # por «correcta».
            continue
        assert (
            respuesta.status_code == 200
        ), f"{ruta} → {respuesta.status_code} {respuesta.text[:200]}"
        cuerpo = respuesta.json()
        if es_lista:
            assert isinstance(cuerpo, list), f"{ruta} no devuelve una lista"
        else:
            for campo in campos:
                assert campo in cuerpo, f"la pantalla lee «{campo}» y {ruta} no lo manda"
        vistas += 1

    # RECORRER CERO NO ES ESTAR EN VERDE: si los prefijos cambiaran, todas
    # contestarían 404 y esto pasaría sin haber comprobado nada.
    assert vistas >= 5, f"en «{servicio}» sólo se han podido pedir {vistas} de las ocho"


def test_el_audit_trail_y_las_anomalias_contestan(db: Any, tenant_id: UUID) -> None:
    """Las dos que no son por servicio: viven en `tenancy` y valen para el tenant."""
    cliente = _cliente("tenancy", db)
    cabeceras = _cabeceras(tenant_id)

    apuntes = cliente.get("/api/v1/grc/auditoria?limite=5", headers=cabeceras)
    assert apuntes.status_code == 200, apuntes.text[:300]
    assert isinstance(apuntes.json(), list)

    anomalias = cliente.get("/api/v1/grc/anomalias?dias=30", headers=cabeceras)
    assert anomalias.status_code == 200, anomalias.text[:300]
    assert isinstance(anomalias.json(), list)


def test_un_apunte_de_auditoria_trae_lo_que_la_pantalla_pinta(db: Any, tenant_id: UUID) -> None:
    """Con un apunte de verdad: una lista vacía no comprueba ningún campo.

    Es el mismo error que el de barrer cero rutas — pedir la ruta y recibir `[]`
    da verde sin haber mirado una sola forma.
    """
    from crmcore.audit import registrar

    with db.begin_nested():
        registrar(
            db,
            accion="cuenta.creada",
            objeto="cuenta",
            objeto_id=uuid4(),
            datos={"nombre": "Ferrosa"},
            tenant_id=tenant_id,
        )
    db.commit()

    cliente = _cliente("tenancy", db)
    filas = cliente.get("/api/v1/grc/auditoria?limite=20", headers=_cabeceras(tenant_id)).json()
    assert filas, "se ha registrado un apunte y el audit trail sale vacío"
    for campo in ("secuencia", "cuando", "accion", "objeto", "actor_id", "origen"):
        assert campo in filas[0], f"la pantalla lee «{campo}» y la ruta no lo manda"
