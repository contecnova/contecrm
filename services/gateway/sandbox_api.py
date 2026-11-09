"""El sandbox de API, de verdad: entorno, datos sintéticos y credencial (CRM-00.02.01.15).

Hasta el 09-11-2026 `POST /integracion/sandbox` devolvía un diccionario: «se
crearía un entorno con estos objetos, caduca tal día». No creaba nada. Un
integrador que lo pedía se quedaba sin dónde probar, que es lo único que un
sandbox tiene que dar.

Ahora hace las tres cosas que lo convierten en un sitio donde probar:

1. **Un entorno aparte**: un sandbox de tenancy, que es un tenant hijo con su
   caducidad. Se pide a tenancy por HTTP —el gateway no lee su tabla— con la
   identidad de quien lo pide, así que hacen falta sus permisos.
2. **Datos sintéticos generados del contrato**: para cada colección pedida se
   lee el esquema de su `POST` en el contrato publicado del servicio y se
   rellenan sus campos obligatorios —y los correos y las referencias a lo ya
   generado— con valores que tienen la forma del campo. Generados y no
   copiados: copiar producción a pruebas es como se filtra una base de clientes.
   Y genérico a propósito: ninguna lista de objetos ni de campos, porque una
   lista escrita a mano se queda atrás el día que alguien añade un objeto.
3. **Una credencial de API que sólo abre ese entorno**: la clave se emite en el
   tenant del sandbox, así que con ella no se ve nada del tenant real. Caduca
   con el sandbox.

La credencial se pide a identity como **servicio** y no como la persona, y por
eso no exige volver a verificarse: la reverificación existe para que nadie se
lleve un acceso permanente a los datos reales desde un portátil desbloqueado, y
esta clave no llega a ellos — abre un tenant con datos inventados. Lo que la
protege es su alcance y su caducidad, y queda en la auditoría con quién la pidió.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any

from crmcore.config import get_settings
from crmcore.errors import ErrorValidacion, NoDisponible
from crmcore.logging import get_logger
from crmcore.rutas_de_api import servicio_de

logger = get_logger(__name__)


# ── El generador ─────────────────────────────────────────────────────────


def _resolver(esquema: dict[str, Any], documento: dict[str, Any]) -> dict[str, Any]:
    """Sigue un `$ref` y aplana el `anyOf` de lo opcional (`X | None`)."""
    vistos = 0
    while "$ref" in esquema and vistos < 10:
        nombre = str(esquema["$ref"]).split("/")[-1]
        esquema = documento.get("components", {}).get("schemas", {}).get(nombre, {})
        vistos += 1
    for clave in ("anyOf", "oneOf"):
        if clave in esquema:
            utiles = [o for o in esquema[clave] if o.get("type") != "null"]
            if utiles:
                return _resolver(
                    {**utiles[0], **{k: v for k, v in esquema.items() if k != clave}}, documento
                )
    return esquema


def esquema_de_alta(documento: dict[str, Any], ruta: str) -> dict[str, Any] | None:
    """El esquema del cuerpo del `POST` de una colección, o `None` si no tiene."""
    operacion = documento.get("paths", {}).get(ruta, {}).get("post")
    if not operacion:
        return None
    cuerpo = (
        operacion.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    if not cuerpo:
        return None
    return _resolver(cuerpo, documento)


def alias_del_identificador(documento: dict[str, Any], ruta: str) -> str:
    """Cómo llaman los demás al identificador de esta colección.

    Sale de la ruta de su ficha en el contrato: `/accounts/{cuenta_id}` dice que
    una cuenta se nombra `cuenta_id`. Así un contacto generado después cuelga de
    una cuenta generada antes sin que nadie haya escrito «los contactos van con
    cuentas».
    """
    prefijo = ruta.rstrip("/") + "/{"
    for camino in documento.get("paths", {}):
        if camino.startswith(prefijo) and camino.endswith("}") and camino.count("{") == 1:
            return camino[len(prefijo) : -1]
    return ""


def _valor(
    nombre: str,
    esquema: dict[str, Any],
    i: int,
    *,
    semilla: str,
    referencias: dict[str, list[str]],
) -> Any:
    from crmcore.seguridad import anonimizar as anon

    tipo = esquema.get("type")
    formato = esquema.get("format", "")
    if esquema.get("enum"):
        opciones = list(esquema["enum"])
        return opciones[i % len(opciones)]
    if formato == "uuid" or nombre.endswith("_id"):
        candidatos = referencias.get(nombre) or []
        return random.Random(f"{semilla}{nombre}{i}").choice(candidatos) if candidatos else None
    if tipo == "boolean":
        return i % 2 == 0
    if tipo in ("integer", "number"):
        minimo = esquema.get("minimum", esquema.get("exclusiveMinimum", 0)) or 0
        maximo = esquema.get("maximum", esquema.get("exclusiveMaximum", minimo + 1000))
        valor = random.Random(f"{semilla}{nombre}{i}").randint(int(minimo), int(maximo))
        return valor if tipo == "integer" else float(valor)
    if formato == "date":
        return date.today().isoformat()
    if formato == "date-time":
        return datetime.now(timezone.utc).isoformat()
    if tipo == "string":
        forma = anon.forma_de(nombre)
        if formato == "email":
            forma = "email"
        if forma == "texto":
            texto = f"{esquema.get('title') or nombre} sintético {i + 1}"
        else:
            texto = str(anon.seudonimo(f"{nombre}{i}", sal=semilla, forma=forma))
        if forma == "email":
            # El dominio del seudónimo es `.invalid`, y la validación de correo
            # de los servicios lo rechaza con razón: un sandbox donde ningún
            # contacto se puede dar de alta no sirve. Se usa un dominio
            # reservado para ejemplos, que valida y no entrega a nadie.
            texto = f"{texto.split('@')[0]}@{get_settings().sandbox_api_dominio_correo}"
        maximo = int(esquema.get("maxLength") or 0)
        return texto[:maximo] if maximo else texto
    return None


def cuerpo_sintetico(
    esquema: dict[str, Any],
    documento: dict[str, Any],
    i: int,
    *,
    semilla: str,
    referencias: dict[str, list[str]],
) -> dict[str, Any]:
    """Un cuerpo válido para el `POST`, generado del esquema.

    Se rellena lo obligatorio, y de lo opcional sólo los correos y las
    referencias a lo ya generado: un sandbox donde ningún contacto tiene correo
    no sirve para probar un envío, y uno donde nada cuelga de nada no sirve para
    probar una relación. Lo demás se deja vacío, que también hay que probarlo.
    """
    requeridos = set(esquema.get("required") or [])
    cuerpo: dict[str, Any] = {}
    for nombre, crudo in (esquema.get("properties") or {}).items():
        propiedad = _resolver(crudo, documento)
        relevante = (
            nombre in requeridos
            or propiedad.get("format") == "email"
            or (nombre in referencias and referencias[nombre])
        )
        if not relevante:
            continue
        valor = _valor(nombre, propiedad, i, semilla=semilla, referencias=referencias)
        if valor is not None:
            cuerpo[nombre] = valor
    return cuerpo


# ── El sandbox entero ─────────────────────────────────────────────────────


async def crear(
    *,
    cliente: Any,
    destinos: dict[str, Any],
    principal: Any,
    nombre: str,
    objetos: list[str],
    filas_por_objeto: int,
) -> dict[str, Any]:
    """Crea el entorno, lo llena y emite su credencial. Devuelve lo que pasó."""
    from services.gateway import proxy

    s = get_settings()
    secreto = s.secret_key.get_secret_value()
    prefijo = s.api_prefix.rstrip("/")
    objetos = [o.strip().strip("/") for o in (objetos or list(s.sandbox_api_objetos)) if o.strip()]
    if not objetos:
        raise ErrorValidacion(
            "Un sandbox sin objetos no sirve para probar nada",
            error_code="sandbox.sin_objetos",
        )

    def _url(servicio: str) -> str:
        destino = destinos.get(servicio)
        if destino is None:
            raise NoDisponible(
                f"No hay dirección para el servicio «{servicio}»",
                error_code="sandbox.servicio_sin_direccion",
            )
        return str(destino.url_base)

    # 1. El entorno: un sandbox de tenancy, como quien lo pide.
    respuesta = await cliente.post(
        f"{_url('tenancy')}{prefijo}/sandboxes",
        json={"nombre": nombre, "proposito": "desarrollo"},
        headers=proxy.cabeceras_de_identidad(principal, secreto),
        timeout=30.0,
    )
    if respuesta.status_code >= 400:
        return _error_de(respuesta, "tenancy no ha creado el entorno")
    entorno = respuesta.json()
    hijo = entorno["tenant_sandbox_id"]

    # Dentro del sandbox, como servicio y con los permisos de quien lo pidió:
    # ni uno más.
    dentro = replace(principal, tenant_id=_uuid(hijo), tipo="servicio")
    cabeceras = proxy.cabeceras_de_identidad(dentro, secreto)

    # 2. Los datos, generados del contrato.
    contratos: dict[str, dict[str, Any]] = {}
    referencias: dict[str, list[str]] = {}
    por_objeto: list[dict[str, Any]] = []
    for objeto in objetos:
        ruta = f"{prefijo}/{objeto}"
        servicio = servicio_de(ruta)
        if not servicio or servicio not in destinos:
            por_objeto.append(
                {"objeto": objeto, "creadas": 0, "error": "Ningún servicio lo atiende"}
            )
            continue
        if servicio not in contratos:
            r = await cliente.get(f"{_url(servicio)}{prefijo}/openapi.json", timeout=10.0)
            contratos[servicio] = r.json() if r.status_code == 200 else {}
        documento = contratos[servicio]
        esquema = esquema_de_alta(documento, ruta)
        if esquema is None:
            por_objeto.append(
                {"objeto": objeto, "creadas": 0, "error": "No tiene alta (POST) en el contrato"}
            )
            continue
        creadas: list[str] = []
        primer_error = ""
        for i in range(filas_por_objeto):
            cuerpo = cuerpo_sintetico(
                esquema, documento, i, semilla=str(entorno["id"]), referencias=referencias
            )
            r = await cliente.post(
                f"{_url(servicio)}{ruta}", json=cuerpo, headers=cabeceras, timeout=15.0
            )
            if r.status_code < 300:
                fila = r.json() if r.content else {}
                if isinstance(fila, dict) and fila.get("id"):
                    creadas.append(str(fila["id"]))
            elif not primer_error:
                primer_error = f"{r.status_code}: {_detalle(r)}"
        alias = alias_del_identificador(documento, ruta)
        if alias and creadas:
            referencias[alias] = creadas
        por_objeto.append(
            {
                "objeto": objeto,
                "servicio": servicio,
                "creadas": len(creadas),
                "pedidas": filas_por_objeto,
                "error": primer_error,
            }
        )

    # 3. La credencial, en el tenant del sandbox y con su caducidad.
    r = await cliente.post(
        f"{_url('identity')}{prefijo}/claves-api",
        json={
            "nombre": f"Sandbox · {nombre}"[:120],
            "rol": "integracion",
            "dias": int(s.sandbox_dias),
        },
        headers=cabeceras,
        timeout=15.0,
    )
    if r.status_code >= 400:
        credencial: dict[str, Any] = {"error": f"{r.status_code}: {_detalle(r)}"}
    else:
        clave = r.json()
        credencial = {
            "id": clave.get("id"),
            "prefijo": clave.get("prefijo"),
            "secreto": clave.get("secreto"),
            "expira_at": clave.get("expira_at"),
            "solo_una_vez": "El secreto se enseña ahora y no se vuelve a poder leer",
        }
    logger.info(
        "sandbox_api.creado",
        sandbox=str(entorno["id"]),
        objetos=len(objetos),
        filas=sum(int(o.get("creadas") or 0) for o in por_objeto),
    )
    return {
        "sandbox_id": entorno["id"],
        "tenant_sandbox_id": hijo,
        "datos": "sinteticos",
        "objetos": por_objeto,
        "filas": sum(int(o.get("creadas") or 0) for o in por_objeto),
        "credencial": credencial,
        "porque_sinteticos": (
            "Copiar datos de producción a un entorno de pruebas es cómo se filtra "
            "una base de clientes por un sitio sin las mismas protecciones. Y los "
            "sintéticos se pueden romper, que es lo que hay que poder hacer aquí."
        ),
        "alcance": (
            "La credencial es del tenant del sandbox: con ella no se ve nada de la "
            "empresa real. Se apaga con el sandbox."
        ),
    }


def _uuid(valor: Any) -> Any:
    from uuid import UUID

    return UUID(str(valor))


def _detalle(respuesta: Any) -> str:
    try:
        cuerpo = respuesta.json()
        return str(cuerpo.get("detail") or cuerpo.get("title") or cuerpo)[:200]
    except Exception:  # noqa: BLE001 — un cuerpo que no es JSON se resume tal cual
        return respuesta.text[:200]


def _error_de(respuesta: Any, que: str) -> dict[str, Any]:
    """El error de tenancy, con su misma clase: un 403 sigue siendo un 403."""
    from crmcore.errors import ErrorDependencia, NoAutenticado, Prohibido

    clase = {401: NoAutenticado, 403: Prohibido, 422: ErrorValidacion, 400: ErrorValidacion}.get(
        respuesta.status_code, ErrorDependencia
    )
    raise clase(f"{que}: {_detalle(respuesta)}", error_code="sandbox.no_creado")
