"""Por qué campos se puede filtrar un listado, preguntado a él (CRM-00.03.01.05).

**Medido el 29-10-2026.** El contrato de `GET /accounts` declara siete
parámetros —`limite`, `cursor`, `orden`, `buscar`, `estado`, `owner_id`— y el
servidor acepta filtros sobre **treinta** columnas, con nueve operadores:
rangos, listas, «vacío» y «no vacío». Ninguno se puede descubrir leyendo el
contrato: la única forma de enterarse es pedir uno mal y leer el 422, que sí los
lista.

Eso lo paga todo el que integra, y se vio con el asistente de Nexus: a «hay
contactos sin teléfono» contestó que la API no ofrece manera de filtrar por eso.
**Sí la ofrece** —`?telefono__vacio=true`— y él no tenía cómo saberlo.

**Por qué no se publica en el OpenAPI y hace falta una ruta.** El conjunto
depende de **quién pregunta**: por un campo que esa persona ve enmascarado no se
puede filtrar, porque filtrarlo lo reconstruye a base de preguntar
—`?telefono=6…` una y otra vez— sin llegar a verlo nunca. Un contrato estático
diría que se puede filtrar por el teléfono y para la mitad de la plantilla sería
mentira. Se contesta en caliente y con la identidad de quien llama.

Va por servicio, como el rastro y la papelera: el modelo de cada objeto vive en
el proceso que lo guarda, y es ahí donde se sabe qué columnas tiene.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep


def crear_router_filtros(servicio: str) -> APIRouter:
    router = APIRouter(prefix=f"/{servicio}/filtros", tags=["filtros de un listado"])

    @router.get(
        "",
        summary="De qué objetos de este servicio se puede preguntar por sus filtros",
        description=(
            "La lista de objetos que este servicio guarda. Existe para no tener "
            "que adivinar el nombre: preguntar por uno que no es da un 404 y no "
            "dice cuáles hay, que es la forma de que alguien pruebe seis veces."
        ),
    )
    def objetos_del_servicio(principal: AutenticadoDep) -> Any:
        from crmcore.metamodelo import objetos_de_este_servicio

        return {"servicio": servicio, "objetos": objetos_de_este_servicio(servicio)}

    @router.get(
        "/{objeto}",
        summary="Por qué campos puede filtrar ESTA persona este listado",
        description=(
            "Los campos y los operadores, resueltos con la identidad de quien "
            "pregunta.\n\n"
            "**No sale del contrato y no puede salir**: por un campo que esta "
            "persona ve enmascarado no se puede filtrar —hacerlo lo reconstruye "
            "preguntando, sin llegar a verlo— así que el conjunto cambia con el "
            "rol. Un contrato estático diría que se puede filtrar por el "
            "teléfono y para media plantilla sería mentira."
        ),
    )
    def filtros_de(objeto: str, db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.authz.proyeccion import columnas_usables
        from crmcore.http.listados import OPERADORES_DE_URL
        from crmcore.metamodelo import es_de_este_servicio, modelo_del_objeto

        # **`es_de_este_servicio` y no «¿existe el modelo?»**, que no es lo
        # mismo. El registro de modelos es del PROCESO: cuando varios servicios
        # comparten uno —la suite entera, o las pruebas— es la unión de todos,
        # y preguntar si el modelo existe hace que `party` conteste por las
        # oportunidades de `sales`. Lo cazó su propia prueba: pasaba sola y
        # fallaba en la suite completa.
        modelo = modelo_del_objeto(objeto) if es_de_este_servicio(objeto, servicio) else None
        if modelo is None:
            from crmcore.metamodelo import objetos_de_este_servicio

            raise NoEncontrado(
                f"Este servicio no guarda ningún «{objeto}»",
                error_code="filtros.objeto_desconocido",
                # Y cuáles sí: un 404 que no dice las alternativas se contesta
                # probando, que es justo lo que esta ruta viene a evitar.
                detalle={"objetos": objetos_de_este_servicio(servicio)},
            )

        tabla = getattr(modelo, "__table__", None)
        columnas = set(tabla.columns.keys()) if tabla is not None else set()
        usables = columnas_usables(
            columnas,
            modelo=modelo,
            objeto=objeto,
            roles=frozenset(getattr(principal, "roles", frozenset())),
            es_admin=bool(getattr(principal, "es_admin_plataforma", False)),
            tenant_id=getattr(principal, "tenant_id", None),
            db=db,
        )
        # `tenant_id` nunca, igual que al filtrar: lo pone la RLS, y ofrecerlo
        # daría a entender que se puede pedir el de otro.
        usables = {c for c in usables if c != "tenant_id"}
        tapados = sorted(columnas - usables - {"tenant_id"})

        return {
            "objeto": objeto,
            "se_puede_filtrar_por": sorted(usables),
            "operadores": dict(OPERADORES_DE_URL),
            "como_se_escribe": "?campo=valor · ?campo__desde=… · ?campo__vacio=true",
            # **Lo que NO se puede, y por qué.** Devolver sólo lo permitido deja
            # a quien integra buscando un campo que ve en la respuesta y no
            # puede usar, sin saber si es que no existe o que no le toca.
            "no_se_puede_filtrar_por": tapados,
            "porque_esos_no": (
                "Son campos que esta persona no ve en claro. Filtrar por uno "
                "enmascarado lo reconstruye a base de preguntar —«¿empieza por "
                "6?», «¿y por 7?»— sin llegar a verlo nunca."
            ),
            "que_significa": (
                "Esta lista es de QUIEN pregunta, no del listado: con otro rol "
                "sale otra. Por eso no está en el contrato."
            ),
        }

    return router
