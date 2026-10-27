"""Conectividad: transportes, catálogo de conectores, MCP, canales, federación y
convivencia.

CRM-00.03.04.01, .03, .10, .11 · CRM-07.02.01.09 · CRM-00.02.03.09, .10 ·
CRM-01.01.05.04 · CRM-00.03.01.07 · CRM-01.02.01.04.

Las pruebas van detrás de los sitios donde una integración falla sin fallar:

  * el SOAP Fault que llega con HTTP 200 y se procesa como resultado vacío,
  * el fichero cuyo formato se adivina y entra mal,
  * el conector que se actualiza solo y cambia producción un martes,
  * el agente que hereda los permisos de quien lo lanzó,
  * la interacción que se duplica en cada reintento,
  * el saldo externo que no contesta y se enseña como cero,
  * y el registro que nadie sabe si edita aquí o en el sistema viejo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz.principal import Principal
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorDependencia, ErrorValidacion, Prohibido

from services.integration import canales_entrada as canales
from services.integration import convivencia as conv
from services.integration import federacion as fed
from services.integration import manifiestos as man
from services.integration import mcp as mcp_mod
from services.integration import transportes_legado as tr


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── Transportes (CRM-00.03.04.03) ─────────────────────────────────────────


def test_fichero_delimitado_con_cabecera() -> None:
    salida = tr.leer_fichero("nif;nombre\nB1;Acme\nB2;Beta\n", {"separador": ";"})
    assert salida.filas == [{"nif": "B1", "nombre": "Acme"}, {"nif": "B2", "nombre": "Beta"}]


def test_una_linea_con_menos_campos_avisa_y_no_tumba_el_fichero() -> None:
    """Un fichero de 50.000 pedidos no se descarta entero por uno malo."""
    salida = tr.leer_fichero("nif;nombre\nB1;Acme\nB2\n", {"separador": ";"})
    assert len(salida.filas) == 2
    assert any("se esperaban" in a for a in salida.avisos)


def test_ancho_fijo_avisa_de_la_linea_corta() -> None:
    config = {
        "formato": "ancho_fijo",
        "columnas": [
            {"nombre": "nif", "desde": 0, "hasta": 9},
            {"nombre": "nombre", "desde": 9, "hasta": 29},
        ],
    }
    salida = tr.leer_fichero("B12345678Acme SL\nB2\n", config)
    assert salida.filas[0]["nif"] == "B12345678"
    assert any("más corta" in a for a in salida.avisos)


def test_json_por_lineas_cuenta_las_rotas() -> None:
    salida = tr.leer_fichero('{"a":1}\nesto no es json\n{"a":2}\n', {"formato": "json_lineas"})
    assert len(salida.filas) == 2
    assert any("ilegible" in a for a in salida.avisos)


def test_un_formato_inventado_se_rechaza() -> None:
    """Adivinar funciona el 95 % de las veces, y el 5 % son cargas que entran mal
    sin fallar."""
    with pytest.raises(ErrorValidacion):
        tr.leer_fichero("a,b", {"formato": "excel_magico"})


def test_edi_parte_los_segmentos_sin_interpretarlos() -> None:
    mensaje = "UNB+UNOC:3+REMITENTE+DESTINO'BGM+220+PED-1'NAD+BY+CLI-9'UNZ+1+1'"
    salida = tr.leer_edi(mensaje, {"dialecto": "edifact"})
    assert [f["segmento"] for f in salida.filas] == ["UNB", "BGM", "NAD", "UNZ"]


def test_edi_filtra_por_segmento_cuando_se_pide() -> None:
    mensaje = "UNB+X'BGM+220+PED-1'NAD+BY+CLI-9'"
    salida = tr.leer_edi(mensaje, {"segmentos": ["BGM"]})
    assert len(salida.filas) == 1 and salida.filas[0]["segmento"] == "BGM"


def test_edi_con_separadores_equivocados_lo_dice() -> None:
    """Cambian entre emisores, y sin aviso el resultado es silencio."""
    salida = tr.leer_edi("BGM*220*PED-1~", {"dialecto": "edifact"})
    assert any("separadores" in a for a in salida.avisos)


def test_el_soap_fault_no_pasa_por_resultado_vacio() -> None:
    """Llega con HTTP 200 en muchísimos servicios: sin mirar el cuerpo, un error
    se procesa como cero filas y el proceso nocturno dice que fue bien."""
    fault = (
        '<?xml version="1.0"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body><soap:Fault><faultcode>Server</faultcode>"
        "<faultstring>Credenciales caducadas</faultstring></soap:Fault></soap:Body>"
        "</soap:Envelope>"
    )
    with pytest.raises(ErrorDependencia) as error:
        tr.leer_soap(fault)
    assert "Credenciales caducadas" in str(error.value)


def test_el_soap_normal_devuelve_filas() -> None:
    respuesta = (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body><Respuesta><Cliente><nif>B1</nif><nombre>Acme</nombre></Cliente>"
        "<Cliente><nif>B2</nif><nombre>Beta</nombre></Cliente></Respuesta></soap:Body>"
        "</soap:Envelope>"
    )
    salida = tr.leer_soap(respuesta, {"nodo_filas": "Cliente"})
    assert salida.filas == [
        {"nif": "B1", "nombre": "Acme"},
        {"nif": "B2", "nombre": "Beta"},
    ]


def test_una_respuesta_que_no_es_xml_falla_como_dependencia() -> None:
    with pytest.raises(ErrorDependencia):
        tr.leer_soap("<html>502 Bad Gateway</html>")


def test_el_sobre_soap_se_construye_con_su_version() -> None:
    sobre = tr.envolver_soap("<Consulta/>", {"version": "1.2"})
    assert "www.w3.org/2003/05/soap-envelope" in sobre and "<Consulta/>" in sobre


def test_sftp_sin_huella_del_host_se_rechaza() -> None:
    """Aceptar la clave que venga es abrir la puerta a que alguien se ponga en
    medio del canal por el que viaja el maestro de clientes."""
    with pytest.raises(ErrorValidacion) as error:
        tr.listar_sftp({"host": "sftp.proveedor.com", "usuario": "x"})
    assert "huella" in str(error.value).lower()


# ── Catálogo de conectores (CRM-00.03.04.01, .10, CRM-07.02.01.09) ────────


def _manifiesto(uow: UnidadDeTrabajo, **kw: Any) -> man.Manifiesto:
    base: dict[str, Any] = {
        "clave": "erp-demo",
        "nombre": "ERP Demo",
        "version": "1",
        "categoria": "erp",
        "operaciones": [{"clave": "clientes", "ruta": "/clientes", "mapeo": {"nif": "cif"}}],
        "credenciales": [{"clave": "api_key", "obligatoria": True}],
        "dominios": ["api.erpdemo.com"],
    }
    base.update(kw)
    return man.publicar(uow, **base)


def test_un_manifiesto_sin_operaciones_no_se_publica(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion):
        _manifiesto(uow, operaciones=[])


def test_un_manifiesto_sin_dominios_declarados_no_se_publica(uow: UnidadDeTrabajo) -> None:
    """Sin eso, nadie puede revisar a dónde van los datos antes de instalarlo."""
    with pytest.raises(ErrorValidacion) as error:
        _manifiesto(uow, dominios=[])
    assert "dominios" in str(error.value.detalle).lower()


def test_una_version_nueva_exige_decir_que_cambia(uow: UnidadDeTrabajo) -> None:
    """Quien decida actualizar producción no puede hacerlo a ciegas."""
    _manifiesto(uow)
    with pytest.raises(ErrorValidacion):
        _manifiesto(uow, version="2")
    _manifiesto(uow, version="2", notas_version="Se añade el endpoint de pedidos")


def test_una_version_publicada_no_se_reescribe(uow: UnidadDeTrabajo) -> None:
    _manifiesto(uow)
    with pytest.raises(Conflicto):
        _manifiesto(uow, notas_version="lo que sea")


def test_el_catalogo_ensena_la_ultima_version_de_cada_uno(uow: UnidadDeTrabajo) -> None:
    _manifiesto(uow)
    _manifiesto(uow, version="2", notas_version="Pedidos")
    salida = man.catalogo(uow.db)
    assert salida["cuantos"] == 1
    assert salida["conectores"][0]["version"] == "2"
    assert salida["conectores"][0]["versiones_publicadas"] == 2


def test_instalar_dice_que_credenciales_faltan_en_vez_de_fallar(
    uow: UnidadDeTrabajo,
) -> None:
    """Instalar y configurar son dos momentos, y la credencial la tiene a veces
    otra persona."""
    _manifiesto(uow)
    fila, informe = man.instalar(uow, clave="erp-demo")
    assert fila.estado == "instalada"
    assert informe["credenciales_pendientes"] == ["api_key"]
    assert informe["operativa"] is False and informe["aviso"]


def test_no_se_instala_dos_veces_el_mismo_conector(uow: UnidadDeTrabajo) -> None:
    _manifiesto(uow)
    man.instalar(uow, clave="erp-demo")
    with pytest.raises(Conflicto):
        man.instalar(uow, clave="erp-demo")


def test_lo_instalado_no_se_actualiza_solo(uow: UnidadDeTrabajo) -> None:
    """Cambiar producción sin que nadie lo decida es cómo algo que funcionaba deja
    de funcionar un martes sin despliegue de por medio."""
    _manifiesto(uow)
    man.instalar(uow, clave="erp-demo", credenciales_puestas=["api_key"])
    _manifiesto(uow, version="2", notas_version="Cambia el mapeo del NIF")

    pendientes = man.actualizaciones(uow.db, uow.tenant_id)
    linea = pendientes["instalaciones"][0]
    assert linea["version_instalada"] == "1"
    assert linea["hay_actualizacion"] is True
    assert linea["que_cambia"] == "Cambia el mapeo del NIF"

    subida = man.actualizar(uow, clave="erp-demo")
    assert subida["hasta"] == "2" and subida["que_cambia"]


def test_retirar_no_rompe_lo_instalado_y_dice_a_cuantos_afecta(
    uow: UnidadDeTrabajo,
) -> None:
    _manifiesto(uow)
    man.instalar(uow, clave="erp-demo")
    with pytest.raises(ErrorValidacion):
        man.retirar(uow, clave="erp-demo", version="1", motivo="")
    salida = man.retirar(uow, clave="erp-demo", version="1", motivo="El proveedor apaga esa API")
    assert salida["instalaciones_afectadas"] == 1
    assert salida["siguen_funcionando"] is True


def test_un_conector_retirado_del_catalogo_con_instalaciones_se_senala(
    uow: UnidadDeTrabajo,
) -> None:
    _manifiesto(uow)
    man.instalar(uow, clave="erp-demo")
    man.retirar(uow, clave="erp-demo", version="1", motivo="Fin de vida")
    salida = man.actualizaciones(uow.db, uow.tenant_id)
    assert salida["retirados"] == 1


# ── MCP (CRM-00.03.04.11) ─────────────────────────────────────────────────


def _exposicion(uow: UnidadDeTrabajo, **kw: Any) -> mcp_mod.Exposicion:
    base: dict[str, Any] = {"clave": "agentes-ventas", "cuota_hora": 100}
    base.update(kw)
    return mcp_mod.crear_exposicion(uow, **base)


def _principal(*permisos: str) -> Principal:
    return Principal(id=uuid4(), permisos=frozenset(permisos))


def test_una_herramienta_de_escritura_declara_a_que_comando_va(
    uow: UnidadDeTrabajo,
) -> None:
    """Escribir directamente saltaría las reglas del servicio dueño."""
    exposicion = _exposicion(uow)
    with pytest.raises(ErrorValidacion):
        mcp_mod.publicar_herramienta(
            uow, exposicion.id, nombre="crear_lead", permiso="lead:write", tipo="escritura"
        )


def test_una_herramienta_de_escritura_sin_confirmacion_avisa(
    uow: UnidadDeTrabajo,
) -> None:
    exposicion = _exposicion(uow)
    _, avisos = mcp_mod.publicar_herramienta(
        uow,
        exposicion.id,
        nombre="crear_lead",
        permiso="lead:write",
        tipo="escritura",
        descripcion="Crea un lead",
        destino={"objeto": "lead", "accion": "crear"},
    )
    assert any("sin confirmación humana" in a for a in avisos)


def test_el_catalogo_se_filtra_por_los_permisos_del_agente(
    uow: UnidadDeTrabajo,
) -> None:
    """Publicar todo y fallar al invocar le hace gastar llamadas en lo que no
    puede hacer, y peor: intentar rodearlo."""
    exposicion = _exposicion(uow)
    mcp_mod.publicar_herramienta(
        uow, exposicion.id, nombre="buscar_cuentas", permiso="account:read", descripcion="x"
    )
    mcp_mod.publicar_herramienta(
        uow, exposicion.id, nombre="ver_comisiones", permiso="commission:read", descripcion="y"
    )
    salida = mcp_mod.catalogo_para(
        uow.db, uow.tenant_id, exposicion="agentes-ventas", principal=_principal("account:read")
    )
    assert [h["nombre"] for h in salida["herramientas"]] == ["buscar_cuentas"]
    assert salida["ocultas_por_permisos"] == 1


def test_invocar_sin_permiso_se_rechaza_y_queda_contado(uow: UnidadDeTrabajo) -> None:
    exposicion = _exposicion(uow)
    mcp_mod.publicar_herramienta(
        uow, exposicion.id, nombre="buscar", permiso="account:read", descripcion="x"
    )
    with pytest.raises(Prohibido):
        mcp_mod.invocar(
            uow,
            exposicion="agentes-ventas",
            herramienta="buscar",
            principal=_principal("case:read"),
        )
    uso = mcp_mod.uso(uow.db, uow.tenant_id)
    assert uso["rechazadas"] == 1


def test_la_escritura_queda_pedida_y_no_hecha(uow: UnidadDeTrabajo) -> None:
    """Lo ejecuta el servicio dueño, que puede rechazarlo por sus propias reglas."""
    exposicion = _exposicion(uow)
    mcp_mod.publicar_herramienta(
        uow,
        exposicion.id,
        nombre="crear_lead",
        permiso="lead:write",
        tipo="escritura",
        descripcion="x",
        destino={"objeto": "lead", "accion": "crear"},
    )
    salida = mcp_mod.invocar(
        uow,
        exposicion="agentes-ventas",
        herramienta="crear_lead",
        argumentos={"nombre": "Acme"},
        principal=_principal("lead:write"),
    )
    assert salida["estado"] == "pedido"


def test_la_que_exige_confirmacion_no_se_ejecuta_sola(uow: UnidadDeTrabajo) -> None:
    exposicion = _exposicion(uow)
    mcp_mod.publicar_herramienta(
        uow,
        exposicion.id,
        nombre="cerrar_oportunidad",
        permiso="opportunity:write",
        tipo="escritura",
        descripcion="x",
        destino={"objeto": "oportunidad", "accion": "cerrar"},
        exige_confirmacion=True,
    )
    salida = mcp_mod.invocar(
        uow,
        exposicion="agentes-ventas",
        herramienta="cerrar_oportunidad",
        principal=_principal("opportunity:write"),
    )
    assert salida["estado"] == "pendiente_confirmacion"


def test_la_cuota_corta_al_agente_en_bucle(uow: UnidadDeTrabajo) -> None:
    """Un agente sin cuota es una factura sorpresa."""
    exposicion = _exposicion(uow, cuota_hora=2)
    mcp_mod.publicar_herramienta(
        uow, exposicion.id, nombre="buscar", permiso="account:read", descripcion="x"
    )
    principal = _principal("account:read")
    for _ in range(2):
        mcp_mod.invocar(uow, exposicion="agentes-ventas", herramienta="buscar", principal=principal)
    with pytest.raises(Conflicto):
        mcp_mod.invocar(uow, exposicion="agentes-ventas", herramienta="buscar", principal=principal)


def test_el_interruptor_corta_aunque_todo_lo_demas_este_bien(
    uow: UnidadDeTrabajo,
) -> None:
    exposicion = _exposicion(uow)
    mcp_mod.publicar_herramienta(
        uow, exposicion.id, nombre="buscar", permiso="account:read", descripcion="x"
    )
    with pytest.raises(ErrorValidacion):
        mcp_mod.detener(uow, exposicion="agentes-ventas", motivo="")
    mcp_mod.detener(uow, exposicion="agentes-ventas", motivo="El agente se ha vuelto loco")
    with pytest.raises(Prohibido):
        mcp_mod.invocar(
            uow,
            exposicion="agentes-ventas",
            herramienta="buscar",
            principal=_principal("account:read"),
        )
    catalogo = mcp_mod.catalogo_para(
        uow.db, uow.tenant_id, exposicion="agentes-ventas", principal=_principal("account:read")
    )
    assert catalogo["detenida"] is True and catalogo["herramientas"] == []


# ── Canales de entrada (CRM-00.02.03.09, CRM-01.02.01.04) ─────────────────


def test_la_misma_interaccion_no_se_registra_dos_veces(uow: UnidadDeTrabajo) -> None:
    """El proveedor de correo reintenta y el calendario reenvía el mismo evento."""
    primera = canales.registrar(
        uow, canal="correo", id_externo="<msg-1@correo>", interlocutor="a@cliente.com"
    )
    segunda = canales.registrar(
        uow, canal="correo", id_externo="<msg-1@correo>", interlocutor="a@cliente.com"
    )
    assert primera["registrada"] is True
    assert segunda["duplicada"] is True


def test_sin_identificador_del_canal_no_se_registra(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion):
        canales.registrar(uow, canal="correo", id_externo="  ")


def test_lo_que_no_se_puede_atribuir_se_guarda_y_se_cuenta(
    uow: UnidadDeTrabajo,
) -> None:
    """Un correo de una dirección desconocida es un contacto que falta, no basura."""
    for i in range(3):
        canales.registrar(
            uow,
            canal="correo",
            id_externo=f"<msg-{i}@correo>",
            interlocutor="nuevo@cliente.com",
        )
    salida = canales.sin_atribuir(uow.db, uow.tenant_id)
    assert salida["cuantas"] == 3
    assert salida["interlocutores_frecuentes"][0] == {
        "interlocutor": "nuevo@cliente.com",
        "veces": 3,
    }


def test_el_contenido_no_se_guarda_salvo_que_se_declare(uow: UnidadDeTrabajo) -> None:
    """Volcar el buzón dentro del CRM multiplica el dato personal para algo que
    casi nadie vuelve a leer."""
    canales.declarar_canal(uow, clave="soporte", canal="correo", produce="caso")
    salida = canales.registrar(
        uow,
        canal="correo",
        id_externo="<x@correo>",
        clave_canal="soporte",
        contenido="Texto del correo",
        contacto_id=uuid4(),
    )
    assert salida["contenido_guardado"] is False

    canales.declarar_canal(uow, clave="soporte-con-texto", canal="correo", guardar_contenido=True)
    con_texto = canales.registrar(
        uow,
        canal="correo",
        id_externo="<y@correo>",
        clave_canal="soporte-con-texto",
        contenido="Texto del correo",
        contacto_id=uuid4(),
    )
    assert con_texto["contenido_guardado"] is True


def test_atribuida_pide_crear_lo_que_el_canal_declare(uow: UnidadDeTrabajo) -> None:
    canales.declarar_canal(uow, clave="soporte", canal="correo", produce="caso")
    salida = canales.registrar(
        uow,
        canal="correo",
        id_externo="<z@correo>",
        clave_canal="soporte",
        contacto_id=uuid4(),
        asunto="No arranca",
    )
    assert salida["atribuida"] is True and salida["pedido"] == "caso"


def test_sin_atribuir_no_se_pide_crear_nada(uow: UnidadDeTrabajo) -> None:
    """Una actividad colgando de nadie no la ve nadie."""
    canales.declarar_canal(uow, clave="soporte", canal="correo", produce="caso")
    salida = canales.registrar(uow, canal="correo", id_externo="<w@correo>", clave_canal="soporte")
    assert salida["atribuida"] is False and salida["pedido"] == ""


def test_la_actividad_de_un_contacto_junta_todos_los_canales(
    uow: UnidadDeTrabajo,
) -> None:
    """La pregunta antes de llamar es «¿qué hemos hablado?», no «¿qué correos?»."""
    contacto = uuid4()
    canales.registrar(uow, canal="correo", id_externo="<1>", contacto_id=contacto)
    canales.registrar(uow, canal="voz", id_externo="cdr-1", contacto_id=contacto, duracion_s=180)
    salida = canales.actividad_de(uow.db, uow.tenant_id, contacto_id=contacto)
    assert salida["cuantas"] == 2
    assert salida["por_canal"] == {"correo": 1, "voz": 1}


# ── Federación y embebido (CRM-01.01.05.04, CRM-00.02.03.10) ──────────────


def _vista(uow: UnidadDeTrabajo, **kw: Any) -> fed.VistaFederada:
    base: dict[str, Any] = {
        "clave": "saldo",
        "objeto": "cuenta",
        "campos": [{"nombre": "saldo", "origen": "balance"}],
        "instalacion_clave": "erp-demo",
        "clave_registro": "nif",
        "cache_s": 0,
    }
    base.update(kw)
    fila, _ = fed.declarar_vista(uow, **base)
    return fila


def test_si_el_sistema_externo_no_contesta_se_dice(uow: UnidadDeTrabajo) -> None:
    """Un saldo vacío se lee como «no debe nada»."""
    fed.limpiar_cache()
    _vista(uow)

    def _falla(vista: Any, clave: str) -> dict[str, Any]:
        raise RuntimeError("timeout contra el ERP")

    salida = fed.componer(
        uow.db, uow.tenant_id, objeto="cuenta", registro={"nif": "B1"}, traer=_falla
    )
    bloque = salida["bloques"][0]
    assert bloque["disponible"] is False
    assert "no ha contestado" in bloque["porque"]
    assert salida["aviso"]


def test_sin_la_clave_del_registro_no_se_consulta_y_se_explica(
    uow: UnidadDeTrabajo,
) -> None:
    fed.limpiar_cache()
    _vista(uow)
    salida = fed.componer(
        uow.db, uow.tenant_id, objeto="cuenta", registro={}, traer=lambda v, c: {}
    )
    assert salida["bloques"][0]["disponible"] is False
    assert "no trae" in salida["bloques"][0]["porque"]


def test_lo_federado_se_marca_como_externo_y_con_su_edad(uow: UnidadDeTrabajo) -> None:
    fed.limpiar_cache()
    _vista(uow, cache_s=60)
    llamadas: list[str] = []

    def _traer(vista: Any, clave: str) -> dict[str, Any]:
        llamadas.append(clave)
        return {"balance": 1200}

    primera = fed.componer(
        uow.db, uow.tenant_id, objeto="cuenta", registro={"nif": "B1"}, traer=_traer, ahora=100.0
    )
    assert primera["bloques"][0]["datos"] == {"saldo": 1200}
    assert primera["bloques"][0]["externo"] is True
    assert primera["bloques"][0]["edad_s"] == 0.0

    segunda = fed.componer(
        uow.db, uow.tenant_id, objeto="cuenta", registro={"nif": "B1"}, traer=_traer, ahora=130.0
    )
    assert llamadas == ["B1"]
    assert segunda["bloques"][0]["de_cache"] is True
    assert segunda["bloques"][0]["edad_s"] == 30.0


def test_la_cache_caduca(uow: UnidadDeTrabajo) -> None:
    fed.limpiar_cache()
    _vista(uow, cache_s=10)
    llamadas: list[str] = []

    def _traer(vista: Any, clave: str) -> dict[str, Any]:
        llamadas.append(clave)
        return {"balance": 1}

    fed.componer(
        uow.db, uow.tenant_id, objeto="cuenta", registro={"nif": "B1"}, traer=_traer, ahora=0.0
    )
    fed.componer(
        uow.db, uow.tenant_id, objeto="cuenta", registro={"nif": "B1"}, traer=_traer, ahora=20.0
    )
    assert len(llamadas) == 2


def test_una_cache_larga_avisa(uow: UnidadDeTrabajo) -> None:
    """Si puede quedarse viejo, quizá lo que toca es replicarlo y decirlo."""
    _, avisos = fed.declarar_vista(
        uow,
        clave="riesgo",
        objeto="cuenta",
        campos=[{"nombre": "riesgo"}],
        instalacion_clave="erp",
        cache_s=3600,
    )
    assert any("deja de ser un dato en vivo" in a for a in avisos)


def test_un_embebido_sin_origenes_no_se_declara(uow: UnidadDeTrabajo) -> None:
    """Sin esa lista, cualquier página podría incrustarlo y pedir datos con la
    sesión de quien la abra."""
    with pytest.raises(ErrorValidacion):
        fed.declarar_embebido(uow, clave="erp", anfitrion="ERP", origenes=[], bloques=["ficha"])


def test_un_embebido_por_http_no_se_declara(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion):
        fed.declarar_embebido(
            uow, clave="erp", anfitrion="ERP", origenes=["http://erp.local"], bloques=["ficha"]
        )


def test_el_origen_no_admitido_no_dice_cuales_valen(uow: UnidadDeTrabajo) -> None:
    """Decirlo sería indicarle a quien prueba dónde tiene que ponerse."""
    fed.declarar_embebido(
        uow,
        clave="erp",
        anfitrion="ERP",
        origenes=["https://erp.cliente.com"],
        bloques=["ficha"],
        contexto={"customer_id": "cuenta_id"},
    )
    salida = fed.resolver_contexto(
        uow.db, uow.tenant_id, clave="erp", origen="https://otro.com", parametros={}
    )
    assert salida["admitido"] is False
    assert "erp.cliente.com" not in salida["porque"]


def test_si_el_anfitrion_no_manda_el_contexto_se_dice(uow: UnidadDeTrabajo) -> None:
    fed.declarar_embebido(
        uow,
        clave="erp",
        anfitrion="ERP",
        origenes=["https://erp.cliente.com"],
        bloques=["ficha"],
        contexto={"customer_id": "cuenta_id"},
    )
    salida = fed.resolver_contexto(
        uow.db,
        uow.tenant_id,
        clave="erp",
        origen="https://erp.cliente.com",
        parametros={},
    )
    assert salida["admitido"] is True
    assert salida["completo"] is False and salida["faltan_parametros"] == ["customer_id"]

    con_contexto = fed.resolver_contexto(
        uow.db,
        uow.tenant_id,
        clave="erp",
        origen="https://erp.cliente.com",
        parametros={"customer_id": "C-1"},
    )
    assert con_contexto["contexto"] == {"cuenta_id": "C-1"}


# ── Convivencia con el heredado (CRM-00.03.01.07) ─────────────────────────


def test_sin_reglas_manda_el_sistema_viejo(uow: UnidadDeTrabajo) -> None:
    """Equivocarse hacia el viejo produce un dato que hay que traer; hacia el
    nuevo, dos verdades."""
    salida = conv.quien_manda(uow.db, uow.tenant_id, objeto="pedido")
    assert salida["dueno"] == "heredado"
    assert salida["escribible_aqui"] is False
    assert salida["por_defecto"] is True


def test_ambos_escribiendo_exige_decir_quien_gana(uow: UnidadDeTrabajo) -> None:
    """Sin eso se decidiría por orden de llegada, que es perder datos sin que
    nadie se entere."""
    with pytest.raises(ErrorValidacion):
        conv.declarar(uow, objeto="cuenta", dueno="ambos")
    conv.declarar(uow, objeto="cuenta", dueno="ambos", manda_en_empate="nuevo")


def test_se_puede_cortar_por_criterio_y_se_explica(uow: UnidadDeTrabajo) -> None:
    """«Los clientes nuevos aquí, los antiguos allí» es como se migra de verdad."""
    conv.declarar(
        uow,
        objeto="cuenta",
        dueno="nuevo",
        nombre="cuentas-nuevas",
        prioridad=10,
        condiciones=[{"atributo": "migrada", "operador": "=", "valor": True}],
    )
    conv.declarar(uow, objeto="cuenta", dueno="heredado", nombre="resto", prioridad=100)

    nueva = conv.quien_manda(uow.db, uow.tenant_id, objeto="cuenta", registro={"migrada": True})
    vieja = conv.quien_manda(uow.db, uow.tenant_id, objeto="cuenta", registro={"migrada": False})
    assert nueva["dueno"] == "nuevo" and nueva["escribible_aqui"] is True
    assert vieja["dueno"] == "heredado"
    assert "cuentas-nuevas" in nueva["porque"]


def test_dos_reglas_con_la_misma_prioridad_avisan(uow: UnidadDeTrabajo) -> None:
    conv.declarar(uow, objeto="cuenta", dueno="nuevo", nombre="una", prioridad=10)
    _, avisos = conv.declarar(uow, objeto="cuenta", dueno="heredado", nombre="otra", prioridad=10)
    assert any("prioridad" in a for a in avisos)


def test_el_progreso_marca_las_medidas_viejas(uow: UnidadDeTrabajo) -> None:
    """Una medida de hace tres meses presentada como actual hace creer que va
    bien."""
    conv.declarar(uow, objeto="cuenta", dueno="ambos", manda_en_empate="nuevo")
    medida = conv.medir(uow, objeto="cuenta", en_heredado=20, en_nuevo=80)
    medida.medido_at = datetime.now(timezone.utc) - timedelta(days=100)
    uow.db.flush()
    salida = conv.progreso(uow.db, uow.tenant_id)
    assert salida["objetos"][0]["pct_migrado"] == 80.0
    assert salida["objetos"][0]["medida_fresca"] is False
    assert salida["concluyente"] is False


def test_un_objeto_con_regla_y_sin_medir_se_senala(uow: UnidadDeTrabajo) -> None:
    """Son los que llevan la migración a no terminar nunca."""
    conv.declarar(uow, objeto="pedido", dueno="heredado")
    salida = conv.progreso(uow.db, uow.tenant_id)
    assert salida["con_regla_sin_medir"] == ["pedido"]


def test_no_se_da_por_migrado_con_registros_en_el_viejo(uow: UnidadDeTrabajo) -> None:
    """Cerrarlo dejaría fuera lo que queda allí, y nadie volvería a mirarlo."""
    conv.declarar(uow, objeto="cuenta", dueno="heredado")
    conv.medir(uow, objeto="cuenta", en_heredado=5, en_nuevo=95)
    with pytest.raises(ErrorValidacion):
        conv.dar_por_migrado(uow, objeto="cuenta")
    with pytest.raises(ErrorValidacion):
        conv.dar_por_migrado(uow, objeto="cuenta", forzar=True)
    salida = conv.dar_por_migrado(
        uow, objeto="cuenta", forzar=True, motivo="Los 5 que quedan son basura histórica"
    )
    assert salida["quedaban_en_heredado"] == 5
    assert conv.quien_manda(uow.db, uow.tenant_id, objeto="cuenta")["dueno"] == "nuevo"


def test_no_se_da_por_migrado_algo_que_nadie_ha_contado(uow: UnidadDeTrabajo) -> None:
    conv.declarar(uow, objeto="cuenta", dueno="heredado")
    with pytest.raises(ErrorValidacion) as error:
        conv.dar_por_migrado(uow, objeto="cuenta")
    assert "nadie ha contado" in str(error.value)


# ── Transformación y validación del mapeo (CRM-00.03.04.04) ──────────────
#
# El mapeo copiaba valores de un sitio a otro y nada más. Lo que pasa en toda
# integración de verdad es que el valor NO sirve tal cual: el código viene con
# espacios, el país en minúsculas, el importe como texto con coma, la fecha con
# el formato del otro lado. Sin transformaciones hay dos salidas y las dos son
# malas — escribir un conector a medida por cliente, que es lo que el conector
# genérico existe para evitar, o meter los datos sucios y arreglarlos después,
# cuando ya han disparado automatizaciones.


def test_el_valor_se_transforma_antes_de_entrar_crm_00_03_04_04() -> None:
    """Las que se piden siempre: recortar, mayúsculas y el número con coma.

    Un `1.234,56` que llega como texto y se guarda como texto convierte toda
    suma posterior en una concatenación, y eso se descubre en un informe.
    """
    from decimal import Decimal

    from services.integration.conector import mapear

    operacion = {
        "mapeo": {"nombre": "n", "importe": "i"},
        "transformar": {"nombre": ["recortar", "mayusculas"], "importe": ["numero"]},
    }
    salida = mapear([{"n": "  acme ", "i": "1.234,56"}], operacion)
    assert salida == [{"nombre": "ACME", "importe": Decimal("1234.56")}], salida


def test_el_valor_por_defecto_corre_aunque_no_venga_nada_crm_00_03_04_04() -> None:
    """Es la transformación más pedida de todas, y sólo sirve si se aplica al
    hueco: si sólo corriera sobre lo que viene, no serviría para nada."""
    from services.integration.conector import mapear

    operacion = {
        "mapeo": {"pais": "p"},
        "transformar": {"pais": [{"f": "defecto", "arg": "ES"}]},
    }
    assert mapear([{"otro": 1}], operacion) == [{"pais": "ES"}]


def test_la_fecha_no_se_adivina_crm_00_03_04_04() -> None:
    """Con el formato del otro lado se convierte; sin él, ISO.

    Lo que NO se hace es elegir entre `%d/%m` y `%m/%d` por sorteo: el 3 de
    abril y el 4 de marzo son los dos válidos, y acertar por casualidad mete
    una fecha equivocada que nadie revisa.
    """
    from services.integration.conector import aplicar_funciones

    assert aplicar_funciones("03/04/2026", [{"f": "fecha", "arg": "%d/%m/%Y"}]) == "2026-04-03"
    # Sin formato y sin ser ISO, se deja como está en vez de inventarse una.
    assert aplicar_funciones("03/04/2026", ["fecha"]) == "03/04/2026"


def test_un_codigo_que_no_esta_en_la_tabla_no_se_inventa_crm_00_03_04_04() -> None:
    """Devuelve el original, y entonces la validación lo rechaza si el campo
    tiene lista cerrada. Es mejor que meter un estado que aquí no significa
    nada y que nadie volverá a mirar."""
    from services.integration.conector import aplicar_funciones

    tabla = [{"f": "mapa", "arg": {"OPEN": "abierta"}}]
    assert aplicar_funciones("OPEN", tabla) == "abierta"
    assert aplicar_funciones("WEIRD", tabla) == "WEIRD"


def test_lo_que_no_cumple_se_aparta_con_su_motivo_crm_00_03_04_04() -> None:
    """Ni se cuela ni se tira en silencio.

    Colarlo mete datos sucios que disparan automatizaciones; tirarlo callando
    deja una importación que dice «200 registros» y guarda 180 sin que nadie
    pregunte, y el hueco se descubre semanas después.
    """
    from services.integration.conector import mapear

    operacion = {
        "mapeo": {"nombre": "n", "pais": "p"},
        "validar": {"obligatorios": ["nombre"], "admitidos": {"pais": ["ES", "FR"]}},
    }
    rechazos: list[dict[str, Any]] = []
    salida = mapear(
        [{"n": "uno", "p": "ES"}, {"p": "DE"}, {"n": "dos", "p": "PT"}],
        operacion,
        rechazos=rechazos,
    )
    assert salida == [{"nombre": "uno", "pais": "ES"}], salida
    assert len(rechazos) == 2, rechazos
    assert "falta «nombre»" in rechazos[0]["motivos"]
    assert "no está entre los admitidos" in rechazos[1]["motivos"][0]


def test_una_funcion_mal_escrita_se_caza_al_publicar_crm_00_03_04_04() -> None:
    """Y no en la primera importación de un cliente, donde ya hay registros a
    medio traducir y nadie sabe cuáles."""
    from services.integration.manifiestos import validar

    base = {
        "clave": "erp",
        "nombre": "ERP",
        "version": "1.0.0",
        "dominios": ["erp.example"],
    }
    mala = {
        "clave": "pedidos",
        "ruta": "/p",
        "mapeo": {"nombre": "n"},
        "transformar": {"nombre": ["mayuscuals"]},
    }
    problemas = validar({**base, "operaciones": [mala]})
    assert any("mayuscuals" in p for p in problemas), problemas

    buena = {**mala, "transformar": {"nombre": ["mayusculas"]}}
    assert validar({**base, "operaciones": [buena]}) == []


def test_validar_un_campo_que_el_mapeo_no_produce_se_caza_crm_00_03_04_04() -> None:
    """Sería una regla que no se cumple jamás: rechazaría todos los registros
    y el motivo señalaría a un campo que no existe."""
    from services.integration.manifiestos import validar

    manifiesto = {
        "clave": "erp",
        "nombre": "ERP",
        "version": "1.0.0",
        "dominios": ["erp.example"],
        "operaciones": [
            {
                "clave": "pedidos",
                "ruta": "/p",
                "mapeo": {"nombre": "n"},
                "validar": {"obligatorios": ["pais"]},
            }
        ],
    }
    problemas = validar(manifiesto)
    assert any("no produce" in p for p in problemas), problemas


def test_las_funciones_son_una_lista_cerrada_crm_00_03_04_04() -> None:
    """**Una expresión arbitraria en la configuración de una integración es
    código de un usuario final corriendo en el servidor**, con los permisos del
    servicio y sin revisión. Es la misma decisión que en las acciones de las
    automatizaciones, y por el mismo motivo."""
    from services.integration.conector import FUNCIONES

    assert FUNCIONES, "no hay funciones de transformación"
    prohibidas = {"eval", "exec", "codigo", "script", "python", "lambda", "expresion"}
    assert not (set(FUNCIONES) & prohibidas), sorted(set(FUNCIONES) & prohibidas)
