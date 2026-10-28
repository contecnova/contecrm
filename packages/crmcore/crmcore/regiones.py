"""Dónde se procesa un dato. UNA lista, porque es UNA promesa.

Había dos, y las dos decían llamarse `REGIONES`:

  * `services/tenancy/residencia.py` — las que el despliegue sabe distinguir
    cuando un cliente firma dónde se queda su dato: siete, con `latam` y
    `apac`;
  * `services/intelligence/enrutador.py` — las que la política de IA admitía:
    seis, **sin** `latam` ni `apac`, y con una `otra` que las otras no tienen.

Lo que eso producía no es una incoherencia de catálogo, son dos fallos:

  * un cliente con residencia en `latam` o en `apac` **no podía declarar su
    política de IA**: `fijar_politica(regiones_admitidas=["latam"])` contestaba
    `ia.region_no_valida`. Justo el cliente que más necesita el modo «el dato
    no sale de aquí» era el único que no podía pedirlo;
  * y al revés, `otra` sí se admitía como región de un tenant. `otra` en un
    proveedor significa «no sabemos dónde está». Admitirla como región del
    tenant hacía que el modo sin salida eligiera un proveedor de paradero
    desconocido y lo anunciara como «la misma región del tenant».

Por eso `otra` se queda donde tiene sentido —describiendo un proveedor— y no
donde se promete algo: en `REGIONES_DE_PROVEEDOR`, que es ésta más esa.
"""

from __future__ import annotations

# Lista cerrada porque es lo que se le firma al cliente: con texto libre, «UE» y
# «eu-west» serían dos regiones para el informe y la misma para quien la firmó.
REGIONES: tuple[str, ...] = (
    "ue",
    "ee_uu",
    "reino_unido",
    "suiza",
    "latam",
    "apac",
    "local",
)

# Dónde puede estar alojado un proveedor. Lo mismo, más «no consta»: un
# proveedor puede estar en un sitio que el despliegue no distingue, y eso hay
# que poder decirlo. Lo que no se puede es prometerlo.
REGIONES_DE_PROVEEDOR: tuple[str, ...] = (*REGIONES, "otra")
