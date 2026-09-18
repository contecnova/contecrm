"""Núcleo transversal de contecrm.

Todo lo que el catálogo funcional llama "transversal" (Módulo 0) vive aquí y lo
comparten los servicios: multi-tenancy, contratos de API, bus de eventos,
identidad, observabilidad y gobierno del dato.

La regla que ordena este paquete: **un servicio no puede cumplir una restricción
transversal por su cuenta**. Si el aislamiento por tenant dependiera de que cada
servicio se acuerde de filtrar, fallaría el día que alguien se despiste. Por eso
lo transversal se impone desde aquí —sesión de base de datos, middleware,
factoría de aplicación— y el servicio hereda el comportamiento correcto sin
tener que pedirlo.
"""

__version__ = "0.1.0"
