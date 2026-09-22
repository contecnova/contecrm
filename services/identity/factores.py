"""Segundo factor: OTP por SMS y correo, reautenticación reforzada,
dispositivos de confianza, delegación al IdP y panel de adopción
(CRM-00.05.01.17, .18, .20, .24, .25).

Reutiliza `contecmind:app/services/mfa.py` para la mecánica del código y el
transporte genérico de `crmcore.notificaciones`: **no hay código de ningún
proveedor de SMS**. El tenant declara URL, cabeceras y plantilla, y con eso
funciona Twilio, Vonage o la pasarela del operador local. Con un conector por
casa, cada cliente con un proveedor distinto sería una versión del producto.

Las cuatro decisiones que gobiernan el módulo:

**El SMS es el factor más débil y se dice.** Se intercepta con un cambio de SIM
que no depende de nadie de aquí. Está apagado de fábrica, se marca como débil en
el panel de adopción y una política puede prohibirlo sin quitar la MFA. Ofrecerlo
callando eso sería vender una seguridad que no da.

**Lo que hace seguro un OTP no es el código.** Son seis dígitos: un millón de
combinaciones, que sin tope de intentos se agotan a fuerza bruta en minutos. Lo
seguro es el conjunto —caduca pronto, vale una vez, los intentos están contados y
el reenvío tiene espera—. Cada una de esas cuatro piezas está aquí porque quitar
cualquiera deja el resto sin valor.

**El segundo factor caduca antes que la sesión.** Si valiera lo que la sesión,
quien pasó el factor a las nueve de la mañana podría exportar la base entera a
las seis de la tarde sin volver a demostrar nada. Por eso el step-up mira
*cuándo* fue, no *si* fue.

**Recordar un equipo es renunciar al factor en ese equipo.** Se puede —es la
razón número uno por la que la gente pide que le quiten la MFA—, pero caduca, se
revoca en remoto y es por usuario: un ordenador compartido no hereda la confianza
de quien lo usó antes.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.errors import Conflicto, ErrorValidacion, LimiteExcedido, NoAutenticado, Prohibido
from crmcore.notificaciones import Destino, Mensaje, transporte_de
from crmcore.runtime import settings as rt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.identity.modelos import (
    DesafioFactor,
    DispositivoConfianza,
    Membresia,
    Sesion,
    Usuario,
)

CANALES_OTP = ("sms", "email")

# Factores, de más débil a más fuerte. El orden importa: el panel de adopción lo
# usa para decir quién está protegido de verdad, y una política puede exigir un
# mínimo. Sin orden, «tiene MFA» mete en el mismo saco una passkey y un SMS.
FUERZA = {"sms": 1, "email": 1, "totp": 2, "push": 2, "webauthn": 3, "idp": 2}


def _cfg(db: Session, clave: str) -> Any:
    return rt.efectivo(clave, db)


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(valor: datetime | None) -> datetime | None:
    """Los tiempos que vuelven de la base pueden venir sin zona según el motor.
    Compararlos con uno que sí la trae revienta, y revienta en la ruta de
    entrar, que es la peor de todas para un fallo tonto."""
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


# ── OTP por SMS y correo (CRM-00.05.01.17) ────────────────────────────────


def _enmascarar(direccion: str, canal: str) -> str:
    """La dirección que se le enseña al usuario, recortada.

    Se le enseña algo —«hemos enviado un código al ***·34»— porque si no, quien
    tiene dos números no sabe a cuál mirar. Y se recorta porque la pantalla del
    segundo factor se ve **antes** de estar autenticado del todo: enseñarla
    entera convertiría el login en una forma de leer el teléfono de cualquiera
    con solo saber su correo.
    """
    direccion = (direccion or "").strip()
    if not direccion:
        return ""
    if canal == "email" and "@" in direccion:
        usuario, _, dominio = direccion.partition("@")
        visible = usuario[0] if usuario else ""
        return f"{visible}{'*' * max(3, len(usuario) - 1)}@{dominio}"
    return f"{'*' * max(3, len(direccion) - 2)}{direccion[-2:]}"


def _codigo(digitos: int) -> str:
    """Código de un solo uso. `secrets` y no `random`: el segundo es
    predecible a partir de unas cuantas salidas, y aquí eso es la credencial."""
    tope = 10**digitos
    return str(secrets.randbelow(tope)).zfill(digitos)


@dataclass(frozen=True, slots=True)
class DesafioEmitido:
    """Lo que se le devuelve a quien pidió el código. **Nunca lleva el código**:
    devolverlo «para pruebas» es el atajo que acaba en producción."""

    id: UUID
    canal: str
    destino_visible: str
    expira_at: datetime
    reenviable_at: datetime


def emitir_desafio(
    db: Session,
    usuario: Usuario,
    tenant_id: UUID,
    *,
    canal: str,
    direccion: str,
    proposito: str = "entrar",
) -> DesafioEmitido:
    """Genera y envía un código de un solo uso."""
    if canal not in CANALES_OTP:
        raise ErrorValidacion(
            f"Canal «{canal}» no válido para un código. Los válidos: {', '.join(CANALES_OTP)}",
            error_code="factor.canal_no_valido",
        )
    activo = _cfg(db, "otp_sms_enabled") if canal == "sms" else _cfg(db, "otp_email_enabled")
    if not activo:
        raise Prohibido(
            f"El segundo factor por {canal} no está habilitado en esta instalación.",
            error_code="factor.canal_desactivado",
        )
    if not (direccion or "").strip():
        # No es un error del sistema: es un dato que falta, y decirlo así evita
        # que soporte busque un fallo de envío que no existe.
        raise ErrorValidacion(
            "No hay dirección de destino para ese canal en la ficha del usuario.",
            error_code="factor.sin_direccion",
            detalle={"canal": canal},
        )

    espera = int(_cfg(db, "otp_reenvio_segundos") or 60)
    ultimo = db.execute(
        select(DesafioFactor)
        .where(
            DesafioFactor.usuario_id == usuario.id,
            DesafioFactor.tenant_id == tenant_id,
            DesafioFactor.canal == canal,
            DesafioFactor.usado_at.is_(None),
        )
        .order_by(DesafioFactor.creado_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if ultimo is not None:
        creado = _con_tz(ultimo.creado_at) or _ahora()
        restante = espera - (_ahora() - creado).total_seconds()
        if restante > 0:
            # Sin esta espera, «reenviar código» es un amplificador de SMS a
            # costa del cliente: un bucle en el navegador y la factura del mes.
            raise LimiteExcedido(
                f"Espera {int(restante)} s antes de pedir otro código.",
                error_code="factor.reenvio_demasiado_pronto",
                reintentar_en_s=int(restante) + 1,
            )
        # El anterior deja de valer en cuanto se pide otro: dos códigos vivos a
        # la vez doblan la superficie y confunden a quien recibe los dos.
        ultimo.usado_at = _ahora()

    digitos = int(_cfg(db, "otp_digitos") or 6)
    validez = int(_cfg(db, "otp_validez_segundos") or 300)
    codigo = _codigo(digitos)
    visible = _enmascarar(direccion, canal)

    fila = DesafioFactor(
        tenant_id=tenant_id,
        usuario_id=usuario.id,
        canal=canal,
        destino_visible=visible,
        hash_codigo=_hash(codigo),
        proposito=proposito,
        expira_at=_ahora() + timedelta(seconds=validez),
    )
    db.add(fila)
    db.flush()

    _entregar(
        db,
        usuario,
        tenant_id,
        canal=canal,
        direccion=direccion,
        codigo=codigo,
        minutos=max(1, validez // 60),
        proposito=proposito,
    )

    registrar(
        db,
        accion="factor.desafio_emitido",
        objeto="usuario",
        objeto_id=usuario.id,
        # El código NO se audita. Un apunte de auditoría con la credencial
        # dentro convierte el registro que sirve para investigar en el sitio
        # donde se encuentran credenciales.
        datos={"canal": canal, "proposito": proposito, "destino": visible},
        tenant_id=tenant_id,
    )
    return DesafioEmitido(
        id=fila.id,
        canal=canal,
        destino_visible=visible,
        expira_at=fila.expira_at,
        reenviable_at=_ahora() + timedelta(seconds=espera),
    )


def _entregar(
    db: Session,
    usuario: Usuario,
    tenant_id: UUID,
    *,
    canal: str,
    direccion: str,
    codigo: str,
    minutos: int,
    proposito: str,
) -> None:
    """Manda el código por el transporte genérico del canal."""
    transporte = transporte_de(canal)
    if transporte is None:
        raise Prohibido(
            f"Esta instalación no tiene transporte para «{canal}».",
            error_code="factor.sin_transporte",
        )
    que_autoriza = "para entrar" if proposito == "entrar" else f"para autorizar: {proposito}"
    resultado = transporte.entregar(
        Destino(usuario_id=usuario.id, direccion=direccion, nombre=usuario.nombre or ""),
        Mensaje(
            titulo="Código de verificación",
            cuerpo=(
                f"Tu código {que_autoriza} es {codigo}. Caduca en {minutos} minutos. "
                "Si no lo has pedido tú, cambia tu contraseña: alguien conoce tus "
                "credenciales."
            ),
            tipo="factor.codigo",
            prioridad="alta",
            datos={"codigo": codigo, "minutos": minutos},
        ),
        {"tenant_id": str(tenant_id)},
    )
    if not resultado.entregado:
        # Que no salga tiene que fallar aquí y ahora. Si se tragara el error, el
        # usuario esperaría un código que no va a llegar y el sistema diría que
        # todo fue bien.
        raise Prohibido(
            f"No se ha podido enviar el código por {canal}: {resultado.detalle or 'sin detalle'}",
            error_code="factor.envio_fallido",
        )


def comprobar_desafio(
    db: Session, usuario_id: UUID, tenant_id: UUID, codigo: str, *, proposito: str = "entrar"
) -> DesafioFactor:
    """Valida el código. Consume el desafío pase lo que pase con el intento."""
    fila = db.execute(
        select(DesafioFactor)
        .where(
            DesafioFactor.usuario_id == usuario_id,
            DesafioFactor.tenant_id == tenant_id,
            DesafioFactor.proposito == proposito,
            DesafioFactor.usado_at.is_(None),
        )
        .order_by(DesafioFactor.creado_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if fila is None:
        raise NoAutenticado(
            "No hay ningún código pendiente. Pide uno nuevo.",
            error_code="factor.sin_desafio",
        )
    if (_con_tz(fila.expira_at) or _ahora()) <= _ahora():
        fila.usado_at = _ahora()
        raise NoAutenticado("El código ha caducado. Pide uno nuevo.", error_code="factor.caducado")

    maximo = int(_cfg(db, "otp_max_intentos") or 5)
    fila.intentos += 1
    # `compare_digest` y no `==`: comparar cadenas sale antes cuanto más se
    # diferencian, y ese tiempo se mide desde fuera. Con seis dígitos y suficiente
    # paciencia, eso es el código.
    if not hmac.compare_digest(fila.hash_codigo, _hash((codigo or "").strip())):
        if fila.intentos >= maximo:
            fila.usado_at = _ahora()
            registrar(
                db,
                accion="factor.desafio_agotado",
                objeto="usuario",
                objeto_id=usuario_id,
                datos={"canal": fila.canal, "intentos": fila.intentos},
                tenant_id=tenant_id,
            )
            raise LimiteExcedido(
                "Demasiados intentos. Pide un código nuevo.",
                error_code="factor.intentos_agotados",
            )
        raise NoAutenticado(
            f"Código incorrecto. Te quedan {maximo - fila.intentos} intentos.",
            error_code="factor.codigo_incorrecto",
        )

    fila.usado_at = _ahora()
    # Se vacía en el acto: el desafío se busca por SQL, y sin esto un código
    # correcto seguiría valiendo dentro de la misma transacción. Valer dos veces
    # es justo lo que un código de un solo uso no puede hacer.
    db.flush()
    return fila


def purgar_desafios(db: Session, *, limite: int = 5000) -> int:
    """Tira los desafíos caducados. Sin esto la tabla crece sin techo con filas
    que ya no sirven para nada."""
    filas = (
        db.execute(select(DesafioFactor).where(DesafioFactor.expira_at < _ahora()).limit(limite))
        .scalars()
        .all()
    )
    for fila in filas:
        db.delete(fila)
    return len(filas)


# ── Reautenticación reforzada, step-up (CRM-00.05.01.18) ──────────────────

# Operaciones que piden volver a demostrar el factor. Es una tabla de datos y no
# una lista de `if` repartidos: lo que hace que una operación sensible nueva
# quede cubierta es añadirla aquí, y lo que hace que se vea lo que NO está
# cubierto es poder leer la tabla entera de una vez.
OPERACIONES_SENSIBLES: dict[str, str] = {
    "exportacion_masiva": "Exportar muchos registros de una vez",
    "cambio_permisos": "Cambiar roles, permisos o políticas de acceso",
    "borrado_masivo": "Borrar registros en bloque",
    "suplantacion": "Entrar como otro usuario",
    "clave_api": "Crear o regenerar una credencial de máquina",
    "cambio_mfa": "Desactivar o reconfigurar el segundo factor",
    "restauracion": "Restaurar datos sobre los actuales",
    "baja_tenant": "Dar de baja el tenant",
}


def anotar_factor(db: Session, sesion: Sesion, factor: str) -> None:
    """Deja constancia en la sesión de que se ha superado un factor."""
    momento = _ahora()
    sesion.factores = [*(sesion.factores or []), {"factor": factor, "at": momento.isoformat()}]
    if FUERZA.get(factor, 0) >= 2:
        sesion.factor_fuerte_at = momento


def nivel_de(sesion: Sesion) -> int:
    """El factor más fuerte superado en esta sesión."""
    return max((FUERZA.get(f.get("factor", ""), 0) for f in (sesion.factores or [])), default=0)


def exige_reautenticacion(db: Session, sesion: Sesion | None, operacion: str) -> None:
    """Corta la operación si el segundo factor es viejo o no lo hubo.

    Que el nivel de autenticación caduque antes que la sesión es todo el punto:
    una sesión dura horas porque tenerla que renovar cada cuarto de hora haría
    el producto inusable, y una exportación de toda la base a las seis de la
    tarde no puede apoyarse en un factor que se superó a las nueve.
    """
    if operacion not in OPERACIONES_SENSIBLES:
        raise ErrorValidacion(
            f"«{operacion}» no está declarada como operación sensible.",
            error_code="stepup.operacion_desconocida",
            detalle={"declaradas": sorted(OPERACIONES_SENSIBLES)},
        )
    if sesion is None:
        # Sin sesión no se puede afirmar nada del factor. Dejar pasar «porque no
        # se puede comprobar» es como no tener la comprobación.
        raise NoAutenticado(
            "Esta operación exige volver a verificar tu identidad.",
            error_code="stepup.requerido",
            detalle={"operacion": operacion, "descripcion": OPERACIONES_SENSIBLES[operacion]},
        )

    validez = int(_cfg(db, "stepup_validez_minutos") or 15)
    momento = _con_tz(sesion.factor_fuerte_at)
    if momento is not None and (_ahora() - momento) <= timedelta(minutes=validez):
        return

    raise NoAutenticado(
        "Esta operación exige volver a verificar tu identidad.",
        error_code="stepup.requerido",
        detalle={
            "operacion": operacion,
            "descripcion": OPERACIONES_SENSIBLES[operacion],
            "validez_minutos": validez,
            # Se dice si alguna vez hubo factor fuerte, porque «vuelve a
            # verificarte» y «configúrate un segundo factor» son dos cosas muy
            # distintas para quien está delante de la pantalla.
            "tiene_factor": momento is not None,
        },
    )


# ── Dispositivos de confianza (CRM-00.05.01.20) ───────────────────────────


def recordar_dispositivo(
    db: Session,
    usuario_id: UUID,
    tenant_id: UUID,
    *,
    huella: str,
    nombre: str = "",
    ip: str = "",
) -> DispositivoConfianza:
    """Marca este equipo como de confianza durante el plazo configurado."""
    dias = int(_cfg(db, "dispositivo_confianza_dias") or 0)
    if dias <= 0:
        raise Prohibido(
            "Esta instalación no permite recordar dispositivos.",
            error_code="dispositivo.desactivado",
        )
    if not (huella or "").strip():
        raise ErrorValidacion(
            "Falta la huella del dispositivo.", error_code="dispositivo.sin_huella"
        )

    hash_huella = _hash(huella)
    fila = db.execute(
        select(DispositivoConfianza).where(
            DispositivoConfianza.tenant_id == tenant_id,
            DispositivoConfianza.usuario_id == usuario_id,
            DispositivoConfianza.hash_huella == hash_huella,
        )
    ).scalar_one_or_none()
    expira = _ahora() + timedelta(days=dias)
    if fila is None:
        fila = DispositivoConfianza(
            tenant_id=tenant_id,
            usuario_id=usuario_id,
            hash_huella=hash_huella,
            nombre=(nombre or "Equipo sin nombre")[:120],
            ip_alta=ip or None,
            expira_at=expira,
        )
        db.add(fila)
    else:
        # Renovar y **desrevocar** explícitamente: si alguien revocó el equipo,
        # volver a confiar en él es una decisión nueva y tiene que quedar
        # escrita como tal.
        fila.expira_at = expira
        fila.revocado_at = None
        fila.motivo_revocacion = None
    db.flush()
    registrar(
        db,
        accion="dispositivo.recordado",
        objeto="usuario",
        objeto_id=usuario_id,
        datos={"dispositivo": str(fila.id), "nombre": fila.nombre, "dias": dias},
        tenant_id=tenant_id,
    )
    return fila


def dispositivo_de_confianza(
    db: Session, usuario_id: UUID, tenant_id: UUID, huella: str
) -> DispositivoConfianza | None:
    """El dispositivo vivo que corresponde a esa huella, si lo hay."""
    if not (huella or "").strip():
        return None
    fila = db.execute(
        select(DispositivoConfianza).where(
            DispositivoConfianza.tenant_id == tenant_id,
            DispositivoConfianza.usuario_id == usuario_id,
            DispositivoConfianza.hash_huella == _hash(huella),
            DispositivoConfianza.revocado_at.is_(None),
        )
    ).scalar_one_or_none()
    if fila is None:
        return None
    if (_con_tz(fila.expira_at) or _ahora()) <= _ahora():
        return None
    fila.ultimo_uso_at = _ahora()
    return fila


def revocar_dispositivo(
    db: Session,
    dispositivo_id: UUID,
    tenant_id: UUID,
    *,
    motivo: str = "revocado por el usuario",
) -> DispositivoConfianza:
    fila = db.execute(
        select(DispositivoConfianza).where(
            DispositivoConfianza.id == dispositivo_id,
            DispositivoConfianza.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise Conflicto("Ese dispositivo no existe aquí", error_code="dispositivo.no_encontrado")
    fila.revocado_at = _ahora()
    fila.motivo_revocacion = motivo[:120]
    registrar(
        db,
        accion="dispositivo.revocado",
        objeto="usuario",
        objeto_id=fila.usuario_id,
        datos={"dispositivo": str(fila.id), "motivo": motivo},
        tenant_id=tenant_id,
    )
    return fila


def revocar_todos_los_dispositivos(db: Session, usuario_id: UUID, tenant_id: UUID) -> int:
    """El botón que de verdad se usa: «he perdido el portátil»."""
    filas = (
        db.execute(
            select(DispositivoConfianza).where(
                DispositivoConfianza.tenant_id == tenant_id,
                DispositivoConfianza.usuario_id == usuario_id,
                DispositivoConfianza.revocado_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    for fila in filas:
        fila.revocado_at = _ahora()
        fila.motivo_revocacion = "revocación en bloque"
    if filas:
        registrar(
            db,
            accion="dispositivo.revocados_todos",
            objeto="usuario",
            objeto_id=usuario_id,
            datos={"cuantos": len(filas)},
            tenant_id=tenant_id,
        )
    return len(filas)


def dispositivos_de(db: Session, usuario_id: UUID, tenant_id: UUID) -> list[dict[str, Any]]:
    filas = (
        db.execute(
            select(DispositivoConfianza)
            .where(
                DispositivoConfianza.tenant_id == tenant_id,
                DispositivoConfianza.usuario_id == usuario_id,
            )
            .order_by(DispositivoConfianza.created_at.desc())
        )
        .scalars()
        .all()
    )
    ahora = _ahora()
    return [
        {
            "id": str(f.id),
            "nombre": f.nombre,
            "ip_alta": f.ip_alta,
            "expira_at": f.expira_at.isoformat() if f.expira_at else None,
            "ultimo_uso_at": f.ultimo_uso_at.isoformat() if f.ultimo_uso_at else None,
            "revocado": f.revocado_at is not None,
            "vigente": f.revocado_at is None and (_con_tz(f.expira_at) or ahora) > ahora,
        }
        for f in filas
    ]


# ── Delegar el segundo factor al IdP (CRM-00.05.01.24) ────────────────────


def el_idp_ya_hizo_mfa(db: Session, proveedor: Any, claims: dict[str, Any]) -> bool:
    """¿El proveedor ya ha exigido un segundo factor en esta entrada?

    Pedirlo dos veces —una en el IdP corporativo y otra aquí— es la queja más
    repetida de cualquier despliegue de SSO, y lo que consigue de verdad es que
    el cliente pida que se quite la MFA del CRM. Pero **no se da por hecho**: se
    acepta únicamente si el proveedor declara qué valores de `acr`/`amr` cuentan.
    Sin esa lista se pide el factor aquí, porque cualquier IdP puede mandar un
    `amr` que diga lo que sea y creérselo sin acuerdo previo convierte la MFA en
    una casilla que rellena el otro lado.
    """
    if not _cfg(db, "delegar_mfa_al_idp"):
        return False
    aceptados = {str(v).strip().lower() for v in (getattr(proveedor, "acr_con_mfa", None) or [])}
    if not aceptados:
        return False

    recibidos: set[str] = set()
    acr = claims.get("acr")
    if acr:
        recibidos.add(str(acr).strip().lower())
    amr = claims.get("amr") or []
    if isinstance(amr, str):
        amr = [amr]
    recibidos.update(str(v).strip().lower() for v in amr)
    # SAML trae el contexto en otro sitio; se admite el mismo nombre para que la
    # configuración sea una sola y no una por protocolo.
    contexto = claims.get("authn_context") or claims.get("AuthnContextClassRef")
    if contexto:
        recibidos.add(str(contexto).strip().lower())
    return bool(recibidos & aceptados)


# ── Panel de adopción de MFA (CRM-00.05.01.25) ────────────────────────────


def adopcion_mfa(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Quién tiene segundo factor, quién no, y con cuál.

    Un panel que solo diga «78 % de adopción» no sirve para nada: lo que hace
    falta es **la lista de los que faltan**, porque el trabajo es hablar con
    ellos. Y se separa por fuerza del factor, porque «tiene MFA» mete en el
    mismo saco una passkey y un SMS, que es precisamente la distinción que
    alguien va a querer hacer cuando decida apretar.
    """
    filas = db.execute(
        select(Usuario, Membresia)
        .join(Membresia, Membresia.usuario_id == Usuario.id)
        .where(Membresia.tenant_id == tenant_id, Membresia.activa.is_(True))
        .order_by(Usuario.email)
    ).all()

    con_factor: list[dict[str, Any]] = []
    sin_factor: list[dict[str, Any]] = []
    for usuario, membresia in filas:
        entrada = {
            "usuario_id": str(usuario.id),
            "email": usuario.email,
            "nombre": usuario.nombre,
            "roles": list(membresia.roles or []),
            "ultimo_acceso_at": (
                usuario.ultimo_acceso_at.isoformat() if usuario.ultimo_acceso_at else None
            ),
        }
        if usuario.mfa_activo:
            entrada["factor"] = "totp"
            entrada["fuerza"] = FUERZA["totp"]
            entrada["codigos_recuperacion"] = len(usuario.mfa_recuperacion or [])
            con_factor.append(entrada)
        else:
            sin_factor.append(entrada)

    total = len(filas)
    obligatoria = bool(_cfg(db, "mfa_obligatoria"))
    return {
        "total_usuarios": total,
        "con_factor": len(con_factor),
        "sin_factor": len(sin_factor),
        # Con cero usuarios el porcentaje no es 100: es que no hay nada que
        # medir, y decir 100 sería un verde que nadie se ha ganado.
        "adopcion_pct": round(100 * len(con_factor) / total, 1) if total else None,
        "medible": total > 0,
        "mfa_obligatoria": obligatoria,
        "usuarios_sin_factor": sin_factor,
        "usuarios_con_factor": con_factor,
        "canales_debiles_activos": [
            canal
            for canal, clave in (("sms", "otp_sms_enabled"), ("email", "otp_email_enabled"))
            if _cfg(db, clave)
        ],
        "aviso": (
            "El SMS y el correo son los factores más débiles: se interceptan sin "
            "tocar el dispositivo. Cuentan como segundo factor, pero no protegen "
            "como una passkey o un TOTP."
        ),
    }


