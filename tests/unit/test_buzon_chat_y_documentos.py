"""Correo y calendario, chat, plantillas documentales y firma presencial
(CRM-06.01.01.01 a .04, .06 · CRM-06.01.02.09, .13, .14).

Conectar el buzón de la gente tiene dos formas de salir mal, y las dos son peores
que no conectarlo: volcar el buzón entero dentro del CRM, y sincronizar en los
dos sentidos sin regla de conflicto. Las pruebas van detrás de eso, y de las
cuatro cosas que convierten una firma en una rúbrica.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado

from services.integration import buzon as buz
from services.integration import colaboracion as colab


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _buzon(uow: UnidadDeTrabajo, **kw: Any) -> Any:
    base: dict[str, Any] = {
        "usuario_id": uuid4(),
        "perfil": "correo-generico",
        "direccion": "comercial@empresa.com",
    }
    base.update(kw)
    fila = buz.conectar(uow, **base)
    return fila


# ── Buzón: qué entra y qué no (CRM-06.01.01.01) ───────────────────────────


@pytest.mark.db
def test_un_buzon_nace_sin_credencial(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Darlo por conectado antes de que la persona autorice haría que el panel
    dijera que todo va bien mientras no entra nada."""
    fila = _buzon(uow)
    assert fila.estado == "sin_credencial"
    with pytest.raises(ErrorValidacion) as fallo:
        buz.sincronizar(uow, buzon_id=fila.id, elementos=[])
    assert fallo.value.error_code == "buzon.no_conectado"


