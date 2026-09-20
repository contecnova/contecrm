"""Corpus documental delegado en contecmind, frontless (RT-5, CRM-06.01.01.05).

Dos capas, y la distinción decide todo:

  * **Adjunto**: lo que cuelga de un registro. Vive en contecrm y tiene que
    poder subirse aunque el gestor documental no responda.
  * **Documento**: el corpus de la empresa, versionado y aprobado, que ya hace
    contecmind.

Lo que estas pruebas defienden por encima de todo son las dos obligaciones que
**cruzan la frontera**: el bloqueo legal tiene que alcanzar a los documentos
enlazados, y el certificado de destrucción tiene que decir qué queda fuera.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.documental import (
    DocumentoEnlazado,
    documentos_de,
    enlazar,
    inventario_para_certificado,
    mapear_organizacion,
    organizacion_de,
    quitar_enlace,
)
from crmcore.errors import Conflicto, ErrorValidacion, NoDisponible


@pytest.fixture
def dms_activo() -> Any:
    from crmcore.config import limpiar_cache_settings

    os.environ.update(
        DMS_ENABLED="true",
        DMS_BASE_URL="https://dms.ejemplo.test",
        DMS_CLIENT_ID="crm",
        DMS_CLIENT_SECRET="secreto",
    )
    limpiar_cache_settings()
    yield
    for clave in ("DMS_ENABLED", "DMS_BASE_URL", "DMS_CLIENT_ID", "DMS_CLIENT_SECRET"):
        os.environ.pop(clave, None)
    limpiar_cache_settings()


# ── Se puede apagar, y apagado no rompe nada ──────────────────────────────


def test_apagado_el_corpus_lo_dice_sin_reventar() -> None:
    """Es la condición de toda la integración: se activa o no, y sin él el CRM
    funciona igual."""
    from crmcore.config import limpiar_cache_settings
    from crmcore.documental import cliente

    limpiar_cache_settings()
    estado = cliente.estado()
    assert estado["activo"] is False
    # Y dice qué sigue funcionando: sin esa línea, un estado que pone «no
    # alcanzable» hace pensar que no se puede adjuntar nada, y sí se puede.
    assert "adjuntos" in estado["sin_el"]


def test_usarlo_apagado_da_un_error_que_se_entiende() -> None:
    from crmcore.config import limpiar_cache_settings
    from crmcore.documental import cliente

    limpiar_cache_settings()
    with pytest.raises(NoDisponible, match="desactivado"):
        cliente.comprobar()


def test_encendido_y_sin_direccion_lo_dice_al_arrancar() -> None:
    """Descubrirlo cuando alguien abre el primer documento significa que el
    fallo aparece delante de un usuario, días después de desplegar."""
    from crmcore.config import limpiar_cache_settings
    from crmcore.documental import cliente

    os.environ["DMS_ENABLED"] = "true"
    limpiar_cache_settings()
    try:
        with pytest.raises(NoDisponible, match="DMS_BASE_URL"):
            cliente.comprobar()
    finally:
        os.environ.pop("DMS_ENABLED", None)
        limpiar_cache_settings()


# ── Multitenant: sin mapeo no se llama al gestor ──────────────────────────


@pytest.mark.db
def test_sin_organizacion_mapeada_no_se_canjea_token(
    dms_activo: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que hace la integración multitenant de verdad y no una confianza en
    que el de enfrente filtre bien: el gestor solo acepta nombrar organizaciones
    mapeadas, y ese control se pierde si el nombre viaja desde el navegador."""
    from crmcore.documental import cliente

    assert organizacion_de(db, tenant_id) == ""
    with pytest.raises(ErrorValidacion, match="organización"):
        cliente.canjear_token(organizacion="", sujeto=str(uuid4()), rol="reader")