def usuarios_sin_factor(db: Session, tenant_id: UUID) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(Usuario)
            .join(Membresia, Membresia.usuario_id == Usuario.id)
            .where(
                Membresia.tenant_id == tenant_id,
                Membresia.activa.is_(True),
                Usuario.mfa_activo.is_(False),
            )
        ).scalar_one()
        or 0
    )


# ── Ciclo de vida del segundo factor (CRM-00.05.01.19, .21, .23) ──────────

# Por qué se puede pedir un segundo factor aunque el dispositivo sea de
# confianza. Lista cerrada: cada motivo se explica al usuario, y «por seguridad»
# no explica nada — al tercer aviso así, la gente escribe el código sin mirar.
MOTIVOS_RIESGO = {
    "ip_nueva": "Estás entrando desde una red desde la que no habías entrado",
    "pais_nuevo": "Estás entrando desde un país distinto al habitual",
    "dispositivo_nuevo": "Es la primera vez que entras desde este equipo",
    "salto_imposible": "Has entrado desde otro país hace muy poco: uno de los dos no eras tú",
    "operacion_sensible": "Vas a hacer algo que puede costar dinero o borrar datos",
    "tiempo_sin_entrar": "Hace mucho que no entrabas",
}

# Cuántos factores hacen falta para poder desbloquear a alguien sin soporte. Dos
# personas y no una: el desbloqueo es la puerta de atrás de toda la MFA, y una
# sola persona con ese poder es el eslabón que se ataca.
APROBADORES_DESBLOQUEO = 2


