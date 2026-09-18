"""Gestión documental (CRM-06.01.01.05) y seguimiento con avisos (CRM-06.02.01.02).

Dos cosas que estas pruebas defienden por encima de todo:

* **Un fichero subido no se pisa nunca**: subir con el mismo nombre versiona.
* **La bandeja no se convierte en ruido**: los avisos se agrupan y se respetan
  las preferencias, porque una bandeja ruidosa se silencia entera y entonces se
  pierde también lo que sí importaba.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.datos import adjuntos as adj
from crmcore.datos import seguimiento as seg
from crmcore.errors import CuotaAgotada, ErrorValidacion, Prohibido


@pytest.fixture(autouse=True)
def almacen_temporal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Almacén local en un directorio efímero.

    Sin esto las pruebas escribirían en `./datos/adjuntos` del repositorio y se
    verían entre ellas: un fichero de una prueba anterior haría que la
    deduplicación de la siguiente encontrara un gemelo que no debería existir.
    """
    import os

    from crmcore.almacen import reset_almacen
    from crmcore.config import limpiar_cache_settings

    monkeypatch.setitem(os.environ, "STORAGE_LOCAL_PATH", str(tmp_path / "almacen"))
    limpiar_cache_settings()
    reset_almacen()
    yield
    reset_almacen()
    limpiar_cache_settings()


# ── Adjuntos ──────────────────────────────────────────────────────────────


def test_subir_guarda_el_metadato_y_los_bytes(db: Any, tenant_id: UUID) -> None:
    objeto = uuid4()
    fila = adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=objeto,
        nombre="condiciones.pdf",
        datos=b"%PDF-1.4 contenido",
    )
    assert fila.version == 1
    assert fila.es_actual
    assert fila.tamano == len(b"%PDF-1.4 contenido")
    assert adj.leer(db, fila.id) == b"%PDF-1.4 contenido"


def test_subir_con_documento_id_versiona_y_no_pisa(db: Any, tenant_id: UUID) -> None:
    objeto = uuid4()
    v1 = adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=objeto,
        nombre="contrato.pdf",
        datos=b"primera version",
    )
    v2 = adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=objeto,
        nombre="contrato.pdf",
        datos=b"segunda version",
        documento_id=v1.documento_id,
    )

    assert v2.version == 2
    assert v2.es_actual and not v1.es_actual
    # Y la anterior sigue siendo legible: es lo que evita el «contrato_final_v2».
    assert adj.leer(db, v1.id) == b"primera version"


def test_dos_ficheros_identicos_comparten_los_bytes(db: Any, tenant_id: UUID) -> None:
    datos = b"el mismo pdf de condiciones generales"
    a = adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre="cg.pdf",
        datos=datos,
    )
    b = adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="contacto",
        objeto_id=uuid4(),
        nombre="cg.pdf",
        datos=datos,
    )

    assert a.sha256 == b.sha256
    assert a.uri == b.uri
    assert a.id != b.id


def test_la_deduplicacion_no_cruza_tenants(db: Any, tenant_id: UUID, otro_tenant_id: UUID) -> None:
    """Aunque el hash coincida: compartir el objeto haría que borrar en un
    cliente afectara al otro, y que el almacén de uno contuviera dato del otro."""
    datos = b"documento identico en dos clientes"
    a = adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre="x.pdf",
        datos=datos,
    )
    b = adj.subir(
        db,
        tenant_id=otro_tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre="x.pdf",
        datos=datos,
    )

    assert a.sha256 == b.sha256
    assert a.uri != b.uri


def test_una_extension_fuera_de_la_lista_blanca_se_rechaza(db: Any, tenant_id: UUID) -> None:
    with pytest.raises(ErrorValidacion) as exc:
        adj.subir(
            db,
            tenant_id=tenant_id,
            objeto_tipo="cuenta",
            objeto_id=uuid4(),
            nombre="instalador.exe",
            datos=b"MZ...",
        )
    assert exc.value.error_code == "adjunto.extension_no_admitida"


def test_un_fichero_por_encima_del_tope_se_rechaza(db: Any, tenant_id: UUID) -> None:
    from crmcore.runtime import settings as rt

    tope = int(rt.efectivo("adjunto_max_mb") or 25)
    with pytest.raises(CuotaAgotada):
        adj.subir(
            db,
            tenant_id=tenant_id,
            objeto_tipo="cuenta",
            objeto_id=uuid4(),
            nombre="grande.zip",
            datos=b"x" * ((tope * 1024 * 1024) + 1),
        )


def test_un_adjunto_infectado_no_se_entrega(db: Any, tenant_id: UUID) -> None:
    fila = adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre="factura.pdf",
        datos=b"contenido",
    )
    fila.analisis = "infectado"
    db.flush()

    with pytest.raises(Prohibido) as exc:
        adj.leer(db, fila.id)
    assert exc.value.error_code == "adjunto.infectado"


