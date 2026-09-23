"""Recuperación, catálogo de servicios, malla, alta disponibilidad, despliegue,
presión, particionado, escalado y entornos de pruebas
(CRM-00.06.02.02, .05, .06, .08 · CRM-00.03.01.04, .05 · CRM-08.01.01.02, .04,
.06 · CRM-07.02.01.02).

Lo que persiguen estas pruebas es lo que se descubre en el peor momento: la copia
que nadie ha restaurado, el plan multi-zona que nadie ha probado, el mecanismo de
degradación que existe y no se activa nunca, y la copia de producción en un
entorno de pruebas del que ya nadie se acuerda.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from crmcore.datos import particionado as part
from crmcore.datos import recuperacion as rec
from crmcore.errors import Conflicto, ErrorValidacion, Prohibido
from crmcore.obs import escalado as esc
from crmcore.obs import presion as pre
from crmcore.obs import topologia as top

from services.tenancy import sandboxes as sbx

AHORA = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
HOY = date(2026, 9, 23)


# ── Recuperación a un punto en el tiempo (CRM-00.06.02.02) ────────────────


def test_no_se_restaura_a_un_momento_del_que_no_hay_copia() -> None:
    """Se dice ahora y no al final del proceso, que es cuando se descubre en la
    mayoría de los sistemas."""
    with pytest.raises(Conflicto) as fallo:
        rec.plan_de_restauracion(
            tenant_id=__import__("uuid").uuid4(),
            momento=AHORA - timedelta(days=200),
            alcance="datos",
            copia_mas_antigua=AHORA - timedelta(days=30),
            ahora=AHORA,
        )
    assert fallo.value.error_code == "recuperacion.fuera_de_retencion"


def test_la_restauracion_va_sobre_una_copia() -> None:
    """Restaurar encima de lo vivo convierte un error en dos."""
    salida = rec.plan_de_restauracion(
        tenant_id=__import__("uuid").uuid4(),
        momento=AHORA - timedelta(hours=3),
        alcance="datos",
        copia_mas_antigua=AHORA - timedelta(days=30),
        ahora=AHORA,
    )
    assert salida["sobre_una_copia"] is True
    assert any(x["que"] == "auditoria" for x in salida["no_se_restaura"])


def test_se_dice_que_salio_fuera_en_el_tramo_que_se_deshace() -> None:
    """Restaurar las tablas a las 10:00 no desmanda el correo de las 10:15."""
    salida = rec.efectos_irreversibles(
        salidas=[
            {"tipo": "correo", "referencia": "m1", "cuando": AHORA - timedelta(hours=2)},
            {"tipo": "webhook", "referencia": "w1", "cuando": AHORA - timedelta(hours=1)},
            {"tipo": "correo", "referencia": "m2", "cuando": AHORA - timedelta(days=5)},
        ],
        desde=AHORA - timedelta(hours=3),
        hasta=AHORA,
    )
    assert salida["total"] == 2
    assert "no se pueden" in salida["que_significa"]


def test_una_prueba_con_diferencias_no_pasa() -> None:
    """Una copia que restaura el 99 % es una copia que pierde datos."""
    salida = rec.registrar_prueba(
        tenant_id=None,
        inicio=AHORA - timedelta(minutes=10),
        fin=AHORA,
        filas_comprobadas=1000,
        diferencias=["faltan 3 actividades"],
        rto_comprometido_min=60,
    )
    assert salida["paso"] is False


def test_sin_pruebas_no_se_dice_que_las_copias_esten_bien() -> None:
    """Una copia sin restaurar nunca es un fichero grande."""
    salida = rec.estado_de_las_pruebas(pruebas=[], ahora=AHORA)
    assert salida["al_dia"] is False
    assert "fichero grande" in salida["porque"]


def test_sin_copias_el_dato_que_se_perderia_no_es_cero() -> None:
    salida = rec.rpo_real(ultima_copia=None, rpo_comprometido_min=15, ahora=AHORA)
    assert salida["medible"] is False


def test_se_avisa_de_que_se_esta_incumpliendo_el_rpo_ahora_mismo() -> None:
    salida = rec.rpo_real(
        ultima_copia=AHORA - timedelta(hours=5), rpo_comprometido_min=15, ahora=AHORA
    )
    assert salida["dentro"] is False
    assert "ahora mismo" in salida["aviso"]


# ── Catálogo de servicios y malla (CRM-00.03.01.04, .05) ──────────────────


def test_un_servicio_sin_dueno_no_pasa_el_catalogo() -> None:
    """Es uno que en una guardia nadie sabe de quién es."""
    salida = top.validar_catalogo(
        servicios={
            "party": {"slo": "99.9", "depende_de": [], "runbook": "x", "criticidad": "critico"}
        }
    )
    assert salida["valido"] is False
    assert any(p["falta"] == "dueno" for p in salida["problemas"])


def test_las_dependencias_circulares_se_cazan() -> None:
    """Producen un arranque que nunca termina y una guardia en la que todos
    esperan al otro."""
    completo = {"dueno": "a", "slo": "x", "runbook": "r", "criticidad": "critico"}
    salida = top.validar_catalogo(
        servicios={
            "a": {**completo, "depende_de": ["b"]},
            "b": {**completo, "depende_de": ["a"]},
        }
    )
    assert salida["dependencias_circulares"]


def test_un_post_sin_idempotencia_no_se_reintenta() -> None:
    """Crearía dos pedidos, y el cliente lo vería antes que nosotros."""
    salida = top.politica_de_reintento(metodo="POST", idempotente=False)
    assert salida["reintentar"] is False


def test_un_post_con_clave_de_idempotencia_si() -> None:
    salida = top.politica_de_reintento(metodo="POST", idempotente=True)
    assert salida["reintentar"] is True


# ── Alta disponibilidad y despliegue (CRM-00.06.02.05, .08) ───────────────


def test_dos_zonas_al_sesenta_por_ciento_no_sobreviven_a_perder_una() -> None:
    """Se sabe sumando, no esperando."""
    salida = top.plan_multi_zona(
        zonas=[
            {"activa": True, "capacidad_pct": 60, "carga_pct": 50},
            {"activa": True, "capacidad_pct": 60, "carga_pct": 50},
        ],
        ultimo_simulacro=AHORA - timedelta(days=30),
        ahora=AHORA,
    )
    assert salida["aguanta_perder_una"] is False


def test_un_plan_sin_simulacro_es_una_suposicion() -> None:
    """Nadie sabe cuánto tarda una promoción hasta que la ha hecho con el reloj
    delante."""
    salida = top.plan_multi_zona(
        zonas=[
            {"activa": True, "capacidad_pct": 100},
            {"activa": True, "capacidad_pct": 100},
        ],
        ultimo_simulacro=None,
        ahora=AHORA,
    )
    assert salida["plan_probado"] is False


def test_un_canario_que_no_se_revierte_no_es_un_canario() -> None:
    """Es un despliegue con público: cuando algo va mal se espera a ver si se
    arregla."""
    salida = top.comprobar_despliegue(
        estrategia="canary",
        puede_volver_atras_en_min=30,
        migracion_compatible_hacia_atras=True,
        porcentaje_canario=5,
    )
    assert salida["sin_corte"] is False


def test_una_migracion_incompatible_rompe_el_despliegue_sin_corte() -> None:
    """Durante el despliegue hay dos versiones contra la misma base y una falla."""
    salida = top.comprobar_despliegue(
        estrategia="rolling",
        puede_volver_atras_en_min=2,
        migracion_compatible_hacia_atras=False,
    )
    assert salida["sin_corte"] is False


def test_los_umbrales_para_abortar_se_deciden_antes() -> None:
    """En caliente siempre parece que «todavía no es para tanto»."""
    salida = top.senales_para_abortar(
        metricas={"error_pct": 6.0, "p95_ms": 900},
        base={"error_pct": 0.5, "p95_ms": 400},
    )
    assert salida["abortar"] is True
    assert salida["decidido_de_antemano"] is True


# ── Presión y degradación (CRM-08.01.01.06) ───────────────────────────────


def test_manda_la_peor_senal_y_no_la_media() -> None:
    """Promediar suaviza justo la señal que está dando el problema."""
    salida = pre.calcular(
        p95_ms=100,
        objetivo_ms=500,
        pool_en_uso=98,
        pool_tamano=100,
        cola_pendientes=0,
        workers=4,
    )
    assert salida["manda"] == "pool"
    assert salida["presion"] > 0.8


def test_lo_que_no_se_puede_medir_no_cuenta_como_cero() -> None:
    """Un proceso que solo mide latencia y da presión baja mientras su cola crece
    está tranquilizando sobre algo que no ha mirado."""
    salida = pre.calcular(p95_ms=100, objetivo_ms=500)
    assert "cola" in salida["sin_medir"]
    assert "no cuenta como cero" in salida["porque"]


def test_sin_ninguna_senal_la_presion_se_queda_como_estaba() -> None:
    """Ponerla a cero sería decir que todo va bien sin haber mirado."""
    salida = pre.calcular(presion_anterior=0.8)
    assert salida["medible"] is False
    assert salida["presion"] == 0.8


def test_la_presion_sube_de_golpe_y_baja_despacio() -> None:
    """Si bajara igual de rápido el sistema oscilaría, y media petición fallando
    sin patrón es peor que una degradación estable."""
    salida = pre.calcular(p95_ms=100, objetivo_ms=500, presion_anterior=0.9)
    assert salida["presion"] == pytest.approx(0.75, abs=0.001)


def test_la_presion_llega_de_verdad_al_mecanismo_de_degradacion() -> None:
    """Era el hueco: el mecanismo existía y nadie le decía nunca que el sistema
    estaba saturado, así que no se activó jamás."""
    from crmcore import resiliencia

    try:
        pre.aplicar({"presion": 0.95})
        assert resiliencia.presion() == pytest.approx(0.95)
        assert resiliencia.admite(resiliencia.DIFERIBLE) is False
        assert resiliencia.admite(resiliencia.CRITICA) is True
    finally:
        resiliencia.fijar_presion(0.0)


def test_se_puede_explicar_que_se_esta_aplazando() -> None:
    salida = pre.que_se_esta_aplazando(0.7)
    assert salida["diferible"] is False
    assert salida["normal"] is True


# ── Particionado y archivado (CRM-08.01.01.04) ────────────────────────────


def test_no_se_particiona_lo_que_no_crece() -> None:
    """Trocear una tabla de cincuenta mil filas la hace más lenta."""
    with pytest.raises(ErrorValidacion) as fallo:
        part.plan_de_particion(tabla="paises", estrategia="mes")
    assert fallo.value.error_code == "particion.tabla_no_procede"


def test_no_se_particiona_por_tenant() -> None:
    """Con dos mil tenants el planificador tarda más en decidir que en ejecutar."""
    with pytest.raises(ErrorValidacion) as fallo:
        part.plan_de_particion(tabla="actividades", estrategia="tenant")
    assert "por_que_no_por_tenant" in fallo.value.detalle


def test_las_particiones_se_crean_por_delante() -> None:
    """Crearla cuando llega la primera fila del mes es crearla a las 00:00 del
    día 1, dentro de la transacción de un usuario."""
    salida = part.particiones_a_crear(ultima_existente=HOY, hoy=HOY)
    assert salida["faltan"]


def test_lo_retenido_no_se_archiva() -> None:
    """Moverlo a frío es cumplir el plazo de retención por accidente y romper otra
    obligación a la vez."""
    salida = part.se_puede_archivar(
        fila={"fecha": (HOY - timedelta(days=1000)).isoformat(), "litigio": True}, hoy=HOY
    )
    assert salida["puede"] is False
    assert salida["impedimentos"][0]["motivo"] == "litigio"


def test_archivar_no_borra_nada() -> None:
    """Confundir archivar con borrar es como un CRM deja de ser el registro de la
    empresa."""
    salida = part.archivar(
        filas=[{"id": 1, "fecha": (HOY - timedelta(days=1000)).isoformat()}],
        destino="s3://frio",
        hoy=HOY,
    )
    assert salida["se_borra_algo"] is False
    assert salida["sigue_consultable"] is True


def test_no_se_borra_lo_que_esta_retenido() -> None:
    with pytest.raises(Prohibido) as fallo:
        part.exigir_no_retenido(fila={"obligacion_legal": True})
    assert fallo.value.error_code == "archivado.retenido"


def test_el_aviso_util_es_el_ritmo_al_que_crece() -> None:
    """Una tabla de cien millones estable no molesta; una de diez que dobla cada
    trimestre es un incidente dentro de nueve meses."""
    salida = part.salud_del_volumen(
        tablas=[
            {"nombre": "actividades", "filas": 20_000_000, "crecimiento_mensual_pct": 20},
            {"nombre": "paises", "filas": 200, "crecimiento_mensual_pct": 0},
        ]
    )
    assert [a["tabla"] for a in salida["avisos"]] == ["actividades"]


# ── Escalado horizontal (CRM-08.01.01.02) ─────────────────────────────────


def test_un_contador_en_memoria_impide_replicar() -> None:
    """Ya pasó aquí: el presupuesto de error medía la mitad con dos réplicas."""
    salida = esc.comprobar_replicable(servicio="party", declaracion={"contador_en_memoria": True})
    assert salida["replicable"] is False
    assert "un tercio" in salida["riesgos"][0]["pasa"]


def test_por_encima_del_limite_las_replicas_estorban() -> None:
    """La quinta réplica no reparte trabajo: quita conexiones a las otras cuatro."""
    salida = esc.replicas_utiles(
        servicio="party",
        limite="pool_postgres",
        capacidad_del_limite=100,
        consumo_por_replica=20,
        replicas_actuales=7,
    )
    assert salida["sobran"] == 2
    assert "quita capacidad" in salida["que_significa"]


def test_no_se_escala_el_que_se_nota_sino_el_que_tarda() -> None:
    """Si el gateway tarda porque `party` tarda, más gateways solo hacen que
    esperen más peticiones a la vez."""
    salida = esc.donde_escalar(
        servicios=[
            {"nombre": "gateway", "uso_del_limite_pct": 95, "depende_de": ["party"]},
            {"nombre": "party", "uso_del_limite_pct": 92, "depende_de": []},
        ]
    )
    assert salida["escalar"] == ["party"]


def test_si_nadie_esta_cerca_del_limite_el_problema_no_es_de_capacidad() -> None:
    """Es la respuesta incómoda que ahorra una factura."""
    salida = esc.donde_escalar(servicios=[{"nombre": "party", "uso_del_limite_pct": 20}])
    assert salida["escalar"] == []


# ── Entornos de pruebas (CRM-07.02.01.02) ─────────────────────────────────


def test_copiar_sin_anonimizar_exige_motivo_y_nombre() -> None:
    """La mayoría de las filtraciones de un CRM no salen de producción: salen de
    una copia."""
    with pytest.raises(Prohibido) as fallo:
        sbx.plan_de_copia(proposito="pruebas", porcentaje=100, anonimizar=False)
    assert fallo.value.error_code == "sandbox.sin_anonimizar_sin_motivo"


def test_la_copia_completa_se_avisa() -> None:
    """Con el 5 % se prueba igual de bien y hay veinte veces menos que proteger."""
    salida = sbx.plan_de_copia(proposito="pruebas", porcentaje=100, anonimizar=True)
    assert "por riesgo" in salida["aviso"]


def test_los_tokens_no_se_copian_nunca() -> None:
    """Un token válido en pruebas es una puerta abierta a producción."""
    salida = sbx.plan_de_copia(proposito="desarrollo", porcentaje=5, anonimizar=True)
    assert any(x["que"] == "credenciales" for x in salida["no_se_copian"])


def test_la_anonimizacion_es_consistente_dentro_del_entorno() -> None:
    """Si el mismo cliente sale distinto en dos tablas, el entorno no sirve para
    probar nada que cruce datos."""
    a = sbx.anonimizar_fila(
        fila={"nombre": "Ana Pérez"}, reglas={"nombre": "anonimizar"}, semilla="s1"
    )
    b = sbx.anonimizar_fila(
        fila={"nombre": "Ana Pérez"}, reglas={"nombre": "anonimizar"}, semilla="s1"
    )
    distinto = sbx.anonimizar_fila(
        fila={"nombre": "Ana Pérez"}, reglas={"nombre": "anonimizar"}, semilla="s2"
    )
    assert a["fila"]["nombre"] == b["fila"]["nombre"]
    assert a["fila"]["nombre"] != distinto["fila"]["nombre"]


def test_una_regla_desconocida_vacia_el_campo_en_vez_de_copiarlo() -> None:
    """El silencio por defecto tiene que ser el seguro, no el cómodo."""
    salida = sbx.anonimizar_fila(fila={"iban": "ES00"}, reglas={"iban": "lo_que_sea"}, semilla="s")
    assert salida["fila"]["iban"] is None
    assert salida["avisos"]


def test_se_detecta_la_columna_personal_que_nadie_declaro() -> None:
    """Se anonimiza lo que se ve y se olvidan el teléfono de una tabla secundaria
    y el nombre escrito a mano en una nota."""
    salida = sbx.comprobar_reglas(
        campos_personales=["nombre", "email", "telefono_secundario"],
        reglas={"nombre": "anonimizar", "email": "anonimizar"},
    )
    assert salida["sin_regla"] == ["telefono_secundario"]


def test_un_sandbox_vencido_con_datos_reales_es_urgente() -> None:
    """Es una copia de datos de clientes en un sitio del que ya nadie se acuerda."""
    salida = sbx.caducados(
        sandboxes=[
            {
                "nombre": "migracion-2025",
                "proposito": "migracion",
                "creado": (HOY - timedelta(days=500)).isoformat(),
                "con_datos_reales": True,
            }
        ],
        hoy=HOY,
    )
    assert salida["urgentes"]
    assert "y hoy" in salida["que_hacer"]
