"""Las listas cerradas que conoce un servicio, publicadas en su contrato.

Un campo como `estado` sale en las filas como un código —«abierta»,
«en_curso»— y la pantalla tiene que poder escribirlo como texto sin
adivinarlo: una palabra suelta en minúscula puede ser también un nombre o un
identificador. Medido el 09-11-2026: de 208 campos de estado, tipo o motivo,
sólo 12 declaraban su lista en algún esquema del contrato, porque las opciones
sólo llegaban a él a través del formulario de edición —y el estado de una
oportunidad, a propósito, no se edita ahí: se mueve con su acción—.

Así que cada servicio publica en `components.x-opciones` lo que sabe:

- las columnas de sus modelos que declaran `info={"opciones": …}` o un `Enum`;
- los estados de sus máquinas de estado, que son la lista completa por
  definición.

Por nombre de campo y no por objeto: es como el front lo usa —«este valor en
este campo es una opción»— y dos objetos con un `estado` comparten el campo
sin que mezclar sus valores cambie nada al escribirlos.
"""

from __future__ import annotations

from typing import Any


def opciones_del_servicio() -> dict[str, list[str]]:
    from crmcore.datos.estados import MAQUINAS
    from crmcore.db.base import Base

    salida: dict[str, set[str]] = {}
    for mapeador in Base.registry.mappers:
        for columna in mapeador.columns:
            info = getattr(columna, "info", None) or {}
            declaradas = info.get("opciones")
            if not declaradas and info.get("vocabulario"):
                # Los de fábrica de un vocabulario: son códigos, no texto
                # libre. Los que añada la empresa llegan con su rótulo.
                from crmcore import vocabulario

                definida = vocabulario.definicion(str(info["vocabulario"]))
                declaradas = definida.defectos if definida else None
            if not declaradas:
                declaradas = getattr(getattr(columna, "type", None), "enums", None)
            if declaradas:
                salida.setdefault(columna.key, set()).update(str(v) for v in declaradas)
    for maquina in MAQUINAS.values():
        salida.setdefault("estado", set()).update(maquina.estados)
    return {campo: sorted(valores) for campo, valores in sorted(salida.items())}


def publicar_en_el_contrato(app: Any) -> None:
    """Añade `components.x-opciones` al OpenAPI de `app`, una vez."""
    original = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        documento = original()
        documento.setdefault("components", {})["x-opciones"] = opciones_del_servicio()
        return documento

    app.openapi = openapi
