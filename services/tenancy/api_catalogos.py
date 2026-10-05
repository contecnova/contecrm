"""API de los catálogos de configuración: plantillas, calendarios y monedas.

Separada de `api.py` porque son tres superficies con vida propia y ninguna
relación con el ciclo de vida del tenant más allá de colgar de él. Juntarlas
haría de `api.py` el fichero al que todo el mundo teme entrar.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.errors import Conflicto, NoEncontrado
from crmcore.fechas import hoy
from crmcore.http.deps import (
    AutenticadoDep,
    DbDep,
    PlataformaDep,
    UowDep,
    exige_permiso,
)
from crmcore.http.pagination import PaginaDeListado, paginar_consulta
from crmcore.http.reverificacion import dependencia as exige_reverificacion
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.tenancy.catalogos import (
    CalendarioLaboral,
    Festivo,
    Plantilla,
    TipoCambio,
    _clave_formato,
    convertir,
    es_laborable,
    fijar_tipo_cambio,
    render,
    sumar_horas_laborables,
    variables_sin_resolver,
)

# ── Plantillas (CRM-07.01.01.04) ──────────────────────────────────────────

router_plantillas = APIRouter(prefix="/plantillas", tags=["plantillas"])


class CrearPlantilla(BaseModel):
    clave: str = Field(..., max_length=120)
    nombre: str = Field(..., max_length=200)
    tipo: str = Field("correo", pattern="^(correo|documento|notificacion|sms)$")
    idioma: str = Field("es", max_length=10)
    asunto: str | None = Field(None, max_length=300)
    cuerpo: str = ""
    variables: list[str] = Field(default_factory=list)


class EditarPlantilla(BaseModel):
    nombre: str | None = None
    asunto: str | None = None
    cuerpo: str | None = None
    variables: list[str] | None = None
    activa: bool | None = None
    bloqueada: bool | None = None


class PlantillaOut(BaseModel):
    id: UUID
    clave: str
    idioma: str
    tipo: str
    nombre: str
    asunto: str | None
    cuerpo: str
    variables: list[Any]
    activa: bool
    bloqueada: bool

    model_config = {"from_attributes": True}


@router_plantillas.get("", response_model=PaginaDeListado, summary="Listar plantillas")
def listar_plantillas(
    db: DbDep,
    _: AutenticadoDep,
    tipo: str | None = Query(None, description="correo | documento | notificacion | sms"),
    idioma: str | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
) -> Any:
    consulta = select(Plantilla)
    if tipo:
        consulta = consulta.where(Plantilla.tipo == tipo)
    if idioma:
        consulta = consulta.where(Plantilla.idioma == idioma)
    return paginar_consulta(
        db,
        Plantilla,
        consulta,
        limite=limite,
        cursor=cursor,
        orden="clave",
        modelo_salida=PlantillaOut,
    )


@router_plantillas.post(
    "",
    response_model=PlantillaOut,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una plantilla",
    dependencies=[Depends(exige_permiso("plantilla:crear"))],
)
def crear_plantilla(datos: CrearPlantilla, uow: UowDep) -> Any:
    ya = uow.db.execute(
        select(Plantilla).where(Plantilla.clave == datos.clave, Plantilla.idioma == datos.idioma)
    ).scalar_one_or_none()
    if ya is not None:
        raise Conflicto(
            f"Ya hay una plantilla «{datos.clave}» en idioma «{datos.idioma}»",
            error_code="tenancy.plantilla_duplicada",
        )
    fila = Plantilla(tenant_id=uow.tenant_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return fila


@router_plantillas.patch(
    "/{plantilla_id}",
    response_model=PlantillaOut,
    summary="Editar una plantilla",
    dependencies=[Depends(exige_permiso("plantilla:editar"))],
)
def editar_plantilla(plantilla_id: UUID, datos: EditarPlantilla, uow: UowDep) -> Any:
    fila = uow.db.get(Plantilla, plantilla_id)
    if fila is None:
        raise NoEncontrado("Plantilla no encontrada", error_code="tenancy.plantilla_no_existe")
    cambios = datos.model_dump(exclude_unset=True)
    # `bloqueada` protege el CONTENIDO, no la propia marca: si bloqueara también
    # quitarse a sí misma, una plantilla bloqueada por error no se podría
    # recuperar nunca por API.
    if fila.bloqueada and set(cambios) - {"bloqueada", "activa"}:
        raise Conflicto(
            "La plantilla está bloqueada: desbloquéala antes de editar su contenido",
            error_code="tenancy.plantilla_bloqueada",
        )
    for campo, valor in cambios.items():
        setattr(fila, campo, valor)
    return fila


class PruebaPlantilla(BaseModel):
    datos: dict[str, Any] = Field(default_factory=dict)


@router_plantillas.post(
    "/{plantilla_id}/previsualizar",
    response_model=dict,
    summary="Previsualizar una plantilla con datos de prueba",
    description=(
        "Devuelve el asunto y el cuerpo ya sustituidos, y la lista de variables "
        "que quedarían sin resolver. Es lo que hay que mirar ANTES de un envío "
        "masivo: un hueco sin resolver en 20.000 correos no se deshace."
    ),
)
def previsualizar(plantilla_id: UUID, cuerpo: PruebaPlantilla, db: DbDep, _: AutenticadoDep) -> Any:
    fila = db.get(Plantilla, plantilla_id)
    if fila is None:
        raise NoEncontrado("Plantilla no encontrada", error_code="tenancy.plantilla_no_existe")
    asunto, texto = render(fila, cuerpo.datos, db=db)
    faltan = sorted(
        set(variables_sin_resolver(fila.asunto or "", cuerpo.datos))
        | set(variables_sin_resolver(fila.cuerpo or "", cuerpo.datos))
    )
    return {"asunto": asunto, "cuerpo": texto, "sin_resolver": faltan}


# ── Calendarios laborales (CRM-07.01.01.05) ───────────────────────────────

router_calendarios = APIRouter(prefix="/calendarios", tags=["calendarios"])


class CrearCalendario(BaseModel):
    clave: str = Field(..., max_length=60)
    nombre: str = Field(..., max_length=150)
    zona_horaria: str = Field("Europe/Madrid", max_length=60)
    pais: str = Field("ES", min_length=2, max_length=2)
    horario: dict[str, list[dict[str, str]]] = Field(
        default_factory=dict,
        description='Por día de la semana, 0=lunes: {"0":[{"desde":"09:00","hasta":"18:00"}]}',
    )
    por_defecto: bool = False


class CalendarioOut(BaseModel):
    id: UUID
    clave: str
    nombre: str
    zona_horaria: str
    pais: str
    horario: dict[str, Any]
    por_defecto: bool

    model_config = {"from_attributes": True}


class CrearFestivo(BaseModel):
    fecha: date
    nombre: str = Field(..., max_length=150)
    anual: bool = False


class FestivoOut(BaseModel):
    id: UUID
    fecha: date
    nombre: str
    anual: bool

    model_config = {"from_attributes": True}


@router_calendarios.get("", response_model=PaginaDeListado, summary="Listar calendarios")
def listar_calendarios(
    db: DbDep,
    _: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
) -> Any:
    return paginar_consulta(
        db,
        CalendarioLaboral,
        select(CalendarioLaboral),
        limite=limite,
        cursor=cursor,
        orden="clave",
        modelo_salida=CalendarioOut,
    )


@router_calendarios.post(
    "",
    response_model=CalendarioOut,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un calendario laboral",
    dependencies=[Depends(exige_permiso("calendario:crear"))],
)
def crear_calendario(datos: CrearCalendario, uow: UowDep) -> Any:
    if datos.por_defecto:
        # Solo puede haber uno por defecto, y lo garantiza además un índice
        # único parcial: esto quita el anterior para que la escritura no falle.
        for otro in (
            uow.db.execute(select(CalendarioLaboral).where(CalendarioLaboral.por_defecto.is_(True)))
            .scalars()
            .all()
        ):
            otro.por_defecto = False
        uow.db.flush()
    fila = CalendarioLaboral(tenant_id=uow.tenant_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return fila


@router_calendarios.post(
    "/{calendario_id}/festivos",
    response_model=FestivoOut,
    status_code=status.HTTP_201_CREATED,
    summary="Añadir un festivo",
    dependencies=[Depends(exige_permiso("calendario:editar"))],
)
def anadir_festivo(calendario_id: UUID, datos: CrearFestivo, uow: UowDep) -> Any:
    cal = uow.db.get(CalendarioLaboral, calendario_id)
    if cal is None:
        raise NoEncontrado("Calendario no encontrado", error_code="tenancy.calendario_no_existe")
    fila = Festivo(tenant_id=uow.tenant_id, calendario_id=calendario_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return fila


@router_calendarios.get(
    "/{calendario_id}/festivos", response_model=list[FestivoOut], summary="Festivos del calendario"
)
def listar_festivos(calendario_id: UUID, db: DbDep, _: AutenticadoDep) -> Any:
    # El padre se comprueba antes: un subrecurso de algo que no existe —o que
    # no es tuyo— tiene que responder 404 igual que el recurso padre. No
    # filtraba datos (el guard vacía la lista), pero el mismo identificador
    # daba 404 en un sitio y 200 en otro, y esa incoherencia es por donde se
    # cuela una fuga el día que el subrecurso incluya algo que no cuelgue de
    # una tabla con `tenant_id`. Lo encontró el fuzzing sistemático de rutas.
    if db.get(CalendarioLaboral, calendario_id) is None:
        raise NoEncontrado("Calendario no encontrado", error_code="tenancy.calendario_no_existe")
    return (
        db.execute(
            select(Festivo).where(Festivo.calendario_id == calendario_id).order_by(Festivo.fecha)
        )
        .scalars()
        .all()
    )


@router_calendarios.get(
    "/{calendario_id}/vencimiento",
    response_model=dict,
    summary="Calcular un vencimiento en horas laborables",
    description=(
        "Suma horas **laborables** —saltando noches, fines de semana y "
        "festivos— a un instante. Es el cálculo que usan los relojes de SLA y "
        "los vencimientos de tarea, y se expone para que cualquier servicio lo "
        "use en vez de reimplementarlo."
    ),
)
def vencimiento(
    calendario_id: UUID,
    db: DbDep,
    _: AutenticadoDep,
    horas: float = Query(..., gt=0, le=8760, description="Horas laborables a sumar"),
    desde: datetime | None = Query(None, description="Instante de partida (por defecto, ahora)"),
) -> Any:
    from datetime import timezone

    cal = db.get(CalendarioLaboral, calendario_id)
    if cal is None:
        raise NoEncontrado("Calendario no encontrado", error_code="tenancy.calendario_no_existe")
    partida = desde or datetime.now(timezone.utc)
    fin = sumar_horas_laborables(db, cal, partida, horas)
    return {
        "desde": partida.isoformat(),
        "horas_laborables": horas,
        "vence": fin.isoformat(),
        "partida_en_horario": es_laborable(db, cal, partida),
        "zona_horaria": cal.zona_horaria,
    }


# ── Monedas y tipos de cambio (CRM-07.01.01.06) ───────────────────────────

router_monedas = APIRouter(prefix="/monedas", tags=["monedas"])


class FijarCambio(BaseModel):
    desde: str = Field(..., min_length=3, max_length=3)
    hasta: str = Field(..., min_length=3, max_length=3)
    tasa: Decimal = Field(..., gt=0)
    fecha: date | None = None
    origen: str = Field("manual", max_length=60)


class CambioOut(BaseModel):
    id: UUID
    desde_moneda: str
    hasta_moneda: str
    fecha: date
    tasa: Decimal
    origen: str | None

    model_config = {"from_attributes": True}


@router_monedas.get("/cambios", response_model=list[CambioOut], summary="Histórico de cambios")
def listar_cambios(
    db: DbDep,
    _: AutenticadoDep,
    desde: str | None = Query(None, min_length=3, max_length=3),
    hasta: str | None = Query(None, min_length=3, max_length=3),
    limite: int = Query(100, ge=1, le=1000),
) -> Any:
    consulta = select(TipoCambio)
    if desde:
        consulta = consulta.where(TipoCambio.desde_moneda == desde.upper())
    if hasta:
        consulta = consulta.where(TipoCambio.hasta_moneda == hasta.upper())
    return db.execute(consulta.order_by(TipoCambio.fecha.desc()).limit(limite)).scalars().all()


@router_monedas.put(
    "/cambios",
    response_model=CambioOut,
    summary="Fijar un tipo de cambio para una fecha",
    dependencies=[Depends(exige_permiso("moneda:editar"))],
)
def poner_cambio(datos: FijarCambio, uow: UowDep) -> Any:
    fila = fijar_tipo_cambio(
        uow.db,
        tenant_id=uow.tenant_id,
        desde=datos.desde,
        hasta=datos.hasta,
        tasa=datos.tasa,
        en_fecha=datos.fecha,
        origen=datos.origen,
    )
    uow.db.flush()
    return fila


@router_monedas.get(
    "/convertir",
    response_model=dict,
    summary="Convertir un importe",
    description=(
        "Usa el cambio vigente **en la fecha pedida**, no el de hoy: una "
        "oportunidad cerrada en marzo tiene que seguir valiendo lo de marzo."
    ),
)
def convertir_importe(
    db: DbDep,
    principal: AutenticadoDep,
    importe: Decimal = Query(...),
    desde: str = Query(..., min_length=3, max_length=3),
    hasta: str = Query(..., min_length=3, max_length=3),
    en_fecha: date | None = Query(None),
) -> Any:
    resultado = convertir(
        db,
        tenant_id=principal.tenant_id,
        importe=importe,
        desde=desde,
        hasta=hasta,
        en_fecha=en_fecha,
    )
    return {
        "importe": str(importe),
        "desde": desde.upper(),
        "hasta": hasta.upper(),
        "fecha": (en_fecha or hoy(db)).isoformat(),
        "resultado": str(resultado),
    }


# ── Baja y portabilidad (CRM-00.01.03.05, CRM-08.02.01.05) ────────────────

router_baja = APIRouter(prefix="/tenants", tags=["baja y portabilidad"])


class ExportacionOut(BaseModel):
    id: UUID
    motivo: str
    estado: str
    formato: str
    version_formato: int
    total_filas: int
    sha256: str | None
    uri: str | None
    manifiesto: dict[str, Any]
    error: str | None

    model_config = {"from_attributes": True}


@router_baja.post(
    "/{tenant_id}/exportacion",
    response_model=ExportacionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Exportar los datos del tenant",
    description=(
        "Vuelca en JSON Lines, con un manifiesto que lleva el recuento y el "
        "SHA-256 de cada fichero y un LEEME que explica cómo leerlo sin tener "
        "este producto delante. La misma exportación sirve para la "
        "portabilidad y para la baja: separarlas haría que la de la baja se "
        "ejercitara una vez al año, y lo que no se ejercita no funciona.\n\n"
        "Exporta **los objetos de este servicio**. La exportación completa de "
        "un tenant es la unión de la de cada servicio, porque los permisos de "
        "base de datos impiden —a propósito— que uno lea el esquema de otro."
    ),
    dependencies=[
        Depends(exige_permiso("tenant:exportar")),
        # Es la salida de datos más grande que existe en el producto: todo el
        # tenant en un fichero. Si alguna exportación exige reverificarse, es
        # esta.
        exige_reverificacion("exportacion_masiva"),
    ],
)
def exportar_tenant(
    tenant_id: UUID,
    uow: UowDep,
    principal: AutenticadoDep,
    motivo: str = Query("portabilidad", pattern="^(portabilidad|baja)$"),
) -> Any:
    from services.tenancy.baja import exportar
    from services.tenancy.modelos import Consumo, FeatureFlag, UnidadNegocio

    return exportar(
        uow.db,
        tenant_id=tenant_id,
        tablas={
            "unidades_negocio": UnidadNegocio,
            "feature_flags": FeatureFlag,
            "consumo": Consumo,
            "plantillas": Plantilla,
            "calendarios_laborales": CalendarioLaboral,
            "festivos": Festivo,
            "tipos_cambio": TipoCambio,
        },
        motivo=motivo,
        por=principal.id,
    )


@router_baja.post(
    "/{tenant_id}/exportacion/{exportacion_id}/verificar",
    response_model=ExportacionOut,
    summary="Verificar una exportación releyéndola del almacén",
    description=(
        "No comprueba lo que se escribió: **relee** y recalcula los hashes. Es "
        "la diferencia entre «creemos que se exportó» y «hemos comprobado que "
        "está ahí», y es justo antes de destruir los originales cuando hay que "
        "saberlo."
    ),
    dependencies=[Depends(exige_permiso("tenant:exportar"))],
)
def verificar_exportacion(tenant_id: UUID, exportacion_id: UUID, uow: UowDep) -> Any:
    from services.tenancy.baja import verificar

    return verificar(uow.db, exportacion_id)


@router_baja.get(
    "/{tenant_id}/exportaciones",
    response_model=list[ExportacionOut],
    summary="Exportaciones del tenant",
)
def listar_exportaciones(tenant_id: UUID, db: DbDep, _: AutenticadoDep) -> Any:
    from services.tenancy.baja import Exportacion

    return list(
        db.execute(
            select(Exportacion)
            .where(Exportacion.tenant_id == tenant_id)
            .order_by(Exportacion.created_at.desc())
        )
        .scalars()
        .all()
    )


class DestruirDatos(BaseModel):
    exportacion_id: UUID = Field(
        ...,
        description=(
            "La exportación verificada que justifica la destrucción. Sin ella no "
            "hay nada que entregar ni nada que certificar."
        ),
    )
    confirmacion: str = Field(
        ...,
        description="El slug del tenant, escrito a mano. No es burocracia: es irreversible.",
    )


class CertificadoOut(BaseModel):
    id: UUID
    tenant_id: UUID
    tenant_slug: str
    exportacion_id: UUID | None
    exportacion_sha256: str | None
    alcance: dict[str, Any]
    hash: str

    model_config = {"from_attributes": True}


@router_baja.post(
    "/{tenant_id}/destruir-datos",
    response_model=CertificadoOut,
    dependencies=[exige_reverificacion("baja_tenant")],
    summary="Destruir los datos del tenant y emitir el certificado",
    description=(
        "Irreversible. Exige que el tenant esté en baja, que haya pasado la "
        "ventana de recuperación y que exista una exportación **verificada**.\n\n"
        "Destruye lo que no vive en la base —la caché y el almacén de "
        "ficheros—; las filas las borra cada servicio en su esquema, porque los "
        "permisos de base de datos impiden que uno escriba en el de otro. El "
        "certificado, encadenado como el registro de auditoría, recoge las dos "
        "partes y sobrevive al tenant: es lo único que queda cuando ya no queda "
        "nada."
    ),
)
def destruir_datos(
    tenant_id: UUID, datos: DestruirDatos, uow: UowDep, principal: PlataformaDep
) -> Any:
    from services.tenancy.baja import destruir
    from services.tenancy.modelos import Tenant

    tenant = uow.db.get(Tenant, tenant_id)
    if tenant is None:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")
    if datos.confirmacion != tenant.slug:
        raise Conflicto(
            "La confirmación no coincide con el identificador del tenant",
            error_code="tenant.confirmacion_no_coincide",
        )
    return destruir(uow.db, tenant=tenant, exportacion_id=datos.exportacion_id, por=principal.id)


@router_baja.get(
    "/{tenant_id}/certificados",
    response_model=list[CertificadoOut],
    summary="Certificados de destrucción",
    description=(
        "Sobreviven al tenant. Un cliente que pregunta dos años después «¿seguís "
        "teniendo mis datos?» necesita una respuesta que no sea «creemos que no»."
    ),
)
def certificados(tenant_id: UUID, db: DbDep, _: AutenticadoDep) -> Any:
    from services.tenancy.baja import CertificadoDestruccion

    return list(
        db.execute(
            select(CertificadoDestruccion)
            .where(CertificadoDestruccion.tenant_id == tenant_id)
            .order_by(CertificadoDestruccion.created_at.desc())
        )
        .scalars()
        .all()
    )


# ── Localización (CRM-00.01.04.07) ────────────────────────────────────────

router_localizacion = APIRouter(prefix="/localizacion", tags=["localizacion"])


@router_localizacion.get(
    "",
    summary="Cómo se escriben aquí las fechas, los números y los importes",
    description=(
        "Las preferencias **ya resueltas** por la jerarquía global → tier → "
        "tenant → unidad → usuario, con un ejemplo de cada una.\n\n"
        "Existe porque el CRM es headless: si cada frontend resolviera los "
        "ajustes por su cuenta, la web y el móvil acabarían escribiendo la "
        "misma fecha de dos maneras. Los ejemplos no son decorativos — son el "
        "contrato: un cliente puede comprobar que su formateo coincide con el "
        "del servidor sin implementar la jerarquía."
    ),
)
def localizacion(db: DbDep, _: AutenticadoDep) -> Any:
    from datetime import datetime, timezone
    from decimal import Decimal

    from crmcore import i18n

    loc = i18n.resolver(db)
    muestra = datetime(2026, 9, 18, 23, 30, tzinfo=timezone.utc)
    return {
        "idioma": loc.idioma,
        "zona_horaria": str(loc.zona),
        "formato_fecha": _clave_formato(loc),
        "moneda_funcional": loc.moneda,
        "primer_dia_semana": loc.primer_dia,
        "dias_de_la_semana": loc.dias_de_la_semana(),
        "ejemplos": {
            # El instante es a las 23:30 UTC a propósito: en media Europa ya es
            # el día siguiente, así que el ejemplo enseña si el huso se está
            # aplicando de verdad o solo se está recortando la cadena.
            "instante_utc": muestra.isoformat(),
            "fecha": loc.fecha(muestra),
            "fecha_hora": loc.fecha_hora(muestra),
            "numero": loc.numero(Decimal("1234567.5")),
            "importe": loc.importe(Decimal("1234567.5")),
        },
    }


ROUTERS_CATALOGOS = [
    router_plantillas,
    router_calendarios,
    router_monedas,
    router_baja,
    router_localizacion,
]


from crmcore.http.listados import montar_exportacion  # noqa: E402

# Las dos colecciones de este módulo con listado escrito a mano. Igual que en
# ventas y en party: `montar_listado` monta la exportación sola, y lo que no se
# monta con él se queda sin ella sin que nadie lo note.
montar_exportacion(
    router_plantillas,
    modelo=Plantilla,
    objeto="plantilla",
    permiso="tenant:read",
    nombre="Plantillas",
)
montar_exportacion(
    router_calendarios,
    modelo=CalendarioLaboral,
    objeto="calendario_laboral",
    permiso="tenant:read",
    nombre="Calendarios",
)
