"""Almacenamiento de ficheros: local y S3 con la misma interfaz.

**Portado de `contecmind/app/core/storage.py`**, no reescrito. Aquel módulo ya
pasó por dos auditorías que corrigieron cosas que no son evidentes al escribirlo
de cero:

  * El guard de path traversal estaba **cinco veces** copiado y dos copias
    estaban mal: comparaban rutas cosiendo una barra POSIX a mano, así que en
    Windows rechazaban toda clave legítima y el lado de lectura quedaba muerto
    en silencio (`exists` se tragaba el error y devolvía `False`). Aquí hay
    **uno solo**, `_bajo_base`, y usa `is_relative_to`.
  * El `mkdir` corría **antes** de validar la clave, así que una clave con `..`
    creaba directorios fuera de la base antes de fallar.
  * `put_file` existe para no cargar en RAM un fichero de varios GB.

Reescribirlo habría significado volver a tropezar con las tres.

Se expone como servicio del núcleo y no de un servicio concreto porque los
adjuntos cuelgan de cualquier objeto: una cuenta, un caso, una oportunidad.
"""

from crmcore.almacen.base import Almacen, AlmacenLocal, AlmacenS3, get_almacen, reset_almacen

__all__ = ["Almacen", "AlmacenLocal", "AlmacenS3", "get_almacen", "reset_almacen"]
