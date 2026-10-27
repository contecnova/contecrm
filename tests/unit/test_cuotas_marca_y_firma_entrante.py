"""El plan no acotaba nada, el panel enseñaba ceros y la firma no caducaba
(CRM-00.01.04.05, CRM-00.01.04.06, CRM-00.01.06.07, CRM-06.01.01.03).

Cuatro cosas que contestaban exactamente lo que contestarían si todo fuera bien.

**Las cuotas del plan no las aplicaba nadie.** Lo que corta de verdad lee los
ajustes, y los ajustes no sabían del plan: un plan vendido con 5.000 correos al
mes dejaba pasar cincuenta mil. La única función que miraba el plan la usaban dos
pantallas, y ninguna de las dos corta nada.

**El panel de consumo enseñaba cero de todo, siempre**, con los topes bien
puestos al lado — que es lo que lo hacía creíble. Leía una tabla de contadores
que sólo escribía una función sin llamantes. Y el componente de estado de la
plataforma, que lee lo mismo, no podía avisar de una cuota agotada ni queriendo.

**La marca blanca no tenía ni una ruta.** No faltaba una pieza: el módulo estaba
entero —los cuatro sitios por los que se escapa la marca del fabricante, el
contraste comprobado, el dominio que no se da por bueno hasta verificarlo— y era
inalcanzable desde fuera.

**Y la firma del chat entrante no caducaba.** Era una tercera implementación del
mismo HMAC, y la que menos se mira es la que se queda corta: no miraba el
instante, así que un mensaje capturado una vez valía para siempre — y lo que hay
al otro lado son cambios en el CRM.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


# ── Las cuotas del plan (CRM-00.01.04.05) ─────────────────────────────────


@pytest.fixture
def plan(db: Any) -> Any:
    from services.tenancy.modelos import Plan

    fila = Plan(
        codigo="pyme-2026",
        nombre="PYME",
        cuotas={"cuota_correos_mes": 5000, "cuota_registros": 10000},
    )
    db.add(fila)
    db.flush()
    return fila


def test_el_plan_acota_de_verdad(db: Any, plan: Any) -> None:
    """**Es el agujero.** Lo que corta lee los ajustes, y los ajustes no sabían
    del plan: un plan vendido con 5.000 correos dejaba pasar cincuenta mil."""
    from crmcore.cuotas import tope
    from crmcore.tenancy.context import con_contexto

    from services.tenancy.servicio import aplicar_cuotas_del_plan

    tenant_id = uuid4()
    with con_contexto(tenant_id=tenant_id, origen="prueba"):
        assert tope(db, tenant_id, "cuota_correos_mes") == 0, "partía ya con tope"

        salida = aplicar_cuotas_del_plan(db, tenant_id, plan_codigo="pyme-2026")
        assert "cuota_correos_mes" in salida["aplicadas"]

        # Y ahora el que corta lo ve.
        assert tope(db, tenant_id, "cuota_correos_mes") == 5000


def test_lo_negociado_a_mano_no_se_pisa(db: Any, plan: Any) -> None:
    """Un cliente al que se le subió el tope por una negociación no puede
    perderlo porque alguien le reasigne el mismo plan."""
    from crmcore.runtime import settings as rt
    from crmcore.tenancy.context import con_contexto

    from services.tenancy.servicio import aplicar_cuotas_del_plan

    tenant_id = uuid4()
    with con_contexto(tenant_id=tenant_id, origen="prueba"):
        rt.fijar(db, "cuota_correos_mes", 50000, ambito="tenant", ambito_id=str(tenant_id))

        salida = aplicar_cuotas_del_plan(db, tenant_id, plan_codigo="pyme-2026")

        assert "cuota_correos_mes" in salida["respetadas"]
        assert "cuota_correos_mes" not in salida["aplicadas"]
        assert int(rt.efectivo("cuota_correos_mes", db)) == 50000


def test_un_plan_que_no_existe_se_dice(db: Any) -> None:
    """Devolver «aplicadas: ninguna» sin decir por qué deja al tenant sin topes y
    a quien lo provisionó creyendo que los tiene."""
    from services.tenancy.servicio import aplicar_cuotas_del_plan

    salida = aplicar_cuotas_del_plan(db, uuid4(), plan_codigo="no-existe")
    assert salida["aplicadas"] == []
    assert "no existe" in salida["porque"]


def test_provisionar_un_tenant_le_pone_las_cuotas_de_su_plan(db: Any, plan: Any) -> None:
    """Ponerlas en una llamada aparte garantiza que al cuarto tenant se olvide."""
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.runtime import settings as rt
    from crmcore.tenancy.context import con_contexto

    from services.tenancy.servicio import crear_tenant

    uow = UnidadDeTrabajo(db=db, tenant_id=None)
    tenant = crear_tenant(uow, slug="acme-cuotas", nombre="Acme", plan="pyme-2026")

    with con_contexto(tenant_id=tenant.id, origen="prueba"):
        assert int(rt.efectivo("cuota_correos_mes", db)) == 5000


# ── El panel de consumo (CRM-00.01.06.07) ─────────────────────────────────


def test_el_consumo_sale_de_lo_medido_y_no_de_una_tabla_vacia(db: Any, tenant_id: UUID) -> None:
    """Enseñaba «0 de 5.000 correos» el mes que mandaste cuatro mil."""
    from crmcore.consumo import limpiar_medidores, medido_aqui, registrar_medidor

    limpiar_medidores()
    registrar_medidor("correos", lambda _db, _t: (4000, "cuota_correos_mes"))
    try:
        filas = {f["metrica"]: f for f in medido_aqui(db, tenant_id)}
    finally:
        limpiar_medidores()

    assert filas["correos"]["consumido"] == 4000, "el panel sigue leyendo una tabla vacía"


def test_una_metrica_rota_se_dice_en_su_fila_y_no_tumba_el_panel(db: Any, tenant_id: UUID) -> None:
    """Una métrica rota no puede dejar sin consumo a las otras cinco. Y «no se ha
    podido medir» no es «cero», que es justo la confusión que había."""
    from crmcore.consumo import limpiar_medidores, medido_aqui, registrar_medidor

    def _rota(_db: Any, _t: Any) -> tuple[int, str]:
        raise RuntimeError("se cayó")

    limpiar_medidores()
    registrar_medidor("buena", lambda _db, _t: (7, "cuota_registros"))
    registrar_medidor("rota", _rota)
    try:
        filas = {f["metrica"]: f for f in medido_aqui(db, tenant_id)}
    finally:
        limpiar_medidores()

    assert filas["buena"]["legible"] is True
    assert filas["rota"]["legible"] is False
    assert "consumido" not in filas["rota"]


def test_el_componente_de_estado_ya_puede_avisar(db: Any, tenant_id: UUID) -> None:
    """No podía: leía una tabla que no escribía nadie, así que devolvía «no hay
    nada que contar» en todos los despliegues y a todas horas."""
    from crmcore.consumo import limpiar_medidores, registrar_medidor
    from crmcore.runtime import settings as rt
    from crmcore.tenancy.context import con_contexto

    from services.tenancy.estado_componentes import cuotas

    limpiar_medidores()
    registrar_medidor("correos", lambda _db, _t: (990, "cuota_correos_mes"))
    try:
        with con_contexto(tenant_id=tenant_id, origen="prueba"):
            rt.fijar(db, "cuota_correos_mes", 1000, ambito="tenant", ambito_id=str(tenant_id))
            salida = cuotas(db, tenant_id)
    finally:
        limpiar_medidores()

    assert salida is not None, "el componente sigue sin poder ver nada"
    assert "correos" in str(salida)


# ── La marca blanca (CRM-00.01.04.06) ─────────────────────────────────────


def test_la_marca_no_se_activa_a_medias(db: Any, tenant_id: UUID) -> None:
    """Una marca blanca a medias es peor que ninguna: si se anuncia y el correo
    sale con el dominio del fabricante, la conversación que sigue no es sobre el
    correo."""
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.errors import Conflicto

    from services.tenancy import marca as mrc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    mrc.guardar(uow, tenant_id=tenant_id, nombre_producto="Acme CRM")

    with pytest.raises(Conflicto) as fallo:
        mrc.activar(uow, tenant_id=tenant_id)
    assert fallo.value.error_code == "marca.incompleta"


def test_el_dominio_no_se_da_por_bueno_solo(db: Any, tenant_id: UUID) -> None:
    """Un dominio sin verificar hace que los correos acaben en spam o que los
    enlaces no lleven a ninguna parte, y las dos cosas parecen un fallo del
    producto."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.tenancy import marca as mrc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    mrc.guardar(uow, tenant_id=tenant_id, dominio_propio="crm.acme.es")

    puntos = {f["punto"] for f in mrc.comprobar(db, tenant_id)["faltan"]}
    assert "dominio_enlaces" in puntos

    fila = mrc.verificar_dominio(
        uow, tenant_id=tenant_id, cual="propio", verificado=True, detalle="TXT encontrado"
    )
    assert fila.dominio_verificado is True
    assert "dominio_enlaces" not in {f["punto"] for f in mrc.comprobar(db, tenant_id)["faltan"]}


