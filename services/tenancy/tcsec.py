"""Clasificación TCSEC de la instalación (CRM-07.03.02.11).

Pedido el 09-11-2026 («un GRC que pueda llegar a tener un TCSEC como los de
Infor») y aclarado por formulario: clasificar la instalación por nivel (D, C1,
C2, B1, B2, B3, A1), los controles que exige cada nivel con su comprobación
automática donde se pueda, y un informe exportable para auditoría.

Tres decisiones:

- **Lo que se puede medir, se mide; no se declara.** Cada requisito
  automático lee una comprobación que ya existe —la cadena de auditoría de
  cada servicio, las capas de aislamiento, la adopción del segundo factor, la
  segregación de funciones, las etiquetas de sensibilidad—. Un requisito que
  no se puede medir en este momento sale **sin medir**, nunca como cumplido:
  una comprobación que no mira parece verde.
- **Lo que sólo puede afirmar una persona se atestigua en el GRC.** Canales
  encubiertos, gestión de la configuración, recuperación de confianza y
  verificación formal no salen de una consulta. Se anotan como evaluación de
  un control del GRC (`TCSEC-<requisito>`), con evidencia, fecha y
  caducidad: así no hay una segunda tabla de controles y salen también en
  Riesgos y controles, bajo el marco «TCSEC».
- **Lo que el producto no hace, no se atestigua.** El control obligatorio de
  ESCRITURA por etiquetas (no escribir hacia abajo) no existe; B1 lo exige y
  se dice. Dejar atestiguar algo que el producto no hace sería un informe que
  miente a favor.

El nivel alcanzado es el más alto con todos sus requisitos y los de los
niveles inferiores cumplidos.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.fechas import hoy
from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = get_logger(__name__)

NIVELES = ("D", "C1", "C2", "B1", "B2", "B3", "A1")

NOMBRE_NIVEL = {
    "D": "Protección mínima",
    "C1": "Protección discrecional",
    "C2": "Acceso controlado",
    "B1": "Protección por etiquetas",
    "B2": "Protección estructurada",
    "B3": "Dominios de seguridad",
    "A1": "Diseño verificado",
}

# Estados de un requisito. «sin_medir» no es «no cumple»: es que no se ha
# podido comprobar, y en una auditoría la diferencia es la que importa.
CUMPLE = "cumple"
NO_CUMPLE = "no_cumple"
SIN_MEDIR = "sin_medir"
NO_IMPLEMENTADO = "no_implementado"
ESTADOS = (CUMPLE, NO_CUMPLE, SIN_MEDIR, NO_IMPLEMENTADO)


@dataclass
class Contexto:
    """Lo que comparten las comprobaciones de una evaluación.

    Lo que viene de otros servicios se pide una vez y se guarda aquí: el
    informe de cumplimiento de un servicio sirve para la cadena de auditoría y
    para las etiquetas, y pedirlo dos veces es pagar dos veces la verificación
    de la cadena entera.
    """

    db: Session
    tenant_id: UUID
    principal_id: UUID
    _cache: dict[str, Any]

    def pedir(
        self, ruta: str, permisos: list[str], parametros: dict[str, Any] | None = None
    ) -> Any:
        """GET a otro servicio con la identidad de quien evalúa. None si no contesta.

        Los parámetros van aparte y nunca en la ruta: la ruta es lo que decide a
        qué servicio se llama, y con `?limite=` pegado no la reconoce ninguno.
        """
        if ruta not in self._cache:
            from crmcore.http.interno import invocar

            try:
                r = invocar(
                    metodo="GET",
                    ruta=ruta,
                    parametros=parametros,
                    tenant_id=self.tenant_id,
                    principal_id=self.principal_id,
                    permisos=permisos,
                )
                self._cache[ruta] = r["datos"] if r.get("estado") == 200 else None
            except Exception as exc:  # noqa: BLE001 — se dice como «sin medir»
                logger.warning("tcsec.no_contesta", ruta=ruta, error=str(exc)[:200])
                self._cache[ruta] = None
        return self._cache[ruta]


Resultado = tuple[str, str, dict[str, Any]]


def _servicios() -> list[str]:
    from crmcore.config import get_settings
    from crmcore.rutas_de_api import cargar_destinos

    return sorted(cargar_destinos(get_settings().rutas_servicios))


def _informes(ctx: Contexto) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """El informe de cumplimiento de cada servicio, y los que no contestaron."""
    informes: dict[str, dict[str, Any]] = {}
    sin_respuesta: list[str] = []
    for servicio in _servicios():
        datos = ctx.pedir(f"/api/v1/{servicio}/cumplimiento/informe", ["cumplimiento:leer"])
        if isinstance(datos, dict):
            informes[servicio] = datos
        else:
            sin_respuesta.append(servicio)
    return informes, sin_respuesta


# ── Comprobaciones automáticas ────────────────────────────────────────────


def _ajuste(clave: str, db: Session) -> Any:
    """El valor de la empresa si lo ha cambiado, y si no el de `.env`.

    No todos los ajustes son editables en caliente: sin el respaldo,
    `login_bloqueo_minutos` daba vacío y el bloqueo salía «apagado» estando a 15.
    """
    from crmcore.config import get_settings
    from crmcore.runtime.settings import efectivo

    return efectivo(clave, db, default=getattr(get_settings(), clave, None))


def _identificacion(ctx: Contexto) -> Resultado:
    intentos = int(_ajuste("login_max_intentos", ctx.db) or 0)
    bloqueo = int(_ajuste("login_bloqueo_minutos", ctx.db) or 0)
    datos = {"login_max_intentos": intentos, "login_bloqueo_minutos": bloqueo}
    if intentos > 0 and bloqueo > 0:
        return (
            CUMPLE,
            f"Cada persona entra con su cuenta; tras {intentos} intentos fallidos "
            f"se bloquea {bloqueo} minutos.",
            datos,
        )
    return (
        NO_CUMPLE,
        "El bloqueo por intentos fallidos está apagado: la contraseña se puede "
        "probar sin límite.",
        datos,
    )


def _discrecional(ctx: Contexto) -> Resultado:
    roles = ctx.pedir("/api/v1/roles", ["user:read"], {"limite": 200})
    if roles is None:
        return SIN_MEDIR, "Identidad no ha contestado: no se han podido leer los roles.", {}
    filas = roles.get("items", roles) if isinstance(roles, dict) else roles
    con_permisos = [r for r in filas or [] if r.get("permisos")]
    if con_permisos:
        return (
            CUMPLE,
            f"El acceso lo decide el rol: {len(con_permisos)} roles con sus permisos.",
            {"roles": len(con_permisos)},
        )
    return NO_CUMPLE, "No hay ningún rol con permisos declarados.", {"roles": 0}


def _aislamiento(ctx: Contexto) -> Resultado:
    from services.tenancy.aislamiento import garantias

    g = garantias(ctx.db)
    capas = {c["clave"]: c for c in g.get("capas", [])}
    motor, rol = capas.get("motor", {}), capas.get("rol", {})
    datos = {
        "rol_se_salta_la_red": g.get("rol_se_salta_la_red"),
        "tablas_con_tenant": g.get("tablas_con_tenant"),
    }
    if motor.get("ok") and rol.get("ok"):
        return (
            CUMPLE,
            f"Las {g.get('tablas_con_tenant')} tablas con empresa tienen RLS forzado "
            "y el rol de conexión no se lo salta.",
            datos,
        )
    # El título de la capa es la garantía («El rol de conexión no se salta la
    # red»): va entre comillas y con su explicación, o se lee al revés.
    falla = [
        f"No se cumple «{c.get('titulo', k)}»"
        + (f": {str(c['detalle']).rstrip('. ')}" if c.get("detalle") else "")
        for k, c in (("motor", motor), ("rol", rol))
        if not c.get("ok")
    ]
    return NO_CUMPLE, ". ".join(falla) + ".", datos


def _auditoria(ctx: Contexto) -> Resultado:
    informes, sin_respuesta = _informes(ctx)
    rotas: list[str] = []
    vacias: list[str] = []
    apuntes = 0
    for servicio, informe in informes.items():
        v = (informe.get("integridad_del_audit_trail") or {}).get("verificacion") or {}
        if not v:
            sin_respuesta.append(servicio)
            continue
        apuntes += int(v.get("apuntes") or 0)
        if not v.get("intacta"):
            rotas.append(f"{servicio} (en el apunte {v.get('rota_en')})")
        elif not v.get("apuntes"):
            vacias.append(servicio)
    datos = {
        "servicios": sorted(informes),
        "sin_respuesta": sorted(set(sin_respuesta)),
        "apuntes": apuntes,
        "rotas": rotas,
    }
    if rotas:
        return NO_CUMPLE, "Cadena de auditoría alterada en: " + ", ".join(rotas) + ".", datos
    if not informes or sin_respuesta:
        return (
            SIN_MEDIR,
            "No se ha podido verificar la cadena de: "
            + ", ".join(sorted(set(sin_respuesta)) or ["ningún servicio configurado"])
            + ".",
            datos,
        )
    if apuntes == 0:
        return NO_CUMPLE, "No hay ningún apunte de auditoría que verificar.", datos
    return (
        CUMPLE,
        f"{apuntes} apuntes encadenados e intactos en {len(informes)} servicios.",
        datos,
    )


def _segundo_factor(ctx: Contexto) -> Resultado:
    minimo = float(_ajuste("tcsec_mfa_minima_pct", ctx.db) or 0)
    a = ctx.pedir("/api/v1/factores/adopcion", ["user:read"])
    if a is None or not a.get("medible", True):
        return SIN_MEDIR, "Identidad no ha dado la adopción del segundo factor.", {}
    pct = float(a.get("adopcion_pct") or 0)
    datos = {
        "adopcion_pct": pct,
        "minimo_pct": minimo,
        "sin_factor": a.get("sin_factor"),
        "total": a.get("total_usuarios"),
    }
    if pct >= minimo:
        return (
            CUMPLE,
            f"El {pct:g} % de las personas tiene segundo factor (mínimo {minimo:g} %).",
            datos,
        )
    return (
        NO_CUMPLE,
        f"Sólo el {pct:g} % tiene segundo factor; el mínimo es {minimo:g} %: "
        f"faltan {a.get('sin_factor')} personas.",
        datos,
    )


def _reutilizacion(ctx: Contexto) -> Resultado:
    from crmcore.security.byok import activa

    if activa(ctx.db, ctx.tenant_id) is not None:
        return (
            CUMPLE,
            "Hay clave propia de cifrado: revocarla deja ilegible lo guardado, "
            "también en copias.",
            {"clave_propia": True},
        )
    return (
        NO_CUMPLE,
        "Sin clave propia de cifrado, lo borrado no se puede destruir "
        "criptográficamente: queda en copias hasta que caducan.",
        {"clave_propia": False},
    )


def _etiquetas(ctx: Contexto) -> Resultado:
    informes, sin_respuesta = _informes(ctx)
    campos = 0
    por_nivel: dict[str, int] = {}
    for informe in informes.values():
        for actividad in (informe.get("rat") or {}).get("actividades", []):
            for c in actividad.get("campos", []):
                campos += 1
                s = str(c.get("sensibilidad"))
                por_nivel[s] = por_nivel.get(s, 0) + 1
    datos = {"campos": campos, "por_nivel": por_nivel, "sin_respuesta": sin_respuesta}
    if not informes:
        return SIN_MEDIR, "Ningún servicio ha dado su registro de tratamiento.", datos
    if campos:
        return (
            CUMPLE,
            f"{campos} campos llevan su etiqueta de sensibilidad"
            + (f" (sin leer: {', '.join(sin_respuesta)})." if sin_respuesta else "."),
            datos,
        )
    return NO_CUMPLE, "Ningún campo declara su sensibilidad.", datos


def _lectura_por_etiqueta(ctx: Contexto) -> Resultado:
    politica = _ajuste("politica_sensibilidad", ctx.db) or {}
    roles = sorted(r for r in politica if r != "*")
    datos = {"roles_con_nivel": roles}
    if roles:
        return (
            CUMPLE,
            f"Cada rol tiene su nivel ({len(roles)} roles): un campo por encima de "
            "él se enmascara o no se ve, y la persona no lo puede cambiar.",
            datos,
        )
    return NO_CUMPLE, "Ningún rol tiene nivel de sensibilidad declarado.", datos


def _escritura_por_etiqueta(ctx: Contexto) -> Resultado:
    return (
        NO_IMPLEMENTADO,
        "El producto no impide copiar un dato de un nivel alto a un campo de "
        "nivel más bajo (la regla «no escribir hacia abajo»). Sin eso no hay "
        "B1 completo, y no se puede atestiguar.",
        {},
    )


def _segregacion(ctx: Contexto) -> Resultado:
    v = ctx.pedir("/api/v1/segregacion/violaciones", ["user:read"])
    if v is None:
        return SIN_MEDIR, "Identidad no ha dado los conflictos de segregación.", {}
    datos = {"reglas": v.get("reglas"), "sin_exceptuar": v.get("sin_exceptuar", 0)}
    if not v.get("reglas"):
        return NO_CUMPLE, "No hay reglas de segregación de funciones.", datos
    if v.get("sin_exceptuar", 0):
        return (
            NO_CUMPLE,
            f"{v.get('sin_exceptuar')} conflictos de segregación sin resolver ni exceptuar.",
            datos,
        )
    return CUMPLE, f"{v.get('reglas')} reglas y ningún conflicto sin resolver.", datos


def _administrador_aparte(ctx: Contexto) -> Resultado:
    v = ctx.pedir("/api/v1/segregacion/violaciones", ["user:read"])
    reglas = ctx.pedir("/api/v1/segregacion/reglas", ["user:read"])
    if v is None or reglas is None:
        return SIN_MEDIR, "Identidad no ha dado las reglas de segregación.", {}
    # La regla que separa a quien da de alta usuarios de quien les da poderes.
    separa = [
        r["codigo"]
        for r in reglas
        if r.get("activa")
        and {"user:write", "role:write"} <= set(r.get("permisos_a", []) + r.get("permisos_b", []))
    ]
    if not separa:
        return (
            NO_CUMPLE,
            "No hay ninguna regla que separe dar de alta usuarios (user:write) "
            "de asignar roles (role:write).",
            {},
        )
    en_conflicto = [
        x for x in v.get("violaciones", []) if x.get("regla") in separa and not x.get("exceptuado")
    ]
    datos = {"reglas": separa, "en_conflicto": len(en_conflicto)}
    if en_conflicto:
        return (
            NO_CUMPLE,
            f"{len(en_conflicto)} personas administran usuarios y roles a la vez.",
            datos,
        )
    return CUMPLE, "Quien da de alta usuarios no les asigna roles.", datos


# ── Requisitos ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Requisito:
    clave: str
    nivel: str
    titulo: str
    exige: str
    comprobar: Callable[[Contexto], Resultado] | None = None  # None = se atestigua

    @property
    def control(self) -> str:
        return f"TCSEC-{self.clave}"


REQUISITOS: tuple[Requisito, ...] = (
    Requisito(
        "C1-IA",
        "C1",
        "Identificación y autenticación",
        "Cada persona entra con su cuenta y la contraseña no se puede probar sin límite.",
        _identificacion,
    ),
    Requisito(
        "C1-DAC",
        "C1",
        "Control de acceso discrecional",
        "Lo que cada uno puede hacer lo deciden sus roles.",
        _discrecional,
    ),
    Requisito(
        "C1-AISLA",
        "C1",
        "Separación entre empresas",
        "Una empresa no puede leer los datos de otra, ni por un error del código.",
        _aislamiento,
    ),
    Requisito(
        "C2-AUD",
        "C2",
        "Auditoría íntegra",
        "Queda registro de quién hizo qué, y no se puede alterar sin que se note.",
        _auditoria,
    ),
    Requisito(
        "C2-RESP",
        "C2",
        "Responsabilidad individual",
        "Cada acción se puede atribuir a una persona: segundo factor en las cuentas.",
        _segundo_factor,
    ),
    Requisito(
        "C2-REUSO",
        "C2",
        "Reutilización de objetos",
        "Lo que se borra no se puede recuperar después.",
        _reutilizacion,
    ),
    Requisito(
        "B1-ETIQ",
        "B1",
        "Etiquetas de sensibilidad",
        "Cada dato lleva su nivel de sensibilidad.",
        _etiquetas,
    ),
    Requisito(
        "B1-MAC-LEER",
        "B1",
        "Lectura obligatoria por etiqueta",
        "Nadie ve un dato por encima de su nivel, y no lo decide quien tiene el dato.",
        _lectura_por_etiqueta,
    ),
    Requisito(
        "B1-MAC-ESCRIBIR",
        "B1",
        "Escritura obligatoria por etiqueta",
        "Nadie puede copiar un dato a un sitio de nivel más bajo.",
        _escritura_por_etiqueta,
    ),
    Requisito(
        "B2-SOD",
        "B2",
        "Gestión de confianza de la instalación",
        "Funciones separadas: nadie concentra permisos incompatibles.",
        _segregacion,
    ),
    Requisito(
        "B2-CANALES",
        "B2",
        "Análisis de canales encubiertos",
        "Se han analizado las vías por las que un dato podría salir sin pasar por los controles.",
    ),
    Requisito(
        "B2-CONFIG",
        "B2",
        "Gestión de la configuración",
        "Cada cambio del sistema pasa por control de cambios y queda registrado.",
    ),
    Requisito(
        "B3-ADMIN",
        "B3",
        "Administrador de seguridad aparte",
        "Quien administra usuarios no es quien les da los permisos.",
        _administrador_aparte,
    ),
    Requisito(
        "B3-RECUP",
        "B3",
        "Recuperación de confianza",
        "Se ha probado restaurar el sistema tras un fallo sin perder la protección.",
    ),
    Requisito(
        "A1-VERIF",
        "A1",
        "Verificación formal del diseño",
        "El modelo de seguridad está especificado y verificado formalmente.",
    ),
)

_POR_CLAVE = {r.clave: r for r in REQUISITOS}


def _atestacion(ctx: Contexto, req: Requisito) -> Resultado:
    """La última evaluación del control del GRC, si sigue vigente."""
    from services.tenancy.grc import EvaluacionControl

    ultima = (
        ctx.db.execute(
            select(EvaluacionControl)
            .where(
                EvaluacionControl.tenant_id == ctx.tenant_id,
                EvaluacionControl.control_codigo == req.control,
            )
            .order_by(EvaluacionControl.fecha.desc(), EvaluacionControl.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if ultima is None:
        return NO_CUMPLE, "Nadie lo ha atestiguado todavía.", {"control": req.control}
    datos = {
        "control": req.control,
        "fecha": ultima.fecha.isoformat(),
        "resultado": ultima.resultado,
        "proxima_at": ultima.proxima_at.isoformat() if ultima.proxima_at else None,
        "evidencia": (ultima.evidencia or {}).get("texto", ""),
        "por": str(ultima.evaluado_por) if ultima.evaluado_por else None,
    }
    if ultima.proxima_at and ultima.proxima_at < hoy(ctx.db):
        return NO_CUMPLE, f"La atestación caducó el {ultima.proxima_at.isoformat()}.", datos
    if ultima.resultado != "efectivo":
        return (
            NO_CUMPLE,
            f"Atestiguado como «{ultima.resultado}»: {ultima.plan_accion}",
            datos,
        )
    return CUMPLE, f"Atestiguado el {ultima.fecha.isoformat()}.", datos


def requisito(clave: str) -> Requisito | None:
    return _POR_CLAVE.get(clave)


def medir_requisito(
    db: Session, tenant_id: UUID, principal_id: UUID, clave: str, cache: dict[str, Any]
) -> Resultado:
    """Mide un requisito automático, para dejarlo como evidencia en el GRC.

    Lo usa el control `TCSEC-<clave>` al evaluarse (CRM-07.03.02.14). La caché
    es la de la evaluación entera: los informes de cumplimiento de cada servicio
    sirven a varios requisitos y pedirlos una vez por requisito es pagar la
    verificación de todas las cadenas varias veces.
    """
    req = _POR_CLAVE.get(clave)
    if req is None or req.comprobar is None:
        return SIN_MEDIR, "Este requisito no se mide: se atestigua.", {}
    ctx = Contexto(db=db, tenant_id=tenant_id, principal_id=principal_id, _cache=cache)
    try:
        return req.comprobar(ctx)
    except Exception as exc:  # noqa: BLE001 — se dice, no se esconde
        logger.warning("tcsec.comprobacion_fallida", requisito=clave, error=str(exc))
        return SIN_MEDIR, f"La comprobación falló: {str(exc)[:200]}", {}


def evaluar(db: Session, tenant_id: UUID, principal_id: UUID) -> dict[str, Any]:
    """Cada requisito con su estado, y el nivel que alcanza la instalación."""
    ctx = Contexto(db=db, tenant_id=tenant_id, principal_id=principal_id, _cache={})
    requisitos: list[dict[str, Any]] = []
    for req in REQUISITOS:
        if req.comprobar is None:
            estado, detalle, datos = _atestacion(ctx, req)
            como = "atestiguado"
        else:
            try:
                estado, detalle, datos = req.comprobar(ctx)
            except Exception as exc:  # noqa: BLE001 — se dice, no se esconde
                logger.warning("tcsec.comprobacion_fallida", requisito=req.clave, error=str(exc))
                estado, detalle, datos = SIN_MEDIR, f"La comprobación falló: {str(exc)[:200]}", {}
            como = "automatico"
        requisitos.append(
            {
                "clave": req.clave,
                "nivel": req.nivel,
                "titulo": req.titulo,
                "exige": req.exige,
                "como": como,
                "estado": estado,
                "detalle": detalle,
                "datos": datos,
            }
        )

    alcanzado = "D"
    for nivel in NIVELES[1:]:
        if all(r["estado"] == CUMPLE for r in requisitos if r["nivel"] == nivel):
            alcanzado = nivel
        else:
            break
    siguiente = NIVELES[NIVELES.index(alcanzado) + 1] if alcanzado != NIVELES[-1] else None
    return {
        "generado_at": datetime.now(timezone.utc).isoformat(),
        "nivel": alcanzado,
        "nombre_nivel": NOMBRE_NIVEL[alcanzado],
        "siguiente": siguiente,
        "falta_para_el_siguiente": [
            r["clave"] for r in requisitos if r["nivel"] == siguiente and r["estado"] != CUMPLE
        ],
        "niveles": [{"nivel": n, "nombre": NOMBRE_NIVEL[n]} for n in NIVELES],
        "requisitos": requisitos,
    }


def atestiguar(
    db: Session,
    *,
    tenant_id: UUID,
    requisito: str,
    resultado: str,
    evidencia: str,
    plan_accion: str = "",
    por: UUID | None,
) -> dict[str, Any]:
    """Anota que una persona da fe de un requisito que no se puede medir.

    Va como evaluación de un control del GRC, que se crea la primera vez con el
    marco «TCSEC»: así hereda la frecuencia, la caducidad y la exigencia de
    plan de acción cuando el resultado no es «efectivo».
    """
    from crmcore.errors import ErrorValidacion

    from services.tenancy import grc

    req = _POR_CLAVE.get(requisito)
    if req is None:
        raise ErrorValidacion("Ese requisito no existe.", error_code="tcsec.requisito_desconocido")
    if req.comprobar is not None:
        # Lo que se mide no se atestigua: una persona diciendo «cumple» encima
        # de una medida que dice que no es justo lo que este informe evita.
        raise ErrorValidacion(
            "Este requisito se comprueba solo; no se atestigua.",
            error_code="tcsec.se_mide_solo",
        )
    if not evidencia.strip():
        raise ErrorValidacion(
            "Hace falta la evidencia: qué se revisó y dónde está.",
            error_code="tcsec.sin_evidencia",
        )
    existe = db.execute(
        select(grc.Control).where(
            grc.Control.tenant_id == tenant_id, grc.Control.codigo == req.control
        )
    ).scalar_one_or_none()
    if existe is None:
        nuevo = grc.guardar_control(
            db,
            tenant_id=tenant_id,
            codigo=req.control,
            nombre=f"TCSEC {req.nivel}: {req.titulo}",
            descripcion=req.exige,
            tipo="detectivo",
            frecuencia="anual",
            marcos=[{"marco": "TCSEC", "referencia": f"{req.nivel} {req.titulo}"}],
        )
        # Enlazado a su requisito, como los que instala el GRC de serie
        # (CRM-07.03.02.14): del control se vuelve a la pantalla TCSEC.
        nuevo.origen, nuevo.referencia = "tcsec", req.clave
    ev = grc.evaluar_control(
        db,
        tenant_id=tenant_id,
        control_codigo=req.control,
        resultado=resultado,
        evidencia={"texto": evidencia.strip(), "origen": "atestacion"},
        plan_accion=plan_accion,
        por=por,
    )
    return {
        "control": req.control,
        "resultado": ev.resultado,
        "proxima_at": ev.proxima_at.isoformat() if ev.proxima_at else None,
    }


ROTULO_ESTADO = {
    CUMPLE: "Cumple",
    NO_CUMPLE: "No cumple",
    SIN_MEDIR: "Sin medir",
    NO_IMPLEMENTADO: "No implementado",
}


def informe_markdown(evaluacion: dict[str, Any], empresa: str = "") -> str:
    """El informe para auditoría, en texto que se adjunta o se imprime."""
    lineas = ["# Clasificación TCSEC de la instalación", ""]
    if empresa:
        lineas.append(f"- **Empresa**: {empresa}")
    lineas += [
        f"- **Generado**: {evaluacion['generado_at']}",
        f"- **Nivel alcanzado**: {evaluacion['nivel']} — {evaluacion['nombre_nivel']}",
    ]
    if evaluacion.get("siguiente"):
        lineas.append(
            f"- **Para {evaluacion['siguiente']} falta**: "
            + (", ".join(evaluacion["falta_para_el_siguiente"]) or "nada")
        )
    lineas += [
        "",
        "Los requisitos automáticos se han medido sobre el sistema al generar "
        "este informe; los atestiguados, con la evidencia que escribió quien "
        "los evaluó. «Sin medir» significa que no se pudo comprobar, no que se cumpla.",
    ]
    for nivel in NIVELES[1:]:
        filas = [r for r in evaluacion["requisitos"] if r["nivel"] == nivel]
        if not filas:
            continue
        lineas += ["", f"## {nivel} — {NOMBRE_NIVEL[nivel]}", ""]
        lineas += ["| Requisito | Cómo | Estado | Detalle |", "|---|---|---|---|"]
        for r in filas:
            detalle = r["detalle"].replace("|", "/")
            evidencia = r["datos"].get("evidencia") if r["como"] == "atestiguado" else ""
            if evidencia:
                detalle += f" Evidencia: {str(evidencia).replace('|', '/')}"
            lineas.append(
                f"| {r['clave']} {r['titulo']} | "
                f"{'Medido' if r['como'] == 'automatico' else 'Atestiguado'} | "
                f"{ROTULO_ESTADO.get(r['estado'], r['estado'])} | {detalle} |"
            )
    return "\n".join(lineas) + "\n"
