"""Servicio de campo: órdenes, rutas, repuestos, preventivo y sincronización
(CRM-04.04.01).

En campo, quien ejecuta no está delante de un ordenador: está subido a una
máquina, a veces sin cobertura, y con el cliente mirando. Las pruebas van detrás
de lo que hace que un sistema así deje de usarse:

  * el consumo de pieza que se rechaza por stock y acaba sin apuntarse,
  * la ruta que presenta como óptimo el orden de la lista,
  * el checklist que se puede dejar a medias,
  * la firma que no dice sobre qué se dio,
  * el lote de seis horas de trabajo que se pierde entero por un cambio malo,
  * y el preventivo que genera seis órdenes idénticas de un plan desatendido.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.fechas import hoy

from services.service import activos as act
from services.service import campo


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _tecnico(uow: UnidadDeTrabajo, **kw: Any) -> campo.Tecnico:
    base: dict[str, Any] = {
        "usuario_id": uuid4(),
        "nombre": "Ana",
        "competencias": [{"clave": "frigorista", "nivel": 2}],
        "base_latitud": Decimal("41.390000"),
        "base_longitud": Decimal("2.170000"),
    }
    base.update(kw)
    fila = campo.Tecnico(tenant_id=uow.tenant_id, **base)
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _orden(uow: UnidadDeTrabajo, **kw: Any) -> campo.OrdenTrabajo:
    base: dict[str, Any] = {"titulo": "Avería en cámara"}
    base.update(kw)
    fila, _ = campo.crear_orden(uow, **base)
    return fila


def _repuesto(uow: UnidadDeTrabajo, sku: str = "REP-1") -> campo.Repuesto:
    fila = campo.Repuesto(tenant_id=uow.tenant_id, sku=sku, nombre=sku)
    uow.db.add(fila)
    uow.db.flush()
    return fila


# ── Órdenes (CRM-04.04.01.01) ─────────────────────────────────────────────


def test_la_orden_avisa_de_lo_que_no_se_podra_hacer(uow: UnidadDeTrabajo) -> None:
    """Sin coordenadas no entra en la ruta; sin competencias le toca a cualquiera."""
    _, avisos = campo.crear_orden(uow, titulo="Avería")
    assert any("coordenadas" in a for a in avisos)
    assert any("competencias" in a for a in avisos)


def test_la_orden_hereda_ubicacion_del_activo(uow: UnidadDeTrabajo) -> None:
    activo, _ = act.crear(
        uow,
        nombre="Cámara",
        cuenta_id=uuid4(),
        ubicacion="Polígono Sur, nave 3",
        latitud=Decimal("41.400000"),
        longitud=Decimal("2.180000"),
    )
    orden = _orden(uow, activo_id=activo.id)
    assert orden.direccion == "Polígono Sur, nave 3"
    assert orden.cuenta_id == activo.cuenta_id
    assert orden.latitud == activo.latitud


def test_los_candidatos_dicen_por_que_se_descarta_a_cada_uno(uow: UnidadDeTrabajo) -> None:
    """«Nadie disponible» por competencia, por zona o por bajas son tres
    decisiones distintas."""
    apto = _tecnico(uow)
    _tecnico(uow, nombre="Sin competencia", competencias=[], usuario_id=uuid4())
    _tecnico(uow, nombre="De baja", usuario_id=uuid4(), activo=False)
    orden = _orden(uow, competencias=["frigorista"])

    salida = campo.candidatos(uow.db, uow.tenant_id, orden.id)
    assert [a["tecnico_id"] for a in salida["aptos"]] == [str(apto.id)]
    porques = " ".join(d["porque"] for d in salida["descartados"])
    assert "competencias" in porques and "activo" in porques


def test_un_tecnico_sin_zonas_cubre_todas(uow: UnidadDeTrabajo) -> None:
    """Un dato que falta no puede dejar a alguien sin trabajo sin que nadie sepa
    por qué."""
    _tecnico(uow, zonas=[])
    orden = _orden(uow, competencias=["frigorista"], zona="norte")
    assert campo.candidatos(uow.db, uow.tenant_id, orden.id)["hay_candidatos"] is True


def test_no_se_asigna_sin_competencias_salvo_forzando_con_motivo(
    uow: UnidadDeTrabajo,
) -> None:
    tecnico = _tecnico(uow, competencias=[])
    orden = _orden(uow, competencias=["frigorista"])
    with pytest.raises(Conflicto):
        campo.asignar(uow, orden.id, tecnico_id=tecnico.id)
    with pytest.raises(ErrorValidacion):
        campo.asignar(uow, orden.id, tecnico_id=tecnico.id, forzar=True)
    _, avisos = campo.asignar(
        uow, orden.id, tecnico_id=tecnico.id, forzar=True, motivo="No hay nadie más hoy"
    )
    assert any("sin las competencias" in a for a in avisos)


def test_el_solape_de_citas_avisa_pero_no_bloquea(uow: UnidadDeTrabajo) -> None:
    """En campo, dos citas solapadas a veces son un trabajo de diez minutos metido
    entre dos. Bloquearlo obliga a planificar fuera del sistema."""
    tecnico = _tecnico(uow)
    inicio = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    una = _orden(uow, competencias=["frigorista"])
    campo.asignar(
        uow,
        una.id,
        tecnico_id=tecnico.id,
        cita_desde=inicio,
        cita_hasta=inicio + timedelta(hours=2),
    )
    otra = _orden(uow, competencias=["frigorista"])
    _, avisos = campo.asignar(
        uow,
        otra.id,
        tecnico_id=tecnico.id,
        cita_desde=inicio + timedelta(minutes=30),
        cita_hasta=inicio + timedelta(hours=1),
    )
    assert any("solapa" in a for a in avisos)


def test_la_cita_fuera_de_la_ventana_comprometida_avisa(uow: UnidadDeTrabajo) -> None:
    tecnico = _tecnico(uow)
    inicio = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    orden = _orden(
        uow,
        competencias=["frigorista"],
        ventana_desde=inicio,
        ventana_hasta=inicio + timedelta(hours=4),
    )
    _, avisos = campo.asignar(
        uow,
        orden.id,
        tecnico_id=tecnico.id,
        cita_desde=inicio + timedelta(hours=5),
        cita_hasta=inicio + timedelta(hours=6),
    )
    assert any("ventana" in a for a in avisos)


def test_una_orden_sin_tecnico_no_la_empieza_nadie(uow: UnidadDeTrabajo) -> None:
    orden = _orden(uow)
    with pytest.raises(Conflicto):
        campo.iniciar(uow, orden.id)


def test_pausar_exige_motivo(uow: UnidadDeTrabajo) -> None:
    """«Esperando pieza» y «el cliente no estaba» se corrigen distinto."""
    orden = _orden(uow)
    with pytest.raises(ErrorValidacion):
        campo.pausar(uow, orden.id, motivo="  ")
    campo.pausar(uow, orden.id, motivo="Falta la pieza")


# ── Cobertura en la línea ─────────────────────────────────────────────────


def test_la_linea_dice_si_lo_paga_el_cliente_al_apuntarla(uow: UnidadDeTrabajo) -> None:
    """El técnico tiene que poder decírselo ahí mismo, no al facturar."""
    activo, _ = act.crear(uow, nombre="Cámara")
    act.registrar_garantia(
        uow,
        activo.id,
        desde=hoy(uow.db) - timedelta(days=10),
        hasta=hoy(uow.db) + timedelta(days=300),
        cobertura=["piezas"],
    )
    orden = _orden(uow, activo_id=activo.id)
    pieza, _ = campo.anotar_linea(uow, orden.id, tipo="material", concepto="Junta")
    viaje, _ = campo.anotar_linea(uow, orden.id, tipo="desplazamiento", concepto="Viaje")
    assert pieza.cubierto_garantia is True
    assert viaje.cubierto_garantia is False


def test_sin_garantias_la_linea_queda_sin_determinar(uow: UnidadDeTrabajo) -> None:
    """Marcarla como no cubierta factura al cliente que sí lo estaba."""
    activo, _ = act.crear(uow, nombre="Cámara")
    orden = _orden(uow, activo_id=activo.id)
    linea, avisos = campo.anotar_linea(uow, orden.id, tipo="material", concepto="Junta")
    assert linea.cubierto_garantia is None
    assert avisos and "no se sabe" in avisos[0]

    resumen = campo.resumen_orden(uow.db, uow.tenant_id, orden.id)
    assert resumen["sin_determinar"] == 1
    assert resumen["a_facturar"] == 0 and resumen["a_garantia"] == 0


def test_un_tramo_de_tiempo_al_reves_se_rechaza(uow: UnidadDeTrabajo) -> None:
    orden = _orden(uow)
    ahora = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    with pytest.raises(ErrorValidacion):
        campo.anotar_linea(
            uow, orden.id, tipo="tiempo", desde=ahora, hasta=ahora - timedelta(hours=1)
        )


# ── Repuestos (CRM-04.04.01.04) ───────────────────────────────────────────


def test_el_consumo_sin_stock_se_registra_y_se_marca(uow: UnidadDeTrabajo) -> None:
    """Si el técnico dice que ha montado la pieza, está montada: lo que está mal
    es el stock. Rechazarlo pierde las dos cosas."""
    tecnico = _tecnico(uow)
    repuesto = _repuesto(uow)
    salida = campo.mover_repuesto(
        uow, tecnico_id=tecnico.id, repuesto_id=repuesto.id, tipo="consumo", cantidad=Decimal(2)
    )
    assert salida["dejo_negativo"] is True and salida["aviso"]
    assert Decimal(salida["saldo"]) == Decimal(-2)


def test_el_ajuste_fija_el_saldo_y_exige_motivo(uow: UnidadDeTrabajo) -> None:
    tecnico = _tecnico(uow)
    repuesto = _repuesto(uow)
    campo.mover_repuesto(
        uow, tecnico_id=tecnico.id, repuesto_id=repuesto.id, tipo="carga", cantidad=Decimal(10)
    )
    with pytest.raises(ErrorValidacion):
        campo.mover_repuesto(
            uow, tecnico_id=tecnico.id, repuesto_id=repuesto.id, tipo="ajuste", cantidad=Decimal(7)
        )
    salida = campo.mover_repuesto(
        uow,
        tecnico_id=tecnico.id,
        repuesto_id=repuesto.id,
        tipo="ajuste",
        cantidad=Decimal(7),
        motivo="Recuento de furgoneta",
    )
    assert Decimal(salida["saldo"]) == Decimal(7)
    assert Decimal(salida["delta"]) == Decimal(-3)


def test_apuntar_material_descuenta_de_la_furgoneta(uow: UnidadDeTrabajo) -> None:
    """Si el consumo no toca el stock, el stock no significa nada a los dos días."""
    tecnico = _tecnico(uow)
    repuesto = _repuesto(uow)
    campo.mover_repuesto(
        uow, tecnico_id=tecnico.id, repuesto_id=repuesto.id, tipo="carga", cantidad=Decimal(5)
    )
    orden = _orden(uow, competencias=["frigorista"])
    campo.asignar(uow, orden.id, tecnico_id=tecnico.id)
    campo.anotar_linea(uow, orden.id, tipo="material", repuesto_id=repuesto.id, cantidad=Decimal(2))
    stock = campo.reposicion(uow.db, uow.tenant_id, tecnico_id=tecnico.id)
    assert stock["medible"] is True
    # 5 - 2 = 3, y sin mínimo puesto no pide reposición… y eso se dice.
    assert stock["sin_minimo"] == 1


def test_la_reposicion_dice_cuantas_referencias_no_tienen_minimo(
    uow: UnidadDeTrabajo,
) -> None:
    """Un mínimo a cero nunca pide reposición: la lista sale vacía y parece que
    todo está bien."""
    tecnico = _tecnico(uow)
    uno = _repuesto(uow, "REP-1")
    dos = _repuesto(uow, "REP-2")
    campo.mover_repuesto(
        uow, tecnico_id=tecnico.id, repuesto_id=uno.id, tipo="carga", cantidad=Decimal(1)
    )
    fila = campo.StockFurgoneta(
        tenant_id=uow.tenant_id,
        tecnico_id=tecnico.id,
        repuesto_id=dos.id,
        cantidad=Decimal(1),
        minimo=Decimal(5),
    )
    uow.db.add(fila)
    uow.db.flush()
    salida = campo.reposicion(uow.db, uow.tenant_id, tecnico_id=tecnico.id)
    assert salida["sin_minimo"] == 1
    assert [linea["reponer"] for linea in salida["lineas"]] == ["4.00"]


def test_el_minimo_se_puede_fijar_desde_el_producto(uow: UnidadDeTrabajo) -> None:
    """La mitad que faltaba no era la medida: era la puerta.

    `reposicion()` decide qué hay que cargar comparando la existencia con
    `stock_furgoneta.minimo`. Ese campo lo leía ella, lo contaba —devuelve
    `sin_minimo`— y **ninguna ruta lo escribía**. Se quedaba en el cero por
    defecto, con el que «por debajo del mínimo» no se cumple nunca, así que la
    pantalla salía vacía: lo mismo que se ve con un almacén perfectamente
    surtido. Medido el 28-10-2026 sembrando cinco referencias con existencias y
    movimientos de verdad, y «qué hay que cargar» sin una sola línea.

    Por qué no se había cazado: la prueba de arriba **planta la fila a mano**,
    con su mínimo puesto, así que demuestra que el cálculo está bien y pasa por
    encima de que no haya forma de llegar hasta él. Ésta entra por donde entra
    el producto.
    """
    tecnico = _tecnico(uow)
    repuesto = _repuesto(uow, "REP-MIN")

    # Y se puede declarar antes de cargar nada: preparar una furgoneta empieza
    # por decir qué tiene que llevar, no por llevarlo.
    salida = campo.fijar_minimo(
        uow, tecnico_id=tecnico.id, repuesto_id=repuesto.id, minimo=Decimal(6)
    )
    assert salida["hay_que_reponer"] is True
    assert campo.reposicion(uow.db, uow.tenant_id, tecnico_id=tecnico.id)["lineas"] == [
        {
            "tecnico_id": str(tecnico.id),
            "repuesto_id": str(repuesto.id),
            "cantidad": "0.000",
            # Tres decimales porque es lo que guarda la columna; «reponer» sale
            # con dos porque lo calcula `_redondear`.
            "minimo": "6.000",
            "reponer": "6.00",
            "en_negativo": False,
        }
    ]

    # Al cargar por encima del mínimo deja de pedirse, que es lo que convierte
    # la pantalla en una lista de trabajo y no en un inventario.
    campo.mover_repuesto(
        uow, tecnico_id=tecnico.id, repuesto_id=repuesto.id, tipo="carga", cantidad=Decimal(10)
    )
    assert campo.reposicion(uow.db, uow.tenant_id, tecnico_id=tecnico.id)["lineas"] == []


def test_un_minimo_negativo_no_quiere_decir_nada(uow: UnidadDeTrabajo) -> None:
    """Y se rechaza al escribirlo, no al leerlo: un mínimo de −3 haría que la
    reposición pidiera cantidades negativas y nadie sabría de dónde salen."""
    tecnico = _tecnico(uow)
    repuesto = _repuesto(uow, "REP-NEG")
    with pytest.raises(ErrorValidacion) as e:
        campo.fijar_minimo(uow, tecnico_id=tecnico.id, repuesto_id=repuesto.id, minimo=Decimal(-3))
    assert e.value.error_code == "campo.minimo_invalido"


# ── Rutas (CRM-04.04.01.02) ───────────────────────────────────────────────


def _con_cita(
    uow: UnidadDeTrabajo, tecnico: campo.Tecnico, hora: int, lat: str, lon: str
) -> campo.OrdenTrabajo:
    orden = _orden(
        uow,
        competencias=["frigorista"],
        latitud=Decimal(lat),
        longitud=Decimal(lon),
        duracion_estimada_min=60,
    )
    inicio = datetime(2026, 10, 1, hora, tzinfo=timezone.utc)
    campo.asignar(
        uow,
        orden.id,
        tecnico_id=tecnico.id,
        cita_desde=inicio,
        cita_hasta=inicio + timedelta(hours=1),
    )
    return orden


def test_la_ruta_ordena_por_cercania_desde_la_base(uow: UnidadDeTrabajo) -> None:
    tecnico = _tecnico(uow)
    lejos = _con_cita(uow, tecnico, 9, "41.600000", "2.600000")
    cerca = _con_cita(uow, tecnico, 11, "41.395000", "2.175000")
    salida = campo.planificar_ruta(
        uow.db, uow.tenant_id, tecnico_id=tecnico.id, dia=date(2026, 10, 1)
    )
    assert [p["orden_id"] for p in salida["ruta"]] == [str(cerca.id), str(lejos.id)]
    assert salida["optimizada"] is True
    assert salida["estimacion"] == "linea_recta"


def test_lo_que_no_tiene_coordenadas_va_al_final_y_se_dice(uow: UnidadDeTrabajo) -> None:
    """Colocarlo donde caiga daría una ruta que parece calculada y no lo está."""
    tecnico = _tecnico(uow)
    _con_cita(uow, tecnico, 9, "41.395000", "2.175000")
    ciega = _orden(uow, competencias=["frigorista"])
    inicio = datetime(2026, 10, 1, 11, tzinfo=timezone.utc)
    campo.asignar(
        uow,
        ciega.id,
        tecnico_id=tecnico.id,
        cita_desde=inicio,
        cita_hasta=inicio + timedelta(hours=1),
    )
    salida = campo.planificar_ruta(
        uow.db, uow.tenant_id, tecnico_id=tecnico.id, dia=date(2026, 10, 1)
    )
    assert salida["ruta"][-1]["orden_id"] == str(ciega.id)
    assert salida["sin_coordenadas"] == [str(ciega.id)]
    assert salida["aviso"]


def test_sin_base_del_tecnico_la_ruta_no_se_declara_optimizada(
    uow: UnidadDeTrabajo,
) -> None:
    """Sin base, el primer viaje del día no se cuenta y la jornada parece media
    hora más corta."""
    tecnico = _tecnico(uow, base_latitud=None, base_longitud=None)
    _con_cita(uow, tecnico, 9, "41.395000", "2.175000")
    salida = campo.planificar_ruta(
        uow.db, uow.tenant_id, tecnico_id=tecnico.id, dia=date(2026, 10, 1)
    )
    assert salida["base_conocida"] is False and salida["optimizada"] is False


def test_la_ruta_dice_si_no_cabe_en_la_jornada(uow: UnidadDeTrabajo) -> None:
    tecnico = _tecnico(uow, minutos_jornada=120)
    for hora, lat in ((9, "41.395000"), (11, "41.396000"), (13, "41.397000")):
        _con_cita(uow, tecnico, hora, lat, "2.175000")
    salida = campo.planificar_ruta(
        uow.db, uow.tenant_id, tecnico_id=tecnico.id, dia=date(2026, 10, 1)
    )
    assert salida["cabe_en_jornada"] is False
    assert salida["exceso_min"] > 0


# ── Partes y firma (CRM-04.04.01.06) ──────────────────────────────────────


def _lista(obligatorio: bool = True, resultado: str | None = None) -> list[dict[str, Any]]:
    return [
        {"clave": "estanqueidad", "texto": "Prueba de estanqueidad", "obligatorio": obligatorio}
        | ({"resultado": resultado} if resultado else {})
    ]


def test_un_checklist_obligatorio_sin_responder_no_cierra(uow: UnidadDeTrabajo) -> None:
    """Uno que se puede dejar a medias se deja a medias, y entonces no vale ni
    como control ni como prueba."""
    orden = _orden(uow)
    with pytest.raises(Conflicto) as error:
        campo.completar(uow, orden.id, checklist=_lista())
    assert "estanqueidad" in str(error.value.detalle)
    _, informe = campo.completar(uow, orden.id, checklist=_lista(), forzar=True)
    assert informe["forzado"] is True


def test_completar_escribe_el_historial_del_activo(uow: UnidadDeTrabajo) -> None:
    activo, _ = act.crear(uow, nombre="Cámara")
    orden = _orden(uow, activo_id=activo.id)
    campo.completar(uow, orden.id, resumen="Cambiada la junta")
    eventos = act.historial(uow.db, uow.tenant_id, activo.id)["eventos"]
    assert any(e["origen"] == "orden_trabajo" and "junta" in e["descripcion"] for e in eventos)


def test_la_firma_guarda_la_huella_de_lo_firmado(uow: UnidadDeTrabajo) -> None:
    """Una conformidad que no dice sobre qué se dio no sirve el día que se
    discute lo que se hizo."""
    orden = _orden(uow)
    campo.completar(uow, orden.id, resumen="Reparado", checklist=_lista(resultado="ok"))
    salida = campo.firmar(uow, orden.id, firmado_por="Cliente")
    assert salida["huella"]
    resumen = campo.resumen_orden(uow.db, uow.tenant_id, orden.id)
    assert resumen["parte"]["alterado_tras_firmar"] is False


def test_el_parte_firmado_no_se_modifica(uow: UnidadDeTrabajo) -> None:
    orden = _orden(uow)
    campo.completar(uow, orden.id, resumen="Reparado")
    campo.firmar(uow, orden.id, firmado_por="Cliente")
    with pytest.raises(Conflicto):
        campo.completar(uow, orden.id, resumen="Otra cosa")


def test_se_puede_firmar_no_conforme_con_motivo(uow: UnidadDeTrabajo) -> None:
    """Exigir conformidad para cerrar hace que firme el técnico, y entonces
    ninguna firma vale nada."""
    orden = _orden(uow)
    campo.completar(uow, orden.id, resumen="Reparado a medias")
    with pytest.raises(ErrorValidacion):
        campo.firmar(uow, orden.id, firmado_por="Cliente", conforme=False)
    salida = campo.firmar(
        uow, orden.id, firmado_por="Cliente", conforme=False, motivo_no_conforme="Sigue goteando"
    )
    assert salida["conforme"] is False


def test_no_se_cierra_sin_firma_salvo_forzando(uow: UnidadDeTrabajo) -> None:
    orden = _orden(uow)
    campo.completar(uow, orden.id, resumen="Hecho")
    with pytest.raises(Conflicto):
        campo.cerrar(uow, orden.id)
    assert campo.cerrar(uow, orden.id, forzar=True).estado == "cerrada"


# ── Preventivo (CRM-04.04.01.05) ──────────────────────────────────────────


def test_un_plan_sin_periodicidad_no_se_dispara_nunca(uow: UnidadDeTrabajo) -> None:
    activo, _ = act.crear(uow, nombre="Cámara")
    with pytest.raises(ErrorValidacion):
        campo.crear_plan(uow, nombre="Revisión", activo_id=activo.id)


def test_un_plan_puede_arrancar_cuando_se_instalo_la_maquina(uow: UnidadDeTrabajo) -> None:
    """`crear_plan` admitía `desde` y la API no lo dejaba poner.

    Con lo cual todo plan empezaba el día que se escribía y el primer
    preventivo caía a un ciclo entero vista. Al cargar un parque que lleva años
    funcionando eso es falso: la revisión semestral de una máquina instalada en
    2019 toca el mes que viene, no dentro de seis meses. Mientras tanto
    «próximos vencimientos» sale vacío y el servicio de campo parece sin uso.
    """
    from services.service.api_campo import CrearPlan

    activo, _ = act.crear(uow, nombre="Prensa de 2019")
    # **Por el modelo de la API y no llamando al servicio.** La primera versión
    # de esta prueba llamaba a `campo.crear_plan` directamente, y entonces
    # pasaba igual de verde con el campo quitado del contrato: la mitad que
    # faltaba era justo la puerta, y una prueba que la salta no la vigila. Es el
    # mismo descuido que dejó el mínimo de furgoneta sin forma de escribirse.
    datos = CrearPlan(
        nombre="Revisión semestral",
        activo_id=activo.id,
        cada_dias=180,
        antelacion_dias=15,
        desde=date.today() - timedelta(days=172),
    )
    plan = campo.crear_plan(uow, **datos.model_dump())
    # Ocho días vista, no seis meses.
    assert plan.proxima_fecha == date.today() + timedelta(days=8)
    claves = [v["plan_id"] for v in campo.vencimientos(uow.db, uow.tenant_id)["vencimientos"]]
    assert str(plan.id) in claves, "un plan que vence en ocho días tiene que salir"


def test_el_preventivo_vence_por_uso_aunque_la_fecha_no_llegue(
    uow: UnidadDeTrabajo,
) -> None:
    """Un plan que solo sabe de fechas revisa una máquina parada y deja pasar la
    que trabaja a tres turnos."""
    activo, _ = act.crear(uow, nombre="Cámara", contador=Decimal(0), unidad_contador="h")
    campo.crear_plan(
        uow,
        nombre="Revisión 500 h",
        activo_id=activo.id,
        cada_dias=365,
        cada_contador=Decimal(500),
    )
    act.leer_contador(uow, activo.id, valor=Decimal(600))
    salida = campo.vencimientos(uow.db, uow.tenant_id)
    assert len(salida["vencimientos"]) == 1
    assert salida["vencimientos"][0]["por_uso"] is True
    assert "por uso" in salida["vencimientos"][0]["porque"]


def test_un_plan_por_uso_sin_lectura_no_concluye(uow: UnidadDeTrabajo) -> None:
    """Callarlo haría creer que está al día."""
    activo, _ = act.crear(uow, nombre="Cámara")
    plan = campo.crear_plan(uow, nombre="Revisión", activo_id=activo.id, cada_contador=Decimal(500))
    salida = campo.vencimientos(uow.db, uow.tenant_id)
    assert salida["concluyente"] is False
    assert str(plan.id) in salida["planes_sin_lectura_de_contador"]


def test_no_se_generan_dos_ordenes_del_mismo_plan(uow: UnidadDeTrabajo) -> None:
    """Un plan mensual desatendido seis meses generaría seis órdenes idénticas, y
    lo que se hace entonces es cerrarlas todas sin mirar."""
    activo, _ = act.crear(uow, nombre="Cámara")
    campo.crear_plan(
        uow,
        nombre="Revisión mensual",
        activo_id=activo.id,
        cada_dias=30,
        desde=hoy(uow.db) - timedelta(days=60),
    )
    primera = campo.generar_preventivas(uow)
    segunda = campo.generar_preventivas(uow)
    assert len(primera["creadas"]) == 1
    assert segunda["creadas"] == []
    assert segunda["saltadas"][0]["porque"] == "ya tiene una orden abierta"


def test_el_preventivo_se_reprograma_desde_que_se_hizo(uow: UnidadDeTrabajo) -> None:
    """Contarlo desde que tocaba haría que la siguiente naciera vencida y el plan
    arrastrara el retraso para siempre."""
    activo, _ = act.crear(uow, nombre="Cámara")
    campo.crear_plan(
        uow,
        nombre="Revisión mensual",
        activo_id=activo.id,
        cada_dias=30,
        desde=hoy(uow.db) - timedelta(days=60),
    )
    creada = campo.generar_preventivas(uow)["creadas"][0]
    orden_id = UUID(creada)
    campo.completar(uow, orden_id, resumen="Revisión hecha")
    plan = campo.registrar_preventivo_hecho(uow, orden_id)
    assert plan is not None
    assert plan.proxima_fecha == hoy(uow.db) + timedelta(days=30)


def test_un_plan_de_un_activo_retirado_no_vence(uow: UnidadDeTrabajo) -> None:
    activo, _ = act.crear(uow, nombre="Cámara")
    campo.crear_plan(
        uow,
        nombre="Revisión",
        activo_id=activo.id,
        cada_dias=30,
        desde=hoy(uow.db) - timedelta(days=60),
    )
    act.cambiar_estado(uow, activo.id, estado="retirado", motivo="Baja")
    assert campo.vencimientos(uow.db, uow.tenant_id)["vencimientos"] == []


# ── Sincronización del móvil (CRM-04.04.01.03) ────────────────────────────


def test_reenviar_el_lote_no_duplica_nada(uow: UnidadDeTrabajo) -> None:
    """Sin idempotencia, el técnico que sincroniza dos veces consume la pieza dos
    veces."""
    tecnico = _tecnico(uow)
    repuesto = _repuesto(uow)
    campo.mover_repuesto(
        uow, tecnico_id=tecnico.id, repuesto_id=repuesto.id, tipo="carga", cantidad=Decimal(10)
    )
    orden = _orden(uow, competencias=["frigorista"])
    campo.asignar(uow, orden.id, tecnico_id=tecnico.id)
    lote = [
        {
            "id_cliente": "movil-1",
            "tipo": "linea",
            "orden_id": str(orden.id),
            "linea_tipo": "material",
            "repuesto_id": str(repuesto.id),
            "cantidad": "2",
        }
    ]
    primera = campo.sincronizar(uow, dispositivo="tablet-01", cambios=lote)
    segunda = campo.sincronizar(uow, dispositivo="tablet-01", cambios=lote)
    assert primera["resumen"]["aplicada"] == 1
    assert segunda["resumen"]["duplicada"] == 1

    saldo = uow.db.execute(
        campo.select(campo.StockFurgoneta).where(
            campo.StockFurgoneta.tecnico_id == tecnico.id,
            campo.StockFurgoneta.repuesto_id == repuesto.id,
        )
    ).scalar_one()
    assert Decimal(saldo.cantidad) == Decimal(8)


def test_un_cambio_sin_id_de_cliente_se_rechaza(uow: UnidadDeTrabajo) -> None:
    salida = campo.sincronizar(uow, dispositivo="tablet-01", cambios=[{"tipo": "linea"}])
    assert salida["resumen"]["rechazada"] == 1
    assert "id_cliente" in salida["resultados"][0]["porque"]


def test_el_conflicto_se_devuelve_y_no_se_resuelve_solo(uow: UnidadDeTrabajo) -> None:
    """Elegir automáticamente significa perder media jornada de alguien en
    silencio."""
    tecnico = _tecnico(uow)
    orden = _orden(uow, competencias=["frigorista"])
    campo.asignar(uow, orden.id, tecnico_id=tecnico.id)
    campo.completar(uow, orden.id, resumen="Hecho en oficina")

    salida = campo.sincronizar(
        uow,
        dispositivo="tablet-01",
        cambios=[
            {
                "id_cliente": "movil-2",
                "tipo": "completar",
                "orden_id": str(orden.id),
                "visto_en_estado": "asignada",
                "resumen": "Hecho en campo",
            }
        ],
    )
    assert salida["resumen"]["conflicto"] == 1
    assert salida["todo_aplicado"] is False


def test_un_cambio_malo_no_tumba_el_lote(uow: UnidadDeTrabajo) -> None:
    """El técnico trajo seis horas de trabajo; perder las cinco buenas por una
    mala es lo que hace que se deje de sincronizar."""
    tecnico = _tecnico(uow)
    orden = _orden(uow, competencias=["frigorista"])
    campo.asignar(uow, orden.id, tecnico_id=tecnico.id)
    salida = campo.sincronizar(
        uow,
        dispositivo="tablet-01",
        cambios=[
            {
                "id_cliente": "a",
                "tipo": "linea",
                "orden_id": str(orden.id),
                "linea_tipo": "material",
                "concepto": "Junta",
                "cantidad": "1",
            },
            {"id_cliente": "b", "tipo": "loquesea", "orden_id": str(orden.id)},
            {
                "id_cliente": "c",
                "tipo": "linea",
                "orden_id": str(orden.id),
                "linea_tipo": "otro",
                "concepto": "Limpieza",
            },
        ],
    )
    assert salida["resumen"]["aplicada"] == 2
    assert salida["resumen"]["rechazada"] == 1
    assert salida["todo_aplicado"] is False


def test_el_reloj_del_movil_se_guarda_aparte(uow: UnidadDeTrabajo) -> None:
    """Va mal —zona horaria, hora cambiada a mano— y aun así es el único que sabe
    cuándo se hizo el trabajo."""
    tecnico = _tecnico(uow)
    orden = _orden(uow, competencias=["frigorista"])
    campo.asignar(uow, orden.id, tecnico_id=tecnico.id)
    capturado = datetime(2026, 9, 30, 8, 30, tzinfo=timezone.utc)
    campo.sincronizar(
        uow,
        dispositivo="tablet-01",
        cambios=[
            {
                "id_cliente": "x",
                "tipo": "completar",
                "orden_id": str(orden.id),
                "resumen": "Hecho ayer sin cobertura",
                "capturado_at": capturado.isoformat(),
            }
        ],
    )
    fila = uow.db.execute(
        campo.select(campo.OperacionSincronizada).where(
            campo.OperacionSincronizada.id_cliente == "x"
        )
    ).scalar_one()
    assert fila.capturado_at is not None
    # Se compara el INSTANTE, no la representación: la base lo devuelve en la
    # zona del servidor y `replace(tzinfo=...)` desplazaría la hora en vez de
    # convertirla — que es cómo se cuelan los fallos de dos horas.
    assert fila.capturado_at.astimezone(timezone.utc) == capturado
    assert fila.recibido_at is not None

    recargada = uow.db.get(campo.OrdenTrabajo, orden.id)
    assert recargada is not None and recargada.completada_at is not None
    # El trabajo consta hecho cuando dijo el móvil, no cuando llegó la red.
    assert recargada.completada_at.astimezone(timezone.utc) == capturado


# ── El histórico del almacén móvil, que se escribía y no leía nadie ───────


def test_los_movimientos_de_almacen_se_pueden_LEER(uow: UnidadDeTrabajo, tenant_id: UUID) -> None:
    """Un almacén sin histórico no se puede cuadrar.

    El movimiento guardaba quién, qué, cuánto, por qué y si dejó la existencia
    en negativo — y ninguna ruta lo devolvía. Cuando falta una pieza, la
    pregunta es quién se la llevó y cuándo; sin esto la respuesta es «nadie lo
    sabe».

    Y los que **dejaron negativo** van contados aparte: es la señal de que el
    inventario y la realidad dejaron de coincidir, y a partir de ahí todo lo
    que se planifique con esas existencias se planifica sobre un número
    inventado.
    """
    from decimal import Decimal

    from services.service.campo import MovimientoRepuesto

    tecnico = uuid4()
    uow.db.add_all(
        [
            MovimientoRepuesto(
                tenant_id=tenant_id,
                tecnico_id=tecnico,
                repuesto_id=uuid4(),
                tipo="salida",
                cantidad=Decimal("2"),
                motivo="montada en la orden de ayer",
            ),
            MovimientoRepuesto(
                tenant_id=tenant_id,
                tecnico_id=tecnico,
                repuesto_id=uuid4(),
                tipo="salida",
                cantidad=Decimal("5"),
                motivo="no cuadraba el inventario",
                dejo_negativo=True,
            ),
        ]
    )
    uow.db.flush()

    historial = campo.movimientos_de_almacen(uow.db, tenant_id)
    assert historial["cuantos"] == 2
    assert historial["dejaron_negativo"] == 1
    # El motivo entero: es lo único que explica una salida sin orden de
    # trabajo, que es justo la que hay que justificar.
    assert any(m["motivo"] == "no cuadraba el inventario" for m in historial["movimientos"])

    # Y se pueden pedir sólo los que descuadraron, que es lo que se busca al
    # cuadrar el almacén.
    solo = campo.movimientos_de_almacen(uow.db, tenant_id, solo_negativos=True)
    assert solo["cuantos"] == 1


def test_sin_movimientos_no_se_dice_que_el_almacen_cuadra(
    uow: UnidadDeTrabajo, tenant_id: UUID
) -> None:
    """«Está cuadrado» y «aquí no hay registro» no son lo mismo."""
    historial = campo.movimientos_de_almacen(uow.db, tenant_id)
    assert historial["cuantos"] == 0
    assert historial["aviso"]
