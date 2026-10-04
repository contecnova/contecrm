def test_el_actua_como_del_embebido_no_acota_nada_todavia() -> None:
    """Lo que el enlace promete y lo que de verdad hace (`CRM-05.01.02.06`).

    `actua_como_id` se guarda y se devuelve al resolver el enlace, y **no lo
    aplica nadie**: la consulta la hace quien mira, con sus propios permisos.
    No hay fuga —la ruta exige sesión y permiso de lectura— pero tampoco hay
    tope: un cuadro montado por un comercial y abierto por un director enseña
    los datos del director.

    Esta prueba existe para que no se olvide. **Falla el día que alguien lo
    implemente**, y entonces hay que borrarla y escribir la de verdad — que es
    justo lo que se quiere que pase, en vez de que el hueco siga ahí con el
    manual diciendo lo contrario.
    """
    import inspect

    from services.analytics import api_cuadros, cuadros

    aplicado = any(
        "actua_como" in inspect.getsource(fn) and "suplant" in inspect.getsource(fn).lower()
        for fn in (cuadros.resolver_embebido, api_cuadros.embebido)
    )
    assert not aplicado, (
        "parece que el «actúa como» del embebido ya se aplica: borra esta "
        "prueba, escribe la que comprueba que acota de verdad, y quita el "
        "párrafo del manual que dice que todavía no"
    )
