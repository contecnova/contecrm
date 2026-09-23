"""API de recorridos, plantillas y centro de preferencias
(CRM-02.02.02, CRM-02.03.01.01, CRM-02.03.01.05, CRM-02.03.01.07)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha, montar_listado
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.marketing import ajustes as _ajustes  # noqa: F401  (registra las claves)
from services.marketing import correo as cor
from services.marketing import recorridos as rec
from services.marketing.correo import BloqueCorreo, CategoriaPreferencia, PlantillaMarketing
from services.marketing.recorridos import Recorrido

router = APIRouter(prefix="/recorridos", tags=["recorridos"])
router_correo = APIRouter(prefix="/correo", tags=["correo"])
router_preferencias = APIRouter(prefix="/preferencias", tags=["correo"])


class CrearRecorrido(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    nodos: dict[str, Any] = Field(
        ...,
        description="El lienzo ES la definición: nodos con tipo, salidas y posiciones",
        examples=[
            {
                "bienvenida": {
                    "tipo": "accion",
                    "accion": "email",
                    "plantilla": "bienvenida",
                    "siguiente": "esperar",
                },
                "esperar": {"tipo": "espera", "dias": 3, "siguiente": "abrio"},
                "abrio": {
                    "tipo": "decision",
                    "comportamiento": "abrio",
                    "espera_dias": 3,
                    "rutas": {"si": "fin", "no": "recordatorio"},
                },
                "recordatorio": {"tipo": "accion", "accion": "email", "siguiente": "fin"},
                "fin": {"tipo": "fin"},
            }
        ],
    )
    inicio: str = Field(..., min_length=1)
    descripcion: str = ""
    entrada: str = Field("manual", description="evento · segmento · api · manual")
    evento_entrada: str = ""
    segmento_id: UUID | None = None
    salidas: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Valen para TODO el recorrido y se comprueban antes de cada paso. Sin "
            "ellas, quien compre seguirá recibiendo la oferta de bienvenida"
        ),
        examples=[
            [
                {
                    "motivo": "conversion",
                    "condiciones": [{"atributo": "persona.compro", "operador": "=", "valor": True}],
                }
            ]
        ],
    )
    excluye_si_en: list[str] = Field(
        default_factory=list,
        description="Sin esto, quien pasa de captación a cliente recibe las dos cosas a la vez",
    )
    dias_maximos: int = Field(
        90, ge=1, le=730, description="Sin tope, la gente se queda dentro años"
    )
    reentrada: bool = False
    por_cuenta: bool = Field(
        False,
        description=(
            "En B2B, cuatro personas de la misma empresa recibiendo la misma "
            "secuencia es cuatro veces el mismo mensaje en la misma reunión"
        ),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Crear un recorrido",
    description=(
        "Se valida el lienzo **antes de publicar y no al ejecutar**: un recorrido "
        "roto descubierto en ejecución son diez mil personas paradas a mitad de "
        "camino, y sacarlas de ahí cuesta más que el error."
    ),
)
def crear(datos: CrearRecorrido, uow: UowDep) -> Any:
    fila, avisos = rec.crear(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "avisos": avisos}


@router.post(
    "/{recorrido_id}/publicar",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Publicar el recorrido",
    description=(
        "Quien esté dentro **sigue con su versión**. Cambiar el recorrido bajo los "
        "pies de quien ya recibió tres correos produce saltos que nadie puede "
        "explicar después, y son justo los que se descubren por una queja."
    ),
)
def publicar(recorrido_id: UUID, uow: UowDep) -> Any:
    return rec.publicar(uow, recorrido_id)


class Entrar(BaseModel):
    objeto_id: UUID
    objeto: str = "contacto"
    cuenta_id: UUID | None = None


@router.post(
    "/{recorrido_id}/entrar",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Meter a alguien en el recorrido",
    description=(
        "Cuatro comprobaciones y ninguna opcional: que esté publicado, que no esté "
        "ya dentro, que no esté en un recorrido excluyente y que **no esté "
        "suprimido** — quien pidió no ser alcanzado no lo es por mucho que el "
        "recorrido lo diga.\n\n"
        "Devuelve `entro: false` con su motivo en vez de fallar: meter a mil "
        "personas donde cien están suprimidas no es un error, es el caso normal."
    ),
)
def entrar(recorrido_id: UUID, datos: Entrar, uow: UowDep) -> Any:
    return rec.entrar(uow, recorrido_id, **datos.model_dump())


class Comportamiento(BaseModel):
    objeto_id: UUID
    que: str = Field(..., description="abrio · clico · visito · compro · respondio · no_respondio")
    cuando: datetime | None = None


@router.post(
    "/comportamiento",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Anotar que alguien abrió, hizo clic o compró",
    description=(
        "Se anota en **todos los recorridos donde esté** a la vez: el mismo clic "
        "resuelve la rama de los tres, y anotarlo en uno solo dejaría a los otros "
        "dos esperando un comportamiento que ya ocurrió.\n\n"
        "Si estaba esperando, se despierta ya: esperar al plazo cuando la "
        "respuesta ya está es hacer esperar cinco días a quien contestó en cinco "
        "minutos."
    ),
)
def comportamiento(datos: Comportamiento, uow: UowDep) -> Any:
    return rec.anotar_comportamiento(uow, **datos.model_dump())


@router.post(
    "/avanzar",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Mover a la gente por sus recorridos",
    description=(
        "Antes de cada paso se comprueban la **salida** y la **supresión**. Las "
        "dos van aquí y no al entrar porque las dos cambian con el tiempo: alguien "
        "compra a mitad, alguien se da de baja a mitad, y los dos tienen que dejar "
        "de recibir en el paso siguiente y no al final.\n\n"
        "Lo que se salta por supresión o fatiga sale en `omitidos`: contarlo como "
        "enviado inflaría el embudo con correos que nadie recibió."
    ),
)
def avanzar(uow: UowDep, principal: AutenticadoDep) -> Any:
    return rec.avanzar(uow, principal.tenant_id)


class Salir(BaseModel):
    motivo: str = Field("manual", description="conversion · exclusion · fin · manual")


@router.post(
    "/inscritos/{en_recorrido_id}/salir",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Sacar a alguien del recorrido",
)
def salir(en_recorrido_id: UUID, datos: Salir, uow: UowDep) -> Any:
    return rec.salir(uow, en_recorrido_id, motivo=datos.motivo)


@router.get(
    "/{recorrido_id}/embudo",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Cuánta gente pasó por cada nodo y dónde se cae",
    description=(
        "Se cuenta **gente distinta por nodo**, no pasos: un bucle haría que un "
        "nodo tuviera más pasos que personas y el embudo saldría al revés.\n\n"
        "La caída se dice entre nodos **consecutivos del camino**, no contra el "
        "total: contra el total, un nodo al que solo llega una rama parece un "
        "desastre cuando está funcionando. Y si el recorrido tiene ramas se avisa, "
        "porque entonces el camino principal es una aproximación."
    ),
)
def embudo(recorrido_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return rec.embudo(db, principal.tenant_id, recorrido_id)


@router.get(
    "/{recorrido_id}/prueba/{nodo}",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Qué variante gana en una prueba A/B",
    description=(
        "**Con pocos datos no se declara ganador.** Con treinta personas por rama "
        "la diferencia que se ve es ruido, y elegir por ella es peor que no "
        "probar: consolida una variante peor con la confianza de haberla medido."
    ),
)
def prueba(
    recorrido_id: UUID,
    nodo: str,
    db: DbDep,
    principal: AutenticadoDep,
    minimo: int = Query(100, ge=10, le=10000),
) -> Any:
    return rec.resultado_prueba(db, principal.tenant_id, recorrido_id, nodo, minimo=minimo)


# ── Correo ────────────────────────────────────────────────────────────────


class CrearBloque(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    tipo: str = Field(
        "texto", description="texto · imagen · boton · separador · columnas · pie · cabecera"
    )
    contenido: dict[str, Any] = Field(default_factory=dict)
    obligatorio_en_promocional: bool = Field(
        False,
        description=(
            "Se añade a toda plantilla promocional aunque quien la monte se olvide. "
            "El bloque de baja lo es por ley"
        ),
    )


@router_correo.post(
    "/bloques",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Crear un bloque reutilizable",
    description=(
        "Existe para que el pie legal, la cabecera y el bloque de baja estén **en "
        "un solo sitio**. Con plantillas enteras copiadas, cambiar el pie exige "
        "tocar cuarenta y siempre quedan seis con el viejo."
    ),
)
def crear_bloque(datos: CrearBloque, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = cor.BloqueCorreo(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id), "clave": fila.clave}


@router_correo.get(
    "/bloques",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Bloques reutilizables",
)
def listar_bloques(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(cor.BloqueCorreo)
            .where(cor.BloqueCorreo.tenant_id == principal.tenant_id)
            .order_by(cor.BloqueCorreo.clave)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "clave": f.clave,
            "nombre": f.nombre,
            "tipo": f.tipo,
            "obligatorio_en_promocional": f.obligatorio_en_promocional,
        }
        for f in filas
    ]


class CrearPlantillaMarketing(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    asunto: str = Field(..., min_length=1, max_length=300)
    preencabezado: str = ""
    clase: str = Field("promocional", description="promocional · transaccional")
    bloques: list[dict[str, Any]] = Field(default_factory=list)
    categoria: str | None = Field(
        None, description="De qué se puede dar de baja. Sin ella, una promocional no se manda"
    )
    idioma: str = "es"


@router_correo.post(
    "/plantillas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Crear una plantilla",
)
def crear_plantilla(datos: CrearPlantillaMarketing, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = cor.PlantillaMarketing(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id), "clave": fila.clave}


@router_correo.get(
    "/plantillas",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Plantillas del tenant",
)
def listar_plantillas(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(cor.PlantillaMarketing)
            .where(cor.PlantillaMarketing.tenant_id == principal.tenant_id)
            .order_by(cor.PlantillaMarketing.clave)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "clave": f.clave,
            "nombre": f.nombre,
            "clase": f.clase,
            "categoria": f.categoria,
            "idioma": f.idioma,
        }
        for f in filas
    ]


@router_correo.get(
    "/plantillas/{clave}/componer",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Ver la plantilla montada",
    description=(
        "Los bloques **obligatorios se añaden aunque la plantilla no los nombre**, "
        "y se dice cuáles: quien previsualiza tiene que entender por qué aparece "
        "un pie que él no puso.\n\n"
        "Un bloque que falta no se ignora: la plantilla saldría con un hueco y "
        "nadie sabría de dónde salió."
    ),
)
def componer(clave: str, db: DbDep, principal: AutenticadoDep, idioma: str = Query("es")) -> Any:
    return cor.componer(db, principal.tenant_id, clave, idioma=idioma)


@router_correo.get(
    "/comprobar-envio",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Todo lo que hay que mirar antes de mandar",
    description=(
        "Una sola comprobación y no cuatro repartidas: la que se olvida es siempre "
        "la misma —las preferencias— y el resultado es un correo a quien se dio de "
        "baja."
    ),
)
def comprobar(
    db: DbDep,
    principal: AutenticadoDep,
    email: str = Query(...),
    plantilla: str = Query(...),
    idioma: str = Query("es"),
) -> Any:
    return cor.comprobar_envio(
        db, principal.tenant_id, email=email, plantilla_clave=plantilla, idioma=idioma
    )


@router_correo.get(
    "/remitente",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Por qué dominio sale cada clase",
    description=(
        "Lo promocional y lo transaccional comparten reputación: una campaña con "
        "muchas quejas hunde la entrega de las facturas, y mezclarlos hace que "
        "darse de baja de la newsletter parezca que apaga los avisos de "
        "servicio.\n\n"
        "Si no hay dominios separados **se dice**, en vez de mandarlo todo por el "
        "mismo y callar: el día que la entrega se hunda, nadie sabrá por qué."
    ),
)
def remitente(clase: str = Query("promocional")) -> Any:
    from crmcore.runtime.settings import efectivo

    return cor.remitente_para(
        clase,
        config={
            "dominio_promocional": efectivo("dominio_promocional", default=""),
            "dominio_transaccional": efectivo("dominio_transaccional", default=""),
        },
    )


class CrearCategoria(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    descripcion: str = ""
    obligatoria: bool = Field(
        False,
        description=(
            "Los avisos de servicio y las facturas no son marketing, y ofrecer "
            "darse de baja de ellos produce clientes que no reciben su factura"
        ),
    )
    por_defecto: bool = False
    orden: str = "50"


@router_preferencias.post(
    "/categorias",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Declarar de qué se puede dar de baja alguien",
)
def crear_categoria(datos: CrearCategoria, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = cor.CategoriaPreferencia(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id), "clave": fila.clave}


@router_preferencias.get(
    "/categorias",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Categorías de preferencia declaradas",
)
def listar_categorias(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(cor.CategoriaPreferencia)
            .where(cor.CategoriaPreferencia.tenant_id == principal.tenant_id)
            .order_by(cor.CategoriaPreferencia.orden, cor.CategoriaPreferencia.nombre)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "clave": f.clave,
            "nombre": f.nombre,
            "obligatoria": f.obligatoria,
            "por_defecto": f.por_defecto,
        }
        for f in filas
    ]


@router_preferencias.get(
    "",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="El centro de preferencias de una persona",
    description=(
        "Las categorías obligatorias salen **marcadas como tales y no como una "
        "casilla apagada**: enseñar una casilla que no se puede desmarcar se lee "
        "como un engaño, y decir «esto no se puede quitar porque es tu factura» se "
        "entiende."
    ),
)
def centro(db: DbDep, principal: AutenticadoDep, email: str = Query(...)) -> Any:
    return cor.centro_de_preferencias(db, principal.tenant_id, email)


class FijarPreferencias(BaseModel):
    email: str = Field(..., min_length=3)
    elecciones: dict[str, bool]
    origen: str = "centro"


@router_preferencias.put(
    "",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Guardar lo que ha elegido",
    description=(
        "Una categoría obligatoria **no se puede apagar**, y se dice cuál se ha "
        "ignorado en vez de fingir que se guardó: dejar creer que se apagó el "
        "aviso de facturación produce la queja de que «sigo recibiendo lo que "
        "quité».\n\n"
        "Darse de baja no puede ser todo o nada: quien solo quiere dejar la "
        "newsletter y encuentra un botón que le saca de todo marca el correo como "
        "basura, y eso no se deshace."
    ),
)
def fijar(datos: FijarPreferencias, request: Request, uow: UowDep) -> Any:
    return cor.fijar_preferencias(
        uow,
        email=datos.email,
        elecciones=datos.elecciones,
        origen=datos.origen,
        ip=request.client.host if request.client else "",
    )


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router,
    modelo=Recorrido,
    objeto="recorrido",
    permiso="campana:read",
    nombre="Recorridos",
)


ROUTERS_RECORRIDOS = [router, router_correo, router_preferencias]


# ── Fichas: ver, editar y borrar ──────────────────────────────────────────
# De los veintidós recursos que el front deja crear, uno solo se podía abrir,
# editar y borrar. Estos no tenían ni ficha: se creaban y no había forma de
# volver a verlos —ni de corregir una errata— desde ninguna pantalla.
montar_ficha(
    router_correo,
    modelo=PlantillaMarketing,
    objeto="plantilla_correo_marketing",
    permiso_leer="marketing:read",
    permiso_escribir="marketing:write",
    nombre="Plantillas de correo",
    ruta="/plantillas",
    parametro="registro_id",
)
montar_ficha(
    router_correo,
    modelo=BloqueCorreo,
    objeto="bloque_correo",
    permiso_leer="marketing:read",
    permiso_escribir="marketing:write",
    nombre="Bloques de correo",
    ruta="/bloques",
    parametro="registro_id",
)
montar_ficha(
    router_preferencias,
    modelo=CategoriaPreferencia,
    objeto="categoria_preferencia",
    permiso_leer="marketing:read",
    permiso_escribir="marketing:write",
    nombre="Categorías de preferencia",
    ruta="/categorias",
    parametro="registro_id",
)
