"""Entornos de pruebas con datos del cliente (CRM-07.02.01.02).

Un entorno de pruebas sin datos parecidos a los de verdad no sirve: las pruebas
pasan, y luego en producción falla el cliente que tiene ocho direcciones, la
oportunidad de tres años o el nombre con una comilla. Por eso se pide copiar
producción a pruebas.

Y ahí está el problema: **copiar producción a pruebas es sacar los datos
personales de tus clientes de donde están protegidos y ponerlos donde entra todo
el mundo**. A pruebas tienen acceso el consultor externo, el becario y el proveedor
que está integrando algo; no tienen las mismas reglas, ni el mismo cifrado, ni el
mismo control de acceso. La mayoría de las filtraciones de un CRM no salen de
producción: salen de una copia.

Las decisiones:

**La anonimización no es opcional cuando el destino no es producción.** Se puede
desactivar, sí — pidiéndolo expresamente, con un motivo y dejándolo escrito. Que
sea una casilla marcada por defecto es lo que hace que nadie la mire.

**Se anonimiza de forma consistente.** Si «Ana Pérez» se convierte en «Laura Gómez»
en una tabla y en otra cosa en otra, el entorno deja de servir para probar nada que
cruce datos. El mismo valor original da siempre el mismo valor falso dentro del
mismo entorno, y distinto entre entornos.

**Una copia parcial es mejor que una completa.** No por espacio: por riesgo. Con el
5 % de los clientes se prueba igual de bien y hay veinte veces menos que proteger.

**Y un sandbox caduca.** El que se creó para una migración hace año y medio sigue
ahí con los datos de entonces, sin actualizaciones de seguridad y sin que nadie
recuerde quién tiene acceso.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Para qué se crea un entorno. De aquí sale cuánto puede durar y qué se puede
# copiar: un sandbox de formación no necesita datos reales de nadie.
PROPOSITOS = {
    "desarrollo": 90,
    "pruebas": 60,
    "formacion": 180,
    "migracion": 30,
    "soporte": 15,
}

# Qué se hace con cada tipo de dato personal al copiar. `tal_cual` existe para
# poder decir que no se usa, y para que cuando se use quede escrito quién lo pidió.
TRATOS = ("anonimizar", "seudonimizar", "vaciar", "tal_cual")

# Campos que no se copian nunca, ni siquiera anonimizados. No es exceso de celo:
# un token válido en un entorno de pruebas es una puerta abierta a producción.
NUNCA_SE_COPIAN = {
    "credenciales": "Un token copiado a pruebas es una puerta abierta a producción",
    "claves_api": "Lo mismo, y además suelen tener más permisos de los que parece",
    "secretos_de_webhook": "Permiten falsificar eventos contra el sistema del cliente",
    "tokens_de_suite": "Darían acceso al correo real de personas reales desde pruebas",
    "firmas_electronicas": "Son prueba legal: una copia en pruebas la debilita",
}


def _hoy(db: Any = None) -> date:
    """El día de hoy **donde está el cliente**, si hay sesión con la que saberlo.

    Sin sesión cae a UTC, que es lo que hacía antes: no empeora nada y deja
    claro dónde falta el dato. Quien la tenga a mano está obligado a pasarla —
    hay un gate que lo mira—, porque entre medianoche y las dos de la mañana en
    Madrid la respuesta sin sesión es **la de ayer**.
    """
    from crmcore.fechas import hoy as _hoy_del_cliente

    return _hoy_del_cliente(db)


def _falsear(valor: str, semilla: str, campo: str = "") -> str:
    """Valor falso **estable dentro del entorno y distinto entre entornos**.

    Estable, porque si «Ana Pérez» sale distinta en dos tablas el entorno no sirve
    para probar nada que cruce datos. Y distinta entre entornos, porque si fuera
    igual en todos, cruzando dos entornos se podría deshacer la anonimización.

    **Conserva la forma del campo**, y eso es lo que decide si el entorno sirve.
    Antes devolvía dieciséis caracteres hexadecimales para todo: un correo
    anonimizado no era un correo, así que ninguna pantalla con validación de
    correo funcionaba en pruebas y cualquier envío de prueba fallaba por formato.
    La pieza que lo resuelve —`seudonimo` con la forma adivinada por el nombre
    del campo— estaba escrita en `crmcore.seguridad.anonimizar` y **no la
    llamaba nadie**: dos implementaciones de la misma regla, y la que se usaba
    era la peor.
    """
    from crmcore.seguridad import anonimizar as anon

    return str(anon.seudonimo(valor, sal=semilla, forma=anon.forma_de(campo)))


def plan_de_copia(
    *,
    proposito: str,
    porcentaje: int,
    anonimizar: bool,
    motivo_sin_anonimizar: str = "",
    pedido_por: UUID | None = None,
) -> dict[str, Any]:
    """Prepara la copia a un entorno que no es producción.

    **Copiar sin anonimizar exige pedirlo y explicarlo.** Que sea una casilla
    marcada por defecto es lo que hace que nadie la mire: a pruebas entran el
    consultor externo, el becario y el proveedor que está integrando algo, y no hay
    ni el mismo cifrado ni el mismo control de acceso.

    Y se recomienda copia **parcial**, no por espacio sino por riesgo: con el 5 %
    de los clientes se prueba igual de bien y hay veinte veces menos que proteger.
    """
    if proposito not in PROPOSITOS:
        raise ErrorValidacion(
            f"Propósito «{proposito}» desconocido",
            error_code="sandbox.proposito_invalido",
            detalle={"admitidos": sorted(PROPOSITOS)},
        )
    if not 1 <= porcentaje <= 100:
        raise ErrorValidacion(
            "El porcentaje de copia va de 1 a 100", error_code="sandbox.porcentaje_invalido"
        )
    if not anonimizar:
        if not motivo_sin_anonimizar.strip() or pedido_por is None:
            raise Prohibido(
                "Copiar datos personales sin anonimizar a un entorno que no es "
                "producción exige pedirlo expresamente, con un motivo y con nombre. La "
                "mayoría de las filtraciones de un CRM no salen de producción: salen de "
                "una copia.",
                error_code="sandbox.sin_anonimizar_sin_motivo",
            )
        logger.warning(
            "sandbox.copia_sin_anonimizar",
            extra={"proposito": proposito, "pedido_por": str(pedido_por)},
        )

    return {
        "proposito": proposito,
        "porcentaje": porcentaje,
        "anonimiza": anonimizar,
        "caduca_en_dias": PROPOSITOS[proposito],
        "no_se_copian": [{"que": k, "porque": v} for k, v in NUNCA_SE_COPIAN.items()],
        "aviso": (
            ""
            if porcentaje <= 20
            else f"Se va a copiar el {porcentaje} % de los datos. Con el 5 % se prueba "
            "igual de bien y hay veinte veces menos que proteger: la copia parcial no es "
            "por espacio, es por riesgo."
        ),
        "queda_escrito": not anonimizar,
    }


def anonimizar_fila(
    *, fila: dict[str, Any], reglas: dict[str, str], semilla: str
) -> dict[str, Any]:
    """Aplica la anonimización a una fila, campo a campo.

    **Consistente dentro del entorno**: el mismo valor original da siempre el mismo
    valor falso, así que una búsqueda por cliente sigue devolviendo sus
    oportunidades y sus casos. Sin eso, el entorno no sirve para probar nada que
    cruce datos, que es casi todo lo que se prueba.

    Y un campo con regla desconocida **no se copia tal cual**: se vacía. El
    silencio por defecto tiene que ser el seguro, no el cómodo.
    """
    salida: dict[str, Any] = {}
    avisos: list[str] = []
    for campo, valor in fila.items():
        regla = reglas.get(campo)
        if regla is None:
            salida[campo] = valor
            continue
        if regla not in TRATOS:
            salida[campo] = None
            avisos.append(
                f"«{campo}» tiene una regla desconocida («{regla}») y se ha vaciado: por "
                "defecto se protege, no se copia."
            )
            continue
        if valor in (None, ""):
            salida[campo] = valor
        elif regla == "vaciar":
            salida[campo] = None
        elif regla == "tal_cual":
            salida[campo] = valor
        else:
            salida[campo] = _falsear(str(valor), semilla, campo)

    return {"fila": salida, "avisos": avisos}


def comprobar_reglas(*, campos_personales: list[str], reglas: dict[str, str]) -> dict[str, Any]:
    """Comprueba que toda columna personal tiene decidido qué hacer con ella.

    Es la comprobación que evita el fallo típico: se anonimizan los nombres y los
    correos —los que se ven— y se olvidan el teléfono de contacto de una tabla
    secundaria, el campo personalizado que alguien creó y el texto libre de una
    nota, donde está el nombre completo del cliente escrito a mano.
    """
    sin_regla = sorted(c for c in campos_personales if c not in reglas)
    tal_cual = sorted(c for c, r in reglas.items() if r == "tal_cual")
    return {
        "valido": not sin_regla,
        "sin_regla": sin_regla,
        "se_copian_tal_cual": tal_cual,
        "porque": (
            f"{len(sin_regla)} columnas personales no dicen qué hacer con ellas. Es el "
            "fallo típico: se anonimiza lo que se ve —nombres y correos— y se olvidan el "
            "teléfono de una tabla secundaria y el nombre escrito a mano en una nota."
            if sin_regla
            else "Todas las columnas personales tienen decidido su tratamiento."
        ),
        "aviso": (
            ""
            if not tal_cual
            else f"{len(tal_cual)} columnas se copian tal cual. Queda escrito: con el "
            "tiempo, nadie recuerda qué había en ese entorno."
        ),
    }


def caducados(*, sandboxes: list[dict[str, Any]], hoy: date) -> dict[str, Any]:
    """Qué entornos hay que refrescar o apagar.

    El sandbox que se creó para una migración hace año y medio sigue ahí con los
    datos de entonces, sin actualizaciones y sin que nadie recuerde quién tiene
    acceso. No es una molestia de orden: es una copia de datos de clientes viviendo
    en un sitio del que ya nadie se acuerda.
    """
    # `hoy` lo pone quien tiene la sesión (`_hoy(db)`, la ruta con
    # `fechas.hoy(db)`): con el reloj de UTC, de madrugada vencía un día antes.
    momento = hoy
    vencidos, por_vencer = [], []
    for caja in sandboxes:
        creado = caja.get("creado")
        if isinstance(creado, str):
            creado = date.fromisoformat(creado)
        if not isinstance(creado, date):
            continue
        dias_max = PROPOSITOS.get(str(caja.get("proposito")), 60)
        vence = creado + timedelta(days=dias_max)
        entrada = {
            "nombre": caja.get("nombre"),
            "proposito": caja.get("proposito"),
            "vence": vence.isoformat(),
            "con_datos_reales": bool(caja.get("con_datos_reales")),
        }
        if vence < momento:
            vencidos.append({**entrada, "dias_vencido": (momento - vence).days})
        elif (vence - momento).days <= 7:
            por_vencer.append(entrada)

    con_datos = [v for v in vencidos if v["con_datos_reales"]]
    return {
        "vencidos": vencidos,
        "por_vencer": por_vencer,
        "urgentes": con_datos,
        "que_hacer": (
            "No hay entornos vencidos."
            if not vencidos
            else (
                f"{len(con_datos)} entornos vencidos tienen datos reales sin anonimizar. "
                "Eso es una copia de datos de clientes en un sitio del que ya nadie se "
                "acuerda: se refresca o se apaga, y hoy."
                if con_datos
                else f"{len(vencidos)} entornos vencidos: refrescar o apagar."
            )
        ),
    }


# ── Sandboxes de verdad: guardados y con su copia (CRM-07.02.01.02) ─────────
#
# Todo lo de arriba eran comprobaciones previas sin nada guardado: se podía
# preparar un plan de copia y no había sandbox, ni copia, ni caducidad que mirar.
# Lo de aquí los guarda y hace la copia pidiéndosela a cada servicio
# (`crmcore.datos.copia_sandbox`).

from crmcore.db.base import Base, TimestampMixin  # noqa: E402
from crmcore.db.uow import UnidadDeTrabajo  # noqa: E402
from crmcore.ids import nuevo_id  # noqa: E402
from sqlalchemy import Boolean, Date, Integer, String, Text, select, text  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: E402
from sqlalchemy.orm import Mapped, Session, mapped_column  # noqa: E402

ESTADOS_SANDBOX = ("preparado", "copiando", "listo", "con_avisos", "fallido", "apagado")


class Sandbox(Base, TimestampMixin):
    """Un entorno de pruebas de un tenant: otro tenant, hijo suyo, con su copia."""

    __tablename__ = "sandboxes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tenant_sandbox_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    proposito: Mapped[str] = mapped_column(String(20), nullable=False)
    porcentaje: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    anonimiza: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    motivo_sin_anonimizar: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pedido_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    caduca_el: Mapped[date] = mapped_column(Date, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="preparado")
    # Lo que contestó cada servicio: qué copió, qué no y por qué, qué falló.
    resultado: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


def crear_sandbox(
    uow: UnidadDeTrabajo,
    *,
    nombre: str,
    proposito: str,
    porcentaje: int = 5,
    anonimizar: bool = True,
    motivo_sin_anonimizar: str = "",
    pedido_por: UUID | None = None,
) -> dict[str, str]:
    """Da de alta el sandbox: el plan de siempre y un tenant hijo donde copiar.

    El tenant hijo y la fila del sandbox van en la transacción de la petición:
    si una falla, no queda un tenant huérfano que nadie sabe de quién es. Que
    el alta escriba las filas del hijo desde la sesión del origen lo resuelve
    `crear_tenant` con `escribir_como`.
    """
    from services.tenancy import servicio as svc
    from services.tenancy.modelos import Tenant

    plan = plan_de_copia(
        proposito=proposito,
        porcentaje=porcentaje,
        anonimizar=anonimizar,
        motivo_sin_anonimizar=motivo_sin_anonimizar,
        pedido_por=pedido_por,
    )
    origen = uow.db.get(Tenant, uow.tenant_id)
    if origen is None:
        raise ErrorValidacion("El tenant de origen no existe", error_code="sandbox.sin_origen")
    # El FINAL del identificador, que es aleatorio. El principio de un UUID7 es
    # la hora: con él, dos sandboxes del mismo tenant en unas cuatro horas
    # sacaban el mismo slug y el segundo contestaba «ya existe».
    sufijo = nuevo_id().hex[-6:]
    hijo = svc.crear_tenant(
        uow,
        slug=f"{origen.slug[:40]}-sbx-{sufijo}",
        nombre=f"{origen.nombre} · {nombre}"[:200],
        tenant_padre_id=origen.id,
    )
    fila = Sandbox(
        tenant_id=origen.id,
        tenant_sandbox_id=hijo.id,
        nombre=nombre,
        proposito=proposito,
        porcentaje=porcentaje,
        anonimiza=anonimizar,
        motivo_sin_anonimizar=motivo_sin_anonimizar,
        pedido_por=pedido_por,
        caduca_el=_hoy(uow.db) + timedelta(days=int(plan["caduca_en_dias"])),
    )
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id), "tenant_sandbox_id": str(hijo.id), "estado": fila.estado}


def _usuarios_del_tenant(tenant_id: UUID) -> list[str]:
    """Los usuarios son globales: sus identificadores no se traducen al copiar."""
    from crmcore.http.interno import invocar

    salida: list[str] = []
    cursor = ""
    while True:
        respuesta = invocar(
            metodo="GET",
            ruta="/api/v1/usuarios",
            parametros={"limite": 200, **({"cursor": cursor} if cursor else {})},
            tenant_id=tenant_id,
            principal_id=tenant_id,
            permisos=["user:read"],
        )
        datos = respuesta.get("datos") or {}
        salida.extend(str(u["id"]) for u in datos.get("items", []) if u.get("id"))
        cursor = str(datos.get("siguiente") or "")
        if not cursor:
            return salida


def copiar(sandbox_id: UUID, tenant_id: UUID) -> None:
    """Pide a cada servicio su parte de la copia y guarda lo que contesta.

    Corre después de contestar al que lo pidió —la copia tarda—, así que abre su
    propia sesión y deja el resultado en el sandbox, que es lo que la ficha
    enseña. Un servicio que no contesta se dice por su nombre: un «listo»
    calculado sobre los que sí contestaron sería un sandbox a medias que parece
    entero.
    """
    import httpx
    from crmcore.config import get_settings
    from crmcore.db.session import sesion
    from crmcore.http.interno import cabeceras_firmadas
    from crmcore.rutas_de_api import cargar_destinos

    with sesion(sistema=True) as db:
        fila = db.get(Sandbox, sandbox_id)
        if fila is None or fila.tenant_id != tenant_id:
            return
        fila.estado = "copiando"
        db.commit()
        cuerpo = {
            "origen": str(fila.tenant_id),
            "destino": str(fila.tenant_sandbox_id),
            "semilla": str(fila.id),
            "porcentaje": fila.porcentaje,
            "anonimizar": fila.anonimiza,
        }

    try:
        cuerpo["conservar"] = _usuarios_del_tenant(tenant_id)
        sin_usuarios = ""
    except Exception as exc:  # noqa: BLE001 — se dice y se sigue con la copia
        cuerpo["conservar"] = []
        sin_usuarios = f"No se ha podido preguntar a identity por los usuarios: {exc}"[:300]

    por_servicio: dict[str, Any] = {}
    sin_respuesta: dict[str, str] = {}
    destinos = cargar_destinos(get_settings().rutas_servicios)
    for nombre, destino in sorted(destinos.items()):
        if nombre == "gateway":
            continue
        try:
            respuesta = httpx.post(
                f"{destino.url_base}/api/v1/{nombre}/sandbox/copiar",
                json=cuerpo,
                headers=cabeceras_firmadas(),
                timeout=600.0,
            )
            if respuesta.status_code == 200:
                por_servicio[nombre] = respuesta.json()
            else:
                sin_respuesta[nombre] = f"contestó {respuesta.status_code}"
        except httpx.HTTPError as exc:
            sin_respuesta[nombre] = f"no responde: {str(exc)[:120]}"

    fallidas = sum(len(r.get("fallidas") or []) for r in por_servicio.values())
    with sesion(sistema=True) as db:
        fila = db.get(Sandbox, sandbox_id)
        if fila is None:
            return
        fila.resultado = {
            "filas": sum(int(r.get("filas") or 0) for r in por_servicio.values()),
            "por_servicio": por_servicio,
            "sin_respuesta": sin_respuesta,
            "usuarios": sin_usuarios or "conservados",
        }
        fila.estado = (
            "fallido"
            if not por_servicio
            else "con_avisos"
            if sin_respuesta or fallidas or sin_usuarios
            else "listo"
        )
        db.commit()


def apagar(uow: UnidadDeTrabajo, sandbox_id: UUID, *, motivo: str) -> Sandbox:
    """Lo suspende: el tenant sandbox deja de dejar entrar, y queda dicho por qué."""
    from services.tenancy import servicio as svc

    fila = uow.db.get(Sandbox, sandbox_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        from crmcore.errors import NoEncontrado

        raise NoEncontrado("Ese sandbox no existe", error_code="sandbox.no_encontrado")
    svc.cambiar_estado(uow, fila.tenant_sandbox_id, nuevo="suspendido", motivo=motivo)
    fila.estado = "apagado"
    uow.db.flush()
    return fila


def caducidad(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Qué sandboxes hay que refrescar o apagar, con los guardados."""
    filas = db.execute(
        select(Sandbox).where(Sandbox.tenant_id == tenant_id, Sandbox.estado != "apagado")
    ).scalars()
    return caducados(
        sandboxes=[
            {
                "nombre": f.nombre,
                "proposito": f.proposito,
                "creado": f.created_at.date() if f.created_at else _hoy(db),
                "con_datos_reales": not f.anonimiza,
            }
            for f in filas
        ],
        hoy=_hoy(db),
    )
