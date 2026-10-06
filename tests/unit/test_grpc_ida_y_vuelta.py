"""El transporte gRPC estaba encendido y no funcionaba (CRM-00.02.01.03).

El ajuste se leía, el servidor se levantaba y el contrato `.proto` se generaba y
se entregaba. Lo que no había era **la conversión**: el servidor declaraba
`request_deserializer=bytes` y `response_serializer=bytes`, así que el manejador
recibía `bytes` donde esperaba un mensaje —se quedaba con el cuerpo vacío, y un
`Create` por gRPC creaba un registro sin datos— y la respuesta ni siquiera
llegaba a serializarse, porque `bytes(diccionario)` revienta.

Las dos piezas que faltaban estaban escritas y sin llamante: `clase_de_objeto`,
que construye el mensaje del objeto desde el mismo esquema del que sale el
`.proto`, y `a_mensaje`, que lo rellena.

Y **los números del contrato no viajaban con el esquema**. Cada servicio los
habría recalculado al servir y le habrían salido otros: un número reutilizado no
rompe nada visible — el mensaje se decodifica, el valor entra en el campo
equivocado y nadie se entera hasta que alguien pregunta por qué ese cliente tiene
una zona que no existe.

Aquí se ejercita la ida y la vuelta de verdad, con protobuf. El transporte en sí
(`grpcio`) es una dependencia opcional y puede no estar instalada; lo que se
prueba es lo que falla con ella instalada, que es todo lo demás.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

CAMPOS = [
    {"nombre": "zona", "tipo": "texto", "obligatorio": False},
    {"nombre": "cupo", "tipo": "numero", "obligatorio": False},
    {"nombre": "etiquetas", "tipo": "lista_multiple", "obligatorio": False},
    # Un campo cifrado NO sale por el contrato, a propósito.
    {"nombre": "iban", "tipo": "cifrado", "obligatorio": False},
]

NUMEROS = {"zona": 1, "cupo": 2, "etiquetas": 3}


# ── Los números viajan con el esquema ─────────────────────────────────────


@pytest.mark.db
def test_los_numeros_del_contrato_se_replican_con_el_esquema(db: Any, tenant_id: UUID) -> None:
    """Sin ellos cada servicio los recalcularía y le saldrían otros. El número es
    el contrato; el orden de los campos es cosmético."""
    from crmcore.metamodelo import aplicar_esquema, numeros_rpc_de

    aplicar_esquema(
        db, tenant_id=tenant_id, objeto="zona_x", campos=CAMPOS, version=1, numeros_rpc=NUMEROS
    )
    assert numeros_rpc_de(db, tenant_id, "zona_x") == NUMEROS


@pytest.mark.db
def test_un_objeto_sin_contrato_publicado_no_inventa_numeros(db: Any, tenant_id: UUID) -> None:
    """Vacío significa «todavía no hay contrato», que no es lo mismo que «no
    tiene campos»."""
    from crmcore.metamodelo import aplicar_esquema, numeros_rpc_de

    aplicar_esquema(db, tenant_id=tenant_id, objeto="zona_y", campos=CAMPOS, version=1)
    assert numeros_rpc_de(db, tenant_id, "zona_y") == {}


@pytest.mark.db
def test_un_esquema_nuevo_no_se_queda_con_los_numeros_del_anterior(
    db: Any, tenant_id: UUID
) -> None:
    """Es la forma silenciosa de que el contrato diga una cosa y el servidor
    hable otra."""
    from crmcore.metamodelo import aplicar_esquema, numeros_rpc_de

    aplicar_esquema(
        db, tenant_id=tenant_id, objeto="zona_z", campos=CAMPOS, version=1, numeros_rpc=NUMEROS
    )
    nuevos = [*CAMPOS, {"nombre": "responsable", "tipo": "texto"}]
    aplicar_esquema(
        db,
        tenant_id=tenant_id,
        objeto="zona_z",
        campos=nuevos,
        version=2,
        numeros_rpc={**NUMEROS, "responsable": 7},
    )
    assert numeros_rpc_de(db, tenant_id, "zona_z") == {**NUMEROS, "responsable": 7}


@pytest.mark.db
def test_el_productor_manda_los_numeros(db: Any, tenant_id: UUID) -> None:
    """Si `metadata` no los emite, no hay nada que replicar y la vuelta al
    contrato se recalcula en cada servicio."""
    import ast
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "services" / "metadata" / "publicacion.py").read_text(encoding="utf-8")
    assert '"numeros_rpc"' in fuente, "el evento de esquema no lleva los números del contrato"
    # Y salen del contrato sincronizado, no de recalcularlos aquí.
    arbol = ast.parse(fuente)
    assert any(
        isinstance(n, ast.Attribute) or isinstance(n, ast.Call) for n in ast.walk(arbol)
    ), "el recorrido no mira"
    assert 'contrato.get("numeros")' in fuente


# ── La ida y la vuelta, con protobuf de verdad ────────────────────────────


@pytest.fixture
def clase() -> Any:
    from crmcore.rpc.mensajes import clase_de_objeto

    return clase_de_objeto(
        objeto="zona",
        campos=[
            {"clave": "zona", "tipo": "texto", "obligatorio": False},
            {"clave": "cupo", "tipo": "numero", "obligatorio": False},
            {"clave": "etiquetas", "tipo": "lista_multiple", "obligatorio": False},
        ],
        asignados=NUMEROS,
    )


def test_lo_que_entra_vuelve_igual(clase: Any) -> None:
    """Era lo que no pasaba: el manejador recibía `bytes` y se quedaba con el
    cuerpo vacío, así que un `Create` por gRPC creaba un registro sin datos."""
    from crmcore.rpc.servidor import codificar, descodificar

    # `cupo` es entero: el tipo «numero» del metamodelo viaja como `int64`, y
    # los importes van como cadena a propósito —`double` no representa 0,1 y en
    # dinero eso son céntimos que no cuadran—.
    bytes_ = codificar(clase, {"zona": "norte", "cupo": 12, "etiquetas": ["a", "b"]})
    assert isinstance(bytes_, bytes) and bytes_
    assert descodificar(clase, bytes_) == {"zona": "norte", "cupo": 12, "etiquetas": ["a", "b"]}


def test_lo_que_no_vino_no_vuelve_a_cero(clase: Any) -> None:
    """Devolver ceros por lo que no vino es lo que hace que un `Update` de dos
    campos ponga a cero los otros veinte."""
    from crmcore.rpc.servidor import codificar, descodificar

    vuelta = descodificar(clase, codificar(clase, {"zona": "norte"}))
    assert vuelta == {"zona": "norte"}
    assert "cupo" not in vuelta


def test_un_cero_que_si_vino_vuelve(clase: Any) -> None:
    """La otra mitad: si no se distinguiera, poner el cupo a cero sería
    indistinguible de no tocarlo."""
    from crmcore.rpc.servidor import codificar, descodificar

    assert descodificar(clase, codificar(clase, {"cupo": 0})) == {"cupo": 0}


def test_lo_que_el_contrato_no_publica_se_queda_fuera_al_contestar(clase: Any) -> None:
    """El CRM devuelve identificadores y marcas de tiempo que el contrato no
    tiene. Metérselos a la fuerza rompería la serialización entera por un campo
    que nadie pidió."""
    from crmcore.rpc.servidor import codificar, descodificar

    bytes_ = codificar(
        clase,
        {"zona": "norte", "id": str(uuid4()), "created_at": "2026-10-06T00:00:00Z", "iban": "ES12"},
    )
    assert descodificar(clase, bytes_) == {"zona": "norte"}


def test_un_campo_que_no_existe_en_una_peticion_se_rechaza(clase: Any) -> None:
    """Al revés que al contestar: quien escribe `descuneto` cree que mandó un
    descuento, y lo que recibiría es un «todo bien» con la ficha sin él."""
    from crmcore.errors import PeticionMalFormada
    from crmcore.rpc.mensajes import a_mensaje

    with pytest.raises(PeticionMalFormada) as fallo:
        a_mensaje(clase, {"descuneto": 10})
    assert fallo.value.error_code == "rpc.campo_desconocido"


def test_un_cliente_viejo_sobrevive_a_un_campo_nuevo(clase: Any) -> None:
    """Protobuf descarta lo desconocido al leer, y eso aquí se queda así: es lo
    que permite desplegar un campo sin romper a quien ya integró."""
    from crmcore.rpc.mensajes import clase_de_objeto
    from crmcore.rpc.servidor import codificar, descodificar

    nueva = clase_de_objeto(
        objeto="zona",
        campos=[
            {"clave": "zona", "tipo": "texto"},
            {"clave": "cupo", "tipo": "numero"},
            {"clave": "etiquetas", "tipo": "lista_multiple"},
            {"clave": "responsable", "tipo": "texto"},
        ],
        asignados={**NUMEROS, "responsable": 7},
    )
    bytes_ = codificar(nueva, {"zona": "norte", "responsable": "ana"})

    # El cliente viejo lo lee con SU contrato y no se cae.
    assert descodificar(clase, bytes_) == {"zona": "norte"}


# ── El servidor construye la clase del tenant ─────────────────────────────


@pytest.mark.db
def test_la_clase_sale_del_esquema_replicado_de_ese_tenant(db: Any, tenant_id: UUID) -> None:
    """Construirla desde otro sitio haría que el `.proto` entregado y lo que el
    servidor entiende dijeran cosas distintas, y eso no da error: el valor entra
    en el campo equivocado."""
    from crmcore.metamodelo import aplicar_esquema
    from crmcore.rpc.servidor import clase_del_objeto_replicado

    aplicar_esquema(
        db, tenant_id=tenant_id, objeto="zona_w", campos=CAMPOS, version=1, numeros_rpc=NUMEROS
    )
    clase = clase_del_objeto_replicado(db, tenant_id, "zona_w")

    por_nombre = {c.name: c.number for c in clase.DESCRIPTOR.fields}
    assert por_nombre == NUMEROS
    # El cifrado no sale por aquí: se descifra para quien tiene permiso y por el
    # camino que ya se auditó, no por una superficie nueva.
    assert "iban" not in por_nombre


@pytest.mark.db
def test_un_objeto_que_este_tenant_no_tiene_se_dice(db: Any, tenant_id: UUID) -> None:
    """Contestar con un mensaje vacío hace creer al que integra que el registro
    no tiene datos."""
    from crmcore.errors import PeticionMalFormada
    from crmcore.rpc.servidor import clase_del_objeto_replicado

    with pytest.raises(PeticionMalFormada) as fallo:
        clase_del_objeto_replicado(db, tenant_id, "lo_que_sea")
    assert fallo.value.error_code == "rpc.objeto_sin_contrato"


# ── El listado por gRPC devuelve registros, no el sobre ───────────────────


def test_un_list_devuelve_los_registros_y_no_la_pagina() -> None:
    """Buscaba «datos», que no existe en ninguna respuesta del CRM: por gRPC, un
    `List` contestaba un elemento con forma de página en lugar de N registros."""
    import ast
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "packages" / "crmcore" / "crmcore" / "service.py").read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.FunctionDef) and nodo.name == "_list":
            textos = {n.value for n in ast.walk(nodo) if isinstance(n, ast.Constant)}
            assert "items" in textos, "el `List` de gRPC no sabe de dónde sacar la lista"
            return
    raise AssertionError("no se ha encontrado el manejador `_list`: el recorrido no mira")


def test_el_servidor_ya_no_declara_bytes_como_serializador() -> None:
    """`bytes` no era «sin conversión»: era `bytes(diccionario)`, que revienta.
    La conversión va donde se sabe de qué tenant es la petición."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "packages" / "crmcore" / "crmcore" / "rpc" / "servidor.py").read_text(
        encoding="utf-8"
    )
    assert "request_deserializer=bytes" not in fuente
    assert "response_serializer=bytes" not in fuente
    assert "codificar(clase" in fuente
    assert "descodificar(clase" in fuente
