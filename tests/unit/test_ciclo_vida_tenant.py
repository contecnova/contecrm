"""Ciclo de vida del tenant, marca blanca, jerarquía replicada y throttling
(CRM-00.01.03.02, .03, .06, CRM-00.01.04.06, CRM-00.01.05.04, CRM-00.01.06.05,
CRM-00.01.07.09, .13, CRM-00.05.02.07, CRM-00.05.02.12).

Las operaciones de este bloque fallan todas igual: **a medias y en silencio**. Un
clonado que copia nueve tablas de diez deja una demo que funciona hasta que
alguien abre la pantalla que falta; una marca blanca a medias manda el primer
correo con el dominio del fabricante.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto

from services.gateway import anomalias as ano
from services.tenancy import ciclo_vida as cv
from services.tenancy import marca as mrc


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── Onboarding por industria (CRM-00.01.03.02) ────────────────────────────


@pytest.mark.db
def test_aplicar_un_perfil_no_pisa_lo_que_ya_hay(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Pisar la configuración de un tenant que ya trabaja es la forma más rápida
    de perder tres semanas de trabajo suyo."""
    cv.guardar_perfil(
        uow.db,
        clave="industrial",
        nombre="Industrial",
        contenido={"pipelines": ["venta_proyecto", "recambios"]},
        no_incluye=["Configuración de almacén"],
    )
    salida = cv.aplicar_perfil(
        uow,
        tenant_id=tenant_id,
        clave="industrial",
        existentes={"pipelines": ["recambios"]},
    )
    assert salida["aplicado"]["pipelines"] == ["venta_proyecto"]
    assert salida["saltado"][0]["clave"] == "recambios"


