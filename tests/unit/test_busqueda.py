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


# ── Escribir más no puede encontrar menos ─────────────────────────────────


def test_el_ultimo_termino_busca_por_prefijo(db: Any, tenant_id: UUID) -> None:
    """**Medido el 03-11-2026** haciendo el trabajo de verdad contra la
    instalación servida: se da de alta una oportunidad «Venta 924762», se
    busca «Venta» y aparece, se escribe «Venta 9» y **desaparece**.

    `websearch_to_tsquery` casa palabras enteras, y «9» no es una palabra de
    «924762». Quien teclea escribe el principio de lo que ve, así que la
    búsqueda se vaciaba justo cuando el usuario afinaba — que es lo contrario
    de lo que espera cualquiera y la forma más rápida de que deje de usarla.
    """
    _doc(db, tenant_id, titulo="Venta 924762")
    db.flush()

    # Cada paso de lo que se teclea encuentra lo mismo, no menos.
    for escrito in ("Venta", "Venta 9", "Venta 92", "Venta 924762"):
        encontrados = [r.titulo for r in buscar(db, tenant_id=tenant_id, texto=escrito)]
        assert encontrados == ["Venta 924762"], f"con «{escrito}» salió {encontrados}"

    # Y el prefijo es del ÚLTIMO término, no de todos: «9 Venta» no es lo
    # mismo que «Venta 9», y lo que no empieza así no se trae de propina.
    assert buscar(db, tenant_id=tenant_id, texto="Compra 9") == []


def test_una_consulta_sin_palabras_no_revienta(db: Any, tenant_id: UUID) -> None:
    """La red del prefijo. Una consulta que se queda sin lexemas —todo
    palabras vacías, o un paréntesis suelto— daría `':*'`, que es un error de
    sintaxis de Postgres en la cara de quien no ha escrito nada raro."""
    _doc(db, tenant_id, titulo="Construcciones Ejemplo")
    db.flush()

    for escrito in ("de la", "(", "   ", "-"):
        assert buscar(db, tenant_id=tenant_id, texto=escrito) == [], escrito
    # Y lo normal sigue encontrándose: si esto fallara, el vacío de arriba
    # podría ser «la búsqueda está rota» en vez de «eso no es una consulta».
    assert len(buscar(db, tenant_id=tenant_id, texto="construcciones")) == 1


# ── Lo que está en la papelera no se encuentra (10-11-2026) ───────────────


def test_lo_que_esta_en_la_papelera_no_se_encuentra_y_vuelve_al_restaurarlo(
    db: Any, tenant_id: UUID
) -> None:
    """Borrar no tocaba el índice: el buscador ofrecía la cuenta borrada, se
    pulsaba y la ficha decía que no existe. Medido contra la pila: 40
    resultados de cuentas ya borradas. Y restaurar tiene que devolverla sin
    que nadie reindexe nada."""
    from crmcore.datos import papelera
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.tenancy.context import con_contexto

    from services.party import servicio as svc
    from services.party.modelos import Cuenta

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    with con_contexto(tenant_id=tenant_id):
        cuenta = svc.crear_cuenta(uow, nombre="Hormigones del Turia")
        db.flush()
        assert len(buscar(db, tenant_id=tenant_id, texto="turia")) == 1

        entrada = papelera.borrar(db, cuenta, objeto="cuenta")
        db.flush()
        assert buscar(db, tenant_id=tenant_id, texto="turia") == []

        papelera.restaurar(db, entrada.id, modelos={"cuenta": Cuenta})
        db.flush()
        assert len(buscar(db, tenant_id=tenant_id, texto="turia")) == 1


@pytest.mark.db
def test_un_caso_se_encuentra_por_su_codigo(db: Any, tenant_id: UUID) -> None:
    """El buscador de arriba no preguntaba por casos: «CS-00777» daba «Nada
    coincide» y el agente buscaba a mano en las cincuenta filas cargadas."""
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.tenancy.context import con_contexto

    from services.service import servicio as svc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    with con_contexto(tenant_id=tenant_id):
        caso = svc.abrir_caso(uow, asunto="La prensa vibra al arrancar")
    db.flush()

    resultados = buscar(db, tenant_id=tenant_id, texto=caso.codigo)
    assert [(r.objeto, r.titulo) for r in resultados] == [("caso", "La prensa vibra al arrancar")]
    assert resultados[0].subtitulo == caso.codigo
