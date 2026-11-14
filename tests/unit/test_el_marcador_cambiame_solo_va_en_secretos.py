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


# ── Y si se queda en el `.env`, producción no arranca (SEC-3, 13-11-2026) ──
#
# `.env.example` trae `ENV=prod` y diez secretos con `CAMBIAME`, y el arranque
# no conocía ese marcador: una copia a mano de la plantilla arrancaba en
# producción con `SECRET_KEY` publicada en el repositorio.


def _produccion_sana() -> dict[str, Any]:
    return dict(
        env="prod",
        secret_key="k" * 48,
        database_url="postgresql+psycopg://u:p@db:5432/crm",
        db_sslmode="verify-full",
        encryption_key="e" * 48,
        cache_backend="redis",
        cache_url="redis://r:6379/0",
        storage_backend="s3",
        storage_s3_bucket="b",
        ci_enabled=False,
    )


def test_cada_secreto_con_el_marcador_de_la_plantilla_impide_arrancar() -> None:
    """Todos los de `.env.example`, también los propios de un servicio."""
    import importlib

    from crmcore.config import MARCADOR_PLANTILLA, Settings

    for modulo in (
        "analytics",
        "integration",
        "intelligence",
        "marketing",
        "party",
        "sales",
        "service",
    ):
        importlib.import_module(f"services.{modulo}.ajustes")
    clases = [Settings, *Settings.__subclasses__()]

    con_marcador = {k.lower(): v for k, v in _env().items() if v == MARCADOR_PLANTILLA}
    assert "secret_key" in con_marcador and "encryption_key" in con_marcador, con_marcador

    for clave in con_marcador:
        duena = next((c for c in clases if clave in c.model_fields), None)
        assert duena is not None, f"{clave} está en la plantilla y no lo declara nadie"
        propios = {k: v for k, v in con_marcador.items() if k in duena.model_fields}
        problemas = duena(**{**_produccion_sana(), **propios}).verificar_para_produccion()
        assert any(clave.upper() in p for p in problemas), (clave, duena.__name__, problemas)


def test_el_generador_y_el_arranque_usan_el_mismo_marcador() -> None:
    from crmcore.config import MARCADOR_PLANTILLA

    fuente = (RAIZ / "scripts" / "gen_env_example.py").read_text(encoding="utf-8")
    assert f'return "{MARCADOR_PLANTILLA}"' in fuente


def test_una_clave_maestra_corta_impide_arrancar() -> None:
    from crmcore.config import LONGITUD_MINIMA_SECRETO, Settings

    corta = "x" * (LONGITUD_MINIMA_SECRETO - 1)
    for campo in ("secret_key", "encryption_key"):
        problemas = Settings(**{**_produccion_sana(), campo: corta}).verificar_para_produccion()
        assert any(campo.upper() in p for p in problemas), (campo, problemas)
    assert not [
        p
        for p in Settings(**_produccion_sana()).verificar_para_produccion()
        if "SECRET_KEY" in p or "ENCRYPTION_KEY" in p
    ]


def test_los_valores_por_defecto_del_compose_no_arrancan_en_produccion() -> None:
    """SEC-12: el compose fijaba ENV=dev y su SECRET_KEY no se reconocía."""
    import re

    from crmcore.config import Settings

    compose = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
    assert re.search(r"^\s+ENV: \$\{ENV:-dev\}", compose, re.M), "ENV no puede ir fijo"
    defecto = re.search(r"SECRET_KEY: \$\{SECRET_KEY:-([^}]+)\}", compose)
    assert defecto, "no se encuentra el SECRET_KEY por defecto del compose"
    problemas = Settings(
        **{**_produccion_sana(), "secret_key": defecto.group(1)}
    ).verificar_para_produccion()
    assert any("SECRET_KEY" in p for p in problemas), problemas
