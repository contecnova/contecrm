"""Modelos predictivos y señales de conversación (CRM-05.02.01.01 a .07,
CRM-03.02.01.06, CRM-04.02.02.06 y CRM-04.02.02.07).

Lo que se comprueba aquí no es que los números salgan: es que **el sistema sepa
cuándo no sabe**. Un predictor que siempre contesta algo es exactamente el que
deja de usarse a los dos meses, porque la primera vez que alguien comprueba una
de sus respuestas y no se sostiene, deja de comprobar las demás.

Por eso casi todas estas pruebas van sobre el silencio: el modelo sin métricas
que no se activa, el modelo caducado que deja de puntuar, la serie corta que no
avisa, la cuenta sin señales que no se puntúa, la clasificación por debajo del
umbral que no dice «neutro».
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz.principal import Principal
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorDependencia, ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy

from services.intelligence import anomalias as ano
from services.intelligence import conversacion as conv
from services.intelligence import enrutador as rut
from services.intelligence import gobierno as gob
from services.intelligence import prediccion as pred
from services.intelligence import salud as sal


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture(autouse=True)
def puertos_de_mentira() -> Any:
    """Puertos controlados: lo que se comprueba es qué se manda y qué se hace con
    lo que vuelve, no que el proveedor conteste."""
    estado: dict[str, Any] = {"confianza": 0.9, "sentimiento": "negativo"}

    def _resumir(**kw: Any) -> dict[str, Any]:
        estado.update(kw)
        return {
            "texto": "El cliente reclama una factura duplicada.",
            "pendientes": ["Devolver el importe antes del viernes"],
            "tokens_entrada": 200,
            "tokens_salida": 40,
        }

    def _clasificar(**kw: Any) -> dict[str, Any]:
        estado.update(kw)
        return {
            "sentimiento": estado["sentimiento"],
            "intencion": "reclamacion",
            "confianza": estado["confianza"],
            "indicios": ["es la tercera vez que llamo"],
            "tokens_entrada": 30,
            "tokens_salida": 10,
        }

    conv.registrar_resumidor(_resumir)
    conv.registrar_clasificador(_clasificar)
    return estado


def _proveedor(uow: UnidadDeTrabajo) -> None:
    rut.registrar_proveedor(
        uow,
        clave="modelo-ue",
        base_url="https://ia.example.com/v1",
        region="ue",
        admite_opt_out=True,
        modelos=[
            {"uso": "resumen", "nombre": "m-resumen"},
            {"uso": "clasificacion", "nombre": "m-clasificacion"},
        ],
        coste_entrada_millon=Decimal("1.00"),
        coste_salida_millon=Decimal("3.00"),
    )


def _modelo(uow: UnidadDeTrabajo, **kw: Any) -> Any:
    base: dict[str, Any] = {
        "tipo": "scoring_lead",
        "variables": ["visitas", "presupuestos", "dias_sin_contacto"],
        "pesos": {
            "_sesgo": -1.0,
            "visitas": 0.3,
            "presupuestos": 0.9,
            "dias_sin_contacto": -0.15,
        },
        "metricas": {"auc": 0.78, "precision": 0.7, "recall": 0.6, "muestras": 900},
        "ejemplos": 900,
    }
    base.update(kw)
    modelo, _ = gob.registrar_version(uow, **base)
    return modelo


# ── Gobierno de modelos (CRM-05.02.01.07, .06) ────────────────────────────


def test_un_modelo_sin_metricas_no_se_activa(uow: UnidadDeTrabajo) -> None:
    """Es la puerta por la que entra en producción un modelo que nadie ha medido:
    se entrena el viernes, se activa «para probar», y allí se queda."""
    modelo = _modelo(uow, metricas={})
    with pytest.raises(Conflicto) as fallo:
        gob.activar(uow, tipo=modelo.tipo, version=modelo.version)
    assert "métricas" in str(fallo.value)


def test_activar_compara_con_la_version_anterior(uow: UnidadDeTrabajo) -> None:
    """Activar a ciegas es cómo un modelo peor se queda meses dando peores números
    sin que nadie lo note."""
    primero = _modelo(uow)
    gob.activar(uow, tipo="scoring_lead", version=primero.version)
    segundo = _modelo(uow, metricas={"auc": 0.62, "precision": 0.5, "recall": 0.5, "muestras": 400})
    salida = gob.activar(uow, tipo="scoring_lead", version=segundo.version)
    assert salida["comparacion"]["habia_anterior"] is True
    assert salida["comparacion"]["mejora"] is False
    assert salida["comparacion"]["aviso"], "activar algo peor tiene que verse"


def test_un_modelo_caducado_deja_de_puntuar(uow: UnidadDeTrabajo) -> None:
    """Un modelo entrenado con el mercado del año pasado sigue contestando tan
    seguro como el primer día. Por eso caduca."""
    modelo = _modelo(uow, vigencia_dias=30)
    gob.activar(uow, tipo="scoring_lead", version=modelo.version)
    assert gob.activo(uow.db, uow.tenant_id, "scoring_lead") is not None
    futuro = hoy(uow.db) + timedelta(days=45)
    assert gob.activo(uow.db, uow.tenant_id, "scoring_lead", hoy=futuro) is None


def test_la_deriva_con_pocas_muestras_no_es_concluyente(uow: UnidadDeTrabajo) -> None:
    """Treinta casos no dicen si el modelo se ha estropeado; decir que sí es
    provocar un reentrenamiento por ruido."""
    modelo = _modelo(uow)
    gob.activar(uow, tipo="scoring_lead", version=modelo.version)
    salida = gob.medir_deriva(
        uow,
        tipo="scoring_lead",
        metrica="auc",
        valor=0.55,
        muestras=30,
        desde=hoy(uow.db) - timedelta(days=30),
        hasta=hoy(uow.db),
    )
    assert salida["concluyente"] is False


def test_la_deriva_medida_se_puede_LEER(uow: UnidadDeTrabajo) -> None:
    """Se anotaba y no la leía nadie, que es medirla sin mirarla.

    Había `POST /deriva` para anotar una medición y **ninguna ruta para
    verlas**, así que «qué tal va acertando el modelo con el tiempo» se cumplía
    a medias. Una deriva que no se mira no avisa de nada.

    Y cada medición tiene que venir con **su referencia y su caída**: un AUC de
    0,71 no dice nada solo y dice mucho al lado del 0,86 con el que se entrenó.
    Con las muestras al lado, además, porque una caída medida sobre treinta
    casos no es la misma noticia que una medida sobre treinta mil.
    """
    modelo = _modelo(uow)
    gob.activar(uow, tipo="scoring_lead", version=modelo.version)
    gob.medir_deriva(
        uow,
        tipo="scoring_lead",
        metrica="auc",
        valor=0.55,
        muestras=4000,
        desde=hoy(uow.db) - timedelta(days=30),
        hasta=hoy(uow.db),
    )

    historial = gob.historial_de_deriva(uow.db, uow.tenant_id)
    assert historial["cuantas"] == 1
    medicion = historial["mediciones"][0]
    for campo in ("valor", "referencia", "caida", "muestras", "desde", "hasta"):
        assert campo in medicion, f"la pantalla lee «{campo}» y no viene"
    assert medicion["muestras"] == 4000
    # La caída se calcula en el servidor: si la calculara cada pantalla, dos
    # pantallas acabarían dando dos números para lo mismo.
    assert Decimal(medicion["caida"]) == Decimal(medicion["referencia"]) - Decimal(
        medicion["valor"]
    )


def test_sin_mediciones_no_se_dice_que_el_modelo_acierta(uow: UnidadDeTrabajo) -> None:
    """«No se ha comprobado» y «sigue acertando» son cosas distintas, y una
    lista vacía se lee como la segunda."""
    historial = gob.historial_de_deriva(uow.db, uow.tenant_id)
    assert historial["cuantas"] == 0
    assert historial["aviso"], "una lista vacía sin aviso se lee como «va bien»"


# ── Scoring explicable (CRM-05.02.01.01, .03) ─────────────────────────────


def test_sin_modelo_activo_no_se_inventa_una_puntuacion(uow: UnidadDeTrabajo) -> None:
    """Devolver un 50 % sería lo cómodo y lo peor: se lee como un empate cuando
    en realidad es «no lo sé»."""
    with pytest.raises((NoEncontrado, ErrorValidacion)):
        pred.puntuar(
            uow,
            tipo="scoring_lead",
            objeto="lead",
            objeto_id=uuid4(),
            rasgos={"visitas": 3},
        )


def test_la_puntuacion_dice_lo_que_empuja_a_favor_y_en_contra(uow: UnidadDeTrabajo) -> None:
    """Un scoring que solo enseña lo bueno convierte a todos los leads en buenos
    leads, y entonces el comercial vuelve a su intuición — con razón."""
    modelo = _modelo(uow)
    gob.activar(uow, tipo="scoring_lead", version=modelo.version)
    salida = pred.puntuar(
        uow,
        tipo="scoring_lead",
        objeto="lead",
        objeto_id=uuid4(),
        rasgos={"visitas": 8, "presupuestos": 2, "dias_sin_contacto": 20},
    )
    assert salida["a_favor"], "sin factores a favor la puntuación no se puede defender"
    assert salida["en_contra"], "lo que resta también se enseña"
    assert salida["completa"] is True


def test_si_faltan_variables_se_puntua_pero_se_avisa(uow: UnidadDeTrabajo) -> None:
    """Una puntuación calculada sin la mitad de sus variables es peor, y quien la
    lea tiene que saberlo: en la ficha se ve igual de rotunda."""
    modelo = _modelo(uow)
    gob.activar(uow, tipo="scoring_lead", version=modelo.version)
    salida = pred.puntuar(
        uow, tipo="scoring_lead", objeto="lead", objeto_id=uuid4(), rasgos={"visitas": 4}
    )
    assert salida["completa"] is False
    assert "presupuestos" in salida["variables_ausentes"]
    assert salida["aviso"]


def test_una_prediccion_caducada_no_se_devuelve(uow: UnidadDeTrabajo) -> None:
    """Nadie mira la fecha de un número que aparece en una ficha."""
    modelo = _modelo(uow)
    gob.activar(uow, tipo="scoring_lead", version=modelo.version)
    objeto_id = uuid4()
    pred.puntuar(
        uow,
        tipo="scoring_lead",
        objeto="lead",
        objeto_id=objeto_id,
        rasgos={"visitas": 4, "presupuestos": 1, "dias_sin_contacto": 2},
        vigencia_dias=7,
    )
    futuro = datetime.now(timezone.utc) + timedelta(days=30)
    salida = pred.vigente(
        uow.db, uow.tenant_id, tipo="scoring_lead", objeto_id=objeto_id, ahora=futuro
    )
    assert salida["hay"] is False
    assert salida["caducada"] is True


def test_el_acierto_con_pocos_resultados_no_es_medible(uow: UnidadDeTrabajo) -> None:
    """Medir el acierto sobre cinco casos da un número precioso que no significa
    nada — y que alguien enseñará en una reunión."""
    salida = pred.acierto(uow.db, uow.tenant_id, tipo="scoring_lead")
    assert salida["medible"] is False


# ── Forecast predictivo (CRM-03.02.01.06) ─────────────────────────────────


def test_el_forecast_predictivo_se_pone_al_lado_del_humano(uow: UnidadDeTrabajo) -> None:
    """Sustituirlo hace que el comercial deje de comprometerse con su número, y el
    compromiso es la mitad del valor de un forecast."""
    modelo = _modelo(uow, tipo="cierre")
    gob.activar(uow, tipo="cierre", version=modelo.version)
    una = uuid4()
    pred.puntuar(
        uow,
        tipo="cierre",
        objeto="oportunidad",
        objeto_id=una,
        rasgos={"visitas": 9, "presupuestos": 3, "dias_sin_contacto": 1},
    )
    salida = pred.forecast_predictivo(
        uow.db,
        uow.tenant_id,
        oportunidades=[{"id": str(una), "importe": "10000"}],
        forecast_humano=Decimal("15000"),
    )
    assert salida["sustituye_al_humano"] is False
    assert salida["forecast_humano"] == "15000"
    assert salida["diferencia"] is not None


def test_el_forecast_dice_que_parte_del_pipeline_no_ha_podido_puntuar(
    uow: UnidadDeTrabajo,
) -> None:
    """Calculado sobre la mitad del pipeline parece bajo y no lo es: sin este aviso
    alguien concluye que el trimestre va mal."""
    salida = pred.forecast_predictivo(
        uow.db,
        uow.tenant_id,
        oportunidades=[{"id": str(uuid4()), "importe": "5000"}],
    )
    assert salida["cobertura_pct"] == 0.0
    assert salida["aviso"]


# ── Salud de cuenta y churn (CRM-05.02.01.04) ─────────────────────────────


def test_una_senal_ausente_no_puntua_cero(uow: UnidadDeTrabajo) -> None:
    """Contar «sin datos de uso» como uso nulo hundiría a todos los clientes de
    quien todavía no ha conectado la telemetría."""
    cuenta = uuid4()
    con_todo = sal.medir(
        uow,
        cuenta_id=cuenta,
        senales={
            "uso": 80,
            "soporte": 80,
            "relacion": 80,
            "pago": 80,
            "valor": 80,
            "patrocinador": 80,
        },
    )
    otra = sal.medir(uow, cuenta_id=uuid4(), senales={"uso": 80})
    assert float(otra.puntuacion) == pytest.approx(float(con_todo.puntuacion))
    assert "pago" in otra.senales_ausentes
    assert otra.fiable is False, "con más de la mitad del peso sin medir, el número no es fiable"


def test_sin_ninguna_senal_no_se_inventa_una_salud(uow: UnidadDeTrabajo) -> None:
    """Un 50 por defecto se lee como «regular», no como «no lo sabemos»."""
    with pytest.raises(ErrorValidacion):
        sal.medir(uow, cuenta_id=uuid4(), senales={})


def test_las_cuentas_poco_fiables_no_desaparecen_de_la_lista_de_riesgo(
    uow: UnidadDeTrabajo,
) -> None:
    """Si desaparecieran sin más, una instalación a la que le falta la mitad de las
    señales vería una lista corta y creería que va bien."""
    sal.medir(uow, cuenta_id=uuid4(), senales={"uso": 10})
    salida = sal.en_riesgo(uow.db, uow.tenant_id)
    assert salida["ocultas_por_poco_fiables"] == 1
    assert salida["aviso"]


def test_riesgo_no_se_presenta_como_churn_confirmado(uow: UnidadDeTrabajo) -> None:
    sal.medir(
        uow,
        cuenta_id=uuid4(),
        senales={
            "uso": 10,
            "soporte": 15,
            "relacion": 20,
            "pago": 30,
            "valor": 20,
            "patrocinador": 0,
        },
    )
    salida = sal.en_riesgo(uow.db, uow.tenant_id)
    assert salida["cuentas"], "una cuenta así tiene que salir"
    assert "no" in salida["que_significa"].lower()


# ── Anomalías (CRM-05.02.01.05) ───────────────────────────────────────────


def _serie(uow: UnidadDeTrabajo, valores: list[float], clave: str = "oportunidades") -> None:
    inicio = date(2026, 1, 1)
    for i, valor in enumerate(valores):
        ano.observar(
            uow, ambito="pipeline", clave=clave, fecha=inicio + timedelta(days=i), valor=valor
        )


def test_sin_linea_base_no_se_avisa(uow: UnidadDeTrabajo) -> None:
    """Un pico sobre cuatro datos no es un hallazgo: es una serie nueva."""
    ano.vigilar(uow, ambito="pipeline", clave="nueva", minimo_observaciones=14)
    _serie(uow, [10, 11, 9, 200], clave="nueva")
    salida = ano.observar(uow, ambito="pipeline", clave="nueva", fecha=date(2026, 1, 10), valor=500)
    assert salida["medible"] is False
    assert salida["faltan"] > 0


def test_una_anomalia_lleva_su_normalidad_al_lado(uow: UnidadDeTrabajo) -> None:
    """«17» no dice nada; «17 cuando lo habitual son 40±6» se entiende sin saber
    estadística."""
    _serie(uow, [40, 42, 38, 41, 39, 40, 43, 37, 41, 40, 39, 42, 40, 41, 38])
    salida = ano.observar(
        uow, ambito="pipeline", clave="oportunidades", fecha=date(2026, 3, 1), valor=5
    )
    assert salida["anomalia"] is True
    assert salida["sentido"] == "baja"
    assert "habitual" in salida["porque"]


def test_tambien_se_avisa_de_las_anomalias_buenas(uow: UnidadDeTrabajo) -> None:
    """Un detector que solo mira hacia abajo deja pasar el mes en que alguien cargó
    el pipeline por duplicado."""
    _serie(uow, [40, 42, 38, 41, 39, 40, 43, 37, 41, 40, 39, 42, 40, 41, 38])
    salida = ano.observar(
        uow, ambito="pipeline", clave="oportunidades", fecha=date(2026, 3, 1), valor=300
    )
    assert salida["anomalia"] is True
    assert salida["sentido"] == "sube"


def test_la_anomalia_no_se_inventa_la_causa(uow: UnidadDeTrabajo) -> None:
    _serie(uow, [40, 42, 38, 41, 39, 40, 43, 37, 41, 40, 39, 42, 40, 41, 38])
    salida = ano.observar(
        uow, ambito="pipeline", clave="oportunidades", fecha=date(2026, 3, 1), valor=5
    )
    assert "no una causa" in salida["porque"] or "no es una causa" in salida["porque"]


def test_la_utilidad_del_detector_no_se_afirma_sin_revisiones(uow: UnidadDeTrabajo) -> None:
    """Tocar los umbrales a ciegas es cómo se acaba con un detector que no avisa de
    nada."""
    salida = ano.utilidad(uow.db, uow.tenant_id)
    assert salida["concluyente"] is False


def test_un_ambito_inventado_se_rechaza(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion):
        ano.vigilar(uow, ambito="loquesea", clave="x")


# ── Resumen de conversación (CRM-04.02.02.06) ─────────────────────────────


def test_el_resumen_se_pide_al_dueno_del_caso_y_no_se_escribe(uow: UnidadDeTrabajo) -> None:
    """El caso vive en el servicio de soporte. Que el comando salga no significa
    que el caso ya lo tenga, y decir «hecho» aquí sería mentir."""
    _proveedor(uow)
    salida = conv.resumir(
        uow,
        conversacion_id=uuid4(),
        caso_id=uuid4(),
        mensajes=[
            {"autor": "cliente", "texto": "Me han cobrado dos veces."},
            {"autor": "agente", "texto": "Lo revisamos."},
        ],
        principal=Principal(id=uuid4(), permisos=frozenset({"ia:usar"})),
    )
    assert salida["estado"] == "pedido"
    assert salida["pendientes"]


def test_un_resumen_parcial_se_marca_como_parcial(uow: UnidadDeTrabajo) -> None:
    """Un resumen de cuarenta mensajes hecho con cinco es un resumen del final, y
    quien lo lea sin saberlo creerá que tiene toda la conversación."""
    _proveedor(uow)
    salida = conv.resumir(
        uow,
        conversacion_id=uuid4(),
        mensajes=[{"autor": "cliente", "texto": "Hola"}],
        mensajes_totales=40,
        principal=Principal(id=uuid4(), permisos=frozenset({"ia:usar"})),
    )
    assert salida["parcial"] is True
    assert salida["aviso"]


def test_no_se_resume_una_conversacion_vacia(uow: UnidadDeTrabajo) -> None:
    _proveedor(uow)
    with pytest.raises(ErrorValidacion):
        conv.resumir(uow, conversacion_id=uuid4(), mensajes=[])


def test_sin_proveedor_disponible_no_hay_resumen_inventado(uow: UnidadDeTrabajo) -> None:
    """Preferimos una conversación sin resumen a un resumen inventado."""
    with pytest.raises(NoEncontrado):
        conv.resumir(
            uow,
            conversacion_id=uuid4(),
            mensajes=[{"autor": "cliente", "texto": "Hola"}],
        )


def test_sin_puerto_conectado_tampoco_se_resume(uow: UnidadDeTrabajo) -> None:
    """Un despliegue sin puerto de IA es un caso normal, no un error raro: tiene
    que notarse el hueco, no rellenarse."""
    _proveedor(uow)
    conv.registrar_resumidor(None)  # type: ignore[arg-type]
    with pytest.raises(ErrorDependencia):
        conv.resumir(
            uow,
            conversacion_id=uuid4(),
            mensajes=[{"autor": "cliente", "texto": "Hola"}],
        )


# ── Sentimiento e intención (CRM-04.02.02.07) ─────────────────────────────


def test_por_debajo_del_umbral_no_se_dice_neutro(
    uow: UnidadDeTrabajo, puertos_de_mentira: dict[str, Any]
) -> None:
    """Un neutro falso entra en las medias del día y las aplana: el panel dice que
    todo va bien porque el clasificador no se atrevía a decir nada."""
    _proveedor(uow)
    puertos_de_mentira["confianza"] = 0.3
    salida = conv.clasificar(uow, conversacion_id=uuid4(), texto="es la tercera vez que llamo")
    assert salida["concluyente"] is False
    assert salida["sentimiento"] is None


def test_la_senal_nunca_escala_sola(
    uow: UnidadDeTrabajo, puertos_de_mentira: dict[str, Any]
) -> None:
    """Avisa; escalar lo decide una persona con la regla del cliente."""
    _proveedor(uow)
    puertos_de_mentira.update({"confianza": 0.95, "sentimiento": "muy_negativo"})
    salida = conv.clasificar(uow, conversacion_id=uuid4(), texto="esto es inaceptable")
    assert salida["sugiere_escalar"] is True
    assert salida["escalado_automatico"] is False


def test_una_etiqueta_inventada_por_el_modelo_no_entra(
    uow: UnidadDeTrabajo, puertos_de_mentira: dict[str, Any]
) -> None:
    """La lista es cerrada precisamente para que los paneles cuadren: si el modelo
    devuelve «regulero», no aparece una categoría nueva en el informe."""
    _proveedor(uow)
    puertos_de_mentira["sentimiento"] = "regulero"
    salida = conv.clasificar(uow, conversacion_id=uuid4(), texto="pues bueno")
    assert salida["sentimiento"] == "neutro"


def test_las_no_concluyentes_no_entran_en_la_media_pero_se_cuentan(
    uow: UnidadDeTrabajo, puertos_de_mentira: dict[str, Any]
) -> None:
    """Si desaparecieran, una conversación que el clasificador no entiende
    parecería una conversación tranquila."""
    _proveedor(uow)
    conversacion_id = uuid4()
    puertos_de_mentira["confianza"] = 0.2
    conv.clasificar(uow, conversacion_id=conversacion_id, texto="mmm")
    puertos_de_mentira.update({"confianza": 0.9, "sentimiento": "negativo"})
    conv.clasificar(uow, conversacion_id=conversacion_id, texto="esto no puede ser")
    salida = conv.evolucion(uow.db, uow.tenant_id, conversacion_id)
    assert salida["no_concluyentes"] == 1
    assert salida["concluyentes"] == 1
    assert salida["medio"] == -1.0
