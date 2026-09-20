"""El repartidor: que un aviso salga de verdad (CRM-06.02.01.02).

Las notificaciones se creaban, se agrupaban, respetaban la franja de silencio y
se leían en la bandeja. **No salía ninguna.** Y el ejecutor de automatizaciones
emitía un evento cuyo comentario decía que «el consumidor de identidad ya sabe
traducir esto» — no existía, así que la acción `notificar` de una regla no
producía ningún aviso.

Estas pruebas defienden las dos mitades: que el consumidor recoge el evento, y
que el repartidor entrega lo que hay en la cola y **anota qué pasó**. Lo segundo
importa tanto como lo primero: «no me llegó el aviso» es la incidencia más
frecuente de un CRM y la más difícil de contestar sin un registro de intentos.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.datos.seguimiento import Notificacion, notificar, seguir
from crmcore.notificaciones import Destino, Mensaje, Resultado
from crmcore.notificaciones.entrega import EntregaNotificacion, anotar_resultado, historial

from services.identity.modelos import Membresia, Usuario


class _TransporteFalso:
    """Un transporte que anota lo que le mandan y contesta lo que se le diga."""

    def __init__(self, canal: str, resultado: Resultado) -> None:
        self.canal = canal
        self.resultado = resultado
        self.enviados: list[tuple[Destino, Mensaje]] = []

    def entregar(self, destino: Destino, mensaje: Mensaje, config: dict[str, Any]) -> Resultado:
        self.enviados.append((destino, mensaje))
        return self.resultado


@pytest.fixture
def transporte_correo() -> Any:
    """Sustituye el transporte de correo por uno de mentira.

    Se toca el registro directamente y se restaura al salir: una prueba que
    dejara el falso puesto haría que las siguientes «entregaran» sin mandar
    nada y pasaran por el motivo equivocado.
    """
    from crmcore.notificaciones import base

    previo = base._TRANSPORTES.get("correo")
    falso = _TransporteFalso("correo", Resultado(True, "entregado"))
    base._TRANSPORTES["correo"] = falso
    yield falso
    if previo is None:
        base._TRANSPORTES.pop("correo", None)
    else:
        base._TRANSPORTES["correo"] = previo


def _persona(db: Any, tenant_id: UUID, *, email: str = "ana@ejemplo.test") -> UUID:
    usuario = Usuario(email=email, nombre="Ana", activo=True)
    db.add(usuario)
    db.flush()
    db.add(
        Membresia(
            tenant_id=tenant_id,
            usuario_id=usuario.id,
            activa=True,
            atributos={"telefono": "+34600000000"},
        )
    )
    db.flush()
    return usuario.id


def _aviso(db: Any, tenant_id: UUID, usuario_id: UUID, canales: tuple[str, ...]) -> Notificacion:
    objeto_id = uuid4()
    seguir(
        db,
        tenant_id=tenant_id,
        usuario_id=usuario_id,
        objeto_tipo="cuenta",
        objeto_id=objeto_id,
        motivo="propietario",
    )
    creadas = notificar(
        db,
        tenant_id=tenant_id,
        tipo="prueba.cosa",
        titulo="Ha pasado algo",
        cuerpo="Con detalle",
        objeto_tipo="cuenta",
        objeto_id=objeto_id,
        canales_por_defecto=canales,
    )
    db.flush()
    return creadas[0]


# ── Entrega ───────────────────────────────────────────────────────────────


@pytest.mark.db
def test_un_aviso_pendiente_sale_por_su_canal(
    transporte_correo: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La prueba que justifica todo el módulo: antes no salía ninguno."""
    from services.identity.reparto import repartir_lote

    usuario_id = _persona(db, tenant_id)
    aviso = _aviso(db, tenant_id, usuario_id, ("correo",))
    db.commit()

    cuenta = repartir_lote(db)

    assert cuenta["entregadas"] == 1
    destino, mensaje = transporte_correo.enviados[0]
    assert destino.direccion == "ana@ejemplo.test"
    assert mensaje.titulo == "Ha pasado algo"
    db.expunge_all()
    assert db.get(Notificacion, aviso.id).entregada_at is not None


