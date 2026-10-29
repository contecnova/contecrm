"""Volumen, archivo frío y rastro de agregados, EJERCITADOS por HTTP
(CRM-08.01.01.04, CRM-00.05.04.06, CRM-00.04.03.08, CRM-00.05.03.03).

Dos módulos enteros **no los importaba nadie** y una capacidad estaba encendida
sin encender:

`crmcore.datos.particionado` resolvía qué tablas crecen, por qué se corta por
tiempo y no por tenant, cuántas particiones hay que crear por delante y qué fila
se puede mover a frío. Nueve funciones públicas, cero llamantes. La primera sonda
solo delataba seis, porque cuenta nombres y basta con que otro módulo tenga una
función que se llame igual.

El **rastro de agregados** estaba entero y apagado: la tabla de hechos se creaba
en dos servicios, `declarar_agregado` no la llamaba nadie, así que `anotar`
rechazaba cualquier hecho por «agregado no declarado» y la tabla estaba siempre
vacía. Un rastro vacío no da error: contesta lo mismo que si todo fuera bien.

Y la **exportación** traía las columnas de fábrica: `columnas_exportables` —que
añade los campos propios del tenant— no la llamaba ninguna ruta, porque no había
ruta de exportación en absoluto.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.fechas import hoy
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente() -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.sales.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            # Segundo factor recién superado. Va firmado con lo demás: las
            # operaciones sensibles —exportar en masa, borrar en bloque,
            # restaurar— lo exigen, y sin él una persona de verdad vería un
            # «vuelve a verificarte» en vez de la respuesta.
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


def _oportunidad(db: Any, tenant_id: UUID, nombre: str) -> Any:
    """Una oportunidad con su embudo: `pipeline_id` no admite nulo."""
    from services.sales.modelos import Etapa, Oportunidad, Pipeline

    pipeline = Pipeline(tenant_id=tenant_id, clave=f"p-{nombre}", nombre="Estándar")
    db.add(pipeline)
    db.flush()
    etapa = Etapa(
        tenant_id=tenant_id, pipeline_id=pipeline.id, clave="inicio", nombre="Inicio", orden=1
    )
    db.add(etapa)
    db.flush()
    fila = Oportunidad(
        tenant_id=tenant_id,
        nombre=nombre,
        estado="abierta",
        importe=1000,
        pipeline_id=pipeline.id,
        etapa_id=etapa.id,
    )
    db.add(fila)
    db.flush()
    return fila


# ── Particionado (CRM-08.01.01.04) ────────────────────────────────────────


def test_no_se_particiona_lo_que_no_crece(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Trocear una tabla de cincuenta mil filas la hace más lenta, no más rápida."""
    r = cliente.get(
        "/api/v1/sales/volumen/plan-de-particion?tabla=plantillas_correo", headers=cabeceras
    )
    assert r.status_code == 422, r.text
    assert r.json()["error_code"] == "particion.tabla_no_procede"

    ok = cliente.get(
        "/api/v1/sales/volumen/plan-de-particion?tabla=actividades&estrategia=mes",
        headers=cabeceras,
    )
    assert ok.status_code == 200, ok.text
    # Una sola forma, también al pedir una tabla: dos formas según los
    # parámetros obligan a ramificar a quien lo lee, y la rama que menos se usa
    # es la que se queda sin probar.
    plan = ok.json()["tablas"][0]
    assert plan["estrategia"] == "mes"
    # El aislamiento no cambia: cambia cómo se guarda, no quién ve qué.
    assert plan["indice_por_tenant"] is True


