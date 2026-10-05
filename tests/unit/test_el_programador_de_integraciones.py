"""Lo que hace que una integración se ejecute sola (`CRM-00.03.04.02`, `.05`, `.06`).

Medido el 05-10-2026: el conector declarativo estaba completo —paginación,
OAuth2, mapeo de campos, guard de URL— y lo disparaba **una sola ruta, a mano**.
Una integración que hay que ejecutar pulsando un botón cada mañana no es una
integración: es una pantalla. Y como no corría nada en bucle, las decisiones que
gobiernan una sincronización quedaron escritas, probadas y **sin que las llamara
nadie**: cuándo avanza la marca, cómo se reintenta cuando el proveedor corta, a
qué ritmo se trae la primera carga.

Lo mismo valía para los cinco transportes heredados —soap, sftp, fichero, edi,
amqp—: registrados y ejecutados por nadie.

Estas pruebas van detrás de las cuatro cosas que se pierden cuando esto falla, y
ninguna da un error rojo:

  * la marca que avanza con un fallo dentro y deja un hueco que no se recupera,
  * el reintento que ignora lo que dijo el proveedor y acaba con la cuota
    cortada para todos los clientes,
  * el registro que entra dos veces porque el origen lo reenvía,
  * y la operación que lleva tres semanas fallando sin salir en ninguna pantalla.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorDependencia, ErrorValidacion

from services.integration import programador as prg
from services.integration import transportes_legado as legado
from services.integration.modelos import Conexion, Operacion, RegistroRecibido

AHORA = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _conexion(
    uow: UnidadDeTrabajo, *, protocolo: str = "rest", config: dict | None = None
) -> Conexion:
    fila = Conexion(
        tenant_id=uow.tenant_id,
        nombre=f"ERP {uuid4().hex[:6]}",
        protocolo=protocolo,
        config=config or {"url_base": "https://erp.cliente.com"},
        activa=True,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _operacion(uow: UnidadDeTrabajo, conexion: Conexion, **kw: Any) -> Operacion:
    fila = Operacion(
        tenant_id=uow.tenant_id,
        conexion_id=conexion.id,
        clave=kw.pop("clave", "clientes"),
        nombre="Leer clientes",
        definicion=kw.pop("definicion", {}),
        **kw,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


# ── La cadencia es de la operación, y tiene suelo ─────────────────────────


def test_una_cadencia_por_debajo_del_suelo_se_rechaza_al_configurarla(
    uow: UnidadDeTrabajo,
) -> None:
    """Y se rechaza aquí, no al ejecutar.

    Aplicarla en silencio dejaría una pantalla que dice «cada minuto» y un
    sistema que hace otra cosa. Y por debajo del suelo el proveedor acaba
    cortando la cuota — a todos los clientes, no sólo al que se pasó.
    """
    operacion = _operacion(uow, _conexion(uow))
    with pytest.raises(ErrorValidacion) as fallo:
        prg.programar(uow, operacion.id, cada_minutos=1)
    assert fallo.value.error_code == "integracion.cadencia_demasiado_corta"


def test_la_primera_vuelta_sale_ya_y_no_dentro_de_un_ciclo(uow: UnidadDeTrabajo) -> None:
    """Quien acaba de configurarla quiere ver si funciona, no enterarse mañana
    de que la ruta estaba mal escrita."""
    operacion = _operacion(uow, _conexion(uow))
    salida = prg.programar(uow, operacion.id, cada_minutos=60)
    assert salida["proxima_at"] is not None
    assert operacion.proxima_at is not None


def test_cero_minutos_es_solo_a_mano_y_no_entra_en_la_cola(uow: UnidadDeTrabajo) -> None:
    """Es el comportamiento que tenían todas antes, y por eso es el de serie:
    nadie se encuentra una integración ejecutándose sola sin haberlo pedido."""
    operacion = _operacion(uow, _conexion(uow))
    prg.programar(uow, operacion.id, cada_minutos=0)
    assert operacion.proxima_at is None
    assert prg.pendientes(uow.db, uow.tenant_id) == []


def test_una_operacion_en_reposo_no_se_ejecuta_aunque_le_tocara(uow: UnidadDeTrabajo) -> None:
    """El proveedor dijo cuánto esperar y se le hace caso.

    Reintentar antes gasta cuota para que vuelva a decir que no, y de paso
    parece un ataque.
    """
    conexion = _conexion(uow)
    operacion = _operacion(uow, conexion, cada_minutos=10)
    operacion.proxima_at = AHORA - timedelta(minutes=1)
    operacion.pausada_hasta = AHORA + timedelta(minutes=30)
    uow.db.flush()
    assert prg.pendientes(uow.db, uow.tenant_id, ahora=AHORA) == []


def test_lo_vencido_sale_por_orden_de_antiguedad(uow: UnidadDeTrabajo) -> None:
    """Con tope por vuelta, el orden decide quién se queda fuera **siempre**.

    Por fecha, el que se quedó fuera es el siguiente en entrar; al azar, hay
    operaciones que no se ejecutan nunca y nadie entiende por qué.
    """
    conexion = _conexion(uow)
    vieja = _operacion(uow, conexion, clave="vieja", cada_minutos=10)
    nueva = _operacion(uow, conexion, clave="nueva", cada_minutos=10)
    vieja.proxima_at = AHORA - timedelta(hours=3)
    nueva.proxima_at = AHORA - timedelta(minutes=1)
    uow.db.flush()
    assert [o.clave for o in prg.pendientes(uow.db, uow.tenant_id, ahora=AHORA)] == [
        "vieja",
        "nueva",
    ]


# ── Lo que entra aterriza, y no entra dos veces ───────────────────────────


def test_el_mismo_registro_dos_veces_no_se_duplica(uow: UnidadDeTrabajo) -> None:
    """El origen reenvía: un ERP marca el pedido como modificado cada vez que
    alguien lo toca, y sin clave externa el mismo pedido entra cuatro veces."""
    operacion = _operacion(uow, _conexion(uow))
    primera = prg._aterrizar(uow, operacion, [{"id_externo": "C-1", "nombre": "Ana"}])
    segunda = prg._aterrizar(uow, operacion, [{"id_externo": "C-1", "nombre": "Ana"}])
    assert primera["nuevos"] == 1
    assert segunda["nuevos"] == 0 and segunda["repetidos"] == 1


def test_un_registro_sin_identificador_no_se_inventa_uno(uow: UnidadDeTrabajo) -> None:
    """Inventarlo lo duplicaría en cada vuelta; descartarlo en silencio haría
    que faltaran filas sin que nadie supiera por qué. Se cuenta aparte."""
    operacion = _operacion(uow, _conexion(uow))
    salida = prg._aterrizar(uow, operacion, [{"nombre": "Sin id"}, {"id_externo": "C-2"}])
    assert salida == {"nuevos": 1, "repetidos": 0, "sin_identificador": 1}


def test_el_mismo_identificador_repetido_dentro_de_la_misma_tanda_entra_una_vez(
    uow: UnidadDeTrabajo,
) -> None:
    """La página 2 de una API que se pagina mal repite filas de la página 1. Sin
    esto, la primera vuelta ya revienta contra la clave única."""
    operacion = _operacion(uow, _conexion(uow))
    salida = prg._aterrizar(uow, operacion, [{"id_externo": "C-3"}, {"id_externo": "C-3"}])
    assert salida["nuevos"] == 1 and salida["repetidos"] == 1


# ── La vuelta entera ──────────────────────────────────────────────────────


def _responde(monkeypatch: pytest.MonkeyPatch, salida: Any) -> None:
    def _falso(conexion: Any, operacion: Any, parametros: Any, secretos: Any) -> Any:
        if isinstance(salida, Exception):
            raise salida
        return salida

    monkeypatch.setattr(prg, "_leer", _falso)


def test_una_vuelta_buena_aterriza_apunta_y_reprograma(
    uow: UnidadDeTrabajo, monkeypatch: pytest.MonkeyPatch
) -> None:
    conexion = _conexion(uow)
    operacion = _operacion(uow, conexion, cada_minutos=30)
    _responde(monkeypatch, {"registros": [{"id_externo": "C-1"}], "paginas": 1, "marca": "t2"})
    salida = prg.ejecutar_programada(uow, operacion)
    assert salida["resultado"] == "ok" and salida["nuevos"] == 1
    assert operacion.marca == "t2", "la marca no avanzó con una vuelta limpia"
    assert operacion.proxima_at is not None and operacion.ultima_at is not None


def test_la_marca_no_avanza_si_algo_se_quedo_fuera(
    uow: UnidadDeTrabajo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Es la prueba que más importa de este fichero.**

    Avanzar la marca con un fallo dentro deja un hueco que no se recupera nunca:
    la vuelta siguiente pide «desde la marca nueva» y lo que se quedó fuera
    queda detrás, para siempre. Y nadie lo nota, porque no falta una pantalla:
    falta un pedido.
    """
    conexion = _conexion(uow)
    operacion = _operacion(uow, conexion, cada_minutos=30)
    operacion.marca = "t1"
    uow.db.flush()
    _responde(
        monkeypatch,
        {
            "registros": [{"id_externo": "C-9"}, {"sin": "identificador"}],
            "paginas": 1,
            "marca": "t2",
        },
    )
    salida = prg.ejecutar_programada(uow, operacion)
    assert salida["marca_avanza"] is False
    assert operacion.marca == "t1", "la marca avanzó dejando un registro detrás"