def evaluar_riesgo(
    *,
    ip_conocida: bool,
    pais_conocido: bool,
    dispositivo_conocido: bool,
    minutos_desde_otro_pais: int | None = None,
    dias_sin_entrar: int = 0,
    operacion_sensible: bool = False,
    dias_para_considerar_ausencia: int = 30,
) -> dict[str, Any]:
    """Si hay que pedir el segundo factor **ahora** (CRM-00.05.01.21).

    La MFA adaptativa se vende como comodidad y su valor real es otro: pedir el
    factor **cuando el contexto cambia** detecta el robo de sesión, que es lo que
    la MFA de siempre no ve — una vez dentro, ya estás dentro.

    Y cada motivo se dice con palabras. «Por seguridad» no explica nada, y al
    tercer aviso así la gente teclea el código sin mirar — que es exactamente la
    costumbre que un atacante necesita.
    """
    motivos: list[str] = []
    if not dispositivo_conocido:
        motivos.append("dispositivo_nuevo")
    if not ip_conocida:
        motivos.append("ip_nueva")
    if not pais_conocido:
        motivos.append("pais_nuevo")
    if minutos_desde_otro_pais is not None and minutos_desde_otro_pais < 120:
        # Dos países en dos horas: o hay un avión imposible o hay dos personas.
        # Es la señal más fiable de las seis y por eso va sola al principio.
        motivos.append("salto_imposible")
    if dias_sin_entrar >= dias_para_considerar_ausencia:
        motivos.append("tiempo_sin_entrar")
    if operacion_sensible:
        motivos.append("operacion_sensible")

    return {
        "exigir_factor": bool(motivos),
        "motivos": motivos,
        # El texto que se le enseña, no el código del motivo: quien lo lee es una
        # persona con prisa, no un programa.
        "explicacion": (
            " · ".join(MOTIVOS_RIESGO[m] for m in motivos)
            if motivos
            else "Nada ha cambiado desde la última vez: no hace falta el segundo factor."
        ),
        # La señal más fuerte, aparte: un salto imposible no se resuelve pidiendo
        # un código, se resuelve mirando qué ha pasado.
        "sospechoso": "salto_imposible" in motivos,
        "que_hacer_si_sospechoso": (
            "Además del factor, conviene avisar a la persona y revisar sus sesiones "
            "abiertas: si uno de los dos accesos no era ella, el otro sigue vivo."
            if "salto_imposible" in motivos
            else ""
        ),
    }


