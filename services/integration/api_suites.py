"""API de las suites de productividad (CRM-06.01.03.01 a .10).

El perfil lo declara un administrador; **autorizar lo hace cada persona**. Esa
separación no es burocracia: un administrador que conecta el correo de su equipo
entero desde una pantalla es exactamente lo que hace que una integración acabe
discutiéndose en el comité de empresa.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from services.integration import suites as su
from services.integration import suites_operacion as sop
from services.integration import suites_recursos as sur
from services.integration.modelos import Conexion
from services.integration.suites import ConsentimientoSuite

router_suites = APIRouter(prefix="/suites", tags=["suites de productividad"])


class PerfilIn(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    sistema: str = Field("", max_length=80, description="Informativo: no cambia el comportamiento")
    config: dict[str, Any] = Field(default_factory=dict)


class ConsentimientoIn(BaseModel):
    perfil: str
    recursos: list[str]
    sentido: str = "leer"
    credencial_caduca_at: datetime | None = Field(
        None,
        description=(
            "Cuándo deja de valer la credencial que entrega el proveedor. Sin esto "
            "no se puede avisar de nada: lo que pasa entonces es que un martes deja "
            "de entrar el correo de veinte personas a la vez"
        ),
    )
    tiene_refresco: bool = Field(
        False,
        description=(
            "Si hay con qué renovarla sin volver a molestar a la persona. Una "
            "credencial **sin refresco y con caducidad** es una bomba de relojería: "
            "funciona meses y deja de funcionar de golpe"
        ),
    )


class SuscripcionIn(BaseModel):
    perfil: str
    recurso: str
    externo_id: str
    caduca_at: datetime | None = None


class ReunionIn(BaseModel):
    perfil: str
    asunto: str
    inicio: datetime
    fin: datetime
    confirmada: bool = False
    asistentes: list[str] = Field(default_factory=list)


@router_suites.post(
    "/perfiles",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Declarar un proveedor de productividad como configuración",
    description=(
        "Outlook y Gmail son el mismo problema con otras URLs. Un proveedor es un "
        "**perfil declarado** —qué recursos ofrece, en qué endpoint, con qué "
        "campos, cómo pide el incremento y qué límites tiene—, no un módulo: en "
        "cuanto se escribe un módulo por casa, cada implantación nueva es una "
        "versión del producto.\n\n"
        "Se rechaza el perfil incompleto y se dicen **todos** los problemas de "
        "una vez. Un perfil sin correspondencia de campos no sustituye a nada, y "
        "uno que declara alcances de recursos que no usa pide permisos de más — "
        "que es justo por lo que a muchas integraciones no las dejan entrar."
    ),
)
def declarar_perfil(cuerpo: PerfilIn, uow: UowDep) -> Any:
    fila = su.declarar_perfil(
        uow, nombre=cuerpo.nombre, sistema=cuerpo.sistema, config=cuerpo.config
    )
    return {"id": str(fila.id), "nombre": fila.nombre, **su.capacidades_de(dict(fila.config))}


@router_suites.post(
    "/perfiles/comprobar",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué le falta a este perfil, sin guardarlo",
)
def comprobar_perfil(cuerpo: PerfilIn, principal: AutenticadoDep) -> Any:
    return su.validar_perfil(cuerpo.config)


@router_suites.get(
    "/perfiles/{nombre}/capacidades",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué sabe hacer este perfil, antes de conectar nada",
    description=(
        "Con el dato de terceros **marcado**. Quien va a autorizar tiene derecho "
        "a saber que sincronizar sus contactos sube al CRM el teléfono de su "
        "médico, y esa frase tiene que poder ponerse en la pantalla de permiso."
    ),
)
def capacidades(nombre: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return su.capacidades_de(su.perfil(db, principal.tenant_id, nombre))


@router_suites.post(
    "/consentimiento",
    status_code=status.HTTP_201_CREATED,
    summary="Autorizar el acceso a los propios recursos",
    description=(
        "**Lo concede el dueño del buzón, y solo él.** No hay permiso de "
        "administrador que valga: un administrador puede declarar el perfil y "
        "pedirlo; autorizarlo por otra persona, no.\n\n"
        "Se concede **recurso a recurso**, que es lo que permite contestar "
        "después qué se autorizó exactamente — «conectó su Microsoft 365» no es "
        "una respuesta cuando alguien pregunta si el CRM lee sus correos.\n\n"
        "Y se pide el **alcance mínimo**: los alcances de los recursos que se van "
        "a usar y ni uno más."
    ),
)
def conceder(cuerpo: ConsentimientoIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    config = su.perfil(uow.db, uow.tenant_id, cuerpo.perfil)
    alcance = su.alcance_minimo(config=config, recursos=cuerpo.recursos, sentido=cuerpo.sentido)
    salida = su.conceder(
        uow,
        usuario_id=principal.id,
        quien_concede=principal.id,
        perfil_nombre=cuerpo.perfil,
        recursos=cuerpo.recursos,
        alcances=alcance["alcances"],
        sentido=cuerpo.sentido,
        credencial_caduca_at=cuerpo.credencial_caduca_at,
        tiene_refresco=cuerpo.tiene_refresco,
    )
    return {**salida, "no_se_piden": alcance["no_se_piden"]}


@router_suites.delete(
    "/consentimiento/{perfil}",
    summary="Retirar el permiso",
    description=(
        "Revocar **no borra lo ya sincronizado**, y se dice: lo que entró son "
        "actividades del CRM que otra gente ha usado. Lo que se para es que entre "
        "más. Borrar lo anterior es otra decisión y se pide aparte."
    ),
)
def revocar(perfil: str, uow: UowDep, principal: AutenticadoDep) -> Any:
    return su.revocar(uow, usuario_id=principal.id, perfil_nombre=perfil)


@router_suites.post(
    "/suscripciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Registrar una suscripción a los cambios del proveedor",
    description=(
        "Se exige el identificador que devolvió el proveedor: sin él no se puede "
        "renovar ni borrar, y queda una suscripción huérfana mandando avisos a "
        "una URL que ya no los atiende.\n\n"
        "Se rechaza una segunda suscripción al mismo recurso desde otro perfil: "
        "con dos, cada cambio entra dos veces y la ficha acaba con la misma "
        "reunión duplicada."
    ),
)
def suscribir(cuerpo: SuscripcionIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    su.exigir_sin_conflicto(
        uow.db,
        uow.tenant_id,
        usuario_id=principal.id,
        recurso=cuerpo.recurso,
        perfil_nombre=cuerpo.perfil,
    )
    fila = su.suscribir(
        uow,
        usuario_id=principal.id,
        perfil_nombre=cuerpo.perfil,
        recurso=cuerpo.recurso,
        externo_id=cuerpo.externo_id,
        caduca_at=cuerpo.caduca_at,
    )
    return {"id": str(fila.id), "recurso": fila.recurso, "estado": fila.estado}


@router_suites.get(
    "/suscripciones/por-renovar",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué suscripciones hay que renovar ya",
    description=(
        "Con margen y no en el último momento: renovar justo al caducar deja que "
        "un reintento fallido la mate, y entonces el flujo se para **sin dar "
        "ningún error** — el CRM se queda quieto y el usuario cree que no ha "
        "pasado nada en su buzón.\n\n"
        "Se avisa aparte de las que no declaran caducidad. Todas caducan: la que "
        "no lo dice es la que se muere sin que nadie lo vea venir."
    ),
)
def suscripciones_por_renovar(db: DbDep, principal: AutenticadoDep) -> Any:
    return su.por_renovar(db, principal.tenant_id)


@router_suites.post(
    "/reuniones",
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Preparar una reunión en línea con el proveedor del tenant",
    description=(
        "No se crea la sala hasta que la reunión está **confirmada**: crearla al "
        "proponer la hora deja salas abiertas de todas las que no cuajaron, y "
        "alguien acaba entrando a una vacía convencido de que le han dado "
        "plantón.\n\n"
        "El enlace **es una credencial**: quien lo tiene entra. Por eso la "
        "respuesta dice dónde puede ir y dónde no — y un push no es uno de los "
        "sitios donde puede ir."
    ),
)
def reunion(cuerpo: ReunionIn, db: DbDep, principal: AutenticadoDep) -> Any:
    return sur.crear_reunion(
        perfil_config=su.perfil(db, principal.tenant_id, cuerpo.perfil),
        asunto=cuerpo.asunto,
        inicio=cuerpo.inicio,
        fin=cuerpo.fin,
        confirmada=cuerpo.confirmada,
        asistentes=cuerpo.asistentes,
    )


class HuecosIn(BaseModel):
    ocupado: list[dict[str, Any]] = Field(default_factory=list)
    desde: datetime
    hasta: datetime
    minutos: int = 30
    calendario_legible: bool = True


class ExportacionIn(BaseModel):
    formato: str
    objetos: list[str] = Field(default_factory=list)
    referencias: list[str] = Field(default_factory=list)


class DiagnosticoIn(BaseModel):
    codigo: int | None = None
    alcances_concedidos: list[str] = Field(default_factory=list)
    alcances_necesarios: list[str] = Field(default_factory=list)
    mensaje_del_proveedor: str = ""


@router_suites.post(
    "/disponibilidad",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Huecos reales leídos del calendario",
    description=(
        "**Si el calendario no se puede leer, no se propone nada.** Es el error "
        "clásico de las herramientas de agenda: no se sabe y se propone "
        "igualmente «porque no consta nada», y se cita a alguien encima de la "
        "reunión que ya tenía.\n\n"
        "Del calendario ajeno se lee **que está ocupado, no de qué**: el asunto "
        "de una cita puede ser «revisión médica», y para proponer una hora no "
        "hace ninguna falta."
    ),
)
def disponibilidad(cuerpo: HuecosIn, principal: AutenticadoDep) -> Any:
    return sop.huecos_libres(
        ocupado=cuerpo.ocupado,
        desde=cuerpo.desde,
        hasta=cuerpo.hasta,
        minutos=cuerpo.minutos,
        calendario_legible=cuerpo.calendario_legible,
    )


@router_suites.post(
    "/exportacion",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Preparar una salida en formato estándar, sin pasar por ninguna suite",
    description=(
        "Es la puerta de salida. Un CRM cuyos datos solo pueden salir por la API "
        "de un fabricante tiene al cliente atado, y eso se descubre el día que "
        "quiere irse — cuando ya no hay tiempo de construir nada.\n\n"
        "El paquete dice **qué NO lleva dentro**: las notas y los ficheros están "
        "enlazados y no copiados. Sin esa lista, el cliente cree que se lo lleva "
        "todo y descubre el hueco cuando ya ha apagado lo otro."
    ),
)
def exportacion(cuerpo: ExportacionIn, principal: AutenticadoDep) -> Any:
    return sop.preparar_exportacion(
        formato=cuerpo.formato, objetos=cuerpo.objetos, incluye_referencias=cuerpo.referencias
    )


@router_suites.get(
    "/salud",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué lleva sin sincronizar, desde cuándo y por qué",
    description=(
        "**Lo que no se ha medido no está en verde.** Un panel que solo cuenta "
        "lo sincronizado enseña un número que sube mientras tres buzones llevan "
        "una semana parados: el número es verdad y la impresión es falsa.\n\n"
        "Se dicen aparte las conexiones que van por sondeo porque no se pudo "
        "renovar la suscripción: sus cambios entran con retraso, no al instante."
    ),
)
def salud(db: DbDep, principal: AutenticadoDep) -> Any:
    from sqlalchemy import select

    from services.integration.buzon import Buzon

    buzones = list(
        db.execute(select(Buzon).where(Buzon.tenant_id == principal.tenant_id)).scalars().all()
    )
    suscripciones = list(
        db.execute(
            select(su.SuscripcionSuite).where(su.SuscripcionSuite.tenant_id == principal.tenant_id)
        )
        .scalars()
        .all()
    )
    en_sondeo = {(s.usuario_id, s.recurso) for s in suscripciones if s.en_sondeo}
    return sop.salud(
        conexiones=[
            {
                "id": str(b.id),
                "recurso": b.ambito,
                "estado": b.estado,
                "motivo": b.motivo,
                "sincronizado_at": b.sincronizado_at,
                "en_sondeo": (b.usuario_id, b.ambito) in en_sondeo,
            }
            for b in buzones
        ]
    )


@router_suites.post(
    "/diagnostico",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué falla exactamente, no «error de autenticación»",
    description=(
        "«Error de autenticación» es el mensaje que hace que una implantación se "
        "atasque una semana: el consultor no sabe si es la contraseña, el "
        "permiso, el inquilino o el reloj, así que lo prueba todo y acaba "
        "pidiendo permisos de administrador global «para descartar» — que es "
        "como una integración acaba con más permisos de los que necesita.\n\n"
        "Aquí se dice qué alcance concreto falta, o que la credencial caducó, o "
        "que es una política del inquilino del cliente que no se arregla desde "
        "el CRM."
    ),
)
def diagnostico(cuerpo: DiagnosticoIn, principal: AutenticadoDep) -> Any:
    return sop.diagnosticar(
        codigo=cuerpo.codigo,
        alcances_concedidos=cuerpo.alcances_concedidos,
        alcances_necesarios=cuerpo.alcances_necesarios,
        mensaje_del_proveedor=cuerpo.mensaje_del_proveedor,
    )


@router_suites.get(
    "/baja/{motivo}",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué se queda en el CRM y qué desaparece al darse de baja",
    description=(
        "**Las actividades se quedan y la copia de su agenda se va.** Las "
        "primeras son el registro de la empresa —quién habló con qué cliente y "
        "cuándo— y borrarlas dejaría a la compañía sin su historia comercial; la "
        "segunda era suya.\n\n"
        "Y la suscripción **se borra también en el proveedor**: quitarla solo de "
        "este lado deja al proveedor mandando avisos de un buzón que ya nadie "
        "atiende, y al CRM con permiso para leerlo."
    ),
)
def baja(motivo: str, principal: AutenticadoDep) -> Any:
    return sop.plan_de_baja(motivo=motivo)


# ── Motor externo de compensación (CRM-03.02.03.04) ───────────────────────

# ── Contactos, tareas, notas, ficheros y enlaces de reunión ──────────────
#
# Nueve decisiones que estaban escritas, probadas y **sin una sola puerta**.
# Son funciones puras —reciben lo que hay en los dos lados y dicen qué hacer—
# y por eso se exponen como se expone `/telefonia/identificar`: quien integra
# pregunta «¿qué harías?» y se queda con la respuesta y con su motivo.
#
# Lo que estas rutas NO hacen, y conviene que quede dicho: no sincronizan. No
# hay todavía ningún motor que las llame en bucle; eso es una decisión —cada
# cuánto, con qué configuración y dónde van los resultados— y no se inventa
# aquí. Lo que sí hay es que la decisión deja de estar encerrada en el módulo.


class ContactosQueSubenIn(BaseModel):
    contactos_del_crm: list[dict[str, Any]] = Field(default_factory=list)
    solo_relacionados: bool = Field(
        True,
        description=(
            "Subirle los cuarenta mil del CRM llena su agenda de gente que no "
            "conoce, y lo primero que hace cualquiera entonces es desconectar "
            "la integración — con lo que se pierde también lo que sí servía."
        ),
    )


class ContactosQueEntranIn(BaseModel):
    contactos_del_proveedor: list[dict[str, Any]] = Field(default_factory=list)
    correos_conocidos: list[str] = Field(default_factory=list)


class CampoIn(BaseModel):
    campo: str
    valor_crm: Any = None
    valor_proveedor: Any = None
    origen: str
    mas_reciente: str = "crm"


class TareaIn(BaseModel):
    en_el_crm: dict[str, Any] | None = None
    en_el_proveedor: dict[str, Any] | None = None
    ultima_sincronizacion: datetime | None = None


class NotaIn(BaseModel):
    objeto: str
    objeto_id: UUID
    proveedor: str
    referencia: str
    titulo: str
    copiar_contenido: bool = Field(
        False,
        description=(
            "Copiar la página de un cuaderno al CRM duplica el dato y queda " "vieja el mismo día."
        ),
    )


class ResolverNotaIn(BaseModel):
    referencia: str
    tiene_acceso: bool
    existe: bool


class FicheroIn(BaseModel):
    objeto: str
    objeto_id: UUID
    proveedor: str
    referencia: str
    nombre: str
    tamano_bytes: int | None = None


class EstadoEnlaceIn(BaseModel):
    existe: bool
    tiene_acceso: bool
    nombre: str


class EnlaceReunionIn(BaseModel):
    enlace: str
    destino: str


@router_suites.post(
    "/contactos/que-suben",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué contactos del CRM van a la agenda del usuario",
)
def contactos_que_suben(cuerpo: ContactosQueSubenIn, principal: AutenticadoDep) -> Any:
    return sur.que_contactos_suben(
        contactos_del_crm=cuerpo.contactos_del_crm,
        solo_relacionados=cuerpo.solo_relacionados,
    )


@router_suites.post(
    "/contactos/que-entran",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué contactos de la agenda entran al CRM",
    description=(
        "La agenda de un comercial tiene a su médico, a su hermana y a tres "
        "antiguos compañeros. Volcarla es meter datos personales de gente que "
        "no es ni cliente ni usuaria, sin base legal y sin que nadie se lo haya "
        "preguntado."
    ),
)
def contactos_que_entran(cuerpo: ContactosQueEntranIn, principal: AutenticadoDep) -> Any:
    return sur.que_contactos_entran(
        contactos_del_proveedor=cuerpo.contactos_del_proveedor,
        correos_conocidos=cuerpo.correos_conocidos,
    )


@router_suites.post(
    "/contactos/campo",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué valor gana cuando los dos lados discrepan",
)
def resolver_campo(cuerpo: CampoIn, principal: AutenticadoDep) -> Any:
    return sur.resolver_campo(
        campo=cuerpo.campo,
        valor_crm=cuerpo.valor_crm,
        valor_proveedor=cuerpo.valor_proveedor,
        origen=cuerpo.origen,
        mas_reciente=cuerpo.mas_reciente,
    )


@router_suites.post(
    "/tareas/sincronizar",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué hacer con una tarea que está en los dos sitios",
    description=(
        "Lo que la gente espera es que cerrarla en un sitio la cierre en el "
        "otro. Lo que **no** espera es que borrarla en su móvil borre la "
        "actividad del CRM que otros han comentado: un borrado en el proveedor "
        "no borra aquí."
    ),
)
def sincronizar_tarea(cuerpo: TareaIn, principal: AutenticadoDep) -> Any:
    return sur.sincronizar_tarea(
        en_el_crm=cuerpo.en_el_crm,
        en_el_proveedor=cuerpo.en_el_proveedor,
        ultima_sincronizacion=cuerpo.ultima_sincronizacion,
    )


@router_suites.post(
    "/notas/vincular",
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Enlazar una nota del proveedor a un registro",
    description=(
        "Va **por referencia**: el permiso lo resuelve el proveedor con la "
        "identidad de quien mira, así que quien no tiene acceso ve que no lo "
        "tiene, no el contenido."
    ),
)
def vincular_nota(cuerpo: NotaIn, principal: AutenticadoDep) -> Any:
    return sur.vincular_nota(
        objeto=cuerpo.objeto,
        objeto_id=cuerpo.objeto_id,
        proveedor=cuerpo.proveedor,
        referencia=cuerpo.referencia,
        titulo=cuerpo.titulo,
        copiar_contenido=cuerpo.copiar_contenido,
    )


@router_suites.post(
    "/notas/resolver",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué enseñar de una nota enlazada",
)
def resolver_nota(cuerpo: ResolverNotaIn, principal: AutenticadoDep) -> Any:
    return sur.resolver_nota(
        referencia=cuerpo.referencia, tiene_acceso=cuerpo.tiene_acceso, existe=cuerpo.existe
    )


@router_suites.post(
    "/ficheros/vincular",
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Enlazar un fichero del proveedor a un registro",
    description=(
        "Por referencia y no copiando: copiar rompe la promesa de «bórralo y "
        "desaparece». Si el cliente borra el documento en su Drive y el CRM "
        "tiene una copia, sigue ahí."
    ),
)
def vincular_fichero(cuerpo: FicheroIn, principal: AutenticadoDep) -> Any:
    return sur.vincular_fichero(
        objeto=cuerpo.objeto,
        objeto_id=cuerpo.objeto_id,
        proveedor=cuerpo.proveedor,
        referencia=cuerpo.referencia,
        nombre=cuerpo.nombre,
        tamano_bytes=cuerpo.tamano_bytes,
    )


@router_suites.post(
    "/ficheros/estado",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué enseñar de un fichero enlazado",
)
def estado_del_enlace(cuerpo: EstadoEnlaceIn, principal: AutenticadoDep) -> Any:
    return sur.estado_del_enlace(
        existe=cuerpo.existe, tiene_acceso=cuerpo.tiene_acceso, nombre=cuerpo.nombre
    )


@router_suites.post(
    "/reuniones/enlace",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Si este enlace de reunión puede ir por ese canal",
    description=(
        "El enlace de una reunión **es una credencial**: quien lo tiene entra. "
        "No viaja en una notificación push ni en una página pública."
    ),
)
def enlace_de_reunion(cuerpo: EnlaceReunionIn, principal: AutenticadoDep) -> Any:
    return sur.enlace_para(enlace=cuerpo.enlace, destino=cuerpo.destino)


# ── Operar la suite: lo que decide si sigue viva a los seis meses ─────────
#
# Casi nada de esto falla: **se degrada en silencio**. Una suscripción que
# caduca, un proveedor que corta la cuota, un buzón que lleva una semana sin
# credencial. Nada de eso da un error rojo: el CRM se queda quieto y la gente
# deja de fiarse sin saber por qué. Estas ocho decisiones estaban escritas,
# probadas y sin que las llamara nadie.


class AntesDeSincronizarIn(BaseModel):
    usuario_id: UUID
    perfil: str
    recurso: str
    sentido: str = "leer"
    alcances_concedidos: list[str] = Field(default_factory=list)
    alcances_necesarios: list[str] = Field(default_factory=list)


@router_suites.post(
    "/antes-de-sincronizar",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Las dos comprobaciones que van antes de cada vuelta",
    description=(
        "**Antes de cada sincronización, no al conectar.** Comprobar el "
        "consentimiento sólo al conectar deja seguir leyendo el buzón de alguien "
        "que lo revocó ayer, y lo que ve esa persona es que su revocación no "
        "sirvió de nada.\n\n"
        "Y los alcances **antes de llamar, no después de fallar**: llamar sin el "
        "permiso y esperar el 403 gasta una petición de la cuota del tenant para "
        "averiguar algo que ya se sabía."
    ),
)
def antes_de_sincronizar(cuerpo: AntesDeSincronizarIn, db: DbDep, principal: AutenticadoDep) -> Any:
    # Los alcances PRIMERO: si faltan, no hace falta ir a la base a mirar el
    # consentimiento, y el error que interesa es el que dice qué permiso falta.
    sop.exigir_alcances(
        concedidos=cuerpo.alcances_concedidos, necesarios=cuerpo.alcances_necesarios
    )
    consentimiento = su.exigir_consentimiento(
        db,
        principal.tenant_id,
        usuario_id=cuerpo.usuario_id,
        perfil_nombre=cuerpo.perfil,
        recurso=cuerpo.recurso,
        sentido=cuerpo.sentido,
    )
    return {
        "se_puede": True,
        "consentimiento_id": str(consentimiento.id),
        "alcances_concedidos": list(consentimiento.alcances or []),
        "porque": (
            "Hay consentimiento vivo para este recurso y este sentido, y los "
            "alcances necesarios están concedidos."
        ),
    }


@router_suites.post(
    "/mantenimiento",
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Caer al sondeo lo que ha caducado y avisar de lo que va a caducar",
    description=(
        "Una suscripción que caduca **no da ningún error**: deja de llegar lo que "
        "llegaba, el CRM se queda quieto y el usuario lo descubre cuando echa de "
        "menos una cita. Caer al sondeo es la decisión que separa una integración "
        "que se degrada de una que se para — y se marca, porque sondear cada diez "
        "minutos no es enterarse al instante y el usuario tiene derecho a saber "
        "por qué su cita tarda.\n\n"
        "Corre sola cada tanto; esta ruta es para forzarla y para poder verla."
    ),
)
def mantenimiento(uow: UowDep) -> Any:
    return su.mantener_suscripciones(uow)


@router_suites.get(
    "/credenciales/salud",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué credenciales van a dejar de funcionar, y cuáles se romperán solas",
    description=(
        "Una credencial **sin refresco y con caducidad** es una bomba de "
        "relojería: funciona meses y un martes deja de entrar el correo de veinte "
        "personas a la vez. Se dice ahora, no el martes.\n\n"
        "Sale también lo que **no es fiable**: de una credencial de la que no "
        "consta caducidad no se sabe que esté bien, se sabe que no está medida — y "
        "tratarla como buena es cómo se llega a ese martes."
    ),
)
def salud_credenciales(db: DbDep, principal: AutenticadoDep) -> Any:
    return su.salud_de_las_credenciales(db, principal.tenant_id)


class ReglasIn(BaseModel):
    del_tenant: dict[str, Any] = Field(default_factory=dict)
    del_usuario: dict[str, Any] | None = None


@router_suites.post(
    "/reglas",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué entra de verdad, juntando la política de la empresa y la preferencia de la persona",
    description=(
        "**La del usuario sólo puede estrechar, nunca ensanchar.** Si pudiera "
        "ensancharla, la política de la empresa sería una sugerencia: bastaría con "
        "que una persona marcara «traerlo todo» para que entrara su buzón entero, "
        "que es precisamente lo que el tenant había decidido que no.\n\n"
        "Y lo que nunca entra no entra: privados, carpetas personales y "
        "borradores. No es una casilla, porque una casilla acaba desmarcada."
    ),
)
def reglas(cuerpo: ReglasIn, principal: AutenticadoDep) -> Any:
    return sop.combinar_reglas(del_tenant=cuerpo.del_tenant, del_usuario=cuerpo.del_usuario)


class ImportacionIn(BaseModel):
    formato: str = Field(..., examples=["vcard"])
    filas: list[dict[str, Any]] = Field(default_factory=list)


@router_suites.post(
    "/importacion/comprobar",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué entraría y qué no de un fichero estándar, antes de importarlo",
    description=(
        "Se enseña primero y se importa después. Una importación que se ejecuta y "
        "luego cuenta lo que hizo obliga a deshacer a mano lo que no debía entrar, "
        "y **deshacer a mano una importación de diez mil filas no lo hace nadie**: "
        "se queda."
    ),
)
def comprobar_importacion(cuerpo: ImportacionIn, principal: AutenticadoDep) -> Any:
    return sop.comprobar_importacion(formato=cuerpo.formato, filas=cuerpo.filas)


class CuentaIn(BaseModel):
    direccion_del_proveedor: str
    usuarios: list[dict[str, Any]] = Field(default_factory=list)


@router_suites.post(
    "/cuenta/resolver",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="A qué usuario del CRM corresponde una cuenta de la suite",
    description=(
        "Los **alias** son el fallo típico: la misma persona manda desde `j.perez@` "
        "y desde `juan.perez@`, y si cada uno se resuelve a un usuario distinto, la "
        "misma conversación aparece dos veces en la ficha atribuida a dos "
        "comerciales.\n\n"
        "Y un **buzón compartido no tiene dueño**: `info@` o `ventas@` es del "
        "equipo. Atribuirlo a quien lo conectó pone en su nombre correos que no "
        "escribió, y eso acaba en la comisión de alguien."
    ),
)
def resolver_cuenta(cuerpo: CuentaIn, principal: AutenticadoDep) -> Any:
    return sop.resolver_cuenta(
        direccion_del_proveedor=cuerpo.direccion_del_proveedor, usuarios=cuerpo.usuarios
    )


class ConversacionIn(BaseModel):
    objeto: str
    objeto_id: UUID
    proveedor: str
    referencia: str
    exportable: bool = False
    resumen: str = ""


@router_suites.post(
    "/conversaciones/vincular",
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Enlazar un hilo de chat a un registro, por referencia",
    description=(
        "Un hilo de chat corporativo tiene de todo: la negociación, el precio y el "
        "comentario que alguien hizo sobre un compañero. **Copiarlo al CRM mete "
        "todo eso** donde lo ve quien tenga permiso de lectura, que no es la gente "
        "que estaba en el hilo."
    ),
)
def vincular_conversacion(cuerpo: ConversacionIn, principal: AutenticadoDep) -> Any:
    return sop.vincular_conversacion(
        objeto=cuerpo.objeto,
        objeto_id=cuerpo.objeto_id,
        proveedor=cuerpo.proveedor,
        referencia=cuerpo.referencia,
        exportable=cuerpo.exportable,
        resumen=cuerpo.resumen,
    )


router_compensacion = APIRouter(prefix="/compensacion", tags=["compensación"])


class HechoIn(BaseModel):
    tipo: str
    referencia: str
    fecha: date
    importe: Decimal
    moneda: str = "EUR"
    reparto: list[dict[str, Any]] = Field(default_factory=list)
    datos: dict[str, Any] = Field(default_factory=dict)


class ConciliarIn(BaseModel):
    hechos_enviados: list[dict[str, Any]] = Field(default_factory=list)
    calculos_recibidos: list[dict[str, Any]] = Field(default_factory=list)


@router_compensacion.post(
    "/hecho",
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Componer el hecho que se manda al motor de comisiones",
    description=(
        "Se manda **el hecho, no la comisión**. Si el CRM enviara un importe ya "
        "calculado «para ayudar», habría dos cálculos y la nómina se haría con el "
        "que no es.\n\n"
        "El reparto sí va —es información del CRM, que es quien sabe quién vendió "
        "qué— y tiene que sumar 100: un descuadre aquí se convierte en una nómina "
        "mal calculada."
    ),
)
def hecho_de_compensacion(cuerpo: HechoIn, principal: AutenticadoDep) -> Any:
    from services.integration import compensacion

    return compensacion.componer_hecho(
        tipo=cuerpo.tipo,
        referencia=cuerpo.referencia,
        fecha=cuerpo.fecha,
        importe=cuerpo.importe,
        moneda=cuerpo.moneda,
        reparto=cuerpo.reparto,
        datos=cuerpo.datos,
    )


@router_compensacion.post(
    "/conciliar",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué se mandó y no ha vuelto calculado",
    description=(
        "Ahí está el problema de verdad: un hecho que se pierde por el camino no "
        "da ningún error — simplemente esa venta no aparece en la comisión de "
        "nadie, y lo descubre el comercial al mirar su nómina.\n\n"
        "Se comprueba antes de cerrar el periodo, que es el único momento en el "
        "que todavía se puede arreglar sin que duela."
    ),
)
def conciliar(cuerpo: ConciliarIn, principal: AutenticadoDep) -> Any:
    from services.integration import compensacion

    return compensacion.conciliar(
        hechos_enviados=cuerpo.hechos_enviados, calculos_recibidos=cuerpo.calculos_recibidos
    )


class CalculoIn(BaseModel):
    referencia: str
    periodo: str
    lineas: list[dict[str, Any]] = Field(default_factory=list)
    cerrado: bool = False


@router_compensacion.post(
    "/calculo",
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Recoger lo que ha calculado el motor de comisiones, tal cual",
    description=(
        "**No se recalcula ni se redondea.** Enseñar en el CRM una comisión "
        "distinta de la que se va a cobrar es la forma más rápida de que nadie se "
        "crea ninguna de las dos, y de que el comercial se haga su propia hoja de "
        "cálculo — que es donde empieza cualquier discusión de comisiones.\n\n"
        "Un periodo **no cerrado** se enseña como provisional: es lo que evita la "
        "conversación de «pero si el CRM decía otra cosa» a final de mes."
    ),
)
def recibir_calculo(cuerpo: CalculoIn, principal: AutenticadoDep) -> Any:
    from services.integration import compensacion

    return compensacion.recibir_calculo(
        referencia=cuerpo.referencia,
        lineas=cuerpo.lineas,
        periodo=cuerpo.periodo,
        cerrado=cuerpo.cerrado,
    )


class ClawbackIn(BaseModel):
    referencia: str
    importe_original: Decimal
    importe_nuevo: Decimal
    ya_pagada: bool = False
    motivo: str = Field(..., min_length=1)


@router_compensacion.post(
    "/clawback",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué hacer cuando un cierre cambia después de pagada la comisión",
    description=(
        "Se llama **clawback** y es una conversación, no un ajuste automático. "
        "Quitarle dinero a alguien de la próxima nómina sin decírselo es lo que "
        "hace que un equipo comercial deje de fiarse del sistema entero — y "
        "entonces cada uno lleva su propia cuenta.\n\n"
        "El motivo es obligatorio por lo mismo: «ajuste» no es una explicación que "
        "se le pueda dar a quien ve menos dinero en su nómina."
    ),
)
def clawback(cuerpo: ClawbackIn, principal: AutenticadoDep) -> Any:
    from services.integration import compensacion

    return compensacion.cambio_despues_de_pagar(
        referencia=cuerpo.referencia,
        importe_original=cuerpo.importe_original,
        importe_nuevo=cuerpo.importe_nuevo,
        ya_pagada=cuerpo.ya_pagada,
        motivo=cuerpo.motivo,
    )


# ── Telefonía conectada al CRM (CRM-04.02.01.05) ──────────────────────────

router_telefonia = APIRouter(prefix="/telefonia", tags=["telefonía"])


def telefonia_eventos() -> tuple[str, ...]:
    """Los eventos admitidos, **del módulo**: repetirlos aquí es cómo acaban
    diciendo cosas distintas la documentación y la validación."""
    from services.integration.telefonia import EVENTOS

    return EVENTOS


def telefonia_resultados() -> tuple[str, ...]:
    from services.integration.telefonia import RESULTADOS

    return RESULTADOS


class IdentificarIn(BaseModel):
    numero: str
    candidatos: list[dict[str, Any]] = Field(default_factory=list)


class TransferirIn(BaseModel):
    a: str
    resumen: str = ""
    contacto_id: UUID | None = None
    caso_id: UUID | None = None
    lo_ya_hablado: list[str] = Field(default_factory=list)


class PantallaIn(BaseModel):
    """Lo que la centralita sabe cuando empieza a sonar."""

    identificacion: dict[str, Any] = Field(
        default_factory=dict, description="Lo que devolvió `/identificar`."
    )
    datos_del_ivr: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Lo que el cliente ya tecleó. Volver a pedírselo al descolgar es la "
            "forma más rápida de que se enfade antes de empezar."
        ),
    )
    ultimo_caso: dict[str, Any] | None = None
    ultima_interaccion: dict[str, Any] | None = None


class LlamadaIn(BaseModel):
    """El parte de una llamada, la haya cogido alguien o no."""

    evento: str = Field(description=" | ".join(telefonia_eventos()))
    resultado: str = Field(description=" | ".join(telefonia_resultados()))
    numero: str
    duracion_s: int = Field(0, ge=0)
    espera_s: int = Field(0, ge=0)
    contacto_id: UUID | None = None
    grabacion_ref: str = ""


@router_telefonia.post(
    "/pantalla",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué se le pone delante al agente antes de descolgar",
    description=(
        "Lo que el cliente **ya tecleó en el IVR viaja con la llamada**: si "
        "marcó su número de pedido, volver a pedírselo al descolgar es la forma "
        "más rápida de que se enfade antes de empezar.\n\n"
        "Y lo que se enseña es **lo último que le pasó**, no su ficha entera: un "
        "agente tiene cuatro segundos mientras suena, y un panel con veinte "
        "campos no se lee en cuatro segundos.\n\n"
        "Esta ruta faltaba: la función estaba escrita y probada, y la centralita "
        "no tenía dónde pedirla."
    ),
)
def pantalla(cuerpo: PantallaIn, principal: AutenticadoDep) -> Any:
    from services.integration import telefonia

    return telefonia.pantalla_al_sonar(
        identificacion=cuerpo.identificacion,
        datos_del_ivr=cuerpo.datos_del_ivr,
        ultimo_caso=cuerpo.ultimo_caso,
        ultima_interaccion=cuerpo.ultima_interaccion,
    )


@router_telefonia.post(
    "/llamadas",
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Dejar constancia de una llamada, la cojan o no",
    description=(
        "**Las perdidas y las abandonadas son las que más dicen**: una llamada "
        "que nadie cogió es un cliente que lo intentó, y si no consta, el panel "
        "enseña un servicio impecable construido con las llamadas que sí se "
        "atendieron.\n\n"
        "Se distinguen **perdida** —sonó y nadie la cogió— de **abandonada** —la "
        "colgaron en la cola antes de sonar—: confundirlas oculta un problema de "
        "enrutado detrás de uno de plantilla.\n\n"
        "Esta ruta faltaba: la centralita no tenía dónde dar el parte."
    ),
)
def registrar_llamada(cuerpo: LlamadaIn, principal: AutenticadoDep) -> Any:
    from services.integration import telefonia

    return telefonia.registrar_llamada(
        evento=cuerpo.evento,
        resultado=cuerpo.resultado,
        numero=cuerpo.numero,
        duracion_s=cuerpo.duracion_s,
        espera_s=cuerpo.espera_s,
        contacto_id=cuerpo.contacto_id,
        grabacion_ref=cuerpo.grabacion_ref,
    )


@router_telefonia.post(
    "/identificar",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Quién llama, y con qué confianza",
    description=(
        "Tres respuestas distintas y ninguna se redondea: **una ficha**, "
        "**varias** y **ninguna**. Abrir la primera de tres «porque suele ser "
        "esa» hace que el agente salude por el nombre equivocado, que es peor que "
        "no saludar por ninguno.\n\n"
        "Se compara por el final del número a propósito: el mismo teléfono "
        "aparece como `+34600…`, `0034600…` y `600…` según quién lo escribiera, y "
        "comparar literalmente hace que no salte justo con los clientes de toda "
        "la vida, que son los que están mal escritos."
    ),
)
def identificar(cuerpo: IdentificarIn, principal: AutenticadoDep) -> Any:
    from services.integration import telefonia

    return telefonia.identificar(numero=cuerpo.numero, candidatos=cuerpo.candidatos)


@router_telefonia.post(
    "/transferir",
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Transferir con el contexto dentro",
    description=(
        "El resumen es obligatorio: pasar la llamada sin lo que ya se ha hablado "
        "obliga al cliente a empezar de cero, y esa es literalmente la queja "
        "número uno de cualquier servicio de atención. Una transferencia sin "
        "resumen es la que se hace por quitarse la llamada de encima."
    ),
)
def transferir(cuerpo: TransferirIn, principal: AutenticadoDep) -> Any:
    from services.integration import telefonia

    return telefonia.transferir(
        a=cuerpo.a,
        resumen=cuerpo.resumen,
        contacto_id=cuerpo.contacto_id,
        caso_id=cuerpo.caso_id,
        lo_ya_hablado=cuerpo.lo_ya_hablado,
    )


# ── Listados de las sub-colecciones ───────────────────────────────────────
# Mismo agujero que en las colecciones raíz: se podían crear y no se podían
# leer. Un sobre de firma, una tabla del almacén o una predicción que no se
# pueden listar no existen para quien tiene que revisarlos.

montar_listado(
    router_suites,
    modelo=ConsentimientoSuite,
    objeto="consentimiento_suite",
    permiso="integration:read",
    ruta="/consentimiento",
    nombre="Consentimientos de suite",
)
montar_listado(
    router_suites,
    modelo=Conexion,
    objeto="perfil_suite",
    permiso="integration:read",
    ruta="/perfiles",
    nombre="Perfiles de suite",
    # Los perfiles viven en la tabla de conexiones junto a las demás
    # integraciones: sin acotar, este listado devolvería conectores que no
    # tienen nada que ver con productividad.
    filtro=lambda c: c.where(Conexion.config["clase"].astext == "suite_productividad"),
)


ROUTERS_SUITES = [router_suites, router_compensacion, router_telefonia]