def test_cuando_el_proveedor_dice_cuanto_esperar_se_le_hace_caso(
    uow: UnidadDeTrabajo, monkeypatch: pytest.MonkeyPatch
) -> None:
    conexion = _conexion(uow)
    operacion = _operacion(uow, conexion, cada_minutos=5)
    _responde(
        monkeypatch,
        ErrorDependencia(
            "cortado",
            error_code="conector.fallo_remoto",
            detalle={"codigo": 429, "reintentar_en": 600},
        ),
    )
    salida = prg.ejecutar_programada(uow, operacion)
    assert salida["resultado"] == "error"
    assert salida["decision"]["reintentar"] is True
    assert salida["decision"]["lo_dice_el_proveedor"] is True
    assert operacion.pausada_hasta is not None
    # 600 s y no los 300 de su cadencia: manda lo que dijo el proveedor. Se
    # mide con holgura porque entre el cálculo y esta línea pasa tiempo real,
    # pero el margen es mucho menor que la diferencia entre las dos cifras — si
    # se aplicara la cadencia en vez del `Retry-After`, esto estaría en rojo.
    faltan = (operacion.pausada_hasta - datetime.now(timezone.utc)).total_seconds()
    assert 570 <= faltan <= 600, f"el reposo es de {faltan:.0f} s y el proveedor pidió 600"
    assert operacion.proxima_at == operacion.pausada_hasta
    assert operacion.intentos == 1