def plan_de_inscripcion(*, factores_activos: list[str], politica_minima: int = 1) -> dict[str, Any]:
    """Qué le falta a esta persona para tener el segundo factor en condiciones
    (CRM-00.05.01.19).

    **Un solo factor no es tener MFA: es tener un único punto de fallo.** Quien
    solo tiene el móvil y lo pierde se queda fuera, y entonces alguien de soporte
    lo desbloquea por teléfono — que es la puerta de atrás por la que se entra de
    verdad.

    Por eso el plan pide siempre un **segundo método de respaldo**, y lo dice con
    esas palabras en vez de dejarlo como una recomendación que nadie sigue.
    """
    activos = sorted(set(factores_activos))
    pasos: list[dict[str, str]] = []
    if not activos:
        pasos.append(
            {
                "paso": "inscribir_primero",
                "porque": "Sin ningún factor, la cuenta depende solo de la contraseña",
            }
        )
    if len(activos) < max(2, politica_minima):
        pasos.append(
            {
                "paso": "inscribir_respaldo",
                "porque": (
                    "Con un solo método, perder el móvil deja fuera a la persona y "
                    "obliga a un desbloqueo manual — que es la puerta de atrás de "
                    "toda la MFA"
                ),
            }
        )
    return {
        "activos": activos,
        "pasos": pasos,
        "completo": not pasos,
        "porque": (
            "Tiene un método y un respaldo: puede perder uno sin quedarse fuera."
            if not pasos
            else "Le falta respaldo. Mientras tanto, cualquier pérdida acaba en el "
            "mostrador de soporte."
        ),
    }


