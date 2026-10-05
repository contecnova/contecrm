"""Lo que el enlace embebido promete y lo que de verdad hace (`CRM-05.01.02.06`).

Aquí vivía una prueba que afirmaba el hueco: `actua_como_id` se guardaba, se
devolvía al resolver el enlace y **no lo aplicaba nadie**. Decía de sí misma que
tenía que fallar el día que alguien lo implementara, para que no se quedara ahí
con el manual diciendo lo contrario.

No falló. Buscaba la palabra «suplant» en el código y la implementación no la
usa, así que una comprobación escrita para avisar del hueco habría dado verde
con el hueco cerrado **y** con el hueco abierto. Es el mismo fallo que persigue:
una comprobación que no mira parece verde.

Lo que hay ahora comprueba el comportamiento por donde pasa de verdad: que
ninguna ruta del cuadro incrustado exige sesión del CRM, y que ninguna devuelve
datos sin pasar por el ticket.
"""

from __future__ import annotations

import ast
import inspect

# Las rutas que SIRVEN el cuadro de fuera, por su camino. Crear el enlace y
# revocarlo también llevan «embebido» en el camino y son otra cosa: las llama un
# empleado desde el CRM, y ahí la sesión y el permiso son justo lo que toca.
CAMINOS_SERVIDOS = ("/embebidos/abrir", "/embebido", "/embebido/datos")


def _rutas_del_embebido() -> dict[str, ast.FunctionDef]:
    from services.analytics import api_cuadros

    arbol = ast.parse(inspect.getsource(api_cuadros))
    salida: dict[str, ast.FunctionDef] = {}
    for nodo in arbol.body:
        if not isinstance(nodo, ast.FunctionDef):
            continue
        for deco in nodo.decorator_list:
            if not isinstance(deco, ast.Call) or not deco.args:
                continue
            camino = getattr(deco.args[0], "value", None)
            if camino in CAMINOS_SERVIDOS:
                salida[nodo.name] = nodo
    faltan = set(CAMINOS_SERVIDOS) - {
        getattr(d.args[0], "value", None)
        for nodo in salida.values()
        for d in nodo.decorator_list
        if isinstance(d, ast.Call) and d.args
    }
    assert not faltan, f"estas rutas del embebido ya no existen: {sorted(faltan)}"
    return salida


def test_incrustar_un_cuadro_fuera_no_exige_sesion_del_crm() -> None:
    """Era el motivo por el que el enunciado decía «con SSO» y no lo era.

    Las rutas del embebido exigían `AutenticadoDep` y permiso de lectura, así
    que un cuadro no se podía incrustar en la aplicación de un cliente sin
    repartir credenciales de empleado entre sus usuarios. Eso no es incrustar un
    cuadro: es compartir una cuenta del CRM por internet.
    """
    rutas = _rutas_del_embebido()
    assert rutas, "no se ha encontrado ninguna ruta del cuadro incrustado"
    con_sesion_del_crm = []
    for nombre, nodo in rutas.items():
        texto = ast.unparse(nodo.decorator_list) + ast.unparse(nodo.args)
        if "AutenticadoDep" in texto or "exige_permiso" in texto:
            con_sesion_del_crm.append(nombre)
    assert not con_sesion_del_crm, (
        "estas rutas del cuadro incrustado exigen sesión del CRM, que es lo que "
        f"impedía incrustarlo en una aplicación de fuera: {sorted(con_sesion_del_crm)}"
    )


def test_ninguna_ruta_del_embebido_sirve_datos_sin_ticket() -> None:
    """El ticket es lo único que dice en nombre de quién se ejecuta.

    Una ruta del embebido que sirviera datos sin él volvería al punto de
    partida: la consulta la haría quien mira, con lo suyo, y el «actúa como» del
    enlace volvería a no acotar nada.
    """
    rutas = _rutas_del_embebido()
    # `abrir_embebido` es la que CAMBIA el secreto por el ticket, así que no
    # puede exigirlo: es la puerta. No devuelve datos del cuadro.
    sin_ticket = [
        nombre
        for nombre, nodo in rutas.items()
        if nombre != "abrir_embebido" and "TicketDep" not in ast.unparse(nodo.args)
    ]
    assert not sin_ticket, f"sirven algo del cuadro sin ticket: {sorted(sin_ticket)}"


def test_el_actua_como_llega_al_motor_de_informes() -> None:
    """Que es donde acota: el informe se compila con esos roles.

    La prueba de comportamiento está en `test_cuadros_mando.py`; esta es la
    estructural, y está aquí porque es la que se rompe si alguien «simplifica»
    `datos_del_embebido` quitándole los roles y dejando que el motor coja los
    de la sesión.
    """
    from services.analytics import cuadros as cua

    fuente = inspect.getsource(cua.datos_del_embebido)
    assert "alcance_roles" in fuente, "la ejecución ya no pasa los roles del ticket"
    assert "roles=" in fuente and "usuario_id=" in fuente
