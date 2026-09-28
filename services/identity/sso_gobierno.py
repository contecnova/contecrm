"""Gobierno del SSO: forzarlo, descubrir el proveedor, rotar certificados,
aceptar aserciones iniciadas en el IdP y cerrar la sesión en los dos lados
(CRM-00.05.01.11, .12, .13, .14, .15).

Reutiliza `contecweb:app/services/saml.py` y el `sso.py` de este servicio. Lo
que se añade aquí es lo que separa un SSO que funciona en la demo de uno que se
sostiene en una empresa de verdad: qué pasa cuando hay seis dominios, cuando el
certificado caduca un sábado, cuando alguien pulsa «salir» y cuando la aserción
llega sin que nadie la haya pedido.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, Prohibido
from crmcore.runtime import settings as rt
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.identity.modelos import (
    AsercionConsumida,
    ProveedorIdentidad,
    Sesion,
    SesionIdP,
    Usuario,
)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


# ── Descubrimiento de dominio (CRM-00.05.01.14) ───────────────────────────


def _dominios_de(proveedor: ProveedorIdentidad) -> set[str]:
    """Todos los dominios del proveedor: el principal y los añadidos.

    Son varios porque las empresas acumulan dominios —adquisiciones, marcas,
    el de siempre y el nuevo— y con uno solo cada dominio extra obliga a
    duplicar el proveedor entero: la misma configuración, el mismo certificado y
    el mismo mapeo de roles, mantenidos por separado hasta que divergen.
    """
    salida = {str(d).strip().lower().lstrip("@") for d in (proveedor.dominios or []) if d}
    if proveedor.dominio_email:
        salida.add(proveedor.dominio_email.strip().lower().lstrip("@"))
    return {d for d in salida if d}


def proveedor_por_correo(db: Session, tenant_id: UUID, email: str) -> ProveedorIdentidad | None:
    """A qué proveedor le toca este correo.

    Preguntarle al usuario cuál es su proveedor es una pregunta que no sabe
    contestar: él sabe su correo, no si su empresa usa Entra ID o Ping. El
    dominio lo decide sin preguntar nada.

    El subdominio hereda del dominio padre —`ventas.ejemplo.com` va al proveedor
    de `ejemplo.com`—, porque si no, cada filial obligaría a una fila nueva y el
    día que falte una, esa gente no puede entrar. Gana **el más específico**: si
    alguien configura `ventas.ejemplo.com` aparte, es porque quiere otra cosa
    para esa gente.
    """
    dominio = (email or "").strip().lower().rpartition("@")[2]
    if not dominio:
        return None

    candidatos = (
        db.execute(
            select(ProveedorIdentidad).where(
                ProveedorIdentidad.tenant_id == tenant_id,
                ProveedorIdentidad.activo.is_(True),
            )
        )
        .scalars()
        .all()
    )
    mejor: tuple[int, ProveedorIdentidad] | None = None
    for proveedor in candidatos:
        for suyo in _dominios_de(proveedor):
            if dominio == suyo:
                especificidad = 1000  # exacto: no hay nada mejor
            elif dominio.endswith("." + suyo):
                especificidad = suyo.count(".") + 1
            else:
                continue
            if mejor is None or especificidad > mejor[0]:
                mejor = (especificidad, proveedor)
    return mejor[1] if mejor else None


# ── Forzar SSO (CRM-00.05.01.13) ──────────────────────────────────────────


def exigir_sso_si_toca(db: Session, usuario: Usuario, tenant_id: UUID) -> None:
    """Corta la entrada con contraseña local cuando el tenant fuerza el SSO.

    Forzar SSO es lo que hace que la baja en el directorio corte el acceso de
    verdad. Con una contraseña local viva, el SSO es una comodidad y no un
    control: quien se va del directorio sigue entrando por la otra puerta, y esa
    puerta no la ve nadie porque nadie la mira.

    **La excepción de rescate es nominal y queda escrita.** Sin ninguna, un IdP
    mal configurado —o un certificado caducado un sábado— deja al cliente fuera
    de su propio CRM sin forma de arreglarlo, y la salida acaba siendo tocar la
    base de datos a mano. Se permite, pero con nombre y apellidos en la
    configuración y con un apunte de auditoría en cada uso: una excepción que no
    se ve deja de ser una excepción y pasa a ser la puerta de siempre.
    """
    forzado_global = bool(rt.efectivo("sso_forzado", db))
    proveedor = proveedor_por_correo(db, tenant_id, usuario.email)
    forzado = forzado_global or bool(proveedor and (proveedor.config or {}).get("forzar_sso"))
    if not forzado:
        return

    rescate = {
        str(c).strip().lower()
        for c in ((proveedor.config or {}).get("cuentas_de_rescate") or [])
        if proveedor
    }
    if usuario.email.lower() in rescate:
        registrar(
            db,
            accion="sso.rescate_usado",
            objeto="usuario",
            objeto_id=usuario.id,
            datos={
                "email": usuario.email,
                "motivo": "entrada con contraseña local en un tenant con SSO forzado",
            },
            tenant_id=tenant_id,
        )
        return

    raise Prohibido(
        "Esta organización exige entrar por su proveedor de identidad.",
        error_code="sso.obligatorio",
        detalle={"proveedor": proveedor.nombre if proveedor else None},
    )


def puede_tener_contrasena_local(db: Session, tenant_id: UUID, email: str) -> bool:
    """Si a este correo se le puede poner contraseña aquí.

    Se consulta antes de crear o cambiar una: dejar poner la contraseña y
    después no admitirla al entrar es un camino que acaba en un ticket.
    """
    if bool(rt.efectivo("sso_forzado", db)):
        return False
    proveedor = proveedor_por_correo(db, tenant_id, email)
    if proveedor is None:
        return True
    if not (proveedor.config or {}).get("forzar_sso"):
        return True
    rescate = {
        str(c).strip().lower() for c in ((proveedor.config or {}).get("cuentas_de_rescate") or [])
    }
    return email.strip().lower() in rescate


# ── Certificados del IdP y su caducidad (CRM-00.05.01.15) ─────────────────


@dataclass(frozen=True, slots=True)
class EstadoCertificado:
    proveedor_id: UUID
    proveedor: str
    huella: str
    caduca_at: datetime | None
    dias_restantes: int | None
    estado: str  # vigente | por_caducar | caducado | sin_fecha


def _fecha(valor: Any) -> datetime | None:
    if not valor:
        return None
    try:
        momento = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _con_tz(momento)


def certificados_de(db: Session, proveedor: ProveedorIdentidad) -> list[EstadoCertificado]:
    aviso = int(rt.efectivo("idp_aviso_caducidad_dias", db) or 30)
    ahora = _ahora()
    salida: list[EstadoCertificado] = []
    for entrada in proveedor.certificados or []:
        if not isinstance(entrada, dict):
            continue
        caduca = _fecha(entrada.get("caduca_at"))
        if caduca is None:
            estado, dias = "sin_fecha", None
        else:
            dias = (caduca - ahora).days
            if caduca <= ahora:
                estado = "caducado"
            elif dias <= aviso:
                estado = "por_caducar"
            else:
                estado = "vigente"
        salida.append(
            EstadoCertificado(
                proveedor_id=proveedor.id,
                proveedor=proveedor.nombre,
                huella=str(entrada.get("huella") or "")[:64],
                caduca_at=caduca,
                dias_restantes=dias,
                estado=estado,
            )
        )
    return salida


def revision_de_certificados(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Qué certificados de firma caducan y cuándo.

    Un certificado de IdP que caduca no avisa: un sábado por la noche deja de
    validar toda aserción y el lunes nadie de la empresa puede entrar. Esto se
    consulta desde el panel y alimenta el aviso, que es lo que convierte una
    caída en un correo de un mes antes.
    """
    proveedores = (
        db.execute(select(ProveedorIdentidad).where(ProveedorIdentidad.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    todos: list[EstadoCertificado] = []
    sin_declarar: list[str] = []
    for proveedor in proveedores:
        estados = certificados_de(db, proveedor)
        if not estados:
            # Se dice, en vez de omitirlo: un proveedor sin certificados
            # declarados no es uno «en verde», es uno del que no se sabe nada, y
            # la diferencia importa justo el día que caduca.
            sin_declarar.append(proveedor.nombre)
        todos.extend(estados)

    return {
        "revisado_at": _ahora().isoformat(),
        "certificados": [
            {
                "proveedor": c.proveedor,
                "proveedor_id": str(c.proveedor_id),
                "huella": c.huella,
                "caduca_at": c.caduca_at.isoformat() if c.caduca_at else None,
                "dias_restantes": c.dias_restantes,
                "estado": c.estado,
            }
            for c in sorted(todos, key=lambda c: (c.dias_restantes is None, c.dias_restantes or 0))
        ],
        "caducados": [c.proveedor for c in todos if c.estado == "caducado"],
        "por_caducar": [c.proveedor for c in todos if c.estado == "por_caducar"],
        "proveedores_sin_certificado_declarado": sin_declarar,
        "en_verde": (
            not [c for c in todos if c.estado in ("caducado", "por_caducar")] and not sin_declarar
        ),
    }


def anadir_certificado(
    db: Session,
    proveedor: ProveedorIdentidad,
    *,
    huella: str,
    caduca_at: datetime | None,
    pem: str = "",
) -> None:
    """Añade un certificado **sin quitar el anterior**.

    Una rotación bien hecha tiene los dos válidos a la vez: el IdP empieza a
    firmar con el nuevo cuando le toca, y mientras tanto las aserciones firmadas
    con el viejo siguen valiendo. Sustituir uno por otro convierte la rotación en
    una ventana de caída para todo el tenant, coordinada al minuto con un
    departamento que no es el nuestro.
    """
    if not (huella or "").strip():
        raise ErrorValidacion("Falta la huella del certificado.", error_code="idp.sin_huella")
    actuales = list(proveedor.certificados or [])
    if any(str(c.get("huella")) == huella for c in actuales if isinstance(c, dict)):
        raise Conflicto("Ese certificado ya está declarado", error_code="idp.certificado_repetido")
    actuales.append(
        {
            "huella": huella,
            "caduca_at": caduca_at.isoformat() if caduca_at else None,
            "pem": pem,
            "alta_at": _ahora().isoformat(),
        }
    )
    proveedor.certificados = actuales
    registrar(
        db,
        accion="idp.certificado_anadido",
        objeto="proveedor_identidad",
        objeto_id=proveedor.id,
        datos={"huella": huella, "caduca_at": caduca_at.isoformat() if caduca_at else None},
        tenant_id=proveedor.tenant_id,
    )


def retirar_certificado(db: Session, proveedor: ProveedorIdentidad, huella: str) -> None:
    """Quita un certificado, salvo que sea el último vigente.

    Quitar el último deja al tenant sin poder validar nada, y el momento en que
    se descubre es cuando alguien intenta entrar. Que falle **aquí**, con el
    administrador delante, es la diferencia entre un mensaje y una caída.
    """
    actuales = [c for c in (proveedor.certificados or []) if isinstance(c, dict)]
    quedan = [c for c in actuales if str(c.get("huella")) != huella]
    if len(quedan) == len(actuales):
        raise Conflicto("Ese certificado no está declarado", error_code="idp.certificado_ausente")

    ahora = _ahora()
    vigentes = [
        c for c in quedan if (_fecha(c.get("caduca_at")) or ahora + timedelta(days=1)) > ahora
    ]
    if not vigentes:
        raise Conflicto(
            "No se puede retirar: es el único certificado vigente y el tenant se "
            "quedaría sin poder validar ninguna aserción.",
            error_code="idp.ultimo_certificado",
        )
    proveedor.certificados = quedan
    registrar(
        db,
        accion="idp.certificado_retirado",
        objeto="proveedor_identidad",
        objeto_id=proveedor.id,
        datos={"huella": huella, "quedan": len(quedan)},
        tenant_id=proveedor.tenant_id,
    )


# ── SSO iniciado por el proveedor (CRM-00.05.01.11) ───────────────────────


def admitir_asercion_idp(
    db: Session,
    proveedor: ProveedorIdentidad,
    *,
    id_asercion: str,
    no_despues_de: datetime | None,
    en_respuesta_a: str | None = None,
) -> None:
    """Acepta una aserción que empieza en el IdP, una sola vez.

    En el SSO que empieza aquí, nuestra petición lleva un identificador y la
    respuesta tiene que citarlo (`InResponseTo`): eso ata la aserción a una
    petición concreta e impide reenviarla. En el que empieza en el IdP **no hay
    petición**, así que no hay nada que citar, y una aserción interceptada —en un
    proxy, en un registro de servidor, en el historial del navegador— vale otra
    vez hasta que caduque.

    Lo único que lo cierra es recordar las que ya se han usado. Por eso esto es
    obligatorio y no una opción, y por eso el flujo entero va apagado por
    defecto: activarlo tiene que ser la decisión de alguien que sepa que está
    aceptando aserciones que él no ha pedido.
    """
    if not proveedor.permite_idp_initiated:
        raise Prohibido(
            "Este proveedor no acepta inicios de sesión que empiecen en el IdP.",
            error_code="sso.idp_initiated_desactivado",
            detalle={"proveedor": proveedor.nombre},
        )
    if en_respuesta_a:
        # Si cita una petición, no es una aserción iniciada en el IdP: es una
        # normal y tiene que validarse por el otro camino, que es más fuerte.
        raise ErrorValidacion(
            "La aserción cita una petición: no es un inicio del IdP.",
            error_code="sso.no_es_idp_initiated",
        )
    if not (id_asercion or "").strip():
        # Sin identificador no hay forma de detectar el reenvío, y aceptar
        # «porque no se puede comprobar» es no tener la comprobación.
        raise NoAutenticado(
            "La aserción no trae identificador; no se puede garantizar que no sea " "un reenvío.",
            error_code="sso.asercion_sin_id",
        )

    caduca = _con_tz(no_despues_de) or (_ahora() + timedelta(minutes=10))
    if caduca <= _ahora():
        raise NoAutenticado("La aserción ha caducado.", error_code="sso.asercion_caducada")

    hash_asercion = _hash(id_asercion)
    ya = db.execute(
        select(AsercionConsumida).where(
            AsercionConsumida.tenant_id == proveedor.tenant_id,
            AsercionConsumida.hash_asercion == hash_asercion,
        )
    ).scalar_one_or_none()
    if ya is not None:
        registrar(
            db,
            accion="sso.asercion_reenviada",
            objeto="proveedor_identidad",
            objeto_id=proveedor.id,
            datos={"proveedor": proveedor.nombre},
            tenant_id=proveedor.tenant_id,
        )
        raise NoAutenticado("Esa aserción ya se ha usado.", error_code="sso.asercion_reenviada")

    db.add(
        AsercionConsumida(
            tenant_id=proveedor.tenant_id,
            hash_asercion=hash_asercion,
            proveedor_id=proveedor.id,
            expira_at=caduca,
        )
    )
    db.flush()


def purgar_aserciones(db: Session, *, limite: int = 5000) -> int:
    """Tira las aserciones ya caducadas: pasada su ventana no sirven ni para
    reenviarlas, así que guardarlas solo hace crecer la tabla."""
    filas = (
        db.execute(
            select(AsercionConsumida).where(AsercionConsumida.expira_at < _ahora()).limit(limite)
        )
        .scalars()
        .all()
    )
    for fila in filas:
        db.delete(fila)
    return len(filas)


# ── Cierre de sesión único (CRM-00.05.01.12) ──────────────────────────────


def atar_sesion_al_idp(
    db: Session,
    *,
    sesion: Sesion,
    proveedor_id: UUID,
    usuario_id: UUID,
    tenant_id: UUID,
    indice_idp: str,
    sujeto_idp: str = "",
) -> SesionIdP | None:
    """Guarda la correspondencia entre nuestra sesión y la del IdP.

    Sin ella, el aviso de cierre llega con el identificador del IdP y no hay a
    quién aplicárselo: cerrar sesión en el proveedor deja el CRM abierto, que es
    justo lo que el usuario cree que acaba de evitar.
    """
    if not (indice_idp or "").strip() and not (sujeto_idp or "").strip():
        # No es un fallo: hay proveedores que no mandan índice de sesión. Se
        # devuelve `None` y el cierre único se degrada a cerrar por sujeto o a
        # no cerrar, pero eso se ve en la lista, no se descubre.
        return None
    fila = SesionIdP(
        tenant_id=tenant_id,
        sesion_id=sesion.id,
        proveedor_id=proveedor_id,
        usuario_id=usuario_id,
        indice_idp=(indice_idp or "")[:200],
        sujeto_idp=(sujeto_idp or "")[:300],
    )
    db.add(fila)
    db.flush()
    return fila


def cerrar_por_aviso_del_idp(
    db: Session,
    tenant_id: UUID,
    *,
    indice_idp: str = "",
    sujeto_idp: str = "",
) -> dict[str, Any]:
    """Cierra aquí las sesiones que el IdP dice que se han cerrado allí.

    Se admite cerrar por índice de sesión o por sujeto, porque los proveedores
    hacen las dos cosas: unos mandan la sesión concreta y otros dicen «esta
    persona ha salido de todo». Por sujeto cierra **todas** las suyas de ese
    proveedor, que es lo que el usuario ha pedido al pulsar salir.
    """
    if not (indice_idp or sujeto_idp):
        raise ErrorValidacion(
            "El aviso de cierre no trae ni índice de sesión ni sujeto.",
            error_code="slo.aviso_vacio",
        )

    consulta = select(SesionIdP).where(
        SesionIdP.tenant_id == tenant_id, SesionIdP.cerrada_at.is_(None)
    )
    if indice_idp:
        consulta = consulta.where(SesionIdP.indice_idp == indice_idp)
    else:
        consulta = consulta.where(SesionIdP.sujeto_idp == sujeto_idp)

    enlaces = db.execute(consulta).scalars().all()
    cerradas = 0
    for enlace in enlaces:
        enlace.cerrada_at = _ahora()
        sesion = db.get(Sesion, enlace.sesion_id)
        if sesion is not None and sesion.revocada_at is None:
            sesion.revocada_at = _ahora()
            sesion.motivo_revocacion = "cierre_unico_idp"
            cerradas += 1

    registrar(
        db,
        accion="sesion.cierre_unico",
        objeto="usuario",
        objeto_id=enlaces[0].usuario_id if enlaces else None,
        datos={
            "origen": "idp",
            "por": "indice" if indice_idp else "sujeto",
            "enlaces": len(enlaces),
            "sesiones_cerradas": cerradas,
        },
        tenant_id=tenant_id,
    )
    return {
        "enlaces": len(enlaces),
        "sesiones_cerradas": cerradas,
        # Que no hubiera nada que cerrar NO es un error: el IdP puede avisar de
        # una sesión que aquí ya había caducado. Se responde 200 y se dice,
        # porque devolver un error haría que el proveedor reintentara en bucle.
        "nada_que_cerrar": not enlaces,
    }


def enlaces_de_sesion(db: Session, sesion_id: UUID, tenant_id: UUID) -> list[SesionIdP]:
    return list(
        db.execute(
            select(SesionIdP).where(
                SesionIdP.sesion_id == sesion_id, SesionIdP.tenant_id == tenant_id
            )
        )
        .scalars()
        .all()
    )


def salida_propagada(db: Session, sesion: Sesion, tenant_id: UUID) -> dict[str, Any]:
    """Cuando la salida empieza aquí: cerrar y decir a quién hay que avisar.

    El cierre en el IdP no lo hace este módulo —lo manda el canal del protocolo,
    que conoce `saml.py` u `oidc.py`—, pero sí dice **qué** hay que mandar y a
    quién. Cerrar solo aquí deja la sesión del IdP viva, y volver a entrar no
    pide credenciales: para el usuario, el botón de salir no ha hecho nada.
    """
    if sesion.revocada_at is None:
        sesion.revocada_at = _ahora()
        sesion.motivo_revocacion = "cierre_sesion"

    pendientes = []
    for enlace in enlaces_de_sesion(db, sesion.id, tenant_id):
        if enlace.cerrada_at is None:
            enlace.cerrada_at = _ahora()
        pendientes.append(
            {
                "proveedor_id": str(enlace.proveedor_id),
                "indice_idp": enlace.indice_idp,
                "sujeto_idp": enlace.sujeto_idp,
            }
        )
    return {
        "sesion_cerrada": True,
        "avisar_al_idp": pendientes,
        # Si no hay enlace, la sesión no vino de un IdP: no hay nada que
        # propagar y decirlo evita que alguien busque un fallo de propagación.
        "sin_federacion": not pendientes,
    }


# ── SSO compartido por la suite (CRM-00.01.07.09) ─────────────────────────

# Qué herramientas se cablean contra el proveedor es **una decisión del cliente**
# y se declara en el propio proveedor, no se descubre solo ni viene escrita aquí:
# conectar una herramienta nueva al SSO es algo que se pide, no un efecto de que
# aparezca un servicio. Aquí hubo tres nombres de la casa escritos a fuego, y eso
# dejaba fuera a la cuarta el día que existiera y a cualquier herramienta que no
# fuera nuestra desde el primer día.


def _huella_certificados(certificados: Any) -> str:
    """Un resumen estable de los certificados que acepta el proveedor.

    Estable importa: durante una rotación conviven el viejo y el nuevo, y si la
    huella cambiara según el orden en que llegan, las tres herramientas parecerían
    tener certificados distintos justo el día de la rotación — que es el día en
    que hay que poder mirarlo.
    """
    valores = sorted(str(c) for c in (certificados or []))
    return hashlib.sha256("|".join(valores).encode()).hexdigest()[:32] if valores else ""


def plan_de_sso_compartido(
    db: Session,
    tenant_id: UUID,
    *,
    herramientas: Sequence[str] | None = None,
    herramientas_conectadas: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Qué herramientas de la suite usan ya el proveedor de identidad del tenant.

    El proveedor se configura **una vez** y lo usan las tres: repetir la
    configuración en cada herramienta es cómo se acaba con tres certificados
    distintos, dos caducados, y nadie sabiendo cuál es el bueno.

    Lo que devuelve es el **estado real**, no la intención. Una herramienta que
    dice estar conectada y tiene otro certificado no está compartiendo el SSO:
    está teniendo el suyo, y el día que el cliente rote el certificado se caerá
    solo esa.

    **Qué herramientas se miran es configuración, no producto.** Salen del propio
    proveedor (`config["herramientas"]`), que es donde se declara qué se cablea
    contra él. Traer tres nombres escritos en el código dejaba fuera a la cuarta
    el día que existiera, y a cualquier herramienta que no fuera de la casa desde
    el primer día. La lista fija se queda sólo como último recurso para un
    proveedor que no declare ninguna.

    Y el cableado se declara **aquí y no en la conexión de aprovisionamiento**,
    porque son dos hechos distintos: que empujemos usuarios a una herramienta no
    dice nada de contra quién autentica, y una puede estar conectada para lo
    primero y no para lo segundo.
    """
    from services.identity.modelos import ProveedorIdentidad

    proveedor = (
        db.execute(
            select(ProveedorIdentidad).where(
                ProveedorIdentidad.tenant_id == tenant_id,
                ProveedorIdentidad.activo.is_(True),
            )
        )
        .scalars()
        .first()
    )
    if proveedor is None:
        return {
            "hay_proveedor": False,
            "porque": (
                "Este tenant no tiene proveedor de identidad activo: no hay nada "
                "que compartir todavía."
            ),
            "herramientas": [],
        }

    declaradas = (proveedor.config or {}).get("herramientas") or {}
    nombres = list(herramientas) if herramientas is not None else sorted(declaradas)

    if not nombres:
        # Ni «completo» ni «incompleto»: no hay nada que compartir. Decir que sí
        # porque la lista está vacía —que es lo que sale de comparar dos ceros—
        # pintaría de verde a un tenant sin ninguna herramienta cableada.
        return {
            "hay_proveedor": True,
            "proveedor": proveedor.nombre,
            "tipo": proveedor.tipo,
            "herramientas": [],
            "comparten": [],
            "completo": False,
            "que_significa": (
                "Hay proveedor de identidad, pero no hay ninguna herramienta "
                "declarada contra él: no hay con quién compartirlo todavía."
            ),
        }

    estado = herramientas_conectadas or declaradas or {}
    filas = []
    for herramienta in nombres:
        suyo = estado.get(herramienta) or {}
        conectada = bool(suyo.get("conectada"))
        # La huella se calcula de los certificados declarados: el modelo guarda
        # la lista, no un resumen, porque durante una rotación conviven dos.
        misma_huella = str(suyo.get("huella_certificado") or "") == _huella_certificados(
            proveedor.certificados
        )
        filas.append(
            {
                "herramienta": herramienta,
                "conectada": conectada,
                # Conectada y compartiendo no son lo mismo, y es la distinción que
                # decide qué se cae el día que el cliente rote el certificado.
                "comparte_de_verdad": conectada and misma_huella,
                "porque": (
                    "Usa el mismo proveedor y el mismo certificado."
                    if conectada and misma_huella
                    else "Está conectada con OTRO certificado: tiene su propio SSO, no "
                    "el compartido. El día que el cliente rote el suyo, esta se cae "
                    "sola y nadie sabrá por qué."
                    if conectada
                    else "No está conectada al SSO del tenant: sus usuarios entran por "
                    "otro camino."
                ),
            }
        )

    comparten = [f["herramienta"] for f in filas if f["comparte_de_verdad"]]
    return {
        "hay_proveedor": True,
        "proveedor": proveedor.nombre,
        "tipo": proveedor.tipo,
        "herramientas": filas,
        "comparten": comparten,
        "completo": len(comparten) == len(nombres),
        "que_significa": (
            "Todas las herramientas conectadas entran por el mismo proveedor: una "
            "rotación de certificado se hace una vez."
            if len(comparten) == len(nombres)
            else "No todas comparten. Cada una que no lo haga es una configuración "
            "más que mantener y un certificado más que caduca por su cuenta."
        ),
    }
