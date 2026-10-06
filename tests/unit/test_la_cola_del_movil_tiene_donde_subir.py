"""El móvil sin conexión no tenía por dónde sincronizar (`CRM-06.02.01.04`).

Auditado el 05-10-2026. `crmcore.movil` resolvía lo difícil —qué es un conflicto
de verdad, qué se guarda cuando lo hay, qué se queda en la cola— y **no lo
alcanzaba ninguna ruta**. El propio módulo decía «lo que aquí se resuelve es la
parte del servidor», y la parte del servidor no estaba servida.

Lo que eso cuesta: cualquier aplicación que se escribiera encima tenía que
reimplementar las cuatro decisiones, y la primera que se reimplementa mal es la
del conflicto — gana el último en llegar, el otro cambio desaparece y no queda
rastro de que existió.

La ruta **devuelve el plan, no escribe**. Quien escribe es la ruta de siempre de
cada objeto, con sus permisos y sus validaciones: una segunda puerta de
escritura sin las comprobaciones de la primera es como se cuela un dato que la
pantalla no habría dejado poner.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


class _Principal:
    def __init__(self, tenant_id: UUID) -> None:
        self.tenant_id = tenant_id
        self.id = uuid4()


def _sincronizar(db: Any, tenant_id: UUID, operaciones: list[dict], estrategia: str = "") -> Any:
    from crmcore.http.movil_router import Operacion, Sincronizar, crear_router_movil

    router = crear_router_movil("party")
    fn = next(r.endpoint for r in router.routes if getattr(r, "path", "").endswith("/sincronizar"))
    cuerpo = Sincronizar(operaciones=[Operacion(**o) for o in operaciones], estrategia=estrategia)
    return fn(cuerpo, db, _Principal(tenant_id))


def _contacto(uow: UnidadDeTrabajo, **campos: Any) -> Any:
    from services.party.modelos import Contacto

    fila = Contacto(
        tenant_id=uow.tenant_id,
        nombre=campos.pop("nombre", "Ana"),
        nombre_completo="Ana Pérez",
        clave_canonica="ana perez",
        **campos,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_una_operacion_sin_identificador_de_cliente_no_entra() -> None:
    """Sin él, un reintento tras un corte crea duplicados y nadie sabe cuál es
    el bueno. La respuesta correcta a esa duda no existe.

    Se comprueba en los DOS sitios porque son dos cosas: el esquema del cuerpo
    lo corta en la puerta —y así el error que ve quien integra dice qué campo
    es— y `preparar_envio` lo corta igual para quien la llame desde dentro, que
    no pasa por el esquema.
    """
    from crmcore import movil
    from crmcore.http.movil_router import Operacion

    with pytest.raises(Exception) as del_esquema:
        Operacion(id_cliente="", objeto="contacto")
    assert "id_cliente" in str(del_esquema.value)

    with pytest.raises(ErrorValidacion) as de_dentro:
        movil.preparar_envio(operaciones=[{"objeto": "contacto", "tipo": "crear"}])
    assert de_dentro.value.error_code == "movil.operacion_sin_id"


def test_la_version_cero_es_una_version() -> None:
    """La del registro que nadie ha tocado todavía.

    Comprobándolo por falsedad, toda actualización sobre un registro recién
    creado se rechazaba diciendo que no declaraba su versión base — y la
    declaraba.
    """
    from crmcore import movil

    salida = movil.preparar_envio(
        operaciones=[
            {"id_cliente": "c1", "tipo": "actualizar", "objeto": "contacto", "version_base": 0}
        ]
    )
    assert salida["listo"] is True


def test_una_actualizacion_sin_version_base_no_entra(db: Any, tenant_id: UUID) -> None:
    """Sin ella se aplicaría encima de lo que haya y el cambio de otra persona
    desaparecería sin rastro."""
    with pytest.raises(ErrorValidacion) as fallo:
        _sincronizar(
            db,
            tenant_id,
            [
                {
                    "id_cliente": "c1",
                    "tipo": "actualizar",
                    "objeto": "contacto",
                    "registro_id": str(uuid4()),
                    "campos": {"nombre": "Ana"},
                }
            ],
        )
    assert fallo.value.error_code == "movil.actualizacion_sin_version"


def test_tocar_campos_distintos_no_es_un_conflicto(uow: UnidadDeTrabajo) -> None:
    """Tratarlo como conflicto enseña a la gente a pulsar «quedarme con lo mío»,
    que es como se pierde el trabajo del otro de todas formas."""
    from services.party.main import app  # noqa: F401 — registra los objetos

    fila = _contacto(uow, cargo="Directora")
    salida = _sincronizar(
        uow.db,
        uow.tenant_id,
        [
            {
                "id_cliente": "c1",
                "tipo": "actualizar",
                "objeto": "contacto",
                "registro_id": str(fila.id),
                "version_base": 0,
                "campos": {"nombre": "Ana María"},
            }
        ],
    )
    plan = salida["plan"][0]
    assert plan["accion"] == "aplicar"


def test_tocar_el_mismo_campo_si_lo_es_y_se_devuelven_los_dos(uow: UnidadDeTrabajo) -> None:
    """Descartar una versión para «no molestar al usuario» es descartar trabajo
    de alguien."""
    from services.party.main import app  # noqa: F401

    fila = _contacto(uow, cargo="Directora")
    uow.db.flush()
    # La base se deriva de la fila: la versión la lleva el ORM y fijarla a mano
    # la pisa el flush — y entonces base y servidor coinciden, no hay choque que
    # detectar, y la prueba daría por bueno lo contrario de lo que mide.
    uow.db.refresh(fila)
    anterior = int(fila.version or 1) - 1
    assert anterior != int(fila.version or 1), "la prueba no monta dos versiones distintas"
    salida = _sincronizar(
        uow.db,
        uow.tenant_id,
        [
            {
                "id_cliente": "c1",
                "tipo": "actualizar",
                "objeto": "contacto",
                "registro_id": str(fila.id),
                "version_base": anterior,
                # Lo que el móvil LEYÓ antes de perder la señal. Entre medias,
                # otra persona lo dejó en «Directora».
                "campos_base": {"cargo": "Comercial"},
                "campos": {"cargo": "Consejera"},
            }
        ],
    )
    plan = salida["plan"][0]
    assert plan["accion"] == "conflicto"
    assert "cargo" in plan.get("campos", [])


def test_un_objeto_de_otro_servicio_se_queda_en_la_cola(uow: UnidadDeTrabajo) -> None:
    """Descartarlo sería perderlo: una cola que tira lo que no sabe resolver
    convierte un problema de sincronización en una pérdida de datos.

    **Se carga a propósito el servicio que SÍ guarda `oportunidad`.** Sin eso
    esta prueba pasaba por no haberlo cargado nadie todavía: el registro de
    objetos es del proceso, y en la suite caben los catorce servicios. Medido
    el 06-10-2026 ejecutándola detrás de `test_ventas_por_http`: el plan decía
    «aplicar», y la ruta de `party` se disponía a resolver una oportunidad de
    `sales` contra sus propios registros.
    """
    from services.party.main import app  # noqa: F401
    from services.sales import api  # noqa: F401

    salida = _sincronizar(
        uow.db,
        uow.tenant_id,
        [{"id_cliente": "c9", "tipo": "crear", "objeto": "oportunidad", "campos": {"nombre": "x"}}],
    )
    assert salida["plan"][0]["accion"] == "otro_servicio"


def test_un_registro_borrado_no_se_recrea(uow: UnidadDeTrabajo) -> None:
    """Recrearlo devolvería a la vida algo que alguien borró a propósito, y sin
    su historia."""
    from services.party.main import app  # noqa: F401

    salida = _sincronizar(
        uow.db,
        uow.tenant_id,
        [
            {
                "id_cliente": "c2",
                "tipo": "actualizar",
                "objeto": "contacto",
                "registro_id": str(uuid4()),
                "version_base": 1,
                "campos": {"nombre": "x"},
            }
        ],
    )
    assert salida["plan"][0]["accion"] == "descartada_en_origen"


def test_el_estado_de_la_cola_viene_en_la_misma_respuesta(uow: UnidadDeTrabajo) -> None:
    """Pedirlo aparte significa que nadie lo pide, y entonces una operación que
    lleva una semana sin subir no la mira nunca nadie."""
    from services.party.main import app  # noqa: F401

    fila = _contacto(uow)
    salida = _sincronizar(
        uow.db,
        uow.tenant_id,
        [
            {
                "id_cliente": "c1",
                "tipo": "actualizar",
                "objeto": "contacto",
                "registro_id": str(fila.id),
                "version_base": 0,
                "campos": {"nombre": "Ana"},
            }
        ],
    )
    assert "cola" in salida and salida["cola"]
