"""Las tres cuotas que faltaban: correos, workflows y registros (CRM-00.01.06.02).

De las seis del catálogo, tres ya se aplicaban —rate limiting, gasto de IA y
tamaño de fichero— y el almacenamiento total se cerró aparte. Éstas tres no
existían: correos y workflows **ni siquiera tenían clave de ajuste**.

**Las dos mitades en cada una, y la segunda es la que nadie escribe:** que corta
cuando toca **y que no corta cuando no toca**. Sin la segunda, «aplicar la
cuota» se implementa como «cortar» y sale en verde.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import CuotaAgotada

# EN CADA PUSH. Tres de estas pruebas comprueban que lo que hace un tenant no
# consuma la cuota de otro: no es una fuga de datos, es que a un cliente se le
# corten los correos, los procesos o las altas por lo que hace otro. Se nota al
# instante, no hay forma de deducirlo, y no lo cubre el barrido de fugas.
pytestmark = [pytest.mark.db, pytest.mark.despliegue]


def _fijar(db: Any, tenant_id: UUID, clave: str, valor: int) -> None:
    from crmcore.runtime import settings as rt

    rt.fijar(db, clave, valor, ambito="tenant", ambito_id=str(tenant_id))
    db.commit()


# ── Correos ───────────────────────────────────────────────────────────────


def _mandar(db: Any, tenant_id: UUID, canal: str = "email") -> Any:
    from crmcore.notificaciones.entrega import registrar_intento

    return registrar_intento(
        db,
        tenant_id=tenant_id,
        notificacion_id=uuid4(),
        usuario_id=uuid4(),
        canal=canal,
        direccion="quien@cliente.com",
    )


def test_al_agotar_la_cuota_de_correos_no_se_manda(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _fijar(db, tenant_id, "cuota_correos_mes", 2)

    _mandar(db, tenant_id)
    _mandar(db, tenant_id)
    db.commit()

    with pytest.raises(CuotaAgotada) as excinfo:
        _mandar(db, tenant_id)
    assert excinfo.value.error_code == "cuota.email"
    # Qué ajuste hay que tocar para subirlo: sin eso, quien lo recibe tiene que
    # averiguar a qué clave corresponde «email».
    assert excinfo.value.detalle["ajuste"] == "cuota_correos_mes"


def test_sin_cuota_declarada_se_mandan_todos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La omisión abre. Un despliegue sin cuotas configuradas no puede quedarse
    sin poder avisar a nadie porque a alguien se le olvidara declararlas."""
    for _ in range(5):
        _mandar(db, tenant_id)
    db.commit()


