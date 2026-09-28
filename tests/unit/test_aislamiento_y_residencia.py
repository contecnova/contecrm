"""Aislamiento, residencia de datos y migración de tenants
(CRM-00.01.01.02 a .06, CRM-00.01.03.09, .10, CRM-00.01.05.01 a .03).

Un CRM multi-tenant se vende con una frase —«sus datos están aislados»— y lo que
pasa siempre es que alguien aprovisiona con la plantilla de siempre y el cliente
que paga por una base dedicada acaba en el pool. Funcionar funciona igual; se
descubre el día de la auditoría.

Las pruebas van detrás de eso y de su gemela en residencia: lo transaccional se
queda donde se prometió y los registros se van a otro continente porque nadie
preguntó.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado

from services.tenancy import aislamiento as ais
from services.tenancy import residencia as res

# Su fallo llega a producción y no se arregla después: una fuga entre tenants o
# una ruta publicada que no responde. Por eso esta prueba NO sale del push.
pytestmark = pytest.mark.despliegue


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── Declarar el aislamiento (CRM-00.01.01.02 a .05) ───────────────────────


@pytest.mark.db
def test_una_base_dedicada_sin_decir_cual_no_se_declara(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin ese dato no se puede comprobar después si el tenant está donde se
    vendió, que es lo único que convierte la promesa en un hecho."""
    with pytest.raises(ErrorValidacion) as fallo:
        ais.declarar(uow, tenant_id=tenant_id, modalidad="base")
    assert fallo.value.error_code == "aislamiento.sin_base"


