"""Firma electrónica: sobres, niveles, evidencia y panel (CRM-06.01.02).

Lo que decide si esto sirve no es mandar el sobre: es poder demostrar, dos años
después y ante quien lo discuta, qué se firmó, quién lo firmó y cuándo. Las
pruebas van detrás de los cinco sitios donde eso se pierde:

  * la firma que dice ser avanzada y se verifica por correo,
  * el proveedor al que se le pide un nivel que no hace,
  * el aviso duplicado que mete el mismo acceso dos veces en la custodia,
  * el firmado que se archiva sobre un sobre que sigue abierto,
  * y el sobre que caduca y sigue apareciendo como negocio vivo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado

from services.integration import firma as fir


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def proveedor(db: Any, tenant_id: UUID) -> fir.ProveedorFirma:
    fila = fir.ProveedorFirma(
        tenant_id=tenant_id,
        clave="firmafacil",
        nombre="FirmaFácil",
        niveles=["simple", "avanzada"],
        identificaciones=["correo", "sms", "certificado"],
        mapa_estados={
            "delivered": "entregado",
            "opened": "abierto",
            "signed": "firmado",
            "declined": "rechazado",
        },
    )
    db.add(fila)
    db.flush()
    return fila


def _sobre(uow: UnidadDeTrabajo, **kw: Any) -> fir.Sobre:
    base: dict[str, Any] = {
        "documento_id": "doc-1",
        "firmantes": [{"nombre": "Ana", "email": "ana@cliente.com"}],
        "proveedor": "firmafacil",
        "asunto": "Contrato marco",
    }
    base.update(kw)
    return fir.crear(uow, **base)


# ── Niveles eIDAS e identificación (CRM-06.01.02.05, CRM-06.01.02.08) ─────


def test_una_firma_avanzada_no_se_verifica_por_correo() -> None:
    """Decir que es avanzada verificando un buzón es decirlo sin serlo, y eso solo
    se descubre cuando alguien impugna la firma — el único momento en que la firma
    importaba."""
    with pytest.raises(ErrorValidacion) as e:
        fir.comprobar_identificacion("avanzada", "correo")
    assert e.value.error_code == "firma.identificacion_insuficiente"


def test_una_cualificada_exige_certificado() -> None:
    """Sin certificado cualificado no es cualificada, por mucho que el proveedor
    lo llame así en su folleto."""
    fir.comprobar_identificacion("cualificada", "certificado")
    with pytest.raises(ErrorValidacion):
        fir.comprobar_identificacion("cualificada", "sms")


def test_un_nivel_inventado_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion):
        fir.comprobar_identificacion("superfirmada", "certificado")


def test_no_se_manda_un_nivel_que_el_proveedor_no_hace(
    uow: UnidadDeTrabajo, proveedor: Any
) -> None:
    """Produce una firma que parece válida y no lo es. Se para aquí, no en el
    juzgado."""
    with pytest.raises(Conflicto) as e:
        _sobre(
            uow,
            nivel="cualificada",
            firmantes=[{"nombre": "Ana", "email": "a@b.c", "identificacion": "certificado"}],
        )
    assert e.value.error_code == "firma.nivel_no_soportado"


def test_no_se_pide_una_identificacion_que_el_proveedor_no_tiene(
    uow: UnidadDeTrabajo, proveedor: Any
) -> None:
    with pytest.raises(Conflicto) as e:
        _sobre(
            uow,
            nivel="avanzada",
            firmantes=[{"nombre": "Ana", "email": "a@b.c", "identificacion": "video"}],
        )
    assert e.value.error_code == "firma.identificacion_no_soportada"


def test_una_copia_no_necesita_identificacion_fuerte(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """Quien recibe copia no firma: exigirle certificado sería pedir un trámite
    para leer un correo."""
    sobre = _sobre(
        uow,
        nivel="avanzada",
        firmantes=[
            {"nombre": "Ana", "email": "a@b.c", "identificacion": "sms"},
            {"nombre": "Gestoría", "email": "g@b.c", "papel": "copia", "orden": 1},
        ],
    )
    assert sobre.estado == "borrador"


# ── Elección de proveedor y nivel (CRM-06.01.02.12) ───────────────────────


def test_gana_la_primera_regla_que_encaja(db: Any, tenant_id: UUID, proveedor: Any) -> None:
    db.add(
        fir.ReglaProveedorFirma(
            tenant_id=tenant_id,
            nombre="portugal",
            prioridad=10,
            condiciones=[{"atributo": "documento.pais", "operador": "=", "valor": "PT"}],
            proveedor="otro",
        )
    )
    db.add(
        fir.ReglaProveedorFirma(
            tenant_id=tenant_id,
            nombre="resto",
            prioridad=90,
            condiciones=[],
            proveedor="firmafacil",
        )
    )
    db.flush()
    assert fir.elegir_proveedor(db, tenant_id, {"pais": "PT"})[0] == "otro"
    assert fir.elegir_proveedor(db, tenant_id, {"pais": "ES"})[0] == "firmafacil"


def test_una_regla_sube_el_nivel_pero_no_lo_baja(db: Any, tenant_id: UUID, proveedor: Any) -> None:
    """Dejar que una regla rebaje el nivel convierte la política en una
    sugerencia."""
    db.add(
        fir.ReglaProveedorFirma(
            tenant_id=tenant_id,
            nombre="importes altos",
            condiciones=[{"atributo": "documento.importe", "operador": ">", "valor": 50000}],
            proveedor="firmafacil",
            nivel_minimo="avanzada",
        )
    )
    db.flush()
    _, sube, _ = fir.elegir_proveedor(db, tenant_id, {"importe": 100000}, nivel="simple")
    assert sube == "avanzada"

    db.add(
        fir.ReglaProveedorFirma(
            tenant_id=tenant_id,
            nombre="todo simple",
            prioridad=1,
            condiciones=[],
            proveedor="firmafacil",
            nivel_minimo="simple",
        )
    )
    db.flush()
    _, mantiene, _ = fir.elegir_proveedor(db, tenant_id, {}, nivel="avanzada")
    assert mantiene == "avanzada"


def test_la_eleccion_dice_que_regla_gano(db: Any, tenant_id: UUID, proveedor: Any) -> None:
    assert "sin regla" in fir.elegir_proveedor(db, tenant_id, {})[2]


def test_sin_proveedores_se_dice_en_vez_de_fallar_luego(db: Any, tenant_id: UUID) -> None:
    with pytest.raises(ErrorValidacion) as e:
        fir.elegir_proveedor(db, tenant_id, {})
    assert e.value.error_code == "firma.sin_proveedor"


def test_un_proveedor_en_retirada_no_recibe_sobres_nuevos(
    db: Any, tenant_id: UUID, proveedor: Any
) -> None:
    """Cambiar de proveedor sin perder lo enviado: los sobres en curso terminan
    con el suyo y los nuevos salen con el otro."""
    proveedor.solo_en_curso = True
    otro = fir.ProveedorFirma(
        tenant_id=tenant_id, clave="nuevo", nombre="Nuevo", niveles=["simple"]
    )
    db.add(otro)
    db.flush()
    assert fir.elegir_proveedor(db, tenant_id, {})[0] == "nuevo"


# ── Crear y mandar (CRM-06.01.02.01) ──────────────────────────────────────


def test_crear_no_manda(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """Mandar un contrato es irreversible de cara al cliente, y el error más caro
    es pulsar creyendo que aún se estaba montando."""
    sobre = _sobre(uow)
    assert sobre.estado == "borrador"
    assert sobre.enviado_at is None


def test_un_sobre_sin_documento_no_manda_nada(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    with pytest.raises(ErrorValidacion):
        _sobre(uow, documento_id="")


def test_un_sobre_sin_firmantes_no_lo_firma_nadie(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    with pytest.raises(ErrorValidacion):
        _sobre(uow, firmantes=[])


def test_un_sobre_de_solo_copias_no_se_manda(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    sobre = _sobre(uow, firmantes=[{"nombre": "G", "email": "g@b.c", "papel": "copia"}])
    with pytest.raises(Conflicto) as e:
        fir.enviar(uow, sobre.id)
    assert e.value.error_code == "firma.sin_firmantes_reales"


def test_el_alta_deja_su_primera_evidencia(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """Sin ella, la custodia empieza cuando habló el proveedor y no se puede medir
    cuánto tardó en salir."""
    sobre = _sobre(uow)
    assert [e["tipo"] for e in fir.evidencia(uow.db, uow.tenant_id, sobre.id)["eventos"]] == [
        "creado"
    ]


def test_con_orden_estricto_solo_le_toca_al_siguiente(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """Es lo que hace que un contrato lo firme el cliente DESPUÉS del nuestro, que
    es el orden que pide quien redacta contratos."""
    sobre = _sobre(
        uow,
        orden_estricto=True,
        firmantes=[
            {"nombre": "Nuestro", "email": "n@casa.com", "orden": 0},
            {"nombre": "Cliente", "email": "c@cliente.com", "orden": 1},
        ],
    )
    assert [f.email for f in fir.a_quien_le_toca(uow.db, sobre)] == ["n@casa.com"]


def test_sin_orden_les_toca_a_todos(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    sobre = _sobre(
        uow,
        firmantes=[
            {"nombre": "A", "email": "a@b.c", "orden": 0},
            {"nombre": "B", "email": "b@b.c", "orden": 1},
        ],
    )
    assert len(fir.a_quien_le_toca(uow.db, sobre)) == 2


# ── Ingesta y estados (CRM-06.01.02.03) ───────────────────────────────────


def test_el_estado_lo_traduce_el_proveedor_y_no_el_codigo(proveedor: Any) -> None:
    assert fir.traducir_estado(proveedor, "signed") == ("firmado", "")
    assert fir.traducir_estado(proveedor, " SIGNED ")[0] == "firmado"


def test_un_estado_desconocido_no_se_adivina(proveedor: Any) -> None:
    """Suponer que «completed» de un proveedor nuevo significa firmado haría dar
    por firmado un sobre que fue rechazado, y con eso se factura."""
    destino, aviso = fir.traducir_estado(proveedor, "completed")
    assert destino is None
    assert "no está en el mapa" in aviso


def test_cuando_firman_todos_el_sobre_se_completa(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    sobre = _sobre(
        uow,
        firmantes=[
            {"nombre": "A", "email": "a@b.c", "orden": 0},
            {"nombre": "B", "email": "b@b.c", "orden": 1},
        ],
    )
    fir.enviar(uow, sobre.id)
    fir.ingerir(
        uow,
        proveedor="firmafacil",
        referencia=sobre.referencia,
        estado_proveedor="signed",
        email_firmante="a@b.c",
        id_externo="e1",
    )
    assert fir.evidencia(uow.db, uow.tenant_id, sobre.id)["estado"] == "en_curso"
    fir.ingerir(
        uow,
        proveedor="firmafacil",
        referencia=sobre.referencia,
        estado_proveedor="signed",
        email_firmante="b@b.c",
        id_externo="e2",
    )
    assert fir.evidencia(uow.db, uow.tenant_id, sobre.id)["estado"] == "completado"


def test_un_rechazo_cierra_el_sobre(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """El documento ya no se puede completar, y seguir mandando recordatorios a
    los demás es hacerles perder el tiempo con algo muerto."""
    sobre = _sobre(
        uow,
        firmantes=[
            {"nombre": "A", "email": "a@b.c", "orden": 0},
            {"nombre": "B", "email": "b@b.c", "orden": 1},
        ],
    )
    fir.enviar(uow, sobre.id)
    fir.ingerir(
        uow,
        proveedor="firmafacil",
        referencia=sobre.referencia,
        estado_proveedor="declined",
        email_firmante="a@b.c",
        motivo="el precio no es el pactado",
        id_externo="r1",
    )
    salida = fir.evidencia(uow.db, uow.tenant_id, sobre.id)
    assert salida["estado"] == "rechazado"
    assert salida["firmantes"][0]["motivo_rechazo"] == "el precio no es el pactado"


def test_el_mismo_aviso_dos_veces_no_duplica_la_custodia(
    uow: UnidadDeTrabajo, proveedor: Any
) -> None:
    """Es exactamente lo que un perito mira para decidir si la evidencia es
    fiable."""
    sobre = _sobre(uow)
    fir.enviar(uow, sobre.id)
    uno = fir.ingerir(
        uow,
        proveedor="firmafacil",
        referencia=sobre.referencia,
        estado_proveedor="opened",
        email_firmante="ana@cliente.com",
        id_externo="x",
    )
    dos = fir.ingerir(
        uow,
        proveedor="firmafacil",
        referencia=sobre.referencia,
        estado_proveedor="opened",
        email_firmante="ana@cliente.com",
        id_externo="x",
    )
    assert uno["aplicado"] is True
    assert dos["duplicado"] is True
    abiertos = [
        e
        for e in fir.evidencia(uow.db, uow.tenant_id, sobre.id)["eventos"]
        if e["tipo"] == "abierto"
    ]
    assert len(abiertos) == 1


def test_un_estado_sin_mapear_deja_su_evidencia_igual(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """Perder un acceso porque no supimos traducir su nombre deja un hueco que
    después no se puede rellenar."""
    sobre = _sobre(uow)
    fir.enviar(uow, sobre.id)
    salida = fir.ingerir(
        uow,
        proveedor="firmafacil",
        referencia=sobre.referencia,
        estado_proveedor="lo_que_sea",
        id_externo="z",
    )
    assert salida["aplicado"] is False
    tipos = [e["tipo"] for e in fir.evidencia(uow.db, uow.tenant_id, sobre.id)["eventos"]]
    assert "error" in tipos


def test_un_aviso_de_un_sobre_que_no_consta_no_crea_uno(
    uow: UnidadDeTrabajo, proveedor: Any
) -> None:
    with pytest.raises(NoEncontrado):
        fir.ingerir(uow, proveedor="firmafacil", referencia="NO-EXISTE", estado_proveedor="signed")


# ── Evidencia (CRM-06.01.02.04) ───────────────────────────────────────────


def test_la_evidencia_guarda_cuando_paso_y_cuando_nos_enteramos(
    uow: UnidadDeTrabajo, proveedor: Any
) -> None:
    """La diferencia es la latencia de la integración, y sin las dos no se puede
    defender una fecha."""
    sobre = _sobre(uow)
    fir.enviar(uow, sobre.id)
    ayer = _ahora() - timedelta(days=1)
    fir.ingerir(
        uow,
        proveedor="firmafacil",
        referencia=sobre.referencia,
        estado_proveedor="signed",
        email_firmante="ana@cliente.com",
        ocurrio_at=ayer,
        id_externo="f1",
    )
    evento = next(
        e
        for e in fir.evidencia(uow.db, uow.tenant_id, sobre.id)["eventos"]
        if e["tipo"] == "firmado"
    )
    assert evento["ocurrio_at"] != evento["registrado_at"]


def test_sin_las_dos_huellas_el_expediente_no_es_verificable(
    uow: UnidadDeTrabajo, proveedor: Any
) -> None:
    """Sin ellas, «esto no es lo que yo firmé» no se puede contestar."""
    sobre = _sobre(uow, contenido=b"contrato original")
    assert fir.evidencia(uow.db, uow.tenant_id, sobre.id)["verificable"] is False


def test_con_las_dos_huellas_si_lo_es(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    sobre = _sobre(uow, contenido=b"contrato original")
    fir.enviar(uow, sobre.id)
    fir.ingerir(
        uow,
        proveedor="firmafacil",
        referencia=sobre.referencia,
        estado_proveedor="signed",
        email_firmante="ana@cliente.com",
        id_externo="f1",
    )
    fir.archivar_firmado(uow, sobre.id, documento_firmado_id="doc-2", contenido=b"contrato firmado")
    salida = fir.evidencia(uow.db, uow.tenant_id, sobre.id)
    assert salida["verificable"] is True
    assert salida["hash_enviado"] != salida["hash_firmado"]


def test_la_huella_es_del_contenido(proveedor: Any) -> None:
    assert fir.huella(b"a") != fir.huella(b"b")
    assert len(fir.huella(b"a")) == 64


# ── El firmado vuelve (CRM-06.01.02.07) ───────────────────────────────────


def test_el_firmado_se_enlaza_al_registro_que_lo_origino(
    uow: UnidadDeTrabajo, proveedor: Any, db: Any
) -> None:
    from crmcore.documental.enlaces import documentos_de

    origen = uuid4()
    sobre = _sobre(uow, objeto_origen="presupuesto", objeto_origen_id=origen)
    fir.enviar(uow, sobre.id)
    fir.ingerir(
        uow,
        proveedor="firmafacil",
        referencia=sobre.referencia,
        estado_proveedor="signed",
        email_firmante="ana@cliente.com",
        id_externo="f1",
    )
    fir.archivar_firmado(uow, sobre.id, documento_firmado_id="doc-2", certificado_id="cert-1")
    roles = {d["rol"] for d in documentos_de(db, objeto_tipo="presupuesto", objeto_id=origen)}
    assert roles == {"documento_firmado", "certificado_firma"}


def test_el_original_no_se_pisa(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """El original tiene que seguir existiendo tal como salió: es la mitad de la
    prueba de que lo firmado es lo que se mandó."""
    sobre = _sobre(uow)
    fir.enviar(uow, sobre.id)
    fir.ingerir(
        uow,
        proveedor="firmafacil",
        referencia=sobre.referencia,
        estado_proveedor="signed",
        email_firmante="ana@cliente.com",
        id_externo="f1",
    )
    fir.archivar_firmado(uow, sobre.id, documento_firmado_id="doc-2")
    assert sobre.documento_id == "doc-1"
    assert sobre.documento_firmado_id == "doc-2"


def test_no_se_archiva_el_firmado_de_un_sobre_abierto(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """Es cómo se acaba con un contrato a medio firmar en el expediente, con toda
    la apariencia de estar cerrado."""
    sobre = _sobre(uow)
    fir.enviar(uow, sobre.id)
    with pytest.raises(Conflicto) as e:
        fir.archivar_firmado(uow, sobre.id, documento_firmado_id="doc-2")
    assert e.value.error_code == "firma.sobre_no_completado"


def test_un_firmado_sin_origen_se_dice(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """Existe en el corpus y no aparece en ninguna ficha: si no se dijera, nadie
    lo echaría de menos hasta que hiciera falta."""
    sobre = _sobre(uow)
    fir.enviar(uow, sobre.id)
    fir.ingerir(
        uow,
        proveedor="firmafacil",
        referencia=sobre.referencia,
        estado_proveedor="signed",
        email_firmante="ana@cliente.com",
        id_externo="f1",
    )
    salida = fir.archivar_firmado(uow, sobre.id, documento_firmado_id="doc-2")
    assert salida["sin_origen"] is True


# ── Recordatorios, cancelación y caducidad ────────────────────────────────


def test_no_se_recuerda_dos_veces_seguidas(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """Tres correos en un minuto no hacen que firme antes: hacen que marque el
    remitente como no deseado y deje de recibir los siguientes."""
    sobre = _sobre(uow)
    fir.enviar(uow, sobre.id)
    assert fir.recordar(uow, sobre.id)["recordados"] == ["ana@cliente.com"]
    with pytest.raises(Conflicto) as e:
        fir.recordar(uow, sobre.id)
    assert e.value.error_code == "firma.recordatorio_demasiado_pronto"


def test_un_sobre_terminado_no_se_recuerda(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    sobre = _sobre(uow)
    fir.enviar(uow, sobre.id)
    fir.cancelar(uow, sobre.id, motivo="se rehace")
    with pytest.raises(Conflicto):
        fir.recordar(uow, sobre.id)


def test_cancelar_exige_motivo(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """Al cliente le llegó un correo que va a dejar de funcionar, y sin motivo
    nadie sabe por qué: la pregunta llega por teléfono."""
    sobre = _sobre(uow)
    fir.enviar(uow, sobre.id)
    with pytest.raises(ErrorValidacion) as e:
        fir.cancelar(uow, sobre.id, motivo="   ")
    assert e.value.error_code == "firma.cancelacion_sin_motivo"


def test_lo_caducado_se_marca(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """Un sobre que sigue diciendo «en curso» tres meses después aparece como
    negocio vivo esperando una firma que ya no va a llegar."""
    sobre = _sobre(uow)
    fir.enviar(uow, sobre.id)
    sobre.caduca_at = _ahora() - timedelta(days=1)
    uow.db.flush()
    salida = fir.caducar_vencidos(uow, uow.tenant_id)
    assert salida["caducados"] == [sobre.referencia]


def test_sin_sobres_abiertos_no_se_dice_que_todo_esta_firmado(
    uow: UnidadDeTrabajo,
) -> None:
    assert fir.caducar_vencidos(uow, uow.tenant_id)["medible"] is False


# ── El panel (CRM-06.01.02.10) ────────────────────────────────────────────


def test_el_panel_ordena_por_antiguedad(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """Una lista por fecha entierra lo viejo debajo de lo nuevo, que es justo al
    revés de lo que hace falta."""
    viejo = _sobre(uow, asunto="viejo")
    fir.enviar(uow, viejo.id)
    viejo.enviado_at = _ahora() - timedelta(days=20)
    nuevo = _sobre(uow, asunto="nuevo")
    fir.enviar(uow, nuevo.id)
    uow.db.flush()
    assert fir.panel(uow.db, uow.tenant_id)["sobres"][0]["asunto"] == "viejo"


def test_el_panel_dice_a_quien_se_espera(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """Sin el nombre de quien tiene que firmar, el panel dice que algo está parado
    y no qué hacer al respecto."""
    sobre = _sobre(uow)
    fir.enviar(uow, sobre.id)
    fila = fir.panel(uow.db, uow.tenant_id)["sobres"][0]
    assert fila["esperando_a"] == ["ana@cliente.com"]


def test_el_panel_distingue_el_que_nadie_ha_abierto(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    """El primero es un correo que no llegó y el segundo una decisión que no se
    toma, y se persiguen de forma distinta."""
    sin_abrir = _sobre(uow, asunto="sin abrir")
    fir.enviar(uow, sin_abrir.id)
    abierto = _sobre(uow, asunto="abierto")
    fir.enviar(uow, abierto.id)
    fir.ingerir(
        uow,
        proveedor="firmafacil",
        referencia=abierto.referencia,
        estado_proveedor="opened",
        email_firmante="ana@cliente.com",
        id_externo="o1",
    )
    por_asunto = {s["asunto"]: s for s in fir.panel(uow.db, uow.tenant_id)["sobres"]}
    assert por_asunto["sin abrir"]["nadie_lo_ha_abierto"] is True
    assert por_asunto["abierto"]["nadie_lo_ha_abierto"] is False


def test_lo_terminado_no_sale_en_el_panel(uow: UnidadDeTrabajo, proveedor: Any) -> None:
    sobre = _sobre(uow)
    fir.enviar(uow, sobre.id)
    fir.cancelar(uow, sobre.id, motivo="ya no hace falta")
    assert fir.panel(uow.db, uow.tenant_id)["sobres"] == []
