"""Alta autoservicio de una empresa (`CRM-00.01.03.01`).

El enunciado pide provisioning «API + autoservicio» y hasta hoy sólo existía la
API: `POST /tenants` exige administrador de la plataforma. `ONBOARDING_ENABLED`
prometía la otra mitad y no la leía nadie.

Lo que un alta pública tiene que resolver, y lo que se comprueba aquí:

  · **Nada existe hasta que alguien demuestra que el correo es suyo.** Pedirlo
    no crea el tenant: guarda la solicitud y devuelve el token del enlace. Crear
    primero dejaría el sistema lleno de empresas a medias con los slugs buenos
    cogidos, y un slug es permanente.
  · **La respuesta no dice si el identificador estaba libre.** Si lo dijera,
    esta pantalla sería un comprobador de qué empresas son clientes: se prueba
    un nombre, se mira la respuesta, y ya se sabe.
  · **Un solo uso y con caducidad.** Un enlace que vale siempre es una
    credencial permanente en el buzón de alguien.
  · **El slug se vuelve a comprobar al confirmar.** Entre pedir y confirmar
    pasan horas, y en ese rato puede haberlo cogido otro. Fiarse de lo que se
    anotó daría dos empresas con el mismo subdominio.
  · **El administrador no se crea aquí.** Los usuarios son de `identity` y los
    servicios no se llaman entre sí: se emite el hecho y lo recoge él.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def autoservicio(request: Any) -> Any:
    """Enciende o apaga el alta autoservicio, y lo deja como estaba."""
    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("ONBOARDING_ENABLED")
    os.environ["ONBOARDING_ENABLED"] = "true" if request.param else "false"
    limpiar_cache_settings()
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop("ONBOARDING_ENABLED", None)
        else:
            os.environ["ONBOARDING_ENABLED"] = previo
        limpiar_cache_settings()


def _uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _pedir(db: Any, tenant_id: UUID, slug: str = "acme-nueva", **extra: Any) -> str:
    from services.tenancy import alta

    return alta.solicitar(
        _uow(db, tenant_id),
        slug=slug,
        nombre_empresa=extra.pop("nombre_empresa", "ACME Nueva"),
        email=extra.pop("email", "ana@acme.example"),
        nombre_persona=extra.pop("nombre_persona", "Ana Pérez"),
        **extra,
    )


# ── El interruptor ────────────────────────────────────────────────────────


@pytest.mark.parametrize("autoservicio", [False], indirect=True)
def test_apagado_no_admite_altas(db: Any, tenant_id: UUID, autoservicio: Any) -> None:
    """De fábrica va apagado: un despliegue empresarial da de alta por API, y
    dejar abierta un alta pública en una instalación privada es una superficie
    regalada."""
    from crmcore.errors import Prohibido

    with pytest.raises(Prohibido) as fallo:
        _pedir(db, tenant_id)
    assert fallo.value.error_code == "alta.autoservicio_desactivado"
    assert "ONBOARDING_ENABLED" in str(fallo.value)


@pytest.mark.parametrize("autoservicio", [False], indirect=True)
def test_apagado_tampoco_confirma(db: Any, tenant_id: UUID, autoservicio: Any) -> None:
    """Apagar el alta tiene que cerrar también los enlaces ya emitidos. Si no,
    apagarla dejaría entrando a todo el que tuviera un correo de ayer."""
    from crmcore.errors import Prohibido

    from services.tenancy import alta

    with pytest.raises(Prohibido):
        alta.confirmar(_uow(db, tenant_id), "lo-que-sea")


# ── Pedirlo no crea nada ──────────────────────────────────────────────────


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_pedirlo_no_crea_la_empresa(db: Any, tenant_id: UUID, autoservicio: Any) -> None:
    """Es la decisión de fondo: nada existe hasta que alguien demuestra que ese
    buzón es suyo."""
    from sqlalchemy import select

    from services.tenancy.modelos import Tenant

    _pedir(db, tenant_id)
    db.flush()
    assert db.execute(select(Tenant.id).where(Tenant.slug == "acme-nueva")).first() is None


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_el_token_no_se_guarda_en_claro(db: Any, tenant_id: UUID, autoservicio: Any) -> None:
    """Quien lea la base no puede confirmar un alta ajena."""
    from sqlalchemy import select

    from services.tenancy.alta import AltaPendiente

    token = _pedir(db, tenant_id)
    db.flush()
    guardado = db.execute(select(AltaPendiente.hash_token)).scalars().all()
    assert token not in guardado
    assert all(len(h) == 64 for h in guardado)


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_un_slug_cogido_no_se_distingue_al_pedirlo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, autoservicio: Any
) -> None:
    """**El caso que hace de esto un comprobador de clientes si se hace mal.**
    Se prueba un nombre, se mira la respuesta, y ya se sabe quién es cliente."""
    from services.tenancy import servicio as svc

    svc.crear_tenant(_uow(db, tenant_id), slug="ocupada", nombre="Ya existe")
    db.flush()

    # Las dos devuelven un token, y de la misma pinta.
    libre = _pedir(db, tenant_id, slug="libre-del-todo")
    cogida = _pedir(db, tenant_id, slug="ocupada")
    assert len(libre) == len(cogida)


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_un_slug_con_mala_forma_si_se_dice(db: Any, tenant_id: UUID, autoservicio: Any) -> None:
    """La forma no depende de qué haya en la base, así que no filtra nada — y
    callarla dejaría a alguien escribiendo mayúsculas sin saber por qué no le
    llega el correo nunca."""
    from crmcore.errors import ErrorValidacion

    with pytest.raises(ErrorValidacion) as fallo:
        _pedir(db, tenant_id, slug="ACME S.A.")
    assert fallo.value.error_code == "tenant.slug_invalido"


# ── Confirmar ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_confirmar_crea_la_empresa(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, autoservicio: Any
) -> None:
    from services.tenancy import alta

    token = _pedir(db, tenant_id)
    db.flush()
    salida = alta.confirmar(_uow(db, tenant_id), token)
    assert salida["slug"] == "acme-nueva"
    assert salida["nombre"] == "ACME Nueva"


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_el_mismo_enlace_no_vale_dos_veces(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, autoservicio: Any
) -> None:
    """Quien capture el correo lo reenvía y crea otra empresa."""
    from crmcore.errors import ErrorValidacion

    from services.tenancy import alta

    token = _pedir(db, tenant_id)
    db.flush()
    alta.confirmar(_uow(db, tenant_id), token)
    with pytest.raises(ErrorValidacion) as fallo:
        alta.confirmar(_uow(db, tenant_id), token)
    assert fallo.value.error_code == "alta.enlace_usado"


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_un_enlace_caducado_no_vale(db: Any, tenant_id: UUID, autoservicio: Any) -> None:
    """Un enlace que vale siempre es una credencial permanente en un buzón."""
    from datetime import timedelta

    from crmcore.errors import ErrorValidacion
    from sqlalchemy import select

    from services.tenancy import alta
    from services.tenancy.alta import AltaPendiente

    token = _pedir(db, tenant_id)
    db.flush()
    fila = db.execute(select(AltaPendiente)).scalars().one()
    fila.caduca_at = alta._ahora() - timedelta(minutes=1)
    db.flush()

    with pytest.raises(ErrorValidacion) as fallo:
        alta.confirmar(_uow(db, tenant_id), token)
    assert fallo.value.error_code == "alta.enlace_caducado"


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_un_token_inventado_no_vale(db: Any, tenant_id: UUID, autoservicio: Any) -> None:
    from crmcore.errors import NoEncontrado

    from services.tenancy import alta

    with pytest.raises(NoEncontrado) as fallo:
        alta.confirmar(_uow(db, tenant_id), "me-lo-acabo-de-inventar")
    assert fallo.value.error_code == "alta.enlace_desconocido"


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_el_slug_se_comprueba_otra_vez_al_confirmar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, autoservicio: Any
) -> None:
    """**Entre pedir y confirmar pasan horas.** Fiarse de lo que se anotó al
    pedirlo daría dos empresas con el mismo subdominio, que es un estropicio
    permanente."""
    from crmcore.errors import Conflicto

    from services.tenancy import alta
    from services.tenancy import servicio as svc

    token = _pedir(db, tenant_id, slug="carrera")
    db.flush()
    # Y mientras tanto, otro se lo lleva.
    svc.crear_tenant(_uow(db, tenant_id), slug="carrera", nombre="El otro")
    db.flush()

    with pytest.raises(Conflicto) as fallo:
        alta.confirmar(_uow(db, tenant_id), token)
    assert fallo.value.error_code == "tenant.slug_duplicado"


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_al_confirmar_se_emite_el_hecho_para_identity(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, autoservicio: Any
) -> None:
    """El administrador lo crea `identity`. Por evento y no por llamada: atar el
    alta a que el otro servicio esté en pie en ese segundo es el peor momento
    para que falle — la persona está mirando la pantalla."""
    from crmcore.events.dominio import ALTA_CONFIRMADA

    from services.tenancy import alta

    uow = _uow(db, tenant_id)
    token = _pedir(db, tenant_id)
    db.flush()
    alta.confirmar(uow, token)

    tipos = [e.get("tipo") if isinstance(e, dict) else e.type for e in uow._pendientes]
    assert ALTA_CONFIRMADA in tipos, tipos


# ── Que no crezca sin techo ───────────────────────────────────────────────


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_las_solicitudes_viejas_se_olvidan(db: Any, tenant_id: UUID, autoservicio: Any) -> None:
    """Son correos de gente que nunca llegó a ser cliente: dato personal que no
    hay motivo para guardar. Y sin purga sería la tabla más grande del esquema,
    porque crece con cada intento — incluidos los de quien prueba nombres."""
    from datetime import timedelta

    from sqlalchemy import func, select

    from services.tenancy import alta
    from services.tenancy.alta import AltaPendiente

    _pedir(db, tenant_id, slug="vieja")
    db.flush()
    fila = db.execute(select(AltaPendiente)).scalars().one()
    fila.created_at = alta._ahora() - timedelta(days=90)
    db.flush()

    assert alta.purgar(db, dias=30) == 1
    assert db.execute(select(func.count()).select_from(AltaPendiente)).scalar_one() == 0


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_la_purga_no_se_lleva_las_recientes(db: Any, tenant_id: UUID, autoservicio: Any) -> None:
    """Una purga que borra de más deja a alguien con un enlace que acaba de
    recibir y que ya no vale."""
    from sqlalchemy import func, select

    from services.tenancy.alta import AltaPendiente, purgar

    _pedir(db, tenant_id, slug="recien")
    db.flush()
    assert purgar(db, dias=30) == 0
    assert db.execute(select(func.count()).select_from(AltaPendiente)).scalar_one() == 1


# ── La otra mitad: el primer administrador ────────────────────────────────


def _hecho(tenant: UUID, email: str = "ana@acme.example", nombre: str = "Ana Pérez") -> Any:
    from crmcore.events.dominio import ALTA_CONFIRMADA
    from crmcore.events.envelope import Evento

    return Evento(
        type=ALTA_CONFIRMADA,
        tenant_id=tenant,
        subject=("tenant", tenant),
        data={"tenant_id": str(tenant), "slug": "acme-nueva", "email": email, "nombre": nombre},
        dedup_key=f"alta:{tenant}",
    )


def test_identity_crea_al_primer_administrador(db: Any, tenant_id: UUID) -> None:
    import asyncio

    from sqlalchemy import select

    from services.identity.alta_consumidor import consumir_alta_confirmada
    from services.identity.modelos import Usuario

    asyncio.run(consumir_alta_confirmada(_hecho(tenant_id)))

    usuario = db.execute(
        select(Usuario).where(Usuario.email == "ana@acme.example")
    ).scalar_one_or_none()
    assert usuario is not None, "el hecho no ha creado a nadie"
    assert usuario.nombre == "Ana Pérez"


def test_no_se_le_inventa_una_contrasena(db: Any, tenant_id: UUID) -> None:
    """Mandar una generada por correo es ponerla en un buzón y en los registros
    del servidor de correo — y además nadie la cambia después. Se crea sin
    ninguna y se emite el enlace con el que la pone él."""
    import asyncio

    from sqlalchemy import func, select

    from services.identity.alta_consumidor import consumir_alta_confirmada
    from services.identity.modelos import Usuario
    from services.identity.restablecer import EnlaceRestablecer

    asyncio.run(consumir_alta_confirmada(_hecho(tenant_id, email="sin@clave.example")))

    usuario = db.execute(
        select(Usuario).where(Usuario.email == "sin@clave.example")
    ).scalar_one_or_none()
    assert usuario is not None
    assert not getattr(usuario, "hashed_password", None)
    # Y tiene por dónde ponerla.
    assert (
        db.execute(
            select(func.count())
            .select_from(EnlaceRestablecer)
            .where(EnlaceRestablecer.usuario_id == usuario.id)
        ).scalar_one()
        == 1
    )


def test_el_mismo_hecho_dos_veces_no_duplica(db: Any, tenant_id: UUID) -> None:
    """La entrega del bus es at-least-once: este hecho llega dos veces de
    serie. La deduplicación del inbox ya lo cubre, y aun así se comprueba aquí
    — una garantía que depende de que otra capa esté bien configurada no es una
    garantía."""
    import asyncio

    from sqlalchemy import func, select

    from services.identity.alta_consumidor import consumir_alta_confirmada
    from services.identity.modelos import Usuario

    hecho = _hecho(tenant_id, email="repe@acme.example")
    asyncio.run(consumir_alta_confirmada(hecho))
    asyncio.run(consumir_alta_confirmada(hecho))

    cuantos = db.execute(
        select(func.count()).select_from(Usuario).where(Usuario.email == "repe@acme.example")
    ).scalar_one()
    assert cuantos == 1


def test_un_hecho_incompleto_no_tumba_el_consumidor(db: Any, tenant_id: UUID) -> None:
    """Un hecho mal formado que reviente el consumidor se queda reintentándose
    para siempre y tapa los que vienen detrás."""
    import asyncio

    from crmcore.events.envelope import Evento

    from services.identity.alta_consumidor import consumir_alta_confirmada

    roto = Evento(
        type="tenant.alta_confirmada",
        tenant_id=tenant_id,
        subject=("tenant", tenant_id),
        data={"slug": "sin-correo"},
        dedup_key="roto",
    )
    asyncio.run(consumir_alta_confirmada(roto))  # no lanza


# ── Por la ruta de verdad ─────────────────────────────────────────────────


@pytest.fixture
def tenancy_arrancado() -> Any:
    """El servicio tal como se despliega, con su arranque.

    Sin el `with`, `TestClient` no ejecuta el ciclo de vida y se probaría una
    aplicación a medio arrancar — que es donde el servicio monta sus rutas.
    """
    import importlib

    from crmcore.config import limpiar_cache_settings
    from starlette.testclient import TestClient

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    limpiar_cache_settings()
    try:
        app = importlib.import_module("services.tenancy.main").app
        with TestClient(app) as cliente:
            yield cliente
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        limpiar_cache_settings()


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_la_ruta_no_pide_autenticacion(tenancy_arrancado: Any, autoservicio: Any) -> None:
    """**Es lo que la hace autoservicio.** Si pidiera identidad no serviría para
    nada: quien da de alta su empresa todavía no tiene cuenta aquí."""
    salida = tenancy_arrancado.post(
        "/api/v1/alta",
        json={
            "slug": "por-la-ruta",
            "nombre_empresa": "Por La Ruta",
            "email": "ana@porlaruta.example",
            "nombre": "Ana",
        },
    )
    assert salida.status_code == 200, salida.text[:400]
    cuerpo = salida.json()
    assert cuerpo["enviado"] is True
    assert cuerpo["token"]


@pytest.mark.parametrize("autoservicio", [False], indirect=True)
def test_apagada_la_ruta_contesta_403(tenancy_arrancado: Any, autoservicio: Any) -> None:
    salida = tenancy_arrancado.post(
        "/api/v1/alta",
        json={
            "slug": "no-deberia",
            "nombre_empresa": "No Debería",
            "email": "x@y.example",
            "nombre": "X",
        },
    )
    assert salida.status_code == 403, salida.text[:300]
    assert salida.json().get("error_code") == "alta.autoservicio_desactivado"


@pytest.mark.parametrize("autoservicio", [True], indirect=True)
def test_el_tope_por_ip_corta(tenancy_arrancado: Any, autoservicio: Any) -> None:
    """Con el tope general de la API —pensado para lecturas— un portátil llenaría
    el sistema de empresas inventadas en una tarde."""
    from crmcore.config import get_settings

    from services.tenancy.api_alta import _POR_IP

    _POR_IP.clear()
    tope = int(get_settings().onboarding_altas_por_ip_hora)
    codigos = []
    for i in range(tope + 2):
        salida = tenancy_arrancado.post(
            "/api/v1/alta",
            json={
                "slug": f"tope-{i}",
                "nombre_empresa": f"Tope {i}",
                "email": f"a{i}@tope.example",
                "nombre": "A",
            },
        )
        codigos.append(salida.status_code)
    _POR_IP.clear()
    assert 429 in codigos, codigos


def test_el_contador_por_ip_olvida_la_hora_anterior() -> None:
    """Sin olvidar, el contador sólo sube y a la segunda hora nadie podría darse
    de alta nunca más."""
    import time

    from services.tenancy.api_alta import _POR_IP

    _POR_IP.clear()
    _POR_IP["1.2.3.4"] = [time.time() - 7_200]  # de hace dos horas

    class _Req:
        client = type("c", (), {"host": "1.2.3.4"})()

    from services.tenancy.api_alta import _limitar

    _limitar(_Req())  # no lanza: lo viejo se tira antes de contar
    assert len(_POR_IP["1.2.3.4"]) == 1
    _POR_IP.clear()
