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
    for _ in range(suite._suite_max_intentos()):
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
    for _ in range(suite._suite_max_intentos()):
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
    for _ in range(suite._suite_max_intentos()):
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


# ── Campos constantes por conexión (CRM-00.01.07.08) ──────────────────────


def _fila_de_tenant(herramienta: Any, tenant_id: UUID) -> Any:
    return suite.SincronizacionSuite(
        tenant_id=tenant_id,
        herramienta=herramienta.nombre,
        objeto="tenant",
        objeto_id=str(uuid4()),
        operacion="alta",
        identificador_externo="org-1",
        carga={"name": "ACME"},
    )


def _capturar_carga(monkeypatch: Any) -> list[dict[str, Any]]:
    """Qué cuerpo sale por el cable, que es lo único que importa aquí."""
    import contextlib

    import httpx
    from crmcore.red import guard_url

    salidas: list[dict[str, Any]] = []

    def _transporte(peticion: httpx.Request) -> httpx.Response:
        import json as _json

        if peticion.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "t"})
        salidas.append(_json.loads(peticion.content) if peticion.content else {})
        return httpx.Response(200, json={"id": "remoto"})

    @contextlib.contextmanager
    def _fabrica(**_: Any) -> Any:
        with httpx.Client(transport=httpx.MockTransport(_transporte)) as cli:
            yield cli

    monkeypatch.setattr(guard_url, "cliente_seguro", _fabrica)
    return salidas


def test_un_campo_que_exige_la_herramienta_y_no_es_del_objeto_se_configura(
    db: Any, tenant_id: UUID, tenant: Tenant, monkeypatch: Any, con_cifrado: Any
) -> None:
    """El caso real: contecmind exige `app_id` para dar de alta una organización.

    `app_id` dice QUÉ APLICACIÓN la nombra, así que no es un campo del tenant:
    es de la conexión. El mapeo de campos no podía resolverlo por definición
    —renombra claves, no inventa las que no vienen— y el alta se comía un 422
    del gestor. Verificado contra contecmind de verdad: sin el campo contesta
    «app_id: Field required»; con él, deja de quejarse del cuerpo.
    """
    from services.tenancy import suite_conector

    herramienta = _conector_con_login(db, tenant_id, "mind-fijos", monkeypatch)
    herramienta.campos_fijos = {"app_id": "11111111-2222-3333-4444-555555555555"}
    db.flush()
    salidas = _capturar_carga(monkeypatch)
    suite_conector.ConectorGenerico._tokens.clear()

    suite_conector.ConectorContecmind().aplicar(
        herramienta, _fila_de_tenant(herramienta, tenant_id)
    )

    assert salidas, "no salió ninguna carga"
    assert salidas[-1]["app_id"] == "11111111-2222-3333-4444-555555555555"
    assert salidas[-1]["name"] == "ACME"


def test_el_campo_fijo_se_aplica_al_ENVIAR_y_no_al_encolar(
    db: Any, tenant_id: UUID, tenant: Tenant, monkeypatch: Any, con_cifrado: Any
) -> None:
    """Es lo que hace que configurarlo sirva de algo.

    La primera versión los metía al componer la carga, o sea al ENCOLAR, y el
    valor quedaba congelado en la fila. El camino real es justo el contrario:
    montas la integración, el alta falla porque falta `app_id`, lo configuras… y
    **la cola seguiría fallando para siempre**, porque las filas pendientes
    llevan la carga vieja. Quien lo mirara concluiría que configurarlo no sirve.

    Aquí la fila se crea ANTES de configurar el campo, que es el orden en que
    pasa de verdad.
    """
    from services.tenancy import suite_conector

    herramienta = _conector_con_login(db, tenant_id, "mind-tarde", monkeypatch)
    fila = _fila_de_tenant(herramienta, tenant_id)  # encolada sin el campo
    herramienta.campos_fijos = {"app_id": "abc"}  # configurado DESPUÉS
    db.flush()

    salidas = _capturar_carga(monkeypatch)
    suite_conector.ConectorGenerico._tokens.clear()
    suite_conector.ConectorContecmind().aplicar(herramienta, fila)

    assert salidas[-1]["app_id"] == "abc", "configurarlo no arregló lo que ya estaba en la cola"


