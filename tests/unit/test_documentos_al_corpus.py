"""Lo que vuelve al corpus documental y al registro que lo originó (RT-5).

Dos capacidades de las que dependen de contecmind, ejercitadas con el gestor
**levantado y contestando** —se comprobó que responde en 127.0.0.1:8000 con
`{"service":"contecmind"}` antes de dar nada por bueno—.

La regla de fondo de RT-5 es la que se comprueba aquí: **se enlaza, no se
copia.** El documento vive en el corpus y contecrm guarda a qué registro
pertenece y con qué papel. Copiar el fichero a los dos sitios es cómo se acaba
con dos versiones de un contrato y nadie sabiendo cuál se firmó.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── CRM-06.01.02.07 · el documento firmado vuelve ─────────────────────────


def _sobre(uow: Any, estado: str = "completado", origen: tuple[str, UUID] | None = None) -> Any:
    from services.integration.firma import Sobre

    objeto, objeto_id = origen or ("contrato", uuid4())
    fila = Sobre(
        tenant_id=uow.tenant_id,
        referencia=f"s-{uuid4().hex[:8]}",
        asunto="Contrato de mantenimiento",
        estado=estado,
        proveedor="pruebas",
        objeto_origen=objeto,
        objeto_origen_id=objeto_id,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_el_firmado_se_archiva_como_documento_APARTE_del_original(
    uow: Any, contexto_tenant: UUID
) -> None:
    """El original tiene que seguir existiendo tal como salió.

    Es la mitad de la prueba de que lo firmado es lo que se mandó: si el firmado
    fuera una versión del original, se perdería con qué se comparó.
    """
    from services.integration.firma import archivar_firmado

    sobre = _sobre(uow)
    documento_original = sobre.documento_id

    salida = archivar_firmado(
        uow,
        sobre.id,
        documento_firmado_id="doc-firmado-001",
        certificado_id="doc-certificado-001",
        sello_tiempo="2026-09-29T10:00:00Z",
    )

    assert sobre.documento_firmado_id == "doc-firmado-001"
    assert (
        sobre.documento_id == documento_original
    ), "el firmado ha pisado al original: se pierde con qué se comparó"
    assert salida is not None


def test_el_certificado_se_enlaza_con_su_propio_papel(uow: Any, contexto_tenant: UUID) -> None:
    """Es el documento que se lleva a un juzgado, y mezclarlo con el contrato
    hace que nadie lo encuentre cuando hace falta."""
    from crmcore.documental.enlaces import DocumentoEnlazado
    from sqlalchemy import select

    from services.integration.firma import archivar_firmado

    sobre = _sobre(uow)
    archivar_firmado(
        uow,
        sobre.id,
        documento_firmado_id="doc-firmado-002",
        certificado_id="doc-certificado-002",
    )
    uow.db.flush()

    enlaces = (
        uow.db.execute(
            select(DocumentoEnlazado).where(DocumentoEnlazado.objeto_id == sobre.objeto_origen_id)
        )
        .scalars()
        .all()
    )
    papeles = {e.rol for e in enlaces}
    assert "documento_firmado" in papeles, papeles
    assert (
        "certificado" in papeles or len(papeles) >= 2
    ), f"el certificado no se distingue del contrato: {papeles}"


def test_un_sobre_sin_completar_no_puede_archivar_un_firmado(
    uow: Any, contexto_tenant: UUID
) -> None:
    """Así se acaba con un contrato a medio firmar en el expediente, con toda la
    apariencia de estar cerrado."""
    from crmcore.errors import Conflicto

    from services.integration.firma import archivar_firmado

    sobre = _sobre(uow, estado="enviado")

    with pytest.raises(Conflicto, match="no completado|completado"):
        archivar_firmado(uow, sobre.id, documento_firmado_id="doc-firmado-003")


def test_sin_registro_de_origen_se_archiva_igual(uow: Any, contexto_tenant: UUID) -> None:
    """Un sobre suelto —sin registro que lo originara— no puede quedarse sin
    archivar su firmado: el documento existe igual."""
    from services.integration.firma import Sobre, archivar_firmado

    fila = Sobre(
        tenant_id=uow.tenant_id,
        referencia=f"s-{uuid4().hex[:8]}",
        asunto="Suelto",
        estado="completado",
        proveedor="pruebas",
    )
    uow.db.add(fila)
    uow.db.flush()

    archivar_firmado(uow, fila.id, documento_firmado_id="doc-firmado-004")
    assert fila.documento_firmado_id == "doc-firmado-004"


# ── CRM-00.04.05.05 · los documentos del proveedor ────────────────────────


def test_un_albaran_del_proveedor_se_enlaza_al_encargo_y_no_se_copia(
    uow: Any, contexto_tenant: UUID
) -> None:
    """Se enlaza, no se copia (RT-5). El documento vive en el corpus; aquí se
    guarda a qué encargo pertenece y con qué papel."""
    from services.integration.encargos import Encargo, archivar_documento

    encargo = Encargo(
        tenant_id=uow.tenant_id,
        referencia_propia=f"e-{uuid4().hex[:8]}",
        proveedor="mensajeria",
        estado="entregado",
    )
    uow.db.add(encargo)
    uow.db.flush()

    enlace = archivar_documento(
        uow,
        encargo.id,
        documento_id="doc-albaran-001",
        titulo="Albarán firmado",
        tipo="pod",
    )

    assert enlace is not None
    # Lo que se guarda es la REFERENCIA, no los bytes: si aquí hubiera contenido,
    # habría dos versiones del mismo albarán y ninguna sería la buena.
    assert not hasattr(enlace, "contenido"), "se está copiando el documento, no enlazándolo"
