"""Operar las suites: disponibilidad, chat, import/export, reglas, límites,
salud, baja, identidad y diagnóstico (CRM-06.01.03.11 a .17, .19 y .20).

Lo anterior era conectar. Esto es lo que decide si la integración sigue viva a
los seis meses, y casi todo son cosas que no fallan: **se degradan en silencio**.
Una suscripción que caduca, un proveedor que corta la cuota, un buzón que lleva
una semana sin credencial. Nada de eso da un error rojo en ningún sitio: el CRM
se queda quieto y la gente deja de fiarse sin saber muy bien por qué.

Las decisiones:

**Un calendario que no se puede leer no está libre.** Es el error clásico de las
herramientas de agenda: si no se sabe, se propone la hora igualmente, y se cita a
alguien encima de la reunión que ya tenía.

**La regla del usuario solo puede estrechar la del tenant, nunca ensancharla.**
Si pudiera ensancharla, la política de la empresa sería una sugerencia.

**Cuando el proveedor corta, se le hace caso.** Reintentar a ciegas contra una
cuota agotada es lo que hace que el proveedor bloquee la aplicación entera — a
todos los clientes, no solo al que se pasó.

**Lo que no se ha medido no está en verde.** Un panel que solo cuenta lo
sincronizado enseña un número que sube mientras tres buzones llevan una semana
parados.

**Y al darse de baja, las actividades se quedan y la copia de su agenda se va.**
Las primeras son el registro de la empresa y las segundas eran suyas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Formatos de salida que no dependen de ninguna suite. Es la puerta de salida: un
# CRM cuyos datos solo pueden salir por la API de un fabricante tiene al cliente
# atado, y eso se nota el día que quiere irse — que es cuando ya no hay tiempo de
# construir nada.
FORMATOS = {
    "eml": "Un correo con sus cabeceras, tal y como lo entiende cualquier cliente",
    "mbox": "Varios correos en un fichero, para archivar",
    "vcard": "Contactos (vCard 4.0)",
    "icalendar": "Citas y tareas (iCalendar)",
    "csv": "Tabular, para una hoja de cálculo",
}

# Lo que NUNCA entra, diga lo que diga la regla. Que sea una lista aparte y no una
# opción es el punto: una casilla que se puede desmarcar acaba desmarcada.
NUNCA_ENTRA = (
    "marcado_privado",
    "carpeta_personal",
    "borrador",
)

# Códigos del proveedor que NO se reintentan. Reintentar un 403 es gastar cuota
# para que vuelva a decir que no, y de paso parecer un ataque.
NO_SE_REINTENTA = (400, 401, 403, 404, 422)

# Cuánto se espera si el proveedor corta y no dice cuánto. Es una espera de
# cortesía: la buena es la que él indique.
ESPERA_POR_DEFECTO_S = 60


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ── Disponibilidad real (CRM-06.01.03.11) ─────────────────────────────────


def huecos_libres(
    *,
    ocupado: list[dict[str, Any]],
    desde: datetime,
    hasta: datetime,
    minutos: int,
    calendario_legible: bool = True,
    jornada: tuple[int, int] = (9, 18),
) -> dict[str, Any]:
    """Cuándo está libre de verdad, leyendo su calendario.

    **Si el calendario no se puede leer, no se propone nada.** Es el error
    clásico de las herramientas de agenda: no se sabe, y se propone igualmente
    «porque no consta nada» — y se cita a alguien encima de la reunión que ya
    tenía. Preferir la respuesta incómoda («no puedo ver su agenda») a la
    cómoda y falsa es todo el valor de esto.

    Del calendario ajeno se lee **que está ocupado, no de qué**: el asunto de una
    cita puede ser «revisión médica», y para proponer una hora no hace ninguna
    falta.
    """
    if not calendario_legible:
        return {
            "fiable": False,
            "huecos": [],
            "porque": (
                "No se ha podido leer el calendario. No se proponen horas «porque no "
                "consta nada»: así es como se cita a alguien encima de la reunión que "
                "ya tenía."
            ),
            "que_hacer": "Proponer horas a mano, o pedirle a la persona que reconecte.",
        }
    if minutos <= 0:
        raise ErrorValidacion(
            "Una reunión de cero minutos no es una reunión", error_code="suite.duracion_invalida"
        )

    tramos = sorted(
        ((o["inicio"], o["fin"]) for o in ocupado if o.get("inicio") and o.get("fin")),
        key=lambda t: t[0],
    )
    huecos: list[dict[str, str]] = []
    cursor = desde
    for inicio, fin in [*tramos, (hasta, hasta)]:
        if inicio > cursor and (inicio - cursor) >= timedelta(minutes=minutos):
            if jornada[0] <= cursor.hour < jornada[1]:
                huecos.append({"inicio": cursor.isoformat(), "fin": inicio.isoformat()})
        cursor = max(cursor, fin)
        if cursor >= hasta:
            break

    return {
        "fiable": True,
        "huecos": huecos,
        "lo_que_se_lee": "solo si está ocupado, no de qué",
        "porque": (
            "El asunto de una cita puede ser «revisión médica», y para proponer una "
            "hora no hace ninguna falta."
        ),
        "aviso": (
            ""
            if huecos
            else "No hay ningún hueco en ese tramo. Eso es un dato, no un fallo: "
            "conviene decírselo a quien lo pidió en vez de enseñar una lista vacía."
        ),
    }


# ── Chat vinculado (CRM-06.01.03.12) ──────────────────────────────────────


def vincular_conversacion(
    *,
    objeto: str,
    objeto_id: UUID,
    proveedor: str,
    referencia: str,
    exportable: bool,
    resumen: str = "",
) -> dict[str, Any]:
    """Enlaza un hilo de chat a un registro, **por referencia**.

    Un hilo de chat corporativo tiene de todo: la negociación, el precio y el
    comentario que alguien hizo sobre un compañero. Copiarlo al CRM mete todo eso
    en un sitio donde lo ve gente que no estaba en la conversación — y donde se
    queda para siempre, aunque en el chat se borre.

    Se guarda el enlace y, como mucho, un **resumen escrito por una persona**. Lo
    que el canal no deja exportar tampoco se intenta reconstruir: un hilo
    recuperado a trozos da una versión incompleta que parece completa.
    """
    if not referencia.strip():
        raise ErrorValidacion(
            "Un hilo vinculado sin referencia es un enlace roto",
            error_code="suite.chat_sin_referencia",
        )
    return {
        "objeto": objeto,
        "objeto_id": str(objeto_id),
        "proveedor": proveedor,
        "referencia": referencia.strip(),
        "resumen": resumen.strip()[:2000],
        "contenido_en_el_crm": False,
        "exportable_por_el_canal": exportable,
        "aviso": (
            ""
            if exportable
            else "Este canal no deja exportar el hilo. No se reconstruye a trozos: una "
            "conversación incompleta que parece completa es peor que un enlace."
        ),
        "quien_lo_ve": (
            "Quien tenga acceso al hilo en el proveedor. El CRM no da acceso a una "
            "conversación en la que no estabas."
        ),
    }


# ── Importar y exportar en formatos estándar (CRM-06.01.03.13) ────────────


def preparar_exportacion(
    *, formato: str, objetos: list[str], incluye_referencias: list[str] | None = None
) -> dict[str, Any]:
    """Prepara una salida en formato estándar, **sin pasar por ninguna suite**.

    Es la puerta de salida. Un CRM cuyos datos solo pueden salir por la API de un
    fabricante tiene al cliente atado, y eso se descubre el día que quiere irse —
    cuando ya no hay tiempo de construir nada.

    Y el paquete dice **qué NO lleva dentro**. Las notas y los ficheros están
    enlazados, no copiados: exportarlos sería copiarlos, que es justo lo que no se
    hace. Sin esa lista, el cliente cree que se lo lleva todo y descubre el hueco
    cuando ya ha apagado lo otro.
    """
    if formato not in FORMATOS:
        raise ErrorValidacion(
            f"Formato «{formato}» desconocido",
            error_code="suite.formato_desconocido",
            detalle={"formatos": {k: v for k, v in FORMATOS.items()}},
        )
    return {
        "formato": formato,
        "que_es": FORMATOS[formato],
        "objetos": sorted(set(objetos)),
        "sin_intermediarios": True,
        "no_lleva_dentro": [
            {
                "que": referencia,
                "porque": (
                    "está enlazado y no copiado; el fichero vive en el almacenamiento "
                    "del cliente y ahí se queda"
                ),
            }
            for referencia in sorted(set(incluye_referencias or []))
        ],
        "porque": (
            "Un CRM cuyos datos solo salen por la API de un fabricante tiene al cliente "
            "atado. Esta salida no necesita que ninguna suite esté conectada."
        ),
    }


def comprobar_importacion(*, formato: str, filas: list[dict[str, Any]]) -> dict[str, Any]:
    """Qué entraría y qué no de un fichero estándar, **antes** de importarlo.

    Se enseña primero y se importa después. Una importación que se ejecuta y
    luego cuenta lo que hizo obliga a deshacer a mano lo que no debía entrar, y
    deshacer a mano una importación de diez mil filas no lo hace nadie: se queda.
    """
    if formato not in FORMATOS:
        raise ErrorValidacion(
            f"Formato «{formato}» desconocido", error_code="suite.formato_desconocido"
        )
    sin_identificador = [i for i, f in enumerate(filas) if not f.get("id_externo")]
    vacias = [
        i for i, f in enumerate(filas) if not any(v for k, v in f.items() if k != "id_externo")
    ]
    return {
        "filas": len(filas),
        "entrarian": len(filas) - len(sin_identificador) - len(vacias),
        "sin_identificador": len(sin_identificador),
        "vacias": len(vacias),
        "porque_hace_falta_identificador": (
            "Sin él, reimportar el mismo fichero duplica todo. Y el mismo fichero se "
            "reimporta siempre: es lo primero que hace cualquiera cuando algo sale mal."
        ),
        "se_importa_ya": False,
        "que_hacer": "Revisar estos números y confirmar. Deshacer a mano no lo hace nadie.",
    }


# ── Reglas de qué entra (CRM-06.01.03.14) ─────────────────────────────────


def combinar_reglas(
    *, del_tenant: dict[str, Any], del_usuario: dict[str, Any] | None
) -> dict[str, Any]:
    """Junta la política de la empresa con la preferencia de la persona.

    **La del usuario solo puede estrechar, nunca ensanchar.** Si pudiera
    ensancharla, la política de la empresa sería una sugerencia: bastaría con que
    una persona marcara «traerlo todo» para que entrara todo su buzón, que es
    precisamente lo que el tenant había decidido que no.

    Y lo que nunca entra no entra: privados, carpetas personales y borradores. No
    es una casilla, porque una casilla acaba desmarcada.
    """
    criterio_tenant = str(del_tenant.get("criterio") or "con_contacto_del_crm")
    recursos_tenant = set(del_tenant.get("recursos") or [])
    usuario = dict(del_usuario or {})

    amplitud = {
        "marcado_por_el_usuario": 0,
        "con_externos": 1,
        "con_contacto_del_crm": 1,
        "todo": 2,
    }
    criterio_usuario = str(usuario.get("criterio") or criterio_tenant)
    ignorado = ""
    if amplitud.get(criterio_usuario, 9) > amplitud.get(criterio_tenant, 0):
        ignorado = (
            f"La persona pidió «{criterio_usuario}» y el tenant permite como mucho "
            f"«{criterio_tenant}». Se queda el del tenant: si la preferencia personal "
            "pudiera ensanchar la política, la política sería una sugerencia."
        )
        criterio_usuario = criterio_tenant

    recursos_usuario = set(usuario.get("recursos") or recursos_tenant)
    fuera = sorted(recursos_usuario - recursos_tenant)

    return {
        "criterio": criterio_usuario,
        "recursos": sorted(recursos_usuario & recursos_tenant),
        "nunca_entra": list(NUNCA_ENTRA),
        "ignorado_del_usuario": ignorado,
        "recursos_pedidos_que_no_permite_el_tenant": fuera,
        "porque": ("La preferencia personal estrecha la política de la empresa; nunca la abre."),
    }


def entra(*, elemento: dict[str, Any], reglas: dict[str, Any]) -> tuple[bool, str]:
    """Si un elemento concreto entra, y **por qué no** cuando no entra.

    El motivo importa: sin él, el usuario ve que «no se sincroniza nada» y no
    sabe si es que no hay nada o que la regla lo deja fuera.
    """
    for marca in NUNCA_ENTRA:
        if elemento.get(marca):
            return False, (
                f"Está marcado como «{marca}». Eso no entra nunca, diga lo que diga la "
                "configuración: no es una casilla, porque una casilla acaba desmarcada."
            )
    if elemento.get("recurso") and elemento["recurso"] not in (reglas.get("recursos") or []):
        return False, f"El recurso «{elemento['recurso']}» no está autorizado en este tenant."
    return True, "Cumple el criterio configurado."


# ── Límites del proveedor (CRM-06.01.03.15) ───────────────────────────────


def como_reintentar(
    *, codigo: int, cabecera_reintento: str | int | None, intento: int
) -> dict[str, Any]:
    """Qué hacer cuando el proveedor contesta mal.

    **Se le hace caso a lo que él diga.** Si manda `Retry-After`, se espera eso:
    reintentar antes gasta cuota para que vuelva a decir que no, y de paso parece
    un ataque — y lo que hace un proveedor entonces es bloquear la aplicación
    entera, a todos los clientes, no solo al que se pasó.

    Y hay errores que **no se reintentan nunca**. Un 403 no se arregla
    insistiendo: falta un permiso, y lo que hay que hacer es decirlo.
    """
    if codigo in NO_SE_REINTENTA:
        return {
            "reintentar": False,
            "porque": (
                f"Un {codigo} no se arregla insistiendo: es un permiso que falta, una "
                "credencial mala o algo que ya no existe. Reintentar gasta cuota para "
                "que vuelva a decir que no."
            ),
            "que_hacer": "Enseñarlo en el panel con el diagnóstico, no en un log.",
        }
    if codigo == 429 or codigo >= 500:
        if cabecera_reintento:
            try:
                espera = max(1, int(str(cabecera_reintento).strip()))
                dicho_por_el = True
            except ValueError:
                espera, dicho_por_el = ESPERA_POR_DEFECTO_S, False
        else:
            # Exponencial y acotada. Sin tope, el sexto intento espera una hora y
            # el usuario cree que la integración está muerta.
            espera, dicho_por_el = (
                min(ESPERA_POR_DEFECTO_S * (2 ** max(0, intento - 1)), 900),
                False,
            )
        return {
            "reintentar": True,
            "esperar_s": espera,
            "lo_dice_el_proveedor": dicho_por_el,
            "porque": (
                "El proveedor ha dicho cuánto esperar y se le hace caso: reintentar "
                "antes es lo que hace que bloquee la aplicación entera."
                if dicho_por_el
                else "No ha dicho cuánto, así que se espera con margen creciente y con "
                "tope: sin tope, el sexto intento espera una hora y parece muerto."
            ),
        }
    return {
        "reintentar": False,
        "porque": f"Respuesta {codigo} no prevista: se para y se mira, en vez de insistir.",
    }


def ritmo_de_primera_carga(*, elementos: int, peticiones_por_minuto: int | None) -> dict[str, Any]:
    """A qué ritmo se trae la primera carga de un buzón.

    La primera sincronización de alguien con quince años de correo se come la
    cuota **del tenant entero**, y entonces el proveedor corta a todos los demás
    usuarios. Se reparte: tarda más y no deja a nadie sin servicio.
    """
    if not peticiones_por_minuto:
        return {
            "acotado": False,
            "aviso": (
                "El perfil no declara el límite del proveedor, así que no se puede "
                "repartir. La primera carga grande puede comerse la cuota del tenant "
                "entero y dejar sin sincronizar a todos los demás."
            ),
        }
    # Se deja la mitad libre a propósito: la otra mitad es para la operación
    # normal de los demás usuarios, que no tienen por qué pararse porque alguien
    # acabe de conectar su buzón.
    ritmo = max(1, peticiones_por_minuto // 2)
    minutos = max(1, round(elementos / max(1, ritmo)))
    return {
        "acotado": True,
        "peticiones_por_minuto": ritmo,
        "minutos_estimados": minutos,
        "porque": (
            "Se usa la mitad de la cuota y se deja la otra mitad para los demás: el "
            "que acaba de conectar su buzón no puede parar al resto."
        ),
    }


# ── Panel de salud (CRM-06.01.03.16) ──────────────────────────────────────


def salud(
    *, conexiones: list[dict[str, Any]], ahora: datetime | None = None, horas_aviso: int = 24
) -> dict[str, Any]:
    """Qué lleva sin sincronizar, desde cuándo y por qué.

    **Lo que no se ha medido no está en verde.** Un panel que solo cuenta lo
    sincronizado enseña un número que sube mientras tres buzones llevan una
    semana parados: el número es verdad y la impresión es falsa.
    """
    momento = ahora or _ahora()
    paradas: list[dict[str, Any]] = []
    sin_medir: list[str] = []
    en_sondeo: list[str] = []

    for conexion in conexiones:
        clave = str(conexion.get("id") or conexion.get("recurso") or "?")
        ultima = conexion.get("sincronizado_at")
        if conexion.get("en_sondeo"):
            en_sondeo.append(clave)
        if not isinstance(ultima, datetime):
            sin_medir.append(clave)
            continue
        ultima = ultima if ultima.tzinfo else ultima.replace(tzinfo=timezone.utc)
        horas = (momento - ultima).total_seconds() / 3600
        if horas >= horas_aviso or conexion.get("estado") not in ("conectado", None):
            paradas.append(
                {
                    "conexion": clave,
                    "horas_sin_sincronizar": round(horas, 1),
                    "estado": conexion.get("estado"),
                    "porque": conexion.get("motivo")
                    or "Sin motivo anotado, que ya es un problema: nadie sabrá qué mirar.",
                }
            )

    return {
        "total": len(conexiones),
        "paradas": paradas,
        "sin_medir": sin_medir,
        "en_sondeo": en_sondeo,
        "todo_bien": not paradas and not sin_medir and bool(conexiones),
        "medible": bool(conexiones),
        "que_significa": (
            "No hay ninguna conexión: esto no está en verde, está sin usar."
            if not conexiones
            else f"{len(paradas)} conexiones paradas y {len(sin_medir)} sin medir. Las "
            "que no se han medido no cuentan como buenas: un panel que solo suma lo "
            "sincronizado enseña un número que sube mientras tres buzones llevan una "
            "semana quietos."
            if paradas or sin_medir
            else "Todas las conexiones han sincronizado dentro del plazo."
        ),
        "los_en_sondeo": (
            ""
            if not en_sondeo
            else f"{len(en_sondeo)} van por sondeo porque no se pudo renovar la "
            "suscripción: los cambios entran con retraso, no al instante."
        ),
    }


# ── Desconexión y baja (CRM-06.01.03.17) ──────────────────────────────────


def plan_de_baja(*, motivo: str, hay_buzon_compartido: bool = False) -> dict[str, Any]:
    """Qué se queda en el CRM y qué desaparece cuando alguien se va o revoca.

    La línea está clara y conviene escribirla antes de que haga falta: **las
    actividades se quedan y la copia de su agenda se va**. Las primeras son el
    registro de la empresa —quién habló con qué cliente y cuándo— y borrarlas
    dejaría a la compañía sin su propia historia comercial. La segunda era suya.

    Y **la suscripción se borra en el proveedor**, no solo aquí. Si se quita solo
    de este lado, el proveedor sigue mandando avisos de un buzón que ya nadie
    atiende — y sigue teniendo permiso para leerlo.
    """
    if motivo not in ("revocacion", "baja_del_usuario", "fin_del_contrato"):
        raise ErrorValidacion(
            f"Motivo de baja «{motivo}» desconocido", error_code="suite.baja_motivo_invalido"
        )
    return {
        "motivo": motivo,
        "se_queda": [
            {
                "que": "Las actividades registradas (correos, reuniones, llamadas)",
                "porque": (
                    "Son el registro de la empresa: quién habló con qué cliente y "
                    "cuándo. Borrarlas dejaría a la compañía sin su historia comercial."
                ),
            },
            {
                "que": "El rastro de que hubo un consentimiento y cuándo se revocó",
                "porque": "Es la prueba de que se hizo bien; borrarla es borrar la prueba.",
            },
        ],
        "se_borra": [
            {
                "que": "El token y el refresco, de la bóveda",
                "porque": "Un token vivo de alguien que se fue es un acceso que nadie vigila",
            },
            {
                "que": "La copia local de su agenda personal",
                "porque": "Era suya, y ya no hay motivo para tenerla",
            },
            {
                "que": "La marca de incremento",
                "porque": "No sirve para nada sin credencial, y confunde al que la lea",
            },
        ],
        "se_borra_en_el_proveedor": [
            {
                "que": "La suscripción a cambios",
                "porque": (
                    "Si solo se quita de este lado, el proveedor sigue mandando avisos "
                    "de un buzón que ya nadie atiende, y el CRM sigue teniendo permiso "
                    "para leerlo."
                ),
            }
        ],
        "aviso": (
            ""
            if not hay_buzon_compartido
            else "Esta persona tenía acceso a un buzón compartido. Darla de baja NO "
            "desconecta ese buzón: es del equipo, y desconectarlo dejaría al resto sin "
            "sincronizar sin que nadie lo hubiera pedido."
        ),
    }


# ── Identidad: alias y buzones compartidos (CRM-06.01.03.19) ──────────────


def resolver_cuenta(
    *, direccion_del_proveedor: str, usuarios: list[dict[str, Any]]
) -> dict[str, Any]:
    """A qué usuario del CRM corresponde una cuenta de la suite.

    Los **alias** son el fallo típico: la misma persona manda desde
    `j.perez@` y desde `juan.perez@`, y si cada uno se resuelve a un usuario
    distinto, la misma conversación aparece dos veces en la ficha atribuida a dos
    comerciales.

    Y un **buzón compartido no tiene dueño**: `info@` o `ventas@` es del equipo.
    Atribuirlo a quien lo conectó pone en su nombre correos que no escribió, y
    eso acaba en la comisión de alguien.
    """
    objetivo = direccion_del_proveedor.strip().lower()
    candidatos = [
        u
        for u in usuarios
        if objetivo == str(u.get("email") or "").strip().lower()
        or objetivo in {str(a).strip().lower() for a in (u.get("alias") or [])}
    ]
    compartido = next(
        (u for u in usuarios if objetivo in {str(a).lower() for a in (u.get("compartidos") or [])}),
        None,
    )

    if compartido is not None:
        return {
            "usuario_id": None,
            "es_compartido": True,
            "equipo": compartido.get("equipo"),
            "porque": (
                "Es un buzón compartido: no tiene dueño. Atribuirlo a quien lo conectó "
                "le pondría en su nombre correos que no escribió."
            ),
            "consentimiento": (
                "Lo da el responsable del buzón en nombre del equipo, y se anota así."
            ),
        }
    if not candidatos:
        return {
            "usuario_id": None,
            "es_compartido": False,
            "porque": (
                f"«{objetivo}» no corresponde a ningún usuario ni a ningún alias. No se "
                "adivina: adivinar aquí atribuye la conversación a quien no es."
            ),
        }
    if len({str(u.get("id")) for u in candidatos}) > 1:
        return {
            "usuario_id": None,
            "es_compartido": False,
            "ambiguo": True,
            "candidatos": [str(u.get("id")) for u in candidatos],
            "porque": (
                "Esa dirección está declarada en más de un usuario. Elegir uno haría "
                "que la misma conversación se atribuyera a dos comerciales distintos "
                "según el día."
            ),
        }
    return {"usuario_id": str(candidatos[0].get("id")), "es_compartido": False}


# ── Diagnóstico (CRM-06.01.03.20) ─────────────────────────────────────────


def diagnosticar(
    *,
    codigo: int | None,
    alcances_concedidos: list[str],
    alcances_necesarios: list[str],
    mensaje_del_proveedor: str = "",
) -> dict[str, Any]:
    """Qué falla exactamente, **no «error de autenticación»**.

    Ese mensaje es el que hace que una implantación se atasque una semana: el
    consultor no sabe si es la contraseña, el permiso, el inquilino o el reloj,
    así que lo prueba todo y acaba pidiendo permisos de administrador global
    «para descartar» — que es como una integración acaba con más permisos de los
    que necesita.
    """
    faltan = sorted(set(alcances_necesarios) - set(alcances_concedidos))
    if faltan:
        return {
            "ok": False,
            "que_pasa": "Faltan permisos concretos",
            "faltan_alcances": faltan,
            "que_hacer": (
                "Pedir exactamente estos alcances en la pantalla de consentimiento. No "
                "hace falta ninguno más: pedir de más «para descartar» es como una "
                "integración acaba con permisos que nadie puede justificar."
            ),
        }
    if codigo == 401:
        return {
            "ok": False,
            "que_pasa": "La credencial no vale",
            "que_hacer": (
                "El token ha caducado o se ha revocado desde el proveedor. La persona "
                "tiene que volver a autorizar; no es un problema de permisos."
            ),
        }
    if codigo == 403:
        return {
            "ok": False,
            "que_pasa": "La credencial vale pero el proveedor no deja hacer eso",
            "que_hacer": (
                "Normalmente es una política del inquilino del cliente —acceso "
                "condicional, aplicaciones aprobadas— y no algo que se arregle aquí. "
                "Hay que hablar con quien administre su suite."
            ),
            "mensaje_del_proveedor": mensaje_del_proveedor[:500],
        }
    if codigo == 429:
        return {
            "ok": False,
            "que_pasa": "El proveedor ha cortado por cuota",
            "que_hacer": "Esperar lo que él diga. No es un fallo de configuración.",
        }
    if codigo and codigo >= 500:
        return {
            "ok": False,
            "que_pasa": "El proveedor está caído o degradado",
            "que_hacer": "No hay nada que tocar de este lado. Se reintenta con margen.",
        }
    if codigo is None or codigo < 400:
        return {
            "ok": True,
            "que_pasa": "La conexión responde y los permisos están completos",
            "alcances": sorted(set(alcances_concedidos)),
        }
    return {
        "ok": False,
        "que_pasa": f"Respuesta {codigo} no prevista",
        "mensaje_del_proveedor": mensaje_del_proveedor[:500],
        "que_hacer": (
            "Se enseña tal cual lo que dijo el proveedor. Traducirlo a «error de "
            "autenticación» es lo que hace que una implantación se atasque una semana."
        ),
    }


def exigir_alcances(*, concedidos: list[str], necesarios: list[str]) -> None:
    """Se comprueba antes de llamar, no después de fallar.

    Llamar sin el permiso y esperar el 403 gasta una petición de la cuota del
    tenant para averiguar algo que ya se sabía.
    """
    faltan = sorted(set(necesarios) - set(concedidos))
    if faltan:
        raise Prohibido(
            f"Faltan alcances para esta operación: {', '.join(faltan)}",
            error_code="suite.alcance_insuficiente",
            detalle={"faltan": faltan},
        )