def test_un_campo_fijo_no_pisa_el_dato_del_objeto(
    db: Any, tenant_id: UUID, tenant: Tenant, monkeypatch: Any, con_cifrado: Any
) -> None:
    """Un valor por conexión es un valor POR DEFECTO, no una imposición.

    Si el fijo pisara al objeto, el fallo no daría ningún error —la carga
    saldría bien formada— y se empujaría el mismo valor para todos los
    registros. La otra prueba fallaría a gritos; ésta fallaría en silencio.
    """
    from services.tenancy import suite_conector

    herramienta = _conector_con_login(db, tenant_id, "mind-defecto", monkeypatch)
    herramienta.campos_fijos = {"name": "EL DE LA CONEXIÓN"}
    db.flush()
    salidas = _capturar_carga(monkeypatch)
    suite_conector.ConectorGenerico._tokens.clear()

    suite_conector.ConectorContecmind().aplicar(
        herramienta, _fila_de_tenant(herramienta, tenant_id)
    )

    assert salidas[-1]["name"] == "ACME", "el dato del objeto manda sobre el valor por conexión"


# ── Entrar y renovar: el token dura quince minutos ────────────────────────


def _conector_con_login(db: Any, tenant_id: UUID, nombre: str, monkeypatch: Any) -> Any:
    from crmcore.red import guard_url

    monkeypatch.setattr(guard_url, "exigir", lambda url: None)
    return suite.conectar(
        db,
        tenant_id,
        nombre=nombre,
        base_url="https://mind.ejemplo.com",
        credenciales={"usuario": "conector@ejemplo.test", "clave": "secreta"},
        tipo="contecmind",
        mapeo_campos={"_ruta_login": "/api/v1/auth/login"},
    )


def test_ante_un_token_vencido_la_operacion_acaba_saliendo(
    db: Any, tenant_id: UUID, tenant: Tenant, monkeypatch: Any, con_cifrado: Any
) -> None:
    """La prueba que de verdad hace falta, y no «renueva».

    contecmind emite tokens de QUINCE MINUTOS. El conector guardaba uno escrito
    en la configuración, así que el aprovisionamiento funcionaba el cuarto de
    hora en que alguien lo montaba —justo cuando lo prueba y lo da por bueno— y
    después daba 401 para siempre, disfrazado de credencial mal puesta.

    No se espera al reloj: se le hace contestar 401 la primera vez, que es la
    situación exacta. Una prueba contra el reloj de verdad o tarda quince
    minutos o no comprueba nada.
    """
    import httpx
    from crmcore.red import guard_url

    from services.tenancy import suite_conector

    herramienta = _conector_con_login(db, tenant_id, "mind-login", monkeypatch)
    llamadas: list[str] = []

    def _transporte(peticion: httpx.Request) -> httpx.Response:
        llamadas.append(f"{peticion.method} {peticion.url.path}")
        if peticion.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "nuevo"})
        # La primera vez el token está vencido; tras renovar, pasa.
        if peticion.headers.get("Authorization") != "Bearer nuevo":
            return httpx.Response(401, json={"detail": "token expired"})
        return httpx.Response(200, json={"id": "remoto-1"})

    import contextlib

    @contextlib.contextmanager
    def _fabrica(**_: Any) -> Any:
        with httpx.Client(transport=httpx.MockTransport(_transporte)) as cli:
            yield cli

    monkeypatch.setattr(guard_url, "cliente_seguro", _fabrica)
    suite_conector.ConectorGenerico._tokens.clear()

    fila = suite.SincronizacionSuite(
        tenant_id=tenant_id,
        herramienta=herramienta.nombre,
        objeto="usuario",
        objeto_id=str(uuid4()),
        operacion="alta",
        carga={"email": "a@b.c"},
    )
    resultado = suite_conector.ConectorGenerico().aplicar(herramienta, fila)

    assert resultado.ok is True, f"no salió: {resultado.detalle}"
    assert resultado.identificador_externo == "remoto-1"
    # Y el camino fue el esperado: intento, entrada, reintento.
    assert llamadas[-1].startswith("PUT"), llamadas
    assert any("/auth/login" in x for x in llamadas), llamadas


