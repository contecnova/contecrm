"""Todo listado dice de qué objeto de negocio es (RT-4).

Sin esa declaración, un informe sobre «cuenta» no sabe que sus registros se leen
del recurso `accounts`, y **no falla**: cae a la vista SQL interna del CRM, que
el motor de explotación no tiene y no puede tener —lee el CRM por su API, no por
su base—. Lo que se ve entonces es un informe vacío o un error del otro lado, y
los dos mandan a buscar el problema donde no está.

No se puede deducir del nombre. Son dos vocabularios y los dos son correctos: la
ruta va en inglés porque es contrato con quien integra (`accounts`,
`opportunities`) y el objeto en castellano porque es el idioma del negocio y el
de las políticas de acceso. Deducirlo acierta con unos y falla con
`proveedores-servicio` o con cualquier plural irregular — y una deducción que
falla a veces es peor que no tenerla, porque el informe sale igual, con los datos
de otra tabla y sin avisar.

`montar_listado` y `montar_ficha` lo apuntan solos. Los siete recursos con el
listado escrito a mano lo declaran con `declarar_recurso`, y este gate es lo que
impide que el octavo se olvide.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]

SERVICIOS = sorted(
    p.name
    for p in (RAIZ / "services").iterdir()
    if p.is_dir() and not p.name.startswith("_") and (p / "main.py").exists()
)


def _app(servicio: str) -> Any:
    import os

    os.environ["SERVICE_NAME"] = servicio
    os.environ["BUS_BACKEND"] = "memoria"
    return importlib.import_module(f"services.{servicio}.main").app


def test_todo_listado_raiz_declara_su_objeto() -> None:
    from fastapi.testclient import TestClient

    sin_objeto: list[str] = []
    con_objeto = 0

    for servicio in SERVICIOS:
        if servicio == "gateway":
            continue
        respuesta = TestClient(_app(servicio)).get("/api/v1/superficie")
        if respuesta.status_code != 200:
            continue
        for op in respuesta.json().get("operaciones", []):
            if op.get("metodo") != "GET" or not op.get("devuelve_lista"):
                continue
            ruta = str(op.get("ruta") or "")
            # Solo los listados RAÍZ: una sub-colección cuelga de un registro y
            # no es una entidad propia allí donde se explota.
            if "{" in ruta or ruta.count("/") != 3:
                continue
            if op.get("administracion") or op.get("solo_plataforma") or op.get("exige_datos"):
                continue
            if op.get("objeto"):
                con_objeto += 1
            else:
                sin_objeto.append(f"{servicio}: {ruta}")

    assert con_objeto, "no se ha leído ninguna superficie: el gate no está comprobando nada"
    assert not sin_objeto, (
        "Listados que no dicen de qué objeto son, así que un informe sobre ese "
        "objeto no encontrará su tabla:\n  "
        + "\n  ".join(sorted(sin_objeto))
        + '\n\nDeclaralo junto a su router: `declarar_recurso(router, "<objeto>")`.'
    )
