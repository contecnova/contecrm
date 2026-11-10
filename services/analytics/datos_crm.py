"""Cohortes, embudo y actividad con los datos del CRM (CRM-05.01.03.04, .05, .06).

**Por qué existe.** `cohortes.py` sabía calcular y nadie le daba de comer: las
tres rutas de `/analisis/*` recibían los sujetos tecleados en el cuerpo, así que
el análisis decía lo que quien llamaba quisiera que dijera. Medido el
09-11-2026: ninguna pantalla las llamaba y no había forma de pedir «la cohorte
de mis cuentas» sin montar el JSON a mano.

**De dónde salen los hechos.** Primero del almacén analítico, si hay una tabla
de ese objeto cargada y con las columnas que hacen falta: es la copia que está
para esto, y leerla no carga el operacional. Si no, de los servicios dueños
**por su API y con la identidad de quien pregunta** —`interno.invocar`—: así el
análisis ve lo que esa persona ve en la aplicación, ni un registro más. Leer el
esquema de `party` o de `sales` desde aquí no se puede (y está bien que no).

**Lo que se recorta se dice.** Cada objeto se lee hasta un tope
(`analisis_max_registros`); si se llega, la respuesta lo trae como `recortado`
y la pantalla lo enseña. Un embudo de las dos mil más recientes presentado como
«todas» es un número que no existió.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from crmcore.fechas import hoy as hoy_del_cliente
from crmcore.logging import get_logger
from crmcore.runtime import settings as rt
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.analytics import cohortes as coh
from services.analytics.almacen import FilaAnalitica, TablaAnalitica

logger = get_logger(__name__)

# Columnas que necesita cada análisis de cada objeto. Una tabla del almacén que
# no las tiene no sirve para esto, y se cae a la API en vez de calcular sobre
# campos vacíos.
COLUMNAS: dict[str, set[str]] = {
    "cuenta": {"id", "created_at"},
    "actividad": {"id", "created_at", "cuenta_id", "asignada_a"},
    "oportunidad": {"id", "created_at", "cuenta_id", "owner_id", "estado_significa"},
}

RUTAS: dict[str, str] = {
    "cuenta": "/api/v1/accounts",
    "actividad": "/api/v1/activities",
    "oportunidad": "/api/v1/opportunities",
}

# Qué significa cada estado, no cómo lo llama la empresa: «abierta», «En pausa»
# o lo que haya configurado se leen por su significado (`estado_significa`).
ABIERTO = {"abierto", "abierta"}
GANADO = {"ganado", "ganada"}


def _significa(fila: dict[str, Any]) -> str:
    return str(fila.get("estado_significa") or fila.get("estado") or "")


# Filtros que hay que mandar para ver TODO y no lo que el listado enseña por
# defecto: el de oportunidades devuelve sólo las abiertas si no se le dice otra
# cosa, y un embudo sin las ganadas ni las perdidas no es un embudo.
PARAMETROS: dict[str, dict[str, Any]] = {"oportunidad": {"estado": ""}}


def _ajuste(clave: str, db: Session | None, defecto: int) -> int:
    try:
        return int(rt.efectivo(clave, db) or defecto)
    except Exception:  # noqa: BLE001 — sin catálogo de ajustes vale el defecto
        return defecto


def _a_fecha(valor: Any) -> date | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).date()
    except ValueError:
        return None


class Lector:
    """Lee los objetos del CRM para un análisis, y recuerda de dónde.

    Una instancia por petición: guarda la procedencia de cada objeto para
    devolverla con el resultado. Un análisis que no dice de dónde sacó los
    datos no se puede discutir.
    """

    def __init__(self, db: Session, principal: Any) -> None:
        self.db = db
        self.principal = principal
        self.maximo = _ajuste("analisis_max_registros", db, 2000)
        self.procedencia: dict[str, dict[str, Any]] = {}
        self._leidos: dict[str, list[dict[str, Any]]] = {}

    # ── Llamadas ──────────────────────────────────────────────────────────

    def _invocar(self, ruta: str, parametros: dict[str, Any] | None = None) -> dict[str, Any]:
        from crmcore.errors import NoDisponible
        from crmcore.http.interno import invocar

        try:
            return invocar(
                metodo="GET",
                ruta=ruta,
                parametros=parametros or None,
                tenant_id=self.principal.tenant_id,
                principal_id=self.principal.id,
                permisos=sorted(getattr(self.principal, "permisos", None) or []),
                roles=sorted(getattr(self.principal, "roles", None) or []),
                tipo="usuario",
            )
        except NoDisponible as exc:
            # Un servicio caído o sin dirección no tumba el análisis entero:
            # ese objeto sale como «no se ha podido leer» y lo demás se calcula.
            logger.warning("analisis.servicio_no_disponible", ruta=ruta, error=str(exc)[:200])
            return {"estado": 503, "ok": False, "datos": {}}

    def _por_api(self, objeto: str, filtros: dict[str, Any]) -> list[dict[str, Any]]:
        ruta = RUTAS[objeto]
        salida: list[dict[str, Any]] = []
        cursor = ""
        recortado = False
        estado_http = 200
        while True:
            parametros: dict[str, Any] = {
                **PARAMETROS.get(objeto, {}),
                **filtros,
                "limite": min(200, self.maximo - len(salida)),
            }
            if cursor:
                parametros["cursor"] = cursor
            r = self._invocar(ruta, parametros)
            estado_http = int(r.get("estado") or 0)
            if estado_http != 200:
                break
            datos = r.get("datos")
            filas = datos.get("items") if isinstance(datos, dict) else datos
            salida.extend(f for f in (filas or []) if isinstance(f, dict))
            cursor = str((datos or {}).get("siguiente") or "") if isinstance(datos, dict) else ""
            if len(salida) >= self.maximo:
                recortado = bool(cursor)
                break
            if not cursor:
                break
        self.procedencia[objeto] = {
            "fuente": "api",
            "ruta": ruta,
            "filtros": filtros,
            "leidos": len(salida),
            "recortado": recortado,
            # Un 403 no es «no hay datos»: es que quien pregunta no puede verlos,
            # y la pantalla lo tiene que decir así.
            "sin_permiso": estado_http in (401, 403),
            # Cualquier otra respuesta que no sea 200 —un 429 porque la cuota
            # de quien pregunta se agotó, un 503— tampoco es «cero»: se marca
            # para que la pantalla diga que no se pudo leer.
            "no_leido": estado_http not in (200, 401, 403),
            "estado_http": estado_http,
        }
        return salida

    def _del_almacen(self, objeto: str) -> list[dict[str, Any]] | None:
        tabla = (
            self.db.execute(
                select(TablaAnalitica).where(
                    TablaAnalitica.tenant_id == self.principal.tenant_id,
                    TablaAnalitica.objeto == objeto,
                    TablaAnalitica.activa.is_(True),
                    TablaAnalitica.deleted_at.is_(None),
                    TablaAnalitica.ultima_carga_at.is_not(None),
                    TablaAnalitica.filas > 0,
                )
            )
            .scalars()
            .first()
        )
        if tabla is None:
            return None
        columnas = {str(c.get("nombre")) for c in (tabla.columnas or []) if isinstance(c, dict)}
        # El almacén guarda el id de origen como `clave_origen`.
        columnas.add("id")
        if not COLUMNAS[objeto] <= columnas:
            return None
        filas = (
            self.db.execute(
                select(FilaAnalitica)
                .where(
                    FilaAnalitica.tenant_id == self.principal.tenant_id,
                    FilaAnalitica.tabla_id == tabla.id,
                )
                .order_by(FilaAnalitica.ocurrido_at.desc())
                .limit(self.maximo + 1)
            )
            .scalars()
            .all()
        )
        salida = [{"id": f.clave_origen, **(f.datos or {})} for f in filas[: self.maximo]]
        self.procedencia[objeto] = {
            "fuente": "almacen",
            "tabla": tabla.clave,
            "leidos": len(salida),
            "recortado": len(filas) > self.maximo,
            "datos_de": tabla.ultima_carga_at.isoformat() if tabla.ultima_carga_at else None,
            "sin_permiso": False,
        }
        return salida

    def leer(self, objeto: str, **filtros: Any) -> list[dict[str, Any]]:
        """Las filas de un objeto. `filtros` son los filtros comunes de la URL
        (`created_at__desde=…`): se mandan a la API para no traer de más, y con
        ellos no se usa el almacén, que no los sabe aplicar igual."""
        clave = objeto + repr(sorted(filtros.items()))
        if clave not in self._leidos:
            filas = None if filtros else self._del_almacen(objeto)
            self._leidos[clave] = filas if filas is not None else self._por_api(objeto, filtros)
        return self._leidos[clave]

    def pipelines(self) -> list[dict[str, Any]]:
        r = self._invocar("/api/v1/pipelines", {"limite": 200})
        estado_http = int(r.get("estado") or 0)
        if estado_http != 200:
            self.procedencia["embudos"] = {
                "fuente": "api",
                "ruta": "/api/v1/pipelines",
                "leidos": 0,
                "recortado": False,
                "sin_permiso": estado_http in (401, 403),
                "no_leido": estado_http not in (401, 403),
                "estado_http": estado_http,
            }
        datos = r.get("datos")
        filas = datos.get("items") if isinstance(datos, dict) else datos
        return [p for p in (filas or []) if isinstance(p, dict)] if r.get("estado") == 200 else []

    def historiales(
        self, *, pipeline_id: str, desde: date
    ) -> tuple[dict[str, list[dict[str, Any]]], bool, int]:
        """El paso por etapas de las oportunidades de un embudo, en bloque.

        Antes era una llamada por oportunidad y, para no comerse la cuota de
        quien mira, se quedaba en las 100 más recientes. Ahora son páginas de
        200 del listado en bloque de `sales`, hasta el mismo tope que cualquier
        otro objeto (`analisis_max_registros`). Devuelve los cambios por
        oportunidad, si se recortó y el estado HTTP de la última llamada.
        """
        ruta = "/api/v1/opportunities/historial-etapas"
        salida: dict[str, list[dict[str, Any]]] = {}
        cursor = ""
        recortado = False
        estado_http = 200
        while True:
            parametros: dict[str, Any] = {
                "pipeline_id": pipeline_id,
                "created_at__desde": str(desde),
                "limite": min(200, self.maximo - len(salida)),
            }
            if cursor:
                parametros["cursor"] = cursor
            r = self._invocar(ruta, parametros)
            estado_http = int(r.get("estado") or 0)
            if estado_http != 200:
                break
            datos = r.get("datos") if isinstance(r.get("datos"), dict) else {}
            for fila in datos.get("items") or []:
                if isinstance(fila, dict) and fila.get("oportunidad_id"):
                    salida[str(fila["oportunidad_id"])] = [
                        c for c in (fila.get("cambios") or []) if isinstance(c, dict)
                    ]
            cursor = str(datos.get("siguiente") or "")
            if len(salida) >= self.maximo:
                recortado = bool(cursor)
                break
            if not cursor:
                break
        return salida, recortado, estado_http


# ── Cohortes (CRM-05.01.03.04) ────────────────────────────────────────────


def cohortes_crm(
    db: Session,
    principal: Any,
    *,
    periodo: str = "mes",
    periodos: int = 6,
    hoy: date | None = None,
    lector: Lector | None = None,
) -> dict[str, Any]:
    """Retención de las cuentas por mes de alta.

    Cohorte = cuándo se dio de alta la cuenta. «Activa» en un periodo = tuvo
    una actividad o se le abrió una oportunidad en ese periodo. Las dos cosas
    son señales de vida que el CRM ya guarda; inventarse otra (facturar, por
    ejemplo) exigiría un dato que el CRM no tiene.
    """
    lec = lector or Lector(db, principal)
    cuentas = lec.leer("cuenta")
    actividad: dict[str, list[str]] = {}
    for a in lec.leer("actividad"):
        if a.get("cuenta_id"):
            fecha = a.get("inicio_at") or a.get("completada_at") or a.get("created_at")
            actividad.setdefault(str(a["cuenta_id"]), []).append(str(fecha or ""))
    for o in lec.leer("oportunidad"):
        if o.get("cuenta_id"):
            actividad.setdefault(str(o["cuenta_id"]), []).append(str(o.get("created_at") or ""))
    sujetos = [
        {
            "id": str(c.get("id")),
            "alta": c.get("created_at"),
            "actividad": [f for f in actividad.get(str(c.get("id")), []) if f],
        }
        for c in cuentas
    ]
    salida = coh.cohortes(
        sujetos=sujetos, periodo=periodo, periodos=periodos, hoy=hoy or hoy_del_cliente(db)
    )
    salida["procedencia"] = lec.procedencia
    salida["sujeto"] = "cuenta"
    return salida


# ── Embudo (CRM-05.01.03.05) ──────────────────────────────────────────────


def embudo_crm(
    db: Session,
    principal: Any,
    *,
    pipeline_id: UUID | None = None,
    desde: date | None = None,
    hoy: date | None = None,
    lector: Lector | None = None,
) -> dict[str, Any]:
    """Conversión y tiempos entre etapas de un embudo de ventas real.

    Las etapas son las del embudo elegido —o el de por defecto—, en su orden y
    sin las terminales de pérdida: «perdida» no es una etapa a la que se
    convierte. Los pasos salen del historial de etapas de cada oportunidad, que
    guarda cuándo entró en cada una.
    """
    lec = lector or Lector(db, principal)
    embudos = lec.pipelines()
    elegido = None
    for p in embudos:
        if pipeline_id and str(p.get("id")) == str(pipeline_id):
            elegido = p
    if elegido is None and not pipeline_id:
        elegido = next((p for p in embudos if p.get("por_defecto")), None) or (
            embudos[0] if embudos else None
        )
    base = {
        "embudos": [{"id": str(p.get("id")), "nombre": p.get("nombre")} for p in embudos],
        "procedencia": lec.procedencia,
    }
    if elegido is None:
        return {
            **base,
            "pipeline": None,
            "etapas": [],
            "medible": False,
            "aviso": (
                "No se han podido leer los embudos de ventas."
                if "embudos" in lec.procedencia
                else "No hay ningún embudo de ventas definido."
            ),
        }
    etapas = sorted(
        [e for e in (elegido.get("etapas") or []) if not e.get("terminal") or e.get("ganada")],
        key=lambda e: int(e.get("orden") or 0),
    )
    nombre_de = {str(e.get("id")): str(e.get("nombre")) for e in etapas}
    ventana = _ajuste("analisis_dias_ventana", db, 365)
    corte = desde or ((hoy or hoy_del_cliente(db)) - timedelta(days=ventana))
    oportunidades = [
        o
        for o in lec.leer("oportunidad")
        if str(o.get("pipeline_id")) == str(elegido.get("id"))
        and (_a_fecha(o.get("created_at")) or date.min) >= corte
    ]
    historiales, recortado, estado_http = lec.historiales(
        pipeline_id=str(elegido.get("id")), desde=corte
    )
    recorridos = []
    for o in oportunidades:
        pasos = [
            {"etapa": nombre_de[str(c.get("etapa_hasta_id"))], "fecha": c.get("created_at")}
            for c in historiales.get(str(o.get("id")), [])
            if str(c.get("etapa_hasta_id")) in nombre_de
        ]
        recorridos.append(
            {
                "id": str(o.get("id")),
                "pasos": pasos,
                "abierto": _significa(o) in ABIERTO,
            }
        )
    salida = coh.embudo(
        etapas=[nombre_de[str(e.get("id"))] for e in etapas],
        recorridos=recorridos,
        hoy=hoy or hoy_del_cliente(db),
        contar_saltadas=True,
    )
    lec.procedencia["historial_etapas"] = {
        "fuente": "api",
        "ruta": "/api/v1/opportunities/historial-etapas",
        "leidos": len(historiales),
        "recortado": recortado,
        "sin_permiso": estado_http in (401, 403),
        "no_leido": estado_http not in (200, 401, 403),
        "estado_http": estado_http,
    }
    return {
        **salida,
        **base,
        "procedencia": lec.procedencia,
        "pipeline": {"id": str(elegido.get("id")), "nombre": elegido.get("nombre")},
        "desde": str(corte),
    }


# ── Actividad y resultados (CRM-05.01.03.06) ──────────────────────────────


def actividad_crm(
    db: Session,
    principal: Any,
    *,
    desde: date | None = None,
    hoy: date | None = None,
    lector: Lector | None = None,
) -> dict[str, Any]:
    """Por comercial: actividades hechas frente a oportunidades ganadas.

    El sujeto es la persona —quien tiene la actividad asignada y quien es dueña
    de la oportunidad—, en la misma ventana de tiempo para las dos series.
    """
    lec = lector or Lector(db, principal)
    ahora = hoy or hoy_del_cliente(db)
    corte = desde or (ahora - timedelta(days=_ajuste("analisis_dias_ventana", db, 365)))
    por: dict[str, dict[str, Any]] = {}

    def sujeto(uid: str) -> dict[str, Any]:
        return por.setdefault(uid, {"id": uid, "actividades": 0, "ganadas": 0, "importe": 0.0})

    for a in lec.leer("actividad", created_at__desde=str(corte)):
        uid = str(a.get("asignada_a") or "")
        fecha = _a_fecha(a.get("inicio_at") or a.get("completada_at") or a.get("created_at"))
        if uid and fecha and corte <= fecha <= ahora:
            sujeto(uid)["actividades"] += 1
    for o in lec.leer("oportunidad"):
        uid = str(o.get("owner_id") or "")
        if not uid:
            continue
        s = sujeto(uid)
        fecha = _a_fecha(o.get("fecha_cierre_real") or o.get("fecha_cierre"))
        if _significa(o) in GANADO and fecha and corte <= fecha <= ahora:
            s["ganadas"] += 1
            try:
                s["importe"] += float(o.get("importe_funcional") or o.get("importe") or 0)
            except (TypeError, ValueError):
                pass
    sujetos = sorted(por.values(), key=lambda s: (-s["actividades"], s["id"]))
    salida = coh.correlacion_actividad(
        sujetos=sujetos,
        metrica="ganadas",
        minimo=_ajuste("analisis_minimo_correlacion", db, 8),
    )
    return {
        **salida,
        "por_persona": sujetos,
        "desde": str(corte),
        "hasta": str(ahora),
        "procedencia": lec.procedencia,
    }
