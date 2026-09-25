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
    # El identificador de la fuente ALLÍ. Sin él, la pantalla no puede preguntar:
    # `/api/ask` exige decir a qué fuente, y el navegador no tiene forma de
    # averiguarlo —ni debe, porque implicaría listarle las fuentes del tenant—.
    # `server_default` además del `default` de Python: la columna se añadió a una
    # tabla que ya tenía filas, y sin valor por defecto en la BASE la migración
    # muere con «contains null values» al arrancar el servicio.
    externa_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )

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
        externa = _publicar(modelo, organizacion, tenant_id=tenant_id, externa_id=fila.externa_id)
    except Exception as exc:  # noqa: BLE001 — el otro sistema es externo
        fila.estado = "error"
        fila.error = str(exc)[:1000]
        uow.db.flush()
        logger.warning(
            "analytics.registro_fuente_fallido", tenant=str(tenant_id), error=str(exc)[:200]
        )
        return {"registrada": False, "sin_cambios": False, "error": fila.error}

    fila.huella = huella
    fila.externa_id = externa or fila.externa_id
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


# La ruta de alta de fuentes de contecintelligence. Aquí decía
# `/api/v1/sources/register`, que NO EXISTE: su contrato no tiene nada bajo
# `/api/v1` y la ruta es `/api/sources`. Es el mismo desajuste que tenían el
# canje de token y el cliente documental, por tercera vez, y se descubrió igual
# que los otros: levantando el vecino de verdad. Lo fija
# `tests/unit/test_contratos_vecinos.py`.
RUTA_FUENTES = "/api/sources"

# Lo que hace falta para poder dar de alta una fuente allí. `sources:write` no
# existía: sus alcances delegados llegaban a `sources:read`, así que esta
# operación era imposible desde aquí por mucho que la ruta fuera correcta.
ALCANCES_REGISTRO = ["sources:read", "sources:write"]


def _publicar(
    modelo: dict[str, Any], organizacion: str, *, tenant_id: UUID, externa_id: str = ""
) -> str:
    """Da de alta el CRM como fuente consultable en contecintelligence.

    **Se registra una fuente de API, no una descripción suelta.** Mandar solo el
    esquema —que es lo que hacía— deja a contecintelligence sabiendo qué campos
    existen y sin poder leer ni una fila, así que cualquier pregunta se queda sin
    respuesta. Lo que se registra es cómo LEER el CRM: su dirección, una clave de
    solo lectura y la lista de entidades con su paginación.

    Las entidades salen de `describir()`, o sea del modelo semántico del propio
    tenant: no hay lista escrita a mano, y un objeto nuevo entra solo.

    La credencial de aplicación no vale aquí: hay que canjearla por un token de
    usuario con `sources:write`, que es el mismo camino de dos pasos que usa todo
    lo demás.
    """
    from crmcore.red import cliente_seguro

    from services.analytics.cliente import _config, canjear_token

    s = _config()
    # La clave se pide AQUÍ y no antes: `registrar_fuente` la sustituye entera en
    # las pruebas, y sacar la petición fuera obligaba a montar media
    # infraestructura para probar la huella, que no tiene nada que ver.
    clave_api = _clave_de_lectura(tenant_id)
    token = canjear_token(
        organizacion=organizacion,
        sujeto="contecrm",
        rol="admin",
        alcances=ALCANCES_REGISTRO,
    )

    entidades = _entidades_de(s.ci_url_del_crm, clave_api)
    if not entidades:
        raise ErrorValidacion(
            "Este tenant no tiene ningún objeto consultable que registrar",
            error_code="analytics.sin_objetos",
        )

    cuerpo = {
        "name": f"contecrm-{organizacion}",
        "source_type": "api",
        "plantilla_id": "api-paginacion-por-cursor",
        "config": {
            "base_url": s.ci_url_del_crm or "",
            "auth": {"type": "bearer", "value": clave_api},
            "entities": entidades,
        },
    }
    with cliente_seguro(timeout=s.ci_timeout_s) as cli:
        # Se borra la anterior ANTES de crear la nueva. Sin esto, cada registro
        # dejaba una fuente más y solo la última funcionaba:
        #
        #   * El secreto de una clave de API no se puede volver a leer —se guarda
        #     hasheado—, así que cada registro tiene que emitir una nueva.
        #   * Emitirla revoca la anterior, que es lo correcto: acumular
        #     credenciales vivas es repartir llaves.
        #   * Y la fuente registrada antes se quedaba con la llave muerta.
        #
        # El resultado medido eran seis claves (cuatro revocadas) y dos fuentes,
        # de las cuales una contestaba 401. contecintelligence no tiene ruta de
        # actualización —solo alta y baja—, así que una sola fuente por tenant
        # se consigue rehaciéndola.
        if externa_id:
            cli.delete(
                s.ci_base_url.rstrip("/") + f"{RUTA_FUENTES}/{externa_id}",
                headers={"Authorization": f"Bearer {token.token}"},
            )
        respuesta = cli.post(
            s.ci_base_url.rstrip("/") + RUTA_FUENTES,
            json=cuerpo,
            headers={"Authorization": f"Bearer {token.token}"},
        )
    if respuesta.status_code >= 400:
        raise ErrorDependencia(
            "contecintelligence ha rechazado el registro de la fuente",
            error_code="analytics.registro_rechazado",
            detalle={"codigo_http": respuesta.status_code, "cuerpo": respuesta.text[:300]},
        )
    return str((respuesta.json() or {}).get("id") or "")


