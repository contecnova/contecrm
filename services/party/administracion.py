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

from crmcore.authz.decision import exigir
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
    exigir(db, objeto="contacto", accion="delete", registro=contacto)
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
        campos=_campos_propios(db, "cuenta", fila),
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
    _rellenar_campos_propios(db, "cuenta", cuenta, fila)
    return cuenta


def _campos_propios(db: Session, objeto: str, fila: dict[str, Any]) -> dict[str, Any]:
    """Los campos propios del tenant que trae la fila, validados (CRM-00.04.03.08).

    `importar` ya los ha recogido en `fila["campos"]` a partir de las columnas
    que casan con el esquema publicado; aquí se validan con la misma regla que
    un alta de una en una. Sin esto se tiraban: el plan los separaba y nadie los
    escribía.
    """
    from crmcore import metamodelo

    propios = fila.get("campos")
    if not propios:
        return {}
    return metamodelo.validar_y_anotar(db, _tenant_de(db), objeto, propios)


def _rellenar_campos_propios(db: Session, objeto: str, registro: Any, fila: dict[str, Any]) -> None:
    """Rellena huecos en los campos propios, sin pisar los que ya tienen valor."""
    from crmcore import metamodelo

    propios = fila.get("campos")
    if not propios:
        return
    validos = metamodelo.validar_y_anotar(db, _tenant_de(db), objeto, propios, parcial=True)
    actuales = dict(registro.campos or {})
    nuevos = {k: v for k, v in validos.items() if actuales.get(k) in (None, "")}
    if nuevos:
        registro.campos = {**actuales, **nuevos}


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
    modelo=Cuenta,
    columnas=(
        "nombre",
        "nif",
        "tipo_nif",
        "pais",
        "email",
        "telefono",
        "web",
        "sector_esquema",
        "sector_codigo",
    ),
)


# ── Importación de contactos ──────────────────────────────────────────────


def _validar_contacto(fila: dict[str, Any]) -> list[str]:
    errores: list[str] = []
    if not str(fila.get("nombre", "")).strip():
        errores.append("«nombre» es obligatorio")
    for campo in ("email", "email_secundario"):
        correo = str(fila.get(campo, "")).strip()
        if correo and "@" not in correo:
            errores.append(f"«{correo}» no parece una dirección de correo")
    return errores


def _buscar_contacto(db: Session, fila: dict[str, Any]) -> Contacto | None:
    """Por correo y sólo por correo: dos personas no comparten buzón.

    Por nombre no, a propósito: «Ana García» hay muchas, y una importación que
    actualizara por nombre pisaría la ficha de otra persona sin que nada
    fallara.
    """
    correo = norm.normalizar_email(str(fila.get("email", "")))
    if not correo:
        return None
    return (
        db.execute(
            select(Contacto).where(
                Contacto.email == correo,
                Contacto.deleted_at.is_(None),
                Contacto.fusionado_en_id.is_(None),
            )
        )
        .scalars()
        .first()
    )


def _crear_contacto(db: Session, fila: dict[str, Any]) -> Contacto:
    nombre = str(fila["nombre"]).strip()
    apellidos = str(fila.get("apellidos", "")).strip() or None
    contacto = Contacto(
        tenant_id=_tenant_de(db),
        nombre=nombre,
        apellidos=apellidos,
        nombre_completo=" ".join(p for p in (nombre, apellidos or "") if p),
        clave_canonica=norm.clave_canonica_persona(nombre, apellidos),
        email=norm.normalizar_email(str(fila.get("email", ""))) or None,
        email_secundario=norm.normalizar_email(str(fila.get("email_secundario", ""))) or None,
        telefono=norm.normalizar_telefono(str(fila.get("telefono", ""))) or None,
        movil=norm.normalizar_telefono(str(fila.get("movil", ""))) or None,
        cargo=str(fila.get("cargo", "")).strip() or None,
        departamento=str(fila.get("departamento", "")).strip() or None,
        idioma=str(fila.get("idioma", "")).strip() or None,
        campos=_campos_propios(db, "contacto", fila),
    )
    db.add(contacto)
    db.flush()
    return contacto


def _actualizar_contacto(db: Session, contacto: Contacto, fila: dict[str, Any]) -> Contacto:
    """Rellena huecos, no pisa: lo mismo que con las cuentas."""
    for campo in ("telefono", "movil"):
        valor = norm.normalizar_telefono(str(fila.get(campo, "")))
        if valor and not getattr(contacto, campo, None):
            setattr(contacto, campo, valor)
    for campo in ("cargo", "departamento", "idioma", "apellidos"):
        valor = str(fila.get(campo, "")).strip()
        if valor and not getattr(contacto, campo, None):
            setattr(contacto, campo, valor)
    _rellenar_campos_propios(db, "contacto", contacto, fila)
    return contacto


