"""Con qué alcance mira alguien que no está delante (`CRM-05.01.02.06`).

Existe para un caso concreto y bien delimitado: ejecutar algo **en nombre de**
una persona que no ha iniciado sesión. Un cuadro de mando incrustado en la
intranet de un cliente se calcula con el alcance de quien lo montó, no con el de
quien tiene el navegador abierto — y hasta el 05-10-2026 no había forma de saber
ese alcance desde otro servicio, así que el «actúa como» del enlace se guardaba
y no lo aplicaba nadie.

Lo que estas pruebas vigilan es que sea **un dato y no una credencial**: quien
llama recibe roles y permisos, nunca un token. Con un token podría hacer mucho
más que ejecutar un informe acotado, y viajaría por la red interna.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import NoEncontrado

pytestmark = pytest.mark.db


def _usuario(db: Any, tenant_id: UUID, email: str, roles: list[str]) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    from services.identity import servicio as svc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    usuario = svc.crear_usuario(
        uow,
        tenant_id=tenant_id,
        email=email,
        nombre="Quien sea",
        contrasena="una-contrasena-larga",
        roles=roles,
    )
    db.flush()
    return usuario


def test_devuelve_los_roles_con_los_que_esa_persona_mira(db: Any, contexto_tenant: UUID) -> None:
    from services.identity import servicio as svc

    usuario = _usuario(db, contexto_tenant, "montador@cliente.com", ["comercial"])
    alcance = svc.alcance_de_usuario(db, usuario.id, contexto_tenant)
    assert alcance["roles"] == ["comercial"]
    assert alcance["usuario_id"] == str(usuario.id)


def test_no_devuelve_ninguna_credencial(db: Any, contexto_tenant: UUID) -> None:
    """Es un dato, no una llave.

    Con un token, quien pregunta podría hacer mucho más que ejecutar un informe
    acotado — y lo haría con la identidad de otro.
    """
    from services.identity import servicio as svc

    usuario = _usuario(db, contexto_tenant, "sinllave@cliente.com", ["comercial"])
    alcance = svc.alcance_de_usuario(db, usuario.id, contexto_tenant)
    prohibidas = {"token", "access_token", "jwt", "secreto", "hash_contrasena", "contrasena"}
    assert not (prohibidas & set(alcance)), f"el alcance lleva una credencial: {alcance.keys()}"


def test_una_persona_de_otra_organizacion_no_tiene_alcance_aqui(
    db: Any, contexto_tenant: UUID
) -> None:
    """Sin esto, el cuadro incrustado de una empresa podría ejecutarse en nombre
    de alguien de otra: el enlace guarda un identificador, y un identificador
    por sí solo no dice de qué organización es."""
    from services.identity import servicio as svc

    usuario = _usuario(db, contexto_tenant, "deotra@cliente.com", ["comercial"])
    with pytest.raises(NoEncontrado):
        svc.alcance_de_usuario(db, usuario.id, uuid4())


def test_un_usuario_desactivado_no_da_alcance_vacio_sino_que_se_dice(
    db: Any, contexto_tenant: UUID
) -> None:
    """Un alcance vacío se leería como «no ve nada» y el cuadro saldría en
    blanco sin decir por qué, que es justo lo que hace que se culpe a los
    datos."""
    from services.identity import servicio as svc

    usuario = _usuario(db, contexto_tenant, "debaja@cliente.com", ["comercial"])
    usuario.activo = False
    db.flush()
    with pytest.raises(NoEncontrado) as fallo:
        svc.alcance_de_usuario(db, usuario.id, contexto_tenant)
    assert fallo.value.error_code == "usuario.sin_membresia_activa"


def test_por_correo_resuelve_lo_mismo_y_no_distingue_mayusculas(
    db: Any, contexto_tenant: UUID
) -> None:
    """Es la forma en que llega un sujeto desde fuera: la aplicación anfitriona
    sabe el correo de quien autenticó, no el identificador que tiene aquí."""
    from services.identity import servicio as svc

    usuario = _usuario(db, contexto_tenant, "ana@cliente.com", ["director"])
    por_correo = svc.alcance_por_correo(db, "  Ana@Cliente.com  ", contexto_tenant)
    assert por_correo == svc.alcance_de_usuario(db, usuario.id, contexto_tenant)


def test_un_correo_que_no_existe_no_se_confunde_con_uno_sin_membresia(
    db: Any, contexto_tenant: UUID
) -> None:
    """El mismo error para los dos: distinguirlos dejaría comprobar desde fuera
    qué correos tienen cuenta aquí, probando uno a uno."""
    from services.identity import servicio as svc

    _usuario(db, contexto_tenant, "dentro@cliente.com", ["comercial"])
    with pytest.raises(NoEncontrado) as inventado:
        svc.alcance_por_correo(db, "nadie@ninguna.com", contexto_tenant)
    with pytest.raises(NoEncontrado) as otra_org:
        svc.alcance_por_correo(db, "dentro@cliente.com", uuid4())
    assert inventado.value.error_code == otra_org.value.error_code


def test_la_ruta_interna_no_sale_en_el_contrato_publico() -> None:
    """Con la firma interna ya se podría preguntar por cualquiera, así que lo
    que la protege es el secreto compartido — y publicarla en el contrato sería
    decirle a quien mire por dónde se pregunta."""
    import ast
    import inspect

    from services.identity import api

    arbol = ast.parse(inspect.getsource(api))
    vistas = 0
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.FunctionDef):
            continue
        for deco in nodo.decorator_list:
            if not isinstance(deco, ast.Call) or "router_interno_usuarios" not in ast.unparse(deco):
                continue
            vistas += 1
            texto = ast.unparse(deco)
            assert "exige_firma_interna" in texto, f"«{nodo.name}» no exige la firma interna"
            assert "include_in_schema=False" in texto, f"«{nodo.name}» sale en el contrato público"
    assert vistas == 2, f"se esperaban 2 rutas de alcance y se han recorrido {vistas}"
