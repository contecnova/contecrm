"""Configuración como código, sagas con compensación y vistas servidas
(CRM-07.02.01.03, .04, .06, .07 · CRM-00.03.03.08, .09 · CRM-00.03.05.15 ·
CRM-00.03.02.13 · CRM-03.03.02.12 · CRM-00.02.03.08).

Un CRM configurable acaba siempre igual: alguien toca producción un viernes
porque «es un cambio pequeño», y a los tres meses nadie sabe qué hay configurado.
Y un pedido que se cobra toca cuatro servicios sin una transacción que los abarque.

Las pruebas van detrás de eso: lo que se toca a mano y no consta, el paquete que
se aplica a medias, la saga que dice estar compensada cuando ya mandó un correo,
y el formulario que se pinta mal en vez de no pintarse.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion

from services.automation import entornos_auto as auto
from services.metadata import entornos as ent
from services.metadata import vistas_servidas as vis
from services.orchestrator import sagas as sg


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── Empaquetar y promocionar (CRM-07.02.01.03, .04) ───────────────────────


@pytest.mark.db
def test_cada_empaquetado_es_una_version_nueva(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Sobrescribir la anterior dejaría sin sitio al que está desplegado en
    producción, y volver atrás exigiría reconstruirlo de memoria."""
    uno = ent.empaquetar(uow, nombre="base", contenido={"campos": [{"clave": "nif"}]})
    dos = ent.empaquetar(
        uow, nombre="base", contenido={"campos": [{"clave": "nif"}, {"clave": "cif"}]}
    )
    assert (uno.version, dos.version) == (1, 2)
    assert uno.huella != dos.huella


