"""Motor de informes y cuadros de mando (CRM-05.01.01, CRM-05.01.02.01).

Aquí no se ejecuta SQL contra el dato: eso lo resuelve contecintelligence (RT-4).
Lo que se prueba es lo que sí vive aquí, y son las cinco cosas que se rompen en
silencio:

  * el campo que alguien no puede ver y aun así sale en el informe,
  * el filtro de usuario concatenado en la consulta,
  * el resultado truncado que se lee como el total,
  * el informe programado que deja de llegar sin que nadie se entere,
  * y la instantánea duplicada que inventa un pico en la tendencia.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido

from services.analytics import informes as inf


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture(autouse=True)
def sin_ejecutor() -> Any:
    """Cada prueba parte sin ejecutor: registrar uno es lo que se está probando."""
    inf._EJECUTOR = None
    yield
    inf._EJECUTOR = None


def _informe(uow: UnidadDeTrabajo, **kw: Any) -> inf.Informe:
    base: dict[str, Any] = {
        "clave": "pipeline",
        "nombre": "Pipeline por mes",
        "objeto": "oportunidad",
        "tipo": "tabular",
        "columnas": ["nombre", "importe"],
    }
    base.update(kw)
    fila = inf.Informe(tenant_id=uow.tenant_id, **base)
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _ejecutor(filas: list[dict[str, Any]]) -> Any:
    def fn(plan: dict[str, Any], tenant_id: UUID) -> dict[str, Any]:
        return {"filas": filas}

    return fn


# ── Validación (CRM-05.01.01.01) ──────────────────────────────────────────


def test_un_agregado_inventado_se_rechaza() -> None:
    """Una definición es dato del tenant y no puede convertirse en SQL
    arbitrario."""
    with pytest.raises(ErrorValidacion) as e:
        inf.validar(
            {"objeto": "oportunidad", "metricas": [{"campo": "importe", "agregado": "drop"}]}
        )
    assert e.value.error_code == "informe.agregado_no_valido"


def test_un_operador_inventado_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion):
        inf.validar({"objeto": "oportunidad", "filtros": [{"campo": "importe", "operador": ";--"}]})


def test_un_agrupado_sin_agrupaciones_se_rechaza() -> None:
    """Es un informe tabular con otro nombre, y quien lo abra no entenderá por qué
    no agrupa nada."""
    with pytest.raises(ErrorValidacion) as e:
        inf.validar({"objeto": "oportunidad", "tipo": "agrupado"})
    assert e.value.error_code == "informe.agrupado_sin_agrupaciones"


def test_un_matricial_sin_pivote_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion):
        inf.validar(
            {
                "objeto": "oportunidad",
                "tipo": "matricial",
                "agrupaciones": [{"campo": "etapa"}],
            }
        )


def test_agrupar_sin_metricas_avisa_pero_no_rompe() -> None:
    """Rechazar por un aviso deja a alguien sin poder guardar un borrador a
    medias."""
    avisos = inf.validar(
        {"objeto": "oportunidad", "tipo": "agrupado", "agrupaciones": [{"campo": "etapa"}]}
    )
    assert any("ninguna cifra" in a for a in avisos)


def test_un_informe_vacio_avisa() -> None:
    assert any("saldrá vacío" in a for a in inf.validar({"objeto": "oportunidad"}))


# ── Compilación y seguridad (CRM-05.01.01.08) ─────────────────────────────


def test_el_plan_no_es_sql(uow: UnidadDeTrabajo) -> None:
    """Escribir SQL aquí sería un segundo motor de explotación, que es lo que
    RT-4 dice que no se haga. El plan es una estructura de datos y quien lo
    ejecuta lo traduce a su lenguaje."""
    fila = _informe(uow)
    plan = inf.compilar(uow.db, uow.tenant_id, fila)
    assert "sql" not in plan
    assert plan["columnas"] == ["nombre", "importe"]


def test_el_valor_de_un_filtro_viaja_como_valor(uow: UnidadDeTrabajo) -> None:
    """Un filtro es un dato que escribe un usuario. Va como dato en el plan, no
    concatenado en ningún texto."""
    fila = _informe(
        uow, filtros=[{"campo": "etapa", "operador": "=", "valor": "'; DROP TABLE x;--"}]
    )
    plan = inf.compilar(uow.db, uow.tenant_id, fila)
    assert plan["filtros"][0]["valor"] == "'; DROP TABLE x;--"


def test_un_nombre_de_campo_raro_se_rechaza(uow: UnidadDeTrabajo) -> None:
    """Los valores iban parametrizados pero los NOMBRES se interpolaban: un campo
    llamado `importe"; DROP TABLE x; --` se habría salido de sus comillas."""
    fila = _informe(uow, columnas=['importe"; DROP TABLE x; --'])
    with pytest.raises(ErrorValidacion) as e:
        inf.compilar(uow.db, uow.tenant_id, fila)
    assert e.value.error_code == "informe.campo_no_valido"


def test_un_campo_personal_no_sale_en_el_informe(
    uow: UnidadDeTrabajo, db: Any, tenant_id: UUID
) -> None:
    """Un informe que trae el dato y lo esconde en la pantalla ya lo ha sacado de
    la base: la respuesta de la API la ve cualquiera que abra las herramientas del
    navegador."""
    from crmcore import metamodelo

    metamodelo.aplicar_esquema(
        db,
        tenant_id=tenant_id,
        objeto="oportunidad",
        version=1,
        campos=[
            {
                "nombre": "dni_contacto",
                "tipo": "texto",
                "etiqueta": "DNI",
                "sensibilidad": "personal",
            },
            {"nombre": "region", "tipo": "texto", "etiqueta": "Región"},
        ],
    )
    fila = _informe(uow, columnas=["region", "dni_contacto"])
    plan = inf.compilar(uow.db, uow.tenant_id, fila, roles=frozenset({"comercial"}))
    assert plan["campos_retirados"] == ["dni_contacto"]
    assert plan["columnas"] == ["region"]


def test_el_administrador_si_lo_ve(uow: UnidadDeTrabajo, db: Any, tenant_id: UUID) -> None:
    from crmcore import metamodelo

    metamodelo.aplicar_esquema(
        db,
        tenant_id=tenant_id,
        objeto="oportunidad",
        version=1,
        campos=[{"nombre": "dni", "tipo": "texto", "etiqueta": "DNI", "sensibilidad": "personal"}],
    )
    fila = _informe(uow, columnas=["dni"])
    plan = inf.compilar(uow.db, uow.tenant_id, fila, es_admin=True)
    assert plan["campos_retirados"] == []


def test_el_filtro_por_dueno_lo_pone_el_servidor(uow: UnidadDeTrabajo) -> None:
    """Si viniera del cliente, bastaría quitarlo de la petición para ver los datos
    de todos, que es exactamente lo que el informe quería impedir."""
    yo = uuid4()
    fila = _informe(uow, solo_mios=True)
    plan = inf.compilar(uow.db, uow.tenant_id, fila, usuario_id=yo)
    impuesto = next(f for f in plan["filtros"] if f.get("impuesto"))
    assert impuesto["campo"] == "propietario_id"
    assert impuesto["valor"] == str(yo)
    assert plan["acotado_al_usuario"] is True


def test_un_campo_calculado_no_acepta_sql_libre(uow: UnidadDeTrabajo) -> None:
    """Una expresión libre sería SQL arbitrario escrito por un usuario final sobre
    la base de producción."""
    fila = _informe(
        uow,
        columnas=["importe", "unidades"],
        calculados=[{"izquierda": "importe", "operacion": "; DROP", "derecha": "unidades"}],
    )
    with pytest.raises(ErrorValidacion) as e:
        inf.compilar(uow.db, uow.tenant_id, fila)
    assert e.value.error_code == "informe.operacion_no_valida"


def test_dividir_por_cero_no_revienta_el_informe(uow: UnidadDeTrabajo) -> None:
    """En SQL revienta la consulta entera; en un informe, eso es una pantalla en
    blanco en vez de una fila rara."""
    fila = _informe(
        uow,
        columnas=["importe", "unidades"],
        calculados=[
            {"izquierda": "importe", "operacion": "/", "derecha": "unidades", "como": "medio"}
        ],
    )
    calculado = inf.compilar(uow.db, uow.tenant_id, fila)["calculados"][0]
    assert calculado["proteger_division"] is True


def test_un_calculado_sobre_un_campo_prohibido_se_para(
    uow: UnidadDeTrabajo, db: Any, tenant_id: UUID
) -> None:
    from crmcore import metamodelo

    metamodelo.aplicar_esquema(
        db,
        tenant_id=tenant_id,
        objeto="oportunidad",
        version=1,
        campos=[
            {"nombre": "coste", "tipo": "numero", "etiqueta": "Coste", "sensibilidad": "especial"},
            {"nombre": "importe", "tipo": "numero", "etiqueta": "Importe"},
        ],
    )
    fila = _informe(
        uow,
        columnas=["importe", "coste"],
        calculados=[{"izquierda": "importe", "operacion": "-", "derecha": "coste", "como": "m"}],
    )
    with pytest.raises(Prohibido):
        inf.compilar(uow.db, uow.tenant_id, fila, roles=frozenset({"comercial"}))


def test_la_agrupacion_por_periodo_se_compila(uow: UnidadDeTrabajo) -> None:
    fila = _informe(
        uow,
        tipo="agrupado",
        columnas=[],
        agrupaciones=[{"campo": "cerrada_el", "periodo": "mes"}],
        metricas=[{"campo": "importe", "agregado": "suma", "como": "total"}],
    )
    plan = inf.compilar(uow.db, uow.tenant_id, fila)
    assert plan["agrupaciones"] == [{"campo": "cerrada_el", "periodo": "mes"}]
    assert plan["metricas"][0] == {"campo": "importe", "agregado": "suma", "como": "total"}


def test_se_pide_una_fila_de_mas_que_el_tope(uow: UnidadDeTrabajo) -> None:
    """Es lo que permite decir «hay más» sin contar la tabla entera, que en un
    informe grande cuesta más que el propio informe."""
    plan = inf.compilar(uow.db, uow.tenant_id, _informe(uow, limite=10))
    assert (plan["limite"], plan["pedir"]) == (10, 11)


# ── Ejecución (CRM-05.01.01.09) ───────────────────────────────────────────


def test_sin_ejecutor_se_dice_en_vez_de_devolver_vacio(uow: UnidadDeTrabajo) -> None:
    """Un informe vacío se lee como «no hay datos» y manda a buscar el problema al
    sitio equivocado."""
    fila = _informe(uow)
    with pytest.raises(Conflicto) as e:
        inf.ejecutar(uow, fila.id)
    assert e.value.error_code == "informe.sin_ejecutor"


def test_el_intento_fallido_queda_registrado(uow: UnidadDeTrabajo, db: Any) -> None:
    """Sin el apunte, nadie sabría que alguien intentó abrirlo y no pudo."""
    from sqlalchemy import select

    fila = _informe(uow)
    with pytest.raises(Conflicto):
        inf.ejecutar(uow, fila.id)
    ejecucion = db.execute(select(inf.EjecucionInforme)).scalars().one()
    assert ejecucion.ok is False
    assert "ejecutor" in ejecucion.error


def test_un_informe_que_no_es_de_mi_rol_da_404(uow: UnidadDeTrabajo) -> None:
    """Un 403 confirma que ese informe existe y de qué va su nombre."""
    inf.registrar_ejecutor(_ejecutor([]))
    fila = _informe(uow, roles=["direccion"])
    with pytest.raises(NoEncontrado):
        inf.ejecutar(uow, fila.id, roles=frozenset({"comercial"}))


def test_el_resultado_truncado_se_dice(uow: UnidadDeTrabajo) -> None:
    """Un informe truncado en silencio se lee como el total, y con eso se toman
    decisiones."""
    inf.registrar_ejecutor(_ejecutor([{"n": i} for i in range(5)]))
    fila = _informe(uow, limite=3)
    salida = inf.ejecutar(uow, fila.id)
    assert salida["truncado"] is True
    assert salida["cuantas"] == 3


def test_un_fallo_del_motor_se_cuenta_como_fallo_y_no_como_vacio(
    uow: UnidadDeTrabajo, db: Any
) -> None:
    from sqlalchemy import select

    def revienta(plan: dict[str, Any], tenant_id: UUID) -> dict[str, Any]:
        raise RuntimeError("el almacén no responde")

    inf.registrar_ejecutor(revienta)
    fila = _informe(uow)
    with pytest.raises(Conflicto) as e:
        inf.ejecutar(uow, fila.id)
    assert e.value.error_code == "informe.fallo_ejecutor"
    assert db.execute(select(inf.EjecucionInforme)).scalars().one().ok is False


def test_la_ejecucion_guarda_que_campos_se_retiraron(
    uow: UnidadDeTrabajo, db: Any, tenant_id: UUID
) -> None:
    """Es la prueba de que el informe no enseñó más de lo permitido, y lo que
    permite auditarlo sin repetirlo."""
    from crmcore import metamodelo
    from sqlalchemy import select

    metamodelo.aplicar_esquema(
        db,
        tenant_id=tenant_id,
        objeto="oportunidad",
        version=1,
        campos=[{"nombre": "dni", "tipo": "texto", "etiqueta": "DNI", "sensibilidad": "personal"}],
    )
    inf.registrar_ejecutor(_ejecutor([]))
    fila = _informe(uow, columnas=["dni"])
    inf.ejecutar(uow, fila.id, roles=frozenset({"comercial"}))
    assert db.execute(select(inf.EjecucionInforme)).scalars().one().campos_retirados == ["dni"]


# ── Exportación (CRM-05.01.01.07) ─────────────────────────────────────────


def test_el_csv_se_genera_aqui() -> None:
    salida = inf.exportar([{"a": 1, "b": "x"}], formato="csv")
    assert salida["contenido"].splitlines()[0] == "a,b"
    assert salida["filas"] == 1


def test_el_csv_vacio_se_dice_vacio() -> None:
    assert inf.exportar([], formato="csv")["vacio"] is True


def test_el_pdf_no_se_genera_aqui() -> None:
    """Meter una librería de PDF en el servicio de explotación obligaría a
    desplegarlo para cambiar una tipografía, y acabaría habiendo dos maquetaciones
    del mismo dato."""
    salida = inf.exportar([{"a": 1}], formato="pdf")
    assert "encargo" in salida
    assert salida["encargo"]["plantilla"] == "informe/pdf"


def test_un_formato_inventado_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion):
        inf.exportar([], formato="docx")


def test_las_fechas_salen_en_iso_en_el_csv() -> None:
    salida = inf.exportar([{"dia": date(2026, 3, 1)}], formato="csv")
    assert "2026-03-01" in salida["contenido"]


# ── Programación (CRM-05.01.01.06) ────────────────────────────────────────


def test_una_programacion_sin_destino_no_manda_nada(uow: UnidadDeTrabajo) -> None:
    fila = _informe(uow)
    with pytest.raises(ErrorValidacion) as e:
        inf.programar(uow, fila.id)
    assert e.value.error_code == "informe.programacion_sin_destino"


def test_la_programacion_calcula_su_proxima_vez(uow: UnidadDeTrabajo) -> None:
    fila = _informe(uow)
    programacion = inf.programar(
        uow, fila.id, periodicidad="diaria", hora=7, destinatarios=["a@b.c"]
    )
    assert programacion.proxima_at > datetime.now(timezone.utc)


def test_un_informe_programado_que_falla_avisa(uow: UnidadDeTrabajo) -> None:
    """Un informe que deja de llegar no se echa de menos: la gente supone que no
    había nada que contar, y eso convierte un fallo en un punto ciego de
    semanas."""
    fila = _informe(uow)
    programacion = inf.programar(uow, fila.id, destinatarios=["a@b.c"])
    programacion.proxima_at = datetime.now(timezone.utc) - timedelta(hours=1)
    uow.db.flush()
    salida = inf.correr_programadas(uow, uow.tenant_id)
    assert len(salida["fallados"]) == 1
    assert programacion.fallos_seguidos == 1


def test_a_los_tres_fallos_seguidos_se_desactiva(uow: UnidadDeTrabajo) -> None:
    """Seguir intentándolo cada día contra un informe roto llena la bandeja de
    todo el mundo con el mismo error."""
    fila = _informe(uow)
    programacion = inf.programar(uow, fila.id, destinatarios=["a@b.c"])
    for _ in range(3):
        programacion.proxima_at = datetime.now(timezone.utc) - timedelta(hours=1)
        uow.db.flush()
        inf.correr_programadas(uow, uow.tenant_id)
    assert programacion.activa is False


def test_un_envio_correcto_limpia_el_contador(uow: UnidadDeTrabajo) -> None:
    inf.registrar_ejecutor(_ejecutor([{"a": 1}]))
    fila = _informe(uow)
    programacion = inf.programar(uow, fila.id, destinatarios=["a@b.c"])
    programacion.fallos_seguidos = 2
    programacion.proxima_at = datetime.now(timezone.utc) - timedelta(hours=1)
    uow.db.flush()
    salida = inf.correr_programadas(uow, uow.tenant_id)
    assert len(salida["mandados"]) == 1
    assert programacion.fallos_seguidos == 0


def test_omitir_si_vacio_esta_apagado_por_defecto(uow: UnidadDeTrabajo) -> None:
    """El silencio se lee como «no pasa nada» en vez de como «no se ejecutó»."""
    inf.registrar_ejecutor(_ejecutor([]))
    fila = _informe(uow)
    programacion = inf.programar(uow, fila.id, destinatarios=["a@b.c"])
    assert programacion.omitir_si_vacio is False
    programacion.proxima_at = datetime.now(timezone.utc) - timedelta(hours=1)
    uow.db.flush()
    salida = inf.correr_programadas(uow, uow.tenant_id)
    assert salida["mandados"][0].get("omitido_por_vacio") is None


def test_sin_programaciones_pendientes_no_se_dice_que_todo_fue_bien(
    uow: UnidadDeTrabajo,
) -> None:
    assert inf.correr_programadas(uow, uow.tenant_id)["medible"] is False


# ── Instantáneas y tendencia (CRM-05.01.01.05) ────────────────────────────


def test_dos_instantaneas_el_mismo_dia_no_crean_dos_puntos(
    uow: UnidadDeTrabajo,
) -> None:
    """Con dos, un gráfico de tendencia saldría con un pico que no ocurrió."""
    inf.registrar_ejecutor(_ejecutor([{"total": 10}]))
    fila = _informe(uow)
    inf.tomar_instantanea(uow, fila.id)
    segunda = inf.tomar_instantanea(uow, fila.id)
    assert segunda["sustituida"] is True
    assert inf.tendencia(uow.db, uow.tenant_id, fila.id)["cuantos"] == 1


def test_la_instantanea_guarda_los_totales_y_no_las_filas(uow: UnidadDeTrabajo, db: Any) -> None:
    """Guardar el detalle entero convertiría la tabla en una copia del CRM que
    crece sin fin y que nadie purga."""
    from sqlalchemy import select

    inf.registrar_ejecutor(_ejecutor([{"total": 10}, {"total": 5}]))
    fila = _informe(uow)
    inf.tomar_instantanea(uow, fila.id)
    guardada = db.execute(select(inf.InstantaneaInforme)).scalars().one()
    assert guardada.resumen["totales"]["total"] == "15"
    assert "filas_detalle" not in guardada.resumen


def test_con_un_solo_punto_no_hay_tendencia(uow: UnidadDeTrabajo) -> None:
    """Una sola instantánea es una foto, y llamarla tendencia hace que alguien
    saque una conclusión de un punto."""
    inf.registrar_ejecutor(_ejecutor([{"total": 1}]))
    fila = _informe(uow)
    inf.tomar_instantanea(uow, fila.id)
    salida = inf.tendencia(uow.db, uow.tenant_id, fila.id)
    assert salida["hay_tendencia"] is False
    assert "es una foto" in salida["aviso"]


def test_con_dos_puntos_si(uow: UnidadDeTrabajo) -> None:
    inf.registrar_ejecutor(_ejecutor([{"total": 1}]))
    fila = _informe(uow)
    inf.tomar_instantanea(uow, fila.id, el_dia=date.today() - timedelta(days=1))
    inf.tomar_instantanea(uow, fila.id)
    assert inf.tendencia(uow.db, uow.tenant_id, fila.id)["hay_tendencia"] is True


# ── Cuadros de mando (CRM-05.01.02.01) ────────────────────────────────────


def test_solo_hay_un_cuadro_por_defecto_por_rol(uow: UnidadDeTrabajo) -> None:
    """Con dos, cuál se abre dependería del orden de la consulta, y eso cambia al
    restaurar una copia."""
    inf.crear_cuadro(uow, clave="a", nombre="A", por_defecto_para="comercial")
    with pytest.raises(Conflicto) as e:
        inf.crear_cuadro(uow, clave="b", nombre="B", por_defecto_para="comercial")
    assert e.value.error_code == "cuadro.defecto_duplicado"


def test_un_cuadro_sin_publico_es_de_todos(uow: UnidadDeTrabajo) -> None:
    """Exigir declarar el público de cada uno haría que el primero que alguien
    crea no lo vea nadie, y la conclusión sería que los cuadros no funcionan."""
    inf.crear_cuadro(uow, clave="general", nombre="General")
    visibles = inf.cuadros_de(uow.db, uow.tenant_id, roles=frozenset({"quien_sea"}))
    assert [c["clave"] for c in visibles] == ["general"]


def test_un_cuadro_de_otro_rol_no_se_ve(uow: UnidadDeTrabajo) -> None:
    inf.crear_cuadro(uow, clave="direccion", nombre="Dirección", roles=["direccion"])
    assert inf.cuadros_de(uow.db, uow.tenant_id, roles=frozenset({"comercial"})) == []


def test_el_propietario_ve_el_suyo_aunque_no_sea_de_su_rol(
    uow: UnidadDeTrabajo,
) -> None:
    yo = uuid4()
    inf.crear_cuadro(uow, clave="mio", nombre="Mío", roles=["otro_rol"], propietario_id=yo)
    visibles = inf.cuadros_de(uow.db, uow.tenant_id, roles=frozenset({"comercial"}), usuario_id=yo)
    assert visibles[0]["propio"] is True


# ── Corregir un informe (CRM-05.01.01.02) ─────────────────────────────────


@pytest.mark.db
def test_un_informe_se_puede_corregir(uow: UnidadDeTrabajo) -> None:
    """Existía crear y no existía corregir.

    Una errata —o un campo que resultó no existir— solo se arreglaba creando
    otro informe al lado, y entonces los cuadros de mando siguen apuntando al
    viejo: la pantalla sigue enseñando el número equivocado.
    """
    informe = _informe(uow, clave="para-corregir", nombre="Con errata")
    inf.editar(uow, informe.id, cambios={"nombre": "Sin errata", "columnas": ["nombre"]})
    assert informe.nombre == "Sin errata"
    assert informe.columnas == ["nombre"]


@pytest.mark.db
def test_corregir_no_cambia_la_clave_ni_el_objeto(uow: UnidadDeTrabajo) -> None:
    """La clave es como lo referencian los cuadros: cambiarla los deja apuntando
    a nada. Y un informe de oportunidades convertido en uno de cuentas conserva
    columnas y filtros que ya no existen — sale roto con el mismo nombre."""
    informe = _informe(uow, clave="intocable", objeto="oportunidad")
    inf.editar(uow, informe.id, cambios={"clave": "otra", "objeto": "cuenta"})
    assert informe.clave == "intocable"
    assert informe.objeto == "oportunidad"


@pytest.mark.db
def test_no_se_borra_un_informe_que_usa_un_cuadro(uow: UnidadDeTrabajo) -> None:
    """Borrarlo deja el cuadro con un hueco que solo aparece al abrirlo.

    Y aparece delante de quien lo abre, sin ninguna pista de qué pasó.
    """
    from crmcore.errors import Conflicto

    informe = _informe(uow, clave="usado-en-un-cuadro")
    inf.crear_cuadro(
        uow,
        clave="el-cuadro",
        nombre="El cuadro",
        descripcion="",
        componentes=[{"tipo": "tabla", "informe": "usado-en-un-cuadro"}],
        roles=[],
        equipos=[],
        por_defecto_para="",
    )
    with pytest.raises(Conflicto) as e:
        inf.borrar_informe(uow, informe.id)
    assert e.value.error_code == "informe.en_uso"
    # Y se dice CUÁL, que es lo que permite arreglarlo sin buscarlo.
    assert "El cuadro" in e.value.detalle["cuadros"]


@pytest.mark.db
def test_un_informe_que_ningun_cuadro_usa_se_borra(uow: UnidadDeTrabajo) -> None:
    informe = _informe(uow, clave="sin-usar")
    inf.borrar_informe(uow, informe.id)
    assert informe.deleted_at is not None


# ── Lo que el plan pide y el motor no aplica ──────────────────────────────


def test_un_informe_con_campos_calculados_avisa_de_que_no_se_aplican(
    uow: UnidadDeTrabajo,
) -> None:
    """El plan viaja entero y el ejecutor solo aplica lo que su esquema declara.

    `/api/query/plan` de contecintelligence declara nueve campos y el plan lleva
    quince: `calculados` y `pivote` se ignoran sin error, porque un campo que un
    cuerpo JSON no declara no es un fallo para nadie. El informe sale con su
    tabla y sus cifras, y le faltan las columnas que alguien definió.
    """
    inf.registrar_ejecutor(_ejecutor([["ACME", 10]]))
    fila = _informe(
        uow,
        calculados=[
            {"como": "margen", "izquierda": "importe", "operacion": "-", "derecha": "importe"}
        ],
    )
    salida = inf.ejecutar(uow, fila.id)
    assert salida["incompleto"] is True
    assert "calculado" in salida["aviso_plan"]
    # Y las cabeceras no se inventan la columna que no ha venido.
    assert "margen" not in salida["columnas"]


def test_un_informe_matricial_avisa_de_que_no_se_pivota(uow: UnidadDeTrabajo) -> None:
    # Una sola columna nombrada y una sola por fila: si no cuadraran, lo que
    # saltaría es el otro aviso —el de que vienen columnas de más—, y esta
    # prueba estaría mirando otra cosa.
    inf.registrar_ejecutor(_ejecutor([["ACME"]]))
    fila = _informe(uow, tipo="matricial", pivote="etapa", agrupaciones=[{"campo": "nombre"}])
    salida = inf.ejecutar(uow, fila.id)
    assert salida["incompleto"] is True
    assert "etapa" in salida["aviso_plan"]


def test_sin_calculados_ni_pivote_no_se_avisa_de_nada(uow: UnidadDeTrabajo) -> None:
    """Un aviso que sale siempre deja de leerse."""
    inf.registrar_ejecutor(_ejecutor([["ACME", 10]]))
    salida = inf.ejecutar(uow, _informe(uow).id)
    assert "aviso_plan" not in salida


def test_si_el_motor_ya_los_aplica_el_aviso_cambia(uow: UnidadDeTrabajo) -> None:
    """Se mide, no se supone: una fila más ancha significa que ya vienen.

    Es la condición que dice que hay que quitar este aviso, y por eso la prueba
    existe: el día que contecintelligence aplique los calculados, esto avisa de
    que las cabeceras se han quedado cortas en vez de seguir diciendo que no se
    aplican.
    """
    inf.registrar_ejecutor(_ejecutor([["ACME", 10, 3]]))
    fila = _informe(
        uow,
        calculados=[
            {"como": "margen", "izquierda": "importe", "operacion": "-", "derecha": "importe"}
        ],
    )
    salida = inf.ejecutar(uow, fila.id)
    assert "incompleto" not in salida
    assert "más columnas" in salida["aviso_plan"]


def test_toda_clave_del_plan_esta_declarada_o_apuntada_como_no_aplicada(
    uow: UnidadDeTrabajo,
) -> None:
    """El plan y el esquema de quien lo ejecuta, comparados clave a clave.

    No se puede leer del código —el cuerpo sale de `plan.items()`, no de un
    diccionario literal— así que se compila uno de verdad y se mira. Lo que se
    defiende es que nadie añada una clave al plan sin decidir qué pasa con ella:
    o la declara el ejecutor, o se apunta aquí como sabida y no aplicada.

    Las seis de abajo son las que hoy se pierden. `calculados` y `pivote` cambian
    el resultado y por eso el informe sale avisando; las otras cuatro son
    contexto que contecrm consume por su cuenta al componer la respuesta.
    """
    import json
    from pathlib import Path

    NO_APLICADAS = {
        "calculados": "el motor no las aplica; el resultado sale marcado «incompleto»",
        "pivote": "idem: un matricial sale sin pivotar, y se avisa",
        "pedir": "es `limite + 1`, para saber si hay más; el ejecutor aplica `limite`",
        "objeto": "de qué objeto del CRM es; se usa aquí, no allí",
        "campos_retirados": "lo que se quitó por permisos; va a la respuesta, no a la consulta",
        "acotado_al_usuario": "idem: se dice en la respuesta",
    }

    contrato = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "tests"
            / "fixtures"
            / "contratos"
            / "contecintelligence.json"
        ).read_text("utf-8")
    )
    declaradas = set(contrato["/api/query/plan"]["post"]["campos"])

    plan = inf.compilar(uow.db, uow.tenant_id, _informe(uow))
    viajan = {k for k in plan if not k.startswith("_")}

    sin_decidir = sorted(viajan - declaradas - set(NO_APLICADAS))
    assert not sin_decidir, (
        f"El plan manda {sin_decidir} y `/api/query/plan` no lo declara: se "
        "ignorará sin error. O se implementa allí y se refresca el contrato, o "
        "se apunta en NO_APLICADAS con lo que pasa cuando se pierde."
    )
    ya_declaradas = sorted(set(NO_APLICADAS) & declaradas)
    assert not ya_declaradas, (
        f"{ya_declaradas} ya está en el esquema del ejecutor. Quítalas de "
        "NO_APLICADAS y del aviso: mientras estén, se sigue avisando de algo "
        "que ya funciona."
    )


def test_el_informe_programado_dice_si_lo_que_manda_esta_incompleto(
    uow: UnidadDeTrabajo,
) -> None:
    """Un informe que llega por correo se lee como el total.

    En pantalla el aviso va debajo de la cifra; en un correo no hay debajo. Si
    el evento no lo lleva, quien lo recibe se queda con un fichero de aspecto
    impecable al que le faltan las columnas que alguien definió.

    Va SIEMPRE, también cuando es `False`: un campo que solo aparece cuando hay
    problema obliga a quien integra a distinguir «no está» de «está y es que
    no», y por el camino se lee como que todo va bien.
    """
    inf.registrar_ejecutor(_ejecutor([["ACME", 10]]))
    fila = _informe(
        uow,
        calculados=[
            {"como": "margen", "izquierda": "importe", "operacion": "-", "derecha": "importe"}
        ],
    )
    programacion = inf.programar(uow, fila.id, destinatarios=["jefe@ejemplo.test"])
    programacion.proxima_at = datetime.now(timezone.utc) - timedelta(hours=1)
    uow.db.flush()

    inf.correr_programadas(uow, uow.tenant_id)
    entregado = next(e for e in uow._pendientes if e["tipo"] == "report.delivered")
    assert entregado["data"]["incompleto"] is True
    assert "calculado" in entregado["data"]["aviso"]


def test_un_programado_completo_lo_dice_tambien(uow: UnidadDeTrabajo) -> None:
    inf.registrar_ejecutor(_ejecutor([["ACME", 10]]))
    programacion = inf.programar(uow, _informe(uow).id, destinatarios=["a@b.c"])
    programacion.proxima_at = datetime.now(timezone.utc) - timedelta(hours=1)
    uow.db.flush()
    inf.correr_programadas(uow, uow.tenant_id)
    entregado = next(e for e in uow._pendientes if e["tipo"] == "report.delivered")
    assert entregado["data"]["incompleto"] is False


# ── Exportar: las filas son LISTAS ────────────────────────────────────────


def test_exportar_a_csv_con_la_forma_que_de_verdad_tienen_las_filas(
    uow: UnidadDeTrabajo,
) -> None:
    """El ejecutor devuelve `rows: list[list]`, no diccionarios.

    `exportar` pedía diccionarios y hacía `filas[0].keys()`, así que descargar
    un informe en CSV daba un 500 y un informe programado fallaba cada noche
    hasta desactivarse solo a los tres intentos. Las pruebas no lo cazaron
    porque le pasaban diccionarios: una forma que el sistema no produce.
    """
    salida = inf.exportar([["ACME", 10], ["OTRA", 20]], columnas=["nombre", "importe"])
    assert salida["contenido"].splitlines()[0] == "nombre,importe"
    assert salida["contenido"].splitlines()[1] == "ACME,10"
    assert salida["filas"] == 2


def test_un_valor_sin_cabecera_sale_con_un_nombre_puesto(uow: UnidadDeTrabajo) -> None:
    """Tirarlo es peor: es un dato que el motor ha devuelto y nadie vería.

    Pasa cuando el ejecutor aplica algo que este lado no sabe nombrar todavía
    —los campos calculados, el día que se implementen allí—.
    """
    salida = inf.exportar([["ACME", 10, 3]], columnas=["nombre", "importe"])
    assert salida["contenido"].splitlines()[0] == "nombre,importe,columna_3"
    assert salida["contenido"].splitlines()[1] == "ACME,10,3"


def test_el_encargo_de_pdf_tambien_lleva_sus_columnas(uow: UnidadDeTrabajo) -> None:
    """El generador documental maqueta con ellas: sin nombres, una tabla muda."""
    salida = inf.exportar([["ACME", 10]], columnas=["nombre", "importe"], formato="pdf")
    assert salida["encargo"]["columnas"] == ["nombre", "importe"]
    assert salida["encargo"]["filas"] == [{"nombre": "ACME", "importe": 10}]


def test_descargar_un_informe_en_csv_no_revienta(uow: UnidadDeTrabajo) -> None:
    """La vía completa, tal y como la llama la API."""
    inf.registrar_ejecutor(_ejecutor([["ACME", 10]]))
    salida = inf.ejecutar(uow, _informe(uow).id, formato="csv")
    export = inf.exportar(
        salida["filas"], columnas=salida["columnas"], formato="csv", nombre=salida["informe"]
    )
    assert export["vacio"] is False
    assert "ACME" in export["contenido"]
