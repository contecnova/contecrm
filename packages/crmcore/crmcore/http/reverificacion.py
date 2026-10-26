"""La reautenticación reforzada, aplicable desde cualquier servicio
(CRM-00.05.01.18).

La lista de operaciones sensibles existía, se publicaba en una ruta y **no la
aplicaba nadie fuera de `identity`**. Era exactamente el patrón que más caro sale
aquí: el sistema sabía decir qué operaciones exigen volver a verificarse, lo
enseñaba en una pantalla, y se podían hacer todas sin verificarse.

Y no se aplicaba por una razón concreta: `exige_reautenticacion` necesita la fila
de la sesión —cuándo se superó el último factor fuerte— y esa tabla vive en el
esquema de `identity`. Ningún servicio lee el esquema de otro, así que las tres
operaciones sensibles que ocurren fuera —exportar media base, borrar en bloque,
restaurar encima de lo actual— no tenían forma de comprobarlo.

Lo que lo resuelve es propagar **la marca y no la tabla**: el instante del último
factor fuerte viaja en el token y en las cabeceras firmadas, igual que los
permisos. Firmada, porque una cabecera suelta la pondría cualquiera que llegara a
la red interna y la reautenticación entera dejaría de valer.

**Que el nivel caduque antes que la sesión es todo el punto.** Una sesión dura
horas porque renovarla cada cuarto de hora haría el producto inusable; una
exportación de toda la base a las seis de la tarde no puede apoyarse en un factor
que se superó a las nueve de la mañana.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends

# A nivel de módulo y no dentro de la función: con `from __future__ import
# annotations` las anotaciones son cadenas, y FastAPI las resuelve mirando el
# espacio de nombres del MÓDULO donde está la función. Importados dentro del
# cuerpo, `AutenticadoDep` no existe ahí: FastAPI no reconocía la dependencia,
# daba por hecho que era un parámetro de query y la ruta contestaba «falta el
# campo principal» — un 422 en una exportación que estaba perfectamente bien.
from crmcore.http.deps import AutenticadoDep, DbDep

# Qué exige volver a verificarse. Es una tabla de datos y no `if` repartidos por
# el código: lo que hace que una operación nueva quede cubierta es añadirla aquí,
# y lo que hace que se vea lo que **no** está cubierto es poder leerla entera.
#
# Vive en `crmcore` y no en `identity` porque la mitad de estas operaciones
# ocurren en otros servicios. Tenerla allí era lo que obligaba a que la
# comprobación viviera allí también, y por eso no vivía en ninguna parte.
OPERACIONES_SENSIBLES: dict[str, str] = {
    "exportacion_masiva": "Exportar muchos registros de una vez",
    "cambio_permisos": "Cambiar roles, permisos o políticas de acceso",
    "borrado_masivo": "Borrar registros en bloque",
    "suplantacion": "Entrar como otro usuario",
    "clave_api": "Crear o regenerar una credencial de máquina",
    "cambio_mfa": "Desactivar o reconfigurar el segundo factor",
    "restauracion": "Restaurar datos sobre los actuales",
    "baja_tenant": "Dar de baja el tenant",
    # Recuperar un número de tarjeta o una cuenta bancaria de la bóveda. Es la
    # única operación del CRM que devuelve un dato que el CRM no guarda.
    "destokenizacion": "Recuperar un dato que se sacó del CRM (tarjeta, cuenta, NIF)",
}


# Cuánto vale un factor fuerte, si nadie lo ha configurado. Quince minutos: lo
# bastante para encadenar dos operaciones sensibles sin volver a teclear, y lo
# bastante poco para que una sesión abierta toda la tarde no sirva de salvoconducto.
def _reverificacion_validez_min() -> int:
    """Tope del núcleo, antes `_reverificacion_validez_min() = 15`.

    Era una constante de módulo. Sale del `.env`, no de los ajustes en
    caliente: es un tope operativo del despliegue y «por cliente» no
    significaría nada.
    """
    from crmcore.config import get_settings

    return get_settings().reverificacion_validez_min


def minutos_de_validez(db: Any = None) -> int:
    from crmcore.runtime import settings as rt

    try:
        valor = rt.efectivo("stepup_validez_minutos", db)
    except Exception:  # pragma: no cover — sin ajustes, el valor de serie
        valor = None
    try:
        return max(1, int(valor))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _reverificacion_validez_min()


def comprobar(principal: Any, operacion: str, *, db: Any = None) -> None:
    """Corta la operación si el segundo factor es viejo o no lo hubo.

    Lo que se mira es **cuándo** fue el último factor fuerte, no si la persona
    tiene MFA configurada: son dos preguntas distintas y confundirlas deja pasar
    exactamente el caso que esto existe para parar.
    """
    from crmcore.errors import ErrorValidacion, NoAutenticado

    if operacion not in OPERACIONES_SENSIBLES:
        raise ErrorValidacion(
            f"«{operacion}» no está declarada como operación sensible.",
            error_code="stepup.operacion_desconocida",
            detalle={"declaradas": sorted(OPERACIONES_SENSIBLES)},
        )

    # Una credencial de máquina no teclea un código. Se exceptúa **por tipo y a
    # propósito**: tratarla como a una persona dejaría los procesos automáticos
    # —la exportación nocturna, la purga— parados para siempre y sin nadie a
    # quien pedirle el segundo factor. Lo que la protege es otra cosa: la
    # credencial, su ámbito y el registro de lo que hace.
    if str(getattr(principal, "tipo", "usuario")) in ("servicio", "automatizacion"):
        return

    validez = minutos_de_validez(db)
    crudo = str(getattr(principal, "factor_fuerte_at", "") or "")
    momento = _leer(crudo)
    if momento is not None and (datetime.now(timezone.utc) - momento) <= timedelta(minutes=validez):
        return

    raise NoAutenticado(
        "Esta operación exige volver a verificar tu identidad.",
        error_code="stepup.requerido",
        detalle={
            "operacion": operacion,
            "descripcion": OPERACIONES_SENSIBLES[operacion],
            "validez_minutos": validez,
            # «Vuelve a verificarte» y «configúrate un segundo factor» son dos
            # cosas muy distintas para quien está delante de la pantalla.
            "tiene_factor": momento is not None,
        },
    )


def _leer(crudo: str) -> datetime | None:
    if not crudo:
        return None
    try:
        momento = datetime.fromisoformat(crudo)
    except ValueError:
        # Una marca ilegible **no vale como verificación**. Dejarla pasar
        # convertiría un error de formato en una puerta abierta.
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def exige_reverificacion(operacion: str) -> Callable[..., None]:
    """Dependencia de FastAPI: `dependencies=[Depends(exige_reverificacion("…"))]`.

    Se declara en la ruta y no dentro del cuerpo por lo mismo que el permiso:
    así aparece en el contrato publicado, el front sabe **antes** de que el
    usuario rellene el formulario que esa acción va a pedir reverificación, y no
    hay forma de escribir la ruta olvidándose de llamarla.
    """

    def _dependencia(principal: AutenticadoDep, db: DbDep) -> None:
        comprobar(principal, operacion, db=db)

    return _dependencia


def dependencia(operacion: str) -> Any:
    """Azúcar para `dependencies=[...]`."""
    return Depends(exige_reverificacion(operacion))
