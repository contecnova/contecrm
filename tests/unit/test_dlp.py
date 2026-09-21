"""Control de fuga de datos y comportamiento anómalo
(CRM-00.05.03.06, CRM-00.05.03.08).

El robo de datos de un CRM casi nunca es una intrusión: es alguien de dentro,
con permiso para leer, que se lleva más de lo que le toca. Los permisos no lo
ven —está haciendo exactamente lo que puede hacer— así que hay que mirar cuánto
y cuándo.

Lo que estas pruebas defienden es lo que separa esto de una alarma que nadie
mira: que el umbral se mida contra el patrón de cada uno, que no se avise cuando
no hay historial con el que comparar, y que bloquear sea una decisión del
cliente mientras que registrar no lo es.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import Prohibido
from crmcore.seguridad import dlp


def _historial(db: Any, tenant_id: UUID, usuario_id: UUID, cantidades: list[int]) -> None:
    """Exportaciones pasadas de esta persona, como las apunta el propio módulo."""
    from crmcore.audit.chain import registrar
    from crmcore.audit.modelos import ApunteAuditoria

    for cantidad in cantidades:
        registrar(
            db,
            accion=dlp.ACCION_EXPORTACION,
            objeto="cuenta",
            datos={"registros": cantidad, "permitido": True, "anomalia": False},
            tenant_id=tenant_id,
        )
    db.flush()
    # El actor lo pone la cadena desde el contexto; en la prueba se fija a mano
    # para no montar una sesión HTTP entera solo por eso.
    for apunte in db.query(ApunteAuditoria).all():
        apunte.actor_id = usuario_id
    db.flush()


@pytest.mark.db
def test_sin_historial_no_se_avisa(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Con dos datos, cualquier tercero parece una anomalía. Un sistema que
    avisa de todo el mundo el primer día se desactiva la primera semana."""
    veredicto = dlp.comprobar_exportacion(
        db, tenant_id=tenant_id, usuario_id=uuid4(), registros=900, objeto="cuenta"
    )
    assert veredicto.permitido is True
    assert veredicto.anomalia is False
    assert veredicto.media_propia is None


@pytest.mark.db
def test_salirse_del_patron_propio_avisa(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Cincuenta registros son normales en un tenant y un incidente en otro: lo
    que decide es la media de cada uno, no un número."""
    usuario = uuid4()
    _historial(db, tenant_id, usuario, [10, 12, 9, 11, 10])

    veredicto = dlp.comprobar_exportacion(
        db, tenant_id=tenant_id, usuario_id=usuario, registros=500, objeto="cuenta"
    )

    assert veredicto.anomalia is True
    assert "veces lo habitual" in veredicto.motivo
    # Avisa pero NO bloquea: salirse de lo habitual no es ilegítimo —el día del
    # cierre todo el mundo exporta más— y cortarlo pararía trabajo real.
    assert veredicto.permitido is True


@pytest.mark.db
def test_lo_habitual_no_avisa(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    usuario = uuid4()
    _historial(db, tenant_id, usuario, [100, 120, 90, 110, 100])

    veredicto = dlp.comprobar_exportacion(
        db, tenant_id=tenant_id, usuario_id=usuario, registros=130, objeto="cuenta"
    )
    assert veredicto.anomalia is False


@pytest.mark.db
def test_el_tope_duro_salta_aunque_sea_su_costumbre(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Es la red de arriba: impide que alguien se lleve la base entera de una
    vez aunque lleve meses acostumbrando al sistema."""
    from crmcore.config import limpiar_cache_settings

    monkeypatch.setenv("DLP_MAX_REGISTROS_EXPORT", "100")
    limpiar_cache_settings()
    usuario = uuid4()
    _historial(db, tenant_id, usuario, [90, 95, 99, 98, 97])

    veredicto = dlp.comprobar_exportacion(
        db, tenant_id=tenant_id, usuario_id=usuario, registros=5000, objeto="cuenta"
    )
    limpiar_cache_settings()
    assert veredicto.anomalia is True
    assert "sobre el tope" in veredicto.motivo


@pytest.mark.db
def test_trocear_para_esquivar_el_tope_tambien_se_ve(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quien de verdad se está llevando datos trocea para no disparar el tope
    por volumen."""
    from crmcore.config import limpiar_cache_settings

    monkeypatch.setenv("DLP_MAX_EXPORTS_HORA", "3")
    limpiar_cache_settings()
    usuario = uuid4()
    _historial(db, tenant_id, usuario, [5, 5, 5, 5])

    veredicto = dlp.comprobar_exportacion(
        db, tenant_id=tenant_id, usuario_id=usuario, registros=5, objeto="cuenta"
    )
    limpiar_cache_settings()
    assert veredicto.anomalia is True
    assert "última hora" in veredicto.motivo


@pytest.mark.db
def test_bloquear_es_opcional_y_registrar_no(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bloquear una migración legítima cuesta tanto como dejar pasar una fuga, y
    esa decisión es del cliente. Lo que no es opcional es el rastro."""
    from crmcore.config import limpiar_cache_settings

    monkeypatch.setenv("DLP_MAX_REGISTROS_EXPORT", "100")
    monkeypatch.setenv("DLP_BLOQUEAR", "true")
    limpiar_cache_settings()

    with pytest.raises(Prohibido) as e:
        dlp.comprobar_exportacion(
            db, tenant_id=tenant_id, usuario_id=uuid4(), registros=5000, objeto="cuenta"
        )
    limpiar_cache_settings()
    assert e.value.error_code == "dlp.bloqueada"

    # Y ha quedado registrada aunque no se sirviera: una exportación bloqueada
    # sin rastro no se puede investigar después.
    assert dlp.anomalias(db, tenant_id) != []


@pytest.mark.db
def test_tambien_se_apuntan_las_permitidas(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """El patrón de mañana se calcula con lo de hoy: apuntar solo lo sospechoso
    haría que la media fuera la media de lo sospechoso."""
    from crmcore.audit.modelos import ApunteAuditoria

    dlp.comprobar_exportacion(
        db, tenant_id=tenant_id, usuario_id=uuid4(), registros=7, objeto="cuenta"
    )
    db.flush()
    apuntes = db.query(ApunteAuditoria).filter_by(accion=dlp.ACCION_EXPORTACION).all()
    assert len(apuntes) == 1
    assert apuntes[0].datos["registros"] == 7


@pytest.mark.db
def test_las_anomalias_salen_del_audit_trail(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una tabla de alertas aparte es un segundo registro de lo mismo que puede
    discrepar del primero, y el primero es el que tiene la cadena de hashes."""
    from crmcore.config import limpiar_cache_settings

    monkeypatch.setenv("DLP_MAX_REGISTROS_EXPORT", "100")
    limpiar_cache_settings()
    dlp.comprobar_exportacion(
        db, tenant_id=tenant_id, usuario_id=uuid4(), registros=500, objeto="cuenta"
    )
    db.flush()
    limpiar_cache_settings()

    salida = dlp.anomalias(db, tenant_id)
    assert len(salida) == 1
    assert salida[0]["registros"] == 500
    assert "sobre el tope" in salida[0]["motivo"]


@pytest.mark.db
def test_apagado_no_estorba(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from crmcore.config import limpiar_cache_settings

    monkeypatch.setenv("DLP_ENABLED", "false")
    limpiar_cache_settings()
    veredicto = dlp.comprobar_exportacion(
        db, tenant_id=tenant_id, usuario_id=uuid4(), registros=10**6, objeto="cuenta"
    )
    limpiar_cache_settings()
    assert veredicto.permitido is True
