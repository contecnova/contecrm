"""RAT, informes de cumplimiento, SLO y restauración selectiva
(CRM-07.03.01.04, CRM-07.03.01.07, CRM-00.06.01.04, CRM-00.06.02.03).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from crmcore import cumplimiento
from crmcore.obs import slo


@pytest.fixture(autouse=True)
def _limpio() -> Any:
    cumplimiento.limpiar_tratamientos()
    slo.reiniciar()
    yield
    cumplimiento.limpiar_tratamientos()
    slo.reiniciar()


# ── RAT y mapa de datos personales ────────────────────────────────────────


def test_el_mapa_sale_del_modelo_y_no_de_una_lista() -> None:
    """Una lista se queda desfasada al primer campo nuevo, y ese campo no
    existiría para el RAT hasta que alguien se acordara — y nadie se acuerda."""
    from services.party.modelos import Contacto

    campos = cumplimiento.mapa_de_datos({"contacto": Contacto})
    assert campos, "el contacto declara campos personales y no se han encontrado"
    assert all(c.objeto == "contacto" for c in campos)


def test_un_objeto_con_datos_personales_sin_tratamiento_sale_como_hueco() -> None:
    """Un RAT que presenta como completo lo que no lo está es peor que no
    tenerlo, porque nadie vuelve a mirarlo."""
    from services.party.modelos import Contacto

    rat = cumplimiento.registro_de_tratamiento({"contacto": Contacto})
    assert rat["objetos_sin_tratamiento_declarado"] == ["contacto"]
    assert rat["completo"] is False


def test_declarar_el_tratamiento_cierra_el_hueco() -> None:
    from services.party.modelos import Contacto

    cumplimiento.declarar(
        cumplimiento.Tratamiento(
            objeto="contacto",
            finalidad="Gestión de la relación comercial",
            base_legal="interés legítimo",
            plazo="Mientras dure la relación y 6 años más",
        )
    )
    rat = cumplimiento.registro_de_tratamiento({"contacto": Contacto})
    assert rat["objetos_sin_tratamiento_declarado"] == []
    assert rat["actividades"][0]["base_legal"] == "interés legítimo"


def test_un_tratamiento_sobre_un_objeto_sin_datos_personales_tambien_sale() -> None:
    """Suele significar que el objeto cambió y el RAT no."""
    from services.sales.modelos import Pipeline

    cumplimiento.declarar(
        cumplimiento.Tratamiento(objeto="pipeline", finalidad="x", base_legal="y", plazo="z")
    )
    rat = cumplimiento.registro_de_tratamiento({"pipeline": Pipeline})
    assert rat["tratamientos_sobre_objetos_sin_datos_personales"] == ["pipeline"]


@pytest.mark.db
def test_el_informe_dice_lo_que_no_ha_podido_componer(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un apartado ausente se lee como «no aplica», y la diferencia entre eso y
    «no se ha podido comprobar» es justo la que importa en una auditoría."""
    from services.party.modelos import Contacto

    informe = cumplimiento.informe_de_cumplimiento(db, tenant_id, {"contacto": Contacto})
    assert "rat" in informe and "avisos" in informe
    # El RAT tiene huecos porque no se ha declarado nada: eso se avisa.
    assert any("registro de tratamiento" in a for a in informe["avisos"])


# ── SLO y presupuesto de error ────────────────────────────────────────────


def _objetivo() -> slo.Objetivo:
    return slo.Objetivo(
        servicio="party", tier="premium", disponibilidad_pct=99.9, latencia_p95_ms=500
    )


def test_sin_trafico_no_se_dice_que_va_bien() -> None:
    """«100 % disponible» sin peticiones es mentir con la verdad: un servicio
    que nadie usa no ha demostrado nada."""
    salida = slo.presupuesto(_objetivo())
    assert salida["medible"] is False


def test_lo_lento_cuenta_aparte_de_lo_fallido() -> None:
    """Una respuesta que llega en cuatro segundos es un error para quien la
    espera aunque devuelva 200."""
    objetivo = _objetivo()
    for _ in range(90):
        slo.anotar("party", "premium", ok=True, ms=100, objetivo=objetivo)
    for _ in range(5):
        slo.anotar("party", "premium", ok=True, ms=4000, objetivo=objetivo)
    for _ in range(5):
        slo.anotar("party", "premium", ok=False, ms=50, objetivo=objetivo)

    salida = slo.presupuesto(objetivo)
    assert salida["lentas"] == 5
    assert salida["fallidas"] == 5


