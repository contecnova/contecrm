"""Ejecutar una solicitud de derechos, y poder demostrar que se hizo.

`CRM-07.03.01.03`. El registro de la solicitud con su plazo legal ya estaba. Lo
que faltaba es lo único que el interesado nota y lo único que un inspector pide:
**hacerlo y poder demostrarlo**.

Una solicitud que se registra, se tramita a mano y se marca resuelta sin
evidencia deja a la empresa exactamente igual que si no tuviera sistema: cuando
llegue la reclamación, la respuesta será «lo hicimos» sin nada detrás.

Tres cosas gobiernan este módulo:

**El bloqueo legal manda sobre el derecho de supresión, y hay que decirlo.** Si
un juzgado ha pedido conservar esos datos, no se borran — y eso **no es un fallo
del sistema**: es la ley resolviendo un conflicto entre dos obligaciones. Se
rechaza con el motivo, se registra, y el interesado recibe una respuesta que
explica por qué. Borrar igualmente destruiría prueba; callarlo dejaría al
responsable sin saber qué contestar.

**Suprimir no es borrar filas.** Hay datos que la empresa tiene obligación de
conservar —una factura, un contrato— aunque el interesado pida la supresión. Lo
que se hace es **anonimizar**: se rompe el vínculo con la persona y se conserva
el hecho económico. Borrar la fila entera rompería la contabilidad y sería otro
incumplimiento distinto.

**La evidencia se guarda con lo que se hizo, no con lo que se pidió.** Qué
registros se tocaron, cuántos, cuándo y con qué huella. Sin eso, la evidencia es
una casilla marcada.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = get_logger(__name__)

# Los seis derechos del RGPD. Lista cerrada: cada uno tiene una ejecución
# distinta y un plazo que se cuenta igual, y admitir uno inventado dejaría una
# solicitud sin forma de resolverse.
TIPOS = ("acceso", "rectificacion", "supresion", "portabilidad", "oposicion", "limitacion")

# Los que este módulo sabe ejecutar. La rectificación necesita que una persona
# diga QUÉ cambia y a qué valor —de una solicitud en prosa no se deduce—, y la
# oposición y la limitación, sobre qué tratamientos; pero una vez decidido eso,
# los seis se ejecutan y dejan evidencia (CRM-02.04.02.04, CRM-02.04.02.05).
EJECUTABLES = (
    "acceso",
    "portabilidad",
    "supresion",
    "rectificacion",
    "oposicion",
    "limitacion",
)

# Campos que se vacían al anonimizar un contacto. Lo que identifica a la
# persona, y nada más: el resto —fechas, importes, qué compró— es el hecho
# económico que la empresa tiene obligación de conservar.
CAMPOS_IDENTIFICATIVOS = (
    "nombre",
    "apellidos",
    "nombre_completo",
    "email",
    "telefono",
    "movil",
    "linkedin",
    "cargo",
)


def _solicitud(db: Session, solicitud_id: UUID) -> Any:
    from services.party.modelos import SolicitudDerechos

    fila = db.get(SolicitudDerechos, solicitud_id)
    if fila is None:
        raise NoEncontrado(
            "La solicitud no existe", error_code="party.solicitud_derechos_no_existe"
        )
    return fila


def _contactos_del_solicitante(db: Session, solicitud: Any) -> list[Any]:
    """Todos los contactos que son esta persona.

    Se busca por identificador **y por correo**: una solicitud puede llegar de
    alguien que está tres veces en el sistema con la misma dirección, y
    resolverla solo sobre la ficha enlazada dejaría las otras dos intactas —que
    es incumplir, aunque la solicitud figure resuelta.
    """
    from services.party.modelos import Contacto

    encontrados: dict[UUID, Any] = {}
    if solicitud.contacto_id:
        contacto = db.get(Contacto, solicitud.contacto_id)
        if contacto is not None:
            encontrados[contacto.id] = contacto

    if solicitud.email_solicitante:
        for contacto in db.execute(
            select(Contacto).where(
                Contacto.email == solicitud.email_solicitante,
                Contacto.deleted_at.is_(None),
            )
        ).scalars():
            encontrados[contacto.id] = contacto
    return list(encontrados.values())


# ── Acceso y portabilidad ─────────────────────────────────────────────────


def ejecutar_acceso(db: Session, solicitud_id: UUID, *, por: UUID | None = None) -> dict[str, Any]:
    """Reúne todo lo que este servicio guarda de la persona.

    **Solo lo de este servicio**, y se dice: `party` no puede leer el esquema de
    `sales` ni el de `service`. La respuesta completa al interesado la compone
    quien llame a los tres, y devolver esto como si fuera todo sería la forma más
    silenciosa de incumplir — el interesado recibiría un expediente incompleto
    creyendo que es completo.

    El formato es JSON estructurado, que es lo que el RGPD llama «de uso común y
    lectura mecánica» para la portabilidad. Acceso y portabilidad comparten
    ejecución porque el contenido es el mismo; lo que cambia es a quién se le
    entrega y en qué formato, y eso lo decide quien responde.
    """
    solicitud = _solicitud(db, solicitud_id)
    contactos = _contactos_del_solicitante(db, solicitud)
    if not contactos:
        # No es un error: hay solicitudes de personas que no están en el sistema,
        # y la respuesta correcta es «no tenemos nada suyo». Fingir un error
        # dejaría la solicitud sin resolver y el plazo corriendo.
        return _con_evidencia(
            db,
            solicitud,
            accion="acceso",
            datos={"contactos": [], "nota": "no hay datos de esta persona en este servicio"},
            por=por,
        )

    from services.party.modelos import Actividad, Consentimiento, Direccion, RelacionContactoCuenta

    expediente: dict[str, Any] = {"servicio": "party", "contactos": []}
    for contacto in contactos:
        expediente["contactos"].append(
            {
                "ficha": _limpio(contacto),
                "direcciones": [
                    _limpio(d)
                    for d in db.execute(
                        select(Direccion).where(
                            Direccion.objeto == "contacto", Direccion.objeto_id == contacto.id
                        )
                    ).scalars()
                ],
                "consentimientos": [
                    _limpio(c)
                    for c in db.execute(
                        select(Consentimiento).where(Consentimiento.contacto_id == contacto.id)
                    ).scalars()
                ],
                "vinculos_con_cuentas": [
                    _limpio(r)
                    for r in db.execute(
                        select(RelacionContactoCuenta).where(
                            RelacionContactoCuenta.contacto_id == contacto.id
                        )
                    ).scalars()
                ],
                "actividades": [
                    _limpio(a)
                    for a in db.execute(
                        select(Actividad).where(
                            Actividad.contacto_id == contacto.id,
                            Actividad.deleted_at.is_(None),
                        )
                    ).scalars()
                ],
            }
        )

    return _con_evidencia(db, solicitud, accion="acceso", datos=expediente, por=por)


def _limpio(fila: Any) -> dict[str, Any]:
    """Una fila como diccionario serializable, sin metadatos internos.

    Se quitan las columnas de auditoría técnica: al interesado le interesan sus
    datos, no nuestras claves ajenas ni la versión de la fila. Incluirlas
    convierte un expediente legible en un volcado de base de datos, que cumple la
    letra y no el propósito.
    """
    datos = fila.a_dict(json_seguro=True) if hasattr(fila, "a_dict") else dict(fila.__dict__)
    for tecnico in ("_sa_instance_state", "tenant_id", "version", "deleted_by", "updated_by"):
        datos.pop(tecnico, None)
    return {k: (str(v) if isinstance(v, UUID) else v) for k, v in datos.items()}


# ── Supresión ─────────────────────────────────────────────────────────────


def ejecutar_supresion(
    db: Session, solicitud_id: UUID, *, por: UUID | None = None, confirmado: bool = False
) -> dict[str, Any]:
    """Anonimiza a la persona, respetando los bloqueos legales.

    **Anonimizar y no borrar**: hay datos que la empresa tiene obligación de
    conservar —una factura, un contrato— aunque el interesado pida la supresión.
    Se rompe el vínculo con la persona y se conserva el hecho económico. Borrar
    la fila entera rompería la contabilidad y sería otro incumplimiento
    distinto.

    **El bloqueo legal gana.** Si un juzgado ha pedido conservar esos datos, no
    se tocan. No es un fallo del sistema: es la ley resolviendo un conflicto
    entre dos obligaciones, y se responde con el motivo en vez de fingir que se
    hizo.
    """
    from crmcore.datos.retencion import bajo_bloqueo

    solicitud = _solicitud(db, solicitud_id)
    if solicitud.tipo != "supresion":
        raise ErrorValidacion(
            f"Esta solicitud es de «{solicitud.tipo}», no de supresión",
            error_code="party.solicitud_tipo_distinto",
        )
    if not confirmado:
        # Anonimizar no tiene vuelta atrás. Se exige decirlo, como en la
        # revocación de la clave del tenant y por el mismo motivo.
        raise ErrorValidacion(
            "Anonimizar es irreversible: los datos identificativos no se pueden "
            "recuperar. Hay que confirmarlo explícitamente",
            error_code="party.supresion_sin_confirmar",
        )

    contactos = _contactos_del_solicitante(db, solicitud)
    anonimizados: list[dict[str, Any]] = []
    bloqueados: list[dict[str, Any]] = []

    for contacto in contactos:
        bloqueo = bajo_bloqueo(
            db, tenant_id=solicitud.tenant_id, objeto="contacto", objeto_id=contacto.id
        )
        if bloqueo is not None:
            bloqueados.append(
                {
                    "contacto_id": str(contacto.id),
                    "bloqueo": bloqueo.motivo,
                    "referencia": bloqueo.referencia or "",
                }
            )
            continue
        anonimizados.append(_anonimizar(db, contacto))

    if bloqueados and not anonimizados:
        # Nada se pudo suprimir. La solicitud NO se marca resuelta: se deja en
        # curso con la evidencia de por qué, para que alguien conteste al
        # interesado explicando el conflicto.
        logger.warning(
            "party.supresion_bloqueada",
            solicitud=str(solicitud_id),
            bloqueos=len(bloqueados),
        )

    return _con_evidencia(
        db,
        solicitud,
        accion="supresion",
        datos={"anonimizados": anonimizados, "bloqueados": bloqueados},
        por=por,
        resolver=bool(anonimizados) and not bloqueados,
    )


def _anonimizar(db: Session, contacto: Any) -> dict[str, Any]:
    """Vacía lo que identifica a la persona y conserva el resto.

    El identificador de la fila se mantiene: las referencias desde
    oportunidades, casos y facturas siguen apuntando a algo, y romperlas dejaría
    huérfanos registros que la empresa sí tiene que conservar.
    """
    from services.party.modelos import Consentimiento

    antes = {
        campo: getattr(contacto, campo, None)
        for campo in CAMPOS_IDENTIFICATIVOS
        if getattr(contacto, campo, None)
    }
    for campo in CAMPOS_IDENTIFICATIVOS:
        if hasattr(contacto, campo):
            setattr(contacto, campo, None)
    contacto.nombre = "(suprimido)"
    contacto.nombre_completo = "(suprimido)"
    contacto.clave_canonica = f"suprimido-{contacto.id}"
    contacto.anonimizado_at = datetime.now(timezone.utc)

    # Los consentimientos se revocan además de anonimizarse: conservar un
    # «consintió recibir comercial» de alguien cuya ficha ya no lo identifica
    # permitiría seguir contándolo como base legal de un envío.
    for consentimiento in db.execute(
        select(Consentimiento).where(Consentimiento.contacto_id == contacto.id)
    ).scalars():
        consentimiento.concedido = False

    db.flush()
    return {
        "contacto_id": str(contacto.id),
        # Huella de lo borrado, no el contenido: sirve para demostrar que se
        # borró algo concreto sin conservar precisamente lo que se pidió borrar.
        "huella_datos_borrados": hashlib.sha256(
            json.dumps(antes, sort_keys=True, default=str).encode()
        ).hexdigest(),
        "campos_borrados": sorted(antes),
    }


# ── Evidencia ─────────────────────────────────────────────────────────────


def _con_evidencia(
    db: Session,
    solicitud: Any,
    *,
    accion: str,
    datos: dict[str, Any],
    por: UUID | None,
    resolver: bool = True,
) -> dict[str, Any]:
    """Guarda qué se hizo y devuelve el resultado.

    La evidencia lleva **huella del contenido**: es lo que permite demostrar
    dentro de dos años que lo entregado fue exactamente esto y no otra cosa, sin
    tener que conservar una copia del expediente —que sería conservar los datos
    que el interesado quería que dejáramos de tener—.
    """
    from crmcore.audit.chain import registrar

    ahora = datetime.now(timezone.utc)
    serializado = json.dumps(datos, sort_keys=True, default=str, ensure_ascii=False)
    huella = hashlib.sha256(serializado.encode()).hexdigest()

    solicitud.evidencia = {
        **(solicitud.evidencia or {}),
        accion: {
            "momento": ahora.isoformat(),
            "por": str(por) if por else None,
            "huella": huella,
            "tamano_bytes": len(serializado),
            "resumen": _resumen(accion, datos),
        },
    }
    if resolver:
        solicitud.estado = "resuelta"
        solicitud.resuelta_at = ahora
        solicitud.resolucion = f"{accion} ejecutado"
    else:
        solicitud.estado = "en_curso"
    db.flush()

    registrar(
        db,
        accion=f"derechos.{accion}",
        objeto="solicitud_derechos",
        objeto_id=solicitud.id,
        datos={"huella": huella, "resumen": solicitud.evidencia[accion]["resumen"]},
        tenant_id=solicitud.tenant_id,
    )
    return {
        "solicitud_id": str(solicitud.id),
        "tipo": solicitud.tipo,
        "estado": solicitud.estado,
        "evidencia": solicitud.evidencia[accion],
        # El contenido va en la respuesta y NO se guarda: guardarlo sería
        # conservar exactamente los datos que el interesado pidió que dejáramos
        # de tener. La huella basta para demostrar qué se entregó.
        "contenido": datos,
        "alcance": (
            "Solo los datos que guarda el servicio «party». La respuesta "
            "completa al interesado exige preguntar también a los demás "
            "servicios: ninguno lee el esquema de otro."
        ),
    }


def _resumen(accion: str, datos: dict[str, Any]) -> str:
    if accion == "supresion":
        return (
            f"{len(datos.get('anonimizados', []))} contacto(s) anonimizado(s), "
            f"{len(datos.get('bloqueados', []))} bloqueado(s) por retención legal"
        )
    if accion == "rectificacion":
        tocados = datos.get("rectificados", [])
        campos = sorted({c for t in tocados for c in (t.get("antes") or {})})
        return f"{len(tocados)} ficha(s) rectificada(s) en: {', '.join(campos) or 'ningún campo'}"
    if accion in ("oposicion", "limitacion"):
        limitaciones = datos.get("limitaciones", [])
        tratamientos = sorted({t for lim in limitaciones for t in lim.get("limitados", [])})
        return (
            f"{len(limitaciones)} contacto(s) con tratamiento limitado: "
            f"{', '.join(tratamientos) or 'ninguno'}"
        )
    return f"{len(datos.get('contactos', []))} ficha(s) entregada(s)"


def comprobar_evidencia(solicitud: Any, accion: str, contenido: dict[str, Any]) -> bool:
    """Si un contenido coincide con la huella guardada.

    Es la otra mitad de la evidencia: guardarla no sirve de nada si no hay forma
    de comprobarla. Con esto, ante una reclamación se puede demostrar que el
    expediente que se entregó es el que consta.
    """
    registro = (solicitud.evidencia or {}).get(accion)
    if not registro:
        return False
    serializado = json.dumps(contenido, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(serializado.encode()).hexdigest() == registro.get("huella")


# ── Rectificación, portabilidad y oposición (CRM-02.04.02.04) ─────────────


def ejecutar_portabilidad(
    db: Session, solicitud_id: UUID, *, por: UUID | None = None
) -> dict[str, Any]:
    """Entrega los datos en formato de lectura mecánica (art. 20).

    Comparte contenido con el acceso porque **son los mismos datos**; lo que
    cambia es el encuadre legal y, sobre todo, el alcance: la portabilidad cubre
    solo lo que el interesado **aportó** o generó con su actividad, no lo que la
    empresa dedujo sobre él. Entregar un scoring interno como si fuera «sus
    datos» es regalar el trabajo propio y, peor, dar por bueno ante el
    interesado un juicio que nunca pidió.

    Así que se entrega lo mismo y **se dice qué queda fuera y por qué**.
    """
    salida = ejecutar_acceso(db, solicitud_id, por=por)
    salida["formato"] = "JSON estructurado, de uso común y lectura mecánica (art. 20.1)"
    salida["fuera_del_derecho"] = {
        "puntuaciones_y_segmentos": (
            "Inferencias de la empresa, no datos aportados por el interesado: el "
            "derecho de portabilidad no las cubre (art. 20.1)."
        ),
        "notas_internas_de_terceros": (
            "Lo que escribió un empleado sobre la conversación es también dato de "
            "ese empleado; se entrega en el derecho de ACCESO, no en el de portabilidad."
        ),
    }
    return salida


def ejecutar_rectificacion(
    db: Session,
    solicitud_id: UUID,
    *,
    cambios: dict[str, Any],
    por: UUID | None = None,
) -> dict[str, Any]:
    """Corrige los datos que el interesado dice que están mal (art. 16).

    **Los cambios los decide una persona, no el sistema.** Llegan como parámetro
    porque nadie puede deducir de una solicitud en prosa qué campo hay que
    cambiar y a qué valor; automatizarlo produciría rectificaciones inventadas
    sobre datos que nadie ha comprobado.

    Se guarda **lo que había antes**. Sin el valor anterior, una rectificación es
    indistinguible de una edición cualquiera, y lo que hay que poder demostrar es
    justo que se corrigió lo que el interesado señaló.
    """
    solicitud = _solicitud(db, solicitud_id)
    if not cambios:
        raise ErrorValidacion(
            "Una rectificación sin cambios no rectifica nada. Di qué campo y con "
            "qué valor: nadie puede deducirlo de la solicitud.",
            error_code="derechos.rectificacion_vacia",
        )
    contactos = _contactos_del_solicitante(db, solicitud)
    if not contactos:
        raise NoEncontrado(
            "No hay ninguna ficha de esta persona que rectificar",
            error_code="derechos.sin_fichas",
        )

    permitidos = set(CAMPOS_IDENTIFICATIVOS) | {"nombre_pila", "departamento", "idioma"}
    desconocidos = sorted(set(cambios) - permitidos)
    if desconocidos:
        raise ErrorValidacion(
            f"Estos campos no se rectifican por esta vía: {desconocidos}. La "
            "rectificación cubre los datos de la persona; cambiar importes o "
            "estados desde aquí sería usar un derecho para saltarse las reglas "
            "de negocio.",
            error_code="derechos.campo_no_rectificable",
            detalle={"permitidos": sorted(permitidos)},
        )

    tocados = []
    for contacto in contactos:
        antes = {}
        for campo, valor in cambios.items():
            if not hasattr(contacto, campo):
                continue
            antes[campo] = getattr(contacto, campo)
            setattr(contacto, campo, valor)
        if antes:
            tocados.append({"contacto_id": str(contacto.id), "antes": antes, "despues": cambios})
    db.flush()

    return _con_evidencia(
        db,
        solicitud,
        accion="rectificacion",
        datos={
            "rectificados": tocados,
            # Lo que este servicio NO ha podido corregir: el dato equivocado
            # puede estar copiado en una oportunidad o en un caso, y decir
            # «rectificado» sin avisar dejaría al interesado creyendo que ya no
            # existe en ninguna parte.
            "aviso": (
                "Rectificado en «party». Si el mismo dato se copió a otro servicio "
                "—una oportunidad, un caso— hay que pedírselo a él: ninguno escribe "
                "en el esquema de otro."
            ),
        },
        por=por,
    )


def ejecutar_oposicion(
    db: Session,
    solicitud_id: UUID,
    *,
    tratamientos: list[str] | None = None,
    por: UUID | None = None,
) -> dict[str, Any]:
    """Atiende la oposición al tratamiento (art. 21) **limitándolo de verdad**.

    La oposición se resuelve casi siempre anotando «no contactar» en un campo de
    texto, y eso dura hasta la siguiente importación. Aquí se traduce en una
    limitación con su fila, su fecha y su motivo, que es lo que el punto de
    decisión consulta antes de cada envío.

    Y se dice **qué no para**: oponerse a la publicidad no para la facturación,
    y prometerlo sería prometer lo que la ley no pide.
    """
    from crmcore.db.uow import UnidadDeTrabajo

    from services.party import limitacion as lim

    solicitud = _solicitud(db, solicitud_id)
    contactos = _contactos_del_solicitante(db, solicitud)
    if not contactos:
        raise NoEncontrado(
            "No hay ninguna ficha de esta persona a la que aplicar la oposición",
            error_code="derechos.sin_fichas",
        )

    uow = UnidadDeTrabajo(db=db, tenant_id=solicitud.tenant_id)
    aplicadas = []
    for contacto in contactos:
        salida = lim.limitar(
            uow,
            contacto_id=contacto.id,
            tratamientos=tratamientos or ["marketing", "perfilado", "cesion_terceros"],
            motivo="oposicion_en_estudio",
            detalle=f"Oposición del interesado, solicitud {solicitud.id}",
            solicitud_id=solicitud.id,
            por=por,
        )
        aplicadas.append(salida)

    return _con_evidencia(
        db,
        solicitud,
        accion="oposicion",
        datos={
            "limitaciones": aplicadas,
            "no_se_paran": lim.NO_SE_PUEDE_LIMITAR,
        },
        por=por,
    )


def ejecutar_limitacion(
    db: Session,
    solicitud_id: UUID,
    *,
    tratamientos: list[str] | None = None,
    motivo: str = "exactitud_discutida",
    por: UUID | None = None,
) -> dict[str, Any]:
    """Aplica el derecho de limitación (art. 18) sin borrar nada
    (CRM-02.04.02.05)."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.party import limitacion as lim

    solicitud = _solicitud(db, solicitud_id)
    contactos = _contactos_del_solicitante(db, solicitud)
    if not contactos:
        raise NoEncontrado(
            "No hay ninguna ficha de esta persona que limitar",
            error_code="derechos.sin_fichas",
        )
    uow = UnidadDeTrabajo(db=db, tenant_id=solicitud.tenant_id)
    aplicadas = [
        lim.limitar(
            uow,
            contacto_id=c.id,
            tratamientos=tratamientos,
            motivo=motivo,
            detalle=f"Limitación pedida en la solicitud {solicitud.id}",
            solicitud_id=solicitud.id,
            por=por,
        )
        for c in contactos
    ]
    return _con_evidencia(
        db,
        solicitud,
        accion="limitacion",
        datos={"limitaciones": aplicadas, "no_se_paran": lim.NO_SE_PUEDE_LIMITAR},
        por=por,
    )
