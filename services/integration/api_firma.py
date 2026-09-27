"""API de firma electrónica (CRM-06.01.02)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.integration import firma as fir
from services.integration.firma import Sobre

router = APIRouter(prefix="/firma", tags=["firma electrónica"])


# ── Proveedores y reglas ──────────────────────────────────────────────────


class CrearProveedorFirma(BaseModel):
    clave: str = Field(..., min_length=1, max_length=60, examples=["signaturit"])
    nombre: str = Field(..., min_length=1, max_length=200)
    conexion_id: UUID | None = Field(
        None,
        description="La conexión declarativa por la que se le llama. No hay código por proveedor",
    )
    niveles: list[str] = Field(
        default_factory=lambda: ["simple"],
        description=(
            "Qué sabe hacer. Mandarle un contrato que exige cualificada a quien "
            "no la hace produce una firma que parece válida y no lo es"
        ),
        examples=[["simple", "avanzada"]],
    )
    identificaciones: list[str] = Field(
        default_factory=lambda: ["correo"],
        examples=[["correo", "sms", "certificado"]],
    )
    mapa_estados: dict[str, str] = Field(
        default_factory=dict,
        description="Sus estados traducidos a los del sistema, igual que en el seguimiento de encargos",
        examples=[{"signed": "firmado", "declined": "rechazado", "opened": "abierto"}],
    )
    coste_sobre: Decimal | None = None


class ProveedorFirmaOut(BaseModel):
    id: UUID
    clave: str
    nombre: str
    niveles: list[Any] = []
    identificaciones: list[Any] = []
    activo: bool
    solo_en_curso: bool

    model_config = {"from_attributes": True}


@router.post(
    "/proveedores",
    response_model=ProveedorFirmaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("firma:write"))],
    summary="Configurar un proveedor de firma",
    description=(
        "Sobre el transporte declarativo que ya existe. **No hay un conector por "
        "producto ni una lista de proveedores en el código**: eso convertiría "
        "cada cliente con otro proveedor en una versión del producto, y cada alta "
        "en un despliegue."
    ),
)
def crear_proveedor(datos: CrearProveedorFirma, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = fir.ProveedorFirma(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return fila


@router.get(
    "/proveedores",
    response_model=list[ProveedorFirmaOut],
    dependencies=[Depends(exige_permiso("firma:read"))],
    summary="Proveedores configurados",
)
def listar_proveedores(db: DbDep, principal: AutenticadoDep) -> Any:
    return list(
        db.execute(
            select(fir.ProveedorFirma)
            .where(fir.ProveedorFirma.tenant_id == principal.tenant_id)
            .order_by(fir.ProveedorFirma.clave)
        )
        .scalars()
        .all()
    )


class CrearReglaFirma(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=150)
    prioridad: int = 100
    condiciones: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Misma gramática que el resto del producto",
        examples=[[{"atributo": "documento.pais", "operador": "=", "valor": "PT"}]],
    )
    proveedor: str = Field(..., min_length=1, max_length=60)
    nivel_minimo: str | None = Field(
        None,
        description=(
            "Una regla puede SUBIR el nivel pedido, nunca bajarlo: dejar que lo "
            "rebaje convierte la política en una sugerencia"
        ),
    )


@router.post(
    "/reglas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("firma:write"))],
    summary="Regla de elección de proveedor y nivel",
)
def crear_regla(datos: CrearReglaFirma, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = fir.ReglaProveedorFirma(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id), "nombre": fila.nombre}


@router.post(
    "/simular",
    dependencies=[Depends(exige_permiso("firma:read"))],
    summary="Con qué proveedor y qué nivel saldría",
    description=(
        "Sin crear nada, y diciendo **qué regla ganó**. Una elección que no se "
        "puede explicar no se puede corregir, y aquí decide con qué validez legal "
        "sale un contrato."
    ),
)
def simular(
    datos: dict[str, Any], db: DbDep, principal: AutenticadoDep, nivel: str = Query("simple")
) -> Any:
    proveedor, nivel_final, regla = fir.elegir_proveedor(
        db, principal.tenant_id, datos, nivel=nivel
    )
    return {"proveedor": proveedor, "nivel": nivel_final, "regla": regla}


class CrearPlantillaFirma(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    tipo_documento: str = ""
    nivel: str = "simple"
    campos: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Dos formas de decir dónde va cada cosa: por página y coordenadas, o "
            "por **anclaje de texto**. El anclaje existe porque las coordenadas "
            "se rompen en cuanto el contrato gana un párrafo, y eso pasa siempre"
        ),
        examples=[
            [
                {"tipo": "firma", "firmante": 0, "anclaje": "/firma_cliente/"},
                {"tipo": "texto", "firmante": 0, "etiqueta": "NIF", "obligatorio": True},
            ]
        ],
    )
    dias_validez: int = Field(30, ge=1, le=365)
    orden_estricto: bool = False


@router.post(
    "/plantillas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("firma:write"))],
    summary="Plantilla de firma: dónde se firma y qué rellena cada uno",
)
def crear_plantilla(datos: CrearPlantillaFirma, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = fir.PlantillaFirma(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id), "clave": fila.clave}


# ── Sobres ────────────────────────────────────────────────────────────────


class FirmanteEntrada(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=320)
    telefono: str | None = None
    orden: int = 0
    papel: str = Field("firmante", description="firmante · aprobador · copia")
    identificacion: str = Field(
        "correo", description="correo · sms · video · certificado · dni_electronico"
    )


class CrearSobre(BaseModel):
    documento_id: str = Field(..., min_length=1, description="El documento del corpus que se firma")
    firmantes: list[FirmanteEntrada] = Field(..., min_length=1)
    objeto_origen: str = Field("", examples=["presupuesto", "contrato"])
    objeto_origen_id: UUID | None = None
    cuenta_id: UUID | None = None
    asunto: str = ""
    mensaje: str = ""
    nivel: str = Field("simple", description="simple · avanzada · cualificada")
    proveedor: str = Field("", description="Vacío: lo eligen las reglas")
    plantilla: str = ""
    dias_validez: int | None = None
    orden_estricto: bool = Field(
        False,
        description=(
            "Con orden, solo le llega al siguiente cuando firma el anterior: es "
            "lo que hace que un contrato lo firme el cliente DESPUÉS del nuestro"
        ),
    )
    contexto: dict[str, Any] = Field(
        default_factory=dict, description="Lo que deciden las reglas: país, importe, tipo"
    )


@router.post(
    "/sobres",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("firma:write"))],
    summary="Preparar un sobre",
    description=(
        "**No lo manda.** Separar crear de mandar es a propósito: mandar un "
        "contrato a firmar es irreversible de cara al cliente —le llega un "
        "correo— y el error más caro que puede cometer quien lo maneja es pulsar "
        "creyendo que aún estaba montándolo."
    ),
)
def crear_sobre(datos: CrearSobre, uow: UowDep) -> Any:
    campos = datos.model_dump()
    firmantes = campos.pop("firmantes")
    sobre = fir.crear(uow, firmantes=firmantes, **campos)
    return {
        "id": str(sobre.id),
        "referencia": sobre.referencia,
        "proveedor": sobre.proveedor,
        "nivel": sobre.nivel,
        "estado": sobre.estado,
    }


@router.post(
    "/sobres/{sobre_id}/enviar",
    dependencies=[Depends(exige_permiso("firma:write"))],
    summary="Mandarlo al proveedor",
    description=(
        "**No se da por firmado porque la llamada no diera error**: el proveedor "
        "acepta el sobre y el firmante puede tardar una semana o no abrirlo nunca."
    ),
)
def enviar_sobre(sobre_id: UUID, uow: UowDep) -> Any:
    return fir.enviar(uow, sobre_id)


class EventoFirma(BaseModel):
    proveedor: str = Field(..., min_length=1)
    referencia_externa: str = ""
    referencia: str = ""
    estado_proveedor: str = Field(..., description="Tal cual lo dice él, sin traducir")
    email_firmante: str = ""
    ocurrio_at: datetime | None = None
    id_externo: str = Field(
        "", description="Su identificador del evento: es lo que hace idempotente la ingesta"
    )
    ip: str = ""
    agente: str = ""
    motivo: str = ""
    crudo: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/eventos",
    dependencies=[Depends(exige_permiso("firma:write"))],
    summary="Ingerir un aviso del proveedor (webhook o sondeo)",
    description=(
        "Idempotente por el identificador del evento: sin eso, la cadena de "
        "custodia tendría el mismo acceso dos veces, que es exactamente lo que un "
        "perito mira para decidir si la evidencia es fiable.\n\n"
        "La evidencia **se guarda siempre**, se entienda o no el estado: perder "
        "un acceso porque no supimos traducir su nombre deja un hueco que después "
        "no se puede rellenar."
    ),
)
def ingerir(datos: EventoFirma, uow: UowDep) -> Any:
    return fir.ingerir(uow, **datos.model_dump())


class ArchivarFirmado(BaseModel):
    documento_firmado_id: str = Field(..., min_length=1)
    certificado_id: str = ""
    sello_tiempo: str = ""
    hash_firmado: str = Field(
        "", description="SHA-256 del firmado, si quien lo archiva ya lo calculó"
    )


# «archivar-firmado» y no «archivar» a secas: el listado genérico ya monta un
# `/sobres/{id}/archivar` para todos los recursos —mandar el registro a la
# papelera— con los mismos tres tramos. Con el mismo nombre, esta se declaraba
# antes y dejaba la otra inalcanzable, y además las dos querían decir cosas
# distintas: aquí se archiva EL FIRMADO, allí el sobre.
@router.post(
    "/sobres/{sobre_id}/archivar-firmado",
    dependencies=[Depends(exige_permiso("firma:write"))],
    summary="Archivar el firmado y enlazarlo a su registro",
    description=(
        "El firmado es **otro documento**, no una versión del original: el "
        "original tiene que seguir existiendo tal como salió, porque es la mitad "
        "de la prueba de que lo firmado es lo que se mandó.\n\n"
        "El certificado se enlaza aparte y con su propio rol: es el documento que "
        "se lleva a un juzgado, y mezclarlo con el contrato hace que nadie lo "
        "encuentre cuando hace falta."
    ),
)
def archivar(sobre_id: UUID, datos: ArchivarFirmado, uow: UowDep) -> Any:
    salida = fir.archivar_firmado(
        uow,
        sobre_id,
        documento_firmado_id=datos.documento_firmado_id,
        certificado_id=datos.certificado_id,
        sello_tiempo=datos.sello_tiempo,
    )
    if datos.hash_firmado:
        sobre = uow.db.get(fir.Sobre, sobre_id)
        if sobre is not None:
            sobre.hash_firmado = datos.hash_firmado
            uow.db.flush()
    return salida


@router.get(
    "/sobres/{sobre_id}/evidencia",
    dependencies=[Depends(exige_permiso("firma:read"))],
    summary="La cadena de custodia completa",
    description=(
        "Se guarda **aquí** y no solo en el proveedor: el día que se cambia de "
        "proveedor —o que cierra— se perdería la prueba de todo lo firmado con "
        "él, y eso se descubre justo cuando hace falta.\n\n"
        "Dice si el expediente es `verificable`, es decir si están las dos "
        "huellas: sin ellas, «esto no es lo que yo firmé» no se puede contestar."
    ),
)
def evidencia(sobre_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return fir.evidencia(db, principal.tenant_id, sobre_id)


class Recordar(BaseModel):
    minimo_horas: int = Field(
        24, ge=1, description="Mínimo entre recordatorios, para no quemar al firmante"
    )


@router.post(
    "/sobres/{sobre_id}/recordar",
    dependencies=[Depends(exige_permiso("firma:write"))],
    summary="Recordar a quien le toca",
    description=(
        "Con un mínimo entre recordatorios. Sin él, un botón pulsado tres veces "
        "manda tres correos en un minuto, y el resultado no es que firme antes: "
        "es que marque el remitente como no deseado y deje de recibir los "
        "siguientes."
    ),
)
def recordar(sobre_id: UUID, datos: Recordar, uow: UowDep) -> Any:
    return fir.recordar(uow, sobre_id, minimo_horas=datos.minimo_horas)


class Cancelar(BaseModel):
    motivo: str = Field(..., min_length=1)


@router.post(
    "/sobres/{sobre_id}/cancelar",
    dependencies=[Depends(exige_permiso("firma:write"))],
    summary="Cancelar un sobre en curso",
    description=(
        "Se exige motivo: al cliente le llegó un correo que va a dejar de "
        "funcionar, y sin motivo nadie sabe por qué — la pregunta llega por "
        "teléfono."
    ),
)
def cancelar(sobre_id: UUID, datos: Cancelar, uow: UowDep) -> Any:
    return fir.cancelar(uow, sobre_id, motivo=datos.motivo)


@router.post(
    "/caducar-vencidos",
    dependencies=[Depends(exige_permiso("firma:write"))],
    summary="Marcar caducados los sobres que pasaron su plazo",
    description=(
        "Un sobre que sigue diciendo «en curso» tres meses después aparece en el "
        "panel como negocio vivo esperando una firma que ya no va a llegar."
    ),
)
def caducar(uow: UowDep, principal: AutenticadoDep) -> Any:
    return fir.caducar_vencidos(uow, principal.tenant_id)


@router.get(
    "/panel",
    dependencies=[Depends(exige_permiso("firma:read"))],
    summary="Lo que está esperando una firma",
    description=(
        "Ordenado por **antigüedad y no por fecha de creación**: lo que lleva más "
        "esperando es lo que hay que empujar, y una lista por fecha entierra lo "
        "viejo debajo de lo nuevo.\n\n"
        "Dice **a quién se espera** en cada sobre, y distingue el que nadie ha "
        "abierto del abierto y no firmado: el primero es un correo que no llegó y "
        "el segundo una decisión que no se toma, y se persiguen de forma distinta."
    ),
)
def panel(db: DbDep, principal: AutenticadoDep, limite: int = Query(100, ge=1, le=500)) -> Any:
    return fir.panel(db, principal.tenant_id, limite=limite)


# ── Listados de las sub-colecciones ───────────────────────────────────────
# Mismo agujero que en las colecciones raíz: se podían crear y no se podían
# leer. Un sobre de firma, una tabla del almacén o una predicción que no se
# pueden listar no existen para quien tiene que revisarlos.

montar_listado(
    router,
    modelo=Sobre,
    objeto="sobre_firma",
    permiso="firma:read",
    ruta="/sobres",
    nombre="Sobres de firma",
)


ROUTERS_FIRMA = [router]
