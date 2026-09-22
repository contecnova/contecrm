"""RAT, informes de cumplimiento, SLO y restauración selectiva
(CRM-07.03.01.04, CRM-07.03.01.07, CRM-00.06.01.04, CRM-00.06.02.03).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore import cumplimiento
from crmcore.obs import slo


@pytest.fixture(autouse=True)
def _limpio() -> Any:
    """Aísla las declaraciones **y las devuelve como estaban**.

    Vaciarlas sin más dejaba el proceso con menos de lo que se encontró, y el
    gate que comprueba que todo objeto con datos personales declara su
    tratamiento fallaba en cuanto se ejecutaba después de este fichero. Un
    registro global que se limpia y no se restaura es una prueba que rompe a
    otra según el orden, y eso acaba con alguien desactivando la que falla.
    """
    from crmcore import redis_cliente
    from crmcore.cumplimiento import _tratamientos

    previos = dict(_tratamientos)
    cumplimiento.limpiar_tratamientos()
    slo.reiniciar()
    redis_cliente.olvidar()
    yield
    cumplimiento.limpiar_tratamientos()
    _tratamientos.update(previos)
    slo.reiniciar()


# ── RAT y mapa de datos personales ────────────────────────────────────────


def test_el_mapa_sale_del_modelo_y_no_de_una_lista() -> None:
    """Una lista se queda desfasada al primer campo nuevo, y ese campo no
    existiría para el RAT hasta que alguien se acordara — y nadie se acuerda."""
    from services.party.modelos import Contacto

    campos = cumplimiento.mapa_de_datos({"contacto": Contacto})
    assert campos, "el contacto declara campos personales y no se han encontrado"
    assert all(c.objeto == "contacto" for c in campos)


def test_un_objeto_con_datos_personales_sin_tratamiento_sale_como_hueco() -> None:
    """Un RAT que presenta como completo lo que no lo está es peor que no
    tenerlo, porque nadie vuelve a mirarlo."""
    from services.party.modelos import Contacto

    rat = cumplimiento.registro_de_tratamiento({"contacto": Contacto})
    assert rat["objetos_sin_tratamiento_declarado"] == ["contacto"]
    assert rat["completo"] is False


def test_declarar_el_tratamiento_cierra_el_hueco() -> None:
    from services.party.modelos import Contacto

    cumplimiento.declarar(
        cumplimiento.Tratamiento(
            objeto="contacto",
            finalidad="Gestión de la relación comercial",
            base_legal="interes_legitimo",
            plazo="Mientras dure la relación y 6 años más",
        )
    )
    rat = cumplimiento.registro_de_tratamiento({"contacto": Contacto})
    assert rat["objetos_sin_tratamiento_declarado"] == []
    assert rat["actividades"][0]["base_legal"] == "interes_legitimo"


def test_un_tratamiento_sobre_un_objeto_sin_datos_personales_tambien_sale() -> None:
    """Suele significar que el objeto cambió y el RAT no."""
    from services.sales.modelos import Pipeline

    cumplimiento.declarar(
        cumplimiento.Tratamiento(objeto="pipeline", finalidad="x", base_legal="contrato", plazo="z")
    )
    rat = cumplimiento.registro_de_tratamiento({"pipeline": Pipeline})
    # `in` y no `==`: importar el modelo arrastra las declaraciones reales del
    # servicio, y fijar la lista exacta haría que esta prueba se rompiera cada
    # vez que alguien declara un tratamiento nuevo — que es algo que queremos
    # que pase.
    assert "pipeline" in rat["tratamientos_sobre_objetos_sin_datos_personales"]


def test_una_base_legal_inventada_no_entra() -> None:
    """Es el campo que un auditor mira primero. Con texto libre acaban conviviendo
    «legítimo interés», «interes legitimo» e «interés legítimo (ver contrato)»
    como tres bases distintas en el mismo registro."""
    with pytest.raises(ValueError) as fallo:
        cumplimiento.declarar(
            cumplimiento.Tratamiento(
                objeto="contacto", finalidad="x", base_legal="porque sí", plazo="z"
            )
        )
    assert "artículo 6" in str(fallo.value)


def test_el_producto_declara_el_tratamiento_de_todo_lo_que_guarda() -> None:
    """El RAT de verdad, no el de la prueba: si un objeto del producto guarda
    datos personales y nadie ha dicho para qué, el registro que se le enseña a
    un auditor tiene un agujero."""
    import importlib
    import pathlib

    from crmcore.db.base import Base

    raiz = pathlib.Path(__file__).resolve().parents[2] / "services"
    for servicio in sorted(d.name for d in raiz.iterdir() if d.is_dir()):
        if (raiz / servicio / "modelos.py").exists():
            importlib.import_module(f"services.{servicio}.modelos")
        # Se recargan las declaraciones: el módulo ya está importado de antes, y
        # un import cacheado no vuelve a declarar nada.
        if (raiz / servicio / "tratamientos.py").exists():
            importlib.reload(importlib.import_module(f"services.{servicio}.tratamientos"))

    modelos = {
        t.name: m.class_
        for m in Base.registry.mappers
        if (t := getattr(m.class_, "__table__", None)) is not None
    }
    rat = cumplimiento.registro_de_tratamiento(modelos)
    assert rat["objetos_sin_tratamiento_declarado"] == []
    assert rat["campos_personales"] > 0, "el mapa no puede salir vacío: hay datos personales"


@pytest.mark.db
def test_lo_que_ajusta_el_cliente_manda_sobre_lo_que_trae_el_producto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La misma tabla de contactos se trata por contrato en una empresa y por
    interés legítimo en otra. El responsable del tratamiento es el cliente, no el
    fabricante, así que la declaración de fábrica es un punto de partida."""
    from crmcore.runtime import settings as ajustes

    from services.party.modelos import Contacto

    cumplimiento.declarar(
        cumplimiento.Tratamiento(
            objeto="contactos",
            finalidad="Gestionar la relación",
            base_legal="interes_legitimo",
            plazo="6 años",
        )
    )
    ajustes.fijar(
        db,
        "rat_ajustes",
        {"contactos": {"base_legal": "contrato"}},
        ambito="tenant",
        ambito_id=str(tenant_id),
    )

    rat = cumplimiento.registro_de_tratamiento({"contactos": Contacto}, db)
    actividad = rat["actividades"][0]
    assert actividad["base_legal"] == "contrato"
    assert actividad["ajustado_por_el_cliente"] == ["base_legal"]
    # Y lo que NO ha revisado también se dice: si no, un responsable cree haber
    # revisado lo que solo venía puesto de fábrica.
    assert "finalidad" in actividad["sin_revisar_por_el_cliente"]


