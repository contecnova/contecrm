"""Conversación omnicanal (CRM-04.02.01, CRM-04.02.02, CRM-04.03.02.03).

Lo que se prueba es lo que separa un servicio de atención que funciona de uno que
enfada: que no se abran seis casos por seis correos, que un bucle de respuestas
automáticas no tumbe el canal, que cambiar de canal no pierda el hilo y que una
macro no mande «Hola {contacto.nombre}».
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, LimiteExcedido, NoAutenticado, NoEncontrado

from services.service import omnicanal as omni
from services.service import servicio as svc


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def canal(db: Any, tenant_id: UUID) -> tuple[Any, str]:
    return omni.crear_canal(
        db,
        tenant_id=tenant_id,
        clave="soporte",
        nombre="Soporte por correo",
        tipo="correo",
        mapeo={"asunto": "subject", "cuerpo": "body"},
        fijos={"linea": "soporte"},
        campo_trampa="web_site",
        direccion_propia="soporte@nosotros.com",
    )


def _entrada(**kw: Any) -> dict[str, Any]:
    base = {"subject": "No arranca", "body": "Buenos días…", "remitente": "ana@cliente.com"}
    base.update(kw)
    return base


# ── El canal (CRM-04.02.01.01, .02, .04, .07) ─────────────────────────────


@pytest.mark.db
def test_el_secreto_no_se_guarda_en_claro(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any
) -> None:
    """Una fuga de la base no puede llevar dentro las claves de los canales de
    todos los tenants."""
    fila, secreto = canal
    assert secreto not in fila.secreto_hash
    assert len(fila.secreto_hash) == 64


@pytest.mark.db
def test_una_clave_mala_y_un_canal_inexistente_dan_el_mismo_error(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    """Distinguirlos convertiría el endpoint en un comprobador de qué canales
    tiene cada tenant."""
    errores = []
    for clave, secreto in (("soporte", "mala"), ("no_existe", "loquesea")):
        with pytest.raises(NoAutenticado) as e:
            omni.recibir(uow, canal_clave=clave, secreto=secreto, entrada=_entrada())
        errores.append(e.value.error_code)
    assert errores[0] == errores[1] == "service.canal_no_autorizado"


@pytest.mark.db
def test_la_trampa_descarta_con_exito_aparente(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    """Devolver un error le dice al robot qué tiene que cambiar para la
    próxima."""
    fila, secreto = canal
    salida = omni.recibir(
        uow, canal_clave="soporte", secreto=secreto, entrada=_entrada(web_site="spam")
    )
    assert salida["aceptado"] is True
    assert salida["descartado"] == "trampa"
    assert salida["caso_id"] is None


@pytest.mark.db
def test_los_valores_fijos_los_pone_el_canal(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    """Si viniesen en la petición, quien escribe podría abrir todos sus casos
    como críticos."""
    _, secreto = canal
    salida = omni.recibir(
        uow, canal_clave="soporte", secreto=secreto, entrada=_entrada(prioridad="critica")
    )
    caso = svc.exigir_caso(db, UUID(salida["caso_id"]))
    assert caso.linea == "soporte"
    assert caso.prioridad == "media"


# ── Anti-bucle (CRM-04.02.01.01) ──────────────────────────────────────────


@pytest.mark.parametrize(
    "cabeceras",
    [
        {"Auto-Submitted": "auto-replied"},
        {"Precedence": "bulk"},
        {"X-Autoreply": "yes"},
        {"List-Id": "<clientes.ejemplo.com>"},
    ],
)
def test_una_respuesta_automatica_se_reconoce(cabeceras: dict[str, str]) -> None:
    """Nuestra respuesta automática dispara el «estoy de vacaciones» del cliente,
    que abre un caso, que dispara la nuestra, y así toda la noche."""
    automatico, motivo = omni.es_automatico(cabeceras)
    assert automatico is True and motivo


def test_un_correo_normal_no_se_toma_por_automatico() -> None:
    assert omni.es_automatico({"Auto-Submitted": "no", "Subject": "Ayuda"})[0] is False


@pytest.mark.db
def test_el_buzon_no_se_contesta_a_si_mismo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    """Un mensaje que viene de nuestra propia dirección es nuestra respuesta
    rebotando; sin esto el buzón se contesta indefinidamente."""
    _, secreto = canal
    salida = omni.recibir(
        uow,
        canal_clave="soporte",
        secreto=secreto,
        entrada=_entrada(remitente="soporte@nosotros.com"),
    )
    assert salida["descartado"] == "propio"


@pytest.mark.db
def test_el_antibucle_va_antes_del_tope(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    """Un bucle de respuestas automáticas agota el tope en minutos y dejaría
    fuera a los clientes de verdad."""
    fila, secreto = canal
    fila.max_por_hora = 1
    db.flush()
    omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=_entrada())
    db.flush()
    # El tope está agotado, pero un automático se descarta antes de mirarlo.
    salida = omni.recibir(
        uow,
        canal_clave="soporte",
        secreto=secreto,
        entrada=_entrada(remitente="otro@cliente.com"),
        cabeceras={"Auto-Submitted": "auto-generated"},
    )
    assert salida["descartado"] == "automatico"


@pytest.mark.db
def test_pasado_el_tope_se_frena(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    fila, secreto = canal
    fila.max_por_hora = 1
    db.flush()
    omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=_entrada())
    db.flush()
    with pytest.raises(LimiteExcedido):
        omni.recibir(
            uow,
            canal_clave="soporte",
            secreto=secreto,
            entrada=_entrada(remitente="otro@cliente.com"),
        )


# ── Hilo e idempotencia ───────────────────────────────────────────────────


def test_el_hilo_sale_de_la_ultima_referencia() -> None:
    """Coger la primera colgaría toda la conversación del mensaje original y
    perdería las ramas."""
    assert omni.hilo_de({"References": "<a@x> <b@x> <c@x>"}) == "<c@x>"
    assert omni.hilo_de({"In-Reply-To": "<b@x>", "References": "<a@x>"}) == "<b@x>"
    assert omni.hilo_de({}) is None


@pytest.mark.db
def test_un_reintento_de_la_pasarela_no_duplica(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    """Las pasarelas reintentan, y sin esto cada reintento abriría un caso."""
    _, secreto = canal
    entrada = _entrada(id_externo="<msg-1@cliente.com>")
    una = omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=entrada)
    db.flush()
    otra = omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=entrada)
    assert otra["duplicado"] is True
    assert otra["conversacion_id"] == una["conversacion_id"]


@pytest.mark.db
def test_seis_correos_no_son_seis_casos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    """Si lo fueran, el cliente recibiría seis respuestas distintas de seis
    personas."""
    _, secreto = canal
    casos = set()
    for i in range(6):
        salida = omni.recibir(
            uow,
            canal_clave="soporte",
            secreto=secreto,
            entrada=_entrada(id_externo=f"<m{i}@cliente.com>"),
        )
        db.flush()
        casos.add(salida["caso_id"])
    assert len(casos) == 1


@pytest.mark.db
def test_una_respuesta_al_hilo_va_a_su_conversacion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    _, secreto = canal
    una = omni.recibir(
        uow,
        canal_clave="soporte",
        secreto=secreto,
        entrada=_entrada(id_externo="<m1@cliente.com>"),
    )
    db.flush()
    otra = omni.recibir(
        uow,
        canal_clave="soporte",
        secreto=secreto,
        # Remitente distinto a propósito: lo que ata el hilo es la cabecera.
        entrada=_entrada(id_externo="<m2@otro.com>", remitente="jefe@cliente.com"),
        cabeceras={"In-Reply-To": "<m1@cliente.com>"},
    )
    assert otra["conversacion_id"] == una["conversacion_id"]


# ── Conversación unificada (CRM-04.02.02.01, .02) ─────────────────────────


@pytest.mark.db
def test_el_correo_y_el_chat_del_mismo_cliente_son_un_hilo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    """Tres hilos separados hacen que el agente pregunte tres veces lo mismo, que
    es lo que el cliente resume como «no os enteráis de nada»."""
    _, secreto_correo = canal
    _, secreto_chat = omni.crear_canal(
        db,
        tenant_id=tenant_id,
        clave="chat",
        nombre="Chat",
        tipo="chat",
        mapeo={"asunto": "subject", "cuerpo": "body"},
    )
    db.flush()

    a = omni.recibir(uow, canal_clave="soporte", secreto=secreto_correo, entrada=_entrada())
    db.flush()
    b = omni.recibir(uow, canal_clave="chat", secreto=secreto_chat, entrada=_entrada())
    assert a["conversacion_id"] == b["conversacion_id"]


@pytest.mark.db
def test_el_historial_va_por_tiempo_y_no_por_canal(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    """Agrupar por canal reproduce exactamente el problema que esto viene a
    resolver."""
    _, secreto = canal
    salida = omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=_entrada())
    omni.responder(uow, UUID(salida["conversacion_id"]), cuerpo="Lo miramos")
    db.flush()

    hilo = omni.historial(db, tenant_id, identidad="ana@cliente.com")
    assert [m["direccion"] for m in hilo] == ["entrante", "saliente"]


@pytest.mark.db
def test_sin_cliente_no_se_puede_pedir_historial(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    with pytest.raises(ErrorValidacion) as e:
        omni.historial(db, tenant_id)
    assert e.value.error_code == "service.historial_sin_cliente"


@pytest.mark.db
def test_cambiar_de_canal_no_pierde_el_hilo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    """Si abriera una conversación nueva, pasar de chat a correo haría perder
    todo lo hablado y el cliente tendría que explicarse otra vez."""
    _, secreto = canal
    salida = omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=_entrada())
    conversacion_id = UUID(salida["conversacion_id"])
    omni.transferir_canal(uow, conversacion_id, canal="telefono", motivo="lo llamamos")
    db.flush()

    # El agente ve la nota de traslado; el portal del cliente, no.
    assert len(omni.historial(db, tenant_id, identidad="ana@cliente.com")) == 2
    del_cliente = omni.historial(db, tenant_id, identidad="ana@cliente.com", incluir_internos=False)
    assert len(del_cliente) == 1
    from sqlalchemy import select

    from services.service.omnicanal import Conversacion

    conversacion = db.execute(
        select(Conversacion).where(Conversacion.id == conversacion_id)
    ).scalar_one()
    assert conversacion.canal_actual == "telefono"


@pytest.mark.db
def test_un_canal_inventado_no_se_acepta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    _, secreto = canal
    salida = omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=_entrada())
    with pytest.raises(ErrorValidacion):
        omni.transferir_canal(uow, UUID(salida["conversacion_id"]), canal="paloma_mensajera")


# ── Primera respuesta y notas internas ────────────────────────────────────


@pytest.mark.db
def test_una_nota_interna_no_cuenta_como_primera_respuesta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    """Si contaran, el tiempo de primera respuesta saldría siempre magnífico y no
    mediría nada."""
    _, secreto = canal
    salida = omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=_entrada())
    conversacion_id = UUID(salida["conversacion_id"])
    caso = svc.exigir_caso(db, UUID(salida["caso_id"]))

    omni.responder(uow, conversacion_id, cuerpo="ojo con este", interno=True)
    db.flush()
    assert caso.primera_respuesta_at is None

    omni.responder(uow, conversacion_id, cuerpo="Buenos días, lo vemos")
    db.flush()
    assert caso.primera_respuesta_at is not None


# ── Escalado a humano (CRM-04.03.02.03) ───────────────────────────────────


@pytest.mark.db
def test_escalar_traspasa_el_contexto_entero(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    """Escalar diciendo solo «quiere hablar con alguien» hace que el cliente
    repita todo lo que acaba de contarle al bot."""
    _, secreto = canal
    salida = omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=_entrada())
    conversacion_id = UUID(salida["conversacion_id"])
    omni.responder(uow, conversacion_id, cuerpo="¿Has probado a reiniciar?")
    db.flush()

    traspaso = omni.escalar_a_humano(uow, conversacion_id, motivo="el bot no resuelve")
    assert len(traspaso["contexto"]) == 2
    assert traspaso["caso_id"] == salida["caso_id"]


@pytest.mark.db
def test_escalar_exige_motivo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    _, secreto = canal
    salida = omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=_entrada())
    with pytest.raises(ErrorValidacion) as e:
        omni.escalar_a_humano(uow, UUID(salida["conversacion_id"]), motivo="  ")
    assert e.value.error_code == "service.escalado_sin_motivo"


# ── Macros (CRM-04.02.02.04) ──────────────────────────────────────────────


@pytest.fixture
def macro(db: Any, tenant_id: UUID) -> Any:
    fila = omni.Macro(
        tenant_id=tenant_id,
        clave="cerrar_resuelto",
        nombre="Cerrar como resuelto",
        cuerpo="Hola {contacto.nombre}, hemos resuelto tu caso {caso.codigo}.",
        acciones={"cerrar": "resuelto"},
    )
    db.add(fila)
    db.flush()
    return fila


@pytest.mark.db
def test_una_macro_con_variables_sin_resolver_no_se_manda(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, macro: Any, uow: Any
) -> None:
    """Es la diferencia entre una macro que ahorra tiempo y una que manda «Hola
    {contacto.nombre}» a un cliente."""
    _, secreto = canal
    salida = omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=_entrada())
    with pytest.raises(ErrorValidacion) as e:
        omni.aplicar_macro(
            uow, macro_clave="cerrar_resuelto", conversacion_id=UUID(salida["conversacion_id"])
        )
    assert e.value.error_code == "service.macro_variables_sin_resolver"
    assert "contacto.nombre" in e.value.detalle["sin_resolver"]


@pytest.mark.db
def test_la_macro_escribe_y_hace_de_una_vez(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, macro: Any, uow: Any
) -> None:
    """Partida en cuatro clics, la mitad de las veces se queda a medias y el caso
    acaba contestado pero sin clasificar."""
    _, secreto = canal
    salida = omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=_entrada())
    caso = svc.exigir_caso(db, UUID(salida["caso_id"]))

    resultado = omni.aplicar_macro(
        uow,
        macro_clave="cerrar_resuelto",
        conversacion_id=UUID(salida["conversacion_id"]),
        contexto={"contacto": {"nombre": "Ana"}, "caso": {"codigo": caso.codigo}},
    )
    db.flush()
    assert resultado["variables_sin_resolver"] == []
    assert caso.estado == "cerrado"


@pytest.mark.db
def test_una_accion_que_no_se_puede_aplicar_se_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    """Ignorarla haría que la macro pareciera funcionar y el caso quedara a
    medias sin que nadie lo notara."""
    db.add(
        omni.Macro(
            tenant_id=tenant_id,
            clave="rara",
            nombre="Rara",
            cuerpo="Hecho",
            acciones={"campo_que_no_existe": 1},
        )
    )
    db.flush()
    _, secreto = canal
    salida = omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=_entrada())
    resultado = omni.aplicar_macro(
        uow, macro_clave="rara", conversacion_id=UUID(salida["conversacion_id"])
    )
    assert "campo_que_no_existe" in resultado["acciones"]["no_aplicadas"]


@pytest.mark.db
def test_una_macro_que_no_existe_no_manda_nada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, uow: Any
) -> None:
    _, secreto = canal
    salida = omni.recibir(uow, canal_clave="soporte", secreto=secreto, entrada=_entrada())
    with pytest.raises(NoEncontrado):
        omni.aplicar_macro(
            uow, macro_clave="fantasma", conversacion_id=UUID(salida["conversacion_id"])
        )


# ── Consola (CRM-04.02.02.08) ─────────────────────────────────────────────


@pytest.mark.db
def test_la_consola_trae_todo_en_una_llamada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any, macro: Any, uow: Any
) -> None:
    """Una consola que abre seis peticiones para pintar una pantalla tarda lo que
    tarde la más lenta, y el agente lo ve como un producto lento."""
    from services.service import operacion as ope

    agente = uuid4()
    ope.fijar_presencia(db, tenant_id, agente, presencia="disponible")
    caso = svc.abrir_caso(uow, asunto="Mío")
    caso.owner_id = agente
    db.flush()

    salida = omni.consola(db, tenant_id, agente)
    assert salida["agente"]["presencia"] == "disponible"
    assert [c["asunto"] for c in salida["mis_casos"]] == ["Mío"]
    assert salida["macros"][0]["clave"] == "cerrar_resuelto"


@pytest.mark.db
def test_un_canal_duplicado_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, canal: Any
) -> None:
    with pytest.raises(Conflicto):
        omni.crear_canal(db, tenant_id=tenant_id, clave="soporte", nombre="Otro")


# ── La pantalla de la conversación, por HTTP ──────────────────────────────
#
# La pantalla declara la forma de dos respuestas: la de la conversación y la
# del historial del cliente. Un contrato declarado que ninguna prueba pide es
# un contrato que puede dejar de cumplirse sin que falle nada: el servidor deja
# de mandar un campo y la pantalla se queda en blanco.


@pytest.fixture
def cliente_http(db: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings
    from starlette.testclient import TestClient

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.service.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def cabeceras_http(tenant_id: UUID) -> dict[str, str]:
    from datetime import datetime, timezone

    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "agente",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.mark.db
def test_la_pantalla_de_la_conversacion_recibe_lo_que_lee(
    db: Any,
    tenant_id: UUID,
    contexto_tenant: UUID,
    canal: Any,
    uow: Any,
    cliente_http: Any,
    cabeceras_http: dict[str, str],
) -> None:
    """Los campos con los que la pantalla decide qué pintar.

    `identidad_externa` es el que permite traer el historial: sin él la
    pantalla no sabe por quién preguntar y enseña una conversación suelta.
    """
    _, secreto = canal
    salida = omni.recibir(
        uow,
        canal_clave="soporte",
        secreto=secreto,
        entrada=_entrada(id_externo="<para-la-pantalla@cliente.com>"),
    )
    db.flush()

    conversacion_id = salida["conversacion_id"]
    respuesta = cliente_http.get(
        f"/api/v1/conversaciones/{conversacion_id}", headers=cabeceras_http
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    for campo in ("id", "canal_actual", "estado", "identidad_externa"):
        assert campo in cuerpo, f"falta «{campo}»: {sorted(cuerpo)}"


@pytest.mark.db
def test_el_historial_que_pinta_la_pantalla_trae_sus_campos(
    db: Any,
    tenant_id: UUID,
    contexto_tenant: UUID,
    canal: Any,
    uow: Any,
    cliente_http: Any,
    cabeceras_http: dict[str, str],
) -> None:
    """Y **por identidad**, que es como lo pide la pantalla cuando la
    conversación no está ligada a un contacto todavía.

    Sin cliente responde 422 a propósito: traer «los últimos mensajes de
    cualquiera» en una pantalla de atención es enseñarle a un agente lo que ha
    hablado otro con otro.
    """
    _, secreto = canal
    omni.recibir(
        uow,
        canal_clave="soporte",
        secreto=secreto,
        entrada=_entrada(id_externo="<historial@cliente.com>", remitente="ana@cliente.com"),
    )
    db.flush()

    respuesta = cliente_http.get(
        "/api/v1/conversaciones/historial",
        params={"identidad": "ana@cliente.com"},
        headers=cabeceras_http,
    )
    assert respuesta.status_code == 200, respuesta.text
    filas = respuesta.json()
    assert isinstance(filas, list) and filas, filas
    for campo in ("at", "canal", "direccion", "interno", "cuerpo", "conversacion_id"):
        assert campo in filas[0], f"falta «{campo}»: {sorted(filas[0])}"

    sin_cliente = cliente_http.get("/api/v1/conversaciones/historial", headers=cabeceras_http)
    assert sin_cliente.status_code == 422, sin_cliente.text
