"""Qué datos de `party` tienen vida limitada (CRM-07.03.01.01).

Se declara aquí, en el servicio dueño de los datos, y no en el núcleo: una lista
central obligaría a tocarlo cada vez que un servicio añade un objeto, y acabaría
desfasada justo en lo que borra cosas.

**Ningún valor por defecto destruye nada.** Todas las clases se declaran con
`dias_defecto=0`, que significa «se guarda indefinidamente». La retención la fija
el tenant, que es quien conoce su obligación legal: los plazos de un fabricante
de componentes de automoción no son los de una agencia de marketing, y acertar
por ellos sería destruir datos de alguien con una suposición.
"""

from __future__ import annotations

from crmcore.datos.adjuntos import Adjunto, DescargaAdjunto
from crmcore.datos.comentarios import Comentario
from crmcore.datos.papelera import EntradaPapelera
from crmcore.datos.retencion import ClaseDato, registrar_clase

from services.party.modelos import Actividad, Contacto, Cuenta, SolicitudDerechos

registrar_clase(
    ClaseDato(
        clave="actividades",
        descripcion="Tareas, llamadas, reuniones y notas ya completadas",
        modelo=Actividad,
        # Desde que se COMPLETÓ, no desde que se creó: una tarea abierta de hace
        # tres años sigue siendo la única cosa pendiente de ese cliente.
        campo_fecha="completada_at",
        borrado="logico",
    )
)
registrar_clase(
    ClaseDato(
        clave="papelera",
        descripcion="Registros ya borrados esperando la purga definitiva",
        modelo=EntradaPapelera,
        campo_fecha="borrado_at",
        borrado="fisico",
    )
)
registrar_clase(
    ClaseDato(
        clave="cuentas_borradas",
        descripcion="Cuentas en la papelera, para su destrucción definitiva",
        modelo=Cuenta,
        campo_fecha="deleted_at",
        borrado="fisico",
        # Solo lo ya borrado lógicamente: aquí la retención define cuánto vive
        # lo que alguien decidió borrar, no cuánto vive un cliente activo.
        solo_si_borrado=True,
    )
)
registrar_clase(
    ClaseDato(
        clave="contactos_borrados",
        descripcion="Contactos en la papelera, para su destrucción definitiva",
        modelo=Contacto,
        campo_fecha="deleted_at",
        borrado="fisico",
        solo_si_borrado=True,
    )
)
registrar_clase(
    ClaseDato(
        clave="descargas_adjunto",
        descripcion="Registro de quién descargó qué documento",
        modelo=DescargaAdjunto,
        campo_fecha="created_at",
        borrado="fisico",
    )
)
registrar_clase(
    ClaseDato(
        clave="adjuntos_borrados",
        descripcion="Adjuntos retirados, para su destrucción definitiva",
        modelo=Adjunto,
        campo_fecha="deleted_at",
        borrado="fisico",
        solo_si_borrado=True,
    )
)
registrar_clase(
    ClaseDato(
        clave="comentarios_borrados",
        descripcion="Comentarios retirados de una conversación",
        modelo=Comentario,
        campo_fecha="borrado_at",
        borrado="fisico",
    )
)
registrar_clase(
    ClaseDato(
        clave="solicitudes_derechos",
        descripcion="Solicitudes de derechos del interesado ya resueltas",
        modelo=SolicitudDerechos,
        campo_fecha="created_at",
        # Físico y no lógico: una solicitud resuelta es la PRUEBA de haberla
        # atendido, así que o se conserva o se destruye — marcarla como borrada
        # dejaría una evidencia a medias que no vale para enseñar a nadie.
        borrado="fisico",
    )
)
