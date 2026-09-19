"""Qué campos ve cada quien (CRM-00.05.02.03, CRM-00.05.03.03).

El permiso por objeto dice si alguien puede leer cuentas. Esto dice **qué
columnas** de una cuenta ve. Sin ello, dar acceso de lectura a un maestro de
clientes es darlo todo —el teléfono del contacto, la facturación, el
identificador fiscal— y la única alternativa práctica acaba siendo no dar
acceso, que es peor para todos.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from crmcore.authz.proyeccion import (
    SENSIBILIDAD_POR_DEFECTO,
    SENSIBILIDADES,
    fijar_politica_campo,
    nivel_para,
    proyectar,
    sensibilidad_de,
)
from crmcore.errors import ErrorValidacion

from services.party.modelos import Contacto, Cuenta

POLITICA = {
    "admin": {"ve_hasta": "especial", "enmascara": "especial"},
    "comercial": {"ve_hasta": "confidencial", "enmascara": "personal"},
    "usuario": {"ve_hasta": "interno", "enmascara": "confidencial"},
    "*": {"ve_hasta": "publico", "enmascara": "interno"},
}


# ── Sensibilidad declarada en el modelo ───────────────────────────────────


def test_la_sensibilidad_se_lee_de_la_columna() -> None:
    """Vive junto a la definición del campo para que quien añada una columna
    sensible vea en la línea de al lado que sus vecinas la declaran."""
    assert sensibilidad_de(Cuenta, "email") == "personal"
    assert sensibilidad_de(Cuenta, "facturacion_anual") == "confidencial"
    assert sensibilidad_de(Contacto, "movil") == "personal"


def test_un_campo_sin_declarar_no_es_publico() -> None:
    """Un campo nuevo que nadie clasificó no puede entrar visible para
    cualquiera: equivocarse hacia la discreción se arregla con una línea de
    configuración; al revés, con una notificación de brecha."""
    assert sensibilidad_de(Cuenta, "nombre") == SENSIBILIDAD_POR_DEFECTO
    assert SENSIBILIDAD_POR_DEFECTO != "publico"


def test_un_campo_que_no_existe_cae_al_defecto() -> None:
    assert sensibilidad_de(Cuenta, "inventado") == SENSIBILIDAD_POR_DEFECTO


# ── La matriz de rol × sensibilidad ───────────────────────────────────────


@pytest.mark.parametrize(
    "rol,sensibilidad,esperado",
    [
        ("usuario", "interno", "claro"),
        ("usuario", "confidencial", "enmascarado"),
        ("usuario", "personal", "oculto"),
        ("comercial", "confidencial", "claro"),
        ("comercial", "personal", "enmascarado"),
        ("comercial", "especial", "oculto"),
        ("admin", "especial", "claro"),
    ],
)
def test_cada_rol_ve_lo_suyo(rol: str, sensibilidad: str, esperado: str) -> None:
    assert nivel_para(sensibilidad, frozenset({rol}), POLITICA) == esperado


def test_con_varios_roles_gana_el_mas_permisivo() -> None:
    """Los roles suman, igual que los permisos: que añadir un rol quitara
    visibilidad sería incomprensible para quien lo administra."""
    assert nivel_para("personal", frozenset({"usuario", "comercial"}), POLITICA) == "enmascarado"
    assert nivel_para("especial", frozenset({"usuario", "admin"}), POLITICA) == "claro"


def test_un_rol_sin_configurar_no_ve_lo_sensible() -> None:
    """Un rol nuevo no puede nacer viendo los datos personales de todos los
    clientes."""
    assert nivel_para("personal", frozenset({"rol_recien_inventado"}), POLITICA) == "oculto"


def test_sin_roles_se_aplica_lo_minimo() -> None:
    assert nivel_para("interno", frozenset(), POLITICA) == "enmascarado"


def test_las_sensibilidades_estan_ordenadas_de_menos_a_mas() -> None:
    """El orden es lo que permite decir «ve hasta confidencial» en vez de
    enumerar niveles; invertirlo daría la política del revés sin fallar."""
    assert SENSIBILIDADES.index("publico") < SENSIBILIDADES.index("personal")
    assert SENSIBILIDADES[-1] == "especial"


# ── Proyección de un registro ─────────────────────────────────────────────


def _cuenta(**extra: Any) -> dict[str, Any]:
    base = {
        "nombre": "Construcciones Ejemplo",
        "email": "contacto@ejemplo.com",
        "telefono": "934567890",
        "facturacion_anual": Decimal("1500000"),
    }
    base.update(extra)
    return base


def test_un_comercial_ve_el_nombre_y_la_facturacion_pero_no_el_telefono_entero(
    db: Any, tenant_id: UUID
) -> None:
    resultado = proyectar(
        _cuenta(),
        objeto="cuenta",
        modelo=Cuenta,
        roles=frozenset({"comercial"}),
        tenant_id=tenant_id,
        db=db,
    )
    assert resultado.datos["nombre"] == "Construcciones Ejemplo"
    assert resultado.datos["facturacion_anual"] == Decimal("1500000")
    assert resultado.datos["telefono"] == "·····7890"
    assert "telefono" in resultado.enmascarados


def test_un_usuario_basico_no_recibe_el_correo(db: Any, tenant_id: UUID) -> None:
    """Oculto significa que **no viene**, no que venga vacío: un `null` es
    indistinguible de un campo sin rellenar."""
    resultado = proyectar(
        _cuenta(),
        objeto="cuenta",
        modelo=Cuenta,
        roles=frozenset({"usuario"}),
        tenant_id=tenant_id,
        db=db,
    )
    assert "email" not in resultado.datos
    assert "email" in resultado.ocultos


def test_un_campo_vacio_no_se_enmascara(db: Any, tenant_id: UUID) -> None:
    """«····» donde no hay nada hace creer que hay algo escondido, y eso es peor
    que un hueco."""
    resultado = proyectar(
        _cuenta(telefono=None),
        objeto="cuenta",
        modelo=Cuenta,
        roles=frozenset({"comercial"}),
        tenant_id=tenant_id,
        db=db,
    )
    assert resultado.datos["telefono"] is None
    assert "telefono" not in resultado.enmascarados


def test_el_administrador_de_plataforma_no_queda_exento(db: Any, tenant_id: UUID) -> None:
    """Su acceso ya está auditado con motivo; eximirle aquí convertiría ese
    privilegio en «ve todo siempre», que es lo que la auditoría acota. Lo que
    tiene es el rol con la política más amplia, no una puerta aparte."""
    import inspect

    from crmcore.authz import proyeccion

    fuente = inspect.getsource(proyeccion.proyectar)
    assert "es_admin else frozenset()" in fuente.replace('"', "'")


# ── Excepciones por campo ─────────────────────────────────────────────────


def test_una_excepcion_puede_ocultar_lo_que_por_nivel_se_veria(db: Any, tenant_id: UUID) -> None:
    fijar_politica_campo(db, tenant_id=tenant_id, objeto="cuenta", campo="nombre", nivel="oculto")
    db.flush()

    resultado = proyectar(
        _cuenta(),
        objeto="cuenta",
        modelo=Cuenta,
        roles=frozenset({"admin"}),
        es_admin=True,
        tenant_id=tenant_id,
        db=db,
    )
    assert "nombre" not in resultado.datos


def test_una_excepcion_puede_abrir_lo_que_por_nivel_se_ocultaria(db: Any, tenant_id: UUID) -> None:
    """La clasificación por niveles acierta en el 95 %; el 5 % restante son
    decisiones que un cliente concreto necesita tomar."""
    fijar_politica_campo(
        db,
        tenant_id=tenant_id,
        objeto="cuenta",
        campo="email",
        nivel="claro",
        rol="usuario",
    )
    db.flush()

    resultado = proyectar(
        _cuenta(),
        objeto="cuenta",
        modelo=Cuenta,
        roles=frozenset({"usuario"}),
        tenant_id=tenant_id,
        db=db,
    )
    assert resultado.datos["email"] == "contacto@ejemplo.com"


def test_una_excepcion_de_un_objeto_no_afecta_a_otro(db: Any, tenant_id: UUID) -> None:
    fijar_politica_campo(db, tenant_id=tenant_id, objeto="contacto", campo="nombre", nivel="oculto")
    db.flush()

    resultado = proyectar(
        _cuenta(),
        objeto="cuenta",
        modelo=Cuenta,
        roles=frozenset({"comercial"}),
        tenant_id=tenant_id,
        db=db,
    )
    assert "nombre" in resultado.datos


def test_una_excepcion_de_un_tenant_no_afecta_a_otro(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    fijar_politica_campo(
        db, tenant_id=otro_tenant_id, objeto="cuenta", campo="nombre", nivel="oculto"
    )
    db.flush()

    resultado = proyectar(
        _cuenta(),
        objeto="cuenta",
        modelo=Cuenta,
        roles=frozenset({"comercial"}),
        tenant_id=tenant_id,
        db=db,
    )
    assert "nombre" in resultado.datos


def test_un_nivel_desconocido_se_rechaza(db: Any, tenant_id: UUID) -> None:
    with pytest.raises(ErrorValidacion) as exc:
        fijar_politica_campo(
            db, tenant_id=tenant_id, objeto="cuenta", campo="x", nivel="medio_visible"
        )
    assert exc.value.error_code == "proyeccion.nivel_desconocido"


# ── Interruptor general ───────────────────────────────────────────────────


def test_con_el_enmascarado_apagado_no_se_toca_nada(
    db: Any, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apagarlo es una decisión válida para una instalación de un solo equipo.
    Lo que no vale es que apagarlo deje el sistema en un estado raro."""
    import os

    from crmcore.config import limpiar_cache_settings

    monkeypatch.setitem(os.environ, "MASKING_ENABLED", "false")
    limpiar_cache_settings()
    try:
        resultado = proyectar(
            _cuenta(),
            objeto="cuenta",
            modelo=Cuenta,
            roles=frozenset({"usuario"}),
            tenant_id=tenant_id,
            db=db,
        )
        assert resultado.datos["email"] == "contacto@ejemplo.com"
        assert resultado.ocultos == ()
    finally:
        limpiar_cache_settings()
