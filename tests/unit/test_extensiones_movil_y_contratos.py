"""Código del tenant, móvil sin cobertura, CDC al lago y el contrato binario
(CRM-00.04.02.01, .05, .06, .07 · CRM-06.02.01.03, .04 · CRM-00.02.02.06 ·
CRM-00.02.01.03 · CRM-00.02.03.02 · CRM-00.04.03.01).

Lo que persiguen estas pruebas son fallos que **no dan error**: la extensión que
se queda sin cortar, el cambio del móvil que desaparece sin rastro, el borrado
que no viaja y se queda en el lago del cliente para siempre, y el número de
campo reutilizado, que mete un valor en la casilla equivocada sin que salte nada
en ningún sitio.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import (
    Conflicto,
    ErrorValidacion,
    NoAutenticado,
    NoDisponible,
    PeticionMalFormada,
    Prohibido,
)
from crmcore.movil import (
    detectar_conflicto,
    estado_de_la_cola,
    preparar_envio,
    preparar_push,
    resolver,
)
from crmcore.rpc import esquema as rpc
from crmcore.rpc import mensajes as msg
from crmcore.rpc import servidor as srv

from services.automation import extensiones as ext
from services.eventing import cdc
from services.metadata import disenador as dis


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── Sandbox de extensiones (CRM-00.04.02.01) ──────────────────────────────


def test_el_limite_lo_pone_el_sandbox_y_no_la_buena_voluntad() -> None:
    """Pedirle al cliente que su función no tarde es pedirle que se porte bien.
    Eso funciona hasta que alguien mete un bucle."""
    salida = ext.comprobar_limites(consumo={"milisegundos": 9_000, "memoria_mb": 10})
    assert salida["dentro"] is False
    assert salida["excedidos"][0]["limite"] == "milisegundos"
    assert "todos los que comparten ese worker" in salida["que_pasa"]


def test_una_capacidad_prohibida_se_rechaza_al_declararla_no_al_ejecutarla() -> None:
    """Aceptarla y bloquearla después deja la comprobación en ejecución como
    única barrera, y esa se salta el día que alguien añade un camino nuevo."""
    with pytest.raises(Prohibido) as fallo:
        ext.exigir_permitido(capacidades=["leer_otro_tenant", "leer_agenda"])
    assert fallo.value.error_code == "extension.capacidad_prohibida"
    assert "aislamiento" in str(fallo.value)


def test_una_version_nueva_no_pisa_a_la_anterior() -> None:
    """Desplegar pisando deja sin sitio a lo que está ejecutándose, y volver
    atrás exige tener la anterior entera y viva."""
    with pytest.raises(Conflicto):
        ext.publicar_version(
            clave="x",
            codigo=b"...",
            version=2,
            dependencias={"requests": "2.31.0"},
            capacidades=[],
            versiones_vivas=[1, 2],
        )
    salida = ext.publicar_version(
        clave="x",
        codigo=b"...",
        version=3,
        dependencias={"requests": "2.31.0"},
        capacidades=[],
        versiones_vivas=[1, 2],
    )
    assert salida["convive_con"] == [1, 2]


def test_una_dependencia_sin_fijar_no_pasa() -> None:
    """Una extensión que declara «la última versión» falla el día que esa
    librería publique un cambio, sin que nadie haya tocado nada."""
    with pytest.raises(ErrorValidacion) as fallo:
        ext.publicar_version(
            clave="x",
            codigo=b"c",
            version=1,
            dependencias={"requests": "^2.31"},
            capacidades=[],
            versiones_vivas=[],
        )
    assert fallo.value.error_code == "extension.dependencia_sin_fijar"


def test_firmada_pero_sin_revisar_no_se_instala() -> None:
    """La firma dice QUIÉN lo escribió, no que sea seguro. Automatizar «¿este
    código es seguro?» es el problema que nadie ha resuelto."""
    codigo = b"print(1)"
    salida = ext.revisar_firma(
        codigo=codigo,
        huella_firmada=ext.huella_de(codigo),
        firmante="acme",
        firmantes_de_confianza=["acme"],
    )
    assert salida["instalable"] is False
    assert "sin revisar" in salida["porque"]


def test_el_codigo_que_no_coincide_con_la_firma_no_se_instala() -> None:
    """Puede ser manipulación o un empaquetado mal hecho; en los dos casos, lo
    que se instalaría no es lo que alguien revisó."""
    salida = ext.revisar_firma(
        codigo=b"otro",
        huella_firmada=ext.huella_de(b"original"),
        firmante="acme",
        firmantes_de_confianza=["acme"],
        revisada_por=uuid4(),
    )
    assert salida["instalable"] is False


def test_sin_ejecuciones_no_se_dice_que_va_bien() -> None:
    """No se ha ejecutado, o no se está midiendo. Las dos cosas son distintas de
    «va bien»."""
    salida = ext.observabilidad(clave="x", ejecuciones=[])
    assert salida["medible"] is False
    assert "no se ha ejecutado" in salida["porque"]


def test_el_coste_se_atribuye_a_quien_lo_gasta() -> None:
    """Sin números no se puede tener la conversación con el cliente que se pasa."""
    salida = ext.observabilidad(
        clave="x",
        ejecuciones=[{"ok": True, "milisegundos": 2_000}, {"ok": False, "milisegundos": 1_000}],
        coste_por_segundo=0.01,
    )
    assert salida["coste_atribuido"] == 0.03
    assert salida["fallidas"] == 1
    assert salida["errores_son_del_tenant"] is True


def test_una_cortada_por_limite_no_se_cuenta_como_un_error_cualquiera() -> None:
    """Una que falla tiene un error que arreglar; una que se corta tiene un
    diseño que revisar."""
    resumen = ext.resumen_de_ejecucion(
        clave="x", version=1, entrada={"id": "1"}, consumo={"milisegundos": 99_000}
    )
    assert resumen["cortada_por_limite"] is True
    salida = ext.observabilidad(clave="x", ejecuciones=[resumen])
    assert salida["cortadas_por_limite"] == 1
    assert "pide más de lo que se le da" in salida["que_mirar"]


def test_se_guarda_la_entrada_y_no_la_salida() -> None:
    """Reproducir a ciegas un fallo son horas; guardar la salida duplica el dato
    que hay que proteger en una tabla de logs."""
    resumen = ext.resumen_de_ejecucion(
        clave="x", version=1, entrada={"id": "42"}, consumo={"milisegundos": 5}
    )
    assert resumen["entrada"] == {"id": "42"}
    assert "salida" not in resumen


# ── Móvil y modo sin conexión (CRM-06.02.01.03, .04) ──────────────────────


def test_sin_identificador_del_cliente_no_se_sincroniza() -> None:
    """Es lo que hace que un reintento tras un timeout no cree una visita
    duplicada: sin él, la duda de si llegó no tiene respuesta correcta."""
    with pytest.raises(ErrorValidacion) as fallo:
        preparar_envio(operaciones=[{"tipo": "crear"}])
    assert fallo.value.error_code == "movil.operacion_sin_id"


def test_una_actualizacion_sin_version_base_no_pasa() -> None:
    """Sin ella no se puede detectar el conflicto: se aplicaría encima de lo que
    haya y el cambio de la otra persona desaparecería sin rastro."""
    with pytest.raises(ErrorValidacion) as fallo:
        preparar_envio(operaciones=[{"tipo": "actualizar", "id_cliente": "a"}])
    assert fallo.value.error_code == "movil.actualizacion_sin_version"


def test_tocar_campos_distintos_no_es_un_conflicto() -> None:
    """Tratarlo como conflicto enseña a la gente a pulsar «quedarme con lo mío»,
    que es como se pierde el trabajo del otro de todas formas."""
    salida = detectar_conflicto(
        version_base=1,
        version_servidor=2,
        campos_cliente={"telefono": "600"},
        campos_servidor={"direccion": "Calle 2"},
    )
    assert salida["hay_conflicto"] is False
    assert salida["fusionable"] is True


def test_el_mismo_campo_tocado_por_los_dos_si_lo_es() -> None:
    salida = detectar_conflicto(
        version_base=1,
        version_servidor=2,
        campos_cliente={"telefono": "600"},
        campos_servidor={"telefono": "700"},
    )
    assert salida["hay_conflicto"] is True
    assert salida["campos"] == ["telefono"]


def test_la_resolucion_manual_guarda_las_dos_versiones() -> None:
    """Descartar una para «no molestar al usuario» es descartar trabajo de
    alguien: decidirlo cuesta un minuto, reconstruirlo una mañana."""
    salida = resolver(
        estrategia="manual",
        campos_cliente={"telefono": "600"},
        campos_servidor={"telefono": "700"},
        campos_en_conflicto=["telefono"],
    )
    assert salida["resuelto"] is False
    assert salida["version_del_movil"]["telefono"] == "600"
    assert salida["version_del_servidor"]["telefono"] == "700"


def test_lo_que_se_descarta_se_devuelve() -> None:
    """Descartarlo en silencio es lo que hace que nadie pueda reconstruirlo."""
    salida = resolver(
        estrategia="gana_cliente",
        campos_cliente={"telefono": "600"},
        campos_servidor={"telefono": "700"},
        campos_en_conflicto=["telefono"],
    )
    assert salida["descartado"] == {"telefono": "700"}


def test_no_se_llama_fusion_a_elegir_uno() -> None:
    with pytest.raises(Conflicto) as fallo:
        resolver(
            estrategia="fusionar_campos",
            campos_cliente={"a": 1},
            campos_servidor={"a": 2},
            campos_en_conflicto=["a"],
        )
    assert fallo.value.error_code == "movil.fusion_imposible"


def test_la_cola_no_descarta_nada_y_avisa_de_lo_viejo() -> None:
    """Una cola que tira lo que falla convierte un problema de red en una
    pérdida de datos que el usuario descubre semanas después."""
    ahora = datetime(2026, 9, 23, tzinfo=timezone.utc)
    salida = estado_de_la_cola(
        pendientes=[
            {"id_cliente": "a", "creado_at": ahora - timedelta(days=9)},
            {"id_cliente": "b", "creado_at": ahora, "en_conflicto": True},
        ],
        ahora=ahora,
    )
    assert salida["se_descarta_algo"] is False
    assert salida["esperando_demasiado"][0]["id_cliente"] == "a"
    assert salida["en_conflicto"] == 1


def test_el_push_no_lleva_el_dato_dentro() -> None:
    """Llega a una pantalla bloqueada que puede ver cualquiera que coja el
    teléfono, y pasa por servidores de terceros."""
    salida = preparar_push(
        tipo="oportunidad_ganada", objeto="oportunidad", objeto_id=uuid4(), titulo_corto="Cerrada"
    )
    assert salida["sin_datos_dentro"] is True
    assert set(salida["referencia"]) == {"objeto", "objeto_id"}


# ── CDC hacia el lago del cliente (CRM-00.02.02.06) ───────────────────────


def test_lo_personal_no_sale_por_defecto() -> None:
    """Lo que sale ya no vuelve: una vez está en su lago está bajo sus reglas,
    sus permisos y sus copias."""
    salida = cdc.declarar_flujo(
        objeto="contacto",
        campos=[
            {"clave": "email", "sensibilidad": "personal"},
            {"clave": "sector"},
        ],
        destino="s3://lago",
    )
    assert [c["clave"] for c in salida["campos_que_salen"]] == ["sector"]
    assert salida["campos_que_no_salen"][0]["campo"] == "email"


def test_si_sale_un_personal_sin_seudonimizar_se_avisa() -> None:
    salida = cdc.declarar_flujo(
        objeto="contacto",
        campos=[{"clave": "email", "sensibilidad": "personal", "trato": "tal_cual"}],
        destino="s3://lago",
    )
    assert "transferencia" in salida["aviso"]
    assert salida["personales_que_salen"] == ["email"]


def test_se_manda_el_hecho_y_no_la_foto() -> None:
    """Con la foto sola, el que recibe no puede reconstruir nada si se le escapó
    un mensaje: se queda con algo que no sabe de cuándo es."""
    mensaje = cdc.componer_cambio(
        objeto="cuenta",
        registro_id=uuid4(),
        tipo="modificacion",
        antes={"nombre": "A", "sector": "X"},
        despues={"nombre": "B", "sector": "X"},
        campos_permitidos=["nombre", "sector"],
        secuencia=7,
    )
    assert mensaje["campos_cambiados"] == ["nombre"]
    assert mensaje["antes"] == {"nombre": "A"}
    assert mensaje["despues"] == {"nombre": "B"}


def test_el_borrado_viaja_como_borrado_y_sin_datos() -> None:
    """Omitirlo deja un lago que crece para siempre con gente que ya ejerció su
    derecho de supresión, y el incumplimiento pasa a casa del cliente."""
    mensaje = cdc.componer_cambio(
        objeto="contacto",
        registro_id=uuid4(),
        tipo="baja",
        antes={"email": "a@b.c"},
        despues=None,
        campos_permitidos=["email"],
        secuencia=8,
    )
    assert mensaje["sin_datos"] is True
    assert mensaje["campos_cambiados"] == []
    assert "email" not in str(mensaje)


def test_la_marca_se_para_en_el_primer_fallo() -> None:
    """Avanzar hasta el último confirmado dejaría un hueco que no se detecta: el
    lago tendría un dato viejo y se descubriría cuadrando cifras."""
    salida = cdc.avanzar_marca(marca_actual=1, confirmados=[2, 3, 6, 7], fallidos=[4])
    assert salida["marca"] == 3
    assert salida["parada_en"] == 4


def test_sin_nada_confirmado_la_marca_no_se_mueve() -> None:
    salida = cdc.avanzar_marca(marca_actual=5, confirmados=[], fallidos=[])
    assert salida["avanza"] is False


# ── Contrato protobuf (CRM-00.02.01.03) ───────────────────────────────────


def test_un_numero_que_se_borra_queda_reservado_para_siempre() -> None:
    """Reutilizarlo mete el valor en el campo equivocado: no hay error, no hay
    log, y se descubre cuando alguien pregunta por una zona que no existe."""
    campos = [{"clave": "nombre", "tipo": "texto"}, {"clave": "descuento", "tipo": "numero"}]
    primera = rpc.asignar_numeros(campos=campos)
    segunda = rpc.asignar_numeros(
        campos=[{"clave": "nombre", "tipo": "texto"}, {"clave": "id_zona", "tipo": "numero"}],
        asignados=primera["numeros"],
    )
    assert primera["numeros"]["descuento"] in segunda["reservados"]
    assert segunda["numeros"]["id_zona"] != primera["numeros"]["descuento"]


def test_reordenar_los_campos_no_cambia_ningun_numero() -> None:
    """El orden del `.proto` es cosmético y el número es el contrato."""
    campos = [{"clave": "a", "tipo": "texto"}, {"clave": "b", "tipo": "texto"}]
    antes = rpc.asignar_numeros(campos=campos)["numeros"]
    despues = rpc.asignar_numeros(campos=list(reversed(campos)), asignados=antes)["numeros"]
    assert antes == despues


def test_un_tipo_sin_correspondencia_no_cae_a_string() -> None:
    """Caer a string convierte un decimal en una cadena que el otro lado parsea
    como puede, y en importes acaba en una factura mal."""
    with pytest.raises(ErrorValidacion) as fallo:
        rpc.proto_de_objeto(objeto="x", campos=[{"clave": "c", "tipo": "lo_que_sea"}])
    assert fallo.value.error_code == "rpc.tipo_sin_correspondencia"


def test_un_campo_cifrado_no_sale_por_el_contrato() -> None:
    """Lo que se guarda cifrado se descifra por el camino que ya se auditó, no
    por una superficie nueva."""
    with pytest.raises(ErrorValidacion) as fallo:
        rpc.proto_de_objeto(objeto="x", campos=[{"clave": "iban", "tipo": "cifrado"}])
    assert fallo.value.error_code == "rpc.tipo_no_publicable"


def test_el_proto_declara_reserved_cuando_hubo_bajas() -> None:
    campos = [{"clave": "nombre", "tipo": "texto"}, {"clave": "viejo", "tipo": "texto"}]
    primera = rpc.asignar_numeros(campos=campos)["numeros"]
    salida = rpc.proto_de_objeto(
        objeto="cuenta", campos=[{"clave": "nombre", "tipo": "texto"}], asignados=primera
    )
    assert "reserved" in salida["contenido"]
    assert '"viejo"' in salida["contenido"]


def test_cambiar_el_tipo_de_un_campo_rompe_a_quien_consume() -> None:
    salida = rpc.comprobar_compatibilidad(
        antes={"numeros": {"a": 1}, "tipos": {"a": "int64"}, "reservados": []},
        despues={"numeros": {"a": 1}, "tipos": {"a": "string"}, "reservados": []},
    )
    assert salida["compatible"] is False
    assert salida["problemas"][0]["tipo"] == "tipo_cambiado"


def test_quitar_un_campo_sin_reservar_su_numero_se_caza() -> None:
    salida = rpc.comprobar_compatibilidad(
        antes={"numeros": {"a": 1, "b": 2}, "tipos": {}, "reservados": []},
        despues={"numeros": {"a": 1}, "tipos": {}, "reservados": []},
    )
    assert salida["compatible"] is False
    assert salida["problemas"][0]["tipo"] == "campo_quitado_sin_reservar"


def test_anadir_un_campo_es_compatible() -> None:
    """Es justo lo que protobuf garantiza: lo que no se conoce se ignora."""
    salida = rpc.comprobar_compatibilidad(
        antes={"numeros": {"a": 1}, "tipos": {"a": "string"}, "reservados": []},
        despues={"numeros": {"a": 1, "b": 2}, "tipos": {"a": "string", "b": "string"}},
    )
    assert salida["compatible"] is True
    assert salida["campos_nuevos"] == ["b"]


def test_un_cero_y_un_no_lo_mando_no_son_lo_mismo() -> None:
    """Sin presencia explícita, un `Update` de tres campos borraría los otros
    veinte sin que el cliente lo pretendiera."""
    clase = msg.clase_de_objeto(
        objeto="cuenta",
        campos=[{"clave": "nombre", "tipo": "texto"}, {"clave": "empleados", "tipo": "numero"}],
    )
    con_cero = msg.a_diccionario(msg.a_mensaje(clase, {"empleados": 0}))
    sin_nada = msg.a_diccionario(msg.a_mensaje(clase, {"nombre": "A"}))
    assert con_cero == {"empleados": 0}
    assert "empleados" not in sin_nada


def test_un_campo_que_no_esta_en_el_contrato_es_un_error() -> None:
    """Protobuf descarta lo desconocido por diseño: quien manda `descuneto` cree
    que puso un descuento y recibiría un «todo bien» con la ficha sin él."""
    clase = msg.clase_de_objeto(objeto="cuenta", campos=[{"clave": "nombre", "tipo": "texto"}])
    with pytest.raises(PeticionMalFormada) as fallo:
        msg.a_mensaje(clase, {"descuneto": 1})
    assert fallo.value.error_code == "rpc.campo_desconocido"


def test_el_mensaje_va_y_vuelve_por_el_cable_igual() -> None:
    clase = msg.clase_de_objeto(
        objeto="cuenta",
        campos=[{"clave": "nombre", "tipo": "texto"}, {"clave": "tags", "tipo": "lista_multiple"}],
    )
    original = {"nombre": "Acme", "tags": ["vip", "activo"]}
    ida = msg.a_mensaje(clase, original).SerializeToString()
    assert msg.a_diccionario(clase.FromString(ida)) == original


def test_una_ruta_grpc_desconocida_no_se_adivina() -> None:
    """Adivinar aquí significa servir `contacto` a quien pidió otra cosa, y el
    cliente se queda con datos que no son suyos creyendo que va bien."""
    with pytest.raises(PeticionMalFormada):
        srv.resolver_metodo("/loquesea/Get")
    assert srv.resolver_metodo("/crm.contacto.v1.ContactoService/Get")["objeto"] == "contacto"


def test_sin_token_no_se_entra_por_grpc() -> None:
    """gRPC no tiene cookies ni sesión: la identidad viaja en los metadatos de
    cada llamada, y se valida con el mismo código que HTTP."""
    with pytest.raises(NoAutenticado) as fallo:
        srv.principal_de_metadatos({"x-tenant": "acme"})
    assert fallo.value.error_code == "rpc.sin_token"


def test_sin_la_libreria_el_transporte_lo_dice_en_vez_de_callarse() -> None:
    """Un hueco callado es peor que una dependencia que falta: aquí se dice qué
    instalar, y el contrato sigue funcionando sin ella."""
    if srv.disponible():
        pytest.skip("este despliegue tiene grpcio instalado")
    with pytest.raises(NoDisponible) as fallo:
        srv.exigir_disponible()
    assert "requirements-grpc.txt" in str(fallo.value.detalle)


def test_los_topes_del_flujo_salen_de_la_configuracion() -> None:
    """Un `Watch` retiene una conexión mientras dura: el tope no puede ser una
    constante escondida en el código."""
    from crmcore.config import get_settings

    topes = srv.limites(get_settings())
    assert topes["elementos_por_flujo"] == get_settings().grpc_elementos_por_flujo


# ── Diseñador visual (CRM-00.04.03.01) ────────────────────────────────────


CAMPOS = [
    {"clave": "nombre", "tipo": "texto", "obligatorio": True},
    {"clave": "importe", "tipo": "moneda"},
    {"clave": "notas", "tipo": "texto_largo"},
]


def test_un_campo_que_no_existe_no_se_guarda_en_el_diseno() -> None:
    """Se guardaría, no se pintaría, y nadie relacionaría la pantalla vacía con
    el diseño que se tocó hace un mes."""
    salida = dis.validar_layout(
        secciones=[{"clave": "general", "campos": [{"clave": "inventado"}]}],
        campos_del_esquema=CAMPOS,
    )
    assert salida["valido"] is False
    assert any("no existe" in p["problema"] for p in salida["problemas"])


def test_el_mismo_campo_en_dos_secciones_se_caza() -> None:
    """Se pinta dos veces: el usuario escribe en uno y al guardar gana el otro,
    el que no tocó."""
    salida = dis.validar_layout(
        secciones=[
            {"clave": "a", "campos": [{"clave": "nombre"}]},
            {"clave": "b", "campos": [{"clave": "nombre"}]},
        ],
        campos_del_esquema=CAMPOS,
    )
    assert any("ya está en" in p["problema"] for p in salida["problemas"])


def test_un_obligatorio_sin_sitio_no_pasa() -> None:
    """No se puede rellenar y el alta fallará sin que el usuario vea dónde está
    el problema."""
    salida = dis.validar_layout(
        secciones=[{"clave": "a", "campos": [{"clave": "importe"}]}],
        campos_del_esquema=CAMPOS,
    )
    assert any("obligatorios que no están" in p["problema"] for p in salida["problemas"])


def test_una_condicion_sobre_un_campo_inexistente_no_se_cumple_nunca() -> None:
    """El campo no aparecería jamás y nadie sabría por qué."""
    problemas = dis.validar_condicion({"campo": "fantasma", "operador": "="}, {"nombre"})
    assert problemas
    assert "no se cumple nunca" in problemas[0]


def test_arrastrar_un_campo_lo_quita_de_donde_estaba() -> None:
    """Un «añadir» sin «quitar» deja el campo en los dos sitios, que es el fallo
    que hace que al guardar gane el que el usuario no tocó."""
    secciones = [
        {"clave": "a", "campos": [{"clave": "nombre"}, {"clave": "importe"}]},
        {"clave": "b", "campos": []},
    ]
    nuevas = dis.mover(secciones=secciones, campo="importe", a_seccion="b")
    assert [c["clave"] for c in nuevas[0]["campos"]] == ["nombre"]
    assert [c["clave"] for c in nuevas[1]["campos"]] == ["importe"]


def test_la_visibilidad_se_resuelve_en_el_servidor() -> None:
    """Si la evaluara el front, el dato del campo escondido habría viajado hasta
    el navegador igualmente."""
    salida = dis.evaluar_visibilidad(
        secciones=[
            {
                "clave": "a",
                "campos": [
                    {"clave": "nombre"},
                    {"clave": "importe", "condicion": {"campo": "nombre", "operador": "="}},
                ],
            }
        ],
        registro={"nombre": "Acme"},
    )
    claves = [c["clave"] for c in salida["secciones"][0]["campos"]]
    assert claves == ["nombre"]
    assert salida["cuantos_escondidos"] == 1
    assert "es un permiso" in salida["aviso"]


def test_esconder_por_condicion_no_es_proteger() -> None:
    """Lo que no se puede ver es un permiso; la condición solo quita ruido."""
    salida = dis.validar_layout(
        secciones=[
            {
                "clave": "a",
                "campos": [
                    {"clave": "nombre"},
                    {
                        "clave": "importe",
                        "condicion": {"campo": "nombre", "operador": "no_vacio"},
                    },
                ],
            }
        ],
        campos_del_esquema=[*CAMPOS[:1], {**CAMPOS[1], "permiso": "finanzas:read"}, CAMPOS[2]],
    )
    assert any("lo que protege el dato es el permiso" in a for a in salida["avisos"])


def test_ordenar_por_un_texto_largo_se_rechaza() -> None:
    """Con mil filas no se nota; con un millón, la lista deja de abrirse y nadie
    relaciona una cosa con la otra."""
    salida = dis.columnas_de_lista(
        columnas=[{"clave": "notas", "ordenable": True}], campos_del_esquema=CAMPOS
    )
    assert salida["valido"] is False
    assert "recorrer la tabla entera" in salida["problemas"][0]["consecuencia"]


def test_comparar_un_nulo_no_es_falso_sin_mas() -> None:
    """Tratarlo como falso esconde el campo sin que nadie sepa por qué."""
    salida = dis.evaluar_visibilidad(
        secciones=[
            {
                "clave": "a",
                "campos": [
                    {"clave": "importe", "condicion": {"campo": "x", "operador": ">", "valor": 1}}
                ],
            }
        ],
        registro={},
    )
    assert salida["cuantos_escondidos"] == 1


# ── La UI de referencia es opcional (CRM-00.02.03.02) ─────────────────────


def test_un_servicio_no_sirve_la_interfaz_desde_la_api() -> None:
    """Un estático montado hace que el front viaje dentro del backend:
    desplegar la API pasa a desplegar la interfaz."""
    from crmcore.http.ui_opcional import comprobar_independencia

    from services.metadata.main import app

    salida = comprobar_independencia(app, origenes_cors=[])
    assert salida["independiente"] is True, salida["hallazgos"]


def test_un_cors_con_un_solo_origen_ata_la_api_a_una_interfaz() -> None:
    """Cualquier otro front —el del cliente, un portal, un quiosco— queda fuera
    por configuración, por muy headless que sea la API."""
    from crmcore.http.ui_opcional import comprobar_independencia

    from services.metadata.main import app

    salida = comprobar_independencia(app, origenes_cors=["https://consola.acme.com"])
    assert salida["independiente"] is False
    assert salida["hallazgos"][0]["donde"] == "CORS"


def test_apagar_la_interfaz_no_quita_ninguna_operacion() -> None:
    """Todo lo que hace la consola es una llamada de la superficie publicada,
    que es de donde ella misma las saca."""
    from crmcore.config import get_settings
    from crmcore.http.ui_opcional import estado_de_la_ui

    salida = estado_de_la_ui(settings=get_settings())
    assert salida["es_requisito_de_licencia"] is False
    assert any("Ninguna operación" in x for x in salida["que_NO_se_pierde"])


# ── El contrato guardado, con base de datos (CRM-00.02.01.03) ─────────────


@pytest.mark.db
def test_publicar_un_esquema_incompatible_se_para_antes_de_congelarlo(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Romper aquí cuesta un minuto; romper en producción cuesta la llamada del
    cliente que integró hace seis meses."""
    from services.metadata import contrato_rpc as cr

    cr.sincronizar(
        uow,
        objeto="cuenta",
        campos=[{"clave": "nombre", "tipo": "texto"}, {"clave": "empleados", "tipo": "numero"}],
    )
    with pytest.raises(Conflicto) as fallo:
        cr.sincronizar(
            uow,
            objeto="cuenta",
            campos=[
                {"clave": "nombre", "tipo": "texto"},
                {"clave": "empleados", "tipo": "texto"},
            ],
        )
    assert fallo.value.error_code == "rpc.contrato_roto"


