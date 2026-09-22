"""Analítica avanzada y resolución de identidad.

CRM-05.01.03.01 a .07 · CRM-05.01.04.09, .10 · CRM-01.01.05.02.

Las pruebas van detrás de los números que engañan:

  * la carga que se repite y duplica todas las filas,
  * la marca de agua que avanza aunque el envío fallara,
  * el panel que enseña datos de anoche como si fueran de ahora,
  * la métrica que cambia y hace que un número publicado cambie solo,
  * la cohorte de este mes al 0 % porque aún no ha terminado,
  * la oportunidad abierta contada como perdida en el embudo,
  * la correlación presentada como una instrucción,
  * y la unión de dos personas distintas, que enseña a una el historial de otra.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion

from services.analytics import almacen as alm
from services.analytics import cohortes as coh
from services.analytics import semantico as sem
from services.party import identidad as idt


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── Almacén analítico (CRM-05.01.03.01) ───────────────────────────────────


def _tabla(uow: UnidadDeTrabajo, **kw: Any) -> alm.TablaAnalitica:
    base: dict[str, Any] = {
        "clave": "oportunidades",
        "servicio": "sales",
        "columnas": [
            {"nombre": "importe", "tipo": "numero", "obligatoria": True},
            {"nombre": "etapa", "tipo": "texto"},
        ],
        "frecuencia_min": 60,
    }
    base.update(kw)
    return alm.declarar_tabla(uow, **base)


def test_una_tabla_sin_columnas_declaradas_no_se_crea(uow: UnidadDeTrabajo) -> None:
    """Un almacén que acepta cualquier forma acaba siendo un montón de JSON que
    nadie sabe consultar, y entonces se consulta el operacional otra vez."""
    with pytest.raises(ErrorValidacion):
        alm.declarar_tabla(uow, clave="x", columnas=[])


def test_cargar_dos_veces_no_duplica(uow: UnidadDeTrabajo) -> None:
    """Sin clave de origen, repetir una carga duplica las filas y todos los
    recuentos salen al doble."""
    _tabla(uow)
    filas = [{"clave_origen": "OP-1", "importe": 100, "etapa": "cierre"}]
    alm.cargar(uow, tabla="oportunidades", filas=filas)
    segunda = alm.cargar(uow, tabla="oportunidades", filas=filas)
    assert segunda["filas_totales"] == 1


def test_una_fila_sin_clave_de_origen_se_descarta_y_se_cuenta(
    uow: UnidadDeTrabajo,
) -> None:
    _tabla(uow)
    salida = alm.cargar(uow, tabla="oportunidades", filas=[{"importe": 100}])
    assert salida["aplicadas"] == 0
    assert "idempotente" in salida["descartadas"][0]["porque"]
    assert salida["completa"] is False


def test_una_fila_sin_campo_obligatorio_no_entra_a_medias(
    uow: UnidadDeTrabajo,
) -> None:
    """Una fila con la mitad de los campos produce un informe que suma mal sin
    que nadie sepa por qué."""
    _tabla(uow)
    salida = alm.cargar(
        uow, tabla="oportunidades", filas=[{"clave_origen": "OP-2", "etapa": "cierre"}]
    )
    assert salida["aplicadas"] == 0
    assert "importe" in salida["descartadas"][0]["porque"]


def test_la_marca_de_agua_avanza_con_lo_aplicado(uow: UnidadDeTrabajo) -> None:
    _tabla(uow)
    ayer = datetime.now(timezone.utc) - timedelta(days=1)
    salida = alm.cargar(
        uow,
        tabla="oportunidades",
        filas=[
            {"clave_origen": "OP-1", "importe": 1, "ocurrido_at": ayer.isoformat()},
        ],
    )
    assert salida["marca_agua"] is not None


def test_la_frescura_marca_lo_obsoleto(uow: UnidadDeTrabajo) -> None:
    """Un panel que enseña datos de anoche como de ahora hace que alguien llame a
    un cliente con una cifra que ya no existe."""
    ficha = _tabla(uow, frecuencia_min=60)
    alm.cargar(uow, tabla="oportunidades", filas=[{"clave_origen": "OP-1", "importe": 1}])
    ficha.ultima_carga_at = datetime.now(timezone.utc) - timedelta(hours=5)
    uow.db.flush()
    salida = alm.frescura(uow.db, uow.tenant_id)
    assert salida["obsoletas"] == ["oportunidades"]
    assert salida["fiable"] is False


def test_una_tabla_nunca_cargada_no_pasa_por_fresca(uow: UnidadDeTrabajo) -> None:
    _tabla(uow)
    salida = alm.frescura(uow.db, uow.tenant_id)
    assert salida["tablas"][0]["nunca_cargada"] is True
    assert salida["tablas"][0]["obsoleta"] is True


def test_leer_dice_de_cuando_son_los_datos(uow: UnidadDeTrabajo) -> None:
    _tabla(uow)
    alm.cargar(uow, tabla="oportunidades", filas=[{"clave_origen": "OP-1", "importe": 7}])
    salida = alm.leer(uow.db, uow.tenant_id, tabla="oportunidades")
    assert salida["filas"] == [{"importe": 7}]
    assert salida["datos_de"] is not None


# ── Exportación continua (CRM-05.01.03.02) ────────────────────────────────


def test_un_destino_sin_tablas_no_se_declara(uow: UnidadDeTrabajo) -> None:
    """Exportar «todo» por defecto saca datos personales a un sitio que quizá no
    está preparado para tenerlos."""
    with pytest.raises(ErrorValidacion):
        alm.declarar_destino(uow, clave="dw", tipo="snowflake", tablas=[])


def test_un_destino_con_una_tabla_inexistente_se_rechaza(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion):
        alm.declarar_destino(uow, clave="dw", tipo="snowflake", tablas=["no_existe"])


def test_preparar_envio_no_avanza_la_marca(uow: UnidadDeTrabajo) -> None:
    """Avanzarla antes de confirmar es cómo se pierde un día entero de cambios."""
    _tabla(uow)
    alm.cargar(uow, tabla="oportunidades", filas=[{"clave_origen": "OP-1", "importe": 1}])
    alm.declarar_destino(uow, clave="dw", tipo="snowflake", tablas=["oportunidades"])

    primera = alm.preparar_envio(uow.db, uow.tenant_id, destino="dw")
    assert primera["total"] == 1
    # Sin confirmar, lo mismo sigue pendiente.
    segunda = alm.preparar_envio(uow.db, uow.tenant_id, destino="dw")
    assert segunda["total"] == 1

    marca = primera["lotes"][0]["hasta_propuesto"]
    alm.confirmar_envio(uow, destino="dw", marcas={"oportunidades": marca})
    tercera = alm.preparar_envio(uow.db, uow.tenant_id, destino="dw")
    assert tercera["total"] == 0


def test_un_envio_con_error_no_avanza_nada(uow: UnidadDeTrabajo) -> None:
    """Un destino que avanza la marca tras un fallo se salta ese tramo para
    siempre."""
    _tabla(uow)
    alm.cargar(uow, tabla="oportunidades", filas=[{"clave_origen": "OP-1", "importe": 1}])
    alm.declarar_destino(uow, clave="dw", tipo="snowflake", tablas=["oportunidades"])
    alm.confirmar_envio(uow, destino="dw", marcas={}, error="El almacén rechazó el lote")
    salida = alm.preparar_envio(uow.db, uow.tenant_id, destino="dw")
    assert salida["total"] == 1
    estado = alm.retraso_exportacion(uow.db, uow.tenant_id)
    assert estado["con_error"] == 1


def test_el_lote_lleno_dice_que_hay_mas(uow: UnidadDeTrabajo) -> None:
    """Quien envía tiene que volver a llamar; si no lo sabe, deja la mitad sin
    mandar creyendo que terminó."""
    _tabla(uow)
    alm.cargar(
        uow,
        tabla="oportunidades",
        filas=[{"clave_origen": f"OP-{i}", "importe": i} for i in range(5)],
    )
    alm.declarar_destino(uow, clave="dw", tipo="s3", tablas=["oportunidades"])
    salida = alm.preparar_envio(uow.db, uow.tenant_id, destino="dw", tope=2)
    assert salida["hay_mas"] is True


# ── Consulta federada (CRM-05.01.03.07) ───────────────────────────────────


def test_una_fuente_federada_sin_objetos_no_se_declara(uow: UnidadDeTrabajo) -> None:
    """Sin lista, una consulta federada puede leer el lake entero con nuestra
    credencial."""
    with pytest.raises(ErrorValidacion):
        alm.declarar_fuente_federada(uow, clave="lake", tipo="databricks", objetos=[])


def test_no_se_consulta_un_objeto_no_declarado(uow: UnidadDeTrabajo) -> None:
    alm.declarar_fuente_federada(
        uow, clave="lake", tipo="databricks", objetos=["ventas_historicas"]
    )
    with pytest.raises(ErrorValidacion):
        alm.plan_federado(uow.db, uow.tenant_id, fuente="lake", objeto="nominas")


def test_el_plan_federado_dice_que_no_se_cruza_con_el_crm(
    uow: UnidadDeTrabajo,
) -> None:
    """Dejar que alguien lo descubra con una consulta que no termina es peor que
    decirlo."""
    alm.declarar_fuente_federada(
        uow, clave="lake", tipo="databricks", objetos=["ventas"], tope_filas=1000
    )
    plan = alm.plan_federado(uow.db, uow.tenant_id, fuente="lake", objeto="ventas", limite=5000)
    assert plan["cruzable_con_el_crm"] is False
    assert plan["limite"] == 1000
    assert plan["recortado"] is True


# ── Modelo semántico (CRM-05.01.03.03) ────────────────────────────────────


def _metrica(uow: UnidadDeTrabajo, **kw: Any) -> sem.Metrica:
    base: dict[str, Any] = {
        "clave": "ingresos",
        "nombre": "Ingresos firmados",
        "objeto": "oportunidad",
        "definicion": "Importe de las oportunidades ganadas, por fecha de firma",
        "agregacion": "suma",
        "campo": "importe",
        "dimensiones": ["mes", "equipo"],
        "dueno_id": uuid4(),
    }
    base.update(kw)
    fila, _ = sem.definir(uow, **base)
    return fila


def test_la_metrica_nace_en_borrador(uow: UnidadDeTrabajo) -> None:
    """Una métrica que nace certificada no la ha revisado nadie."""
    assert _metrica(uow).estado == "borrador"


def test_certificar_exige_dueno_y_definicion(uow: UnidadDeTrabajo) -> None:
    _metrica(uow, clave="sin_dueno", dueno_id=None, definicion="algo")
    with pytest.raises(ErrorValidacion):
        sem.certificar(uow, clave="sin_dueno")
    _metrica(uow, clave="sin_definicion", definicion="")
    with pytest.raises(ErrorValidacion):
        sem.certificar(uow, clave="sin_definicion")


def test_no_se_reescribe_una_metrica_vigente(uow: UnidadDeTrabajo) -> None:
    """Un número publicado que cambia solo hace que se desconfíe de todos."""
    _metrica(uow)
    with pytest.raises(Conflicto):
        _metrica(uow)


def test_la_version_nueva_exige_motivo_y_nace_sin_certificar(
    uow: UnidadDeTrabajo,
) -> None:
    _metrica(uow)
    sem.certificar(uow, clave="ingresos")
    with pytest.raises(ErrorValidacion):
        sem.nueva_version(uow, clave="ingresos", motivo="")
    nueva = sem.nueva_version(
        uow, clave="ingresos", motivo="Ahora cuenta por fecha de cobro", campo="cobrado"
    )
    assert nueva.version == 2
    assert nueva.estado == "borrador"


def test_se_puede_pedir_el_plan_de_una_version_anterior(uow: UnidadDeTrabajo) -> None:
    """Es lo que permite reproducir un informe de hace tres meses con la
    definición de entonces."""
    _metrica(uow)
    sem.nueva_version(uow, clave="ingresos", motivo="Cambio de criterio", campo="cobrado")
    v1 = sem.plan_de(uow.db, uow.tenant_id, clave="ingresos", version=1)
    v2 = sem.plan_de(uow.db, uow.tenant_id, clave="ingresos")
    assert v1["campo"] == "importe" and v2["campo"] == "cobrado"


def test_agrupar_por_una_dimension_no_declarada_se_rechaza(
    uow: UnidadDeTrabajo,
) -> None:
    """Agrupar por algo que no forma parte de la definición da un número que no
    es esa métrica."""
    _metrica(uow)
    with pytest.raises(ErrorValidacion):
        sem.plan_de(uow.db, uow.tenant_id, clave="ingresos", dimensiones=["pais"])


def test_el_plan_de_una_metrica_sin_certificar_lo_dice(uow: UnidadDeTrabajo) -> None:
    _metrica(uow)
    plan = sem.plan_de(uow.db, uow.tenant_id, clave="ingresos")
    assert plan["certificada"] is False and plan["aviso"]


def test_un_ratio_necesita_numerador_y_denominador(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion):
        sem.definir(uow, clave="conversion", nombre="Conversión", objeto="lead", agregacion="ratio")


def test_el_catalogo_lista_las_que_no_tienen_dueno(uow: UnidadDeTrabajo) -> None:
    """Es la lista con la que se empieza a ordenar esto."""
    _metrica(uow, clave="huerfana", dueno_id=None)
    salida = sem.catalogo(uow.db, uow.tenant_id)
    assert "huerfana" in salida["sin_dueno"]


# ── Cohortes (CRM-05.01.03.04) ────────────────────────────────────────────


def test_el_periodo_que_no_ha_terminado_sale_inmaduro() -> None:
    """Marcarlo al 0 % pinta como un desastre lo que aún no ha tenido tiempo."""
    hoy = date(2026, 3, 10)
    sujetos = [{"id": i, "alta": "2026-03-01", "actividad": ["2026-03-02"]} for i in range(10)]
    salida = coh.cohortes(sujetos=sujetos, periodo="mes", periodos=3, hoy=hoy)
    celdas = salida["cohortes"][0]["celdas"]
    assert celdas[0]["inmaduro"] is True
    assert celdas[0]["pct"] is None


def test_una_cohorte_pequena_no_da_porcentaje() -> None:
    """Con tres clientes, uno que se va es un −33 % que se lee como un desplome."""
    hoy = date(2026, 6, 1)
    sujetos = [{"id": i, "alta": "2026-01-01", "actividad": ["2026-02-01"]} for i in range(3)]
    salida = coh.cohortes(sujetos=sujetos, periodo="mes", periodos=3, hoy=hoy)
    assert salida["cohortes"][0]["significativa"] is False
    assert all(c["pct"] is None for c in salida["cohortes"][0]["celdas"])


def test_la_retencion_se_calcula_sobre_la_propia_cohorte() -> None:
    hoy = date(2026, 6, 1)
    sujetos = [
        {"id": i, "alta": "2026-01-01", "actividad": ["2026-01-05", "2026-02-05"]}
        for i in range(10)
    ]
    sujetos += [
        {"id": 90 + i, "alta": "2026-01-01", "actividad": ["2026-01-05"]} for i in range(10)
    ]
    salida = coh.cohortes(sujetos=sujetos, periodo="mes", periodos=3, hoy=hoy)
    celdas = salida["cohortes"][0]["celdas"]
    assert celdas[0]["pct"] == 100.0
    assert celdas[1]["pct"] == 50.0


def test_los_sujetos_sin_fecha_de_alta_se_cuentan_aparte() -> None:
    """Meterlos en la primera cohorte sería inventarse su origen."""
    salida = coh.cohortes(
        sujetos=[{"id": 1, "actividad": []}, {"id": 2, "alta": "2026-01-01"}],
        hoy=date(2026, 6, 1),
    )
    assert salida["sin_fecha_de_alta"] == 1
    assert salida["concluyente"] is False


# ── Embudo (CRM-05.01.03.05) ──────────────────────────────────────────────


def test_lo_abierto_no_cuenta_como_perdido() -> None:
    """Contarlo como caído hunde la tasa de las etapas finales y hace parecer que
    el equipo cierra peor de lo que cierra."""
    recorridos = [
        {
            "id": 1,
            "abierto": True,
            "pasos": [
                {"etapa": "alta", "fecha": "2026-01-01"},
                {"etapa": "demo", "fecha": "2026-01-05"},
            ],
        },
        {
            "id": 2,
            "abierto": False,
            "pasos": [
                {"etapa": "alta", "fecha": "2026-01-01"},
                {"etapa": "demo", "fecha": "2026-01-03"},
                {"etapa": "cierre", "fecha": "2026-01-10"},
            ],
        },
    ]
    salida = coh.embudo(etapas=["alta", "demo", "cierre"], recorridos=recorridos)
    cierre = salida["etapas"][2]
    assert cierre["llegaron"] == 1
    # El que sigue abierto en «demo» no cuenta como caído en «cierre».
    assert cierre["caidos"] == 0
    assert salida["abiertos"] == 1


def test_el_tiempo_entre_etapas_es_la_mediana() -> None:
    """Un solo negocio de dos años mueve la media de todo el trimestre."""
    recorridos = []
    for i, dias in enumerate([2, 3, 4, 400]):
        recorridos.append(
            {
                "id": i,
                "abierto": False,
                "pasos": [
                    {"etapa": "alta", "fecha": "2026-01-01"},
                    {
                        "etapa": "demo",
                        "fecha": str(date(2026, 1, 1) + timedelta(days=dias)),
                    },
                ],
            }
        )
    salida = coh.embudo(etapas=["alta", "demo"], recorridos=recorridos)
    assert salida["etapas"][0]["dias_mediana"] in (3, 4)


def test_el_embudo_senala_la_mayor_caida() -> None:
    """La pregunta que sigue a «¿cómo va el embudo?» es siempre «¿dónde se
    atasca?»."""
    recorridos = [
        {"id": i, "abierto": False, "pasos": [{"etapa": "alta", "fecha": "2026-01-01"}]}
        for i in range(8)
    ]
    recorridos.append(
        {
            "id": 99,
            "abierto": False,
            "pasos": [
                {"etapa": "alta", "fecha": "2026-01-01"},
                {"etapa": "demo", "fecha": "2026-01-02"},
                {"etapa": "cierre", "fecha": "2026-01-03"},
            ],
        }
    )
    salida = coh.embudo(etapas=["alta", "demo", "cierre"], recorridos=recorridos)
    assert salida["mayor_caida"]["etapa"] == "demo"


def test_sin_recorridos_no_hay_embudo_y_se_dice() -> None:
    salida = coh.embudo(etapas=["alta", "demo"], recorridos=[])
    assert salida["medible"] is False and salida["aviso"]


# ── Actividad y resultados (CRM-05.01.03.06) ──────────────────────────────


def test_con_pocos_sujetos_no_se_calcula_la_correlacion() -> None:
    """Con cinco comerciales, un valor atípico da 0,9 o −0,3 según quién esté de
    vacaciones."""
    sujetos = [{"id": i, "actividades": i, "cerrado": i * 2} for i in range(4)]
    salida = coh.correlacion_actividad(sujetos=sujetos)
    assert salida["medible"] is False


def test_sin_variacion_no_hay_correlacion() -> None:
    """Devolver cero se leería como «no influye», que es otra cosa."""
    sujetos = [{"id": i, "actividades": 10, "cerrado": i} for i in range(10)]
    salida = coh.correlacion_actividad(sujetos=sujetos)
    assert salida["medible"] is False
    assert "variación" in salida["porque"]


def test_la_correlacion_viene_con_el_aviso_de_que_no_es_causa() -> None:
    """Quien lea el panel no va a leer la documentación."""
    sujetos = [{"id": i, "actividades": i * 10, "cerrado": i * 1000} for i in range(1, 11)]
    salida = coh.correlacion_actividad(sujetos=sujetos)
    assert salida["medible"] is True
    assert salida["coeficiente"] > 0.9
    assert "no es causa" in salida["aviso"]


def test_los_atipicos_son_la_parte_accionable() -> None:
    """El que hace mucho y cierra poco necesita ayuda con la cualificación, no
    con el teléfono."""
    sujetos = [{"id": i, "actividades": i * 10, "cerrado": i * 1000} for i in range(1, 11)]
    sujetos.append({"id": 99, "actividades": 100, "cerrado": 100})
    salida = coh.correlacion_actividad(sujetos=sujetos)
    assert any(a["id"] == "99" and a["por_encima"] is False for a in salida["atipicos"])


# ── Resolución de identidad (CRM-01.01.05.02) ─────────────────────────────


def test_la_normalizacion_cruza_el_mismo_correo_escrito_distinto() -> None:
    """Sin normalizar, el cruce no encuentra nada y parece que no hay duplicados."""
    uno, _ = idt.normalizar("email", " Ana@Empresa.com ")
    dos, _ = idt.normalizar("email", "ana@empresa.com")
    assert uno == dos


def test_el_telefono_cruza_con_y_sin_prefijo() -> None:
    uno, _ = idt.normalizar("telefono", "+34 600 11 22 33")
    dos, _ = idt.normalizar("telefono", "600112233")
    assert uno == dos


def test_la_senal_se_guarda_con_huella_y_pista(uow: UnidadDeTrabajo) -> None:
    """Una tabla de identidades es un índice de todos los correos del CRM."""
    fila = idt.observar(uow, tipo="email", valor="ana@empresa.com", contacto_id=uuid4())
    assert "ana@empresa.com" not in fila.huella
    assert fila.pista.endswith("@empresa.com")


def test_resolver_devuelve_el_porque_y_no_solo_un_id(uow: UnidadDeTrabajo) -> None:
    contacto = uuid4()
    idt.observar(uow, tipo="email", valor="ana@empresa.com", contacto_id=contacto)
    salida = idt.resolver(
        uow.db, uow.tenant_id, senales=[{"tipo": "email", "valor": "ana@empresa.com"}]
    )
    assert salida["resuelto"] is True
    assert salida["contacto_id"] == str(contacto)
    assert salida["candidatos"][0]["senales"][0]["tipo"] == "email"


def test_una_senal_debil_no_resuelve_sola(uow: UnidadDeTrabajo) -> None:
    """Decir «es este» con un teléfono de centralita compartida es cómo se
    mezclan dos clientes."""
    idt.observar(uow, tipo="telefono", valor="600112233", contacto_id=uuid4())
    salida = idt.resolver(
        uow.db, uow.tenant_id, senales=[{"tipo": "telefono", "valor": "600112233"}]
    )
    assert salida["resuelto"] is False
    assert "se propone" in salida["porque"]


def test_una_senal_compartida_pesa_menos(uow: UnidadDeTrabajo) -> None:
    """Un teléfono que comparten cinco personas no identifica a ninguna."""
    for _ in range(3):
        idt.observar(uow, tipo="telefono", valor="911223344", contacto_id=uuid4())
    salida = idt.resolver(
        uow.db, uow.tenant_id, senales=[{"tipo": "telefono", "valor": "911223344"}]
    )
    assert salida["resuelto"] is False
    assert salida["candidatos"][0]["senales"][0]["compartida"] is True


def test_dos_candidatos_empatados_no_resuelven(uow: UnidadDeTrabajo) -> None:
    """Elegir uno sería jugársela a cara o cruz con el historial de un cliente."""
    uno, dos = uuid4(), uuid4()
    idt.observar(uow, tipo="nif", valor="B12345678", contacto_id=uno)
    idt.observar(uow, tipo="nif", valor="B12345678", contacto_id=dos)
    salida = idt.resolver(uow.db, uow.tenant_id, senales=[{"tipo": "nif", "valor": "B12345678"}])
    assert salida["ambiguo"] is True and salida["resuelto"] is False


def test_el_nombre_no_une_a_nadie(uow: UnidadDeTrabajo) -> None:
    """«García» hay miles."""
    idt.observar(uow, tipo="nombre", valor="Ana García", contacto_id=uuid4())
    salida = idt.resolver(
        uow.db, uow.tenant_id, senales=[{"tipo": "nombre", "valor": "Ana García"}]
    )
    assert salida["resuelto"] is False


def test_proponer_uniones_no_une_nada(uow: UnidadDeTrabajo) -> None:
    """Unir automáticamente dos personas distintas enseña a una el historial de
    la otra, y eso no se deshace aunque se deshaga la unión."""
    uno, dos = uuid4(), uuid4()
    idt.observar(uow, tipo="email", valor="ana@empresa.com", contacto_id=uno)
    idt.observar(uow, tipo="email", valor="ana@empresa.com", contacto_id=dos)
    salida = idt.proponer_uniones(uow.db, uow.tenant_id)
    assert salida["cuantas"] == 1
    assert (
        uow.db.execute(idt.select(idt.Union).where(idt.Union.tenant_id == uow.tenant_id))
        .scalars()
        .all()
        == []
    )


def test_una_union_automatica_pide_mucha_mas_puntuacion(uow: UnidadDeTrabajo) -> None:
    """Quien une a mano está mirando las dos fichas; un proceso nocturno no mira
    nada."""
    uno, dos = uuid4(), uuid4()
    with pytest.raises(Conflicto):
        idt.unir(uow, principal_id=uno, secundario_id=dos, puntuacion=90, modo="automatica")
    idt.unir(uow, principal_id=uno, secundario_id=dos, puntuacion=90, modo="manual")


def test_deshacer_una_union_exige_motivo(uow: UnidadDeTrabajo) -> None:
    """Si la regla vuelve a proponerla, el motivo es lo único que explica por qué
    estaba mal."""
    uno, dos = uuid4(), uuid4()
    idt.unir(uow, principal_id=uno, secundario_id=dos, puntuacion=100)
    with pytest.raises(ErrorValidacion):
        idt.deshacer(uow, principal_id=uno, secundario_id=dos, motivo="")
    fila = idt.deshacer(
        uow, principal_id=uno, secundario_id=dos, motivo="Son padre e hijo, mismo correo"
    )
    assert fila.deshecha_at is not None


def test_un_contacto_con_una_sola_senal_no_es_cruzable(uow: UnidadDeTrabajo) -> None:
    """Es el que va a seguir apareciendo sin atribuir."""
    contacto = uuid4()
    idt.observar(uow, tipo="email", valor="solo@empresa.com", contacto_id=contacto)
    salida = idt.identidades_de(uow.db, uow.tenant_id, contacto)
    assert salida["cruzable"] is False
    # Y lo que se enseña son pistas, no valores.
    assert all("solo@empresa.com" != s["pista"] for s in salida["senales"])
