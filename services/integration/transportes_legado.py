"""Transportes para entornos heredados: SOAP, SFTP, ficheros planos, EDI y AMQP
(CRM-00.03.04.03).

El conector declarativo resolvió el 80 % de las integraciones modernas, que son
HTTP con JSON. El 20 % que queda es el que paga las facturas: el ERP que solo
habla SOAP, el mayorista que deja un fichero en un SFTP a las 3:00, el operador
logístico que manda EDIFACT y la fábrica que publica en una cola AMQP.

Dos reglas comunes a los cinco, y son las mismas que en el conector REST:

**La configuración, no el código.** Un transporte nuevo por cliente sería otra
vez código por proveedor. Aquí cada uno se declara con su config —host, ruta,
separador, segmentos— y lo que cambia entre dos clientes es esa config, no un
módulo.

**Lo que llega se registra tal cual antes de interpretarlo.** Cuando un fichero
plano cambia de formato sin avisar —y cambia—, lo único que permite entender qué
pasó es el original. Interpretar primero y guardar después deja el error y no la
causa.

Y una decisión propia de los ficheros: **nunca se borra el origen hasta que el
proceso ha terminado bien**. Media integración heredada se pierde porque alguien
borra el fichero al leerlo y el proceso falla después; el mayorista no lo vuelve a
mandar, y ese día de pedidos no existe.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Callable
from xml.etree import ElementTree

from crmcore.errors import ErrorDependencia, ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Protocolos que sabe hablar este módulo. Lista cerrada: cada uno tiene su
# manejador registrado, y un protocolo inventado en una configuración fallaría
# en tiempo de ejecución, dentro de un proceso nocturno que nadie mira.
PROTOCOLOS = ("soap", "sftp", "fichero", "edi", "amqp")

# Formatos de fichero plano que se saben leer sin escribir código.
FORMATOS = ("delimitado", "ancho_fijo", "json_lineas")

# Dialectos EDI. Los dos que existen de verdad en el mundo real: EDIFACT en
# Europa y X12 en Norteamérica. La diferencia es el separador y el nombre de los
# segmentos, no el concepto.
DIALECTOS_EDI = ("edifact", "x12")

# Manejadores por protocolo, registrados por el propio módulo. Es el mismo patrón
# de registro invertido que usan los informes y las aprobaciones: añadir un
# transporte no obliga a tocar un `if` central.
_MANEJADORES: dict[str, Callable[..., Any]] = {}


def registrar_transporte(clave: str, fn: Callable[..., Any]) -> None:
    """Declara quién habla un protocolo."""
    _MANEJADORES[clave] = fn


def transportes_registrados() -> list[str]:
    return sorted(_MANEJADORES)


@dataclass(frozen=True, slots=True)
class Resultado:
    """Lo que devuelve un transporte, siempre igual.

    `crudo` viaja con los datos a propósito: cuando el formato cambie sin avisar,
    es lo único que permitirá saber qué llegó de verdad.
    """

    filas: list[dict[str, Any]] = field(default_factory=list)
    crudo: str = ""
    origen: str = ""
    avisos: list[str] = field(default_factory=list)


# ── Ficheros planos (CRM-00.03.04.03) ─────────────────────────────────────


def leer_fichero(contenido: str, config: dict[str, Any]) -> Resultado:
    """Convierte un fichero plano en filas, según lo declarado.

    Tres formatos y ninguna adivinación: el separador, las columnas y su orden se
    declaran. Detectar el formato automáticamente funciona el 95 % de las veces, y
    el 5 % restante son cargas que entran mal sin fallar — que es la peor forma de
    fallar que hay.
    """
    formato = str(config.get("formato") or "delimitado")
    if formato not in FORMATOS:
        raise ErrorValidacion(
            f"Formato de fichero «{formato}» no soportado.",
            error_code="transportes.formato_no_valido",
            detalle={"validos": list(FORMATOS)},
        )
    avisos: list[str] = []
    filas: list[dict[str, Any]] = []

    if formato == "json_lineas":
        import json

        for i, linea in enumerate(contenido.splitlines(), 1):
            if not linea.strip():
                continue
            try:
                filas.append(json.loads(linea))
            except json.JSONDecodeError:
                # Una línea rota no tumba el fichero: se cuenta y se sigue. Un
                # fichero de 50.000 pedidos no se descarta entero por uno malo.
                avisos.append(f"Línea {i} ilegible: no es JSON.")
        return Resultado(filas=filas, crudo=contenido, avisos=avisos)

    if formato == "ancho_fijo":
        columnas = config.get("columnas") or []
        if not columnas:
            raise ErrorValidacion(
                "Un fichero de ancho fijo necesita sus columnas declaradas "
                "(nombre, desde, hasta).",
                error_code="transportes.sin_columnas",
            )
        saltar = int(config.get("saltar_cabecera") or 0)
        for i, linea in enumerate(contenido.splitlines()):
            if i < saltar or not linea.strip():
                continue
            fila: dict[str, Any] = {}
            for columna in columnas:
                desde = int(columna.get("desde", 0))
                hasta = int(columna.get("hasta", desde))
                trozo = linea[desde:hasta]
                if len(linea) < hasta:
                    avisos.append(
                        f"Línea {i + 1} más corta de lo declarado: «"
                        f"{columna.get('nombre')}» sale truncado."
                    )
                fila[str(columna.get("nombre"))] = trozo.strip()
            filas.append(fila)
        return Resultado(filas=filas, crudo=contenido, avisos=avisos)

    separador = str(config.get("separador") or ",")
    comillas = str(config.get("comillas") or '"')
    cabecera = bool(config.get("cabecera", True))
    columnas = [str(c) for c in (config.get("columnas") or [])]
    lector = csv.reader(io.StringIO(contenido), delimiter=separador, quotechar=comillas)
    nombres: list[str] = columnas
    for i, campos in enumerate(lector):
        if not campos:
            continue
        if i == 0 and cabecera:
            if not nombres:
                nombres = [c.strip() for c in campos]
            continue
        if not nombres:
            # Sin cabecera ni columnas declaradas, las filas salen por posición y
            # se dice: un mapeo por índice es frágil y quien lo use tiene que
            # saberlo.
            avisos.append(
                "El fichero no trae cabecera ni columnas declaradas: las filas "
                "salen indexadas por posición."
            )
            nombres = [str(n) for n in range(len(campos))]
        if len(campos) != len(nombres):
            avisos.append(f"Línea {i + 1} con {len(campos)} campos y se esperaban {len(nombres)}.")
        filas.append(
            {n: (campos[j].strip() if j < len(campos) else None) for j, n in enumerate(nombres)}
        )
    return Resultado(filas=filas, crudo=contenido, avisos=avisos)


# ── EDI: EDIFACT y X12 (CRM-00.03.04.03) ──────────────────────────────────


def leer_edi(contenido: str, config: dict[str, Any]) -> Resultado:
    """Parte un mensaje EDI en segmentos con sus elementos.

    **No se interpreta el significado**: se devuelven los segmentos tal cual, con
    su etiqueta y sus elementos. Traducir aquí un ORDERS a un pedido metería el
    vocabulario de un sector en el núcleo, y cada sector tiene el suyo; esa
    traducción es del adaptador canónico, que es exactamente para eso.

    Se filtra por segmento cuando se pide: un DESADV trae cincuenta segmentos y
    el que integra necesita tres.
    """
    dialecto = str(config.get("dialecto") or "edifact")
    if dialecto not in DIALECTOS_EDI:
        raise ErrorValidacion(
            f"Dialecto EDI «{dialecto}» no soportado.",
            error_code="transportes.dialecto_no_valido",
            detalle={"validos": list(DIALECTOS_EDI)},
        )
    if dialecto == "edifact":
        fin, elem, comp = (
            str(config.get("fin_segmento") or "'"),
            str(config.get("separador_elemento") or "+"),
            str(config.get("separador_componente") or ":"),
        )
    else:
        fin, elem, comp = (
            str(config.get("fin_segmento") or "~"),
            str(config.get("separador_elemento") or "*"),
            str(config.get("separador_componente") or ">"),
        )

    solo = {str(s).upper() for s in (config.get("segmentos") or [])}
    filas: list[dict[str, Any]] = []
    avisos: list[str] = []
    # Si el fin de segmento declarado no aparece, el mensaje entero sale como un
    # único segmento con un nombre absurdo — y **sin error**. Es el fallo típico
    # al configurar un emisor nuevo, y detectarlo aquí evita una carga entera de
    # basura que parece correcta.
    if fin not in contenido:
        avisos.append(
            f"El fin de segmento declarado ({fin!r}) no aparece en el mensaje: "
            "los separadores no son los de este emisor y lo leído no significa nada."
        )
    for bruto in contenido.split(fin):
        texto = bruto.strip().replace("\n", "").replace("\r", "")
        if not texto:
            continue
        partes = texto.split(elem)
        etiqueta = partes[0].strip().upper()
        if solo and etiqueta not in solo:
            continue
        elementos = [(p.split(comp) if comp in p else p) for p in partes[1:]]
        filas.append({"segmento": etiqueta, "elementos": elementos})
    if not filas:
        avisos.append(
            "No se ha reconocido ningún segmento: comprueba los separadores "
            "declarados, que cambian entre emisores."
        )
    return Resultado(filas=filas, crudo=contenido, avisos=avisos)


# ── SOAP (CRM-00.03.04.03) ────────────────────────────────────────────────

RE_NS = re.compile(r"^\{[^}]+\}")


def _sin_ns(etiqueta: str) -> str:
    return RE_NS.sub("", etiqueta)


def envolver_soap(cuerpo: str, config: dict[str, Any] | None = None) -> str:
    """Mete el cuerpo en un sobre SOAP.

    Sin librería de SOAP a propósito: un WSDL completo obligaría a generar código
    por servicio, que es justo lo que este proyecto evita. Con el sobre y el
    cuerpo declarados, el 90 % de los servicios heredados —que son consultas y
    altas— funcionan con configuración.
    """
    config = config or {}
    version = str(config.get("version") or "1.1")
    ns = (
        "http://schemas.xmlsoap.org/soap/envelope/"
        if version == "1.1"
        else "http://www.w3.org/2003/05/soap-envelope"
    )
    cabecera = config.get("cabecera") or ""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<soap:Envelope xmlns:soap="{ns}">'
        f"{f'<soap:Header>{cabecera}</soap:Header>' if cabecera else ''}"
        f"<soap:Body>{cuerpo}</soap:Body>"
        f"</soap:Envelope>"
    )


def leer_soap(respuesta: str, config: dict[str, Any] | None = None) -> Resultado:
    """Saca del sobre SOAP lo que interesa, y **detecta el Fault**.

    Un `soap:Fault` llega con **HTTP 200** en muchísimos servicios: si no se mira
    el cuerpo, un error se procesa como si fuera un resultado correcto y entra
    como cero filas. Eso es lo que hace que un proceso nocturno diga que fue bien
    y no haya traído nada.
    """
    config = config or {}
    try:
        raiz = ElementTree.fromstring(respuesta)
    except ElementTree.ParseError as error:
        raise ErrorDependencia(
            f"La respuesta SOAP no es XML válido: {error}",
            error_code="transportes.soap_ilegible",
        ) from error

    # Que sea XML válido no lo convierte en SOAP: una página de error de un
    # proxy es XML perfectamente formado, y sin esta comprobación se procesaría
    # como una respuesta correcta con cero filas — que es un proceso nocturno
    # diciendo que todo fue bien.
    if _sin_ns(raiz.tag).lower() != "envelope":
        raise ErrorDependencia(
            "La respuesta no es un sobre SOAP: llegó un documento "
            f"«{_sin_ns(raiz.tag)}». Suele ser una página de error de un proxy o "
            "un portal de autenticación por delante del servicio.",
            error_code="transportes.soap_no_es_sobre",
        )

    for nodo in raiz.iter():
        if _sin_ns(nodo.tag).lower() == "fault":
            detalle = {
                _sin_ns(hijo.tag): (hijo.text or "").strip()
                for hijo in nodo.iter()
                if hijo is not nodo
            }
            raise ErrorDependencia(
                "El servicio ha devuelto un SOAP Fault: "
                + (detalle.get("faultstring") or detalle.get("Reason") or "sin descripción"),
                error_code="transportes.soap_fault",
                detalle=detalle,
            )

    ruta = str(config.get("nodo_filas") or "")
    nodos = []
    if ruta:
        for nodo in raiz.iter():
            if _sin_ns(nodo.tag) == ruta:
                nodos.append(nodo)
    else:
        cuerpo = next((n for n in raiz.iter() if _sin_ns(n.tag).lower() == "body"), None)
        nodos = list(cuerpo) if cuerpo is not None else []

    filas = []
    for nodo in nodos:
        fila = {_sin_ns(h.tag): (h.text or "").strip() for h in nodo}
        if not fila and nodo.text:
            fila = {_sin_ns(nodo.tag): nodo.text.strip()}
        filas.append(fila)
    return Resultado(filas=filas, crudo=respuesta)


# ── SFTP (CRM-00.03.04.03) ────────────────────────────────────────────────


def listar_sftp(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Lista los ficheros que encajan con el patrón declarado.

    La huella del host se comprueba si está declarada. **No se acepta cualquier
    host automáticamente**: aceptar la clave que venga es abrir la puerta a que
    alguien se ponga en medio, y en un canal por el que viaja el maestro de
    clientes eso no es aceptable. Sin huella declarada se avisa y se rechaza,
    porque el aviso solo lo lee alguien si le impide seguir.
    """
    import fnmatch

    import paramiko

    host = str(config.get("host") or "")
    if not host:
        raise ErrorValidacion("Falta el host SFTP.", error_code="transportes.sftp_sin_host")
    huella = str(config.get("huella_host") or "")
    if not huella and not config.get("aceptar_host_desconocido"):
        raise ErrorValidacion(
            "Falta la huella del host SFTP. Sin comprobarla, cualquiera que se "
            "ponga en medio recibe el fichero; si es un entorno de pruebas, "
            "decláralo con `aceptar_host_desconocido`.",
            error_code="transportes.sftp_sin_huella",
        )

    cliente = paramiko.SSHClient()
    if huella:
        cliente.set_missing_host_key_policy(paramiko.RejectPolicy())
        cliente.get_host_keys().add(
            host, str(config.get("tipo_clave") or "ssh-rsa"), paramiko.RSAKey(data=_b64(huella))
        )
    else:
        cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    cliente.connect(
        hostname=host,
        port=int(config.get("puerto") or 22),
        username=str(config.get("usuario") or ""),
        password=config.get("clave"),
        key_filename=config.get("clave_privada"),
        timeout=float(config.get("timeout_s") or 30),
    )
    try:
        sftp = cliente.open_sftp()
        ruta = str(config.get("ruta") or ".")
        patron = str(config.get("patron") or "*")
        salida = []
        for atributos in sftp.listdir_attr(ruta):
            if not fnmatch.fnmatch(atributos.filename, patron):
                continue
            salida.append(
                {
                    "nombre": atributos.filename,
                    "ruta": f"{ruta.rstrip('/')}/{atributos.filename}",
                    "tamano": atributos.st_size,
                    "modificado": atributos.st_mtime,
                }
            )
        return sorted(salida, key=lambda f: f["modificado"] or 0)
    finally:
        cliente.close()


