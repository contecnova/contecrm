"""Base de conocimiento y portal de cliente
(CRM-04.03.01, CRM-04.03.02, CRM-00.05.01.10).

Una base de conocimiento fracasa porque nadie sabe cuáles artículos siguen siendo
verdad, y un portal de cliente por lo que enseña de más. Estas pruebas van detrás
de esas dos cosas.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, NoEncontrado, Prohibido
from crmcore.fechas import hoy

from services.service import conocimiento as kb
from services.service import portal as prt
from services.service import servicio as svc

HOY = hoy()


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _articulo(uow: Any, **kw: Any) -> tuple[Any, Any]:
    base = {"clave": "reiniciar", "titulo": "Cómo reiniciar", "cuerpo": "Pulsa el botón"}
    base.update(kw)
    return kb.crear_articulo(uow, **base)


# ── Alta, versiones y publicación (CRM-04.03.01.01) ───────────────────────


@pytest.mark.db
def test_un_articulo_nace_en_borrador_e_interno(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """El fallo caro —publicar hacia fuera un procedimiento interno con nombres
    de clientes dentro— ocurre siempre por omisión, nunca por decisión."""
    articulo, _ = _articulo(uow)
    assert articulo.estado == "borrador"
    assert articulo.audiencia == "interno"


@pytest.mark.db
def test_una_version_nueva_no_toca_la_publicada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Es lo que permite corregir un artículo que está en el portal sin que el
    cliente vea el texto a medias."""
    articulo, _ = _articulo(uow, revisar_el=HOY + timedelta(days=90))
    kb.publicar(uow, articulo.id, aprobada_por=uuid4(), audiencia="cliente")
    db.flush()
    assert articulo.version_publicada == 1

    kb.nueva_version(uow, articulo.id, titulo="Otra cosa", cuerpo="…")
    assert articulo.version_publicada == 1
    assert articulo.estado == "en_revision"


@pytest.mark.db
def test_no_se_publica_hacia_el_cliente_sin_otro_par_de_ojos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Quien escribe un artículo no es quien mejor detecta que lleva dentro el
    nombre de un cliente."""
    autor = uuid4()
    articulo, version = _articulo(uow, autor_id=autor, revisar_el=HOY + timedelta(days=30))
    version.autor_id = autor
    db.flush()

    with pytest.raises(Prohibido) as e:
        kb.publicar(uow, articulo.id, aprobada_por=autor, audiencia="cliente")
    assert e.value.error_code == "service.aprobacion_requerida"

    kb.publicar(uow, articulo.id, aprobada_por=uuid4(), audiencia="cliente")
    assert articulo.estado == "publicado"


@pytest.mark.db
def test_sin_fecha_de_revision_no_sale_hacia_fuera(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Sin ella nadie vuelve a mirarlo, y es el que sigue apareciendo tres años
    después describiendo una versión que ya no existe."""
    articulo, _ = _articulo(uow)
    with pytest.raises(ErrorValidacion) as e:
        kb.publicar(uow, articulo.id, aprobada_por=uuid4(), audiencia="cliente")
    assert e.value.error_code == "service.sin_fecha_de_revision"


@pytest.mark.db
def test_lo_interno_se_publica_sin_esas_dos_trabas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Exigirlas para lo interno haría que nadie documentara nada, que es peor."""
    articulo, _ = _articulo(uow)
    kb.publicar(uow, articulo.id)
    assert articulo.estado == "publicado"


@pytest.mark.db
def test_retirar_exige_motivo_y_no_borra(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Borrar rompe los enlaces que alguien pegó en un correo hace dos años."""
    articulo, _ = _articulo(uow)
    with pytest.raises(ErrorValidacion):
        kb.marcar_obsoleto(uow, articulo.id, motivo="")
    kb.marcar_obsoleto(uow, articulo.id, motivo="el producto ya no existe")
    db.flush()
    assert kb.leer(db, tenant_id, articulo.id)["obsoleto"] is True


# ── Audiencia (CRM-04.03.01.02) ───────────────────────────────────────────