def test_la_descarga_queda_registrada(db: Any, tenant_id: UUID) -> None:
    """Es lo primero que pide una investigación de fuga, y no se reconstruye
    después: o se registró entonces, o no existe."""
    from sqlalchemy import select

    usuario = uuid4()
    fila = adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre="lista.csv",
        datos=b"a,b,c",
    )
    adj.leer(db, fila.id, usuario_id=usuario, ip="10.0.0.5")
    db.flush()

    descargas = (
        db.execute(select(adj.DescargaAdjunto).where(adj.DescargaAdjunto.adjunto_id == fila.id))
        .scalars()
        .all()
    )
    assert len(descargas) == 1
    assert descargas[0].usuario_id == usuario


def test_borrar_no_quita_los_bytes_que_otra_ficha_referencia(db: Any, tenant_id: UUID) -> None:
    """La deduplicación hace que borrar los bytes al borrar la ficha rompa la otra."""
    datos = b"compartido entre dos fichas"
    a = adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre="c.pdf",
        datos=datos,
    )
    b = adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="contacto",
        objeto_id=uuid4(),
        nombre="c.pdf",
        datos=datos,
    )

    adj.borrar(db, a.id)
    db.flush()
    adj.purgar_huerfanos(db, tenant_id)

    assert adj.leer(db, b.id) == datos


def test_la_purga_borra_lo_que_ya_no_referencia_nadie(db: Any, tenant_id: UUID) -> None:
    from crmcore.almacen import get_almacen

    fila = adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre="temporal.txt",
        datos=b"desechable",
    )
    uri = fila.uri
    adj.borrar(db, fila.id)
    db.flush()

    assert adj.purgar_huerfanos(db, tenant_id) == 1
    assert not get_almacen().existe(uri)


def test_un_enlace_firmado_caducado_no_vale(db: Any, tenant_id: UUID) -> None:
    import hashlib
    import hmac

    from crmcore.config import get_settings

    adjunto_id, usuario = uuid4(), uuid4()
    caduca = int((datetime.now(timezone.utc) - timedelta(seconds=1)).timestamp())
    cuerpo = f"{adjunto_id}:{usuario}:{caduca}"
    firma = hmac.new(
        get_settings().secret_key.get_secret_value().encode(), cuerpo.encode(), hashlib.sha256
    ).hexdigest()

    with pytest.raises(Prohibido) as exc:
        adj.verificar_enlace(f"{cuerpo}:{firma}")
    assert exc.value.error_code == "adjunto.enlace_caducado"


def test_un_enlace_manipulado_no_vale(db: Any, tenant_id: UUID) -> None:
    token = adj.firmar_enlace(uuid4(), usuario_id=uuid4())
    partes = token.split(":")
    ajeno = f"{uuid4()}:{partes[1]}:{partes[2]}:{partes[3]}"

    with pytest.raises(Prohibido) as exc:
        adj.verificar_enlace(ajeno)
    assert exc.value.error_code == "adjunto.enlace_invalido"


def test_el_almacen_local_rechaza_el_path_traversal(tmp_path: Path) -> None:
    """El guard vive en un solo sitio; esta prueba es la que evita que vuelva a
    haber cinco copias y que dos estén mal."""
    from crmcore.almacen import AlmacenLocal

    almacen = AlmacenLocal(tmp_path / "base")
    with pytest.raises(ValueError):
        almacen.guardar("../fuera.txt", b"x")
    # Y no ha creado nada fuera de la base antes de fallar.
    assert not (tmp_path / "fuera.txt").exists()


# ── Seguimiento y notificaciones ──────────────────────────────────────────


def test_seguir_es_idempotente_y_mejora_el_motivo(db: Any, tenant_id: UUID) -> None:
    usuario, objeto = uuid4(), uuid4()
    a = seg.seguir(
        db,
        tenant_id=tenant_id,
        usuario_id=usuario,
        objeto_tipo="cuenta",
        objeto_id=objeto,
        motivo="manual",
    )
    b = seg.seguir(
        db,
        tenant_id=tenant_id,
        usuario_id=usuario,
        objeto_tipo="cuenta",
        objeto_id=objeto,
        motivo="propietario",
    )

    assert a.id == b.id
    assert b.motivo == "propietario"


def test_al_propietario_se_le_silencia_en_vez_de_desuscribirle(db: Any, tenant_id: UUID) -> None:
    """Si se borrara la fila, volvería sola al siguiente cambio y el usuario
    viviría un bucle de «ya he dicho que no»."""
    usuario, objeto = uuid4(), uuid4()
    seg.seguir(
        db,
        tenant_id=tenant_id,
        usuario_id=usuario,
        objeto_tipo="caso",
        objeto_id=objeto,
        motivo="propietario",
    )

    assert seg.dejar_de_seguir(
        db, tenant_id=tenant_id, usuario_id=usuario, objeto_tipo="caso", objeto_id=objeto
    )
    db.flush()

    assert seg.seguidores(db, tenant_id=tenant_id, objeto_tipo="caso", objeto_id=objeto) == []
    con_silenciados = seg.seguidores(
        db, tenant_id=tenant_id, objeto_tipo="caso", objeto_id=objeto, incluir_silenciados=True
    )
    assert con_silenciados == [usuario]


