"""Lo que sale de verdad en marketing (CRM-02.01.01.09, CRM-02.02.01.06,
CRM-02.02.02.01, CRM-02.02.02.04, CRM-02.02.02.05, CRM-02.02.02.09,
CRM-02.03.01.02, CRM-02.03.01.06, CRM-02.03.01.07).

Medido el 09-11-2026: estas capacidades constaban hechas y sólo simulaban —una
audiencia que se preparaba y no se mandaba, una «mejor hora» sobre datos
tecleados, un spam score de seis palabras—. Las pruebas van detrás de lo que
cambia el resultado: quién sale y quién no, a qué hora, por qué dominio y con
qué puntuación.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo

from services.integration import conector
from services.marketing import audiencias_sync as aud
from services.marketing import campanas as cmp
from services.marketing import envios as env
from services.marketing import recorridos as rec
from services.marketing import vista_correo as vis


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _ajustes(monkeypatch: pytest.MonkeyPatch, modulo: Any, **valores: Any) -> None:
    """Fija ajustes para la prueba sin tocar la base: el resto, su defecto."""
    from crmcore.runtime.settings import efectivo

    original = modulo._ajuste

    def _leer(clave: str, db: Any) -> Any:
        return valores[clave] if clave in valores else original(clave, db)

    monkeypatch.setattr(modulo, "_ajuste", _leer)
    del efectivo


def _perfil(uow: UnidadDeTrabajo, **kw: Any) -> UUID:
    from services.marketing.modelos import PerfilMarketing

    quien = kw.pop("objeto_id", None) or uuid4()
    uow.db.add(
        PerfilMarketing(
            tenant_id=uow.tenant_id,
            objeto="contacto",
            objeto_id=quien,
            email=kw.pop("email", f"{quien.hex[:8]}@cliente.com"),
            **kw,
        )
    )
    uow.db.flush()
    return quien


# ── El conector manda listas en el cuerpo ────────────────────────────────


def test_un_marcador_solo_con_una_lista_se_manda_como_lista() -> None:
    """Sin esto `{"miembros": "{{miembros}}"}` salía como `"['a', 'b']"`."""
    cuerpo = conector._renderizar(
        {"miembros": "{{miembros}}", "nombre": "Audiencia {{nombre}}", "id": "{{id}}"},
        {"miembros": ["a1", "b2"], "nombre": "x", "id": 7},
    )
    assert cuerpo == {"miembros": ["a1", "b2"], "nombre": "Audiencia x", "id": "7"}


# ── Audiencias (CRM-02.01.01.09) ─────────────────────────────────────────


class Plataforma:
    """Doble de `integration` y de `party`: guarda lo que se le pide."""

    def __init__(self, sin_consentimiento: set[UUID] | None = None) -> None:
        self.llamadas: list[tuple[str, dict[str, Any]]] = []
        self.sin_consentimiento = sin_consentimiento or set()

    def __call__(self, **kw: Any) -> dict[str, Any]:
        ruta = kw["ruta"]
        if ruta.endswith("/puede-contactar"):
            contacto = UUID(ruta.split("/")[4])
            return {
                "ok": True,
                "estado": 200,
                "datos": {"puede": contacto not in self.sin_consentimiento},
            }
        clave = ruta.split("/operaciones/")[1].split("/")[0]
        self.llamadas.append((clave, kw["cuerpo"]["parametros"]))
        if clave == "crear_audiencia":
            return {"ok": True, "estado": 200, "datos": {"registros": [{"id_externo": "AUD-1"}]}}
        return {"ok": True, "estado": 200, "datos": {"registros": []}}


def _segmento(uow: UnidadDeTrabajo, ids: list[UUID]) -> UUID:
    """Un segmento estático con esos miembros: lo que importa aquí es la audiencia."""
    from services.marketing.modelos import MiembroSegmento, Segmento

    seg = Segmento(
        tenant_id=uow.tenant_id,
        clave=f"s{uuid4().hex[:6]}",
        nombre="s",
        objeto="contacto",
        definicion={},
        dinamico=False,
    )
    uow.db.add(seg)
    uow.db.flush()
    for i in ids:
        uow.db.add(MiembroSegmento(tenant_id=uow.tenant_id, segmento_id=seg.id, objeto_id=i))
    uow.db.flush()
    return seg.id


@pytest.mark.db
def test_la_audiencia_se_crea_fuera_y_sube_solo_a_quien_consintio(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ajustes(monkeypatch, aud, audiencia_minimo=2)
    gente = [_perfil(uow) for _ in range(4)]
    plataforma = Plataforma(sin_consentimiento={gente[0]})
    audiencia = aud.crear(
        uow, nombre="Clientes", segmento_id=_segmento(uow, gente), conexion_id=uuid4()
    )

    r = aud.sincronizar(uow, audiencia.id, principal_id=uuid4(), invocar=plataforma)

    assert r["ok"] and r["estado"] == "sincronizada" and r["id_externo"] == "AUD-1"
    assert r["altas"] == 3 and r["sin_consentimiento"] == 1
    anadidos = [p for c, p in plataforma.llamadas if c == "anadir_miembros"]
    assert len(anadidos[0]["miembros"]) == 3
    # Troceado, nunca en claro.
    assert all("@" not in m and len(m) == 64 for m in anadidos[0]["miembros"])


@pytest.mark.db
def test_una_supresion_sale_como_baja_antes_que_ninguna_alta(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.marketing.modelos import Supresion

    _ajustes(monkeypatch, aud, audiencia_minimo=1)
    gente = [_perfil(uow) for _ in range(3)]
    plataforma = Plataforma()
    audiencia = aud.crear(uow, nombre="A", segmento_id=_segmento(uow, gente), conexion_id=uuid4())
    aud.sincronizar(uow, audiencia.id, principal_id=None, invocar=plataforma)

    from services.marketing.modelos import PerfilMarketing

    correo = db.get(
        PerfilMarketing, db.query(PerfilMarketing.id).filter_by(objeto_id=gente[1]).scalar()
    ).email
    db.add(Supresion(tenant_id=uow.tenant_id, canal="email", direccion=correo, motivo="baja"))
    db.flush()
    plataforma.llamadas.clear()
    r = aud.sincronizar(uow, audiencia.id, principal_id=None, invocar=plataforma)

    assert r["bajas"] == 1 and r["altas"] == 0
    assert plataforma.llamadas[0][0] == "quitar_miembros"
    historial = aud.ficha(db, uow.tenant_id, audiencia.id)["historial"]
    assert len(historial) == 2 and historial[0]["bajas"] == 1


@pytest.mark.db
def test_por_debajo_del_minimo_no_se_sube_nadie(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ajustes(monkeypatch, aud, audiencia_minimo=10)
    gente = [_perfil(uow) for _ in range(3)]
    plataforma = Plataforma()
    audiencia = aud.crear(uow, nombre="A", segmento_id=_segmento(uow, gente), conexion_id=uuid4())
    r = aud.sincronizar(uow, audiencia.id, principal_id=None, invocar=plataforma)
    assert r["estado"] == "pequena" and plataforma.llamadas == [] and "mínimo es 10" in r["porque"]


@pytest.mark.db
def test_si_la_plataforma_rechaza_queda_en_error_con_su_motivo(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ajustes(monkeypatch, aud, audiencia_minimo=1)
    gente = [_perfil(uow)]
    audiencia = aud.crear(uow, nombre="A", segmento_id=_segmento(uow, gente), conexion_id=uuid4())

    def rechaza(**kw: Any) -> dict[str, Any]:
        if kw["ruta"].endswith("/puede-contactar"):
            return {"ok": True, "estado": 200, "datos": {"puede": True}}
        return {"ok": False, "estado": 401, "datos": {"mensaje": "token caducado"}}

    r = aud.sincronizar(uow, audiencia.id, principal_id=None, invocar=rechaza)
    assert not r["ok"] and r["estado"] == "error" and "token caducado" in r["error"]


# ── Mejor hora y canal (CRM-02.02.02.05) ─────────────────────────────────


@pytest.mark.db
def test_sin_historial_va_a_la_hora_y_al_canal_por_defecto(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ajustes(monkeypatch, env, momento_hora_por_defecto=9)
    quien = _perfil(uow)
    from services.marketing.modelos import PerfilMarketing

    perfil = db.query(PerfilMarketing).filter_by(objeto_id=quien).one()
    e = env.elegir(
        db,
        uow.tenant_id,
        quien,
        perfil=perfil,
        ahora=datetime(2026, 11, 9, 12, tzinfo=timezone.utc),
    )
    assert e["hora_local"] == 9 and e["eleccion"]["hora"] == "por_defecto"
    assert e["canal"] == "email" and e["programado_at"] > datetime(
        2026, 11, 9, 12, tzinfo=timezone.utc
    )


@pytest.mark.db
def test_con_historial_va_a_la_hora_a_la_que_contesta(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    from crmcore.config import get_settings

    quien = _perfil(uow)
    minimo = get_settings().momento_minimo_interacciones
    campana = cmp.crear(uow, clave="c", nombre="c")
    for i in range(minimo + 1):
        db.add(
            env.EnvioProgramado(
                tenant_id=uow.tenant_id,
                origen="campana",
                origen_id=campana.id,
                objeto_id=quien,
                canal="email",
                plantilla="p",
                programado_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                clic_at=datetime(2026, 10, 1 + i, 17, 5, tzinfo=timezone.utc),
            )
        )
    db.flush()
    from services.marketing.modelos import PerfilMarketing

    perfil = db.query(PerfilMarketing).filter_by(objeto_id=quien).one()
    perfil.campos = {"zona_horaria": "UTC"}
    e = env.elegir(db, uow.tenant_id, quien, perfil=perfil)
    assert e["hora_local"] == 17 and e["eleccion"]["hora"] == "historial"


@pytest.mark.db
def test_lo_que_dijo_la_persona_manda_sobre_el_historial(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    quien = _perfil(
        uow,
        telefono="+34600000000",
        campos={"canal_preferido": "sms", "horario_preferido": "08:00"},
    )
    from services.marketing.modelos import PerfilMarketing

    perfil = db.query(PerfilMarketing).filter_by(objeto_id=quien).one()
    e = env.elegir(db, uow.tenant_id, quien, perfil=perfil, canales=["email", "sms"])
    assert e["canal"] == "sms" and e["hora_local"] == 8
    assert e["eleccion"] == {**e["eleccion"], "canal": "lo_dijo", "hora": "lo_dijo"}


@pytest.mark.db
def test_programar_la_campana_omite_al_suprimido_con_su_motivo(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.marketing.correo import PlantillaMarketing
    from services.marketing.modelos import Supresion

    db.add(
        PlantillaMarketing(
            tenant_id=uow.tenant_id,
            clave="p",
            nombre="p",
            asunto="Hola",
            clase="promocional",
            bloques=[],
        )
    )
    a, b = _perfil(uow), _perfil(uow, email="fuera@cliente.com")
    db.add(
        Supresion(
            tenant_id=uow.tenant_id, canal="email", direccion="fuera@cliente.com", motivo="baja"
        )
    )
    campana = cmp.crear(uow, clave="c", nombre="c")
    cmp.anadir_miembros(uow, campana.id, objeto_ids=[a, b])
    db.flush()

    r = env.programar_campana(uow, campana.id, plantilla="p")
    assert r["programados"] == 1 and r["omitidos"] == 1
    lista = env.listado(db, uow.tenant_id, origen="campana", origen_id=campana.id)
    omitido = next(x for x in lista["envios"] if x["estado"] == "omitido")
    assert omitido["motivo"] == "suprimido" and omitido["porque"]
    # Programar otra vez no duplica.
    assert env.programar_campana(uow, campana.id, plantilla="p")["envios"] == 0


# ── Transaccional por su dominio (CRM-02.03.01.07) ───────────────────────


@pytest.mark.db
def test_cada_clase_sale_por_su_dominio_y_el_remitente_ajeno_no_sale(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from crmcore.notificaciones.smtp import TransporteSMTP

    from services.marketing.correo import PlantillaMarketing

    valores = {
        "dominio_promocional": "info.marca.com",
        "dominio_transaccional": "marca.com",
        "remitente_promocional": "noticias@info.marca.com",
        "remitente_transaccional": "facturas@info.marca.com",  # del dominio equivocado
        "correo_flujo_promocional": {"host": "smtp-promo.local"},
        "correo_flujo_transaccional": {"host": "smtp-tx.local"},
    }
    _ajustes(monkeypatch, vis, **valores)
    _ajustes(monkeypatch, env, correo_url_baja="https://marca.com/baja?e={email}")
    mandados: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        TransporteSMTP,
        "_enviar",
        lambda self, correo, host, config, s: mandados.append(
            (correo["From"], host, str(correo.get("List-Unsubscribe")))
        ),
    )
    for clave, clase in (("promo", "promocional"), ("factura", "operativa")):
        db.add(
            PlantillaMarketing(
                tenant_id=uow.tenant_id,
                clave=clave,
                nombre=clave,
                asunto="Hola {{nombre|cliente}}",
                clase=clase,
                bloques=[],
            )
        )
    quien = _perfil(uow)
    campana = cmp.crear(uow, clave="c", nombre="c")
    db.flush()
    env.programar(
        uow,
        origen="campana",
        origen_id=campana.id,
        destinatarios=[quien],
        plantilla="promo",
        inmediato=True,
    )
    env.programar(
        uow,
        origen="campana",
        origen_id=campana.id,
        destinatarios=[quien],
        plantilla="factura",
        inmediato=True,
    )

    r = env.despachar(uow, principal_id=None, forzar=True, origen="campana", origen_id=campana.id)

    assert r["enviados"] == 1 and r["fallidos"] == 1
    assert mandados == [
        (
            "noticias@info.marca.com",
            "smtp-promo.local",
            f"<https://marca.com/baja?e={_correo(db, quien)}>",
        )
    ]
    fallido = next(
        x
        for x in env.listado(db, uow.tenant_id, origen="campana", origen_id=campana.id)["envios"]
        if x["estado"] == "fallido"
    )
    assert fallido["clase"] == "transaccional" and "no es del dominio" in fallido["motivo"]


def test_la_respuesta_de_un_caso_sale_por_lo_transaccional_y_consta(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El envío suelto de la respuesta a un caso (10-11-2026): sale ya, por la
    clase transaccional y con la plantilla de la empresa si la tiene; y si no
    puede salir, queda el envío con su motivo."""
    from crmcore.notificaciones.smtp import TransporteSMTP

    from services.marketing.correo import BloqueCorreo, PlantillaMarketing

    caso = uuid4()
    # Sin canal configurado no sale, y consta con el porqué; sin plantilla de
    # la empresa, la de serie, y se dice.
    r = env.enviar_suelto(
        uow, para="c@example.com", objeto="caso", objeto_id=caso, asunto="Re: X", mensaje="Hola"
    )
    assert r["enviado"] is False and r["estado"] == "fallido" and r["motivo"]
    assert r["plantilla_de_serie"] is True

    _ajustes(
        monkeypatch,
        vis,
        dominio_transaccional="marca.com",
        remitente_transaccional="soporte@marca.com",
        correo_flujo_transaccional={"host": "smtp-tx.local"},
    )
    mandados: list[Any] = []
    monkeypatch.setattr(
        TransporteSMTP, "_enviar", lambda self, correo, host, config, s: mandados.append(correo)
    )
    db.add(
        BloqueCorreo(
            tenant_id=uow.tenant_id,
            clave="firma",
            nombre="f",
            tipo="texto",
            contenido={"texto": "Equipo de soporte · {{caso.codigo}}"},
        )
    )
    db.add(
        PlantillaMarketing(
            tenant_id=uow.tenant_id,
            clave="respuesta_caso",
            nombre="Respuesta",
            asunto="Sobre su caso",
            clase="transaccional",
            bloques=[{"bloque": "cuerpo"}, {"bloque": "firma"}],
        )
    )
    db.add(
        BloqueCorreo(
            tenant_id=uow.tenant_id,
            clave="cuerpo",
            nombre="c",
            tipo="texto",
            contenido={"texto": "{{mensaje}}"},
        )
    )
    db.flush()
    r = env.enviar_suelto(
        uow,
        para="c@example.com",
        objeto="caso",
        objeto_id=caso,
        asunto="Re: Ruido [C-1]",
        mensaje="Primera línea\nSegunda línea",
        plantilla="respuesta_caso",
        datos={"caso": {"codigo": "C-1"}},
    )
    assert r["enviado"] is True and r["plantilla"] == "respuesta_caso"
    (correo,) = mandados
    assert correo["To"] == "c@example.com" and "soporte@marca.com" in correo["From"]
    # El asunto que escribe quien responde manda sobre el de la plantilla.
    assert correo["Subject"] == "Re: Ruido [C-1]"
    html = correo.get_body(preferencelist=("html",)).get_content()
    assert "Primera línea<br>Segunda línea" in html and "C-1" in html

    envios = env.listado(db, uow.tenant_id, origen="respuesta", origen_id=caso)["envios"]
    assert [e["estado"] for e in envios] == ["fallido", "enviado"]


