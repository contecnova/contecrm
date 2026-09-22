"""Consentimiento, derechos del interesado y cumplimiento
(CRM-02.04.02.01 a .05, CRM-07.03.01.02, CRM-07.03.01.08, CRM-07.03.02.09,
CRM-07.03.02.10, CRM-02.04.01.03).

Todo lo de aquí existe para poder **demostrar algo dos años después**, así que
las pruebas van detrás de las formas de acabar sin poder demostrarlo:

  * el «no contactar» escrito en un campo de texto que la siguiente importación
    pisa,
  * la limitación que se queda en el servicio que la anotó mientras otro sigue
    enviando,
  * el doble opt-in que registra el alta como válida y manda mientras tanto,
  * el consentimiento de cookies sobre un aviso que después cambió,
  * el archivado que en realidad es una purga porque nadie puede leerlo,
  * y el panel en verde porque no hay nada declarado.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion

from services.marketing import consentimiento as cons
from services.party import limitacion as lim


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _contacto(db: Any, tenant_id: UUID, **extra: Any) -> Any:
    from services.party.modelos import Contacto

    base: dict[str, Any] = {
        "tenant_id": tenant_id,
        "nombre": "Ana",
        "apellidos": "García",
        "nombre_completo": "Ana García",
        "clave_canonica": f"ana-{uuid4().hex[:8]}",
        "email": "ana@example.com",
    }
    base.update(extra)
    fila = Contacto(**base)
    db.add(fila)
    db.flush()
    return fila


# ── Limitación de tratamiento (CRM-02.04.02.05) ───────────────────────────


@pytest.mark.db
def test_limitar_sin_decir_que_limita_todo_lo_limitable(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es lo que pide quien invoca el artículo 18 sin entrar en detalle.
    Interpretar la lista vacía como «ninguno» registraría una limitación que no
    limita nada."""
    contacto = _contacto(uow.db, uow.tenant_id)
    salida = lim.limitar(uow, contacto_id=contacto.id)
    assert set(salida["limitados"]) == set(lim.TRATAMIENTOS)


