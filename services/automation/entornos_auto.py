"""Probar y promocionar automatizaciones, y plantillas por industria
(CRM-00.03.03.08, CRM-00.03.03.09).

Una automatización se escribe en producción porque es donde están los datos de
verdad, y se prueba **activándola**. Eso funciona hasta el día en que la regla
que debía avisar a una persona manda cuatro mil correos, o la que debía cambiar
un campo lo cambia en veinte mil registros.

Lo que evita eso no es prohibir escribir en producción: es poder **ejecutarla
sobre datos reales sin que haga nada**, y ver qué habría hecho.

Las decisiones:

**La prueba en seco es contra datos de verdad.** Contra datos inventados, la
regla siempre funciona: los casos raros que la rompen son los que tiene el
cliente, no los que a uno se le ocurren.

**Y dice a CUÁNTOS habría afectado.** Es el número que para una mano: nadie
activa una regla cuando ve «afectaría a 19.480 registros» — y casi todo el mundo
la activa si solo ve «la regla es válida».

**Promocionar no copia el estado, copia la definición.** Lo que lleva dentro una
automatización en marcha —qué registros ya procesó, qué tiene pendiente— es de su
entorno. Copiarlo haría que la de producción creyera haber hecho ya el trabajo
que hizo la de pruebas.

**Y una plantilla llega apagada.** Una biblioteca que instala reglas activas es
una biblioteca que empieza a mandar correos en cuanto alguien la mira.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)


# Cuántos registros afectados hacen que la prueba exija confirmación aparte. No
# es un límite técnico: es el número a partir del cual un error deja de ser un
# error y pasa a ser un incidente que se cuenta a los clientes.
def _cambio_umbral_masivo() -> int:
    """Antes `_cambio_umbral_masivo() = 500`.

    Era una constante de módulo. Sale del `.env`, que es donde una instalación
    puede afinarla sin tocar código.
    """
    from crmcore.config import get_settings

    return get_settings().cambio_umbral_masivo


def probar_en_seco(
    *,
    nombre: str,
    afectados: list[dict[str, Any]],
    acciones: list[dict[str, Any]],
    limite_muestra: int = 20,
) -> dict[str, Any]:
    """Ejecuta la automatización **sin hacer nada** y cuenta qué habría hecho.

    Sobre datos reales: contra datos inventados la regla siempre funciona, porque
    los casos raros que la rompen son los que tiene el cliente y no los que a uno
    se le ocurren.

    Devuelve una **muestra** además del recuento. El número asusta; la muestra es
    lo que hace que alguien diga «espera, ese no debería estar ahí» — que es el
    momento en que la prueba en seco ha servido para algo.
    """
    if not acciones:
        raise ErrorValidacion(
            "Una automatización sin acciones no hace nada, ni en seco ni de verdad",
            error_code="automatizacion.sin_acciones",
        )

    total = len(afectados)
    envios = [a for a in acciones if str(a.get("tipo") or "") in ("notificar", "enviar_correo")]
    escrituras = [a for a in acciones if str(a.get("tipo") or "") in ("actualizar", "crear")]

    return {
        "automatizacion": nombre,
        "en_seco": True,
        # El número que para una mano. Nadie activa una regla cuando ve esto;
        # casi todo el mundo la activa si solo ve «la regla es válida».
        "afectaria_a": total,
        "muestra": [
            {"objeto": a.get("objeto"), "id": str(a.get("id") or ""), "porque": a.get("porque")}
            for a in afectados[:limite_muestra]
        ],
        "hay_mas": total > limite_muestra,
        # Las dos consecuencias que no se deshacen igual: un campo mal puesto se
        # arregla; cuatro mil correos enviados, no.
        "correos_que_saldrian": total * len(envios),
        "registros_que_cambiarian": total * len(escrituras),
        "es_masiva": total >= _cambio_umbral_masivo(),
        "aviso": (
            ""
            if total < _cambio_umbral_masivo()
            else f"Esto tocaría {total} registros. A partir de ahí, un error deja de "
            "ser un error y pasa a ser un incidente que hay que contarle a los "
            "clientes: activarla exige confirmarlo aparte."
        ),
        "porque_datos_reales": (
            "Se prueba contra los datos del tenant y no contra unos inventados: los "
            "casos raros que rompen una regla son los que tiene el cliente."
        ),
    }


def promocionar(
    *,
    definicion: dict[str, Any],
    desde: str,
    hacia: str,
    probada_en_seco: bool,
    afectados_en_pruebas: int = 0,
) -> dict[str, Any]:
    """Lleva una automatización de un entorno a otro (CRM-00.03.03.08).

    **Copia la definición, no el estado.** Lo que lleva dentro una automatización
    en marcha —qué registros ya procesó, qué tiene pendiente, cuándo se ejecutó
    por última vez— es de su entorno. Copiarlo haría que la de producción creyera
    haber hecho ya el trabajo que hizo la de pruebas, y se saltaría justo los
    registros que tenía que tocar.

    Y **llega apagada**. Una automatización que se enciende sola al promocionarse
    empieza a actuar sobre datos reales en el momento en que alguien pulsa
    «desplegar», que no es el momento en que alguien ha decidido que actúe.
    """
    if hacia == "produccion" and not probada_en_seco:
        raise Conflicto(
            "No se promociona a producción una automatización que no se ha probado "
            "en seco. La prueba cuesta un minuto; la regla que manda cuatro mil "
            "correos cuesta una semana de explicaciones.",
            error_code="automatizacion.sin_prueba",
        )

    limpia = {
        k: v
        for k, v in (definicion or {}).items()
        # El estado se queda: es del entorno de origen y no significa nada en el
        # destino.
        if k not in ("ultima_ejecucion", "procesados", "pendientes", "estado_interno")
    }
    return {
        "desde": desde,
        "hacia": hacia,
        "definicion": limpia,
        "llega_activa": False,
        "estado_descartado": sorted(set(definicion or {}) - set(limpia)),
        "porque_apagada": (
            "Una automatización que se enciende sola al promocionarse empieza a "
            "actuar en el momento en que alguien pulsa «desplegar», que no es el "
            "momento en que alguien ha decidido que actúe."
        ),
        "porque_sin_estado": (
            "Lo que ya procesó en pruebas no lo ha procesado en producción: "
            "copiarlo haría que se saltara justo los registros que tiene que tocar."
        ),
        "recordatorio": (
            f"En pruebas afectó a {afectados_en_pruebas} registros. En producción "
            "serán otros: conviene volver a probar en seco antes de encenderla."
            if afectados_en_pruebas
            else ""
        ),
    }


def instalar_plantilla(
    *,
    plantilla: dict[str, Any],
    existentes: list[str],
) -> dict[str, Any]:
    """Instala una plantilla de automatización por industria (CRM-00.03.03.09).

    **Todo llega apagado.** Una biblioteca que instala reglas activas es una
    biblioteca que empieza a mandar correos en cuanto alguien la mira por
    curiosidad — y la primera vez que eso pasa, nadie vuelve a abrir la
    biblioteca.

    Lo que ya existe **no se pisa**: se salta y se cuenta. Y se devuelve lo que
    la plantilla **da por supuesto** —que existe un campo, que hay un pipeline
    con ciertas etapas—, porque una regla que se apoya en algo que este tenant no
    tiene no falla al instalarse: falla la primera vez que se dispara, semanas
    después.
    """
    reglas = list(plantilla.get("reglas") or [])
    if not reglas:
        raise ErrorValidacion(
            "Una plantilla sin reglas no instala nada", error_code="plantilla.vacia"
        )

    ya = set(existentes)
    instaladas = [r for r in reglas if str(r.get("clave")) not in ya]
    saltadas = [str(r.get("clave")) for r in reglas if str(r.get("clave")) in ya]

    return {
        "plantilla": plantilla.get("clave"),
        "instaladas": [str(r.get("clave")) for r in instaladas],
        "saltadas": saltadas,
        "todas_apagadas": True,
        # Lo que la plantilla necesita y puede no estar. No falla al instalar:
        # falla la primera vez que se dispara, semanas después.
        "da_por_supuesto": list(plantilla.get("requiere") or []),
        "instalado_at": datetime.now(timezone.utc).isoformat(),
        "que_hacer_ahora": (
            "Probar cada una en seco y encenderlas de una en una. Encenderlas todas "
            "de golpe hace imposible saber cuál mandó el correo raro."
        ),
    }


# ── Lo que antes solo se calculaba, ahora se hace ─────────────────────────
#
# `promocionar` devolvía un JSON con la definición limpia y no guardaba nada en
# ningún sitio; `instalar_plantilla` contestaba «instaladas» sin crear ninguna.
# Las dos siguen arriba —son el cálculo— y lo de abajo es lo que las aplica.

# Lo que se copia de una regla al promoverla: su DEFINICIÓN. Ni contadores, ni
# fechas, ni la cola, ni el horario ya calculado: eso es de su entorno.
CAMPOS_DE_DEFINICION = (
    "descripcion",
    "disparador",
    "objetivo",
    "campos_vigilados",
    "programacion",
    "condiciones",
    "combinacion",
    "acciones",
    "prioridad",
    "momento",
)


def _definicion_de(regla: Any) -> dict[str, Any]:
    return {campo: getattr(regla, campo) for campo in CAMPOS_DE_DEFINICION}


def _sandbox(principal: Any, sandbox_id: Any) -> dict[str, Any]:
    """El sandbox, preguntado a `tenancy` **con los permisos de quien promueve**.

    Por HTTP y no leyendo su tabla: los sandboxes son de `tenancy`. Y con la
    identidad de quien llama, porque es lo que garantiza que el sandbox es de
    SU empresa —tenancy sólo enseña los propios— y que esa persona puede verlo.
    """
    from crmcore.errors import NoEncontrado
    from crmcore.http.interno import invocar

    respuesta = invocar(
        metodo="GET",
        ruta=f"/api/v1/sandboxes/{sandbox_id}",
        tenant_id=principal.tenant_id,
        principal_id=principal.id,
        permisos=sorted(principal.permisos),
        roles=sorted(principal.roles),
        tipo="usuario",
    )
    datos = respuesta.get("datos") or {}
    if respuesta.get("estado") != 200 or not datos.get("tenant_sandbox_id"):
        raise NoEncontrado(
            "Ese sandbox no existe en esta empresa o no tienes permiso para verlo",
            error_code="automatizacion.sandbox_no_encontrado",
            detalle={"respuesta": respuesta.get("estado")},
        )
    return datos


def plan_de_promocion(
    db: Any, *, origen: Any, destino: Any, nombres: list[str]
) -> list[dict[str, Any]]:
    """Qué pasaría en el destino con cada automatización del origen.

    Por **nombre**, que es lo que las identifica para una persona y lo que el
    destino tiene único: los identificadores cambian al copiar un sandbox, así
    que casar por identificador no encontraría nunca la de producción.
    """
    from crmcore.db.session import sesion
    from sqlalchemy import select

    from services.automation.modelos import Automatizacion

    with sesion(origen) as db_origen:
        consulta = select(Automatizacion).where(
            Automatizacion.tenant_id == origen, Automatizacion.deleted_at.is_(None)
        )
        if nombres:
            consulta = consulta.where(Automatizacion.nombre.in_(nombres))
        de_origen = {
            r.nombre: _definicion_de(r) for r in db_origen.execute(consulta).scalars().all()
        }
    faltan = sorted(set(nombres) - set(de_origen))
    if faltan:
        raise ErrorValidacion(
            "En el sandbox no hay automatizaciones con estos nombres: " + ", ".join(faltan),
            error_code="automatizacion.no_esta_en_origen",
            detalle={"faltan": faltan},
        )
    en_destino = {
        r.nombre: r
        for r in db.execute(
            select(Automatizacion).where(
                Automatizacion.tenant_id == destino,
                Automatizacion.nombre.in_(list(de_origen)),
            )
        )
        .scalars()
        .all()
    }
    from services.automation import validacion

    plan: list[dict[str, Any]] = []
    for nombre, definicion in sorted(de_origen.items()):
        actual = en_destino.get(nombre)
        if actual is None:
            accion, cambios = "crear", sorted(CAMPOS_DE_DEFINICION)
        else:
            cambios = [c for c in CAMPOS_DE_DEFINICION if getattr(actual, c) != definicion[c]]
            accion = "actualizar" if cambios or actual.deleted_at is not None else "sin_cambios"
        plan.append(
            {
                "nombre": nombre,
                "accion": accion,
                "cambios": cambios,
                # Lo que estaba encendido en producción y se va a apagar: es lo
                # que más sorprende después de promover, así que se dice antes.
                "se_apagara": bool(
                    actual is not None and actual.activa and accion != "sin_cambios"
                ),
                "problemas": validacion.problemas_de({**definicion, "nombre": nombre}),
                "_definicion": definicion,
            }
        )
    return plan


def _huella(plan: list[dict[str, Any]]) -> str:
    import hashlib
    import json

    material = json.dumps(
        [{k: v for k, v in p.items() if k != "problemas"} for p in plan],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def promover(
    uow: Any, principal: Any, *, sandbox_id: Any, nombres: list[str], huella: str
) -> dict[str, Any]:
    """Lleva automatizaciones de un sandbox a esta empresa (CRM-00.03.03.08).

    **Primero en seco, siempre.** Sin `huella` no se toca nada: se devuelve qué
    pasaría con cada una —crear, actualizar, sin cambios, cuáles se apagarían— y
    una huella de ese plan. Para aplicarlo se manda la misma huella, y si entre
    medias algo cambió en el sandbox o aquí, la huella ya no casa y no se aplica:
    lo que se confirma es lo que se vio.

    Lo que llega, **llega apagado** y sin su estado (ver `promocionar`), y cada
    una deja su apunte en la auditoría con de qué sandbox vino.
    """
    from crmcore.audit.chain import registrar
    from crmcore.errors import Conflicto
    from sqlalchemy import select

    from services.automation.modelos import Automatizacion

    sandbox = _sandbox(principal, sandbox_id)
    origen = sandbox["tenant_sandbox_id"]
    plan = plan_de_promocion(uow.db, origen=origen, destino=uow.tenant_id, nombres=nombres)
    calculada = _huella(plan)
    visible = [{k: v for k, v in p.items() if not k.startswith("_")} for p in plan]
    resumen = {
        "sandbox": sandbox.get("nombre") or str(sandbox_id),
        "estado_del_sandbox": sandbox.get("estado"),
        "plan": visible,
        "crearia": sum(1 for p in plan if p["accion"] == "crear"),
        "actualizaria": sum(1 for p in plan if p["accion"] == "actualizar"),
        "sin_cambios": sum(1 for p in plan if p["accion"] == "sin_cambios"),
    }
    if not huella:
        return {
            **resumen,
            "en_seco": True,
            "huella": calculada,
            "que_hacer_ahora": (
                "Revisa el plan. Para aplicarlo, vuelve a promover con esta huella: "
                "si algo cambia antes, la huella dejará de valer y no se aplicará nada."
            ),
        }
    if huella.strip() != calculada:
        raise Conflicto(
            "La prueba en seco ya no vale: algo ha cambiado en el sandbox o aquí desde "
            "que se hizo. Vuelve a probar en seco y confirma el plan nuevo.",
            error_code="automatizacion.huella_caducada",
        )
    con_problemas = [p for p in plan if p["problemas"] and p["accion"] != "sin_cambios"]
    if con_problemas:
        raise ErrorValidacion(
            "Hay automatizaciones que no podrían correr aquí: "
            + "; ".join(f"{p['nombre']}: {', '.join(p['problemas'])}" for p in con_problemas),
            error_code="automatizacion.no_valida",
        )

    aplicadas: list[dict[str, Any]] = []
    for paso in plan:
        if paso["accion"] == "sin_cambios":
            continue
        definicion = paso["_definicion"]
        regla = (
            uow.db.execute(
                select(Automatizacion).where(
                    Automatizacion.tenant_id == uow.tenant_id,
                    Automatizacion.nombre == paso["nombre"],
                )
            )
            .scalars()
            .first()
        )
        if regla is None:
            regla = Automatizacion(tenant_id=uow.tenant_id, nombre=paso["nombre"], **definicion)
            uow.db.add(regla)
        else:
            for campo, valor in definicion.items():
                setattr(regla, campo, valor)
            regla.deleted_at = None
        regla.activa = False
        # Llega apagada: la identidad de quien la activó en producción ya no
        # vale, la pondrá quien la vuelva a encender.
        regla.activada_por_id = None
        regla.activada_con = {}
        regla.proxima_ejecucion_at = None
        regla.proxima_segun = None
        uow.db.flush()
        registrar(
            uow.db,
            accion="automatizacion.promovida",
            objeto="automatizacion",
            objeto_id=regla.id,
            datos={
                "nombre": regla.nombre,
                "accion": paso["accion"],
                "cambios": paso["cambios"],
                "desde_sandbox": str(sandbox_id),
                "desde_tenant": str(origen),
            },
        )
        aplicadas.append({"nombre": regla.nombre, "accion": paso["accion"], "id": str(regla.id)})
    logger.info("automatizacion.promovidas", cuantas=len(aplicadas), sandbox=str(sandbox_id))
    return {
        **resumen,
        "en_seco": False,
        "aplicadas": aplicadas,
        "llegan_apagadas": True,
        "que_hacer_ahora": (
            "Llegan apagadas. Pruébalas con datos de aquí y enciéndelas de una en una."
        ),
    }


def instalar(
    uow: Any, *, clave: str, responsable_id: Any = None, nombre: str = ""
) -> dict[str, Any]:
    """Instala una plantilla de la biblioteca: crea la automatización, apagada.

    Lo que ya existe con ese nombre **no se pisa** —sería perder el trabajo de
    alguien sin preguntar—: se dice, y se puede instalar con otro nombre.
    """
    from crmcore.audit.chain import registrar
    from crmcore.errors import NoEncontrado
    from sqlalchemy import select

    from services.automation import plantillas, validacion
    from services.automation.modelos import Automatizacion

    plantilla = plantillas.POR_CLAVE.get(clave)
    if plantilla is None:
        raise NoEncontrado(
            f"No hay ninguna plantilla «{clave}»",
            error_code="plantilla.no_encontrada",
            detalle={"hay": list(plantillas.CLAVES)},
        )
    if plantilla.necesita_responsable and not responsable_id:
        raise ErrorValidacion(
            f"«{plantilla.nombre}» necesita saber a quién asignar o avisar: elige un responsable",
            error_code="plantilla.falta_responsable",
        )
    definicion = plantillas.definicion(
        plantilla, responsable=str(responsable_id) if responsable_id else None
    )
    if nombre.strip():
        definicion["nombre"] = nombre.strip()[:200]
    validacion.exigir(definicion, estricta=True)

    existente = (
        uow.db.execute(
            select(Automatizacion.id).where(
                Automatizacion.tenant_id == uow.tenant_id,
                Automatizacion.nombre == definicion["nombre"],
            )
        )
        .scalars()
        .first()
    )
    calculo = instalar_plantilla(
        plantilla={"clave": clave, "reglas": [{"clave": definicion["nombre"]}]},
        existentes=[definicion["nombre"]] if existente else [],
    )
    if not calculo["instaladas"]:
        raise Conflicto(
            f"Ya tienes una automatización llamada «{definicion['nombre']}». No se pisa: "
            "instálala con otro nombre si quieres las dos.",
            error_code="plantilla.ya_instalada",
            detalle={"automatizacion_id": str(existente)},
        )
    regla = Automatizacion(tenant_id=uow.tenant_id, **definicion)
    uow.db.add(regla)
    uow.db.flush()
    registrar(
        uow.db,
        accion="automatizacion.plantilla_instalada",
        objeto="automatizacion",
        objeto_id=regla.id,
        datos={"plantilla": clave, "nombre": regla.nombre},
    )
    return {
        "automatizacion_id": str(regla.id),
        "nombre": regla.nombre,
        "plantilla": clave,
        "activa": False,
        "da_por_supuesto": list(plantilla.requiere),
        "que_hacer_ahora": calculo["que_hacer_ahora"],
    }
