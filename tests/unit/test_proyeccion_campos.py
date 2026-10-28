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


# ── La otra mitad: filtros, orden y agregados ─────────────────────────────
#
# Proyectar solo la salida deja una puerta que no se ve. Quien no puede leer la
# facturación puede reconstruirla entera si se le deja ordenar por ella —basta
# pedir la lista ascendente y descendente— y, con un filtro de rango, por
# búsqueda binaria en una docena de peticiones.


def test_para_usar_un_campo_hay_que_verlo_en_claro(db: Any, tenant_id: UUID) -> None:
    from crmcore.authz.proyeccion import puede_usar

    # El comercial ve la facturación en claro (confidencial): puede ordenar.
    assert puede_usar(
        "facturacion_anual",
        modelo=Cuenta,
        objeto="cuenta",
        roles=frozenset({"comercial"}),
        tenant_id=tenant_id,
        db=db,
    )
    # Pero el correo lo ve enmascarado, así que no.
    assert not puede_usar(
        "email",
        modelo=Cuenta,
        objeto="cuenta",
        roles=frozenset({"comercial"}),
        tenant_id=tenant_id,
        db=db,
    )


def test_enmascarado_no_basta_para_filtrar(db: Any, tenant_id: UUID) -> None:
    """Quien ve `·····7890` no lee el número, pero si puede filtrar por él lo
    adivina: con un filtro de igualdad, en unos cientos de intentos; con uno de
    rango, en una docena."""
    from crmcore.authz.proyeccion import nivel_para, puede_usar

    roles = frozenset({"usuario"})
    assert nivel_para("confidencial", roles, POLITICA) == "enmascarado"
    assert not puede_usar(
        "facturacion_anual",
        modelo=Cuenta,
        objeto="cuenta",
        roles=roles,
        tenant_id=tenant_id,
        db=db,
    )


def test_el_error_no_dice_por_que(db: Any, tenant_id: UUID) -> None:
    """Responder «no puedes ordenar por facturación porque es confidencial»
    confirma que el campo existe y que tiene valor, que es la mitad de lo que
    quería averiguar quien lo intenta."""
    from crmcore.authz.proyeccion import exigir_campo_usable
    from crmcore.errors import Prohibido

    with pytest.raises(Prohibido) as exc:
        exigir_campo_usable(
            "email",
            modelo=Cuenta,
            objeto="cuenta",
            roles=frozenset({"usuario"}),
            tenant_id=tenant_id,
            db=db,
        )
    assert "confidencial" not in str(exc.value)
    assert "personal" not in str(exc.value)
    assert exc.value.error_code == "proyeccion.campo_no_usable"


def test_las_columnas_ordenables_se_recortan_al_rol(db: Any, tenant_id: UUID) -> None:
    from crmcore.authz.proyeccion import columnas_usables

    candidatas = {"nombre", "created_at", "facturacion_anual", "email"}
    comercial = columnas_usables(
        candidatas,
        modelo=Cuenta,
        objeto="cuenta",
        roles=frozenset({"comercial"}),
        tenant_id=tenant_id,
        db=db,
    )
    basico = columnas_usables(
        candidatas,
        modelo=Cuenta,
        objeto="cuenta",
        roles=frozenset({"usuario"}),
        tenant_id=tenant_id,
        db=db,
    )
    assert "facturacion_anual" in comercial and "email" not in comercial
    assert "facturacion_anual" not in basico


def test_ordenar_por_un_campo_no_visible_se_rechaza(db: Any, tenant_id: UUID) -> None:
    """La comprobación va en el punto central de ordenación, no en cada
    listado: hay uno por recurso y el que se olvide es el que se explota."""
    from types import SimpleNamespace

    from crmcore.errors import ErrorValidacion
    from crmcore.http.pagination import ParametrosPagina, aplicar_orden_y_cursor
    from sqlalchemy import select

    principal = SimpleNamespace(
        roles=frozenset({"usuario"}), es_admin_plataforma=False, tenant_id=tenant_id
    )
    params = ParametrosPagina.desde_query(limite=50, cursor="", orden="-facturacion_anual")

    with pytest.raises(ErrorValidacion) as exc:
        aplicar_orden_y_cursor(
            select(Cuenta),
            Cuenta,
            params,
            columnas_permitidas={"created_at", "facturacion_anual"},
            objeto="cuenta",
            principal=principal,
            db=db,
        )
    assert exc.value.error_code == "paginacion.orden_no_permitido"


def test_quien_puede_verlo_si_ordena_por_el(db: Any, tenant_id: UUID) -> None:
    from types import SimpleNamespace

    from crmcore.http.pagination import ParametrosPagina, aplicar_orden_y_cursor
    from sqlalchemy import select

    principal = SimpleNamespace(
        roles=frozenset({"comercial"}), es_admin_plataforma=False, tenant_id=tenant_id
    )
    params = ParametrosPagina.desde_query(limite=50, cursor="", orden="-facturacion_anual")

    consulta = aplicar_orden_y_cursor(
        select(Cuenta),
        Cuenta,
        params,
        columnas_permitidas={"created_at", "facturacion_anual"},
        objeto="cuenta",
        principal=principal,
        db=db,
    )
    assert consulta is not None


