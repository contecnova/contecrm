"""Ejecutar una solicitud de derechos, y poder demostrarlo (CRM-07.03.01.03).

El registro de la solicitud con su plazo legal ya estaba. Faltaba lo único que
el interesado nota y lo único que un inspector pide: **hacerlo y poder
demostrarlo**.

Una solicitud que se registra, se tramita a mano y se marca resuelta sin
evidencia deja a la empresa igual que si no tuviera sistema: cuando llegue la
reclamación, la respuesta será «lo hicimos» sin nada detrás.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import ErrorValidacion

from services.party import derechos
from services.party import servicio as svc
from services.party.modelos import Consentimiento, Contacto, SolicitudDerechos


def _persona(db: Any, tenant_id: UUID, email: str = "ana@ejemplo.test") -> Contacto:
    contacto = Contacto(
        tenant_id=tenant_id,
        nombre="Ana",
        apellidos="Pérez",
        nombre_completo="Ana Pérez",
        clave_canonica="ana perez",
        email=email,
        telefono="+34600000000",
        cargo="Directora",
    )
    db.add(contacto)
    db.flush()
    return contacto


def _solicitud(
    db: Any, tenant_id: UUID, tipo: str, *, email: str = "ana@ejemplo.test", contacto_id: Any = None
) -> SolicitudDerechos:
    solicitud = svc.crear_solicitud_derechos(
        db, tenant_id=tenant_id, email_solicitante=email, tipo=tipo, contacto_id=contacto_id
    )
    db.flush()
    return solicitud


# ── Acceso y portabilidad ─────────────────────────────────────────────────


@pytest.mark.db
def test_el_acceso_reune_lo_que_hay_de_la_persona(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    contacto = _persona(db, tenant_id)
    db.add(
        Consentimiento(
            tenant_id=tenant_id,
            contacto_id=contacto.id,
            finalidad="comercial",
            canal="email",
            concedido=True,
            base_legal="consentimiento",
        )
    )
    db.flush()
    solicitud = _solicitud(db, tenant_id, "acceso", contacto_id=contacto.id)

    salida = derechos.ejecutar_acceso(db, solicitud.id)

    fichas = salida["contenido"]["contactos"]
    assert len(fichas) == 1
    assert fichas[0]["ficha"]["email"] == "ana@ejemplo.test"
    assert len(fichas[0]["consentimientos"]) == 1


@pytest.mark.db
def test_el_acceso_encuentra_todas_las_fichas_de_la_misma_persona(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una persona puede estar tres veces con el mismo correo. Resolverla solo
    sobre la ficha enlazada dejaría las otras dos intactas — que es incumplir,
    aunque la solicitud figure resuelta."""
    primera = _persona(db, tenant_id)
    segunda = _persona(db, tenant_id)
    segunda.clave_canonica = "ana perez 2"
    db.flush()
    solicitud = _solicitud(db, tenant_id, "acceso", contacto_id=primera.id)

    salida = derechos.ejecutar_acceso(db, solicitud.id)
    assert len(salida["contenido"]["contactos"]) == 2


