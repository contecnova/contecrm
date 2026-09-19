"""Máquinas de estado forzadas al escribir (CRM-00.04.01.07).

Un campo `estado` sin máquina es una cadena de texto con nombres bonitos.
Funciona mientras todo el mundo use la interfaz; el día que alguien escribe por
API —una integración, una importación, un script— aparecen oportunidades
«ganadas» que nunca pasaron por negociación, y los informes de conversión dejan
de significar nada sin que nada haya fallado.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.datos.estados import (
    MAQUINAS,
    Maquina,
    aplicar,
    comprobar,
    registrar_maquina,
    transiciones_de,
)
from crmcore.errors import Conflicto, ErrorValidacion

# Importar los módulos que DECLARAN las máquinas. Sin esto, `MAQUINAS` está
# vacío y las pruebas pasarían comprobando nada — que es justo el fallo que
# `test_las_maquinas_reales_estan_declaradas` existe para cazar.
import services.sales.estados  # noqa: E402,F401  (isort: skip)
import services.tenancy.servicio  # noqa: E402,F401  (isort: skip)

# ── Declaración ───────────────────────────────────────────────────────────


def test_una_maquina_con_un_destino_inexistente_se_rechaza() -> None:
    """Es un error que hay que ver al arrancar, no cuando alguien intente
    moverse."""
    with pytest.raises(ValueError, match="que no declara"):
        registrar_maquina(
            Maquina(
                objeto="_malo",
                inicial="a",
                transiciones={"a": frozenset({"b"}), "b": frozenset({"fantasma"})},
            )
        )


def test_los_estados_incluyen_los_terminales() -> None:
    m = MAQUINAS["lead"]
    assert "convertido" in m.estados
    assert m.terminales() == frozenset({"convertido"})


def test_las_maquinas_reales_estan_declaradas() -> None:
    """Si una desaparece, las transiciones de ese objeto dejan de comprobarse
    **en silencio**: `comprobar` no bloquea lo que no conoce."""
    assert {"lead", "oportunidad", "tenant"} <= set(MAQUINAS)


# ── Transiciones ──────────────────────────────────────────────────────────


def test_una_transicion_legal_pasa(db: Any) -> None:
    comprobar("lead", desde="nuevo", hasta="contactado", db=db)


def test_una_transicion_ilegal_se_rechaza(db: Any) -> None:
    with pytest.raises(Conflicto) as exc:
        comprobar("lead", desde="convertido", hasta="nuevo", db=db)
    assert exc.value.error_code == "estados.transicion_no_permitida"
    assert exc.value.detalle["permitidas"] == []


def test_un_estado_inventado_se_distingue_de_uno_prohibido(db: Any) -> None:
    """Casi siempre es una errata o una integración desactualizada, y decir
    «desconocido» ahorra media hora buscando un permiso que no falta."""
    with pytest.raises(ErrorValidacion) as exc:
        comprobar("lead", desde="nuevo", hasta="medio_cualificado", db=db)
    assert exc.value.error_code == "estados.estado_desconocido"


def test_quedarse_en_el_mismo_estado_no_es_una_transicion(db: Any) -> None:
    comprobar("lead", desde="descartado", hasta="descartado", db=db)


def test_un_lead_se_puede_convertir_desde_nuevo(db: Any) -> None:
    """Un lead que llega de una feria con el pedido firmado se convierte en el
    momento. Obligar a marcarlo antes como contactado y cualificado produce dos
    clics de mentira y un histórico que dice que hubo un seguimiento que no
    existió: la máquina codifica lo LEGÍTIMO, no el proceso ideal."""
    comprobar("lead", desde="nuevo", hasta="convertido", db=db)


def test_hay_transiciones_que_exigen_motivo(db: Any) -> None:
    """Son las que alguien preguntará meses después, y la respuesta se pierde
    con quien la tomó."""
    with pytest.raises(ErrorValidacion) as exc:
        comprobar("lead", desde="nuevo", hasta="descartado", db=db)
    assert exc.value.error_code == "estados.motivo_requerido"

    comprobar("lead", desde="nuevo", hasta="descartado", motivo="Sin presupuesto", db=db)


def test_un_objeto_sin_maquina_no_se_bloquea(db: Any) -> None:
    """Hay objetos cuyo estado es una etiqueta libre; exigirles una máquina
    llevaría a inventar una para callar a esta función."""
    comprobar("objeto_sin_maquina", desde="lo_que_sea", hasta="otra_cosa", db=db)


# ── Restricciones del tenant ──────────────────────────────────────────────


def test_un_tenant_puede_quitar_una_transicion(
    db: Any, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Aquí una oportunidad perdida no se reabre» es la petición real."""
    import crmcore.datos.estados as est

    monkeypatch.setattr(est, "_restricciones", lambda _db, _o: {"perdida": {"abierta"}})

    assert "abierta" not in transiciones_de("oportunidad", "perdida", db)
    with pytest.raises(Conflicto) as exc:
        comprobar("oportunidad", desde="perdida", hasta="abierta", motivo="x", db=db)
    # Se dice que está desactivada por configuración: sin eso, quien administra
    # no sabe si cambiar un ajuste o pedir un cambio de producto.
    assert exc.value.detalle["restringida_por_configuracion"] is True


