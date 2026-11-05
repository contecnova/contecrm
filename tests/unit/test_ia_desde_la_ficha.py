"""La IA desde la ficha (CRM-01.01.05.05, 03.01.02.04, 04.02.02.05, .06, .07,
05.02.02.01, .02, .06).

Todo esto existía en `intelligence` como cálculos a los que había que darles los
hechos, y nada se podía pedir desde una ficha. En la primera llamada de verdad,
con un proveedor declarado, salieron cuatro cosas que ninguna prueba veía y que
se fijan aquí:

- un tenant no tenía ninguna plantilla y todo contestaba «No hay plantilla»;
- el resumen de cuenta mandaba los hechos como datos y no como contexto, y el
  mínimo de contexto del resumen no le dejaba llamar al modelo nunca;
- y un fragmento sin permiso declarado se descarta, así que hay que declararlo;
- un resumen —que lo lee la gente de la empresa— no tenía idioma si el tenant no
  lo había fijado; lo que se escribe al cliente sigue exigiéndolo;
- Gemini no tiene campo de opt-out en la petición: su garantía es del contrato.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo

from services.intelligence import asistencia as asis
from services.intelligence import generacion as gen
from tests.unit.test_ia_generativa import (  # noqa: F401
    _principal,
    _proveedor,
    puerto_de_mentira,
    uow,
)

pytestmark = pytest.mark.db


def test_la_plantilla_de_serie_se_guarda_como_version_1_del_tenant(
    uow: UnidadDeTrabajo,  # noqa: F811
    puerto_de_mentira: dict[str, Any],  # noqa: F811
) -> None:
    _proveedor(uow)
    salida = gen.generar(
        uow,
        plantilla="redactar_correo",
        datos={"destinatario": "Marta", "proposito": "quedar el martes"},
        idioma="es",
        principal=_principal("*:*"),
    )
    assert salida["generado"], salida
    assert salida["plantilla"] == "redactar_correo v1"
    guardada = gen._vigente(uow.db, uow.tenant_id, "redactar_correo")
    assert guardada is not None and "De serie" in guardada.motivo_version
    # Y es del tenant: la siguiente vez se usa la suya, no la del código.
    assert gen._vigente(uow.db, uow.tenant_id, "redactar_correo").id == guardada.id
    # Una clave que no existe ni de serie sigue sin inventarse.
    with pytest.raises(Exception) as error:
        gen.generar(uow, plantilla="no-existe", principal=_principal("*:*"))
    assert getattr(error.value, "error_code", "") == "generacion.plantilla_no_encontrada"


def test_el_resumen_de_cuenta_manda_los_hechos_como_contexto_y_en_el_idioma_de_la_casa(
    uow: UnidadDeTrabajo,  # noqa: F811
    puerto_de_mentira: dict[str, Any],  # noqa: F811
) -> None:
    _proveedor(uow)
    hechos = {
        "nombre": "Metales Norte",
        "estado": "activa",
        "contactos_en_total": 3,
        "ultimas_interacciones": [{"tipo": "llamada", "titulo": "Queja por el retraso"}] * 5,
    }
    salida = asis.resumen_de_cuenta(
        uow, cuenta_id=uuid4(), hechos=hechos, principal=_principal("account:read")
    )
    assert salida["generado"], salida
    assert "Metales Norte" in puerto_de_mentira["contexto"]
    # Sin idioma pedido ni en la plantilla: el de la casa, porque lo lee la gente
    # de la empresa.
    assert puerto_de_mentira["idioma"] == "es"
    # Y quien no puede leer la cuenta no le pasa nada al modelo.
    sin_permiso = asis.resumen_de_cuenta(
        uow, cuenta_id=uuid4(), hechos=hechos, principal=_principal("case:read")
    )
    assert not sin_permiso["generado"]


def test_lo_que_se_escribe_al_cliente_sigue_exigiendo_idioma(
    uow: UnidadDeTrabajo,  # noqa: F811
    puerto_de_mentira: dict[str, Any],  # noqa: F811
) -> None:
    _proveedor(uow)
    salida = gen.generar(
        uow,
        plantilla="redactar_correo",
        datos={"destinatario": "Pierre", "proposito": "relancer le devis"},
        principal=_principal("*:*"),
    )
    assert salida["generado"] is False and "adivinarlo" in salida["porque"]


def test_la_garantia_de_no_entrenar_puede_ser_del_contrato_pero_tiene_que_constar() -> None:
    from crmcore.errors import ErrorDependencia

    from services.intelligence import dialectos

    base = {
        "formato": "gemini_generate",
        "modelo": "gemini-2.5-flash",
        "mensajes": [{"role": "user", "content": "Hola"}],
        "opt_out": True,
        "max_tokens": 100,
    }
    with pytest.raises(ErrorDependencia) as error:
        dialectos.peticion(**base)
    assert error.value.error_code == "ia.opt_out_sin_campo"
    cuerpo = dialectos.peticion(**base, opt_out_contrato="Contrato API de pago, 2026")
    # No se inventa un campo que el proveedor no tiene.
    assert set(cuerpo) <= {"contents", "systemInstruction", "generationConfig", "tools"}


# ── Las rutas de las fichas: reúnen los hechos y piden ────────────────────


def _cliente(nombre: str) -> Any:
    from tests.unit.test_lo_que_preguntan_las_pantallas_de_apoyo import _cliente as cli

    return cli(nombre)


def _cab(tenant_id: UUID, permisos: str = "*:*") -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: permisos},
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def pedidos(monkeypatch: Any) -> list[tuple[str, Any]]:
    """Lo que las fichas leen y piden, sin salir a otro servicio."""
    from crmcore import ia_ficha

    vistos: list[tuple[str, Any]] = []
    lecturas: dict[str, Any] = {}

    def _leer(ruta: str, principal: Any, parametros: Any = None) -> Any:
        vistos.append(("leer", ruta))
        for clave, valor in lecturas.items():
            if clave in ruta:
                return valor
        return {}

    def _pedir(ruta: str, cuerpo: dict[str, Any], principal: Any) -> Any:
        vistos.append((ruta, cuerpo))
        return {"generado": True}

    monkeypatch.setattr(ia_ficha, "leer", _leer)
    monkeypatch.setattr(ia_ficha, "pedir", _pedir)
    vistos.append(("lecturas", lecturas))
    return vistos


def test_la_ficha_de_la_cuenta_pide_el_resumen_con_su_360(
    db: Any, tenant_id: UUID, pedidos: list[Any]
) -> None:
    pedidos[0][1]["/360"] = {
        "cuenta": {"nombre": "Metales Norte", "estado": "activa"},
        "contactos": [{"nombre_completo": "Marta Ruiz", "cargo": "Compras"}],
        "timeline": [{"tipo": "llamada", "titulo": "Queja"}],
        "metricas": {},
    }
    for cli in _cliente("party"):
        cuenta = uuid4()
        r = cli.post(f"/api/v1/accounts/{cuenta}/resumen-ia", headers=_cab(tenant_id))
        assert r.status_code == 200, r.text
    ruta, cuerpo = pedidos[-1]
    assert ruta == "/api/v1/ia/asistencia/resumen-cuenta"
    assert cuerpo["hechos"]["nombre"] == "Metales Norte"
    assert cuerpo["hechos"]["contactos"][0]["cargo"] == "Compras"
    # La 360 se lee por su ruta, con la máscara de quien pide.
    assert ("leer", f"/api/v1/accounts/{cuenta}/360") in pedidos


def test_el_correo_al_contacto_va_en_su_idioma(
    db: Any, tenant_id: UUID, pedidos: list[Any]
) -> None:
    pedidos[0][1]["/contacts/"] = {"nombre_completo": "Pierre Martin", "idioma": "fr"}
    for cli in _cliente("party"):
        r = cli.post(
            f"/api/v1/contacts/{uuid4()}/redactar-correo",
            headers=_cab(tenant_id),
            json={"proposito": "Relancer le devis"},
        )
        assert r.status_code == 200, r.text
        _, cuerpo = pedidos[-1]
        assert cuerpo["idioma"] == "fr"
        assert cuerpo["datos"]["destinatario"] == "Pierre Martin"
        # Si se dice otro, manda el que se dice.
        cli.post(
            f"/api/v1/contacts/{uuid4()}/redactar-correo",
            headers=_cab(tenant_id),
            json={"proposito": "Relancer le devis", "idioma": "es"},
        )
        assert pedidos[-1][1]["idioma"] == "es"


def test_el_caso_se_resume_con_su_historial_y_con_permiso_declarado(
    db: Any, tenant_id: UUID, pedidos: list[Any]
) -> None:
    import json

    pedidos[0][1]["/casos/"] = {
        "asunto": "No arranca la máquina",
        "descripcion": "Desde el lunes",
        "historial": [{"tipo": "nota", "texto": "Se pidió el número de serie"}],
    }
    for cli in _cliente("service"):
        r = cli.post(f"/api/v1/casos/{uuid4()}/resumen-ia", headers=_cab(tenant_id))
        assert r.status_code == 200, r.text
    ruta, cuerpo = pedidos[-1]
    assert ruta == "/api/v1/ia/generar" and cuerpo["plantilla"] == "resumen_caso"
    fragmento = cuerpo["contexto"][0]
    assert fragmento["permiso"] == "case:read"
    assert "número de serie" in json.loads(fragmento["texto"])["historial"][0]["texto"]


def test_sin_permiso_de_ia_no_se_pide_nada(db: Any, tenant_id: UUID, pedidos: list[Any]) -> None:
    for cli in _cliente("party"):
        r = cli.post(
            f"/api/v1/accounts/{uuid4()}/resumen-ia",
            headers=_cab(tenant_id, permisos="account:read"),
        )
        assert r.status_code == 403
    assert not [p for p in pedidos if p[0] != "lecturas"]


def test_la_conversacion_se_resume_se_lee_y_se_traduce_desde_su_ficha(
    db: Any, tenant_id: UUID, pedidos: list[Any]
) -> None:
    from services.service.omnicanal import Conversacion, Mensaje

    conversacion = Conversacion(tenant_id=tenant_id)
    db.add(conversacion)
    db.flush()
    for direccion, texto, interno in (
        ("entrante", "Bonjour, ma commande n'est pas arrivée", False),
        ("saliente", "La revisamos ahora mismo", False),
        ("saliente", "Nota: el transportista confirma retraso", True),
        ("entrante", "C'est la troisième fois, je veux parler à quelqu'un", False),
    ):
        db.add(
            Mensaje(
                tenant_id=tenant_id,
                conversacion_id=conversacion.id,
                canal="chat",
                direccion=direccion,
                cuerpo=texto,
                interno=interno,
            )
        )
    db.commit()
    for cli in _cliente("service"):
        base = f"/api/v1/conversaciones/{conversacion.id}"
        assert cli.post(f"{base}/resumen-ia", headers=_cab(tenant_id), json={}).status_code == 200
        ruta, cuerpo = pedidos[-1]
        assert ruta == "/api/v1/ia/conversacion/resumen"
        assert cuerpo["mensajes_totales"] == 4 and len(cuerpo["mensajes"]) == 4
        assert [m["quien"] for m in cuerpo["mensajes"]][:2] == ["cliente", "agente"]

        assert cli.post(f"{base}/intencion", headers=_cab(tenant_id)).status_code == 200
        ruta, cuerpo = pedidos[-1]
        # El ÚLTIMO mensaje del cliente, nunca una nota interna.
        assert ruta == "/api/v1/ia/conversacion/senal"
        assert cuerpo["texto"].startswith("C'est la troisième fois")

        r = cli.post(f"{base}/traducir", headers=_cab(tenant_id), json={"idioma": "es"})
        assert r.status_code == 200, r.text
        ruta, cuerpo = pedidos[-1]
        assert cuerpo["plantilla"] == "traducir" and cuerpo["idioma"] == "es"
        assert cuerpo["datos"]["texto"].startswith("C'est la troisième fois")

        vacia = Conversacion(tenant_id=tenant_id)
        db.add(vacia)
        db.commit()
        r = cli.post(
            f"/api/v1/conversaciones/{vacia.id}/resumen-ia", headers=_cab(tenant_id), json={}
        )
        assert r.status_code == 422 and r.json()["error_code"] == "ia.conversacion_vacia"
