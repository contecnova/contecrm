"""Todo lo que hay en la aplicación, controlado por el GRC (CRM-07.03.02.12 a .15).

Pedido el 09-11-2026: «revisar que todo lo que hay en la aplicación esté
controlado por GRC; algo como el TCSEC y el DEM de Infor para controlar accesos,
todo ello enlazado con el GRC». Medido ese día en el tenant de plataforma: 0 de
781 capacidades hechas tenían control, la segregación no dejaba nada en el GRC
y del TCSEC sólo pasaban por él los cuatro requisitos que se atestiguan.

Aquí están las cuatro piezas que lo cierran, todas como **controles de serie**
—instalables, ajustables y desactivables por cada empresa— y todas con su
evidencia puesta por el sistema al evaluarse:

- **Uno por familia del catálogo** (CRM-XX.YY), anclado a sus capacidades
  hechas, con la fuente `trazabilidad`: la comprobación registrada de cada
  capacidad en el catálogo y la cadena de auditoría de los servicios que la
  sirven. Anclar no es comprobar: la cobertura cuenta aparte lo verificado.
- **Uno por regla de segregación**, preventivo, con su riesgo; cada conflicto
  sin excepción es un hallazgo, y cada excepción aprobada una evidencia que
  caduca cuando caduca la excepción.
- **Uno por requisito TCSEC**: los medidos dejan la medida como evidencia; los
  atestiguados siguen siendo de una persona.
- **El de la revisión periódica de accesos**: su evidencia es la última campaña
  cerrada, y cada campaña cerrada queda como evidencia con caducidad.

Ningún servicio importa a otro: lo de `identity` se pregunta por HTTP firmado
con la identidad de quien evalúa, y lo que no contesta se dice — un control
que no se pudo medir no se evalúa, porque una comprobación que no mira parece
verde.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion, NoDisponible, NoEncontrado
from crmcore.fechas import hoy
from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.tenancy import grc

logger = get_logger(__name__)

# Las fuentes de evidencia de los controles de serie. Las tres de antes
# (`audit_trail`, `politicas_abac`, `certificados_destruccion`) siguen en
# `grc._evidencia_automatica`.
FUENTES = ("trazabilidad", "segregacion", "tcsec", "recertificacion")
ORIGENES = ("familia", "segregacion", "tcsec", "recertificacion")

CAP_SERIE = "CRM-07.03.02.12"
CAP_SOD = "CRM-07.03.02.13"
CAP_TCSEC = "CRM-07.03.02.14"
CAP_REC = "CRM-07.03.02.15"
CAP_SOD_IDENTITY = "CRM-07.03.02.06"
CAP_TCSEC_PANTALLA = "CRM-07.03.02.11"
CONTROL_REC = "REC-ACCESOS"

# Lo que se pide a identity: leer reglas, conflictos y excepciones, y el
# resumen de las campañas de revisión de accesos.
_PERMISOS_IDENTITY = ["user:read", "role:read"]

# Marcos a los que responde cada clase de control de serie. Son referencias de
# ISO 27001:2022 que dicen lo mismo que el control: registro de actividad y
# gestión de cambios, segregación de funciones y derechos de acceso.
_MARCOS_FAMILIA = [
    {"marco": "ISO 27001", "referencia": "A.8.15"},
    {"marco": "ISO 27001", "referencia": "A.8.32"},
]
_MARCOS_SOD = [{"marco": "ISO 27001", "referencia": "A.5.3"}]
_MARCOS_REC = [{"marco": "ISO 27001", "referencia": "A.5.18"}]


# ── Utilidades ───────────────────────────────────────────────────────────


def _ajuste(clave: str, db: Session) -> Any:
    from crmcore.config import get_settings
    from crmcore.runtime.settings import efectivo

    return efectivo(clave, db, default=getattr(get_settings(), clave, None))


def _frecuencia_serie(db: Session) -> str:
    valor = str(_ajuste("grc_serie_frecuencia", db) or "trimestral")
    return valor if valor in grc.FRECUENCIAS else "trimestral"


def _servicios_desplegados() -> set[str]:
    from crmcore.config import get_settings
    from crmcore.rutas_de_api import cargar_destinos

    return set(cargar_destinos(get_settings().rutas_servicios))


def _pedir(
    cache: dict[str, Any],
    *,
    tenant_id: UUID,
    por: UUID | None,
    ruta: str,
    permisos: list[str],
    parametros: dict[str, Any] | None = None,
) -> Any:
    """GET firmado a otro servicio con la identidad de quien evalúa.

    None si no contesta o contesta un error, y se anota en la caché por qué:
    quien mide lo pone en la evidencia en vez de dar por vacío lo que no ha
    podido leer.
    """
    clave = ruta + "?" + "&".join(f"{k}={v}" for k, v in sorted((parametros or {}).items()))
    if clave in cache:
        return cache[clave]
    from crmcore.http.interno import invocar

    try:
        r = invocar(
            metodo="GET",
            ruta=ruta,
            parametros=parametros,
            tenant_id=tenant_id,
            principal_id=por,
            permisos=permisos,
        )
        datos = r["datos"] if r.get("estado") == 200 else None
        if datos is None:
            cache.setdefault("_fallos", {})[ruta] = f"contestó {r.get('estado')}"
    except Exception as exc:  # noqa: BLE001 — se dice en la evidencia
        logger.warning("grc_serie.no_contesta", ruta=ruta, error=str(exc)[:200])
        cache.setdefault("_fallos", {})[ruta] = str(exc)[:200]
        datos = None
    cache[clave] = datos
    return datos


def _control(db: Session, tenant_id: UUID, codigo: str) -> grc.Control | None:
    return db.execute(
        select(grc.Control).where(grc.Control.tenant_id == tenant_id, grc.Control.codigo == codigo)
    ).scalar_one_or_none()


def _guardar_de_serie(
    db: Session,
    tenant_id: UUID,
    *,
    codigo: str,
    origen: str,
    referencia: str,
    **campos: Any,
) -> str:
    """Crea o pone al día un control de serie. Devuelve qué ha pasado.

    El que la empresa ha ajustado no se pisa: reinstalar los de serie es para
    traer los nuevos y poner al día los que nadie ha tocado, no para deshacer
    lo que decidió el administrador —ni reactivar uno que desactivó—.
    """
    existente = _control(db, tenant_id, codigo)
    if existente is not None and existente.ajustado:
        return "respetado"
    activo = campos.pop("activo", True)
    fila = grc.guardar_control(db, tenant_id=tenant_id, codigo=codigo, activo=activo, **campos)
    fila.origen, fila.referencia = origen, referencia
    return "creado" if existente is None else "actualizado"


def _guardar_evidencia(
    db: Session,
    tenant_id: UUID,
    *,
    control: str,
    origen: str,
    referencia: str,
    descripcion: str,
    datos: dict[str, Any],
    caduca_at: date | None,
) -> grc.Evidencia:
    fila = db.execute(
        select(grc.Evidencia).where(
            grc.Evidencia.tenant_id == tenant_id,
            grc.Evidencia.origen == origen,
            grc.Evidencia.referencia == referencia,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = grc.Evidencia(tenant_id=tenant_id, origen=origen, referencia=referencia)
        db.add(fila)
    fila.control_codigo = control
    fila.descripcion = descripcion
    fila.datos = datos
    fila.caduca_at = caduca_at
    return fila


# ── Familias del catálogo (CRM-07.03.02.12) ───────────────────────────────


def familias() -> dict[str, dict[str, Any]]:
    """Cada familia CRM-XX.YY con sus capacidades hechas."""
    from crmcore.catalogo import capacidades

    salida: dict[str, dict[str, Any]] = {}
    for cid, cap in capacidades().items():
        if cap["estado"] != "hecho":
            continue
        familia = cid[:9]
        fila = salida.setdefault(familia, {"nombre": cap["seccion"], "capacidades": []})
        fila["capacidades"].append(cid)
    for fila in salida.values():
        fila["capacidades"].sort()
    return dict(sorted(salida.items()))


def codigo_de_familia(familia: str) -> str:
    return f"FAM-{familia.removeprefix('CRM-')}"


def _medir_trazabilidad(
    db: Session, tenant_id: UUID, control: grc.Control, por: UUID | None, cache: dict[str, Any]
) -> dict[str, Any]:
    """La comprobación registrada de cada capacidad y la cadena de sus servicios.

    Dos pruebas que ya genera el sistema: el `visto` del catálogo —cuándo y
    cómo se comprobó cada capacidad— y la integridad de la cadena de auditoría
    de cada servicio que las sirve. Lo que no es un servicio desplegado (la
    librería común, el front, la documentación) sólo tiene la primera, y se
    dice.
    """
    from crmcore.catalogo import capacidades

    catalogo = capacidades()
    caps = [catalogo[c] for c in (control.capacidades or []) if c in catalogo]
    sin_visto = sorted(c["id"] for c in caps if not c.get("visto"))
    fechas = sorted(c["visto"][:10] for c in caps if c.get("visto", "")[:4].isdigit())
    desplegados = _servicios_desplegados()
    servicios = sorted({c["servicio"] for c in caps if c["servicio"] in desplegados})

    cadenas: dict[str, dict[str, Any]] = {}
    sin_respuesta: list[str] = []
    rotas: list[str] = []
    apuntes = 0
    for servicio in servicios:
        informe = _pedir(
            cache,
            tenant_id=tenant_id,
            por=por,
            ruta=f"/api/v1/{servicio}/cumplimiento/informe",
            permisos=["cumplimiento:leer"],
        )
        v = ((informe or {}).get("integridad_del_audit_trail") or {}).get("verificacion") or {}
        if not v:
            sin_respuesta.append(servicio)
            continue
        cadenas[servicio] = {
            "apuntes": int(v.get("apuntes") or 0),
            "intacta": bool(v.get("intacta")),
            "rota_en": v.get("rota_en"),
        }
        apuntes += cadenas[servicio]["apuntes"]
        if not v.get("intacta"):
            rotas.append(f"{servicio} (apunte {v.get('rota_en')})")

    # Capacidad a capacidad: comprobada en el catálogo y con la cadena de su
    # servicio intacta (o sin servicio propio). Es lo que la cobertura cuenta
    # como verificado aunque el control entero salga «parcial»: que falte el
    # recorrido de dieciséis no quita que las otras ocho estén comprobadas.
    bien = set(cadenas) - {r.split(" ")[0] for r in rotas}
    verificadas = sorted(
        c["id"]
        for c in caps
        if c.get("visto") and (c["servicio"] not in desplegados or c["servicio"] in bien)
    )
    evidencia = {
        "fuente": "trazabilidad",
        "capacidades": len(caps),
        "capacidades_verificadas": verificadas,
        "comprobadas_en_catalogo": len(caps) - len(sin_visto),
        "sin_comprobacion": sin_visto[:50],
        "ultima_comprobacion": fechas[-1] if fechas else None,
        "servicios": cadenas,
        "apuntes_verificados": apuntes,
        "sin_respuesta": sin_respuesta,
        "solo_catalogo": not servicios,
    }
    if not caps:
        return {
            "resultado": "inefectivo",
            "evidencia": evidencia,
            "plan": "El control no se ancla a ninguna capacidad del catálogo: no prueba nada.",
        }
    if rotas:
        return {
            "resultado": "inefectivo",
            "evidencia": evidencia,
            "plan": "Cadena de auditoría alterada en " + ", ".join(rotas) + ": investigar "
            "qué apunte se tocó y desde cuándo.",
        }
    faltas: list[str] = []
    if sin_respuesta:
        faltas.append("no se pudo verificar la cadena de " + ", ".join(sin_respuesta))
    if sin_visto:
        faltas.append(f"{len(sin_visto)} capacidades sin comprobación registrada en el catálogo")
    if servicios and not sin_respuesta and apuntes == 0:
        faltas.append("no hay ningún apunte de auditoría que verificar en sus servicios")
    if faltas:
        return {
            "resultado": "parcial",
            "evidencia": evidencia,
            "plan": "Falta: " + "; ".join(faltas) + ".",
        }
    return {"resultado": "efectivo", "evidencia": evidencia, "plan": ""}


# ── Segregación de funciones (CRM-07.03.02.13) ────────────────────────────


def codigo_de_regla(regla: str) -> str:
    return (regla if regla.startswith("SOD-") else f"SOD-{regla}")[:40]


def _riesgo_de_regla(control: str) -> str:
    return f"R-{control}"[:40]


def _leer_segregacion(
    cache: dict[str, Any], tenant_id: UUID, por: UUID | None
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    reglas = _pedir(
        cache,
        tenant_id=tenant_id,
        por=por,
        ruta="/api/v1/segregacion/reglas",
        permisos=_PERMISOS_IDENTITY,
    )
    violaciones = _pedir(
        cache,
        tenant_id=tenant_id,
        por=por,
        ruta="/api/v1/segregacion/violaciones",
        permisos=_PERMISOS_IDENTITY,
    )
    excepciones = _pedir(
        cache,
        tenant_id=tenant_id,
        por=por,
        ruta="/api/v1/segregacion/excepciones",
        permisos=_PERMISOS_IDENTITY,
        parametros={"incluir_caducadas": "true"},
    )
    if reglas is None or violaciones is None or excepciones is None:
        raise NoDisponible(
            "Identidad no ha contestado: la segregación no se ha podido llevar al GRC",
            error_code="grc.segregacion_sin_respuesta",
            detalle={"fallos": cache.get("_fallos", {})},
        )
    return list(reglas), dict(violaciones), list(excepciones)


def _nombres(cache: dict[str, Any], tenant_id: UUID, por: UUID | None) -> dict[str, str]:
    datos = _pedir(
        cache,
        tenant_id=tenant_id,
        por=por,
        ruta="/api/v1/usuarios",
        permisos=["user:read"],
        parametros={"limite": 200},
    )
    filas = (datos or {}).get("items", []) if isinstance(datos, dict) else (datos or [])
    return {str(f.get("id")): f.get("nombre") or f.get("email") or "" for f in filas}


def sincronizar_segregacion(
    db: Session, tenant_id: UUID, por: UUID | None, cache: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Lleva la segregación de identity al GRC: controles, riesgos, hallazgos y evidencias.

    - **Cada regla, un control preventivo** con su riesgo. Una regla apagada
      deja su control inactivo; una que ya no existe, también.
    - **Cada conflicto sin excepción, un hallazgo abierto** contra ese riesgo.
      Cuando deja de verse se cierra diciendo por qué: resuelto o exceptuado.
    - **Cada excepción aprobada, una evidencia** que caduca el día que caduca
      la excepción.

    Se puede repetir: deja el mismo estado.
    """
    cache = {} if cache is None else cache
    reglas, violaciones, excepciones = _leer_segregacion(cache, tenant_id, por)
    nombres = _nombres(cache, tenant_id, por)
    por_nivel = _ajuste("grc_sod_riesgo_por_nivel", db) or {}
    frecuencia = _frecuencia_serie(db)

    control_de: dict[str, str] = {}
    controles = {"creado": 0, "actualizado": 0, "respetado": 0}
    for regla in reglas:
        codigo = codigo_de_regla(regla["codigo"])
        control_de[regla["codigo"]] = codigo
        riesgo = _riesgo_de_regla(codigo)
        existe_riesgo = db.execute(
            select(grc.Riesgo.id).where(
                grc.Riesgo.tenant_id == tenant_id, grc.Riesgo.codigo == riesgo
            )
        ).first()
        if existe_riesgo is None:
            # El riesgo se registra una vez y luego es de la empresa: si lo
            # reevalúa, la siguiente sincronización no le devuelve los números
            # de fábrica.
            prob, imp = (list(por_nivel.get(regla.get("nivel"), [3, 3])) + [3, 3])[:2]
            grc.guardar_riesgo(
                db,
                tenant_id=tenant_id,
                codigo=riesgo,
                titulo=f"Una persona concentra «{regla['nombre']}»",
                descripcion=regla.get("descripcion", ""),
                categoria="segregacion",
                probabilidad=int(prob),
                impacto=int(imp),
            )
        estado = _guardar_de_serie(
            db,
            tenant_id,
            codigo=codigo,
            origen="segregacion",
            referencia=regla["codigo"],
            nombre=f"Segregación: {regla['nombre']}",
            descripcion=regla.get("descripcion", ""),
            tipo="preventivo",
            automatico=True,
            frecuencia=frecuencia,
            activo=bool(regla.get("activa", True)),
            capacidades=[CAP_SOD_IDENTITY, CAP_SOD],
            riesgos=[riesgo],
            marcos=_MARCOS_SOD,
            fuente_evidencia="segregacion",
        )
        controles[estado] += 1

    # Las reglas que ya no están en identity dejan su control inactivo: un
    # control activo sobre una regla borrada saldría evaluado sin mirar nada.
    retirados = 0
    for fila in (
        db.execute(
            select(grc.Control).where(
                grc.Control.tenant_id == tenant_id,
                grc.Control.origen == "segregacion",
                grc.Control.activo.is_(True),
            )
        )
        .scalars()
        .all()
    ):
        if fila.referencia not in control_de and not fila.ajustado:
            fila.activo = False
            retirados += 1

    # ── Hallazgos ──
    exceptuados = {
        (v["regla"], v["usuario_id"])
        for v in violaciones.get("violaciones", [])
        if v.get("exceptuado")
    }
    actuales: dict[str, dict[str, Any]] = {}
    for v in violaciones.get("violaciones", []):
        if v.get("exceptuado") or v["regla"] not in control_de:
            continue
        control = control_de[v["regla"]]
        actuales[f"{control}:{v['usuario_id']}"] = {**v, "control": control}

    abiertos = cerrados = 0
    existentes = {
        h.codigo: h
        for h in db.execute(
            select(grc.Hallazgo).where(
                grc.Hallazgo.tenant_id == tenant_id, grc.Hallazgo.origen == "segregacion"
            )
        ).scalars()
    }
    ahora = datetime.now(timezone.utc)
    for codigo, h in existentes.items():
        if h.estado == "abierto" and codigo not in actuales:
            h.estado = "cerrado"
            h.cerrado_at = ahora
            h.motivo_cierre = (
                "exceptuado" if (h.referencia, str(h.sujeto_id)) in exceptuados else "resuelto"
            )
            cerrados += 1
    for codigo, v in actuales.items():
        h = existentes.get(codigo)
        if h is None:
            h = grc.Hallazgo(
                tenant_id=tenant_id,
                codigo=codigo,
                origen="segregacion",
                sujeto_id=UUID(v["usuario_id"]),
            )
            db.add(h)
        elif h.estado != "abierto":
            # Vuelve a verse: se reabre el mismo, con fecha nueva, para que el
            # historial diga que se cerró y volvió.
            h.detectado_at = ahora
        persona = nombres.get(v["usuario_id"]) or f"{v['usuario_id'][:8]}…"
        h.control_codigo = v["control"]
        h.referencia = v["regla"]
        h.titulo = f"{persona} tiene los dos lados de «{v['nombre']}»"
        h.detalle = {
            "nivel": v.get("nivel"),
            "por_el_lado_a": v.get("por_el_lado_a", []),
            "por_el_lado_b": v.get("por_el_lado_b", []),
        }
        h.riesgo_codigo = _riesgo_de_regla(v["control"])
        h.estado = "abierto"
        h.cerrado_at = None
        h.motivo_cierre = ""
        abiertos += 1

    # ── Evidencias: cada excepción aprobada, con su caducidad ──
    evidencias = 0
    for e in excepciones:
        control = control_de.get(e["regla_codigo"])
        if control is None:
            continue
        persona = nombres.get(e["usuario_id"]) or f"{e['usuario_id'][:8]}…"
        _guardar_evidencia(
            db,
            tenant_id,
            control=control,
            origen="segregacion",
            referencia=e["id"],
            descripcion=f"Excepción aprobada para {persona}: {e['motivo']}",
            datos={
                "regla": e["regla_codigo"],
                "usuario_id": e["usuario_id"],
                "aprobada_por": e.get("aprobada_por"),
                "motivo": e["motivo"],
            },
            caduca_at=date.fromisoformat(e["caduca_at"][:10]),
        )
        evidencias += 1
    db.flush()
    logger.info(
        "grc_serie.segregacion_sincronizada",
        reglas=len(reglas),
        hallazgos_abiertos=abiertos,
        cerrados=cerrados,
    )
    return {
        "reglas": len(reglas),
        "controles": controles,
        "controles_retirados": retirados,
        "hallazgos_abiertos": abiertos,
        "hallazgos_cerrados": cerrados,
        "evidencias": evidencias,
    }


