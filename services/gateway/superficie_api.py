"""Lo que un integrador necesita del gateway: GraphQL, BFF, sandbox, mTLS y
portal de desarrollador
(CRM-00.02.01.02, CRM-00.02.01.15, CRM-00.02.03.03, CRM-00.02.04.03,
CRM-00.02.04.06, CRM-00.04.02.04).

Todo lo de aquí existe por la misma queja, que es la que se oye en cada
integración: **«para pintar una pantalla tengo que hacer siete llamadas»**. Y por
su gemela, que se oye después: «llevo tres días peleando con las credenciales».

Las decisiones:

**La lectura compuesta se declara, no se abre.** Un GraphQL abierto contra el
modelo entero es una forma elegante de dejar que cualquiera monte una consulta
que tumba la base. Aquí las composiciones se declaran, se les pone coste máximo y
se comprueban los permisos de cada parte por separado: una lectura compuesta no
puede enseñar lo que sus partes no enseñarían.

**El sandbox tiene datos sintéticos, no una copia.** Copiar datos de producción a
un entorno de pruebas es cómo se filtra una base de clientes entera por un
entorno sin las mismas protecciones. Los datos se generan.

**mTLS se exige por integración, no globalmente.** Obligarlo a todos deja fuera a
quien se integra con un script; no ofrecerlo deja sin nada a quien mueve dinero.
Se declara por cliente de API, con su huella.

**El portal enseña lo que de verdad pasó**, no lo que el contrato promete: sus
llamadas, sus errores, su cuota y lo que le queda. Un portal que solo documenta
es una web bonita que no resuelve la llamada de las tres de la mañana.

**Y un endpoint propio del tenant no se salta nada.** Es una composición con
nombre suyo: los permisos, los límites y la auditoría son los mismos. Si fuera
una puerta aparte, sería la puerta por la que se entra.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Coste máximo de una composición. No es el número de campos: es cuántas
# llamadas internas cuesta servirla. Sin tope, «dame la cuenta con sus contactos
# y las oportunidades de cada uno» es una consulta que hace mil peticiones.
COSTE_MAXIMO = 50

# Cuánto cuesta cada pieza. Una lista cuesta más que una ficha porque puede
# traer cien; una lista anidada cuesta por lo que multiplica.
COSTE = {"ficha": 1, "lista": 5, "lista_anidada": 20}

# Perfiles de composición para cada tipo de cliente (CRM-00.02.03.03). El móvil
# no necesita lo mismo que la web, y mandarle lo mismo es la razón por la que las
# aplicaciones móviles de CRM van lentas: traen quince campos para pintar tres.
PERFILES_BFF = ("web", "movil", "portal", "quiosco")


def coste_de(partes: list[dict[str, Any]]) -> int:
    """Cuánto cuesta servir una composición.

    Se calcula **antes** de ejecutarla. Calcularlo después es descubrir que
    costaba mil cuando ya se han hecho las mil llamadas.
    """
    total = 0
    for parte in partes:
        tipo = str(parte.get("tipo") or "ficha")
        total += COSTE.get(tipo, COSTE["ficha"])
    return total


def validar_composicion(
    *,
    nombre: str,
    partes: list[dict[str, Any]],
    permisos_del_llamante: frozenset[str] | set[str],
    perfil: str = "web",
) -> dict[str, Any]:
    """Comprueba una lectura compuesta antes de ejecutarla
    (CRM-00.02.01.02, CRM-00.02.03.03).

    **Los permisos se comprueban parte a parte.** Una composición no puede
    enseñar lo que sus partes no enseñarían: si alguien puede leer cuentas y no
    oportunidades, la composición «cuenta con sus oportunidades» le devuelve la
    cuenta y dice que la otra parte no se ha incluido. Devolverla entera sería
    convertir la comodidad en una vía de escalada.

    **Y se dice qué se ha quitado.** Devolver la respuesta recortada sin avisar
    hace que el integrador crea que ese cliente no tiene oportunidades.
    """
    from crmcore.authz.matriz import _cubre

    if perfil not in PERFILES_BFF:
        raise ErrorValidacion(
            f"Perfil de composición desconocido: «{perfil}»",
            error_code="bff.perfil_invalido",
            detalle={"admitidos": list(PERFILES_BFF)},
        )
    if not partes:
        raise ErrorValidacion(
            "Una composición sin partes no compone nada", error_code="bff.sin_partes"
        )

    total = coste_de(partes)
    if total > COSTE_MAXIMO:
        raise Conflicto(
            f"La composición «{nombre}» cuesta {total} y el tope es {COSTE_MAXIMO}. No "
            "es el número de campos: es cuántas llamadas internas cuesta servirla, y "
            "sin tope una sola consulta hace mil peticiones.",
            error_code="bff.demasiado_cara",
            detalle={"coste": total, "tope": COSTE_MAXIMO},
        )

    incluidas: list[str] = []
    quitadas: list[dict[str, str]] = []
    for parte in partes:
        exigido = str(parte.get("permiso") or "")
        clave = str(parte.get("nombre") or exigido or "?")
        if exigido and not any(_cubre(p, exigido) for p in permisos_del_llamante):
            quitadas.append({"parte": clave, "porque": f"no tiene «{exigido}»"})
            continue
        incluidas.append(clave)

    return {
        "composicion": nombre,
        "perfil": perfil,
        "coste": total,
        "incluidas": incluidas,
        # Lo quitado se dice: si no, el integrador cree que ese cliente no tiene
        # oportunidades, y lo que pasa es que él no puede verlas.
        "quitadas": quitadas,
        "completa": not quitadas,
        "aviso": (
            ""
            if not quitadas
            else "Faltan partes por permisos. No es que no haya datos: es que quien "
            "pregunta no puede verlos."
        ),
    }


# ── Sandbox de API (CRM-00.02.01.15) ──────────────────────────────────────

# Cuánto vive un sandbox sin tocarse. Uno eterno acumula credenciales que nadie
# recuerda y datos que nadie mira, y acaba siendo la puerta más vieja del
# sistema.
DIAS_SANDBOX = 30


def crear_sandbox(
    *, tenant_id: UUID, objetos: list[str], filas_por_objeto: int = 25
) -> dict[str, Any]:
    """Prepara un entorno de pruebas con datos **sintéticos**.

    Generados y no copiados. Copiar datos de producción a un entorno de pruebas
    es cómo se filtra una base de clientes entera por un sitio que no tiene las
    mismas protecciones — y es lo que casi todo el mundo hace, porque es más
    cómodo y los datos «parecen más reales».

    Los sintéticos tienen otra ventaja que nadie cuenta: se pueden romper. Un
    integrador puede borrar, duplicar y estropear a gusto, que es exactamente lo
    que hay que poder hacer en un entorno de pruebas.
    """
    if not objetos:
        raise ErrorValidacion(
            "Un sandbox sin objetos no sirve para probar nada",
            error_code="sandbox.sin_objetos",
        )
    if filas_por_objeto < 1 or filas_por_objeto > 500:
        raise ErrorValidacion(
            "Entre 1 y 500 filas por objeto: más no ayuda a probar y convierte el "
            "sandbox en un sitio donde hay que buscar.",
            error_code="sandbox.tamano_invalido",
        )
    caduca = datetime.now(timezone.utc) + timedelta(days=DIAS_SANDBOX)
    return {
        "tenant_id": str(tenant_id),
        "objetos": sorted(set(objetos)),
        "filas_por_objeto": filas_por_objeto,
        "datos": "sinteticos",
        "caduca_at": caduca.isoformat(),
        "porque_sinteticos": (
            "Copiar datos de producción a un entorno de pruebas es cómo se filtra "
            "una base de clientes por un sitio sin las mismas protecciones. Y los "
            "sintéticos se pueden romper, que es lo que hay que poder hacer aquí."
        ),
        "caduca_porque": (
            "Un sandbox eterno acumula credenciales que nadie recuerda y acaba "
            "siendo la puerta más vieja del sistema."
        ),
    }


# ── mTLS por integración (CRM-00.02.04.03) ────────────────────────────────


def exigir_mtls(
    *,
    huella_declarada: str,
    huella_presentada: str,
    obligatorio: bool,
) -> None:
    """Comprueba el certificado de cliente de una integración crítica.

    **Por integración y no globalmente.** Obligarlo a todos deja fuera a quien se
    integra con un script de cuatro líneas; no ofrecerlo deja sin nada a quien
    mueve dinero por esa API. Se declara por cliente.

    Y se compara la **huella**, no la cadena: un certificado firmado por la misma
    autoridad no es el mismo certificado, y aceptar cualquiera de la cadena
    convierte el mTLS en una comprobación de que existe una autoridad.
    """
    if not obligatorio:
        return
    if not huella_presentada:
        raise NoAutenticado(
            "Esta integración exige certificado de cliente y no ha llegado ninguno",
            error_code="mtls.sin_certificado",
        )
    if huella_presentada.strip().lower() != (huella_declarada or "").strip().lower():
        raise Prohibido(
            "El certificado presentado no es el declarado para esta integración. Se "
            "compara la huella y no la cadena: uno firmado por la misma autoridad no "
            "es el mismo certificado.",
            error_code="mtls.certificado_distinto",
        )


# ── Portal de desarrollador (CRM-00.02.04.06) ─────────────────────────────


def panel_de_integrador(
    *,
    clave: str,
    llamadas: list[dict[str, Any]],
    cuota_mes: int,
    scopes: list[str],
) -> dict[str, Any]:
    """Lo que ve un integrador de su propia clave.

    **Lo que de verdad pasó, no lo que el contrato promete.** Un portal que solo
    documenta es una web bonita que no resuelve la llamada de las tres de la
    mañana; lo que la resuelve es ver el último error con su código y su hora.

    Los errores van **separados por culpa**: los suyos —4xx— y los nuestros
    —5xx—. Mezclarlos hace que un integrador pase una tarde revisando su código
    por una caída nuestra, o al revés.
    """
    total = len(llamadas)
    suyos = [ll for ll in llamadas if 400 <= int(ll.get("status") or 0) < 500]
    nuestros = [ll for ll in llamadas if int(ll.get("status") or 0) >= 500]
    ultimos_errores = sorted(
        (ll for ll in llamadas if int(ll.get("status") or 0) >= 400),
        key=lambda ll: str(ll.get("cuando") or ""),
        reverse=True,
    )[:10]

    return {
        "clave": clave,
        "scopes": sorted(set(scopes)),
        "llamadas": total,
        "consumido_pct": round(100 * total / cuota_mes, 1) if cuota_mes else None,
        "quedan": max(0, cuota_mes - total) if cuota_mes else None,
        # Separados por culpa: mezclarlos hace que un integrador pase una tarde
        # revisando su código por una caída nuestra.
        "errores_suyos": len(suyos),
        "errores_nuestros": len(nuestros),
        "ultimos_errores": [
            {
                "cuando": ll.get("cuando"),
                "ruta": ll.get("ruta"),
                "status": ll.get("status"),
                "detalle": str(ll.get("detalle") or "")[:200],
            }
            for ll in ultimos_errores
        ],
        "que_mirar_primero": (
            "Nada: no hay errores en la ventana."
            if not suyos and not nuestros
            else "Los errores 5xx son nuestros: si los hay, abre incidencia en vez de "
            "revisar tu código."
            if nuestros
            else "Todos los errores son 4xx: la petición no cuadra con el contrato. El "
            "detalle de cada uno dice qué campo."
        ),
    }


# ── Endpoints propios del tenant (CRM-00.04.02.04) ────────────────────────


def declarar_endpoint_propio(
    *,
    ruta: str,
    composicion: str,
    permiso: str,
    tenant_id: UUID,
) -> dict[str, Any]:
    """Un endpoint con nombre del tenant, sobre el mismo gateway.

    Es una **composición con nombre suyo**, no una puerta aparte: los permisos,
    los límites de tasa y la auditoría son los mismos. Si fuera una puerta
    aparte, sería la puerta por la que se entra — un camino que no pasa por donde
    pasan los demás es un camino donde los controles se ponen otra vez, peor y
    más tarde.

    Y **no puede pisar una ruta del producto**. Dejar que un tenant declare
    `/api/v1/accounts` haría que su integración dejara de funcionar el día que se
    publique la nuestra, o peor: que la nuestra dejara de funcionar para él.
    """
    limpia = "/" + ruta.strip("/")
    if not limpia.startswith("/api/v1/x/"):
        raise ErrorValidacion(
            "Los endpoints propios del tenant viven bajo «/api/v1/x/». Fuera de ahí "
            "chocarían con las rutas del producto: el día que se publique una con "
            "ese nombre, una de las dos deja de funcionar.",
            error_code="endpoint.fuera_del_espacio",
        )
    if not permiso:
        raise ErrorValidacion(
            "Un endpoint propio sin permiso declarado sería el único sitio del "
            "producto donde se entra sin comprobar nada.",
            error_code="endpoint.sin_permiso",
        )
    return {
        "ruta": limpia,
        "composicion": composicion,
        "permiso": permiso,
        "tenant_id": str(tenant_id),
        "hereda": [
            "el mismo límite de tasa",
            "la misma auditoría",
            "la misma comprobación de permisos",
            "el mismo presupuesto de error",
        ],
        "porque": (
            "Es una composición con nombre propio, no una puerta aparte. Un camino "
            "que no pasa por donde pasan los demás es un camino donde los controles "
            "se ponen otra vez, peor y más tarde."
        ),
    }
