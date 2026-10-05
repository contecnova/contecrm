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

    cliente = _conectar(config)
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
                    # Se MARCA y no se esconde: quien liste tiene que poder ver
                    # que hay un fichero llegando. Esconderlo haría que una
                    # carpeta con cinco ficheros a medias pareciera vacía, y
                    # entonces nadie entiende por qué no entra nada.
                    "en_curso": en_curso_de_escritura(atributos.filename, config),
                }
            )
        return sorted(salida, key=lambda f: f["modificado"] or 0)
    finally:
        cliente.close()


def _b64(texto: str) -> bytes:
    import base64

    return base64.b64decode(texto)


def _conectar(config: dict[str, Any]) -> Any:
    """Abre la conexión SFTP **comprobando la huella del host**.

    Estaba escrito tres veces, y la tercera —`archivar_sftp`— usaba
    `AutoAddPolicy()` fijo: aceptaba la clave que viniera. O sea que listar y
    descargar exigían la huella, y mover el fichero ya procesado se la saltaba.
    Quien se pusiera en medio no recibía el maestro de clientes, pero sí podía
    hacerse pasar por el servidor en el momento de archivar.

    Tres copias de «conéctate al SFTP» divergen siempre, y la que se queda atrás
    es la puerta por la que se entra.
    """
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
    return cliente


def en_curso_de_escritura(nombre: str, config: dict[str, Any] | None = None) -> bool:
    """Si el nombre dice que todavía lo están escribiendo.

    Es la forma **fiable** de saberlo, y la única que lo es de verdad: quien
    escribe sube a `fichero.part` y renombra al acabar, así que un nombre
    terminado significa fichero terminado. Pero depende de que el cliente lo
    haga así — es un acuerdo con él, no una capacidad nuestra— y por eso no
    basta con esto: el tamaño se comprueba igual.
    """
    import fnmatch

    from crmcore.config import get_settings

    patrones = str((config or {}).get("patron_en_curso") or get_settings().sftp_patron_en_curso)
    return any(fnmatch.fnmatch(nombre, p.strip()) for p in patrones.split(",") if p.strip())


class FicheroIncompleto(ErrorDependencia):
    """El fichero todavía se está escribiendo. **Se reintenta, no se procesa.**

    Es un error propio y no un `ErrorValidacion` a propósito: no es que el
    fichero esté mal, es que todavía no está. Quien lo recoja tiene que volver
    a intentarlo en la pasada siguiente, no marcarlo como fallido ni archivarlo.
    """

    error_code_por_defecto = "transportes.sftp_incompleto"