def test_un_403_no_se_reintenta_nunca(
    db: Any, tenant_id: UUID, tenant: Tenant, monkeypatch: Any, con_cifrado: Any
) -> None:
    """Un 403 no es un token vencido: es una credencial que no puede hacer eso.

    Reintentarlo convierte un permiso mal configurado en un bucle de peticiones
    contra la otra herramienta, y el error real —que alguien tiene que
    arreglar— queda enterrado bajo el ruido.
    """
    import contextlib

    import httpx
    from crmcore.red import guard_url

    from services.tenancy import suite_conector

    herramienta = _conector_con_login(db, tenant_id, "mind-403", monkeypatch)
    intentos: list[str] = []

    def _transporte(peticion: httpx.Request) -> httpx.Response:
        intentos.append(peticion.url.path)
        if peticion.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(403, json={"detail": "no puedes"})

    @contextlib.contextmanager
    def _fabrica(**_: Any) -> Any:
        with httpx.Client(transport=httpx.MockTransport(_transporte)) as cli:
            yield cli

    monkeypatch.setattr(guard_url, "cliente_seguro", _fabrica)
    suite_conector.ConectorGenerico._tokens.clear()

    fila = suite.SincronizacionSuite(
        tenant_id=tenant_id,
        herramienta=herramienta.nombre,
        objeto="usuario",
        objeto_id=str(uuid4()),
        operacion="alta",
        carga={"email": "a@b.c"},
    )
    resultado = suite_conector.ConectorGenerico().aplicar(herramienta, fila)

    assert resultado.ok is False
    assert "403" in (resultado.detalle or "")
    # Una sola llamada a la ruta de verdad: ni un reintento.
    assert len([x for x in intentos if not x.endswith("/auth/login")]) == 1, intentos


def test_el_token_se_comparte_entre_llamadas(
    db: Any, tenant_id: UUID, tenant: Tenant, monkeypatch: Any, con_cifrado: Any
) -> None:
    """Un alta en cascada de doscientos usuarios no puede hacer doscientos logins.

    Ese coste no aparece el día que se configura la integración con tres
    usuarios de prueba: aparece el día que alguien sincroniza de verdad.
    """
    import contextlib

    import httpx
    from crmcore.red import guard_url

    from services.tenancy import suite_conector

    herramienta = _conector_con_login(db, tenant_id, "mind-cache", monkeypatch)
    logins = 0

    def _transporte(peticion: httpx.Request) -> httpx.Response:
        nonlocal logins
        if peticion.url.path.endswith("/auth/login"):
            logins += 1
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(200, json={"id": "x"})

    @contextlib.contextmanager
    def _fabrica(**_: Any) -> Any:
        with httpx.Client(transport=httpx.MockTransport(_transporte)) as cli:
            yield cli

    monkeypatch.setattr(guard_url, "cliente_seguro", _fabrica)
    suite_conector.ConectorGenerico._tokens.clear()

    conector = suite_conector.ConectorGenerico()
    for _ in range(5):
        fila = suite.SincronizacionSuite(
            tenant_id=tenant_id,
            herramienta=herramienta.nombre,
            objeto="usuario",
            objeto_id=str(uuid4()),
            operacion="alta",
            carga={"email": "a@b.c"},
        )
        conector.aplicar(herramienta, fila)

    assert logins == 1, f"cinco altas hicieron {logins} inicios de sesión"
