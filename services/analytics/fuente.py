"""Registrar el CRM como fuente consultable y ejecutar sus planes
(CRM-05.01.04.04, CRM-05.01.04.05, CRM-05.01.04.06, CRM-05.01.04.08).

Para que alguien pueda preguntar «¿cuánto vendimos en marzo?» en lenguaje
natural, contecintelligence tiene que **saber qué hay**: qué objetos, qué campos,
de qué tipo y —lo que de verdad lo hace usable— cómo se llaman en cristiano. El
modelo semántico ya publica lo primero; esto publica lo segundo y mantiene el
registro al día.

Cuatro decisiones:

**Se registra la descripción, nunca el dato.** Va el esquema y va el nombre
humano de cada campo; no va una fila. Mandar datos convertiría una descripción en
una copia del CRM fuera de su sitio.

**El registro se rehace cuando cambia el esquema, no cada noche.** Un registro que
se refresca por reloj está desfasado la mayor parte del tiempo justo después de
que alguien añada un campo —que es cuando lo va a buscar—, y uno que se refresca
en cada consulta paga el coste en la pregunta de todo el mundo.

**Los permisos viajan con la pregunta, no con el registro.** El registro dice qué
existe; quién ve qué lo decide el token de usuario en cada consulta. Un registro
con permisos dentro obligaría a rehacerlo cada vez que alguien cambia de rol.

**Cuando no responde, se dice qué se puede hacer sin él.** «Servicio no
disponible» deja a quien lo lee sin saber si su CRM está roto. No lo está: lo que
no funciona es preguntar, y lo demás sigue.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorDependencia, ErrorValidacion, NoDisponible
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)


class FuenteRegistrada(Base, TimestampMixin):
    """Lo que contecintelligence sabe de este tenant (CRM-05.01.04.04)."""

    __tablename__ = "fuentes_registradas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    organizacion: Mapped[str] = mapped_column(String(120), nullable=False)
    # Huella del modelo publicado. Es lo que permite saber si hay que volver a
    # registrar sin comparar el modelo entero, y lo que evita reenviarlo cuando
    # no ha cambiado nada.
    huella: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    objetos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    campos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # pendiente | registrada | error
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    registrada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", name="uq_fuente_tenant"),)


class PreguntaGuardada(Base, TimestampMixin):
    """Una pregunta que alguien quiso conservar (CRM-05.01.04.06)."""

    __tablename__ = "preguntas_guardadas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    pregunta: Mapped[str] = mapped_column(Text, nullable=False)
    autor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Publicada = la ve todo el tenant. Sin publicar es de quien la guardó: una
    # pregunta a medio afinar que aparece en la lista de todos se usa como si
    # estuviera bien, y su autor ni se entera.
    publicada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    roles: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # El informe que la publica, si se convirtió en uno. Enlaza las dos mitades:
    # la pregunta en lenguaje natural y el informe programable que salió de ella.
    informe_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    veces_usada: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultima_vez_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_pregunta_clave"),
        Index("ix_preguntas_publicadas", "tenant_id", "publicada"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ── Registro de la fuente (CRM-05.01.04.04) ───────────────────────────────


def describir(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """El CRM descrito para que se le pueda preguntar en lenguaje natural.

    Sobre el modelo semántico que ya existe, añadiendo lo que hace falta para
    entenderlo sin conocer el esquema: la etiqueta de cada campo, su papel
    analítico y una frase de qué es cada objeto. Sin eso, quien pregunta tiene que
    adivinar que «importe» es el valor del negocio y no el coste.
    """
    from services.analytics.modelo_semantico import modelo_de

    modelo = modelo_de(db, tenant_id)
    objetos = modelo.get("objetos") or []
    campos = sum(len(o.get("campos") or []) for o in objetos)
    descrito = {
        "origen": "contecrm",
        "organizacion": "",
        "objetos": objetos,
        # Qué NO se manda, dicho en el propio paquete para que se vea al leerlo.
        "sin_datos": True,
        "nota": (
            "Descripción del esquema. No lleva ni una fila: quien pregunte "
            "recibe los datos con su propio token y con sus propios permisos."
        ),
    }
    return {"modelo": descrito, "objetos": len(objetos), "campos": campos}


def _huella(modelo: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(modelo, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def registrar_fuente(
    uow: UnidadDeTrabajo, tenant_id: UUID, *, organizacion: str, forzar: bool = False
) -> dict[str, Any]:
    """Publica la descripción del CRM en contecintelligence.

    **No se reenvía si no ha cambiado nada.** La huella lo decide: un registro que
    se reenvía por reloj gasta en cada tenant y en cada vuelta sin que nadie haya
    tocado un campo, y lo que de verdad importa —que el campo nuevo esté— no
    depende del reloj sino del cambio.
    """
    descripcion = describir(uow.db, tenant_id)
    modelo = {**descripcion["modelo"], "organizacion": organizacion}
    huella = _huella(modelo)

    fila = uow.db.execute(
        select(FuenteRegistrada).where(FuenteRegistrada.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if fila is None:
        fila = FuenteRegistrada(tenant_id=tenant_id, organizacion=organizacion)
        uow.db.add(fila)
        uow.db.flush()

    if fila.huella == huella and fila.estado == "registrada" and not forzar:
        return {
            "registrada": False,
            "sin_cambios": True,
            "huella": huella,
            "objetos": fila.objetos,
        }

    fila.organizacion = organizacion
    fila.objetos = descripcion["objetos"]
    fila.campos = descripcion["campos"]
    try:
        _publicar(modelo, organizacion)
    except Exception as exc:  # noqa: BLE001 — el otro sistema es externo
        fila.estado = "error"
        fila.error = str(exc)[:1000]
        uow.db.flush()
        logger.warning(
            "analytics.registro_fuente_fallido", tenant=str(tenant_id), error=str(exc)[:200]
        )
        return {"registrada": False, "sin_cambios": False, "error": fila.error}

    fila.huella = huella
    fila.estado = "registrada"
    fila.error = None
    fila.registrada_at = _ahora()
    uow.db.flush()
    uow.emitir(
        "analytics.source.registered",
        subject=("fuente", fila.id),
        data={
            "organizacion": organizacion,
            "objetos": descripcion["objetos"],
            "campos": descripcion["campos"],
        },
    )
    return {
        "registrada": True,
        "sin_cambios": False,
        "huella": huella,
        "objetos": descripcion["objetos"],
        "campos": descripcion["campos"],
    }


def _publicar(modelo: dict[str, Any], organizacion: str) -> None:
    """Manda la descripción. Aislado para poder sustituirlo en las pruebas."""
    from crmcore.red import cliente_seguro

    from services.analytics.cliente import _config

    s = _config()
    url = s.ci_base_url.rstrip("/") + "/api/v1/sources/register"
    with cliente_seguro(timeout=s.ci_timeout_s) as cli:
        respuesta = cli.post(
            url,
            json=modelo,
            auth=(s.ci_client_id, s.ci_client_secret.get_secret_value()),
        )
    if respuesta.status_code >= 400:
        raise ErrorDependencia(
            "contecintelligence ha rechazado el registro de la fuente",
            error_code="analytics.registro_rechazado",
            detalle={"codigo_http": respuesta.status_code},
        )


async def consumir_esquema_cambiado(mensaje: Any) -> None:
    """Vuelve a registrar cuando el tenant cambia su esquema.

    Por evento y no por reloj: un registro que se refresca cada noche está
    desfasado justo después de que alguien añada un campo, que es exactamente
    cuando lo va a buscar en la herramienta de preguntas.
    """
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.metamodelo import ESQUEMA_CAMBIADO
    from crmcore.tenancy.context import con_contexto

    if str(getattr(mensaje, "tipo", "") or "") != ESQUEMA_CAMBIADO:
        return
    bruto = getattr(mensaje, "tenant_id", None)
    if not bruto:
        return
    tenant_id = UUID(str(bruto))
    with con_contexto(tenant_id=tenant_id, origen="bus"), unidad_de_trabajo(tenant_id) as uow:
        fila = uow.db.execute(
            select(FuenteRegistrada).where(FuenteRegistrada.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if fila is None or fila.estado != "registrada":
            # Un tenant que nunca se registró no se registra solo por un cambio
            # de esquema: registrarlo es una decisión de implantación, y hacerlo
            # aquí mandaría a contecintelligence tenants que nadie quería allí.
            return
        registrar_fuente(uow, tenant_id, organizacion=fila.organizacion)


# ── Degradación explicada (CRM-05.01.04.08) ───────────────────────────────


def diagnostico(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Qué funciona y qué no cuando contecintelligence no responde.

    «Servicio no disponible» deja a quien lo lee sin saber si su CRM está roto.
    No lo está: lo que no funciona es **preguntar**, y el CRM entero sigue
    operativo. Decirlo por su nombre es la diferencia entre una llamada al
    soporte y un rato de espera.
    """
    from services.analytics.cliente import estado as estado_integracion
    from services.analytics.modelos import OrganizacionExterna

    estado = estado_integracion()
    organizacion = db.execute(
        select(OrganizacionExterna).where(OrganizacionExterna.tenant_id == tenant_id)
    ).scalar_one_or_none()
    fuente = db.execute(
        select(FuenteRegistrada).where(FuenteRegistrada.tenant_id == tenant_id)
    ).scalar_one_or_none()

    problemas: list[str] = []
    if not estado.get("activa"):
        problemas.append("La explotación está desactivada en la configuración (CI_ENABLED).")
    elif not estado.get("url"):
        problemas.append("No hay dirección de contecintelligence configurada (CI_BASE_URL).")
    elif estado.get("alcanzable") is False:
        problemas.append(f"contecintelligence no responde: {estado.get('error') or 'sin detalle'}.")
    if organizacion is None:
        problemas.append(
            "Este tenant no tiene organización asignada, así que no se le puede "
            "pedir un token de usuario."
        )
    if fuente is None or fuente.estado != "registrada":
        problemas.append(
            "El CRM no está registrado como fuente consultable, así que las "
            "preguntas no encontrarían de dónde sacar los datos."
        )

    return {
        "puede_preguntar": not problemas,
        "problemas": problemas,
        # Lo que sigue funcionando, dicho por su nombre. Es la mitad de la
        # respuesta y la que evita que alguien crea que el CRM se ha caído.
        "sigue_funcionando": [
            "El CRM entero: fichas, procesos, casos y automatizaciones.",
            "Las definiciones de informe y sus programaciones, que se guardan aquí.",
            "El histórico de instantáneas ya tomadas.",
        ],
        "no_funciona": [
            "Preguntar en lenguaje natural.",
            "Ejecutar un informe, porque la consulta la resuelve contecintelligence.",
        ]
        if problemas
        else [],
        "estado_integracion": estado,
    }