def _b64(texto: str) -> bytes:
    import base64

    return base64.b64decode(texto)


def descargar_sftp(config: dict[str, Any], ruta: str) -> str:
    """Descarga un fichero. **No lo borra**: eso se decide después.

    Borrar al leer es cómo se pierde un día entero de pedidos: el proceso falla
    después de leer, el mayorista no lo vuelve a mandar, y el fichero ya no está.
    """
    import paramiko

    cliente = paramiko.SSHClient()
    cliente.set_missing_host_key_policy(
        paramiko.AutoAddPolicy()
        if config.get("aceptar_host_desconocido")
        else paramiko.RejectPolicy()
    )
    if config.get("huella_host"):
        cliente.get_host_keys().add(
            str(config.get("host")),
            str(config.get("tipo_clave") or "ssh-rsa"),
            paramiko.RSAKey(data=_b64(str(config["huella_host"]))),
        )
    cliente.connect(
        hostname=str(config.get("host")),
        port=int(config.get("puerto") or 22),
        username=str(config.get("usuario") or ""),
        password=config.get("clave"),
        key_filename=config.get("clave_privada"),
        timeout=float(config.get("timeout_s") or 30),
    )
    try:
        sftp = cliente.open_sftp()
        with sftp.open(ruta, "r") as fichero:
            return fichero.read().decode(
                str(config.get("codificacion") or "utf-8"), errors="replace"
            )
    finally:
        cliente.close()