@pytest.mark.db
def test_el_portal_publico_no_ve_lo_interno(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Si el filtro dependiera del llamante, bastaría una ruta nueva que se
    olvidara de pasarlo."""
    interno, _ = _articulo(uow, clave="procedimiento")
    kb.publicar(uow, interno.id)
    publico, _ = _articulo(uow, clave="faq", revisar_el=HOY + timedelta(days=30))
    kb.publicar(uow, publico.id, aprobada_por=uuid4(), audiencia="publico")
    db.flush()

    claves = {a["clave"] for a in kb.buscar(db, tenant_id, audiencia="publico")}
    assert claves == {"faq"}
    assert "procedimiento" in {a["clave"] for a in kb.buscar(db, tenant_id, audiencia="interno")}


@pytest.mark.db
def test_un_articulo_fuera_de_audiencia_da_404_y_no_403(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Un 403 confirma que existe, y con eso se recorre el catálogo interno
    preguntando por identificadores."""
    articulo, _ = _articulo(uow)
    kb.publicar(uow, articulo.id)
    db.flush()
    with pytest.raises(NoEncontrado):
        kb.leer(db, tenant_id, articulo.id, audiencia="publico")


# ── Traducciones (CRM-04.03.01.03) ────────────────────────────────────────


@pytest.mark.db
def test_una_traduccion_desincronizada_se_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Una traducción vieja no falla, simplemente miente, y el cliente que la lee
    no tiene forma de saberlo."""
    original, _ = _articulo(uow, revisar_el=HOY + timedelta(days=90))
    kb.publicar(uow, original.id, aprobada_por=uuid4(), audiencia="cliente")
    db.flush()
    kb.traducir(uow, original.id, idioma="en", titulo="How to restart", cuerpo="Press it")
    db.flush()

    assert kb.estado_de_traducciones(db, tenant_id, original.id)["desincronizadas"] == []

    kb.nueva_version(uow, original.id, titulo="Cómo reiniciar", cuerpo="Otra cosa")
    kb.publicar(uow, original.id, aprobada_por=uuid4(), audiencia="cliente")
    db.flush()

    estado = kb.estado_de_traducciones(db, tenant_id, original.id)
    assert estado["desincronizadas"] == ["en"]
    assert estado["traducciones"][0]["versiones_por_detras"] == 1


@pytest.mark.db
def test_no_se_traduce_una_traduccion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    original, _ = _articulo(uow)
    traduccion, _ = kb.traducir(uow, original.id, idioma="en", titulo="T", cuerpo="C")
    db.flush()
    with pytest.raises(ErrorValidacion) as e:
        kb.traducir(uow, traduccion.id, idioma="fr", titulo="T", cuerpo="C")
    assert e.value.error_code == "service.traduccion_de_traduccion"


# ── KCS (CRM-04.03.01.05) ─────────────────────────────────────────────────


@pytest.mark.db
def test_no_se_documenta_un_caso_sin_resolver(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """El artículo saldría de una solución que aún no se sabe si funciona."""
    caso = svc.abrir_caso(uow, asunto="Algo pasa")
    with pytest.raises(Conflicto) as e:
        kb.desde_caso(uow, caso.id, clave="algo")
    assert e.value.error_code == "service.caso_no_resuelto"


@pytest.mark.db
def test_el_articulo_de_un_caso_nace_interno(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """El texto de una resolución lleva casi siempre el nombre del cliente, su
    configuración y a veces sus credenciales."""
    caso = svc.abrir_caso(uow, asunto="No arranca")
    svc.cerrar_caso(uow, caso.id, motivo="resuelto", resolucion="Se cambió la fuente")
    db.flush()

    articulo, _ = kb.desde_caso(uow, caso.id, clave="fuente", audiencia="publico")
    assert articulo.audiencia == "interno"
    assert articulo.caso_origen_id == caso.id


@pytest.mark.db
def test_usar_un_articulo_en_un_caso_se_cuenta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Un artículo muy valorado que nadie usa en un caso es un artículo bonito."""
    articulo, _ = _articulo(uow)
    caso = svc.abrir_caso(uow, asunto="X")
    db.flush()
    kb.enlazar_a_caso(uow, articulo.id, caso.id)
    assert articulo.usos_en_caso == 1


# ── Valoración y eficacia (CRM-04.03.01.06) ───────────────────────────────


@pytest.mark.db
def test_un_voto_por_votante(db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any) -> None:
    """Sin eso, el mismo visitante vota cien veces y el primero que lo descubra
    decidirá qué artículos parecen buenos."""
    articulo, _ = _articulo(uow)
    for _ in range(5):
        kb.valorar(uow, articulo.id, util=True, votante="visitante-1")
    db.flush()
    assert articulo.utiles == 1


@pytest.mark.db
def test_cambiar_de_opinion_ajusta_el_contador(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    articulo, _ = _articulo(uow)
    kb.valorar(uow, articulo.id, util=True, votante="v1")
    kb.valorar(uow, articulo.id, util=False, votante="v1", comentario="no funciona")
    db.flush()
    assert (articulo.utiles, articulo.inutiles) == (0, 1)


@pytest.mark.db
def test_un_voto_sin_votante_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    articulo, _ = _articulo(uow)
    with pytest.raises(ErrorValidacion) as e:
        kb.valorar(uow, articulo.id, util=True, votante="  ")
    assert e.value.error_code == "service.voto_sin_votante"


@pytest.mark.db
def test_la_eficacia_separa_daninos_de_huerfanos_y_caducados(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Tres listas para tres decisiones distintas: un artículo con muchas visitas
    y pulgar abajo es peor que no tenerlo."""
    danino, _ = _articulo(uow, clave="malo")
    kb.publicar(uow, danino.id)
    danino.vistas = 100
    for i in range(3):
        kb.valorar(uow, danino.id, util=False, votante=f"v{i}")

    huerfano, _ = _articulo(uow, clave="nadie")
    kb.publicar(uow, huerfano.id)

    caducado, _ = _articulo(uow, clave="viejo", revisar_el=HOY - timedelta(days=400))
    kb.publicar(uow, caducado.id)
    caducado.vistas = 5
    db.flush()

    salida = kb.eficacia(db, tenant_id, minimo_vistas=20)
    assert [a["clave"] for a in salida["dañinos"]] == ["malo"]
    assert "nadie" in [a["clave"] for a in salida["huerfanos"]]
    assert [a["clave"] for a in salida["caducados"]] == ["viejo"]


@pytest.mark.db
def test_la_deflexion_se_da_como_aproximada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Presentarla como exacta sería inventarse un número que después alguien
    cita en una reunión."""
    articulo, _ = _articulo(uow)
    kb.publicar(uow, articulo.id)
    articulo.vistas = 100
    articulo.usos_en_caso = 10
    db.flush()
    salida = kb.eficacia(db, tenant_id)
    assert salida["deflexion_aproximada_pct"] == 90.0
    assert "aproximación" in salida["aviso_deflexion"]


@pytest.mark.db
def test_un_articulo_caducado_se_marca_en_la_busqueda(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Ocultarlo dejaría al cliente sin respuesta y enseñarlo sin avisar le daría
    una que puede estar vieja."""
    articulo, _ = _articulo(uow, revisar_el=HOY - timedelta(days=10))
    kb.publicar(uow, articulo.id, aprobada_por=uuid4(), audiencia="cliente")
    db.flush()
    resultado = kb.buscar(db, tenant_id, audiencia="cliente")[0]
    assert resultado["pendiente_de_revision"] is True


# ── Portal: identidad (CRM-04.03.02.05, CRM-00.05.01.10) ──────────────────


@pytest.fixture
def acceso(db: Any, tenant_id: UUID, uow: Any) -> Any:
    return prt.dar_acceso(uow, contacto_id=uuid4(), email="cliente@empresa.com", cuenta_id=uuid4())


@pytest.mark.db
def test_el_acceso_nace_en_el_nivel_mas_bajo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any
) -> None:
    """Impide que el técnico que abrió una incidencia acabe viendo las facturas
    de su empresa porque alguien creó el acceso deprisa."""
    assert acceso.nivel == "propio"
    assert "facturas" not in prt.secciones_de(acceso)


@pytest.mark.db
def test_pedir_enlace_para_un_correo_desconocido_responde_igual(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    """Distinguirlo convertiría el portal en un comprobador de qué correos son
    clientes nuestros, que es la lista que quiere un competidor."""
    enlace, token = prt.emitir_enlace(uow, email="nadie@fuera.com")
    assert enlace is None and token == ""


@pytest.mark.db
def test_el_enlace_es_de_un_solo_uso(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    _, token = prt.emitir_enlace(uow, email="cliente@empresa.com")
    db.flush()
    prt.canjear_enlace(uow, token)
    db.flush()
    with pytest.raises(NoAutenticado):
        prt.canjear_enlace(uow, token)


@pytest.mark.db
def test_revocar_invalida_los_enlaces_vivos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    """Si no, alguien a quien acaban de retirar el acceso sigue entrando con el
    correo que recibió esta mañana."""
    _, token = prt.emitir_enlace(uow, email="cliente@empresa.com")
    db.flush()
    prt.revocar_acceso(uow, acceso.id, motivo="ya no trabaja allí")
    db.flush()
    with pytest.raises(NoAutenticado):
        prt.canjear_enlace(uow, token)


@pytest.mark.db
def test_un_token_inventado_da_el_mismo_error(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    with pytest.raises(NoAutenticado) as e:
        prt.canjear_enlace(uow, "inventado")
    assert e.value.error_code == "portal.enlace_no_valido"


@pytest.mark.db
def test_no_se_da_acceso_dos_veces_al_mismo_contacto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    with pytest.raises(Conflicto):
        prt.dar_acceso(uow, contacto_id=acceso.contacto_id, email="otro@empresa.com")


# ── Portal: lo que ve (CRM-04.03.02.01) ───────────────────────────────────


@pytest.mark.db
def test_el_nivel_propio_solo_ve_lo_suyo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    """Filtrar en el cliente funciona hasta que alguien mira la respuesta de la
    API."""
    mio = svc.abrir_caso(
        uow, asunto="Mío", contacto_id=acceso.contacto_id, cuenta_id=acceso.cuenta_id
    )
    svc.abrir_caso(uow, asunto="De un compañero", cuenta_id=acceso.cuenta_id)
    db.flush()

    claves = {c["asunto"] for c in prt.mis_casos(db, acceso)}
    assert claves == {"Mío"}
    del mio


@pytest.mark.db
def test_el_nivel_cuenta_ve_los_de_su_empresa(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    acceso.nivel = "cuenta"
    svc.abrir_caso(uow, asunto="Mío", contacto_id=acceso.contacto_id, cuenta_id=acceso.cuenta_id)
    svc.abrir_caso(uow, asunto="De un compañero", cuenta_id=acceso.cuenta_id)
    svc.abrir_caso(uow, asunto="De otra empresa", cuenta_id=uuid4())
    db.flush()

    asuntos = {c["asunto"] for c in prt.mis_casos(db, acceso)}
    assert asuntos == {"Mío", "De un compañero"}


@pytest.mark.db
def test_nivel_cuenta_sin_cuenta_no_ve_nada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Enseñar todo «porque tiene nivel de cuenta» sería el peor fallo posible
    aquí.

    El acceso se construye a mano y no con `dar_acceso`, que ya no deja crear
    uno así: crearlo se rechaza porque un portal que entra bien y sale vacío se
    lee como «no tengo casos» y no como «el acceso está mal dado». Lo que se
    defiende aquí es lo otro — que si una fila así existe igualmente, por datos
    viejos o por una importación, **no se enseña nada**.
    """
    acceso = prt.AccesoPortal(
        tenant_id=tenant_id,
        contacto_id=uuid4(),
        email="huerfano@empresa.com",
        nivel="cuenta",
    )
    db.add(acceso)
    svc.abrir_caso(uow, asunto="De alguien", cuenta_id=uuid4())
    db.flush()
    assert prt.mis_casos(db, acceso) == []


@pytest.mark.db
def test_no_se_puede_crear_un_acceso_de_cuenta_sin_cuenta(uow: Any) -> None:
    """Se rechaza al crearlo, no se deja pasar: el síntoma sería un portal que
    entra y sale vacío, y eso no se lee como un acceso mal dado."""
    from crmcore.errors import ErrorValidacion

    with pytest.raises(ErrorValidacion) as fallo:
        prt.dar_acceso(uow, contacto_id=uuid4(), email="huerfano@empresa.com", nivel="cuenta")

    assert fallo.value.error_code == "service.acceso_portal_sin_cuenta"


@pytest.mark.db
def test_declarar_secciones_no_salta_el_nivel(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any
) -> None:
    """Si las declaradas mandaran, declarar una sección sería una forma de
    saltarse el nivel."""
    acceso.secciones = ["facturas", "casos"]
    assert prt.secciones_de(acceso) == ["casos"]


@pytest.mark.db
def test_el_caso_del_portal_lleva_el_contacto_del_acceso(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    """Aceptarlos de quien llama permitiría abrir casos en nombre de otra
    empresa, que es la fuga más fácil de un portal."""
    caso = prt.abrir_caso_desde_portal(
        uow, acceso, asunto="Ayuda", contacto_id=uuid4(), cuenta_id=uuid4()
    )
    assert caso.contacto_id == acceso.contacto_id
    assert caso.cuenta_id == acceso.cuenta_id


@pytest.mark.db
def test_un_acceso_desactivado_no_abre_casos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    acceso.activo = False
    db.flush()
    with pytest.raises(Prohibido):
        prt.abrir_caso_desde_portal(uow, acceso, asunto="Ayuda")


# ── Comunidad (CRM-04.03.02.04) ───────────────────────────────────────────


@pytest.mark.db
def test_un_hilo_nace_en_moderacion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    """Un foro sin moderación acaba con un cliente publicando su clave de
    licencia o la configuración de su red, y eso ya no se retira del todo."""
    hilo = prt.abrir_hilo(uow, acceso, titulo="¿Cómo se hace?", cuerpo="…")
    assert hilo.estado == "moderacion"
    db.flush()
    assert prt.hilos(db, tenant_id) == []


@pytest.mark.db
def test_la_respuesta_del_fabricante_se_marca(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    """Sin marcarla, el cliente aplica el consejo de cualquiera creyendo que es
    oficial."""
    hilo = prt.abrir_hilo(uow, acceso, titulo="X", cuerpo="…", moderar=False)
    db.flush()
    de_cliente = prt.responder_hilo(uow, hilo.id, cuerpo="A mí me pasó", contacto_id=uuid4())
    de_nosotros = prt.responder_hilo(
        uow, hilo.id, cuerpo="Es un fallo conocido", usuario_id=uuid4()
    )
    assert de_cliente.oficial is False and de_nosotros.oficial is True


@pytest.mark.db
def test_aceptar_una_respuesta_resuelve_el_hilo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    """Sin ella, quien llega el mes que viene tiene que leerse los treinta
    mensajes para saber cuál sirvió."""
    hilo = prt.abrir_hilo(uow, acceso, titulo="X", cuerpo="…", moderar=False)
    db.flush()
    respuesta = prt.responder_hilo(uow, hilo.id, cuerpo="Así se arregla", usuario_id=uuid4())
    db.flush()
    prt.aceptar_respuesta(uow, hilo.id, respuesta.id)
    assert hilo.respuesta_aceptada_id == respuesta.id


@pytest.mark.db
def test_rechazar_un_hilo_exige_motivo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    """El cliente que lo escribió tiene derecho a saber por qué no se publica."""
    hilo = prt.abrir_hilo(uow, acceso, titulo="X", cuerpo="…")
    db.flush()
    with pytest.raises(ErrorValidacion) as e:
        prt.moderar_hilo(uow, hilo.id, aprobar=False)
    assert e.value.error_code == "service.rechazo_sin_motivo"


@pytest.mark.db
def test_no_se_convierte_en_articulo_un_hilo_sin_resolver(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    """El artículo describiría el problema y no su solución: parece una respuesta
    y no lo es."""
    hilo = prt.abrir_hilo(uow, acceso, titulo="X", cuerpo="…", moderar=False)
    db.flush()
    with pytest.raises(Conflicto) as e:
        prt.convertir_en_articulo(uow, hilo.id, clave="del-foro")
    assert e.value.error_code == "service.hilo_sin_respuesta_aceptada"


@pytest.mark.db
def test_un_hilo_resuelto_si_se_convierte(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, acceso: Any, uow: Any
) -> None:
    hilo = prt.abrir_hilo(uow, acceso, titulo="Cómo migrar", cuerpo="…", moderar=False)
    db.flush()
    respuesta = prt.responder_hilo(uow, hilo.id, cuerpo="Con el asistente", usuario_id=uuid4())
    db.flush()
    prt.aceptar_respuesta(uow, hilo.id, respuesta.id)
    db.flush()

    articulo = prt.convertir_en_articulo(uow, hilo.id, clave="migrar")
    assert articulo.audiencia == "interno"
    assert hilo.articulo_id == articulo.id