def _medir_segregacion(
    db: Session, tenant_id: UUID, control: grc.Control, por: UUID | None, cache: dict[str, Any]
) -> dict[str, Any]:
    try:
        if not cache.get("_segregacion_sincronizada"):
            # Al evaluar se trae lo de hoy: los hallazgos y las evidencias que
            # salen son los de este momento, no los de la última sincronización.
            sincronizar_segregacion(db, tenant_id, por, cache)
            cache["_segregacion_sincronizada"] = True
        reglas, violaciones, excepciones = _leer_segregacion(cache, tenant_id, por)
    except NoDisponible as exc:
        return {
            "resultado": None,
            "evidencia": {"fuente": "segregacion", "error": exc.mensaje},
            "plan": "",
        }
    regla = control.referencia
    if not any(r["codigo"] == regla for r in reglas):
        return {
            "resultado": None,
            "evidencia": {
                "fuente": "segregacion",
                "error": f"La regla {regla} ya no existe en identidad",
            },
            "plan": "",
        }
    suyas = [v for v in violaciones.get("violaciones", []) if v["regla"] == regla]
    sin_exceptuar = [v for v in suyas if not v.get("exceptuado")]
    dia = hoy(db).isoformat()
    vigentes = [e for e in excepciones if e["regla_codigo"] == regla and e["caduca_at"] >= dia]
    evidencia = {
        "fuente": "segregacion",
        "regla": regla,
        "conflictos": len(suyas),
        "sin_exceptuar": len(sin_exceptuar),
        "excepciones_vigentes": [
            {"usuario_id": e["usuario_id"], "caduca_at": e["caduca_at"], "motivo": e["motivo"]}
            for e in vigentes
        ],
        "excepciones_caducadas": sum(
            1 for e in excepciones if e["regla_codigo"] == regla and e["caduca_at"] < dia
        ),
    }
    if sin_exceptuar:
        return {
            "resultado": "inefectivo",
            "evidencia": evidencia,
            "plan": f"{len(sin_exceptuar)} personas tienen los dos lados sin excepción: "
            "quitarles uno de los dos, o aprobar la excepción con motivo y caducidad.",
        }
    return {"resultado": "efectivo", "evidencia": evidencia, "plan": ""}