def test_sin_tabla_salen_todas_las_que_crecen(cliente: Any, cabeceras: dict[str, str]) -> None:
    """`tabla` era obligatoria, y eso dejaba la ruta sin puerta posible.

    Para pedirla había que saber ya cuáles son las tablas de alto volumen, y esa
    lista solo existía dentro del núcleo: la única forma de sacarla era pedir una
    tabla mala y leerla del detalle del error. Quien administra la base no quiere
    elegir una de cinco, quiere ver las cinco.
    """
    from crmcore.datos.particionado import DE_ALTO_VOLUMEN

    r = cliente.get("/api/v1/sales/volumen/plan-de-particion", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["cuantas"] == len(DE_ALTO_VOLUMEN)
    assert {t["tabla"] for t in cuerpo["tablas"]} == set(DE_ALTO_VOLUMEN)
    # Y cada una dice POR QUÉ crece: sin eso, la lista es un inventario y no
    # una explicación de por qué sólo se parten éstas.
    assert all(t["por_que_crece"] for t in cuerpo["tablas"])
    assert "más lenta" in cuerpo["porque_solo_estas"]


def test_particionar_por_tenant_no_es_una_opcion(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Con dos mil tenants el planificador tarda más en decidir que en ejecutar."""
    r = cliente.get(
        "/api/v1/sales/volumen/plan-de-particion?tabla=actividades&estrategia=tenant",
        headers=cabeceras,
    )
    assert r.status_code == 422, r.text
    assert r.json()["error_code"] == "particion.estrategia_invalida"
    assert "dos mil particiones" in r.json()["detalle"]["por_que_no_por_tenant"]


def test_las_particiones_se_crean_por_delante(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    """Crearla cuando llega la primera fila del mes es crearla a las 00:00 del
    día 1, dentro de la transacción de un usuario y con un bloqueo de tabla."""
    atrasada = (hoy(db).replace(day=1) - timedelta(days=90)).isoformat()
    r = cliente.get(
        f"/api/v1/sales/volumen/particiones-a-crear?ultima_existente={atrasada}"
        "&meses_por_delante=3",
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert len(salida["faltan"]) >= 4
    # La primera que falta es la del MES EN CURSO. Con la última partición
    # creada hace tres meses, la de hoy no existe: no es un aviso, es un
    # incidente ocurriendo. La versión anterior no podía decirlo —excluía el mes
    # en curso del recorrido, así que «urgente» era inalcanzable—.
    assert salida["faltan"][0] == hoy(db).isoformat()[:7]
    assert salida["ya_falta_la_de_este_mes"] is True
    assert salida["urgente"] is True


def test_el_aviso_de_volumen_va_por_ritmo_y_no_por_tamano(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Cien millones estables no molestan; diez que doblan cada trimestre son un
    incidente dentro de nueve meses."""
    r = cliente.post(
        "/api/v1/sales/volumen/salud",
        headers=cabeceras,
        json={
            "tablas": [
                {
                    "nombre": "estable",
                    "filas": 40_000_000,
                    "crecimiento_mensual_pct": 0.1,
                    "particionada": False,
                },
                {
                    "nombre": "disparada",
                    "filas": 10_000_000,
                    "crecimiento_mensual_pct": 30,
                    "particionada": False,
                },
            ]
        },
    )
    assert r.status_code == 200, r.text
    avisados = [a["tabla"] for a in r.json()["avisos"]]
    assert avisados == ["disparada"]


def test_sin_datos_de_volumen_no_se_dice_que_todo_este_bien(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    r = cliente.post("/api/v1/sales/volumen/salud", headers=cabeceras, json={"tablas": []})
    assert r.status_code == 200, r.text
    assert r.json()["medible"] is False
    assert "no se puede anticipar nada" in r.json()["que_significa"]


# ── Archivo frío y retenciones ────────────────────────────────────────────


def test_lo_que_esta_en_litigio_no_se_mueve_a_frio(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    """Moverlo sería cumplir el plazo de retención por accidente y romper otra
    obligación a la vez — y la que se rompe suele ser la cara."""
    vieja = (hoy(db) - timedelta(days=5 * 365)).isoformat()
    r = cliente.post(
        "/api/v1/sales/volumen/archivar",
        headers=cabeceras,
        json={
            "destino": "s3://frio/ventas",
            "filas": [
                {"id": "A", "fecha": vieja},
                {"id": "B", "fecha": vieja, "litigio": True},
            ],
        },
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["se_mueven"] == 1
    assert salida["se_quedan"] == 1
    # Y se dice CUÁL se queda y por qué: un recuento obliga a adivinarlo.
    assert salida["detalle_de_los_que_se_quedan"][0]["id"] == "B"
    # Archivar no borra nada.
    assert salida["se_borra_algo"] is False
    assert salida["sigue_consultable"] is True


def test_archivar_sin_decir_a_donde_es_borrar_con_otro_nombre(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    r = cliente.post(
        "/api/v1/sales/volumen/archivar",
        headers=cabeceras,
        json={"destino": "   ", "filas": []},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error_code"] == "archivado.sin_destino"


def test_no_se_borra_de_la_tabla_viva_lo_retenido(cliente: Any, cabeceras: dict[str, str]) -> None:
    """El borrado es el paso que no tiene vuelta atrás, y se comprueba antes."""
    r = cliente.post(
        "/api/v1/sales/volumen/puede-borrarse",
        headers=cabeceras,
        json={
            "destino": "s3://frio/ventas",
            "filas": [{"id": "A"}, {"id": "B", "obligacion_legal": True}],
        },
    )
    assert r.status_code == 403, r.text
    assert r.json()["error_code"] == "archivado.retenido"
    assert r.json()["detalle"]["retenciones"] == ["obligacion_legal"]


# ── Las purgas que no distinguen por registro ─────────────────────────────


def test_la_purga_del_rastro_se_abstiene_con_un_bloqueo_activo(db: Any, tenant_id: UUID) -> None:
    """Una purga nocturna que borra el rastro durante un litigio no da ningún
    error: lo que se descubre semanas después es que la prueba que pedía el
    juzgado la borró un proceso automático."""
    from crmcore.datos.retencion import bloquear
    from crmcore.seguridad import siem

    sin_bloqueo = siem.purgar(db, tenant_id, dias_retencion=30)
    assert "abstenida" not in sin_bloqueo

    bloquear(db, tenant_id=tenant_id, motivo="Pleito con el cliente X")
    db.flush()

    con_bloqueo = siem.purgar(db, tenant_id, dias_retencion=30)
    assert con_bloqueo["abstenida"] is True
    assert con_bloqueo["borrados"] == 0


def test_la_purga_de_adjuntos_se_abstiene_con_un_bloqueo_activo(db: Any, tenant_id: UUID) -> None:
    """Un adjunto borrado es recuperable mientras sus bytes sigan en el almacén;
    en cuanto esta purga pasa, deja de serlo.

    Se planta un huérfano **de verdad**. Con la base vacía, la purga devuelve
    cero tanto si se abstiene como si no, y la prueba no distinguiría lo uno de
    lo otro: diría que el bloqueo funciona sin haberlo ejercido.
    """
    from datetime import datetime, timezone

    from crmcore.almacen import get_almacen
    from crmcore.datos import adjuntos
    from crmcore.datos.retencion import bloquear

    almacen = get_almacen()
    uri = almacen.guardar(f"pruebas/{uuid4()}.txt", b"bytes de prueba")
    db.add(
        adjuntos.Adjunto(
            tenant_id=tenant_id,
            objeto_tipo="oportunidad",
            objeto_id=uuid4(),
            nombre="contrato.txt",
            extension="txt",
            sha256="0" * 64,
            uri=uri,
            tamano=15,
            deleted_at=datetime.now(timezone.utc),
        )
    )
    db.flush()

    bloquear(db, tenant_id=tenant_id, motivo="Inspección en curso")
    db.flush()

    # Con el bloqueo activo no se toca nada...
    assert adjuntos.purgar_huerfanos(db, tenant_id) == 0
    assert almacen.existe(uri) is True


# ── Rastro de agregados (CRM-00.05.04.06) ─────────────────────────────────


def test_el_historial_de_campos_se_puede_leer_y_dice_de_donde_vino(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """**Se escribía y no lo leía nadie.**

    Cada edición anota el campo, el valor anterior, el nuevo, quién lo hizo y
    **desde dónde** —la pantalla, la API o una automatización—, y ninguna ruta
    lo devolvía. La pregunta que contesta es la primera de cualquier discusión
    sobre un registro: «esto antes no decía esto».

    El origen es la mitad que casi nunca se guarda y la que zanja la
    discusión: no es lo mismo que lo cambiara una persona a que lo pisara una
    sincronización todas las noches.
    """
    from crmcore.audit.chain import registrar_cambios

    objeto_id = uuid4()
    registrar_cambios(
        db,
        objeto="oportunidad",
        objeto_id=objeto_id,
        anterior={"importe": "1000", "etapa": "analisis"},
        nuevo={"importe": "2500", "etapa": "analisis"},
        tenant_id=tenant_id,
    )
    db.flush()

    r = cliente.get(f"/api/v1/sales/rastro/campos/oportunidad/{objeto_id}", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    cambios = {c["campo"]: c for c in cuerpo["cambios"]}
    # Solo lo que de verdad cambió: anotar los cincuenta campos cada vez que
    # alguien corrige uno hace el historial ilegible, que es la forma habitual
    # de que estos historiales acaben sin usarse.
    assert set(cambios) == {"importe"}
    assert cambios["importe"]["valor_anterior"] == "1000"
    assert cambios["importe"]["valor_nuevo"] == "2500"
    assert "origen" in cambios["importe"]

    # No hay prueba de que la ruta genérica no tape a ésta, y es a propósito:
    # se escribió, se validó plantando el caso malo —declarando `/campos/…`
    # después de `/{objeto}/{objeto_id}`— y **pasó igual**. No puede fallar:
    # `/campos/{objeto}/{objeto_id}` tiene tres tramos y `/{objeto}/{objeto_id}`
    # dos, así que no compiten. Una comprobación que no puede ponerse roja no
    # vigila nada y da por cubierto lo que no mira.


def test_un_historial_vacio_distingue_sin_cambios_de_sin_anotarlos(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Son dos cosas distintas y con la lista vacía se ven igual.

    El rastro campo a campo lo escribe quien pasa por `registrar_cambios`, y no
    todos los servicios lo hacen: en los que no, esta ruta contestaría vacío
    para siempre y quien la mira concluiría que el registro no se ha tocado.
    """
    r = cliente.get(f"/api/v1/sales/rastro/campos/oportunidad/{uuid4()}", headers=cabeceras)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["cambios"] == []
    # Dice CUÁL de las dos cosas es, no «no hay nada». Se comprueba que el
    # texto nombre exactamente una de las dos, no que diga algo: un mensaje
    # genérico volvería a dejar las dos indistinguibles con otras palabras.
    dice = cuerpo["que_significa"]
    este_registro = "no se ha tocado por una vía que lo anote" in dice
    este_servicio = "ningún cambio de campo de ningún registro" in dice
    assert este_registro != este_servicio, (
        "El vacío tiene que decir si es que ESTE registro no se ha tocado o si "
        f"es que este servicio no lleva ese histórico. Dice: «{dice}»"
    )


def test_se_dice_que_agregados_tienen_el_rastro_encendido(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Y con el motivo: dentro de dos años alguien mirará por qué esta tabla
    ocupa lo que ocupa."""
    r = cliente.get("/api/v1/sales/rastro", headers=cabeceras)
    assert r.status_code == 200, r.text
    agregados = r.json()["agregados"]
    assert "oportunidad" in agregados
    assert agregados["oportunidad"].strip()


def test_un_agregado_apagado_lo_dice_en_vez_de_contestar_vacio(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    """Un rastro vacío contesta lo mismo que si todo fuera bien."""
    r = cliente.get(f"/api/v1/sales/rastro/lead/{uuid4()}", headers=cabeceras)
    assert r.status_code == 404, r.text
    assert r.json()["error_code"] == "rastro.agregado_no_declarado"


def test_cada_cambio_de_estado_deja_su_hecho(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Sin esto la tabla de hechos se creaba en dos servicios y estaba siempre
    vacía: `declarar_agregado` no la llamaba nadie."""
    from crmcore.datos.estados import aplicar

    oportunidad = _oportunidad(db, tenant_id, "Reforma")

    aplicar(db, oportunidad, objeto="oportunidad", nuevo="ganada")
    db.flush()

    r = cliente.get(f"/api/v1/sales/rastro/oportunidad/{oportunidad.id}", headers=cabeceras)
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["hechos"] == 1
    assert salida["estado"] == {"estado": "ganada"}


def test_se_detecta_que_alguien_escribio_sin_pasar_por_aqui(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Un script de corrección, una migración, un arreglo a mano un viernes. A
    partir de ahí el rastro deja de ser una prueba y nadie se entera."""
    from crmcore.datos.estados import aplicar

    oportunidad = _oportunidad(db, tenant_id, "Ampliación")
    aplicar(db, oportunidad, objeto="oportunidad", nuevo="ganada")
    db.flush()

    cuadra = cliente.get(
        f"/api/v1/sales/rastro/oportunidad/{oportunidad.id}/cuadra", headers=cabeceras
    )
    assert cuadra.status_code == 200, cuadra.text
    assert cuadra.json()["cuadra"] is True

    # Y ahora el arreglo a mano del viernes: se escribe en la tabla sin pasar
    # por la transición.
    oportunidad.estado = "perdida"
    db.flush()

    despues = cliente.get(
        f"/api/v1/sales/rastro/oportunidad/{oportunidad.id}/cuadra", headers=cabeceras
    )
    assert despues.status_code == 200, despues.text
    salida = despues.json()
    assert salida["cuadra"] is False
    assert [d["campo"] for d in salida["diferencias"]] == ["estado"]


# ── Exportación con los campos del tenant (CRM-00.04.03.08, CRM-00.05.03.03) ─


def test_la_exportacion_trae_los_campos_propios_del_tenant(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Sin esto trae lo que traía el producto de fábrica, no lo que el cliente ve
    en su ficha: una diferencia que solo nota quien conoce el dato, y la nota
    cuando ya ha mandado el fichero."""
    from crmcore.metamodelo import EsquemaTenant

    db.add(
        EsquemaTenant(
            tenant_id=tenant_id,
            objeto="oportunidad",
            campos=[
                {"nombre": "num_expediente", "tipo": "texto", "activo": True},
                {"nombre": "retirado", "tipo": "texto", "activo": False},
            ],
        )
    )
    oportunidad = _oportunidad(db, tenant_id, "Con expediente")
    oportunidad.campos = {"num_expediente": "EXP-99"}
    db.flush()

    r = cliente.get("/api/v1/opportunities/exportar", headers=cabeceras)
    assert r.status_code == 200, r.text
    salida = r.json()

    assert "num_expediente" in salida["columnas"]
    # Un campo dado de baja no se exporta: la columna existiría vacía y se leería
    # como «no hay dato» en vez de «ya no se usa».
    assert "retirado" not in salida["columnas"]
    assert "nombre" in salida["columnas"]

    fila = next(f for f in salida["filas"] if f.get("nombre") == "Con expediente")
    assert fila["num_expediente"] == "EXP-99"
    # Y se dice si el fichero viene cortado: uno truncado en silencio es el que
    # alguien manda creyendo que lleva todo.
    assert salida["truncado"] is False


def test_la_exportacion_no_saca_lo_que_la_ficha_tapa(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Un CSV que enseña lo que la pantalla oculta es la vía más fácil de
    saltarse la protección, y la más silenciosa.

    Se prueba con un **secreto declarado**, que es el caso que no depende de
    roles ni de configuración: `secreto_hash` es una columna del modelo y la
    proyección no la devuelve a nadie. Si la exportación leyera los atributos
    por su cuenta, saldría — y saldría para cualquiera con permiso de lectura.
    """
    from services.sales.captura import CanalCaptura

    db.add(
        CanalCaptura(
            tenant_id=tenant_id,
            clave="web",
            nombre="Formulario de la web",
            secreto_hash="a" * 64,
        )
    )
    db.flush()

    r = cliente.get("/api/v1/captura/canales/exportar", headers=cabeceras)
    assert r.status_code == 200, r.text
    salida = r.json()

    fila = next(f for f in salida["filas"] if f.get("clave") == "web")
    assert fila["nombre"] == "Formulario de la web"
    # La columna existe en el modelo y NO sale por la API, para nadie.
    assert "secreto_hash" in {c.name for c in CanalCaptura.__table__.columns}
    assert "secreto_hash" not in fila


def _principal(cabeceras: dict[str, str], tenant_id: UUID) -> Any:
    from crmcore.http.deps import Principal

    return Principal(
        id=uuid4(),
        tenant_id=tenant_id,
        permisos=frozenset({"*:*"}),
        roles=frozenset({"admin"}),
    )


def test_toda_coleccion_que_se_lista_se_puede_exportar() -> None:
    """La exportación no puede quedarse en las colecciones secundarias.

    `montar_listado` la monta sola, y **once colecciones no se montan con él**:
    cuentas, contactos, actividades, leads y oportunidades tienen su listado
    escrito a mano. Montarla solo ahí habría dado exportación en las sesenta que
    nadie exporta y ninguna en las cinco que se exportan de verdad — el arreglo
    que no cierra la familia.
    """
    import importlib

    # Las dos que no son colecciones, con su motivo.
    NO_SON_COLECCION = {
        "/api/v1/proveedores": (
            "Es la vista del portal del propio proveedor sobre su ficha, no un "
            "maestro: lo que hay detrás son cuentas, y esas sí se exportan."
        ),
        "/api/v1/tenants": (
            "Lo que lista son cosas DE un tenant —sus exportaciones, sus "
            "certificados—, no una colección raíz."
        ),
    }

    sin_exportar = []
    mirados = 0
    for servicio in (
        "sales",
        "party",
        "service",
        "marketing",
        "metadata",
        "tenancy",
        "identity",
        "analytics",
        "automation",
        "integration",
        "intelligence",
        "eventing",
        "orchestrator",
    ):
        modulo = importlib.import_module(f"services.{servicio}.main")
        rutas = modulo.app.openapi()["paths"]
        exportan = {p[: -len("/exportar")] for p in rutas if p.endswith("/exportar")}
        for ruta, operaciones in rutas.items():
            resumen = str((operaciones.get("get") or {}).get("summary", "")).lower()
            if not resumen.startswith("listar"):
                continue
            mirados += 1
            if ruta not in exportan and ruta not in NO_SON_COLECCION:
                sin_exportar.append(ruta)

    # Que diga cuántas ha mirado: una comprobación que no mira parece verde, y
    # ya pasó en este repositorio — un cero que significaba «no se ha mirado».
    assert mirados > 50, f"solo se han mirado {mirados} listados: el recorrido no mira"
    assert not sin_exportar, (
        "Estas colecciones se listan y no se pueden exportar:\n  "
        + "\n  ".join(sin_exportar)
        + "\n\nO se les monta `montar_exportacion`, o entran en NO_SON_COLECCION "
        "diciendo por qué no lo son."
    )
