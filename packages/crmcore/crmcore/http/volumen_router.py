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

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from crmcore import fechas
from crmcore.datos import particionado as part
from crmcore.datos.archivado import desarchivar as _desarchivar
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso


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
        tabla: str = Query(..., description="Una de las declaradas de alto volumen"),
        estrategia: str = Query("mes", description="mes · trimestre · anio"),
    ) -> Any:
        return part.plan_de_particion(tabla=tabla, estrategia=estrategia)

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
    def desarchivar(registro_id: Any, db: DbDep, principal: AutenticadoDep) -> Any:
        return _desarchivar(db, principal.tenant_id, registro_id=registro_id, por=principal.id)

    return router