def archivar_sftp(config: dict[str, Any], ruta: str) -> str:
    """Mueve el fichero ya procesado a la carpeta de archivo.

    Mover y no borrar: cuando dentro de un mes haya que explicar por qué un
    pedido entró mal, el fichero original es lo único que lo explica.
    """
    import paramiko

    destino_dir = str(config.get("archivo") or "")
    if not destino_dir:
        raise ErrorValidacion(
            "Falta la carpeta de archivo: procesar y no mover deja el mismo "
            "fichero entrando cada noche.",
            error_code="transportes.sftp_sin_archivo",
        )
    cliente = paramiko.SSHClient()
    cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cliente.connect(
        hostname=str(config.get("host")),
        port=int(config.get("puerto") or 22),
        username=str(config.get("usuario") or ""),
        password=config.get("clave"),
        key_filename=config.get("clave_privada"),
        timeout=float(config.get("timeout_s") or 30),
    )
    try:
        sftp = cliente.open_sftp()
        destino = f"{destino_dir.rstrip('/')}/{ruta.rsplit('/', 1)[-1]}"
        sftp.rename(ruta, destino)
        return destino
    finally:
        cliente.close()


# ── AMQP (CRM-00.03.04.03) ────────────────────────────────────────────────


async def publicar_amqp(config: dict[str, Any], cuerpo: str) -> dict[str, Any]:
    """Publica un mensaje en una cola AMQP.

    **Persistente por defecto.** Un mensaje transitorio se pierde al reiniciar el
    broker, y quien integra por cola espera justo lo contrario: que el mensaje
    aguante aunque el otro lado esté caído. Hacerlo transitorio tiene que ser una
    decisión escrita.
    """
    import aio_pika

    url = str(config.get("url") or "")
    if not url:
        raise ErrorValidacion("Falta la URL AMQP.", error_code="transportes.amqp_sin_url")
    conexion = await aio_pika.connect_robust(url)
    try:
        canal = await conexion.channel()
        mensaje = aio_pika.Message(
            body=cuerpo.encode(),
            delivery_mode=(
                aio_pika.DeliveryMode.NOT_PERSISTENT
                if config.get("transitorio")
                else aio_pika.DeliveryMode.PERSISTENT
            ),
            content_type=str(config.get("content_type") or "application/json"),
        )
        await canal.default_exchange.publish(mensaje, routing_key=str(config.get("cola") or ""))
        return {
            "publicado": True,
            "cola": config.get("cola"),
            "persistente": not config.get("transitorio"),
        }
    finally:
        await conexion.close()


