"""Cifrado en tránsito (CRM-00.05.03.01) y página de estado del tenant (CRM-00.06.01.06).

Dos capacidades distintas en un fichero porque comparten el mismo modo de fallo
y la misma lección: **un ajuste configurado y no aplicado es peor que no
tenerlo**. `HSTS_MAX_AGE` existía, se documentaba, y no salía en ninguna
respuesta. Nadie lo llamaba avería porque no había error.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import pytest
from starlette.testclient import TestClient


def _app(**entorno: str) -> Any:
    from crmcore.config import limpiar_cache_settings
    from crmcore.service import crear_servicio
    from fastapi import APIRouter

    previo = {k: os.environ.get(k) for k in entorno}
    os.environ.update(entorno)
    limpiar_cache_settings()

    router = APIRouter()

    @router.get("/eco")
    def eco() -> dict[str, str]:
        return {"ok": "sí"}

    app = crear_servicio(
        nombre="pruebas",
        descripcion="Servicio para las pruebas de cifrado en tránsito",
        routers=[router],
        necesita_bus=False,
        necesita_db=False,
    )
    cliente = TestClient(app)

    class _Ctx:
        def __enter__(self) -> Any:
            return cliente

        def __exit__(self, *_a: Any) -> None:
            for clave, valor in previo.items():
                if valor is None:
                    os.environ.pop(clave, None)
                else:
                    os.environ[clave] = valor
            limpiar_cache_settings()

    return _Ctx()


# ── Cabeceras ─────────────────────────────────────────────────────────────


def test_toda_respuesta_lleva_hsts() -> None:
    """`HSTS_MAX_AGE` estaba configurado y no se aplicaba en NINGUNA respuesta.

    Sin HSTS, la primera petición de cada navegador puede ir por HTTP y ser
    interceptada antes de que exista la sesión — que es justo el momento en que
    viaja la credencial.
    """
    with _app(HSTS_MAX_AGE="31536000") as cliente:
        respuesta = cliente.get("/api/v1/eco")
    assert "max-age=31536000" in respuesta.headers["strict-transport-security"]
    assert "includeSubDomains" in respuesta.headers["strict-transport-security"]


def test_con_hsts_a_cero_no_se_manda_la_cabecera() -> None:
    """Hay despliegues internos sin TLS donde HSTS dejaría el dominio
    inaccesible para siempre desde ese navegador. Poder apagarlo es necesario;
    que sea el defecto, no."""
    with _app(HSTS_MAX_AGE="0") as cliente:
        respuesta = cliente.get("/api/v1/eco")
    assert "strict-transport-security" not in respuesta.headers


def test_las_tres_cabeceras_minimas_siempre_salen() -> None:
    with _app() as cliente:
        cabeceras = cliente.get("/api/v1/eco").headers
    assert cabeceras["x-content-type-options"] == "nosniff"
    assert cabeceras["x-frame-options"] == "DENY"
    assert cabeceras["referrer-policy"] == "strict-origin-when-cross-origin"


# ── Rechazo de HTTP en claro ──────────────────────────────────────────────


def test_con_tls_exigido_una_peticion_en_claro_se_rechaza() -> None:
    """Se responde 403 y no se redirige: una redirección a HTTPS llega después
    de que la credencial ya haya viajado en claro, así que arregla la petición
    siguiente y no la que importa."""
    with _app(TLS_EXIGIDO="true") as cliente:
        respuesta = cliente.get("/api/v1/eco")
    assert respuesta.status_code == 403
    assert respuesta.json()["error_code"] == "http.tls_requerido"


def test_la_salud_sigue_respondiendo_aunque_se_exija_tls() -> None:
    """El orquestador comprueba la salud por HTTP dentro del contenedor. Si esa
    ruta exigiera TLS, todos los servicios saldrían como caídos y el despliegue
    entraría en bucle de reinicios."""
    with _app(TLS_EXIGIDO="true") as cliente:
        assert cliente.get("/health/live").status_code == 200


def test_la_cabecera_de_proxy_no_se_cree_sin_proxy_de_confianza() -> None:
    """Sin esa condición cualquiera manda `X-Forwarded-Proto: https` y se salta
    la comprobación entera."""
    with _app(TLS_EXIGIDO="true", TRUST_PROXY_HEADERS="false") as cliente:
        respuesta = cliente.get("/api/v1/eco", headers={"x-forwarded-proto": "https"})
    assert respuesta.status_code == 403


def test_con_proxy_de_confianza_la_cabecera_si_vale() -> None:
    """Es el despliegue normal: el TLS lo termina el balanceador y al servicio
    le llega HTTP por la red interna."""
    with _app(
        TLS_EXIGIDO="true", TRUST_PROXY_HEADERS="true", TRUSTED_PROXIES="10.0.0.0/8"
    ) as cliente:
        respuesta = cliente.get("/api/v1/eco", headers={"x-forwarded-proto": "https"})
    assert respuesta.status_code == 200


def test_en_desarrollo_no_se_exige_tls_por_defecto() -> None:
    """Un `True` fijo haría imposible el ciclo local, que es exactamente cómo
    acaban desactivándose estas cosas en el `.env` de producción."""
    from crmcore.config import get_settings, limpiar_cache_settings

    limpiar_cache_settings()
    assert get_settings().tls_efectivo is False


# ── Lo que impide arrancar en producción ──────────────────────────────────


def test_produccion_rechaza_hablar_con_la_base_en_claro() -> None:
    """No es «menos seguro»: es un despliegue donde cualquiera con acceso a la
    red lee y modifica los datos de todos los clientes, y no se nota nunca
    desde dentro."""
    from crmcore.config import Settings

    problemas = Settings(
        env="prod",
        secret_key="una-clave-larga-y-propia-de-este-despliegue",
        database_url="postgresql+psycopg://u:p@db:5432/crm",
        db_sslmode="prefer",
        encryption_key="otra-clave-larga",
        cache_backend="redis",
        cache_url="redis://r:6379/0",
        storage_backend="s3",
        storage_s3_bucket="b",
        ci_enabled=False,
    ).verificar_para_produccion()
    assert any("DB_SSLMODE" in p for p in problemas)


@pytest.mark.parametrize(
    "cambio,esperado",
    [
        ({"hsts_max_age": 0}, "HSTS_MAX_AGE"),
        ({"tls_exigido": False}, "TLS_EXIGIDO"),
        ({"encryption_key": ""}, "ENCRYPTION_KEY"),
        ({"storage_s3_ssl": False}, "STORAGE_S3_SSL"),
    ],
)
def test_produccion_rechaza_cada_agujero_de_cifrado(cambio: dict, esperado: str) -> None:
    from crmcore.config import Settings

    base = dict(
        env="prod",
        secret_key="una-clave-larga-y-propia-de-este-despliegue",
        database_url="postgresql+psycopg://u:p@db:5432/crm",
        db_sslmode="verify-full",
        encryption_key="otra-clave-larga",
        cache_backend="redis",
        cache_url="redis://r:6379/0",
        storage_backend="s3",
        storage_s3_bucket="b",
        ci_enabled=False,
    )
    problemas = Settings(**{**base, **cambio}).verificar_para_produccion()
    assert any(esperado in p for p in problemas), problemas


# ── Página de estado del tenant ───────────────────────────────────────────


@pytest.mark.db
def test_un_tenant_sano_sale_operativo(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    from crmcore.datos.estado import calcular

    estado = calcular(db, tenant_id)
    assert estado["estado"] == "operativo"
    assert estado["cacheado"] is False
    assert {"base_de_datos", "eventos_salientes"} <= {
        c["componente"] for c in estado["componentes"]
    }


@pytest.mark.db
def test_una_cola_de_eventos_grande_sale_como_degradada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que más veces explica un «no me ha llegado nada a mi sistema» sin
    que nada esté roto: la cola va con retraso."""
    from crmcore.bus.modelos import EventoSaliente
    from crmcore.datos.estado import COLA_DEGRADADA, calcular

    db.add_all(
        [
            EventoSaliente(
                tenant_id=tenant_id,
                tipo="prueba.cosa",
                version=1,
                subject_tipo="x",
                subject_id="1",
                dedup_key=f"k{i}",
                sobre={},
            )
            for i in range(COLA_DEGRADADA)
        ]
    )
    db.flush()

    estado = calcular(db, tenant_id)
    cola = next(c for c in estado["componentes"] if c["componente"] == "eventos_salientes")
    assert cola["estado"] == "degradado"
    assert estado["estado"] == "degradado"