PLAN_CONTACTOS = PlanImportacion(
    objeto="contacto",
    validar=_validar_contacto,
    buscar_existente=_buscar_contacto,
    crear=_crear_contacto,
    actualizar=_actualizar_contacto,
    columnas_obligatorias=("nombre",),
    modelo=Contacto,
    columnas=(
        "nombre",
        "apellidos",
        "email",
        "email_secundario",
        "telefono",
        "movil",
        "cargo",
        "departamento",
        "idioma",
    ),
)

# Qué se puede importar desde la pantalla, y con qué plan.
PLANES: dict[str, PlanImportacion] = {"cuenta": PLAN_CUENTAS, "contacto": PLAN_CONTACTOS}
MODELOS_IMPORTABLES: dict[str, type] = {"cuenta": Cuenta, "contacto": Contacto}


def importar_cuentas(
    db: Session, filas: list[dict[str, Any]], *, simular: bool = True, actualizar: bool = False
) -> Informe:
    return importar(db, filas, PLAN_CUENTAS, simular=simular, actualizar_existentes=actualizar)


def plan_de(objeto: str, tenant_id: UUID) -> PlanImportacion:
    """El plan del objeto, con el tenant puesto para que lea sus campos propios."""
    from dataclasses import replace

    from crmcore.errors import ErrorValidacion

    plan = PLANES.get(objeto)
    if plan is None:
        raise ErrorValidacion(
            f"No se puede importar «{objeto}»",
            error_code="importacion.objeto_no_admitido",
            detalle={"admitidos": sorted(PLANES)},
        )
    return replace(plan, tenant_id=tenant_id)


def campos_importables(db: Session, tenant_id: UUID, objeto: str) -> dict[str, Any]:
    """A qué campos se puede llevar cada columna del fichero: los de serie y los
    propios del tenant (CRM-00.04.03.08)."""
    from crmcore import metamodelo

    plan = plan_de(objeto, tenant_id)
    propios = [
        {
            "nombre": str(c.get("nombre")),
            "titulo": str(c.get("etiqueta") or c.get("titulo") or c.get("nombre")),
            "tipo": str(c.get("tipo") or "texto"),
            "obligatorio": bool(c.get("obligatorio")),
            "propio": True,
        }
        for c in metamodelo.campos_de(db, tenant_id, objeto)
        if c.get("activo", True) and c.get("nombre")
    ]
    return {
        "objeto": objeto,
        "campos": [
            {
                "nombre": c,
                "titulo": c,
                "tipo": "texto",
                "obligatorio": c in plan.columnas_obligatorias,
                "propio": False,
            }
            for c in plan.columnas
        ]
        + propios,
    }


def importar_objeto(
    db: Session,
    *,
    tenant_id: UUID,
    objeto: str,
    filas: list[dict[str, Any]],
    simular: bool,
    actualizar: bool,
    fichero: str = "",
    por: UUID | None = None,
) -> dict[str, Any]:
    """Importa —o simula— y, si escribe, guarda la importación para revertirla."""
    from crmcore.datos import importaciones

    registro: list[dict[str, Any]] = []
    informe = importar(
        db,
        filas,
        plan_de(objeto, tenant_id),
        simular=simular,
        actualizar_existentes=actualizar,
        registro=None if simular else registro,
    )
    salida = informe.a_dict()
    if not simular:
        guardada = importaciones.guardar(
            db,
            tenant_id=tenant_id,
            objeto=objeto,
            fichero=fichero,
            por=por,
            informe=informe,
            registros=registro,
        )
        salida["importacion"] = importaciones.a_dict(guardada)
    return salida


def revertir_importacion(
    db: Session,
    importacion_id: UUID,
    *,
    simular: bool,
    forzar: bool,
    por: UUID | None,
    motivo: str,
) -> dict[str, Any]:
    """Deshace una importación: lo creado a la papelera —con su cascada—, lo
    actualizado a su valor anterior."""
    from crmcore.datos import importaciones

    return importaciones.revertir(
        db,
        importacion_id,
        modelos=MODELOS_IMPORTABLES,
        borrar={
            "cuenta": lambda sesion, i: borrar_cuenta(sesion, i, por=por),
            "contacto": lambda sesion, i: borrar_contacto(sesion, i, por=por),
        },
        simular=simular,
        forzar=forzar,
        por=por,
        motivo=motivo,
    )