@pytest.mark.db
def test_el_perfil_dice_lo_que_no_trae(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un perfil que promete «todo lo de tu sector» y deja fuera la mitad hace
    que el cliente descubra los huecos cuando ya ha metido datos."""
    cv.guardar_perfil(
        uow.db,
        clave="retail",
        nombre="Retail",
        contenido={"pipelines": ["tienda"]},
        no_incluye=["Integración con TPV"],
    )
    salida = cv.simular_perfil(uow.db, tenant_id, clave="retail")
    assert salida["no_incluye"] == ["Integración con TPV"]


# ── Clonado (CRM-00.01.03.03) ─────────────────────────────────────────────


@pytest.mark.db
def test_el_clon_avisa_de_lo_que_nunca_se_copia(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """No es una lista de exclusiones técnicas: es la diferencia entre un sandbox
    y un incidente."""
    salida = cv.simular_clonado(
        uow, origen_id=tenant_id, uso="sandbox", bloques=["configuracion", "integraciones"]
    )
    assert "credenciales" in salida["nunca_se_copia"]
    assert any("no es un sandbox" in a for a in salida["avisos"])


@pytest.mark.db
def test_copiar_usuarios_a_una_demo_se_avisa(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Manda correos a gente real en cuanto alguien pruebe una campaña."""
    salida = cv.simular_clonado(
        uow, origen_id=tenant_id, uso="demo", bloques=["configuracion", "usuarios"]
    )
    assert any("correos a gente real" in a for a in salida["avisos"])


@pytest.mark.db
def test_un_clon_incompleto_no_se_da_por_bueno(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Copia nueve tablas de diez y deja una demo que funciona hasta que alguien
    abre la pantalla que falta."""
    plan = cv.simular_clonado(
        uow,
        origen_id=tenant_id,
        uso="preproduccion",
        bloques=["datos"],
        recuentos={"datos": 500},
    )
    salida = cv.ejecutar_clonado(
        uow,
        operacion_id=UUID(plan["operacion_id"]),
        destino_id=uuid4(),
        copiado={"datos": 480},
    )
    assert salida["completo"] is False
    assert salida["estado"] == "fallida"


@pytest.mark.db
def test_el_destino_nace_marcado_como_copia(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Si no se marca, a las dos semanas alguien manda una campaña de verdad
    desde la copia de demostración."""
    plan = cv.simular_clonado(uow, origen_id=tenant_id, uso="demo", bloques=["configuracion"])
    salida = cv.ejecutar_clonado(
        uow, operacion_id=UUID(plan["operacion_id"]), destino_id=uuid4(), copiado={}
    )
    assert salida["marcar_el_destino_como"]["es_copia"] is True
    assert salida["marcar_el_destino_como"]["integraciones"] == "apagadas"


# ── Fusión y escisión (CRM-00.01.03.06) ───────────────────────────────────


@pytest.mark.db
def test_una_fusion_con_choques_no_se_puede_ejecutar(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Resolverlos automáticamente produciría un catálogo que no es de ninguna de
    las dos empresas."""
    salida = cv.simular_fusion(
        uow,
        absorbido_id=uuid4(),
        superviviente_id=tenant_id,
        choques={"productos": ["SKU-1", "SKU-2"]},
    )
    assert salida["se_puede_ejecutar"] is False
    assert salida["total_choques"] == 2


@pytest.mark.db
def test_lo_que_no_se_asigna_al_escindir_se_queda_donde_estaba(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Repartirlo por la mitad es cómo se pierden carteras enteras: nadie revisa
    tres mil cuentas antes de aprobar."""
    salida = cv.simular_escision(
        uow,
        origen_id=tenant_id,
        reparto={"cuenta-1": "nuevo"},
        inventario=["cuenta-1", "cuenta-2", "cuenta-3"],
    )
    assert salida["cuantos_sin_asignar"] == 2
    assert salida["se_quedan_en_el_origen"] is True


# ── Baja en cascada (CRM-00.01.07.13) ─────────────────────────────────────


@pytest.mark.db
def test_no_se_certifica_la_baja_si_queda_una_abierta(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Firmar que se destruyó todo sin comprobar la tercera es firmar sobre algo
    que sigue ahí."""
    salida = cv.certificado_de_baja(
        uow.db,
        tenant_id,
        cierres={
            "contecrm": {"cerrado": True},
            "contecmind": {"cerrado": True},
            "contecflow": {"cerrado": False, "porque": "no ha contestado"},
        },
    )
    assert salida["completo"] is False
    assert "NO se puede certificar" in salida["certificado"]
    assert salida["abiertas"][0]["herramienta"] == "contecflow"


# ── Marca blanca (CRM-00.01.04.06) ────────────────────────────────────────


@pytest.mark.db
def test_no_se_activa_una_marca_a_medias(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Si se anuncia y el correo sale con el dominio del fabricante, la
    conversación que sigue no es sobre el correo."""
    mrc.guardar(uow, tenant_id=tenant_id, nombre_producto="CRM de Acme")
    with pytest.raises(Conflicto) as fallo:
        mrc.activar(uow, tenant_id=tenant_id)
    assert fallo.value.error_code == "marca.incompleta"


@pytest.mark.db
def test_cambiar_de_dominio_lo_deja_sin_verificar(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Arrastrar la marca de verificado haría que los correos salieran por un
    dominio que nadie ha comprobado."""
    mrc.guardar(uow, tenant_id=tenant_id, dominio_envio="correo.acme.com")
    mrc.verificar_dominio(uow, tenant_id=tenant_id, cual="envio", verificado=True)
    fila = mrc.guardar(uow, tenant_id=tenant_id, dominio_envio="otro.acme.com")
    assert fila.dominio_envio_verificado is False


@pytest.mark.db
def test_la_marca_completa_se_activa_y_avisa_del_contraste(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La paleta la elige alguien mirando su pantalla buena; quien sufre el
    resultado es quien tiene una mala."""
    mrc.guardar(
        uow,
        tenant_id=tenant_id,
        nombre_producto="CRM de Acme",
        dominio_propio="crm.acme.com",
        dominio_envio="correo.acme.com",
        remitente="no-reply@correo.acme.com",
        pie_correo="Acme SA",
        color_texto="#bbbbbb",
        color_fondo="#ffffff",
    )
    mrc.verificar_dominio(uow, tenant_id=tenant_id, cual="propio", verificado=True)
    mrc.verificar_dominio(uow, tenant_id=tenant_id, cual="envio", verificado=True)
    salida = mrc.activar(uow, tenant_id=tenant_id)
    assert salida["activa"] is True
    assert "mínimo legible" in salida["aviso_contraste"]


def test_el_contraste_se_calcula_y_no_se_estima() -> None:
    assert mrc.contraste("#000000", "#ffffff") > 20
    assert mrc.contraste("#bbbbbb", "#ffffff") < mrc.CONTRASTE_MINIMO


# ── Throttling adaptativo (CRM-00.01.06.05) ───────────────────────────────


def test_sin_historia_no_se_frena() -> None:
    """Con cuatro minutos de observación cualquier pico es una anomalía, y frenar
    por ruido es frenar a quien está trabajando."""
    ano.reiniciar()
    tenant = uuid4()
    for _ in range(3):
        ano.anotar(tenant, 100)
    salida = ano.evaluar(tenant)
    assert salida["medible"] is False
    assert salida["anomalo"] is False


def test_se_compara_con_lo_suyo_y_no_con_un_numero_global() -> None:
    """Un cliente grande hace mil peticiones por minuto y es normal; uno pequeño
    haciendo cien no lo es."""
    ano.reiniciar()
    grande, pequeno = uuid4(), uuid4()
    for _ in range(12):
        ano.anotar(grande, 1000)
        ano.anotar(pequeno, 10)
    ano.anotar(grande, 1100)
    ano.anotar(pequeno, 100)

    assert ano.evaluar(grande)["anomalo"] is False
    assert ano.evaluar(pequeno)["anomalo"] is True


def test_el_freno_es_gradual_y_temporal() -> None:
    """Cortar a un cliente porque su importación va rápida convierte un problema
    de reparto en una incidencia."""
    ano.reiniciar()
    tenant = uuid4()
    primero = ano.frenar(tenant, motivo="pico")
    segundo = ano.frenar(tenant, motivo="sigue")
    assert primero["factor_de_cuota"] > segundo["factor_de_cuota"]
    assert segundo["factor_de_cuota"] > 0, "se ralentiza, no se corta"


def test_al_frenado_se_le_dice_que_esta_frenado() -> None:
    """Un 429 sin explicación hace que la integración reintente más fuerte."""
    ano.reiniciar()
    salida = ano.frenar(uuid4(), motivo="pico")
    assert "se restablece solo" in salida["mensaje_para_el_cliente"]
    assert "empeora" in salida["mensaje_para_el_cliente"]


def test_el_freno_se_suelta_solo() -> None:
    """Uno que hay que quitar a mano se queda puesto, y el cliente lleva semanas
    a un cuarto de cuota sin que nadie sepa por qué."""
    from datetime import datetime as dt
    from datetime import timedelta, timezone

    ano.reiniciar()
    tenant = uuid4()
    ano.frenar(tenant, motivo="pico")
    despues = dt.now(timezone.utc) + timedelta(minutes=ano.MINUTOS_FRENO + 1)
    assert ano.estado(tenant, ahora=despues)["frenado"] is False


# ── Jerarquía y territorios replicados (CRM-00.05.02.12, .07) ─────────────


@pytest.mark.db
def test_la_jerarquia_replicada_da_subordinados_en_este_servicio(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es el hueco que el manual llevaba tiempo declarando: un responsable no
    veía por jerarquía los registros de su equipo en `party` ni en `sales`."""
    from crmcore.authz.jerarquia import aplicar_mando, subordinados_de

    jefe, medio, base = uuid4(), uuid4(), uuid4()
    aplicar_mando(db, tenant_id=tenant_id, usuario_id=medio, superior_id=jefe)
    aplicar_mando(db, tenant_id=tenant_id, usuario_id=base, superior_id=medio)

    assert subordinados_de(db, tenant_id, jefe) == {medio, base}
    assert subordinados_de(db, tenant_id, base) == set()


@pytest.mark.db
def test_dejar_de_depender_de_alguien_se_aplica_el_mismo_dia(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Ignorar el vacío dejaría a su antiguo jefe viendo su cartera para
    siempre."""
    from crmcore.authz.jerarquia import aplicar_mando, subordinados_de

    jefe, persona = uuid4(), uuid4()
    aplicar_mando(db, tenant_id=tenant_id, usuario_id=persona, superior_id=jefe)
    assert subordinados_de(db, tenant_id, jefe) == {persona}

    aplicar_mando(db, tenant_id=tenant_id, usuario_id=persona, superior_id=None)
    assert subordinados_de(db, tenant_id, jefe) == set()


@pytest.mark.db
def test_un_ciclo_en_el_organigrama_no_cuelga_el_listado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«A depende de B y B depende de A» pasa de verdad —dos cambios el mismo
    día— y sin cortarlo esto no termina nunca."""
    from crmcore.authz.jerarquia import aplicar_mando, subordinados_de

    a, b = uuid4(), uuid4()
    aplicar_mando(db, tenant_id=tenant_id, usuario_id=a, superior_id=b)
    aplicar_mando(db, tenant_id=tenant_id, usuario_id=b, superior_id=a)
    assert subordinados_de(db, tenant_id, a) == {b}


@pytest.mark.db
def test_el_territorio_hereda_hacia_abajo_y_no_hacia_arriba(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Quien lleva «Europa» ve lo de «España»; quien lleva «España» no ve lo del
    resto de Europa. Al revés es el error clásico y se nota tarde."""
    from crmcore.authz.jerarquia import aplicar_territorio, territorios_de

    europa, espana = uuid4(), uuid4()
    jefe_europa, jefe_espana = uuid4(), uuid4()
    aplicar_territorio(db, tenant_id=tenant_id, territorio_id=europa, usuario_id=jefe_europa)
    aplicar_territorio(
        db, tenant_id=tenant_id, territorio_id=espana, padre_id=europa, usuario_id=jefe_espana
    )

    assert territorios_de(db, tenant_id, jefe_europa) == {europa, espana}
    assert territorios_de(db, tenant_id, jefe_espana) == {espana}


@pytest.mark.db
def test_salir_de_un_territorio_quita_visibilidad_de_inmediato(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """No puede esperar a que llegue un alta que lo sustituya: entre los dos
    momentos, la persona seguiría viendo la cartera que ya no lleva."""
    from crmcore.authz.jerarquia import aplicar_territorio, quitar_territorio, territorios_de

    territorio, persona = uuid4(), uuid4()
    aplicar_territorio(db, tenant_id=tenant_id, territorio_id=territorio, usuario_id=persona)
    assert territorios_de(db, tenant_id, persona) == {territorio}

    quitar_territorio(db, tenant_id=tenant_id, territorio_id=territorio, usuario_id=persona)
    assert territorios_de(db, tenant_id, persona) == set()


@pytest.mark.db
def test_una_replica_vacia_no_es_lo_mismo_que_nadie_con_subordinados(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Confundirlas lleva a dar por buena una réplica que nunca se llenó."""
    from crmcore.authz.jerarquia import frescura

    salida = frescura(db, tenant_id)
    assert salida["vacia"] is True
    assert "no ha llegado ningún cambio" in salida["que_significa"]
