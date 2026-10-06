"""Un ajuste que no lee nadie es peor que no tenerlo (`CRM-00.01.01`).

Quien lo pone cree que ya está. Pone `SAML_ENABLED=false` y sigue entrando por
SAML; pone `SUPLANTACION_EXIGE_MOTIVO=true` y se puede suplantar sin motivo. No
falla, no avisa y no hay forma de notarlo desde fuera: el sistema contesta
exactamente lo que contestaría si el ajuste funcionara.

Ya había pasado dos veces, y las dos se encontraron a mano: `INBOX_RETENCION_DIAS`
existía, estaba documentado y no lo leía nadie; `GRPC_ACTIVO` lo mismo —
encenderlo no encendía nada. Dos hallazgos iguales separados por semanas son una
familia, y una familia se barre, no se busca.

Medidos el 06-10-2026: **20 de 307 ajustes no los leía nadie en el producto.**
Hoy son **cero**, y la lista de abajo está vacía: lo que entre, entra en rojo.
Están en `.env.example`, están en el manual de referencia, y de ahí no pasan.

Qué cuenta como leerlo: que el nombre aparezca en el código del producto, en el
front o en un script de despliegue. Tres cosas NO cuentan, y cada una por su
motivo:

  · `.env.example` y `docs/manual-6-referencia-ajustes.md`, porque **los dos se
    generan desde esta misma declaración**. Contarlos haría que todo ajuste
    tuviera lector por el hecho de existir: un guardián mirando su reflejo.
  · **Las pruebas.** Que una prueba nombre un ajuste no dice nada de si el
    producto lo usa; es justo el caso que hay que cazar.

**Y el nombre no siempre está escrito.** Un ajuste leído con
`getattr(s, f"rpo_minutos_{tier}")` no aparece nunca como literal, así que la
primera versión de este recorrido marcó como muertos los **doce** compromisos de
servicio —RPO, RTO, disponibilidad y latencia por tier—, que se leen todos. Un
recorrido que acusa de más es tan inútil como uno que no mira: a la segunda
tanda de falsos positivos nadie vuelve a mirar la lista. Así que se recogen
también los prefijos construidos y se da por leído lo que empiece por uno.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PARTES = RAIZ / "packages" / "crmcore" / "crmcore" / "config_parts"

# Un campo de Settings: cuatro espacios de sangría, nombre, dos puntos, tipo, `=`.
RE_CAMPO = re.compile(r"^\s{4}([a-z_][a-z0-9_]*)\s*:\s*[^=\n]+=", re.M)

# Dónde se busca al lector. El front y los scripts cuentan: un ajuste que sólo
# usa el despliegue es un ajuste usado.
DONDE_BUSCAR: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("services", (".py",)),
    ("packages", (".py",)),
    ("scripts", (".py", ".sh", ".sql")),
    ("deploy", (".py", ".sh", ".sql", ".yaml", ".yml")),
    ("alembic", (".py",)),
    ("frontend/src", (".ts", ".tsx")),
)

# ── Los que hoy no lee nadie ──────────────────────────────────────────────
#
# Lista CERRADA y nominal, no un tope con hueco: sólo puede encoger. Un tope
# numérico deja sitio para que entre uno nuevo cada vez que se arregla otro, y
# entonces el número baja mientras el problema se queda igual.
#
#   06-10-2026  32  medición inicial — DOCE eran falsos positivos: los
#                   compromisos de servicio se leen con `getattr` y un nombre
#                   construido, así que su literal no aparece nunca
#   06-10-2026  20  medición buena, con los prefijos construidos recogidos
#   06-10-2026  30  SAML_ENABLED y OIDC_ENABLED: cuatro puertas cada uno
#   06-10-2026  29  SCIM_ENABLED: en el router, para que no se olvide ninguna ruta
#   06-10-2026  27  MFA_ENABLED manda sobre las dos formas de exigirla, y
#                   SUPLANTACION_EXIGE_MOTIVO se QUITA: el motivo se exige
#                   siempre y el único valor honesto del ajuste era `true`
#   06-10-2026  23  auditoría: AUDIT_ENABLED y AUDIT_HASH_CHAIN enchufados —y el
#                   readiness dice cuando están apagados—, LOG_REQUEST_BODY con
#                   el cuerpo censurado por dentro, y AUDIT_SIEM_URL quitado
#                   porque la exportación es por descarga, no por empuje
#   06-10-2026  19  resiliencia y arranque: CIRCUIT_BREAKER_ENABLED (que además
#                   cierra los circuitos ya abiertos), DEGRADACION_ENABLED,
#                   INBOX_ENABLED y DB_MIGRATE_ON_BOOT con cerrojo de aviso
#   06-10-2026  15  cifrado y secretos: BUS_TLS y CACHE_TLS pasan a EXIGIR (no
#                   reescriben la URL), SECRETOS_BACKEND corta si se configura
#                   un almacén que no existe, y SECRETOS_VAULT_URL se quita
#   06-10-2026   0  TENANT_DEFAULT_REGION y TENANT_DEFAULT_ISOLATION pasan a
#                   decidir el alta —estaban a fuego en tres sitios— y
#                   ONBOARDING_ENABLED se quita: el alta autoservicio no existe
SIN_LECTOR_HOY: set[str] = set()


@functools.cache
def _declarados() -> dict[str, str]:
    campos: dict[str, str] = {}
    for p in sorted(PARTES.glob("*.py")):
        for m in RE_CAMPO.finditer(p.read_text(encoding="utf-8")):
            campos[m.group(1)] = p.name
    return campos


@functools.cache
def _corpus() -> str:
    trozos = []
    for carpeta, extensiones in DONDE_BUSCAR:
        base = RAIZ / carpeta
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if (
                p.suffix in extensiones
                and "__pycache__" not in str(p)
                and "config_parts" not in str(p)
                and p.name != Path(__file__).name
            ):
                trozos.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(trozos)


# Un nombre de ajuste construido: `getattr(s, f"rpo_minutos_{tier}")`. De ahí
# sale el prefijo `rpo_minutos_`, y todo ajuste que empiece así está leído.
RE_PREFIJO = re.compile(r'f"([a-z_][a-z0-9_]*_)\{')


@functools.cache
def _prefijos_construidos() -> frozenset[str]:
    """Los prefijos con los que el producto arma nombres de ajuste.

    Se exige que el prefijo tenga algo de cuerpo: `f"{x}"` o `f"a_{x}"` darían
    un prefijo tan corto que casaría con medio fichero de ajustes, y entonces el
    recorrido dejaría de ver los muertos de verdad — que es la otra forma de
    romperlo.
    """
    return frozenset(p for p in RE_PREFIJO.findall(_corpus()) if len(p) >= 4)


@functools.cache
def _palabras() -> frozenset[str]:
    """El corpus partido en palabras, una vez.

    Buscar 307 nombres con 614 expresiones regulares sobre cinco megas tardaba
    veinte segundos — y un guardián que tarda veinte segundos se acaba sacando
    del preflight, que es la forma de perderlo. Partir una vez y preguntar al
    conjunto da lo mismo en milésimas.
    """
    return frozenset(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", _corpus()))


@functools.cache
def _sin_lector() -> frozenset[str]:
    palabras = _palabras()
    prefijos = tuple(_prefijos_construidos())
    return frozenset(
        c
        for c in _declarados()
        if c not in palabras and c.upper() not in palabras and not c.startswith(prefijos)
    )


def test_el_recorrido_mira_de_verdad() -> None:
    """Un recorrido que no encuentra nada pasa siempre.

    Se exige que vea los 307 ajustes y que reconozca como leído uno que
    evidentemente lo está: sin esto, un fallo al leer los ficheros daría «cero
    sin lector», que es el mismo verde que tenerlo todo bien.
    """
    campos = _declarados()
    assert len(campos) >= 300, f"solo se ven {len(campos)} ajustes: el recorrido no mira"
    assert "secret_key" in campos
    assert "secret_key" not in _sin_lector(), "el corpus no se está leyendo"


def test_ningun_ajuste_nuevo_nace_sin_lector() -> None:
    """Lo que no puede pasar es que la lista CREZCA.

    Un ajuste nuevo sin lector es una promesa nueva que no se cumple, y se
    descubre el día que un cliente la usa — que es el peor día para descubrirlo.
    """
    hoy = _sin_lector()
    nuevos = sorted(hoy - SIN_LECTOR_HOY)
    assert not nuevos, (
        "Ajustes nuevos que no lee nadie. Están en `.env.example` y en el manual, "
        "o sea prometidos, y no encienden nada:\n  " + "\n  ".join(nuevos)
    )


def test_los_que_se_arreglan_salen_de_la_lista() -> None:
    """Si uno ya tiene lector y sigue en la lista, el número miente a la baja y
    el trabajo hecho no se ve."""
    sobran = sorted(SIN_LECTOR_HOY - _sin_lector())
    assert not sobran, (
        "Ya tienen lector y siguen apuntados como si no. Quítalos de "
        "`SIN_LECTOR_HOY`:\n  " + "\n  ".join(sobran)
    )


def test_ni_el_env_ni_el_manual_cuentan_como_lector() -> None:
    """Los dos se generan desde la propia declaración. Contarlos haría que todo
    ajuste tuviera lector por existir: un guardián mirando su reflejo."""
    corpus = _corpus()
    assert "MFA_ENABLED=true" not in corpus, ".env.example se está colando en el corpus"
    assert "| `MFA_ENABLED` |" not in corpus, "el manual de ajustes se está colando en el corpus"
