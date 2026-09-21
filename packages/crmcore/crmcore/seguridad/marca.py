"""Marca de agua e identificación de origen en exportaciones (CRM-00.05.03.07).

El audit trail dice **quién exportó**. Esto dice **de dónde salió este fichero**,
que es una pregunta distinta y se hace en otro momento: cuando la hoja de
cálculo con la cartera de clientes aparece en el ordenador de un competidor, el
audit trail de quien la perdió no está disponible.

La marca va **dentro del fichero**, no en el nombre ni en una cabecera HTTP: el
nombre se cambia y la cabecera se pierde en cuanto alguien lo reenvía, que es
justo el momento en el que hace falta.

Lo que **no** es: una protección. Quien sepa que está ahí la quita. Lo que hace
es cerrar el caso más común con diferencia —una copia reenviada sin mala
intención, o con ella pero sin cuidado— y dejar constancia de que el fichero
salió identificado, que a efectos de una reclamación no es poco.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


def firma(
    *, tenant_id: UUID, usuario_id: UUID | None, cuando: datetime | None = None
) -> dict[str, Any]:
    """Los datos de origen de una exportación.

    El identificador del usuario va **resumido** y no en claro: el fichero puede
    acabar en manos de cualquiera y el identificador en claro es un dato de la
    plantilla del cliente. Resumido sigue sirviendo para cotejarlo contra el
    audit trail, que es para lo que hace falta.
    """
    momento = cuando or datetime.now(timezone.utc)
    traza = hashlib.sha256(f"{tenant_id}|{usuario_id}|{momento.isoformat()}".encode()).hexdigest()
    return {
        "origen": "contecrm",
        "tenant": str(tenant_id),
        "exportado_at": momento.isoformat(),
        "traza": traza[:32],
    }


def cabecera_csv(datos: dict[str, Any]) -> str:
    """La marca como comentario al principio de un CSV.

    Con `#` delante: Excel y las herramientas habituales la enseñan como una
    fila más y no rompen la carga, y quien abra el fichero con un editor la ve
    primero. Ponerla al final la haría invisible en un fichero de mil filas.
    """
    partes = "; ".join(f"{k}={v}" for k, v in datos.items())
    return f"# {partes}\n"


def marcar_jsonl(datos: dict[str, Any]) -> str:
    """La marca como primera línea de un JSON Lines.

    Una línea más con `_marca` dentro, que cualquier lector de JSON Lines
    procesa sin enterarse y que quien la busque encuentra en la primera línea.
    """
    import json

    return json.dumps({"_marca": datos}, ensure_ascii=False) + "\n"


def marcar_texto(cuerpo: str, datos: dict[str, Any]) -> str:
    """Un fichero de texto, con la marca arriba y abajo.

    Las dos, porque un recorte de las primeras líneas es lo más habitual al
    pegar un fragmento en un correo, y un recorte del final también. Estar en
    los dos sitios no lo hace irrompible; lo hace más caro de romper sin querer.
    """
    pie = "; ".join(f"{k}={v}" for k, v in datos.items())
    return f"{cabecera_csv(datos)}{cuerpo}\n# {pie}\n"
