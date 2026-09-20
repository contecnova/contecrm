"""Corpus documental delegado en contecmind, de forma frontless (RT-5).

Dos capas, y la distinción decide todo lo demás:

  * **Adjunto** (`crmcore.datos.adjuntos`): lo que cuelga de un registro. La foto
    de una visita, el PDF firmado de una oportunidad. Vive en contecrm, sigue la
    papelera y la retención del registro, y **tiene que poder subirse aunque el
    gestor documental no responda**. Que un comercial no pueda adjuntar una foto
    porque un servicio externo está caído sería una regresión.

  * **Documento** (esto): el corpus de la empresa. Contratos, procedimientos,
    certificados. Versionado con aprobación, obsolescencia, diff entre versiones
    y búsqueda — todo eso ya lo hace contecmind y lleva en producción.
    Reescribirlo aquí sería mantener dos veces lo mismo, peor.

contecrm guarda **el enlace y el contexto**: qué registro tiene qué documento y
para qué. El documento vive allí.

**Lo que esto obliga a hacer bien, y no es un detalle:** dos obligaciones de
contecrm cruzan la frontera.

  * El **bloqueo legal** de un registro tiene que impedir borrar sus documentos
    enlazados. Un bloqueo que solo alcanza a media prueba no es un bloqueo.
  * El **certificado de destrucción** al dar de baja un tenant tiene que decir
    qué había enlazado fuera. Callarlo sería certificar una destrucción que no
    se ha hecho entera.

Con contecintelligence esto no pasaba porque solo lee. Aquí se escribe y se
borra, así que la frontera tiene que sostener las dos cosas.
"""

from __future__ import annotations

from crmcore.documental.enlaces import (
    DocumentoEnlazado,
    OrganizacionDocumental,
    documentos_de,
    enlazar,
    inventario_para_certificado,
    mapear_organizacion,
    organizacion_de,
    quitar_enlace,
)

__all__ = [
    "DocumentoEnlazado",
    "OrganizacionDocumental",
    "documentos_de",
    "enlazar",
    "inventario_para_certificado",
    "mapear_organizacion",
    "organizacion_de",
    "quitar_enlace",
]
