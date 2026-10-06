"""API de correo, calendario, chat, plantillas documentales y firma presencial
(CRM-06.01.01, CRM-06.01.02.09, .13, .14).

Nada de aquí vuelca un buzón entero en el CRM. Se conecta, se sincroniza lo que
tiene que ver con el CRM y **se dice lo que se ha dejado fuera**: un panel que
solo cuenta lo sincronizado enseña un número que sube mientras tres buzones
llevan una semana sin credencial.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.documental.firma_presencial import FirmaPresencial
from crmcore.documental.plantillas import PlantillaDocumento
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from services.integration import buzon as buz
from services.integration import colaboracion as colab
from services.integration import firma as fir

router_buzon = APIRouter(prefix="/buzones", tags=["correo y calendario"])
router_chat = APIRouter(prefix="/canales-chat", tags=["chat corporativo"])
router_plantillas = APIRouter(prefix="/plantillas-documento", tags=["generación documental"])
router_presencial = APIRouter(prefix="/firma-presencial", tags=["firma electrónica"])


class ConectarBuzon(BaseModel):
    usuario_id: UUID
    perfil: str = Field(..., description="Clave del perfil declarado, no el nombre de la casa")
    direccion: str
    ambito: str = "correo"
    criterio: str = "con_contacto_del_crm"
    entrante: bool = True
    saliente: bool = False


class Sincronizar(BaseModel):
    elementos: list[dict[str, Any]] = Field(default_factory=list)
    marca_nueva: str = ""
    direcciones_conocidas: list[str] = Field(default_factory=list)


class Pausar(BaseModel):
    motivo: str = Field(..., min_length=3)


@router_buzon.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Conectar el correo o el calendario de una persona",
    description=(
        "Nace **sin credencial**: conectar es declarar la intención y autorizar es "
        "otra cosa que hace la persona. Darlo por conectado antes haría que el "
        "panel dijera que todo va bien mientras no entra nada."
    ),
)
def conectar(cuerpo: ConectarBuzon, uow: UowDep) -> Any:
    fila = buz.conectar(uow, **cuerpo.model_dump())
    return {
        "id": str(fila.id),
        "estado": fila.estado,
        "criterio": fila.criterio,
        "porque": "Falta que la persona autorice el acceso.",
    }


@router_buzon.post(
    "/{buzon_id}/autorizado",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="La persona ha autorizado el acceso",
)
def autorizado(buzon_id: UUID, uow: UowDep) -> Any:
    fila = buz.marcar_autorizado(uow, buzon_id=buzon_id)
    return {"id": str(fila.id), "estado": fila.estado}


@router_buzon.post(
    "/{buzon_id}/pausar",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Dejar de sincronizar sin perder lo registrado",
    description=(
        "La alternativa real es que alguien revoque el acceso desde el proveedor, "
        "y entonces el CRM no sabe si está pausado o roto."
    ),
)
def pausar(buzon_id: UUID, cuerpo: Pausar, uow: UowDep) -> Any:
    fila = buz.pausar(uow, buzon_id=buzon_id, motivo=cuerpo.motivo)
    return {"id": str(fila.id), "estado": fila.estado, "motivo": fila.motivo}


@router_buzon.post(
    "/{buzon_id}/sincronizar",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Procesar lo que ha traído el proveedor (CRM-06.01.01.01, .04)",
    description=(
        "Lo privado no entra nunca, y **se cuenta**: si desapareciera sin más, "
        "nadie sabría que hubo algo que no se trajo.\n\n"
        "La marca de incremento solo avanza si no ha fallado nada. Avanzar con un "
        "fallo dentro deja un hueco que no se recupera y que nadie nota hasta que "
        "falta una reunión."
    ),
)
def sincronizar(buzon_id: UUID, cuerpo: Sincronizar, uow: UowDep) -> Any:
    return buz.sincronizar(
        uow,
        buzon_id=buzon_id,
        elementos=cuerpo.elementos,
        marca_nueva=cuerpo.marca_nueva,
        direcciones_conocidas=cuerpo.direcciones_conocidas,
    )


@router_buzon.get(
    "/panel",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Cómo va la sincronización, y sobre todo qué no está entrando",
)
def panel_buzones(
    db: DbDep, principal: AutenticadoDep, horas: int = Query(24, ge=1, le=720)
) -> Any:
    return buz.panel(db, principal.tenant_id, horas=horas)


# ── Chat corporativo (CRM-06.01.01.03) ────────────────────────────────────


class DeclararCanalChat(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    url_entrante: str
    secreto: str = Field(..., min_length=8)
    perfil: str = "generico"
    cabecera_firma: str = "x-signature"
    ordenes: list[str] | None = None


class OrdenChat(BaseModel):
    orden: str
    objeto: str = ""
    objeto_id: UUID | None = None
    texto: str = ""
    usuario_externo: str = ""


@router_chat.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Conectar un espacio de chat",
    description=(
        "El secreto es obligatorio: un canal sin firma acepta cualquier POST de "
        "quien sepa la URL, y desde ahí se piden las mismas cosas que desde el "
        "CRM.\n\n"
        "Sin declarar órdenes, el canal **solo consulta**: es lo menos que puede "
        "hacer y lo que menos daño hace si alguien se equivoca."
    ),
)
def declarar_canal_chat(cuerpo: DeclararCanalChat, uow: UowDep) -> Any:
    fila = colab.declarar_canal(uow, **cuerpo.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "ordenes": fila.ordenes}


@router_chat.post(
    "/{clave}/orden",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Atender una orden que llega del chat",
    description=(
        "Se comprueba la firma antes de creer nada. Lo que escribe sale como "
        "**comando** al servicio dueño del objeto: venir de un chat no da "
        "permisos distintos, así que el estado que se devuelve es «pedido»."
    ),
)
async def orden_chat(clave: str, cuerpo: OrdenChat, request: Request, uow: UowDep) -> Any:
    crudo = await request.body()
    firma = request.headers.get("x-signature", "")
    return colab.atender(
        uow,
        clave=clave,
        cuerpo=crudo,
        firma=firma,
        orden=cuerpo.orden,
        objeto=cuerpo.objeto,
        objeto_id=cuerpo.objeto_id,
        texto=cuerpo.texto,
        usuario_externo=cuerpo.usuario_externo,
    )


# ── Generación documental (CRM-06.01.01.06) ───────────────────────────────


class GuardarPlantillaDoc(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    cuerpo: str = Field(..., min_length=1)
    tipo: str = "propuesta"
    nombre: str = ""
    idioma: str = "es"
    clausulas_bloqueadas: list[str] | None = None


class GenerarDocumento(BaseModel):
    clave: str
    datos: dict[str, Any] = Field(default_factory=dict)
    objeto: str = ""
    objeto_id: UUID | None = None
    permitir_incompleto: bool = False
    documento_id: str = Field(
        "",
        max_length=200,
        description=(
            "El identificador en el gestor documental, si ya está archivado. "
            "Vacío si no: hay documentos que se generan y acaban en un correo sin "
            "pasar por el gestor, y ésos son justo los que después nadie rastrea"
        ),
    )


@router_plantillas.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Guardar una versión nueva de plantilla",
    description=(
        "Nueva y no una actualización: cuando una cláusula resulta estar mal, la "
        "pregunta no es cuál está mal sino **a quién se le mandó**, y sin "
        "versiones la respuesta es «no consta»."
    ),
)
def guardar_plantilla(cuerpo: GuardarPlantillaDoc, uow: UowDep, principal: AutenticadoDep) -> Any:
    from crmcore.documental.plantillas import guardar_plantilla as guardar

    fila = guardar(uow.db, tenant_id=principal.tenant_id, **cuerpo.model_dump())
    return {"clave": fila.clave, "version": fila.version, "tipo": fila.tipo}


@router_plantillas.post(
    "/comprobar",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Qué faltaría si se generase ahora, sin generar nada",
    description=(
        "Un documento con `{{importe}}` sin sustituir llega al cliente igual que "
        "uno bueno: nadie relee un contrato de doce páginas antes de mandarlo."
    ),
)
def comprobar_plantilla(cuerpo: GenerarDocumento, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.documental.plantillas import comprobar

    return comprobar(db, principal.tenant_id, clave=cuerpo.clave, datos=cuerpo.datos)


@router_plantillas.post(
    "/generar",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="Componer el documento (CRM-06.01.01.06)",
    description=(
        "No genera si falta algo, salvo que se pida expresamente. Y comprueba que "
        "**las cláusulas bloqueadas siguen ahí después de sustituir**: el caso "
        "real es un marcador dentro de la cláusula que la rompe al rellenarse."
    ),
)
def generar_documento(cuerpo: GenerarDocumento, uow: UowDep, principal: AutenticadoDep) -> Any:
    from crmcore.documental.plantillas import generar

    return generar(
        uow.db,
        tenant_id=principal.tenant_id,
        clave=cuerpo.clave,
        datos=cuerpo.datos,
        objeto=cuerpo.objeto,
        objeto_id=cuerpo.objeto_id,
        por=principal.id,
        permitir_incompleto=cuerpo.permitir_incompleto,
        documento_id=cuerpo.documento_id,
    )


@router_plantillas.get(
    "/{clave}/version/{version}/destinatarios",
    dependencies=[Depends(exige_permiso("integracion:read"))],
    summary="A quién se le mandó esta versión de la plantilla",
    description="La pregunta que se hace cuando una cláusula resulta estar mal.",
)
def quien_recibio(clave: str, version: int, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.documental.plantillas import quien_recibio as quien

    return quien(db, principal.tenant_id, clave=clave, version=version)


# ── Firma presencial y proveedores (CRM-06.01.02.09, .13, .14) ────────────


class CapturarFirma(BaseModel):
    trazo: dict[str, Any]
    contenido_firmado_b64: str = Field(..., description="Lo que se firma, en base64")
    firmante_nombre: str
    consentimiento_biometrico: bool = False
    texto_consentimiento: str = ""
    documento_identidad: str = ""
    testigo_id: UUID | None = None
    objeto: str = ""
    objeto_id: UUID | None = None
    documento_id: str = ""
    dispositivo: str = ""


class MigrarProveedor(BaseModel):
    desde: str
    hacia: str
    motivo: str = ""


@router_presencial.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("firma:write"))],
    summary="Capturar una firma hecha delante, en tableta (CRM-06.01.02.09)",
    description=(
        "El trazo es **dato biométrico del artículo 9**: sin consentimiento "
        "explícito no se guarda, y la firma se puede hacer igual sin capturarlo.\n\n"
        "Se rechaza un trazo que parezca un toque accidental, y se exige el "
        "testigo: en presencial la identificación la hace una persona mirando un "
        "documento, y sin constancia de quién fue esto es una rúbrica.\n\n"
        "Lo que ata la firma al documento es la **huella**, no la imagen: si el "
        "documento cambia una coma, deja de cuadrar."
    ),
)
def capturar_firma(cuerpo: CapturarFirma, uow: UowDep, principal: AutenticadoDep) -> Any:
    import base64

    from crmcore.documental.firma_presencial import capturar

    datos = cuerpo.model_dump()
    contenido = base64.b64decode(datos.pop("contenido_firmado_b64") or b"")
    fila = capturar(uow.db, tenant_id=principal.tenant_id, contenido_firmado=contenido, **datos)
    return {
        "id": str(fila.id),
        "huella_documento": fila.huella_documento,
        "puntos": fila.puntos,
        "duracion_ms": fila.duracion_ms,
    }


@router_presencial.get(
    "/{objeto}/{objeto_id}",
    dependencies=[Depends(exige_permiso("firma:read"))],
    summary="Firmas presenciales de un registro",
    description=(
        "**Sin el trazo**: es biometría, y devolverla en una consulta de rutina la "
        "reparte por los registros de acceso, las cachés y los navegadores de "
        "quien mire la ficha."
    ),
)
def firmas_de(objeto: str, objeto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.documental.firma_presencial import firmas_de as listar

    return {"firmas": listar(db, principal.tenant_id, objeto=objeto, objeto_id=objeto_id)}


@router_presencial.post(
    "/proveedores/{clave}/probar",
    dependencies=[Depends(exige_permiso("firma:write"))],
    summary="Probar credenciales antes de mandar un contrato (CRM-06.01.02.14)",
    description=(
        "`en_vacio` crea un sobre de prueba y lo cancela. Solo consultar no vale: "
        "hay proveedores donde leer funciona con una credencial que no puede "
        "escribir, y entonces la prueba pasa y el primer envío falla."
    ),
)
def probar_proveedor(clave: str, uow: UowDep, en_vacio: bool = Query(True)) -> Any:
    return fir.probar_conexion(uow, clave=clave, en_vacio=en_vacio)


@router_presencial.post(
    "/proveedores/migrar",
    dependencies=[Depends(exige_permiso("firma:write"))],
    summary="Cambiar de proveedor sin perder lo enviado (CRM-06.01.02.13)",
    description=(
        "Los sobres en vuelo terminan con el suyo: el enlace que tiene el cliente "
        "en su correo apunta al proveedor viejo.\n\n"
        "Devuelve cuántos quedan y cuál es el más antiguo, que es lo que decide "
        "**cuándo se puede apagar la credencial vieja** — la pregunta que nadie "
        "sabe contestar cuando llega el momento."
    ),
)
def migrar_proveedor(cuerpo: MigrarProveedor, uow: UowDep) -> Any:
    return fir.migrar_proveedor(uow, desde=cuerpo.desde, hacia=cuerpo.hacia, motivo=cuerpo.motivo)


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router_buzon,
    modelo=buz.Buzon,
    objeto="buzon",
    permiso="integracion:read",
    nombre="Buzones conectados",
)
montar_listado(
    router_chat,
    modelo=colab.CanalChat,
    objeto="canal_chat",
    permiso="integracion:read",
    nombre="Canales de chat",
)
montar_listado(
    router_plantillas,
    modelo=PlantillaDocumento,
    objeto="plantilla_documento",
    permiso="integracion:read",
    nombre="Plantillas de documento",
)


# ── Listados de las sub-colecciones ───────────────────────────────────────
# Mismo agujero que en las colecciones raíz: se podían crear y no se podían
# leer. Un sobre de firma, una tabla del almacén o una predicción que no se
# pueden listar no existen para quien tiene que revisarlos.

montar_listado(
    router_presencial,
    modelo=FirmaPresencial,
    objeto="firma_presencial",
    permiso="firma:read",
    nombre="Firmas presenciales",
    # Por `firmado_at` y no por la marca genérica: este modelo no la tiene, y el
    # listado devolvía 500 con `AttributeError` en cuanto alguien lo abría.
    # Además es la fecha que importa de una firma — cuándo se firmó, no cuándo
    # se guardó la fila.
    orden="-firmado_at",
    columnas_orden=frozenset({"firmado_at"}),
)


ROUTERS_BUZON = [router_buzon, router_chat, router_plantillas, router_presencial]
