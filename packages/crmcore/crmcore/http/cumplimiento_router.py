"""RAT e informe de cumplimiento por servicio (CRM-07.03.01.04, CRM-07.03.01.07).

`crmcore.cumplimiento` sabía componer las dos cosas y no había ninguna ruta que
llegara hasta ellas. Un registro de tratamiento que solo existe dentro del
proceso no lo lee un auditor, y un informe que nadie puede pedir es un informe
que no existe.

Se monta solo en `crear_servicio`. Cada servicio publica **lo suyo**: el RAT
completo de una instalación es la unión del de cada servicio, porque ninguno lee
el esquema de otro y por tanto ninguno puede hablar de los datos de otro.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso


def modelos_del_servicio() -> dict[str, type]:
    """Los modelos cargados en este proceso, por nombre de tabla.

    Es lo que hace que el mapa de datos personales no se quede viejo: sale del
    modelo, no de un documento. Cuando alguien añade un campo con datos
    personales, aparece aquí sin que nadie lo transcriba — y si no declara su
    sensibilidad, el gate de datos personales lo caza antes de que llegue a
    producción.
    """
    from crmcore.db.base import Base

    salida: dict[str, type] = {}
    for mapper in Base.registry.mappers:
        tabla = getattr(mapper.class_, "__table__", None)
        if tabla is not None:
            salida[tabla.name] = mapper.class_
    return salida


def crear_router_cumplimiento(servicio: str) -> APIRouter:
    # Cuelga del nombre del servicio: cada uno publica el RAT de lo suyo, y sin
    # el segmento el gateway no podría distinguir doce rutas idénticas.
    router = APIRouter(prefix=f"/{servicio}/cumplimiento", tags=["cumplimiento"])

    @router.get(
        "/rat",
        dependencies=[Depends(exige_permiso("cumplimiento:leer"))],
        summary=f"Registro de actividades de tratamiento de «{servicio}»",
        description=(
            "El RAT que exige el RGPD (CRM-07.03.01.04), compuesto de lo que "
            "declara el modelo —qué campos llevan datos personales y de qué "
            "categoría— y de lo que se declara a mano —finalidad, base legal, "
            "plazo y destinatarios—, que son decisiones y no datos técnicos.\n\n"
            "**Los huecos se dicen.** Un objeto con datos personales y sin "
            "tratamiento declarado sale en la lista de huecos, y un tratamiento "
            "declarado sobre un objeto que ya no tiene datos personales también. "
            "Un RAT que presenta como completo lo que no lo está es peor que no "
            "tenerlo, porque nadie vuelve a mirarlo."
        ),
    )
    def rat(db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.cumplimiento import registro_de_tratamiento

        # Con la sesión, para que lo que este cliente haya ajustado mande sobre
        # lo que trae el producto: la finalidad y la base legal las decide el
        # responsable del tratamiento, que es él y no el fabricante.
        return {"servicio": servicio, **registro_de_tratamiento(modelos_del_servicio(), db)}

    @router.get(
        "/informe",
        dependencies=[Depends(exige_permiso("cumplimiento:leer"))],
        summary=f"Evidencias de cumplimiento de «{servicio}» para este tenant",
        description=(
            "Lo que un auditor pide, junto y sin tener que pedirlo "
            "(CRM-07.03.01.07): RAT, integridad del audit trail, políticas de "
            "acceso y lo que cada servicio aporte.\n\n"
            "Se compone de lo que ya existe en vez de mantener un informe "
            "aparte: uno que se rellena a mano dice lo que alguien quería que "
            "dijera. Y cuando una parte no se puede leer **se dice**, en vez de "
            "omitirla — un apartado ausente se lee como «no aplica», y la "
            "diferencia con «no se ha podido comprobar» es la que importa en una "
            "auditoría."
        ),
    )
    def informe(db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.cumplimiento import informe_de_cumplimiento

        return {
            "servicio": servicio,
            **informe_de_cumplimiento(db, principal.tenant_id, modelos_del_servicio()),
        }

    @router.get(
        "/matriz-permisos",
        dependencies=[Depends(exige_permiso("cumplimiento:leer"))],
        summary=f"Quién puede hacer qué en «{servicio}» (CRM-07.03.02.09)",
        description=(
            "«¿Quién puede borrar una cuenta?» se contesta casi siempre leyendo "
            "código, y se contesta mal: alguien mira la pantalla de roles, ve que "
            "«comercial» no tiene el permiso y dice que nadie — sin saber que hay "
            "un rol con `*:*` y tres personas dentro.\n\n"
            "Esto sale de las **rutas montadas** cruzadas con los **permisos de "
            "los roles**, con los comodines expandidos: el asterisco es donde se "
            "esconden los privilegios que nadie contó.\n\n"
            "Y enseña los dos huecos, que son opuestos: un permiso que una ruta "
            "exige y ningún rol tiene es funcionalidad muerta; uno concedido que "
            "ninguna ruta exige es un privilegio que alguien dio por si acaso."
        ),
    )
    def matriz_permisos(request: Request, db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.authz.matriz import matriz
        from crmcore.authz.politicas import cargar
        from crmcore.authz.rbac import ROLES_BASE

        # Los roles propios del tenant viven en `identity` y este servicio no lee
        # su esquema: se publican los de base, y se dice. Enseñar solo estos como
        # si fueran todos sería justo el error que esta matriz existe para evitar.
        return {
            "servicio": servicio,
            **matriz(request.app, dict(ROLES_BASE), politicas=cargar(db, principal.tenant_id)),
            "alcance_de_los_roles": (
                "Roles de base del producto. Los roles propios del tenant los "
                "gobierna «identity» y hay que pedírselos a él: ningún servicio "
                "lee el esquema de otro."
            ),
        }

    return router