@pytest.mark.db
def test_una_persona_que_no_esta_en_el_sistema_no_es_un_error(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La respuesta correcta es «no tenemos nada suyo». Fingir un error dejaría
    la solicitud sin resolver y el plazo corriendo."""
    solicitud = _solicitud(db, tenant_id, "acceso", email="nadie@ejemplo.test")
    salida = derechos.ejecutar_acceso(db, solicitud.id)

    assert salida["contenido"]["contactos"] == []
    assert salida["estado"] == "resuelta"


@pytest.mark.db
def test_el_expediente_no_lleva_metadatos_internos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Al interesado le interesan sus datos, no nuestras claves ni la versión de
    la fila. Incluirlas convierte un expediente legible en un volcado de base de
    datos, que cumple la letra y no el propósito."""
    contacto = _persona(db, tenant_id)
    solicitud = _solicitud(db, tenant_id, "acceso", contacto_id=contacto.id)

    ficha = derechos.ejecutar_acceso(db, solicitud.id)["contenido"]["contactos"][0]["ficha"]
    for tecnico in ("tenant_id", "version", "updated_by"):
        assert tecnico not in ficha


@pytest.mark.db
def test_la_respuesta_dice_que_solo_cubre_este_servicio(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Devolver esto como si fuera todo sería la forma más silenciosa de
    incumplir: el interesado recibiría un expediente incompleto creyendo que es
    completo."""
    solicitud = _solicitud(db, tenant_id, "acceso")
    salida = derechos.ejecutar_acceso(db, solicitud.id)
    assert "party" in salida["alcance"]
    assert "demás servicios" in salida["alcance"]


# ── Supresión ─────────────────────────────────────────────────────────────


@pytest.mark.db
def test_suprimir_exige_confirmacion(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    contacto = _persona(db, tenant_id)
    solicitud = _solicitud(db, tenant_id, "supresion", contacto_id=contacto.id)
    with pytest.raises(ErrorValidacion, match="irreversible"):
        derechos.ejecutar_supresion(db, solicitud.id, confirmado=False)


@pytest.mark.db
def test_suprimir_anonimiza_y_no_borra(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Hay datos que la empresa tiene obligación de conservar. Borrar la fila
    rompería la contabilidad y sería otro incumplimiento distinto."""
    contacto = _persona(db, tenant_id)
    solicitud = _solicitud(db, tenant_id, "supresion", contacto_id=contacto.id)

    derechos.ejecutar_supresion(db, solicitud.id, confirmado=True)

    db.refresh(contacto)
    # La fila sigue: las referencias desde oportunidades y facturas tienen que
    # seguir apuntando a algo.
    assert contacto.id is not None
    assert contacto.email is None and contacto.telefono is None
    assert contacto.nombre == "(suprimido)"
    assert contacto.anonimizado_at is not None


@pytest.mark.db
def test_suprimir_revoca_los_consentimientos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Conservar un «consintió recibir comercial» de alguien cuya ficha ya no lo
    identifica permitiría seguir contándolo como base legal de un envío."""
    contacto = _persona(db, tenant_id)
    db.add(
        Consentimiento(
            tenant_id=tenant_id,
            contacto_id=contacto.id,
            finalidad="comercial",
            canal="email",
            concedido=True,
            base_legal="consentimiento",
        )
    )
    db.flush()
    solicitud = _solicitud(db, tenant_id, "supresion", contacto_id=contacto.id)

    derechos.ejecutar_supresion(db, solicitud.id, confirmado=True)

    consentimiento = db.query(Consentimiento).filter_by(contacto_id=contacto.id).one()
    assert consentimiento.concedido is False


@pytest.mark.db
def test_un_bloqueo_legal_gana_sobre_la_supresion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """No es un fallo del sistema: es la ley resolviendo dos obligaciones que
    chocan. Borrar igualmente destruiría prueba."""
    from crmcore.datos.retencion import bloquear

    contacto = _persona(db, tenant_id)
    bloquear(
        db,
        tenant_id=tenant_id,
        motivo="Litigio 2026/114",
        objeto="contacto",
        objeto_id=contacto.id,
        referencia="JDO-114",
    )
    db.flush()
    solicitud = _solicitud(db, tenant_id, "supresion", contacto_id=contacto.id)

    salida = derechos.ejecutar_supresion(db, solicitud.id, confirmado=True)

    db.refresh(contacto)
    assert contacto.email == "ana@ejemplo.test"
    assert salida["contenido"]["bloqueados"][0]["bloqueo"] == "Litigio 2026/114"
    # La solicitud NO se marca resuelta: alguien tiene que contestar al
    # interesado explicando el conflicto.
    assert salida["estado"] == "en_curso"


@pytest.mark.db
def test_una_solicitud_de_otro_tipo_no_se_suprime(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Ejecutar una supresión sobre una solicitud de acceso sería irreversible y
    sobre la petición equivocada."""
    contacto = _persona(db, tenant_id)
    solicitud = _solicitud(db, tenant_id, "acceso", contacto_id=contacto.id)
    with pytest.raises(ErrorValidacion, match="no de supresión"):
        derechos.ejecutar_supresion(db, solicitud.id, confirmado=True)


# ── Evidencia ─────────────────────────────────────────────────────────────


@pytest.mark.db
def test_la_ejecucion_deja_evidencia_con_huella(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin esto, «lo hicimos» no tiene nada detrás cuando llega la
    reclamación."""
    contacto = _persona(db, tenant_id)
    solicitud = _solicitud(db, tenant_id, "acceso", contacto_id=contacto.id)
    quien = uuid4()

    salida = derechos.ejecutar_acceso(db, solicitud.id, por=quien)

    evidencia = salida["evidencia"]
    assert len(evidencia["huella"]) == 64
    assert evidencia["por"] == str(quien)
    assert evidencia["tamano_bytes"] > 0
    assert "ficha(s) entregada(s)" in evidencia["resumen"]


@pytest.mark.db
def test_la_evidencia_se_puede_comprobar_despues(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Guardar evidencia no sirve de nada si no hay forma de comprobarla: es lo
    que permite demostrar que el expediente entregado es el que consta."""
    contacto = _persona(db, tenant_id)
    solicitud = _solicitud(db, tenant_id, "acceso", contacto_id=contacto.id)

    salida = derechos.ejecutar_acceso(db, solicitud.id)
    db.refresh(solicitud)

    assert derechos.comprobar_evidencia(solicitud, "acceso", salida["contenido"]) is True
    manipulado = {**salida["contenido"], "contactos": []}
    assert derechos.comprobar_evidencia(solicitud, "acceso", manipulado) is False


@pytest.mark.db
def test_el_contenido_entregado_no_se_guarda(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Guardarlo sería conservar exactamente los datos que el interesado quiere
    que dejemos de tener. La huella basta para demostrar qué se entregó."""
    contacto = _persona(db, tenant_id)
    solicitud = _solicitud(db, tenant_id, "acceso", contacto_id=contacto.id)

    derechos.ejecutar_acceso(db, solicitud.id)
    db.refresh(solicitud)

    guardado = str(solicitud.evidencia)
    assert "ana@ejemplo.test" not in guardado
    assert "+34600000000" not in guardado


@pytest.mark.db
def test_la_supresion_deja_huella_de_lo_borrado_sin_guardarlo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Demostrar que se borró algo concreto sin conservar precisamente lo que se
    pidió borrar."""
    contacto = _persona(db, tenant_id)
    solicitud = _solicitud(db, tenant_id, "supresion", contacto_id=contacto.id)

    salida = derechos.ejecutar_supresion(db, solicitud.id, confirmado=True)

    anonimizado = salida["contenido"]["anonimizados"][0]
    assert len(anonimizado["huella_datos_borrados"]) == 64
    assert "email" in anonimizado["campos_borrados"]
    assert "ana@ejemplo.test" not in str(salida["evidencia"])


@pytest.mark.db
def test_la_ejecucion_queda_en_la_auditoria(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que un inspector mira primero: qué se hizo, cuándo y quién."""
    from crmcore.audit.modelos import ApunteAuditoria
    from sqlalchemy import select

    contacto = _persona(db, tenant_id)
    solicitud = _solicitud(db, tenant_id, "acceso", contacto_id=contacto.id)
    derechos.ejecutar_acceso(db, solicitud.id)

    apuntes = (
        db.execute(select(ApunteAuditoria).where(ApunteAuditoria.accion == "derechos.acceso"))
        .scalars()
        .all()
    )
    assert len(apuntes) == 1
