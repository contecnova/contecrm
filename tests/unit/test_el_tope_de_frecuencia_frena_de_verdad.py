"""El tope de frecuencia existía, se configuraba, salía en pantalla y no frenaba
nada (`CRM-02.03.01`, `CRM-02.02.02`).

Medido el 05-10-2026. `comprobar_fatiga` lee la tabla `contactos_enviados` para
decidir si hoy se le puede escribir a alguien. Quien la llena es `anotar_envio`,
y **no la llamaba nadie**: la tabla estaba siempre vacía, así que la respuesta
era «permitido» siempre, para todo el mundo y todos los días.

El síntoma no es un error. Es que quien ha entrado en cinco recorridos recibe
los cinco correos el mismo día, se da de baja, y el tope que existía para evitar
exactamente eso figura configurado en la pantalla de ajustes.

Aquí van también las otras dos piezas del mismo módulo que no llamaba nadie:
los tokens sin sustituir y el recorte del perfil del autor de una mención.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from sqlalchemy import select

from services.marketing import campanas as cmp
from services.marketing import recorridos as rec


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _plantilla(uow: UnidadDeTrabajo, **kw: Any) -> Any:
    from services.marketing import correo as cor

    base: dict[str, Any] = {
        "clave": "oferta",
        "nombre": "Oferta",
        "asunto": "Hola {{nombre}}",
        "clase": "promocional",
        "bloques": [{"bloque": "cuerpo"}],
        "categoria": "novedades",
    }
    base.update(kw)
    fila = cor.PlantillaMarketing(tenant_id=uow.tenant_id, **base)
    uow.db.add(fila)
    uow.db.flush()
    return fila


NODOS = {
    "bienvenida": {"tipo": "accion", "accion": "email", "siguiente": "fin"},
    "fin": {"tipo": "fin"},
}


def _publicado(uow: UnidadDeTrabajo) -> Any:
    fila, _ = rec.crear(
        uow,
        clave=f"r{uuid4().hex[:8]}",
        nombre="Bienvenida",
        nodos=NODOS,
        inicio="bienvenida",
    )
    rec.publicar(uow, fila.id)
    return fila


def _alcanzable(uow: UnidadDeTrabajo) -> UUID:
    """Un contacto con dirección: sin perfil no se le puede escribir, y entonces
    el recorrido se salta el envío y la prueba mediría otra cosa."""
    from services.marketing.modelos import PerfilMarketing

    quien = uuid4()
    uow.db.add(
        PerfilMarketing(
            tenant_id=uow.tenant_id,
            objeto="contacto",
            objeto_id=quien,
            email=f"{quien.hex[:8]}@cliente.com",
        )
    )
    uow.db.flush()
    return quien


def test_ejecutar_una_accion_deja_constancia_del_envio(uow: UnidadDeTrabajo) -> None:
    """**Esta es la prueba del agujero.**

    Sin esta fila, `comprobar_fatiga` no tiene nada que contar y contesta
    «permitido» siempre: el tope de frecuencia no frena ni un correo.
    """
    recorrido = _publicado(uow)
    quien = _alcanzable(uow)
    rec.entrar(uow, recorrido.id, objeto_id=quien)
    rec.avanzar(uow, uow.tenant_id)

    enviados = (
        uow.db.execute(select(cmp.ContactoEnviado).where(cmp.ContactoEnviado.objeto_id == quien))
        .scalars()
        .all()
    )
    assert len(enviados) == 1, "el recorrido ha mandado y no ha quedado constancia"
    assert enviados[0].canal == "email"
    assert enviados[0].transaccional is False, (
        "contarlo como transaccional lo dejaría fuera del tope, que es la forma "
        "elegante de que el tope siga sin existir"
    )


def test_con_el_envio_apuntado_el_tope_pasa_a_decir_que_no(uow: UnidadDeTrabajo) -> None:
    """Lo que se gana con lo anterior: la decisión cambia.

    Antes decía «permitido» con el tope puesto a uno y con un envío hecho, que
    es la definición de un control decorativo.
    """
    quien = uuid4()
    uow.db.add(cmp.ReglaFatiga(tenant_id=uow.tenant_id, canal="email", maximo=1, ventana_dias=7))
    uow.db.flush()
    antes = cmp.comprobar_fatiga(uow.db, uow.tenant_id, quien, canal="email")
    cmp.anotar_envio(uow.db, uow.tenant_id, objeto_id=quien, canal="email")
    uow.db.flush()
    despues = cmp.comprobar_fatiga(uow.db, uow.tenant_id, quien, canal="email")
    assert antes["permitido"] is True
    assert despues["permitido"] is False, "con el tope a uno y un envío hecho sigue diciendo que sí"


# ── Las otras del mismo módulo que no llamaba nadie ───────────────────────


def test_la_comprobacion_previa_caza_un_token_sin_sustituir(uow: UnidadDeTrabajo) -> None:
    """`comprobar_envio` se anuncia como «todo lo que hay que mirar antes de
    mandar, en una llamada» y dejaba pasar el caso más visible de todos.

    Un «Hola {{nombre}}» sin sustituir no es un fallo técnico: es un correo que
    dice en voz alta que es automático, y lo reciben miles de personas a la vez.
    """
    from services.marketing import correo as cor

    _plantilla(uow, clave="bienvenida", nombre="Bienvenida")
    salida = cor.comprobar_envio(
        uow.db,
        uow.tenant_id,
        email="ana@cliente.com",
        plantilla_clave="bienvenida",
        idioma="es",
        datos={},
    )
    assert salida["se_puede_mandar"] is False
    assert any("token" in m.lower() for m in salida["motivos"])


def test_sin_datos_no_se_inventa_un_rojo(uow: UnidadDeTrabajo) -> None:
    """Decir que faltan todos los tokens cuando no hay con qué comprobarlos es
    un falso rojo, y un falso rojo acaba con la comprobación desactivada."""
    from services.marketing import correo as cor

    _plantilla(uow, clave="sinDatos", nombre="Sin datos")
    salida = cor.comprobar_envio(
        uow.db, uow.tenant_id, email="ana@cliente.com", plantilla_clave="sinDatos", idioma="es"
    )
    assert salida["tokens"] is None
    assert not any("token" in m.lower() for m in salida["motivos"])


def test_el_contenido_web_viene_con_los_empates_de_prioridad() -> None:
    """Dos reglas que encajan a la vez hacen que el contenido dependa del orden
    en que lleguen de la base: cambia solo, nadie lo reproduce y se culpa a la
    caché. Van CON el contenido: en otra llamada no los pide nadie."""
    from services.marketing import audiencias_externas as aud

    salida = aud.contenido_para(
        visitante={"contacto_id": "c1", "sector": "pyme"},
        reglas=[
            {"nombre": "A", "campo": "sector", "valor": "pyme", "contenido": "a", "prioridad": 1},
            {"nombre": "B", "campo": "sector", "valor": "pyme", "contenido": "b", "prioridad": 1},
        ],
    )
    assert salida["personalizado"] is True
    assert salida["empates_de_prioridad"]


def test_una_sola_definicion_de_que_base_habilita_publicidad() -> None:
    """El camino de uno en uno y el del lote tienen que decir lo mismo.

    Dos comprobaciones de la misma regla acaban diciendo cosas distintas, y la
    que se queda corta es siempre la del lote — que es justo la que manda miles
    de direcciones a una red de anuncios.
    """
    import inspect

    from services.marketing import audiencias_externas as aud

    fuente = inspect.getsource(aud.preparar_audiencia)
    assert (
        "exigir_base_publicitaria(" in fuente
    ), "el camino del lote ha vuelto a tener su propia copia de la condición"


def test_clasificar_una_mencion_no_se_queda_el_perfil_entero() -> None:
    """Un perfil público sigue siendo dato personal.

    Traerse su biografía, su foto y su historial «por contexto» crea la ficha de
    alguien que nunca nos dio nada, y esa ficha hay que protegerla, conservarla
    y borrarla como cualquier otra.
    """
    from services.marketing import social as soc

    salida = soc.clasificar(
        mencion={
            "texto": "qué mal servicio",
            "tipo": "queja",
            "autor": {
                "usuario": "@ana",
                "biografia": "Madre de dos, amante de los gatos",
                "foto": "https://red/ana.jpg",
            },
        }
    )
    assert "biografia" not in salida["autor"]
    assert salida["descartado_del_autor"], "no dice qué se ha tirado del perfil"
