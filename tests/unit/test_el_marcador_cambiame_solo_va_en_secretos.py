"""Un marcador de sustitución donde no hace falta es una avería esperando.

Medido el 06-10-2026. `gen_env_example.py` decidía qué ajuste es un secreto
buscando «secret», «password», «key» o «token» **dentro** del nombre, así que
cuatro que no lo son salían como `CAMBIAME` en `.env.example` y en el `.env` de
esta máquina:

    SECRETOS_BACKEND   lleva «secret» y es el NOMBRE del almacén
    PASSKEY_RP_ID      lleva «key» y es un identificador público
    PASSKEY_RP_NOMBRE  lo mismo
    PASSKEY_ORIGENES   lo mismo

No era teórico. En cuanto `SECRETOS_BACKEND` empezó a leerse de verdad —ese
mismo día—, el alta de herramientas de suite empezó a contestar «SECRETOS_BACKEND
=CAMBIAME no está implementado»: un ajuste que no necesitaba marcador tumbó una
ruta en cuanto alguien enchufó el ajuste.

Y la regla por subcadena ocultaba lo contrario: `SMTP_CLAVE` **sí** es un
secreto y salía en claro, porque «clave» no estaba en la lista.

Se deciden dos cosas a la vez y se usan las dos:

  · el **último segmento** del nombre, no la subcadena;
  · y el **tipo declarado**, `SecretStr`, que no es una suposición sino lo que
    puso quien escribió el ajuste — y caza `ENCRYPTION_KEY_PREVIA`, que acaba
    en «previa».
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import Any

RAIZ = pathlib.Path(__file__).resolve().parents[2]


def _generador() -> Any:
    ruta = RAIZ / "scripts" / "gen_env_example.py"
    spec = importlib.util.spec_from_file_location("gen_env_", ruta)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    try:
        spec.loader.exec_module(modulo)
    finally:
        sys.modules.pop(spec.name, None)
    return modulo


def _env() -> dict[str, str]:
    pares = {}
    for linea in (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines():
        if "=" in linea and not linea.startswith("#"):
            clave, _, valor = linea.partition("=")
            pares[clave.strip()] = valor.strip()
    return pares


def test_el_recorrido_mira_de_verdad() -> None:
    """Un `.env.example` que no se hubiera generado daría cero marcadores, que
    es el mismo verde que tenerlo todo bien."""
    pares = _env()
    assert len(pares) >= 280, f"solo se ven {len(pares)} ajustes en .env.example"
    assert pares.get("SECRET_KEY") == "CAMBIAME"


def test_los_que_no_son_secretos_traen_su_valor_de_verdad() -> None:
    """`CAMBIAME` en un ajuste con valor por defecto esconde ese valor, y quien
    copie el fichero arranca con algo que no es nada."""
    pares = _env()
    assert pares.get("SECRETOS_BACKEND") == "db"
    for clave in ("PASSKEY_RP_ID", "PASSKEY_RP_NOMBRE", "PASSKEY_ORIGENES"):
        assert pares.get(clave) != "CAMBIAME", f"{clave} no es un secreto"


def test_los_secretos_de_verdad_siguen_marcados() -> None:
    """Equivocarse de menos aquí saca un secreto al fichero de ejemplo."""
    pares = _env()
    for clave in (
        "SECRET_KEY",
        "SUPERADMIN_PASSWORD",
        "ENCRYPTION_KEY",
        "ENCRYPTION_KEY_PREVIA",
        "STORAGE_S3_SECRET_KEY",
        "DMS_CLIENT_SECRET",
        "CI_CLIENT_SECRET",
        "SMTP_CLAVE",
    ):
        assert pares.get(clave) == "CAMBIAME", f"{clave} sale en claro"


def test_smtp_clave_salia_en_claro_con_la_regla_vieja() -> None:
    """La regla por subcadena no llevaba «clave», así que la contraseña del
    correo saliente se escribía tal cual en el fichero de ejemplo."""
    vieja = ("secret", "password", "key", "token")
    assert not any(p in "smtp_clave" for p in vieja)
    assert "clave" in _generador().PALABRAS_DE_SECRETO


def test_el_tipo_declarado_tambien_cuenta() -> None:
    """Sólo el nombre deja fuera los que llevan un calificativo detrás."""
    g = _generador()
    assert "SecretStr" in g.TIPOS_DE_SECRETO
    assert "previa" not in g.PALABRAS_DE_SECRETO


def test_un_entero_con_token_en_el_nombre_sigue_sin_marcarse() -> None:
    """Es el fallo que ya se había arreglado una vez: `DMS_TOKEN_TTL_S` salía
    como `CAMBIAME` y el servicio se negaba a arrancar por un número mal puesto.
    Arreglar lo de arriba no puede volver a romper esto."""
    pares = _env()
    for clave, valor in pares.items():
        if valor == "CAMBIAME":
            assert not clave.endswith(("_S", "_MS", "_DIAS", "_PCT")), f"{clave} es un número"
