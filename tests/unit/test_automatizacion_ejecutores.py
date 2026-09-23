"""Las automatizaciones hacen algo (CRM-00.03.03.03).

El motor evaluaba condiciones y llamaba a unos ejecutores que **nadie
inyectaba**, y `disparar()` no lo llamaba nadie: las reglas se guardaban, se
validaban, se simulaban y no pasaba nada. Esta suite defiende que eso no vuelva.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.bus.comandos import MANEJADORES, Comando, filtrar_campos
from crmcore.errors import ErrorValidacion

from services.automation.ejecutores import construir
from services.automation.motor import ACCIONES


class _Uow:
    """Unidad de trabajo mínima que recoge lo que se emite."""

    def __init__(self, db: Any, tenant_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.emitidos: list[dict[str, Any]] = []

    def emitir(self, tipo: str, *, subject: Any, data: Any, **extra: Any) -> None:
        self.emitidos.append({"tipo": tipo, "data": data})


# ── Toda acción declarada tiene ejecutor ──────────────────────────────────


def test_toda_accion_admitida_tiene_ejecutor(db: Any, tenant_id: UUID) -> None:
    """Declarar una acción sin ejecutor es peor que no declararla: la regla se
    guarda, se valida, se simula, y al ejecutarse falla — o, antes de esto, no
    hacía nada en silencio."""
    faltan = ACCIONES - set(construir(_Uow(db, tenant_id)))
    assert not faltan, f"Acciones sin ejecutor: {sorted(faltan)}"


def test_enviar_correo_vuelve_ahora_que_hay_con_que_enviar() -> None:
    """Estuvo fuera mientras no había repartidor: una regla que lo usara se
    habría guardado, validado y ejecutado «bien» sin que saliera ningún correo.

    Vuelve con `CRM-06.02.01.02`, y lo que la sostiene no es esta línea sino el
    gate de arriba —toda acción declarada tiene ejecutor— más la prueba del
    consumidor, que comprueba que el evento que emite lo recoge alguien. La
    primera vez faltaba justo eso: el ejecutor emitía y nadie escuchaba.
    """
    assert "enviar_correo" in ACCIONES


def test_enviar_correo_pide_el_canal_explicitamente(db: Any, tenant_id: UUID) -> None:
    """Es la diferencia con `notificar`: quien escribe esta regla quiere que
    salga un correo, no que salga por donde el destinatario prefiera recibir los
    avisos de movimiento."""
    uow = _Uow(db, tenant_id)
    construir(uow)["enviar_correo"](
        titulo="Tu pedido está confirmado", cuerpo="Gracias", _tenant_id=tenant_id
    )
    assert uow.emitidos[-1]["data"]["canales"] == ["correo"]


# ── Los ejecutores emiten, no escriben ────────────────────────────────────


def test_crear_registro_emite_un_comando(db: Any, tenant_id: UUID) -> None:
    """Una automatización no puede escribir en el esquema de otro servicio: los
    permisos de base de datos lo impiden, y eso es lo que mantiene la propiedad
    exclusiva del dato."""
    uow = _Uow(db, tenant_id)
    salida = construir(uow)["crear_registro"](
        objeto="actividad", asunto="Llamar de bienvenida", _tenant_id=tenant_id
    )

    assert salida["comando"] == "comando.actividad.crear"
    assert uow.emitidos[0]["data"]["datos"]["asunto"] == "Llamar de bienvenida"


def test_asignar_emite_el_comando_con_el_propietario(db: Any, tenant_id: UUID) -> None:
    uow = _Uow(db, tenant_id)
    quien = uuid4()
    construir(uow)["asignar"](
        objeto="lead", registro_id=str(uuid4()), usuario_id=str(quien), _tenant_id=tenant_id
    )
    assert uow.emitidos[0]["data"]["datos"] == {"owner_id": str(quien)}


def test_calcular_es_actualizar_con_un_solo_campo(db: Any, tenant_id: UUID) -> None:
    """Se mantiene aparte porque en el editor es lo que la gente busca; obligar
    a encontrarlo dentro de «actualizar registro» hace que no lo usen."""
    uow = _Uow(db, tenant_id)
    registro = uuid4()
    construir(uow)["calcular"](
        objeto="lead",
        registro_id=str(registro),
        campo="puntuacion",
        valor=80,
        _tenant_id=tenant_id,
    )
    assert uow.emitidos[0]["data"]["datos"] == {"puntuacion": 80}


def test_emitir_un_evento_que_no_esta_en_el_catalogo_se_rechaza(db: Any, tenant_id: UUID) -> None:
    """Un evento fuera del catálogo no lo consume nadie: la regla parecería
    funcionar y no haría nada. Y el Anexo B es el contrato con los integradores."""
    uow = _Uow(db, tenant_id)
    with pytest.raises(ErrorValidacion) as exc:
        construir(uow)["emitir_evento"](tipo="inventado.por.alguien", _tenant_id=tenant_id)
    assert exc.value.error_code == "automatizacion.evento_desconocido"


def test_emitir_un_evento_del_catalogo_pasa(db: Any, tenant_id: UUID) -> None:
    # El catálogo de negocio vive en el núcleo desde que se comprobó que
    # ningún proceso importaba los ocho módulos de servicio a la vez.
    import crmcore.events.dominio  # noqa: F401 — registra los tipos

    uow = _Uow(db, tenant_id)
    construir(uow)["emitir_evento"](tipo="account.created", cuenta_id="x", _tenant_id=tenant_id)
    assert uow.emitidos[0]["tipo"] == "account.created"


@pytest.mark.parametrize(
    "accion,parametros,codigo",
    [
        ("crear_registro", {}, "automatizacion.falta_objeto"),
        ("actualizar_registro", {"objeto": "lead"}, "automatizacion.falta_registro"),
        ("asignar", {"objeto": "lead"}, "automatizacion.falta_usuario"),
        ("notificar", {}, "automatizacion.falta_titulo"),
        ("lanzar_proceso", {}, "automatizacion.falta_proceso"),
        ("llamar_api", {}, "automatizacion.falta_url"),
        ("calcular", {"objeto": "lead"}, "automatizacion.falta_campo"),
    ],
)
def test_cada_accion_dice_que_le_falta(
    db: Any, tenant_id: UUID, accion: str, parametros: dict[str, Any], codigo: str
) -> None:
    """Un error genérico obliga a leer el código para saber qué parámetro pusiste
    mal, y quien configura reglas no lee el código."""
    uow = _Uow(db, tenant_id)
    with pytest.raises(ErrorValidacion) as exc:
        construir(uow)[accion](_tenant_id=tenant_id, **parametros)
    assert exc.value.error_code == codigo


# ── La lista blanca del servicio dueño ────────────────────────────────────


def test_el_dueno_del_objeto_decide_que_campos_se_tocan() -> None:
    """Sin esta lista, una regla podría fijar el `owner_id` de cualquier cuenta
    o su estado: sería una escalada de privilegios disfrazada de configuración."""
    import services.party.comandos  # noqa: F401
    import services.sales.comandos  # noqa: F401

    permitidos = filtrar_campos(
        "cuenta", "actualizar", {"ciclo_vida": "cliente", "owner_id": str(uuid4())}
    )
    assert permitidos == {"ciclo_vida": "cliente"}


def test_una_regla_no_puede_cambiar_el_estado_por_comando() -> None:
    """Para eso está la máquina de estados, que exige motivo donde toca y
    prohíbe las transiciones imposibles."""
    import services.sales.comandos  # noqa: F401

    assert filtrar_campos("lead", "actualizar", {"estado": "convertido"}) == {}


def test_un_comando_sin_manejador_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion) as exc:
        filtrar_campos("marciano", "actualizar", {"x": 1})
    assert exc.value.error_code == "comandos.sin_manejador"


def test_los_manejadores_reales_estan_registrados() -> None:
    import services.party.comandos  # noqa: F401
    import services.sales.comandos  # noqa: F401

    assert "actividad.crear" in MANEJADORES
    assert "lead.asignar" in MANEJADORES
    assert "oportunidad.actualizar" in MANEJADORES


def test_el_comando_lleva_de_donde_viene() -> None:
    """Es lo que permite que la auditoría distinga «lo cambió una persona» de
    «lo cambió la regla X», y esa es la primera pregunta cuando un dato aparece
    modificado y nadie se reconoce."""
    comando = Comando(accion="asignar", objeto="lead", tenant_id=uuid4(), origen_id="regla-7")
    assert comando.a_data()["origen"] == "automatizacion"
    assert comando.a_data()["origen_id"] == "regla-7"
