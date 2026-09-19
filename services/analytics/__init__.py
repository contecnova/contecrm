"""Explotación del dato: la puerta a contecintelligence (RT-4).

Este servicio **no** calcula informes. Su trabajo es que contecrm pueda
enseñarlos sin que el usuario salga de aquí: guarda a qué organización de
contecintelligence corresponde cada tenant, canja la credencial de aplicación
por un token corto de usuario final, y dice si la integración está viva.

Que sea un servicio aparte y no un módulo del gateway es deliberado: tiene
estado propio —la correspondencia de organizaciones—, tiene una credencial que
no debe estar en el proceso que atiende todo el tráfico, y su caída no puede
llevarse por delante el resto del CRM.
"""
