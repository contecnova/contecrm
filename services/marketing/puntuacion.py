"""Puntuación y calificación de leads
(CRM-02.01.02.01, .03, .04, .05).

El error clásico del *lead scoring* es tener **un solo número**. Un estudiante que
abre diez correos suma lo mismo que un director de compras que abrió uno, ventas
recibe los dos como «lead caliente», y a la tercera vez que le pasan uno que no
compra nunca deja de fiarse de la lista. A partir de ahí el scoring está puesto y
no sirve para nada, que es peor que no tenerlo porque nadie lo revisa.

Aquí hay **dos ejes**:

* **Encaje** — ¿es el cliente que buscamos? Sector, tamaño, país, cargo. No
  decae: que alguien sea director de compras de una empresa de quinientas
  personas no deja de ser cierto porque lleve dos meses sin abrir un correo.
* **Interés** — ¿nos está haciendo caso? Visitas, descargas, respuestas. Este sí
  decae, porque el interés de hace seis meses no es interés.

Y para pasar a MQL se exigen **los dos**. Con uno solo, o pasan estudiantes muy
activos o directores que no han mostrado ningún interés.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.marketing.modelos import ModeloPuntuacion, PuntuacionLead
from services.marketing.segmentos import evalua, validar

logger = get_logger(__name__)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def modelo_activo(db: Session, tenant_id: UUID, clave: str = "") -> ModeloPuntuacion | None:
    """El modelo vigente. Si hay varias versiones, la más alta.

    La versión más alta y no la última editada: publicar una versión nueva es la
    forma de decir «a partir de ahora, esta», igual que en los SLA y en el
    esquema del tenant. Una misma regla en todo el producto.
    """
    consulta = select(ModeloPuntuacion).where(
        ModeloPuntuacion.tenant_id == tenant_id, ModeloPuntuacion.activo.is_(True)
    )
    if clave:
        consulta = consulta.where(ModeloPuntuacion.clave == clave)
    return db.execute(
        consulta.order_by(ModeloPuntuacion.version.desc()).limit(1)
    ).scalar_one_or_none()


def crear_modelo(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    reglas_interes: list[dict[str, Any]] | None = None,
    reglas_encaje: list[dict[str, Any]] | None = None,
    **datos: Any,
) -> ModeloPuntuacion:
    """Publica una versión nueva del modelo.

    Cada publicación es una **versión**, no una edición. Editar el modelo en
    caliente hace que las puntuaciones de ayer y las de hoy no sean comparables
    sin que nadie lo sepa: el lead que ayer tenía 80 y hoy tiene 40 no ha hecho
    nada distinto, y quien lo mira no tiene forma de saberlo.
    """
    for lote, eje in ((reglas_interes or [], "interes"), (reglas_encaje or [], "encaje")):
        for regla in lote:
            if not isinstance(regla, dict) or "condicion" not in regla:
                raise ErrorValidacion(
                    f"Una regla de {eje} necesita su condición.",
                    error_code="marketing.regla_sin_condicion",
                )
            validar(regla["condicion"])
            if not isinstance(regla.get("puntos"), int):
                raise ErrorValidacion(
                    f"Una regla de {eje} necesita puntos enteros.",
                    error_code="marketing.regla_sin_puntos",
                )

    ultima = int(
        uow.db.execute(
            select(ModeloPuntuacion.version)
            .where(ModeloPuntuacion.tenant_id == uow.tenant_id, ModeloPuntuacion.clave == clave)
            .order_by(ModeloPuntuacion.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        or 0
    )
    fila = ModeloPuntuacion(
        tenant_id=uow.tenant_id,
        clave=clave,
        nombre=nombre,
        version=ultima + 1,
        reglas_interes=reglas_interes or [],
        reglas_encaje=reglas_encaje or [],
        **datos,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


# ── Cálculo ───────────────────────────────────────────────────────────────


def _aplicar(
    reglas: list[Any], ambito: dict[str, Any], eje: str
) -> tuple[int, list[dict[str, Any]]]:
    total = 0
    desglose: list[dict[str, Any]] = []
    for regla in reglas or []:
        if not isinstance(regla, dict):
            continue
        try:
            cumple = evalua(regla.get("condicion") or {}, ambito)
        except Exception:  # noqa: BLE001 — una regla rota no puede tumbar el cálculo
            logger.warning("marketing.regla_rota", eje=eje, regla=regla.get("nombre"))
            continue
        if not cumple:
            continue
        puntos = int(regla.get("puntos", 0))
        total += puntos
        desglose.append(
            {"regla": regla.get("nombre") or "(sin nombre)", "eje": eje, "puntos": puntos}
        )
    return total, desglose


def _grado(encaje: int, grados: list[Any]) -> str | None:
    """La letra de encaje con el cliente ideal (CRM-02.01.02.03).

    Va aparte del interés y no sumada a él: el grado dice **si es el cliente que
    buscamos**, y esa respuesta no cambia porque hoy nos haya hecho más o menos
    caso. Un director de compras de una empresa objetivo es un «A» aunque lleve
    dos meses callado, y saberlo es lo que decide a quién se llama primero cuando
    hay veinte leads y una tarde.

    Los tramos se ordenan de mayor a menor y gana el primero que alcanza: con el
    orden al revés, un encaje de 95 caería en el tramo de 20 y todo el mundo
    sería «D».
    """
    tramos = sorted(
        [t for t in (grados or []) if isinstance(t, dict)],
        key=lambda t: int(t.get("desde", 0)),
        reverse=True,
    )
    for tramo in tramos:
        if encaje >= int(tramo.get("desde", 0)):
            return str(tramo.get("grado"))
    return None


def _decaimiento(
    modelo: ModeloPuntuacion, interes: int, ultima_actividad: datetime | None
) -> tuple[int, int]:
    """Cuánto interés se pierde por inactividad (CRM-02.01.02.04).

    Solo decae el interés. Y **nunca baja del mínimo declarado**: si bajara a
    cero, un lead que fue muy activo hace un año quedaría indistinguible de uno
    que no ha hecho nada nunca, y esos dos merecen tratos distintos.
    """
    if modelo.decaimiento_puntos <= 0 or ultima_actividad is None:
        return interes, 0
    dias = (_ahora() - _con_tz(ultima_actividad)).days
    periodos = dias // max(1, modelo.decaimiento_dias)
    if periodos <= 0:
        return interes, 0
    perdido = periodos * modelo.decaimiento_puntos
    final = max(modelo.interes_minimo, interes - perdido)
    return final, interes - final


def calificar(modelo: ModeloPuntuacion, interes: int, encaje: int) -> str:
    """MQL, SQL o ninguno, exigiendo **los dos ejes**.

    Con un solo eje, o pasan estudiantes muy activos o directores que no han
    mostrado ningún interés. Un umbral sin declarar se trata como «no aplica» y
    no como cero: cero dejaría pasar a todo el mundo.
    """

    def _pasa(umbral_i: int | None, umbral_e: int | None) -> bool:
        if umbral_i is None and umbral_e is None:
            return False
        return (umbral_i is None or interes >= umbral_i) and (
            umbral_e is None or encaje >= umbral_e
        )

    if _pasa(modelo.umbral_sql_interes, modelo.umbral_sql_encaje):
        return "sql"
    if _pasa(modelo.umbral_mql_interes, modelo.umbral_mql_encaje):
        return "mql"
    return "ninguno"


def puntuar(
    uow: UnidadDeTrabajo,
    lead_id: UUID,
    *,
    modelo_clave: str = "",
    ambito_extra: dict[str, Any] | None = None,
) -> PuntuacionLead:
    """Calcula y guarda la puntuación de un lead.

    Emite el cambio de calificación **solo cuando cambia**. Emitirlo en cada
    recálculo llenaría la cola de eventos idénticos y haría que la regla «avisa a
    ventas cuando pase a MQL» disparara cada hora sobre el mismo lead.
    """
    from services.marketing.modelos import PerfilMarketing

    modelo = modelo_activo(uow.db, uow.tenant_id, modelo_clave)
    if modelo is None:
        raise NoEncontrado(
            "No hay ningún modelo de puntuación activo",
            error_code="marketing.sin_modelo_de_puntuacion",
        )
    # El lead se lee de la proyección local (`PerfilMarketing`): `marketing` no
    # puede leer el esquema de `sales`, y puntuar no puede depender de que ese
    # servicio esté en pie. El precio es que un lead recién creado puede no estar
    # todavía, y por eso se dice cuál es el error en vez de puntuarlo a cero —que
    # lo dejaría al final de la lista sin que nadie entendiera por qué.
    lead = uow.db.execute(
        select(PerfilMarketing).where(
            PerfilMarketing.tenant_id == uow.tenant_id,
            PerfilMarketing.objeto == "lead",
            PerfilMarketing.objeto_id == lead_id,
        )
    ).scalar_one_or_none()
    if lead is None:
        raise NoEncontrado(
            "Ese lead todavía no está en la proyección de marketing. Si acaba de "
            "crearse, vuelve a intentarlo en unos segundos.",
            error_code="marketing.lead_no_proyectado",
        )

    ambito = {
        "lead": {
            **{
                c.name: getattr(lead, c.name, None)
                for c in PerfilMarketing.__table__.columns
                if c.name != "campos"
            },
            **(lead.campos or {}),
        },
        **(ambito_extra or {}),
    }

    interes_bruto, desglose_i = _aplicar(modelo.reglas_interes, ambito, "interes")
    encaje, desglose_e = _aplicar(modelo.reglas_encaje, ambito, "encaje")
    ultima = _con_tz(getattr(lead, "ultima_actividad_at", None))
    interes, decaido = _decaimiento(modelo, interes_bruto, ultima)
    grado = _grado(encaje, modelo.grados)
    calificacion = calificar(modelo, interes, encaje)

    fila = uow.db.execute(
        select(PuntuacionLead).where(
            PuntuacionLead.tenant_id == uow.tenant_id, PuntuacionLead.lead_id == lead_id
        )
    ).scalar_one_or_none()
    anterior = fila.calificacion if fila is not None else "ninguno"
    if fila is None:
        fila = PuntuacionLead(tenant_id=uow.tenant_id, lead_id=lead_id)
        uow.db.add(fila)

    fila.modelo = modelo.clave
    fila.modelo_version = modelo.version
    fila.interes = interes
    fila.encaje = encaje
    fila.grado = grado
    fila.calificacion = calificacion
    fila.desglose = desglose_i + desglose_e
    fila.decaido = decaido
    fila.ultima_actividad_at = ultima
    fila.calculado_at = _ahora()
    uow.db.flush()

    if calificacion != anterior and calificacion != "ninguno":
        registrar(
            uow.db,
            accion=f"marketing.lead_{calificacion}",
            objeto="lead",
            objeto_id=lead_id,
            datos={
                "desde": anterior,
                "interes": interes,
                "encaje": encaje,
                "grado": grado,
                "modelo": f"{modelo.clave} v{modelo.version}",
            },
            tenant_id=uow.tenant_id,
        )
        uow.emitir(
            "lead.qualified",
            subject=("lead", lead_id),
            data={
                "lead_id": str(lead_id),
                "calificacion": calificacion,
                "anterior": anterior,
                "interes": interes,
                "encaje": encaje,
                "grado": grado or "",
                # El desglose viaja en el evento para que quien reciba el aviso
                # sepa **por qué**: «lead caliente» sin el motivo obliga al
                # comercial a abrir la ficha antes de llamar, y la mitad de las
                # veces no la abre.
                "motivos": [d["regla"] for d in fila.desglose],
            },
            dedup_key=f"lead.qualified:{lead_id}:{calificacion}",
        )
    return fila


def explicar(db: Session, tenant_id: UUID, lead_id: UUID) -> dict[str, Any]:
    """Por qué este lead tiene esta puntuación.

    «Este lead tiene 87» no le sirve a nadie: lo que hace que un comercial llame
    es saber que descargó el comparativo de precios y visitó la página de
    contratación dos veces. Sin el porqué, el número es un adorno.
    """
    fila = db.execute(
        select(PuntuacionLead).where(
            PuntuacionLead.tenant_id == tenant_id, PuntuacionLead.lead_id == lead_id
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            "Ese lead no está puntuado todavía",
            error_code="marketing.lead_sin_puntuacion",
        )
    return {
        "lead_id": str(lead_id),
        "modelo": f"{fila.modelo} v{fila.modelo_version}",
        "interes": fila.interes,
        "encaje": fila.encaje,
        "grado": fila.grado,
        "calificacion": fila.calificacion,
        "por_interes": [d for d in fila.desglose if d["eje"] == "interes"],
        "por_encaje": [d for d in fila.desglose if d["eje"] == "encaje"],
        # El decaimiento se enseña aparte: sin él, quien mira no entiende por qué
        # un lead que hizo muchas cosas tiene poco interés, y concluye que el
        # scoring está roto.
        "perdido_por_inactividad": fila.decaido,
        "ultima_actividad_at": (
            fila.ultima_actividad_at.isoformat() if fila.ultima_actividad_at else None
        ),
        "calculado_at": fila.calculado_at.isoformat(),
        # Se dice contra qué versión se calculó: comparar dos leads puntuados con
        # modelos distintos es comparar dos cosas que no son la misma.
        "aviso": (
            "Calculado con una versión anterior del modelo; vuelve a puntuarlo "
            "para compararlo con los demás."
        )
        if _version_desfasada(db, tenant_id, fila)
        else "",
    }


def _version_desfasada(db: Session, tenant_id: UUID, fila: PuntuacionLead) -> bool:
    modelo = modelo_activo(db, tenant_id, fila.modelo)
    return modelo is not None and modelo.version != fila.modelo_version


def pendientes_de_recalcular(db: Session, tenant_id: UUID, *, limite: int = 500) -> list[UUID]:
    """Leads puntuados con una versión vieja del modelo.

    Existe porque publicar una versión nueva no repuntúa a nadie por sí solo, y
    dejar la mitad de la base con el modelo viejo hace que dos leads iguales
    salgan con puntuaciones distintas — y entonces la lista deja de servir para
    ordenar por prioridad, que es lo único para lo que se usa.
    """
    modelo = modelo_activo(db, tenant_id)
    if modelo is None:
        return []
    return list(
        db.execute(
            select(PuntuacionLead.lead_id)
            .where(
                PuntuacionLead.tenant_id == tenant_id,
                PuntuacionLead.modelo == modelo.clave,
                PuntuacionLead.modelo_version != modelo.version,
            )
            .limit(limite)
        ).scalars()
    )
