"""El punto único de decisión (CRM-00.05.02.18, CRM-00.05.02.19, CRM-00.05.02.20).

Todo lo que lee o escribe un registro pasa por aquí. No es una capa más: es la
respuesta al fallo que tenía este subsistema, que era tener un motor de
políticas impecable al que **no llamaba nadie**.

Tres entradas, y las tres tienen que dar la misma respuesta o el sistema miente:

  * `exigir(...)` — la ficha y la escritura. Evalúa en Python sobre el registro.
  * `filtro(...)` — el listado. La MISMA condición traducida a SQL.
  * `campos_ocultos(...)` — la proyección. Qué columnas se caen.

Que la ficha y el listado coincidan no es una aspiración: es lo que impide el
fallo clásico de estos sistemas, un listado que enseña un registro que la ficha
luego niega —o al revés, un registro invisible en la lista y accesible por su
identificador—.

**Ante la duda, se deniega.** Si una condición no se puede traducir a SQL o
mira una columna que el modelo no tiene, el listado no devuelve nada en vez de
devolverlo todo. En compartición la duda amplía —comparte de más, nunca de
menos— porque ahí no aplicar la regla deja de enseñar algo que se podría ver.
Aquí es al revés: una política ABAC **restringe**, así que no aplicarla enseña
lo que no se debe. La asimetría es deliberada y es la parte que hay que tener
clara al leer los dos módulos juntos.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, false, or_
from sqlalchemy.orm import Session

from crmcore.authz.abac import Condicion, Decision, Politica, ambito_estandar, evaluar
from crmcore.logging import get_logger

logger = get_logger(__name__)


def decidir(
    db: Session,
    *,
    objeto: str,
    accion: str,
    registro: Any = None,
    tenant_id: UUID | None = None,
) -> Decision:
    """Decide sobre ESTE registro y dice por qué.

    Sin políticas aplicables devuelve permitido: el ABAC **restringe**, y lo que
    autoriza de base es el permiso del rol, que ya se ha comprobado antes de
    llegar aquí.
    """
    from crmcore.authz.politicas import cargar
    from crmcore.tenancy.context import contexto_actual

    tid = tenant_id or contexto_actual().tenant_id
    if tid is None:
        return Decision(permitido=True)
    from crmcore.authz import motor_externo

    politicas = cargar(db, tid, alcance="registro")
    ambito = ambito_estandar(registro=_como_dict(registro))
    interna = (
        evaluar(politicas, objeto=objeto, accion=accion, ambito=ambito)
        if politicas
        else Decision(permitido=True)
    )
    # El motor externo se consulta aunque no haya políticas propias: el cliente
    # que lo activa lo hace precisamente para que decida el suyo. Si no está
    # configurado, `consultar` devuelve `None` y esto no cuesta nada.
    return motor_externo.combinar(
        interna,
        motor_externo.consultar(objeto=objeto, accion=accion, ambito=ambito, tenant_id=tid),
    )


def exigir(
    db: Session,
    *,
    objeto: str,
    accion: str,
    registro: Any = None,
    tenant_id: UUID | None = None,
) -> None:
    """Como `decidir`, pero corta con 403 y **con la explicación dentro**.

    El detalle lleva la política que decide y la condición que falló. Un «no
    tienes permiso» a secas es el ticket de soporte más caro de cualquier CRM,
    y quien lo recibe no puede hacer nada con él.
    """
    from crmcore.errors import Prohibido

    decision = decidir(db, objeto=objeto, accion=accion, registro=registro, tenant_id=tenant_id)
    if decision.permitido:
        return
    raise Prohibido(
        "Una política de acceso lo impide",
        error_code="abac.denegado",
        detalle={
            "politica": decision.politica_decisiva,
            "porque": decision.explicacion(),
        },
    )


def filtro(
    db: Session,
    modelo: type,
    *,
    objeto: str,
    accion: str = "read",
    tenant_id: UUID | None = None,
) -> Any:
    """La misma decisión, como condición de `WHERE`. `None` si no hay política.

    Se resuelve en dos partes, y la separación es lo que lo hace posible:

      * Las condiciones sobre el **usuario y el contexto** no dependen de la
        fila, así que se evalúan una vez aquí. Una política que exige horario
        laboral no se traduce a SQL: o son las cuatro de la tarde para toda la
        consulta, o no lo son para ninguna fila.
      * Las condiciones sobre el **registro** sí, y esas van al `WHERE`.
    """
    from crmcore.authz.politicas import cargar
    from crmcore.tenancy.context import contexto_actual

    tid = tenant_id or contexto_actual().tenant_id
    if tid is None:
        return None
    politicas = [p for p in cargar(db, tid, alcance="registro") if p.aplica_a(objeto, accion)]
    if not politicas:
        return None

    ambito = ambito_estandar()
    condiciones = []
    for politica in politicas:
        parte = _politica_a_sql(politica, modelo, ambito)
        if parte is not None:
            condiciones.append(parte)
    if not condiciones:
        return None
    # Conjunción entre políticas, igual que en `evaluar`: si dos aplican, tienen
    # que pasar las dos. Con disyunción, añadir una política permisiva anularía
    # en silencio a una restrictiva ya existente.
    return and_(*condiciones)


def _politica_a_sql(politica: Politica, modelo: type, ambito: dict[str, Any]) -> Any:
    """Traduce una política. `None` si no restringe nada, `false()` si lo niega todo."""
    del_registro: list[Condicion] = []
    fuera_del_registro: list[bool] = []
    for condicion in politica.condiciones:
        if condicion.atributo.startswith("registro."):
            del_registro.append(condicion)
        else:
            fuera_del_registro.append(condicion.evaluar(ambito))

    if politica.combinacion == "todas":
        if fuera_del_registro and not all(fuera_del_registro):
            # Una condición de contexto que no se cumple tumba la política
            # entera para todas las filas.
            return false()
        partes = [_condicion_a_sql(c, modelo, ambito, politica.nombre) for c in del_registro]
        return and_(*partes) if partes else None

    # `alguna`: si algo de fuera del registro ya se cumple, la política pasa
    # para toda la consulta y no hay nada que filtrar.
    if any(fuera_del_registro):
        return None
    partes = [_condicion_a_sql(c, modelo, ambito, politica.nombre) for c in del_registro]
    if not partes:
        # Ninguna condición se cumple y no queda nada por mirar en la fila.
        return false()
    return or_(*partes)


def _condicion_a_sql(
    condicion: Condicion, modelo: type, ambito: dict[str, Any], politica: str
) -> Any:
    """Una condición sobre el registro, como expresión SQL. Nunca devuelve `None`.

    Lo que no se puede traducir se convierte en `false()` y se registra. Dejarlo
    pasar sería enseñar filas que la política niega, y el síntoma sería que la
    ficha y el listado dicen cosas distintas del mismo registro — que es el
    fallo por el que existe este módulo.
    """
    from crmcore.authz.abac import a_sql

    campo = condicion.atributo.split(".", 1)[1]
    columna = getattr(modelo, campo, None)
    if columna is None:
        logger.error(
            "abac.condicion_sin_columna",
            politica=politica,
            atributo=condicion.atributo,
            modelo=getattr(modelo, "__name__", str(modelo)),
        )
        return false()

    valor = condicion.valor
    if isinstance(valor, str) and valor.startswith("@"):
        # El motor resuelve `@usuario.id` contra el ámbito; en SQL no hay
        # ámbito, así que se resuelve ANTES y va como literal.
        from crmcore.authz.abac import _leer

        valor = _leer(ambito, valor[1:])

    expresion = a_sql(columna, condicion.operador, valor)
    if expresion is None:
        logger.error(
            "abac.condicion_sin_traduccion",
            politica=politica,
            atributo=condicion.atributo,
            operador=condicion.operador,
        )
        return false()
    return expresion


def campos_ocultos(
    db: Session,
    *,
    objeto: str,
    accion: str = "read",
    registro: Any = None,
    tenant_id: UUID | None = None,
) -> set[str]:
    """Campos que una política esconde en ESTE registro (CRM-00.05.02.20).

    Es distinto de la proyección por sensibilidad, y las dos conviven a
    propósito: la sensibilidad dice «el identificador fiscal es dato personal y
    este rol no lo ve nunca», y esto dice «el margen de las oportunidades de
    otra unidad de negocio no se ve». Una es del campo y la otra del registro
    que se está mirando.
    """
    from crmcore.authz.politicas import campos_de, cargar
    from crmcore.tenancy.context import contexto_actual

    tid = tenant_id or contexto_actual().tenant_id
    if tid is None:
        return set()
    politicas = [p for p in cargar(db, tid, alcance="campos") if p.aplica_a(objeto, accion)]
    if not politicas:
        return set()

    ambito = ambito_estandar(registro=_como_dict(registro))
    ocultos: set[str] = set()
    for politica in politicas:
        if not politica.evaluar(ambito):
            ocultos |= set(campos_de(tid, politica.nombre))
    return ocultos


def _como_dict(registro: Any) -> Any:
    """El ámbito trabaja con diccionarios; un modelo se convierte al vuelo."""
    if registro is None or isinstance(registro, dict):
        return registro
    if hasattr(registro, "a_dict"):
        return registro.a_dict()
    return registro
