"""El modelo que contecintelligence puede explotar (CRM-00.04.03.06).

La explotación no se reimplementa aquí (RT-4): la resuelve contecintelligence de
forma frontless. Pero para ofrecer un campo como dimensión o como métrica hace
falta **saber que existe y de qué tipo es**, y los campos que un cliente añade en
su implantación no están en ningún esquema que contecintelligence pueda leer.

Este módulo es el puente: publica, por tenant, qué objetos hay, qué campos
propios tienen, de qué tipo son y —lo que de verdad lo hace usable— **en qué
vista SQL están ya proyectados como columnas tipadas**. Con eso, un campo nuevo
aparece como dimensión sin que nadie modele nada aparte, que es la diferencia
entre «se puede informar» y «se puede informar después de que alguien lo
configure».

Lo que **no** se manda: valores. Va el modelo, nunca el dato. Mandar datos aquí
convertiría una descripción de esquema en una copia del CRM fuera de su sitio.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore import metamodelo
from crmcore.logging import get_logger
from sqlalchemy.orm import Session

logger = get_logger(__name__)

# Qué se puede hacer con cada tipo en un informe. Va explícito y no deducido por
# el consumidor: si cada herramienta decidiera por su cuenta, una acabaría
# ofreciendo «sumar» sobre un código postal, que es un número que no se suma.
ROL_ANALITICO = {
    "numero": "metrica",
    "moneda": "metrica",
    "porcentaje": "metrica",
    "fecha": "temporal",
    "fecha_hora": "temporal",
    "booleano": "dimension",
    "lista": "dimension",
    "lista_multiple": "dimension",
    "texto": "dimension",
    "texto_largo": "descriptivo",
    "json": "descriptivo",
    "fichero": "descriptivo",
    "geolocalizacion": "geografico",
}

# Sensibilidades que no salen al modelo semántico. Un campo personal ofrecido
# como dimensión acaba en un cuadro de mando que alguien comparte por correo, y
# el enmascaramiento por rol que sí aplica la API no llega hasta ahí.
NO_EXPLOTABLES = frozenset({"personal", "especial"})

# Objetos estándar y su tabla. Igual que en la previsualización de esquema: se
# escribe en vez de adivinarse del plural, porque un nombre mal adivinado daría
# una vista que no existe y un informe vacío que nadie sabría explicar.
TABLAS = {
    "cuenta": "cuentas",
    "contacto": "contactos",
    "lead": "leads",
    "oportunidad": "oportunidades",
    "actividad": "actividades",
}


def modelo_de(db: Session, tenant_id: UUID, objetos: list[str] | None = None) -> dict[str, Any]:
    """Qué puede explotar contecintelligence de este tenant, y cómo."""
    nombres = objetos or sorted(TABLAS)
    salida: list[dict[str, Any]] = []
    excluidos: list[str] = []

    for objeto in nombres:
        campos = metamodelo.campos_de(db, tenant_id, objeto)
        if not campos:
            continue
        explotables = []
        for definicion in campos:
            if not definicion.get("activo", True):
                continue
            sensibilidad = str(definicion.get("sensibilidad") or "interno")
            nombre = str(definicion.get("nombre"))
            if sensibilidad in NO_EXPLOTABLES:
                excluidos.append(f"{objeto}.{nombre}")
                continue
            tipo = str(definicion.get("tipo", "texto"))
            explotables.append(
                {
                    "nombre": nombre,
                    "tipo": tipo,
                    "rol": ROL_ANALITICO.get(tipo, "dimension"),
                    "opciones": (definicion.get("restricciones") or {}).get("opciones") or [],
                    # Se dice si está indexado: una dimensión sin índice sobre
                    # millones de filas se puede ofrecer igual, pero quien monte
                    # el cuadro de mando merece saber que va a ir lento.
                    "indexado": bool(definicion.get("indexado")),
                }
            )
        if not explotables:
            continue
        salida.append(
            {
                "objeto": objeto,
                "tabla": TABLAS.get(objeto),
                # La vista tipada es lo que hace que esto sea usable sin modelar
                # nada: las columnas ya vienen con su tipo y no hay que saber que
                # por debajo hay JSONB.
                "vista": metamodelo.nombre_de_vista(objeto, tenant_id),
                "campos": explotables,
            }
        )

    return {
        "tenant": str(tenant_id),
        "objetos": salida,
        # Se dice lo que se ha dejado fuera y por qué. Omitirlo en silencio haría
        # que alguien buscara un campo que existe, no lo encontrara y concluyera
        # que el sistema no lo tiene.
        "excluidos_por_sensibilidad": sorted(excluidos),
        "motivo_exclusion": (
            "Los campos personales y de categoría especial no se ofrecen como "
            "dimensión: acabarían en un cuadro de mando que alguien comparte, y "
            "el enmascaramiento por rol de la API no llega hasta ahí."
        ),
        "contiene_datos": False,
    }
