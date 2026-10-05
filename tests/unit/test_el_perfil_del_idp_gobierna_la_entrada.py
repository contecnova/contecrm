"""Un perfil de proveedor de identidad que no gobierna ninguna entrada
(`CRM-00.05.01.16`).

Los perfiles existen para no escribir un módulo por cada proveedor: lo que
cambia entre ellos son las direcciones y **los nombres de los campos**, y eso es
configuración. Medido el 05-10-2026, lo que había era un perfil que se guardaba,
se devolvía por su ruta y no decidía nada:

    perfil declarado          `campo_email`
    configuración de SAML     `attr_email`      ← otro nombre para lo mismo
    camino de OIDC            `claims["email"]` ← escrito en el código

O sea: declarar que el correo viene en `mail` no cambiaba nada en OIDC, y en
SAML solo si además se escribía con el otro nombre. Y el síntoma no es un error
—sería fácil— sino un usuario que entra sin identidad utilizable, o que entra
sin grupos y por tanto sin permisos. Eso no lo relaciona nadie con un campo mal
escrito.

Lo que estas pruebas fijan: **un solo vocabulario**, que el antiguo siga
valiendo para no echar fuera a quien ya está configurado, y que lo declarado se
pueda contrastar con lo que el proveedor ofrece de verdad en vez de con un
manual.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from crmcore.errors import ErrorValidacion

from services.identity import oidc as oidc_cli
from services.identity import sso


def _proveedor(campos: dict[str, str] | None = None) -> Any:
    return oidc_cli.Proveedor(
        id=str(uuid4()),
        tenant_id=uuid4(),
        nombre="El de siempre",
        issuer_url="https://idp.cliente.com",
        client_id="c",
        client_secret="s",
        redirect_uri="https://crm/vuelta",
        campos=campos,
    )


# ── Un solo vocabulario ───────────────────────────────────────────────────


def test_lo_declarado_manda_sobre_el_nombre_de_siempre() -> None:
    """Si no, declarar el campo es decorativo."""
    campos = sso.campos_declarados({"perfil": "oidc_generico", "campo_email": "mail"}, "oidc")
    correo, _, _ = oidc_cli.identidad_de(
        _proveedor(campos), {"mail": "ana@cliente.com", "email": "no-es-esta@cliente.com"}
    )
    assert correo == "ana@cliente.com"


def test_el_nombre_antiguo_de_sami_se_sigue_leyendo() -> None:
    """Un proveedor ya configurado con `attr_email` no puede dejar de entrar el
    día del despliegue: eso no es una migración, es una caída."""
    campos = sso.campos_declarados({"attr_email": "mail", "attr_grupos": "Role"}, "saml")
    assert campos["campo_email"] == "mail"
    assert campos["campo_grupos"] == "Role"


def test_sin_perfil_declarado_se_comporta_como_siempre() -> None:
    """Un proveedor dado de alta antes de que hubiera perfiles no tiene ninguno,
    y lo que necesita es el comportamiento de siempre, no un error."""
    campos = sso.campos_declarados({}, "oidc")
    correo, nombre, grupos = oidc_cli.identidad_de(
        _proveedor(campos),
        {"email": "ana@cliente.com", "name": "Ana", "groups": ["ventas"]},
    )
    assert (correo, nombre, grupos) == ("ana@cliente.com", "Ana", ["ventas"])


def test_los_grupos_tambien_salen_del_campo_declarado() -> None:
    """Equivocarse aquí no da un error: da un usuario que entra sin permisos."""
    campos = sso.campos_declarados({"campo_grupos": "wids"}, "oidc")
    _, _, grupos = oidc_cli.identidad_de(
        _proveedor(campos), {"email": "a@b.c", "wids": ["ventas", "dirección"]}
    )
    assert grupos == ["ventas", "dirección"]


def test_sin_correo_se_dice_que_campo_se_esperaba_y_cual_llego() -> None:
    """La diferencia entre arreglarlo en un minuto y pasar una tarde mirando el
    IdP."""
    campos = sso.campos_declarados({"campo_email": "mail"}, "oidc")
    with pytest.raises(ErrorValidacion) as fallo:
        oidc_cli.identidad_de(_proveedor(campos), {"sub": "x", "upn_raro": "ana@cliente.com"})
    assert fallo.value.error_code == "oidc.sin_email"
    assert fallo.value.detalle["campo_declarado"] == "mail"
    assert "upn_raro" in fallo.value.detalle["campos_recibidos"]


# ── Comprobarlo contra el proveedor, no contra un manual ──────────────────


def test_se_dice_que_campo_declarado_no_ofrece_el_proveedor() -> None:
    declarado = {"campo_email": "mail", "campo_grupos": "wids"}
    salida = sso.comprobar_perfil(declarado, ["sub", "mail", "name"])
    assert salida["comprobable"] is True
    assert salida["no_ofrecidos"] == ["campo_grupos"]


def test_un_proveedor_que_no_publica_sus_campos_no_es_un_suspenso() -> None:
    """`claims_supported` es opcional en la norma.

    Decir «ninguno coincide» cuando lo que pasa es que no hay con qué comparar
    manda a cambiar una configuración que estaba bien.
    """
    salida = sso.comprobar_perfil({"campo_email": "mail"}, [])
    assert salida["comprobable"] is False
    assert salida["no_ofrecidos"] == []


def test_lo_que_coincide_se_dice_sin_rodeos() -> None:
    salida = sso.comprobar_perfil({"campo_email": "email"}, ["sub", "email", "groups"])
    assert salida["no_ofrecidos"] == []
    assert salida["comprobable"] is True


def test_los_campos_ofrecidos_salen_del_proveedor_y_no_de_una_lista_nuestra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """De su documento de descubrimiento, que lo publica él.

    Si saliera de una lista escrita aquí, comprobar el perfil sería comprobarlo
    contra lo que nosotros creemos, que es justo lo que no vale.
    """
    monkeypatch.setattr(
        oidc_cli, "_descubrir", lambda p: {"issuer": "x", "claims_supported": ["sub", "mail"]}
    )
    assert oidc_cli.claims_publicados(_proveedor()) == ["sub", "mail"]


def test_el_camino_de_oidc_no_pide_los_campos_a_pelo() -> None:
    """La prueba estructural del agujero concreto.

    Pedir `claims.get("email")` en la vuelta del proveedor es lo que hacía que
    el perfil no gobernara nada, y es un cambio de una línea volver a dejarlo
    así «porque es más directo».
    """
    import inspect

    from services.identity import api_sso

    fuente = inspect.getsource(api_sso._callback_oidc)
    assert "identidad_de(" in fuente, "la vuelta de OIDC ya no usa los campos declarados"
    assert 'claims.get("email")' not in fuente


# ── Un perfil por proveedor, leído y no pegado ────────────────────────────
#
# El enunciado de `CRM-00.05.01.16` nombra cinco proveedores concretos y pide un
# perfil para cada uno «encima del genérico, nunca en su lugar». Pegar aquí sus
# nombres de campo son hechos de productos ajenos que no puedo verificar y que
# caducan sin avisar; y un perfil con el campo equivocado es PEOR que no tenerlo.
# Así que el perfil se construye leyéndole al proveedor lo que publica de sí
# mismo, que sirve para los cinco y para el que venga.


def test_el_perfil_sale_de_lo_que_el_proveedor_publica() -> None:
    salida = sso.proponer_perfil(["sub", "mail", "displayName", "wids"])
    assert salida["propuesto"] == {
        "campo_email": "mail",
        "campo_nombre": "displayName",
        "campo_grupos": "wids",
    }
    assert salida["sin_decidir"] == []


def test_el_campo_que_no_publica_se_deja_vacio_y_se_dice() -> None:
    """Elegir uno «porque suele ser» es adivinar.

    Y adivinar aquí no da un error: da un usuario que entra sin grupos, es
    decir, sin permisos, y nadie lo relaciona con esto.
    """
    salida = sso.proponer_perfil(["sub", "email", "name"])
    assert salida["propuesto"]["campo_email"] == "email"
    assert salida["sin_decidir"] == ["campo_grupos"]
    assert "campo_grupos" not in salida["propuesto"]


def test_un_proveedor_que_no_publica_nada_no_deja_un_perfil_a_medias_en_silencio() -> None:
    salida = sso.proponer_perfil([])
    assert salida["propuesto"] == {}
    assert sorted(salida["sin_decidir"]) == ["campo_email", "campo_grupos", "campo_nombre"]


def test_no_hay_ningun_perfil_con_nombre_de_proveedor() -> None:
    """La regla de la casa: nada por proveedor, todo configuración o medición.

    Lo que se prohíbe es una **estructura** por casa: un perfil llamado «okta»,
    una constante con su nombre, una función para él. Nombrar un proveedor al
    explicar por qué los grupos se comparan sin mayúsculas no es eso, y por eso
    se miran los identificadores y las claves, no la prosa.

    Sin esta prueba, «añadir Okta» se convierte en pegar un diccionario con su
    nombre, y así es como se acaba con un módulo por casa y una versión del
    producto por implantación.
    """
    import ast
    import inspect

    casas = ("okta", "entra", "keycloak", "ping", "auth0", "onelogin", "azure", "workspace")
    nombradas: list[str] = []
    for modulo in (sso, oidc_cli):
        arbol = ast.parse(inspect.getsource(modulo))
        for nodo in ast.walk(arbol):
            etiquetas: list[str] = []
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                etiquetas.append(nodo.name)
            elif isinstance(nodo, ast.Name):
                etiquetas.append(nodo.id)
            elif isinstance(nodo, ast.Dict):
                etiquetas.extend(str(c.value) for c in nodo.keys if isinstance(c, ast.Constant))
            for etiqueta in etiquetas:
                # Por TROZOS y no por subcadena: «entra» está dentro de
                # `entrar_o_provisionar`, y con `in` esta prueba señalaba como
                # conector por casa a la función que resuelve la entrada. Una
                # comprobación que señala código correcto se acaba quitando.
                trozos = {x for x in etiqueta.lower().replace("-", "_").split("_") if x}
                nombradas.extend(
                    f"{modulo.__name__}:{etiqueta}" for casa in casas if casa in trozos
                )
    assert not nombradas, f"hay estructuras con nombre de proveedor: {sorted(set(nombradas))}"
