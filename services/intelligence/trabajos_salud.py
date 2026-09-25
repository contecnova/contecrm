"""Medir la salud de todas las cuentas, en diferido (CRM-05.02.01.04).

Va por trabajo y **con cursor de verdad**, al revés que el alta de fuente: aquí
sí hay elementos que recorrer —una cuenta detrás de otra—, cada una son cuatro
llamadas a la API, y una cartera de mil cuentas son cuatro mil. Si el worker se
cae en la 600, otro sigue en la 600 en vez de empezar de cero.

La lista de cuentas se resuelve UNA VEZ, al empezar, y se guarda en la entrada
del trabajo. Pedirla en cada tanda haría que una cuenta creada a mitad
descolocara el cursor y alguna se midiera dos veces o ninguna.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.datos.trabajos import Tanda, Trabajo, registrar_ejecutor
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.logging import get_logger
from sqlalchemy.orm import Session

logger = get_logger(__name__)

TIPO = "ia.medir_salud"


def _cuentas_del_tenant(cli: Any, base: str, clave: str) -> list[str]:
    """Los identificadores de todas las cuentas, paginando de verdad."""
    cabeceras = {"Authorization": f"Bearer {clave}"}
    ids: list[str] = []
    cursor = ""
    for _ in range(200):
        url = f"{base}/accounts?limite=200" + (f"&cursor={cursor}" if cursor else "")
        r = cli.get(url, headers=cabeceras)
        if r.status_code != 200:
            break
        cuerpo = r.json()
        for fila in cuerpo.get("items") or []:
            if fila.get("id"):
                ids.append(str(fila["id"]))
        cursor = str(cuerpo.get("siguiente") or "")
        if not cursor:
            break
    return ids


def _ejecutar(db: Session, trabajo: Trabajo, tope: int) -> Tanda:
    from crmcore.config import get_settings
    from crmcore.integracion.clave_lectura import clave_de_lectura, url_del_crm
    from crmcore.red import cliente_seguro

    from services.intelligence import medidor_salud as med
    from services.intelligence import salud as sal

    s = get_settings()
    base = url_del_crm()
    clave = clave_de_lectura(trabajo.tenant_id, nombre="salud-de-cuenta")

    with cliente_seguro(timeout=60.0) as cli:
        cuentas: list[str] = list(trabajo.entrada.get("cuentas") or [])
        if not cuentas:
            cuentas = _cuentas_del_tenant(cli, base, clave)
            # Se guarda en la entrada para que las tandas siguientes recorran la
            # MISMA lista: pedirla otra vez con una cuenta nueva por medio
            # descolocaría el cursor.
            trabajo.entrada = {**trabajo.entrada, "cuentas": cuentas}
            if not cuentas:
                return Tanda(
                    avanzados=0, total=0, resultado={"motivo": "el tenant no tiene cuentas"}
                )

        trozo = cuentas[trabajo.cursor : trabajo.cursor + tope]
        if not trozo:
            return Tanda(avanzados=0, total=len(cuentas))

        uow = UnidadDeTrabajo(db=db, tenant_id=trabajo.tenant_id)
        pesos, umbrales = med.pesos_de(s), med.umbrales_de(s)
        medidas = 0
        errores: list[dict[str, Any]] = []
        for bruto in trozo:
            cuenta_id = UUID(bruto)
            datos = med.leer_del_crm(cli, base, clave, cuenta_id)
            senales = med.senales_de(datos, s)
            if not senales:
                # Ninguna señal: no se mide, y no es un fallo. Una cuenta recién
                # creada no tiene actividad, ni casos, ni contactos — y ponerle un
                # cero la sacaría en la lista de riesgo el primer día.
                continue
            try:
                sal.medir(
                    uow,
                    cuenta_id=cuenta_id,
                    senales=senales,
                    pesos=pesos,
                    umbrales=umbrales,
                )
                medidas += 1
            except Exception as exc:  # noqa: BLE001 — una cuenta no para las demás
                errores.append({"cuenta_id": bruto, "motivo": str(exc)[:200]})
        uow.volcar()

    return Tanda(
        avanzados=len(trozo),
        ok=medidas,
        fallidos=len(errores),
        errores=errores,
        total=len(cuentas),
        resultado={"medidas": medidas, "sin_senales": len(trozo) - medidas - len(errores)},
    )


def encolar_medicion(db: Session, *, tenant_id: UUID, pedido_por: UUID | None) -> Trabajo:
    from crmcore.datos.trabajos import encolar

    return encolar(db, tenant_id=tenant_id, tipo=TIPO, entrada={}, pedido_por=pedido_por)


registrar_ejecutor(TIPO, _ejecutar)
