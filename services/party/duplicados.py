"""Detección de duplicados y fusión (CRM-01.01.04.01, .02, .03).

Dos momentos distintos, con exigencias distintas:

  * **Al capturar** (tiempo real): se buscan candidatos y se avisa. Tiene que
    ser rápido —bloquea a quien está dando de alta— así que criba primero por
    índice (clave canónica, dominio, identificador fiscal) y solo compara en
    detalle lo que pasa la criba.
  * **Por lotes**: recorre el maestro entero y propone. Puede tardar.

**La regla que evita el desastre**: una clave canónica igual es un *candidato*,
no una prueba. Para bloquear un alta hace falta una señal fuerte —el mismo
identificador fiscal— o una similitud altísima. Fusionar dos clientes que no
eran el mismo obliga a reconstruir a mano contratos, actividades y facturación,
y casi nunca se reconstruye del todo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from crmcore.authz.decision import exigir
from crmcore.logging import get_logger
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from services.party import normalizacion as norm
from services.party.modelos import (
    Actividad,
    Consentimiento,
    Contacto,
    Cuenta,
    Direccion,
    Fusion,
    IdentificadorFiscal,
    JerarquiaCuenta,
    MiembroEquipoCuenta,
    RelacionContactoCuenta,
    RelacionCuenta,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Candidato:
    """Una ficha que podría ser la misma, con su porqué."""

    id: UUID
    nombre: str
    similitud: float
    # Qué señales han coincidido: `nif`, `dominio`, `nombre`, `email`. Se
    # devuelven porque quien decide necesita saber POR QUÉ se le propone: «mismo
    # NIF» y «nombre parecido» llevan a decisiones distintas.
    senales: tuple[str, ...]
    # `True` cuando la señal es concluyente y el alta debe bloquearse.
    concluyente: bool = False

    def a_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "nombre": self.nombre,
            "similitud": round(self.similitud, 3),
            "senales": list(self.senales),
            "concluyente": self.concluyente,
        }


def buscar_cuentas_duplicadas(
    db: Session,
    *,
    tenant_id: UUID,
    nombre: str,
    identificadores: list[str] | None = None,
    email: str | None = None,
    web: str | None = None,
    excluir_id: UUID | None = None,
) -> list[Candidato]:
    """Candidatos a duplicado de una cuenta, ordenados por certeza."""
    from crmcore.runtime import settings as rt

    from services.party.ajustes import ajustes

    a = ajustes()
    umbral = float(rt.efectivo("dedupe_umbral_sugerencia", db) or a.dedupe_umbral_sugerencia)
    bloqueo = float(rt.efectivo("dedupe_umbral_bloqueo", db) or a.dedupe_umbral_bloqueo)
    usar_nif = bool(rt.efectivo("dedupe_bloquear_por_nif", db))
    maximo = a.dedupe_max_candidatos

    clave = norm.clave_canonica_empresa(nombre)
    dominio = norm.dominio_de(email) or norm.dominio_de(web)
    nifs = [norm.normalizar_identificador_fiscal(i) for i in (identificadores or []) if i]

    candidatos: dict[UUID, Candidato] = {}

    # ── 1. Identificador fiscal: la única señal concluyente ───────────────
    # Dos entidades con el mismo NIF son la misma entidad jurídica. No hay
    # interpretación posible, así que esto sí bloquea.
    if usar_nif and nifs:
        filas = db.execute(
            select(IdentificadorFiscal, Cuenta)
            .join(Cuenta, Cuenta.id == IdentificadorFiscal.cuenta_id)
            .where(
                IdentificadorFiscal.tenant_id == tenant_id,
                IdentificadorFiscal.valor_normalizado.in_(nifs),
                Cuenta.deleted_at.is_(None),
                Cuenta.fusionada_en_id.is_(None),
            )
        ).all()
        for _ident, cuenta in filas:
            if excluir_id and cuenta.id == excluir_id:
                continue
            candidatos[cuenta.id] = Candidato(
                id=cuenta.id,
                nombre=cuenta.nombre,
                similitud=1.0,
                senales=("identificador_fiscal",),
                concluyente=True,
            )

    # ── 2. Criba por índice ───────────────────────────────────────────────
    # Se traen solo las que comparten clave canónica, dominio o la primera
    # palabra significativa. Comparar contra el maestro entero sería correcto y
    # nunca terminaría con cien mil cuentas.
    primera = clave.split()[0] if clave else ""
    condiciones = []
    if clave:
        condiciones.append(Cuenta.clave_canonica == clave)
    if primera:
        condiciones.append(Cuenta.clave_canonica.like(f"%{primera}%"))
    if dominio and a.dedupe_usar_dominio:
        condiciones.append(Cuenta.dominio == dominio)
    if not condiciones:
        return sorted(candidatos.values(), key=lambda c: -c.similitud)[:maximo]

    posibles = (
        db.execute(
            select(Cuenta)
            .where(
                Cuenta.tenant_id == tenant_id,
                Cuenta.deleted_at.is_(None),
                Cuenta.fusionada_en_id.is_(None),
                or_(*condiciones),
            )
            # Tope de la criba: si una palabra es tan común que trae cientos de
            # cuentas, comparar todas cuesta más de lo que aporta.
            .limit(200)
        )
        .scalars()
        .all()
    )

    for cuenta in posibles:
        if excluir_id and cuenta.id == excluir_id:
            continue
        if cuenta.id in candidatos:
            continue
        senales: list[str] = []
        parecido = norm.similitud(clave, cuenta.clave_canonica)
        if parecido >= umbral:
            senales.append("nombre")
        if dominio and cuenta.dominio == dominio and a.dedupe_usar_dominio:
            senales.append("dominio")
            # El dominio sube la confianza pero no la lleva a certeza: un grupo
            # tiene varias sociedades con el mismo dominio.
            parecido = max(parecido, 0.9)
        if not senales:
            continue
        candidatos[cuenta.id] = Candidato(
            id=cuenta.id,
            nombre=cuenta.nombre,
            similitud=parecido,
            senales=tuple(senales),
            concluyente=parecido >= bloqueo,
        )

    return sorted(candidatos.values(), key=lambda c: (-int(c.concluyente), -c.similitud))[:maximo]


def buscar_contactos_duplicados(
    db: Session,
    *,
    tenant_id: UUID,
    nombre: str,
    apellidos: str | None = None,
    email: str | None = None,
    excluir_id: UUID | None = None,
) -> list[Candidato]:
    """Candidatos a duplicado de un contacto.

    El correo es aquí lo que el NIF en las cuentas: dos personas no comparten
    buzón. Es la señal concluyente.
    """
    from crmcore.runtime import settings as rt

    from services.party.ajustes import ajustes

    a = ajustes()
    umbral = float(rt.efectivo("dedupe_umbral_sugerencia", db) or a.dedupe_umbral_sugerencia)
    bloqueo = float(rt.efectivo("dedupe_umbral_bloqueo", db) or a.dedupe_umbral_bloqueo)

    clave = norm.clave_canonica_persona(nombre, apellidos)
    correo = norm.normalizar_email(email)
    candidatos: dict[UUID, Candidato] = {}

    if correo:
        for contacto in (
            db.execute(
                select(Contacto).where(
                    Contacto.tenant_id == tenant_id,
                    Contacto.email == correo,
                    Contacto.deleted_at.is_(None),
                    Contacto.fusionado_en_id.is_(None),
                )
            )
            .scalars()
            .all()
        ):
            if excluir_id and contacto.id == excluir_id:
                continue
            candidatos[contacto.id] = Candidato(
                id=contacto.id,
                nombre=contacto.nombre_completo,
                similitud=1.0,
                senales=("email",),
                concluyente=True,
            )

    primera = clave.split()[0] if clave else ""
    if primera:
        for contacto in (
            db.execute(
                select(Contacto)
                .where(
                    Contacto.tenant_id == tenant_id,
                    Contacto.deleted_at.is_(None),
                    Contacto.fusionado_en_id.is_(None),
                    Contacto.clave_canonica.like(f"%{primera}%"),
                )
                .limit(200)
            )
            .scalars()
            .all()
        ):
            if (excluir_id and contacto.id == excluir_id) or contacto.id in candidatos:
                continue
            parecido = norm.similitud(clave, contacto.clave_canonica)
            if parecido < umbral:
                continue
            candidatos[contacto.id] = Candidato(
                id=contacto.id,
                nombre=contacto.nombre_completo,
                similitud=parecido,
                senales=("nombre",),
                concluyente=parecido >= bloqueo,
            )

    return sorted(candidatos.values(), key=lambda c: (-int(c.concluyente), -c.similitud))[
        : a.dedupe_max_candidatos
    ]


# ── Fusión ────────────────────────────────────────────────────────────────

# Tablas cuyas filas apuntan a una cuenta y hay que reparentar al fusionar. Se
# declaran aquí, en un solo sitio: una tabla nueva que apunte a `cuenta_id` y no
# esté en esta lista dejaría filas colgando de una cuenta absorbida, y eso no da
# ningún síntoma hasta que alguien busca el histórico y no aparece.
RELACIONES_CUENTA: tuple[tuple[type, str], ...] = (
    (IdentificadorFiscal, "cuenta_id"),
    (JerarquiaCuenta, "cuenta_id"),
    (MiembroEquipoCuenta, "cuenta_id"),
    (RelacionContactoCuenta, "cuenta_id"),
    (Actividad, "cuenta_id"),
)
RELACIONES_CONTACTO: tuple[tuple[type, str], ...] = (
    (RelacionContactoCuenta, "contacto_id"),
    (Consentimiento, "contacto_id"),
    (Actividad, "contacto_id"),
)


def fusionar_cuentas(
    db: Session,
    *,
    superviviente_id: UUID,
    absorbida_id: UUID,
    campos_ganadores: dict[str, str] | None = None,
    motivo: str = "",
    por: UUID | None = None,
) -> Fusion:
    """Fusiona dos cuentas y reparenta todo lo que colgaba de la absorbida.

    `campos_ganadores` dice, por campo, de cuál de las dos se queda el valor
    (`"superviviente"` o `"absorbida"`). Lo que no se indique se queda del
    superviviente, salvo que esté vacío y la absorbida lo tenga: rellenar un
    hueco nunca empeora la ficha.

    La absorbida **no se borra**: se marca con `fusionada_en_id`. Hay documentos,
    correos y sistemas externos que guardan ese identificador, y borrarlo los
    deja apuntando al vacío. Además, así la fusión se puede deshacer.
    """
    from crmcore.audit.chain import registrar
    from crmcore.errors import Conflicto, NoEncontrado

    superviviente = db.get(Cuenta, superviviente_id)
    absorbida = db.get(Cuenta, absorbida_id)
    # Fusionar es la escritura más destructiva que hay sobre una cuenta: una
    # deja de existir. Se decide sobre las DOS, porque quien no puede tocar la
    # absorbida no puede hacerla desaparecer dentro de otra.
    for fila in (superviviente, absorbida):
        if fila is not None:
            exigir(db, objeto="cuenta", accion="write", registro=fila)
    if superviviente is None or absorbida is None:
        raise NoEncontrado("Una de las cuentas no existe", error_code="party.cuenta_no_encontrada")
    if superviviente_id == absorbida_id:
        raise Conflicto(
            "No se puede fusionar una cuenta consigo misma", error_code="party.fusion_misma"
        )
    if absorbida.fusionada_en_id is not None:
        raise Conflicto(
            "Esa cuenta ya se fusionó en otra",
            error_code="party.ya_fusionada",
            detalle={"fusionada_en": str(absorbida.fusionada_en_id)},
        )

    estado_previo = absorbida.a_dict(json_seguro=True)
    supervivencia: dict[str, Any] = {}
    campos_ganadores = campos_ganadores or {}

    # Campos que NUNCA se copian de la absorbida: son propios de la fila.
    intocables = {
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
        "version",
        "fusionada_en_id",
        "deleted_at",
        "deleted_by",
        "clave_canonica",
    }
    for columna in superviviente.__table__.columns:
        campo = columna.name
        if campo in intocables:
            continue
        valor_absorbida = getattr(absorbida, campo, None)
        valor_superviviente = getattr(superviviente, campo, None)
        gana_absorbida = campos_ganadores.get(campo) == "absorbida" or (
            campo not in campos_ganadores
            and valor_superviviente in (None, "", [], {})
            and valor_absorbida not in (None, "", [], {})
        )
        if gana_absorbida:
            setattr(superviviente, campo, valor_absorbida)
            supervivencia[campo] = "absorbida"
        else:
            supervivencia[campo] = "superviviente"

    movidas = _reparentar(db, RELACIONES_CUENTA, absorbida_id, superviviente_id)

    absorbida.fusionada_en_id = superviviente_id
    absorbida.estado = "inactiva"

    fusion = Fusion(
        tenant_id=superviviente.tenant_id,
        objeto="cuenta",
        superviviente_id=superviviente_id,
        absorbido_id=absorbida_id,
        estado_previo=estado_previo,
        supervivencia=supervivencia,
        relaciones_movidas=movidas,
        fusionado_por=por,
        motivo=motivo or None,
    )
    db.add(fusion)
    registrar(
        db,
        accion="cuenta.fusionada",
        objeto="cuenta",
        objeto_id=superviviente_id,
        datos={"absorbida": str(absorbida_id), "relaciones_movidas": movidas},
        motivo=motivo or None,
        # El tenant se pasa explícito y no se toma del contexto: esta función la
        # llaman también trabajos de fondo y el consolidador por lotes, que no
        # tienen petición y por tanto no tienen contexto.
        tenant_id=superviviente.tenant_id,
    )
    logger.info(
        "party.fusion_cuentas",
        superviviente=str(superviviente_id),
        absorbida=str(absorbida_id),
        movidas=sum(movidas.values()),
    )
    return fusion


def fusionar_contactos(
    db: Session,
    *,
    superviviente_id: UUID,
    absorbido_id: UUID,
    campos_ganadores: dict[str, str] | None = None,
    motivo: str = "",
    por: UUID | None = None,
) -> Fusion:
    """Fusiona dos contactos. Mismo criterio que con las cuentas."""
    from crmcore.audit.chain import registrar
    from crmcore.errors import Conflicto, NoEncontrado

    superviviente = db.get(Contacto, superviviente_id)
    absorbido = db.get(Contacto, absorbido_id)
    for fila in (superviviente, absorbido):
        if fila is not None:
            exigir(db, objeto="contacto", accion="write", registro=fila)
    if superviviente is None or absorbido is None:
        raise NoEncontrado(
            "Uno de los contactos no existe", error_code="party.contacto_no_encontrado"
        )
    if superviviente_id == absorbido_id:
        raise Conflicto(
            "No se puede fusionar un contacto consigo mismo", error_code="party.fusion_misma"
        )
    if absorbido.fusionado_en_id is not None:
        raise Conflicto("Ese contacto ya se fusionó", error_code="party.ya_fusionada")

    estado_previo = absorbido.a_dict(json_seguro=True)
    supervivencia: dict[str, Any] = {}
    campos_ganadores = campos_ganadores or {}
    intocables = {
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
        "version",
        "fusionado_en_id",
        "deleted_at",
        "deleted_by",
        "clave_canonica",
        "nombre_completo",
    }
    for columna in superviviente.__table__.columns:
        campo = columna.name
        if campo in intocables:
            continue
        valor_absorbido = getattr(absorbido, campo, None)
        valor_superviviente = getattr(superviviente, campo, None)
        if campos_ganadores.get(campo) == "absorbida" or (
            campo not in campos_ganadores
            and valor_superviviente in (None, "", [], {})
            and valor_absorbido not in (None, "", [], {})
        ):
            setattr(superviviente, campo, valor_absorbido)
            supervivencia[campo] = "absorbida"
        else:
            supervivencia[campo] = "superviviente"

    # El `no_contactar` se propaga siempre que alguno de los dos lo tenga, sin
    # mirar quién gana el campo: si una de las dos fichas dijo «no me
    # contactéis», la fusionada tampoco puede ser contactada. Equivocarse aquí
    # significa escribir a alguien que pidió expresamente que no se le escriba.
    if absorbido.no_contactar or superviviente.no_contactar:
        superviviente.no_contactar = True
        supervivencia["no_contactar"] = "mas_restrictivo"

    movidas = _reparentar(db, RELACIONES_CONTACTO, absorbido_id, superviviente_id)
    absorbido.fusionado_en_id = superviviente_id

    fusion = Fusion(
        tenant_id=superviviente.tenant_id,
        objeto="contacto",
        superviviente_id=superviviente_id,
        absorbido_id=absorbido_id,
        estado_previo=estado_previo,
        supervivencia=supervivencia,
        relaciones_movidas=movidas,
        fusionado_por=por,
        motivo=motivo or None,
    )
    db.add(fusion)
    registrar(
        db,
        accion="contacto.fusionado",
        objeto="contacto",
        objeto_id=superviviente_id,
        datos={"absorbido": str(absorbido_id), "relaciones_movidas": movidas},
        motivo=motivo or None,
        tenant_id=superviviente.tenant_id,
    )
    return fusion


def _reparentar(
    db: Session, relaciones: tuple[tuple[type, str], ...], de_id: UUID, a_id: UUID
) -> dict[str, int]:
    """Mueve las filas que apuntaban al absorbido hacia el superviviente."""
    from sqlalchemy import update

    movidas: dict[str, int] = {}
    for modelo, columna in relaciones:
        resultado = db.execute(
            update(modelo)
            .where(getattr(modelo, columna) == de_id)
            .values({columna: a_id})
            .execution_options(synchronize_session=False)
        )
        if resultado.rowcount:
            movidas[modelo.__tablename__] = int(resultado.rowcount)
    return movidas


def deshacer_fusion(db: Session, fusion_id: UUID, *, motivo: str) -> None:
    """Deshace una fusión: separa las fichas y devuelve los valores previos.

    **No devuelve las relaciones a su sitio.** Y decirlo importa: al reparentar
    se pierde la información de cuáles venían de cada ficha —una actividad
    movida es indistinguible de una que ya estaba—, así que deshacer restaura
    los CAMPOS de la ficha absorbida y la reactiva, pero las actividades,
    identificadores y vínculos se quedan donde están. Repartirlos a ojo sería
    peor que dejarlos juntos.
    """
    from crmcore.audit.chain import registrar
    from crmcore.errors import Conflicto, NoEncontrado

    fusion = db.get(Fusion, fusion_id)
    if fusion is None:
        raise NoEncontrado("Esa fusión no existe", error_code="party.fusion_no_encontrada")
    if fusion.deshecha_at is not None:
        raise Conflicto("Esa fusión ya se deshizo", error_code="party.fusion_ya_deshecha")

    modelo = Cuenta if fusion.objeto == "cuenta" else Contacto
    absorbido = db.get(modelo, fusion.absorbido_id)
    if absorbido is None:
        raise NoEncontrado(
            "La ficha absorbida ya no existe", error_code="party.absorbido_no_encontrado"
        )

    intocables = {"id", "tenant_id", "created_at", "version"}
    for campo, valor in (fusion.estado_previo or {}).items():
        if campo in intocables or not hasattr(absorbido, campo):
            continue
        setattr(absorbido, campo, valor)
    if fusion.objeto == "cuenta":
        absorbido.fusionada_en_id = None
    else:
        absorbido.fusionado_en_id = None

    from datetime import datetime, timezone

    fusion.deshecha_at = datetime.now(timezone.utc)
    registrar(
        db,
        accion="fusion.deshecha",
        objeto=fusion.objeto,
        objeto_id=fusion.absorbido_id,
        datos={"fusion_id": str(fusion_id)},
        motivo=motivo,
        tenant_id=fusion.tenant_id,
    )
    logger.warning("party.fusion_deshecha", fusion=str(fusion_id), objeto=fusion.objeto)


def _sin_usar(*_a: Direccion | RelacionCuenta) -> None:  # pragma: no cover
    """Mantiene vivos los imports usados solo en anotaciones de la lista."""
