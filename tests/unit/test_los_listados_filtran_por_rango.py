"""Un listado que sólo filtra por igualdad no contesta «qué vence esta semana».

Los filtros de la URL eran **igualdad y nada más**, así que no había forma de
pedir un rango: ni «las actividades que vencen antes del viernes», ni «las
oportunidades de más de 50.000», ni «las que no están cerradas». Cualquier
pantalla que necesitara eso tenía dos salidas, y las dos malas: una ruta a
medida por pantalla —catorce rutas que hacen casi lo mismo— o traerse todas las
filas y filtrar en el navegador, que es traerse datos que no se van a enseñar.

Lo que se añade **no es una gramática nueva**. El motor de permisos ya tenía una
lista cerrada de operadores con su traductor a SQL, y su documentación explica
por qué no puede haber dos: con dos gramáticas se acaba con un listado que
enseña un registro que la ficha luego niega. Esto son nombres url-safe de esa
misma gramática.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db

AHORA = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def cliente(db: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.party.main")
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
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def tres_visitas(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> list[Any]:
    """Tres visitas: una de hace cinco días, una de hoy y una de dentro de una
    semana.

    Se prueba sobre **visitas** y no sobre actividades a propósito: el listado
    de actividades está escrito a mano con sus propios filtros y no pasa por la
    fábrica. Probar aquí lo que arregla la fábrica sobre un listado que no la
    usa habría dado verde sin que nada funcionara — o rojo culpando al cambio
    equivocado, que es lo que pasó al escribir esto.
    """
    from services.party.actividades_extra import Visita

    filas = []
    for notas, dias, distancia in (("vieja", -5, 10), ("hoy", 0, 120), ("lejana", 7, 1_500)):
        fila = Visita(
            tenant_id=tenant_id,
            usuario_id=uuid4(),
            notas=notas,
            distancia_m=distancia,
            entrada_at=AHORA + timedelta(days=dias),
        )
        db.add(fila)
        filas.append(fila)
    db.flush()
    return filas


def _notas(respuesta: Any) -> set[str]:
    assert respuesta.status_code == 200, respuesta.text
    return {f["notas"] for f in respuesta.json()["items"]}


# ── El recorrido mira de verdad ───────────────────────────────────────────


def test_sin_filtro_salen_las_tres(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    """La comprobación que hace honestas a las de abajo: si el listado
    devolviera vacío por otro motivo, todos los filtros «funcionarían»."""
    assert _notas(cliente.get("/api/v1/visitas", headers=cabeceras)) == {
        "vieja",
        "hoy",
        "lejana",
    }


# ── Los rangos ────────────────────────────────────────────────────────────


def test_lo_que_vence_antes_de_una_fecha(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    corte = quote((AHORA + timedelta(days=1)).isoformat())
    r = cliente.get(f"/api/v1/visitas?entrada_at__hasta={corte}", headers=cabeceras)
    assert _notas(r) == {"vieja", "hoy"}


def test_lo_que_vence_despues_de_una_fecha(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    corte = quote((AHORA + timedelta(days=1)).isoformat())
    r = cliente.get(f"/api/v1/visitas?entrada_at__desde={corte}", headers=cabeceras)
    assert _notas(r) == {"lejana"}


def test_los_dos_extremos_a_la_vez_acotan_una_ventana(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    """Es el caso de verdad —«esta semana»— y el que distingue un filtro de
    rango de dos filtros sueltos: tienen que componerse con Y, no pisarse."""
    desde = quote((AHORA - timedelta(days=1)).isoformat())
    hasta = quote((AHORA + timedelta(days=1)).isoformat())
    r = cliente.get(
        f"/api/v1/visitas?entrada_at__desde={desde}&entrada_at__hasta={hasta}",
        headers=cabeceras,
    )
    assert _notas(r) == {"hoy"}


def test_mayor_y_menor_son_estrictos(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    """`desde` incluye el extremo y `mayor` no. Confundirlos deja fuera —o
    mete— justo la fila del borde, que es la que alguien va a mirar."""
    exacto = quote((AHORA + timedelta(days=7)).isoformat())
    assert "lejana" in _notas(
        cliente.get(f"/api/v1/visitas?entrada_at__desde={exacto}", headers=cabeceras)
    )
    assert "lejana" not in _notas(
        cliente.get(f"/api/v1/visitas?entrada_at__mayor={exacto}", headers=cabeceras)
    )


# ── Los demás operadores ──────────────────────────────────────────────────


def test_distinto_deja_fuera_uno_solo(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    r = cliente.get("/api/v1/visitas?notas__distinto=hoy", headers=cabeceras)
    assert _notas(r) == {"vieja", "lejana"}


def test_en_admite_una_lista_por_comas(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    r = cliente.get("/api/v1/visitas?notas__en=vieja,lejana", headers=cabeceras)
    assert _notas(r) == {"vieja", "lejana"}


def test_vacio_y_no_vacio_no_necesitan_valor(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any], db: Any
) -> None:
    """Distinguir «sin cerrar» de «cerrada» es la pregunta que ordena una
    bandeja. Las tres visitas se crearon sin hora de salida, así que están
    todas abiertas; se cierra una y tienen que separarse."""
    tres_visitas[0].salida_at = AHORA
    db.flush()

    assert _notas(cliente.get("/api/v1/visitas?salida_at__no_vacio=1", headers=cabeceras)) == {
        "vieja"
    }
    assert _notas(cliente.get("/api/v1/visitas?salida_at__vacio=1", headers=cabeceras)) == {
        "hoy",
        "lejana",
    }


def test_el_rango_vale_igual_sobre_un_numero(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    """No es sólo para fechas: «de más de X» es la otra mitad de las preguntas
    —importe, distancia, días— y el valor se ata al tipo de su columna, así que
    `1500` llega como entero y no como el texto «1500»."""
    assert _notas(cliente.get("/api/v1/visitas?distancia_m__mayor=100", headers=cabeceras)) == {
        "hoy",
        "lejana",
    }
    assert _notas(cliente.get("/api/v1/visitas?distancia_m__hasta=120", headers=cabeceras)) == {
        "vieja",
        "hoy",
    }


def test_la_igualdad_de_siempre_sigue_igual(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    """Sin sufijo no cambia nada. Es lo que permite añadir esto sin tocar una
    sola llamada de las que ya había."""
    assert _notas(cliente.get("/api/v1/visitas?notas=hoy", headers=cabeceras)) == {"hoy"}


# ── Lo que NO se puede hacer ──────────────────────────────────────────────


def test_un_operador_inventado_se_rechaza_y_dice_cuales_valen(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    """**Es la mitad que importa.** Si `?importe__mayorque=1000` se tratara como
    igualdad —o se ignorara— el listado devolvería de más y parecería correcto,
    que es exactamente el fallo que ya costó caro con los filtros que no
    filtraban."""
    r = cliente.get("/api/v1/visitas?entrada_at__mayorque=x", headers=cabeceras)
    assert r.status_code == 422, r.text
    assert "hasta" in r.text and "desde" in r.text


def test_una_columna_inventada_sigue_rechazandose_aunque_traiga_operador(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    """El sufijo no puede ser una puerta trasera para colar un campo que no
    existe o que este principal no ve en claro."""
    r = cliente.get("/api/v1/visitas?inventado__hasta=3", headers=cabeceras)
    assert r.status_code == 422, r.text
    assert "inventado" in r.text


def test_en_sin_valores_se_rechaza(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    """Una lista vacía en SQL no devuelve nada, así que `?notas__en=` daría un
    listado vacío que parece «no hay resultados» cuando es «la consulta está
    mal escrita»."""
    r = cliente.get("/api/v1/visitas?notas__en=", headers=cabeceras)
    assert r.status_code == 422, r.text


def test_no_existe_contiene(cliente: Any, cabeceras: dict[str, str]) -> None:
    """En SQL depende del tipo de la columna y `a_sql` devuelve `None` a
    propósito en vez de inventarse una traducción aproximada. Si un día se
    añade, tendrá que ser con su traducción de verdad y no por descuido."""
    from crmcore.http.listados import OPERADORES_DE_URL

    assert "contiene" not in OPERADORES_DE_URL
    r = cliente.get("/api/v1/visitas?notas__contiene=ho", headers=cabeceras)
    assert r.status_code == 422, r.text


def test_la_gramatica_es_la_del_motor_de_permisos_y_no_otra() -> None:
    """Si alguien añade aquí un operador que `a_sql` no sabe traducir, el
    listado reventaría en ejecución con una condición vacía. Se comprueba
    contra la fuente, no contra una copia de la lista."""
    from crmcore.authz.abac import OPERADORES
    from crmcore.http.listados import OPERADORES_DE_URL

    assert set(OPERADORES_DE_URL.values()) <= set(OPERADORES)


def test_una_fecha_mal_escrita_es_un_422_y_no_un_500(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    """Un filtro mal escrito es un error de quien llama. Llegaba hasta Postgres
    y volvía como error interno —«invalid input syntax for type timestamp»—,
    que manda a mirar los registros del servidor para descubrir una errata.

    Ya pasaba con la igualdad de siempre: el rango no lo trae, lo destapa.
    """
    r = cliente.get("/api/v1/visitas?entrada_at__hasta=manzana", headers=cabeceras)
    assert r.status_code == 422, r.text
    assert "manzana" in r.text

    # Y lo mismo con un número y con un identificador.
    assert (
        cliente.get("/api/v1/visitas?distancia_m__mayor=lejos", headers=cabeceras).status_code
        == 422
    )
    assert (
        cliente.get("/api/v1/visitas?usuario_id=no-es-un-uuid", headers=cabeceras).status_code
        == 422
    )


def test_la_Z_de_UTC_se_entiende(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    """Medio mundo manda la hora en UTC con `Z`. Rechazarla sería un error que
    parece de formato y es de dialecto."""
    r = cliente.get("/api/v1/visitas?entrada_at__hasta=2026-10-27T09:00:00Z", headers=cabeceras)
    assert _notas(r) == {"vieja", "hoy"}


def test_un_desfase_que_llega_como_espacio_tambien(
    cliente: Any, cabeceras: dict[str, str], tres_visitas: list[Any]
) -> None:
    """El `+` de `+02:00` viaja como espacio en una query —lo dice el
    estándar— y quien lo manda sin codificar recibiría un error de formato que
    no entiende. Se admite esa forma y se dice aquí para que no parezca magia.
    """
    r = cliente.get(
        "/api/v1/visitas?entrada_at__hasta=2026-10-27T09:00:00 00:00", headers=cabeceras
    )
    assert _notas(r) == {"vieja", "hoy"}


# ── Lo que la ruta declara es de la ruta ──────────────────────────────────


@pytest.fixture
def cliente_ventas(db: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.sales.main").app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


def test_un_parametro_propio_y_vacio_no_se_convierte_en_filtro(
    cliente_ventas: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**La regresión que trajo el filtro genérico.**

    Los listados escritos a mano declaran sus propios parámetros, y el front
    manda `?estado=` para decir «todos los estados». Sin excluir lo que la ruta
    declara, eso se reinterpretaba como filtro: `WHERE estado = ''` —cero
    resultados— o un 422 «no se puede filtrar por estado» sobre un parámetro
    que la propia operación documenta.

    La ficha de cliente pedía exactamente así sus oportunidades.
    """
    from services.sales.modelos import Lead

    db.add(Lead(tenant_id=tenant_id, nombre="Uno", estado="nuevo"))
    db.flush()

    sin = cliente_ventas.get("/api/v1/leads", headers=cabeceras)
    con = cliente_ventas.get("/api/v1/leads?estado=", headers=cabeceras)
    assert sin.status_code == 200, sin.text
    assert con.status_code == 200, con.text
    assert len(con.json()["items"]) == len(sin.json()["items"]) == 1


def test_un_parametro_propio_CON_valor_sigue_filtrando_una_sola_vez(
    cliente_ventas: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Y no se desactiva: lo que la ruta declara lo aplica la ruta."""
    from services.sales.modelos import Lead

    db.add(Lead(tenant_id=tenant_id, nombre="Uno", estado="nuevo"))
    db.add(Lead(tenant_id=tenant_id, nombre="Dos", estado="descartado"))
    db.flush()

    r = cliente_ventas.get("/api/v1/leads?estado=nuevo", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert [f["nombre"] for f in r.json()["items"]] == ["Uno"]


def test_los_rangos_siguen_funcionando_al_lado_de_los_propios(
    cliente_ventas: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es la combinación real: la pantalla manda los suyos y además un rango."""
    from services.sales.modelos import Lead

    db.add(Lead(tenant_id=tenant_id, nombre="Uno", estado="nuevo", puntuacion=10))
    db.add(Lead(tenant_id=tenant_id, nombre="Dos", estado="nuevo", puntuacion=90))
    db.flush()

    r = cliente_ventas.get("/api/v1/leads?estado=nuevo&puntuacion__mayor=50", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert [f["nombre"] for f in r.json()["items"]] == ["Dos"]