def test_un_permiso_que_falta_no_se_reintenta_pero_tampoco_se_esconde(
    uow: UnidadDeTrabajo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un 403 no se arregla insistiendo. Y desactivar la operación la quitaría
    del panel: lo que hay que hacer con un permiso que falta es **enseñarlo**."""
    conexion = _conexion(uow)
    operacion = _operacion(uow, conexion, cada_minutos=30)
    _responde(
        monkeypatch,
        ErrorDependencia("prohibido", error_code="conector.rechazada", detalle={"codigo": 403}),
    )
    salida = prg.ejecutar_programada(uow, operacion)
    assert salida["decision"]["reintentar"] is False
    assert operacion.activa is True, "se ha desactivado sola y el error desaparece del panel"
    assert operacion.ultimo_error, "el fallo no ha quedado apuntado en ninguna parte"
    assert "conector.rechazada" in operacion.ultimo_error
    # Sin reposo: no se reintenta antes de tiempo, pero tampoco se aparta. La
    # siguiente vuelta le toca por su cadencia normal y el error sigue a la
    # vista mientras tanto.
    assert operacion.pausada_hasta is None
    assert operacion.proxima_at is not None


def test_una_conexion_desactivada_detiene_la_operacion_y_lo_dice(uow: UnidadDeTrabajo) -> None:
    conexion = _conexion(uow)
    operacion = _operacion(uow, conexion, cada_minutos=30)
    conexion.activa = False
    uow.db.flush()
    salida = prg.ejecutar_programada(uow, operacion)
    assert salida["resultado"] == "detenida"
    assert operacion.activa is False and operacion.ultimo_error


def test_no_se_inventa_un_parametro_de_fecha_que_la_api_no_entiende(
    uow: UnidadDeTrabajo,
) -> None:
    """Pedir `?desde=` a una API que no lo declara devuelve el catálogo entero y
    **parece que funciona**: cada vuelta trae todo y la marca no sirve de nada."""
    operacion = _operacion(uow, _conexion(uow), definicion={})
    operacion.marca = "t1"
    salida = prg._parametros(operacion)
    assert salida["parametros"] == {} and salida["es_completa"] is True


def test_si_declara_el_incremento_se_pide_solo_lo_cambiado(uow: UnidadDeTrabajo) -> None:
    operacion = _operacion(
        uow,
        _conexion(uow),
        definicion={"incremento": "marca_de_tiempo", "parametro_incremento": "desde"},
    )
    operacion.marca = "2026-10-01T00:00:00Z"
    salida = prg._parametros(operacion)
    assert salida["parametros"] == {"desde": "2026-10-01T00:00:00Z"}


# ── Los cinco transportes heredados, por fin ejecutados ───────────────────


def test_un_protocolo_que_este_modulo_no_habla_se_dice() -> None:
    """Fallar con un `KeyError` dentro de un proceso nocturno es cómo una
    integración lleva tres semanas sin traer nada y nadie se ha enterado."""
    with pytest.raises(ErrorValidacion) as fallo:
        legado.leer_programado("carrier_pigeon", {}, {})
    assert fallo.value.error_code == "transportes.protocolo_desconocido"


def test_un_fichero_plano_entra_con_el_identificador_que_la_configuracion_diga() -> None:
    salida = legado.leer_programado(
        "fichero",
        {"formato": "delimitado", "separador": ",", "cabecera": True},
        {"contenido": "codigo,nombre\nC-1,Ana\nC-2,Luis", "campo_id": "codigo"},
    )
    assert [r["id_externo"] for r in salida["registros"]] == ["C-1", "C-2"]


def test_sin_campo_id_declarado_no_se_coge_el_primero_que_parezca() -> None:
    """Funciona el día de la demostración y duplica el maestro de clientes el
    día que el proveedor añade una columna delante."""
    salida = legado.leer_programado(
        "fichero",
        {"formato": "delimitado", "separador": ",", "cabecera": True},
        {"contenido": "codigo,nombre\nC-1,Ana"},
    )
    assert "id_externo" not in salida["registros"][0]


def test_por_un_transporte_de_solo_lectura_no_se_manda_nada() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        legado.enviar_programado("sftp", {}, {}, "lo que sea")
    assert fallo.value.error_code == "transportes.protocolo_solo_lectura"


def test_el_soap_sin_url_se_dice_antes_de_salir_a_la_red() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        legado.leer_programado("soap", {}, {"cuerpo": "<x/>"})
    assert fallo.value.error_code == "transportes.soap_sin_url"


# ── Lo que entra no se queda para siempre ─────────────────────────────────


def test_la_purga_no_toca_lo_que_todavia_no_se_ha_procesado(uow: UnidadDeTrabajo) -> None:
    """Un registro que nadie ha mirado no es basura: es trabajo pendiente, y
    borrarlo es perder lo que entró sin que nadie lo sepa."""
    conexion = _conexion(uow)
    viejo = datetime.now(timezone.utc) - timedelta(days=90)
    for estado, externo in (("recibido", "R-1"), ("procesado", "R-2")):
        fila = RegistroRecibido(
            tenant_id=uow.tenant_id,
            conexion_id=conexion.id,
            operacion="clientes",
            externo_id=externo,
            estado=estado,
        )
        uow.db.add(fila)
    uow.db.flush()
    uow.db.execute(
        RegistroRecibido.__table__.update()
        .where(RegistroRecibido.conexion_id == conexion.id)
        .values(created_at=viejo)
    )
    borrados = prg.purgar_registros(uow.db, dias=30)
    assert borrados == 1
    quedan = [
        e
        for (e,) in uow.db.execute(
            RegistroRecibido.__table__.select().with_only_columns(RegistroRecibido.externo_id)
        ).all()
    ]
    assert quedan == ["R-1"]


def test_del_sftp_se_archiva_despues_de_leer_y_nunca_antes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archivar al bajar es cómo se pierde un día de pedidos.

    Si el proceso falla después de mover el fichero, el mayorista no lo vuelve a
    mandar: ese día no existe. Se baja, se interpreta y **sólo entonces** se
    archiva.
    """
    orden: list[str] = []

    def _recoger(config: Any, *, intentos: Any = None) -> dict[str, Any]:
        orden.append("bajar")
        return {
            "bajados": 1,
            "ficheros": [{"ruta": "/in/clientes.csv", "contenido": "codigo\nC-1"}],
            "esperando": [],
        }

    def _archivar(config: Any, ruta: str) -> str:
        orden.append("archivar")
        return "/archivo/clientes.csv"

    monkeypatch.setattr(legado, "recoger_de_sftp", _recoger)
    monkeypatch.setattr(legado, "archivar_sftp", _archivar)
    salida = legado.leer_programado(
        "sftp",
        {"formato": "delimitado", "separador": ",", "cabecera": True},
        {"campo_id": "codigo"},
    )
    assert orden == ["bajar", "archivar"]
    assert [r["id_externo"] for r in salida["registros"]] == ["C-1"]


def test_que_falle_archivar_no_invalida_lo_ya_leido(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tratarlo como un fallo haría que el fichero entero se volviera a leer en
    la pasada siguiente, y entonces entra dos veces."""
    monkeypatch.setattr(
        legado,
        "recoger_de_sftp",
        lambda config, intentos=None: {
            "bajados": 1,
            "ficheros": [{"ruta": "/in/x.csv", "contenido": "codigo\nC-7"}],
            "esperando": [],
        },
    )

    def _revienta(config: Any, ruta: str) -> str:
        raise OSError("permiso denegado al mover")

    monkeypatch.setattr(legado, "archivar_sftp", _revienta)
    salida = legado.leer_programado(
        "sftp",
        {"formato": "delimitado", "separador": ",", "cabecera": True},
        {"campo_id": "codigo"},
    )
    assert [r["id_externo"] for r in salida["registros"]] == ["C-7"]
    assert any("archivar" in aviso for aviso in salida["avisos"])


def test_el_contador_de_ficheros_a_medias_vuelve_a_la_operacion(
    uow: UnidadDeTrabajo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """En memoria del proceso se perdía al reiniciar.

    Y entonces un fichero atascado desde hace tres días volvía a empezar de cero
    y el aviso de «esto nunca termina» no saltaba nunca. La propia función lo
    dejó dicho; esto comprueba que ahora se guarda.
    """
    conexion = _conexion(uow, protocolo="sftp", config={"host": "sftp.cliente.com"})
    operacion = _operacion(uow, conexion, cada_minutos=60)
    operacion.estado_transporte = {"/in/lento.csv": 2}
    uow.db.flush()

    def _leer_programado(
        protocolo: Any, config: Any, definicion: Any, *, intentos: Any = None
    ) -> Any:
        assert intentos == {"/in/lento.csv": 2}, "el contador no ha llegado al transporte"
        intentos["/in/lento.csv"] = 3
        return {"registros": [], "paginas": 0}

    monkeypatch.setattr(legado, "leer_programado", _leer_programado)
    monkeypatch.setattr(prg, "_secretos", lambda db, cid: {}, raising=False)
    prg._leer(conexion, operacion, {}, {})
    assert operacion.estado_transporte == {"/in/lento.csv": 3}
