"""Llenar el almacén analítico, que llevaba vacío desde siempre
(CRM-05.01.03.01).

**Por qué existe.** El diseño decía que las filas «las entrega el servicio
dueño»: cada servicio llamaría a `POST /almacen/cargas` con lo suyo. Ningún
servicio lo hizo nunca. El resultado no fallaba —no hay error que dé una tabla
que nadie llena—: simplemente el almacén estaba vacío, «Frescura del almacén»
decía «nunca cargada» para todas y siempre, y cualquier informe que leyera de
ahí devolvía cero filas. Trece cargadores que nadie escribió es peor que uno que
existe.

**Por qué tira de la API y no del esquema.** Leer las tablas de otro servicio
por debajo rompería el aislamiento, y además saltaría el enmascarado por rol: el
almacén acabaría con los campos que la API oculta. Pasando por la API pública
con una credencial de solo lectura, el almacén ve exactamente lo que ve un
lector, ni un campo más.

**Y la ruta se declara, no se adivina.** Deducirla del objeto parecía posible
—la superficie etiqueta cada operación— hasta que se mira: `casos` etiqueta
tanto la bandeja de casos como las COLAS de casos, y cargar la tabla equivocada
es peor que no cargarla.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorDependencia
from crmcore.logging import get_logger
from sqlalchemy import select

from services.analytics import almacen as alm

logger = get_logger(__name__)


# Cuántas filas se piden por vuelta. El tope de la API es 200.
def _carga_filas_por_vuelta() -> int:
    """Tope, antes `_carga_filas_por_vuelta() = 200`.

    Era una constante de módulo. Sale del `.env`: es un tope del despliegue y
    «por cliente» no significaría nada.
    """
    from crmcore.config import get_settings

    return get_settings().carga_filas_por_vuelta


# Tope de vueltas por tabla y carga. Una tabla con un millón de filas no se trae
# entera en el camino de un botón: se trae lo más reciente y el resto en la
# siguiente. Sin tope, alguien pulsa «cargar» y la petición no vuelve nunca.
def _carga_vueltas_maximas() -> int:
    """Tope, antes `_carga_vueltas_maximas() = 50`.

    Era una constante de módulo. Sale del `.env`: es un tope del despliegue y
    «por cliente» no significaría nada.
    """
    from crmcore.config import get_settings

    return get_settings().carga_vueltas_maximas


def cargar_tabla(
    uow: UnidadDeTrabajo, clave: str, *, clave_api: str, base_url: str
) -> dict[str, Any]:
    """Trae las filas de una tabla declarada y las aplica al almacén."""
    from crmcore.red import cliente_seguro

    ficha = uow.db.execute(
        select(alm.TablaAnalitica).where(
            alm.TablaAnalitica.tenant_id == uow.tenant_id, alm.TablaAnalitica.clave == clave
        )
    ).scalar_one_or_none()
    if ficha is None:
        raise ErrorDependencia(
            f"La tabla «{clave}» no está declarada", error_code="almacen.tabla_no_declarada"
        )
    if not ficha.ruta:
        return {
            "tabla": clave,
            "cargadas": 0,
            "motivo": "la tabla no declara de dónde traer las filas",
        }

    columnas = {str(c.get("nombre")) for c in (ficha.columnas or []) if isinstance(c, dict)}
    raiz = base_url.rstrip("/")
    # `ruta` viene con el prefijo completo (`/api/v1/accounts`) y `base_url` ya
    # lo lleva, así que se recorta: concatenarlos a pelo daba
    # `/api/v1/api/v1/accounts` y un 404 que parecía un fallo de red.
    camino = ficha.ruta[len("/api/v1") :] if ficha.ruta.startswith("/api/v1") else ficha.ruta

    recogidas: list[dict[str, Any]] = []
    cursor = ""
    with cliente_seguro(timeout=60.0) as cli:
        for _ in range(_carga_vueltas_maximas()):
            sep = "&" if "?" in camino else "?"
            url = f"{raiz}{camino}{sep}limite={_carga_filas_por_vuelta()}" + (
                f"&cursor={cursor}" if cursor else ""
            )
            r = cli.get(url, headers={"Authorization": f"Bearer {clave_api}"})
            if r.status_code != 200:
                raise ErrorDependencia(
                    f"El listado de «{clave}» ha contestado {r.status_code}",
                    error_code="almacen.origen_rechaza",
                    detalle={"ruta": ficha.ruta, "codigo_http": r.status_code},
                )
            cuerpo = r.json()
            trozo = cuerpo.get("items") if isinstance(cuerpo, dict) else cuerpo
            if not isinstance(trozo, list):
                break
            for fila in trozo:
                if not isinstance(fila, dict):
                    continue
                # Solo las columnas declaradas, y `clave_origen` para que repetir
                # una carga no duplique nada. Sin ella, cada pase doblaría los
                # recuentos y nadie sabría por qué.
                plana = {k: v for k, v in fila.items() if k in columnas}
                plana["clave_origen"] = str(fila.get("id") or "")
                if plana["clave_origen"]:
                    recogidas.append(plana)
            cursor = str((cuerpo or {}).get("siguiente") or "") if isinstance(cuerpo, dict) else ""
            if not cursor:
                break

    if not recogidas:
        return {"tabla": clave, "cargadas": 0, "motivo": "el origen no ha devuelto filas"}
    # `completa` cuando la tabla se declara así: es lo que permite que una fila
    # borrada en el operacional desaparezca del almacén en vez de quedarse.
    resultado = alm.cargar(
        uow, tabla=clave, filas=recogidas, completa=ficha.estrategia == "completa"
    )
    logger.info("almacen.cargada", tabla=clave, filas=len(recogidas))
    return {"tabla": clave, **resultado}


def cargar_todas(uow: UnidadDeTrabajo, *, clave_api: str, base_url: str) -> dict[str, Any]:
    """Todas las tablas activas del tenant, una a una.

    Un fallo en una NO para las demás: si la tabla de casos no responde, la de
    cuentas se carga igual y el informe de cuentas deja de estar en blanco. Lo
    que no se hace es esconder el fallo — cada tabla lleva su resultado.
    """
    filas = (
        uow.db.execute(
            select(alm.TablaAnalitica).where(
                alm.TablaAnalitica.tenant_id == uow.tenant_id,
                alm.TablaAnalitica.activa.is_(True),
            )
        )
        .scalars()
        .all()
    )
    salida = []
    for tabla in filas:
        try:
            salida.append(cargar_tabla(uow, tabla.clave, clave_api=clave_api, base_url=base_url))
        except Exception as exc:  # noqa: BLE001 — una tabla rota no puede parar el resto
            logger.warning("almacen.carga_fallida", tabla=tabla.clave, error=str(exc)[:200])
            salida.append({"tabla": tabla.clave, "cargadas": 0, "error": str(exc)[:300]})
    return {"tablas": salida}


def clave_y_base(tenant_id: UUID) -> tuple[str, str]:
    """La credencial de lectura y la dirección del CRM, para cargar.

    Nombre PROPIO y no el de la fuente. Emitir una clave ROTA la anterior que se
    llame igual, así que compartir nombre hacía que cada carga del almacén matara
    la credencial con la que quedó registrada la fuente en contecintelligence —y
    al revés—. Dos usos distintos, dos credenciales.
    """
    from crmcore.integracion.clave_lectura import clave_de_lectura, url_del_crm

    return clave_de_lectura(tenant_id, nombre="almacen-analitico"), url_del_crm()