def _clave_de_lectura(tenant_id: UUID) -> str:
    """Pide a `identity` una clave de solo lectura para que el otro lado lea.

    Se pide aquí y no se guarda en configuración porque una clave en el `.env`
    hay que ponerla a mano, y esto tiene que poder ser un botón. Cada registro
    rota la anterior, así que no se acumulan credenciales.
    """
    from crmcore.config import get_settings
    from crmcore.http.deps import firmar_cabeceras_internas
    from crmcore.red import cliente_seguro

    s = get_settings()
    destino = _url_de_identity(s)
    cabeceras = firmar_cabeceras_internas({}, s.secret_key.get_secret_value())
    with cliente_seguro(timeout=10.0) as cli:
        respuesta = cli.post(
            f"{destino}/api/v1/claves-api/interna",
            json={"tenant_id": str(tenant_id), "nombre": "contecintelligence"},
            headers=cabeceras,
        )
    if respuesta.status_code != 201:
        raise ErrorDependencia(
            "No se ha podido emitir la clave de lectura para contecintelligence",
            error_code="analytics.sin_clave",
            detalle={"codigo_http": respuesta.status_code},
        )
    return str(respuesta.json()["secreto"])


def _url_de_identity(s: Any) -> str:
    """La dirección de `identity` en este despliegue, de `RUTAS_SERVICIOS`."""
    for trozo in (s.rutas_servicios or "").replace("\n", " ").split(","):
        nombre, _, url = trozo.strip().partition("=")
        if nombre.strip() == "identity" and url.strip():
            return url.strip().rstrip("/")
    raise ErrorDependencia(
        "No hay dirección de `identity` en RUTAS_SERVICIOS",
        error_code="analytics.sin_identity",
    )