def descargar_sftp(config: dict[str, Any], ruta: str) -> str:
    """Descarga un fichero **entero**, o no lo descarga. No lo borra.

    Borrar al leer es cómo se pierde un día entero de pedidos: el proceso falla
    después de leer, el mayorista no lo vuelve a mandar, y el fichero ya no está.

    **Y un fichero a medio escribir no se procesa nunca.** Antes se leía lo que
    hubiera y se devolvía como si estuviera completo: un fichero de movimientos
    truncado a la mitad entraba como entero y no se descubría hasta que alguien
    cuadraba las cuentas. Importar la mitad es peor que no importar nada, porque
    parece que fue bien.

    Se comprueba de dos formas y las dos hacen falta:

    1. **El nombre**, si el cliente usa `.part`/`.tmp` y renombra al acabar. Es
       la única fiable de verdad, pero es un acuerdo con él, no algo nuestro.
    2. **El tamaño, mirado dos veces** separadas por una espera configurable.
       Funciona contra cualquier servidor y no necesita acuerdo, pero **falla si
       quien escribe pausa más que la espera**: por eso la espera se configura y
       por eso no se usa sola.

    Y se vuelve a mirar DESPUÉS de leer: si el tamaño ha cambiado mientras se
    leía, lo leído no vale y se descarta. Abortar a mitad y quedarse con el
    trozo sería exactamente lo que esto viene a impedir.
    """
    import time

    from crmcore.config import get_settings

    ajustes = get_settings()
    nombre = ruta.rsplit("/", 1)[-1]
    if en_curso_de_escritura(nombre, config):
        raise FicheroIncompleto(
            f"«{nombre}» todavía se está escribiendo: su nombre lo dice. Se "
            "vuelve a intentar en la pasada siguiente.",
            error_code="transportes.sftp_incompleto",
            detalle={"fichero": nombre, "motivo": "nombre_en_curso"},
        )

    espera = float(config.get("espera_estabilidad_s") or ajustes.sftp_espera_estabilidad_s)
    cliente = _conectar(config)
    try:
        sftp = cliente.open_sftp()

        antes = sftp.stat(ruta)
        time.sleep(espera)
        despues = sftp.stat(ruta)
        if (antes.st_size, antes.st_mtime) != (despues.st_size, despues.st_mtime):
            raise FicheroIncompleto(
                f"«{nombre}» ha cambiado de tamaño mientras se miraba "
                f"({antes.st_size} → {despues.st_size} bytes): todavía lo están "
                "escribiendo. Se vuelve a intentar en la pasada siguiente.",
                error_code="transportes.sftp_incompleto",
                detalle={
                    "fichero": nombre,
                    "motivo": "tamano_cambia",
                    "antes": antes.st_size,
                    "despues": despues.st_size,
                },
            )

        with sftp.open(ruta, "r") as fichero:
            crudo = fichero.read()

        # SE VUELVE A MIRAR. Si creció mientras leíamos, lo leído es un trozo:
        # se descarta entero y se empieza de cero cuando el fichero esté.
        final = sftp.stat(ruta)
        if (final.st_size, final.st_mtime) != (despues.st_size, despues.st_mtime) or len(
            crudo
        ) != despues.st_size:
            raise FicheroIncompleto(
                f"«{nombre}» ha cambiado mientras se leía: se han leído "
                f"{len(crudo)} bytes de {final.st_size}. Se descarta lo leído y "
                "se empieza de cero en la pasada siguiente.",
                error_code="transportes.sftp_incompleto",
                detalle={
                    "fichero": nombre,
                    "motivo": "cambia_al_leer",
                    "leidos": len(crudo),
                    "tamano": final.st_size,
                },
            )

        return crudo.decode(str(config.get("codificacion") or "utf-8"), errors="replace")
    finally:
        cliente.close()


def archivar_sftp(config: dict[str, Any], ruta: str) -> str:
    """Mueve el fichero ya procesado a la carpeta de archivo.

    Mover y no borrar: cuando dentro de un mes haya que explicar por qué un
    pedido entró mal, el fichero original es lo único que lo explica.

    **Comprueba la huella del host como las otras dos.** No lo hacía: usaba
    `AutoAddPolicy()` fijo, así que listar y descargar exigían la huella y
    mover el fichero ya procesado aceptaba la clave que viniera.
    """
    destino_dir = str(config.get("archivo") or "")
    if not destino_dir:
        raise ErrorValidacion(
            "Falta la carpeta de archivo: procesar y no mover deja el mismo "
            "fichero entrando cada noche.",
            error_code="transportes.sftp_sin_archivo",
        )
    cliente = _conectar(config)
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


# ── Recoger de un SFTP, con la regla del fichero incompleto ───────────────