# ── TCSEC (CRM-07.03.02.14) ───────────────────────────────────────────────


def _medir_tcsec(
    db: Session, tenant_id: UUID, control: grc.Control, por: UUID | None, cache: dict[str, Any]
) -> dict[str, Any]:
    from services.tenancy import tcsec

    clave = control.referencia
    estado, detalle, datos = tcsec.medir_requisito(
        db, tenant_id, por, clave, cache.setdefault("_tcsec", {})
    )
    evidencia = {
        "fuente": "tcsec",
        "requisito": clave,
        "estado": estado,
        "detalle": detalle,
        "datos": datos,
    }
    if estado == tcsec.CUMPLE:
        return {"resultado": "efectivo", "evidencia": evidencia, "plan": ""}
    if estado == tcsec.SIN_MEDIR:
        # Lo que no se ha podido medir no se evalúa: ni efectivo, que mentiría
        # a favor, ni inefectivo, que diría que se miró y falló.
        return {"resultado": None, "evidencia": {**evidencia, "error": detalle}, "plan": ""}
    return {"resultado": "inefectivo", "evidencia": evidencia, "plan": detalle}


# ── Revisión periódica de accesos (CRM-07.03.02.15) ───────────────────────


def _medir_recertificacion(
    db: Session, tenant_id: UUID, control: grc.Control, por: UUID | None, cache: dict[str, Any]
) -> dict[str, Any]:
    resumen = _pedir(
        cache,
        tenant_id=tenant_id,
        por=por,
        ruta="/api/v1/recertificacion/resumen",
        permisos=["user:read"],
    )
    if resumen is None:
        return {
            "resultado": None,
            "evidencia": {
                "fuente": "recertificacion",
                "error": "Identidad no ha dado el resumen de las campañas",
            },
            "plan": "",
        }
    dias = grc.DIAS_FRECUENCIA.get(control.frecuencia, 91)
    # Cada campaña cerrada es una evidencia que vale hasta que toca la
    # siguiente: pasada esa fecha, ya no prueba que los accesos estén revisados.
    for c in resumen.get("cerradas", []):
        cerrada = date.fromisoformat(c["cerrada_at"][:10])
        _guardar_evidencia(
            db,
            tenant_id,
            control=control.codigo,
            origen="recertificacion",
            referencia=c["id"],
            descripcion=(
                f"Campaña «{c['nombre']}» cerrada: {c['confirmados']} confirmados, "
                f"{c['retirados']} retirados, {c['vencidas']} sin contestar a tiempo"
            ),
            datos={k: c.get(k) for k in ("total", "confirmados", "retirados", "vencidas")},
            caduca_at=cerrada + timedelta(days=dias),
        )
    ultima = resumen.get("ultima_cerrada")
    evidencia = {
        "fuente": "recertificacion",
        "ultima_cerrada": ultima,
        "en_curso": resumen.get("en_curso", []),
        "ventana_dias": dias,
    }
    limite = hoy(db) - timedelta(days=dias)
    if not ultima or date.fromisoformat(ultima["cerrada_at"][:10]) < limite:
        return {
            "resultado": "inefectivo",
            "evidencia": evidencia,
            "plan": f"No hay ninguna campaña de revisión de accesos cerrada en los últimos "
            f"{dias} días: lanzar una desde Revisión de accesos.",
        }
    if ultima.get("vencidas"):
        return {
            "resultado": "parcial",
            "evidencia": evidencia,
            "plan": f"{ultima['vencidas']} revisiones quedaron sin contestar en plazo: "
            "pedir a sus responsables que las contesten en la próxima campaña.",
        }
    return {"resultado": "efectivo", "evidencia": evidencia, "plan": ""}


