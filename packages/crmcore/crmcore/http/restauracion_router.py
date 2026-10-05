"""Restauración selectiva de registros (CRM-00.06.02.03).

La lógica vive en `crmcore.datos.restaurar` desde hace tiempo, y hasta ahora no
la podía llamar nadie: no había una sola ruta que llegara hasta ella. Una
recuperación que existe en el código y no se puede pedir es una recuperación que
no existe el día que hace falta, que es el único día que importa.

Se monta sola en `crear_servicio`, como la página de estado. Si dependiera de que
cada servicio se acuerde, faltaría precisamente en el que guarde lo que alguien
acabe borrando.

Cada servicio restaura **lo suyo**. Los objetos restaurables se leen del propio
mapeo del servicio, no de una lista escrita a mano: una lista se queda corta al
primer modelo nuevo, y ese modelo sería justo el que no se puede recuperar.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso


class Previsualizar(BaseModel):
    exportacion: str = Field(..., description="URI o clave de la exportación verificada")
    objeto: str = Field(..., description="Tabla a restaurar, tal como sale en /objetos")
    ids: list[str] = Field(..., min_length=1, max_length=1000)
    desde: datetime | None = Field(
        None,
        description=(
            "Punto de restauración. Lo modificado después se marca aparte: es "
            "trabajo que alguien hizo a sabiendas."
        ),
    )


class Restaurar(Previsualizar):
    forzar_modificados: bool = Field(
        False,
        description=(
            "Pisar también lo modificado después del punto de restauración. Es "
            "una decisión, y por eso hay que decirla: por defecto no se toca."
        ),
    )


def objetos_restaurables() -> dict[str, type]:
    """Los modelos con `tenant_id` de este servicio, por nombre de tabla.

    Salen del mapeo y no de una lista: en un proceso solo están cargados los
    modelos del servicio que corre, así que esto es exactamente lo suyo y no
    puede quedarse viejo.

    Los que no llevan `tenant_id` quedan fuera a propósito: son catálogos de
    instalación, y restaurarlos «para un tenant» no significa nada.
    """
    from crmcore.db.base import Base

    salida: dict[str, type] = {}
    for mapper in Base.registry.mappers:
        modelo = mapper.class_
        tabla = getattr(modelo, "__table__", None)
        if tabla is None or "tenant_id" not in tabla.columns:
            continue
        salida[tabla.name] = modelo
    return salida


class PlanIn(BaseModel):
    momento: datetime = Field(..., description="A qué instante se quiere volver")
    alcance: str = Field("tenant", description="tenant · objeto")
    copia_mas_antigua: datetime = Field(
        ..., description="La copia más antigua que queda, de la política de retención"
    )


class EfectosIn(BaseModel):
    salidas: list[dict[str, Any]] = Field(default_factory=list)
    desde: datetime
    hasta: datetime


class PruebaIn(BaseModel):
    inicio: datetime
    fin: datetime
    filas_comprobadas: int = Field(0, ge=0)
    diferencias: list[str] = Field(default_factory=list)
    rto_comprometido_min: int = Field(..., ge=1)


class EstadoPruebasIn(BaseModel):
    pruebas: list[dict[str, Any]] = Field(default_factory=list)


def crear_router_restauracion(servicio: str) -> APIRouter:
    # Cuelga del nombre del servicio, como la retención y los trabajos: todos
    # publican la misma ruta, y sin el segmento del servicio el gateway no
    # sabría a cuál de los doce mandar la petición.
    router = APIRouter(prefix=f"/{servicio}/restauracion", tags=["restauración selectiva"])

    @router.get(
        "/objetos",
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary=f"Qué objetos de «{servicio}» se pueden restaurar",
        description=(
            "Se leen del mapeo del servicio, no de una lista: una lista se queda "
            "corta al primer modelo nuevo, y ese sería justo el que no se puede "
            "recuperar el día que alguien lo borre."
        ),
    )
    def objetos(principal: AutenticadoDep) -> Any:
        return {"servicio": servicio, "objetos": sorted(objetos_restaurables())}

    @router.post(
        "/previsualizar",
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary="Qué cambiaría, antes de cambiar nada",
        description=(
            "Quien restaura casi nunca sabe exactamente qué va a sobrescribir, y "
            "descubrirlo después es cambiar un problema por otro. Lo modificado "
            "después del punto de restauración sale marcado aparte."
        ),
    )
    def previsualizar(cuerpo: Previsualizar, db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.datos import restaurar as rest

        modelo = _modelo(cuerpo.objeto)
        origen = rest.leer_exportacion(cuerpo.exportacion, cuerpo.objeto)
        diferencias = rest.previsualizar(
            db, modelo, origen=origen, ids=cuerpo.ids, desde=cuerpo.desde
        )
        encontrados = {d.id for d in diferencias}
        return {
            "objeto": cuerpo.objeto,
            "diferencias": [
                {
                    "id": d.id,
                    "estado": d.estado,
                    "campos_distintos": d.campos_distintos,
                    "modificado_despues": d.modificado_despues,
                }
                for d in diferencias
            ],
            # Los que no están en la exportación se dicen: sin esto, alguien pide
            # trescientos identificadores, ve doscientos y cree que los otros
            # cien estaban bien.
            "no_estan_en_la_exportacion": [i for i in cuerpo.ids if i not in encontrados],
            "modificados_despues": [d.id for d in diferencias if d.modificado_despues],
        }

    # ── Volver atrás un tenant, y lo que eso no deshace ───────────────────
    #
    # Seis decisiones del módulo de recuperación estaban escritas, probadas y
    # **sin que las alcanzara ninguna ruta**. Es el peor sitio donde dejarlas:
    # son las que se consultan el día del incidente, y ese día nadie se pone a
    # escribir código.

    @router.post(
        "/plan",
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary="Qué pasa si volvemos a ese momento",
        description=(
            "**Se restaura sobre una copia, no encima.** Se levanta el estado de "
            "ese momento en paralelo, alguien lo mira y entonces se decide qué se "
            "trae: restaurar directamente sobre lo vivo convierte un error en "
            "dos.\n\n"
            "Y el plan dice **qué no se puede deshacer**. Restaurar las tablas a "
            "las 10:00 no deshace los eventos que salieron entre las 10:00 y "
            "ahora: el webhook ya llegó al ERP del cliente, el correo ya se mandó "
            "y la audiencia ya se subió a la plataforma de anuncios. Una "
            "restauración que no lo dice deja al CRM diciendo una cosa y al mundo "
            "otra."
        ),
    )
    def plan_de_restauracion(cuerpo: PlanIn, principal: AutenticadoDep) -> Any:
        from crmcore.datos import recuperacion as rec

        return rec.plan_de_restauracion(
            tenant_id=principal.tenant_id,
            momento=cuerpo.momento,
            alcance=cuerpo.alcance,
            copia_mas_antigua=cuerpo.copia_mas_antigua,
        )

    @router.post(
        "/efectos-irreversibles",
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary="Qué salió fuera en ese tramo y no se puede deshacer",
        description=(
            "Eventos publicados, correos enviados, documentos firmados. **Nada de "
            "eso se puede deshacer** y, si no se dice, nadie lo tiene en cuenta: "
            "se restaura, se da por resuelto, y el ERP del cliente sigue con el "
            "pedido que aquí ya no existe."
        ),
    )
    def efectos_irreversibles(cuerpo: EfectosIn, principal: AutenticadoDep) -> Any:
        from crmcore.datos import recuperacion as rec

        return rec.efectos_irreversibles(
            salidas=cuerpo.salidas, desde=cuerpo.desde, hasta=cuerpo.hasta
        )

    @router.post(
        "/pruebas",
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary="Anotar una prueba de restauración",
        description=(
            "Una copia que no se ha restaurado nunca **no es una copia**: es un "
            "fichero del que se supone que serviría. Lo que convierte lo segundo "
            "en lo primero es haberlo probado, con su fecha y su resultado."
        ),
    )
    def registrar_prueba(cuerpo: PruebaIn, principal: AutenticadoDep) -> Any:
        from crmcore.datos import recuperacion as rec

        return rec.registrar_prueba(
            tenant_id=principal.tenant_id,
            inicio=cuerpo.inicio,
            fin=cuerpo.fin,
            filas_comprobadas=cuerpo.filas_comprobadas,
            diferencias=cuerpo.diferencias,
            rto_comprometido_min=cuerpo.rto_comprometido_min,
        )

    @router.post(
        "/pruebas/estado",
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary="Si las pruebas de restauración están al día",
    )
    def estado_de_las_pruebas(cuerpo: EstadoPruebasIn, principal: AutenticadoDep) -> Any:
        from crmcore.datos import recuperacion as rec

        return rec.estado_de_las_pruebas(pruebas=cuerpo.pruebas)

    @router.get(
        "/rpo",
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary="Cuánto se perdería ahora mismo, frente a lo comprometido",
        description=(
            "El RPO **real**, no el del contrato. La diferencia entre los dos es "
            "lo único que se puede enseñar en una auditoría, y el día del "
            "incidente es lo primero que se pregunta."
        ),
    )
    def rpo_real(
        principal: AutenticadoDep,
        ultima_copia: datetime | None = None,
        rpo_comprometido_min: int = 60,
    ) -> Any:
        from crmcore.datos import recuperacion as rec

        return rec.rpo_real(ultima_copia=ultima_copia, rpo_comprometido_min=rpo_comprometido_min)

    @router.get(
        "/ventana",
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary="Si se puede volver tan atrás como se pide",
        description=(
            "Pedir volver a hace noventa días cuando la retención son treinta no "
            "es un error de quien lo pide: es una expectativa que alguien le dio. "
            "Decirlo antes de intentarlo evita la conversación en el peor momento."
        ),
    )
    def ventana_de_retencion(
        principal: AutenticadoDep,
        dias_retencion: int = 30,
        dias_pedidos: int = 7,
    ) -> Any:
        from crmcore.datos import recuperacion as rec

        return rec.ventana_de_retencion(dias_retencion=dias_retencion, dias_pedidos=dias_pedidos)

    @router.post(
        "",
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary="Devolver registros concretos a como estaban",
        description=(
            "Sin restaurar nada más. Es el hueco entre la papelera —que cubre el "
            "borrado de un usuario— y la restauración de clúster —que cubre el "
            "desastre—, y es donde caen casi todos los casos reales: una "
            "importación que machacó trescientas cuentas, una automatización que "
            "vació un campo.\n\n"
            "Lo modificado después del punto de restauración **no se toca** salvo "
            "que se diga explícitamente. Y todo queda en la auditoría."
        ),
    )
    def restaurar_registros(cuerpo: Restaurar, uow: UowDep, principal: AutenticadoDep) -> Any:
        from crmcore.datos import restaurar as rest

        modelo = _modelo(cuerpo.objeto)
        origen = rest.leer_exportacion(cuerpo.exportacion, cuerpo.objeto)
        return rest.restaurar(
            uow.db,
            modelo,
            origen=origen,
            ids=cuerpo.ids,
            tenant_id=uow.tenant_id,
            objeto=cuerpo.objeto,
            por=principal.id,
            forzar_modificados=cuerpo.forzar_modificados,
            desde=cuerpo.desde,
        )

    return router


def _modelo(objeto: str) -> type:
    modelos = objetos_restaurables()
    modelo = modelos.get(objeto)
    if modelo is None:
        raise NoEncontrado(
            f"Este servicio no guarda «{objeto}»: mira /restauracion/objetos. "
            "Cada servicio restaura lo suyo, porque ninguno escribe en el "
            "esquema de otro.",
            error_code="restaurar.objeto_desconocido",
        )
    return modelo
