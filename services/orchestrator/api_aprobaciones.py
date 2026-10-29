"""API de aprobaciones y analítica de proceso (CRM-00.03.05.06 a .14, .16)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.orchestrator import analitica as ana
from services.orchestrator import aprobaciones as apr
from services.orchestrator.aprobaciones import SolicitudAprobacion

router = APIRouter(prefix="/aprobaciones", tags=["aprobaciones"])
router_analitica = APIRouter(prefix="/analitica-procesos", tags=["procesos"])


class EtapaEntrada(BaseModel):
    nombre: str = ""
    origen: str = Field(
        ...,
        description=(
            "De dónde sale el aprobador: jerarquia, rol, usuario, campo o unidad. "
            "No hay valor por defecto: un aprobador elegido por defecto es una "
            "firma que alguien pone sin que le correspondiera"
        ),
        examples=["jerarquia"],
    )
    escalones: int = Field(1, ge=1, le=10, description="Con `jerarquia`: cuántos niveles subir")
    rol: str = ""
    usuarios: list[UUID] = Field(default_factory=list)
    campo: str = Field("", description="Con `campo`: qué clave del contexto trae el aprobador")
    quorum: str = Field(
        "todos", description="todos · mayoria · cualquiera · n_de_m", examples=["mayoria"]
    )
    minimo: int = Field(1, ge=1, description="Con `n_de_m`: cuántos hacen falta")
    vence_en_horas: int | None = Field(None, ge=1)
    avisar_al_pct: float = Field(
        0.7, gt=0, le=1, description="A qué fracción del plazo se avisa, antes de escalar"
    )
    permitir_autoaprobacion: bool = Field(
        False,
        description=(
            "Por defecto quien pide no se aprueba a sí mismo aunque la regla le "
            "señale: es la separación de funciones que más veces se cuela"
        ),
    )


class CrearSolicitud(BaseModel):
    politica: str = Field(..., min_length=1, max_length=80, examples=["descuento_comercial"])
    objeto: str = Field(..., min_length=1, max_length=40, examples=["oportunidad"])
    objeto_id: UUID
    titulo: str = ""
    etapas: list[EtapaEntrada] = Field(..., min_length=1)
    contexto: dict[str, Any] = Field(
        default_factory=dict,
        description="Lo que hace falta para decidir sin abrir otra pantalla",
        examples=[{"importe": "120000", "descuento_pct": 22, "cuenta": "Acme"}],
    )
    campos_vigilados: list[str] = Field(
        default_factory=list,
        description=(
            "Qué campos, si cambian, obligan a volver a aprobar. Solo esos: con "
            "el registro entero, un cambio en la descripción obligaría a "
            "reaprobar un importe que nadie ha tocado"
        ),
        examples=[["descuento_pct", "importe"]],
    )
    umbral_automatico: dict[str, Any] | None = Field(
        None,
        description="Bajo este umbral se aprueba sola, dejando escrito a quién le habría tocado",
        examples=[{"campo": "descuento_pct", "menor_que": 5}],
    )
    instancia_id: UUID | None = None


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("aprobacion:write"))],
    summary="Poner algo a aprobar",
    description=(
        "Las etapas se resuelven y **se congelan** al crear la solicitud. "
        "Recalcular los aprobadores a cada consulta haría que una reorganización "
        "a mitad de una aprobación cambiara a quién le tocaba mientras está "
        "decidiendo."
    ),
)
def crear(datos: CrearSolicitud, uow: UowDep, principal: AutenticadoDep) -> Any:
    solicitud = apr.crear(
        uow,
        politica=datos.politica,
        objeto=datos.objeto,
        objeto_id=datos.objeto_id,
        titulo=datos.titulo,
        etapas=[e.model_dump() for e in datos.etapas],
        contexto=datos.contexto,
        solicitante_id=principal.id,
        campos_vigilados=datos.campos_vigilados,
        umbral_automatico=datos.umbral_automatico,
        instancia_id=datos.instancia_id,
    )
    return apr.estado(uow.db, principal.tenant_id, solicitud.id)


class Decidir(BaseModel):
    decision: str = Field(..., description="aprobar · rechazar · pedir_cambios")
    comentario: str = ""


@router.post(
    "/{aprobacion_id}/decidir",
    dependencies=[Depends(exige_permiso("aprobacion:decidir"))],
    summary="Decidir sobre una aprobación",
    description=(
        "Quien no tiene nada que decidir aquí recibe **404 y no 403**: un 403 "
        "confirmaría que esa aprobación existe y sobre qué registro va.\n\n"
        "Si la persona es suplente de un titular, decide por él y se guardan "
        "**los dos**: perder quién firmó de verdad convierte la delegación en un "
        "agujero de responsabilidad."
    ),
)
def decidir(aprobacion_id: UUID, datos: Decidir, uow: UowDep, principal: AutenticadoDep) -> Any:
    return apr.decidir(
        uow,
        aprobacion_id,
        usuario_id=principal.id,
        decision=datos.decision,
        comentario=datos.comentario,
    )


@router.get(
    "/bandeja",
    dependencies=[Depends(exige_permiso("aprobacion:read"))],
    summary="Lo que me toca decidir",
    description=(
        "Con el contexto dentro y en una sola llamada. Una bandeja que solo dice "
        "«tienes 14 cosas» obliga a abrir catorce pantallas, y lo que pasa "
        "entonces es que se aprueba en bloque sin mirar.\n\n"
        "Lo vencido primero, y después lo que lleva más esperando."
    ),
)
def bandeja(db: DbDep, principal: AutenticadoDep, limite: int = Query(50, ge=1, le=200)) -> Any:
    return apr.bandeja(db, principal.tenant_id, principal.id, limite=limite)


# Estas dos van ANTES de `GET /{aprobacion_id}`, y no es cosmético: con el
# comodín delante, «delegaciones» y «enlaces» se intentan leer como
# identificadores y la respuesta es un 422 de UUID mal formado. Lo cazó la
# prueba que las pide por la ruta; llamando a la función no se ve.
@router.get(
    "/delegaciones",
    dependencies=[Depends(exige_permiso("aprobacion:read"))],
    summary="Quién decide por quién, y hasta cuándo",
    description=(
        "**Se podía delegar y no leer.** Una delegación dice que, mientras "
        "alguien no está, otro firma por él. Sin forma de consultarlas no se "
        "puede contestar «¿quién tiene hoy la firma de dirección?», que es la "
        "pregunta de cualquier revisión de poderes — y una delegación que se "
        "puso para unas vacaciones de agosto sigue viva en marzo sin que nadie "
        "lo note.\n\n"
        "Salen **las vigentes primero y las caducadas detrás, marcadas**, no "
        "escondidas: una delegación que acaba de caducar explica por qué una "
        "aprobación que antes salía sola ahora se queda parada. Y con su "
        "**motivo** y su **política**, porque delegar las vacaciones no es "
        "delegar la firma de los contratos."
    ),
)
def listar_delegaciones(
    db: DbDep, principal: AutenticadoDep, incluir_caducadas: bool = True
) -> Any:
    from crmcore.fechas import ahora
    from sqlalchemy import select

    momento = ahora()
    filas = (
        db.execute(
            select(apr.Delegacion)
            .where(apr.Delegacion.tenant_id == principal.tenant_id)
            .order_by(apr.Delegacion.hasta.desc())
        )
        .scalars()
        .all()
    )
    salida = []
    for f in filas:
        vigente = bool(f.activa and f.desde <= momento <= f.hasta)
        if not vigente and not incluir_caducadas:
            continue
        salida.append(
            {
                "id": str(f.id),
                "titular_id": str(f.titular_id),
                "suplente_id": str(f.suplente_id),
                "desde": f.desde.isoformat(),
                "hasta": f.hasta.isoformat(),
                "vigente": vigente,
                "motivo": f.motivo,
                # Acotada o no: delegar las vacaciones no es delegar la firma
                # de los contratos, y si no se dice se asume lo segundo.
                "politica": f.politica,
                "todas_las_politicas": f.politica is None,
            }
        )
    vigentes = [s for s in salida if s["vigente"]]
    return {
        "delegaciones": salida,
        "vigentes": len(vigentes),
        "que_significa": (
            "Nadie decide por nadie ahora mismo."
            if not vigentes
            else f"{len(vigentes)} personas están firmando por otra. Revisar "
            "quién y hasta cuándo es parte de revisar quién puede qué."
        ),
    }


@router.get(
    "/enlaces",
    dependencies=[Depends(exige_permiso("aprobacion:read"))],
    summary="Qué enlaces de decisión siguen vivos",
    description=(
        "**Se podían emitir y no leer.** Un enlace de éstos permite aprobar "
        "sin entrar al CRM: es una credencial con patas, y hasta hoy no había "
        "forma de saber cuántas hay sueltas ni a nombre de quién.\n\n"
        "No se devuelve el token —en la base sólo está su hash, y ése es el "
        "punto—: se devuelve **a quién representa, cuándo caduca y si ya se "
        "usó**. Los usados salen igual, porque un enlace gastado explica quién "
        "decidió desde fuera, y esconderlo deja esa decisión sin rastro "
        "visible.\n\n"
        "Los **vivos primero**: son los únicos sobre los que se puede actuar."
    ),
)
def listar_enlaces(db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.fechas import ahora
    from sqlalchemy import select

    momento = ahora()
    filas = (
        db.execute(
            select(apr.EnlaceDecision)
            .where(apr.EnlaceDecision.tenant_id == principal.tenant_id)
            .order_by(apr.EnlaceDecision.caduca_at.desc())
        )
        .scalars()
        .all()
    )
    salida = [
        {
            "id": str(f.id),
            "etapa_id": str(f.etapa_id),
            "titular_id": str(f.titular_id),
            "caduca_at": f.caduca_at.isoformat(),
            "usado_at": f.usado_at.isoformat() if f.usado_at else None,
            # Vivo es no usado y no caducado: las dos cosas, porque de un solo
            # uso significa que gastarlo lo mata aunque le quede tiempo.
            "vivo": f.usado_at is None and f.caduca_at > momento,
        }
        for f in filas
    ]
    salida.sort(key=lambda e: (not e["vivo"], e["caduca_at"]))
    vivos = [e for e in salida if e["vivo"]]
    return {
        "enlaces": salida,
        "vivos": len(vivos),
        "que_significa": (
            "No hay ningún enlace de decisión suelto."
            if not vivos
            else f"{len(vivos)} enlaces permiten decidir sin entrar al CRM. "
            "Cada uno es de un solo uso y caduca, pero mientras vive vale."
        ),
    }


@router.get(
    "/{aprobacion_id}",
    dependencies=[Depends(exige_permiso("aprobacion:read"))],
    summary="Estado de una aprobación, etapa a etapa",
)
def estado(aprobacion_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return apr.estado(db, principal.tenant_id, aprobacion_id)


class Vigencia(BaseModel):
    datos_actuales: dict[str, Any] = Field(
        ..., description="Los valores de ahora de los campos vigilados"
    )


@router.post(
    "/{aprobacion_id}/comprobar-vigencia",
    dependencies=[Depends(exige_permiso("aprobacion:write"))],
    summary="¿Lo aprobado sigue siendo lo que se aprobó?",
    description=(
        "Si cambió, la aprobación vuelve a empezar **desde la primera etapa**: "
        "quien aprobó el 10 % no ha aprobado el 30 %, y conservarle el voto es "
        "hacerle firmar algo que no vio.\n\n"
        "Los votos anteriores no se borran: son la prueba de que aquella versión "
        "sí se aprobó."
    ),
)
def comprobar_vigencia(aprobacion_id: UUID, datos: Vigencia, uow: UowDep) -> Any:
    return apr.comprobar_vigencia(uow, aprobacion_id, datos.datos_actuales)


class CrearDelegacion(BaseModel):
    titular_id: UUID
    suplente_id: UUID
    desde: datetime
    hasta: datetime = Field(
        ...,
        description=(
            "Obligatorio: una delegación sin fecha de fin es una cesión "
            "permanente que nadie recuerda haber hecho, y en la práctica se queda"
        ),
    )
    motivo: str = ""
    politica: str | None = Field(
        None, description="Acotada a una política. Delegar las vacaciones no es delegar contratos"
    )


@router.post(
    "/delegaciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("aprobacion:write"))],
    summary="Poner un suplente mientras alguien no está",
)
def delegar(datos: CrearDelegacion, uow: UowDep) -> Any:
    fila = apr.delegar(uow, **datos.model_dump())
    return {"id": str(fila.id), "hasta": fila.hasta.isoformat()}


class PedirEnlace(BaseModel):
    solicitud_id: UUID
    titular_id: UUID
    validez_horas: int = Field(72, ge=1, le=720)


@router.post(
    "/enlaces",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("aprobacion:write"))],
    summary="Enlace para decidir desde el correo o el móvil",
    description=(
        "De un solo uso y con caducidad. El token se devuelve **una sola vez** y "
        "en la base queda solo su hash: quien lea esa tabla —una copia de "
        "seguridad, un volcado de soporte— no puede aprobar en nombre de nadie."
    ),
)
def pedir_enlace(datos: PedirEnlace, uow: UowDep, principal: AutenticadoDep) -> Any:
    estado_actual = apr.estado(uow.db, principal.tenant_id, datos.solicitud_id)
    etapa = next(
        (e for e in estado_actual["etapas"] if e["orden"] == estado_actual["etapa_actual"]), None
    )
    if etapa is None:
        from crmcore.errors import Conflicto

        raise Conflicto(
            "Esa aprobación no tiene ninguna etapa abierta",
            error_code="aprobacion.sin_etapa_abierta",
        )
    from sqlalchemy import select

    fila_etapa = uow.db.execute(
        select(apr.EtapaAprobacion).where(
            apr.EtapaAprobacion.solicitud_id == datos.solicitud_id,
            apr.EtapaAprobacion.orden == etapa["orden"],
        )
    ).scalar_one()
    _, token = apr.emitir_enlace(
        uow,
        etapa_id=fila_etapa.id,
        titular_id=datos.titular_id,
        validez_horas=datos.validez_horas,
    )
    return {"token": token, "validez_horas": datos.validez_horas}


class DecidirConEnlace(BaseModel):
    token: str = Field(..., min_length=10)
    decision: str
    comentario: str = ""


@router.post(
    "/decidir-con-enlace",
    dependencies=[Depends(exige_permiso("aprobacion:decidir"))],
    summary="Decidir canjeando el enlace del correo",
    description=(
        "Un token inexistente, usado o caducado dan **el mismo error**: "
        "distinguirlos le diría a quien prueba si ese enlace existió, y con eso "
        "se sabe que hay una aprobación en marcha sobre algo."
    ),
)
def decidir_con_enlace(datos: DecidirConEnlace, uow: UowDep) -> Any:
    return apr.decidir_con_enlace(
        uow, datos.token, decision=datos.decision, comentario=datos.comentario
    )


@router.post(
    "/revisar-plazos",
    dependencies=[Depends(exige_permiso("aprobacion:write"))],
    summary="Avisar a los que van tarde y escalar a los que ya se pasaron",
    description=(
        "Primero se avisa y después se escala. Al escalar, el superior **se "
        "añade**, no sustituye: quitar al titular le quitaría la decisión a quien "
        "todavía puede tomarla, y borraría el rastro de a quién le tocaba."
    ),
)
def revisar_plazos(uow: UowDep, principal: AutenticadoDep) -> Any:
    return apr.revisar_plazos(uow, principal.tenant_id)


# ── Analítica del proceso ─────────────────────────────────────────────────


@router_analitica.get(
    "/instancias/{instancia_id}/grafico",
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Por dónde va esta instancia, sobre su propio gráfico",
    description=(
        "Devuelve cada nodo con su estado para que el lienzo lo pinte encima. No "
        "devuelve colores ni posiciones: eso es del front, y si viniera de aquí, "
        "cambiar la paleta sería un despliegue del backend.\n\n"
        "Se pinta **la versión con la que arrancó la instancia**, no la "
        "publicada: enseñarla sobre el gráfico nuevo señalaría nodos que esa "
        "instancia no tiene."
    ),
)
def grafico(instancia_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return ana.vista_de_instancia(db, principal.tenant_id, instancia_id)


@router_analitica.get(
    "/{clave}",
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Dónde se atasca un proceso",
    description=(
        "El tiempo de un paso humano se cuenta **desde que se creó la tarea hasta "
        "que alguien respondió**, no lo que tardó el motor: medir el motor da "
        "milisegundos en todos los pasos y esconde los tres días que esperó la "
        "firma.\n\n"
        "La mediana va junto a la media, y con menos de diez ejecuciones se dice "
        "que el dato **no es concluyente**: un cuello de botella deducido de tres "
        "ejecuciones lleva a rediseñar un flujo que funcionaba."
    ),
)
def analitica(
    clave: str, db: DbDep, principal: AutenticadoDep, dias: int = Query(30, ge=1, le=365)
) -> Any:
    return ana.analitica_de_proceso(db, principal.tenant_id, clave, dias=dias)


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router,
    modelo=SolicitudAprobacion,
    objeto="aprobacion",
    permiso="aprobacion:read",
    nombre="Solicitudes de aprobación",
)


ROUTERS_APROBACIONES = [router, router_analitica]