# ── Medir y evaluar ───────────────────────────────────────────────────────


_MEDIDORES = {
    "trazabilidad": _medir_trazabilidad,
    "segregacion": _medir_segregacion,
    "tcsec": _medir_tcsec,
    "recertificacion": _medir_recertificacion,
}


def medir(
    db: Session,
    tenant_id: UUID,
    control: grc.Control,
    *,
    por: UUID | None,
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`{resultado, evidencia, plan}` del control, leídos de su fuente.

    `resultado` es None cuando la fuente no se ha podido leer: entonces no hay
    evaluación, y la evidencia dice por qué.
    """
    cache = {} if cache is None else cache
    fuente = control.fuente_evidencia
    medidor = _MEDIDORES.get(fuente)
    if medidor is not None:
        return medidor(db, tenant_id, control, por, cache)
    # Las fuentes de antes: cuentan algo, y contar cero es que no hay prueba.
    evidencia = grc._evidencia_automatica(db, tenant_id, control, por=por)
    if not evidencia or "error" in evidencia:
        return {"resultado": None, "evidencia": evidencia, "plan": ""}
    cifras = [v for k, v in evidencia.items() if k != "fuente" and isinstance(v, int)]
    if cifras and cifras[0] > 0:
        return {"resultado": "efectivo", "evidencia": evidencia, "plan": ""}
    return {
        "resultado": "inefectivo",
        "evidencia": evidencia,
        "plan": "La fuente de evidencia no tiene nada que probar todavía.",
    }


def _poner_al_dia_familia(control: grc.Control) -> None:
    """La familia crece con el producto: sus capacidades hechas de hoy."""
    if control.origen != "familia" or control.ajustado:
        return
    actuales = familias().get(control.referencia, {}).get("capacidades")
    if actuales and actuales != list(control.capacidades or []):
        control.capacidades = actuales


def evaluar_automatico(
    db: Session,
    tenant_id: UUID,
    codigo: str,
    *,
    por: UUID | None,
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evalúa un control con su fuente: la evidencia y el resultado los pone el sistema."""
    control = _control(db, tenant_id, codigo)
    if control is None:
        raise NoEncontrado("Ese control no existe", error_code="grc.control_no_existe")
    if not control.fuente_evidencia:
        raise ErrorValidacion(
            "Este control no tiene fuente de evidencia: lo evalúa una persona.",
            error_code="grc.sin_fuente",
        )
    _poner_al_dia_familia(control)
    medida = medir(db, tenant_id, control, por=por, cache=cache)
    if medida["resultado"] is None:
        motivo = medida["evidencia"].get("error") or "La fuente no se ha podido leer."
        return {"control": codigo, "evaluado": False, "motivo": motivo}
    fila = grc.evaluar_control(
        db,
        tenant_id=tenant_id,
        control_codigo=codigo,
        resultado=medida["resultado"],
        evidencia=medida["evidencia"],
        plan_accion=medida["plan"],
        observaciones="Evaluado por el sistema con su fuente de evidencia.",
        por=por,
    )
    return {
        "control": codigo,
        "evaluado": True,
        "resultado": fila.resultado,
        "evidencia": fila.evidencia,
        "plan_accion": fila.plan_accion,
        "proxima_at": fila.proxima_at.isoformat() if fila.proxima_at else None,
    }


def evaluar_automaticos(
    db: Session, tenant_id: UUID, *, por: UUID | None, origen: str = ""
) -> dict[str, Any]:
    """Todos los controles activos con fuente de evidencia, de una vez.

    Cada uno en su SAVEPOINT: uno que revienta deja su motivo y no se lleva a
    los demás por delante. Y con una caché común: el informe de cumplimiento de
    cada servicio se pide una vez, no una por familia.
    """
    consulta = select(grc.Control).where(
        grc.Control.tenant_id == tenant_id,
        grc.Control.activo.is_(True),
        grc.Control.fuente_evidencia != "",
    )
    if origen:
        consulta = consulta.where(grc.Control.origen == origen)
    codigos = [c.codigo for c in db.execute(consulta.order_by(grc.Control.codigo)).scalars()]
    cache: dict[str, Any] = {}
    resultados: list[dict[str, Any]] = []
    for codigo in codigos:
        punto = db.begin_nested()
        try:
            resultados.append(evaluar_automatico(db, tenant_id, codigo, por=por, cache=cache))
            punto.commit()
        except Exception as exc:  # noqa: BLE001 — se dice cuál y por qué
            punto.rollback()
            logger.warning("grc_serie.evaluacion_fallida", control=codigo, error=str(exc)[:200])
            resultados.append({"control": codigo, "evaluado": False, "motivo": str(exc)[:200]})
    por_resultado: dict[str, int] = {}
    for r in resultados:
        clave = r.get("resultado") if r.get("evaluado") else "sin_evaluar"
        por_resultado[clave] = por_resultado.get(clave, 0) + 1
    return {
        "controles": len(codigos),
        "por_resultado": por_resultado,
        "resultados": resultados,
    }


# ── Instalar los de serie ─────────────────────────────────────────────────


def instalar_de_serie(db: Session, tenant_id: UUID, *, por: UUID | None) -> dict[str, Any]:
    """Instala o pone al día los controles de serie de este tenant.

    Se puede repetir: trae los nuevos —una familia que estrena capacidad hecha,
    una regla de segregación nueva— y no toca los que la empresa ha ajustado.
    """
    from services.tenancy import tcsec

    frecuencia = _frecuencia_serie(db)
    cuenta: dict[str, dict[str, int]] = {}

    def anotar(clase: str, estado: str) -> None:
        fila = cuenta.setdefault(clase, {"creado": 0, "actualizado": 0, "respetado": 0})
        fila[estado] += 1

    for familia, datos in familias().items():
        anotar(
            "familia",
            _guardar_de_serie(
                db,
                tenant_id,
                codigo=codigo_de_familia(familia),
                origen="familia",
                referencia=familia,
                nombre=f"Trazabilidad de {datos['nombre']}",
                descripcion=(
                    "Cada capacidad hecha de la familia tiene su comprobación registrada en "
                    "el catálogo, y cada cambio en los servicios que la sirven deja un apunte "
                    "encadenado que no se puede alterar sin que se note."
                ),
                tipo="detectivo",
                automatico=True,
                frecuencia=frecuencia,
                capacidades=datos["capacidades"],
                marcos=_MARCOS_FAMILIA,
                fuente_evidencia="trazabilidad",
            ),
        )

    for req in tcsec.REQUISITOS:
        medido = req.comprobar is not None
        anotar(
            "tcsec",
            _guardar_de_serie(
                db,
                tenant_id,
                codigo=req.control,
                origen="tcsec",
                referencia=req.clave,
                nombre=f"TCSEC {req.nivel}: {req.titulo}",
                descripcion=req.exige,
                tipo="detectivo",
                automatico=medido,
                # Lo atestiguado vale un año, como hasta ahora; lo medido, lo
                # que diga la frecuencia de los de serie.
                frecuencia=frecuencia if medido else "anual",
                capacidades=[CAP_TCSEC_PANTALLA, CAP_TCSEC],
                marcos=[{"marco": "TCSEC", "referencia": f"{req.nivel} {req.titulo}"}],
                fuente_evidencia="tcsec" if medido else "",
            ),
        )

    rec_frecuencia = str(_ajuste("recertificacion_frecuencia", db) or "trimestral")
    anotar(
        "recertificacion",
        _guardar_de_serie(
            db,
            tenant_id,
            codigo=CONTROL_REC,
            origen="recertificacion",
            referencia="",
            nombre="Revisión periódica de accesos",
            descripcion=(
                "Cada responsable confirma o retira los accesos de su gente en una campaña "
                "con plazo; lo retirado se quita de verdad y lo no contestado se marca."
            ),
            tipo="detectivo",
            automatico=True,
            frecuencia=rec_frecuencia if rec_frecuencia in grc.FRECUENCIAS else "trimestral",
            capacidades=[CAP_REC],
            marcos=_MARCOS_REC,
            fuente_evidencia="recertificacion",
        ),
    )

    try:
        segregacion = sincronizar_segregacion(db, tenant_id, por)
    except NoDisponible as exc:
        # La segregación vive en identity: si no contesta, lo demás se instala
        # igual y se dice que esta parte falta.
        segregacion = {"error": exc.mensaje}
    db.flush()
    logger.info("grc_serie.instalados", cuenta=cuenta)
    return {"controles": cuenta, "segregacion": segregacion}


def estado_de_serie(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Qué controles de serie hay en este tenant y cuáles faltan por instalar."""
    from services.tenancy import tcsec

    tiene = {
        c.codigo: c
        for c in db.execute(
            select(grc.Control).where(grc.Control.tenant_id == tenant_id, grc.Control.origen != "")
        ).scalars()
    }
    esperados = (
        [codigo_de_familia(f) for f in familias()]
        + [r.control for r in tcsec.REQUISITOS]
        + [CONTROL_REC]
    )
    return {
        "esperados": len(esperados),
        "instalados": sum(1 for c in esperados if c in tiene),
        "faltan": [c for c in esperados if c not in tiene],
        "ajustados": sorted(c.codigo for c in tiene.values() if c.ajustado),
        "inactivos": sorted(c.codigo for c in tiene.values() if not c.activo),
        "por_origen": {o: sum(1 for c in tiene.values() if c.origen == o) for o in ORIGENES},
    }