def test_un_tenant_no_puede_anadir_estados(db: Any) -> None:
    """Un estado que el código no conoce dejaría el registro en un limbo que
    ningún `if` sabe manejar. La configuración solo QUITA."""
    import inspect

    import crmcore.datos.estados as est

    fuente = inspect.getsource(est._restricciones)
    assert "Solo quita" in fuente
    # Y se comprueba por su efecto: un destino inventado sigue siendo desconocido.
    with pytest.raises(ErrorValidacion):
        comprobar("oportunidad", desde="abierta", hasta="en_revision_legal", db=db)


# ── Aplicar ───────────────────────────────────────────────────────────────


class _Fila:
    def __init__(self, tenant_id: UUID, estado: str) -> None:
        from crmcore.ids import nuevo_id

        self.id = nuevo_id()
        self.tenant_id = tenant_id
        self.estado = estado


def test_aplicar_cambia_el_estado_y_lo_audita(db: Any, tenant_id: UUID) -> None:
    """Una transición sin apunte es un cambio que nadie puede explicar, y son
    justo los que se preguntan."""
    from crmcore.audit.modelos import ApunteAuditoria
    from sqlalchemy import select

    fila = _Fila(tenant_id, "nuevo")
    anterior = aplicar(db, fila, objeto="lead", nuevo="contactado")
    db.flush()

    assert anterior == "nuevo"
    assert fila.estado == "contactado"
    apuntes = (
        db.execute(select(ApunteAuditoria).where(ApunteAuditoria.accion == "lead.estado_cambiado"))
        .scalars()
        .all()
    )
    assert len(apuntes) == 1
    assert apuntes[0].datos == {"desde": "nuevo", "hasta": "contactado"}


def test_aplicar_una_transicion_ilegal_no_toca_la_fila(db: Any, tenant_id: UUID) -> None:
    fila = _Fila(tenant_id, "convertido")
    with pytest.raises(Conflicto):
        aplicar(db, fila, objeto="lead", nuevo="nuevo")
    assert fila.estado == "convertido"


def test_aplicar_el_mismo_estado_no_audita(db: Any, tenant_id: UUID) -> None:
    """Un cambio que no cambia nada no es un cambio; anotarlo llenaría el
    historial de ruido y escondería los que sí importan."""
    from crmcore.audit.modelos import ApunteAuditoria
    from sqlalchemy import select

    fila = _Fila(tenant_id, "contactado")
    aplicar(db, fila, objeto="lead", nuevo="contactado")
    db.flush()

    assert db.execute(select(ApunteAuditoria)).scalars().all() == []
