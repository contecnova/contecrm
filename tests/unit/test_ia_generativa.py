"""IA generativa: enrutado, guardarraíles, generación, RAG, extracción y coste
(CRM-05.02.02.01 a .10).

El puerto hacia el modelo se sustituye por uno de mentira a propósito: lo que hay
que comprobar no es que el proveedor conteste, es **qué se le manda y qué se hace
con lo que vuelve**. Ahí están los fallos que importan:

  * datos personales saliendo hacia un modelo sin que nadie lo autorizara,
  * un resumen construido con documentos que el usuario no podía abrir,
  * una respuesta perfecta sin una sola fuente comprobable,
  * un campo extraído que pisa el que había escrito una persona,
  * y una factura que nadie vio venir.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz.principal import Principal
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, Prohibido

from services.intelligence import enrutador as rut
from services.intelligence import extraccion as ext
from services.intelligence import generacion as gen
from services.intelligence import guardias as gua
from services.intelligence import rag as rag_mod
from services.intelligence import uso as med


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture(autouse=True)
def puerto_de_mentira() -> Any:
    """Conecta puertos controlados y guarda lo que se les manda."""
    enviado: dict[str, Any] = {}

    def _generar(**kw: Any) -> dict[str, Any]:
        enviado.update(kw)
        return {
            "texto": "Estimado cliente: le confirmamos la visita.",
            "modelo": kw.get("modelo") or "modelo-prueba",
            "tokens_entrada": 100,
            "tokens_salida": 40,
        }

    def _responder(**kw: Any) -> dict[str, Any]:
        enviado.update(kw)
        return {
            "texto": "El contrato vence en marzo [1].",
            "tokens_entrada": 80,
            "tokens_salida": 20,
        }

    def _traducir(**kw: Any) -> dict[str, Any]:
        enviado.update(kw)
        return {
            "plan": {
                "objeto": "oportunidad",
                "campos": ["importe"],
                "filtros": [{"campo": "etapa", "operador": "=", "valor": "cierre"}],
            },
            "interpretacion": "Importe de las oportunidades en cierre",
            "tokens_entrada": 50,
            "tokens_salida": 30,
        }

    def _extraer(**kw: Any) -> dict[str, Any]:
        enviado.update(kw)
        return {
            "campos": [
                {"clave": "nif", "valor": "B12345678", "confianza": 0.95, "cita": "NIF B12345678"},
            ],
            "tokens_entrada": 60,
            "tokens_salida": 15,
        }

    gen.registrar_generador(_generar)
    rag_mod.registrar_respondedor(_responder)
    rag_mod.registrar_traductor(_traducir)
    ext.registrar_extractor(_extraer)
    return enviado


def _proveedor(uow: UnidadDeTrabajo, **kw: Any) -> rut.ProveedorIA:
    base: dict[str, Any] = {
        "clave": "modelo-ue",
        "base_url": "https://ia.example.com/v1",
        "region": "ue",
        "admite_opt_out": True,
        "modelos": [
            {"uso": "redaccion", "nombre": "m-redaccion"},
            {"uso": "resumen", "nombre": "m-resumen"},
            {"uso": "consulta", "nombre": "m-consulta"},
            {"uso": "extraccion", "nombre": "m-extraccion"},
            {"uso": "traduccion", "nombre": "m-traduccion"},
        ],
        "coste_entrada_millon": Decimal("1.00"),
        "coste_salida_millon": Decimal("3.00"),
    }
    base.update(kw)
    fila, _ = rut.registrar_proveedor(uow, **base)
    return fila


def _principal(*permisos: str) -> Principal:
    return Principal(id=uuid4(), permisos=frozenset(permisos))


# ── Enrutado de modelos (CRM-05.02.02.10, .09) ────────────────────────────


def test_sin_proveedores_se_dice_en_vez_de_fallar_raro(uow: UnidadDeTrabajo) -> None:
    salida = rut.elegir(uow.db, uow.tenant_id, uso="redaccion")
    assert salida["puede_llamar"] is False
    assert salida["motivo_codigo"] == "sin_proveedor"


def test_un_proveedor_sin_opt_out_se_descarta_y_se_explica(uow: UnidadDeTrabajo) -> None:
    """No basta con haberlo firmado: la garantía es técnica, y si el proveedor no
    la da, no se usa."""
    _proveedor(uow, clave="sin-opt-out", admite_opt_out=False)
    rut.fijar_politica(uow, exigir_opt_out=True)
    salida = rut.elegir(uow.db, uow.tenant_id, uso="redaccion")
    assert salida["puede_llamar"] is False
    assert "no garantiza" in salida["descartados"][0]["porque"]


def test_la_region_es_una_condicion_no_una_preferencia(uow: UnidadDeTrabajo) -> None:
    """Llamar igual y anotarlo es contarle después a alguien que sus datos ya
    salieron."""
    _proveedor(uow, clave="fuera", region="ee_uu")
    rut.fijar_politica(uow, regiones_admitidas=["ue"], exigir_opt_out=False)
    salida = rut.elegir(uow.db, uow.tenant_id, uso="redaccion")
    assert salida["puede_llamar"] is False
    assert "solo admite" in salida["descartados"][0]["porque"]


def test_el_modelo_propio_del_tenant_gana(uow: UnidadDeTrabajo) -> None:
    """Es su modelo, en su casa."""
    _proveedor(uow, clave="general")
    _proveedor(uow, clave="suyo", solo_este_tenant=True)
    salida = rut.elegir(uow.db, uow.tenant_id, uso="redaccion")
    assert salida["elegido"] == "suyo"
    assert salida["propio_del_tenant"] is True


def test_el_interruptor_corta_aunque_todo_lo_demas_este_bien(
    uow: UnidadDeTrabajo,
) -> None:
    _proveedor(uow)
    with pytest.raises(ErrorValidacion):
        rut.apagar(uow, motivo="")
    rut.apagar(uow, motivo="Se ha detectado una fuga en el proveedor")
    salida = rut.elegir(uow.db, uow.tenant_id, uso="redaccion")
    assert salida["puede_llamar"] is False and salida["motivo_codigo"] == "apagada"
    with pytest.raises(Prohibido):
        rut.exigir_disponible(uow.db, uow.tenant_id, uso="redaccion")


def test_el_presupuesto_corta_antes_de_llamar(uow: UnidadDeTrabajo) -> None:
    """Comprobarlo después es descubrir que ya se gastó, y la factura llega
    igual."""
    _proveedor(uow)
    rut.fijar_politica(uow, presupuesto_mes=Decimal("1.00"))
    rut.anotar_gasto(
        uow, proveedor="modelo-ue", tokens_entrada=0, tokens_salida=0, coste=Decimal("1.50")
    )
    estado = rut.presupuesto(uow.db, uow.tenant_id)
    assert estado["agotado"] is True
    with pytest.raises(Conflicto):
        rut.exigir_disponible(uow.db, uow.tenant_id, uso="redaccion")


def test_sin_tope_declarado_se_dice_que_no_hay_tope(uow: UnidadDeTrabajo) -> None:
    _proveedor(uow)
    estado = rut.presupuesto(uow.db, uow.tenant_id)
    assert estado["con_tope"] is False and estado["agotado"] is False


# ── Guardarraíles (CRM-05.02.02.07) ───────────────────────────────────────


def test_el_contexto_se_filtra_por_permisos_antes_de_generar(
    uow: UnidadDeTrabajo,
) -> None:
    """Filtrar la respuesta ya redactada es imposible: el modelo ya mezcló lo que
    podía con lo que no."""
    salida = gua.filtrar_contexto(
        uow.db,
        uow.tenant_id,
        fragmentos=[
            {"texto": "Puede verlo", "permiso": "account:read", "fuente": "a"},
            {"texto": "No puede verlo", "permiso": "commission:read", "fuente": "b"},
        ],
        principal=_principal("account:read"),
    )
    assert [f["fuente"] for f in salida["fragmentos"]] == ["a"]
    assert salida["completo"] is False and salida["aviso"]


def test_un_fragmento_sin_permiso_declarado_se_descarta(uow: UnidadDeTrabajo) -> None:
    """Ante la duda no se enseña: el coste de equivocarse al revés es enseñar lo
    que no se podía ver."""
    salida = gua.filtrar_contexto(
        uow.db,
        uow.tenant_id,
        fragmentos=[{"texto": "Algo", "fuente": "x"}],
        principal=_principal("*:*"),
    )
    assert salida["fragmentos"] == []
    assert "ante la duda" in salida["quitados"][0]["porque"]


def test_lo_personal_no_sale_salvo_que_se_declare(uow: UnidadDeTrabajo) -> None:
    fragmentos = [
        {
            "texto": "Historial médico",
            "permiso": "account:read",
            "sensibilidad": "especial",
            "fuente": "s",
        }
    ]
    principal = _principal("account:read")
    antes = gua.filtrar_contexto(uow.db, uow.tenant_id, fragmentos=fragmentos, principal=principal)
    assert antes["fragmentos"] == []

    _, avisos = gua.declarar_regla(uow, sensibilidades_permitidas=["interno", "especial"])
    assert any("base legal" in a for a in avisos)
    despues = gua.filtrar_contexto(
        uow.db, uow.tenant_id, fragmentos=fragmentos, principal=principal
    )
    assert len(despues["fragmentos"]) == 1


def test_los_patrones_sensibles_se_tapan_en_el_texto_libre(
    uow: UnidadDeTrabajo,
) -> None:
    """Ningún campo declara un IBAN escrito dentro de una nota."""
    gua.declarar_regla(uow, patrones_a_tapar=["iban", "email"])
    salida = gua.filtrar_contexto(
        uow.db,
        uow.tenant_id,
        fragmentos=[
            {
                "texto": "Paga a ES9121000418450200051332 y avisa a ana@empresa.com",
                "permiso": "account:read",
                "fuente": "nota",
            }
        ],
        principal=_principal("account:read"),
    )
    texto = salida["fragmentos"][0]["texto"]
    assert "ES9121000418450200051332" not in texto and "ana@empresa.com" not in texto
    assert salida["tapados"]["iban"] == 1


def test_una_regla_puede_cortar_en_vez_de_tapar(uow: UnidadDeTrabajo) -> None:
    gua.declarar_regla(uow, patrones_a_tapar=["iban"], cortar_si_aparece=True)
    with pytest.raises(Prohibido):
        gua.filtrar_contexto(
            uow.db,
            uow.tenant_id,
            fragmentos=[
                {
                    "texto": "ES9121000418450200051332",
                    "permiso": "account:read",
                    "fuente": "n",
                }
            ],
            principal=_principal("account:read"),
        )


# ── Generación (CRM-05.02.02.01, .02, .06) ────────────────────────────────


def _plantilla(uow: UnidadDeTrabajo, **kw: Any) -> gen.PlantillaPrompt:
    base: dict[str, Any] = {
        "clave": "correo-visita",
        "cuerpo": "Escribe un correo a {{cliente}} confirmando la visita.",
        "tarea": "redaccion",
        "sistema": "Tono formal, sin prometer descuentos.",
        "idioma_defecto": "es",
    }
    base.update(kw)
    fila, _ = gen.guardar_plantilla(uow, **base)
    return fila


def test_cambiar_una_plantilla_crea_version_y_exige_motivo(
    uow: UnidadDeTrabajo,
) -> None:
    """El día que los textos salgan raros, esto es lo único que explicará por
    qué."""
    _plantilla(uow)
    with pytest.raises(ErrorValidacion):
        _plantilla(uow, cuerpo="Otro texto {{cliente}}")
    nueva = _plantilla(uow, cuerpo="Otro texto {{cliente}}", motivo_version="Tono más directo")
    assert nueva.version == 2


def test_generar_con_un_marcador_sin_dato_no_manda_nada(
    uow: UnidadDeTrabajo, puerto_de_mentira: dict[str, Any]
) -> None:
    """Generar con huecos produce un texto que alguien manda sin verlos."""
    _proveedor(uow)
    _plantilla(uow)
    with pytest.raises(ErrorValidacion):
        gen.generar(uow, plantilla="correo-visita", datos={}, principal=_principal("*:*"))
    assert puerto_de_mentira == {}


def test_lo_generado_es_un_borrador_y_no_se_escribe(
    uow: UnidadDeTrabajo,
) -> None:
    _proveedor(uow)
    _plantilla(uow)
    salida = gen.generar(
        uow,
        plantilla="correo-visita",
        datos={"cliente": "Acme"},
        objeto="cuenta",
        objeto_id=uuid4(),
        principal=_principal("*:*"),
    )
    assert salida["generado"] is True
    assert salida["aplicado"] is False
    assert salida["texto"]
    assert salida["plantilla"] == "correo-visita v1"


def test_sin_idioma_declarado_no_se_genera(uow: UnidadDeTrabajo) -> None:
    """Contestar en castellano a un cliente francés es el error más frecuente."""
    _proveedor(uow)
    _plantilla(uow, clave="sin-idioma", idioma_defecto="")
    salida = gen.generar(
        uow, plantilla="sin-idioma", datos={"cliente": "Acme"}, principal=_principal("*:*")
    )
    assert salida["generado"] is False
    assert "adivinarlo" in salida["porque"]


def test_un_resumen_sin_contexto_suficiente_no_llama_al_modelo(
    uow: UnidadDeTrabajo, puerto_de_mentira: dict[str, Any]
) -> None:
    """Redactaría algo plausible y vacío: cuesta dinero y engaña."""
    _proveedor(uow)
    _plantilla(uow, clave="resumen", tarea="resumen", cuerpo="Resume {{cliente}}")
    salida = gen.generar(
        uow,
        plantilla="resumen",
        datos={"cliente": "Acme"},
        contexto=[{"texto": "Nada", "permiso": "account:read", "fuente": "x"}],
        principal=_principal("account:read"),
    )
    assert salida["generado"] is False
    assert "plausible y vacío" in salida["porque"]
    assert puerto_de_mentira == {}


def test_lo_que_se_quito_por_permisos_viaja_con_la_respuesta(
    uow: UnidadDeTrabajo,
) -> None:
    _proveedor(uow)
    _plantilla(uow)
    salida = gen.generar(
        uow,
        plantilla="correo-visita",
        datos={"cliente": "Acme"},
        contexto=[{"texto": "Secreto", "permiso": "commission:read", "fuente": "s"}],
        principal=_principal("account:read"),
    )
    assert salida["contexto_incompleto"] is True
    assert salida["quitados_por_permisos"]


def test_descartar_un_borrador_no_conserva_el_texto(uow: UnidadDeTrabajo) -> None:
    """Es un texto sobre un cliente que nadie ha validado, y esos textos acaban
    leyéndose como si fueran datos."""
    _proveedor(uow)
    _plantilla(uow)
    salida = gen.generar(
        uow, plantilla="correo-visita", datos={"cliente": "Acme"}, principal=_principal("*:*")
    )
    fila = gen.decidir(uow, UUID(salida["propuesta_id"]), estado="descartada")
    assert fila.texto == ""


def test_marcar_editada_exige_el_texto_que_quedo(uow: UnidadDeTrabajo) -> None:
    """Sin él no se puede saber cuánto había que corregir."""
    _proveedor(uow)
    _plantilla(uow)
    salida = gen.generar(
        uow, plantilla="correo-visita", datos={"cliente": "Acme"}, principal=_principal("*:*")
    )
    with pytest.raises(ErrorValidacion):
        gen.decidir(uow, UUID(salida["propuesta_id"]), estado="editada")


def test_la_calidad_dice_cuando_nadie_ha_juzgado(uow: UnidadDeTrabajo) -> None:
    """Sin eso se sabe lo que cuesta la IA y no lo que vale."""
    _proveedor(uow)
    _plantilla(uow)
    gen.generar(
        uow, plantilla="correo-visita", datos={"cliente": "Acme"}, principal=_principal("*:*")
    )
    salida = gen.calidad(uow.db, uow.tenant_id)
    assert salida["medible"] is False and salida["aviso"]


# ── RAG con citación (CRM-05.02.02.03) ────────────────────────────────────


def _fragmento(texto: str = "El contrato vence en marzo.") -> dict[str, Any]:
    return {"texto": texto, "permiso": "account:read", "fuente": "contrato", "id": "DOC-1"}


def test_la_respuesta_trae_sus_citas(uow: UnidadDeTrabajo) -> None:
    _proveedor(uow)
    salida = rag_mod.responder(
        uow,
        pregunta="¿Cuándo vence?",
        fragmentos=[_fragmento()],
        principal=_principal("account:read"),
    )
    assert salida["respondida"] is True
    assert salida["citas"][0]["fuente"] == "contrato"
    assert salida["fiable"] is True


def test_una_respuesta_sin_citas_no_se_presenta_como_buena(
    uow: UnidadDeTrabajo,
) -> None:
    """Un párrafo perfecto sin fuente es lo que escribe un modelo cuando no
    encontró nada."""
    _proveedor(uow)
    rag_mod.registrar_respondedor(
        lambda **kw: {"texto": "Vence en marzo.", "tokens_entrada": 1, "tokens_salida": 1}
    )
    salida = rag_mod.responder(
        uow,
        pregunta="¿Cuándo vence?",
        fragmentos=[_fragmento()],
        principal=_principal("account:read"),
    )
    assert salida["respondida"] is False
    assert salida["fiable"] is False
    assert "no cita ninguna fuente" in salida["porque"]


def test_una_cita_inventada_se_marca(uow: UnidadDeTrabajo) -> None:
    """Tiene la misma forma que una buena."""
    _proveedor(uow)
    rag_mod.registrar_respondedor(
        lambda **kw: {
            "texto": "Vence en marzo [1] y se renueva [7].",
            "tokens_entrada": 1,
            "tokens_salida": 1,
        }
    )
    salida = rag_mod.responder(
        uow,
        pregunta="¿Cuándo vence?",
        fragmentos=[_fragmento()],
        principal=_principal("account:read"),
    )
    assert salida["citas_inventadas"] == [7]
    assert salida["fiable"] is False and salida["aviso"]


def test_que_el_modelo_diga_que_no_sabe_es_un_acierto(uow: UnidadDeTrabajo) -> None:
    """Es la respuesta que hace que las demás se puedan creer."""
    _proveedor(uow)
    rag_mod.registrar_respondedor(
        lambda **kw: {
            "texto": "No lo sé con el contexto dado.",
            # La señal la declara el adaptador —es él quien sabe cómo dice cada
            # modelo que no sabe—, igual que hace el puerto de verdad.
            "sin_respuesta": True,
            "tokens_entrada": 1,
            "tokens_salida": 1,
        }
    )
    salida = rag_mod.responder(
        uow,
        pregunta="¿Cuánto factura?",
        fragmentos=[_fragmento()],
        principal=_principal("account:read"),
    )
    assert salida["respondida"] is False and salida["fiable"] is True


def test_sin_contexto_visible_se_distingue_de_sin_contexto(
    uow: UnidadDeTrabajo,
) -> None:
    """Son dos problemas distintos y solo uno se arregla pidiendo permiso."""
    _proveedor(uow)
    salida = rag_mod.responder(
        uow,
        pregunta="¿Y esto?",
        fragmentos=[{"texto": "x", "permiso": "commission:read", "fuente": "c"}],
        principal=_principal("account:read"),
    )
    assert "que puedas ver" in salida["porque"]


# ── Consulta en lenguaje natural (CRM-05.02.02.04) ────────────────────────


def _modelo_datos() -> dict[str, Any]:
    return {
        "objetos": [
            {
                "clave": "oportunidad",
                "campos": [{"nombre": "importe"}, {"nombre": "etapa"}],
            }
        ]
    }


def test_la_pregunta_se_traduce_a_un_plan_y_no_se_ejecuta(
    uow: UnidadDeTrabajo,
) -> None:
    """Dejar que el modelo escriba SQL sería darle acceso a cualquier tabla."""
    _proveedor(uow)
    salida = rag_mod.preguntar_a_los_datos(
        uow,
        pregunta="¿Cuánto hay en cierre?",
        modelo_datos=_modelo_datos(),
        principal=_principal("*:*"),
    )
    assert salida["valido"] is True
    assert salida["ejecutado"] is False
    assert salida["interpretacion"]


def test_un_plan_con_un_campo_inventado_se_rechaza(uow: UnidadDeTrabajo) -> None:
    """Produciría una consulta que falla lejos de aquí, con un error que no se
    parece a la causa."""
    _proveedor(uow)
    rag_mod.registrar_traductor(
        lambda **kw: {
            "plan": {"objeto": "oportunidad", "campos": ["margen_secreto"]},
            "interpretacion": "x",
            "tokens_entrada": 1,
            "tokens_salida": 1,
        }
    )
    salida = rag_mod.preguntar_a_los_datos(
        uow,
        pregunta="¿Y el margen?",
        modelo_datos=_modelo_datos(),
        principal=_principal("*:*"),
    )
    assert salida["valido"] is False
    assert salida["plan"] is None


# ── Extracción estructurada (CRM-05.02.02.05) ─────────────────────────────


def test_lo_extraido_es_una_propuesta_con_su_cita(uow: UnidadDeTrabajo) -> None:
    _proveedor(uow)
    salida = ext.extraer(
        uow,
        texto="Nuestro NIF B12345678 para la factura.",
        campos=[{"clave": "nif", "tipo": "texto"}],
        objeto="cuenta",
        objeto_id=uuid4(),
        principal=_principal("account:read"),
    )
    assert salida["aplicado"] is False
    assert salida["extraidos"][0]["cita"] == "NIF B12345678"


def test_una_cita_que_no_esta_en_el_texto_se_descarta(uow: UnidadDeTrabajo) -> None:
    """La referencia es inventada, y sin comprobarla el valor entra igual."""
    _proveedor(uow)
    ext.registrar_extractor(
        lambda **kw: {
            "campos": [{"clave": "nif", "valor": "B999", "confianza": 0.99, "cita": "no aparece"}],
            "tokens_entrada": 1,
            "tokens_salida": 1,
        }
    )
    salida = ext.extraer(
        uow,
        texto="Texto sin ese dato",
        campos=[{"clave": "nif", "tipo": "texto"}],
        objeto="cuenta",
        principal=_principal("account:read"),
    )
    assert salida["extraidos"] == []
    assert "inventada" in salida["descartados"][0]["porque"]


def test_lo_que_ya_tiene_valor_queda_en_conflicto(uow: UnidadDeTrabajo) -> None:
    """El dato que ya estaba lo puso alguien, y una máquina no tiene autoridad
    para corregirlo en silencio."""
    _proveedor(uow)
    salida = ext.extraer(
        uow,
        texto="Nuestro NIF B12345678 para la factura.",
        campos=[{"clave": "nif", "tipo": "texto"}],
        objeto="cuenta",
        objeto_id=uuid4(),
        valores_actuales={"nif": "B00000000"},
        principal=_principal("account:read"),
    )
    assert salida["conflictos"] == 1
    assert salida["extraidos"][0]["estado"] == "conflicto"


def test_un_valor_que_no_convierte_se_marca_en_vez_de_guardarse(
    uow: UnidadDeTrabajo,
) -> None:
    """Un «el martes» dentro de una columna de fecha es basura con buena cara."""
    _proveedor(uow)
    ext.registrar_extractor(
        lambda **kw: {
            "campos": [
                {"clave": "cierre", "valor": "el martes", "confianza": 0.9, "cita": "el martes"}
            ],
            "tokens_entrada": 1,
            "tokens_salida": 1,
        }
    )
    salida = ext.extraer(
        uow,
        texto="Lo firmamos el martes",
        campos=[{"clave": "cierre", "tipo": "fecha"}],
        objeto="oportunidad",
        principal=_principal("account:read"),
    )
    assert salida["no_convertibles"] == 1
    campo_id = UUID(salida["extraidos"][0]["id"])
    with pytest.raises(ErrorValidacion):
        ext.decidir(uow, campo_id, aceptar=True)


def test_la_confianza_baja_no_se_propone(uow: UnidadDeTrabajo) -> None:
    """Revisarlo costaría más que escribirlo a mano, y entonces se deja de usar."""
    _proveedor(uow)
    ext.registrar_extractor(
        lambda **kw: {
            "campos": [{"clave": "nif", "valor": "B1", "confianza": 0.2, "cita": "B1"}],
            "tokens_entrada": 1,
            "tokens_salida": 1,
        }
    )
    salida = ext.extraer(
        uow,
        texto="Algo con B1 dentro",
        campos=[{"clave": "nif", "tipo": "texto"}],
        objeto="cuenta",
        principal=_principal("account:read"),
    )
    assert salida["extraidos"] == []
    assert "confianza" in salida["descartados"][0]["porque"]


def test_aceptar_pide_el_cambio_y_no_lo_escribe(uow: UnidadDeTrabajo) -> None:
    """Escribir desde aquí saltaría el metamodelo para la IA y para nadie más."""
    _proveedor(uow)
    salida = ext.extraer(
        uow,
        texto="Nuestro NIF B12345678 para la factura.",
        campos=[{"clave": "nif", "tipo": "texto"}],
        objeto="cuenta",
        objeto_id=uuid4(),
        principal=_principal("account:read"),
    )
    decision = ext.decidir(uow, UUID(salida["extraidos"][0]["id"]), aceptar=True)
    assert decision["estado"] == "aceptado"
    assert decision["cambio_pedido"] is True


def test_los_conflictos_salen_primero(uow: UnidadDeTrabajo) -> None:
    """Son los únicos donde equivocarse borra un dato que ya existía."""
    _proveedor(uow)
    ext.extraer(
        uow,
        texto="Nuestro NIF B12345678 para la factura.",
        campos=[{"clave": "nif", "tipo": "texto"}],
        objeto="cuenta",
        objeto_id=uuid4(),
        principal=_principal("account:read"),
    )
    ext.extraer(
        uow,
        texto="Nuestro NIF B12345678 para la factura.",
        campos=[{"clave": "nif", "tipo": "texto"}],
        objeto="cuenta",
        objeto_id=uuid4(),
        valores_actuales={"nif": "otro"},
        principal=_principal("account:read"),
    )
    salida = ext.pendientes(uow.db, uow.tenant_id)
    assert salida["campos"][0]["estado"] == "conflicto"


# ── Trazabilidad y coste (CRM-05.02.02.08) ────────────────────────────────


def test_cada_llamada_queda_registrada_con_su_coste(uow: UnidadDeTrabajo) -> None:
    _proveedor(uow)
    _plantilla(uow)
    gen.generar(
        uow,
        plantilla="correo-visita",
        datos={"cliente": "Acme"},
        objeto="cuenta",
        objeto_id=uuid4(),
        principal=_principal("*:*"),
    )
    salida = med.consumo(uow.db, uow.tenant_id)
    assert salida["llamadas"] == 1
    assert Decimal(salida["coste"]) > 0
    assert salida["por_tarea"]["redaccion"]["llamadas"] == 1


def test_el_historial_contesta_por_que_el_crm_escribio_esto(
    uow: UnidadDeTrabajo,
) -> None:
    _proveedor(uow)
    _plantilla(uow)
    objeto_id = uuid4()
    gen.generar(
        uow,
        plantilla="correo-visita",
        datos={"cliente": "Acme"},
        objeto="cuenta",
        objeto_id=objeto_id,
        principal=_principal("*:*"),
    )
    salida = med.historial_de(uow.db, uow.tenant_id, objeto="cuenta", objeto_id=objeto_id)
    assert salida["cuantas"] == 1
    assert salida["llamadas"][0]["plantilla"] == "correo-visita v1"
    assert salida["llamadas"][0]["region"] == "ue"
    assert salida["llamadas"][0]["opt_out"] is True


def test_no_se_guarda_el_texto_del_prompt_sino_su_huella(
    uow: UnidadDeTrabajo,
) -> None:
    """Guardarlo duplicaría dentro de la auditoría todos los datos personales del
    CRM, y sin la retención de su tabla de origen."""
    _proveedor(uow)
    _plantilla(uow)
    gen.generar(
        uow, plantilla="correo-visita", datos={"cliente": "Acme"}, principal=_principal("*:*")
    )
    fila = (
        uow.db.execute(med.select(med.LlamadaIA).where(med.LlamadaIA.tenant_id == uow.tenant_id))
        .scalars()
        .first()
    )
    assert fila is not None
    assert "Acme" not in fila.huella_prompt
    assert len(fila.huella_prompt) == 64


def test_la_tasa_de_descarte_solo_cuenta_lo_juzgado(uow: UnidadDeTrabajo) -> None:
    """Contar como aceptadas las que nadie miró inflaría el dato hasta no
    significar nada."""
    _proveedor(uow)
    _plantilla(uow)
    primera = gen.generar(
        uow, plantilla="correo-visita", datos={"cliente": "A"}, principal=_principal("*:*")
    )
    gen.generar(uow, plantilla="correo-visita", datos={"cliente": "B"}, principal=_principal("*:*"))
    gen.decidir(uow, UUID(primera["propuesta_id"]), estado="descartada")
    salida = med.consumo(uow.db, uow.tenant_id)
    assert salida["tasa_descarte"] == 100.0


def test_un_error_del_proveedor_tambien_se_registra(uow: UnidadDeTrabajo) -> None:
    """Un módulo que solo apunta los aciertos da una tasa de éxito del 100 %."""
    _proveedor(uow)
    _plantilla(uow)

    def _revienta(**kw: Any) -> dict[str, Any]:
        raise RuntimeError("el proveedor no contesta")

    gen.registrar_generador(_revienta)
    with pytest.raises(RuntimeError):
        gen.generar(
            uow, plantilla="correo-visita", datos={"cliente": "A"}, principal=_principal("*:*")
        )
    salida = med.consumo(uow.db, uow.tenant_id)
    assert salida["errores"] == 1