def test_un_canal_no_declarado_no_se_corta(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Lo que no está en el mapa de canales pasa sin límite.

    Un canal nuevo que nadie declare tiene que seguir funcionando: cortarle el
    aviso a un cliente por un olvido nuestro es peor que dejar pasar de más.
    """
    _fijar(db, tenant_id, "cuota_correos_mes", 1)
    _mandar(db, tenant_id, canal="email")
    db.commit()

    # `push` no está en CUOTA_POR_CANAL: no lo toca la cuota del correo.
    for _ in range(4):
        _mandar(db, tenant_id, canal="push")
    db.commit()


def test_reintentar_un_aviso_ya_contado_no_gasta_cuota_otra_vez(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Si un reintento consumiera cuota, un canal con mal día se comería el mes."""
    _fijar(db, tenant_id, "cuota_correos_mes", 1)

    from crmcore.notificaciones.entrega import registrar_intento

    aviso = uuid4()
    for _ in range(4):
        registrar_intento(
            db,
            tenant_id=tenant_id,
            notificacion_id=aviso,
            usuario_id=uuid4(),
            canal="email",
            direccion="quien@cliente.com",
        )
    db.commit()


def test_lo_que_manda_otro_tenant_no_cuenta(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Agotarle la cuota a un cliente por lo que manda otro es la peor forma
    posible de agotar una cuota."""
    _fijar(db, tenant_id, "cuota_correos_mes", 2)
    for _ in range(5):
        _mandar(db, otro_tenant_id)
    db.commit()

    _mandar(db, tenant_id)
    db.commit()


# ── Registros ─────────────────────────────────────────────────────────────


@pytest.fixture
def contables(db: Any) -> Any:
    from crmcore.cuota_registros import (
        declarar_contable,
        instalar_guard_cuota,
        limpiar_declarados,
    )

    from services.party.modelos import Cuenta

    limpiar_declarados()
    declarar_contable(Cuenta, "cuentas")
    instalar_guard_cuota()
    yield
    limpiar_declarados()


def _cuenta(db: Any, tenant_id: UUID) -> Any:
    """Por el SERVICIO y no por el ORM.

    Construir la fila a mano se salta la puerta por la que pasa un cliente —aquí,
    sin ir más lejos, `clave_canonica` la pone el servicio y la columna no admite
    nulos—, y una prueba que entra por otro sitio no prueba lo que se usa. Es la
    misma lección que en contecmind dejó un tipo de aprobación implementado,
    probado y rechazado por la API: todas sus pruebas montaban el objeto por el
    ORM.
    """
    from crmcore.db.uow import UnidadDeTrabajo

    from services.party import servicio as svc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    return svc.crear_cuenta(uow, nombre=f"ACME {uuid4().hex[:6]}")


def test_al_agotar_la_cuota_de_registros_no_se_crea(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, contables: Any
) -> None:
    _fijar(db, tenant_id, "cuota_registros", 2)

    _cuenta(db, tenant_id)
    _cuenta(db, tenant_id)
    db.commit()

    with pytest.raises(CuotaAgotada) as excinfo:
        _cuenta(db, tenant_id)
        db.flush()
    assert excinfo.value.error_code == "cuota.registros"


def test_sin_cuota_de_registros_se_crean_todos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, contables: Any
) -> None:
    for _ in range(6):
        _cuenta(db, tenant_id)
    db.commit()


def test_un_modelo_no_declarado_no_consume_cuota_de_registros(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, contables: Any
) -> None:
    """Una fila de auditoría o una entrega de aviso no son «registros del
    cliente»: contarlas le agotaría la cuota con nuestro propio ruido."""
    _fijar(db, tenant_id, "cuota_registros", 1)

    for _ in range(5):
        _mandar(db, tenant_id)  # EntregaNotificacion, no declarada
    db.commit()

    _cuenta(db, tenant_id)
    db.commit()


def test_modificar_no_agota_la_cuota_de_registros(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, contables: Any
) -> None:
    """Sólo las altas consumen: editar lo que ya se tiene no puede cortarse por
    cuota, o un cliente al tope no podría ni corregir una errata."""
    _fijar(db, tenant_id, "cuota_registros", 1)
    fila = _cuenta(db, tenant_id)
    db.commit()

    fila.nombre = "ACME corregido"
    db.commit()


def test_los_registros_de_otro_tenant_no_cuentan(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID, contables: Any
) -> None:
    _fijar(db, tenant_id, "cuota_registros", 2)
    for _ in range(5):
        _cuenta(db, otro_tenant_id)
    db.commit()

    _cuenta(db, tenant_id)
    db.commit()


# ── Workflows ─────────────────────────────────────────────────────────────


def _publicar_proceso(db: Any, tenant_id: UUID, clave: str = "alta") -> Any:
    from services.orchestrator.modelos import DefinicionProceso

    fila = DefinicionProceso(
        tenant_id=tenant_id,
        clave=clave,
        version=1,
        nombre=clave,
        definicion={"inicio": "fin", "pasos": {"fin": {"tipo": "fin"}}},
        estado="publicada",
    )
    db.add(fila)
    db.flush()
    return fila


def _arrancar(db: Any, tenant_id: UUID, **extra: Any) -> Any:
    from services.orchestrator.motor import Motor

    return Motor(db).arrancar(tenant_id=tenant_id, clave="alta", **extra)


def test_al_agotar_la_cuota_de_workflows_no_arranca(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _fijar(db, tenant_id, "cuota_workflows_mes", 2)
    _publicar_proceso(db, tenant_id)

    _arrancar(db, tenant_id)
    _arrancar(db, tenant_id)
    db.commit()

    with pytest.raises(CuotaAgotada) as excinfo:
        _arrancar(db, tenant_id)
    assert excinfo.value.error_code == "cuota.workflows"
    assert excinfo.value.detalle["ajuste"] == "cuota_workflows_mes"


def test_sin_cuota_de_workflows_arrancan_todos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _publicar_proceso(db, tenant_id)
    for _ in range(5):
        _arrancar(db, tenant_id)
    db.commit()


def test_un_subproceso_no_consume_cuota_propia(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un subproceso es parte de la misma ejecución, no otra.

    Contarlo aparte haría que un proceso con diez subprocesos gastara once, y el
    cliente vería agotarse su cuota al triple de velocidad sin haber lanzado nada
    más — sin poder cuadrar el número con lo que ve en su pantalla.
    """
    _fijar(db, tenant_id, "cuota_workflows_mes", 1)
    padre_def = _publicar_proceso(db, tenant_id)
    padre = _arrancar(db, tenant_id)
    db.commit()
    assert padre_def is not None

    # Con la cuota ya en el tope, los subprocesos del que arrancó siguen yendo.
    for _ in range(4):
        _arrancar(db, tenant_id, padre_id=padre.id, profundidad=1)
    db.commit()


def test_los_workflows_de_otro_tenant_no_cuentan(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _fijar(db, tenant_id, "cuota_workflows_mes", 2)
    _publicar_proceso(db, tenant_id)
    _publicar_proceso(db, otro_tenant_id)

    for _ in range(5):
        _arrancar(db, otro_tenant_id)
    db.commit()

    _arrancar(db, tenant_id)
    db.commit()


# ── Que el arranque lo instale ────────────────────────────────────────────


def test_el_arranque_instala_el_guard_de_la_cuota_de_registros() -> None:
    """Si no lo instalara, la cuota no se aplicaría y **nada fallaría**.

    Es la avería que más veces ha salido: algo escrito, probado y que no ejecuta
    nadie. Aquí la prueba de arriba seguiría en verde —instala el guard ella
    misma— mientras en producción no se aplicaría nada.
    """
    import inspect

    from crmcore import service

    fuente = inspect.getsource(service.crear_servicio)
    assert "instalar_guard_cuota" in fuente, (
        "El arranque ya no instala el guard de la cuota de registros: se puede "
        "declarar el tope y no se aplicará, sin que nada falle."
    )
