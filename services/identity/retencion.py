"""Qué datos de `identity` tienen vida limitada (CRM-07.03.01.01).

Hasta el 26-10-2026 este fichero no existía: `identity` **no declaraba ninguna
clase purgable y no publicaba el router de retención**, así que nada de lo suyo
caducaba nunca y la papelera del chat no tenía quién la vaciara. El modelo del
mensaje llevaba las columnas de borrado desde el principio y su propio
comentario apuntaba a la capacidad (CRM-06.02.02.09), pero no había ruta que
borrara, ni que recuperara, ni clase declarada, ni purga. Escrito y sin
enchufar.

Los días por defecto son **cero —no se purga nunca— a propósito**: el plazo lo
decide el tenant, que es quien conoce su obligación. Acertar por él sería
destruir datos de alguien con una suposición. Lo que sí hace falta es que la
clase esté declarada, porque sin eso la empresa no puede fijar el plazo aunque
quiera: no aparece en la pantalla de retención.

Y el borrado de un mensaje purgado es **físico**. Una papelera que guarda para
siempre no es una papelera: el caso que justifica todo esto es haber pegado en
un canal algo que no debía estar ahí —una credencial, el dato personal de un
cliente—, y dejarlo en la tabla con una marca no lo quita de ningún sitio. El
plazo lo pone la empresa; pasado el plazo, se va.

La purga consulta los **bloqueos legales** antes de cada borrado, como todas:
eso lo pone el motor común y por eso se reutiliza en vez de escribir otro.
"""

from __future__ import annotations

from crmcore.datos.retencion import ClaseDato, registrar_clase

from services.identity.chat import ConversacionChat, MensajeChat

registrar_clase(
    ClaseDato(
        clave="chat_mensajes_borrados",
        descripcion="Mensajes de chat en la papelera, esperando la purga definitiva",
        modelo=MensajeChat,
        # Desde que se borró y no desde que se escribió: el plazo de la papelera
        # cuenta desde que entró en ella. Contando desde la creación, borrar hoy
        # un mensaje del año pasado lo purgaría en la siguiente pasada y la
        # papelera no serviría para deshacer nada.
        campo_fecha="deleted_at",
        borrado="fisico",
        solo_si_borrado=True,
    )
)

registrar_clase(
    ClaseDato(
        clave="chat_conversaciones_borradas",
        descripcion="Conversaciones de chat en la papelera",
        modelo=ConversacionChat,
        campo_fecha="deleted_at",
        borrado="fisico",
        solo_si_borrado=True,
    )
)
