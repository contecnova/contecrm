"""API del segundo factor y del gobierno del SSO
(CRM-00.05.01.11 a .25, las que se operan desde fuera).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Body, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.identity import factores, sso_gobierno
from services.identity.modelos import ProveedorIdentidad, Sesion, Usuario


def exigir_mfa_activa() -> None:
    """Corta si esta instalación no ofrece segundo factor.

    Va en los DOS routers y no en cada ruta: son doce hoy, y la que se escriba
    mañana heredaría el descuido.

    Los equipos de confianza entran aquí porque sólo significan algo con un
    segundo factor detrás: recordar un equipo es renunciar al factor en ese
    equipo, y sin factor no hay nada a lo que renunciar.
    """
    from crmcore.config import get_settings
    from crmcore.errors import Prohibido

    if get_settings().mfa_enabled:
        return
    raise Prohibido(
        "El segundo factor no está activo en esta instalación. " "Se enciende con MFA_ENABLED.",
        error_code="mfa.desactivada",
    )


router_factores = APIRouter(
    prefix="/factores",
    tags=["segundo factor"],
    dependencies=[Depends(exigir_mfa_activa)],
)
router_dispositivos = APIRouter(
    prefix="/dispositivos-confianza",
    tags=["segundo factor"],
    dependencies=[Depends(exigir_mfa_activa)],
)
router_sso_gob = APIRouter(prefix="/sso-gobierno", tags=["sso"])


# ── Códigos de un solo uso (CRM-00.05.01.17) ──────────────────────────────


class PedirCodigo(BaseModel):
    canal: str = Field(description="sms | email")
    proposito: str = Field("entrar", max_length=40)
    direccion: str = Field(
        "",
        max_length=320,
        description=(
            "Solo al inscribir un número nuevo. En el uso normal se deja vacío y "
            "sale de la ficha: aceptar la dirección del cliente dejaría pedir el "
            "código de otro a un teléfono propio"
        ),
    )


@router_factores.post(
    "/codigo",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enviar un código de un solo uso",
    description=(
        "Manda un OTP por SMS o correo a través del transporte genérico de la "
        "instalación. **No devuelve el código**: devolverlo «para pruebas» es el "
        "atajo que acaba en producción.\n\n"
        "El SMS es el factor más débil de los que hay —se intercepta con un "
        "cambio de SIM que no depende de nadie de aquí— y por eso va apagado de "
        "fábrica."
    ),
)
def pedir_codigo(datos: PedirCodigo, uow: UowDep, principal: AutenticadoDep) -> Any:
    usuario = uow.db.get(Usuario, principal.id)
    if usuario is None:
        raise NoEncontrado("Usuario no encontrado", error_code="usuario.no_encontrado")

    if datos.canal == "email":
        direccion = datos.direccion.strip() or usuario.email
    else:
        direccion = datos.direccion.strip() or str(
            (usuario.preferencias or {}).get("telefono") or ""
        )

    salida = factores.emitir_desafio(
        uow.db,
        usuario,
        principal.tenant_id,
        canal=datos.canal,
        direccion=direccion,
        proposito=datos.proposito,
    )
    return {
        "id": str(salida.id),
        "canal": salida.canal,
        "destino": salida.destino_visible,
        "expira_at": salida.expira_at.isoformat(),
        "reenviable_at": salida.reenviable_at.isoformat(),
    }


class ComprobarCodigo(BaseModel):
    codigo: str = Field(min_length=1, max_length=16)
    proposito: str = Field("entrar", max_length=40)


@router_factores.post(
    "/comprobar",
    summary="Validar un código y elevar el nivel de esta sesión",
    description=(
        "Valida el código y, si es correcto, anota el factor en la sesión. Eso "
        "es lo que abre la ventana de la reautenticación reforzada "
        "(CRM-00.05.01.18): las operaciones sensibles miran **cuándo** fue el "
        "último factor fuerte, no si el usuario tiene MFA configurada."
    ),
)
def comprobar_codigo(datos: ComprobarCodigo, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = factores.comprobar_desafio(
        uow.db,
        principal.id,
        principal.tenant_id,
        datos.codigo,
        proposito=datos.proposito,
    )
    sesion = uow.db.get(Sesion, principal.sesion_id) if principal.sesion_id else None
    token = ""
    if sesion is not None:
        factores.anotar_factor(uow.db, sesion, fila.canal)
        uow.db.flush()
        # Y se devuelve un token NUEVO. La marca del factor fuerte viaja dentro
        # del token —es lo único que llega a los demás servicios—, así que el
        # que se tenía se emitió antes de verificarse y sigue diciendo que no
        # hay factor. Sin esto, elevar el nivel servía dentro de `identity` y no
        # servía para nada fuera: la exportación seguía contestando «vuelve a
        # verificarte» después de haberse verificado, que es la peor forma de
        # tener la comprobación.
        from services.identity.modelos import Usuario
        from services.identity.servicio import emitir_token_acceso

        usuario = uow.db.get(Usuario, principal.id)
        if usuario is not None and principal.tenant_id is not None:
            token = emitir_token_acceso(
                uow.db,
                usuario=usuario,
                tenant_id=principal.tenant_id,
                sesion_id=sesion.id,
                actor_real_id=principal.actor_real_id,
            )
    return {
        "verificado": True,
        "canal": fila.canal,
        "proposito": fila.proposito,
        # Se dice si ha quedado anotado: sin sesión que elevar, el código vale
        # pero el step-up seguiría pidiéndolo, y descubrirlo después es peor.
        "sesion_elevada": sesion is not None,
        "access_token": token,
        "usar_este_token": bool(token),
    }


@router_factores.get(
    "/operaciones-sensibles",
    summary="Qué operaciones exigen volver a verificarse",
    description=(
        "La lista es una tabla de datos y no `if` repartidos por el código: lo "
        "que hace que una operación nueva quede cubierta es añadirla ahí, y lo "
        "que hace que se vea lo que **no** está cubierto es poder leerla entera."
    ),
)
def operaciones_sensibles(principal: AutenticadoDep) -> Any:
    return {
        "operaciones": [
            {"clave": k, "descripcion": v}
            for k, v in sorted(factores.OPERACIONES_SENSIBLES.items())
        ]
    }


@router_factores.get(
    "/nivel",
    summary="Nivel de autenticación de esta sesión",
    description=(
        "Qué factores se superaron al entrar y cuándo fue el último fuerte. Lo "
        "consulta el front para saber si una acción va a pedir reverificación "
        "**antes** de que el usuario rellene un formulario entero."
    ),
)
def nivel_de_sesion(db: DbDep, principal: AutenticadoDep) -> Any:
    sesion = db.get(Sesion, principal.sesion_id) if principal.sesion_id else None
    if sesion is None:
        return {"nivel": 0, "factores": [], "factor_fuerte_at": None}
    return {
        "nivel": factores.nivel_de(sesion),
        "factores": list(sesion.factores or []),
        "factor_fuerte_at": (
            sesion.factor_fuerte_at.isoformat() if sesion.factor_fuerte_at else None
        ),
    }


@router_factores.get(
    "/plan-de-inscripcion",
    summary="Qué me falta para tener el segundo factor en condiciones",
    description=(
        "**Un solo factor no es tener MFA: es tener un único punto de fallo.** "
        "Quien solo tiene el móvil y lo pierde se queda fuera, y entonces "
        "alguien de soporte lo desbloquea por teléfono — que es la puerta de "
        "atrás por la que se entra de verdad.\n\n"
        "Por eso el plan pide siempre un **segundo método de respaldo**, y lo "
        "dice con esas palabras: «añade otro método» se salta, «si pierdes el "
        "móvil te quedas fuera» no."
    ),
)
def plan_de_inscripcion(db: DbDep, principal: AutenticadoDep) -> Any:
    activos = [
        str(d.get("tipo") or "dispositivo")
        for d in factores.dispositivos_de(db, principal.id, principal.tenant_id)
    ]
    return factores.plan_de_inscripcion(factores_activos=activos)


@router_factores.get(
    "/cambio-de-dispositivo",
    summary="Si se puede mover el segundo factor a un móvil nuevo",
    description=(
        "El caso real es siempre el mismo: la persona cambia de teléfono y el "
        "factor se queda en el viejo, que ya ha devuelto o formateado. Dos "
        "caminos, y **ninguno es «llama a soporte»**: con respaldo se hace sola "
        "—es exactamente para esto que se pide un segundo método al "
        "inscribirse—, y sin respaldo hace falta desbloqueo con dos "
        "aprobadores.\n\n"
        "No es burocracia: sin ese requisito, el desbloqueo por teléfono se "
        "convierte en la forma más fácil de entrar en una cuenta ajena, y no "
        "hace falta romper nada."
    ),
)
def cambio_de_dispositivo(
    principal: AutenticadoDep,
    tiene_respaldo: bool = Query(False),
    factor_verificado: bool = Query(False),
) -> Any:
    # `GET` y no `POST`: esto **no escribe nada**, contesta qué camino hay. Un
    # `POST` que no escribe se cuela en el gate de «toda escritura declara
    # permiso» y obliga a inventarle uno, que es peor que arreglar el verbo.
    return factores.cambio_de_dispositivo(
        tiene_respaldo=tiene_respaldo, factor_verificado=factor_verificado
    )


@router_factores.get(
    "/vale-como-unico",
    summary="Si este factor vale como método único de entrada",
    description=(
        "La entrada sin contraseña solo es más segura con un factor **resistente "
        "a phishing** —una llave FIDO2 o el biométrico del dispositivo, atados "
        "al dominio—. Con un código por SMS como método único se quita la "
        "contraseña y se deja lo más débil de los dos: el SMS se intercepta y se "
        "pide por teléfono, y detrás ya no queda nada.\n\n"
        "Y exige respaldo, por lo mismo que el plan de inscripción: un método "
        "único sin segunda vía es un único punto de fallo con otro nombre."
    ),
)
def vale_como_unico(
    principal: AutenticadoDep,
    factor: str = Query(..., min_length=1, examples=["passkey"]),
    resistente_a_phishing: bool = Query(False),
    tiene_respaldo: bool = Query(False),
) -> Any:
    return factores.puede_entrar_sin_contrasena(
        factor=factor,
        resistente_a_phishing=resistente_a_phishing,
        tiene_respaldo=tiene_respaldo,
    )


@router_factores.get(
    "/adopcion",
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Quién tiene segundo factor y quién no",
    description=(
        "Un panel que solo diga «78 % de adopción» no sirve: lo que hace falta "
        "es **la lista de los que faltan**, porque el trabajo es hablar con "
        "ellos. Se separa por fuerza del factor, porque «tiene MFA» mete en el "
        "mismo saco una passkey y un SMS."
    ),
)
def adopcion(db: DbDep, principal: AutenticadoDep) -> Any:
    return factores.adopcion_mfa(db, principal.tenant_id)


# ── Dispositivos de confianza (CRM-00.05.01.20) ───────────────────────────


@router_dispositivos.get("", summary="Mis equipos recordados")
def listar_dispositivos(db: DbDep, principal: AutenticadoDep) -> Any:
    return factores.dispositivos_de(db, principal.id, principal.tenant_id)


@router_dispositivos.delete(
    "/{dispositivo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dejar de confiar en un equipo",
)
def revocar_dispositivo(dispositivo_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Response:
    factores.revocar_dispositivo(uow.db, dispositivo_id, principal.tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router_dispositivos.post(
    "/revocar-todos",
    summary="He perdido el portátil",
    description=(
        "Revoca todos los equipos recordados de una vez. Es el botón que de "
        "verdad se usa: uno a uno no sirve cuando lo que ha pasado es que ya no "
        "se sabe cuáles había."
    ),
)
def revocar_todos(uow: UowDep, principal: AutenticadoDep) -> Any:
    cuantos = factores.revocar_todos_los_dispositivos(uow.db, principal.id, principal.tenant_id)
    return {"revocados": cuantos}


# ── Gobierno del SSO ──────────────────────────────────────────────────────


@router_sso_gob.get(
    "/descubrir",
    summary="A qué proveedor le toca este correo",
    description=(
        "Preguntarle al usuario cuál es su proveedor es una pregunta que no "
        "sabe contestar: él sabe su correo, no si su empresa usa Entra ID o "
        "Ping. El subdominio hereda del dominio padre y gana el más específico "
        "(CRM-00.05.01.14)."
    ),
)
def descubrir(
    db: DbDep,
    principal: AutenticadoDep,
    email: str = Query(description="Correo de quien quiere entrar"),
) -> Any:
    proveedor = sso_gobierno.proveedor_por_correo(db, principal.tenant_id, email)
    if proveedor is None:
        return {"tiene_proveedor": False, "entrada": "contrasena"}
    return {
        "tiene_proveedor": True,
        "proveedor_id": str(proveedor.id),
        "nombre": proveedor.nombre,
        "tipo": proveedor.tipo,
        "entrada": "sso",
        "contrasena_local_permitida": sso_gobierno.puede_tener_contrasena_local(
            db, principal.tenant_id, email
        ),
    }


@router_sso_gob.get(
    "/certificados",
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Certificados de firma del IdP y su caducidad",
    description=(
        "Un certificado de IdP que caduca no avisa: un sábado por la noche deja "
        "de validar toda aserción y el lunes nadie de la empresa puede entrar "
        "(CRM-00.05.01.15). Un proveedor sin certificados declarados se marca "
        "aparte: no está «en verde», es que no se sabe nada de él."
    ),
)
def certificados(db: DbDep, principal: AutenticadoDep) -> Any:
    return sso_gobierno.revision_de_certificados(db, principal.tenant_id)


class CertificadoNuevo(BaseModel):
    huella: str = Field(min_length=1, max_length=64)
    caduca_at: datetime | None = None
    pem: str = ""


@router_sso_gob.post(
    "/proveedores/{proveedor_id}/certificados",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Añadir un certificado sin retirar el anterior",
    description=(
        "Una rotación bien hecha tiene los dos válidos a la vez. Sustituir uno "
        "por otro convierte la rotación en una ventana de caída para todo el "
        "tenant, coordinada al minuto con un departamento que no es el nuestro."
    ),
)
def anadir_certificado(
    proveedor_id: UUID, datos: CertificadoNuevo, uow: UowDep, principal: AutenticadoDep
) -> Any:
    proveedor = uow.db.execute(
        select(ProveedorIdentidad).where(
            ProveedorIdentidad.id == proveedor_id,
            ProveedorIdentidad.tenant_id == principal.tenant_id,
        )
    ).scalar_one_or_none()
    if proveedor is None:
        raise NoEncontrado("Proveedor no encontrado", error_code="idp.no_encontrado")
    sso_gobierno.anadir_certificado(
        uow.db, proveedor, huella=datos.huella, caduca_at=datos.caduca_at, pem=datos.pem
    )
    return {"certificados": len(proveedor.certificados or [])}


@router_sso_gob.delete(
    "/proveedores/{proveedor_id}/certificados/{huella}",
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Retirar un certificado",
    description=(
        "Se niega si es el único vigente: quitarlo dejaría al tenant sin poder "
        "validar nada, y eso se descubriría cuando alguien intentara entrar. Que "
        "falle aquí, con el administrador delante, es la diferencia entre un "
        "mensaje y una caída."
    ),
)
def retirar_certificado(
    proveedor_id: UUID, huella: str, uow: UowDep, principal: AutenticadoDep
) -> Any:
    proveedor = uow.db.execute(
        select(ProveedorIdentidad).where(
            ProveedorIdentidad.id == proveedor_id,
            ProveedorIdentidad.tenant_id == principal.tenant_id,
        )
    ).scalar_one_or_none()
    if proveedor is None:
        raise NoEncontrado("Proveedor no encontrado", error_code="idp.no_encontrado")
    sso_gobierno.retirar_certificado(uow.db, proveedor, huella)
    return {"certificados": len(proveedor.certificados or [])}


@router_sso_gob.post(
    "/cierre-unico",
    summary="Aviso de cierre de sesión del proveedor",
    description=(
        "Lo llama el IdP cuando la persona sale allí (back-channel logout). "
        "Cierra aquí las sesiones atadas a esa sesión del proveedor, o todas las "
        "del sujeto si el aviso viene por sujeto.\n\n"
        "Que no hubiera nada que cerrar **no es un error**: el proveedor puede "
        "avisar de una sesión que aquí ya había caducado, y devolver error haría "
        "que reintentara en bucle."
    ),
)
def cierre_unico(
    uow: UowDep,
    principal: AutenticadoDep,
    indice_idp: str = Body("", embed=True),
    sujeto_idp: str = Body("", embed=True),
) -> Any:
    return sso_gobierno.cerrar_por_aviso_del_idp(
        uow.db, principal.tenant_id, indice_idp=indice_idp, sujeto_idp=sujeto_idp
    )


@router_sso_gob.post(
    "/salir",
    summary="Salir aquí y decir a quién hay que avisar",
    description=(
        "Cierra la sesión local y devuelve los identificadores de sesión del IdP "
        "a los que hay que propagar el cierre. Cerrar solo aquí deja la sesión "
        "del proveedor viva, y volver a entrar no pide credenciales: para el "
        "usuario, el botón de salir no ha hecho nada."
    ),
)
def salir(uow: UowDep, principal: AutenticadoDep) -> Any:
    sesion = uow.db.get(Sesion, principal.sesion_id) if principal.sesion_id else None
    if sesion is None:
        raise NoEncontrado("No hay sesión que cerrar", error_code="sesion.no_encontrada")
    return sso_gobierno.salida_propagada(uow.db, sesion, principal.tenant_id)


ROUTERS_FACTORES = [router_factores, router_dispositivos, router_sso_gob]
