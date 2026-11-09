"""La sincronización de un móvil sin conexión, servida (CRM-06.02.01.04).

Medido el 05-10-2026: `crmcore.movil` resolvía lo difícil —qué es un conflicto
de verdad, qué se guarda cuando lo hay, qué se queda en la cola— y **no lo
alcanzaba ninguna ruta**. El módulo decía de sí mismo «lo que aquí se resuelve
es la parte del servidor», y la parte del servidor no estaba servida: cualquier
aplicación que se escribiera encima tenía que reimplementar las cuatro
decisiones, y la primera que se reimplementa mal es la del conflicto.

Va **por servicio**, como la papelera y la restauración, y por lo mismo: la cola
del móvil lleva operaciones sobre objetos de varios servicios, y cada uno
resuelve los suyos contra sus propios registros. Un único punto central tendría
que leer las tablas de los catorce.

Por defecto devuelve el **plan** —qué se puede aplicar, qué choca y con qué, y
qué se queda esperando— sin escribir. Con `aplicar: true` (09-11-2026) **aplica
lo que no choca** —y lo resuelto por una persona— y devuelve los conflictos;
medido antes: el front no tenía modo sin conexión y la ruta sólo planificaba,
así que lo hecho sin red no llegaba a ningún sitio. No es una segunda puerta de
escritura: escribe con la MISMA función que el PATCH de la ficha genérica
(`operacion_de_ficha`), exigiendo el mismo permiso, con sus mismas reglas de
qué campo es editable. Un objeto con PATCH escrito a mano —con su bloqueo, su
política— no se escribe aquí: sale como `aplicar_por_su_ruta` con la versión
actual, y el cliente lo repite por esa ruta con `If-Match`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from crmcore.logging import get_logger

logger = get_logger(__name__)


class Operacion(BaseModel):
    """Una operación de la cola del móvil."""

    id_cliente: str = Field(
        ...,
        min_length=1,
        description=(
            "Lo genera el MÓVIL antes de mandar nada. Es lo que hace que un "
            "reintento después de un corte no cree una visita duplicada: dejar "
            "que lo genere el servidor obliga a adivinar si la petición que no "
            "contestó llegó o no, y esa duda no tiene respuesta correcta"
        ),
    )
    tipo: str = Field("actualizar", description="crear · actualizar")
    objeto: str = Field("", examples=["contacto"])
    recurso: str = Field(
        "",
        description=(
            "La colección de la API (`accounts`, `contacts`) cuando el cliente no "
            "sabe el objeto de negocio: el front encola la petición que hizo, y "
            "lo que tiene es su ruta. Se traduce con el mismo registro que usan "
            "los informes; deducirlo del plural acierta casi siempre, que es peor"
        ),
    )
    registro_id: UUID | None = None
    version_base: int | None = Field(
        None,
        description=(
            "Sobre qué versión se hizo el cambio. Sin ella no se puede detectar "
            "un conflicto: se aplicaría encima de lo que haya y el cambio de "
            "otra persona desaparecería sin rastro"
        ),
    )
    campos: dict[str, Any] = Field(
        default_factory=dict, description="Lo que el móvil quiere escribir"
    )
    campos_base: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Lo que el móvil **leyó** antes de perder la señal. Hace falta para "
            "una fusión de tres puntos: sin ello no se puede distinguir «el otro "
            "cambió este campo» de «yo escribo encima de un valor que nadie "
            "tocó», y entonces todo cambio sobre un registro que se movió sale "
            "como conflicto — que es la forma de enseñar a pulsar «quedarme con "
            "lo mío» sin leer"
        ),
    )
    encolada_at: str = ""
    en_conflicto: bool = False


class Sincronizar(BaseModel):
    operaciones: list[Operacion] = Field(default_factory=list)
    estrategia: str = Field(
        "",
        description=(
            "Qué hacer con un conflicto, si el cliente ya lo decidió. Vacío: se "
            "devuelve el choque y lo resuelve una persona — que cuesta un minuto, "
            "mientras reconstruir lo perdido cuesta una mañana y a veces no se puede"
        ),
    )
    aplicar: bool = Field(
        False,
        description=(
            "Escribir lo que no choca, además de planificar. Sin él la ruta "
            "sólo devuelve el plan, que es lo que hacía siempre"
        ),
    )


def crear_router_movil(servicio: str) -> APIRouter:
    router = APIRouter(prefix=f"/{servicio}/movil", tags=["móvil sin conexión"])

    @router.post(
        "/sincronizar",
        response_model=dict,
        dependencies=[Depends(exige_permiso("*:read"))],
        summary=f"Qué hacer con la cola del móvil para «{servicio}»",
        description=(
            "**Devuelve el plan, no escribe.** Qué se puede aplicar, qué choca y "
            "con qué campos, y qué se queda esperando. Quien escribe es la ruta "
            "de siempre de cada objeto, con sus permisos y sus validaciones: una "
            "segunda puerta de escritura sin las comprobaciones de la primera es "
            "como se cuela un dato que la pantalla no habría dejado poner.\n\n"
            "**El conflicto se detecta, no se evita.** Dos personas van a tocar "
            "el mismo registro; lo que no puede pasar es que gane el último en "
            "llegar sin que nadie se entere, porque el otro cambio desaparece y "
            "no queda rastro de que existió.\n\n"
            "Y se distingue el choque de verdad —los dos tocaron **el mismo "
            "campo**— del que no lo es. Tratar como conflicto que uno cambiara "
            "el teléfono y otro la dirección enseña a la gente a pulsar "
            "«quedarme con lo mío», que es como se pierde el trabajo del otro "
            "igualmente.\n\n"
            "**Nada se descarta.** Lo que no se puede resolver se queda en la "
            "cola: una cola que tira lo que falla convierte un problema de "
            "sincronización en una pérdida silenciosa de datos."
        ),
    )
    def sincronizar(datos: Sincronizar, db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore import movil
        from crmcore.http.listados import objeto_del_recurso
        from crmcore.metamodelo import es_de_este_servicio, modelo_del_objeto

        operaciones = [op.model_dump() for op in datos.operaciones]
        for op in operaciones:
            if not op.get("objeto") and op.get("recurso"):
                op["objeto"] = objeto_del_recurso(str(op["recurso"]))
        # Las dos comprobaciones de forma van ANTES de tocar la base: una cola
        # sin identificadores no se arregla mirando registros.
        preparado = movil.preparar_envio(operaciones=operaciones)

        plan: list[dict[str, Any]] = []
        for op in operaciones:
            objeto = str(op.get("objeto") or "")
            # Se pregunta por el DUEÑO, no por si la clase está cargada: con
            # varios servicios en un proceso lo segundo contesta que sí a todo
            # y esta rama no se recorre nunca.
            modelo = modelo_del_objeto(objeto) if es_de_este_servicio(objeto, servicio) else None
            if modelo is None:
                # No es de este servicio: se dice y se queda en la cola del
                # móvil para mandarla a quien sea. Descartarla sería perderla.
                plan.append(
                    {
                        "id_cliente": op["id_cliente"],
                        "accion": "otro_servicio",
                        "porque": f"«{op.get('objeto')}» no lo guarda «{servicio}»",
                    }
                )
                continue
            if op.get("tipo") == "crear" or not op.get("registro_id"):
                plan.append({"id_cliente": op["id_cliente"], "accion": "aplicar"})
                continue

            fila = db.get(modelo, op["registro_id"])
            if fila is None or getattr(fila, "tenant_id", None) != principal.tenant_id:
                plan.append(
                    {
                        "id_cliente": op["id_cliente"],
                        "accion": "descartada_en_origen",
                        "porque": (
                            "El registro ya no existe. No se recrea: recrearlo "
                            "devolvería a la vida algo que alguien borró a "
                            "propósito, y sin su historia."
                        ),
                    }
                )
                continue

            # FUSIÓN DE TRES PUNTOS. `detectar_conflicto` espera los campos que
            # **cambió cada lado**, no los valores actuales: pasarle los
            # actuales convierte en conflicto cualquier escritura sobre un
            # registro que se movió, aunque el otro tocara otra cosa — y eso es
            # lo que enseña a pulsar «quedarme con lo mío» sin leer.
            #
            # Con la base que trae el móvil se sabe quién cambió qué:
            #   cambió el servidor  ⟺  actual ≠ base
            #   cambió el cliente   ⟺  entrante ≠ base
            base = dict(op.get("campos_base") or {})
            entrantes = dict(op.get("campos") or {})
            cambio_el_cliente = {
                c: v for c, v in entrantes.items() if c not in base or base[c] != v
            }
            cambio_el_servidor = {
                c: getattr(fila, c, None)
                for c in entrantes
                if c in base and getattr(fila, c, None) != base[c]
            }
            # Lo que se escribirá si no choca: SÓLO lo que cambió el móvil.
            # Escribir todo lo que trae pisaría con valores viejos los campos
            # que otra persona cambió y él ni tocó.
            op["_cambios"] = cambio_el_cliente
            choque = movil.detectar_conflicto(
                version_base=int(op.get("version_base") or 0),
                version_servidor=int(getattr(fila, "version", 0) or 0),
                campos_cliente=cambio_el_cliente,
                campos_servidor=cambio_el_servidor,
            )
            if not choque["hay_conflicto"]:
                plan.append(
                    {
                        "id_cliente": op["id_cliente"],
                        "accion": "aplicar",
                        "porque": choque["porque"],
                        "version_actual": int(getattr(fila, "version", 0) or 0),
                    }
                )
                continue

            entrada = {
                "id_cliente": op["id_cliente"],
                "accion": "conflicto",
                **choque,
                # Lo que hay AHORA en los campos que chocan: es lo que enseña la
                # pantalla de conflictos al lado de lo del móvil. Sin ello, «lo
                # suyo» es una palabra y no un valor que se pueda comparar.
                "valores_servidor": {
                    c: _a_json(getattr(fila, c, None)) for c in (choque.get("campos") or [])
                },
            }
            if datos.estrategia:
                entrada["resolucion"] = movil.resolver(
                    estrategia=datos.estrategia,
                    campos_cliente=cambio_el_cliente,
                    campos_servidor=cambio_el_servidor,
                    campos_en_conflicto=list(choque.get("campos") or []),
                )
            plan.append(entrada)

        if datos.aplicar:
            _aplicar_plan(db, principal, operaciones, plan)

        pendientes = [
            {
                **{k: v for k, v in op.items() if k != "_cambios"},
                "en_conflicto": any(
                    p["id_cliente"] == op["id_cliente"] and p["accion"] == "conflicto" for p in plan
                ),
            }
            for op in operaciones
            # Lo ya escrito sale de la cola: contarlo como pendiente haría que el
            # aviso de «tienes cambios sin subir» no se apagara nunca.
            if not any(
                p["id_cliente"] == op["id_cliente"] and p["accion"] == "aplicada" for p in plan
            )
        ]
        return {
            "servicio": servicio,
            "preparado": preparado,
            "plan": plan,
            # El estado de la cola va en la MISMA respuesta: pedirlo aparte
            # significa que nadie lo pide, y entonces una operación que lleva una
            # semana sin subir no la mira nunca nadie.
            "cola": movil.estado_de_la_cola(pendientes=pendientes),
        }

    return router


def _a_json(valor: Any) -> Any:
    """Un valor de columna como lo devolvería la API."""
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, (Decimal, UUID)):
        return str(valor)
    return valor


def _aplicar_plan(
    db: Any, principal: Any, operaciones: list[dict[str, Any]], plan: list[dict[str, Any]]
) -> None:
    """Escribe lo que el plan dice que se puede aplicar (CRM-06.02.01.04).

    Por la MISMA función que el PATCH de la ficha genérica y con su permiso:
    una segunda puerta de escritura con menos comprobaciones es como se cuela
    un dato que la pantalla no habría dejado poner. Cada operación va en su
    propio punto de guardado: que una falle (un campo que no valida) no tira
    las otras ni deja la transacción rota a medias.

    Lo que no se puede escribir aquí —una creación, o un objeto con su PATCH
    escrito a mano— no se pierde: sale como `aplicar_por_su_ruta` con la versión
    actual, y el cliente lo repite por la ruta de siempre con `If-Match`.
    """
    from pydantic import ValidationError

    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.errors import CrmError
    from crmcore.http.listados import operacion_de_ficha
    from crmcore.metamodelo import modelo_del_objeto
    from crmcore.resiliencia import exigir_escritura

    exigir_escritura()
    uow = UnidadDeTrabajo(db=db, tenant_id=principal.tenant_id)
    por_id = {op["id_cliente"]: op for op in operaciones}
    for entrada in plan:
        if entrada.get("accion") != "aplicar":
            continue
        op = por_id[entrada["id_cliente"]]
        objeto = str(op.get("objeto") or "")
        escribir = operacion_de_ficha(objeto, "actualizar")
        if op.get("tipo") == "crear" or not op.get("registro_id") or escribir is None:
            entrada["accion"] = "aplicar_por_su_ruta"
            entrada["porque"] = (
                "Se escribe por la ruta de siempre del objeto, que tiene sus propias "
                "reglas: aquí se escribiría sin ellas."
            )
            continue
        permiso = operacion_de_ficha(objeto, "permiso_actualizar") or f"{objeto}:write"
        if not principal.tiene(permiso):
            entrada["accion"] = "rechazada"
            entrada["porque"] = f"No tienes el permiso «{permiso}» para escribir esto."
            continue
        punto = db.begin_nested()
        try:
            escribir(uow, op["registro_id"], dict(op.get("_cambios", op.get("campos")) or {}))
            punto.commit()
        except (CrmError, ValidationError) as error:
            punto.rollback()
            entrada["accion"] = "rechazada"
            entrada["porque"] = str(error)
            entrada["error_code"] = getattr(error, "error_code", "")
            continue
        modelo = modelo_del_objeto(objeto)
        fila = db.get(modelo, op["registro_id"]) if modelo is not None else None
        entrada["accion"] = "aplicada"
        entrada["version"] = int(getattr(fila, "version", 0) or 0)
    uow._volcar_eventos()