def _correo(db: Any, quien: UUID) -> str:
    from services.marketing.modelos import PerfilMarketing

    return db.query(PerfilMarketing).filter_by(objeto_id=quien).one().email


# ── Vista previa, spam y recomendaciones (CRM-02.03.01.02, .06) ──────────


def test_el_spam_se_explica_regla_a_regla(db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    cuerpo = '<p>OFERTA</p><a href="http://bit.ly/x">https://mibanco.com</a>' '<img src="a.png">'
    r = vis.puntuar_spam(
        db,
        asunto="GRATIS SOLO HOY!!",
        cuerpo_html=cuerpo,
        clase="promocional",
        salida_clase={
            "dominio": "info.marca.com",
            "remitente": "x@otra.com",
            "autenticacion": {"spf": True, "dkim": False, "dmarc": "none"},
        },
        sin_dato=["nombre"],
    )
    reglas = {x["regla"] for x in r["reglas"]}
    assert {
        "asunto_mayusculas",
        "asunto_exclamaciones",
        "palabras_gatillo",
        "acortador",
        "enlace_engana",
        "enlace_sin_https",
        "promocional_sin_baja",
        "sin_dkim",
        "dmarc_none",
        "remitente_otro_dominio",
        "tokens_sin_rellenar",
        "imagen_sin_alt",
    } <= reglas
    assert r["veredicto"] == "basura" and all(x["porque"] for x in r["reglas"])


def test_un_correo_limpio_sale_bien(db: Any) -> None:
    cuerpo = (
        "<p>"
        + "Texto normal sobre el pedido. " * 20
        + '</p><a href="https://marca.com/baja">Darse de baja</a>'
    )
    r = vis.puntuar_spam(
        db,
        asunto="Tu pedido de noviembre",
        cuerpo_html=cuerpo,
        clase="promocional",
        salida_clase={
            "dominio": "marca.com",
            "remitente": "a@marca.com",
            "autenticacion": {"spf": True, "dkim": True, "dmarc": "reject"},
        },
        sin_dato=[],
    )
    assert r["puntos"] == 0 and r["veredicto"] == "bien"


def test_sin_imagenes_se_ve_el_texto_alternativo_y_las_recomendaciones_se_pintan() -> None:
    composicion = {
        "asunto": "Hola {{nombre}}",
        "bloques": [
            {"tipo": "cabecera", "contenido": {"logo": "https://x/logo.png", "alt": "Marca"}},
            {"tipo": "recomendaciones", "contenido": {}},
        ],
    }
    datos = {
        "nombre": "Ana",
        "recomendaciones": {"productos": [{"nombre": "Freno X", "sku": "F1"}]},
    }
    con = vis.montar(composicion, datos)
    sin = vis.montar(composicion, datos, imagenes=False, ancho=375)
    assert con["asunto"] == "Hola Ana" and "<img" in con["html"] and "Freno X" in con["html"]
    assert (
        "<img" not in sin["html"] and "[Marca]" in sin["html"] and "max-width:375px" in sin["html"]
    )


@pytest.mark.db
def test_recomienda_de_las_familias_que_ya_tiene_y_no_lo_que_ya_tiene(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    def ventas(**kw: Any) -> dict[str, Any]:
        ruta = kw["ruta"]
        if ruta == "/api/v1/opportunities":
            return {"ok": True, "estado": 200, "datos": {"items": [{"id": "op1"}]}}
        if ruta.endswith("/lineas"):
            return {"ok": True, "estado": 200, "datos": [{"producto_id": "p1"}]}
        return {
            "ok": True,
            "estado": 200,
            "datos": {
                "items": [
                    {"id": "p1", "nombre": "Freno A", "familia": "frenos"},
                    {"id": "p2", "nombre": "Freno B", "familia": "frenos"},
                    {"id": "p3", "nombre": "Espejo", "familia": "espejos"},
                ]
            },
        }

    r = vis.recomendar(db, tenant_id, cuenta_id=uuid4(), principal_id=None, invocar=ventas)
    assert [p["nombre"] for p in r["productos"]] == ["Freno B"] and r["familias"] == ["frenos"]


def test_sin_historial_no_se_recomienda_nada_y_se_dice(db: Any, tenant_id: UUID) -> None:
    def vacio(**kw: Any) -> dict[str, Any]:
        return {"ok": True, "estado": 200, "datos": {"items": []}}

    r = vis.recomendar(db, tenant_id, cuenta_id=uuid4(), principal_id=None, invocar=vacio)
    assert r["productos"] == [] and "sin historial" in r["porque"]


# ── Atribución basada en datos (CRM-02.02.01.06) ─────────────────────────


def test_la_campana_que_sale_en_todos_los_caminos_que_convierten_pesa_mas() -> None:
    caminos = [
        (["feria", "correo"], True),
        (["feria"], True),
        (["anuncio"], False),
        (["anuncio", "correo"], False),
    ]
    r = cmp.efecto_de_eliminacion(caminos)
    efectos = r["efectos"]
    # Primer orden: el anuncio lleva al correo, que a veces convierte, así que
    # no vale cero; pero la feria, que está en los dos que convierten, pesa más.
    assert efectos["feria"] > efectos["correo"] > 0 and efectos["feria"] > efectos["anuncio"]
    assert r["convertidos"] == 2 and r["prob_conversion"] == 0.5


# ── Recorridos: lienzo, A/B y por cuenta ─────────────────────────────────


NODOS = {
    "prueba": {
        "tipo": "prueba",
        "variantes": [
            {"clave": "a", "peso": 50, "siguiente": "fin"},
            {"clave": "b", "peso": 50, "siguiente": "fin"},
        ],
    },
    "fin": {"tipo": "fin"},
}


@pytest.mark.db
def test_con_ganadora_significativa_el_trafico_nuevo_va_a_ella(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from crmcore.runtime import settings as rt

    original = rt.efectivo
    monkeypatch.setattr(
        rt,
        "efectivo",
        lambda clave, db=None, **kw: 20
        if clave == "prueba_minimo_por_variante"
        else original(clave, db, **kw),
    )
    fila, _ = rec.crear(uow, clave="ab", nombre="AB", nodos=NODOS, inicio="prueba")
    rec.publicar(uow, fila.id)
    # 40 personas por variante: «b» convierte 30, «a» 5.
    for variante, convierten in (("a", 5), ("b", 30)):
        for i in range(40):
            dentro = rec.EnRecorrido(
                tenant_id=uow.tenant_id,
                recorrido_id=fila.id,
                objeto_id=uuid4(),
                nodo_actual="fin",
                estado="salido",
                motivo_salida="conversion" if i < convierten else "fin",
            )
            db.add(dentro)
            db.flush()
            db.add(
                rec.PasoRecorrido(
                    tenant_id=uow.tenant_id,
                    recorrido_id=fila.id,
                    en_recorrido_id=dentro.id,
                    nodo="prueba",
                    tipo="prueba",
                    variante=variante,
                )
            )
    db.flush()

    r = rec.resultado_prueba(db, uow.tenant_id, fila.id, "prueba")
    assert r["ganadora"] == "b" and r["significativa"] and r["p_valor"] < 0.05

    quien = _perfil(uow)
    rec.entrar(uow, fila.id, objeto_id=quien)
    rec.avanzar(uow, uow.tenant_id)
    nuevo = db.query(rec.EnRecorrido).filter_by(recorrido_id=fila.id, objeto_id=quien).one()
    assert nuevo.variantes == {"prueba": "b"}
    assert rec.ficha(db, uow.tenant_id, fila.id)["nodos"]["prueba"]["ganadora"] == "b"


@pytest.mark.db
def test_con_poca_diferencia_no_hay_ganadora_aunque_haya_muestra(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    fila, _ = rec.crear(uow, clave="ab2", nombre="AB", nodos=NODOS, inicio="prueba")
    for variante, convierten in (("a", 10), ("b", 12)):
        for i in range(30):
            dentro = rec.EnRecorrido(
                tenant_id=uow.tenant_id,
                recorrido_id=fila.id,
                objeto_id=uuid4(),
                motivo_salida="conversion" if i < convierten else "fin",
            )
            db.add(dentro)
            db.flush()
            db.add(
                rec.PasoRecorrido(
                    tenant_id=uow.tenant_id,
                    recorrido_id=fila.id,
                    en_recorrido_id=dentro.id,
                    nodo="prueba",
                    tipo="prueba",
                    variante=variante,
                )
            )
    db.flush()
    r = rec.resultado_prueba(db, uow.tenant_id, fila.id, "prueba", minimo=10)
    assert r["concluyente"] and not r["significativa"] and r["ganadora"] is None


@pytest.mark.db
def test_el_lienzo_se_guarda_validado_y_vuelve_a_borrador(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    from crmcore.errors import ErrorValidacion

    fila, _ = rec.crear(uow, clave="l", nombre="L", nodos={"fin": {"tipo": "fin"}}, inicio="fin")
    rec.publicar(uow, fila.id)
    nuevos = {
        "hola": {
            "tipo": "accion",
            "accion": "email",
            "plantilla": "p",
            "siguiente": "fin",
            "pos": {"x": 10, "y": 20},
        },
        "fin": {"tipo": "fin"},
    }
    r = rec.actualizar_lienzo(uow, fila.id, nodos=nuevos, inicio="hola", por_cuenta=True)
    assert r["estado"] == "borrador"
    ficha = rec.ficha(db, uow.tenant_id, fila.id)
    assert ficha["nodos"]["hola"]["pos"] == {"x": 10, "y": 20} and ficha["por_cuenta"]
    with pytest.raises(ErrorValidacion):
        rec.actualizar_lienzo(
            uow, fila.id, nodos={"x": {"tipo": "fin", "siguiente": "nadie"}}, inicio="x"
        )


@pytest.mark.db
def test_por_cuenta_la_segunda_persona_de_la_empresa_no_entra_aunque_no_se_diga_la_cuenta(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    empresa = uuid4()
    a, b = _perfil(uow, cuenta_id=empresa), _perfil(uow, cuenta_id=empresa)
    fila, _ = rec.crear(
        uow,
        clave="abm",
        nombre="ABM",
        nodos={"fin": {"tipo": "fin"}},
        inicio="fin",
        por_cuenta=True,
    )
    rec.publicar(uow, fila.id)
    assert rec.entrar(uow, fila.id, objeto_id=a)["entro"]
    assert rec.entrar(uow, fila.id, objeto_id=b) == {"entro": False, "motivo": "cuenta_ya_dentro"}


@pytest.mark.db
def test_el_paso_con_plantilla_programa_el_envio_a_su_hora(
    db: Any, uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    from services.marketing.correo import PlantillaMarketing

    db.add(
        PlantillaMarketing(
            tenant_id=uow.tenant_id,
            clave="bienvenida",
            nombre="b",
            asunto="Hola",
            clase="promocional",
            bloques=[],
        )
    )
    nodos = {
        "hola": {
            "tipo": "accion",
            "accion": "email",
            "plantilla": "bienvenida",
            "siguiente": "fin",
        },
        "fin": {"tipo": "fin"},
    }
    fila, _ = rec.crear(uow, clave="r", nombre="R", nodos=nodos, inicio="hola")
    rec.publicar(uow, fila.id)
    quien = _perfil(uow)
    rec.entrar(uow, fila.id, objeto_id=quien)
    rec.avanzar(uow, uow.tenant_id)
    lista = env.listado(db, uow.tenant_id, origen="recorrido", origen_id=fila.id)
    assert lista["programados"] == 1
    envio = lista["envios"][0]
    assert envio["nodo"] == "hola" and envio["como_hora"] == "por_defecto"
    assert envio["programado_at"] > datetime.now(timezone.utc) - timedelta(minutes=1)
