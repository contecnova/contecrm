"""Segundo factor verificado por el proveedor del tenant (CRM-00.05.01.22).

Hasta el 09-11-2026 esto eran tres perfiles fijos —`otp_generico`,
`push_generico`, `webauthn`— que decían qué operaciones tiene un proveedor y no
llamaban a ninguno. Una empresa con Okta Verify, Duo, Twilio Verify o RSA
SecurID no tenía forma de que el código de su aplicación sirviera para entrar.

Un proveedor es aquí **un perfil declarado**, igual que los canales de SMS y
push o las reuniones de la suite: a qué URL se llama, con qué método y qué
autenticación, cómo es el cuerpo y dónde dice la respuesta si el código vale.
No hay una línea de código de ningún proveedor; las cuatro plantillas de
`plantillas_mfa_proveedor.json` son datos que rellenan el formulario.

Tres decisiones:

**El secreto no sale nunca.** Se guarda cifrado con el propósito de los
proveedores de identidad y la API sólo dice si lo hay. «Probar» enseña la
petición que se mandaría con el secreto tapado.

**Lo que no se puede rellenar no se manda.** Una marca sin valor —el teléfono
de alguien que no lo tiene apuntado— corta antes de llamar: mandar
`{{persona.telefono}}` literal al proveedor da un «código incorrecto» que manda
a buscar el fallo en el código y no en la ficha.

**Si el proveedor no contesta, no se entra.** Un segundo factor que se salta
cuando su verificador está caído no es un segundo factor. Lo que sí sigue
valiendo es lo local —el TOTP propio y los códigos de recuperación—, que se
prueban antes y después en el login.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

from crmcore.audit import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, DateTime, Index, String, Text, UniqueConstraint, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# El mismo propósito que los secretos de los proveedores de SSO: es el mismo
# subsistema, y un propósito por pantalla multiplicaría las claves sin aislar
# nada que no esté ya aislado.
PROPOSITO = "idp"

METODOS = ("POST", "PUT", "GET")
FORMATOS = ("json", "form")
AUTENTICACIONES = ("ninguna", "basica", "bearer", "cabecera")

_MARCA = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
_FIJAS = ("codigo", "email", "usuario", "id_peticion")

RUTA_PLANTILLAS = Path(__file__).with_name("plantillas_mfa_proveedor.json")


class PerfilMfaProveedor(Base, TimestampMixin):
    """Cómo se le pregunta al proveedor de este tenant si un código vale."""

    __tablename__ = "perfiles_mfa_proveedor"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    # De qué plantilla salió. Informativo: el perfil manda, no la plantilla.
    plantilla: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    metodo: Mapped[str] = mapped_column(String(10), nullable=False, default="POST")
    formato: Mapped[str] = mapped_column(String(10), nullable=False, default="json")
    autenticacion: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    secreto: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="", info={"secreto": True}
    )
    cabeceras: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    cuerpo: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    variables: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    campos_persona: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    respuesta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    ultima_prueba_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultima_prueba: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "nombre", name="uq_perfil_mfa_proveedor_nombre"),
        Index("ix_perfiles_mfa_proveedor_tenant", "tenant_id", "activo"),
    )


class VinculoMfaProveedor(Base, TimestampMixin):
    """Quién es esta persona en el proveedor: su teléfono, su id de Okta…"""

    __tablename__ = "vinculos_mfa_proveedor"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    perfil_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    datos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    __table_args__ = (
        UniqueConstraint("perfil_id", "usuario_id", name="uq_vinculo_mfa_proveedor"),
        Index("ix_vinculos_mfa_proveedor_tenant", "tenant_id", "perfil_id"),
    )


# ── Plantillas ────────────────────────────────────────────────────────────


def plantillas() -> dict[str, dict[str, Any]]:
    """Las plantillas de perfil, leídas del fichero de datos."""
    crudo = json.loads(RUTA_PLANTILLAS.read_text(encoding="utf-8"))
    return {k: v for k, v in crudo.items() if not k.startswith("_")}


# ── Validación del perfil ─────────────────────────────────────────────────


def _marcas(valor: Any) -> set[str]:
    if isinstance(valor, dict):
        return set().union(*(_marcas(v) for v in valor.values())) if valor else set()
    if isinstance(valor, list):
        return set().union(*(_marcas(v) for v in valor)) if valor else set()
    if isinstance(valor, str):
        return set(_MARCA.findall(valor))
    return set()


def validar(datos: dict[str, Any]) -> dict[str, Any]:
    """Comprueba la forma del perfil y devuelve lo que se guarda.

    Las marcas se comprueban al guardar y no al entrar: una variable mal escrita
    descubierta en el login deja a toda la empresa fuera a la vez.
    """
    url = str(datos.get("url") or "").strip()
    if not url.startswith(("https://", "http://")):
        raise ErrorValidacion(
            "La URL del proveedor tiene que empezar por https:// (o http:// en una red propia)",
            error_code="mfa_proveedor.url_no_valida",
        )
    metodo = str(datos.get("metodo") or "POST").upper()
    if metodo not in METODOS:
        raise ErrorValidacion(
            f"Método «{metodo}» no admitido: {', '.join(METODOS)}",
            error_code="mfa_proveedor.metodo_no_valido",
        )
    formato = str(datos.get("formato") or "json")
    if formato not in FORMATOS:
        raise ErrorValidacion(
            f"Formato «{formato}» no admitido: {', '.join(FORMATOS)}",
            error_code="mfa_proveedor.formato_no_valido",
        )
    autenticacion = dict(datos.get("autenticacion") or {"tipo": "ninguna"})
    tipo = str(autenticacion.get("tipo") or "ninguna")
    if tipo not in AUTENTICACIONES:
        raise ErrorValidacion(
            f"Autenticación «{tipo}» no admitida: {', '.join(AUTENTICACIONES)}",
            error_code="mfa_proveedor.autenticacion_no_valida",
        )
    if tipo == "cabecera" and not str(autenticacion.get("cabecera") or "").strip():
        raise ErrorValidacion(
            "Con autenticación por cabecera hay que decir qué cabecera",
            error_code="mfa_proveedor.sin_cabecera",
        )
    variables = {str(k): str(v) for k, v in dict(datos.get("variables") or {}).items()}
    campos_persona = [
        str(c).strip() for c in list(datos.get("campos_persona") or []) if str(c).strip()
    ]
    respuesta = dict(datos.get("respuesta") or {})
    respuesta = {
        "campo": str(respuesta.get("campo") or "").strip(),
        "validos": [str(v) for v in list(respuesta.get("validos") or []) if str(v).strip()],
    }
    if respuesta["campo"] and not respuesta["validos"]:
        raise ErrorValidacion(
            "Si se dice en qué campo contesta el proveedor, hay que decir qué valores "
            "significan «el código vale»: sin ellos no valdría ninguno",
            error_code="mfa_proveedor.sin_valores_validos",
        )
    cuerpo = dict(datos.get("cuerpo") or {})
    cabeceras = {str(k): str(v) for k, v in dict(datos.get("cabeceras") or {}).items()}

    usadas = _marcas([url, cuerpo, cabeceras]) | _marcas(
        {k: v for k, v in autenticacion.items() if k != "tipo"}
    )
    conocidas = (
        set(_FIJAS) | {f"var.{v}" for v in variables} | {f"persona.{c}" for c in campos_persona}
    )
    secreto_fuera = "secreto" in _marcas([url, cuerpo, cabeceras])
    if secreto_fuera:
        raise ErrorValidacion(
            "{{secreto}} sólo puede ir en la autenticación: en la URL o en el cuerpo "
            "acabaría en los registros del proveedor y en los nuestros",
            error_code="mfa_proveedor.secreto_fuera_de_sitio",
        )
    desconocidas = sorted(usadas - conocidas - {"secreto"})
    if desconocidas:
        raise ErrorValidacion(
            f"Marcas que el perfil no sabe rellenar: {', '.join(desconocidas)}. "
            "Declara la variable o el dato de la persona, o corrige el nombre.",
            error_code="mfa_proveedor.marca_desconocida",
            detalle={"desconocidas": desconocidas},
        )
    if "codigo" not in usadas:
        raise ErrorValidacion(
            "El perfil no manda el código en ninguna parte: el proveedor no tendría "
            "qué comprobar",
            error_code="mfa_proveedor.sin_codigo",
        )
    return {
        "url": url,
        "metodo": metodo,
        "formato": formato,
        "autenticacion": autenticacion,
        "cabeceras": cabeceras,
        "cuerpo": cuerpo,
        "variables": variables,
        "campos_persona": campos_persona,
        "respuesta": respuesta,
    }


# ── Alta, cambio y baja ───────────────────────────────────────────────────


def a_dict(p: PerfilMfaProveedor) -> dict[str, Any]:
    """El perfil tal como sale por la API: el secreto, sólo si lo hay."""
    return {
        "id": str(p.id),
        "nombre": p.nombre,
        "plantilla": p.plantilla,
        "activo": p.activo,
        "url": p.url,
        "metodo": p.metodo,
        "formato": p.formato,
        "autenticacion": dict(p.autenticacion or {}),
        "tiene_secreto": bool(p.secreto),
        "cabeceras": dict(p.cabeceras or {}),
        "cuerpo": dict(p.cuerpo or {}),
        "variables": dict(p.variables or {}),
        "campos_persona": list(p.campos_persona or []),
        "respuesta": dict(p.respuesta or {}),
        "ultima_prueba_at": p.ultima_prueba_at.isoformat() if p.ultima_prueba_at else None,
        "ultima_prueba": dict(p.ultima_prueba or {}),
    }


def listar(db: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    filas = (
        db.execute(
            select(PerfilMfaProveedor)
            .where(PerfilMfaProveedor.tenant_id == tenant_id)
            .order_by(PerfilMfaProveedor.nombre)
        )
        .scalars()
        .all()
    )
    return [a_dict(f) for f in filas]


def _obtener(db: Session, tenant_id: UUID, perfil_id: UUID) -> PerfilMfaProveedor:
    fila = db.get(PerfilMfaProveedor, perfil_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("Ese perfil no existe", error_code="mfa_proveedor.no_encontrado")
    return fila


def activo_de(db: Session, tenant_id: UUID) -> PerfilMfaProveedor | None:
    return (
        db.execute(
            select(PerfilMfaProveedor).where(
                PerfilMfaProveedor.tenant_id == tenant_id, PerfilMfaProveedor.activo.is_(True)
            )
        )
        .scalars()
        .first()
    )


def _exigir_unico_activo(db: Session, tenant_id: UUID, perfil_id: UUID | None) -> None:
    """Uno activo por empresa: con dos, no se sabría a cuál preguntar."""
    otro = activo_de(db, tenant_id)
    if otro is not None and otro.id != perfil_id:
        raise Conflicto(
            f"Ya hay un proveedor de segundo factor activo («{otro.nombre}»). "
            "Desactívalo antes: con dos, el login no sabría a cuál preguntar.",
            error_code="mfa_proveedor.ya_hay_uno_activo",
            detalle={"activo": otro.nombre},
        )


def guardar(
    db: Session,
    tenant_id: UUID,
    datos: dict[str, Any],
    *,
    perfil_id: UUID | None = None,
) -> dict[str, Any]:
    """Crea o cambia un perfil. Un secreto vacío conserva el que había."""
    from crmcore.security.cifrado import cifrar

    nombre = str(datos.get("nombre") or "").strip()
    if not nombre:
        raise ErrorValidacion("El perfil necesita un nombre", error_code="mfa_proveedor.sin_nombre")
    limpio = validar(datos)
    activo = bool(datos.get("activo"))
    if activo:
        _exigir_unico_activo(db, tenant_id, perfil_id)

    if perfil_id is None:
        fila = PerfilMfaProveedor(tenant_id=tenant_id, nombre=nombre)
        db.add(fila)
        accion = "mfa_proveedor.creado"
    else:
        fila = _obtener(db, tenant_id, perfil_id)
        fila.nombre = nombre
        accion = "mfa_proveedor.cambiado"
    fila.plantilla = str(datos.get("plantilla") or fila.plantilla or "")[:60]
    fila.activo = activo
    for clave, valor in limpio.items():
        setattr(fila, clave, valor)
    secreto = str(datos.get("secreto") or "")
    if secreto:
        fila.secreto = cifrar(secreto, proposito=PROPOSITO, db=db)
    elif datos.get("quitar_secreto"):
        fila.secreto = ""
    db.flush()
    registrar(
        db,
        accion=accion,
        objeto="perfil_mfa_proveedor",
        objeto_id=fila.id,
        # Sin el secreto, ni cifrado: la auditoría la lee más gente que esta
        # pantalla.
        datos={
            "nombre": fila.nombre,
            "activo": fila.activo,
            "url": fila.url,
            "secreto_cambiado": bool(secreto),
        },
    )
    return a_dict(fila)


def borrar(db: Session, tenant_id: UUID, perfil_id: UUID) -> None:
    from sqlalchemy import delete

    fila = _obtener(db, tenant_id, perfil_id)
    db.execute(delete(VinculoMfaProveedor).where(VinculoMfaProveedor.perfil_id == fila.id))
    registrar(
        db,
        accion="mfa_proveedor.borrado",
        objeto="perfil_mfa_proveedor",
        objeto_id=fila.id,
        datos={"nombre": fila.nombre},
    )
    db.delete(fila)
    db.flush()


# ── Quién es cada persona en el proveedor ─────────────────────────────────


def vinculos(db: Session, tenant_id: UUID, perfil_id: UUID) -> list[dict[str, Any]]:
    _obtener(db, tenant_id, perfil_id)
    filas = (
        db.execute(
            select(VinculoMfaProveedor).where(
                VinculoMfaProveedor.tenant_id == tenant_id,
                VinculoMfaProveedor.perfil_id == perfil_id,
            )
        )
        .scalars()
        .all()
    )
    return [{"usuario_id": str(f.usuario_id), "datos": dict(f.datos or {})} for f in filas]


def vincular(
    db: Session, tenant_id: UUID, perfil_id: UUID, usuario_id: UUID, datos: dict[str, Any]
) -> dict[str, Any]:
    """Apunta los datos de la persona que pide el perfil. Vacío = quitarla."""
    from services.identity.modelos import Membresia

    perfil = _obtener(db, tenant_id, perfil_id)
    es_de_aqui = db.execute(
        select(Membresia.id).where(
            Membresia.usuario_id == usuario_id, Membresia.tenant_id == tenant_id
        )
    ).first()
    if es_de_aqui is None:
        raise NoEncontrado("Esa persona no es de esta empresa", error_code="usuario.no_encontrado")
    pedidos = list(perfil.campos_persona or [])
    limpio = {
        c: str(datos.get(c) or "").strip() for c in pedidos if str(datos.get(c) or "").strip()
    }
    fila = db.execute(
        select(VinculoMfaProveedor).where(
            VinculoMfaProveedor.perfil_id == perfil.id, VinculoMfaProveedor.usuario_id == usuario_id
        )
    ).scalar_one_or_none()
    if not limpio:
        if fila is not None:
            db.delete(fila)
            db.flush()
        return {"usuario_id": str(usuario_id), "datos": {}}
    if fila is None:
        fila = VinculoMfaProveedor(tenant_id=tenant_id, perfil_id=perfil.id, usuario_id=usuario_id)
        db.add(fila)
    fila.datos = limpio
    db.flush()
    registrar(
        db,
        accion="mfa_proveedor.persona_vinculada",
        objeto="usuario",
        objeto_id=usuario_id,
        datos={"perfil": perfil.nombre, "campos": sorted(limpio)},
    )
    return {"usuario_id": str(usuario_id), "datos": limpio}


def _datos_persona(db: Session, perfil: PerfilMfaProveedor, usuario_id: UUID) -> dict[str, str]:
    fila = db.execute(
        select(VinculoMfaProveedor).where(
            VinculoMfaProveedor.perfil_id == perfil.id, VinculoMfaProveedor.usuario_id == usuario_id
        )
    ).scalar_one_or_none()
    return {str(k): str(v) for k, v in dict(fila.datos if fila else {}).items()}


def aplica_a(db: Session, tenant_id: UUID, usuario_id: UUID) -> bool:
    """¿Puede esta persona demostrar el segundo factor con el proveedor?

    Sí si la empresa tiene uno activo y la persona tiene apuntado todo lo que
    el perfil necesita de ella. Sin eso, pedirle el código sería pedirle algo
    que el proveedor no va a poder comprobar.
    """
    perfil = activo_de(db, tenant_id)
    if perfil is None:
        return False
    persona = _datos_persona(db, perfil, usuario_id)
    return all(persona.get(c) for c in (perfil.campos_persona or []))


# ── La llamada ────────────────────────────────────────────────────────────


class _Falta(Exception):
    pass


def _rellenar(valor: Any, valores: dict[str, str]) -> Any:
    if isinstance(valor, dict):
        return {k: _rellenar(v, valores) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_rellenar(v, valores) for v in valor]
    if isinstance(valor, str):

        def _uno(m: re.Match[str]) -> str:
            clave = m.group(1)
            if not valores.get(clave):
                raise _Falta(clave)
            return valores[clave]

        return _MARCA.sub(_uno, valor)
    return valor


def _leer(cuerpo: Any, ruta: str) -> Any:
    actual = cuerpo
    for trozo in ruta.split("."):
        if isinstance(actual, dict):
            actual = actual.get(trozo)
        elif isinstance(actual, list) and trozo.isdigit() and int(trozo) < len(actual):
            actual = actual[int(trozo)]
        else:
            return None
    return actual


def _componer(
    perfil: PerfilMfaProveedor, *, codigo: str, email: str, persona: dict[str, str], secreto: str
) -> dict[str, Any]:
    valores: dict[str, str] = {
        "codigo": (codigo or "").strip(),
        "email": email,
        "usuario": email.split("@", 1)[0],
        "id_peticion": str(uuid4()),
        **{f"var.{k}": str(v) for k, v in dict(perfil.variables or {}).items()},
        **{f"persona.{k}": v for k, v in persona.items()},
    }
    url = _rellenar(perfil.url, valores)
    cuerpo = _rellenar(dict(perfil.cuerpo or {}), valores)
    cabeceras = {
        str(k): str(_rellenar(v, valores)) for k, v in dict(perfil.cabeceras or {}).items()
    }
    auth = dict(perfil.autenticacion or {})
    tipo = str(auth.get("tipo") or "ninguna")
    con_secreto = {**valores, "secreto": secreto}
    basica: tuple[str, str] | None = None
    if tipo == "basica":
        basica = (str(_rellenar(str(auth.get("usuario") or ""), valores)), secreto)
    elif tipo == "bearer":
        cabeceras["Authorization"] = f"Bearer {secreto}"
    elif tipo == "cabecera":
        cabeceras[str(auth.get("cabecera"))] = str(
            _rellenar(str(auth.get("valor") or "{{secreto}}"), con_secreto)
        )
    return {
        "metodo": perfil.metodo,
        "url": url,
        "cuerpo": cuerpo,
        "cabeceras": cabeceras,
        "basica": basica,
    }


def _tapar(peticion: dict[str, Any], secreto: str, codigo: str) -> dict[str, Any]:
    """La petición para enseñarla: sin secreto y sin el código tecleado."""

    def _t(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: _t(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_t(x) for x in v]
        if isinstance(v, str):
            if secreto:
                v = v.replace(secreto, "••••")
            if codigo:
                v = v.replace(codigo, "••••")
            return v
        return v

    return {
        "metodo": peticion["metodo"],
        "url": _t(peticion["url"]),
        "cuerpo": _t(peticion["cuerpo"]),
        "cabeceras": _t(peticion["cabeceras"]),
        "autenticacion_basica": (peticion["basica"][0] + ":••••") if peticion["basica"] else None,
    }


def verificar(
    db: Session,
    perfil: PerfilMfaProveedor,
    *,
    usuario_id: UUID,
    email: str,
    codigo: str,
) -> dict[str, Any]:
    """Pregunta al proveedor si el código vale. Nunca lanza: dice por qué no."""
    from crmcore.config import get_settings
    from crmcore.red import cliente_seguro
    from crmcore.security.cifrado import descifrar

    secreto = descifrar(perfil.secreto, proposito=PROPOSITO, db=db) if perfil.secreto else ""
    persona = _datos_persona(db, perfil, usuario_id)
    try:
        peticion = _componer(perfil, codigo=codigo, email=email, persona=persona, secreto=secreto)
    except _Falta as falta:
        return {
            "valido": False,
            "estado_http": None,
            "motivo": f"Falta «{falta.args[0]}» para llamar al proveedor; no se ha llamado.",
            "peticion": None,
        }
    tapada = _tapar(peticion, secreto, (codigo or "").strip())
    kwargs: dict[str, Any] = {"headers": peticion["cabeceras"]}
    if peticion["basica"]:
        kwargs["auth"] = peticion["basica"]
    if perfil.metodo == "GET":
        kwargs["params"] = {k: str(v) for k, v in peticion["cuerpo"].items()}
    elif perfil.formato == "form":
        kwargs["content"] = urlencode({k: str(v) for k, v in peticion["cuerpo"].items()})
        kwargs["headers"] = {
            **peticion["cabeceras"],
            "Content-Type": "application/x-www-form-urlencoded",
        }
    else:
        kwargs["json"] = peticion["cuerpo"]
    try:
        with cliente_seguro(timeout=get_settings().http_externo_timeout_s) as cliente:
            r = cliente.request(perfil.metodo, peticion["url"], **kwargs)
    except Exception as exc:  # noqa: BLE001 — el login tiene que poder decir por qué
        logger.warning(
            "mfa_proveedor.sin_respuesta", perfil=perfil.nombre, error=type(exc).__name__
        )
        return {
            "valido": False,
            "estado_http": None,
            "motivo": f"El proveedor no responde ({type(exc).__name__}). No se entra sin él.",
            "peticion": tapada,
        }
    try:
        cuerpo = r.json()
    except ValueError:
        cuerpo = None
    campo = str(dict(perfil.respuesta or {}).get("campo") or "")
    validos = [str(v).lower() for v in dict(perfil.respuesta or {}).get("validos") or []]
    leido = _leer(cuerpo, campo) if campo else None
    if not (200 <= r.status_code < 300):
        valido, motivo = False, f"El proveedor contestó HTTP {r.status_code}"
    elif campo:
        valido = leido is not None and str(leido).lower() in validos
        motivo = f"«{campo}» vale «{leido}»" + (
            "" if valido else f"; para que valga tendría que ser {', '.join(validos)}"
        )
    else:
        valido, motivo = True, f"HTTP {r.status_code} y el perfil no pide leer ningún campo"
    return {
        "valido": valido,
        "estado_http": r.status_code,
        "motivo": motivo,
        "leido": leido,
        "peticion": tapada,
    }


def verificar_en_login(db: Session, tenant_id: UUID, usuario: Any, codigo: str) -> bool:
    """El paso del login: ¿vale el código según el proveedor del tenant?"""
    perfil = activo_de(db, tenant_id)
    if perfil is None or not (codigo or "").strip():
        return False
    resultado = verificar(db, perfil, usuario_id=usuario.id, email=usuario.email, codigo=codigo)
    registrar(
        db,
        accion="mfa_proveedor.verificado" if resultado["valido"] else "mfa_proveedor.rechazado",
        objeto="usuario",
        objeto_id=usuario.id,
        datos={
            "perfil": perfil.nombre,
            "estado_http": resultado["estado_http"],
            "motivo": resultado["motivo"],
        },
        # A mano: en el login todavía no hay tenant en el contexto, y sin él
        # la auditoría contestaba 422 `auditoria.sin_tenant` y deshacía una
        # entrada con el código bueno (medido el 09-11-2026 en la pila).
        tenant_id=tenant_id,
    )
    return bool(resultado["valido"])


def probar(
    db: Session, tenant_id: UUID, perfil_id: UUID, *, usuario_id: UUID, codigo: str
) -> dict[str, Any]:
    """«Probar» desde la pantalla: la misma llamada que el login, sin entrar."""
    from datetime import timezone

    from services.identity.modelos import Membresia, Usuario

    perfil = _obtener(db, tenant_id, perfil_id)
    usuario = db.get(Usuario, usuario_id)
    es_de_aqui = db.execute(
        select(Membresia.id).where(
            Membresia.usuario_id == usuario_id, Membresia.tenant_id == tenant_id
        )
    ).first()
    if usuario is None or es_de_aqui is None:
        raise NoEncontrado("Esa persona no es de esta empresa", error_code="usuario.no_encontrado")
    resultado = verificar(db, perfil, usuario_id=usuario.id, email=usuario.email, codigo=codigo)
    perfil.ultima_prueba_at = datetime.now(timezone.utc)
    perfil.ultima_prueba = {
        "valido": resultado["valido"],
        "estado_http": resultado["estado_http"],
        "motivo": resultado["motivo"],
    }
    registrar(
        db,
        accion="mfa_proveedor.probado",
        objeto="perfil_mfa_proveedor",
        objeto_id=perfil.id,
        datos=dict(perfil.ultima_prueba),
    )
    db.flush()
    return resultado