@pytest.mark.db
def test_el_informe_dice_lo_que_no_ha_podido_componer(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un apartado ausente se lee como «no aplica», y la diferencia entre eso y
    «no se ha podido comprobar» es justo la que importa en una auditoría."""
    from services.party.modelos import Contacto

    informe = cumplimiento.informe_de_cumplimiento(db, tenant_id, {"contacto": Contacto})
    assert "rat" in informe and "avisos" in informe
    # El RAT tiene huecos porque no se ha declarado nada: eso se avisa.
    assert any("registro de tratamiento" in a for a in informe["avisos"])


# ── SLO y presupuesto de error ────────────────────────────────────────────


@pytest.fixture
def tenant() -> UUID:
    """Un tenant por prueba.

    No es cosmético: los contadores viven fuera del proceso a propósito —para
    sobrevivir a un despliegue—, así que dos pruebas que compartieran tenant se
    sumarían la una a la otra y la suite diría cosas distintas según el orden.
    """
    return uuid4()


def _objetivo(tier: str = "premium") -> slo.Objetivo:
    return slo.Objetivo(servicio="party", tier=tier, disponibilidad_pct=99.9, latencia_p95_ms=500)


def _consumo(tenant: UUID, tier: str = "premium") -> slo.Consumo:
    import asyncio

    return asyncio.run(slo.consumo_de("party", tenant, tier=tier))


def _anotar(tenant: UUID, veces: int, *, ok: bool, ms: float) -> None:
    import asyncio

    async def _todas() -> None:
        for _ in range(veces):
            await slo.anotar("party", tenant, ok=ok, ms=ms)

    asyncio.run(_todas())


def test_sin_trafico_no_se_dice_que_va_bien(tenant: UUID) -> None:
    """«100 % disponible» sin peticiones es mentir con la verdad: un servicio
    que nadie usa no ha demostrado nada."""
    salida = slo.presupuesto(_objetivo(), _consumo(tenant))
    assert salida["medible"] is False


def test_lo_lento_cuenta_aparte_de_lo_fallido(tenant: UUID) -> None:
    """Una respuesta que llega en cuatro segundos es un error para quien la
    espera aunque devuelva 200."""
    _anotar(tenant, 90, ok=True, ms=100)
    _anotar(tenant, 5, ok=True, ms=4000)
    _anotar(tenant, 5, ok=False, ms=50)

    salida = slo.presupuesto(_objetivo(), _consumo(tenant))
    assert salida["lentas"] == 5
    assert salida["fallidas"] == 5


def test_la_misma_peticion_es_lenta_o_no_segun_el_tier_contratado(tenant: UUID) -> None:
    """1,5 s es normal en estándar y es una falta en enterprise, y esa es
    exactamente la diferencia que el cliente está pagando. Decidirlo al escribir
    obligaría a saber el tier donde no se sabe, y los milisegundos ya no
    estarían para recalcularlo."""
    _anotar(tenant, 20, ok=True, ms=1_500)
    assert _consumo(tenant, "estandar").lentas == 0
    assert _consumo(tenant, "premium").lentas == 20
    assert _consumo(tenant, "enterprise").lentas == 20


def test_el_presupuesto_se_dice_en_minutos_y_no_solo_en_porcentaje(tenant: UUID) -> None:
    """«Te queda el 37 %» no le dice nada a nadie; «te quedan 16 minutos de
    caída este mes» se entiende a la primera."""
    _anotar(tenant, 1000, ok=True, ms=100)
    salida = slo.presupuesto(_objetivo(), _consumo(tenant))
    assert "minutos_restantes" in salida
    assert salida["agotado"] is False


def test_agotar_el_presupuesto_dice_que_toca_parar(tenant: UUID) -> None:
    """Convierte una discusión de opiniones en una cuenta."""
    _anotar(tenant, 100, ok=False, ms=10)
    salida = slo.presupuesto(_objetivo(), _consumo(tenant))
    assert salida["agotado"] is True
    assert "arreglar" in salida["que_significa"]


def test_contar_en_memoria_se_avisa_en_la_respuesta(tenant: UUID, monkeypatch: Any) -> None:
    """Un presupuesto mensual calculado desde el último despliegue dice siempre
    que queda margen — que es lo que uno quiere oír y por lo que no serviría."""
    # Se fuerza el caso «sin Redis»: es el que hay que dejar dicho, porque es
    # cuando el número deja de ser el del periodo.
    from crmcore import redis_cliente

    async def _sin_redis() -> Any:
        return None

    monkeypatch.setattr(redis_cliente, "cliente", _sin_redis)
    _anotar(tenant, 10, ok=True, ms=10)
    salida = slo.presupuesto(_objetivo(), _consumo(tenant))
    assert salida["contado_en"] == "memoria_del_proceso"
    assert "no es la ventana del periodo" in salida["aviso"]


def test_el_objetivo_sale_de_la_configuracion_y_no_del_codigo() -> None:
    """El compromiso es una decisión de negocio con coste: cambiarlo no puede
    exigir un despliegue de código."""
    estandar = slo.objetivo_de("party", "estandar")
    enterprise = slo.objetivo_de("party", "enterprise")
    assert enterprise.disponibilidad_pct > estandar.disponibilidad_pct
    assert enterprise.latencia_p95_ms < estandar.latencia_p95_ms


def test_un_tier_desconocido_no_hereda_el_mas_exigente() -> None:
    """Aplicar el enterprise a un plan mal escrito llenaría el informe de
    incumplimientos inventados."""
    assert slo.objetivo_de("party", "loquesea").tier == "estandar"


# ── Restauración selectiva ────────────────────────────────────────────────


@pytest.mark.db
def test_no_se_pisa_lo_modificado_despues_sin_decirlo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es trabajo que alguien hizo a sabiendas: sobrescribirlo sin avisar cambia
    un problema por otro peor, porque el primero se conocía."""
    from crmcore.datos.restaurar import restaurar

    from services.party.modelos import Cuenta

    cuenta = Cuenta(tenant_id=tenant_id, nombre="Después", clave_canonica="despues")
    db.add(cuenta)
    db.flush()

    origen = {str(cuenta.id): {"id": str(cuenta.id), "nombre": "Antes"}}
    ayer = datetime.now(timezone.utc) - timedelta(days=1)

    # La cuenta se creó ahora, así que está modificada después del punto de
    # restauración: se salta y se dice por qué.
    from crmcore.errors import NoEncontrado

    with pytest.raises(NoEncontrado) as e:
        restaurar(
            db,
            Cuenta,
            origen=origen,
            ids=[str(cuenta.id)],
            tenant_id=tenant_id,
            objeto="cuenta",
            desde=ayer,
        )
    assert "modificado después" in str(e.value.detalle)
    db.refresh(cuenta)
    assert cuenta.nombre == "Después"


@pytest.mark.db
def test_forzando_si_se_restaura(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Es una decisión y tiene que escribirse."""
    from crmcore.datos.restaurar import restaurar

    from services.party.modelos import Cuenta

    cuenta = Cuenta(tenant_id=tenant_id, nombre="Después", clave_canonica="despues")
    db.add(cuenta)
    db.flush()
    origen = {str(cuenta.id): {"id": str(cuenta.id), "nombre": "Antes"}}

    salida = restaurar(
        db,
        Cuenta,
        origen=origen,
        ids=[str(cuenta.id)],
        tenant_id=tenant_id,
        objeto="cuenta",
        desde=datetime.now(timezone.utc) - timedelta(days=1),
        forzar_modificados=True,
    )
    db.refresh(cuenta)
    assert salida["restaurados"] == [str(cuenta.id)]
    assert cuenta.nombre == "Antes"


@pytest.mark.db
def test_no_se_restaura_sobre_otro_tenant(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sería la peor fuga posible: datos de un cliente escritos en la base de
    otro, con rastro que dice que fue una recuperación legítima."""
    from crmcore.datos.restaurar import restaurar
    from crmcore.errors import Conflicto

    from services.party.modelos import Cuenta

    ajena = Cuenta(tenant_id=otro_tenant_id, nombre="Ajena", clave_canonica="ajena")
    db.add(ajena)
    db.flush()

    with pytest.raises(Conflicto) as e:
        restaurar(
            db,
            Cuenta,
            origen={str(ajena.id): {"id": str(ajena.id), "nombre": "x"}},
            ids=[str(ajena.id)],
            tenant_id=tenant_id,
            objeto="cuenta",
        )
    assert e.value.error_code == "restaurar.otro_tenant"


@pytest.mark.db
def test_la_previsualizacion_dice_qué_campos_cambiarian(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Quien restaura casi nunca sabe qué va a sobrescribir, y descubrirlo
    después es cambiar un problema por otro."""
    from crmcore.datos.restaurar import previsualizar

    from services.party.modelos import Cuenta

    cuenta = Cuenta(tenant_id=tenant_id, nombre="Ahora", clave_canonica="ahora")
    db.add(cuenta)
    db.flush()

    diferencias = previsualizar(
        db,
        Cuenta,
        origen={str(cuenta.id): {"id": str(cuenta.id), "nombre": "Antes"}},
        ids=[str(cuenta.id)],
    )
    assert diferencias[0].estado == "distinto"
    assert "nombre" in diferencias[0].campos_distintos


@pytest.mark.db
def test_un_registro_borrado_se_vuelve_a_crear(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es el caso más común de todos —alguien borró lo que no tocaba— y hasta
    ahora se saltaba en silencio.

    Saltárselo dejaba la recuperación selectiva sirviendo solo para el caso raro:
    el registro que sigue existiendo pero con los campos mal. El que ya no está
    es justo el que hace que alguien la pida.
    """
    from uuid import uuid4 as _uuid4

    from crmcore.datos.restaurar import restaurar

    from services.party.modelos import Cuenta

    perdido = str(_uuid4())
    origen = {
        perdido: {
            "id": perdido,
            "tenant_id": str(tenant_id),
            "nombre": "La que alguien borró",
            "clave_canonica": "la-que-alguien-borro",
        }
    }

    salida = restaurar(
        db, Cuenta, origen=origen, ids=[perdido], tenant_id=tenant_id, objeto="cuenta"
    )
    assert salida["recreados"] == [perdido]
    db.flush()
    vuelta = db.get(Cuenta, UUID(perdido))
    assert vuelta is not None and vuelta.nombre == "La que alguien borró"


@pytest.mark.db
def test_no_se_recrea_un_registro_de_otro_tenant(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sería la peor fuga posible: datos de un cliente escritos en la base de
    otro, con un rastro de auditoría que dice que fue una recuperación legítima.

    Y al recrear no hay fila viva con la que contrastar, así que la comprobación
    tiene que hacerse sobre lo exportado o no se hace.
    """
    from uuid import uuid4 as _uuid4

    from crmcore.datos.restaurar import restaurar
    from crmcore.errors import Conflicto

    from services.party.modelos import Cuenta

    ajeno = str(_uuid4())
    origen = {
        ajeno: {
            "id": ajeno,
            "tenant_id": str(_uuid4()),
            "nombre": "De otro cliente",
            "clave_canonica": "de-otro",
        }
    }
    with pytest.raises(Conflicto) as e:
        restaurar(db, Cuenta, origen=origen, ids=[ajeno], tenant_id=tenant_id, objeto="cuenta")
    assert e.value.error_code == "restaurar.otro_tenant"


def test_los_objetos_restaurables_salen_del_modelo() -> None:
    """Una lista escrita a mano se queda corta al primer modelo nuevo, y ese
    sería justo el que no se puede recuperar el día que alguien lo borre."""
    from crmcore.http.restauracion_router import objetos_restaurables

    objetos = objetos_restaurables()
    assert "cuentas" in objetos
    # Los catálogos de instalación quedan fuera: restaurarlos «para un tenant»
    # no significa nada.
    assert "modulos_publicados" not in objetos
