"""Calidad del dato sobre los datos reales (09-11-2026).

CRM-01.01.04.06 golden record guardado con su procedencia · CRM-01.01.01.08
enriquecimiento por el conector · CRM-01.01.05.02 identidad entre canales con
las señales reales · CRM-01.01.04.02 umbral por objeto · CRM-01.01.04.04
direcciones normalizadas.

Lo que había —`POST /calidad-dato/golden`, `/enriquecimiento/aplicar`— calcula
sobre lo que se teclea y sigue ahí para quien lo use así. Esto es lo que trabaja
sobre las fichas del CRM y guarda lo que decide.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.runtime import settings as rt
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.party import direcciones as dirs
from services.party import enriquecimiento as enr
from services.party import golden as gld
from services.party import identidad as idt

router = APIRouter(prefix="/calidad-dato", tags=["calidad del dato"])


# ── Golden record (CRM-01.01.04.06) ───────────────────────────────────────


class ReglaIn(BaseModel):
    estrategia: str = Field(..., examples=["mayor_confianza"])
    confianza_por_fuente: dict[str, int] = Field(
        default_factory=dict, examples=[{"erp": 90, "crm": 60, "fusionada": 30}]
    )
    activa: bool = True
    nota: str = Field("", max_length=1000)


class ComponerIn(BaseModel):
    aplicar: bool = Field(
        False,
        description=(
            "Falso: compone y guarda, sin tocar la ficha. Verdadero: además "
            "escribe en la ficha los valores ganadores"
        ),
    )


@router.get(
    "/golden/reglas/{objeto}",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Las reglas de supervivencia de un objeto",
    description=(
        "Por campo, con la confianza de cada fuente. El campo `*` es la regla por "
        "defecto del objeto. Devuelve también qué campos se pueden componer y "
        "qué estrategias hay, para que la pantalla no las tenga escritas."
    ),
)
def reglas_golden(objeto: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return gld.reglas(db, principal.tenant_id, objeto)


@router.put(
    "/golden/reglas/{objeto}/{campo}",
    dependencies=[Depends(exige_permiso("party:admin"))],
    summary="Guardar la regla de supervivencia de un campo",
    description=(
        "Es configuración del tenant: queda en la auditoría con quién la cambió. "
        "Una fuente que no aparece en la confianza vale 50."
    ),
)
def guardar_regla_golden(objeto: str, campo: str, cuerpo: ReglaIn, uow: UowDep) -> Any:
    return gld.guardar_regla(
        uow,
        objeto=objeto,
        campo=campo,
        estrategia=cuerpo.estrategia,
        confianza_por_fuente=cuerpo.confianza_por_fuente,
        activa=cuerpo.activa,
        nota=cuerpo.nota,
    )


@router.delete(
    "/golden/reglas/{objeto}/{campo}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("party:admin"))],
    summary="Quitar la regla de un campo (vuelve a la del objeto)",
)
def borrar_regla_golden(objeto: str, campo: str, uow: UowDep) -> None:
    datos = gld.reglas(uow.db, uow.tenant_id, objeto)  # type: ignore[arg-type]
    for regla in datos["reglas"]:
        if regla["campo"] == campo:
            gld.borrar_regla(uow, UUID(regla["id"]))
            return
    from crmcore.errors import NoEncontrado

    raise NoEncontrado("Ese campo no tiene regla propia", error_code="golden.regla_no_encontrada")


@router.get(
    "/golden/candidatas",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Fichas con más de una versión de la verdad",
    description=(
        "Las que tienen fichas fusionadas o unidas por identidad: es donde varias "
        "fuentes dicen cosas distintas del mismo cliente. Componer una ficha con "
        "una sola fuente devuelve lo que ya tiene."
    ),
)
def golden_candidatas(
    db: DbDep, principal: AutenticadoDep, limite: int = Query(50, ge=1, le=200)
) -> Any:
    return gld.con_varias_versiones(db, principal.tenant_id, limite=limite)


@router.post(
    "/golden/{objeto}/{objeto_id}/componer",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Componer —y guardar— la ficha buena de un registro real",
    description=(
        "Los candidatos salen del CRM: el linaje anotado de la ficha, lo que "
        "tiene hoy, la foto de cada ficha fusionada en ella y, en contactos, cada "
        "ficha unida por identidad. Se aplican las reglas guardadas y el "
        "resultado se **guarda** con la procedencia de cada valor. Con "
        "`aplicar` se escribe además en la ficha, con el antes en la auditoría."
    ),
)
def componer_golden(
    objeto: str, objeto_id: UUID, cuerpo: ComponerIn, uow: UowDep, principal: AutenticadoDep
) -> Any:
    return gld.componer(
        uow, objeto=objeto, objeto_id=objeto_id, aplicar=cuerpo.aplicar, por=principal.id
    )


@router.get(
    "/golden/{objeto}/{objeto_id}",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="El golden record guardado de un registro",
)
def golden_guardado(objeto: str, objeto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return gld.guardado(db, principal.tenant_id, objeto=objeto, objeto_id=objeto_id)


# ── Enriquecimiento (CRM-01.01.01.08) ─────────────────────────────────────


class PerfilIn(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=150)
    objeto: str = Field("cuenta", examples=["cuenta"])
    conexion_id: UUID
    operacion: str = Field(..., min_length=1, max_length=80)
    parametros: dict[str, str] = Field(
        default_factory=dict,
        description="Parámetro de la operación → campo de la ficha que lo rellena",
        examples=[{"dominio": "dominio"}],
    )
    mapeo: dict[str, str] = Field(
        default_factory=dict,
        description="Campo de la ficha → campo del registro devuelto (admite a.b)",
        examples=[{"sector": "industria", "web": "sitio"}],
    )
    confianza: int = Field(40, ge=0, le=100)
    coste_por_consulta: float = Field(0.0, ge=0)
    activo: bool = True


class PedirIn(BaseModel):
    objeto_ids: list[UUID] = Field(..., min_length=1)


class AplicarPropuestaIn(BaseModel):
    campos: list[str] | None = Field(
        None, description="Qué campos se aplican. Sin decirlo, sólo los huecos"
    )


@router.get(
    "/enriquecimiento/perfiles",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Los proveedores de enriquecimiento declarados",
)
def perfiles_enriquecimiento(db: DbDep, principal: AutenticadoDep) -> Any:
    return enr.perfiles(db, principal.tenant_id)


@router.put(
    "/enriquecimiento/perfiles/{clave}",
    dependencies=[Depends(exige_permiso("party:admin"))],
    summary="Declarar un proveedor de enriquecimiento sobre el conector",
    description=(
        "Qué conexión y qué operación de `integration` se llaman, con qué campos "
        "de la ficha se rellenan sus parámetros y qué campo de la respuesta va a "
        "qué campo del CRM. Ningún proveedor tiene código: es configuración."
    ),
)
def guardar_perfil_enriquecimiento(clave: str, cuerpo: PerfilIn, uow: UowDep) -> Any:
    return enr.guardar_perfil(uow, clave=clave, **cuerpo.model_dump())


@router.delete(
    "/enriquecimiento/perfiles/{clave}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("party:admin"))],
    summary="Quitar un proveedor de enriquecimiento",
)
def borrar_perfil_enriquecimiento(clave: str, uow: UowDep) -> None:
    enr.borrar_perfil(uow, clave)


@router.post(
    "/enriquecimiento/{perfil}/pedir",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Preguntar al proveedor por unas fichas",
    description=(
        "Llama al proveedor por el conector, con la identidad de quien pide, y "
        "guarda lo que contesta como **propuesta**: lo que rellena un hueco y lo "
        "que contradice a la ficha, por separado. No escribe en la ficha."
    ),
)
def pedir_enriquecimiento(
    perfil: str, cuerpo: PedirIn, uow: UowDep, principal: AutenticadoDep
) -> Any:
    return enr.pedir(uow, principal, perfil=perfil, objeto_ids=cuerpo.objeto_ids)


@router.get(
    "/enriquecimiento/propuestas",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Lo que han contestado los proveedores, por revisar",
)
def propuestas_enriquecimiento(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query("pendiente"),
    limite: int = Query(100, ge=1, le=500),
) -> Any:
    return enr.propuestas(db, principal.tenant_id, estado=estado or None, limite=limite)


@router.post(
    "/enriquecimiento/propuestas/{propuesta_id}/aplicar",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Aplicar a la ficha lo elegido de una propuesta",
    description=(
        "Sin elegir, sólo los huecos: un proveedor rellena lo que falta y no "
        "corrige a quien habló con el cliente. Cada valor queda en el linaje con "
        "el perfil como fuente."
    ),
)
def aplicar_propuesta(
    propuesta_id: UUID, cuerpo: AplicarPropuestaIn, uow: UowDep, principal: AutenticadoDep
) -> Any:
    return enr.aplicar(uow, propuesta_id=propuesta_id, campos=cuerpo.campos, por=principal.id)


@router.post(
    "/enriquecimiento/propuestas/{propuesta_id}/descartar",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Descartar una propuesta del proveedor",
)
def descartar_propuesta(propuesta_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    return enr.descartar(uow, propuesta_id=propuesta_id, por=principal.id)


# ── Identidad entre canales (CRM-01.01.05.02) ─────────────────────────────


class ObservarIn(BaseModel):
    tipo: str = Field(..., examples=["cookie"])
    valor: str = Field(..., min_length=1, max_length=500)
    contacto_id: UUID | None = None
    origen: str = Field("", max_length=40, examples=["web"])


class ResolverIn(BaseModel):
    senales: list[dict[str, str]] = Field(..., min_length=1)


class UnirIn(BaseModel):
    principal_id: UUID
    secundario_id: UUID
    senales: list[dict[str, Any]] = Field(default_factory=list)
    puntuacion: int = Field(0, ge=0)


class DeshacerIn(BaseModel):
    principal_id: UUID
    secundario_id: UUID
    motivo: str = Field(..., min_length=1, max_length=1000)


@router.post(
    "/identidades/observar",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Anotar una señal vista en un canal",
    description=(
        "Lo llama quien la ve: la web con su cookie, la app con su "
        "identificador, el conector del ERP, la captura de una interacción "
        "entrante. Sin `contacto_id` se guarda suelta, y se resuelve cuando "
        "otra señal la ate a alguien. Las de la ficha —correo, teléfono, "
        "canales— se anotan solas al guardarla."
    ),
)
def observar_senal(cuerpo: ObservarIn, uow: UowDep) -> Any:
    fila = idt.observar(
        uow,
        tipo=cuerpo.tipo,
        valor=cuerpo.valor,
        contacto_id=cuerpo.contacto_id,
        origen=cuerpo.origen,
    )
    return {"tipo": fila.tipo, "pista": fila.pista, "veces": fila.veces}


@router.post(
    "/identidades/resolver",
    dependencies=[Depends(exige_permiso("contact:read"))],
    summary="A quién corresponden estas señales, y con qué confianza",
)
def resolver_identidad(cuerpo: ResolverIn, db: DbDep, principal: AutenticadoDep) -> Any:
    return idt.resolver(db, principal.tenant_id, senales=cuerpo.senales)


@router.post(
    "/identidades/barrer",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Anotar las señales de los contactos que ya estaban",
    description=(
        "Una vez: lo que entra desde hoy se anota solo al guardar. Repetible sin " "duplicar."
    ),
)
def barrer_identidades(uow: UowDep, limite: int = Query(2000, ge=1, le=20000)) -> Any:
    return idt.barrer(uow, limite=limite)


@router.get(
    "/identidades/propuestas",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="Contactos que parecen la misma persona, con sus nombres",
)
def propuestas_identidad(
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    from services.party.modelos import Contacto

    datos = idt.proponer_uniones(db, principal.tenant_id, limite=limite)
    for p in datos["propuestas"]:
        for lado in ("a", "b"):
            fila = db.get(Contacto, UUID(p[lado]))
            p[f"{lado}_nombre"] = fila.nombre_completo if fila is not None else ""
    return datos


@router.post(
    "/identidades/unir",
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Declarar que dos contactos son la misma persona",
    description=(
        "Reversible y con rastro: no borra ninguna ficha. Resolver una señal de "
        "cualquiera de las dos lleva desde ahora al principal."
    ),
)
def unir_identidades(cuerpo: UnirIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = idt.unir(
        uow,
        principal_id=cuerpo.principal_id,
        secundario_id=cuerpo.secundario_id,
        senales=cuerpo.senales,
        puntuacion=cuerpo.puntuacion,
        modo="manual",
        por=principal.id,
    )
    return {
        "principal_id": str(fila.principal_id),
        "secundario_id": str(fila.secundario_id),
        "modo": fila.modo,
    }


@router.post(
    "/identidades/deshacer",
    dependencies=[Depends(exige_permiso("contact:write"))],
    summary="Deshacer una unión, con motivo",
)
def deshacer_union(cuerpo: DeshacerIn, uow: UowDep) -> Any:
    fila = idt.deshacer(
        uow,
        principal_id=cuerpo.principal_id,
        secundario_id=cuerpo.secundario_id,
        motivo=cuerpo.motivo,
    )
    return {"deshecha_at": fila.deshecha_at.isoformat() if fila.deshecha_at else None}


# ── Umbral por objeto (CRM-01.01.04.02) ───────────────────────────────────


class UmbralesIn(BaseModel):
    por_objeto: dict[str, dict[str, float]] = Field(
        ..., examples=[{"contacto": {"sugerencia": 0.9, "propuesta": 0.85}}]
    )


@router.get(
    "/umbrales-duplicado",
    dependencies=[Depends(exige_permiso("party:read"))],
    summary="El umbral de coincidencia que vale ahora para cada objeto",
)
def umbrales_duplicado(db: DbDep, _: AutenticadoDep) -> Any:
    from services.party.duplicados import umbrales_por_objeto

    return umbrales_por_objeto(db)


@router.put(
    "/umbrales-duplicado",
    dependencies=[Depends(exige_permiso("party:admin"))],
    summary="Fijar el umbral de coincidencia por objeto",
    description=(
        "Lo que no se diga para un objeto sale del umbral general. Queda en el "
        "histórico de ajustes con quién lo cambió."
    ),
)
def fijar_umbrales(cuerpo: UmbralesIn, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.errors import ErrorValidacion

    from services.party.duplicados import _UMBRAL_GENERAL, umbrales_por_objeto

    limpio: dict[str, dict[str, float]] = {}
    for objeto, umbrales in cuerpo.por_objeto.items():
        if objeto not in ("cuenta", "contacto"):
            raise ErrorValidacion(
                f"«{objeto}» no tiene detección de duplicados aquí.",
                error_code="duplicados.objeto_no_valido",
            )
        for tipo, valor in umbrales.items():
            if tipo not in _UMBRAL_GENERAL or not 0.0 <= float(valor) <= 1.0:
                raise ErrorValidacion(
                    "Cada umbral es sugerencia, bloqueo o propuesta, entre 0 y 1.",
                    error_code="duplicados.umbral_no_valido",
                    detalle={"objeto": objeto, "tipo": tipo},
                )
        if umbrales:
            limpio[objeto] = {k: float(v) for k, v in umbrales.items()}
    rt.fijar(
        db,
        "dedupe_umbral_por_objeto",
        limpio,
        ambito="tenant",
        ambito_id=str(principal.tenant_id),
        por=principal.id,
    )
    return umbrales_por_objeto(db)


# ── Direcciones (CRM-01.01.04.04) ─────────────────────────────────────────


@router.post(
    "/direcciones/normalizar",
    dependencies=[Depends(exige_permiso("party:write"))],
    summary="Normalizar las direcciones guardadas",
    description=(
        "Sin `aplicar` dice qué cambiaría y no toca nada; con `aplicar` lo "
        "escribe y deja el antes en la auditoría. Lo que entra desde hoy se "
        "normaliza solo al guardarlo."
    ),
)
def normalizar_direcciones(
    uow: UowDep,
    aplicar: bool = Query(False),
    limite: int = Query(500, ge=1, le=5000),
    objeto: str | None = Query(None),
    objeto_id: UUID | None = Query(None),
) -> Any:
    return dirs.barrido(uow, aplicar=aplicar, limite=limite, objeto=objeto, objeto_id=objeto_id)


ROUTERS_CALIDAD_REAL = [router]