def _entidades_de(base_url: str, clave_api: str) -> list[dict[str, Any]]:
    """Qué se puede consultar, preguntándoselo al propio CRM.

    Sale de `/superficie`, que es donde este sistema declara lo que publica: todo
    listado RAÍZ que él mismo marca como colección y que no es de administración
    ni de plataforma. No hay lista escrita a mano, así que un módulo nuevo entra
    solo y uno retirado desaparece.

    No vale el modelo semántico: describe los campos PERSONALIZADOS de cinco
    objetos, no los objetos del CRM. Usarlo daba «este tenant no tiene ningún
    objeto consultable» en cuanto el tenant no había añadido campos propios, que
    es el caso normal.

    **Y la forma de cada listado se mide.** Unos devuelven una página con cursor
    y otros una lista pelada; suponer que todos paginan igual hace que el alta
    entera falle por el primero que no.
    """
    from crmcore.red import cliente_seguro

    cabeceras = {"Authorization": f"Bearer {clave_api}"}
    raiz = base_url.rstrip("/")
    with cliente_seguro(timeout=30.0) as cli:
        respuesta = cli.get(f"{raiz}/superficie", headers=cabeceras)
        if respuesta.status_code != 200:
            raise ErrorDependencia(
                "No se ha podido leer la superficie del CRM para registrar la fuente",
                error_code="analytics.sin_superficie",
                detalle={"codigo_http": respuesta.status_code},
            )
        operaciones = respuesta.json().get("operaciones") or []

        entidades: list[dict[str, Any]] = []
        for op in operaciones:
            ruta = str(op.get("ruta") or "")
            if op.get("metodo") != "GET" or not op.get("devuelve_lista"):
                continue
            if "{" in ruta or ruta.count("/") != 3 or not ruta.startswith("/api/v1/"):
                continue
            if op.get("administracion") or op.get("solo_plataforma") or op.get("exige_datos"):
                continue
            muestra = cli.get(f"{raiz}{ruta[len('/api/v1'):]}?limite=1", headers=cabeceras)
            if muestra.status_code != 200:
                continue
            cuerpo = muestra.json()
            entidad: dict[str, Any] = {
                "name": ruta.rsplit("/", 1)[-1].replace("-", "_"),
                "path": ruta[len("/api/v1") :],
                "primary_key": "id",
            }
            if isinstance(cuerpo, dict) and "items" in cuerpo:
                entidad["record_path"] = "items"
                entidad["pagination"] = {
                    "type": "cursor",
                    "cursor_path": "siguiente",
                    "cursor_param": "cursor",
                    "size_param": "limite",
                    "size": 200,
                }
            elif not isinstance(cuerpo, list):
                continue
            entidades.append(entidad)
    return sorted(entidades, key=lambda e: e["name"])


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

    from crmcore.config import get_settings

    s_cfg = get_settings()
    return {
        "puede_preguntar": not problemas,
        "problemas": problemas,
        # Lo que la pantalla necesita para poder preguntar de verdad: a quién y
        # sobre qué. Va en el diagnóstico y no en un ajuste del front porque la
        # dirección pública y el identificador de la fuente son configuración del
        # despliegue, y el navegador no puede adivinar ninguno de los dos.
        "url_publica": s_cfg.ci_url_publica or "",
        "fuente_id": (fuente.externa_id if fuente else "") or "",
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
    # `describir` devuelve {"modelo": {...}, "objetos": <cuántos>}: la LISTA está
    # dentro del modelo y el nivel de arriba trae el recuento. Leerla del sitio
    # equivocado dejaba `objetos` en un entero, y con un modelo publicado esto
    # reventaba al iterarlo. No se veía porque no había prueba que llegara aquí.
    descripcion = describir(db, tenant_id)
    publicados = (descripcion.get("modelo") or {}).get("objetos") or []
    objetos = {str(o.get("clave") or o.get("nombre")) for o in publicados}
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
        "aviso": (f"Respuesta acotada a {etiqueta or objeto}: no es el dato de toda la empresa."),
        # Sin modelo publicado no se ha podido comprobar que el objeto exista al
        # otro lado. Se dice: callarlo daría una respuesta que parece acotada y
        # puede no estarlo, que es peor que no acotar nada.
        "objeto_comprobado": bool(objetos),
        "aviso_modelo": (
            ""
            if objetos
            else "Todavía no hay modelo publicado a contecintelligence, así que no "
            "se ha podido comprobar que «"
            + objeto
            + "» exista allí: si no existe, el filtro se ignorará."
        ),
    }
