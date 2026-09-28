"""Baja de un tenant: exportación verificable y destrucción certificada.

Cubre CRM-00.01.03.05 (offboarding con exportación completa verificable y
certificado de destrucción) y CRM-08.02.01.05 (portabilidad en formato abierto).

Lo que estas pruebas defienden es el **orden**: exportar, verificar, esperar,
destruir. Cada una de las tres condiciones que bloquean la destrucción está aquí
porque saltársela convierte un error administrativo en una pérdida irreversible.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import Conflicto, ErrorValidacion

from services.tenancy import baja
from services.tenancy.modelos import Plan, Tenant, UnidadNegocio

# Su fallo llega a producción y no se arregla después: una fuga entre tenants o
# una ruta publicada que no responde. Por eso esta prueba NO sale del push.
pytestmark = pytest.mark.despliegue


@pytest.fixture(autouse=True)
def almacen_temporal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    import os

    from crmcore.almacen import reset_almacen
    from crmcore.cache import reset_cache
    from crmcore.config import limpiar_cache_settings

    monkeypatch.setitem(os.environ, "STORAGE_LOCAL_PATH", str(tmp_path / "almacen"))
    limpiar_cache_settings()
    reset_almacen()
    reset_cache()
    yield
    reset_almacen()
    reset_cache()
    limpiar_cache_settings()


def _tenant(db: Any, tenant_id: UUID, estado: str = "activo", **extra: Any) -> Tenant:
    # Un plan por prueba, no por tenant: el código es único y una prueba con dos
    # tenants intentaría crearlo dos veces.
    from sqlalchemy import select as _select

    if db.execute(_select(Plan).where(Plan.codigo == "p")).scalar_one_or_none() is None:
        db.add(Plan(codigo="p", nombre="Plan"))
        db.flush()
    # `Tenant` no lleva `tenant_id`: ES el tenant, y una columna apuntando a sí
    # misma no aislaría nada.
    t = Tenant(
        id=tenant_id,
        # El slug lleva el UUID ENTERO: los UUIDv7 empiezan por la marca de
        # tiempo, así que dos generados en el mismo milisegundo comparten los
        # primeros caracteres y truncarlos no da unicidad.
        slug=f"cliente-{tenant_id}",
        nombre="Cliente",
        estado=estado,
        **extra,
    )
    db.add(t)
    db.flush()
    return t


def _con_datos(db: Any, tenant_id: UUID, n: int = 3) -> None:
    for i in range(n):
        db.add(UnidadNegocio(tenant_id=tenant_id, codigo=f"bu{i}", nombre=f"Unidad {i}"))
    db.flush()


# ── Exportación ───────────────────────────────────────────────────────────


def test_la_exportacion_escribe_manifiesto_con_hash_por_fichero(db: Any, tenant_id: UUID) -> None:
    _tenant(db, tenant_id)
    _con_datos(db, tenant_id)

    exp = baja.exportar(db, tenant_id=tenant_id, tablas={"unidades_negocio": UnidadNegocio})

    assert exp.estado == "completa"
    assert exp.total_filas == 3
    assert exp.manifiesto["unidades_negocio"]["filas"] == 3
    assert len(exp.manifiesto["unidades_negocio"]["sha256"]) == 64
    assert exp.sha256


def test_la_exportacion_es_json_lines_legible_sin_este_producto(db: Any, tenant_id: UUID) -> None:
    """Un volcado en formato propietario no es portabilidad: es un rehén con
    otro nombre."""
    import json

    from crmcore.almacen import get_almacen

    _tenant(db, tenant_id)
    _con_datos(db, tenant_id, 2)
    exp = baja.exportar(db, tenant_id=tenant_id, tablas={"unidades_negocio": UnidadNegocio})

    crudo = (
        get_almacen()
        .leer(get_almacen().uri_de(f"{tenant_id}/_exportaciones/{exp.id}/unidades_negocio.jsonl"))
        .decode("utf-8")
    )
    filas = [json.loads(linea) for linea in crudo.strip().split("\n")]

    assert len(filas) == 2
    assert {"codigo", "nombre", "tenant_id"} <= set(filas[0])


def test_la_exportacion_trae_un_leeme_que_explica_como_comprobarla(
    db: Any, tenant_id: UUID
) -> None:
    from crmcore.almacen import get_almacen

    _tenant(db, tenant_id)
    exp = baja.exportar(db, tenant_id=tenant_id, tablas={"unidades_negocio": UnidadNegocio})

    leeme = (
        get_almacen()
        .leer(get_almacen().uri_de(f"{tenant_id}/_exportaciones/{exp.id}/LEEME.md"))
        .decode("utf-8")
    )
    assert "SHA-256" in leeme and "JSON Lines" in leeme


def test_el_hash_del_manifiesto_no_depende_del_orden(db: Any, tenant_id: UUID) -> None:
    """Si dependiera del orden de inserción, el mismo contenido daría hashes
    distintos en dos ejecuciones y la verificación no probaría nada."""
    import hashlib
    import json

    manifiesto = {"b": {"sha256": "2"}, "a": {"sha256": "1"}}
    uno = hashlib.sha256(
        json.dumps(manifiesto, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    otro = hashlib.sha256(
        json.dumps(
            dict(reversed(list(manifiesto.items()))), sort_keys=True, ensure_ascii=False
        ).encode()
    ).hexdigest()
    assert uno == otro


def test_verificar_relee_del_almacen_y_detecta_un_fichero_alterado(
    db: Any, tenant_id: UUID
) -> None:
    """Un fallo de escritura silencioso —disco lleno, objeto truncado— solo se ve
    leyendo de vuelta. Y es justo antes de destruir cuando hay que saberlo."""
    from crmcore.almacen import get_almacen

    _tenant(db, tenant_id)
    _con_datos(db, tenant_id)
    exp = baja.exportar(db, tenant_id=tenant_id, tablas={"unidades_negocio": UnidadNegocio})
    assert baja.verificar(db, exp.id).estado == "verificada"

    get_almacen().guardar(f"{tenant_id}/_exportaciones/{exp.id}/unidades_negocio.jsonl", b"roto")

    assert baja.verificar(db, exp.id).estado == "fallida"


def test_verificar_detecta_un_fichero_que_ya_no_esta(db: Any, tenant_id: UUID) -> None:
    from crmcore.almacen import get_almacen

    _tenant(db, tenant_id)
    exp = baja.exportar(db, tenant_id=tenant_id, tablas={"unidades_negocio": UnidadNegocio})
    get_almacen().borrar(
        get_almacen().uri_de(f"{tenant_id}/_exportaciones/{exp.id}/unidades_negocio.jsonl")
    )

    resultado = baja.verificar(db, exp.id)
    assert resultado.estado == "fallida"
    assert "unidades_negocio" in (resultado.error or "")


# ── Destrucción ───────────────────────────────────────────────────────────


def _listo_para_destruir(db: Any, tenant_id: UUID) -> tuple[Tenant, baja.Exportacion]:
    t = _tenant(
        db,
        tenant_id,
        estado="en_baja",
        datos_borrables_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    _con_datos(db, tenant_id)
    exp = baja.exportar(
        db, tenant_id=tenant_id, tablas={"unidades_negocio": UnidadNegocio}, motivo="baja"
    )
    baja.verificar(db, exp.id)
    return t, exp


def test_no_se_destruye_un_tenant_que_no_esta_en_baja(db: Any, tenant_id: UUID) -> None:
    """Destruir los datos de un tenant activo no es mantenimiento: es un incidente."""
    t = _tenant(db, tenant_id, estado="activo")
    exp = baja.exportar(db, tenant_id=tenant_id, tablas={})
    baja.verificar(db, exp.id)

    with pytest.raises(Conflicto) as exc:
        baja.destruir(db, tenant=t, exportacion_id=exp.id)
    assert exc.value.error_code == "tenant.no_esta_en_baja"


def test_no_se_destruye_durante_la_ventana_de_recuperacion(db: Any, tenant_id: UUID) -> None:
    """Es la que convierte un error administrativo en algo reparable."""
    t = _tenant(
        db,
        tenant_id,
        estado="en_baja",
        datos_borrables_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    exp = baja.exportar(db, tenant_id=tenant_id, tablas={})
    baja.verificar(db, exp.id)

    with pytest.raises(Conflicto) as exc:
        baja.destruir(db, tenant=t, exportacion_id=exp.id)
    assert exc.value.error_code == "tenant.ventana_de_recuperacion"


def test_no_se_destruye_sin_exportacion(db: Any, tenant_id: UUID) -> None:
    t = _tenant(
        db,
        tenant_id,
        estado="en_baja",
        datos_borrables_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    with pytest.raises(ErrorValidacion) as exc:
        baja.destruir(db, tenant=t, exportacion_id=None)
    assert exc.value.error_code == "tenant.sin_exportacion"


def test_no_se_destruye_con_una_exportacion_solo_completa(db: Any, tenant_id: UUID) -> None:
    """«Completa» significa que se escribió; «verificada», que se ha comprobado
    que está ahí. Destruir con la primera es destruir a ciegas."""
    t = _tenant(
        db,
        tenant_id,
        estado="en_baja",
        datos_borrables_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    exp = baja.exportar(db, tenant_id=tenant_id, tablas={})

    with pytest.raises(Conflicto) as exc:
        baja.destruir(db, tenant=t, exportacion_id=exp.id)
    assert exc.value.error_code == "tenant.exportacion_sin_verificar"


def test_no_se_destruye_con_la_exportacion_de_otro_tenant(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    t, _ = _listo_para_destruir(db, tenant_id)
    _tenant(db, otro_tenant_id)
    ajena = baja.exportar(db, tenant_id=otro_tenant_id, tablas={})
    baja.verificar(db, ajena.id)

    with pytest.raises(ErrorValidacion):
        baja.destruir(db, tenant=t, exportacion_id=ajena.id)


def test_destruir_borra_los_ficheros_y_emite_certificado(db: Any, tenant_id: UUID) -> None:
    from crmcore.datos import adjuntos as adj

    t, exp = _listo_para_destruir(db, tenant_id)
    adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre="contrato.pdf",
        datos=b"del cliente que se va",
    )

    certificado = baja.destruir(db, tenant=t, exportacion_id=exp.id, por=uuid4())

    assert certificado.alcance["ficheros_borrados"] >= 1
    assert certificado.alcance["cache_purgada"] is True
    assert certificado.exportacion_sha256 == exp.sha256
    assert len(certificado.hash) == 64


def test_la_destruccion_purga_la_cache_del_tenant(db: Any, tenant_id: UUID) -> None:
    from crmcore.cache.base import fijar, obtener

    t, exp = _listo_para_destruir(db, tenant_id)
    fijar("conteo", "cuentas", valor=99, tenant_id=tenant_id)

    baja.destruir(db, tenant=t, exportacion_id=exp.id)

    assert obtener("conteo", "cuentas", tenant_id=tenant_id) is None


def test_la_destruccion_no_toca_los_ficheros_de_otro_tenant(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    from crmcore.almacen import get_almacen
    from crmcore.datos import adjuntos as adj

    t, exp = _listo_para_destruir(db, tenant_id)
    ajeno = adj.subir(
        db,
        tenant_id=otro_tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre="suyo.pdf",
        datos=b"de otro cliente",
    )

    baja.destruir(db, tenant=t, exportacion_id=exp.id)

    assert get_almacen().existe(ajeno.uri)


def test_los_certificados_se_encadenan(db: Any, tenant_id: UUID, otro_tenant_id: UUID) -> None:
    """Un certificado que se pudiera editar después no probaría nada."""
    t1, e1 = _listo_para_destruir(db, tenant_id)
    c1 = baja.destruir(db, tenant=t1, exportacion_id=e1.id)

    t2 = _tenant(
        db,
        otro_tenant_id,
        estado="en_baja",
        datos_borrables_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    e2 = baja.exportar(db, tenant_id=otro_tenant_id, tablas={})
    baja.verificar(db, e2.id)
    c2 = baja.destruir(db, tenant=t2, exportacion_id=e2.id)

    assert c1.hash_previo == "0" * 64
    assert c2.hash_previo == c1.hash


def test_el_certificado_sobrevive_a_los_datos(db: Any, tenant_id: UUID) -> None:
    """Un cliente que pregunta dos años después «¿seguís teniendo mis datos?»
    necesita una respuesta que no sea «creemos que no»."""
    from sqlalchemy import select

    t, exp = _listo_para_destruir(db, tenant_id)
    baja.destruir(db, tenant=t, exportacion_id=exp.id)
    db.flush()

    guardados = (
        db.execute(
            select(baja.CertificadoDestruccion).where(
                baja.CertificadoDestruccion.tenant_id == tenant_id
            )
        )
        .scalars()
        .all()
    )
    assert len(guardados) == 1
    assert guardados[0].tenant_slug == t.slug


# ── Lo que el certificado NO destruye (RT-5) ──────────────────────────────


def _despliegue(monkeypatch: Any, *servicios: str) -> None:
    """Declara qué servicios tiene este despliegue.

    Sale de `RUTAS_SERVICIOS`, que es un `Settings` con caché: cambiar la
    variable sin vaciarla dejaba la prueba mirando la lista del proceso, y
    pasaba por casualidad.
    """
    from crmcore.config import limpiar_cache_settings

    monkeypatch.setenv("RUTAS_SERVICIOS", ",".join(f"{s}=http://{s}:8000" for s in servicios))
    limpiar_cache_settings()


def _reporte(
    db: Any, tenant_id: UUID, servicio: str, documentos: list[Any], nota: str = ""
) -> None:
    db.add(
        baja.ReporteInventarioDocumental(
            tenant_id=tenant_id,
            servicio=servicio,
            documentos=documentos,
            total=len(documentos),
            nota=nota,
        )
    )
    db.flush()


def test_el_certificado_recoge_los_documentos_de_todos_los_servicios(
    db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    """`documentos_enlazados` vive en el esquema de cada servicio.

    Mirar solo el propio daba «0 documentos fuera» mientras los contratos
    seguían en el gestor, enlazados desde `party` — y el cliente se quedaba
    creyendo que ya no existían.
    """
    _despliegue(monkeypatch, "tenancy", "party")
    _reporte(db, tenant_id, "party", [{"documento_id": "d-1", "sistema": "contecmind"}])
    t, exp = _listo_para_destruir(db, tenant_id)

    cert = baja.destruir(db, tenant=t, exportacion_id=exp.id)

    fuera = cert.alcance["fuera_de_este_certificado"]
    assert fuera["total"] == 1
    assert fuera["documentos"][0]["servicio"] == "party"
    assert fuera["completo"] is True


def test_el_certificado_dice_quien_no_ha_contestado(
    db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    """Una lista incompleta presentada como completa es lo único que no puede hacer."""
    _despliegue(monkeypatch, "tenancy", "party", "sales")
    _reporte(db, tenant_id, "party", [])
    t, exp = _listo_para_destruir(db, tenant_id)

    cert = baja.destruir(db, tenant=t, exportacion_id=exp.id)

    fuera = cert.alcance["fuera_de_este_certificado"]
    assert fuera["servicios_sin_contestar"] == ["sales"]
    assert fuera["completo"] is False
    assert "sales" in fuera["aviso"]


def test_un_servicio_que_no_pudo_leer_su_inventario_no_pasa_por_cero(
    db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    """El silencio, el cero y el error son tres respuestas distintas."""
    _despliegue(monkeypatch, "tenancy", "party")
    _reporte(db, tenant_id, "party", [], nota="no se pudo leer el inventario: tabla ausente")
    t, exp = _listo_para_destruir(db, tenant_id)

    cert = baja.destruir(db, tenant=t, exportacion_id=exp.id)

    fuera = cert.alcance["fuera_de_este_certificado"]
    assert fuera["completo"] is False
    assert any("party" in i for i in fuera["inventarios_ilegibles"])


def test_pasar_a_baja_pide_el_inventario_a_todos(db: Any, tenant_id: UUID) -> None:
    """Se pide al empezar la ventana de recuperación, no al destruir: si se
    pidiera al destruir, nadie tendría tiempo de contestar."""
    from crmcore.bus.modelos import EventoSaliente
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.documental.inventario import INVENTARIO_SOLICITADO
    from sqlalchemy import select

    from services.tenancy import servicio as svc

    _tenant(db, tenant_id, estado="activo")
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    svc.cambiar_estado(uow, tenant_id, nuevo="en_baja", motivo="el cliente se va")
    db.flush()

    tipos = list(
        db.execute(select(EventoSaliente.tipo).where(EventoSaliente.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    assert INVENTARIO_SOLICITADO in tipos


def test_recibir_dos_veces_el_mismo_inventario_no_lo_duplica(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La entrega es at-least-once: un reintento no puede doblar los documentos
    que el certificado dice que quedan fuera."""
    import asyncio

    from sqlalchemy import func, select

    mensaje = {
        "data": {
            "tenant_id": str(tenant_id),
            "servicio": "party",
            "documentos": [{"documento_id": "d-1", "sistema": "contecmind"}],
            "total": 1,
            "nota": "",
        }
    }
    asyncio.run(baja.consumir_reporte_inventario(mensaje))
    asyncio.run(baja.consumir_reporte_inventario(mensaje))

    filas = db.execute(
        select(func.count())
        .select_from(baja.ReporteInventarioDocumental)
        .where(baja.ReporteInventarioDocumental.tenant_id == tenant_id)
    ).scalar_one()
    assert filas == 1


def test_un_servicio_sin_la_tabla_contesta_en_vez_de_callarse(db: Any, tenant_id: UUID) -> None:
    """Si no contestara, quien emite el certificado esperaría para siempre a un
    servicio que nunca iba a tener nada que decir."""
    from crmcore.documental import inventario as inv

    class _RotaSession:
        def __getattr__(self, _nombre: str) -> Any:
            raise RuntimeError("relation «documentos_enlazados» does not exist")

        def rollback(self) -> None:
            return None

    documentos, nota = inv._inventariar(_RotaSession(), tenant_id)  # type: ignore[arg-type]

    assert documentos == []
    assert "no se pudo leer" in nota
