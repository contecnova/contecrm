"""Leer el cuerpo crudo de una petición sin que un error de quien llama se
convierta en un error del servidor.

Casi todas las rutas reciben el cuerpo ya validado por su esquema, y de eso se
encarga FastAPI: un cuerpo mal formado devuelve 422 con el campo que falla. Las
que leen el cuerpo **crudo** —porque aceptan una forma libre— se saltan esa
red, y ahí `await peticion.json()` revienta con una excepción que nadie
maneja: **500**.

Medido el 26-10-2026: dos rutas lo hacían, y una de ellas es la captura pública
de leads, que llama el navegador de un desconocido desde la web del cliente. Un
formulario mal montado, un robot o una petición sin cuerpo producían un error
interno, que además es la peor respuesta posible ahí: dice «me has roto» en vez
de «esto no vale», y eso invita a insistir.
"""

from __future__ import annotations

from typing import Any


async def cuerpo_json(peticion: Any, *, objeto: bool = True) -> Any:
    """El cuerpo decodificado, o un 422 que dice qué pasa.

    Con `objeto=True` —lo normal— además exige que sea un objeto JSON: una
    lista o un número sueltos rompen más adelante, al pedirle una clave, y el
    error aparece lejos del motivo.
    """
    from json import JSONDecodeError

    from crmcore.errors import ErrorValidacion

    try:
        entrada = await peticion.json()
    except (JSONDecodeError, UnicodeDecodeError, ValueError) as error:
        # El motivo va dentro: «no es JSON válido» a secas obliga a adivinar si
        # el problema es una coma, la codificación o que no se mandó nada.
        raise ErrorValidacion(
            "El cuerpo de la petición no es JSON válido",
            error_code="peticion.cuerpo_no_json",
            detalle={"motivo": str(error)[:200]},
        ) from error

    if objeto and not isinstance(entrada, dict):
        raise ErrorValidacion(
            "El cuerpo tiene que ser un objeto JSON",
            error_code="peticion.cuerpo_no_es_objeto",
            detalle={"recibido": type(entrada).__name__},
        )
    return entrada
