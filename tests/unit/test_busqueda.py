"""Búsqueda con aislamiento por tenant (CRM-00.01.01.09).

El índice es la tercera vía silenciosa por la que un cliente ve el dato de otro,
después de la caché y del almacén — y la peor de las tres, porque un buscador
**está hecho para encontrar**: una fuga aquí no espera a que alguien acierte con
un identificador, le sirve al primero que teclee «acuerdo marco» los contratos
de todos los clientes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.busqueda import buscar, desindexar, indexar
from crmcore.errors import ErrorValidacion


def _doc(db: Any, tenant_id: UUID, **extra: Any) -> UUID:
    registro = extra.pop("registro_id", None) or uuid4()
    datos: dict[str, Any] = {
        "objeto": "cuenta",
        "titulo": "Construcciones Ejemplo",
        "subtitulo": "",
        "cuerpo": "",
    }
    datos.update(extra)
    indexar(db, tenant_id=tenant_id, registro_id=registro, **datos)
    return registro


# ── Aislamiento ───────────────────────────────────────────────────────────


def test_no_se_encuentra_lo_de_otro_tenant(db: Any, tenant_id: UUID, otro_tenant_id: UUID) -> None:
    """Es lo único que de verdad importa de este módulo."""
    _doc(db, otro_tenant_id, titulo="Contrato marco confidencial")
    db.flush()

    assert buscar(db, tenant_id=tenant_id, texto="contrato") == []
    assert len(buscar(db, tenant_id=otro_tenant_id, texto="contrato")) == 1


def test_el_filtro_por_tenant_va_ademas_de_rls(db: Any, tenant_id: UUID) -> None:
    """Redundante a propósito: si alguien consulta con una sesión sin tenant
    fijado, RLS no filtra y el filtro explícito sí."""
    import inspect

    from crmcore.busqueda.base import BuscadorPostgres

    fuente = inspect.getsource(BuscadorPostgres.buscar)
    assert "DocumentoIndexado.tenant_id == tenant_id" in fuente


# ── Indexado ──────────────────────────────────────────────────────────────


def test_reindexar_no_duplica(db: Any, tenant_id: UUID) -> None:
    """Reindexar un registro editado es la operación normal; crear una entrada
    nueva cada vez lo haría aparecer varias veces en los resultados."""
    registro = uuid4()
    _doc(db, tenant_id, registro_id=registro, titulo="Nombre viejo")
    _doc(db, tenant_id, registro_id=registro, titulo="Nombre nuevo")
    db.flush()

    assert buscar(db, tenant_id=tenant_id, texto="viejo") == []
    assert len(buscar(db, tenant_id=tenant_id, texto="nuevo")) == 1


def test_un_documento_sin_titulo_se_rechaza(db: Any, tenant_id: UUID) -> None:
    """Saldría en los resultados como una fila en blanco que no se puede ni
    pinchar con sentido."""
    with pytest.raises(ErrorValidacion) as exc:
        indexar(db, tenant_id=tenant_id, objeto="cuenta", registro_id=uuid4(), titulo="   ")
    assert exc.value.error_code == "busqueda.sin_titulo"


def test_desindexar_lo_saca_de_los_resultados(db: Any, tenant_id: UUID) -> None:
    """Si no, sigue apareciendo y al pincharlo da un 404 — que es peor que no
    encontrarlo, porque confirma que existe."""
    registro = _doc(db, tenant_id, titulo="Cliente que se va")
    db.flush()
    assert buscar(db, tenant_id=tenant_id, texto="cliente")

    desindexar(db, tenant_id=tenant_id, objeto="cuenta", registro_id=registro)
    db.flush()

    assert buscar(db, tenant_id=tenant_id, texto="cliente") == []


def test_desindexar_algo_que_no_esta_no_falla(db: Any, tenant_id: UUID) -> None:
    desindexar(db, tenant_id=tenant_id, objeto="cuenta", registro_id=uuid4())


# ── Cómo busca ────────────────────────────────────────────────────────────


def test_encuentra_por_una_palabra_del_cuerpo(db: Any, tenant_id: UUID) -> None:
    _doc(db, tenant_id, titulo="Acme", cuerpo="B12345678 acme.es 934567890")
    db.flush()

    assert len(buscar(db, tenant_id=tenant_id, texto="B12345678")) == 1


def test_encuentra_derivando_la_palabra(db: Any, tenant_id: UUID) -> None:
    """Con la configuración de idioma equivocada, «facturas» no encuentra
    «factura» y la búsqueda parece rota sin que nada falle."""
    _doc(db, tenant_id, titulo="Reclamación de factura pendiente")
    db.flush()

    assert len(buscar(db, tenant_id=tenant_id, texto="facturas")) == 1


def test_una_consulta_vacia_no_devuelve_todo(db: Any, tenant_id: UUID) -> None:
    _doc(db, tenant_id)
    db.flush()
    assert buscar(db, tenant_id=tenant_id, texto="   ") == []


def test_un_parentesis_suelto_no_revienta(db: Any, tenant_id: UUID) -> None:
    """Con `to_tsquery`, buscar `(factura` devuelve un error de sintaxis a quien
    no ha escrito nada raro. Por eso se usa `websearch_to_tsquery`."""
    _doc(db, tenant_id, titulo="Factura 2026")
    db.flush()

    assert buscar(db, tenant_id=tenant_id, texto="(factura") is not None


def test_se_puede_excluir_con_un_guion(db: Any, tenant_id: UUID) -> None:
    _doc(db, tenant_id, titulo="Obra Norte", cuerpo="proyecto")
    _doc(db, tenant_id, titulo="Obra Sur", cuerpo="proyecto")
    db.flush()

    resultados = buscar(db, tenant_id=tenant_id, texto="obra -sur")
    assert [r.titulo for r in resultados] == ["Obra Norte"]


def test_se_puede_acotar_por_tipo_de_objeto(db: Any, tenant_id: UUID) -> None:
    _doc(db, tenant_id, objeto="cuenta", titulo="Ferretería Central")
    _doc(db, tenant_id, objeto="contacto", titulo="Ferretería Central SL contacto")
    db.flush()

    solo_cuentas = buscar(db, tenant_id=tenant_id, texto="ferretería", objetos=["cuenta"])
    assert len(solo_cuentas) == 1
    assert solo_cuentas[0].objeto == "cuenta"


def test_el_titulo_pesa_mas_que_el_cuerpo(db: Any, tenant_id: UUID) -> None:
    """Quien busca «Iberdrola» quiere la cuenta que se llama así, no la que la
    menciona de pasada en una nota."""
    _doc(db, tenant_id, titulo="Iberdrola", cuerpo="")
    _doc(db, tenant_id, titulo="Otra empresa", cuerpo="proveedor de iberdrola desde 2019")
    db.flush()

    resultados = buscar(db, tenant_id=tenant_id, texto="iberdrola")
    assert resultados[0].titulo == "Iberdrola"


def test_el_limite_se_respeta(db: Any, tenant_id: UUID) -> None:
    for i in range(6):
        _doc(db, tenant_id, titulo=f"Cliente número {i}")
    db.flush()

    assert len(buscar(db, tenant_id=tenant_id, texto="cliente", limite=3)) == 3


# ── Integración con los servicios ─────────────────────────────────────────


def test_crear_una_cuenta_la_deja_buscable(db: Any, tenant_id: UUID) -> None:
    """Quien acaba de crear una cuenta la busca a los diez segundos: un índice
    con un día de retraso se percibe como que la búsqueda no funciona."""
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.tenancy.context import con_contexto

    from services.party import servicio as svc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    with con_contexto(tenant_id=tenant_id):
        svc.crear_cuenta(uow, nombre="Hormigones del Ebro", web="hormigonesebro.es")
    db.flush()

    resultados = buscar(db, tenant_id=tenant_id, texto="hormigones")
    assert len(resultados) == 1
    assert resultados[0].objeto == "cuenta"


def test_editar_una_cuenta_actualiza_el_indice(db: Any, tenant_id: UUID) -> None:
    """Sin reindexar, la búsqueda sigue encontrando el nombre viejo y no el
    nuevo, que es peor que no encontrar nada."""
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.tenancy.context import con_contexto

    from services.party import servicio as svc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    with con_contexto(tenant_id=tenant_id):
        cuenta = svc.crear_cuenta(uow, nombre="Nombre Antiguo")
        db.flush()
        svc.actualizar_cuenta(uow, cuenta.id, {"nombre": "Razón Social Nueva"})
    db.flush()

    assert buscar(db, tenant_id=tenant_id, texto="antiguo") == []
    assert len(buscar(db, tenant_id=tenant_id, texto="razón social nueva")) == 1


def test_crear_un_lead_lo_deja_buscable(db: Any, tenant_id: UUID) -> None:
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.tenancy.context import con_contexto

    from services.sales import servicio as svc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    with con_contexto(tenant_id=tenant_id):
        svc.crear_lead(uow, empresa="Talleres Mecánicos Rivas", email="info@rivas.example")
    db.flush()

    resultados = buscar(db, tenant_id=tenant_id, texto="rivas")
    assert [r.objeto for r in resultados] == ["lead"]
