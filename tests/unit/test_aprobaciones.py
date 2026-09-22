"""Aprobaciones: quórum, delegación, escalado y reaprobación (CRM-00.03.05).

Las pruebas van detrás de los cuatro fallos que convierten una cadena de
aprobación en un trámite:

  * el aprobador que el sistema se inventa cuando la regla no resuelve a nadie,
  * la etapa que espera firmas que ya no pueden cambiar el resultado,
  * la delegación que borra quién firmó de verdad,
  * y lo aprobado que cambia después de aprobarse.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, NoEncontrado

from services.orchestrator import aprobaciones as apr
from services.orchestrator import organizacion as org


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def plantilla(db: Any, tenant_id: UUID) -> dict[str, UUID]:
    """Comercial → responsable → director, más dos pares con el mismo rol."""
    gente = {n: uuid4() for n in ("comercial", "jefe", "director", "par1", "par2")}
    org.aplicar(
        db,
        tenant_id,
        {"user_id": str(gente["director"]), "roles": ["direccion"], "activa": True},
    )
    org.aplicar(
        db,
        tenant_id,
        {
            "user_id": str(gente["jefe"]),
            "roles": ["responsable_ventas"],
            "superior_id": str(gente["director"]),
            "activa": True,
        },
    )
    org.aplicar(
        db,
        tenant_id,
        {
            "user_id": str(gente["comercial"]),
            "roles": ["comercial"],
            "superior_id": str(gente["jefe"]),
            "activa": True,
        },
    )
    for clave in ("par1", "par2"):
        org.aplicar(
            db,
            tenant_id,
            {"user_id": str(gente[clave]), "roles": ["comite"], "activa": True},
        )
    return gente


def _crear(uow: UnidadDeTrabajo, gente: dict[str, UUID], **kw: Any) -> Any:
    base = {
        "politica": "descuento",
        "objeto": "oportunidad",
        "objeto_id": uuid4(),
        "etapas": [{"origen": "jerarquia", "escalones": 1}],
        "contexto": {"descuento_pct": 22},
        "solicitante_id": gente["comercial"],
    }
    base.update(kw)
    return apr.crear(uow, **base)


# ── El organigrama replicado (CRM-00.03.05.07) ────────────────────────────


def test_a_quien_no_consta_no_se_le_asigna_nada(db: Any, tenant_id: UUID) -> None:
    """Un aprobador elegido por defecto es una firma que alguien pone sin que le
    correspondiera, y eso se descubre en una auditoría."""
    with pytest.raises(NoEncontrado):
        org.cadena_de_mando(db, tenant_id, uuid4())


def test_la_cadena_de_mando_sube_hasta_arriba(db: Any, tenant_id: UUID, plantilla: Any) -> None:
    cadena = org.cadena_de_mando(db, tenant_id, plantilla["comercial"])
    assert cadena == [plantilla["jefe"], plantilla["director"]]


def test_un_jefe_de_baja_no_bloquea_a_su_equipo(db: Any, tenant_id: UUID, plantilla: Any) -> None:
    """Se salta y se sube un escalón más, que es lo que haría una persona."""
    org.aplicar(
        db,
        tenant_id,
        {
            "user_id": str(plantilla["jefe"]),
            "superior_id": str(plantilla["director"]),
            "activa": False,
        },
    )
    assert org.cadena_de_mando(db, tenant_id, plantilla["comercial"]) == [plantilla["director"]]


def test_un_ciclo_en_la_jerarquia_no_tumba_el_proceso(
    db: Any, tenant_id: UUID, plantilla: Any
) -> None:
    """A reporta a B y B a A es raro pero existe; con recursión ingenua tumbaría
    el proceso en vez de dar una cadena corta y rara."""
    org.aplicar(
        db,
        tenant_id,
        {
            "user_id": str(plantilla["director"]),
            "superior_id": str(plantilla["jefe"]),
            "activa": True,
        },
    )
    cadena = org.cadena_de_mando(db, tenant_id, plantilla["comercial"])
    assert cadena == [plantilla["jefe"], plantilla["director"]]


def test_el_organigrama_dice_de_cuando_es(db: Any, tenant_id: UUID, plantilla: Any) -> None:
    """Va por detrás de la ficha; sin esa marca, una cadena desfasada parece
    actual."""
    assert org.persona(db, tenant_id, plantilla["jefe"]).sincronizado_at is not None


# ── Resolver el aprobador ─────────────────────────────────────────────────


def test_el_aprobador_sale_de_la_jerarquia(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    solicitud = _crear(uow, plantilla)
    estado = apr.estado(uow.db, uow.tenant_id, solicitud.id)
    assert estado["etapas"][0]["aprobadores"] == [str(plantilla["jefe"])]


def test_quien_pide_no_se_aprueba_a_si_mismo(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    """Es la separación de funciones más básica y la que más se cuela: el
    responsable de zona suele ser también el dueño de la cuenta."""
    with pytest.raises(ErrorValidacion) as e:
        _crear(
            uow,
            plantilla,
            etapas=[{"origen": "campo", "campo": "dueno"}],
            contexto={"dueno": str(plantilla["comercial"])},
        )
    assert e.value.error_code == "aprobacion.sin_aprobadores"


def test_una_etapa_sin_aprobadores_no_se_salta(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    """Saltarla haría que una cadena mal configurada aprobara sola y en
    silencio."""
    with pytest.raises(ErrorValidacion) as e:
        _crear(uow, plantilla, etapas=[{"origen": "rol", "rol": "rol_que_no_existe"}])
    assert e.value.error_code == "aprobacion.sin_aprobadores"


def test_un_origen_inventado_se_rechaza(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    with pytest.raises(ErrorValidacion):
        _crear(uow, plantilla, etapas=[{"origen": "el_que_pase_por_ahi"}])


# ── Quórum (CRM-00.03.05.06) ──────────────────────────────────────────────


def test_con_todos_hacen_falta_todos(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    solicitud = _crear(
        uow, plantilla, etapas=[{"origen": "rol", "rol": "comite", "quorum": "todos"}]
    )
    apr.decidir(uow, solicitud.id, usuario_id=plantilla["par1"], decision="aprobar")
    assert apr.estado(uow.db, uow.tenant_id, solicitud.id)["estado"] == "pendiente"
    apr.decidir(uow, solicitud.id, usuario_id=plantilla["par2"], decision="aprobar")
    assert apr.estado(uow.db, uow.tenant_id, solicitud.id)["estado"] == "aprobada"


def test_con_cualquiera_basta_uno(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    solicitud = _crear(
        uow, plantilla, etapas=[{"origen": "rol", "rol": "comite", "quorum": "cualquiera"}]
    )
    apr.decidir(uow, solicitud.id, usuario_id=plantilla["par1"], decision="aprobar")
    assert apr.estado(uow.db, uow.tenant_id, solicitud.id)["estado"] == "aprobada"


def test_un_no_con_quorum_de_todos_cierra_ya(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    """Seguir pidiendo firmas a los que faltan es hacerles perder el tiempo con
    algo que ya no puede aprobarse, y retrasa el rechazo a quien lo pidió."""
    solicitud = _crear(
        uow, plantilla, etapas=[{"origen": "rol", "rol": "comite", "quorum": "todos"}]
    )
    salida = apr.decidir(uow, solicitud.id, usuario_id=plantilla["par1"], decision="rechazar")
    assert salida["estado"] == "rechazada"


def test_n_de_m_imposible_se_caza_al_crear(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    """Pedir tres de dos deja la aprobación bloqueada para siempre, y el sitio
    donde se nota es seis semanas después."""
    with pytest.raises(ErrorValidacion) as e:
        _crear(
            uow,
            plantilla,
            etapas=[{"origen": "rol", "rol": "comite", "quorum": "n_de_m", "minimo": 3}],
        )
    assert e.value.error_code == "aprobacion.minimo_imposible"


def test_la_cadena_avanza_de_etapa_en_etapa(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    solicitud = _crear(
        uow,
        plantilla,
        etapas=[
            {"origen": "jerarquia", "escalones": 1, "nombre": "jefe"},
            {"origen": "rol", "rol": "direccion", "nombre": "direccion"},
        ],
    )
    apr.decidir(uow, solicitud.id, usuario_id=plantilla["jefe"], decision="aprobar")
    estado = apr.estado(uow.db, uow.tenant_id, solicitud.id)
    assert estado["estado"] == "pendiente"
    assert estado["etapa_actual"] == 1
    apr.decidir(uow, solicitud.id, usuario_id=plantilla["director"], decision="aprobar")
    assert apr.estado(uow.db, uow.tenant_id, solicitud.id)["estado"] == "aprobada"


def test_nadie_vota_dos_veces_en_la_misma_etapa(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    solicitud = _crear(
        uow, plantilla, etapas=[{"origen": "rol", "rol": "comite", "quorum": "todos"}]
    )
    apr.decidir(uow, solicitud.id, usuario_id=plantilla["par1"], decision="aprobar")
    with pytest.raises(Conflicto):
        apr.decidir(uow, solicitud.id, usuario_id=plantilla["par1"], decision="aprobar")


def test_quien_no_tiene_nada_que_decidir_recibe_404(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    """Un 403 confirmaría que esa aprobación existe y sobre qué registro va."""
    solicitud = _crear(uow, plantilla)
    with pytest.raises(NoEncontrado):
        apr.decidir(uow, solicitud.id, usuario_id=uuid4(), decision="aprobar")


# ── Delegación (CRM-00.03.05.08) ──────────────────────────────────────────


def test_el_suplente_decide_y_se_guardan_los_dos(
    uow: UnidadDeTrabajo, plantilla: Any, db: Any
) -> None:
    """Perder quién firmó de verdad convierte la delegación en un agujero de
    responsabilidad."""
    apr.delegar(
        uow,
        titular_id=plantilla["jefe"],
        suplente_id=plantilla["par1"],
        desde=_ahora() - timedelta(days=1),
        hasta=_ahora() + timedelta(days=5),
    )
    solicitud = _crear(uow, plantilla)
    apr.decidir(uow, solicitud.id, usuario_id=plantilla["par1"], decision="aprobar")

    from sqlalchemy import select

    voto = db.execute(select(apr.DecisionAprobacion)).scalars().one()
    assert voto.titular_id == plantilla["jefe"]
    assert voto.decidio_id == plantilla["par1"]


def test_una_delegacion_caducada_ya_no_sirve(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    apr.delegar(
        uow,
        titular_id=plantilla["jefe"],
        suplente_id=plantilla["par1"],
        desde=_ahora() - timedelta(days=10),
        hasta=_ahora() - timedelta(days=1),
    )
    solicitud = _crear(uow, plantilla)
    with pytest.raises(NoEncontrado):
        apr.decidir(uow, solicitud.id, usuario_id=plantilla["par1"], decision="aprobar")


def test_una_delegacion_acotada_no_firma_lo_de_otra_politica(
    uow: UnidadDeTrabajo, plantilla: Any
) -> None:
    """Delegar las vacaciones no es delegar la firma de los contratos."""
    apr.delegar(
        uow,
        titular_id=plantilla["jefe"],
        suplente_id=plantilla["par1"],
        desde=_ahora() - timedelta(days=1),
        hasta=_ahora() + timedelta(days=5),
        politica="vacaciones",
    )
    solicitud = _crear(uow, plantilla, politica="contratos")
    with pytest.raises(NoEncontrado):
        apr.decidir(uow, solicitud.id, usuario_id=plantilla["par1"], decision="aprobar")


def test_una_delegacion_sin_fin_no_se_admite(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    """Una cesión permanente que nadie recuerda haber hecho, en la práctica se
    queda."""
    with pytest.raises(ErrorValidacion):
        apr.delegar(
            uow,
            titular_id=plantilla["jefe"],
            suplente_id=plantilla["par1"],
            desde=_ahora(),
            hasta=_ahora() - timedelta(hours=1),
        )


def test_delegar_en_uno_mismo_no_es_delegar(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    with pytest.raises(ErrorValidacion):
        apr.delegar(
            uow,
            titular_id=plantilla["jefe"],
            suplente_id=plantilla["jefe"],
            desde=_ahora(),
            hasta=_ahora() + timedelta(days=1),
        )


# ── Escalado (CRM-00.03.05.09) ────────────────────────────────────────────


def test_primero_se_avisa_y_despues_se_escala(
    uow: UnidadDeTrabajo, plantilla: Any, db: Any
) -> None:
    """Un escalado que llega sin aviso previo se vive como un castigo, y la
    reacción es discutirlo en vez de decidir."""
    solicitud = _crear(
        uow, plantilla, etapas=[{"origen": "jerarquia", "escalones": 1, "vence_en_horas": 10}]
    )
    from sqlalchemy import select

    etapa = (
        db.execute(
            select(apr.EtapaAprobacion).where(apr.EtapaAprobacion.solicitud_id == solicitud.id)
        )
        .scalars()
        .one()
    )

    # Pasado el 70 % del plazo: se avisa y no se escala todavía.
    etapa.avisar_at = _ahora() - timedelta(minutes=1)
    db.flush()
    salida = apr.revisar_plazos(uow, uow.tenant_id)
    assert salida["avisadas"] == [str(etapa.id)]
    assert salida["escaladas"] == []

    # Vencida: ahora sí se escala.
    etapa.vence_at = _ahora() - timedelta(minutes=1)
    db.flush()
    salida = apr.revisar_plazos(uow, uow.tenant_id)
    assert salida["escaladas"][0]["anadidos"] == [str(plantilla["director"])]


def test_escalar_anade_al_superior_y_no_quita_al_titular(
    uow: UnidadDeTrabajo, plantilla: Any, db: Any
) -> None:
    """Quitar al titular le quitaría la decisión a quien todavía puede tomarla, y
    borraría el rastro de a quién le tocaba."""
    solicitud = _crear(
        uow, plantilla, etapas=[{"origen": "jerarquia", "escalones": 1, "vence_en_horas": 1}]
    )
    from sqlalchemy import select

    etapa = (
        db.execute(
            select(apr.EtapaAprobacion).where(apr.EtapaAprobacion.solicitud_id == solicitud.id)
        )
        .scalars()
        .one()
    )
    etapa.vence_at = _ahora() - timedelta(hours=1)
    db.flush()
    apr.revisar_plazos(uow, uow.tenant_id)
    db.refresh(etapa)
    assert str(plantilla["jefe"]) in etapa.aprobadores
    assert str(plantilla["director"]) in etapa.aprobadores


def test_no_se_escala_dos_veces(uow: UnidadDeTrabajo, plantilla: Any, db: Any) -> None:
    solicitud = _crear(
        uow, plantilla, etapas=[{"origen": "jerarquia", "escalones": 1, "vence_en_horas": 1}]
    )
    from sqlalchemy import select

    etapa = (
        db.execute(
            select(apr.EtapaAprobacion).where(apr.EtapaAprobacion.solicitud_id == solicitud.id)
        )
        .scalars()
        .one()
    )
    etapa.vence_at = _ahora() - timedelta(hours=1)
    db.flush()
    apr.revisar_plazos(uow, uow.tenant_id)
    assert apr.revisar_plazos(uow, uow.tenant_id)["escaladas"] == []


def test_sin_etapas_abiertas_no_se_dice_que_todo_va_al_dia(uow: UnidadDeTrabajo) -> None:
    assert apr.revisar_plazos(uow, uow.tenant_id)["medible"] is False


# ── Reaprobación (CRM-00.03.05.10) ────────────────────────────────────────


def test_si_cambia_lo_aprobado_se_vuelve_a_aprobar(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    """Un descuento del 10 % aprobado que alguien sube al 30 % está aprobado por
    el papel y no por la persona."""
    solicitud = _crear(
        uow, plantilla, contexto={"descuento_pct": 10}, campos_vigilados=["descuento_pct"]
    )
    apr.decidir(uow, solicitud.id, usuario_id=plantilla["jefe"], decision="aprobar")
    assert apr.estado(uow.db, uow.tenant_id, solicitud.id)["estado"] == "aprobada"

    salida = apr.comprobar_vigencia(uow, solicitud.id, {"descuento_pct": 30})
    assert salida["cambiado"] is True
    assert salida["cambios"]["descuento_pct"] == {"antes": 10, "ahora": 30}
    assert apr.estado(uow.db, uow.tenant_id, solicitud.id)["estado"] == "pendiente"


def test_un_cambio_en_lo_que_no_se_vigila_no_reabre_nada(
    uow: UnidadDeTrabajo, plantilla: Any
) -> None:
    """Si entrara el registro entero, un cambio en la descripción obligaría a
    reaprobar un importe que nadie ha tocado, y a la tercera vez se aprueba sin
    mirar."""
    solicitud = _crear(
        uow,
        plantilla,
        contexto={"descuento_pct": 10, "nota": "a"},
        campos_vigilados=["descuento_pct"],
    )
    apr.decidir(uow, solicitud.id, usuario_id=plantilla["jefe"], decision="aprobar")
    salida = apr.comprobar_vigencia(uow, solicitud.id, {"descuento_pct": 10, "nota": "b"})
    assert salida["cambiado"] is False
    assert apr.estado(uow.db, uow.tenant_id, solicitud.id)["estado"] == "aprobada"


def test_la_reaprobacion_empieza_por_la_primera_etapa(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    """Quien ya había aprobado el 10 % no ha aprobado el 30 %: conservarle el
    voto es hacerle firmar algo que no vio."""
    solicitud = _crear(
        uow,
        plantilla,
        etapas=[
            {"origen": "jerarquia", "escalones": 1},
            {"origen": "rol", "rol": "direccion"},
        ],
        contexto={"descuento_pct": 10},
        campos_vigilados=["descuento_pct"],
    )
    apr.decidir(uow, solicitud.id, usuario_id=plantilla["jefe"], decision="aprobar")
    apr.comprobar_vigencia(uow, solicitud.id, {"descuento_pct": 30})
    estado = apr.estado(uow.db, uow.tenant_id, solicitud.id)
    assert estado["etapa_actual"] == 0
    assert estado["reaprobaciones"] == 1
    # Y el jefe puede volver a votar, porque su voto anterior era de otra cosa.
    apr.decidir(uow, solicitud.id, usuario_id=plantilla["jefe"], decision="aprobar")
    assert apr.estado(uow.db, uow.tenant_id, solicitud.id)["etapa_actual"] == 1


# ── Aprobación automática (CRM-00.03.05.11) ───────────────────────────────


def test_bajo_umbral_se_aprueba_sola_y_deja_dicho_quien_habria_firmado(
    uow: UnidadDeTrabajo, plantilla: Any
) -> None:
    """Sin ese nombre, «aprobación automática» es una decisión sin responsable, y
    la primera pregunta de cualquier auditoría es de quién era la firma."""
    solicitud = _crear(
        uow,
        plantilla,
        contexto={"descuento_pct": 2},
        umbral_automatico={"campo": "descuento_pct", "menor_que": 5},
    )
    assert solicitud.estado == "aprobada"
    assert solicitud.automatica is True
    assert solicitud.habria_aprobado == [str(plantilla["jefe"])]
    assert "por debajo del umbral" in solicitud.motivo_automatica


def test_por_encima_del_umbral_sigue_haciendo_falta_una_persona(
    uow: UnidadDeTrabajo, plantilla: Any
) -> None:
    solicitud = _crear(
        uow,
        plantilla,
        contexto={"descuento_pct": 22},
        umbral_automatico={"campo": "descuento_pct", "menor_que": 5},
    )
    assert solicitud.estado == "pendiente"
    assert solicitud.automatica is False


# ── Decidir desde el correo (CRM-00.03.05.12) ─────────────────────────────


def test_el_enlace_sirve_una_sola_vez(uow: UnidadDeTrabajo, plantilla: Any, db: Any) -> None:
    solicitud = _crear(uow, plantilla)
    from sqlalchemy import select

    etapa = (
        db.execute(
            select(apr.EtapaAprobacion).where(apr.EtapaAprobacion.solicitud_id == solicitud.id)
        )
        .scalars()
        .one()
    )
    _, token = apr.emitir_enlace(uow, etapa_id=etapa.id, titular_id=plantilla["jefe"])

    salida = apr.decidir_con_enlace(uow, token, decision="aprobar")
    assert salida["estado"] == "aprobada"
    with pytest.raises(NoAutenticado):
        apr.decidir_con_enlace(uow, token, decision="aprobar")


def test_un_enlace_caducado_y_uno_inexistente_dan_lo_mismo(
    uow: UnidadDeTrabajo, plantilla: Any, db: Any
) -> None:
    """Distinguirlos le diría a quien prueba si ese enlace existió, y con eso se
    sabe que hay una aprobación en marcha sobre algo."""
    solicitud = _crear(uow, plantilla)
    from sqlalchemy import select

    etapa = (
        db.execute(
            select(apr.EtapaAprobacion).where(apr.EtapaAprobacion.solicitud_id == solicitud.id)
        )
        .scalars()
        .one()
    )
    enlace, token = apr.emitir_enlace(uow, etapa_id=etapa.id, titular_id=plantilla["jefe"])
    enlace.caduca_at = _ahora() - timedelta(hours=1)
    db.flush()

    with pytest.raises(NoAutenticado) as caducado:
        apr.decidir_con_enlace(uow, token, decision="aprobar")
    with pytest.raises(NoAutenticado) as inventado:
        apr.decidir_con_enlace(uow, "no-existe-este-token", decision="aprobar")
    assert caducado.value.error_code == inventado.value.error_code


def test_el_token_no_se_guarda_en_claro(uow: UnidadDeTrabajo, plantilla: Any, db: Any) -> None:
    """Quien lea esa tabla —una copia de seguridad, un volcado de soporte— no
    puede aprobar en nombre de nadie."""
    solicitud = _crear(uow, plantilla)
    from sqlalchemy import select

    etapa = (
        db.execute(
            select(apr.EtapaAprobacion).where(apr.EtapaAprobacion.solicitud_id == solicitud.id)
        )
        .scalars()
        .one()
    )
    enlace, token = apr.emitir_enlace(uow, etapa_id=etapa.id, titular_id=plantilla["jefe"])
    assert token not in enlace.hash_token
    assert len(enlace.hash_token) == 64


# ── La bandeja (CRM-00.03.05.13) ──────────────────────────────────────────


def test_la_bandeja_trae_el_contexto_para_decidir(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    """Una bandeja que solo dice «tienes 14 cosas» obliga a abrir catorce
    pantallas, y lo que pasa entonces es que se aprueba en bloque sin mirar."""
    _crear(uow, plantilla, contexto={"descuento_pct": 22, "cuenta": "Acme"})
    fila = apr.bandeja(uow.db, uow.tenant_id, plantilla["jefe"])[0]
    assert fila["contexto"]["cuenta"] == "Acme"
    assert fila["por_delegacion"] is False


def test_la_bandeja_no_esconde_lo_interno_en_el_contexto(
    uow: UnidadDeTrabajo, plantilla: Any
) -> None:
    _crear(uow, plantilla)
    fila = apr.bandeja(uow.db, uow.tenant_id, plantilla["jefe"])[0]
    assert "_solicitante_id" not in fila["contexto"]


def test_lo_que_toca_por_delegacion_sale_marcado(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    """Si no se distinguiera, el suplente no sabría que está firmando por otro."""
    apr.delegar(
        uow,
        titular_id=plantilla["jefe"],
        suplente_id=plantilla["par1"],
        desde=_ahora() - timedelta(days=1),
        hasta=_ahora() + timedelta(days=5),
    )
    _crear(uow, plantilla)
    fila = apr.bandeja(uow.db, uow.tenant_id, plantilla["par1"])[0]
    assert fila["por_delegacion"] is True
    assert fila["en_nombre_de"] == str(plantilla["jefe"])


def test_lo_ya_votado_desaparece_de_la_bandeja(uow: UnidadDeTrabajo, plantilla: Any) -> None:
    solicitud = _crear(
        uow, plantilla, etapas=[{"origen": "rol", "rol": "comite", "quorum": "todos"}]
    )
    apr.decidir(uow, solicitud.id, usuario_id=plantilla["par1"], decision="aprobar")
    assert apr.bandeja(uow.db, uow.tenant_id, plantilla["par1"]) == []
    assert len(apr.bandeja(uow.db, uow.tenant_id, plantilla["par2"])) == 1


def test_lo_vencido_sale_primero(uow: UnidadDeTrabajo, plantilla: Any, db: Any) -> None:
    _crear(uow, plantilla, titulo="tranquila")
    urgente = _crear(
        uow, plantilla, titulo="urgente", etapas=[{"origen": "jerarquia", "vence_en_horas": 1}]
    )
    from sqlalchemy import select

    etapa = (
        db.execute(
            select(apr.EtapaAprobacion).where(apr.EtapaAprobacion.solicitud_id == urgente.id)
        )
        .scalars()
        .one()
    )
    etapa.vence_at = _ahora() - timedelta(hours=2)
    db.flush()
    assert apr.bandeja(uow.db, uow.tenant_id, plantilla["jefe"])[0]["titulo"] == "urgente"


# ── El proceso que esperaba (CRM-00.03.05.06) ─────────────────────────────


def test_al_decidir_se_despierta_el_proceso_que_esperaba(
    uow: UnidadDeTrabajo, plantilla: Any, db: Any
) -> None:
    """Sin esto, `instancia_id` sería un campo que promete un enlace que nadie
    recorre: la aprobación quedaría decidida y el expediente parado."""
    from services.orchestrator.modelos import DefinicionProceso, InstanciaProceso

    definicion = DefinicionProceso(
        tenant_id=uow.tenant_id,
        clave="venta",
        version=1,
        nombre="venta",
        definicion={"inicio": "fin", "pasos": {"fin": {"tipo": "fin", "resultado": "ok"}}},
        estado="publicada",
    )
    db.add(definicion)
    db.flush()
    instancia = InstanciaProceso(
        tenant_id=uow.tenant_id,
        definicion_id=definicion.id,
        clave="venta",
        version=1,
        estado="esperando",
        variables={},
    )
    db.add(instancia)
    db.flush()

    solicitud = _crear(uow, plantilla, instancia_id=instancia.id)
    apr.decidir(uow, solicitud.id, usuario_id=plantilla["jefe"], decision="aprobar")

    db.refresh(instancia)
    assert instancia.estado == "ejecutando"
    assert instancia.variables["aprobacion_estado"] == "aprobada"


def test_una_instancia_que_ya_no_esta_no_rompe_la_decision(
    uow: UnidadDeTrabajo, plantilla: Any
) -> None:
    """La aprobación es la decisión de una persona: no puede perderse porque el
    expediente al que colgaba se haya borrado."""
    solicitud = _crear(uow, plantilla, instancia_id=uuid4())
    salida = apr.decidir(uow, solicitud.id, usuario_id=plantilla["jefe"], decision="aprobar")
    assert salida["estado"] == "aprobada"
