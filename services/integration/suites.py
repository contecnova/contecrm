"""Suites de productividad: el perfil, el consentimiento, la credencial, el
incremento y la suscripción (CRM-06.01.03.01 a .05).

Outlook, Gmail, Teams, OneNote, Drive. Lo que los clientes piden —«que el CRM
hable con nuestro correo y nuestro calendario»— es razonable y es donde más
integraciones se pudren, siempre por el mismo sitio: alguien escribe un módulo
para Microsoft, luego otro para Google, y a partir de ahí **cada implantación
nueva es una versión del producto**. Cuando el tercer cliente pide algo raro, hay
tres módulos que mantener y ninguno se parece.

Aquí no hay un conector por casa. Un proveedor es un **perfil declarado**: qué
recursos ofrece, en qué endpoint, con qué campos, cómo pide el incremento y qué
límites tiene. Añadir uno es escribir configuración, y el que lo escribe no
necesita tocar el producto.

Las decisiones:

**El consentimiento es del dueño del buzón, no del administrador.** Un
administrador que conecta el correo de su equipo entero desde una pantalla es
exactamente lo que hace que una integración acabe en el comité de empresa. Aquí
el administrador declara el perfil; autorizar lo hace cada persona.

**Se pide el alcance mínimo, y pedir de más se rechaza.** Pedir «leer todo el
correo» para sincronizar el calendario es lo normal en las integraciones de
mercado, y es la razón de que a muchas no las dejen entrar. Si el perfil declara
un alcance que ningún recurso pedido necesita, no se pide.

**El incremento es del proveedor, y se guarda tal cual.** Cada uno usa el suyo
—un token de delta, un `historyId`, una fecha— y traducirlo a un formato común
sería inventar un estándar que no aporta nada. Lo que sí es nuestro es la regla:
la marca **solo avanza sobre lo confirmado**.

**Y una suscripción a cambios caduca.** Todas. La que no se renueva deja de
llegar sin dar ningún error: el CRM simplemente se queda quieto y el usuario cree
que no ha pasado nada en su buzón. Por eso se renueva antes de tiempo y, si no se
puede, **se vuelve al sondeo** en vez de quedarse mudo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

if TYPE_CHECKING:  # pragma: no cover — solo para el tipo
    from services.integration.modelos import Conexion

logger = get_logger(__name__)

# Qué puede traer o llevar una suite. Lista cerrada porque cada recurso tiene su
# alcance, su forma de pedir el incremento y su conversación distinta con el
# responsable de protección de datos. Con texto libre, un perfil podría declarar
# «todo» y nadie sabría qué firmó.
RECURSOS = (
    "correo",
    "calendario",
    "contactos",
    "tareas",
    "notas",
    "ficheros",
    "reuniones",
    "libre_ocupado",
    "chat",
)

# Recursos que traen datos personales de terceros —gente que no es usuaria del
# CRM ni cliente— y que por eso necesitan una decisión explícita. La agenda
# personal de alguien tiene a su médico y a su hermana.
CON_DATO_DE_TERCEROS = ("correo", "contactos", "calendario", "chat")

# Cómo pide cada perfil «lo que ha cambiado desde la última vez».
ESTRATEGIAS_INCREMENTO = (
    "token_delta",  # el proveedor devuelve un testigo opaco
    "marca_de_tiempo",  # se filtra por fecha de modificación
    "numero_de_version",  # un contador creciente
    "completo",  # no hay incremento: se trae todo cada vez
)

# En qué sentido va cada recurso. `escribir` no es un detalle: un perfil de solo lectura no puede
# estropear el calendario de nadie, y es lo que hay que poder enseñar cuando
# alguien pregunta si esto «toca» su buzón.
SENTIDOS = ("leer", "escribir")

# Cuánto antes de que caduque se renueva una suscripción. Con el margen justo,
# un reintento fallido la deja caducar y el flujo se para sin decir nada.
MARGEN_RENOVACION = timedelta(hours=6)

# Cuánto antes de que caduque una credencial se avisa. Una credencial sin aviso
# se descubre caducada cuando alguien echa de menos una reunión.
MARGEN_AVISO_CREDENCIAL = timedelta(days=7)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class ConsentimientoSuite(Base, TimestampMixin, SoftDeleteMixin):
    """Lo que una persona ha autorizado, recurso a recurso.

    Una fila por persona y recurso a propósito: «conectó su Microsoft 365» no es
    una respuesta cuando alguien pregunta si el CRM lee sus correos. Esto sí lo
    es.
    """

    __tablename__ = "consentimientos_suite"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Marcado como personal a propósito, aunque solo sea un identificador: la
    # fila entera ES un dato sobre esa persona —qué autorizó leer de su buzón y
    # cuándo—, y si no constara aquí no aparecería en el registro de tratamiento.
    usuario_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, info={"sensibilidad": "personal"}
    )
    perfil: Mapped[str] = mapped_column(String(80), nullable=False)
    recurso: Mapped[str] = mapped_column(String(30), nullable=False)
    sentido: Mapped[str] = mapped_column(
        String(10), nullable=False, default="leer", info={"opciones": SENTIDOS}
    )
    # Los alcances que se pidieron de verdad. Se guardan para poder contestar
    # «¿qué permisos le disteis al CRM?» con la lista, no con una impresión.
    alcances: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    concedido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cuándo deja de valer la credencial que el proveedor entregó, y si hay con
    # qué renovarla sin molestar a la persona. Las dos cosas se guardan porque
    # **una credencial sin refresco y con caducidad es una bomba de relojería**:
    # funciona meses y un martes deja de entrar el correo de veinte personas a
    # la vez. Sin este par, `estado_credencial` sólo podía contestar «no consta
    # caducidad», que es verdad y no sirve para nada.
    credencial_caduca_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tiene_refresco: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Quién lo concedió. Tiene que ser la propia persona: si aquí aparece otro,
    # es que alguien lo hizo por ella, y eso hay que poder verlo.
    concedido_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "usuario_id", "perfil", "recurso", "sentido", name="uq_consentimiento"
        ),
    )


class SuscripcionSuite(Base, TimestampMixin):
    """Una suscripción a los cambios de un recurso en el proveedor."""

    __tablename__ = "suscripciones_suite"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Personal por lo mismo: esta fila dice que el buzón de esta persona está
    # siendo escuchado por el CRM, y eso es un dato sobre ella.
    usuario_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, info={"sensibilidad": "personal"}
    )
    perfil: Mapped[str] = mapped_column(String(80), nullable=False)
    recurso: Mapped[str] = mapped_column(String(30), nullable=False)
    # El identificador que devuelve el proveedor. Sin él no se puede renovar ni
    # borrar, y queda una suscripción huérfana mandando avisos a un sitio que ya
    # no los atiende.
    externo_id: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    caduca_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    renovada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # activa | caducada | sondeo | error
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="activa")
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Si se ha caído al sondeo. Se marca para que el panel pueda decirlo: una
    # integración que sondea cada diez minutos no es igual que una que avisa al
    # instante, y el usuario tiene que saber por qué su cita tarda.
    en_sondeo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "usuario_id", "perfil", "recurso", name="uq_suscripcion"),
        Index("ix_suscripciones_caducidad", "tenant_id", "caduca_at"),
    )


# ── El perfil (CRM-06.01.03.01) ───────────────────────────────────────────


def validar_perfil(config: dict[str, Any]) -> dict[str, Any]:
    """Qué le falta o le sobra a un perfil de suite.

    Se devuelven **todos** los problemas: quien está declarando un proveedor
    agradece ver las cinco cosas que faltan de una vez mucho más que
    descubrirlas de una en una, con un intento de sincronizar entre cada dos.
    """
    problemas: list[dict[str, str]] = []
    avisos: list[str] = []

    recursos = dict(config.get("recursos") or {})
    if not recursos:
        problemas.append(
            {
                "donde": "recursos",
                "problema": "el perfil no declara ningún recurso",
                "consecuencia": "no sincronizaría nada, y el panel diría que está bien",
            }
        )

    for nombre, declaracion in recursos.items():
        if nombre not in RECURSOS:
            problemas.append(
                {
                    "donde": nombre,
                    "problema": "recurso desconocido",
                    "consecuencia": (f"nunca se pediría; los admitidos son {', '.join(RECURSOS)}"),
                }
            )
            continue
        decl = dict(declaracion or {})
        if not str(decl.get("endpoint") or "").strip():
            problemas.append(
                {
                    "donde": nombre,
                    "problema": "no dice a qué endpoint se pide",
                    "consecuencia": "la sincronización fallaría en la primera llamada",
                }
            )
        if not dict(decl.get("campos") or {}):
            problemas.append(
                {
                    "donde": nombre,
                    "problema": "no declara la correspondencia de campos",
                    "consecuencia": (
                        "el dato llegaría y no se sabría dónde ponerlo; sin esto, el "
                        "perfil no sustituye a un módulo escrito a mano"
                    ),
                }
            )
        estrategia = str(decl.get("incremento") or "")
        if estrategia not in ESTRATEGIAS_INCREMENTO:
            problemas.append(
                {
                    "donde": nombre,
                    "problema": f"estrategia de incremento «{estrategia}» desconocida",
                    "consecuencia": (
                        "sin incremento hay que traerlo todo cada vez, y eso deja de "
                        "funcionar justo cuando el cliente ya depende de ello"
                    ),
                }
            )
        elif estrategia == "completo":
            avisos.append(
                f"«{nombre}» se trae entero en cada vuelta. Funciona con cien "
                "elementos y deja de funcionar con cien mil, y para entonces ya hay "
                "gente dependiendo de ello."
            )
        for sentido in decl.get("sentidos") or ["leer"]:
            if sentido not in SENTIDOS:
                problemas.append(
                    {
                        "donde": nombre,
                        "problema": f"dirección «{sentido}» desconocida",
                        "consecuencia": "no se sabría si el CRM puede escribir ahí",
                    }
                )

    limites = dict(config.get("limites") or {})
    if not limites.get("peticiones_por_minuto"):
        avisos.append(
            "El perfil no declara el límite del proveedor. Sin él, la primera "
            "sincronización grande se come la cuota del tenant entero y el proveedor "
            "corta — a todo el mundo, no solo a esta integración."
        )
    if not str(config.get("token_url") or "").strip():
        problemas.append(
            {
                "donde": "token_url",
                "problema": "no dice dónde se cambian las credenciales por un token",
                "consecuencia": "no se podría autorizar a nadie",
            }
        )

    alcances = dict(config.get("alcances") or {})
    sobrantes = sorted(
        clave for clave in alcances if clave.split(".")[0] not in recursos and clave != "base"
    )
    if sobrantes:
        problemas.append(
            {
                "donde": "alcances",
                "problema": f"se declaran alcances de recursos que no se usan: {sobrantes}",
                "consecuencia": (
                    "se pediría permiso para algo que el CRM no va a leer, que es "
                    "justo por lo que a muchas integraciones no las dejan entrar"
                ),
            }
        )

    return {"valido": not problemas, "problemas": problemas, "avisos": avisos}


def declarar_perfil(
    uow: UnidadDeTrabajo,
    *,
    nombre: str,
    sistema: str,
    config: dict[str, Any],
) -> "Conexion":
    """Declara un proveedor de productividad como configuración.

    Es una `Conexion` como cualquier otra —el mismo conector declarativo, la
    misma bóveda de credenciales— y no un concepto nuevo. Un «módulo de
    Microsoft» al lado del resto de integraciones sería el principio de tener dos
    formas de integrar y una sola mantenida.
    """
    # Importado aquí y no arriba: `modelos` importa este módulo para registrar
    # sus tablas, y al revés sería un ciclo.
    from services.integration.modelos import Conexion

    veredicto = validar_perfil(config)
    if not veredicto["valido"]:
        raise ErrorValidacion(
            f"El perfil «{nombre}» tiene {len(veredicto['problemas'])} problemas que "
            "harían que la sincronización fallara o trajera de menos sin avisar.",
            error_code="suite.perfil_invalido",
            detalle={"problemas": veredicto["problemas"]},
        )

    fila = uow.db.execute(
        select(Conexion).where(Conexion.tenant_id == uow.tenant_id, Conexion.nombre == nombre)
    ).scalar_one_or_none()
    if fila is None:
        fila = Conexion(tenant_id=uow.tenant_id, nombre=nombre, protocolo="rest")
        uow.db.add(fila)
    fila.sistema = sistema
    fila.config = {**config, "clase": "suite_productividad"}
    uow.db.flush()

    if veredicto["avisos"]:
        logger.warning(
            "suite.perfil_con_avisos", extra={"perfil": nombre, "avisos": veredicto["avisos"]}
        )
    return fila


def perfil(db: Session, tenant_id: UUID, nombre: str) -> dict[str, Any]:
    """El perfil declarado, o un error que dice que no está."""
    from services.integration.modelos import Conexion

    fila = db.execute(
        select(Conexion).where(Conexion.tenant_id == tenant_id, Conexion.nombre == nombre)
    ).scalar_one_or_none()
    if fila is None or dict(fila.config or {}).get("clase") != "suite_productividad":
        raise NoEncontrado(
            f"No hay ningún perfil de suite llamado «{nombre}»",
            error_code="suite.perfil_no_encontrado",
        )
    return dict(fila.config)


def capacidades_de(config: dict[str, Any]) -> dict[str, Any]:
    """Qué sabe hacer este perfil, para poder enseñarlo antes de conectar nada.

    Con el dato de terceros marcado. Quien autoriza tiene derecho a saber que
    sincronizar sus contactos sube al CRM el teléfono de su médico, y esa frase
    hay que poder ponerla en la pantalla.
    """
    recursos = dict(config.get("recursos") or {})
    return {
        "recursos": sorted(recursos),
        "detalle": [
            {
                "recurso": nombre,
                "sentidos": list(dict(d or {}).get("sentidos") or ["leer"]),
                "incremento": dict(d or {}).get("incremento"),
                "trae_dato_de_terceros": nombre in CON_DATO_DE_TERCEROS,
                "aviso": (
                    "Trae datos de gente que no es ni usuaria del CRM ni cliente: la "
                    "agenda personal de alguien tiene a su médico y a su hermana."
                    if nombre in CON_DATO_DE_TERCEROS
                    else ""
                ),
            }
            for nombre, d in sorted(recursos.items())
        ],
        "limites_declarados": dict(config.get("limites") or {}),
    }


# ── Consentimiento y alcance mínimo (CRM-06.01.03.02) ─────────────────────


def alcance_minimo(
    *, config: dict[str, Any], recursos: list[str], sentido: str = "leer"
) -> dict[str, Any]:
    """Los alcances que hay que pedir, **y ni uno más**.

    Pedir «leer todo el correo» para sincronizar el calendario es lo normal en
    las integraciones de mercado y es la razón de que a muchas no las dejen
    entrar en una empresa grande. Aquí se pide lo de los recursos que se van a
    usar, y se dice qué se ha dejado fuera para que se pueda enseñar.
    """
    if sentido not in SENTIDOS:
        raise ErrorValidacion(
            f"Dirección «{sentido}» desconocida", error_code="suite.direccion_invalida"
        )
    declarados = dict(config.get("alcances") or {})
    disponibles = dict(config.get("recursos") or {})

    desconocidos = sorted(set(recursos) - set(disponibles))
    if desconocidos:
        raise ErrorValidacion(
            f"El perfil no ofrece: {', '.join(desconocidos)}",
            error_code="suite.recurso_no_ofrecido",
            detalle={"ofrece": sorted(disponibles)},
        )

    pedidos: list[str] = []
    if declarados.get("base"):
        pedidos.append(str(declarados["base"]))
    for recurso in sorted(set(recursos)):
        clave = f"{recurso}.{sentido}"
        alcance = declarados.get(clave)
        if not alcance:
            raise ErrorValidacion(
                f"El perfil no declara el alcance «{clave}». Pedir uno más amplio "
                "«por si acaso» es exactamente lo que hace que una integración no "
                "pase la revisión de seguridad del cliente.",
                error_code="suite.alcance_sin_declarar",
            )
        pedidos.append(str(alcance))

    no_pedidos = sorted(v for k, v in declarados.items() if k != "base" and str(v) not in pedidos)
    return {
        "alcances": sorted(set(pedidos)),
        "no_se_piden": no_pedidos,
        "porque": (
            "Solo lo de los recursos que se van a usar. Los demás alcances que el "
            "perfil conoce se quedan sin pedir, y eso es lo que se le puede enseñar a "
            "quien revise la integración."
        ),
    }


def conceder(
    uow: UnidadDeTrabajo,
    *,
    usuario_id: UUID,
    quien_concede: UUID,
    perfil_nombre: str,
    recursos: list[str],
    alcances: list[str],
    sentido: str = "leer",
    credencial_caduca_at: datetime | None = None,
    tiene_refresco: bool = False,
) -> dict[str, Any]:
    """La persona autoriza el acceso a sus recursos.

    **Tiene que concederlo ella.** Un administrador que conecta el correo de su
    equipo entero desde una pantalla es exactamente lo que hace que una
    integración acabe discutiéndose en el comité de empresa — y con razón: nadie
    le ha preguntado a esa gente.
    """
    if quien_concede != usuario_id:
        raise Prohibido(
            "El consentimiento lo da el dueño del buzón, no otra persona por él. Un "
            "administrador puede declarar el perfil y pedirlo; autorizarlo, no.",
            error_code="suite.consentimiento_ajeno",
        )
    if not recursos:
        raise ErrorValidacion(
            "No se puede conceder acceso «en general»: se concede recurso a recurso, "
            "que es lo que permite contestar después qué se autorizó exactamente.",
            error_code="suite.consentimiento_vacio",
        )

    concedidos: list[str] = []
    for recurso in sorted(set(recursos)):
        if recurso not in RECURSOS:
            raise ErrorValidacion(
                f"Recurso «{recurso}» desconocido", error_code="suite.recurso_invalido"
            )
        fila = uow.db.execute(
            select(ConsentimientoSuite).where(
                ConsentimientoSuite.tenant_id == uow.tenant_id,
                ConsentimientoSuite.usuario_id == usuario_id,
                ConsentimientoSuite.perfil == perfil_nombre,
                ConsentimientoSuite.recurso == recurso,
                ConsentimientoSuite.sentido == sentido,
            )
        ).scalar_one_or_none()
        if fila is None:
            fila = ConsentimientoSuite(
                tenant_id=uow.tenant_id,
                usuario_id=usuario_id,
                perfil=perfil_nombre,
                recurso=recurso,
                sentido=sentido,
            )
            uow.db.add(fila)
        fila.alcances = sorted(set(alcances))
        fila.concedido_at = _ahora()
        fila.revocado_at = None
        fila.concedido_por = quien_concede
        fila.credencial_caduca_at = credencial_caduca_at
        fila.tiene_refresco = bool(tiene_refresco)
        concedidos.append(recurso)

    uow.db.flush()
    return {
        "usuario_id": str(usuario_id),
        "perfil": perfil_nombre,
        "recursos": concedidos,
        "sentido": sentido,
        "alcances": sorted(set(alcances)),
    }


def revocar(
    uow: UnidadDeTrabajo, *, usuario_id: UUID, perfil_nombre: str, recursos: list[str] | None = None
) -> dict[str, Any]:
    """La persona retira el permiso, entero o de un recurso.

    Revocar **no borra lo ya sincronizado**, y eso hay que decirlo: lo que ya
    entró son actividades del CRM que otra gente ha usado. Lo que se para es que
    entre más. Borrar lo anterior es otra decisión, y se toma aparte
    (CRM-06.01.03.17).
    """
    condiciones = [
        ConsentimientoSuite.tenant_id == uow.tenant_id,
        ConsentimientoSuite.usuario_id == usuario_id,
        ConsentimientoSuite.perfil == perfil_nombre,
    ]
    if recursos:
        condiciones.append(ConsentimientoSuite.recurso.in_(list(recursos)))

    filas = list(uow.db.execute(select(ConsentimientoSuite).where(*condiciones)).scalars().all())
    for fila in filas:
        fila.revocado_at = _ahora()
    uow.db.flush()

    return {
        "revocados": [f.recurso for f in filas],
        "lo_ya_sincronizado": (
            "Se queda. Lo que entró son actividades del CRM que otra gente ha usado; "
            "borrarlas es otra decisión y se pide aparte."
        ),
        "que_pasa_ahora": "No entra nada más de esos recursos hasta que se vuelva a autorizar.",
    }


def exigir_consentimiento(
    db: Session,
    tenant_id: UUID,
    *,
    usuario_id: UUID,
    perfil_nombre: str,
    recurso: str,
    sentido: str = "leer",
) -> ConsentimientoSuite:
    """Se llama **antes** de cada sincronización, no al conectar.

    Comprobarlo solo al conectar deja seguir leyendo el buzón de alguien que
    revocó ayer, y eso no es un fallo técnico: es leer el correo de una persona
    que dijo que no.
    """
    fila = db.execute(
        select(ConsentimientoSuite).where(
            ConsentimientoSuite.tenant_id == tenant_id,
            ConsentimientoSuite.usuario_id == usuario_id,
            ConsentimientoSuite.perfil == perfil_nombre,
            ConsentimientoSuite.recurso == recurso,
            ConsentimientoSuite.sentido == sentido,
        )
    ).scalar_one_or_none()
    if fila is None or fila.concedido_at is None:
        raise Prohibido(
            f"Nadie ha autorizado leer «{recurso}» de esta persona.",
            error_code="suite.sin_consentimiento",
        )
    if fila.revocado_at is not None:
        raise Prohibido(
            f"El acceso a «{recurso}» está revocado desde "
            f"{fila.revocado_at.date().isoformat()}.",
            error_code="suite.consentimiento_revocado",
        )
    return fila


# ── La credencial (CRM-06.01.03.03) ───────────────────────────────────────


def estado_credencial(
    *, caduca_at: datetime | None, tiene_refresco: bool, ahora: datetime | None = None
) -> dict[str, Any]:
    """Si hay que renovar, si hay que avisar, o si esto va a romperse solo.

    Una credencial **sin refresco y con caducidad** es una bomba de relojería:
    funciona meses y un martes deja de entrar el correo de veinte personas a la
    vez. Se dice ahora, no el martes.
    """
    momento = ahora or _ahora()
    if caduca_at is None:
        return {
            "renovar": False,
            "avisar": False,
            "porque": "No consta caducidad. Eso no es que no caduque: es que no se sabe.",
            "fiable": False,
        }
    caduca = caduca_at if caduca_at.tzinfo else caduca_at.replace(tzinfo=timezone.utc)
    queda = caduca - momento
    if queda <= timedelta(0):
        return {
            "renovar": tiene_refresco,
            "avisar": True,
            "caducada": True,
            "fiable": True,
            "porque": (
                "Ya ha caducado. Con refresco se renueva sola; sin él, esto ya no "
                "sincroniza y hace falta que la persona vuelva a autorizar."
            ),
        }
    return {
        "renovar": tiene_refresco and queda <= MARGEN_RENOVACION,
        "avisar": queda <= MARGEN_AVISO_CREDENCIAL,
        "caducada": False,
        "fiable": True,
        "dias_que_quedan": queda.days,
        "porque": (
            f"Quedan {queda.days} días."
            + (
                ""
                if tiene_refresco
                else " Y no hay token de refresco: cuando caduque, dejará de entrar y "
                "habrá que pedirle a la persona que autorice otra vez."
            )
        ),
    }


# ── Incremento (CRM-06.01.03.04) ──────────────────────────────────────────


def parametros_de_incremento(
    *, config: dict[str, Any], recurso: str, marca_actual: str
) -> dict[str, Any]:
    """Cómo se le pide al proveedor «lo que ha cambiado desde la última vez».

    La marca se guarda **tal cual** la dio el proveedor. Traducirla a un formato
    común sería inventar un estándar que no aporta nada y que se rompe con el
    primer proveedor que cambie de forma.
    """
    declaracion = dict(dict(config.get("recursos") or {}).get(recurso) or {})
    estrategia = str(declaracion.get("incremento") or "")
    if estrategia not in ESTRATEGIAS_INCREMENTO:
        raise ErrorValidacion(
            f"El perfil no declara cómo pedir el incremento de «{recurso}»",
            error_code="suite.incremento_sin_declarar",
        )
    if estrategia == "completo" or not marca_actual:
        return {
            "estrategia": estrategia,
            "parametros": {},
            "es_completa": True,
            "porque": (
                "Primera vuelta: no hay marca todavía."
                if marca_actual == "" and estrategia != "completo"
                else "Este recurso no admite incremento: se trae entero cada vez."
            ),
        }
    clave = str(declaracion.get("parametro_incremento") or "desde")
    return {
        "estrategia": estrategia,
        "parametros": {clave: marca_actual},
        "es_completa": False,
        "porque": f"Se pide solo lo cambiado desde «{marca_actual}».",
    }


def avanzar_incremento(
    *, marca_actual: str, marca_nueva: str, hubo_errores: bool
) -> dict[str, Any]:
    """La marca **solo avanza si no ha fallado nada**.

    Avanzar con un fallo dentro deja un hueco que no se recupera nunca: la
    siguiente vuelta pide «desde la marca nueva» y lo que falló queda detrás,
    para siempre. Y nadie lo nota, porque no falta una pantalla: falta una
    reunión.
    """
    if hubo_errores or not marca_nueva:
        return {
            "marca": marca_actual,
            "avanza": False,
            "porque": (
                "Algo falló en esta vuelta: la marca se queda y el tramo se repite. "
                "Avanzar dejaría un hueco que no se recupera y que nadie nota, porque "
                "no falta una pantalla: falta una reunión."
                if hubo_errores
                else "El proveedor no ha devuelto marca nueva: se repite el tramo."
            ),
        }
    return {"marca": marca_nueva, "avanza": True, "porque": "Todo el tramo se ha procesado."}


# ── Suscripción a cambios (CRM-06.01.03.05) ───────────────────────────────


def suscribir(
    uow: UnidadDeTrabajo,
    *,
    usuario_id: UUID,
    perfil_nombre: str,
    recurso: str,
    externo_id: str,
    caduca_at: datetime | None,
) -> SuscripcionSuite:
    """Registra la suscripción que el proveedor acaba de crear.

    Se exige el **identificador del proveedor**: sin él no se puede renovar ni
    borrar, y queda una suscripción huérfana mandando avisos a un sitio que ya no
    los atiende — que además se los manda a alguien, porque la URL sigue viva.
    """
    if not externo_id.strip():
        raise ErrorValidacion(
            "Una suscripción sin el identificador del proveedor no se puede renovar "
            "ni borrar: queda huérfana mandando avisos para siempre.",
            error_code="suite.suscripcion_sin_id",
        )
    fila = uow.db.execute(
        select(SuscripcionSuite).where(
            SuscripcionSuite.tenant_id == uow.tenant_id,
            SuscripcionSuite.usuario_id == usuario_id,
            SuscripcionSuite.perfil == perfil_nombre,
            SuscripcionSuite.recurso == recurso,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = SuscripcionSuite(
            tenant_id=uow.tenant_id,
            usuario_id=usuario_id,
            perfil=perfil_nombre,
            recurso=recurso,
        )
        uow.db.add(fila)
    fila.externo_id = externo_id.strip()
    fila.caduca_at = caduca_at
    fila.estado = "activa"
    fila.en_sondeo = False
    fila.motivo = ""
    fila.renovada_at = _ahora()
    uow.db.flush()
    return fila


def por_renovar(db: Session, tenant_id: UUID, *, ahora: datetime | None = None) -> dict[str, Any]:
    """Qué suscripciones hay que renovar ya.

    Con margen y no en el último momento: si se renovara justo al caducar, un
    reintento fallido la deja morir, y lo que pasa entonces es que el flujo se
    para **sin dar ningún error**. El CRM se queda quieto y el usuario cree que
    no ha pasado nada en su buzón.
    """
    momento = ahora or _ahora()
    filas = list(
        db.execute(
            select(SuscripcionSuite).where(
                SuscripcionSuite.tenant_id == tenant_id,
                SuscripcionSuite.estado == "activa",
            )
        )
        .scalars()
        .all()
    )
    urgentes = [
        f
        for f in filas
        if f.caduca_at is not None
        and (f.caduca_at if f.caduca_at.tzinfo else f.caduca_at.replace(tzinfo=timezone.utc))
        - momento
        <= MARGEN_RENOVACION
    ]
    sin_caducidad = [f for f in filas if f.caduca_at is None]
    return {
        "por_renovar": [
            {
                "id": str(f.id),
                "recurso": f.recurso,
                "usuario_id": str(f.usuario_id),
                "caduca_at": f.caduca_at.isoformat() if f.caduca_at else None,
            }
            for f in urgentes
        ],
        "sin_caducidad_declarada": [str(f.id) for f in sin_caducidad],
        "aviso": (
            ""
            if not sin_caducidad
            else f"{len(sin_caducidad)} suscripciones no dicen cuándo caducan. Todas "
            "caducan: la que no lo declara es la que se muere sin avisar."
        ),
    }


def caer_a_sondeo(uow: UnidadDeTrabajo, *, suscripcion_id: UUID, motivo: str) -> dict[str, Any]:
    """No se ha podido renovar: se sigue sondeando en vez de quedarse mudo.

    Es la decisión que separa una integración que se degrada de una que se para.
    Quedarse esperando avisos que ya no llegan no da ningún error —simplemente no
    entra nada— y el usuario lo descubre cuando echa de menos algo.

    Y **se marca**, porque sondear cada diez minutos no es lo mismo que enterarse
    al instante: el usuario tiene derecho a saber por qué su cita tarda.
    """
    fila = uow.db.get(SuscripcionSuite, suscripcion_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Esa suscripción no existe", error_code="suite.suscripcion_no_existe")
    fila.estado = "sondeo"
    fila.en_sondeo = True
    fila.motivo = motivo
    uow.db.flush()
    return {
        "recurso": fila.recurso,
        "en_sondeo": True,
        "porque": motivo,
        "que_significa": (
            "Los cambios seguirán entrando, pero con el retraso del sondeo en vez de "
            "al instante. Quedarse esperando avisos que ya no llegan no habría dado "
            "ningún error: simplemente no habría entrado nada."
        ),
    }


def exigir_sin_conflicto(
    db: Session, tenant_id: UUID, *, usuario_id: UUID, recurso: str, perfil_nombre: str
) -> None:
    """Impide dos suscripciones al mismo recurso desde perfiles distintos.

    Con dos, cada cambio entra dos veces y la ficha del cliente acaba con la
    misma reunión duplicada — y nadie sospecha del segundo perfil, que alguien
    configuró hace meses para probar.
    """
    otra = db.execute(
        select(SuscripcionSuite).where(
            SuscripcionSuite.tenant_id == tenant_id,
            SuscripcionSuite.usuario_id == usuario_id,
            SuscripcionSuite.recurso == recurso,
            SuscripcionSuite.perfil != perfil_nombre,
            SuscripcionSuite.estado.in_(["activa", "sondeo"]),
        )
    ).scalar_one_or_none()
    if otra is not None:
        raise Conflicto(
            f"Esta persona ya recibe «{recurso}» por el perfil «{otra.perfil}». Con dos, "
            "cada cambio entra dos veces y la ficha acaba con la misma reunión "
            "duplicada.",
            error_code="suite.suscripcion_duplicada",
        )


# ── El mantenimiento, que es lo que faltaba ───────────────────────────────
#
# `por_renovar` tenía ruta y `caer_a_sondeo` estaba escrita, probada y sin que
# la llamara nadie. O sea: el sistema sabía decir qué suscripciones se iban a
# morir, lo enseñaba en una pantalla, y **no hacía nada**. Una suscripción que
# caduca no da ningún error: deja de llegar lo que llegaba, el CRM se queda
# quieto, y el usuario lo descubre cuando echa de menos una cita.
#
# Esto es lo que lo recorre. La decisión que aplica —caer al sondeo en vez de
# quedarse mudo— ya estaba tomada en `caer_a_sondeo`; aquí sólo se ejecuta.


def mantener_suscripciones(
    uow: UnidadDeTrabajo, *, ahora: datetime | None = None
) -> dict[str, Any]:
    """Cae al sondeo lo que ya ha caducado y avisa de lo que está a punto.

    **Caducadas al sondeo, urgentes avisadas.** No se tratan igual a propósito:
    una que caducó ya no trae nada y hay que sustituirla por el sondeo ahora
    mismo; una que caduca en unas horas todavía funciona, y tirarla antes de
    tiempo convertiría un aviso en una degradación.

    Sondear cada diez minutos no es lo mismo que enterarse al instante, así que
    la caída se **marca**: el usuario tiene derecho a saber por qué su cita
    tarda.
    """
    momento = ahora or _ahora()
    estado = por_renovar(uow.db, uow.tenant_id, ahora=momento)
    caidas: list[dict[str, Any]] = []
    for fila in (
        uow.db.execute(
            select(SuscripcionSuite).where(
                SuscripcionSuite.tenant_id == uow.tenant_id,
                SuscripcionSuite.estado == "activa",
                SuscripcionSuite.caduca_at.is_not(None),
                SuscripcionSuite.caduca_at <= momento,
            )
        )
        .scalars()
        .all()
    ):
        caidas.append(
            caer_a_sondeo(
                uow,
                suscripcion_id=fila.id,
                motivo="La suscripción ha caducado y no se ha podido renovar.",
            )
        )
    return {
        "caidas_a_sondeo": caidas,
        # Las urgentes se devuelven para que el panel las enseñe: avisar de lo
        # que va a romperse es la mitad del trabajo, y la que nadie mira es
        # siempre esta.
        "por_renovar": estado["por_renovar"],
        "sin_caducidad_declarada": estado["sin_caducidad_declarada"],
        "aviso": estado["aviso"],
    }


def salud_de_las_credenciales(
    db: Session, tenant_id: UUID, *, ahora: datetime | None = None
) -> dict[str, Any]:
    """Qué consentimientos van a dejar de funcionar, y cuáles se romperán solos.

    `estado_credencial` estaba escrita, probada y sin llamante: el sistema sabía
    distinguir «hay que renovar», «hay que avisar» y «esto es una bomba de
    relojería» —una credencial **sin refresco y con caducidad** funciona meses y
    un martes deja de entrar el correo de veinte personas a la vez— y no lo
    miraba nunca.
    """
    momento = ahora or _ahora()
    filas = (
        db.execute(
            select(ConsentimientoSuite).where(
                ConsentimientoSuite.tenant_id == tenant_id,
                ConsentimientoSuite.revocado_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    salida = []
    for fila in filas:
        estado = estado_credencial(
            caduca_at=fila.credencial_caduca_at,
            tiene_refresco=bool(fila.tiene_refresco),
            ahora=momento,
        )
        # Tres motivos para salir, y el tercero es el que da nombre a esto.
        #
        #   1. Pide renovación o aviso: es lo que `estado_credencial` decide, y
        #      sólo lo dice cuando la fecha está cerca.
        #   2. No es fiable: de una credencial sin caducidad declarada no se
        #      sabe que esté bien, se sabe que no está medida.
        #   3. **Es una bomba de relojería**: tiene caducidad y NO tiene
        #      refresco. Esa sale aunque queden trescientos días, porque el día
        #      que llegue dejará de entrar el correo de veinte personas a la vez
        #      y habrá que pedirles a todas que vuelvan a autorizar. Esperar al
        #      margen de aviso para decirlo es decirlo tarde: lo que hay que
        #      hacer —conseguir refresco o planificar la reautorización— no se
        #      hace en una semana.
        es_bomba = fila.credencial_caduca_at is not None and not fila.tiene_refresco
        if estado["renovar"] or estado["avisar"] or not estado["fiable"] or es_bomba:
            salida.append(
                {
                    "consentimiento_id": str(fila.id),
                    "usuario_id": str(fila.usuario_id),
                    "perfil": fila.perfil,
                    "recurso": fila.recurso,
                    "se_rompera_sola": es_bomba,
                    **estado,
                }
            )
    return {"revisados": len(filas), "que_piden_algo": salida}


def tenants_con_suscripciones() -> list[UUID]:
    """Los tenants que tienen suscripciones vivas, de **su propia tabla**.

    No se le pide la lista de tenants a `tenancy`: es de otro servicio y no se
    lee desde aquí. Y la lista buena es más corta.
    """
    from crmcore.db.session import sesion

    with sesion(sistema=True) as db:
        return [
            t
            for (t,) in db.execute(
                select(SuscripcionSuite.tenant_id)
                .where(SuscripcionSuite.estado == "activa")
                .distinct()
            ).all()
        ]
