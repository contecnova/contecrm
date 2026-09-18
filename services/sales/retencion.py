"""Qué datos de `sales` tienen vida limitada (CRM-07.03.01.01).

Todas con `dias_defecto=0` —se guardan indefinidamente— porque el plazo lo
decide el tenant, que es quien conoce su obligación. Acertar por él sería
destruir datos de alguien con una suposición.

Los **toques** son el caso claro de dato que sí caduca: el recorrido de
navegación de un visitante es dato personal de bajo valor pasados unos meses y
alto volumen, así que es lo primero que un tenant querrá acotar.
"""

from __future__ import annotations

from crmcore.datos.adjuntos import Adjunto, DescargaAdjunto
from crmcore.datos.comentarios import Comentario
from crmcore.datos.papelera import EntradaPapelera
from crmcore.datos.retencion import ClaseDato, registrar_clase

from services.sales.enrutamiento import RegistroEnrutamiento
from services.sales.modelos import Lead
from services.sales.origen import Toque

registrar_clase(
    ClaseDato(
        clave="toques",
        descripcion="Recorrido de navegación y clics atribuibles de los visitantes",
        modelo=Toque,
        campo_fecha="ocurrio_at",
        borrado="fisico",
    )
)
registrar_clase(
    ClaseDato(
        clave="leads_descartados",
        descripcion="Leads descartados que ya no se van a reciclar",
        modelo=Lead,
        campo_fecha="deleted_at",
        borrado="fisico",
        solo_si_borrado=True,
    )
)
registrar_clase(
    ClaseDato(
        clave="registro_enrutamiento",
        descripcion="Traza de por qué cada lead cayó donde cayó",
        modelo=RegistroEnrutamiento,
        campo_fecha="created_at",
        borrado="fisico",
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