@pytest.mark.db
def test_un_paquete_con_cosas_que_no_se_saben_aplicar_se_rechaza(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Aceptarlas dejaría un paquete que se despliega a medias y nadie sabe qué
    parte quedó fuera."""
    with pytest.raises(ErrorValidacion) as fallo:
        ent.empaquetar(uow, nombre="raro", contenido={"lo_que_sea": []})
    assert fallo.value.error_code == "entornos.contenido_desconocido"


def test_la_huella_no_cambia_por_el_orden_de_las_claves() -> None:
    """Si cambiara, el drift saltaría cada día sin que nadie hubiera tocado
    nada — y entonces se deja de mirar."""
    a = ent.huella_de({"campos": [{"clave": "x"}], "vistas": []})
    b = ent.huella_de({"vistas": [], "campos": [{"clave": "x"}]})
    assert a == b


@pytest.mark.db
def test_un_cambio_de_tipo_no_se_aplica_sin_que_alguien_lo_mire(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Lo que en pruebas era un campo nuevo puede ser en producción uno que ya
    existe con otro tipo, y cambiarlo con datos dentro puede perderlos."""
    paquete = ent.empaquetar(
        uow, nombre="p", contenido={"campos": [{"clave": "importe", "tipo": "texto"}]}
    )
    salida = ent.simular_promocion(
        uow.db,
        tenant_id,
        paquete_id=paquete.id,
        hacia="produccion",
        estado_actual={"campos": [{"clave": "importe", "tipo": "decimal"}]},
    )
    assert salida["se_puede_aplicar"] is False
    assert "puede perderlos" in salida["chocan"][0]["porque"]


# ── Drift (CRM-07.02.01.06) ───────────────────────────────────────────────


@pytest.mark.db
def test_sin_paquete_desplegado_no_se_dice_que_esta_limpio(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """No significa que no se haya tocado: significa que no se sabe."""
    salida = ent.medir_drift(uow.db, tenant_id, entorno="produccion", estado_actual={})
    assert salida["medible"] is False
    assert "no se sabe" in salida["porque"]


@pytest.mark.db
def test_lo_tocado_a_mano_aparece_con_su_campo(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Comparar dos entornos dice en qué se diferencian; comparar contra lo
    desplegado dice qué tocó alguien a mano, que es la pregunta."""
    paquete = ent.empaquetar(
        uow,
        nombre="p",
        contenido={"campos": [{"clave": "nif", "obligatorio": False}]},
    )
    ent.desplegar(uow, paquete_id=paquete.id, entorno="produccion")

    salida = ent.medir_drift(
        uow.db,
        tenant_id,
        entorno="produccion",
        estado_actual={"campos": [{"clave": "nif", "obligatorio": True}]},
    )
    assert salida["limpio"] is False
    assert salida["tocado_a_mano"][0]["campos"] == ["obligatorio"]


@pytest.mark.db
def test_lo_que_desaparecio_tambien_es_drift(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Alguien lo borró, y eso es drift igual aunque no lo parezca."""
    paquete = ent.empaquetar(uow, nombre="p", contenido={"campos": [{"clave": "nif"}]})
    ent.desplegar(uow, paquete_id=paquete.id, entorno="produccion")
    salida = ent.medir_drift(uow.db, tenant_id, entorno="produccion", estado_actual={"campos": []})
    assert salida["desaparecido"] == ["campos.nif"]


# ── Volver atrás (CRM-07.02.01.07) ────────────────────────────────────────


@pytest.mark.db
def test_volver_atras_reaplica_el_anterior_entero(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Deshacer cambio a cambio falla en cuanto hay dependencias y deja el
    entorno en un estado que no ha existido nunca."""
    uno = ent.empaquetar(uow, nombre="p", contenido={"campos": [{"clave": "a"}]})
    dos = ent.empaquetar(uow, nombre="p", contenido={"campos": [{"clave": "a"}, {"clave": "b"}]})
    ent.desplegar(uow, paquete_id=uno.id, entorno="produccion")
    ent.desplegar(uow, paquete_id=dos.id, entorno="produccion")

    salida = ent.volver_atras(uow, entorno="produccion", motivo="rompió el alta")
    assert salida["es_vuelta_atras"] is True
    assert salida["version"] == 1


@pytest.mark.db
def test_volver_atras_exige_motivo(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    paquete = ent.empaquetar(uow, nombre="p", contenido={"campos": [{"clave": "a"}]})
    ent.desplegar(uow, paquete_id=paquete.id, entorno="produccion")
    with pytest.raises(ErrorValidacion):
        ent.volver_atras(uow, entorno="produccion", motivo="  ")


@pytest.mark.db
def test_sin_despliegue_anterior_no_hay_vuelta_atras(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    paquete = ent.empaquetar(uow, nombre="p", contenido={"campos": [{"clave": "a"}]})
    ent.desplegar(uow, paquete_id=paquete.id, entorno="pruebas")
    with pytest.raises(Conflicto):
        ent.volver_atras(uow, entorno="pruebas", motivo="x")


# ── Automatizaciones: prueba en seco y promoción (CRM-00.03.03.08, .09) ───


def test_la_prueba_en_seco_dice_a_cuantos_afectaria() -> None:
    """Es el número que para una mano: nadie activa una regla cuando ve
    «afectaría a 19.480 registros»."""
    salida = auto.probar_en_seco(
        nombre="avisar_vencidas",
        afectados=[{"objeto": "actividad", "id": str(uuid4())} for _ in range(600)],
        acciones=[{"tipo": "enviar_correo"}],
    )
    assert salida["afectaria_a"] == 600
    assert salida["es_masiva"] is True
    assert salida["correos_que_saldrian"] == 600


def test_la_prueba_en_seco_no_hace_nada() -> None:
    salida = auto.probar_en_seco(
        nombre="x", afectados=[{"objeto": "cuenta", "id": "1"}], acciones=[{"tipo": "actualizar"}]
    )
    assert salida["en_seco"] is True


def test_no_se_promociona_a_produccion_sin_probar_en_seco() -> None:
    """La prueba cuesta un minuto; la regla que manda cuatro mil correos cuesta
    una semana de explicaciones."""
    with pytest.raises(Conflicto) as fallo:
        auto.promocionar(
            definicion={"clave": "x"}, desde="pruebas", hacia="produccion", probada_en_seco=False
        )
    assert fallo.value.error_code == "automatizacion.sin_prueba"


def test_promocionar_no_copia_el_estado() -> None:
    """Copiarlo haría que la de producción creyera haber hecho ya el trabajo que
    hizo la de pruebas, y se saltaría justo los registros que tiene que tocar."""
    salida = auto.promocionar(
        definicion={"clave": "x", "procesados": 500, "ultima_ejecucion": "ayer"},
        desde="pruebas",
        hacia="produccion",
        probada_en_seco=True,
    )
    assert "procesados" not in salida["definicion"]
    assert salida["llega_activa"] is False


def test_una_plantilla_de_automatizaciones_llega_apagada() -> None:
    """Una biblioteca que instala reglas activas empieza a mandar correos en
    cuanto alguien la mira por curiosidad."""
    salida = auto.instalar_plantilla(
        plantilla={"clave": "industrial", "reglas": [{"clave": "r1"}, {"clave": "r2"}]},
        existentes=["r2"],
    )
    assert salida["todas_apagadas"] is True
    assert salida["instaladas"] == ["r1"]
    assert salida["saltadas"] == ["r2"]


# ── Sagas con compensación (CRM-03.03.02.12) ──────────────────────────────


def _pasos_pedido() -> list[dict[str, Any]]:
    return [
        {
            "nombre": "reservar_stock",
            "servicio": "sales",
            "compensacion": {"accion": "liberar_stock"},
        },
        {"nombre": "cobrar", "servicio": "billing", "compensacion": {"accion": "devolver"}},
        {"nombre": "avisar_cliente", "servicio": "identity"},
    ]


@pytest.mark.db
def test_lo_irreversible_antes_del_final_se_avisa(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Si algo falla después, la saga se compensa entera menos eso: habrá avisado
    al cliente de algo que no ha pasado."""
    pasos = [
        {"nombre": "avisar_cliente", "servicio": "identity"},
        {"nombre": "cobrar", "servicio": "billing", "compensacion": {"accion": "devolver"}},
    ]
    salida = sg.iniciar(uow, clave="order_to_cash", pasos=pasos)
    assert salida["irreversibles_antes_del_final"] == [1]
    assert "va al final" in salida["aviso"]


@pytest.mark.db
def test_al_fallar_se_compensa_hacia_atras(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Deshacer el primero antes que el tercero deja el tercero apuntando a algo
    que ya no está."""
    salida = sg.iniciar(uow, clave="order_to_cash", pasos=_pasos_pedido())
    saga_id = UUID(salida["saga_id"])
    sg.marcar_hecho(uow, saga_id=saga_id, orden=1)
    sg.marcar_hecho(uow, saga_id=saga_id, orden=2)

    resultado = sg.fallar(uow, saga_id=saga_id, orden=3, error="el cliente no existe")
    assert resultado["compensados"] == [2, 1]
    assert resultado["limpia"] is True


@pytest.mark.db
def test_lo_que_no_se_puede_compensar_deja_la_saga_atascada(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Decir que está compensada haría que nadie se fiara de esa palabra."""
    pasos = [
        {"nombre": "avisar_cliente", "servicio": "identity"},
        {"nombre": "cobrar", "servicio": "billing", "compensacion": {"accion": "devolver"}},
    ]
    salida = sg.iniciar(uow, clave="raro", pasos=pasos)
    saga_id = UUID(salida["saga_id"])
    sg.marcar_hecho(uow, saga_id=saga_id, orden=1)

    resultado = sg.fallar(uow, saga_id=saga_id, orden=2, error="la pasarela falló")
    assert resultado["estado"] == "atascada"
    assert resultado["limpia"] is False
    assert resultado["sin_compensar"][0]["nombre"] == "avisar_cliente"


@pytest.mark.db
def test_una_saga_sin_pasos_no_arranca(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    with pytest.raises(ErrorValidacion):
        sg.iniciar(uow, clave="x", pasos=[])


# ── Migración de instancias en vuelo (CRM-00.03.02.13) ────────────────────


@pytest.mark.db
def test_las_instancias_en_vuelo_terminan_con_su_version(
    uow: UnidadDeTrabajo, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Cambiarles el guion a la mitad las deja en un paso que en la nueva no
    existe, y entonces ni avanzan ni se pueden cancelar limpiamente."""
    arrancada = sg.iniciar(uow, clave="order_to_cash", pasos=_pasos_pedido(), version_proceso=1)
    # Se avanza el primer paso para que el pendiente sea «cobrar», que es el que
    # la versión nueva no tiene: con la instancia parada en el primero no habría
    # nada que comprobar, porque ese paso sigue existiendo.
    sg.marcar_hecho(uow, saga_id=UUID(arrancada["saga_id"]), orden=1)

    salida = sg.plan_de_migracion(
        uow.db,
        tenant_id,
        clave="order_to_cash",
        version_nueva=2,
        pasos_nuevos=["reservar_stock", "facturar"],
    )
    assert salida["en_vuelo"] == 1
    assert salida["se_pueden_migrar_todas"] is False
    assert "terminan con SU versión" in salida["que_pasa"]


# ── Plantillas de flujo (CRM-00.03.05.15) ─────────────────────────────────


@pytest.mark.db
def test_una_plantilla_de_flujo_se_clona_y_no_se_hereda(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Si heredara, mejorar la plantilla cambiaría los procesos que ya están
    corriendo en veinte clientes."""
    uow.db.add(
        sg.PlantillaFlujo(
            clave="alta_cliente",
            sector="industrial",
            nombre="Alta de cliente industrial",
            definicion={"pasos": ["verificar", "aprobar"]},
            no_resuelve=["La aprobación de riesgo la decide cada empresa"],
        )
    )
    uow.db.flush()

    salida = sg.clonar_plantilla(uow, clave="alta_cliente", nombre_destino="Mi alta")
    assert salida["es_copia_independiente"] is True
    assert salida["no_resuelve"]


@pytest.mark.db
def test_el_clon_necesita_nombre_propio(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Si se queda con el de la plantilla, nadie sabe después cuál es el suyo y
    cuál el de fábrica."""
    uow.db.add(sg.PlantillaFlujo(clave="x", nombre="X", definicion={"pasos": []}))
    uow.db.flush()
    with pytest.raises(ErrorValidacion):
        sg.clonar_plantilla(uow, clave="x", nombre_destino="  ")


# ── Vistas servidas (CRM-00.02.03.08, CRM-00.04.03.01) ────────────────────


def test_un_tipo_desconocido_no_cae_a_caja_de_texto() -> None:
    """Caer a texto deja escribir «mañana» en un campo de fecha, y eso se
    descubre meses después al intentar ordenar por esa columna."""
    with pytest.raises(ErrorValidacion) as fallo:
        vis.componente_de("lo_que_sea")
    assert fallo.value.error_code == "vistas.tipo_sin_componente"


def test_los_campos_sin_permiso_no_viajan_al_navegador() -> None:
    """Mandarlos y esconderlos en el front deja el dato viajando: basta con abrir
    las herramientas de desarrollo."""
    salida = vis.servir_formulario(
        objeto="cuenta",
        campos=[
            {"clave": "nombre", "tipo": "texto"},
            {"clave": "margen", "tipo": "decimal", "permiso": "finanzas:read"},
        ],
        permisos_del_usuario={"account:read"},
    )
    claves = [c["clave"] for c in salida["campos"]]
    assert claves == ["nombre"]
    assert salida["campos_ocultos_por_permisos"] == 1


def test_un_front_viejo_sabe_que_no_sabe_pintarlo() -> None:
    """Pintarlo mal es peor que no pintarlo: un selector dibujado como caja de
    texto guarda lo que el usuario escriba."""
    salida = vis.comprobar_compatibilidad(
        version_del_front=1,
        definicion={"version_contrato": 2, "campos": [{"componente": "texto"}]},
    )
    assert salida["compatible"] is False
    assert "no intentarlo" in salida["que_hacer"]


def test_un_obligatorio_escondido_en_una_pestana_se_caza() -> None:
    """El formulario no se puede guardar y el usuario no ve por qué: el error
    sale abajo y el campo está en otra pantalla."""
    salida = vis.validar_diseno(
        campos=[{"clave": "nif", "obligatorio": True, "en_pestana_secundaria": True}],
        secciones=[{"clave": "general"}],
    )
    assert salida["valido"] is False
    assert "otra pantalla" in salida["problemas"][0]["consecuencia"]


def test_un_formulario_sin_obligatorios_se_avisa() -> None:
    """Es la forma más silenciosa de llenar el CRM de registros que no sirven."""
    salida = vis.validar_diseno(
        campos=[{"clave": "notas", "obligatorio": False}], secciones=[{"clave": "general"}]
    )
    assert salida["sin_campos_obligatorios"] is True
    assert salida["aviso"]