@pytest.mark.db
def test_los_numeros_sobreviven_a_un_campo_borrado(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es lo único que impide que el siguiente campo coja ese número y el valor
    entre en la casilla equivocada sin error."""
    from services.metadata import contrato_rpc as cr

    primera = cr.sincronizar(
        uow,
        objeto="contacto",
        campos=[{"clave": "nombre", "tipo": "texto"}, {"clave": "movil", "tipo": "telefono"}],
    )
    numero_viejo = primera["numeros"]["movil"]
    segunda = cr.sincronizar(
        uow,
        objeto="contacto",
        campos=[{"clave": "nombre", "tipo": "texto"}, {"clave": "fijo", "tipo": "telefono"}],
    )
    assert numero_viejo in segunda["reservados"]
    assert segunda["numeros"]["fijo"] != numero_viejo


@pytest.mark.db
def test_el_campo_cifrado_se_dice_que_no_sale(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Quien publica es quien tiene que enterarse, no el integrador tres semanas
    después."""
    from services.metadata import contrato_rpc as cr

    salida = cr.sincronizar(
        uow,
        objeto="cuenta",
        campos=[{"clave": "nombre", "tipo": "texto"}, {"clave": "iban", "tipo": "cifrado"}],
    )
    assert salida["campos_que_no_salen"][0]["clave"] == "iban"
    assert "iban" not in salida["numeros"]
