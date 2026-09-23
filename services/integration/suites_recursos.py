"""Contactos, tareas, notas, ficheros y reuniones en línea
(CRM-06.01.03.06 a .10).

Lo de correo y calendario ya estaba. Esto es el resto de lo que la gente usa
todos los días y que, si no está, obliga a trabajar en dos sitios — que es la
forma en que un CRM se deja de usar sin que nadie lo decida.

Cada recurso tiene su trampa, y ninguna es técnica:

**Contactos.** La agenda de un comercial tiene a su médico, a su hermana y a tres
antiguos compañeros. Volcarla al CRM es meter datos personales de gente que no es
ni cliente ni usuaria, sin base legal y sin que nadie se lo haya preguntado. Sube
lo que ya está relacionado con el CRM; lo demás no.

**Tareas.** Lo que la gente espera es que cerrarla en un sitio la cierre en el
otro. Lo que no espera es que borrarla en su móvil borre la actividad del CRM que
otros han comentado — así que un borrado en el proveedor **no borra aquí**.

**Notas.** Copiar la página de un cuaderno al CRM duplica el dato y queda vieja el
mismo día. Va por referencia, y el permiso lo resuelve el proveedor con la
identidad de quien mira: quien no tiene acceso ve que no lo tiene, no el
contenido.

**Ficheros.** Igual, y con un motivo más: copiar rompe la promesa de «bórralo y
desaparece». Si el cliente borra el documento en su Drive y el CRM tiene una
copia, sigue ahí.

**Reuniones en línea.** El enlace de una reunión **es una credencial**: quien lo
tiene entra. No viaja en una notificación push ni en una página pública, y no se
crea hasta que la reunión está confirmada — si no, quedan salas huérfanas que
siguen abiertas.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Quién manda en cada campo cuando los dos lados tienen valor. Es lo único que
# evita la guerra de escrituras: sin una regla declarada, cada sincronización
# revierte la anterior y el registro parpadea entre dos valores para siempre.
ORIGENES = ("crm", "proveedor", "el_mas_reciente", "no_tocar")

# Qué se sube de un contacto del CRM a la agenda del usuario. Cerrada: subir «lo
# que haya» acaba metiendo notas internas de la ficha en un contacto del móvil,
# que se sincroniza con el coche, con el reloj y con lo que tenga.
CAMPOS_QUE_SUBEN = ("nombre", "apellidos", "empresa", "cargo", "email", "telefono")

ESTADOS_TAREA = ("pendiente", "en_curso", "hecha", "cancelada")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ── Contactos en los dos sentidos (CRM-06.01.03.06) ───────────────────────


def que_contactos_suben(
    *, contactos_del_crm: list[dict[str, Any]], solo_relacionados: bool = True
) -> dict[str, Any]:
    """Qué contactos del CRM van a la agenda del usuario.

    Por defecto, **solo los que tienen relación con él**: sus cuentas, sus
    oportunidades. Subirle los cuarenta mil del CRM llena su agenda de gente que
    no conoce, y lo primero que hace cualquiera entonces es desconectar la
    integración — con lo que se pierde también lo que sí servía.
    """
    suben: list[dict[str, Any]] = []
    fuera: list[dict[str, str]] = []
    for contacto in contactos_del_crm:
        if solo_relacionados and not contacto.get("relacionado_con_el_usuario"):
            fuera.append(
                {
                    "contacto": str(contacto.get("id")),
                    "porque": (
                        "no es suyo: subirle los cuarenta mil del CRM llena su agenda "
                        "de gente que no conoce, y entonces desconecta la integración"
                    ),
                }
            )
            continue
        suben.append({c: contacto.get(c) for c in CAMPOS_QUE_SUBEN if contacto.get(c) is not None})
    return {
        "suben": suben,
        "no_suben": fuera,
        "campos": list(CAMPOS_QUE_SUBEN),
        "porque_solo_estos_campos": (
            "Un contacto del móvil se sincroniza con el coche, con el reloj y con lo "
            "que tenga. Las notas internas de la ficha no pintan nada ahí."
        ),
    }


def que_contactos_entran(
    *, contactos_del_proveedor: list[dict[str, Any]], correos_conocidos: list[str]
) -> dict[str, Any]:
    """Qué entra de la agenda personal al CRM: **casi nada, y a propósito**.

    Entra lo que ya está en el CRM —para actualizarlo— y lo que la persona marca
    expresamente. Lo demás es su vida privada: su médico, su hermana, tres
    antiguos compañeros. Meterlo en el CRM es tratar datos personales de gente
    que no es ni cliente ni usuaria, sin base legal y sin habérselo preguntado a
    nadie.
    """
    conocidos = {str(c).strip().lower() for c in correos_conocidos if c}
    actualizan: list[dict[str, Any]] = []
    nuevos: list[dict[str, Any]] = []
    privados = 0

    for contacto in contactos_del_proveedor:
        correo = str(contacto.get("email") or "").strip().lower()
        if correo and correo in conocidos:
            actualizan.append(contacto)
        elif contacto.get("marcado_para_el_crm"):
            nuevos.append(contacto)
        else:
            privados += 1

    return {
        "actualizan_una_ficha": len(actualizan),
        "altas_marcadas_por_la_persona": len(nuevos),
        "se_quedan_en_su_agenda": privados,
        "detalle_altas": nuevos,
        "porque": (
            "Lo que no está en el CRM y nadie ha marcado se queda fuera. Una agenda "
            "personal tiene al médico y a la familia: subirla es tratar datos de gente "
            "que no es ni cliente ni usuaria, y que no lo ha autorizado."
        ),
    }


def resolver_campo(
    *, campo: str, valor_crm: Any, valor_proveedor: Any, origen: str, mas_reciente: str = "crm"
) -> dict[str, Any]:
    """Quién gana en un campo concreto.

    La regla se declara **por campo** y no por objeto: el teléfono lo sabe mejor
    el móvil de quien acaba de hablar con el cliente, y el cargo lo sabe mejor el
    CRM, donde lo actualiza quien lleva la cuenta. Una regla única para todo el
    contacto obliga a elegir entre dos verdades.
    """
    if origen not in ORIGENES:
        raise ErrorValidacion(
            f"Origen «{origen}» desconocido para «{campo}»",
            error_code="suite.origen_invalido",
            detalle={"admitidos": list(ORIGENES)},
        )
    if origen == "no_tocar":
        return {"valor": valor_crm, "gana": "crm", "porque": "Este campo no se sincroniza."}
    if valor_crm == valor_proveedor:
        return {"valor": valor_crm, "gana": "ninguno", "porque": "Dicen lo mismo."}
    if valor_proveedor in (None, ""):
        # Un vacío del proveedor NO borra: casi siempre significa «no lo tengo»,
        # no «está vacío», y borrar un teléfono bueno porque el otro lado no lo
        # trae es de lo que peor sienta.
        return {
            "valor": valor_crm,
            "gana": "crm",
            "porque": (
                "El proveedor no trae valor. Un vacío casi siempre significa «no lo "
                "tengo», no «bórralo»."
            ),
        }
    if origen == "crm":
        return {"valor": valor_crm, "gana": "crm", "porque": "En este campo manda el CRM."}
    if origen == "proveedor":
        return {
            "valor": valor_proveedor,
            "gana": "proveedor",
            "porque": "En este campo manda el proveedor.",
        }
    gana = mas_reciente if mas_reciente in ("crm", "proveedor") else "crm"
    return {
        "valor": valor_crm if gana == "crm" else valor_proveedor,
        "gana": gana,
        "porque": "Gana el que se tocó después.",
    }


# ── Tareas y acciones (CRM-06.01.03.07) ───────────────────────────────────


def sincronizar_tarea(
    *,
    en_el_crm: dict[str, Any] | None,
    en_el_proveedor: dict[str, Any] | None,
    ultima_sincronizacion: datetime | None = None,
) -> dict[str, Any]:
    """Qué hacer con una tarea que existe en uno de los dos lados, o en los dos.

    Lo que la gente espera es que **cerrarla en un sitio la cierre en el otro**;
    es la única razón por la que alguien usa esto. Lo que no espera —y lo que
    hace que se desconfíe de la integración para siempre— es que borrarla en su
    móvil haga desaparecer del CRM una actividad que otras tres personas han
    comentado.

    Por eso un borrado en el proveedor **no borra aquí**: se desvincula y se
    dice. La actividad se queda con su historia y deja de seguir a una tarea que
    ya no existe.
    """
    if en_el_crm is None and en_el_proveedor is None:
        raise ErrorValidacion(
            "No hay tarea en ninguno de los dos lados", error_code="suite.tarea_vacia"
        )

    if en_el_crm is None:
        return {
            "accion": "crear_en_el_crm",
            "datos": en_el_proveedor,
            "porque": "La creó la persona en su gestor y tiene que constar en la ficha.",
        }
    if en_el_proveedor is None:
        if en_el_crm.get("existia_en_el_proveedor"):
            return {
                "accion": "desvincular",
                "porque": (
                    "La tarea se ha borrado en el gestor de la persona. Aquí NO se "
                    "borra: la actividad del CRM tiene historia y puede tener "
                    "comentarios de otros. Se desvincula y se dice."
                ),
                "avisar_al_usuario": True,
            }
        return {
            "accion": "crear_en_el_proveedor",
            "datos": en_el_crm,
            "porque": "Es una tarea del CRM que la persona tiene que ver en su gestor.",
        }

    cerrada_crm = str(en_el_crm.get("estado")) in ("hecha", "cancelada")
    cerrada_prov = str(en_el_proveedor.get("estado")) in ("hecha", "cancelada")
    if cerrada_crm != cerrada_prov:
        # Cerrar gana siempre sobre abrir. Reabrir la tarea de alguien que
        # acaba de marcarla como hecha es la forma más rápida de que deje de
        # usar la integración: la ha cerrado por algo.
        return {
            "accion": "cerrar_en_el_crm" if cerrada_prov else "cerrar_en_el_proveedor",
            "porque": (
                "Cerrar gana sobre abrir: reabrir la tarea de alguien que acaba de "
                "marcarla como hecha es la forma más rápida de que desconecte esto."
            ),
        }

    tocada_crm = en_el_crm.get("modificada_at")
    tocada_prov = en_el_proveedor.get("modificada_at")
    if ultima_sincronizacion and tocada_crm and tocada_prov:
        if tocada_crm > ultima_sincronizacion and tocada_prov > ultima_sincronizacion:
            return {
                "accion": "conflicto",
                "porque": (
                    "Se ha tocado en los dos lados desde la última vuelta. Elegir uno "
                    "automáticamente tira el trabajo de alguien sin que se entere."
                ),
                "version_del_crm": en_el_crm,
                "version_del_proveedor": en_el_proveedor,
            }

    # La asignación no viaja: el gestor de tareas personal no tiene noción de a
    # quién pertenece un registro del CRM, y dejarle decidir eso reasignaría
    # trabajo sin que nadie lo hubiera pedido.
    return {
        "accion": "nada",
        "porque": "Las dos dicen lo mismo.",
        "lo_que_no_viaja": "La asignación: el gestor personal no sabe de quién es la cuenta.",
    }


# ── Notas por referencia (CRM-06.01.03.08) ────────────────────────────────


def vincular_nota(
    *,
    objeto: str,
    objeto_id: UUID,
    proveedor: str,
    referencia: str,
    titulo: str,
    copiar_contenido: bool = False,
) -> dict[str, Any]:
    """Enlaza una nota de un cuaderno externo a un registro del CRM.

    **Por referencia y no por copia.** Una copia queda vieja el mismo día —quien
    escribe sigue escribiendo en el cuaderno— y duplica el dato: si la nota lleva
    lo que contó el cliente en una reunión, ahora hay dos sitios que proteger y
    dos que borrar cuando toque.

    El permiso lo resuelve el proveedor con la identidad de quien mira. Quien no
    tenga acceso verá que no lo tiene, que es la respuesta correcta — y no el
    contenido, que es lo que pasaría si lo hubiéramos copiado con las
    credenciales de quien lo vinculó.
    """
    if copiar_contenido:
        raise Prohibido(
            "Las notas no se copian al CRM. Una copia queda vieja el mismo día y "
            "duplica el dato: dos sitios que proteger y dos que borrar. Y además la "
            "copia se haría con las credenciales de quien la vinculó, así que la "
            "vería gente que en el cuaderno no tiene acceso.",
            error_code="suite.nota_no_se_copia",
        )
    if not referencia.strip():
        raise ErrorValidacion(
            "Una nota vinculada sin referencia es un enlace roto con nombre bonito",
            error_code="suite.nota_sin_referencia",
        )
    return {
        "objeto": objeto,
        "objeto_id": str(objeto_id),
        "proveedor": proveedor,
        "referencia": referencia.strip(),
        "titulo": titulo.strip()[:300],
        "contenido_en_el_crm": False,
        "vinculada_at": _ahora().isoformat(),
        "como_se_ve": (
            "El enlace se abre con la identidad de quien lo pulsa. Quien no tenga "
            "acceso en el cuaderno verá que no lo tiene, no el contenido."
        ),
    }


def resolver_nota(*, referencia: str, tiene_acceso: bool, existe: bool) -> dict[str, Any]:
    """Qué se le enseña a quien abre una nota vinculada.

    Se distingue **«no tienes acceso» de «ya no existe»**, que es la diferencia
    entre pedirle el permiso a un compañero y buscar media hora algo que alguien
    borró hace un mes.
    """
    if not existe:
        return {
            "ver": False,
            "motivo": "no_existe",
            "que_decir": (
                "La nota ya no está en el cuaderno. Alguien la borró o la movió; el "
                "enlace del CRM se queda para que conste que la hubo."
            ),
        }
    if not tiene_acceso:
        return {
            "ver": False,
            "motivo": "sin_acceso",
            "que_decir": (
                "La nota existe pero no tienes acceso en el cuaderno. Pídeselo a quien "
                "la escribió: el CRM no puede dártelo, y menos aún enseñártela por su "
                "cuenta."
            ),
        }
    return {"ver": True, "referencia": referencia}


# ── Ficheros por enlace (CRM-06.01.03.09) ─────────────────────────────────


def vincular_fichero(
    *,
    objeto: str,
    objeto_id: UUID,
    proveedor: str,
    referencia: str,
    nombre: str,
    tamano_bytes: int | None = None,
) -> dict[str, Any]:
    """Enlaza un documento del almacenamiento del cliente a un registro.

    Sin copiarlo, por lo mismo que las notas y por una razón más: **copiar rompe
    la promesa de «bórralo y desaparece»**. Si el cliente borra el contrato en su
    Drive porque se lo han pedido y el CRM guarda una copia, el documento sigue
    ahí — y el que tenía que haber desaparecido no ha desaparecido.

    Los permisos se resuelven **en el origen**. Copiarlos aquí sería mantener dos
    listas de quién puede ver qué, y la segunda se queda desfasada el día que
    alguien cambia la primera.
    """
    if not referencia.strip():
        raise ErrorValidacion(
            "Un fichero vinculado sin referencia es un enlace roto",
            error_code="suite.fichero_sin_referencia",
        )
    return {
        "objeto": objeto,
        "objeto_id": str(objeto_id),
        "proveedor": proveedor,
        "referencia": referencia.strip(),
        "nombre": nombre.strip()[:300],
        "tamano_bytes": tamano_bytes,
        "copia_en_el_crm": False,
        "permisos": "se resuelven en el origen",
        "porque": (
            "Copiar rompe la promesa de «bórralo y desaparece»: si el cliente lo borra "
            "en su almacenamiento y aquí hay una copia, el documento sigue estando."
        ),
    }


def estado_del_enlace(*, existe: bool, tiene_acceso: bool, nombre: str) -> dict[str, Any]:
    """Qué se enseña en la ficha al lado de un documento enlazado.

    Un enlace que no se puede abrir tiene que **decirlo en la ficha**, no al
    pulsarlo. Quien prepara una reunión mirando la ficha necesita saber que ese
    contrato no está antes de sentarse delante del cliente.
    """
    if not existe:
        return {
            "estado": "desaparecido",
            "que_decir": (
                f"«{nombre}» ya no está en el almacenamiento del cliente. Puede ser "
                "correcto —lo borraron a propósito— o puede ser que alguien movió la "
                "carpeta, y eso hay que mirarlo antes de la reunión, no durante."
            ),
        }
    if not tiene_acceso:
        return {
            "estado": "sin_acceso",
            "que_decir": (
                f"«{nombre}» existe pero no tienes permiso en el origen. El CRM no te "
                "lo puede dar: los permisos del documento son de quien lo guarda."
            ),
        }
    return {"estado": "disponible"}


# ── Reunión en línea (CRM-06.01.03.10) ────────────────────────────────────


def crear_reunion(
    *,
    perfil_config: dict[str, Any],
    asunto: str,
    inicio: datetime,
    fin: datetime,
    confirmada: bool,
    asistentes: list[str],
) -> dict[str, Any]:
    """Prepara la creación de una reunión en línea con el proveedor del tenant.

    **No se crea hasta que la reunión está confirmada.** Crear la sala al
    proponer la hora deja salas huérfanas de todas las reuniones que no
    cuajaron: siguen abiertas, siguen en el calendario de quien aceptó, y alguien
    acaba entrando a una sala vacía convencido de que le han dado plantón.

    Y **el enlace es una credencial**: quien lo tiene entra. Por eso viaja en la
    cita y en la ficha, y no en una notificación push ni en una página pública.
    """
    if not confirmada:
        raise ErrorValidacion(
            "La sala se crea cuando la reunión está confirmada. Crearla al proponer "
            "deja salas abiertas de reuniones que no cuajaron, y alguien acaba "
            "entrando a una vacía creyendo que le han dado plantón.",
            error_code="suite.reunion_sin_confirmar",
        )
    if fin <= inicio:
        raise ErrorValidacion(
            "La reunión termina antes de empezar", error_code="suite.reunion_al_reves"
        )

    reuniones = dict(dict(perfil_config.get("recursos") or {}).get("reuniones") or {})
    endpoint = str(reuniones.get("endpoint") or "")
    if not endpoint:
        raise ErrorValidacion(
            "El perfil de este tenant no declara proveedor de reuniones en línea. No "
            "se inventa uno: mandar a la gente a una sala de otro producto es "
            "exactamente lo que el cliente no quiere.",
            error_code="suite.sin_proveedor_de_reuniones",
        )

    return {
        "endpoint": endpoint,
        "cuerpo": {
            "asunto": asunto[:300],
            "inicio": inicio.isoformat(),
            "fin": fin.isoformat(),
            "asistentes": sorted({a.strip().lower() for a in asistentes if a.strip()}),
        },
        "el_enlace_es_una_credencial": True,
        "donde_puede_ir": ["la cita del calendario", "la ficha del registro"],
        "donde_no": [
            "una notificación push: llega a una pantalla bloqueada",
            "una página pública o un enlace compartido sin caducidad",
        ],
    }


def enlace_para(*, enlace: str, destino: str) -> dict[str, Any]:
    """Si el enlace de la reunión puede ir a ese sitio.

    Existe porque la tentación de meterlo en el aviso del móvil es enorme —es
    justo lo que el usuario quiere pulsar— y porque quien tenga ese teléfono en
    la mano entra a la reunión sin identificarse.
    """
    if destino in ("push", "publico", "pagina_publica"):
        return {
            "puede": False,
            "porque": (
                "El enlace de una reunión es una credencial: quien lo tiene entra. En "
                "un push llega a una pantalla bloqueada que ve cualquiera que coja el "
                "teléfono; en una página pública, cualquiera."
            ),
            "que_hacer": "Mandar la referencia y que la aplicación lo resuelva tras identificar.",
        }
    return {"puede": True, "enlace": enlace}
