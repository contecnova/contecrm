"""Canales de ejecución, consentimiento y entregabilidad
(CRM-02.03.02, CRM-02.03.01.02, CRM-02.03.01.03, CRM-02.03.01.06).

Las pruebas van detrás de los cinco sitios donde el marketing multicanal acaba en
una sanción o en una campaña que nadie ve:

  * el SMS a quien solo aceptó el correo,
  * la baja que no se aplica porque llegó escrita de otra manera,
  * el mensaje de WhatsApp fuera de la ventana, que no falla y no llega,
  * el formulario que recoge un teléfono y da por consentido el SMS,
  * y el dominio sin autenticar, que no rebota: llega a basura.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado

from services.marketing import canales as can


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _canal(uow: UnidadDeTrabajo, **kw: Any) -> can.Canal:
    base: dict[str, Any] = {
        "clave": "sms-es",
        "nombre": "SMS España",
        "tipo": "sms",
        "silencio_desde": 21,
        "silencio_hasta": 9,
    }
    base.update(kw)
    fila = can.Canal(tenant_id=uow.tenant_id, **base)
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _mediodia() -> datetime:
    return datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)


# ── Consentimiento por canal (CRM-02.03.02.01) ────────────────────────────


def test_aceptar_el_correo_no_es_aceptar_el_sms(uow: UnidadDeTrabajo) -> None:
    """Mandarle un SMS «porque ya nos dio permiso» es exactamente lo que sanciona
    un regulador."""
    _canal(uow)
    can.fijar_consentimiento(uow, canal="email", destino="ana@b.c", acepta=True)
    salida = can.comprobar_envio(
        uow.db, uow.tenant_id, canal_clave="sms-es", destino="ana@b.c", ahora=_mediodia()
    )
    assert salida["se_puede_mandar"] is False
    assert any("consentimiento" in m for m in salida["motivos"])


def test_con_consentimiento_del_canal_si_se_manda(uow: UnidadDeTrabajo) -> None:
    _canal(uow)
    can.fijar_consentimiento(uow, canal="sms", destino="+34600", acepta=True)
    salida = can.comprobar_envio(
        uow.db, uow.tenant_id, canal_clave="sms-es", destino="+34600", ahora=_mediodia()
    )
    assert salida["se_puede_mandar"] is True


def test_un_canal_inventado_se_rechaza(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion):
        can.fijar_consentimiento(uow, canal="paloma", destino="x", acepta=True)


def test_el_consentimiento_guarda_su_prueba(uow: UnidadDeTrabajo) -> None:
    """Sin ella, la respuesta a «¿quién autorizó esto?» es «no consta», que ante
    un regulador equivale a «nadie»."""
    fila = can.fijar_consentimiento(
        uow,
        canal="sms",
        destino="+34600",
        acepta=True,
        origen="landing:alta",
        prueba="Formulario de alta, casilla marcada",
    )
    assert fila.prueba
    assert fila.origen == "landing:alta"


# ── La baja (CRM-02.03.02.01) ─────────────────────────────────────────────


def test_la_baja_se_reconoce_escrita_de_cualquier_forma() -> None:
    """Quien escribe «BAJA» desde el móvil manda tantas variantes como teclados
    hay, y exigir una exacta deja sin efecto una baja que sí se pidió."""
    for texto in ("BAJA", "baja", "Baja por favor", "  stop  ", "CANCELAR", "bajá"):
        assert can.es_palabra_de_baja(texto) is True
    assert can.es_palabra_de_baja("me interesa, bajad el precio") is False


def test_una_respuesta_de_baja_corta_el_canal(uow: UnidadDeTrabajo) -> None:
    _canal(uow)
    can.fijar_consentimiento(uow, canal="sms", destino="+34600", acepta=True)
    salida = can.procesar_entrante(uow, canal="sms", destino="+34600", texto="BAJA")
    assert salida["baja"] is True
    comprobacion = can.comprobar_envio(
        uow.db, uow.tenant_id, canal_clave="sms-es", destino="+34600", ahora=_mediodia()
    )
    assert comprobacion["se_puede_mandar"] is False


def test_cada_canal_dice_como_se_da_de_baja(uow: UnidadDeTrabajo) -> None:
    """Tratarlos igual produce el mensaje que no se puede parar."""
    assert "palabra" in can.BAJAS_POR_CANAL["sms"]
    assert "pie" in can.BAJAS_POR_CANAL["email"]
    assert can.BAJAS_POR_CANAL["whatsapp"] != can.BAJAS_POR_CANAL["sms"]


# ── Horas de silencio (CRM-02.03.02.01) ───────────────────────────────────


def test_no_se_manda_un_sms_de_madrugada(uow: UnidadDeTrabajo) -> None:
    """Despierta a alguien, y el coste de eso no es una baja: es una queja."""
    _canal(uow)
    can.fijar_consentimiento(uow, canal="sms", destino="+34600", acepta=True)
    noche = datetime(2026, 3, 4, 23, 30, tzinfo=timezone.utc)
    salida = can.comprobar_envio(
        uow.db, uow.tenant_id, canal_clave="sms-es", destino="+34600", ahora=noche
    )
    assert salida["se_puede_mandar"] is False
    assert any("calla" in m for m in salida["motivos"])


def test_el_correo_no_tiene_hora_de_silencio(uow: UnidadDeTrabajo) -> None:
    """Un correo a las tres de la mañana no despierta a nadie: espera en la
    bandeja."""
    _canal(uow, clave="boletin", nombre="Boletín", tipo="email")
    can.fijar_consentimiento(uow, canal="email", destino="ana@b.c", acepta=True)
    noche = datetime(2026, 3, 4, 3, 0, tzinfo=timezone.utc)
    salida = can.comprobar_envio(
        uow.db, uow.tenant_id, canal_clave="boletin", destino="ana@b.c", ahora=noche
    )
    assert salida["se_puede_mandar"] is True


# ── WhatsApp: ventana y plantillas (CRM-02.03.02.02) ──────────────────────


def test_fuera_de_la_ventana_hace_falta_plantilla(uow: UnidadDeTrabajo) -> None:
    """Mandar texto libre fuera de ella no da error: el proveedor lo descarta y el
    mensaje no llega nunca, que es peor porque nadie se entera."""
    _canal(uow, clave="wa", nombre="WhatsApp", tipo="whatsapp")
    can.fijar_consentimiento(uow, canal="whatsapp", destino="+34600", acepta=True)
    salida = can.comprobar_envio(
        uow.db, uow.tenant_id, canal_clave="wa", destino="+34600", ahora=_mediodia()
    )
    assert salida["se_puede_mandar"] is False
    assert salida["necesita_plantilla"] is True


def test_quien_escribe_abre_la_ventana(uow: UnidadDeTrabajo) -> None:
    """El que escribe autoriza a contestarle sin plantilla."""
    _canal(uow, clave="wa", nombre="WhatsApp", tipo="whatsapp")
    can.fijar_consentimiento(uow, canal="whatsapp", destino="+34600", acepta=True)
    can.procesar_entrante(uow, canal="whatsapp", destino="+34600", texto="hola, una duda")
    salida = can.comprobar_envio(
        uow.db, uow.tenant_id, canal_clave="wa", destino="+34600", ahora=_mediodia()
    )
    assert salida["ventana_abierta"] is True
    assert salida["se_puede_mandar"] is True


def test_una_plantilla_no_aprobada_no_se_manda(uow: UnidadDeTrabajo, db: Any) -> None:
    """El proveedor la descarta sin avisar y el mensaje no llega."""
    _canal(uow, clave="wa", nombre="WhatsApp", tipo="whatsapp")
    can.fijar_consentimiento(uow, canal="whatsapp", destino="+34600", acepta=True)
    db.add(
        can.PlantillaCanal(
            tenant_id=uow.tenant_id, canal="whatsapp", clave="aviso", estado="pendiente"
        )
    )
    db.flush()
    salida = can.comprobar_envio(
        uow.db,
        uow.tenant_id,
        canal_clave="wa",
        destino="+34600",
        plantilla="aviso",
        ahora=_mediodia(),
    )
    assert salida["se_puede_mandar"] is False
    assert any("descartaría" in m for m in salida["motivos"])


def test_una_plantilla_aprobada_si(uow: UnidadDeTrabajo, db: Any) -> None:
    _canal(uow, clave="wa", nombre="WhatsApp", tipo="whatsapp")
    can.fijar_consentimiento(uow, canal="whatsapp", destino="+34600", acepta=True)
    db.add(
        can.PlantillaCanal(
            tenant_id=uow.tenant_id, canal="whatsapp", clave="aviso", estado="aprobada"
        )
    )
    db.flush()
    salida = can.comprobar_envio(
        uow.db,
        uow.tenant_id,
        canal_clave="wa",
        destino="+34600",
        plantilla="aviso",
        ahora=_mediodia(),
    )
    assert salida["se_puede_mandar"] is True


# ── Landings (CRM-02.03.02.06) ────────────────────────────────────────────


def _landing(uow: UnidadDeTrabajo, **kw: Any) -> can.Landing:
    base: dict[str, Any] = {
        "clave": "alta",
        "titulo": "Pide una demo",
        "campos": [
            {"clave": "email", "obligatorio": True},
            {"clave": "telefono", "obligatorio": False},
        ],
        "pide_consentimiento": ["email"],
    }
    base.update(kw)
    fila = can.Landing(tenant_id=uow.tenant_id, **base)
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_recoger_un_telefono_no_autoriza_a_mandar_sms(uow: UnidadDeTrabajo) -> None:
    """Dar por consentido lo que solo se ha escrito en una casilla es justo la
    práctica que sanciona un regulador."""
    _landing(uow)
    salida = can.registrar_envio_landing(
        uow,
        "alta",
        datos={"email": "ana@b.c", "telefono": "+34600"},
        consentimientos={"email": True, "sms": True},
    )
    assert salida["consentimientos_guardados"] == ["email"]
    assert salida["consentimientos_ignorados"] == ["sms"]


def test_un_campo_obligatorio_que_falta_se_caza(uow: UnidadDeTrabajo) -> None:
    _landing(uow)
    with pytest.raises(ErrorValidacion) as e:
        can.registrar_envio_landing(uow, "alta", datos={"telefono": "+34600"})
    assert e.value.detalle["faltan"] == ["email"]


def test_el_prerelleno_solo_devuelve_lo_que_la_landing_pide(uow: UnidadDeTrabajo, db: Any) -> None:
    """Pre-rellenar con datos que no estaba pidiendo le enseña a quien lo abre —o a
    quien recibió el enlace reenviado— lo que sabemos de otra persona."""
    from services.marketing.modelos import PerfilMarketing

    _landing(uow)
    db.add(
        PerfilMarketing(
            tenant_id=uow.tenant_id,
            objeto="contacto",
            objeto_id=uuid4(),
            email="ana@b.c",
            nombre="Ana",
            telefono="+34600",
            cargo="Directora",
        )
    )
    db.flush()
    salida = can.prerelleno(db, uow.tenant_id, "alta", "ana@b.c")
    assert set(salida["valores"]) == {"email", "telefono"}
    assert "cargo" not in salida["valores"]


def test_a_quien_no_conocemos_no_se_le_prerellena_nada(uow: UnidadDeTrabajo, db: Any) -> None:
    _landing(uow)
    assert can.prerelleno(db, uow.tenant_id, "alta", "nadie@b.c")["conocido"] is False


# ── Personalización (CRM-02.03.01.02) ─────────────────────────────────────


def test_un_token_sin_dato_y_sin_defecto_se_dice() -> None:
    """«Hola » es lo que se manda cuando el dato falta y nadie lo previó."""
    salida = can.personalizar("Hola {{nombre}}", {})
    assert salida["sin_dato"] == ["nombre"]
    assert salida["listo"] is False


def test_el_valor_por_defecto_salva_el_saludo() -> None:
    salida = can.personalizar("Hola {{nombre|cliente}}", {})
    assert salida["texto"] == "Hola cliente"
    assert salida["listo"] is True


def test_el_condicional_quita_el_bloque_si_no_hay_dato() -> None:
    salida = can.personalizar("Hola{% si empresa %}, de {{empresa}}{% fin %}.", {})
    assert salida["texto"] == "Hola."


def test_el_condicional_lo_deja_si_lo_hay() -> None:
    salida = can.personalizar("Hola{% si empresa %}, de {{empresa}}{% fin %}.", {"empresa": "Acme"})
    assert salida["texto"] == "Hola, de Acme."


def test_los_tokens_anidados_se_leen_por_camino() -> None:
    salida = can.personalizar("{{cuenta.nombre}}", {"cuenta": {"nombre": "Acme"}})
    assert salida["texto"] == "Acme"


# ── Entregabilidad (CRM-02.03.01.03) ──────────────────────────────────────


def _dominio(uow: UnidadDeTrabajo, **kw: Any) -> can.DominioEnvio:
    base: dict[str, Any] = {"dominio": "acme.com", "spf": True, "dkim": True, "dmarc": "reject"}
    base.update(kw)
    fila = can.DominioEnvio(tenant_id=uow.tenant_id, **base)
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_un_dominio_completo_esta_listo(uow: UnidadDeTrabajo) -> None:
    _dominio(uow)
    assert can.estado_dominio(uow.db, uow.tenant_id, "acme.com")["listo"] is True


def test_sin_dkim_no_esta_listo_y_se_dice_por_que(uow: UnidadDeTrabajo) -> None:
    """No rebota: llega a basura, y eso aparece como una campaña que nadie abrió."""
    _dominio(uow, dkim=False)
    salida = can.estado_dominio(uow.db, uow.tenant_id, "acme.com")
    assert salida["listo"] is False
    assert any("DKIM" in f for f in salida["le_falta"])


def test_dmarc_en_none_se_señala(uow: UnidadDeTrabajo) -> None:
    """Detecta pero no bloquea: sirve para medir, no para proteger."""
    _dominio(uow, dmarc="none")
    salida = can.estado_dominio(uow.db, uow.tenant_id, "acme.com")
    assert any("none" in f for f in salida["le_falta"])


def test_el_calentamiento_pone_tope(uow: UnidadDeTrabajo) -> None:
    """Una IP nueva que manda cien mil el primer día se quema, y quemarla cuesta
    semanas."""
    _dominio(uow, calentamiento_desde=datetime.now(timezone.utc) - timedelta(days=2))
    salida = can.estado_dominio(uow.db, uow.tenant_id, "acme.com")
    assert salida["calentando"] is True
    assert salida["tope_hoy"] == can.CALENTAMIENTO[2]


def test_un_dominio_sin_configurar_da_404(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(NoEncontrado):
        can.estado_dominio(uow.db, uow.tenant_id, "noexiste.com")


# ── Revisión previa (CRM-02.03.01.06) ─────────────────────────────────────


def test_la_revision_avisa_pero_nunca_bloquea() -> None:
    """Un sistema que bloquea por una palabra acaba con la gente escribiendo
    «gr4tis», que es peor para el filtro y para quien lee."""
    salida = can.revisar_antes_de_mandar("GRATIS!!! oferta limitada", "haz clic aquí")
    assert salida["cuantos"] >= 3
    assert salida["bloquea"] is False


def test_un_asunto_largo_se_señala() -> None:
    """En el móvil se corta sobre los 40, y lo que importa suele estar al final."""
    salida = can.revisar_antes_de_mandar("x" * 80, "hola")
    assert any(a["senal"] == "asunto largo" for a in salida["avisos"])


def test_un_token_sin_sustituir_se_caza_antes_de_mandar() -> None:
    salida = can.revisar_antes_de_mandar("Hola", "Hola {{nombre}}")
    assert any(a["senal"] == "token sin sustituir" for a in salida["avisos"])


def test_un_dominio_sin_autenticar_se_señala_en_la_revision() -> None:
    salida = can.revisar_antes_de_mandar("Hola", "texto", dominio_listo=False)
    assert any("basura" in a["porque"] for a in salida["avisos"])


def test_un_correo_limpio_no_tiene_avisos() -> None:
    salida = can.revisar_antes_de_mandar("Tu pedido va en camino", "Hola Ana, ya salió.")
    assert salida["avisos"] == []


# ── Mejor hora (CRM-02.02.02.05) ──────────────────────────────────────────


def test_con_pocas_aperturas_no_se_recomienda_hora(uow: UnidadDeTrabajo) -> None:
    """Con tres aperturas, la hora que salga es la de esos tres correos y no un
    hábito."""
    salida = can.mejor_hora(uow.db, uow.tenant_id, uuid4())
    assert salida["hora"] is None
    assert salida["concluyente"] is False


def test_con_aperturas_suficientes_sale_la_hora(uow: UnidadDeTrabajo, db: Any) -> None:
    from services.marketing.campanas import Campana, MiembroCampana

    # Una persona está UNA vez en cada campaña, así que doce aperturas son doce
    # campañas. Eso es justo lo que hace que esta señal sea débil para la mayoría
    # de los contactos, y está dicho en el manual.
    quien = uuid4()
    for i in range(12):
        campana = Campana(tenant_id=uow.tenant_id, clave=f"c{i}", nombre=f"C{i}", nivel="campana")
        db.add(campana)
        db.flush()
        db.add(
            MiembroCampana(
                tenant_id=uow.tenant_id,
                campana_id=campana.id,
                objeto_id=quien,
                estado="abierto",
                estado_at=datetime(2026, 3, 4, 10, 0, tzinfo=timezone.utc),
            )
        )
    db.flush()
    salida = can.mejor_hora(db, uow.tenant_id, quien)
    assert salida["concluyente"] is True
    assert salida["hora"] == 10
