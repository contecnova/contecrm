"""Servicio de integración: conectar con lo que hay fuera sin escribir código.

La regla de la casa aquí es explícita: **nada por proveedor**. Integrar el ERP
de un cliente no añade un fichero de Python, añade una configuración — y esa
configuración la puede escribir un operador desde la consola y corregirla sin
desplegar. Si un sistema externo no cabe en la configuración, se amplía la
configuración, no se hace una excepción para él.

El conector genérico se porta de `contecweb` (`app/connectors/api/`), donde
lleva en producción cubriendo desde APIs sencillas hasta las que obligaban a
escribir código por proveedor. Los cinco patrones que lo hicieron posible están
en `conector.py`, con el porqué de cada uno.
"""