# ── Preguntas guardadas (CRM-05.01.04.06) ─────────────────────────────────


def guardar_pregunta(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    titulo: str,
    pregunta: str,
    autor_id: UUID | None = None,
    publicada: bool = False,
    roles: list[str] | None = None,
) -> PreguntaGuardada:
    """Guarda una pregunta para no volver a escribirla.

    Nace **sin publicar** a propósito: una pregunta a medio afinar que aparece en
    la lista de todos se usa como si estuviera bien, y su autor ni se entera.
    """
    fila = PreguntaGuardada(
        tenant_id=uow.tenant_id,
        clave=clave,
        titulo=titulo,
        pregunta=pregunta,
        autor_id=autor_id,
        publicada=publicada,
        roles=list(roles or []),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def publicar_como_informe(
    uow: UnidadDeTrabajo, pregunta_id: UUID, *, definicion: dict[str, Any]
) -> dict[str, Any]:
    """Convierte una pregunta guardada en un informe del tenant.

    Es lo que cierra el círculo: se pregunta en lenguaje natural hasta dar con la
    respuesta buena, y entonces esa respuesta **se congela como informe**, con su
    programación y su distribución. Sin este paso, lo que funciona vive en la
    cabeza de quien supo preguntar, y cuando se va se va con él.

    El informe se crea a partir de una definición estructurada, no del texto: una
    pregunta en lenguaje natural puede dar dos consultas distintas en dos días
    —el modelo cambia—, y un informe programado que cambia solo de significado es
    peor que no tenerlo.
    """
    from crmcore.errors import Conflicto, NoEncontrado

    from services.analytics.informes import Informe, validar

    tenant_id = uow.tenant_id
    pregunta = uow.db.get(PreguntaGuardada, pregunta_id)
    if pregunta is None or pregunta.tenant_id != tenant_id:
        raise NoEncontrado("La pregunta no existe", error_code="analytics.pregunta_no_encontrada")
    if pregunta.informe_id is not None:
        raise Conflicto(
            "Esa pregunta ya se publicó como informe",
            error_code="analytics.pregunta_ya_publicada",
            detalle={"informe_id": str(pregunta.informe_id)},
        )

    avisos = validar(definicion)
    informe = Informe(
        tenant_id=tenant_id,
        clave=pregunta.clave,
        nombre=pregunta.titulo,
        descripcion=f"Nació de la pregunta: «{pregunta.pregunta}»",
        propietario_id=pregunta.autor_id,
        roles=list(pregunta.roles or []),
        **{k: v for k, v in definicion.items() if k not in ("clave", "nombre", "descripcion")},
    )
    uow.db.add(informe)
    uow.db.flush()
    pregunta.informe_id = informe.id
    pregunta.publicada = True
    uow.db.flush()
    return {
        "informe_id": str(informe.id),
        "clave": informe.clave,
        "avisos": avisos,
    }


def preguntas_de(
    db: Session,
    tenant_id: UUID,
    *,
    usuario_id: UUID | None = None,
    roles: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Las preguntas que puede ver esta persona: las publicadas y las suyas."""
    filas = (
        db.execute(
            select(PreguntaGuardada)
            .where(PreguntaGuardada.tenant_id == tenant_id)
            .order_by(PreguntaGuardada.titulo)
        )
        .scalars()
        .all()
    )
    salida = []
    for fila in filas:
        suya = fila.autor_id is not None and fila.autor_id == usuario_id
        if not suya and not fila.publicada:
            continue
        if fila.roles and not suya and not (set(fila.roles) & set(roles)):
            continue
        salida.append(
            {
                "id": str(fila.id),
                "clave": fila.clave,
                "titulo": fila.titulo,
                "pregunta": fila.pregunta,
                "publicada": fila.publicada,
                "propia": suya,
                "informe_id": str(fila.informe_id) if fila.informe_id else None,
                "veces_usada": fila.veces_usada,
            }
        )
    return salida


def anotar_uso(db: Session, tenant_id: UUID, pregunta_id: UUID) -> None:
    """Cuenta que se usó.

    Sirve para saber qué preguntas merecen convertirse en informe y cuáles sobran:
    una lista de preguntas guardadas que nadie poda acaba con doscientas y nadie
    encuentra la suya.
    """
    fila = db.get(PreguntaGuardada, pregunta_id)
    if fila is None or fila.tenant_id != tenant_id:
        return
    fila.veces_usada += 1
    fila.ultima_vez_at = _ahora()
    db.flush()


# ── El ejecutor de planes (CRM-05.01.04.05) ───────────────────────────────


def ejecutar_plan(*, plan: dict[str, Any], tenant_id: UUID) -> dict[str, Any]:
    """Manda el plan de un informe a contecintelligence y devuelve sus filas.

    Es el ejecutor que el motor de informes registra. El plan viaja como
    **estructura de datos** y quien lo traduce a consulta es el otro lado: aquí no
    se construye SQL, que es lo que dice RT-4.

    **El token va con la pregunta.** Se canjea uno de usuario final, con el rol
    que corresponde a lo que esa persona ve en el CRM: una explotación que ve más
    que la aplicación es una fuga con otro nombre.
    """
    from crmcore.red import cliente_seguro

    from services.analytics.cliente import _config

    # El token se comprueba ANTES que la configuración: que falte es un error
    # nuestro, no del despliegue, y decir «falta configurar contecintelligence»
    # mandaría a arreglar lo que no está roto.
    token = plan.get("_token")
    if not token:
        raise NoDisponible(
            "El plan no trae token de usuario, y sin él la consulta se haría con "
            "la credencial de aplicación, que puede verlo todo.",
            error_code="analytics.plan_sin_token",
        )
    s = _config()
    url = s.ci_base_url.rstrip("/") + "/api/v1/query/plan"
    with cliente_seguro(timeout=s.ci_timeout_s) as cli:
        respuesta = cli.post(
            url,
            json={k: v for k, v in plan.items() if not k.startswith("_")},
            headers={"Authorization": f"Bearer {token}"},
        )
    if respuesta.status_code >= 400:
        raise ErrorDependencia(
            "contecintelligence no ha podido resolver el plan",
            error_code="analytics.plan_rechazado",
            detalle={"codigo_http": respuesta.status_code},
        )
    datos = respuesta.json()
    return {"filas": list(datos.get("rows") or datos.get("filas") or [])}


def contexto_del_registro(
    db: Session,
    tenant_id: UUID,
    *,
    pregunta: str,
    objeto: str,
    registro_id: UUID,
    etiqueta: str = "",
) -> dict[str, Any]:
    """Prepara una pregunta acotada al registro que se está mirando
    (CRM-05.01.04.09).

    Es la diferencia entre «¿cómo va esta cuenta?» y tener que escribir «ingresos
    de la cuenta cuyo identificador es 0f3a…». Sin esto, la explotación en
    contexto no se usa: nadie copia un UUID a mano.

    Tres decisiones:

    **El filtro se añade, no se sugiere.** Si fuera una sugerencia que el otro
    lado puede ignorar, la respuesta podría traer datos de todas las cuentas
    mientras el usuario cree que está preguntando por una.

    **Y se devuelve visible.** Quien lea la respuesta tiene que poder ver que
    estaba acotada: un número que parece de toda la empresa y es de una cuenta se
    lleva a una reunión y allí no cuadra con nada.

    **El objeto se valida contra el modelo publicado.** Preguntar en el contexto
    de un objeto que la fuente no conoce daría un filtro que el otro lado ignora
    en silencio, que es el caso peor de los tres.
    """
    modelo = describir(db, tenant_id)
    objetos = {str(o.get("clave") or o.get("nombre")) for o in (modelo.get("objetos") or [])}
    if objetos and objeto not in objetos:
        raise ErrorValidacion(
            f"«{objeto}» no está en el modelo publicado a contecintelligence: el "
            "filtro se ignoraría y la respuesta saldría sin acotar.",
            error_code="analytics.objeto_no_publicado",
            detalle={"publicados": sorted(objetos)},
        )
    return {
        "pregunta": pregunta.strip(),
        "objeto": objeto,
        "filtros": [{"campo": "id", "operador": "=", "valor": str(registro_id)}],
        # Lo que la pantalla enseña junto a la respuesta.
        "acotada_a": etiqueta or f"{objeto} {registro_id}",
        "aviso": (
            f"Respuesta acotada a {etiqueta or objeto}: no es el dato de toda la " "empresa."
        ),
    }
