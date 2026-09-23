"""API del motor de procesos."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from crmcore.http.listados import montar_ficha
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.orchestrator import motor as mtr
from services.orchestrator.esquemas import (
    ArrancarProceso,
    CambioDeEstado,
    DefinicionOut,
    EditarVariables,
    InstanciaOut,
    PasoOut,
    PublicarDefinicion,
    ResponderTarea,
    SimularProceso,
    TablaEditada,
    TareaOut,
)
from services.orchestrator.modelos import (
    DefinicionProceso,
    InstanciaProceso,
    PasoEjecutado,
    TareaHumana,
)


class DelegarTarea(BaseModel):
    """En quién se delega, por cuerpo y no por query.

    Por cuerpo por dos razones: el formulario de la acción se genera del
    contrato y un parámetro de query no aparece en él —la pantalla salía sin
    ningún campo y al enviar contestaba que faltaba el motivo—, y porque un
    texto libre escrito por una persona puede llevar nombres dentro, y la URL
    queda en el log de acceso y en el historial del navegador.
    """

    usuario_id: UUID = Field(..., description="Quién se queda la tarea")


router_def = APIRouter(prefix="/procesos", tags=["procesos"])


@router_def.post(
    "/definiciones",
    response_model=DefinicionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("proceso:write"))],
    summary="Guardar una versión de un proceso, como borrador o publicada",
    description=(
        "Valida la definición y crea una versión nueva. Las instancias en "
        "vuelo siguen con su versión: publicar no las altera.\n\n"
        "Con `estado: borrador` se guarda sin que nadie la pueda instanciar. "
        "Es lo que permite ir dejando un proceso a medias entre sesiones de "
        "trabajo sin arriesgarse a que un disparador lo arranque a mitad de "
        "escribirlo (CRM-00.03.05.05)."
    ),
)
def publicar(datos: PublicarDefinicion, db: DbDep, principal: AutenticadoDep) -> Any:
    if datos.estado not in ("borrador", "publicada"):
        raise ErrorValidacion(
            "Una versión se crea como «borrador» o como «publicada»",
            error_code="proceso.estado_invalido",
        )
    # El borrador también se valida, y a propósito: descubrir que la definición
    # está rota el día que se publica, con prisa, es exactamente cuando peor
    # viene. Lo que el borrador evita es que ALGUIEN LA EJECUTE, no que se
    # revise.
    problemas = mtr.validar_definicion(datos.definicion)
    if problemas:
        raise ErrorValidacion(
            "La definición del proceso no es válida",
            error_code="proceso.definicion_invalida",
            errores=[{"campo": "definicion", "motivo": p} for p in problemas],
        )

    ultima = db.execute(
        select(DefinicionProceso.version)
        .where(
            DefinicionProceso.tenant_id == principal.tenant_id,
            DefinicionProceso.clave == datos.clave,
        )
        .order_by(DefinicionProceso.version.desc())
        .limit(1)
    ).scalar_one_or_none()

    definicion = DefinicionProceso(
        tenant_id=principal.tenant_id,
        clave=datos.clave,
        version=(ultima or 0) + 1,
        nombre=datos.nombre,
        descripcion=datos.descripcion,
        definicion=datos.definicion,
        disparadores=datos.disparadores,
        estado=datos.estado,
    )
    db.add(definicion)
    # Volcado ANTES de auditar y de devolverla: el identificador lo asigna
    # SQLAlchemy en el flush, así que sin esto el apunte de auditoría se
    # guardaría con `objeto_id` nulo y la respuesta saldría sin id.
    db.flush()
    registrar(
        db,
        accion="proceso.publicado" if datos.estado == "publicada" else "proceso.borrador_guardado",
        objeto="definicion_proceso",
        objeto_id=definicion.id,
        datos={"clave": datos.clave, "version": definicion.version, "estado": datos.estado},
    )
    return definicion


@router_def.post(
    "/definiciones/{clave}/{version}/estado",
    response_model=DefinicionOut,
    dependencies=[Depends(exige_permiso("proceso:write"))],
    summary="Publicar o archivar una versión (CRM-00.03.05.05)",
    description=(
        "Un borrador pasa a publicada y una publicada pasa a archivada. "
        "**Archivar no para nada**: las instancias en vuelo terminan con la "
        "versión con la que empezaron. Lo que impide es que se arranquen "
        "nuevas, que es de lo que se trata cuando un proceso se retira.\n\n"
        "No se vuelve de archivada a publicada: si hace falta, se publica una "
        "versión nueva. Resucitar una versión archivada haría que el historial "
        "dejara de explicar por qué una instancia siguió el camino que siguió."
    ),
)
def cambiar_estado_definicion(
    clave: str, version: int, cuerpo: CambioDeEstado, db: DbDep, principal: AutenticadoDep
) -> Any:
    nuevo = cuerpo.estado
    definicion = db.execute(
        select(DefinicionProceso).where(
            DefinicionProceso.tenant_id == principal.tenant_id,
            DefinicionProceso.clave == clave,
            DefinicionProceso.version == version,
        )
    ).scalar_one_or_none()
    if definicion is None:
        raise NoEncontrado("Esa versión no existe", error_code="proceso.version_no_existe")

    permitidas = {("borrador", "publicada"), ("publicada", "archivada"), ("borrador", "archivada")}
    if (definicion.estado, nuevo) not in permitidas:
        raise Conflicto(
            f"No se puede pasar de «{definicion.estado}» a «{nuevo}»",
            error_code="proceso.transicion_invalida",
            detalle={"permitidas": sorted(f"{a} → {b}" for a, b in permitidas)},
        )
    if nuevo == "publicada":
        # Se revalida al publicar: entre guardar el borrador y publicarlo pueden
        # haber pasado semanas, y lo que valía entonces puede apuntar a una
        # tabla de decisión que ya no existe.
        problemas = mtr.validar_definicion(definicion.definicion)
        if problemas:
            raise ErrorValidacion(
                "La definición ya no es válida",
                error_code="proceso.definicion_invalida",
                errores=[{"campo": "definicion", "motivo": p} for p in problemas],
            )

    anterior = definicion.estado
    definicion.estado = nuevo
    db.flush()
    registrar(
        db,
        accion=f"proceso.{nuevo}",
        objeto="definicion_proceso",
        objeto_id=definicion.id,
        datos={"clave": clave, "version": version, "desde": anterior},
    )
    return definicion


@router_def.post(
    "/definiciones/validar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Validar una definición sin publicarla",
    description=(
        "Comprueba pasos inexistentes, rutas rotas, operadores desconocidos y "
        "pasos inalcanzables. Un error descubierto aquí es un mensaje; "
        "descubierto en ejecución, es un proceso a medias en producción."
    ),
)
def validar(datos: PublicarDefinicion) -> Any:
    problemas = mtr.validar_definicion(datos.definicion)
    return {"valida": not problemas, "problemas": problemas}


@router_def.post(
    "/definiciones/simular",
    response_model=dict,
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Simular un proceso sin publicarlo (CRM-00.03.05.04)",
    description=(
        "Recorre el proceso sin tocar nada: las llamadas a servicios se "
        "registran en vez de ejecutarse y las tareas humanas se responden con "
        "lo que se indique. Sirve para ver por dónde iría un caso concreto."
    ),
)
def simular(datos: SimularProceso, db: DbDep, principal: AutenticadoDep) -> Any:
    problemas = mtr.validar_definicion(datos.definicion)
    if problemas:
        return {"valida": False, "problemas": problemas, "recorrido": []}

    recorrido: list[dict[str, Any]] = []
    variables = dict(datos.variables)
    pasos = datos.definicion.get("pasos") or {}
    actual = datos.definicion.get("inicio")
    # Tope duro del recorrido simulado: una definición con un bucle no puede
    # colgar la petición que la simula.
    for _ in range(200):
        paso = pasos.get(actual or "")
        if paso is None:
            recorrido.append({"paso": actual, "nota": "no existe"})
            break
        tipo = paso.get("tipo")
        recorrido.append({"paso": actual, "tipo": tipo})

        if tipo == "fin":
            variables["resultado"] = paso.get("resultado")
            break
        if tipo == "servicio":
            # No se invoca nada: se anota qué se habría llamado y con qué.
            recorrido[-1]["invocaria"] = {
                "operacion": paso.get("operacion"),
                "entrada": mtr.resolver(paso.get("entrada") or {}, variables),
            }
            if paso.get("salida"):
                variables[str(paso["salida"])] = {"_simulado": True}
            actual = paso.get("siguiente")
        elif tipo == "decision":
            destino = None
            for condicion in paso.get("condiciones") or []:
                izq = mtr.resolver(f"@{condicion.get('si', {}).get('atributo', '')}", variables)
                op = mtr.OPERADORES.get(str(condicion.get("si", {}).get("op", "=")))
                der = mtr.resolver(condicion.get("si", {}).get("valor"), variables)
                if op and op(izq, der):
                    destino = condicion.get("entonces")
                    break
            actual = destino or paso.get("si_no") or paso.get("siguiente")
        elif tipo == "humano":
            respuesta = datos.respuestas_humanas.get(str(actual), "")
            recorrido[-1]["respuesta_simulada"] = respuesta
            actual = (paso.get("rutas") or {}).get(respuesta)
            if actual is None:
                recorrido[-1]["nota"] = "sin respuesta simulada: el proceso se detendría aquí"
                break
        else:
            actual = paso.get("siguiente")
        if actual is None:
            break

    return {"valida": True, "problemas": [], "recorrido": recorrido, "variables": variables}


@router_def.get(
    "/definiciones",
    response_model=list[DefinicionOut],
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Definiciones publicadas",
)
def listar_definiciones(db: DbDep, principal: AutenticadoDep) -> Any:
    return list(
        db.execute(
            select(DefinicionProceso)
            .where(DefinicionProceso.tenant_id == principal.tenant_id)
            .order_by(DefinicionProceso.clave, DefinicionProceso.version.desc())
        )
        .scalars()
        .all()
    )


# ── Instancias ────────────────────────────────────────────────────────────

router_inst = APIRouter(prefix="/instancias", tags=["instancias de proceso"])


@router_inst.post(
    "",
    response_model=InstanciaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("proceso:write"))],
    summary="Arrancar un proceso",
)
def arrancar(datos: ArrancarProceso, db: DbDep, principal: AutenticadoDep) -> Any:
    motor = mtr.Motor(db)
    return motor.arrancar(
        tenant_id=principal.tenant_id,
        clave=datos.clave,
        variables=datos.variables,
        origen=(datos.origen_tipo, datos.origen_id) if datos.origen_tipo else None,
    )


@router_inst.get(
    "",
    response_model=list[InstanciaOut],
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Instancias, filtrables por estado y por origen",
)
def listar_instancias(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query("", description="ejecutando, esperando_humano, fallida…"),
    clave: str = Query(""),
    origen_id: str = Query(""),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(InstanciaProceso).where(InstanciaProceso.tenant_id == principal.tenant_id)
    if estado:
        consulta = consulta.where(InstanciaProceso.estado == estado)
    if clave:
        consulta = consulta.where(InstanciaProceso.clave == clave)
    if origen_id:
        consulta = consulta.where(InstanciaProceso.origen_id == origen_id)
    return list(
        db.execute(consulta.order_by(InstanciaProceso.created_at.desc()).limit(limite))
        .scalars()
        .all()
    )


@router_inst.get(
    "/{instancia_id}",
    response_model=InstanciaOut,
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Estado de una instancia",
)
def obtener_instancia(instancia_id: UUID, db: DbDep) -> Any:
    instancia = db.get(InstanciaProceso, instancia_id)
    if instancia is None:
        raise NoEncontrado("La instancia no existe", error_code="proceso.no_encontrado")
    return instancia


@router_inst.get(
    "/{instancia_id}/historial",
    response_model=list[PasoOut],
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Pasos ejecutados, con entrada, salida y errores",
    description=(
        "Es lo que responde a «¿por dónde va y por qué se paró?». Incluye los "
        "valores de entrada y salida de cada paso: sin ellos, reproducir un "
        "fallo obliga a adivinar con qué datos ocurrió."
    ),
)
def historial(instancia_id: UUID, db: DbDep) -> Any:
    # El padre se comprueba antes: un subrecurso de algo que no existe —o que
    # no es tuyo— tiene que responder 404 igual que el recurso padre. No
    # filtraba datos (el guard vacía la lista), pero el mismo identificador
    # daba 404 en un sitio y 200 en otro, y esa incoherencia es por donde se
    # cuela una fuga el día que el subrecurso incluya algo que no cuelgue de
    # una tabla con `tenant_id`. Lo encontró el fuzzing sistemático de rutas.
    if db.get(InstanciaProceso, instancia_id) is None:
        raise NoEncontrado("Instancia no encontrada", error_code="proceso.instancia_no_existe")
    return list(
        db.execute(
            select(PasoEjecutado)
            .where(PasoEjecutado.instancia_id == instancia_id)
            .order_by(PasoEjecutado.created_at)
        )
        .scalars()
        .all()
    )


@router_inst.post(
    "/{instancia_id}/reintentar",
    response_model=InstanciaOut,
    dependencies=[Depends(exige_permiso("proceso:admin"))],
    summary="Reintentar una instancia fallida",
)
def reintentar(instancia_id: UUID, db: DbDep) -> Any:
    instancia = db.get(InstanciaProceso, instancia_id)
    if instancia is None:
        raise NoEncontrado("La instancia no existe", error_code="proceso.no_encontrado")
    if instancia.estado not in ("fallida", "compensada"):
        raise Conflicto(
            "Solo se puede reintentar una instancia fallida",
            error_code="proceso.no_reintentable",
            detalle={"estado": instancia.estado},
        )
    instancia.estado = "ejecutando"
    instancia.error = None
    instancia.despertar_at = datetime.now(timezone.utc)
    registrar(db, accion="proceso.reintentado", objeto="instancia_proceso", objeto_id=instancia.id)
    return instancia


@router_inst.patch(
    "/{instancia_id}/variables",
    response_model=InstanciaOut,
    dependencies=[Depends(exige_permiso("proceso:admin"))],
    summary="Corregir las variables de una instancia en marcha",
    description=(
        "Herramienta de rescate para un proceso atascado por un dato mal "
        "cargado. Exige motivo y queda auditado: cambia el curso de un proceso "
        "ya en marcha."
    ),
)
def editar_variables(
    instancia_id: UUID, datos: EditarVariables, db: DbDep, principal: AutenticadoDep
) -> Any:
    instancia = db.get(InstanciaProceso, instancia_id)
    if instancia is None:
        raise NoEncontrado("La instancia no existe", error_code="proceso.no_encontrado")
    anteriores = dict(instancia.variables)
    instancia.variables = {**anteriores, **datos.variables}
    registrar(
        db,
        accion="proceso.variables_editadas",
        objeto="instancia_proceso",
        objeto_id=instancia.id,
        datos={"claves": sorted(datos.variables), "anteriores": anteriores},
        motivo=datos.motivo,
    )
    return instancia


# ── Tareas humanas ────────────────────────────────────────────────────────

router_tareas = APIRouter(prefix="/tareas", tags=["tareas humanas"])


@router_tareas.get(
    "",
    response_model=list[TareaOut],
    summary="Mi bandeja de tareas",
    description=(
        "Tareas asignadas a la persona o a alguno de sus roles. El proceso está "
        "detenido esperándolas."
    ),
)
def bandeja(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query("pendiente"),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    from sqlalchemy import or_

    consulta = (
        select(TareaHumana)
        .where(
            TareaHumana.tenant_id == principal.tenant_id,
            TareaHumana.estado == estado,
            or_(
                TareaHumana.asignada_a == principal.id,
                TareaHumana.asignada_rol.in_(list(principal.roles) or [""]),
            ),
        )
        .order_by(TareaHumana.vence_at.nulls_last(), TareaHumana.created_at)
        .limit(limite)
    )
    return list(db.execute(consulta).scalars().all())


@router_tareas.post(
    "/{tarea_id}/responder",
    response_model=InstanciaOut,
    summary="Responder una tarea y reanudar el proceso",
)
def responder(tarea_id: UUID, datos: ResponderTarea, db: DbDep, principal: AutenticadoDep) -> Any:
    tarea = db.get(TareaHumana, tarea_id)
    if tarea is None or tarea.tenant_id != principal.tenant_id:
        raise NoEncontrado("La tarea no existe", error_code="tarea.no_encontrada")
    # Se comprueba que le toca: por asignación directa o por rol. Sin esto,
    # cualquiera con acceso a la API podría aprobar el descuento de otro.
    if tarea.asignada_a and tarea.asignada_a != principal.id:
        if not (tarea.asignada_rol and tarea.asignada_rol in principal.roles):
            raise NoEncontrado("La tarea no existe", error_code="tarea.no_encontrada")

    motor = mtr.Motor(db)
    instancia = motor.responder_tarea(
        tarea,
        respuesta=datos.respuesta,
        usuario_id=principal.id,
        comentario=datos.comentario,
    )
    registrar(
        db,
        accion="tarea.respondida",
        objeto="tarea_humana",
        objeto_id=tarea.id,
        datos={"respuesta": datos.respuesta, "paso": tarea.paso},
    )
    return instancia


@router_tareas.post(
    "/{tarea_id}/delegar",
    response_model=TareaOut,
    summary="Delegar una tarea en otra persona",
)
def delegar(tarea_id: UUID, datos: DelegarTarea, db: DbDep, principal: AutenticadoDep) -> Any:
    tarea = db.get(TareaHumana, tarea_id)
    if tarea is None or tarea.tenant_id != principal.tenant_id:
        raise NoEncontrado("La tarea no existe", error_code="tarea.no_encontrada")
    if tarea.estado != "pendiente":
        raise Conflicto("Esa tarea ya está resuelta", error_code="tarea.ya_resuelta")
    tarea.delegada_por = principal.id
    tarea.asignada_a = datos.usuario_id
    registrar(
        db,
        accion="tarea.delegada",
        objeto="tarea_humana",
        objeto_id=tarea.id,
        datos={"de": str(principal.id), "a": str(datos.usuario_id)},
    )
    return tarea


# ── Tablas de decisión (CRM-00.03.02.10) ──────────────────────────────────

router_tablas = APIRouter(prefix="/tablas-decision", tags=["tablas de decisión"])


@router_tablas.get(
    "",
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Listar las tablas de decisión del tenant",
)
def listar_tablas(db: DbDep) -> Any:
    from services.orchestrator.modelos import TablaDecision

    filas = db.execute(select(TablaDecision).order_by(TablaDecision.clave)).scalars().all()
    return {
        "items": [
            {
                "clave": t.clave,
                "nombre": t.nombre,
                "politica": t.politica,
                "activa": t.activa,
                "reglas": len(t.reglas or []),
            }
            for t in filas
        ]
    }


@router_tablas.get(
    "/{clave}",
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Ver una tabla de decisión",
)
def ver_tabla(clave: str, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.orchestrator import decision as dec

    tabla = dec.leer(db, principal.tenant_id, clave)
    return {
        "clave": tabla.clave,
        "nombre": tabla.nombre,
        "politica": tabla.politica,
        "activa": tabla.activa,
        "entradas": tabla.entradas,
        "salidas": tabla.salidas,
        "reglas": tabla.reglas,
    }


@router_tablas.put(
    "/{clave}",
    dependencies=[Depends(exige_permiso("proceso:write"))],
    summary="Crear o reemplazar una tabla de decisión",
    description=(
        "Valida la tabla antes de guardarla y devuelve el análisis de huecos y "
        "solapes. Publicar con avisos es una decisión legítima —a veces el "
        "hueco es un caso que no existe— pero queda registrada."
    ),
)
def guardar_tabla(clave: str, cuerpo: TablaEditada, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.orchestrator import decision as dec

    datos = {**cuerpo.model_dump(exclude_none=True), "clave": clave}
    tabla = dec.guardar(db, principal.tenant_id, datos)
    registrar(
        db,
        accion="tabla_decision.guardada",
        objeto="tabla_decision",
        objeto_id=tabla.id,
        datos={"clave": clave, "reglas": len(tabla.reglas or [])},
    )
    return {"clave": tabla.clave, "analisis": dec.analizar(datos)}


@router_tablas.post(
    "/{clave}/evaluar",
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Evaluar la tabla con unas variables y ver por qué sale lo que sale",
    description=(
        "Devuelve el resultado **y la explicación**: qué reglas casaron, cuáles "
        "no y en qué condición fallaron. Es de solo lectura: no ejecuta nada."
    ),
)
def evaluar_tabla(
    clave: str, variables: dict[str, Any], db: DbDep, principal: AutenticadoDep
) -> Any:
    from services.orchestrator import decision as dec

    return dec.decidir(db, principal.tenant_id, clave, variables).a_dict()


@router_tablas.post(
    "/validar",
    dependencies=[Depends(exige_permiso("proceso:write"))],
    summary="Validar y analizar una tabla sin guardarla",
    description=(
        "Para probar una tabla antes de publicarla: problemas de forma, huecos "
        "de cobertura, solapes y reglas que nunca podrán casar."
    ),
)
def validar_tabla(cuerpo: TablaEditada) -> Any:
    from services.orchestrator import decision as dec

    tabla = cuerpo.model_dump(exclude_none=True)
    problemas = dec.validar(tabla)
    return {
        "valida": not problemas,
        "problemas": problemas,
        # El análisis solo tiene sentido sobre una tabla bien formada: sobre una
        # con reglas que apuntan a entradas inexistentes diría cosas que no
        # significan nada.
        "analisis": dec.analizar(tabla) if not problemas else None,
    }


ROUTERS = [router_def, router_inst, router_tareas, router_tablas]


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
montar_ficha(
    router_tareas,
    modelo=TareaHumana,
    objeto="tarea_humana",
    permiso_leer="proceso:read",
    permiso_escribir="proceso:write",
    nombre="Tareas",
    parametro="tarea_id",
)