@pytest.mark.db
def test_un_buzon_que_ni_lee_ni_escribe_no_se_conecta(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        _buzon(uow, entrante=False, saliente=False)
    assert fallo.value.error_code == "buzon.sin_sentido"


@pytest.mark.db
def test_lo_privado_no_entra_nunca_y_se_cuenta(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Si desapareciera sin más, nadie sabría que hubo algo que no se trajo."""
    fila = _buzon(uow)
    buz.marcar_autorizado(uow, buzon_id=fila.id)
    salida = buz.sincronizar(
        uow,
        buzon_id=fila.id,
        elementos=[{"id": "m-1", "privado": True, "participantes": ["cliente@acme.com"]}],
        direcciones_conocidas=["cliente@acme.com"],
    )
    assert salida["privados"] == 1
    assert salida["registrados"] == 0


@pytest.mark.db
def test_lo_que_no_tiene_que_ver_con_el_crm_se_deja_fuera_y_se_explica(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """El usuario ve que «no se sincroniza nada» y tiene que poder saber si es
    que no hay nada o que el criterio lo deja fuera."""
    fila = _buzon(uow)
    buz.marcar_autorizado(uow, buzon_id=fila.id)
    salida = buz.sincronizar(
        uow,
        buzon_id=fila.id,
        elementos=[{"id": "m-2", "participantes": ["desconocido@otra.com"]}],
        direcciones_conocidas=["cliente@acme.com"],
    )
    assert salida["sin_relacion"] == 1
    elemento = uow.db.query(buz.ElementoSincronizado).filter_by(externo_id="m-2").one()
    assert "contacto que falta" in elemento.porque


@pytest.mark.db
def test_el_mismo_elemento_dos_veces_no_se_duplica(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """El calendario manda el mismo evento cada vez que alguien lo toca: sin
    idempotencia, una reunión aparece cuatro veces en la ficha."""
    fila = _buzon(uow, ambito="calendario", criterio="todo")
    buz.marcar_autorizado(uow, buzon_id=fila.id)
    elemento = {"id": "ev-1", "asunto": "Reunión", "version": "v1"}
    buz.sincronizar(uow, buzon_id=fila.id, elementos=[elemento])
    salida = buz.sincronizar(uow, buzon_id=fila.id, elementos=[elemento])
    assert salida["repetidos"] == 1
    assert salida["registrados"] == 0


@pytest.mark.db
def test_si_cambio_en_los_dos_lados_es_conflicto(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Pisar el calendario de alguien es la forma más rápida de que desconecte la
    integración."""
    fila = _buzon(uow, ambito="calendario", criterio="todo")
    buz.marcar_autorizado(uow, buzon_id=fila.id)
    buz.sincronizar(
        uow, buzon_id=fila.id, elementos=[{"id": "ev-2", "asunto": "Reunión", "version": "v1"}]
    )
    guardado = uow.db.query(buz.ElementoSincronizado).filter_by(externo_id="ev-2").one()
    guardado.actividad_id = uuid4()
    uow.db.flush()

    salida = buz.sincronizar(
        uow,
        buzon_id=fila.id,
        elementos=[
            {"id": "ev-2", "asunto": "Reunión movida", "version": "v2", "tocado_en_el_crm": True}
        ],
    )
    assert salida["conflictos"] == 1


@pytest.mark.db
def test_la_marca_no_avanza_si_algo_fallo(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Avanzar con un fallo dentro deja un hueco que no se recupera nunca y que
    nadie nota hasta que falta una reunión."""
    fila = _buzon(uow, criterio="todo")
    buz.marcar_autorizado(uow, buzon_id=fila.id)
    salida = buz.sincronizar(
        uow,
        buzon_id=fila.id,
        elementos=[{"id": "ok-1"}, {"sin_id": True}],
        marca_nueva="delta-2",
    )
    assert salida["errores"] == 1
    assert salida["marca_avanzada"] is False
    assert "no se recupera" in salida["aviso"]
    uow.db.refresh(fila)
    assert fila.marca_incremento == ""


@pytest.mark.db
def test_el_panel_cuenta_lo_que_no_esta_entrando(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Un panel que solo cuente lo sincronizado enseña un número que sube
    mientras tres buzones llevan una semana sin credencial."""
    _buzon(uow)
    salida = buz.panel(uow.db, uow.tenant_id)
    assert salida["sin_credencial"] == 1


# ── Chat corporativo (CRM-06.01.01.03) ────────────────────────────────────


def _canal(uow: UnidadDeTrabajo, **kw: Any) -> Any:
    base: dict[str, Any] = {
        "clave": "ventas",
        "url_entrante": "https://chat.example.com/hook",
        "secreto": "un-secreto-largo",
    }
    base.update(kw)
    return colab.declarar_canal(uow, **base)


@pytest.mark.db
def test_un_canal_sin_secreto_no_se_declara(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Sin firma, «actuar desde el chat» es «actuar desde internet»."""
    with pytest.raises(ErrorValidacion) as fallo:
        _canal(uow, secreto="")
    assert fallo.value.error_code == "chat.sin_secreto"


@pytest.mark.db
def test_sin_declarar_ordenes_el_canal_solo_consulta(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es lo menos que puede hacer un canal y lo que menos daño hace si alguien
    se equivoca al declararlo."""
    fila = _canal(uow)
    assert fila.ordenes == ["consultar"]


@pytest.mark.db
def test_una_firma_que_no_cuadra_se_rechaza(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    _canal(uow)
    with pytest.raises(NoAutenticado):
        colab.atender(uow, clave="ventas", cuerpo=b"{}", firma="lo-que-sea", orden="consultar")


@pytest.mark.db
def test_una_orden_no_admitida_se_explica_en_vez_de_fallar(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Decirlo así evita que alguien conceda todas las órdenes «para que
    funcione»."""
    _canal(uow)
    cuerpo = b'{"x":1}'
    firma = hmac.new(b"un-secreto-largo", cuerpo, hashlib.sha256).hexdigest()
    salida = colab.atender(uow, clave="ventas", cuerpo=cuerpo, firma=firma, orden="cambiar_estado")
    assert salida["hecho"] is False
    assert "no admite la orden" in salida["porque"]


@pytest.mark.db
def test_lo_que_escribe_sale_como_comando_y_dice_pedido(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Venir de un chat no da permisos distintos: lo decide el servicio dueño."""
    _canal(uow, ordenes=["consultar", "registrar_nota"])
    cuerpo = b'{"x":1}'
    firma = hmac.new(b"un-secreto-largo", cuerpo, hashlib.sha256).hexdigest()
    salida = colab.atender(
        uow,
        clave="ventas",
        cuerpo=cuerpo,
        firma=firma,
        orden="registrar_nota",
        objeto="oportunidad",
        objeto_id=uuid4(),
        texto="Hablado con el cliente",
    )
    assert salida["estado"] == "pedido"


@pytest.mark.db
def test_un_aviso_sobre_un_registro_exige_enlace(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Un mensaje que dice «oportunidad ganada» sin decir cuál obliga a buscarla,
    y a la tercera vez se deja de mirar el canal."""
    _canal(uow)
    with pytest.raises(ErrorValidacion) as fallo:
        colab.aviso(
            uow.db,
            uow.tenant_id,
            clave="ventas",
            texto="Oportunidad ganada",
            objeto="oportunidad",
            objeto_id=uuid4(),
        )
    assert fallo.value.error_code == "chat.aviso_sin_enlace"


# ── Generación documental (CRM-06.01.01.06) ───────────────────────────────


@pytest.mark.db
def test_no_se_genera_con_marcadores_sin_dato(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un documento con `{{importe}}` sin sustituir llega al cliente igual que
    uno bueno: nadie relee un contrato de doce páginas antes de mandarlo."""
    from crmcore.documental.plantillas import generar, guardar_plantilla

    guardar_plantilla(
        db,
        tenant_id=tenant_id,
        clave="propuesta",
        cuerpo="Para {{cliente.nombre}} por {{importe}} euros",
    )
    with pytest.raises(Conflicto) as fallo:
        generar(db, tenant_id=tenant_id, clave="propuesta", datos={"cliente": {"nombre": "Acme"}})
    assert fallo.value.error_code == "plantilla.datos_incompletos"


@pytest.mark.db
def test_una_clausula_bloqueada_que_desaparece_al_rellenar_se_caza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El caso real es un marcador dentro de la cláusula que la rompe al
    rellenarse — por eso se comprueba DESPUÉS de sustituir."""
    from crmcore.documental.plantillas import generar, guardar_plantilla

    guardar_plantilla(
        db,
        tenant_id=tenant_id,
        clave="contrato",
        tipo="contrato",
        cuerpo="Jurisdicción de {{ciudad}}. Resto del contrato.",
        clausulas_bloqueadas=["Jurisdicción de Barcelona."],
    )
    with pytest.raises(Conflicto) as fallo:
        generar(db, tenant_id=tenant_id, clave="contrato", datos={"ciudad": "Madrid"})
    assert fallo.value.error_code == "plantilla.clausula_perdida"


@pytest.mark.db
def test_cada_cambio_de_plantilla_es_una_version_nueva(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Cuando una cláusula resulta estar mal, la pregunta es a quién se le mandó."""
    from crmcore.documental.plantillas import guardar_plantilla

    primera = guardar_plantilla(db, tenant_id=tenant_id, clave="acta", cuerpo="uno")
    segunda = guardar_plantilla(db, tenant_id=tenant_id, clave="acta", cuerpo="dos")
    assert (primera.version, segunda.version) == (1, 2)
    assert primera.vigente is False


@pytest.mark.db
def test_se_puede_saber_a_quien_se_le_mando_una_version(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.documental.plantillas import (
        anotar_generado,
        guardar_plantilla,
        quien_recibio,
    )

    guardar_plantilla(db, tenant_id=tenant_id, clave="carta", tipo="carta", cuerpo="hola")
    anotar_generado(
        db,
        tenant_id=tenant_id,
        clave="carta",
        version=1,
        documento_id="doc-1",
        objeto="cuenta",
        objeto_id=uuid4(),
    )
    salida = quien_recibio(db, tenant_id, clave="carta", version=1)
    assert salida["cuantos"] == 1


# ── Firma presencial (CRM-06.01.02.09) ────────────────────────────────────


def _trazo(puntos: int = 20, paso: int = 40) -> dict[str, Any]:
    return {"puntos": [{"x": i, "y": i, "t": i * paso, "p": 0.5} for i in range(puntos)]}


@pytest.mark.db
def test_sin_consentimiento_no_se_guarda_el_trazo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El trazo es dato biométrico del artículo 9: la firma se puede hacer igual
    sin capturarlo."""
    from crmcore.documental.firma_presencial import capturar

    with pytest.raises(ErrorValidacion) as fallo:
        capturar(
            db,
            tenant_id=tenant_id,
            trazo=_trazo(),
            contenido_firmado=b"contrato",
            firmante_nombre="Ana",
            consentimiento_biometrico=False,
            texto_consentimiento="Acepto",
            testigo_id=uuid4(),
        )
    assert fallo.value.error_code == "firma_presencial.sin_consentimiento"


@pytest.mark.db
def test_un_toque_accidental_no_es_una_firma(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Produce una rúbrica válida a los ojos del sistema, y eso es peor que no
    capturar nada."""
    from crmcore.documental.firma_presencial import capturar

    with pytest.raises(ErrorValidacion) as fallo:
        capturar(
            db,
            tenant_id=tenant_id,
            trazo=_trazo(puntos=3, paso=10),
            contenido_firmado=b"contrato",
            firmante_nombre="Ana",
            consentimiento_biometrico=True,
            texto_consentimiento="Acepto que se registre mi firma",
            testigo_id=uuid4(),
        )
    assert fallo.value.error_code == "firma_presencial.trazo_insuficiente"


@pytest.mark.db
def test_sin_testigo_es_una_rubrica_y_no_una_firma(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """En presencial la identificación la hace una persona mirando un documento."""
    from crmcore.documental.firma_presencial import capturar

    with pytest.raises(ErrorValidacion) as fallo:
        capturar(
            db,
            tenant_id=tenant_id,
            trazo=_trazo(),
            contenido_firmado=b"contrato",
            firmante_nombre="Ana",
            consentimiento_biometrico=True,
            texto_consentimiento="Acepto",
            testigo_id=None,
        )
    assert fallo.value.error_code == "firma_presencial.sin_testigo"


@pytest.mark.db
def test_si_el_documento_cambia_la_firma_no_lo_ampara(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La única pregunta que importa cuando alguien dice «yo no firmé eso» no es
    si la rúbrica se parece: es si el documento es el mismo."""
    from crmcore.documental.firma_presencial import capturar, comprobar

    fila = capturar(
        db,
        tenant_id=tenant_id,
        trazo=_trazo(),
        contenido_firmado=b"contrato original",
        firmante_nombre="Ana",
        consentimiento_biometrico=True,
        texto_consentimiento="Acepto que se registre mi firma",
        testigo_id=uuid4(),
        objeto="contrato",
        objeto_id=uuid4(),
    )
    igual = comprobar(db, tenant_id, firma_id=fila.id, contenido=b"contrato original")
    distinto = comprobar(db, tenant_id, firma_id=fila.id, contenido=b"contrato original.")
    assert igual["cuadra"] is True
    assert distinto["cuadra"] is False
    assert "NO es el que se firmó" in distinto["que_significa"]


@pytest.mark.db
def test_el_trazo_no_sale_en_los_listados(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Devolverlo en una consulta de rutina reparte biometría por los registros
    de acceso, las cachés y los navegadores de quien mire la ficha."""
    from crmcore.documental.firma_presencial import capturar, firmas_de

    objeto_id = uuid4()
    capturar(
        db,
        tenant_id=tenant_id,
        trazo=_trazo(),
        contenido_firmado=b"x",
        firmante_nombre="Ana",
        consentimiento_biometrico=True,
        texto_consentimiento="Acepto",
        testigo_id=uuid4(),
        objeto="contrato",
        objeto_id=objeto_id,
    )
    filas = firmas_de(db, tenant_id, objeto="contrato", objeto_id=objeto_id)
    assert filas[0]["trazo"].startswith("no se devuelve")