@pytest.mark.db
def test_la_base_del_cliente_hay_que_marcarla(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Marcarlo es lo que cambia de quién es la copia de seguridad y a quién se
    le pide el acceso cuando hay una incidencia."""
    with pytest.raises(ErrorValidacion) as fallo:
        ais.declarar(uow, tenant_id=tenant_id, modalidad="cliente", base="suya")
    assert fallo.value.error_code == "aislamiento.cliente_sin_marcar"


@pytest.mark.db
def test_cambiar_la_declaracion_invalida_la_comprobacion(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La comprobación anterior seguía diciendo que sí sobre una declaración que
    ya no es la misma."""
    ais.declarar(uow, tenant_id=tenant_id, modalidad="compartido")
    ais.comprobar(uow, tenant_id=tenant_id)
    fila = ais.declarar(uow, tenant_id=tenant_id, modalidad="esquema", esquema="t_acme")
    assert fila.comprobado_ok is None
    assert "volver a comprobar" in fila.comprobado_detalle


@pytest.mark.db
def test_un_tenant_sin_declarar_no_se_puede_comprobar(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """No se puede decir si está donde tenía que estar porque nadie ha dicho
    dónde era."""
    with pytest.raises(NoEncontrado) as fallo:
        ais.comprobar(uow, tenant_id=uuid4())
    assert fallo.value.error_code == "aislamiento.no_declarado"


@pytest.mark.db
def test_declarar_un_esquema_que_no_es_el_real_se_caza(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es el caso de verdad: se vende una cosa, se aprovisiona otra y funcionar
    funciona igual."""
    ais.declarar(uow, tenant_id=tenant_id, modalidad="esquema", esquema="esquema_que_no_es")
    salida = ais.comprobar(uow, tenant_id=tenant_id)
    assert salida["cuadra"] is False
    assert "NO es lo que hay" in salida["que_significa"]


@pytest.mark.db
def test_el_que_no_cuadra_sale_aparte_y_primero(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """No es un recordatorio: es una promesa incumplida en vigor."""
    ais.declarar(uow, tenant_id=tenant_id, modalidad="base", base="una_que_no_existe")
    ais.comprobar(uow, tenant_id=tenant_id)
    salida = ais.sin_comprobar(uow.db)
    assert salida["hay_promesas_incumplidas"] is True
    assert salida["no_cuadran"]


def test_un_tier_desconocido_no_hereda_el_mas_aislado() -> None:
    """Dar aislamiento de más por un plan mal escrito cuesta dinero y hace creer
    al cliente que compró algo que no compró."""
    assert ais.modalidad_de_tier("lo_que_sea") == "compartido"
    assert ais.modalidad_de_tier("enterprise") == "base"


# ── Migración de modalidad (CRM-00.01.01.04, CRM-00.01.03.10) ─────────────


@pytest.mark.db
def test_bajar_de_aislamiento_se_avisa_con_todas_las_letras(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """No es un cambio de configuración: es un cambio de lo que se le prometió al
    cliente."""
    ais.declarar(uow, tenant_id=tenant_id, modalidad="base", base="acme_db")
    salida = ais.planificar_migracion(uow, tenant_id=tenant_id, hacia="compartido")
    assert salida["es_una_bajada"] is True
    assert "conviven con los de otros clientes" in salida["aviso"]


@pytest.mark.db
def test_dos_migraciones_a_la_vez_se_rechazan(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Dejarían dos copias y ninguna forma de saber cuál manda."""
    ais.declarar(uow, tenant_id=tenant_id, modalidad="compartido")
    ais.planificar_migracion(uow, tenant_id=tenant_id, hacia="esquema")
    with pytest.raises(Conflicto) as fallo:
        ais.planificar_migracion(uow, tenant_id=tenant_id, hacia="base")
    assert fallo.value.error_code == "aislamiento.migracion_en_curso"


@pytest.mark.db
def test_no_se_cierra_una_migracion_que_no_cuadra(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Cerrarla dejaría un tenant con la mitad de sus datos y la migración
    marcada como buena."""
    ais.declarar(uow, tenant_id=tenant_id, modalidad="compartido")
    plan = ais.planificar_migracion(uow, tenant_id=tenant_id, hacia="esquema")
    migracion_id = UUID(plan["migracion_id"])
    ais.abrir_ventana(uow, migracion_id=migracion_id)
    salida = ais.verificar(
        uow,
        migracion_id=migracion_id,
        recuento_origen={"cuentas": 100, "contactos": 50},
        recuento_destino={"cuentas": 100, "contactos": 49},
    )
    assert salida["integra"] is False
    with pytest.raises(Conflicto) as fallo:
        ais.cerrar(uow, migracion_id=migracion_id)
    assert fallo.value.error_code == "aislamiento.verificacion_fallida"


@pytest.mark.db
def test_una_tabla_que_sobra_en_el_destino_tambien_es_una_diferencia(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Copiar algo dos veces es tan malo como que falte."""
    ais.declarar(uow, tenant_id=tenant_id, modalidad="compartido")
    plan = ais.planificar_migracion(uow, tenant_id=tenant_id, hacia="esquema")
    migracion_id = UUID(plan["migracion_id"])
    ais.abrir_ventana(uow, migracion_id=migracion_id)
    salida = ais.verificar(
        uow,
        migracion_id=migracion_id,
        recuento_origen={"cuentas": 10},
        recuento_destino={"cuentas": 10, "sobrante": 3},
    )
    assert any(d.get("falta") == "sobra en el destino" for d in salida["diferencias"])


@pytest.mark.db
def test_al_cerrar_se_guarda_lo_que_de_verdad_duro(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Guardar solo lo prometido haría que la siguiente estimación se hiciera
    sobre un número inventado."""
    ais.declarar(uow, tenant_id=tenant_id, modalidad="compartido")
    plan = ais.planificar_migracion(uow, tenant_id=tenant_id, hacia="esquema", ventana_minutos=30)
    migracion_id = UUID(plan["migracion_id"])
    ais.abrir_ventana(uow, migracion_id=migracion_id)
    ais.verificar(
        uow, migracion_id=migracion_id, recuento_origen={"x": 1}, recuento_destino={"x": 1}
    )
    salida = ais.cerrar(uow, migracion_id=migracion_id, nuevo_esquema="t_acme")
    assert salida["minutos_prometidos"] == 30
    assert "minutos_solo_lectura_reales" in salida
    assert salida["se_cumplio_la_ventana"] is True


@pytest.mark.db
def test_migrar_deja_el_aislamiento_por_comprobar(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La comprobación anterior era sobre el sitio viejo."""
    ais.declarar(uow, tenant_id=tenant_id, modalidad="compartido")
    ais.comprobar(uow, tenant_id=tenant_id)
    plan = ais.planificar_migracion(uow, tenant_id=tenant_id, hacia="esquema")
    migracion_id = UUID(plan["migracion_id"])
    ais.abrir_ventana(uow, migracion_id=migracion_id)
    ais.verificar(uow, migracion_id=migracion_id, recuento_origen={}, recuento_destino={})
    salida = ais.cerrar(uow, migracion_id=migracion_id, nuevo_esquema="t_acme")
    assert "aislamiento en el destino" in salida["siguiente_paso"]


@pytest.mark.db
def test_revertir_exige_motivo(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que evita que la siguiente migración repita el mismo fallo."""
    ais.declarar(uow, tenant_id=tenant_id, modalidad="compartido")
    plan = ais.planificar_migracion(uow, tenant_id=tenant_id, hacia="esquema")
    with pytest.raises(ErrorValidacion):
        ais.revertir(uow, migracion_id=UUID(plan["migracion_id"]), motivo="")


# ── Residencia (CRM-00.01.05.01, .02) ─────────────────────────────────────


@pytest.mark.db
def test_lo_no_declarado_no_se_da_por_europeo(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El defecto silencioso es exactamente cómo se incumple una promesa de
    residencia sin enterarse."""
    res.fijar_residencia(uow, tenant_id=tenant_id, tipo_dato="transaccional", region="ue")
    salida = res.mapa(uow.db, tenant_id, region_contratada="ue")
    assert "registros" in salida["sin_declarar"]
    assert salida["completo"] is False
    assert salida["cumple_lo_contratado"] is False
    assert "uno que nadie ha mirado" in salida["que_significa"]


@pytest.mark.db
def test_un_tipo_de_dato_fuera_de_la_region_contratada_sale(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es el caso real: lo transaccional se queda y los registros se van."""
    for tipo in res.TIPOS_DATO:
        res.fijar_residencia(
            uow,
            tenant_id=tenant_id,
            tipo_dato=tipo,
            region="ee_uu" if tipo == "registros" else "ue",
        )
    salida = res.mapa(uow.db, tenant_id, region_contratada="ue")
    assert salida["completo"] is True
    assert [f["tipo_dato"] for f in salida["fuera_de_la_region_contratada"]] == ["registros"]
    assert salida["cumple_lo_contratado"] is False


# ── Subprocesadores y transferencias (CRM-00.01.05.03) ────────────────────


@pytest.mark.db
def test_un_subprocesador_sin_decir_que_trata_no_se_declara(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un nombre en una lista no contesta a lo que pregunta un cliente por el
    artículo 28."""
    with pytest.raises(ErrorValidacion) as fallo:
        res.declarar_subprocesador(
            uow,
            tenant_id=tenant_id,
            clave="almacen",
            nombre="Almacén X",
            trata=[],
            finalidad="guardar cosas",
        )
    assert fallo.value.error_code == "residencia.subprocesador_sin_datos"


@pytest.mark.db
def test_contrato_firmado_no_es_una_garantia_del_rgpd(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        res.declarar_subprocesador(
            uow,
            tenant_id=tenant_id,
            clave="x",
            nombre="X",
            trata=["copias"],
            finalidad="copias",
            garantia="contrato_firmado",
        )
    assert fallo.value.error_code == "residencia.garantia_invalida"


@pytest.mark.db
def test_una_transferencia_sin_garantia_se_anota_y_no_se_bloquea(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Bloquear desde aquí sería fingir un control que no existe: el dato sale
    por el conector, no por esta tabla."""
    salida = res.anotar_transferencia(
        uow, tenant_id=tenant_id, tipo_dato="registros", hacia_region="ee_uu"
    )
    assert salida["amparada"] is False
    assert "no se ha bloqueado" in salida["porque"]


@pytest.mark.db
def test_la_transferencia_hereda_la_garantia_del_subprocesador(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    res.declarar_subprocesador(
        uow,
        tenant_id=tenant_id,
        clave="observabilidad",
        nombre="Observabilidad SA",
        trata=["registros"],
        finalidad="Recoger trazas y métricas",
        region="ee_uu",
        garantia="clausulas_tipo",
        referencia_garantia="SCC 2021/914",
    )
    salida = res.anotar_transferencia(
        uow,
        tenant_id=tenant_id,
        tipo_dato="registros",
        hacia_region="ee_uu",
        subprocesador="observabilidad",
    )
    assert salida["garantia"] == "clausulas_tipo"
    assert salida["amparada"] is True


@pytest.mark.db
def test_un_subprocesador_sin_comunicar_sale_en_el_informe(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Uno del que el cliente no se ha enterado es un incumplimiento del
    contrato, no un detalle administrativo."""
    res.declarar_subprocesador(
        uow,
        tenant_id=tenant_id,
        clave="nuevo",
        nombre="Proveedor nuevo",
        trata=["analitico"],
        finalidad="Explotación",
    )
    salida = res.informe_de_transferencias(uow.db, tenant_id)
    assert salida["sin_comunicar_al_cliente"] == ["nuevo"]

    res.comunicar_subprocesador(uow, tenant_id=tenant_id, clave="nuevo")
    despues = res.informe_de_transferencias(uow.db, tenant_id)
    assert despues["sin_comunicar_al_cliente"] == []


@pytest.mark.db
def test_sin_nada_anotado_no_se_dice_que_no_hay_transferencias(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """No significa que no las haya: significa que no se ha anotado ninguna."""
    salida = res.informe_de_transferencias(uow.db, tenant_id)
    assert salida["medible"] is False
    assert "no se ha anotado ninguno" in salida["porque"]