@pytest.mark.db
def test_el_estado_global_es_el_peor_de_sus_componentes(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un «todo bien» con un componente caído es la forma más rápida de que el
    cliente deje de mirar la página."""
    from crmcore.datos.estado import _peor

    assert _peor(["operativo", "degradado"]) == "degradado"
    assert _peor(["operativo", "degradado", "caido"]) == "caido"
    assert _peor(["operativo", "operativo"]) == "operativo"


@pytest.mark.db
def test_una_clave_revocada_sale_en_la_pagina_de_estado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es la única forma de que quien vea errores de descifrado entienda que no
    es una avería sino una decisión suya, sin abrir un ticket."""
    from crmcore.config import limpiar_cache_settings
    from crmcore.datos.estado import calcular
    from crmcore.security import byok

    os.environ["BYOK_ENABLED"] = "true"
    os.environ["ENCRYPTION_KEY"] = "maestra-de-pruebas-suficientemente-larga"
    limpiar_cache_settings()
    try:
        byok.registrar(db, tenant_id=tenant_id, material=os.urandom(32))
        db.flush()
        byok.revocar(db, tenant_id=tenant_id, motivo="baja del cliente", confirmado=True)
        db.flush()

        estado = calcular(db, tenant_id)
        cifrado = next(c for c in estado["componentes"] if c["componente"] == "cifrado")
        assert cifrado["estado"] == "caido"
        assert "irreversible" in cifrado["detalle"]
    finally:
        os.environ.pop("BYOK_ENABLED", None)
        os.environ.pop("ENCRYPTION_KEY", None)
        limpiar_cache_settings()


@pytest.mark.db
def test_un_componente_que_el_tenant_no_usa_no_aparece(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una lista con cosas que no le importan hace que deje de mirarla."""
    from crmcore.datos.estado import calcular

    import services.eventing.estado_componentes  # noqa: F401 — registra webhooks

    componentes = {c["componente"] for c in calcular(db, tenant_id)["componentes"]}
    assert "webhooks" not in componentes
    assert "cifrado" not in componentes


@pytest.mark.db
def test_la_pagina_no_dice_nada_de_la_plataforma(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una página de estado que filtra la forma de la plataforma es un mapa para
    quien quiera atacarla."""
    import json

    from crmcore.datos.estado import calcular

    texto = json.dumps(calcular(db, tenant_id)).lower()
    for filtracion in ("postgres", "localhost", "5432", "replica", "version", "host"):
        assert filtracion not in texto, f"la página de estado filtra «{filtracion}»"


@pytest.mark.db
def test_cada_servicio_aporta_solo_sus_componentes(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La página se compone porque **ningún servicio lee las tablas de otro**.

    La primera versión la calculaba entera en `tenancy`, consultando de paso las
    suscripciones de `eventing`, y el gate de arquitectura la paró — con razón.
    Ahora cada servicio registra sus componentes y el gateway junta las páginas.
    """
    from crmcore.datos.estado import componentes_registrados

    import services.eventing.estado_componentes  # noqa: F401
    import services.tenancy.estado_componentes  # noqa: F401

    assert {"cuotas", "webhooks"} <= set(componentes_registrados())


@pytest.mark.db
def test_el_componente_de_webhooks_ve_una_suscripcion_apagada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una suscripción desactivada por fallos repetidos es la razón número uno
    de «vuestro webhook ha dejado de llegar», y hasta ahora solo se veía
    mirando la tabla."""
    from services.eventing.estado_componentes import webhooks
    from services.eventing.modelos import Suscripcion

    db.add(
        Suscripcion(
            tenant_id=tenant_id,
            nombre="ERP",
            url="https://erp.ejemplo.test/hook",
            eventos=["account.created"],
            secreto="x",
            activa=False,
        )
    )
    db.flush()

    ficha = webhooks(db, tenant_id)
    assert ficha["estado"] == "caido"
    assert ficha["desactivadas"] == 1
