"""Servicio de metadatos: el modelo de datos que cada tenant se define.

Dos cosas que en la mayoría de CRM son la misma y aquí no:

  * **El esquema es dato, no DDL.** Cuando un tenant añade un campo, no se
    altera ninguna tabla: se registra la definición del campo y el valor vive en
    una columna JSONB del registro. Si añadir un campo en un tenant alterara la
    tabla, sería un DDL que bloquea a todos los demás — y con mil tenants, una
    tarde de bloqueos.
  * **La validación se puede consultar antes de enviar.** Un frontend headless
    puede preguntar «¿esto sería válido?» y enseñar los errores sin intentar
    guardar (CRM-00.02.03.07). Sin eso, cada cliente reimplementa las reglas y
    tarde o temprano difieren de las del servidor.

De aquí sale además el `describe` (CRM-00.04.01.08): la API que permite a
cualquier frontend renderizar formularios y listas sin saber nada del CRM.
"""