def cambio_de_dispositivo(*, tiene_respaldo: bool, factor_verificado: bool) -> dict[str, Any]:
    """Si se puede mover el segundo factor a un móvil nuevo.

    El caso real es siempre el mismo: la persona cambia de teléfono y el factor
    se queda en el viejo, que ya ha devuelto o formateado. Dos caminos y ninguno
    es «llama a soporte»:

    **Con respaldo**, se hace sola: es exactamente para esto que se pide un
    segundo método al inscribirse.

    **Sin respaldo**, hace falta desbloqueo con dos aprobadores. No es burocracia:
    sin el factor viejo, lo único que demuestra quién es esa persona es que alguien
    responda por ella, y una sola firma convierte una llamada convincente en un
    acceso.
    """
    if tiene_respaldo and factor_verificado:
        return {
            "puede_solo": True,
            "camino": "respaldo",
            "porque": "Ha demostrado el segundo método: puede inscribir el nuevo sin ayuda.",
        }
    return {
        "puede_solo": False,
        "camino": "desbloqueo_asistido",
        "aprobadores_necesarios": APROBADORES_DESBLOQUEO,
        "porque": (
            "Sin el factor viejo ni respaldo, lo único que demuestra quién es esta "
            f"persona es que otras {APROBADORES_DESBLOQUEO} respondan por ella. Una "
            "sola firma convierte una llamada convincente en un acceso."
        ),
    }