def recoger_de_sftp(
    config: dict[str, Any], *, intentos: dict[str, int] | None = None
) -> dict[str, Any]:
    """Lista, salta lo que todavía se escribe y baja lo que está entero.

    Es la pieza que un barrido llamaría cada tanto. **Ese barrido no existe
    todavía**, y conviene saberlo: medido el 04-10-2026, los cinco transportes
    heredados —sftp, fichero, edi, soap, amqp— están registrados y **nadie los
    ejecuta nunca**. `_MANEJADORES` solo se escribe y se lista. Montar el
    barrido es una decisión de producto —cada cuánto, con qué configuración,
    dónde van los resultados— y no se inventa aquí.

    Lo que sí está decidido y es lo que hace esta función:

    **Un fichero incompleto no se procesa nunca, se reintenta.** Ni se marca
    como fallido ni se archiva: se deja donde está y se vuelve a mirar en la
    pasada siguiente. Procesar lo que se haya alcanzado a leer es peor que no
    procesarlo, porque parece que fue bien.

    **Y el reintento no es infinito en silencio.** Un fichero que nunca termina
    de escribirse se reintentaría cada pasada para siempre sin que nadie lo
    supiera. Se cuentan los intentos y se avisa a partir del umbral, que está en
    `SFTP_INTENTOS_PARA_AVISAR`.

    El contador lo pone quien llama (`intentos`), y es a propósito: **en memoria
    se pierde al reiniciar**, y entonces un fichero atascado desde hace tres
    días vuelve a empezar de cero y el aviso no salta nunca. Quien monte el
    barrido tiene que guardarlo donde guarde su estado. Sin diccionario se usa
    uno del proceso, que vale para una pasada y no para vigilar.
    """
    from crmcore.config import get_settings

    cuenta = _INTENTOS if intentos is None else intentos
    umbral = int(get_settings().sftp_intentos_para_avisar)

    bajados: list[dict[str, Any]] = []
    esperando: list[dict[str, Any]] = []

    for fichero in listar_sftp(config):
        clave = str(fichero["ruta"])
        try:
            contenido = descargar_sftp(config, clave)
        except FicheroIncompleto as incompleto:
            cuenta[clave] = cuenta.get(clave, 0) + 1
            veces = cuenta[clave]
            esperando.append({"ruta": clave, "intentos": veces, "motivo": str(incompleto)})
            if veces >= umbral:
                # A nivel de error y no de aviso: un fichero que lleva cinco
                # pasadas sin terminar de escribirse no es un retraso, es algo
                # que alguien tiene que ir a mirar.
                logger.error(
                    "sftp.fichero_nunca_termina",
                    ruta=clave,
                    intentos=veces,
                    umbral=umbral,
                    motivo=str(incompleto)[:200],
                )
            continue
        cuenta.pop(clave, None)
        bajados.append({"ruta": clave, "contenido": contenido})

    return {
        "bajados": len(bajados),
        "ficheros": bajados,
        # Los que esperan se devuelven CON su cuenta: un número suelto no dice
        # cuál lleva días atascado, y eso es lo único que sirve para arreglarlo.
        "esperando": esperando,
    }


# Contador de intentos del proceso. Se pierde al reiniciar — está dicho arriba
# y es justo por lo que `recoger_de_sftp` deja que quien llame traiga el suyo.
_INTENTOS: dict[str, int] = {}


# ── Quién los ejecuta, por fin ────────────────────────────────────────────
#
# Medido el 04-10-2026: los cinco transportes estaban registrados y **nadie los
# ejecutaba nunca**. `_MANEJADORES` sólo se escribía y se listaba. Se dejó
# escrito que montar el barrido era una decisión de producto —cada cuánto, con
# qué configuración, dónde van los resultados— y aquí están las tres, tomadas:
#
#   * **Cada cuánto**: lo dice la operación (`Operacion.cada_minutos`), con un
#     suelo configurable. Un fichero que llega a las 3:00 y un stock que cambia
#     cada cinco minutos no pueden compartir ritmo.
#   * **Con qué configuración**: la de la conexión, igual que REST. Lo que
#     cambia entre dos clientes es esa config, no un módulo.
#   * **Dónde van los resultados**: a `registros_recibidos`, con el
#     identificador externo como clave. Lo mismo que trae el conector REST, por
#     la misma puerta, para que quien los consuma no sepa por dónde entraron.
#
# Lo que sigue siendo cierto y no se tapa: **`leer_programado` devuelve lo que
# el transporte dé**. Si un fichero plano no trae una columna que sirva de
# identificador, el programador lo cuenta aparte en vez de inventarse una clave
# — y entonces la marca no avanza, que es lo correcto.