def test_lo_que_se_comprobo_queda_escrito(db: Any, tenant_id: UUID) -> None:
    """«Lo verificamos en su momento» no es una respuesta cuando un año después
    los correos empiezan a rebotar."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.tenancy import marca as mrc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    mrc.guardar(uow, tenant_id=tenant_id, dominio_propio="crm.acme.es")
    fila = mrc.verificar_dominio(
        uow, tenant_id=tenant_id, cual="propio", verificado=True, detalle="TXT=abc123"
    )
    assert "TXT=abc123" in str(fila.extra)


def test_solo_hay_dos_dominios(db: Any, tenant_id: UUID) -> None:
    """Admitir un tercero por error dejaría la verificación sin efecto sobre
    ninguno de los dos que importan."""
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.errors import ErrorValidacion

    from services.tenancy import marca as mrc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    mrc.guardar(uow, tenant_id=tenant_id, dominio_propio="crm.acme.es")

    with pytest.raises(ErrorValidacion) as fallo:
        mrc.verificar_dominio(uow, tenant_id=tenant_id, cual="otro", verificado=True)
    assert fallo.value.error_code == "marca.dominio_invalido"


def test_la_marca_blanca_tiene_puerta() -> None:
    """No faltaba una pieza: el módulo estaba entero y no tenía NI UNA ruta."""
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("SERVICE_NAME")
    os.environ["SERVICE_NAME"] = "tenancy"
    get_settings.cache_clear()
    try:
        import importlib

        app = importlib.import_module("services.tenancy.main").app
        rutas = set(app.openapi()["paths"])
    finally:
        if previo is None:
            os.environ.pop("SERVICE_NAME", None)
        else:
            os.environ["SERVICE_NAME"] = previo
        get_settings.cache_clear()

    assert "/api/v1/marca" in rutas
    assert "/api/v1/marca/activar" in rutas
    assert "/api/v1/marca/dominio/verificacion" in rutas


# ── La firma del chat entrante (CRM-06.01.01.03) ──────────────────────────


def _canal(db: Any, tenant_id: UUID, *, cabecera_momento: str = "") -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    from services.integration import colaboracion as colab

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    return colab.declarar_canal(
        uow,
        clave="equipo",
        url_entrante="https://chat.example/hook",
        secreto="un-secreto-largo",
        cabecera_momento=cabecera_momento,
        ordenes=["consultar"],
    )


def test_un_mensaje_viejo_ya_no_se_puede_reenviar(db: Any, tenant_id: UUID) -> None:
    """**Era lo que faltaba.** Quien pueda repetir una orden de chat podía
    repetirla mil veces, y lo que hay al otro lado son cambios en el CRM."""
    from crmcore.errors import NoAutenticado
    from crmcore.security.firma import firmar

    from services.integration import colaboracion as colab

    canal = _canal(db, tenant_id, cabecera_momento="x-timestamp")
    cuerpo = b'{"orden":"consultar"}'

    ahora = int(time.time())
    colab.comprobar_firma(
        canal, cuerpo=cuerpo, firma=firmar(cuerpo, canal.secreto, ahora), momento=ahora
    )

    viejo = ahora - 86_400
    with pytest.raises(NoAutenticado) as fallo:
        colab.comprobar_firma(
            canal, cuerpo=cuerpo, firma=firmar(cuerpo, canal.secreto, viejo), momento=viejo
        )
    assert fallo.value.error_code == "chat.firma_invalida"


def test_un_canal_sin_instante_sigue_funcionando_y_se_dice(db: Any, tenant_id: UUID) -> None:
    """Hay plataformas que no mandan marca de tiempo. Exigirla les cortaría el
    chat; callar que son reproducibles sería peor."""
    from services.integration import colaboracion as colab

    canal = _canal(db, tenant_id)
    cuerpo = b'{"orden":"consultar"}'
    firma = hmac.new(canal.secreto.encode(), cuerpo, hashlib.sha256).hexdigest()

    colab.comprobar_firma(canal, cuerpo=cuerpo, firma=firma)
    assert canal.cabecera_momento == ""


def test_una_firma_que_no_cuadra_se_rechaza_con_y_sin_instante(db: Any, tenant_id: UUID) -> None:
    from crmcore.errors import NoAutenticado

    from services.integration import colaboracion as colab

    cuerpo = b'{"orden":"consultar"}'
    for cabecera in ("", "x-timestamp"):
        canal = _canal(db, tenant_id, cabecera_momento=cabecera)
        with pytest.raises(NoAutenticado):
            colab.comprobar_firma(
                canal,
                cuerpo=cuerpo,
                firma="0" * 64,
                momento=int(time.time()) if cabecera else None,
            )


def test_un_instante_que_no_es_un_numero_se_dice(db: Any, tenant_id: UUID) -> None:
    """Tragárselo y verificar sin ventana convertiría un error de integración en
    una puerta abierta, en silencio."""
    from crmcore.errors import NoAutenticado

    from services.integration import colaboracion as colab

    canal = _canal(db, tenant_id, cabecera_momento="x-timestamp")
    with pytest.raises(NoAutenticado) as fallo:
        colab.comprobar_firma(canal, cuerpo=b"{}", firma="0" * 64, momento="ayer")
    assert fallo.value.error_code == "chat.momento_invalido"


def test_sin_firma_no_se_atiende(db: Any, tenant_id: UUID) -> None:
    """Un canal sin firma acepta cualquier POST de quien sepa la URL, y desde ahí
    se piden las mismas cosas que desde el CRM."""
    from crmcore.errors import NoAutenticado

    from services.integration import colaboracion as colab

    canal = _canal(db, tenant_id)
    with pytest.raises(NoAutenticado) as fallo:
        colab.comprobar_firma(canal, cuerpo=b"{}", firma="")
    assert fallo.value.error_code == "chat.sin_firma"


# ── El apunte de una ejecución de extensión (CRM-00.04.02.07) ─────────────


def test_el_apunte_lleva_la_entrada_y_dice_que_limite_se_paso() -> None:
    """«La extensión ha fallado» no deja arreglar nada. Y una que falla con un
    registro concreto y no guarda cuál obliga a reproducirlo a ciegas."""
    from services.automation import extensiones as ex

    salida = ex.resumen_de_ejecucion(
        clave="validar-nif",
        version=3,
        entrada={"cuenta_id": "abc"},
        consumo={"milisegundos": 999_999, "memoria_mb": 10, "llamadas_salientes": 1},
    )
    assert salida["entrada"] == {"cuenta_id": "abc"}
    assert salida["ok"] is False
    assert [e["limite"] for e in salida["excedidos"]] == ["milisegundos"]
    # La salida NO se guarda: puede llevar el registro entero.
    assert "salida" not in salida
    assert salida["salida_no_se_guarda"].strip()


def test_un_tenant_sin_marca_no_es_un_error(db: Any, tenant_id: UUID) -> None:
    """**No tener marca propia es el caso normal**, no un fallo.

    Devolvía 404 «Este tenant no tiene marca configurada», y el front pide esta
    ruta en CADA carga de página: todos los tenants que no la han configurado
    —o sea casi todos— veían un error rojo en la consola del navegador cada vez
    que entraban. Un error que se aprende a ignorar es donde se esconde el que
    sí importa.

    La respuesta correcta es el diagnóstico completo con los cuatro puntos de
    fuga pendientes y `aplicable` vacío, que es lo que el front ya sabe leer:
    sin marca que aplicar, se queda con la del despliegue.
    """
    from services.tenancy import marca as mrc

    salida = mrc.comprobar(db, tenant_id)
    assert salida["aplicable"] == {}, salida
    assert salida["se_puede_activar"] is False
    # Los cuatro puntos, cada uno con su motivo: un tenant sin marca no tiene
    # «nada pendiente», tiene todo pendiente.
    assert len(salida["faltan"]) == len(mrc.PUNTOS_DE_FUGA), salida["faltan"]
    assert "del despliegue" in salida["porque"]
