"""API del motor de procesos."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import (
    aplicar_filtros_de_la_url,
    declarar_recurso,
    montar_exportacion,
    montar_ficha,
)
from crmcore.http.pagination import CONTAR_TOTAL_DESCRIPCION, PaginaDeListado, paginar_consulta
from crmcore.http.parametros import admite_parametros_abiertos
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.orchestrator import motor as mtr
from services.orchestrator import sagas
from services.orchestrator.esquemas import (
    ArrancarProceso,
    CambioDeEstado,
    DefinicionOut,
    EditarVariables,
    InstanciaOut,
    PasoOut,
    PublicarDefinicion,
    ResponderTarea,
    SaltarPaso,
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
        "lo que se indique. Sirve para ver por dónde iría un caso concreto.\n\n"
        "**Y dice quién aprobaría y cuánto tardaría**, que es la otra mitad de "
        "la pregunta y la que faltaba. El recorrido decía por qué pasos iría y "
        "no por cuántas manos ni en cuánto tiempo, así que la respuesta a «si "
        "publico esto, ¿qué le pasa a un pedido de 30.000 €?» se quedaba a "
        "medias: la ruta se veía y las dos cosas que decide alguien —a quién le "
        "cae y cuándo vence— no.\n\n"
        "El plazo es **el declarado**, no una predicción: suma los "
        "`vence_en_horas` de las tareas humanas del camino. Un paso sin plazo "
        "declarado sale dicho como tal, porque un proceso que espera a una "
        "persona sin fecha no tarda cero: tarda lo que tarde."
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
                # **El mismo evaluador que el motor**, no una copia. Lo estaba:
                # eran dos implementaciones de lo mismo, y al arreglar el caso
                # de la condición sin atributo sólo se arregló una — así que el
                # simulador habría enseñado una rama y el motor habría tomado
                # la otra. Un simulador que no decide igual que el motor es peor
                # que no tener simulador.
                if mtr.cumple_condicion(condicion.get("si") or {}, variables):
                    destino = condicion.get("entonces")
                    break
            actual = destino or paso.get("si_no") or paso.get("siguiente")
        elif tipo == "humano":
            respuesta = datos.respuestas_humanas.get(str(actual), "")
            recorrido[-1]["respuesta_simulada"] = respuesta
            # QUIÉN y CUÁNTO, que es lo que decide alguien al leer esto. Sale
            # de la propia definición —`asignada_a`, `asignada_rol` o `cola`—,
            # que es lo que el motor mirará de verdad al crear la tarea.
            recorrido[-1]["aprobaria"] = (
                paso.get("asignada_a") or paso.get("asignada_rol") or paso.get("cola") or ""
            )
            recorrido[-1]["vence_en_horas"] = paso.get("vence_en_horas")
            actual = (paso.get("rutas") or {}).get(respuesta)
            if actual is None:
                recorrido[-1]["nota"] = "sin respuesta simulada: el proceso se detendría aquí"
                break
        else:
            actual = paso.get("siguiente")
        if actual is None:
            break

    # El resumen de manos y plazo del camino simulado. Va aparte del recorrido
    # porque es lo que se mira primero: «¿por cuántas manos pasa y en cuánto?»
    # se contesta antes de leer paso a paso.
    humanos = [p for p in recorrido if p.get("tipo") == "humano"]
    con_plazo = [p for p in humanos if p.get("vence_en_horas")]
    sin_plazo = [str(p["paso"]) for p in humanos if not p.get("vence_en_horas")]
    return {
        "valida": True,
        "problemas": [],
        "recorrido": recorrido,
        "variables": variables,
        "quien_aprobaria": [
            {
                "paso": str(p["paso"]),
                "quien": p.get("aprobaria") or "",
                "horas": p.get("vence_en_horas"),
            }
            for p in humanos
        ],
        "horas_declaradas": sum(int(p["vence_en_horas"]) for p in con_plazo),
        # Un paso humano sin plazo NO suma cero: suma lo que tarde. Decirlo es
        # la diferencia entre un total y un total que engaña.
        "pasos_sin_plazo": sin_plazo,
        "que_significa": (
            "Suma de los plazos DECLARADOS de las tareas humanas del camino. No "
            "es una predicción."
            if not sin_plazo
            else f"{len(sin_plazo)} tarea(s) humanas del camino no declaran plazo, así "
            "que el total de horas es un suelo y no una estimación: un proceso que "
            "espera a una persona sin fecha no tarda cero."
        ),
    }


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
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Instancias, filtrables por estado y por origen",
)
def listar_instancias(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query("", description="ejecutando, esperando_humano, fallida…"),
    clave: str = Query(""),
    origen_id: str = Query(""),
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    contar: bool = Query(False, description=CONTAR_TOTAL_DESCRIPCION),
) -> Any:
    consulta = select(InstanciaProceso).where(InstanciaProceso.tenant_id == principal.tenant_id)
    if estado:
        consulta = consulta.where(InstanciaProceso.estado == estado)
    if clave:
        consulta = consulta.where(InstanciaProceso.clave == clave)
    if origen_id:
        consulta = consulta.where(InstanciaProceso.origen_id == origen_id)
    # Y los filtros comunes, con sus rangos. Estar escrito a mano no es motivo
    # para quedarse sin ellos: entonces el mismo producto admite
    # `?vence_at__hasta=…` o no según quién escribió cada listado, y eso lo
    # descubre el integrador probando.
    consulta = aplicar_filtros_de_la_url(
        request, InstanciaProceso, consulta, principal=principal, db=db, objeto="instancia_proceso"
    )
    return paginar_consulta(
        db,
        InstanciaProceso,
        consulta,
        limite=limite,
        cursor=cursor,
        modelo_salida=InstanciaOut,
        contar=contar,
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


@router_inst.post(
    "/{instancia_id}/saltar-paso",
    response_model=InstanciaOut,
    dependencies=[Depends(exige_permiso("proceso:admin"))],
    summary="Saltar el paso en el que se ha quedado una instancia",
    description=(
        "La tercera herramienta de rescate, y la que faltaba (CRM-00.03.02.12). "
        "Reintentar vuelve a ejecutar lo mismo y editar las variables corrige "
        "el dato, pero hay pasos que **no se pueden completar nunca**: un "
        "servicio de un tercero que ya no existe, una tarea humana de alguien "
        "que se fue de la empresa. Sin esto, el proceso se queda parado para "
        "siempre y todo lo que venía detrás no se hace.\n\n"
        "**Sólo a un destino que el propio paso declara.** Saltar a cualquier "
        "paso sería un «ejecuta lo que quieras» sobre un proceso en marcha: se "
        "podría meter una instancia en la rama de aprobado sin pasar por la "
        "aprobación, y el histórico diría que el proceso se siguió. Los "
        "destinos salen de los caminos que escribió el autor de la "
        "definición.\n\n"
        "Exige motivo y queda auditado, con el paso del que se salió y al que "
        "se fue: un salto que no se puede revisar después es una puerta "
        "trasera con permiso de administrador."
    ),
)
def saltar_paso(instancia_id: UUID, datos: SaltarPaso, db: DbDep, principal: AutenticadoDep) -> Any:
    instancia = db.get(InstanciaProceso, instancia_id)
    if instancia is None or instancia.tenant_id != principal.tenant_id:
        raise NoEncontrado("La instancia no existe", error_code="proceso.no_encontrado")
    if instancia.estado in ("terminada", "compensada"):
        raise Conflicto(
            "La instancia ya ha terminado: saltar un paso de un proceso cerrado "
            "no lo reabre, lo falsea.",
            error_code="proceso.no_saltable",
            detalle={"estado": instancia.estado},
        )

    definicion = db.get(DefinicionProceso, instancia.definicion_id)
    pasos = (definicion.definicion.get("pasos") or {}) if definicion else {}
    actual = instancia.paso_actual
    paso = pasos.get(actual or "")
    if paso is None:
        raise Conflicto(
            f"La instancia no está parada en ningún paso de su definición "
            f"(«{actual}»), así que no hay de dónde saltar.",
            error_code="proceso.sin_paso_actual",
        )

    # Los destinos los decide la DEFINICIÓN, no quien llama. Ver `destinos_de`.
    posibles = mtr.destinos_de(paso)
    if datos.destino not in posibles:
        raise Conflicto(
            f"«{datos.destino}» no es un destino de «{actual}». Saltar a un paso "
            "cualquiera dejaría el histórico diciendo que el proceso se siguió "
            "cuando no se siguió.",
            error_code="proceso.destino_no_declarado",
            detalle={"desde": actual, "destinos": sorted(set(posibles))},
        )

    instancia.paso_actual = datos.destino
    instancia.estado = "ejecutando"
    instancia.error = None
    instancia.despertar_at = datetime.now(timezone.utc)
    registrar(
        db,
        accion="proceso.paso_saltado",
        objeto="instancia_proceso",
        objeto_id=instancia.id,
        # Los dos extremos: con sólo el destino no se puede saber qué se saltó.
        datos={"desde": actual, "hasta": datos.destino},
        motivo=datos.motivo,
    )
    return instancia


# ── Tareas humanas ────────────────────────────────────────────────────────

router_tareas = APIRouter(prefix="/tareas", tags=["tareas humanas"])


@router_tareas.get(
    "",
    response_model=PaginaDeListado,
    summary="Mi bandeja de tareas",
    description=(
        "Tareas asignadas a la persona o a alguno de sus roles. El proceso está "
        "detenido esperándolas."
    ),
)
def bandeja(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query("pendiente"),
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    contar: bool = Query(False, description=CONTAR_TOTAL_DESCRIPCION),
) -> Any:
    from sqlalchemy import or_

    consulta = select(TareaHumana).where(
        TareaHumana.tenant_id == principal.tenant_id,
        TareaHumana.estado == estado,
        or_(
            TareaHumana.asignada_a == principal.id,
            TareaHumana.asignada_rol.in_(list(principal.roles) or [""]),
        ),
    )
    # Por vencimiento: una bandeja de tareas ordenada por fecha de creación
    # esconde al final la que vence hoy.
    # Y los filtros comunes, con sus rangos. Estar escrito a mano no es motivo
    # para quedarse sin ellos: entonces el mismo producto admite
    # `?vence_at__hasta=…` o no según quién escribió cada listado, y eso lo
    # descubre el integrador probando.
    consulta = aplicar_filtros_de_la_url(
        request, TareaHumana, consulta, principal=principal, db=db, objeto="tarea_humana"
    )
    return paginar_consulta(
        db,
        TareaHumana,
        consulta,
        limite=limite,
        cursor=cursor,
        orden="vence_at",
        modelo_salida=TareaOut,
        contar=contar,
    )


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


# ── Sagas con compensación (CRM-00.03.02) ─────────────────────────────────
#
# El servicio anuncia en su propia descripción «sagas con compensación», y el
# módulo que las resuelve **no lo alcanzaba ninguna ruta**: no se podía arrancar
# una, ni marcar un paso, ni fallarlo, ni mirar qué pasaría al publicar una
# versión nueva. Estaba entero, probado y sin puerta.

router_sagas = APIRouter(prefix="/sagas", tags=["sagas con compensación"])
# De qué objeto es este listado. Sin declararlo, un informe sobre sagas no
# encuentra su tabla y lo que se ve es un informe vacío, no un error.
declarar_recurso(router_sagas, "saga", sagas.Saga)


class IniciarSagaIn(BaseModel):
    clave: str = Field(..., min_length=1, examples=["alta_de_cliente"])
    pasos: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Todos los pasos, **declarados de antemano**, cada uno con su "
            "compensación. Descubrirlos sobre la marcha deja una saga que no "
            "sabe deshacerse"
        ),
    )
    objeto: str = ""
    objeto_id: UUID | None = None
    contexto: dict[str, Any] = Field(default_factory=dict)
    version_proceso: int = Field(1, ge=1)


class PasoHechoIn(BaseModel):
    orden: int = Field(..., ge=1)
    datos: dict[str, Any] = Field(default_factory=dict)


class PasoFallidoIn(BaseModel):
    orden: int = Field(..., ge=1)
    error: str = Field(..., min_length=1)


class MigracionIn(BaseModel):
    clave: str = Field(..., min_length=1)
    version_nueva: int = Field(..., ge=1)
    pasos_nuevos: list[str] = Field(default_factory=list)


class ClonarIn(BaseModel):
    clave: str = Field(..., min_length=1)
    nombre_destino: str = Field(..., min_length=1)


@router_sagas.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("proceso:write"))],
    summary="Arrancar una saga",
    description=(
        "Con **todos los pasos declarados de antemano** y cada uno con su "
        "compensación. Una saga que descubre sus pasos sobre la marcha no sabe "
        "deshacerse: el día que falla el cuarto, nadie sabe qué hay que revertir "
        "de los tres anteriores."
    ),
)
def iniciar_saga(cuerpo: IniciarSagaIn, uow: UowDep) -> Any:
    return sagas.iniciar(
        uow,
        clave=cuerpo.clave,
        pasos=cuerpo.pasos,
        objeto=cuerpo.objeto,
        objeto_id=cuerpo.objeto_id,
        contexto=cuerpo.contexto,
        version_proceso=cuerpo.version_proceso,
    )


@router_sagas.post(
    "/{saga_id}/hecho",
    dependencies=[Depends(exige_permiso("proceso:write"))],
    summary="Anotar que un paso salió bien",
    description=(
        "Es lo que hace avanzar la saga. Sin esta llamada los pasos se quedan "
        "pendientes para siempre y la compensación nunca sabría hasta dónde "
        "deshacer."
    ),
)
def paso_hecho(saga_id: UUID, cuerpo: PasoHechoIn, uow: UowDep) -> Any:
    return sagas.marcar_hecho(uow, saga_id=saga_id, orden=cuerpo.orden, datos=cuerpo.datos)


@router_sagas.post(
    "/{saga_id}/fallo",
    dependencies=[Depends(exige_permiso("proceso:write"))],
    summary="Anotar que un paso falló, y compensar hacia atrás",
    description=(
        "**Hacia atrás y solo lo que se hizo.** Compensar un paso que no llegó a "
        "ejecutarse es deshacer algo que no pasó, y eso rompe más de lo que "
        "arregla: una devolución de un cobro que nunca se hizo sale del banco "
        "igual."
    ),
)
def paso_fallido(saga_id: UUID, cuerpo: PasoFallidoIn, uow: UowDep) -> Any:
    return sagas.fallar(uow, saga_id=saga_id, orden=cuerpo.orden, error=cuerpo.error)


@router_sagas.post(
    "/migracion/simular",
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Qué pasaría con lo que está en vuelo al publicar otra versión",
    description=(
        "Una saga de alta de cliente puede durar semanas. Publicar una versión "
        "nueva sin mirar qué hay dentro es cambiarle los pasos a procesos que ya "
        "están a mitad — y lo que estaba a mitad es lo que nadie reclama.\n\n"
        "No ejecuta nada: dice cuántas instancias hay en vuelo y cuáles se "
        "quedarían con un paso que ya no existe."
    ),
)
def simular_migracion(cuerpo: MigracionIn, db: DbDep, principal: AutenticadoDep) -> Any:
    return sagas.plan_de_migracion(
        db,
        principal.tenant_id,
        clave=cuerpo.clave,
        version_nueva=cuerpo.version_nueva,
        pasos_nuevos=cuerpo.pasos_nuevos,
    )


@router_sagas.post(
    "/plantillas/clonar",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("proceso:write"))],
    summary="Copiar una plantilla de flujo para modificarla",
    description=(
        "Se **copia** y no se edita la original: una plantilla que el producto "
        "actualiza y el cliente ha tocado es la que se queda sin actualizar o "
        "pierde los cambios, y las dos cosas se descubren tarde."
    ),
)
def clonar_plantilla(cuerpo: ClonarIn, uow: UowDep) -> Any:
    return sagas.clonar_plantilla(uow, clave=cuerpo.clave, nombre_destino=cuerpo.nombre_destino)


class SagaOut(BaseModel):
    """Una saga en el listado: lo justo para encontrar la que se busca."""

    id: UUID
    clave: str
    estado: str
    objeto: str
    objeto_id: UUID | None = None
    version_proceso: int
    motivo_fin: str
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


@router_sagas.get(
    "",
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Sagas del tenant",
    description=(
        "Sin listado no se llega a ninguna ficha, y sin ficha no se llega a lo "
        "que hay que arreglar a mano. **`estado=atascada` es la consulta que "
        "importa**: son las que dejaron trabajo hecho que no se puede deshacer y "
        "están esperando a que alguien decida."
    ),
)
def listar_sagas(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query(
        "", description="`en_curso`, `terminada`, `compensando`, `compensada` o `atascada`"
    ),
    clave: str = Query("", description="La clave del proceso"),
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    contar: bool = Query(False, description=CONTAR_TOTAL_DESCRIPCION),
) -> Any:
    consulta = select(sagas.Saga).where(sagas.Saga.tenant_id == principal.tenant_id)
    if estado:
        consulta = consulta.where(sagas.Saga.estado == estado)
    if clave:
        consulta = consulta.where(sagas.Saga.clave == clave)
    # Y los filtros comunes, con sus rangos. Estar escrito a mano no es motivo
    # para quedarse sin ellos: entonces el mismo producto admite
    # `?vence_at__hasta=…` o no según quién escribió cada listado, y eso lo
    # descubre el integrador probando.
    consulta = aplicar_filtros_de_la_url(
        request, sagas.Saga, consulta, principal=principal, db=db, objeto="saga"
    )
    return paginar_consulta(
        db,
        sagas.Saga,
        consulta,
        limite=limite,
        cursor=cursor,
        modelo_salida=SagaOut,
        contar=contar,
    )


@router_sagas.get(
    "/{saga_id}",
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Ver una saga y en qué paso va",
    # Por qué se añadió, que no es lo que lee quien abre la pantalla:
    # Qué pasos se hicieron, cuál falló, cuáles se compensaron y cuáles no
    # se podían compensar. Lo último es lo que hay que arreglar a mano, y
    # una saga que no lo dice deja ese trabajo sin reclamar.
)
def ver_saga(saga_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = db.get(sagas.Saga, saga_id)
    if fila is None or fila.tenant_id != principal.tenant_id:
        raise NoEncontrado("Esa saga no existe", error_code="saga.no_encontrada")
    pasos = sagas.pasos_de(db, principal.tenant_id, saga_id)
    return {
        "saga_id": str(fila.id),
        "clave": fila.clave,
        "estado": fila.estado,
        "version_proceso": fila.version_proceso,
        "objeto": fila.objeto,
        "objeto_id": str(fila.objeto_id) if fila.objeto_id else None,
        "motivo_fin": fila.motivo_fin,
        "pasos": [
            {
                "orden": p.orden,
                "nombre": p.nombre,
                "servicio": p.servicio,
                "estado": p.estado,
                "compensable": p.compensable,
                "error": p.error,
            }
            for p in pasos
        ],
        # Lo que queda por hacer a mano. Sumarlo aquí evita que haya que
        # recorrer los pasos uno a uno para encontrarlo.
        "sin_deshacer": [p.orden for p in pasos if p.estado == "no_compensable"],
    }


# Las rutas literales van declaradas antes que `/{saga_id}`; FastAPI resuelve por
# orden y `/sagas/migracion/simular` casaría con la parametrizada si fuera al
# revés. Van en métodos distintos, pero el orden se mantiene igual: el día que
# alguien añada un GET literal, el error ya no sería suyo.
ROUTERS = [router_def, router_inst, router_tareas, router_tablas, router_sagas]


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


from services.orchestrator.modelos import TablaDecision  # noqa: E402

# Y la tabla de decisión, que también tiene listado propio.
montar_exportacion(
    router_tablas,
    modelo=TablaDecision,
    objeto="tabla_decision",
    permiso="proceso:read",
    nombre="Tablas de decisión",
)


# Estas rutas aceptan además los filtros comunes, cuyos nombres son columnas
# del modelo y cambian con él: no se pueden declarar. Los valida
# `aplicar_filtros_de_la_url`, que rechaza lo que no es columna o lo que este
# principal no ve en claro. Las dos mitades van juntas: con el filtro y sin la
# marca, la ruta contesta 422 a sus propios filtros.
admite_parametros_abiertos(
    listar_instancias, "llama a `aplicar_filtros_de_la_url`, que valida los filtros por columna"
)
admite_parametros_abiertos(
    bandeja, "llama a `aplicar_filtros_de_la_url`, que valida los filtros por columna"
)
admite_parametros_abiertos(
    listar_sagas, "llama a `aplicar_filtros_de_la_url`, que valida los filtros por columna"
)
