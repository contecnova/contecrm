"""Seguimiento de lo que se le encarga a un tercero (CRM-00.04.05).

Las pruebas van detrás de los cuatro modos de fallo que hunden una integración de
seguimiento en producción, y que no aparecen en una demostración:

  * el reintento de la pasarela duplica el hito,
  * el webhook desordenado hace que el paquete retroceda en la pantalla,
  * el estado que no sabemos traducir para el seguimiento sin que nadie falle,
  * y el encargo del que el proveedor no dice nada, que parece que va bien.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado

from services.integration import encargos as enc
from services.integration import proyeccion as proy


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def gls(db: Any, tenant_id: UUID) -> enc.Proveedor:
    fila = enc.Proveedor(
        tenant_id=tenant_id,
        clave="gls",
        nombre="GLS",
        mapa_estados={
            "RECOGIDO": "recogido",
            "EN_TRANSITO": "en_curso",
            "EN_REPARTO": "en_entrega",
            "ENTREGADO": "completado",
            "INCIDENCIA": "incidencia",
        },
        plazo_horas=48,
        silencio_horas=24,
        coste_base=Decimal("10.00"),
    )
    db.add(fila)
    db.flush()
    return fila


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ── El encargo genérico (CRM-00.04.05.01) ─────────────────────────────────


def test_el_encargo_nace_con_referencia_propia_y_plazo(uow: UnidadDeTrabajo, gls: Any) -> None:
    """La referencia propia existe porque la del proveedor llega después: hasta
    que el transportista devuelve la suya, el encargo tiene que poder nombrarse."""
    fila = enc.crear(uow, proveedor="gls", datos={"bultos": 3})
    assert fila.referencia_propia.startswith("ENC-")
    assert fila.estado == "creado"
    assert fila.prometido_para is not None
    assert fila.coste_previsto == Decimal("10.00")


def test_el_alta_deja_su_primer_hito(uow: UnidadDeTrabajo, gls: Any) -> None:
    """Sin el hito del alta, el histórico empieza cuando habló el proveedor y no
    se puede medir cuánto tardó en acusar recibo."""
    fila = enc.crear(uow, proveedor="gls")
    vista = enc.seguimiento_para_cliente(uow.db, uow.tenant_id, fila.id)
    assert [h["estado"] for h in vista["hitos"]] == ["creado"]


def test_un_proveedor_desactivado_no_admite_encargos(uow: UnidadDeTrabajo, gls: Any) -> None:
    gls.activo = False
    uow.db.flush()
    with pytest.raises(Conflicto):
        enc.crear(uow, proveedor="gls")


# ── El mapa de estados (CRM-00.04.05.02) ──────────────────────────────────


def test_el_estado_lo_traduce_el_conector_y_no_el_codigo(gls: Any) -> None:
    assert enc.traducir_estado(gls, "ENTREGADO") == ("completado", "")
    # Y sin distinguir mayúsculas ni espacios: los proveedores no son constantes
    # ni consigo mismos entre dos versiones de su API.
    assert enc.traducir_estado(gls, " entregado ")[0] == "completado"


def test_un_estado_desconocido_no_se_adivina(gls: Any) -> None:
    """Es la prueba que justifica el diseño: adivinar que un estado desconocido
    es «en curso» haría que un envío devuelto siguiera contando como en camino, y
    nadie lo mira hasta que el cliente pregunta."""
    destino, aviso = enc.traducir_estado(gls, "DEVUELTO_ORIGEN")
    assert destino is None
    assert "no está en el mapa" in aviso


def test_un_mapa_que_traduce_a_un_estado_inventado_se_caza(gls: Any) -> None:
    gls.mapa_estados = {"X": "entregadisimo"}
    destino, aviso = enc.traducir_estado(gls, "X")
    assert destino is None
    assert "no es un estado del sistema" in aviso


# ── Ingesta (CRM-00.04.05.03) ─────────────────────────────────────────────


def test_el_evento_mueve_el_encargo(uow: UnidadDeTrabajo, gls: Any) -> None:
    fila = enc.crear(uow, proveedor="gls", referencia_externa="GLS-1")
    salida = enc.ingerir(
        uow,
        proveedor="gls",
        referencia_externa="GLS-1",
        estado_proveedor="EN_TRANSITO",
        id_externo="e1",
    )
    assert salida["aplicado"] is True
    uow.db.refresh(fila)
    assert fila.estado == "en_curso"


def test_el_mismo_evento_dos_veces_no_duplica_el_hito(uow: UnidadDeTrabajo, gls: Any) -> None:
    """Las pasarelas reintentan. Sin idempotencia, el cliente ve dos veces «salió
    de almacén» y la cuenta de hitos deja de servir para medir nada."""
    enc.crear(uow, proveedor="gls", referencia_externa="GLS-2")
    uno = enc.ingerir(
        uow,
        proveedor="gls",
        referencia_externa="GLS-2",
        estado_proveedor="RECOGIDO",
        id_externo="x",
    )
    dos = enc.ingerir(
        uow,
        proveedor="gls",
        referencia_externa="GLS-2",
        estado_proveedor="RECOGIDO",
        id_externo="x",
    )
    assert uno["aplicado"] is True
    assert dos == {
        "aplicado": False,
        "duplicado": True,
        "encargo_id": uno["encargo_id"],
        "estado": "recogido",
    }


def test_un_evento_atrasado_se_guarda_pero_no_retrocede_el_encargo(
    uow: UnidadDeTrabajo, gls: Any
) -> None:
    """Los webhooks llegan desordenados. Guardarlo importa —es la prueba de lo
    que dijo el proveedor— y no aplicarlo también: un paquete que retrocede en la
    pantalla es una llamada al servicio de atención."""
    fila = enc.crear(uow, proveedor="gls", referencia_externa="GLS-3")
    enc.ingerir(
        uow,
        proveedor="gls",
        referencia_externa="GLS-3",
        estado_proveedor="ENTREGADO",
        id_externo="b",
    )
    salida = enc.ingerir(
        uow,
        proveedor="gls",
        referencia_externa="GLS-3",
        estado_proveedor="EN_REPARTO",
        id_externo="a",
    )
    assert salida["aplicado"] is False
    uow.db.refresh(fila)
    assert fila.estado == "completado"
    # Y el cliente no lo ve, porque no se aplicó.
    vista = enc.seguimiento_para_cliente(uow.db, uow.tenant_id, fila.id)
    assert "en_entrega" not in [h["estado"] for h in vista["hitos"]]


def test_un_estado_sin_mapear_no_para_el_reloj_del_silencio(uow: UnidadDeTrabajo, gls: Any) -> None:
    """El proveedor ha hablado aunque no le entendamos. Contar solo los eventos
    aplicados haría que un encargo con estados desconocidos pareciera abandonado,
    y se perseguiría al transportista en vez de arreglar el mapa."""
    fila = enc.crear(uow, proveedor="gls", referencia_externa="GLS-4")
    fila.ultima_novedad_at = _ahora() - timedelta(days=5)
    uow.db.flush()
    salida = enc.ingerir(
        uow,
        proveedor="gls",
        referencia_externa="GLS-4",
        estado_proveedor="LO_QUE_SEA",
        id_externo="z",
    )
    assert salida["aplicado"] is False
    uow.db.refresh(fila)
    assert (_ahora() - fila.ultima_novedad_at) < timedelta(minutes=1)


def test_un_evento_de_un_encargo_que_no_consta_no_crea_uno(uow: UnidadDeTrabajo, gls: Any) -> None:
    """Crearlo sobre la marcha llenaría la base de encargos fantasma que nadie
    reclama, casi siempre por una referencia mal escrita."""
    with pytest.raises(NoEncontrado):
        enc.ingerir(
            uow, proveedor="gls", referencia_externa="NO-EXISTE", estado_proveedor="ENTREGADO"
        )


def test_un_evento_sin_referencia_se_rechaza(uow: UnidadDeTrabajo, gls: Any) -> None:
    with pytest.raises(ErrorValidacion):
        enc.ingerir(uow, proveedor="gls", estado_proveedor="ENTREGADO")


def test_los_estados_sin_mapear_salen_en_una_lista(uow: UnidadDeTrabajo, gls: Any) -> None:
    """Es lo que hay que mirar al integrar un proveedor nuevo: cada entrada es un
    evento que se guardó y no hizo nada."""
    enc.crear(uow, proveedor="gls", referencia_externa="GLS-5")
    for i in range(2):
        enc.ingerir(
            uow,
            proveedor="gls",
            referencia_externa="GLS-5",
            estado_proveedor="ADUANAS",
            id_externo=f"a{i}",
        )
    lista = enc.estados_sin_mapear(uow.db, uow.tenant_id)
    assert lista == [{"proveedor": "gls", "estado_proveedor": "ADUANAS", "veces": 2}]


# ── Incidencias (CRM-00.04.05.04) ─────────────────────────────────────────


def test_la_incidencia_se_enlaza_al_caso_y_no_lo_duplica(uow: UnidadDeTrabajo, gls: Any) -> None:
    caso = uuid4()
    fila = enc.crear(uow, proveedor="gls")
    inc = enc.abrir_incidencia(
        uow, fila.id, tipo="retraso/aduana", caso_id=caso, responsable="proveedor"
    )
    assert inc.caso_id == caso
    uow.db.refresh(fila)
    assert fila.estado == "incidencia"


def test_un_responsable_inventado_se_rechaza(uow: UnidadDeTrabajo, gls: Any) -> None:
    fila = enc.crear(uow, proveedor="gls")
    with pytest.raises(ErrorValidacion):
        enc.abrir_incidencia(uow, fila.id, tipo="x", responsable="el_karma")


def test_una_incidencia_ya_cerrada_no_se_cierra_dos_veces(uow: UnidadDeTrabajo, gls: Any) -> None:
    fila = enc.crear(uow, proveedor="gls")
    inc = enc.abrir_incidencia(uow, fila.id, tipo="dano/embalaje")
    enc.resolver_incidencia(uow, inc.id, responsable="proveedor")
    with pytest.raises(Conflicto):
        enc.resolver_incidencia(uow, inc.id)


# ── Elección de proveedor (CRM-00.04.05.07) ───────────────────────────────


def test_gana_la_primera_regla_que_encaja(db: Any, tenant_id: UUID, gls: Any) -> None:
    db.add(
        enc.ReglaProveedor(
            tenant_id=tenant_id,
            nombre="portugal",
            prioridad=10,
            condiciones=[{"atributo": "encargo.pais", "operador": "=", "valor": "PT"}],
            proveedor="seur",
            alternativos=["gls"],
        )
    )
    db.add(
        enc.ReglaProveedor(
            tenant_id=tenant_id, nombre="resto", prioridad=90, condiciones=[], proveedor="gls"
        )
    )
    db.flush()
    assert enc.elegir_proveedor(db, tenant_id, {"pais": "PT"})[:2] == ("seur", ["gls"])
    assert enc.elegir_proveedor(db, tenant_id, {"pais": "ES"})[0] == "gls"


def test_la_eleccion_dice_que_regla_gano(db: Any, tenant_id: UUID, gls: Any) -> None:
    """Una elección que no se puede explicar no se puede corregir, y acaba en
    «el sistema lo manda por donde quiere»."""
    _, _, regla = enc.elegir_proveedor(db, tenant_id, {})
    assert "sin regla" in regla


def test_sin_proveedores_ni_reglas_se_dice_en_vez_de_fallar_luego(db: Any, tenant_id: UUID) -> None:
    with pytest.raises(ErrorValidacion):
        enc.elegir_proveedor(db, tenant_id, {})


# ── El encargo mudo (CRM-00.04.05.10) ─────────────────────────────────────


def test_el_encargo_del_que_nadie_dice_nada_se_marca(uow: UnidadDeTrabajo, gls: Any) -> None:
    """El fallo más caro no es el error: es el silencio. En la pantalla pone «en
    tránsito» y nadie lo mira hasta que llama el cliente."""
    fila = enc.crear(uow, proveedor="gls")
    fila.ultima_novedad_at = _ahora() - timedelta(hours=30)
    uow.db.flush()
    salida = enc.revisar_silencios(uow, uow.tenant_id)
    assert [m["referencia"] for m in salida["nuevos_mudos"]] == [fila.referencia_propia]
    uow.db.refresh(fila)
    assert fila.mudo is True


def test_el_plazo_de_silencio_es_por_proveedor(uow: UnidadDeTrabajo, gls: Any, db: Any) -> None:
    """Uno que reporta cada hora y otro que reporta una vez al día no pueden
    medirse con la misma vara: una sola llenaría la lista de falsos avisos hasta
    que nadie la mire."""
    db.add(
        enc.Proveedor(tenant_id=uow.tenant_id, clave="lento", nombre="Lento", silencio_horas=240)
    )
    db.flush()
    rapido = enc.crear(uow, proveedor="gls")
    lento = enc.crear(uow, proveedor="lento")
    for fila in (rapido, lento):
        fila.ultima_novedad_at = _ahora() - timedelta(hours=30)
    uow.db.flush()

    salida = enc.revisar_silencios(uow, uow.tenant_id)
    assert [m["proveedor"] for m in salida["nuevos_mudos"]] == ["gls"]


def test_un_encargo_terminado_no_se_marca_mudo(uow: UnidadDeTrabajo, gls: Any) -> None:
    """Un envío entregado hace un mes no tiene por qué seguir dando noticias."""
    fila = enc.crear(uow, proveedor="gls")
    fila.estado = "completado"
    fila.ultima_novedad_at = _ahora() - timedelta(days=30)
    uow.db.flush()
    assert enc.revisar_silencios(uow, uow.tenant_id)["nuevos_mudos"] == []


def test_volver_a_hablar_quita_el_mudo(uow: UnidadDeTrabajo, gls: Any) -> None:
    fila = enc.crear(uow, proveedor="gls", referencia_externa="GLS-6")
    fila.ultima_novedad_at = _ahora() - timedelta(hours=30)
    uow.db.flush()
    enc.revisar_silencios(uow, uow.tenant_id)
    enc.ingerir(
        uow,
        proveedor="gls",
        referencia_externa="GLS-6",
        estado_proveedor="EN_TRANSITO",
        id_externo="q",
    )
    uow.db.refresh(fila)
    assert fila.mudo is False


def test_sin_encargos_abiertos_no_se_dice_que_todo_va_bien(uow: UnidadDeTrabajo) -> None:
    """Un verde vacío se lee igual que uno ganado."""
    assert enc.revisar_silencios(uow, uow.tenant_id)["medible"] is False


# ── Lo que ve el cliente (CRM-00.04.05.06) ────────────────────────────────


def test_al_cliente_no_le_sale_lo_que_nos_cuesta(uow: UnidadDeTrabajo, gls: Any) -> None:
    """Si el filtro dependiera del front, bastaría una pantalla nueva que se
    olvidara de filtrar."""
    fila = enc.crear(uow, proveedor="gls")
    fila.interno = {"nota": "este cliente paga tarde"}
    fila.coste_facturado = Decimal("30.00")
    uow.db.flush()
    vista = enc.seguimiento_para_cliente(uow.db, uow.tenant_id, fila.id)
    plano = str(vista)
    assert "coste" not in plano
    assert "paga tarde" not in plano
    assert "alternativos" not in plano


def test_el_encargo_de_otra_cuenta_da_404_y_no_403(uow: UnidadDeTrabajo, gls: Any) -> None:
    """Un 403 confirma que ese encargo existe, y con eso se puede recorrer la
    base preguntando por referencias."""
    fila = enc.crear(uow, proveedor="gls", cuenta_id=uuid4())
    with pytest.raises(NoEncontrado):
        enc.seguimiento_para_cliente(uow.db, uow.tenant_id, fila.id, cuenta_id=uuid4())


def test_al_cliente_se_le_dice_si_vamos_tarde(uow: UnidadDeTrabajo, gls: Any) -> None:
    """Lo va a notar igual, y enterarse por nosotros es distinto de enterarse
    esperando."""
    fila = enc.crear(uow, proveedor="gls")
    fila.prometido_para = _ahora() - timedelta(hours=1)
    uow.db.flush()
    assert enc.seguimiento_para_cliente(uow.db, uow.tenant_id, fila.id)["va_tarde"] is True


def test_al_cliente_no_se_le_dice_de_quien_fue_la_culpa(uow: UnidadDeTrabajo, gls: Any) -> None:
    """Esa conversación se tiene hablando, no leyendo en una pantalla que la
    culpa fue suya."""
    fila = enc.crear(uow, proveedor="gls")
    enc.abrir_incidencia(uow, fila.id, tipo="retraso", responsable="cliente")
    vista = enc.seguimiento_para_cliente(uow.db, uow.tenant_id, fila.id)
    assert vista["incidencias"][0]["tipo"] == "retraso"
    assert "responsable" not in vista["incidencias"][0]


# ── Conciliación (CRM-00.04.05.08) ────────────────────────────────────────


def test_la_conciliacion_separa_los_tres_problemas(uow: UnidadDeTrabajo, gls: Any) -> None:
    """Llevan a tres acciones distintas: reclamar, investigar y provisionar."""
    caro = enc.crear(uow, proveedor="gls", referencia_externa="F-1")
    caro.estado = "completado"
    entregado = enc.crear(uow, proveedor="gls", referencia_externa="F-2")
    entregado.estado = "completado"
    entregado.coste_facturado = Decimal("10.00")
    fantasma = enc.crear(uow, proveedor="gls", referencia_externa="F-3")
    uow.db.flush()

    salida = enc.conciliar(
        uow,
        proveedor="gls",
        lineas=[
            {"referencia": "F-1", "importe": "25.00"},
            {"referencia": "F-3", "importe": "10.00"},
            {"referencia": "F-9", "importe": "5.00"},
        ],
    )
    assert [d["referencia"] for d in salida["con_diferencia"]] == ["F-1"]
    assert salida["referencias_desconocidas"] == ["F-9"]
    assert salida["en_verde"] is False
    assert fantasma.estado != "completado"


def test_lo_entregado_y_no_facturado_tambien_sale(uow: UnidadDeTrabajo, gls: Any) -> None:
    """Nadie quiere la sorpresa de una factura de hace cuatro meses."""
    fila = enc.crear(uow, proveedor="gls", referencia_externa="F-4")
    fila.estado = "completado"
    uow.db.flush()
    salida = enc.conciliar(uow, proveedor="gls", lineas=[])
    assert [s["referencia"] for s in salida["entregado_sin_facturar"]] == ["F-4"]


# ── Cumplimiento (CRM-00.04.05.09) ────────────────────────────────────────


def test_el_cumplimiento_solo_cuenta_lo_que_es_del_proveedor(
    uow: UnidadDeTrabajo, gls: Any
) -> None:
    """Una incidencia cuya culpa fue nuestra no cuenta contra él: un número que
    no se puede defender en una reunión no se usa."""
    a_tiempo = enc.crear(uow, proveedor="gls")
    a_tiempo.estado = "completado"
    a_tiempo.prometido_para = _ahora() + timedelta(hours=2)
    a_tiempo.completado_at = _ahora()
    tarde = enc.crear(uow, proveedor="gls")
    tarde.estado = "completado"
    tarde.prometido_para = _ahora() - timedelta(hours=2)
    tarde.completado_at = _ahora()
    uow.db.flush()
    enc.abrir_incidencia(uow, tarde.id, tipo="retraso", responsable="proveedor")
    enc.abrir_incidencia(uow, a_tiempo.id, tipo="direccion_mala", responsable="cliente")

    hoy = date.today()
    fila = enc.cumplimiento_proveedor(
        uow.db, uow.tenant_id, desde=hoy - timedelta(days=1), hasta=hoy + timedelta(days=1)
    )[0]
    assert fila["cumplimiento_pct"] == 50.0
    assert fila["incidencias_suyas"] == 1


def test_un_proveedor_recien_contratado_no_cumple_el_cien_por_cien(
    uow: UnidadDeTrabajo, gls: Any
) -> None:
    """Todavía no ha demostrado nada, y un 100 % de cero envíos es el número con
    el que se firma un contrato que después no se cumple."""
    enc.crear(uow, proveedor="gls")
    hoy = date.today()
    fila = enc.cumplimiento_proveedor(
        uow.db, uow.tenant_id, desde=hoy - timedelta(days=1), hasta=hoy + timedelta(days=1)
    )[0]
    assert fila["cumplimiento_pct"] is None
    assert fila["medible"] is False
    assert "no ha demostrado nada" in fila["aviso"]


# ── El conector viene en el módulo (CRM-00.04.04.06) ──────────────────────


def test_el_conector_del_modulo_se_vuelve_proveedor(db: Any, tenant_id: UUID) -> None:
    """Si no llegara, habría que teclearlo otra vez en la otra pantalla: justo el
    trabajo manual que el módulo existe para quitar."""
    salida = proy.aplicar_conectores(
        db,
        tenant_id,
        modulo="logistica",
        conectores=[
            {
                "clave": "gls",
                "nombre": "GLS",
                "mapeo_estados": {"ENTREGADO": "completado"},
                "plazo_horas": 48,
            }
        ],
    )
    assert salida["creados"] == ["gls"]
    fila = enc._proveedor(db, tenant_id, "gls")
    assert fila.modulo == "logistica"
    assert fila.plazo_horas == 48


def test_actualizar_el_modulo_corrige_el_mapa_de_estados(db: Any, tenant_id: UUID) -> None:
    """Sin esto, una versión nueva que arregla la traducción se queda en el
    manifiesto y el seguimiento sigue con la tabla vieja."""
    proy.aplicar_conectores(
        db, tenant_id, modulo="logistica", conectores=[{"clave": "gls", "mapeo_estados": {}}]
    )
    proy.aplicar_conectores(
        db,
        tenant_id,
        modulo="logistica",
        conectores=[{"clave": "gls", "mapeo_estados": {"DELIVERED": "completado"}}],
    )
    assert enc._proveedor(db, tenant_id, "gls").mapa_estados == {"DELIVERED": "completado"}


def test_el_modulo_no_se_queda_el_proveedor_que_alguien_creo_a_mano(
    db: Any, tenant_id: UUID, gls: Any
) -> None:
    """Perder el ajuste de un plazo se nota semanas después, cuando los informes
    empiezan a decir que todo llega tarde."""
    salida = proy.aplicar_conectores(
        db, tenant_id, modulo="logistica", conectores=[{"clave": "gls", "plazo_horas": 1}]
    )
    assert salida["respetados"] == ["gls"]
    assert enc._proveedor(db, tenant_id, "gls").plazo_horas == 48


def test_dos_modulos_que_declaran_el_mismo_transportista_no_se_pisan(
    db: Any, tenant_id: UUID
) -> None:
    """Instalar un módulo no puede cambiar el comportamiento de otro sin que
    nadie lo pidiera."""
    proy.aplicar_conectores(
        db, tenant_id, modulo="logistica", conectores=[{"clave": "gls", "plazo_horas": 48}]
    )
    salida = proy.aplicar_conectores(
        db, tenant_id, modulo="otro", conectores=[{"clave": "gls", "plazo_horas": 2}]
    )
    assert salida["respetados"] == ["gls"]
    assert enc._proveedor(db, tenant_id, "gls").plazo_horas == 48


def test_desinstalar_desactiva_pero_no_borra(db: Any, tenant_id: UUID) -> None:
    """Los encargos en vuelo siguen apuntando al proveedor: borrarlo dejaría sin
    nombre ni mapa de estados a envíos que todavía están en la calle."""
    proy.aplicar_conectores(db, tenant_id, modulo="logistica", conectores=[{"clave": "gls"}])
    assert proy.retirar_conectores(db, tenant_id, modulo="logistica") == ["gls"]
    assert enc._proveedor(db, tenant_id, "gls").activo is False