@pytest.mark.db
def test_la_limitacion_dice_lo_que_NO_para(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Prometer un bloqueo total sería prometer lo que la ley no pide y el
    sistema no puede dar: la facturación no se para por oponerse a la publicidad."""
    contacto = _contacto(uow.db, uow.tenant_id)
    salida = lim.limitar(uow, contacto_id=contacto.id, tratamientos=["marketing"])
    assert "obligacion_legal" in salida["no_se_paran"]
    assert "reclamaciones" in salida["no_se_paran"]


@pytest.mark.db
def test_un_tratamiento_inventado_no_se_limita_en_falso(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Limitar algo que el sistema no sabe comprobar dejaría al interesado
    creyendo que está protegido."""
    contacto = _contacto(uow.db, uow.tenant_id)
    with pytest.raises(ErrorValidacion) as fallo:
        lim.limitar(uow, contacto_id=contacto.id, tratamientos=["lo_que_sea"])
    assert fallo.value.error_code == "limitacion.tratamiento_desconocido"


@pytest.mark.db
def test_consultar_un_tratamiento_desconocido_no_dice_que_si(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Dar por permitido lo que no se sabe comprobar es la forma silenciosa de
    saltarse una limitación."""
    contacto = _contacto(uow.db, uow.tenant_id)
    salida = lim.esta_limitado(uow.db, uow.tenant_id, contacto.id, tratamiento="tratamiento_raro")
    assert salida["comprobado"] is False


@pytest.mark.db
def test_levantar_sin_motivo_se_rechaza(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Una limitación que desaparece sin rastro es peor que no haberla puesto:
    nadie puede decir desde cuándo se volvió a tratar."""
    contacto = _contacto(uow.db, uow.tenant_id)
    lim.limitar(uow, contacto_id=contacto.id)
    with pytest.raises(ErrorValidacion) as fallo:
        lim.levantar(uow, contacto_id=contacto.id, motivo="  ")
    assert fallo.value.error_code == "limitacion.sin_motivo"


@pytest.mark.db
def test_la_limitacion_avisa_a_quien_envia(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """La limitación que se queda en el servicio que la anotó no limita nada:
    quien manda los correos es `marketing`, y no puede leer este esquema.

    El evento lleva las **direcciones**, porque allí se suprime por dirección y
    no por identificador: la misma persona suele estar en tres fichas duplicadas.
    """
    from crmcore.bus.modelos import EventoSaliente
    from sqlalchemy import select

    contacto = _contacto(uow.db, uow.tenant_id, email="ana@example.com", movil="600111222")
    lim.limitar(uow, contacto_id=contacto.id, tratamientos=["marketing"])
    # Los eventos se escriben en la tabla de salida al cerrar la transacción, no
    # al emitirlos: es lo que garantiza que un evento nunca cuente algo que la
    # transacción deshizo. `volcar` es el mismo camino que usa el ejecutor de
    # trabajos, que tampoco puede esperar al final.
    uow.volcar()
    uow.db.flush()

    evento = (
        uow.db.execute(
            select(EventoSaliente).where(EventoSaliente.tipo == "contact.processing_limited")
        )
        .scalars()
        .first()
    )
    assert evento is not None
    destinos = evento.sobre["data"]["destinos"]
    assert {"canal": "email", "destino": "ana@example.com"} in destinos
    assert any(d["canal"] == "sms" for d in destinos)


# ── Derechos (CRM-02.04.02.04) ────────────────────────────────────────────


def _solicitud(db: Any, tenant_id: UUID, tipo: str, email: str = "ana@example.com") -> Any:
    from services.party import servicio as svc

    fila = svc.crear_solicitud_derechos(db, tenant_id=tenant_id, email_solicitante=email, tipo=tipo)
    db.flush()
    return fila


@pytest.mark.db
def test_la_rectificacion_guarda_lo_que_habia_antes(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin el valor anterior, una rectificación es indistinguible de una edición
    cualquiera — y lo que hay que poder demostrar es justo que se corrigió lo que
    el interesado señaló."""
    from services.party import derechos

    _contacto(db, tenant_id, nombre="Ana", apellidos="Garcia")
    solicitud = _solicitud(db, tenant_id, "rectificacion")

    salida = derechos.ejecutar_rectificacion(
        db, solicitud.id, cambios={"apellidos": "García Pérez"}
    )
    tocado = salida["contenido"]["rectificados"][0]
    assert tocado["antes"]["apellidos"] == "Garcia"
    assert salida["evidencia"]["huella"]


@pytest.mark.db
def test_no_se_rectifica_un_importe_desde_un_derecho(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sería usar un derecho para saltarse las reglas de negocio."""
    from services.party import derechos

    _contacto(db, tenant_id)
    solicitud = _solicitud(db, tenant_id, "rectificacion")
    with pytest.raises(ErrorValidacion) as fallo:
        derechos.ejecutar_rectificacion(db, solicitud.id, cambios={"importe": 100})
    assert fallo.value.error_code == "derechos.campo_no_rectificable"


@pytest.mark.db
def test_una_rectificacion_vacia_no_rectifica_nada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.party import derechos

    _contacto(db, tenant_id)
    solicitud = _solicitud(db, tenant_id, "rectificacion")
    with pytest.raises(ErrorValidacion):
        derechos.ejecutar_rectificacion(db, solicitud.id, cambios={})


@pytest.mark.db
def test_la_portabilidad_dice_que_queda_fuera(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Entregar un scoring interno como «sus datos» regala el trabajo propio y da
    por bueno ante el interesado un juicio que nunca pidió."""
    from services.party import derechos

    _contacto(db, tenant_id)
    solicitud = _solicitud(db, tenant_id, "portabilidad")
    salida = derechos.ejecutar_portabilidad(db, solicitud.id)
    assert "puntuaciones_y_segmentos" in salida["fuera_del_derecho"]
    assert "lectura mecánica" in salida["formato"]


@pytest.mark.db
def test_la_oposicion_se_traduce_en_una_limitacion_de_verdad(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La oposición se resuelve casi siempre anotando «no contactar» en un campo
    de texto, y eso dura hasta la siguiente importación."""
    from services.party import derechos

    contacto = _contacto(db, tenant_id)
    solicitud = _solicitud(db, tenant_id, "oposicion")
    derechos.ejecutar_oposicion(db, solicitud.id)

    estado = lim.esta_limitado(db, tenant_id, contacto.id, tratamiento="marketing")
    assert estado["limitado"] is True


# ── Doble opt-in (CRM-02.04.02.02) ────────────────────────────────────────


@pytest.mark.db
def test_un_alta_sin_confirmar_no_es_un_alta(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Registrarla como válida y mandar mientras tanto da apariencia de rigor a
    lo contrario, que es peor que no tener doble opt-in."""
    salida = cons.pedir_confirmacion(
        uow, destino="ana@example.com", texto_aceptado="Acepto recibir novedades"
    )
    assert salida["se_le_puede_escribir"] is False
    assert salida["estado"] == "pendiente"


@pytest.mark.db
def test_sin_el_texto_aceptado_no_se_pide_confirmacion(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Sin él, la prueba de este consentimiento es una casilla marcada, que no
    prueba nada."""
    with pytest.raises(ErrorValidacion) as fallo:
        cons.pedir_confirmacion(uow, destino="ana@example.com", texto_aceptado="")
    assert fallo.value.error_code == "optin.sin_texto"


@pytest.mark.db
def test_confirmar_deja_el_canal_aceptado(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    from sqlalchemy import select

    from services.marketing.canales import ConsentimientoCanal

    pedido = cons.pedir_confirmacion(
        uow, destino="ana@example.com", texto_aceptado="Acepto recibir novedades"
    )
    salida = cons.confirmar(uow, token=pedido["token"])
    assert salida["se_le_puede_escribir"] is True

    fila = (
        uow.db.execute(
            select(ConsentimientoCanal).where(ConsentimientoCanal.destino == "ana@example.com")
        )
        .scalars()
        .first()
    )
    assert fila is not None and fila.acepta is True
    assert "Confirmado el" in (fila.prueba or "")


@pytest.mark.db
def test_un_enlace_caducado_no_confirma(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Un enlace eterno acaba confirmando altas que nadie recuerda haber pedido,
    y ese consentimiento no sostiene nada."""
    pedido = cons.pedir_confirmacion(
        uow, destino="ana@example.com", texto_aceptado="Acepto", horas_validez=1
    )
    from services.marketing.consentimiento import ConfirmacionOptin

    fila = uow.db.get(ConfirmacionOptin, UUID(pedido["confirmacion_id"]))
    fila.caduca_at = datetime.now(timezone.utc) - timedelta(hours=2)
    uow.db.flush()

    with pytest.raises(Conflicto) as fallo:
        cons.confirmar(uow, token=pedido["token"])
    assert fallo.value.error_code == "optin.caducado"


@pytest.mark.db
def test_confirmar_dos_veces_no_mueve_la_fecha(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """La gente pincha el enlace otra vez. Lo que no puede es mover la fecha:
    la que prueba el consentimiento es la primera."""
    pedido = cons.pedir_confirmacion(uow, destino="ana@example.com", texto_aceptado="Acepto")
    cons.confirmar(uow, token=pedido["token"])
    segunda = cons.confirmar(uow, token=pedido["token"])
    assert segunda["ya_estaba"] is True


# ── Cookies (CRM-07.03.01.08) ─────────────────────────────────────────────


@pytest.mark.db
def test_sin_decision_previa_no_se_rastrea(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """El silencio no es un sí: tratarlo como tal es la infracción más común de
    todas."""
    salida = cons.puede_rastrear(uow.db, uow.tenant_id, visitante="v-1", categoria="analitica")
    assert salida["puede"] is False
    assert "silencio no es un sí" in salida["porque"]


@pytest.mark.db
def test_aceptar_una_version_del_aviso_no_vale_para_otra(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es exactamente lo que se discute cuando llega una reclamación."""
    cons.registrar_cookies(
        uow,
        visitante="v-1",
        categorias={"analitica": True},
        version_aviso="2026-01",
    )
    salida = cons.puede_rastrear(
        uow.db, uow.tenant_id, visitante="v-1", categoria="analitica", version_aviso="2026-09"
    )
    assert salida["puede"] is False
    assert "no prueba nada sobre el nuevo" in salida["porque"]


@pytest.mark.db
def test_las_necesarias_no_se_ofrecen_como_interruptor(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Un botón que no apaga nada hace que el usuario deje de creerse el panel
    entero."""
    salida = cons.registrar_cookies(
        uow,
        visitante="v-2",
        categorias={"necesarias": False, "publicidad": True},
        version_aviso="2026-09",
    )
    assert salida["categorias"]["necesarias"] is True


@pytest.mark.db
def test_sin_version_del_aviso_no_se_guarda_la_decision(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        cons.registrar_cookies(
            uow, visitante="v-3", categorias={"analitica": True}, version_aviso=""
        )
    assert fallo.value.error_code == "cookies.sin_version"


# ── Cumplimiento del contenido (CRM-02.04.01.03) ──────────────────────────


@pytest.mark.db
def test_falta_el_texto_obligatorio_y_se_dice(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Faltar la dirección postal o el enlace de baja es lo que convierte un
    envío legítimo en spam a efectos legales."""
    cons.declarar_regla(uow, pais="ES", exige_textos=["darse de baja"])
    salida = cons.comprobar_contenido(
        uow.db, uow.tenant_id, cuerpo="Hola, mira nuestra oferta", pais="ES"
    )
    assert salida["se_puede_mandar"] is False
    assert any("darse de baja" in m for m in salida["motivos"])


@pytest.mark.db
def test_una_plantilla_bloqueada_no_se_puede_editar(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Si el bloqueo fuese un aviso, se ignoraría el día que hay prisa — justo el
    día en que se manda a otro país el texto que allí no cumple."""
    cons.declarar_regla(uow, pais="DE", plantillas_bloqueadas=["aviso_legal"])
    salida = cons.comprobar_contenido(
        uow.db,
        uow.tenant_id,
        cuerpo="Texto cambiado",
        plantilla="aviso_legal",
        pais="DE",
        cuerpo_de_la_plantilla="Texto original aprobado",
    )
    assert salida["se_puede_mandar"] is False
    assert salida["plantilla_bloqueada"] is True


@pytest.mark.db
def test_sin_reglas_declaradas_no_se_dice_que_cumple(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Para que nadie lea un «se puede mandar» como una aprobación de
    cumplimiento."""
    salida = cons.comprobar_contenido(uow.db, uow.tenant_id, cuerpo="Hola", pais="FR")
    assert salida["comprobado"] is False
    assert salida["aviso"]


# ── Archivado consultable (CRM-07.03.01.02) ───────────────────────────────


@pytest.mark.db
def test_lo_archivado_se_puede_leer(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Es lo que separa archivar de purgar: si el dato archivado no se pudiera
    consultar, esto sería una purga con otro nombre."""
    from crmcore.datos import archivado as arch

    import services.party.retencion  # noqa: F401 — declara las clases de dato
    from services.party.modelos import Actividad

    vieja = Actividad(
        tenant_id=tenant_id,
        tipo="tarea",
        asunto="De hace años",
        estado="completada",
        completada_at=datetime.now(timezone.utc) - timedelta(days=2000),
    )
    db.add(vieja)
    db.flush()

    informe = arch.archivar(
        db,
        tenant_id=tenant_id,
        clase="actividades",
        antes_de=datetime.now(timezone.utc) - timedelta(days=365),
        simular=False,
    )
    assert informe.archivadas >= 1

    encontrado = arch.consultar(db, tenant_id, clase="actividades")
    assert encontrado["cuantas"] >= 1
    assert encontrado["filas"][0]["contenido"]["asunto"] == "De hace años"


@pytest.mark.db
def test_el_archivado_simula_por_defecto(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Lo que va a mover diez mil filas hay que poder verlo antes, no después."""
    from crmcore.datos import archivado as arch

    import services.party.retencion  # noqa: F401

    informe = arch.archivar(
        db,
        tenant_id=tenant_id,
        clase="actividades",
        antes_de=datetime.now(timezone.utc),
    )
    assert informe.simulado is True
    assert informe.archivadas == 0


@pytest.mark.db
def test_archivar_una_clase_inventada_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Archivar por nombre de tabla dejaría fuera el criterio de fecha, que no
    siempre es la de creación."""
    from crmcore.datos import archivado as arch

    with pytest.raises(ErrorValidacion) as fallo:
        arch.archivar(
            db, tenant_id=tenant_id, clase="lo_que_sea", antes_de=datetime.now(timezone.utc)
        )
    assert fallo.value.error_code == "archivado.clase_desconocida"


# ── Matriz de permisos (CRM-07.03.02.09) ──────────────────────────────────


def test_la_matriz_expande_los_comodines() -> None:
    """Un rol con `*:*` no puede aparecer con un asterisco: el asterisco es donde
    se esconden los privilegios que nadie contó."""
    from crmcore.authz.matriz import matriz
    from crmcore.authz.rbac import ROLES_BASE

    from services.party.main import app

    salida = matriz(app, dict(ROLES_BASE))
    assert salida["permisos_exigidos"], "ninguna ruta exige permiso: la matriz no probaría nada"
    quien = salida["quien_puede"]
    alguno = next(p for p in salida["permisos_exigidos"] if quien.get(p))
    assert "admin" in quien[alguno], "el rol con *:* tiene que salir en todos"


def test_la_matriz_enseña_los_permisos_que_nadie_tiene() -> None:
    """Un permiso que una ruta exige y ningún rol tiene es funcionalidad muerta:
    nadie puede usarla, y nadie lo sabe."""
    from crmcore.authz.matriz import matriz

    from services.party.main import app

    class _Rol:
        permisos = frozenset({"contact:read"})

    salida = matriz(app, {"solo_lectura": _Rol()})
    assert salida["exigidos_sin_ningun_rol"], "con un rol mínimo tiene que haber huecos"
    assert salida["aviso"]


def test_la_matriz_enseña_los_privilegios_fantasma() -> None:
    """Un permiso concedido que ninguna ruta exige es algo que alguien concedió
    por si acaso, y eso es un riesgo, no una comodidad."""
    from crmcore.authz.matriz import matriz

    from services.party.main import app

    class _Rol:
        permisos = frozenset({"contact:read", "invento:total"})

    salida = matriz(app, {"raro": _Rol()})
    assert "invento:total" in salida["concedidos_que_ninguna_ruta_exige"]


# ── Panel de GRC (CRM-07.03.02.10) ────────────────────────────────────────


@pytest.mark.db
def test_el_panel_sin_nada_declarado_no_dice_que_se_cumpla(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un panel en verde porque no hay nada declarado es el que más tranquiliza y
    el que peor informa."""
    from services.tenancy import grc

    salida = grc.panel(db, tenant_id)
    assert salida["medible"] is False
    assert "no hay nada con lo que comprobarlo" in salida["porque"]
    assert salida["todo_en_orden"] is False