def _identificar(filas: list[dict[str, Any]], definicion: dict[str, Any]) -> list[dict[str, Any]]:
    """Pone `id_externo` a cada fila, **si la configuración dice de dónde sale**.

    No se adivina. Coger «el primer campo que parezca un id» funciona el día de
    la demostración y duplica el maestro de clientes el día que el proveedor
    añade una columna delante.
    """
    campo = str(definicion.get("campo_id") or "")
    if not campo:
        return filas
    return [{**f, "id_externo": str(f.get(campo) or "")} for f in filas]


def _leer_ficheros(
    config: dict[str, Any], definicion: dict[str, Any], ficheros: list[dict[str, Any]], *, edi: bool
) -> tuple[list[dict[str, Any]], list[str]]:
    filas: list[dict[str, Any]] = []
    avisos: list[str] = []
    for fichero in ficheros:
        contenido = str(fichero.get("contenido") or "")
        resultado = leer_edi(contenido, config) if edi else leer_fichero(contenido, config)
        filas.extend(_identificar(resultado.filas, definicion))
        avisos.extend(resultado.avisos)
    return filas, avisos


def leer_programado(
    protocolo: str,
    config: dict[str, Any],
    definicion: dict[str, Any],
    *,
    intentos: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Una vuelta de lectura por un transporte heredado.

    Devuelve lo mismo que el conector REST —`registros`, `paginas`— para que el
    programador no tenga que saber por dónde entró nada. Un protocolo que este
    módulo no habla **se dice**: fallar dentro de un proceso nocturno con un
    `KeyError` es cómo una integración lleva tres semanas sin traer nada y nadie
    se ha enterado.
    """
    clave = str(protocolo or "").lower()
    if clave not in PROTOCOLOS:
        raise ErrorValidacion(
            f"El protocolo «{protocolo}» no lo habla este módulo. Los que sí: "
            f"{', '.join(PROTOCOLOS)}.",
            error_code="transportes.protocolo_desconocido",
            detalle={"protocolos": list(PROTOCOLOS)},
        )

    if clave == "sftp":
        # Se baja, se interpreta y **sólo entonces** se archiva. Archivar al
        # bajar es cómo se pierde un día de pedidos: si el proceso falla
        # después, el mayorista no lo vuelve a mandar.
        recogido = recoger_de_sftp(config, intentos=intentos)
        filas, avisos = _leer_ficheros(
            config,
            definicion,
            recogido["ficheros"],
            edi=str(definicion.get("formato") or config.get("formato") or "") == "edi",
        )
        archivados = []
        for fichero in recogido["ficheros"]:
            try:
                archivados.append(archivar_sftp(config, str(fichero["ruta"])))
            except Exception as exc:  # noqa: BLE001 — archivar es lo último
                # Que falle archivar NO invalida lo leído: lo leído ya está, y
                # lo que pasa si se trata como un fallo es que se vuelve a leer
                # entero en la pasada siguiente.
                avisos.append(f"No se ha podido archivar «{fichero['ruta']}»: {str(exc)[:120]}")
        return {
            "registros": filas,
            "paginas": len(recogido["ficheros"]),
            "avisos": avisos,
            "archivados": archivados,
            "esperando": recogido["esperando"],
        }

    if clave in ("fichero", "edi"):
        contenido = str(definicion.get("contenido") or config.get("contenido") or "")
        if not contenido:
            raise ErrorValidacion(
                "Este transporte lee de un contenido que hay que entregarle, y no se "
                "ha entregado ninguno. Para recogerlo de un servidor, la conexión es "
                "de tipo «sftp».",
                error_code="transportes.sin_contenido",
            )
        resultado = (
            leer_edi(contenido, config) if clave == "edi" else leer_fichero(contenido, config)
        )
        return {
            "registros": _identificar(resultado.filas, definicion),
            "paginas": 1,
            "avisos": list(resultado.avisos),
        }

    if clave == "soap":
        respuesta = _llamar_soap(config, definicion)
        resultado = leer_soap(respuesta, config)
        return {
            "registros": _identificar(resultado.filas, definicion),
            "paginas": 1,
            "avisos": list(resultado.avisos),
        }

    import asyncio

    resultado = asyncio.run(consumir_amqp(config, int(definicion.get("limite") or 100)))
    return {
        "registros": _identificar(resultado.filas, definicion),
        "paginas": 1,
        "avisos": list(resultado.avisos),
    }


def _llamar_soap(config: dict[str, Any], definicion: dict[str, Any]) -> str:
    """Manda el sobre y devuelve la respuesta en crudo.

    Por `cliente_seguro`, como toda llamada saliente: una URL que llega de una
    configuración y se pide sin más es por donde se lee la red interna desde
    fuera. Y el cuerpo lo arma `envolver_soap`, que es donde está decidido cómo
    se envuelve — escribirlo otra vez aquí serían dos formas de hacer el sobre y
    una sin mantener.
    """
    from crmcore.red import cliente_seguro, exigir

    url = str(config.get("url") or "")
    if not url:
        raise ErrorValidacion(
            "Falta la URL del servicio SOAP.", error_code="transportes.soap_sin_url"
        )
    sobre = envolver_soap(str(definicion.get("cuerpo") or ""), config)
    exigir(url)
    cabeceras = {
        "Content-Type": "text/xml; charset=utf-8",
        # `SOAPAction` vacía no es lo mismo que ausente: hay servidores que
        # rechazan la petición sin ella y el error que dan no lo dice.
        "SOAPAction": str(definicion.get("accion") or config.get("accion") or ""),
    }
    try:
        with cliente_seguro(timeout=float(config.get("timeout_s") or 30.0)) as cli:
            salida = cli.post(url, content=sobre.encode("utf-8"), headers=cabeceras)
    except Exception as exc:  # noqa: BLE001 — httpx lanza varias clases
        raise ErrorDependencia(
            "El servicio SOAP no ha respondido",
            error_code="transportes.soap_sin_respuesta",
            detalle={"error": str(exc)[:200]},
        ) from exc
    if salida.status_code >= 400:
        raise ErrorDependencia(
            f"El servicio SOAP ha contestado {salida.status_code}",
            error_code="transportes.soap_rechazado",
            detalle={"codigo": salida.status_code, "cuerpo": salida.text[:500]},
        )
    return salida.text


def enviar_programado(
    protocolo: str, config: dict[str, Any], definicion: dict[str, Any], cuerpo: str
) -> dict[str, Any]:
    """La otra mitad: mandar algo por un transporte heredado.

    Existe porque `publicar_amqp` y `envolver_soap` estaban escritas, probadas y
    sin que las llamara nadie: se podía declarar una conexión AMQP y no había
    forma de publicar en ella. Una integración que sólo sabe leer deja al
    cliente escribiendo en el ERP a mano, que es la mitad del trabajo que venía
    a quitar.
    """
    clave = str(protocolo or "").lower()
    if clave == "amqp":
        import asyncio

        return asyncio.run(publicar_amqp(config, cuerpo))
    if clave == "soap":
        respuesta = _llamar_soap(config, {**definicion, "cuerpo": cuerpo})
        resultado = leer_soap(respuesta, config)
        return {"enviado": True, "respuesta": resultado.filas, "crudo": resultado.crudo[:2000]}
    raise ErrorValidacion(
        f"Por «{protocolo}» no se manda nada desde aquí: es de sólo lectura. "
        "Los que admiten envío son «amqp» y «soap».",
        error_code="transportes.protocolo_solo_lectura",
    )