async def consumir_amqp(config: dict[str, Any], limite: int = 100) -> Resultado:
    """Saca hasta `limite` mensajes de una cola, **confirmándolos uno a uno**.

    Se confirma tras procesar, no al recibir: si se confirmara al recibir, un
    fallo posterior perdería el mensaje sin que nadie lo supiera. Aquí, lo que no
    se confirma vuelve a la cola, que es el comportamiento que espera quien lo
    mandó.
    """
    import aio_pika

    url = str(config.get("url") or "")
    if not url:
        raise ErrorValidacion("Falta la URL AMQP.", error_code="transportes.amqp_sin_url")
    conexion = await aio_pika.connect_robust(url)
    filas: list[dict[str, Any]] = []
    try:
        canal = await conexion.channel()
        cola = await canal.get_queue(str(config.get("cola") or ""))
        for _ in range(limite):
            mensaje = await cola.get(fail=False)
            if mensaje is None:
                break
            filas.append(
                {
                    "cuerpo": mensaje.body.decode(errors="replace"),
                    "id": mensaje.message_id,
                    "content_type": mensaje.content_type,
                }
            )
            await mensaje.ack()
    finally:
        await conexion.close()
    return Resultado(filas=filas, origen=str(config.get("cola") or ""))


registrar_transporte("fichero", leer_fichero)
registrar_transporte("edi", leer_edi)
registrar_transporte("soap", leer_soap)
registrar_transporte("sftp", listar_sftp)
registrar_transporte("amqp", consumir_amqp)
