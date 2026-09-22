"""Gobierno único de la suite (CRM-00.01.07).

Lo que se prueba es lo que decide si esto sirve: que la baja vaya primero, que un
fallo se aparte y se vea, que lo que sobra en la otra herramienta se señale como
acceso abierto, y que no se pise en silencio lo que alguien cambió allí.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado

from services.tenancy import suite
from services.tenancy.modelos import Tenant, UnidadNegocio


@pytest.fixture
def tenant(db: Any, tenant_id: UUID) -> Tenant:
    fila = db.get(Tenant, tenant_id)
    if fila is None:
        fila = Tenant(id=tenant_id, slug="cliente", nombre="Cliente S.A.")
        db.add(fila)
        db.flush()
    return fila


@pytest.fixture
def con_cifrado(monkeypatch: Any) -> Any:
    """Las credenciales de la herramienta van cifradas: en claro serían la llave
    de administración de otra herramienta guardada en una tabla que consulta
    media aplicación."""
    from crmcore.config import get_settings

    monkeypatch.setenv("ENCRYPTION_KEY", "maestra-de-pruebas-suficientemente-larga")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mind(db: Any, tenant_id: UUID, tenant: Tenant, monkeypatch: Any, con_cifrado: Any) -> Any:
    from crmcore.red import guard_url

    monkeypatch.setattr(guard_url, "exigir", lambda url: None)
    return suite.conectar(
        db,
        tenant_id,
        nombre="contecmind",
        base_url="https://mind.ejemplo.com",
        credenciales={"token": "secreto"},
        tipo="contecmind",
        mapeo_roles={
            "roles": {"director": "admin", "comercial": "editor", "becario": "lector"},
            "precedencia": ["admin", "editor", "lector"],
        },
    )


# ── Identidad única (CRM-00.01.07.01) ─────────────────────────────────────


@pytest.mark.db
def test_la_identidad_es_una_sola(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, tenant: Tenant
) -> None:
    """Dos herramientas con dos nombres distintos para el mismo cliente es como
    empieza el trabajo manual de conciliar, y ya no para."""
    identidad = suite.identidad_de_tenant(db, tenant_id)
    assert identidad["slug"] == "cliente"
    assert identidad["id"] == str(tenant_id)


@pytest.mark.db
def test_un_tenant_que_no_existe_no_se_inventa(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    with pytest.raises(NoEncontrado):
        suite.identidad_de_tenant(db, uuid4())


@pytest.mark.db
def test_la_organizacion_va_plana_con_el_padre_dentro(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, tenant: Tenant
) -> None:
    """Un árbol anidado obliga a cada consumidor a recorrerlo, y la mitad de las
    herramientas quieren la lista."""
    norte = UnidadNegocio(tenant_id=tenant_id, codigo="norte", nombre="Norte")
    db.add(norte)
    db.flush()
    db.add(UnidadNegocio(tenant_id=tenant_id, codigo="bilbao", nombre="Bilbao", padre_id=norte.id))
    db.flush()

    unidades = suite.organizacion_de_tenant(db, tenant_id)
    hijo = [u for u in unidades if u["codigo"] == "bilbao"][0]
    assert hijo["padre"] == str(norte.id)


# ── Mapeo de roles (CRM-00.01.07.04) ──────────────────────────────────────


@pytest.mark.db
def test_el_rol_se_traduce_por_herramienta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """El mismo usuario es «director» aquí y «admin» en el gestor documental, y
    eso lo decide cada cliente."""
    assert suite.rol_en(mind, ["director"]) == "admin"
    assert suite.rol_en(mind, ["comercial"]) == "editor"


@pytest.mark.db
def test_un_rol_sin_mapear_no_concede_nada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Si concediera el rol básico, crear un rol nuevo en el CRM daría acceso a
    las otras herramientas sin que nadie lo hubiera decidido."""
    assert suite.rol_en(mind, ["inventado"]) == ""


