"""Retención automática (CRM-07.03.01.01) y bloqueo legal (CRM-07.03.01.06).

Van juntos porque separarlos es un problema legal: una purga que no consulta los
bloqueos borra, puntualmente y sin que nadie se entere, justo la prueba que un
juzgado acaba de pedir.

Lo que estas pruebas defienden, por encima de todo: **no decidir no puede
significar destruir**, y **ante la duda no se borra**.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.datos import retencion as ret
from crmcore.errors import Conflicto, ErrorValidacion

from services.party.modelos import Actividad, Cuenta
from services.party.normalizacion import clave_canonica_empresa


def _actividad(db: Any, tenant_id: UUID, *, completada_hace_dias: int | None) -> Actividad:
    completada = (
        datetime.now(timezone.utc) - timedelta(days=completada_hace_dias)
        if completada_hace_dias is not None
        else None
    )
    fila = Actividad(tenant_id=tenant_id, tipo="tarea", asunto="Llamar", completada_at=completada)
    db.add(fila)
    db.flush()
    return fila


def _politica(db: Any, tenant_id: UUID, clase: str, dias: int) -> None:
    db.add(ret.PoliticaRetencion(tenant_id=tenant_id, clase=clase, dias=dias))
    db.flush()


# ── Política ──────────────────────────────────────────────────────────────


def test_sin_politica_no_se_purga_nada(db: Any, tenant_id: UUID) -> None:
    """No decidir no puede significar destruir: es el valor por defecto a
    propósito."""
    _actividad(db, tenant_id, completada_hace_dias=4_000)

    informe = ret.purgar(db, tenant_id=tenant_id, clase="actividades", simular=True)

    assert informe.dias == 0
    assert informe.candidatos == 0


def test_la_politica_del_tenant_manda_sobre_el_valor_declarado(db: Any, tenant_id: UUID) -> None:
    _politica(db, tenant_id, "actividades", 90)
    assert ret.dias_efectivos(db, tenant_id=tenant_id, clase="actividades") == 90


def test_la_politica_de_un_tenant_no_afecta_a_otro(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    _politica(db, tenant_id, "actividades", 30)
    assert ret.dias_efectivos(db, tenant_id=otro_tenant_id, clase="actividades") == 0


def test_una_clase_que_el_servicio_no_declara_se_rechaza(db: Any, tenant_id: UUID) -> None:
    with pytest.raises(ErrorValidacion) as exc:
        ret.purgar(db, tenant_id=tenant_id, clase="inventada")
    assert exc.value.error_code == "retencion.clase_desconocida"


# ── Declaración de clases ─────────────────────────────────────────────────


def test_una_clase_con_un_campo_de_fecha_inexistente_se_rechaza_al_declararla() -> None:
    """Descubrirlo al purgar sería un error en mitad de una tarea nocturna, con
    la mitad de las clases ya procesadas y nadie delante."""
    with pytest.raises(ValueError, match="no tiene ese campo"):
        ret.registrar_clase(
            ret.ClaseDato(clave="_mala", descripcion="x", modelo=Cuenta, campo_fecha="inventado")
        )


def test_una_clase_logica_sobre_un_modelo_sin_papelera_se_rechaza() -> None:
    from crmcore.datos.retencion import PoliticaRetencion

    with pytest.raises(ValueError, match="deleted_at"):
        ret.registrar_clase(
            ret.ClaseDato(
                clave="_mala2",
                descripcion="x",
                modelo=PoliticaRetencion,
                campo_fecha="created_at",
                borrado="logico",
            )
        )


# ── Purga ─────────────────────────────────────────────────────────────────


def test_simula_por_defecto(db: Any, tenant_id: UUID) -> None:
    """Lo que enseña cuántas filas se llevaría por delante hay que poder verlo
    antes, no después."""
    _politica(db, tenant_id, "actividades", 30)
    vieja = _actividad(db, tenant_id, completada_hace_dias=100)

    informe = ret.purgar(db, tenant_id=tenant_id, clase="actividades")

    assert informe.candidatos == 1
    assert informe.purgados == 0
    assert vieja.deleted_at is None


def test_al_ejecutarla_borra_lo_que_pasó_el_plazo(db: Any, tenant_id: UUID) -> None:
    _politica(db, tenant_id, "actividades", 30)
    vieja = _actividad(db, tenant_id, completada_hace_dias=100)
    reciente = _actividad(db, tenant_id, completada_hace_dias=5)

    informe = ret.purgar(db, tenant_id=tenant_id, clase="actividades", simular=False)

    assert informe.purgados == 1
    assert vieja.deleted_at is not None
    assert reciente.deleted_at is None


def test_lo_que_no_tiene_fecha_no_se_purga(db: Any, tenant_id: UUID) -> None:
    """Una tarea abierta de hace tres años sigue siendo la única cosa pendiente
    de ese cliente: por eso se cuenta desde que se completó y no desde que se
    creó."""
    _politica(db, tenant_id, "actividades", 30)
    abierta = _actividad(db, tenant_id, completada_hace_dias=None)

    informe = ret.purgar(db, tenant_id=tenant_id, clase="actividades", simular=False)

    assert informe.purgados == 0
    assert abierta.deleted_at is None


def test_la_purga_no_toca_a_otro_tenant(db: Any, tenant_id: UUID, otro_tenant_id: UUID) -> None:
    _politica(db, tenant_id, "actividades", 30)
    mia = _actividad(db, tenant_id, completada_hace_dias=100)
    ajena = _actividad(db, otro_tenant_id, completada_hace_dias=100)

    ret.purgar(db, tenant_id=tenant_id, clase="actividades", simular=False)

    assert mia.deleted_at is not None
    assert ajena.deleted_at is None


def test_el_tope_acota_cada_pasada(db: Any, tenant_id: UUID) -> None:
    """Borrar cien mil filas en una transacción la mantiene abierta minutos,
    bloquea el vacuum y, si falla a la mitad, revierte entero."""
    _politica(db, tenant_id, "actividades", 30)
    for _ in range(5):
        _actividad(db, tenant_id, completada_hace_dias=100)

    informe = ret.purgar(db, tenant_id=tenant_id, clase="actividades", simular=False, tope=2)

    assert informe.purgados == 2


def test_la_purga_queda_auditada(db: Any, tenant_id: UUID) -> None:
    """Un día faltan diez mil filas y hay que poder saber si las borró la
    retención o alguien."""
    from crmcore.audit.modelos import ApunteAuditoria
    from sqlalchemy import select

    _politica(db, tenant_id, "actividades", 30)
    _actividad(db, tenant_id, completada_hace_dias=100)
    ret.purgar(db, tenant_id=tenant_id, clase="actividades", simular=False)
    db.flush()

    lineas = (
        db.execute(select(ApunteAuditoria).where(ApunteAuditoria.accion == "retencion.purgada"))
        .scalars()
        .all()
    )
    assert len(lineas) == 1
    assert lineas[0].datos["purgados"] == 1


# ── Bloqueo legal ─────────────────────────────────────────────────────────


def test_un_bloqueo_abstiene_la_purga_entera(db: Any, tenant_id: UUID) -> None:
    """Afinar cuál de cien mil registros cubre el bloqueo cuesta más que esperar
    a que se levante, y equivocarse en esa criba borra justo lo que había que
    conservar."""
    _politica(db, tenant_id, "actividades", 30)
    _actividad(db, tenant_id, completada_hace_dias=100)
    bloqueo = ret.bloquear(db, tenant_id=tenant_id, motivo="Pleito con el cliente X")

    informe = ret.purgar(db, tenant_id=tenant_id, clase="actividades", simular=False)

    assert informe.purgados == 0
    assert informe.bloqueado_por == str(bloqueo.id)


def test_un_bloqueo_sobre_otro_objeto_no_frena_esta_purga(db: Any, tenant_id: UUID) -> None:
    _politica(db, tenant_id, "actividades", 30)
    _actividad(db, tenant_id, completada_hace_dias=100)
    ret.bloquear(db, tenant_id=tenant_id, motivo="Pleito", objeto="cuentas")

    informe = ret.purgar(db, tenant_id=tenant_id, clase="actividades", simular=False)

    assert informe.purgados == 1


def test_un_bloqueo_exige_motivo_escrito(db: Any, tenant_id: UUID) -> None:
    """Puede durar años y sobrevivir a quien lo puso; «¿por qué no se puede
    borrar esto?» es una pregunta que alguien hará cuando ya no esté."""
    with pytest.raises(ErrorValidacion) as exc:
        ret.bloquear(db, tenant_id=tenant_id, motivo="   ")
    assert exc.value.error_code == "retencion.bloqueo_sin_motivo"


def test_un_bloqueo_sobre_un_registro_necesita_su_tipo(db: Any, tenant_id: UUID) -> None:
    with pytest.raises(ErrorValidacion) as exc:
        ret.bloquear(db, tenant_id=tenant_id, motivo="x", objeto_id=uuid4())
    assert exc.value.error_code == "retencion.bloqueo_sin_objeto"


def test_levantar_exige_motivo_y_no_borra_la_fila(db: Any, tenant_id: UUID) -> None:
    """Un bloqueo tiene que poder demostrarse después, con sus fechas."""
    bloqueo = ret.bloquear(db, tenant_id=tenant_id, motivo="Inspección")

    with pytest.raises(ErrorValidacion):
        ret.levantar(db, bloqueo.id, motivo="")

    ret.levantar(db, bloqueo.id, motivo="Archivado el expediente")
    assert bloqueo.activo is False
    assert bloqueo.levantado_at is not None
    assert bloqueo.motivo_levantamiento == "Archivado el expediente"


def test_no_se_levanta_dos_veces(db: Any, tenant_id: UUID) -> None:
    bloqueo = ret.bloquear(db, tenant_id=tenant_id, motivo="x")
    ret.levantar(db, bloqueo.id, motivo="y")
    with pytest.raises(Conflicto) as exc:
        ret.levantar(db, bloqueo.id, motivo="z")
    assert exc.value.error_code == "retencion.bloqueo_ya_levantado"


def test_tras_levantarlo_la_purga_vuelve_a_correr(db: Any, tenant_id: UUID) -> None:
    _politica(db, tenant_id, "actividades", 30)
    _actividad(db, tenant_id, completada_hace_dias=100)
    bloqueo = ret.bloquear(db, tenant_id=tenant_id, motivo="Pleito")
    ret.levantar(db, bloqueo.id, motivo="Resuelto")
    db.flush()

    assert ret.purgar(db, tenant_id=tenant_id, clase="actividades", simular=False).purgados == 1


def test_el_ambito_va_de_lo_general_a_lo_concreto(db: Any, tenant_id: UUID) -> None:
    registro = uuid4()
    ret.bloquear(db, tenant_id=tenant_id, motivo="Pleito", objeto="cuentas", objeto_id=registro)

    assert ret.bajo_bloqueo(db, tenant_id=tenant_id, objeto="cuentas", objeto_id=registro)
    # Otro registro del mismo tipo no está cubierto.
    assert not ret.bajo_bloqueo(db, tenant_id=tenant_id, objeto="cuentas", objeto_id=uuid4())
    # Ni otro tipo.
    assert not ret.bajo_bloqueo(db, tenant_id=tenant_id, objeto="contactos", objeto_id=registro)


def test_un_bloqueo_no_alcanza_a_otro_tenant(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    ret.bloquear(db, tenant_id=tenant_id, motivo="Pleito")
    assert not ret.hay_algun_bloqueo(db, otro_tenant_id)


# ── La papelera lo respeta ────────────────────────────────────────────────


def test_la_papelera_no_purga_lo_bloqueado(db: Any, tenant_id: UUID) -> None:
    """El docstring de la papelera prometía respetar el bloqueo desde el primer
    día; hasta ahora la función devolvía `False` siempre y lo decía."""
    from crmcore.datos.papelera import borrar
    from crmcore.datos.papelera import purgar as purgar_papelera

    cuenta = Cuenta(
        tenant_id=tenant_id,
        nombre="Cliente en pleito",
        clave_canonica=clave_canonica_empresa("Cliente en pleito"),
    )
    db.add(cuenta)
    db.flush()
    entrada = borrar(db, cuenta, objeto="cuentas", etiqueta=cuenta.nombre)
    entrada.purgable_at = datetime.now(timezone.utc) - timedelta(days=1)
    ret.bloquear(db, tenant_id=tenant_id, motivo="Pleito", objeto="cuentas", objeto_id=cuenta.id)
    db.flush()

    purgados = purgar_papelera(
        db, tenant_id=tenant_id, modelos={"cuentas": Cuenta}, motivo="Plazo cumplido"
    )

    assert purgados == {}
    assert db.get(Cuenta, cuenta.id) is not None


def test_la_papelera_purga_lo_no_bloqueado_aunque_haya_otro_bloqueo(
    db: Any, tenant_id: UUID
) -> None:
    """Un bloqueo sobre la cuenta de un cliente con pleito no debe impedir
    purgar el resto de la papelera, que puede ser el 99 %."""
    from crmcore.datos.papelera import borrar
    from crmcore.datos.papelera import purgar as purgar_papelera

    otra = Cuenta(
        tenant_id=tenant_id,
        nombre="Cliente cualquiera",
        clave_canonica=clave_canonica_empresa("Cliente cualquiera"),
    )
    db.add(otra)
    db.flush()
    entrada = borrar(db, otra, objeto="cuentas", etiqueta=otra.nombre)
    entrada.purgable_at = datetime.now(timezone.utc) - timedelta(days=1)
    ret.bloquear(db, tenant_id=tenant_id, motivo="Pleito", objeto="cuentas", objeto_id=uuid4())
    db.flush()

    purgados = purgar_papelera(
        db, tenant_id=tenant_id, modelos={"cuentas": Cuenta}, motivo="Plazo cumplido"
    )

    assert purgados == {"cuentas": 1}
