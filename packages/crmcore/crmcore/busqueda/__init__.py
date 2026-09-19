"""Búsqueda con aislamiento por tenant (CRM-00.01.01.09).

El índice de búsqueda es la tercera vía silenciosa por la que un cliente ve el
dato de otro, después de la caché y del almacén de ficheros. Y es la peor de las
tres, porque un buscador **está hecho para encontrar**: una fuga aquí no se
queda esperando a que alguien acierte con un identificador, sino que le sirve al
primero que teclee «acuerdo marco» los contratos de todos los clientes.

Dos formas de evitarlo, y las dos valen: **un índice por tenant** o **un filtro
por tenant que el motor imponga**. Lo que no vale es un índice compartido donde
el filtro lo ponga quien consulta: basta una consulta escrita deprisa para que
falte, y el resultado no da error — devuelve de más.

Aquí se hace con Postgres y su búsqueda de texto completo, y el aislamiento sale
de donde ya está: la tabla del índice lleva `tenant_id`, RLS la cubre como a
cualquier otra, y además el filtro va explícito en cada consulta. Tres redes, y
ninguna depende de que quien escribe la consulta se acuerde.

**Por qué Postgres y no un motor aparte.** Un motor de búsqueda dedicado es otra
pieza que desplegar, vigilar, respaldar y aislar — y el aislamiento habría que
construirlo entero, porque estos motores no traen RLS. Con el volumen de un CRM
mediano, la búsqueda de texto de Postgres llega de sobra. El día que no llegue,
el protocolo `Buscador` está aquí para meter otro backend sin tocar a quien lo
llama; lo que no se hace es escribirlo hoy «por si acaso», porque un backend sin
usuarios es un backend sin probar.
"""

from crmcore.busqueda.base import (
    Buscador,
    BuscadorPostgres,
    DocumentoIndexado,
    Resultado,
    buscar,
    desindexar,
    get_buscador,
    indexar,
    reset_buscador,
)

__all__ = [
    "Buscador",
    "buscar",
    "BuscadorPostgres",
    "DocumentoIndexado",
    "Resultado",
    "desindexar",
    "get_buscador",
    "indexar",
    "reset_buscador",
]
