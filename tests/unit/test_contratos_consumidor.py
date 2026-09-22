"""Contract testing interno dirigido por el consumidor (CRM-00.03.01.03)."""

from __future__ import annotations

from typing import Any

import pytest
from crmcore import contratos
from crmcore.events.catalogo import TipoEvento, obtener, registrar


@pytest.fixture
def limpio() -> Any:
    previos = list(contratos.consumos())
    contratos.limpiar()
    yield
    contratos.limpiar()
    for c in previos:
        contratos.declarar_consumo(c)


def _tipo(nombre: str, campos: tuple[str, ...], version: int = 1) -> TipoEvento:
    existente = obtener(nombre)
    if existente is not None:
        return existente
    return registrar(
        TipoEvento(
            tipo=nombre,
            version=version,
            productor="party",
            descripcion="de prueba",
            campos=campos,
            publico=False,
        )
    )


def test_un_campo_que_el_productor_no_publica_se_caza(limpio: Any) -> None:
    """Es el caso que justifica el módulo: alguien quita un campo creyendo que
    no lo usa nadie. El productor sigue en verde y el consumidor se rompe días
    después, sin relación aparente con el cambio."""
    _tipo("prueba.contrato.uno", ("id", "nombre"))
    contratos.declarar_consumo(
        contratos.Consumo(
            consumidor="sales",
            evento="prueba.contrato.uno",
            campos=("id", "nombre", "pais"),
            motivo="asignar territorio",
        )
    )
    fallos = contratos.verificar()
    assert [f.clase for f in fallos] == ["campo_no_publicado"]
    assert fallos[0].campos == ("pais",)
    # El motivo del consumidor va en el mensaje: es lo único que le dice a quien
    # quitó el campo por qué no podía.
    assert "asignar territorio" in fallos[0].detalle


def test_un_consumo_opcional_no_rompe(limpio: Any) -> None:
    """Es lo que permite añadir campos sin coordinar despliegues: el consumidor
    nuevo sabe funcionar contra el productor viejo."""
    _tipo("prueba.contrato.dos", ("id",))
    contratos.declarar_consumo(
        contratos.Consumo(
            consumidor="sales",
            evento="prueba.contrato.dos",
            campos=("id", "extra"),
            obligatorio=False,
        )
    )
    assert contratos.verificar() == []


def test_esperar_un_evento_que_nadie_publica_se_caza(limpio: Any) -> None:
    contratos.declarar_consumo(
        contratos.Consumo(consumidor="sales", evento="prueba.inexistente", campos=("id",))
    )
    assert [f.clase for f in contratos.verificar()] == ["evento_sin_productor"]


def test_pedir_una_version_que_no_existe_se_caza(limpio: Any) -> None:
    _tipo("prueba.contrato.tres", ("id",), version=1)
    contratos.declarar_consumo(
        contratos.Consumo(
            consumidor="sales", evento="prueba.contrato.tres", campos=("id",), version_minima=2
        )
    )
    assert [f.clase for f in contratos.verificar()] == ["version_insuficiente"]


def test_un_servicio_no_firma_un_contrato_consigo_mismo(limpio: Any) -> None:
    """Declararlo infla la cobertura sin proteger de nada, y el número acaba
    usándose para decir que todo está cubierto."""
    _tipo("prueba.contrato.cuatro", ("id",))
    contratos.declarar_consumo(
        contratos.Consumo(consumidor="party", evento="prueba.contrato.cuatro", campos=("id",))
    )
    assert [f.clase for f in contratos.verificar()] == ["consumo_de_si_mismo"]


# ── Verificación en ejecución ─────────────────────────────────────────────


def test_una_emision_incompleta_se_detecta(limpio: Any) -> None:
    """Sin esto, productor y consumidor pueden declarar lo mismo y que la
    declaración sea falsa: el campo está en el catálogo y nunca en el `data`."""
    _tipo("prueba.contrato.cinco", ("id", "email"))
    faltan = contratos.comprobar_emision("prueba.contrato.cinco", {"id": "1"})
    assert faltan == ["email"]


def test_un_campo_a_nulo_cuenta_como_ausente(limpio: Any) -> None:
    """Para el consumidor no hay diferencia entre que no venga y que venga
    vacío: en los dos casos no puede hacer su trabajo."""
    _tipo("prueba.contrato.seis", ("id", "email"))
    assert contratos.comprobar_emision("prueba.contrato.seis", {"id": "1", "email": None}) == [
        "email"
    ]


