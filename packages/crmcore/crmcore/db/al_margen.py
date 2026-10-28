"""Ejecutar algo que NO puede tumbar lo principal, y que de verdad no lo tumbe.

Hay trabajo que acompaña a una operación sin ser la operación: anotar que un
campo se ha usado, guardar la versión anterior de un ajuste, mandar un aviso.
Si falla, la operación tiene que seguir adelante.

**Un `try/except` alrededor no basta, y esa es la trampa.** Cuando lo de dentro
escribe en la MISMA sesión, un fallo de la base la deja envenenada: SQLAlchemy la
marca como necesitada de `rollback`, así que la siguiente instrucción —la de la
operación de verdad, que no tiene nada que ver— muere con `PendingRollbackError`.
El `except` atrapa el primer error, escribe su aviso tranquilizador, y la petición
se cae igual unas líneas más abajo con un mensaje que no menciona la causa.

Se ve en el comentario que ya había en `metamodelo.anotar_uso`: «el alta se caía
por culpa de una estadística, que es exactamente lo que el `try` pretendía
impedir — y no lo impedía». Se arregló el orden del `flush` y quedó el agujero.

Con un SAVEPOINT sí lo impide: lo de dentro se deshace solo y la sesión sigue
siendo usable. Es lo mismo que hace `try` con un bloque de código, pero en la
base de datos.

    with al_margen(db, "metamodelo.uso_no_anotado", objeto=objeto):
        db.add(UsoCampo(...))

Lo que NO hace, dicho claro: no reintenta y no encola. Si lo de dentro importa
lo suficiente como para reintentarlo, no es trabajo al margen — es un trabajo de
fondo, y para eso está `crmcore.datos.trabajos`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)


@contextmanager
def al_margen(db: Any, evento: str, **contexto: Any) -> Iterator[None]:
    """Un bloque que puede fallar sin arrastrar la transacción de fuera.

    `evento` es el nombre con el que se registra el fallo. Se pide en vez de
    inventarlo aquí porque quien lo busca en los registros lo busca por su
    nombre, y «al_margen.fallo» para veinte sitios distintos no sirve de nada.
    """
    punto = None
    try:
        # `begin_nested` es un SAVEPOINT de verdad, no una transacción anidada
        # de mentira: el motor puede deshacer hasta aquí sin tocar lo de fuera.
        punto = db.begin_nested()
        yield
        punto.commit()
    except Exception as exc:  # noqa: BLE001 — es justo lo que este bloque atrapa
        # `rollback()` SIEMPRE, no sólo si el punto «sigue activo».
        #
        # Es la trampa de la trampa, y costó encontrarla. Cuando el fallo es de
        # la base —que es el caso para el que existe este bloque—, SQLAlchemy
        # **desactiva** el savepoint y aun así exige que se deshaga antes de
        # seguir. O sea que `if punto.is_active` se saltaba exactamente el
        # único caso que había que atender, y dejaba la sesión envenenada: la
        # siguiente instrucción, que no tiene nada que ver, muere con
        # `PendingRollbackError: Can't reconnect until invalid savepoint
        # transaction is rolled back`.
        #
        # El síntoma no apuntaba aquí ni de lejos. En la suite completa caían
        # dos o tres pruebas **de otros módulos** —las pestañas de la consola
        # de un servicio distinto en cada tanda, el ETag de ida y vuelta—
        # porque comparten la conexión del arnés: lo que se veía era la
        # víctima, nunca el culpable. Y sueltas pasaban todas.
        #
        # Deshacer un savepoint ya deshecho no cuesta nada; dejarlo sin
        # deshacer cuesta la petición siguiente.
        if punto is not None:
            try:
                punto.rollback()
            except Exception as al_deshacer:  # noqa: BLE001 — el motivo ES el valor
                # **Si no se puede deshacer, no se calla.**
                #
                # Que el `ROLLBACK TO SAVEPOINT` falle significa que el punto ya
                # no existe: la transacción entera se vino abajo o la conexión
                # se cayó. La sesión queda inservible, así que seguir como si
                # nada no salva «lo principal» —lo principal ya está muerto—:
                # sólo hace que muera unas líneas más abajo con un
                # `PendingRollbackError` que no nombra ni este bloque ni la
                # causa.
                #
                # Medido el 28-10-2026: así aparecía, en la suite, como «fallan
                # las pestañas de la consola» de un servicio distinto cada vez.
                # El aviso tranquilizador de este `except` era justo lo que
                # impedía ver que la conexión se había caído.
                logger.error(
                    f"{evento}.sin_poder_deshacer",
                    error=f"{type(exc).__name__}: {str(exc)[:200]}",
                    al_deshacer=f"{type(al_deshacer).__name__}: {str(al_deshacer)[:200]}",
                    **contexto,
                )
                raise
        logger.warning(evento, error=f"{type(exc).__name__}: {str(exc)[:200]}", **contexto)