@pytest.mark.db
def test_lo_que_solo_va_por_la_bandeja_no_se_entrega(
    transporte_correo: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """`app` se lee de la tabla: «entregarla» sería escribir en la fila que ya
    está escrita, y procesarlas haría que el repartidor tocara el 90 % de las
    filas para no hacer nada."""
    from services.identity.reparto import repartir_lote

    usuario_id = _persona(db, tenant_id)
    _aviso(db, tenant_id, usuario_id, ("app",))
    db.commit()

    assert repartir_lote(db)["nuevas"] == 0
    assert transporte_correo.enviados == []


@pytest.mark.db
def test_cada_intento_queda_registrado_con_su_direccion(
    transporte_correo: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es la respuesta a «no me llegó». Sin esto se acaba mirando el log del
    servidor de correo de otra empresa."""
    from services.identity.reparto import repartir_lote

    usuario_id = _persona(db, tenant_id)
    aviso = _aviso(db, tenant_id, usuario_id, ("correo",))
    db.commit()
    repartir_lote(db)

    intentos = historial(db, aviso.id)
    assert len(intentos) == 1
    assert intentos[0]["canal"] == "correo"
    assert intentos[0]["estado"] == "entregada"
    assert intentos[0]["direccion"] == "ana@ejemplo.test"


@pytest.mark.db
def test_un_aviso_por_dos_canales_deja_dos_fichas(
    transporte_correo: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una fila por canal, no una por notificación: un aviso puede entregarse
    por uno y fallar por el otro, y una sola fila obligaría a elegir cuál de las
    dos verdades se guarda."""
    from crmcore.notificaciones import base

    from services.identity.reparto import repartir_lote

    base._TRANSPORTES["sms"] = _TransporteFalso("sms", Resultado(False, "caído", reintentar=True))
    try:
        usuario_id = _persona(db, tenant_id)
        aviso = _aviso(db, tenant_id, usuario_id, ("correo", "sms"))
        db.commit()
        repartir_lote(db)
    finally:
        base._TRANSPORTES.pop("sms", None)

    por_canal = {i["canal"]: i["estado"] for i in historial(db, aviso.id)}
    assert por_canal == {"correo": "entregada", "sms": "pendiente"}


# ── Destinatarios ─────────────────────────────────────────────────────────


@pytest.mark.db
def test_a_quien_ya_no_esta_en_el_tenant_no_se_le_manda(
    transporte_correo: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que impide que alguien que se fue de la empresa siga recibiendo
    movimientos de clientes en su correo personal."""
    from services.identity.reparto import repartir_lote

    usuario_id = _persona(db, tenant_id)
    aviso = _aviso(db, tenant_id, usuario_id, ("correo",))
    membresia = db.query(Membresia).filter_by(usuario_id=usuario_id).one()
    membresia.activa = False
    db.commit()

    repartir_lote(db)

    assert transporte_correo.enviados == []
    intento = historial(db, aviso.id)[0]
    assert intento["estado"] == "descartada"
    assert "ya no está activo" in intento["ultimo_error"]


@pytest.mark.db
def test_el_sms_sale_del_telefono_de_la_membresia(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El correo es la identidad de la persona; el teléfono lo guarda el tenant,
    así que sale de la membresía y no de la ficha global."""
    from crmcore.notificaciones import base

    from services.identity.reparto import repartir_lote

    falso = _TransporteFalso("sms", Resultado(True, "ok"))
    base._TRANSPORTES["sms"] = falso
    try:
        usuario_id = _persona(db, tenant_id)
        _aviso(db, tenant_id, usuario_id, ("sms",))
        db.commit()
        repartir_lote(db)
    finally:
        base._TRANSPORTES.pop("sms", None)

    assert falso.enviados[0][0].direccion == "+34600000000"


# ── Reintentos y descarte ─────────────────────────────────────────────────


@pytest.mark.db
def test_un_fallo_transitorio_se_reintenta_con_espera_creciente(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Lineal se queda corta con un proveedor caído una hora; exponencial se
    pasa —al quinto intento serían dieciséis horas— para un aviso que deja de
    tener valor pasada la tarde."""
    from datetime import datetime, timezone

    fila = EntregaNotificacion(
        tenant_id=tenant_id, notificacion_id=uuid4(), usuario_id=uuid4(), canal="correo"
    )
    db.add(fila)
    db.flush()

    esperas = []
    for _ in range(3):
        anotar_resultado(db, fila, Resultado(False, "timeout", reintentar=True))
        esperas.append((fila.proximo_intento_at - datetime.now(timezone.utc)).total_seconds())

    assert fila.estado == "pendiente"
    # 1 min, 4 min, 9 min: crece, y crece con el cuadrado.
    assert esperas[0] < esperas[1] < esperas[2]
    assert esperas[2] / esperas[0] == pytest.approx(9, rel=0.1)


@pytest.mark.db
def test_un_fallo_definitivo_no_se_reintenta(db: Any, tenant_id: UUID) -> None:
    """Reintentar cada cinco minutos un envío a alguien que no tiene teléfono
    llena la cola de algo que nunca va a salir."""
    fila = EntregaNotificacion(
        tenant_id=tenant_id, notificacion_id=uuid4(), usuario_id=uuid4(), canal="sms"
    )
    db.add(fila)
    db.flush()

    anotar_resultado(db, fila, Resultado(False, "sin teléfono", reintentar=False))
    assert fila.estado == "descartada"
    assert fila.proximo_intento_at is None


@pytest.mark.db
def test_tras_agotar_los_intentos_se_marca_fallida(db: Any, tenant_id: UUID) -> None:
    """Un proveedor caído tres días no puede costar tres días de reintentos."""
    from crmcore.config import get_settings

    fila = EntregaNotificacion(
        tenant_id=tenant_id, notificacion_id=uuid4(), usuario_id=uuid4(), canal="correo"
    )
    db.add(fila)
    db.flush()

    for _ in range(get_settings().notificacion_max_intentos):
        anotar_resultado(db, fila, Resultado(False, "caído", reintentar=True))

    assert fila.estado == "fallida"
    assert fila.proximo_intento_at is None


# ── El consumidor que faltaba ─────────────────────────────────────────────


@pytest.mark.db
def test_el_aviso_de_una_automatizacion_produce_una_notificacion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El ejecutor emitía `automatizacion.aviso` y **nadie lo consumía**.

    Su comentario decía que «el consumidor de identidad ya sabe traducir esto».
    No existía: la acción `notificar` de una regla se guardaba, se validaba, se
    simulaba, se ejecutaba sin error y no producía ningún aviso — el mismo modo
    de fallo por el que `enviar_correo` se había retirado, solo que en este no
    se había visto.
    """
    from services.identity.notificaciones import consumir_evento

    usuario_id = _persona(db, tenant_id)
    objeto_id = uuid4()
    db.commit()

    asyncio.run(
        consumir_evento(
            {
                "tipo": "automatizacion.aviso",
                "tenant_id": str(tenant_id),
                "data": {
                    "titulo": "Revisa este cliente",
                    "cuerpo": "Lleva 90 días sin actividad",
                    "objeto_tipo": "cuenta",
                    "objeto_id": str(objeto_id),
                    "menciones": [str(usuario_id)],
                },
            }
        )
    )

    db.expunge_all()
    avisos = db.query(Notificacion).filter_by(usuario_id=usuario_id).all()
    assert [a.titulo for a in avisos] == ["Revisa este cliente"]


@pytest.mark.db
def test_enviar_correo_fuerza_el_canal_sobre_la_preferencia(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Quien escribe esa regla quiere que salga un correo —una confirmación de
    pedido, un aviso de vencimiento— y no que salga por donde el destinatario
    prefiera recibir los avisos de movimiento."""
    from crmcore.datos.seguimiento import PreferenciaNotificacion

    from services.identity.notificaciones import consumir_evento

    usuario_id = _persona(db, tenant_id)
    db.add(
        PreferenciaNotificacion(
            tenant_id=tenant_id,
            usuario_id=usuario_id,
            tipo="automatizacion.aviso",
            canales=["app"],
        )
    )
    db.commit()

    asyncio.run(
        consumir_evento(
            {
                "tipo": "automatizacion.aviso",
                "tenant_id": str(tenant_id),
                "data": {
                    "titulo": "Tu pedido está confirmado",
                    "objeto_tipo": "cuenta",
                    "objeto_id": str(uuid4()),
                    "menciones": [str(usuario_id)],
                    "canales": ["correo"],
                },
            }
        )
    )

    db.expunge_all()
    aviso = db.query(Notificacion).filter_by(usuario_id=usuario_id).one()
    # Se AÑADE a lo que quería el usuario, no lo sustituye: sigue viéndolo en la
    # bandeja además de recibirlo.
    assert set(aviso.canales) == {"app", "correo"}


@pytest.mark.db
def test_un_aviso_de_automatizacion_sin_titulo_se_descarta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Mandar una línea en blanco es peor que no mandar nada: el destinatario
    abre, no entiende y aprende a ignorar los avisos."""
    from services.identity.notificaciones import consumir_evento

    usuario_id = _persona(db, tenant_id)
    db.commit()

    asyncio.run(
        consumir_evento(
            {
                "tipo": "automatizacion.aviso",
                "tenant_id": str(tenant_id),
                "data": {
                    "objeto_tipo": "cuenta",
                    "objeto_id": str(uuid4()),
                    "menciones": [str(usuario_id)],
                },
            }
        )
    )
    db.expunge_all()
    assert db.query(Notificacion).filter_by(usuario_id=usuario_id).count() == 0


# ── Transportes ───────────────────────────────────────────────────────────


def test_esta_instalacion_tiene_transporte_para_sus_canales() -> None:
    """Un canal declarado sin transporte deja los avisos girando en la cola."""
    from crmcore.notificaciones import transportes_registrados

    import services.identity.transportes  # noqa: F401

    assert {"correo", "sms", "push"} <= set(transportes_registrados())


def test_el_transporte_http_no_lleva_codigo_de_ningun_proveedor() -> None:
    """Con un conector por proveedor, cada cliente con uno distinto es una
    versión del producto que hay que mantener, probar y desplegar."""
    from pathlib import Path

    fuente = (
        Path(__file__).resolve().parents[2] / "packages/crmcore/crmcore/notificaciones/http.py"
    ).read_text(encoding="utf-8")
    for proveedor in ("twilio", "sendgrid", "firebase", "vonage", "messagebird", "sns"):
        assert proveedor not in fuente.lower(), f"aparece «{proveedor}»"


def test_el_sms_se_recorta_a_lo_que_cabe_en_uno() -> None:
    """Mandar el cuerpo entero produce tres mensajes cortados a mitad de
    palabra, que es peor que uno resumido."""
    from services.identity.reparto import _mensaje

    class _Falsa:
        titulo = "Aviso"
        cuerpo = "x" * 400
        tipo = "prueba"
        prioridad = "normal"
        objeto_tipo = None
        objeto_id = None
        datos: dict[str, Any] = {}
        agrupadas = 1

    mensaje = _mensaje(None, _Falsa(), "sms")
    assert len(mensaje.cuerpo) <= 160
    assert mensaje.titulo == ""