@pytest.mark.db
def test_el_mapeo_se_guarda_y_se_recupera(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    mapear_organizacion(db, tenant_id=tenant_id, organizacion="acme")
    db.flush()
    assert organizacion_de(db, tenant_id) == "acme"
    # Y el de otro tenant no se ve: sería la fuga más difícil de detectar,
    # porque el token saldría bien firmado con la organización del vecino.
    assert organizacion_de(db, otro_tenant_id) == ""


@pytest.mark.db
def test_remapear_no_duplica(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    mapear_organizacion(db, tenant_id=tenant_id, organizacion="acme")
    mapear_organizacion(db, tenant_id=tenant_id, organizacion="acme-iberica")
    db.flush()
    assert organizacion_de(db, tenant_id) == "acme-iberica"


def test_el_rol_se_traduce_de_lo_que_ve_aqui() -> None:
    """Un corpus documental que enseña más que el CRM es una fuga con otro
    nombre."""
    from crmcore.documental.cliente import rol_para

    assert rol_para(frozenset(), es_admin=True) == "admin"
    assert rol_para(frozenset({"adjunto:subir"}), es_admin=False) == "writer"
    assert rol_para(frozenset({"account:read"}), es_admin=False) == "reader"


# ── Enlaces ───────────────────────────────────────────────────────────────


@pytest.mark.db
def test_enlazar_guarda_el_enlace_y_no_una_copia(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Duplicar el contenido crearía dos verdades que divergen en cuanto alguien
    publique una versión nueva allí, y la del CRM sería la vieja sin decirlo."""
    cuenta_id = uuid4()
    enlazar(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=cuenta_id,
        documento_id="doc-123",
        titulo="Contrato marco",
        rol="contrato",
    )
    db.flush()

    documentos = documentos_de(db, objeto_tipo="cuenta", objeto_id=cuenta_id)
    assert documentos[0]["documento_id"] == "doc-123"
    # Se dice dónde vive el estado real: sin esta marca, alguien construirá un
    # informe sobre `titulo` creyendo que está al día.
    assert documentos[0]["estado_en"] == "contecmind"


@pytest.mark.db
def test_enlazar_dos_veces_lo_mismo_no_duplica(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    cuenta_id = uuid4()
    for _ in range(2):
        enlazar(
            db,
            tenant_id=tenant_id,
            objeto_tipo="cuenta",
            objeto_id=cuenta_id,
            documento_id="doc-1",
            rol="contrato",
        )
    db.flush()
    assert db.query(DocumentoEnlazado).count() == 1


@pytest.mark.db
def test_el_mismo_documento_puede_tener_dos_roles(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El mismo documento puede ser el contrato de una cuenta y el anexo de
    otra: el rol es del CRM, no del gestor."""
    cuenta_id = uuid4()
    enlazar(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=cuenta_id,
        documento_id="doc-1",
        rol="contrato",
    )
    enlazar(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=cuenta_id,
        documento_id="doc-1",
        rol="anexo",
    )
    db.flush()
    assert db.query(DocumentoEnlazado).count() == 2


@pytest.mark.db
def test_quitar_el_enlace_no_borra_el_documento(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El CRM no es dueño del documento. Borrarlo allí desde aquí sería que un
    usuario del CRM destruyera el contrato que otro departamento guardó."""
    cuenta_id = uuid4()
    enlace = enlazar(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=cuenta_id,
        documento_id="doc-1",
    )
    db.flush()
    quitar_enlace(db, enlace.id, objeto_id=cuenta_id)
    assert db.query(DocumentoEnlazado).count() == 0


@pytest.mark.db
def test_no_se_quita_el_enlace_de_otro_registro(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.errors import NoEncontrado

    enlace = enlazar(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        documento_id="doc-1",
    )
    db.flush()
    with pytest.raises(NoEncontrado):
        quitar_enlace(db, enlace.id, objeto_id=uuid4())


# ── Las dos obligaciones que cruzan la frontera ───────────────────────────


@pytest.mark.db
def test_un_bloqueo_legal_impide_quitar_el_enlace(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un bloqueo que permite desenlazar la prueba y luego decir «aquí no
    consta» no es un bloqueo: deja el documento fuera del alcance de quien lo
    pidió sin borrar nada, que es peor porque no queda rastro del intento."""
    from crmcore.datos.retencion import bloquear

    cuenta_id = uuid4()
    enlace = enlazar(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=cuenta_id,
        documento_id="doc-1",
        titulo="Contrato",
    )
    bloquear(
        db,
        tenant_id=tenant_id,
        motivo="Litigio 2026/114",
        objeto="cuenta",
        objeto_id=cuenta_id,
        referencia="JDO-114",
    )
    db.flush()

    with pytest.raises(Conflicto, match="bloqueo legal"):
        quitar_enlace(db, enlace.id, objeto_id=cuenta_id)
    assert db.query(DocumentoEnlazado).count() == 1


@pytest.mark.db
def test_el_inventario_para_el_certificado_dice_lo_que_queda_fuera(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Callarlo sería certificar una destrucción que no se ha hecho entera, y el
    cliente se quedaría creyendo que sus contratos ya no existen."""
    enlazar(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        documento_id="doc-1",
        titulo="Contrato marco",
    )
    db.flush()

    inventario = inventario_para_certificado(db, tenant_id)
    assert inventario[0]["documento_id"] == "doc-1"
    assert (
        "no la ejecuta este certificado" in inventario[0]["aviso"]
        or "destrucción" in inventario[0]["aviso"]
    )


@pytest.mark.db
def test_sin_documentos_enlazados_el_inventario_esta_vacio(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    assert inventario_para_certificado(db, tenant_id) == []


@pytest.mark.db
def test_el_certificado_de_destruccion_incluye_lo_de_fuera(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """De punta a punta: lo que importa no es que la función exista, sino que el
    certificado que se entrega al cliente lo lleve."""
    from services.tenancy.baja import _inventario_externo

    enlazar(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        documento_id="doc-9",
        titulo="Contrato",
    )
    db.flush()

    alcance = _inventario_externo(db, tenant_id)
    assert len(alcance["documentos"]) == 1
    assert "NO los destruye este certificado" in alcance["aviso"]
    # Y cada documento dice de qué servicio sale. Antes el inventario solo
    # miraba el esquema de `tenancy` y se avisaba de que estaba incompleto;
    # ahora se compone con lo que contesta cada servicio por el bus, así que
    # la procedencia deja de ser una suposición.
    assert alcance["documentos"][0]["servicio"] == "tenancy"
    assert alcance["por_servicio"] == {"tenancy": 1}


# ── Las dos capas no se confunden ─────────────────────────────────────────


@pytest.mark.db
def test_adjuntar_un_fichero_funciona_sin_gestor_documental(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es la razón de que sean dos capas: que un comercial no pueda adjuntar una
    foto porque un servicio externo está caído sería una regresión, no una
    integración."""
    from crmcore.config import limpiar_cache_settings
    from crmcore.datos.adjuntos import subir

    limpiar_cache_settings()  # DMS apagado
    adjunto = subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre="visita.txt",
        datos=b"foto de la visita",
    )
    assert adjunto.id is not None
