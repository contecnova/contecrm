"""Superficie de API para integradores: composición, sandbox, mTLS, portal,
SDK, tokenización y rastro de agregados
(CRM-00.02.01.02, .15, CRM-00.02.03.03, .04, .05, CRM-00.02.04.03, .06,
CRM-00.04.02.04, CRM-00.05.03.04, CRM-00.05.04.06).

Todo esto existe por la misma queja —«para pintar una pantalla tengo que hacer
siete llamadas»— y por su gemela: «llevo tres días peleando con las
credenciales». Las pruebas van detrás de las formas en que resolver eso mal abre
un agujero: una composición que enseña lo que sus partes no enseñarían, un
sandbox con datos de producción, un endpoint propio que se salta los controles.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import (
    Conflicto,
    ErrorDependencia,
    ErrorValidacion,
    NoAutenticado,
    Prohibido,
)

from services.gateway import superficie_api as sup

# ── Lectura compuesta y BFF (CRM-00.02.01.02, CRM-00.02.03.03) ────────────


def test_una_composicion_no_ensena_lo_que_sus_partes_no_ensenarian() -> None:
    """Devolverla entera sería convertir la comodidad en una vía de escalada."""
    salida = sup.validar_composicion(
        nombre="cuenta_con_oportunidades",
        partes=[
            {"nombre": "cuenta", "tipo": "ficha", "permiso": "account:read"},
            {"nombre": "oportunidades", "tipo": "lista", "permiso": "opportunity:read"},
        ],
        permisos_del_llamante={"account:read"},
    )
    assert salida["incluidas"] == ["cuenta"]
    assert salida["quitadas"][0]["parte"] == "oportunidades"


def test_lo_quitado_se_dice_para_que_nadie_crea_que_no_hay_datos() -> None:
    """El integrador creería que ese cliente no tiene oportunidades, y lo que
    pasa es que él no puede verlas."""
    salida = sup.validar_composicion(
        nombre="x",
        partes=[{"nombre": "oportunidades", "tipo": "lista", "permiso": "opportunity:read"}],
        permisos_del_llamante=set(),
    )
    assert salida["completa"] is False
    assert "no puede verlos" in salida["aviso"]


def test_una_composicion_demasiado_cara_se_rechaza_antes_de_ejecutarla() -> None:
    """Calcularlo después es descubrir que costaba mil cuando ya se han hecho las
    mil llamadas."""
    partes = [{"nombre": f"p{i}", "tipo": "lista_anidada"} for i in range(5)]
    with pytest.raises(Conflicto) as fallo:
        sup.validar_composicion(nombre="todo", partes=partes, permisos_del_llamante={"*:*"})
    assert fallo.value.error_code == "bff.demasiado_cara"


def test_una_lista_anidada_cuesta_mas_que_una_ficha() -> None:
    """No es el número de campos: es cuántas llamadas internas cuesta servirla."""
    assert sup.coste_de([{"tipo": "lista_anidada"}]) > sup.coste_de([{"tipo": "ficha"}])


def test_un_perfil_de_cliente_desconocido_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion):
        sup.validar_composicion(
            nombre="x",
            partes=[{"tipo": "ficha"}],
            permisos_del_llamante={"*:*"},
            perfil="nevera",
        )


# ── Sandbox (CRM-00.02.01.15) ─────────────────────────────────────────────


def test_el_sandbox_lleva_datos_sinteticos_y_lo_dice() -> None:
    """Copiar datos de producción a pruebas es cómo se filtra una base de
    clientes por un sitio sin las mismas protecciones."""
    salida = sup.crear_sandbox(tenant_id=uuid4(), objetos=["cuenta", "contacto"])
    assert salida["datos"] == "sinteticos"
    assert "se pueden romper" in salida["porque_sinteticos"]


def test_el_sandbox_caduca() -> None:
    """Uno eterno acumula credenciales que nadie recuerda y acaba siendo la
    puerta más vieja del sistema."""
    salida = sup.crear_sandbox(tenant_id=uuid4(), objetos=["cuenta"])
    assert salida["caduca_at"]
    assert "puerta más vieja" in salida["caduca_porque"]


# ── mTLS por integración (CRM-00.02.04.03) ────────────────────────────────


def test_sin_certificado_donde_se_exige_no_se_entra() -> None:
    with pytest.raises(NoAutenticado):
        sup.exigir_mtls(huella_declarada="abc", huella_presentada="", obligatorio=True)


def test_se_compara_la_huella_y_no_la_cadena() -> None:
    """Uno firmado por la misma autoridad no es el mismo certificado: aceptar
    cualquiera de la cadena convierte el mTLS en comprobar que existe una CA."""
    with pytest.raises(Prohibido) as fallo:
        sup.exigir_mtls(huella_declarada="abc", huella_presentada="otra", obligatorio=True)
    assert fallo.value.error_code == "mtls.certificado_distinto"


def test_quien_no_lo_exige_no_lo_necesita() -> None:
    """Obligarlo a todos deja fuera a quien se integra con un script de cuatro
    líneas."""
    sup.exigir_mtls(huella_declarada="", huella_presentada="", obligatorio=False)


# ── Portal de desarrollador (CRM-00.02.04.06) ─────────────────────────────


def test_los_errores_se_separan_por_culpa() -> None:
    """Mezclarlos hace que un integrador pase una tarde revisando su código por
    una caída nuestra."""
    salida = sup.panel_de_integrador(
        clave="k1",
        llamadas=[
            {"status": 200, "cuando": "1"},
            {"status": 422, "cuando": "2", "ruta": "/x"},
            {"status": 503, "cuando": "3", "ruta": "/y"},
        ],
        cuota_mes=100,
        scopes=["account:read"],
    )
    assert salida["errores_suyos"] == 1
    assert salida["errores_nuestros"] == 1
    assert "abre incidencia" in salida["que_mirar_primero"]


def test_el_portal_dice_cuanta_cuota_queda() -> None:
    salida = sup.panel_de_integrador(
        clave="k1", llamadas=[{"status": 200}] * 30, cuota_mes=100, scopes=[]
    )
    assert salida["consumido_pct"] == 30.0
    assert salida["quedan"] == 70


# ── Endpoints propios del tenant (CRM-00.04.02.04) ────────────────────────


def test_un_endpoint_propio_no_puede_pisar_una_ruta_del_producto() -> None:
    """El día que se publique la nuestra, una de las dos deja de funcionar."""
    with pytest.raises(ErrorValidacion) as fallo:
        sup.declarar_endpoint_propio(
            ruta="/api/v1/accounts", composicion="x", permiso="account:read", tenant_id=uuid4()
        )
    assert fallo.value.error_code == "endpoint.fuera_del_espacio"


def test_un_endpoint_propio_sin_permiso_no_se_declara() -> None:
    """Sería el único sitio del producto donde se entra sin comprobar nada."""
    with pytest.raises(ErrorValidacion):
        sup.declarar_endpoint_propio(
            ruta="/api/v1/x/mi-vista", composicion="x", permiso="", tenant_id=uuid4()
        )


def test_un_endpoint_propio_hereda_los_mismos_controles() -> None:
    """Un camino que no pasa por donde pasan los demás es un camino donde los
    controles se ponen otra vez, peor y más tarde."""
    salida = sup.declarar_endpoint_propio(
        ruta="/api/v1/x/mi-vista",
        composicion="cuenta_con_oportunidades",
        permiso="account:read",
        tenant_id=uuid4(),
    )
    assert "la misma auditoría" in salida["hereda"]


# ── SDK y componentes (CRM-00.02.03.04, .05) ──────────────────────────────


def test_el_plan_de_sdk_dice_lo_que_ningun_generador_hace() -> None:
    """Sin esa lista, «tenemos SDK» significa «tenemos un cliente HTTP con los
    nombres de los endpoints»."""
    from crmcore import sdk

    salida = sdk.plan_de_generacion(lenguajes=["python", "go"], version_api="v1")
    assert "paginacion" in salida["hay_que_escribirlo_a_mano"]
    assert "idempotencia" in salida["hay_que_escribirlo_a_mano"]


def test_un_lenguaje_no_soportado_se_rechaza() -> None:
    from crmcore import sdk

    with pytest.raises(ErrorValidacion):
        sdk.plan_de_generacion(lenguajes=["cobol"], version_api="v1")


def test_un_componente_embebible_no_usa_la_sesion_del_crm() -> None:
    """Un componente con la sesión del CRM en una web pública deja entrar a quien
    pase por ahí: basta con abrir las herramientas del navegador."""
    from crmcore import sdk

    salida = sdk.contrato_de_componente("ficha-cuenta")
    assert "token acotado" in salida["identidad"]
    assert salida["contrato_publico"] is True


# ── Tokenización (CRM-00.05.03.04) ────────────────────────────────────────


def test_sin_boveda_no_se_tokeniza_en_falso() -> None:
    """Guardar el número «hasta que haya bóveda» mete el sistema en el alcance de
    PCI sin que nadie lo haya decidido."""
    from crmcore.security import tokenizacion as tok

    with pytest.raises(ErrorDependencia) as fallo:
        tok.tokenizar("4111111111111111", tipo="tarjeta", tenant_id=uuid4())
    assert fallo.value.error_code == "tokenizacion.sin_boveda"


def test_del_nif_no_queda_pista_visible() -> None:
    """Con la letra y dos dígitos se adivina el resto."""
    from crmcore.security import tokenizacion as tok

    tok.registrar_boveda(lambda **kw: "tok-1", lambda **kw: "valor")
    try:
        tarjeta = tok.tokenizar("4111111111111111", tipo="tarjeta", tenant_id=uuid4())
        nif = tok.tokenizar("12345678Z", tipo="identificador_fiscal", tenant_id=uuid4())
        assert tarjeta["pista"] == "1111"
        assert nif["pista"] == ""
    finally:
        tok._boveda = None
        tok._destokenizador = None


def test_destokenizar_exige_motivo() -> None:
    """Sin motivo, la lista de accesos es una lista de nombres sin nada que
    decidir."""
    from crmcore.security import tokenizacion as tok

    tok.registrar_boveda(lambda **kw: "tok-1", lambda **kw: "4111111111111111")
    try:
        with pytest.raises(ErrorValidacion):
            tok.destokenizar("tok-1", tipo="tarjeta", tenant_id=uuid4(), motivo="", por=uuid4())
    finally:
        tok._boveda = None
        tok._destokenizador = None


def test_se_caza_una_tarjeta_colada_en_texto_libre() -> None:
    """El caso real es un integrador que manda el número en un campo de notas, y
    ahí se queda."""
    from crmcore.security import tokenizacion as tok

    salida = tok.comprobar_no_hay_numeros({"notas": "forma de pago: 4111 1111 1111 1111"})
    assert "notas" in salida


def test_un_numero_largo_cualquiera_no_da_la_alarma() -> None:
    """Un aviso que salta con todo se ignora a la semana."""
    from crmcore.security import tokenizacion as tok

    assert tok.comprobar_no_hay_numeros({"ref": "9999999999999999"}) == []


# ── Rastro de agregados (CRM-00.05.04.06) ─────────────────────────────────


@pytest.mark.db
def test_no_se_anota_en_un_agregado_que_nadie_ha_encendido(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Encenderlo para todo multiplica la escritura por algo que casi nunca se
    consulta."""
    from crmcore.datos import event_sourcing as es

    with pytest.raises(ErrorValidacion) as fallo:
        es.anotar(
            db, tenant_id=tenant_id, objeto="nota", objeto_id=uuid4(), tipo="creada", datos={}
        )
    assert fallo.value.error_code == "event_sourcing.agregado_no_declarado"