@pytest.mark.db
def test_con_varios_roles_gana_la_precedencia_declarada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Un usuario con dos roles no puede recibir un permiso distinto según el
    orden en que estén guardados sus roles."""
    assert suite.rol_en(mind, ["becario", "director"]) == "admin"
    assert suite.rol_en(mind, ["director", "becario"]) == "admin"


# ── La cola (CRM-00.01.07.10) ─────────────────────────────────────────────


def _usuario(**kw: Any) -> dict[str, Any]:
    base = {
        "id": str(uuid4()),
        "email": "ana@ejemplo.com",
        "nombre": "Ana",
        "roles": ["comercial"],
        "activa": True,
    }
    base.update(kw)
    return base


@pytest.mark.db
def test_la_baja_va_antes_que_todo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Un alta que tarda es una molestia que alguien reporta; una baja que tarda
    es una puerta abierta que no ve nadie."""
    suite.provisionar_usuario(db, tenant_id, _usuario(email="alta@ejemplo.com"))
    suite.provisionar_usuario(db, tenant_id, _usuario(email="baja@ejemplo.com"), operacion="baja")
    db.flush()

    cola = suite.pendientes(db, tenant_id)
    assert cola[0].operacion == "baja"


@pytest.mark.db
def test_encolar_dos_veces_lo_mismo_no_duplica(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """La cola guarda el estado que se quiere, no el historial de intenciones:
    aplicar tres cambios seguidos de la misma persona sería aplicar dos estados
    intermedios que ya no interesan, y el último podría llegar primero."""
    usuario = _usuario()
    suite.provisionar_usuario(db, tenant_id, usuario)
    suite.provisionar_usuario(db, tenant_id, {**usuario, "nombre": "Ana Ruiz"})
    db.flush()
    assert len(suite.pendientes(db, tenant_id)) == 1


@pytest.mark.db
def test_reencolar_lo_ya_aplicado_no_gasta_una_llamada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Empujar lo mismo otra vez gasta una llamada y, con algunas herramientas,
    cuenta como modificación en su propia auditoría: ruido que después nadie
    sabe interpretar."""
    usuario = _usuario()
    suite.provisionar_usuario(db, tenant_id, usuario)
    db.flush()
    fila = suite.pendientes(db, tenant_id)[0]
    suite.anotar_resultado(db, fila, ok=True)
    db.flush()

    suite.provisionar_usuario(db, tenant_id, usuario)
    db.flush()
    assert suite.pendientes(db, tenant_id) == []


@pytest.mark.db
def test_tras_agotar_intentos_va_a_cuarentena(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Reintentar para siempre esconde el problema en un log que nadie mira."""
    suite.provisionar_usuario(db, tenant_id, _usuario())
    db.flush()
    fila = suite.pendientes(db, tenant_id)[0]
    for _ in range(suite.MAX_INTENTOS):
        suite.anotar_resultado(db, fila, ok=False, detalle="HTTP 500")
    db.flush()

    apartados = suite.cuarentena(db, tenant_id)
    assert len(apartados) == 1
    # Se dice qué se mandó: sin eso, quien lo mira tiene que adivinar si el
    # problema es el dato o la herramienta.
    assert apartados[0]["carga"]["email"] == "ana@ejemplo.com"


@pytest.mark.db
def test_una_baja_en_cuarentena_se_marca_como_grave(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    suite.provisionar_usuario(db, tenant_id, _usuario(), operacion="baja")
    db.flush()
    fila = suite.pendientes(db, tenant_id)[0]
    for _ in range(suite.MAX_INTENTOS):
        suite.anotar_resultado(db, fila, ok=False, detalle="HTTP 500")
    db.flush()
    assert suite.cuarentena(db, tenant_id)[0]["gravedad"] == "alta"


@pytest.mark.db
def test_el_fallo_espera_antes_de_reintentar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Una herramienta caída diez minutos no puede costar diez minutos de
    martilleo."""
    suite.provisionar_usuario(db, tenant_id, _usuario())
    db.flush()
    fila = suite.pendientes(db, tenant_id)[0]
    suite.anotar_resultado(db, fila, ok=False, detalle="timeout")
    db.flush()
    assert fila.reintentar_at is not None
    assert suite.pendientes(db, tenant_id) == []


@pytest.mark.db
def test_reintentar_saca_de_cuarentena(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    suite.provisionar_usuario(db, tenant_id, _usuario())
    db.flush()
    fila = suite.pendientes(db, tenant_id)[0]
    for _ in range(suite.MAX_INTENTOS):
        suite.anotar_resultado(db, fila, ok=False, detalle="x")
    db.flush()
    suite.reintentar(db, tenant_id, fila.id)
    db.flush()
    assert suite.cuarentena(db, tenant_id) == []
    assert len(suite.pendientes(db, tenant_id)) == 1


@pytest.mark.db
def test_un_objeto_no_gobernado_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Una lista abierta acabaría empujando cualquier cosa sin que nadie hubiera
    pensado qué significa allí."""
    with pytest.raises(ErrorValidacion) as e:
        suite.encolar(
            db,
            tenant_id,
            herramienta="contecmind",
            objeto="factura",
            objeto_id="1",
            operacion="alta",
            carga={},
        )
    assert e.value.error_code == "suite.objeto_no_gobernado"


# ── Provisionar (CRM-00.01.07.02, .03) ────────────────────────────────────


@pytest.mark.db
def test_sin_herramientas_conectadas_se_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, tenant: Tenant
) -> None:
    """Un «0 herramientas, todo bien» silencioso haría creer que el cliente está
    en la suite cuando solo está en el CRM."""
    salida = suite.provisionar_tenant(db, tenant_id)
    assert salida["sin_herramientas"] is True


@pytest.mark.db
def test_un_usuario_sin_rol_mapeado_no_se_crea_alli(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Una cuenta sin rol no sirve para nada y además hay que acordarse de darla
    de baja."""
    salida = suite.provisionar_usuario(db, tenant_id, _usuario(roles=["inventado"]))
    assert salida["herramientas"] == []


@pytest.mark.db
def test_la_baja_se_encola_aunque_no_tenga_rol(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Negarse a dar de baja a alguien porque su rol ya no está mapeado sería el
    peor de los fallos posibles: exactamente el caso en que hay que echarlo."""
    salida = suite.provisionar_usuario(
        db, tenant_id, _usuario(roles=["inventado"]), operacion="baja"
    )
    assert salida["herramientas"] == ["contecmind"]


# ── Simulación (CRM-00.01.07.11) ──────────────────────────────────────────


@pytest.mark.db
def test_la_simulacion_separa_altas_bajas_y_cambios(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """El error caro es desactivar a media plantilla por un mapeo mal escrito y
    enterarse cuando llaman."""
    suite.provisionar_usuario(db, tenant_id, _usuario(email="uno@ejemplo.com"))
    suite.provisionar_usuario(db, tenant_id, _usuario(email="dos@ejemplo.com"), operacion="baja")
    db.flush()

    plan = suite.simular(db, tenant_id)["herramientas"][0]
    assert len(plan["altas"]) == 1 and len(plan["bajas"]) == 1


# ── Reconciliación (CRM-00.01.07.07) ──────────────────────────────────────


@pytest.mark.db
def test_lo_que_sobra_alli_se_señala_como_acceso_abierto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Suele ser una baja que no se aplicó, y eso es literalmente un acceso que
    sigue abierto."""
    usuario = _usuario()
    suite.provisionar_usuario(db, tenant_id, usuario, operacion="baja")
    db.flush()

    salida = suite.reconciliar(
        db, tenant_id, "contecmind", {usuario["id"]: {"email": usuario["email"]}}
    )
    assert salida["sobran_alli"] == [usuario["id"]]
    assert "accesos abiertos" in salida["aviso"]


@pytest.mark.db
def test_lo_que_falta_alli_se_detecta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    usuario = _usuario()
    suite.provisionar_usuario(db, tenant_id, usuario)
    db.flush()
    salida = suite.reconciliar(db, tenant_id, "contecmind", {})
    assert salida["faltan_alli"] == [usuario["id"]]


@pytest.mark.db
def test_lo_cambiado_alli_no_se_pisa_sin_decirlo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Puede ser un ajuste deliberado del administrador de allí, y
    sobrescribirlo en silencio es cómo se pierde la confianza en el empuje."""
    usuario = _usuario()
    suite.provisionar_usuario(db, tenant_id, usuario)
    db.flush()

    salida = suite.reconciliar(
        db, tenant_id, "contecmind", {usuario["id"]: {"email": "otro@ejemplo.com"}}
    )
    assert salida["difieren"][0]["objeto_id"] == usuario["id"]

    reparado = suite.reparar(db, tenant_id, "contecmind", objeto_ids=[usuario["id"]])
    assert reparado["reparados"] == []
    assert "pisaría ese cambio" in reparado["omitidos"][0]["motivo"]

    forzado = suite.reparar(db, tenant_id, "contecmind", objeto_ids=[usuario["id"]], forzar=True)
    assert forzado["reparados"] == [usuario["id"]]


@pytest.mark.db
def test_reconciliar_una_herramienta_no_conectada_falla(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, tenant: Tenant
) -> None:
    with pytest.raises(NoEncontrado) as e:
        suite.reconciliar(db, tenant_id, "inexistente", {})
    assert e.value.error_code == "suite.herramienta_no_conectada"


# ── Panel y auditoría (CRM-00.01.07.07, .12) ──────────────────────────────


@pytest.mark.db
def test_el_panel_saca_las_bajas_sin_aplicar_aparte(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Es lo único que hay que mirar con prisa: una baja que no llegó es un
    acceso abierto que no ve nadie hasta una auditoría."""
    suite.provisionar_usuario(db, tenant_id, _usuario(), operacion="baja")
    db.flush()
    panel = suite.panel(db, tenant_id)
    assert panel["bajas_sin_aplicar"] == 1
    assert panel["en_verde"] is False


@pytest.mark.db
def test_el_historial_dice_donde_acabo_aplicandose(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Sin esto, contestar «¿por qué este usuario sigue entrando?» obliga a
    mirar tres registros de auditoría y cruzarlos de memoria."""
    usuario = _usuario()
    suite.provisionar_usuario(db, tenant_id, usuario)
    db.flush()
    fila = suite.pendientes(db, tenant_id)[0]
    suite.anotar_resultado(db, fila, ok=True)
    db.flush()

    historial = suite.historial(db, tenant_id, objeto_id=usuario["id"])
    assert historial[0]["herramienta"] == "contecmind"
    assert historial[0]["resultado"] == "ok"


@pytest.mark.db
def test_conectar_dos_veces_la_misma_herramienta_falla(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any, monkeypatch: Any
) -> None:
    from crmcore.red import guard_url

    monkeypatch.setattr(guard_url, "exigir", lambda url: None)
    with pytest.raises(Conflicto) as e:
        suite.conectar(
            db,
            tenant_id,
            nombre="contecmind",
            base_url="https://otro.ejemplo.com",
            credenciales={},
        )
    assert e.value.error_code == "suite.herramienta_duplicada"


# ── Conectores (CRM-00.01.07.08) ──────────────────────────────────────────


def test_el_conector_nativo_hereda_el_transporte_generico() -> None:
    """Reescribir el transporte entero por producto es lo que hace que mantener
    cinco conectores sea imposible."""
    from services.tenancy.suite_conector import ConectorContecmind, ConectorGenerico

    assert issubclass(ConectorContecmind, ConectorGenerico)


def test_siempre_hay_conector_aunque_el_tipo_sea_desconocido() -> None:
    """Lo genérico es el suelo: una herramienta que no conocemos no puede dejar
    el empuje sin transporte."""
    from services.tenancy.suite_conector import conector_de

    assert conector_de("una_que_no_existe").tipo == "generico"


@pytest.mark.db
def test_una_herramienta_desactivada_no_gasta_intentos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """Si no, el objeto acabaría en cuarentena por algo que no tiene nada que ver
    con él."""
    from services.tenancy import suite_conector

    suite.provisionar_usuario(db, tenant_id, _usuario())
    db.flush()
    mind.activa = False
    db.flush()

    salida = suite_conector.aplicar_pendientes(db, tenant_id)
    assert salida["saltadas_por_herramienta_inactiva"] == 1
    assert suite.pendientes(db, tenant_id)[0].intentos == 0


@pytest.mark.db
def test_sin_forma_de_leer_no_se_da_por_sincronizado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, mind: Any
) -> None:
    """«No se ha podido comprobar» y «está todo bien» son cosas distintas, y
    confundirlas es por lo que nadie se fía de los paneles de sincronización."""
    from services.tenancy import suite_conector

    salida = suite_conector.reconciliar_con_remoto(db, tenant_id, "contecmind")
    assert salida["medible"] is False
    assert "no declara cómo listar" in salida["motivo"]