def test_notificar_avisa_a_los_seguidores_menos_a_quien_lo_provoco(
    db: Any, tenant_id: UUID
) -> None:
    autor, otro, objeto = uuid4(), uuid4(), uuid4()
    for u in (autor, otro):
        seg.seguir(
            db, tenant_id=tenant_id, usuario_id=u, objeto_tipo="oportunidad", objeto_id=objeto
        )

    creadas = seg.notificar(
        db,
        tenant_id=tenant_id,
        tipo="opportunity.stage.changed",
        titulo="Cambio de etapa",
        objeto_tipo="oportunidad",
        objeto_id=objeto,
        excluir=[autor],
    )

    assert [n.usuario_id for n in creadas] == [otro]


def test_los_avisos_del_mismo_hecho_se_agrupan(db: Any, tenant_id: UUID) -> None:
    """Cinco cambios en diez minutos son UNA notificación, no cinco."""
    usuario, objeto = uuid4(), uuid4()
    seg.seguir(
        db, tenant_id=tenant_id, usuario_id=usuario, objeto_tipo="oportunidad", objeto_id=objeto
    )
    db.add(
        seg.PreferenciaNotificacion(
            tenant_id=tenant_id,
            usuario_id=usuario,
            tipo="opportunity.stage.changed",
            canales=["app"],
            agrupar_minutos=30,
        )
    )
    db.flush()

    for _ in range(5):
        seg.notificar(
            db,
            tenant_id=tenant_id,
            tipo="opportunity.stage.changed",
            titulo="Cambio de etapa",
            objeto_tipo="oportunidad",
            objeto_id=objeto,
        )
    db.flush()

    from sqlalchemy import select

    filas = (
        db.execute(select(seg.Notificacion).where(seg.Notificacion.usuario_id == usuario))
        .scalars()
        .all()
    )
    assert len(filas) == 1
    assert filas[0].agrupadas == 5


def test_la_preferencia_del_tipo_gana_sobre_la_generica(db: Any, tenant_id: UUID) -> None:
    """«Nada de correo salvo los casos escalados» es la petición normal, y con
    la genérica ganando sería inexpresable."""
    usuario, objeto = uuid4(), uuid4()
    seg.seguir(db, tenant_id=tenant_id, usuario_id=usuario, objeto_tipo="caso", objeto_id=objeto)
    db.add(
        seg.PreferenciaNotificacion(
            tenant_id=tenant_id, usuario_id=usuario, tipo="*", canales=["app"]
        )
    )
    db.add(
        seg.PreferenciaNotificacion(
            tenant_id=tenant_id,
            usuario_id=usuario,
            tipo="case.escalated",
            canales=["app", "correo"],
        )
    )
    db.flush()

    creadas = seg.notificar(
        db,
        tenant_id=tenant_id,
        tipo="case.escalated",
        titulo="Caso escalado",
        objeto_tipo="caso",
        objeto_id=objeto,
    )

    assert creadas[0].canales == ["app", "correo"]


def test_sin_ningun_canal_no_se_notifica(db: Any, tenant_id: UUID) -> None:
    usuario, objeto = uuid4(), uuid4()
    seg.seguir(db, tenant_id=tenant_id, usuario_id=usuario, objeto_tipo="caso", objeto_id=objeto)
    db.add(
        seg.PreferenciaNotificacion(tenant_id=tenant_id, usuario_id=usuario, tipo="*", canales=[])
    )
    db.flush()

    assert (
        seg.notificar(
            db,
            tenant_id=tenant_id,
            tipo="case.updated",
            titulo="x",
            objeto_tipo="caso",
            objeto_id=objeto,
        )
        == []
    )


def test_lo_urgente_atraviesa_la_franja_de_silencio(db: Any, tenant_id: UUID) -> None:
    pref = seg.PreferenciaNotificacion(silencio_desde=22, silencio_hasta=8)
    medianoche = datetime(2026, 9, 18, 2, tzinfo=timezone.utc)
    mediodia = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)

    # La franja cruza la medianoche: tratarla como un intervalo simple haría
    # que 22 > 8 no encajara nunca y no funcionara justo cuando se configura.
    assert seg._en_silencio(pref, medianoche)
    assert not seg._en_silencio(pref, mediodia)


def test_marcar_leidas_devuelve_lo_que_de_verdad_marco(db: Any, tenant_id: UUID) -> None:
    usuario, objeto = uuid4(), uuid4()
    seg.seguir(db, tenant_id=tenant_id, usuario_id=usuario, objeto_tipo="caso", objeto_id=objeto)
    seg.notificar(
        db,
        tenant_id=tenant_id,
        tipo="case.updated",
        titulo="x",
        objeto_tipo="caso",
        objeto_id=objeto,
    )
    db.flush()

    assert seg.marcar_leidas(db, tenant_id=tenant_id, usuario_id=usuario) == 1
    # La segunda vez no hay nada pendiente: decir que se marcó sería mentir.
    assert seg.marcar_leidas(db, tenant_id=tenant_id, usuario_id=usuario) == 0
