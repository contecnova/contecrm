"""Servicio `sales`: leads, pipelines y oportunidades.

La frontera con `party` está en la **cualificación**: un lead es una pista sin
cualificar y vive aquí; una cuenta es una organización real y vive allí. Meter
los leads en el maestro de clientes es el error que llena el CRM de basura de
captación —formularios rellenados a medias, correos de prueba, nombres
inventados— y hace que el maestro deje de ser fiable justo para lo que se usa:
facturar y decidir.

La conversión (CRM-01.01.03.01) es el puente: al cualificar, el lead se
convierte en cuenta, contacto y oportunidad, y **se conserva** apuntando a lo
que generó. Sin esa traza, la pregunta «¿de dónde salió este cliente?» no tiene
respuesta y la atribución de marketing es una estimación.
"""
