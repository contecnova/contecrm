"""El mapa de territorios replicado, y las políticas que no se podían declarar
(CRM-00.05.02.07, CRM-00.05.01.09, CRM-00.05.02.20, CRM-00.05.03.03).

**El circuito del territorio estaba abierto por los dos extremos.**
`visibilidad.py` de ventas resuelve el acceso por territorio contra una tabla
replicada, y esa tabla **no la escribía nadie**: `territory.published` lo emitía
`sales` y no lo consumía ningún servicio. Así que esa vía devolvía siempre el
conjunto vacío — un comercial cuyo acceso venía de su territorio no veía nada por
ahí, sin error y sin que la pantalla lo dijera.

Y aunque alguien lo hubiera consumido, **no le habría servido**: el evento
llevaba la clave y la versión, y con eso no se puede replicar nada. Ni el
identificador, ni de quién cuelga, ni quién lo trabaja. Faltaba además la puerta
para añadir o quitar miembros, así que la tabla de miembros estaba vacía también.

Lo demás son tres decisiones que estaban escritas y no se podían pedir: la
comprobación de la lista de direcciones de una clave de API, la política de
dimensión y la excepción por campo.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


def _territorio(uow: Any, clave: str, responsable: UUID | None = None) -> Any:
    from services.sales.territorios import Territorio

    fila = Territorio(
        tenant_id=uow.tenant_id,
        clave=clave,
        nombre=clave.title(),
        responsable_id=responsable,
        criterios=[{"tipo": "geografia", "condiciones": [{"campo": "pais", "valor": "ES"}]}],
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── El evento lleva lo que un réplica necesita ────────────────────────────


def test_el_evento_del_territorio_lleva_con_que_replicarlo(uow: Any) -> None:
    """Llevaba la clave y la versión. Con eso no se puede replicar nada: ni el
    identificador, ni de quién cuelga, ni quién lo trabaja."""
    from services.sales import territorios as ter

    jefe = uuid4()
    norte = _territorio(uow, "norte", responsable=jefe)
    salida = ter.publicar(uow, norte.id)

    assert salida["usuarios"] == 1
    emitido = [e for e in uow._pendientes if e.get("tipo") == "territory.published"][-1]
    assert emitido["data"]["territorio_id"] == str(norte.id)
    assert emitido["data"]["usuarios"] == [str(jefe)]
    assert "padre_id" in emitido["data"]


def test_el_responsable_cuenta_como_quien_lo_trabaja(uow: Any) -> None:
    """Tenerlo fuera obligaría a cada lector a acordarse de sumarlo, que es la
    clase de cosa que uno de los lectores olvida."""
    from services.sales import territorios as ter

    jefe, comercial = uuid4(), uuid4()
    norte = _territorio(uow, "norte", responsable=jefe)
    ter.publicar(uow, norte.id)
    ter.anadir_miembro(uow, territorio_id=norte.id, usuario_id=comercial)

    assert set(ter.miembros_de(uow.db, uow.tenant_id, norte.id)) == {jefe, comercial}


def test_anadir_un_miembro_vuelve_a_publicar(uow: Any) -> None:
    """Sin republicar queda apuntado en el maestro y sin efecto en ninguna
    pantalla, que es peor que no poder añadirlo porque parece hecho."""
    from services.sales import territorios as ter

    norte = _territorio(uow, "norte", responsable=uuid4())
    ter.publicar(uow, norte.id)
    antes = len([e for e in uow._pendientes if e.get("tipo") == "territory.published"])

    salida = ter.anadir_miembro(uow, territorio_id=norte.id, usuario_id=uuid4())
    assert salida["publicado"] is True
    assert len([e for e in uow._pendientes if e.get("tipo") == "territory.published"]) == antes + 1


def test_un_territorio_sin_publicar_no_empieza_a_asignar(uow: Any) -> None:
    """Publicarlo es una decisión que se toma una vez, y adelantarla al añadir un
    miembro haría que un mapa a medio montar empezara a asignar cuentas."""
    from services.sales import territorios as ter

    norte = _territorio(uow, "norte")
    salida = ter.anadir_miembro(uow, territorio_id=norte.id, usuario_id=uuid4())

    assert salida["publicado"] is False
    assert not [e for e in uow._pendientes if e.get("tipo") == "territory.published"]


def test_quitar_a_alguien_tambien_se_propaga(uow: Any) -> None:
    """Un alta que se propaga y una baja que no es la forma más silenciosa de que
    alguien siga viendo la cartera de la que ya no se ocupa."""
    from services.sales import territorios as ter

    norte = _territorio(uow, "norte", responsable=uuid4())
    quien = uuid4()
    ter.publicar(uow, norte.id)
    ter.anadir_miembro(uow, territorio_id=norte.id, usuario_id=quien)

    salida = ter.quitar_miembro(uow, territorio_id=norte.id, usuario_id=quien)
    assert salida["quitados"] == 1
    assert salida["publicado"] is True
    ultimo = [e for e in uow._pendientes if e.get("tipo") == "territory.published"][-1]
    assert str(quien) not in ultimo["data"]["usuarios"]


# ── El consumidor llena la copia replicada ────────────────────────────────


def _mensaje(tenant_id: UUID, datos: dict[str, Any]) -> dict[str, Any]:
    return {"tipo": "territory.published", "tenant_id": str(tenant_id), "data": datos}


async def _consumir(tenant_id: UUID, datos: dict[str, Any]) -> None:
    from services.sales.consumidores import consumir_territorio

    await consumir_territorio(_mensaje(tenant_id, datos))


@pytest.mark.asyncio
async def test_sin_consumidor_el_acceso_por_territorio_es_vacio(db: Any, tenant_id: UUID) -> None:
    """Es lo que pasaba: la tabla no la escribía nadie y la vía devolvía siempre
    el conjunto vacío, sin error."""
    from crmcore.authz.jerarquia import territorios_de

    alguien = uuid4()
    assert territorios_de(db, tenant_id, alguien) == set()

    territorio = uuid4()
    await _consumir(
        tenant_id,
        {
            "territorio": "norte",
            "version": 1,
            "territorio_id": str(territorio),
            "padre_id": "",
            "usuarios": [str(alguien)],
        },
    )
    assert territorios_de(db, tenant_id, alguien) == {territorio}


@pytest.mark.asyncio
async def test_quien_sale_del_mapa_deja_de_verlo(db: Any, tenant_id: UUID) -> None:
    """Replicar solo las altas dejaría a quien deja un territorio viendo su
    cartera para siempre, que es la mitad que de verdad importa."""
    from crmcore.authz.jerarquia import territorios_de

    territorio = uuid4()
    uno, dos = uuid4(), uuid4()
    base = {"territorio": "norte", "version": 1, "territorio_id": str(territorio), "padre_id": ""}

    await _consumir(tenant_id, {**base, "usuarios": [str(uno), str(dos)]})
    assert territorios_de(db, tenant_id, uno) == {territorio}

    await _consumir(tenant_id, {**base, "version": 2, "usuarios": [str(dos)]})
    assert territorios_de(db, tenant_id, uno) == set()
    assert territorios_de(db, tenant_id, dos) == {territorio}


@pytest.mark.asyncio
async def test_un_evento_sin_identificador_no_adivina(db: Any, tenant_id: UUID) -> None:
    """Adivinar por la clave mezclaría dos territorios que se llamen parecido."""
    from crmcore.authz.jerarquia import TerritorioReplicado
    from sqlalchemy import func, select

    antes = db.execute(select(func.count()).select_from(TerritorioReplicado)).scalar_one()
    await _consumir(tenant_id, {"territorio": "norte", "version": 1, "usuarios": [str(uuid4())]})
    assert db.execute(select(func.count()).select_from(TerritorioReplicado)).scalar_one() == antes


# ── La lista de direcciones de una clave de API (CRM-00.05.01.09) ─────────


def test_una_red_mal_escrita_se_rechaza_al_guardar(db: Any, tenant_id: UUID) -> None:
    """Descubierta en la primera llamada deja la integración caída y a nadie
    mirando, porque quien la configuró ya se fue."""
    from crmcore.errors import ErrorValidacion

    from services.identity.servicio import crear_clave_api

    with pytest.raises(ErrorValidacion) as fallo:
        crear_clave_api(
            db,
            tenant_id=tenant_id,
            nombre="integración",
            scopes=["account:read"],
            ips_permitidas=["10.0.0.300/8"],
        )
    assert fallo.value.error_code == "clave_api.ips_invalidas"


def test_una_lista_que_abre_a_todo_internet_se_dice(db: Any, tenant_id: UUID) -> None:
    """Avisar es más útil que prohibirlo: hay despliegues donde es legítimo
    durante una migración, y prohibirlo llevaría a desactivar la lista entera."""
    from crmcore.errors import ErrorValidacion

    from services.identity.servicio import crear_clave_api

    with pytest.raises(ErrorValidacion) as fallo:
        crear_clave_api(
            db,
            tenant_id=tenant_id,
            nombre="integración",
            scopes=["account:read"],
            ips_permitidas=["0.0.0.0/0"],
        )
    assert "no restringe nada" in str(fallo.value)


def test_una_lista_correcta_pasa(db: Any, tenant_id: UUID) -> None:
    from services.identity.servicio import crear_clave_api

    clave, secreto = crear_clave_api(
        db,
        tenant_id=tenant_id,
        nombre="integración",
        scopes=["account:read"],
        ips_permitidas=["10.0.0.0/8", "192.168.1.5"],
    )
    assert secreto
    assert clave.ips_permitidas == ["10.0.0.0/8", "192.168.1.5"]


# ── Políticas por dimensión y por campo ───────────────────────────────────


def test_la_politica_de_una_dimension_sale_escrita_siempre_igual() -> None:
    """Montarlas a mano cada vez es lo que hace que una diga `=` y otra `en`, y
    que dos clientes con la misma regla se comporten distinto."""
    from crmcore.authz.politicas import politica_por_dimension

    salida = politica_por_dimension("pais", objeto="cuenta")
    assert salida["objeto"] == "cuenta"
    assert salida["condiciones"][0]["operador"] == "="
    assert salida["acciones"] == ["read", "write"]


def test_una_dimension_que_no_existe_se_dice() -> None:
    from crmcore.authz.politicas import politica_por_dimension
    from crmcore.errors import ErrorValidacion

    with pytest.raises(ErrorValidacion) as fallo:
        politica_por_dimension("color_favorito", objeto="cuenta")
    assert fallo.value.error_code == "politica.dimension_desconocida"


def test_la_excepcion_de_un_campo_queda_escrita(db: Any, tenant_id: UUID) -> None:
    """Una excepción que vive en la cabeza de quien la pidió es la que nadie
    revisa al año siguiente."""
    from crmcore.authz.proyeccion import fijar_politica_campo

    fila = fijar_politica_campo(
        db,
        tenant_id=tenant_id,
        objeto="contacto",
        campo="movil",
        nivel="claro",
        rol="soporte",
    )
    assert fila.campo == "movil"
    assert fila.nivel == "claro"
    assert fila.rol == "soporte"