@pytest.mark.db
def test_se_reconstruye_como_estaba_en_un_momento(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es la pregunta que llega siempre tarde y que el historial de campos no
    contesta: dice qué cambió, no cómo era el conjunto."""
    from crmcore.datos import event_sourcing as es

    es.declarar_agregado("oportunidad", "Se pregunta cómo estaba al cerrar el trimestre")
    oportunidad = uuid4()
    es.anotar(
        db,
        tenant_id=tenant_id,
        objeto="oportunidad",
        objeto_id=oportunidad,
        tipo="creada",
        datos={"importe": 1000, "etapa": "inicial"},
    )
    es.anotar(
        db,
        tenant_id=tenant_id,
        objeto="oportunidad",
        objeto_id=oportunidad,
        tipo="avanzada",
        datos={"etapa": "negociacion"},
    )
    salida = es.reconstruir(db, tenant_id, objeto="oportunidad", objeto_id=oportunidad)
    assert salida["estado"] == {"importe": 1000, "etapa": "negociacion"}


@pytest.mark.db
def test_un_hecho_no_se_edita_se_compensa(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Si el error desapareciera, la reconstrucción saldría como si nunca se
    hubiera equivocado nadie."""
    from crmcore.datos import event_sourcing as es

    es.declarar_agregado("oportunidad", "Se pregunta cómo estaba al cerrar el trimestre")
    oportunidad = uuid4()
    hecho = es.anotar(
        db,
        tenant_id=tenant_id,
        objeto="oportunidad",
        objeto_id=oportunidad,
        tipo="descuento",
        datos={"descuento": 90},
    )
    es.compensar(db, tenant_id=tenant_id, hecho_id=hecho.id, motivo="Se metió mal")

    salida = es.reconstruir(db, tenant_id, objeto="oportunidad", objeto_id=oportunidad)
    assert "descuento" not in salida["estado"]
    assert salida["hechos"] == 2, "el original sigue ahí"


@pytest.mark.db
def test_una_reconstruccion_que_no_cuadra_con_lo_vivo_se_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es la única forma de saber que alguien escribió en la tabla sin pasar por
    aquí — que es exactamente lo que acaba pasando, y en silencio."""
    from crmcore.datos import event_sourcing as es

    es.declarar_agregado("oportunidad", "Se pregunta cómo estaba al cerrar el trimestre")
    oportunidad = uuid4()
    es.anotar(
        db,
        tenant_id=tenant_id,
        objeto="oportunidad",
        objeto_id=oportunidad,
        tipo="creada",
        datos={"importe": 1000},
    )
    salida = es.cuadra_con_lo_vivo(
        db,
        tenant_id,
        objeto="oportunidad",
        objeto_id=oportunidad,
        estado_vivo={"importe": 2000},
    )
    assert salida["cuadra"] is False
    assert "sin pasar por el rastro" in salida["que_significa"]


@pytest.mark.db
def test_encender_un_agregado_exige_decir_por_que(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Dentro de dos años alguien mirará por qué esta tabla ocupa lo que ocupa."""
    from crmcore.datos import event_sourcing as es

    with pytest.raises(ErrorValidacion):
        es.declarar_agregado("contrato", "  ")