def test_lo_que_pide_el_consumidor_tambien_se_exige_al_emitir(limpio: Any) -> None:
    """El productor puede no declarar un campo y emitirlo igual; si un
    consumidor depende de él, dejar de ponerlo lo rompe aunque el catálogo no
    diga nada."""
    _tipo("prueba.contrato.siete", ("id",))
    contratos.declarar_consumo(
        contratos.Consumo(consumidor="sales", evento="prueba.contrato.siete", campos=("pais",))
    )
    assert contratos.comprobar_emision("prueba.contrato.siete", {"id": "1"}) == ["pais"]


def test_un_evento_sin_contrato_no_estorba(limpio: Any) -> None:
    """Exigir contrato a todo evento dejaría el sistema sin poder emitir nada
    hasta haberlo declarado todo, y lo que pasaría es que se apagaría."""
    assert contratos.comprobar_emision("prueba.sin.contrato", {"x": 1}) == []


# ── Cobertura ─────────────────────────────────────────────────────────────


def test_la_cobertura_mide_lo_visto_y_no_lo_escrito(limpio: Any) -> None:
    """Un 100 % de campos declarados sin una sola emisión observada sería un
    informe que dice que todo va bien sin haber mirado."""
    _tipo("prueba.contrato.ocho", ("id", "email"))
    contratos.declarar_consumo(
        contratos.Consumo(consumidor="sales", evento="prueba.contrato.ocho", campos=("id", "email"))
    )
    assert contratos.cobertura().porcentaje == 0.0

    contratos.comprobar_emision("prueba.contrato.ocho", {"id": "1"})
    cob = contratos.cobertura()
    assert cob.porcentaje == 50.0
    assert cob.sin_observar == ["prueba.contrato.ocho: email"]

    contratos.comprobar_emision("prueba.contrato.ocho", {"id": "1", "email": "a@b.c"})
    assert contratos.cobertura().porcentaje == 100.0


def test_el_informe_dice_lo_incumplido_y_lo_no_comprobado(limpio: Any) -> None:
    _tipo("prueba.contrato.nueve", ("id",))
    contratos.declarar_consumo(
        contratos.Consumo(consumidor="sales", evento="prueba.contrato.nueve", campos=("id", "x"))
    )
    informe = contratos.informe()
    assert informe["en_verde"] is False
    assert informe["incumplimientos"][0]["clase"] == "campo_no_publicado"
    assert "sin_observar" in informe


# ── El sistema de verdad ──────────────────────────────────────────────────


def test_los_contratos_reales_del_sistema_se_cumplen() -> None:
    """Esta es la que vale: corre sobre lo declarado de verdad y es la que rompe
    cuando alguien quita un campo de un evento.

    Se cargan **todos** los productores y **todos** los consumidores. Cargar solo
    unos pocos haría que el gate pasara por no conocer al productor del evento
    que un consumidor espera —un falso positivo que llevaría a borrar un consumo
    correcto— o, peor, que no viera un incumplimiento real.
    """
    import importlib
    from pathlib import Path as _Path

    from crmcore.authz import politicas  # noqa: F401
    from crmcore.datos import calendario, cambio  # noqa: F401
    from crmcore.documental import enlaces, inventario  # noqa: F401
    from crmcore.runtime import settings  # noqa: F401
    from crmcore.security import byok  # noqa: F401

    raiz = _Path(__file__).resolve().parents[2] / "services"
    servicios = sorted(d.name for d in raiz.iterdir() if d.is_dir() and not d.name.startswith("_"))
    # Los PRODUCTORES primero y los consumidores después. No es cosmético: si un
    # consumidor se cargara antes que el productor de su evento, el gate diría
    # que nadie lo publica.
    for modulo in ("eventos", "modelos", "proyeccion", "consumidores"):
        for servicio in servicios:
            if (raiz / servicio / f"{modulo}.py").exists():
                importlib.import_module(f"services.{servicio}.{modulo}")

    fallos = contratos.verificar()
    assert not fallos, "\n".join(str(f) for f in fallos)
    assert contratos.consumos(), "no hay ni un consumo declarado: el gate no probaría nada"