def puede_entrar_sin_contrasena(
    *, factor: str, resistente_a_phishing: bool, tiene_respaldo: bool
) -> dict[str, Any]:
    """Si este factor vale como método **único** de entrada (CRM-00.05.01.23).

    La entrada sin contraseña solo es más segura con un factor resistente a
    phishing —una llave FIDO2 o el biométrico del dispositivo, atados al dominio—.
    Con un código por SMS como método único se quita la contraseña y se deja lo
    más débil de los dos: el SMS se intercepta y se pide por teléfono, y ya no
    queda nada detrás.

    Y exige respaldo. Sin contraseña que valga de red, perder la llave deja a la
    persona fuera del todo.
    """
    if not resistente_a_phishing:
        return {
            "puede": False,
            "porque": (
                f"«{factor}» no resiste phishing: como método único dejaría la cuenta "
                "peor que con contraseña, porque se quita la contraseña y se queda lo "
                "más débil de los dos."
            ),
        }
    if not tiene_respaldo:
        return {
            "puede": False,
            "porque": (
                "Sin contraseña no hay red debajo: perder la llave deja a la persona "
                "fuera del todo. Hace falta un segundo método antes de quitarla."
            ),
        }
    return {
        "puede": True,
        "porque": (
            f"«{factor}» está atado al dominio, así que una web falsa no puede usarlo, "
            "y hay respaldo si se pierde."
        ),
    }
