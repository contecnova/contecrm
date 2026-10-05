"""API de conocimiento y portal de cliente
(CRM-04.03.01, CRM-04.03.02, CRM-00.05.01.10).
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha, montar_listado
from crmcore.http.portal_deps import PortalDep
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from services.service import conocimiento as kb
from services.service import portal as prt
from services.service.conocimiento import Articulo
from services.service.portal import AccesoPortal, HiloComunidad

router_conocimiento = APIRouter(prefix="/conocimiento", tags=["conocimiento"])
router_portal = APIRouter(prefix="/portal", tags=["portal de cliente"])
router_comunidad = APIRouter(prefix="/comunidad", tags=["portal de cliente"])


# ── Artículos (CRM-04.03.01.01, .02, .03) ─────────────────────────────────


class CrearArticulo(BaseModel):
    clave: str = Field(max_length=120)
    titulo: str = Field(max_length=300)
    cuerpo: str = ""
    resumen: str = ""
    idioma: str = Field("es", max_length=10)
    audiencia: str = Field("interno", description=" | ".join(kb.AUDIENCIAS))
    etiquetas: list[str] = Field(default_factory=list)
    canales: list[str] = Field(default_factory=list)
    revisar_el: date | None = None
    vigente_hasta: date | None = None


@router_conocimiento.post(
    # En `/articulos`, la misma ruta que los lista. Estaba en `""`, de modo que
    # la colección se leía en un sitio y se creaba en otro: el front pedía el
    # alta donde estaba el listado, no había POST ahí y el botón «Nuevo» de la
    # base de conocimiento no creaba nada.
    "/articulos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("knowledge:write"))],
    summary="Crear un artículo",
    description=(
        "Nace **en borrador y con audiencia interna**, y las dos cosas son "
        "deliberadas: el fallo caro de una base de conocimiento —publicar hacia "
        "fuera un procedimiento interno con nombres de clientes dentro— ocurre "
        "siempre por omisión, nunca por decisión."
    ),
)
def crear(datos: CrearArticulo, uow: UowDep, principal: AutenticadoDep) -> Any:
    cuerpo = datos.model_dump()
    articulo, version = kb.crear_articulo(
        uow,
        clave=cuerpo.pop("clave"),
        titulo=cuerpo.pop("titulo"),
        cuerpo=cuerpo.pop("cuerpo"),
        resumen=cuerpo.pop("resumen"),
        idioma=cuerpo.pop("idioma"),
        audiencia=cuerpo.pop("audiencia"),
        autor_id=principal.id,
        **cuerpo,
    )
    return {"id": str(articulo.id), "clave": articulo.clave, "version": version.version}


class NuevaVersion(BaseModel):
    titulo: str = Field(max_length=300)
    cuerpo: str
    resumen: str = ""
    notas_cambio: str = ""


@router_conocimiento.post(
    "/{articulo_id}/versiones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("knowledge:write"))],
    summary="Escribir una versión nueva",
    description=(
        "No se edita sobre lo publicado: cada cambio es una versión. Editar en "
        "caliente hace que un texto a medias esté en el portal del cliente "
        "mientras alguien lo escribe, y deja sin forma de volver a lo anterior."
    ),
)
def nueva_version(
    articulo_id: UUID, datos: NuevaVersion, uow: UowDep, principal: AutenticadoDep
) -> Any:
    fila = kb.nueva_version(
        uow,
        articulo_id,
        titulo=datos.titulo,
        cuerpo=datos.cuerpo,
        resumen=datos.resumen,
        notas_cambio=datos.notas_cambio,
        autor_id=principal.id,
    )
    return {"version": fila.version}


class Publicar(BaseModel):
    version: int | None = None
    audiencia: str | None = None


@router_conocimiento.post(
    "/{articulo_id}/publicar",
    dependencies=[Depends(exige_permiso("knowledge:write"))],
    summary="Publicar una versión",
    description=(
        "Dos comprobaciones que no son formalismo:\n\n"
        "**Sin aprobación distinta del autor no sale hacia el cliente.** Quien "
        "escribe un artículo no es quien mejor detecta que lleva dentro el nombre "
        "de un cliente.\n\n"
        "**Sin fecha de revisión no sale hacia fuera.** Sin ella nadie vuelve a "
        "mirarlo, y es el que sigue apareciendo tres años después describiendo "
        "una versión que ya no existe."
    ),
)
def publicar(articulo_id: UUID, datos: Publicar, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = kb.publicar(
        uow,
        articulo_id,
        version=datos.version,
        aprobada_por=principal.id,
        audiencia=datos.audiencia,
    )
    return {"id": str(fila.id), "estado": fila.estado, "version": fila.version_publicada}


class Obsoleto(BaseModel):
    motivo: str = Field(min_length=1, max_length=500)
    sustituye_a: UUID | None = None


@router_conocimiento.post(
    "/{articulo_id}/obsoleto",
    dependencies=[Depends(exige_permiso("knowledge:write"))],
    summary="Retirar un artículo sin borrarlo",
    description=(
        "Borrar rompe los enlaces que alguien pegó en un correo hace dos años, y "
        "quien los sigue recibe un «no existe» que parece un error del sistema. "
        "Marcado como obsoleto se puede seguir abriendo con un aviso, y "
        "apuntando al que lo sustituye."
    ),
)
def obsoleto(articulo_id: UUID, datos: Obsoleto, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = kb.marcar_obsoleto(uow, articulo_id, motivo=datos.motivo, sustituye_a=datos.sustituye_a)
    return {"id": str(fila.id), "estado": fila.estado}


class Traducir(BaseModel):
    idioma: str = Field(max_length=10)
    titulo: str = Field(max_length=300)
    cuerpo: str
    resumen: str = ""


@router_conocimiento.post(
    "/{articulo_id}/traducciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("knowledge:write"))],
    summary="Traducir el artículo",
)
def traducir(articulo_id: UUID, datos: Traducir, uow: UowDep, principal: AutenticadoDep) -> Any:
    traduccion, _ = kb.traducir(
        uow,
        articulo_id,
        idioma=datos.idioma,
        titulo=datos.titulo,
        cuerpo=datos.cuerpo,
        resumen=datos.resumen,
    )
    return {"id": str(traduccion.id), "idioma": traduccion.idioma}


@router_conocimiento.get(
    "/{articulo_id}/traducciones",
    dependencies=[Depends(exige_permiso("knowledge:read"))],
    summary="Qué traducciones hay y cuáles se han quedado atrás",
    description=(
        "«Desincronizada» se dice explícitamente en vez de dejar que se note: una "
        "traducción vieja no falla, simplemente miente, y el cliente que la lee "
        "no tiene forma de saberlo."
    ),
)
def traducciones(articulo_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return kb.estado_de_traducciones(db, principal.tenant_id, articulo_id)


# ── KCS (CRM-04.03.01.05) ─────────────────────────────────────────────────


class DesdeCaso(BaseModel):
    clave: str = Field(max_length=120)
    titulo: str = ""
    cuerpo: str = ""


@router_conocimiento.post(
    "/desde-caso/{caso_id}",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("knowledge:write"))],
    summary="Crear un artículo desde la resolución de un caso",
    description=(
        "El momento importa: se escribe **cuando se resuelve**, con el problema "
        "fresco y por quien lo resolvió. Pedirlo después, en una sesión "
        "dedicada, es como no pedirlo.\n\n"
        "Nace en borrador e **interno** aunque venga de un caso resuelto: el "
        "texto de una resolución lleva casi siempre el nombre del cliente, su "
        "configuración y a veces sus credenciales."
    ),
)
def desde_caso(caso_id: UUID, datos: DesdeCaso, uow: UowDep, principal: AutenticadoDep) -> Any:
    articulo, _ = kb.desde_caso(
        uow, caso_id, clave=datos.clave, titulo=datos.titulo, cuerpo=datos.cuerpo
    )
    return {"id": str(articulo.id), "clave": articulo.clave, "estado": articulo.estado}


@router_conocimiento.post(
    "/{articulo_id}/usado-en/{caso_id}",
    dependencies=[Depends(exige_permiso("knowledge:read"))],
    summary="Registrar que este artículo resolvió un caso",
    description=(
        "Es la métrica que de verdad dice si sirve: un artículo muy valorado que "
        "nadie usa en un caso es un artículo bonito."
    ),
)
def usado_en(articulo_id: UUID, caso_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = kb.enlazar_a_caso(uow, articulo_id, caso_id)
    return {"id": str(fila.id), "usos_en_caso": fila.usos_en_caso}


# ── Valoración y eficacia (CRM-04.03.01.06) ───────────────────────────────


class Valorar(BaseModel):
    util: bool
    comentario: str = ""
    votante: str = Field("", max_length=120)


@router_conocimiento.post(
    "/{articulo_id}/valorar",
    summary="Votar si el artículo ha servido",
    description=(
        "Un voto **por votante**, no uno por pulsación: sin eso el mismo "
        "visitante puede votar cien veces y la métrica deja de significar nada — "
        "y el primero que lo descubra decidirá qué artículos parecen buenos.\n\n"
        "El comentario es lo único que dice **por qué** no sirve; el pulgar abajo "
        "solo dice que no."
    ),
)
def valorar(articulo_id: UUID, datos: Valorar, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = kb.valorar(
        uow,
        articulo_id,
        util=datos.util,
        votante=datos.votante or str(principal.id),
        comentario=datos.comentario,
    )
    return {"id": str(fila.id), "util": fila.util}


@router_conocimiento.get(
    "/eficacia",
    dependencies=[Depends(exige_permiso("knowledge:read"))],
    summary="Qué artículos sirven, cuáles estorban y cuáles nadie usa",
    description=(
        "Tres listas para tres decisiones distintas:\n\n"
        "**Dañinos** — muchas visitas y pulgar abajo. Es **peor que no tenerlos**: "
        "el cliente pierde el tiempo y además se queda sin llamar.\n\n"
        "**Huérfanos** — publicados y sin visitas. O no se encuentran o no hacían "
        "falta; en los dos casos ocupan sitio en los resultados.\n\n"
        "**Caducados** — pasada su fecha de revisión. Son los que siguen "
        "describiendo una versión que ya no existe.\n\n"
        "La deflexión se da como **aproximada** a propósito: no se puede "
        "distinguir a quien leyó y le sirvió de quien leyó y se rindió, y "
        "presentarlo como exacto sería inventarse un número que alguien citará."
    ),
)
def eficacia(
    db: DbDep, principal: AutenticadoDep, minimo_vistas: int = Query(20, ge=1, le=10_000)
) -> Any:
    return kb.eficacia(db, principal.tenant_id, minimo_vistas=minimo_vistas)


# ── API de conocimiento (CRM-04.03.01.07) ─────────────────────────────────


@router_conocimiento.get(
    "",
    dependencies=[Depends(exige_permiso("knowledge:read"))],
    summary="Buscar artículos para una audiencia",
    description=(
        "El filtro por audiencia se aplica **en el servidor** y no por un "
        "parámetro de quien llama: si dependiera del llamante, bastaría una ruta "
        "nueva que se olvidara de pasarlo para que el portal público sirviera los "
        "procedimientos internos.\n\n"
        "Es la misma API que alimenta portales, chatbots y agentes externos: se "
        "les pasa la audiencia que les corresponde y no ven nada por encima."
    ),
)
def buscar(
    db: DbDep,
    principal: AutenticadoDep,
    texto: str = Query("", max_length=200),
    audiencia: str = Query("interno", description=" | ".join(kb.AUDIENCIAS)),
    canal: str = Query("", max_length=40),
    idioma: str = Query("", max_length=10),
    limite: int = Query(20, ge=1, le=100),
) -> Any:
    return kb.buscar(
        db,
        principal.tenant_id,
        texto=texto,
        audiencia=audiencia,
        canal=canal,
        idioma=idioma,
        limite=limite,
    )


@router_conocimiento.get(
    "/{articulo_id}",
    dependencies=[Depends(exige_permiso("knowledge:read"))],
    summary="Leer un artículo",
    description=(
        "Un artículo fuera de la audiencia devuelve **404 y no 403**: un 403 "
        "confirma que existe, y con eso se puede recorrer el catálogo interno "
        "preguntando por identificadores."
    ),
)
def leer(
    articulo_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    audiencia: str = Query("interno"),
) -> Any:
    salida = kb.leer(db, principal.tenant_id, articulo_id, audiencia=audiencia)
    kb.anotar_vista(db, principal.tenant_id, articulo_id)
    return salida


# ── Portal: identidad (CRM-04.03.02.05, CRM-00.05.01.10) ──────────────────


class DarAcceso(BaseModel):
    contacto_id: UUID
    email: str = Field(max_length=320)
    cuenta_id: UUID | None = None
    nivel: str = Field("propio", description=" | ".join(prt.NIVELES))
    secciones: list[str] = Field(default_factory=list)


@router_portal.post(
    "/accesos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Dar acceso al portal a un contacto",
    description=(
        "La identidad del cliente **no es la del empleado**: un contacto no tiene "
        "roles del CRM, no cuenta para licencias y su ciclo de vida lo manda la "
        "relación comercial. Reutilizar la tabla de usuarios parece que ahorra "
        "trabajo y deja abierta la puerta a que un contacto acabe con permisos de "
        "empleado porque alguien le asignó un rol por comodidad.\n\n"
        "Nace en el nivel más bajo: eso impide que el técnico que abrió una "
        "incidencia acabe viendo las facturas de su empresa."
    ),
)
def dar_acceso(datos: DarAcceso, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = prt.dar_acceso(
        uow,
        contacto_id=datos.contacto_id,
        email=datos.email,
        cuenta_id=datos.cuenta_id,
        nivel=datos.nivel,
        secciones=datos.secciones,
    )
    return {"id": str(fila.id), "nivel": fila.nivel}


class Revocar(BaseModel):
    motivo: str = ""


@router_portal.post(
    "/accesos/{acceso_id}/revocar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Quitar el acceso al portal",
    description=(
        "Los enlaces pendientes se invalidan **en el acto**: si no, alguien a "
        "quien acaban de retirar el acceso sigue entrando con el correo que "
        "recibió esta mañana, y en la lista figura como revocado."
    ),
)
def revocar(acceso_id: UUID, datos: Revocar, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = prt.revocar_acceso(uow, acceso_id, motivo=datos.motivo)
    return {"id": str(fila.id), "activo": fila.activo}


class PedirEnlace(BaseModel):
    email: str = Field(max_length=320)


@router_portal.post(
    "/enlace",
    summary="Pedir un enlace de acceso",
    description=(
        "La respuesta es **la misma exista o no** ese correo. Distinguirlas "
        "convertiría el portal en un comprobador de qué correos son clientes "
        "nuestros, que es exactamente la lista que quiere un competidor.\n\n"
        "El token se guarda hasheado y caduca pronto: un enlace de acceso viaja "
        "por correo, y el correo se reenvía."
    ),
)
def pedir_enlace(datos: PedirEnlace, uow: UowDep, principal: AutenticadoDep) -> Any:
    enlace, token = prt.emitir_enlace(uow, email=datos.email)
    return {
        "enviado": True,
        # El token va en la respuesta solo para que lo mande quien integre el
        # correo; nunca se enseña al que lo pide.
        "token": token if enlace else "",
    }


class Canjear(BaseModel):
    token: str = Field(min_length=1, max_length=200)


@router_portal.post(
    "/entrar",
    summary="Canjear el enlace y entrar",
    description=(
        "De un solo uso. Un token inexistente, usado o caducado dan **el mismo "
        "error**: distinguirlos le diría a quien prueba si ese enlace existió."
    ),
)
def entrar(datos: Canjear, request: Request, uow: UowDep, principal: AutenticadoDep) -> Any:
    acceso = prt.canjear_enlace(uow, datos.token, ip=request.client.host if request.client else "")
    return {
        "acceso_id": str(acceso.id),
        "contacto_id": str(acceso.contacto_id),
        "nivel": acceso.nivel,
        "secciones": prt.secciones_de(acceso),
    }


# ── El portal visto por el cliente, con su propia sesión ──────────────────
#
# Todo lo de abajo lo llama un empleado: dar acceso, revocarlo, emitir el enlace
# y consultar un acceso concreto. Eso es la administración del portal y está
# bien así.
#
# Lo que sigue es lo otro: que **el cliente entre él**. Sin esto, todas las
# rutas del portal exigían una sesión de empleado, así que quien quisiera un
# portal de verdad tenía que montar un intermediario que guardara credenciales
# de empleado para servir a sus clientes — que no es un portal, es una
# credencial de empleado compartida por internet.


@router_portal.post(
    "/sesion",
    summary="Entrar en el portal con el enlace recibido",
    description=(
        "Canjea el enlace de un solo uso y devuelve la sesión **del portal**: un "
        "token sin permisos del CRM, que por eso no sirve para nada más que "
        "para esto.\n\n"
        "Dura poco y se renueva pidiendo otro enlace: un portal se usa a ratos, "
        "y un token largo en el navegador de un cliente acaba en un correo "
        "reenviado."
    ),
)
def sesion_portal(datos: Canjear, request: Request) -> Any:
    # Sesión de **sistema** y unidad de trabajo propia: quien entra todavía no
    # tiene tenant, y es el enlace el que dice cuál es. Es el mismo patrón que
    # el refresco de sesión del CRM — lo que acota es el secreto, no el tenant.
    from crmcore.db.session import sesion
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.http.portal_deps import emitir_token_portal

    with sesion(sistema=True) as db:
        uow = UnidadDeTrabajo(db=db, tenant_id=None)
        acceso = prt.canjear_enlace(
            uow, datos.token, ip=request.client.host if request.client else ""
        )
        token, dura_s = emitir_token_portal(
            acceso_id=acceso.id,
            tenant_id=acceso.tenant_id,
            nivel=acceso.nivel,
            cuenta_id=acceso.cuenta_id,
        )
        salida = {
            "token": token,
            "caduca_en_s": dura_s,
            "nivel": acceso.nivel,
            "secciones": prt.secciones_de(acceso),
        }
    return salida


def _mi_acceso(db: Any, sesion: Any) -> prt.AccesoPortal:
    return _acceso_de(db, sesion.tenant_id, sesion.acceso_id)


@router_portal.get(
    "/mi/resumen",
    summary="La portada del portal",
    description="Lo mismo que ve el empleado de este acceso, pero pedido por el cliente.",
)
def mi_resumen(db: DbDep, sesion: PortalDep) -> Any:
    return prt.resumen(db, _mi_acceso(db, sesion))


@router_portal.get(
    "/mi/casos",
    summary="Mis casos",
    description=(
        "El filtro va **por el nivel del acceso y en el servidor**: el técnico "
        "ve los suyos y el responsable los de su empresa. Filtrar en el cliente "
        "funciona hasta que alguien mira la respuesta de la API."
    ),
)
def mis_casos(db: DbDep, sesion: PortalDep, limite: int = Query(50, ge=1, le=200)) -> Any:
    acceso = _mi_acceso(db, sesion)
    # LA SECCIÓN SE COMPRUEBA EN EL SERVIDOR. `secciones_de` solo se le contaba
    # al cliente «para que no pinte botones», y el propio módulo avisa de que
    # filtrar en el cliente funciona hasta que alguien mira la respuesta de la
    # API. `exigir_seccion` no la llamaba nadie.
    prt.exigir_seccion(acceso, "casos")
    return prt.mis_casos(db, acceso, limite=limite)


class AbrirPeticion(BaseModel):
    """Lo que el cliente cuenta al abrir una petición.

    Ni contacto ni cuenta: los pone el acceso. Aceptarlos de quien llama
    permitiría abrir casos en nombre de otra empresa, que es la fuga más fácil
    de un portal.
    """

    asunto: str = Field(..., min_length=1, max_length=300)
    descripcion: str = Field("", max_length=20_000)


@router_portal.post(
    "/mi/casos",
    status_code=status.HTTP_201_CREATED,
    summary="Abrir una petición",
    description=(
        "Lo que el cliente abre entra como un caso normal, con su SLA y su "
        "cola. Una petición de portal que fuera a otro sitio sería una bandeja "
        "más que alguien tiene que acordarse de mirar."
    ),
)
def abrir_mi_caso(datos: AbrirPeticion, uow: UowDep, sesion: PortalDep) -> Any:
    acceso = _mi_acceso(uow.db, sesion)
    caso = prt.abrir_caso_desde_portal(
        uow, acceso, asunto=datos.asunto, descripcion=datos.descripcion
    )
    # Solo el identificador y el código: al cliente le sirve para referirse a su
    # petición, y devolver el caso entero le enseñaría los campos internos —cola,
    # prioridad calculada, quién lo lleva— que no son suyos.
    return {"id": str(caso.id), "codigo": caso.codigo, "asunto": caso.asunto}


@router_portal.get(
    "/mi/conversacion",
    summary="Lo que he hablado con vosotros",
    description=(
        "El mismo hilo que ve el agente, **sin las notas internas**. El correo "
        "del lunes y esto de hoy son la misma conversación: es lo que evita "
        "tener que contarlo todo otra vez."
    ),
)
def mi_conversacion(db: DbDep, sesion: PortalDep, limite: int = Query(200, ge=1, le=500)) -> Any:
    return prt.conversacion_del_portal(db, _mi_acceso(db, sesion), limite=limite)


class MensajePortal(BaseModel):
    """Lo que el cliente escribe desde el portal."""

    texto: str = Field(..., min_length=1, max_length=10_000)
    asunto: str = Field("", max_length=300)


@router_portal.post(
    "/mi/conversacion",
    status_code=status.HTTP_201_CREATED,
    summary="Escribir a quien me atiende",
    description=(
        "Entra por la misma conversación omnicanal que el correo, así que "
        "aparece en la consola de agente sin que nadie vigile una bandeja "
        "nueva. Un chat de portal que solo se ve en el portal es un chat que "
        "nadie contesta.\n\n"
        "Si la conversación estaba cerrada, **se reabre**: dejarla cerrada "
        "esconde la respuesta hasta que alguien repase los cerrados, y eso no "
        "lo hace nadie."
    ),
)
def escribir_desde_portal(datos: MensajePortal, uow: UowDep, sesion: PortalDep) -> Any:
    acceso = _mi_acceso(uow.db, sesion)
    return prt.escribir_desde_portal(uow, acceso, texto=datos.texto, asunto=datos.asunto)


# ── Portal: lo que ve el cliente (CRM-04.03.02.01) ────────────────────────


def _acceso_de(db: Any, tenant_id: UUID, acceso_id: UUID) -> prt.AccesoPortal:
    from sqlalchemy import select as _select

    fila = db.execute(
        _select(prt.AccesoPortal).where(
            prt.AccesoPortal.id == acceso_id, prt.AccesoPortal.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if fila is None:
        from crmcore.errors import NoEncontrado

        raise NoEncontrado("Acceso no encontrado", error_code="service.acceso_no_encontrado")
    return fila


@router_portal.get(
    "/accesos/{acceso_id}/resumen",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="La portada del portal, en una llamada",
    description=(
        "Devuelve **datos y no pantallas**: es lo que permite que el cliente "
        "monte su propio portal con su marca sin que nosotros hagamos uno por "
        "cliente.\n\n"
        "Dice qué secciones puede abrir, para que el portal no pinte botones que "
        "después dan 403: un botón que falla al pulsarlo es peor que uno que no "
        "está."
    ),
)
def resumen(acceso_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return prt.resumen(db, _acceso_de(db, principal.tenant_id, acceso_id))


@router_portal.get(
    "/accesos/{acceso_id}/casos",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Los casos que este contacto puede ver",
    description=(
        "El filtro va **en el servidor y por el nivel del acceso**, no por un "
        "parámetro de quien llama. Filtrar en el cliente funciona hasta que "
        "alguien mira la respuesta de la API, y entonces el portal deja de ser un "
        "portal para ser una copia del CRM con un filtro de pantalla."
    ),
)
def casos(
    acceso_id: UUID, db: DbDep, principal: AutenticadoDep, limite: int = Query(50, ge=1, le=200)
) -> Any:
    return prt.mis_casos(db, _acceso_de(db, principal.tenant_id, acceso_id), limite=limite)


class AbrirDesdePortal(BaseModel):
    asunto: str = Field(max_length=300)
    descripcion: str = ""


@router_portal.post(
    "/accesos/{acceso_id}/casos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="El cliente abre un caso desde el portal",
    description=(
        "El contacto y la cuenta los pone **el acceso**, no la petición: "
        "aceptarlos de quien llama permitiría abrir casos en nombre de otra "
        "empresa, que es la fuga más fácil de un portal."
    ),
)
def abrir_caso(
    acceso_id: UUID, datos: AbrirDesdePortal, uow: UowDep, principal: AutenticadoDep
) -> Any:
    caso = prt.abrir_caso_desde_portal(
        uow,
        _acceso_de(uow.db, principal.tenant_id, acceso_id),
        asunto=datos.asunto,
        descripcion=datos.descripcion,
    )
    return {"id": str(caso.id), "codigo": caso.codigo}


# ── Comunidad (CRM-04.03.02.04) ───────────────────────────────────────────


class AbrirHilo(BaseModel):
    acceso_id: UUID
    titulo: str = Field(max_length=300)
    cuerpo: str
    categoria: str = Field("general", max_length=80)


@router_comunidad.post(
    "/hilos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Un cliente publica una pregunta",
    description=(
        "Nace **en moderación**. Un foro de soporte sin moderación previa acaba "
        "con un cliente publicando su clave de licencia, la configuración de su "
        "red o el nombre de su proveedor — y eso, una vez público, ya no se "
        "retira del todo."
    ),
)
def abrir_hilo(datos: AbrirHilo, uow: UowDep, principal: AutenticadoDep) -> Any:
    hilo = prt.abrir_hilo(
        uow,
        _acceso_de(uow.db, principal.tenant_id, datos.acceso_id),
        titulo=datos.titulo,
        cuerpo=datos.cuerpo,
        categoria=datos.categoria,
    )
    return {"id": str(hilo.id), "estado": hilo.estado}


class ResponderHilo(BaseModel):
    cuerpo: str = Field(min_length=1)
    acceso_id: UUID | None = None


@router_comunidad.post(
    "/hilos/{hilo_id}/respuestas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Responder a un hilo",
    description=(
        "Se marca si la respuesta es del fabricante. No es decorativo: en un foro "
        "de soporte, la diferencia entre «lo dice el fabricante» y «lo dice otro "
        "cliente» es toda, y sin marcarla el cliente aplica el consejo de "
        "cualquiera creyendo que es oficial."
    ),
)
def responder_hilo(
    hilo_id: UUID, datos: ResponderHilo, uow: UowDep, principal: AutenticadoDep
) -> Any:
    contacto_id = None
    if datos.acceso_id is not None:
        contacto_id = _acceso_de(uow.db, principal.tenant_id, datos.acceso_id).contacto_id
    fila = prt.responder_hilo(
        uow,
        hilo_id,
        cuerpo=datos.cuerpo,
        contacto_id=contacto_id,
        usuario_id=None if contacto_id else principal.id,
    )
    return {"id": str(fila.id), "oficial": fila.oficial}


@router_comunidad.post(
    "/hilos/{hilo_id}/aceptar/{respuesta_id}",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Marcar cuál fue la respuesta que funcionó",
    description=(
        "Es lo que separa un foro útil de un archivo de conversaciones: sin ella, "
        "quien llega el mes que viene tiene que leerse los treinta mensajes para "
        "saber cuál sirvió — y la mitad de las veces se rinde y abre un caso."
    ),
)
def aceptar(hilo_id: UUID, respuesta_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    hilo = prt.aceptar_respuesta(uow, hilo_id, respuesta_id)
    return {"id": str(hilo.id), "estado": hilo.estado}


class Moderar(BaseModel):
    aprobar: bool
    motivo: str = ""


@router_comunidad.post(
    "/hilos/{hilo_id}/moderar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Aprobar o rechazar un hilo pendiente",
    description=(
        "Rechazar exige motivo: el cliente que lo escribió tiene derecho a saber "
        "por qué no se publica."
    ),
)
def moderar(hilo_id: UUID, datos: Moderar, uow: UowDep, principal: AutenticadoDep) -> Any:
    hilo = prt.moderar_hilo(uow, hilo_id, aprobar=datos.aprobar, motivo=datos.motivo)
    return {"id": str(hilo.id), "estado": hilo.estado}


@router_comunidad.get(
    "/hilos",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Hilos de la comunidad",
    description=(
        "Lo que está en moderación **no se sirve** salvo que se pida: un hilo en "
        "moderación filtrado a la vista pública por un parámetro olvidado es "
        "exactamente lo que la moderación viene a impedir."
    ),
)
def listar_hilos(
    db: DbDep,
    principal: AutenticadoDep,
    categoria: str = Query("", max_length=80),
    incluir_moderacion: bool = Query(False),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    return prt.hilos(
        db,
        principal.tenant_id,
        categoria=categoria,
        solo_publicados=not incluir_moderacion,
        limite=limite,
    )


class AArticulo(BaseModel):
    clave: str = Field(max_length=120)


@router_comunidad.post(
    "/hilos/{hilo_id}/a-articulo",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("knowledge:write"))],
    summary="Convertir un hilo resuelto en artículo",
    description=(
        "Solo si tiene respuesta aceptada: convertir un hilo sin resolver crea un "
        "artículo que describe un problema y no su solución — la peor cosa que "
        "puede haber en una base de conocimiento, porque parece una respuesta y "
        "no lo es."
    ),
)
def a_articulo(hilo_id: UUID, datos: AArticulo, uow: UowDep, principal: AutenticadoDep) -> Any:
    articulo = prt.convertir_en_articulo(uow, hilo_id, clave=datos.clave)
    return {"id": str(articulo.id), "clave": articulo.clave, "estado": articulo.estado}


# ── Listados ──────────────────────────────────────────────────────────────
# Colecciones que se podían crear y no se podían leer. La API contestaba 405
# —o, en el caso de los artículos, un 422 confuso porque `/conocimiento/articulos`
# encajaba en `/conocimiento/{articulo_id}` y «articulos» no es un UUID— y el
# front enseñaba una pantalla vacía sin decir por qué.

montar_listado(
    router_conocimiento,
    modelo=Articulo,
    objeto="articulo",
    permiso="conocimiento:read",
    ruta="/articulos",
    nombre="Artículos de conocimiento",
    # La ficha se monta abajo a mano: su permiso de escritura es
    # `knowledge:write`, que no se deduce de `conocimiento:read`.
    ficha=False,
)
montar_listado(
    router_portal,
    modelo=AccesoPortal,
    objeto="acceso_portal",
    permiso="case:read",
    ruta="/accesos",
    nombre="Accesos al portal",
)


ROUTERS_CONOCIMIENTO = [router_conocimiento, router_portal, router_comunidad]


# ── Fichas: ver, editar y borrar ──────────────────────────────────────────
# De los veintidós recursos que el front deja crear, uno solo se podía abrir,
# editar y borrar. Estos no tenían ni ficha: se creaban y no había forma de
# volver a verlos —ni de corregir una errata— desde ninguna pantalla.
montar_ficha(
    router_conocimiento,
    modelo=Articulo,
    objeto="articulo",
    permiso_leer="conocimiento:read",
    permiso_escribir="knowledge:write",
    nombre="Artículos de conocimiento",
    ruta="/articulos",
)


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
montar_ficha(
    router_comunidad,
    modelo=HiloComunidad,
    objeto="hilo_comunidad",
    permiso_leer="case:read",
    permiso_escribir="case:write",
    nombre="Hilos de la comunidad",
    ruta="/hilos",
    parametro="hilo_id",
)
