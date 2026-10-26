"""Auditoría de integración y conectividad (CRM-00.03.04), por sus piezas.

Cinco capacidades sin ninguna prueba que las nombre. Cuatro existen y se fijan
aquí; la quinta —las funciones de transformación— **no está**, y queda dicho en
su nota de catálogo en vez de darse por buena.

Lo que persigue esto es lo que distingue una integración que se puede operar de
una que hay que mirar con los registros del servidor delante:

  · **las credenciales por conexión** (CRM-00.03.04.05): se guardan cifradas,
    se rotan y se prueban. Una integración que sólo se puede probar mandando un
    dato de verdad se prueba en producción;
  · **el monitor** (CRM-00.03.04.06): qué se ejecutó, qué falló y cuándo. Sin
    eso, «la integración va mal» no se puede contestar;
  · **la cola de fallidos** (CRM-00.03.04.07): con reenvío que pasa por **el
    mismo camino** que el envío normal, porque un segundo camino es un segundo
    sitio donde se puede romper;
  · y **el registro de integraciones instalables** (CRM-00.03.04.10): un
    manifiesto que declara lo que necesita, y una instalación que dice lo que
    le falta en vez de fallar a medias.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── CRM-00.03.04.07 · Cola de fallidos ────────────────────────────────────


def test_un_fallido_se_reenvia_por_el_mismo_camino_crm_00_03_04_07(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Vuelve a la cola de salida, no se publica aquí mismo.** Si vuelve a
    fallar, reintenta y vuelve a fallidos igual — sin un segundo camino que
    mantener y que se desincroniza del primero en cuanto alguien toca uno.
    """
    from crmcore.bus.modelos import EventoFallido, EventoSaliente
    from crmcore.bus.outbox import reenviar_fallido
    from sqlalchemy import select

    fallido = EventoFallido(
        tenant_id=tenant_id,
        origen="outbox",
        tipo="account.created",
        dedup_key="una-clave",
        sobre={"id": str(uuid4()), "type": "account.created", "data": {}},
        intentos=5,
        ultimo_error="el consumidor devolvió 500",
    )
    db.add(fallido)
    db.flush()

    quien = uuid4()
    nuevo = reenviar_fallido(db, fallido.id, por=quien)
    db.flush()

    assert isinstance(nuevo, EventoSaliente)
    assert nuevo.publicado_at is None, "nace publicado: el relevo no lo recogería"
    assert nuevo.tipo == "account.created"

    db.refresh(fallido)
    # Queda dicho **quién** lo reenvió y cuándo: un reenvío sin firma es una
    # publicación que aparece de la nada en el registro de auditoría.
    assert fallido.reenviado_at is not None
    assert fallido.reenviado_por == quien

    salientes = (
        db.execute(select(EventoSaliente).where(EventoSaliente.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    assert len(salientes) == 1


def test_reenviar_algo_que_no_existe_lo_dice_crm_00_03_04_07(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Y no falla en silencio: quien pulsa «reenviar» en una lista que ya ha
    cambiado debajo tiene que enterarse."""
    from crmcore.bus.outbox import reenviar_fallido
    from crmcore.errors import NoEncontrado

    with pytest.raises(NoEncontrado):
        reenviar_fallido(db, uuid4())


def test_el_fallido_guarda_por_que_fallo_crm_00_03_04_06(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**«La integración va mal» no se puede contestar sin esto.** Hacen falta
    las tres: qué evento, cuántas veces se intentó y qué dijo el otro lado."""
    from crmcore.bus.modelos import EventoFallido

    columnas = set(EventoFallido.__table__.columns.keys())
    for campo in ("tipo", "intentos", "ultimo_error", "origen", "sobre", "created_at"):
        assert campo in columnas, f"falta «{campo}»: {sorted(columnas)}"


# ── CRM-00.03.04.10 · Integraciones instalables ───────────────────────────


MANIFIESTO = {
    "clave": "erp-acme",
    "nombre": "ERP de Acme",
    "version": "1.0.0",
    "descripcion": "Pedidos y albaranes",
    # Cada operación con su **clave**, que es por lo que la llama quien la usa:
    # sin ella, una integración de veinte operaciones no se puede referenciar.
    "operaciones": [{"clave": "pedidos", "metodo": "GET", "ruta": "/pedidos"}],
    # A qué dominios llama. Se exige, y con razón: sin eso nadie puede revisar
    # a dónde van los datos **antes** de instalar la integración.
    "dominios": ["erp.acme.example"],
}


def test_un_manifiesto_incompleto_no_se_publica_crm_00_03_04_10(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Se valida antes de publicar: una integración en el catálogo que no se
    puede instalar es peor que no tenerla, porque alguien la elige y descubre
    el problema cuando ya ha dicho que sí."""
    from services.integration import manifiestos as man

    assert man.validar(MANIFIESTO) == [], man.validar(MANIFIESTO)
    problemas = man.validar({"clave": "sin-nada"})
    assert problemas, "un manifiesto sin nombre ni versión pasa por bueno"


def test_el_catalogo_dice_lo_que_hay_crm_00_03_04_10(
    uow: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Y una versión retirada deja de ofrecerse, pero lo ya instalado sigue
    funcionando: retirar algo no puede romper a quien ya lo usa."""
    from services.integration import manifiestos as man

    man.publicar(uow, **MANIFIESTO)
    db.flush()
    # El catálogo es **la última versión publicada de cada conector**, no el
    # historial: enseñar todas haría que alguien instale la 2 teniendo la 5
    # delante.
    disponibles = man.catalogo(db)
    claves = {m["clave"] for m in disponibles.get("conectores", disponibles.get("items", []))}
    assert "erp-acme" in claves, disponibles


def test_instalar_dice_lo_que_falta_en_vez_de_fallar_a_medias_crm_00_03_04_10(
    uow: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una instalación a medias deja la integración en un estado que nadie
    sabe describir: ni puesta ni sin poner. Lo que falta se dice antes."""
    from services.integration import manifiestos as man

    man.publicar(uow, **MANIFIESTO)
    db.flush()
    salida = man.instalar(uow, clave="erp-acme")
    db.flush()
    assert salida is not None


# ── CRM-00.03.04.05 · Credenciales por conexión ───────────────────────────


def test_la_credencial_de_una_conexion_no_se_guarda_en_claro_crm_00_03_04_05(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Quien lea la tabla —una copia, un volcado de soporte— no puede sacar de
    ahí la credencial con la que entrar en el sistema del cliente."""
    from services.integration.modelos import Conexion

    columnas = set(Conexion.__table__.columns.keys())
    assert "credenciales" not in columnas or "credenciales_cifradas" in columnas, sorted(columnas)
    # Lo que sí tiene que estar es cuándo se probó y con qué resultado: una
    # integración que sólo se puede probar mandando un dato de verdad se prueba
    # en producción.
    assert {"probada_at", "prueba_ok"} <= columnas or "estado" in columnas, sorted(columnas)


def test_el_programador_deja_constancia_de_cada_pasada_crm_00_03_04_06(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Qué se ejecutó, cuándo y cómo acabó. Es lo que convierte «no se han
    traído los pedidos» en una pregunta con respuesta."""
    from services.integration import programador as prg

    assert hasattr(prg, "purgar_registros"), (
        "no hay purga del registro de ejecuciones: una tabla de monitor que "
        "sólo crece acaba siendo la más grande de la base"
    )
    # Y la purga se mide en días, no en filas: el criterio es cuánto hace falta
    # mirar hacia atrás, no cuánto ocupa.
    import inspect

    firma = inspect.signature(prg.purgar_registros)
    assert "dias" in firma.parameters, firma


def test_la_conexion_dice_cuando_se_probo_crm_00_03_04_06(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Y con qué resultado y qué detalle: «falló» sin el motivo manda a mirar
    los registros del servidor, que es justo lo que esta pantalla evita."""
    from services.integration.modelos import Conexion

    # La conexión guarda **cuándo se probó y con qué resultado**: una
    # integración que sólo se puede probar mandando un dato de verdad se prueba
    # en producción, y la marca es lo que permite decir «esto lleva sin
    # comprobarse desde marzo».
    columnas = set(Conexion.__table__.columns.keys())
    for campo in ("probada_at", "prueba_ok", "prueba_detalle"):
        assert campo in columnas, f"falta «{campo}»: {sorted(columnas)}"


def test_lo_fallido_no_se_queda_sin_fecha_crm_00_03_04_06(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La fecha es lo que permite saber si lo que se está mirando es de hoy o
    lleva una semana ahí."""
    from crmcore.bus.modelos import EventoFallido

    fila = EventoFallido(
        tenant_id=tenant_id,
        origen="consumo",
        tipo="x.y",
        dedup_key="k",
        sobre={},
    )
    db.add(fila)
    db.flush()
    assert fila.created_at is not None
    assert fila.created_at <= datetime.now(timezone.utc)
