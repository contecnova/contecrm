"""Superficie de administración del servicio `party`.

Papelera, importación masiva y transferencia de propiedad. Cada servicio expone
la suya sobre **sus** objetos, y no hay una consola central que escriba en todas
las bases: eso rompería la propiedad exclusiva de datos y, de hecho, los
permisos de base de datos lo impiden. La consola de administración
(CRM-07.01.01.01) es un consumidor de estas APIs, como cualquier otro cliente.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.datos.masivas import Informe, PlanImportacion, importar, transferir_propiedad
from crmcore.datos.papelera import Cascada, EntradaPapelera, borrar, purgar, restaurar
from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.party import normalizacion as norm
from services.party.modelos import (
    Actividad,
    Contacto,
    Cuenta,
    IdentificadorFiscal,
)

logger = get_logger(__name__)

# Qué se marca en cascada al borrar. Se declara aquí, en un solo sitio: una tabla
# nueva que cuelgue de la cuenta y no esté en esta lista sobreviviría al borrado
# y quedaría huérfana — visible en listados, apuntando a algo que ya no está.
#
# Solo entra lo que tiene **borrado reversible propio**. Las direcciones y los
# identificadores fiscales se van con la cuenta por clave foránea en cascada y
# vuelven con ella; las actividades tienen vida propia y hay que poder
# devolverlas exactamente a las que se fueron.
CASCADA_CUENTA: tuple[Cascada, ...] = (Cascada(Actividad, "cuenta_id"),)
CASCADA_CONTACTO: tuple[Cascada, ...] = (Cascada(Actividad, "contacto_id"),)

# Modelos que la papelera sabe restaurar, por nombre de tabla.
MODELOS: dict[str, type] = {
    "cuenta": Cuenta,
    "contacto": Contacto,
    "actividad": Actividad,
    "cuentas": Cuenta,
    "contactos": Contacto,
    "actividades": Actividad,
}

# Objetos de este servicio que tienen propietario y por tanto se transfieren.
MODELOS_CON_PROPIETARIO: list[type] = [Cuenta, Contacto, Actividad]


# ── Papelera ──────────────────────────────────────────────────────────────


def borrar_cuenta(db: Session, cuenta_id: UUID, *, por: UUID | None = None) -> EntradaPapelera:
    from services.party.servicio import _cuenta

    cuenta = _cuenta(db, cuenta_id)
    return borrar(
        db, cuenta, objeto="cuenta", etiqueta=cuenta.nombre, cascadas=CASCADA_CUENTA, por=por
    )


def borrar_contacto(db: Session, contacto_id: UUID, *, por: UUID | None = None) -> EntradaPapelera:
    from crmcore.errors import NoEncontrado

    contacto = db.get(Contacto, contacto_id)
    if contacto is None:
        raise NoEncontrado("El contacto no existe", error_code="party.contacto_no_encontrado")
    return borrar(
        db,
        contacto,
        objeto="contacto",
        etiqueta=contacto.nombre_completo,
        cascadas=CASCADA_CONTACTO,
        por=por,
    )


def listar_papelera(
    db: Session, tenant_id: UUID, *, objeto: str = "", limite: int = 50
) -> list[dict[str, Any]]:
    consulta = select(EntradaPapelera).where(
        EntradaPapelera.tenant_id == tenant_id,
        EntradaPapelera.restaurado_at.is_(None),
        EntradaPapelera.purgado_at.is_(None),
    )
    if objeto:
        consulta = consulta.where(EntradaPapelera.objeto == objeto)
    filas = (
        db.execute(consulta.order_by(EntradaPapelera.borrado_at.desc()).limit(limite))
        .scalars()
        .all()
    )
    from datetime import datetime, timezone

    ahora = datetime.now(timezone.utc)
    return [
        {
            "id": str(f.id),
            "objeto": f.objeto,
            "registro_id": str(f.registro_id),
            "etiqueta": f.etiqueta,
            "borrado_at": f.borrado_at.isoformat(),
            "purgable_at": f.purgable_at.isoformat(),
            # Días que quedan para que sea irrecuperable. Es el dato que importa
            # a quien mira la papelera buscando algo que borró sin querer.
            "dias_para_purga": (f.purgable_at - ahora).days,
            "en_cascada": sum(len(v) for v in (f.cascada or {}).values()),
        }
        for f in filas
    ]


def restaurar_entrada(db: Session, entrada_id: UUID, *, por: UUID | None = None) -> EntradaPapelera:
    return restaurar(db, entrada_id, modelos=MODELOS, por=por)


def purgar_vencidos(db: Session, tenant_id: UUID, *, motivo: str) -> dict[str, int]:
    return purgar(db, tenant_id=tenant_id, modelos=MODELOS, motivo=motivo)


# ── Transferencia de propiedad ────────────────────────────────────────────


def transferir(
    db: Session,
    *,
    tenant_id: UUID,
    de_usuario: UUID,
    a_usuario: UUID,
    motivo: str,
    simular: bool = False,
) -> dict[str, int]:
    """Mueve cuentas, contactos y actividades de un propietario a otro."""
    return transferir_propiedad(
        db,
        tenant_id=tenant_id,
        modelos=MODELOS_CON_PROPIETARIO,
        de_usuario=de_usuario,
        a_usuario=a_usuario,
        motivo=motivo,
        simular=simular,
    )


# ── Importación de cuentas ────────────────────────────────────────────────


def _validar_cuenta(fila: dict[str, Any]) -> list[str]:
    errores: list[str] = []
    if not str(fila.get("nombre", "")).strip():
        errores.append("«nombre» es obligatorio")
    nif = str(fila.get("nif", "")).strip()
    if nif and str(fila.get("pais", "ES")).upper() == "ES" and not norm.validar_nif_es(nif):
        errores.append(f"«{nif}» no es un NIF, NIE o CIF español válido")
    correo = str(fila.get("email", "")).strip()
    if correo and "@" not in correo:
        errores.append(f"«{correo}» no parece una dirección de correo")
    return errores


def _buscar_cuenta(db: Session, fila: dict[str, Any]) -> Cuenta | None:
    """Busca por identificador fiscal y, si no, por clave canónica.

    Por identificador primero porque es la única señal concluyente: dos filas
    con el mismo NIF son la misma entidad aunque el nombre esté escrito distinto.
    """
    nif = norm.normalizar_identificador_fiscal(str(fila.get("nif", "")))
    if nif:
        encontrada = db.execute(
            select(Cuenta)
            .join(IdentificadorFiscal, IdentificadorFiscal.cuenta_id == Cuenta.id)
            .where(
                IdentificadorFiscal.valor_normalizado == nif,
                Cuenta.deleted_at.is_(None),
                Cuenta.fusionada_en_id.is_(None),
            )
        ).scalar_one_or_none()
        if encontrada is not None:
            return encontrada

    clave = norm.clave_canonica_empresa(str(fila.get("nombre", "")))
    if not clave:
        return None
    return db.execute(
        select(Cuenta).where(
            Cuenta.clave_canonica == clave,
            Cuenta.deleted_at.is_(None),
            Cuenta.fusionada_en_id.is_(None),
        )
    ).scalar_one_or_none()


def _crear_cuenta(db: Session, fila: dict[str, Any]) -> Cuenta:
    nombre = str(fila["nombre"]).strip()
    cuenta = Cuenta(
        tenant_id=_tenant_de(db),
        nombre=nombre,
        clave_canonica=norm.clave_canonica_empresa(nombre),
        email=norm.normalizar_email(str(fila.get("email", ""))) or None,
        telefono=norm.normalizar_telefono(str(fila.get("telefono", ""))) or None,
        web=str(fila.get("web", "")) or None,
        dominio=norm.dominio_de(str(fila.get("email", "")))
        or norm.dominio_de(str(fila.get("web", "")))
        or None,
        sector_esquema=str(fila.get("sector_esquema", "")) or None,
        sector_codigo=str(fila.get("sector_codigo", "")) or None,
    )
    db.add(cuenta)
    db.flush()

    nif = str(fila.get("nif", "")).strip()
    if nif:
        db.add(
            IdentificadorFiscal(
                tenant_id=cuenta.tenant_id,
                cuenta_id=cuenta.id,
                tipo=str(fila.get("tipo_nif", "cif")),
                pais=str(fila.get("pais", "ES")).upper(),
                valor=nif,
                valor_normalizado=norm.normalizar_identificador_fiscal(nif),
                principal=True,
            )
        )
    return cuenta


def _actualizar_cuenta(db: Session, cuenta: Cuenta, fila: dict[str, Any]) -> Cuenta:
    """Rellena huecos, **no** pisa lo que ya hay.

    Una importación que sobrescribe deja el maestro a merced del último fichero
    que alguien subió, que casi nunca es el más completo. Para sobrescribir a
    propósito está la edición, que deja historial campo a campo.
    """
    for destino, origen in (
        ("email", "email"),
        ("telefono", "telefono"),
        ("web", "web"),
        ("sector_codigo", "sector_codigo"),
    ):
        valor = str(fila.get(origen, "")).strip()
        if valor and not getattr(cuenta, destino, None):
            setattr(cuenta, destino, valor)
    return cuenta


def _tenant_de(db: Session) -> UUID:
    """Tenant al que pertenece lo que se está importando.

    Primero la sesión —que es la fuente autoritativa y de donde salen RLS y el
    guard— y, si es de sistema, el contexto. Esa segunda vía es la que permite
    que una importación corra igual desde una petición que desde un trabajo de
    fondo, donde la sesión es de sistema pero el tenant sí se conoce.
    """
    from crmcore.errors import ErrorValidacion
    from crmcore.tenancy.context import contexto_actual

    tenant_id = db.info.get("tenant_id") or contexto_actual().tenant_id
    if tenant_id is None:
        raise ErrorValidacion(
            "No se sabe a qué tenant pertenece la importación",
            error_code="party.sin_tenant",
        )
    return tenant_id


PLAN_CUENTAS = PlanImportacion(
    objeto="cuenta",
    validar=_validar_cuenta,
    buscar_existente=_buscar_cuenta,
    crear=_crear_cuenta,
    actualizar=_actualizar_cuenta,
    columnas_obligatorias=("nombre",),
)


def importar_cuentas(
    db: Session, filas: list[dict[str, Any]], *, simular: bool = True, actualizar: bool = False
) -> Informe:
    return importar(db, filas, PLAN_CUENTAS, simular=simular, actualizar_existentes=actualizar)