def test_el_presupuesto_se_dice_en_minutos_y_no_solo_en_porcentaje() -> None:
    """«Te queda el 37 %» no le dice nada a nadie; «te quedan 16 minutos de
    caída este mes» se entiende a la primera."""
    objetivo = _objetivo()
    for _ in range(1000):
        slo.anotar("party", "premium", ok=True, ms=100, objetivo=objetivo)
    salida = slo.presupuesto(objetivo)
    assert "minutos_restantes" in salida
    assert salida["agotado"] is False


def test_agotar_el_presupuesto_dice_que_toca_parar() -> None:
    """Convierte una discusión de opiniones en una cuenta."""
    objetivo = _objetivo()
    for _ in range(100):
        slo.anotar("party", "premium", ok=False, ms=10, objetivo=objetivo)
    salida = slo.presupuesto(objetivo)
    assert salida["agotado"] is True
    assert "arreglar" in salida["que_significa"]


# ── Restauración selectiva ────────────────────────────────────────────────


@pytest.mark.db
def test_no_se_pisa_lo_modificado_despues_sin_decirlo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es trabajo que alguien hizo a sabiendas: sobrescribirlo sin avisar cambia
    un problema por otro peor, porque el primero se conocía."""
    from crmcore.datos.restaurar import restaurar

    from services.party.modelos import Cuenta

    cuenta = Cuenta(tenant_id=tenant_id, nombre="Después", clave_canonica="despues")
    db.add(cuenta)
    db.flush()

    origen = {str(cuenta.id): {"id": str(cuenta.id), "nombre": "Antes"}}
    ayer = datetime.now(timezone.utc) - timedelta(days=1)

    salida = (
        restaurar(
            db,
            Cuenta,
            origen=origen,
            ids=[str(cuenta.id)],
            tenant_id=tenant_id,
            objeto="cuenta",
            desde=ayer,
        )
        if False
        else None
    )
    # La cuenta se creó ahora, así que está modificada después del punto: se
    # salta y se dice.
    from crmcore.errors import NoEncontrado

    with pytest.raises(NoEncontrado) as e:
        restaurar(
            db,
            Cuenta,
            origen=origen,
            ids=[str(cuenta.id)],
            tenant_id=tenant_id,
            objeto="cuenta",
            desde=ayer,
        )
    assert "modificado después" in str(e.value.detalle)
    db.refresh(cuenta)
    assert cuenta.nombre == "Después"
    del salida


@pytest.mark.db
def test_forzando_si_se_restaura(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Es una decisión y tiene que escribirse."""
    from crmcore.datos.restaurar import restaurar

    from services.party.modelos import Cuenta

    cuenta = Cuenta(tenant_id=tenant_id, nombre="Después", clave_canonica="despues")
    db.add(cuenta)
    db.flush()
    origen = {str(cuenta.id): {"id": str(cuenta.id), "nombre": "Antes"}}

    salida = restaurar(
        db,
        Cuenta,
        origen=origen,
        ids=[str(cuenta.id)],
        tenant_id=tenant_id,
        objeto="cuenta",
        desde=datetime.now(timezone.utc) - timedelta(days=1),
        forzar_modificados=True,
    )
    db.refresh(cuenta)
    assert salida["restaurados"] == [str(cuenta.id)]
    assert cuenta.nombre == "Antes"


@pytest.mark.db
def test_no_se_restaura_sobre_otro_tenant(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sería la peor fuga posible: datos de un cliente escritos en la base de
    otro, con rastro que dice que fue una recuperación legítima."""
    from crmcore.datos.restaurar import restaurar
    from crmcore.errors import Conflicto

    from services.party.modelos import Cuenta

    ajena = Cuenta(tenant_id=otro_tenant_id, nombre="Ajena", clave_canonica="ajena")
    db.add(ajena)
    db.flush()

    with pytest.raises(Conflicto) as e:
        restaurar(
            db,
            Cuenta,
            origen={str(ajena.id): {"id": str(ajena.id), "nombre": "x"}},
            ids=[str(ajena.id)],
            tenant_id=tenant_id,
            objeto="cuenta",
        )
    assert e.value.error_code == "restaurar.otro_tenant"


@pytest.mark.db
def test_la_previsualizacion_dice_qué_campos_cambiarian(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Quien restaura casi nunca sabe qué va a sobrescribir, y descubrirlo
    después es cambiar un problema por otro."""
    from crmcore.datos.restaurar import previsualizar

    from services.party.modelos import Cuenta

    cuenta = Cuenta(tenant_id=tenant_id, nombre="Ahora", clave_canonica="ahora")
    db.add(cuenta)
    db.flush()

    diferencias = previsualizar(
        db,
        Cuenta,
        origen={str(cuenta.id): {"id": str(cuenta.id), "nombre": "Antes"}},
        ids=[str(cuenta.id)],
    )
    assert diferencias[0].estado == "distinto"
    assert "nombre" in diferencias[0].campos_distintos
