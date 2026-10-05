"""Varias operaciones en una llamada, servidas por servicio (CRM-00.02.01.13).

`crmcore.http.compuesto` resolvía lo difícil —el tope, las referencias entre
operaciones, la validación antes de ejecutar nada— y **no lo importaba nadie**.
Un cliente que crea una cuenta, le añade un contacto y le abre una oportunidad
seguía haciendo tres llamadas y tres viajes de red; desde un móvil con mala
cobertura, eso son tres ocasiones de quedarse a medias — y quedarse a medias aquí
significa una cuenta sin contacto que alguien tendrá que limpiar a mano.

**Todo o nada, en una transacción.** Es la diferencia entre esto y mandar tres
peticiones seguidas, y es lo que obliga a que las sub-peticiones compartan la
sesión: si cada una abriera la suya, «todo o nada» serían tres escrituras
independientes con otro nombre.

**Y pasan por la puerta de siempre.** Cada operación se despacha contra la propia
aplicación, así que atraviesa la autenticación, los permisos, la validación del
cuerpo y la auditoría exactamente igual que si hubiera llegado sola. Ejecutarlas
llamando a las funciones por dentro habría sido más rápido y habría creado un
camino sin controles, que es como se cuela un dato que la pantalla no habría
dejado poner.

Va **por servicio**, como la papelera: una composición que cruzara servicios no
podría ser una transacción, y prometerlo sería mentir.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from crmcore.logging import get_logger

logger = get_logger(__name__)


class Operacion(BaseModel):
    metodo: str = Field(..., examples=["POST"])
    ruta: str = Field(..., examples=["/api/v1/cuentas"])
    cuerpo: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Puede referirse a lo que devolvió una operación anterior con "
            "`$1.id`. Solo hacia atrás: una referencia a una posterior no se "
            "puede resolver, y a sí misma es un ciclo"
        ),
    )


class PeticionCompuesta(BaseModel):
    operaciones: list[Operacion] = Field(default_factory=list)


def crear_router_compuesto(servicio: str) -> APIRouter:
    router = APIRouter(prefix=f"/{servicio}/compuesto", tags=["peticiones compuestas"])

    @router.post(
        "",
        response_model=dict,
        summary=f"Varias operaciones de «{servicio}» en una llamada",
        description=(
            "**Todo o nada, en una transacción.** Es la diferencia entre esto y "
            "mandar tres peticiones seguidas: desde un móvil con mala cobertura, "
            "tres llamadas son tres ocasiones de quedarse a medias, y quedarse a "
            "medias aquí deja una cuenta sin contacto que alguien tendrá que "
            "limpiar a mano.\n\n"
            "**Se valida entera antes de ejecutar nada.** Una referencia rota "
            "descubierta a mitad deja la transacción abortada y al cliente con "
            "un error que no dice cuál de sus operaciones estaba mal.\n\n"
            "**Cada operación pasa por la puerta de siempre**: autenticación, "
            "permisos, validación y auditoría, igual que si hubiera llegado "
            "sola. Ejecutarlas por dentro habría creado un camino sin "
            "controles.\n\n"
            "Las referencias van **solo hacia atrás** (`$1.id`): a una posterior "
            "no se pueden resolver, y a sí misma es un ciclo. Y un campo que no "
            "está en el resultado se deja tal cual en vez de poner vacío, para "
            "que falle la validación del recurso — que es donde tiene que "
            "fallar."
        ),
    )
    async def compuesto(datos: PeticionCompuesta, request: Request) -> Any:
        import httpx

        from crmcore.db.session import nueva_sesion
        from crmcore.errors import ErrorValidacion
        from crmcore.http import compuesto as reglas
        from crmcore.http.deps import compartir_sesion, soltar_sesion

        operaciones = [op.model_dump() for op in datos.operaciones]
        # Antes de abrir nada: una petición mal formada no merece una
        # transacción abierta, y el error tiene que decir qué operación falla.
        reglas.validar(operaciones)

        principal = getattr(request.state, "principal_precalculado", None)
        tenant_id = getattr(principal, "tenant_id", None) if principal else None
        if tenant_id is None:
            from crmcore.tenancy.context import contexto_actual

            tenant_id = contexto_actual().tenant_id
        if tenant_id is None:
            raise ErrorValidacion(
                "Una petición compuesta necesita saber de qué tenant es.",
                error_code="compuesto.sin_tenant",
            )

        # Las cabeceras de identidad se reenvían tal cual: la sub-petición tiene
        # que ser **la misma persona**. Pasarla como sistema sería darle a una
        # composición permisos que quien la manda no tiene.
        cabeceras = {
            k: v
            for k, v in request.headers.items()
            if k.lower().startswith("x-crm-") or k.lower() == "authorization"
        }

        db = nueva_sesion(tenant_id)
        testigo = compartir_sesion(db)
        resultados: list[dict[str, Any]] = []
        try:
            transporte = httpx.ASGITransport(app=request.app)
            async with httpx.AsyncClient(
                transport=transporte, base_url="http://compuesto"
            ) as cliente:
                for indice, operacion in enumerate(operaciones, start=1):
                    cuerpo = reglas.resolver(operacion.get("cuerpo") or {}, resultados)
                    respuesta = await cliente.request(
                        str(operacion["metodo"]).upper(),
                        str(operacion["ruta"]),
                        json=cuerpo,
                        headers=cabeceras,
                    )
                    if respuesta.status_code >= 400:
                        # Se deshace todo. Devolver los parciales sería lo
                        # cómodo y rompería la única promesa que hace esto.
                        raise ErrorValidacion(
                            f"La operación {indice} ha fallado y se ha deshecho todo.",
                            error_code="compuesto.operacion_fallida",
                            detalle={
                                "operacion": indice,
                                "metodo": operacion["metodo"],
                                "ruta": operacion["ruta"],
                                "estado": respuesta.status_code,
                                "respuesta": _json(respuesta),
                            },
                        )
                    resultados.append(_json(respuesta) or {})
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            soltar_sesion(testigo)
            db.close()

        return {
            "operaciones": len(resultados),
            "resultados": resultados,
            "porque": (
                "Todo o nada: si una hubiera fallado, no habría quedado escrita "
                "ninguna. Es lo que distingue esto de mandar las peticiones una "
                "detrás de otra."
            ),
        }

    return router


def _json(respuesta: Any) -> dict[str, Any] | None:
    try:
        salida = respuesta.json()
    except Exception:  # noqa: BLE001 — una respuesta sin cuerpo no es un fallo
        return None
    return salida if isinstance(salida, dict) else {"datos": salida}
