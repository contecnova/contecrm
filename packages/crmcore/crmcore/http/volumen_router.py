"""Volumen, particionado y archivo frío, servidos por servicio (CRM-08.01.01.04).

`crmcore.datos.particionado` resolvía lo entero —qué tablas crecen y por qué, por
qué se corta por tiempo y no por tenant, cuántas particiones hay que crear por
delante, qué fila se puede mover a frío y qué lo impide— y **no lo importaba
nadie**. Nueve funciones públicas, ninguna alcanzable. No daba ningún error: hacía
que el producto se comportara como si el volumen no se mirase nunca.

Lo que eso cuesta es la avería más previsible que tiene un CRM, y siempre llega en
el mismo orden: las consultas se ponen lentas, los índices dejan de caber en
memoria, el `VACUUM` tarda más que la ventana de mantenimiento, y una consulta que
iba bien dos años deja de ir en una semana sin que nadie haya tocado nada. El
aviso útil no es «esta tabla es grande»: es **a qué ritmo crece**, porque esos
nueve meses de margen son justo el tiempo que hace falta para arreglarlo con
calma.

Va **por servicio**, como la papelera y la restauración, y se monta en
`crear_servicio` para que ninguno pueda quedarse sin ello: las tablas que crecen
están repartidas por catorce esquemas y cada servicio sabe de las suyas. Un punto
central tendría que leer las tablas de los demás.

**Nada de esto escribe en la base.** Devuelve el plan —qué particionar, qué crear
antes de que haga falta, qué se puede mover a frío y qué lo impide—, y quien
ejecuta un `CREATE TABLE ... PARTITION OF` es la migración del servicio, con su
revisión y su ventana. Una ruta que particiona en caliente bloquea la tabla
durante la petición de un usuario, que es el incidente que esto existe para
evitar.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from crmcore import fechas
from crmcore.datos import archivado as arch
from crmcore.datos import particionado as part
from crmcore.datos.archivado import desarchivar as _desarchivar
from crmcore.errors import ErrorValidacion
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso


class ArchivarPorCriterioIn(BaseModel):
    clase: str = Field(..., min_length=1, description="Una clase de dato declarada del servicio")
    simular: bool = Field(
        True,
        description="Por defecto sólo dice qué movería: diez mil filas se miran antes",
    )


class AntiguedadIn(BaseModel):
    dias: int | None = Field(
        None,
        ge=1,
        le=36_500,
        description="Días a partir de los cuales se archiva esta clase. Vacío: el general",
    )


class ArchivarIn(BaseModel):
    filas: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Cada una con su `fecha` y, si las tiene, sus retenciones: "
            "`obligacion_legal`, `litigio`, `solicitud_pendiente`, `investigacion`"
        ),
    )
    destino: str = Field(
        ...,
        min_length=1,
        description="A dónde se mueve. Archivar sin decir a dónde es borrar con otro nombre",
    )


class VolumenIn(BaseModel):
    tablas: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Cada una con `nombre`, `filas`, `crecimiento_mensual_pct` y si ya está "
            "`particionada`. Lo que decide no es el tamaño: es el ritmo"
        ),
    )
    umbral_filas: int = Field(50_000_000, ge=1_000_000)


def crear_router_volumen(servicio: str) -> APIRouter:
    router = APIRouter(prefix=f"/{servicio}/volumen", tags=["volumen y archivo frío"])

    @router.get(
        "/plan-de-particion",
        dependencies=[Depends(exige_permiso("admin:read"))],
        summary="Cómo se corta una tabla de alto volumen, y por qué así",
        description=(
            "**Por tiempo, no por tenant.** Por tenant parece lo natural y es el "
            "error caro: con dos mil tenants salen dos mil particiones, el "
            "planificador tarda más en decidir que en ejecutar, y el tenant "
            "grande sigue teniendo su partición enorme igual. Por mes, las "
            "consultas normales —que casi siempre miran los últimos días— tocan "
            "una o dos.\n\n"
            "Se **rechaza particionar lo que no lo necesita**: cada partición "
            "tiene su coste de planificación, y trocear una tabla de cincuenta "
            "mil filas la hace más lenta, no más rápida.\n\n"
            "El aislamiento sigue siendo por tenant: lo que cambia es cómo se "
            "guarda, no quién ve qué."
        ),
    )
    def plan_de_particion(
        principal: AutenticadoDep,
        tabla: str = Query("", description="Una de las declaradas de alto volumen. Vacío: todas"),
        estrategia: str = Query("mes", description="mes · trimestre · anio"),
    ) -> Any:
        """Sin `tabla`, todas las que crecen. Y **siempre la misma forma**.

        `tabla` era obligatoria, y eso dejaba la ruta sin puerta posible: para
        pedirla hay que saber ya cuáles son las tablas de alto volumen, y esa
        lista solo existía dentro del núcleo —la única forma de sacarla era
        pedir una tabla mala y leerla del detalle del error—. Quien administra
        la base no quiere elegir una de cinco: quiere ver las cinco y por qué
        cada una se corta como se corta.

        La respuesta lleva `tablas` también cuando se pide una sola. Dos formas
        según los parámetros es lo que obliga a quien lo lee a ramificar, y la
        rama que menos se usa es la que se queda sin probar.
        """
        cuales = [tabla] if tabla else sorted(part.DE_ALTO_VOLUMEN)
        return {
            "tablas": [part.plan_de_particion(tabla=t, estrategia=estrategia) for t in cuales],
            "cuantas": len(cuales),
            "porque_solo_estas": (
                "Particionar lo que no crece la hace más lenta: cada partición "
                "tiene su coste de planificación. Las demás tablas se quedan en "
                "cientos de miles de filas para siempre."
            ),
        }

    @router.get(
        "/particiones-a-crear",
        dependencies=[Depends(exige_permiso("admin:read"))],
        summary="Qué particiones hay que crear antes de que hagan falta",
        description=(
            "**Por delante, siempre.** Una partición que se crea cuando llega la "
            "primera fila de ese mes es una partición que se crea a las 00:00 del "
            "día 1, dentro de la transacción de un usuario y con un bloqueo de "
            "tabla: un incidente con fecha conocida.\n\n"
            "Se marca como urgente lo que ya tendría que existir, que es la única "
            "parte de esta respuesta que obliga a hacer algo hoy."
        ),
    )
    def particiones_a_crear(
        db: DbDep,
        principal: AutenticadoDep,
        ultima_existente: date = Query(..., description="La última partición que ya hay"),
        meses_por_delante: int = Query(3, ge=1, le=24),
    ) -> Any:
        return part.particiones_a_crear(
            ultima_existente=ultima_existente,
            meses_por_delante=meses_por_delante,
            # El día del cliente: «ya tendría que existir» calculado en UTC
            # adelanta la urgencia un día para media Europa de madrugada.
            hoy=fechas.hoy(db),
        )

    @router.post(
        "/salud",
        dependencies=[Depends(exige_permiso("admin:read"))],
        summary="Qué tabla va camino de dar problemas, antes de darlos",
        description=(
            "El aviso útil no es «esta tabla es grande»: es **a qué ritmo "
            "crece**. Una tabla de cien millones de filas estable no molesta a "
            "nadie; una de diez que dobla cada trimestre es un incidente dentro "
            "de nueve meses — y esos nueve meses son justo el tiempo que hace "
            "falta para arreglarlo con calma.\n\n"
            "Sin datos de volumen **no se dice que todo esté bien**: se dice que "
            "no se puede anticipar nada, que es una respuesta distinta."
        ),
    )
    def salud_del_volumen(cuerpo: VolumenIn, principal: AutenticadoDep) -> Any:
        return part.salud_del_volumen(tablas=cuerpo.tablas, umbral_filas=cuerpo.umbral_filas)

    @router.post(
        "/archivar",
        dependencies=[Depends(exige_permiso("admin:write"))],
        summary="Qué se puede mover a frío, y qué lo impide",
        description=(
            "**Lo viejo se archiva, no se borra.** Un CRM al que alguien pregunta "
            "por una llamada de hace tres años y contesta que no existe deja de "
            "ser el registro de la empresa, y eso pasa el día que se confunde "
            "archivar con borrar. Lo archivado se sigue consultando, más despacio "
            "y diciendo dónde está.\n\n"
            "Y lo que está bajo **obligación legal, litigio, solicitud de acceso "
            "pendiente o investigación no se toca**: moverlo a frío es cumplir el "
            "plazo de retención por accidente y romper otra obligación a la vez — "
            "y la que se rompe suele ser la cara.\n\n"
            "Devuelve el plan con el detalle de **los que se quedan y por qué**. "
            "Un recuento sin los motivos obliga a adivinar cuáles son."
        ),
    )
    def archivar(cuerpo: ArchivarIn, db: DbDep, principal: AutenticadoDep) -> Any:
        return part.archivar(
            filas=cuerpo.filas,
            destino=cuerpo.destino,
            # La antigüedad se mide con el día del cliente: trece meses contados
            # en UTC mueven a frío un día antes de tiempo.
            hoy=fechas.hoy(db),
        )

    @router.post(
        "/puede-borrarse",
        dependencies=[Depends(exige_permiso("admin:write"))],
        summary="Si estas filas se pueden borrar de la tabla viva",
        description=(
            "Mover a frío sin borrar de la tabla viva no quita volumen: el "
            "borrado es el paso que de verdad hace sitio, y es el que no tiene "
            "vuelta atrás. Por eso se comprueba **antes y aquí**, no dentro del "
            "proceso de limpieza: ese corre de noche, y lo que borra por error "
            "se descubre semanas después, cuando alguien lo pide para un "
            "juicio.\n\n"
            "Corta en la **primera** fila retenida y dice cuál es la retención. "
            "Seguir con las demás «porque esa es solo una» es como se borra la "
            "mitad de un expediente que había que conservar entero."
        ),
    )
    def puede_borrarse(cuerpo: ArchivarIn, principal: AutenticadoDep) -> Any:
        for fila in cuerpo.filas:
            part.exigir_no_retenido(fila=fila)
        return {
            "filas": len(cuerpo.filas),
            "se_pueden_borrar": True,
            "porque": (
                "Ninguna está bajo obligación legal, litigio, solicitud de acceso "
                "pendiente ni investigación abierta."
            ),
        }

    @router.post(
        "/desarchivar/{registro_id}",
        dependencies=[Depends(exige_permiso("admin:write"))],
        summary="Devolver una fila archivada a su tabla viva",
        description=(
            "Hace falta porque el archivo **se consulta pero no se trabaja**: "
            "cuando una cuenta que se fue vuelve, lo que se quiere no es leer su "
            "historia, es poder seguir escribiendo en ella.\n\n"
            "Si la clase de dato ya no está declarada no se adivina a qué tabla "
            "devolverla: se dice, y el contenido sigue en el archivo. Devolverla "
            "al sitio equivocado sería peor que no devolverla."
        ),
    )
    def desarchivar(registro_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
        _exigir_archivo(db)
        return _desarchivar(db, principal.tenant_id, registro_id=registro_id, por=principal.id)

    # ── El archivo de verdad (CRM-07.03.01.02) ───────────────────────────
    #
    # `/archivar` de arriba PLANIFICA sobre filas tecleadas; no mueve nada y no
    # se puede consultar lo que no se movió. Estas cuatro archivan de verdad,
    # con el criterio de antigüedad por clase del tenant, y leen lo archivado.

    @router.get(
        "/archivo/clases",
        dependencies=[Depends(exige_permiso("admin:read"))],
        summary="Qué se puede archivar en este servicio, con qué criterio y cuánto es",
        description=(
            "Cada clase de dato del servicio con su antigüedad (la suya o la "
            "general), la fecha de corte que sale de ella y **cuántas filas "
            "movería hoy**. Sin el recuento, «se archiva lo de hace dos años» no "
            "dice si son diez filas o diez millones.\n\n"
            "Un servicio sin tabla de archivo contesta `hay_archivo: false` y "
            "ninguna clase, en vez de un error."
        ),
    )
    def clases_del_archivo(db: DbDep, principal: AutenticadoDep) -> Any:
        if not arch.hay_archivo(db):
            return {"servicio": servicio, "hay_archivo": False, "clases": []}
        return {
            "servicio": servicio,
            "hay_archivo": True,
            "clases": arch.clases_archivables(db, principal.tenant_id),
        }

    @router.put(
        "/archivo/clases/{clase}",
        dependencies=[Depends(exige_permiso("admin:write"))],
        summary="Fijar a partir de cuántos días se archiva una clase",
        description=(
            "Se guarda en el ajuste `archivado_antiguedad_por_clase` del tenant, "
            "con su versión y su auditoría como cualquier ajuste. Sin `dias`, la "
            "clase vuelve al criterio general (`archivado_dias_por_defecto`)."
        ),
    )
    def fijar_antiguedad(
        clase: str, cuerpo: AntiguedadIn, db: DbDep, principal: AutenticadoDep
    ) -> Any:
        from crmcore.datos.retencion import CLASES
        from crmcore.runtime import settings as rt

        if clase not in CLASES:
            raise ErrorValidacion(
                f"«{clase}» no es una clase de dato de este servicio",
                error_code="archivado.clase_desconocida",
                detalle={"declaradas": sorted(CLASES)},
            )
        actual = dict(rt.efectivo("archivado_antiguedad_por_clase", db) or {})
        if cuerpo.dias is None:
            actual.pop(clase, None)
        else:
            actual[clase] = int(cuerpo.dias)
        rt.fijar(
            db,
            "archivado_antiguedad_por_clase",
            actual,
            ambito="tenant",
            ambito_id=str(principal.tenant_id),
            por=principal.id,
        )
        return {"clase": clase, "dias": arch.dias_de_antiguedad(db, clase)}

    @router.post(
        "/archivo/archivar",
        dependencies=[Depends(exige_permiso("admin:write"))],
        summary="Archivar lo que el criterio dice que ya es histórico",
        description=(
            "Mueve a la tabla de archivo las filas de la clase anteriores a su "
            "corte, **conservando su identificador**, y las quita de la tabla "
            "viva. Simula por defecto: con `simular: false` mueve, como mucho "
            "`archivado_tope_por_pasada` filas por pasada.\n\n"
            "Un bloqueo legal no impide archivar —prohíbe destruir, y esto no "
            "destruye—; se dice cuántas filas lo tenían."
        ),
    )
    def archivar_de_verdad(
        cuerpo: ArchivarPorCriterioIn, db: DbDep, principal: AutenticadoDep
    ) -> Any:
        _exigir_archivo(db)
        return {
            "servicio": servicio,
            **arch.archivar_por_criterio(
                db,
                tenant_id=principal.tenant_id,
                clase=cuerpo.clase,
                simular=cuerpo.simular,
                por=principal.id,
            ),
        }

    @router.get(
        "/archivo",
        dependencies=[Depends(exige_permiso("admin:read"))],
        summary="Consultar lo archivado",
        description=(
            "Por clase, por fechas, por el identificador ORIGINAL de la fila "
            "(`registro_id`) o por el registro del que cuelga "
            "(`relacionado_con`: lo archivado de una cuenta, por ejemplo). "
            "Archivar no es purgar: lo archivado se lee entero."
        ),
    )
    def consultar_archivo(
        db: DbDep,
        principal: AutenticadoDep,
        clase: str = Query(""),
        registro_id: UUID | None = Query(None),
        relacionado_con: UUID | None = Query(None),
        desde: datetime | None = Query(None),
        hasta: datetime | None = Query(None),
        limite: int = Query(50, ge=1, le=500),
    ) -> Any:
        if not arch.hay_archivo(db):
            return {
                "servicio": servicio,
                "hay_archivo": False,
                "filas": [],
                "cuantas": 0,
                "hay_mas": False,
            }
        return {
            "servicio": servicio,
            "hay_archivo": True,
            **arch.consultar(
                db,
                principal.tenant_id,
                clase=clase,
                registro_id=registro_id,
                relacionado_con=relacionado_con,
                desde=desde,
                hasta=hasta,
                limite=limite,
            ),
        }

    @router.get(
        "/archivo/resumen",
        dependencies=[Depends(exige_permiso("admin:read"))],
        summary="Cuánto hay archivado y de cuándo",
    )
    def resumen_del_archivo(db: DbDep, principal: AutenticadoDep) -> Any:
        if not arch.hay_archivo(db):
            return {"servicio": servicio, "hay_archivo": False, "por_clase": [], "total": 0}
        return {"servicio": servicio, "hay_archivo": True, **arch.resumen(db, principal.tenant_id)}

    return router


def _exigir_archivo(db: Any) -> None:
    if not arch.hay_archivo(db):
        raise ErrorValidacion(
            "Este servicio no tiene archivo de histórico: no guarda nada que crezca "
            "lo bastante como para archivarlo.",
            error_code="archivado.sin_archivo",
        )
