"""Materializar un campo personalizado, en línea y por lotes (CRM-00.04.03.11).

La decisión ya estaba medida: `candidatos_a_materializar` dice qué campos
justifican una columna de verdad por volumen de escrituras. Lo que faltaba era
**hacerlo**, y hacerlo sin parar a nadie.

Va como trabajo largo y no como una petición porque el relleno de una tabla con
millones de filas no cabe en los diez segundos del gateway, y porque **tiene que
poder reanudarse**: un despliegue a mitad del relleno no puede dejar media
columna puesta y a nadie mirando.

El orden de los cuatro pasos no es un detalle de implementación, es la
capacidad: *«con migración en línea y sin bloquear a los demás tenants»*.

  1. la columna se añade **nullable**, que en PostgreSQL moderno es instantáneo
     y no reescribe la tabla —con `NOT NULL` o `DEFAULT` sí, y eso bloquea a
     los mil tenants que la comparten—;
  2. se rellena **por lotes**, cada uno en su transacción;
  3. se **indexa** sólo sobre las filas de ese tenant;
  4. y **sólo entonces** se marca como materializado. Marcarlo antes haría que
     las consultas leyeran una columna a medio rellenar, y las listas saldrían
     incompletas sin que fallara nada — que es peor que fallar.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from crmcore.datos.trabajos import Tanda, Trabajo, registrar_ejecutor
from crmcore.logging import get_logger

logger = get_logger(__name__)

TIPO = "metadata.materializar_campo"


def _ejecutar(db: Session, trabajo: Trabajo, tope: int) -> Tanda:
    from sqlalchemy import select

    from crmcore.metamodelo import (
        UsoCampo,
        crear_columna_materializada,
        indexar_columna,
        quedan_por_rellenar,
        rellenar_columna,
        tabla_del_objeto,
    )

    entrada = trabajo.entrada or {}
    objeto = str(entrada.get("objeto") or "")
    campo = str(entrada.get("campo") or "")
    tipo = str(entrada.get("tipo") or "texto")
    tenant_id = trabajo.tenant_id

    tabla = tabla_del_objeto(objeto)
    if not tabla:
        # Este proceso no guarda ese objeto. No es un fallo: el trabajo se
        # encoló en el servicio que sí lo guarda y aquí no hay nada que hacer.
        return Tanda(avanzados=0, ok=0, resultado={"aplicado": False, "porque": "objeto de otro"})

    # Paso 1, idempotente: si ya está, no hace nada.
    crear_columna_materializada(db, tabla, campo, tipo)

    # Paso 2: un lote por vuelta. El tope lo pone el worker, que es quien sabe
    # cuánto puede tardar un commit.
    lote = max(100, min(tope, 5_000))
    rellenadas = rellenar_columna(db, tabla, campo, tipo, tenant_id, lote=lote)
    quedan = quedan_por_rellenar(db, tabla, campo, tenant_id)
    if quedan:
        # Todavía no se marca ni se indexa: se indexa al final para no mantener
        # el índice durante el relleno, que lo hace más lento y más grande.
        return Tanda(
            avanzados=rellenadas,
            ok=rellenadas,
            resultado={"fase": "rellenando", "quedan": quedan, "columna": f"c_{campo}"},
        )

    # Pasos 3 y 4, cuando ya no queda nada por rellenar.
    indice = indexar_columna(db, tabla, campo, tenant_id)
    uso = db.execute(
        select(UsoCampo).where(
            UsoCampo.tenant_id == tenant_id,
            UsoCampo.objeto == objeto,
            UsoCampo.campo == campo,
        )
    ).scalar_one_or_none()
    if uso is not None:
        # Ahora sí: a partir de aquí las consultas leen de la columna y el
        # campo deja de salir como candidato.
        uso.materializado = True
    logger.info(
        "materializar.terminado", objeto=objeto, campo=campo, indice=indice, tenant=str(tenant_id)
    )
    return Tanda(
        avanzados=rellenadas,
        ok=rellenadas,
        resultado={
            "fase": "activa",
            "columna": f"c_{campo}",
            "indice": indice,
            "quedan": 0,
            # Se dice lo que NO cambia: la columna es de la tabla, común a
            # todos, y sólo se ha rellenado la de este tenant. Los demás siguen
            # leyendo del JSONB, que es lo que el `COALESCE` de la expresión
            # garantiza.
            "los_demas_tenants": "siguen leyendo del JSONB; su columna queda nula",
        },
    )


def encolar_materializacion(
    db: Session,
    *,
    tenant_id: UUID,
    objeto: str,
    campo: str,
    tipo: str,
    pedido_por: UUID | None = None,
) -> Any:
    """Acepta la materialización y devuelve su ficha."""
    from crmcore.datos.trabajos import encolar

    return encolar(
        db,
        tenant_id=tenant_id,
        tipo=TIPO,
        entrada={"objeto": objeto, "campo": campo, "tipo": tipo},
        pedido_por=pedido_por,
    )


# Importar este módulo registra el ejecutor, igual que los demás trabajos: la
# API y el worker son procesos distintos y ninguno se puede fiar del otro.
registrar_ejecutor(TIPO, _ejecutar)