# ── Lo que no se puede enmascarar sin romper el contrato ──────────────────


def test_el_identificador_nunca_se_enmascara() -> None:
    """Enmascararlo devolvía «·······e9be» donde el contrato declara un UUID, y
    la respuesta reventaba con un 500 antes de llegar al cliente. Tampoco
    protegía nada: el cliente acaba de escribirlo en la URL para pedir el
    registro."""
    from crmcore.authz.proyeccion import CAMPOS_ESTRUCTURALES, _nivel_del_campo

    from services.party.modelos import Cuenta

    for campo in ("id", "tenant_id", "version", "created_at"):
        assert campo in CAMPOS_ESTRUCTURALES
        assert _nivel_del_campo(campo, Cuenta, frozenset(), {}, {}) == "claro"


def test_un_valor_que_no_es_texto_no_se_enmascara() -> None:
    """Enmascarar es sustituir caracteres por puntos: sobre un número o una
    lista produce una cadena que ya no encaja en el tipo declarado."""
    from crmcore.authz.proyeccion import enmascarable

    from services.party.modelos import Cuenta

    assert enmascarable(Cuenta, "nombre", "ACME Ibérica")
    assert not enmascarable(Cuenta, "calidad", 87)
    assert not enmascarable(Cuenta, "campos", {"a": 1})
    assert not enmascarable(Cuenta, "roles", ["a", "b"])


@pytest.mark.db
def test_un_principal_sin_rol_conocido_recibe_una_respuesta_valida(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El caso que rompía de verdad: una cuenta de servicio.

    El rol `integracion` no estaba en la política, caía al comodín —que
    enmascara hasta `interno`— y se enmascaraba TODO, incluidos el identificador
    y los enteros. Ninguna integración podía leer una ficha: recibía un 500.
    """
    from crmcore.authz.proyeccion import proyectar

    from services.party.modelos import Cuenta

    cuenta = Cuenta(tenant_id=tenant_id, nombre="ACME Ibérica", clave_canonica="acme iberica")
    db.add(cuenta)
    db.flush()

    proyeccion = proyectar(
        cuenta.a_dict(),
        objeto="cuenta",
        modelo=Cuenta,
        roles=frozenset({"rol_que_nadie_configuro"}),
    )
    datos = proyeccion.datos
    # Los tipos se conservan: es lo que hace que la respuesta sea válida.
    assert datos["id"] == cuenta.id
    assert isinstance(datos["version"], int)
    assert isinstance(datos["campos"], dict)
    # Y lo que sí es texto sigue protegido.
    assert datos["nombre"] != "ACME Ibérica" and "·" in datos["nombre"]


def test_las_excepciones_de_campo_se_pueden_LEER(db: Any, tenant_id: UUID) -> None:
    """Se podían escribir y no leer, que es lo mismo que no escribirlas.

    La ruta que las crea justifica escribirlas con que «una excepción que vive
    en la cabeza de quien la pidió es la que nadie revisa al año siguiente».
    Sin forma de leerlas, la excepción vivía igual de escondida, sólo que en
    una tabla: se podía declarar que el margen lo tapa también dirección y
    nadie podía comprobarlo después. Eso convierte un control en papeleo.

    Van ordenadas **por objeto y campo**, no por fecha, porque se revisan por
    el dato que tapan: la pregunta es «qué pasa con el margen», no «qué se
    declaró en marzo».
    """
    from crmcore.authz.proyeccion import politicas_de_campo

    fijar_politica_campo(
        db, tenant_id=tenant_id, objeto="oportunidad", campo="margen", nivel="oculto"
    )
    fijar_politica_campo(
        db,
        tenant_id=tenant_id,
        objeto="contacto",
        campo="movil",
        nivel="claro",
        rol="soporte",
    )
    db.flush()

    filas = politicas_de_campo(db, tenant_id)
    assert [(f["objeto"], f["campo"], f["rol"], f["nivel"]) for f in filas] == [
        ("contacto", "movil", "soporte", "claro"),
        ("oportunidad", "margen", "*", "oculto"),
    ], "ordenadas por el dato que tapan, no por cuándo se declararon"
    # Y se dice cuál es para todos y cuál para un rol: son dos cosas muy
    # distintas de revisar, y «*» leído de pasada parece un rol más.
    assert [f["para_todos"] for f in filas] == [False, True]


def test_sin_excepciones_la_lista_es_vacia_y_no_un_error(db: Any, tenant_id: UUID) -> None:
    """Una instalación donde la sensibilidad sale entera de la clasificación es
    el caso bueno, no un fallo: tiene que poder contestarse."""
    from crmcore.authz.proyeccion import politicas_de_campo

    assert politicas_de_campo(db, tenant_id) == []
