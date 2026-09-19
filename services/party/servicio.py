"""Lógica de cuentas, contactos, actividades y consentimientos."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar, registrar_cambios
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.logging import get_logger
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from services.party import duplicados
from services.party import normalizacion as norm
from services.party.modelos import (
    Actividad,
    Consentimiento,
    Contacto,
    Cuenta,
    Direccion,
    IdentificadorFiscal,
    JerarquiaCuenta,
    RelacionContactoCuenta,
    SolicitudDerechos,
)

logger = get_logger(__name__)


# ── Cuentas ───────────────────────────────────────────────────────────────


def crear_cuenta(
    uow: UnidadDeTrabajo,
    *,
    nombre: str,
    identificadores: list[dict[str, Any]] | None = None,
    forzar: bool = False,
    **datos: Any,
) -> Cuenta:
    """Da de alta una cuenta, comprobando duplicados antes (CRM-01.01.03.03).

    `forzar=True` salta el bloqueo por duplicado. Existe porque hay casos
    legítimos —dos sociedades del mismo grupo con nombre casi igual— y porque un
    sistema que no deja crear nada acaba con la gente creando la ficha en otro
    sitio. Lo que no hace es ser silencioso: la decisión queda en la auditoría.
    """
    tenant_id = uow.tenant_id
    if tenant_id is None:
        raise ErrorValidacion("Falta el tenant", error_code="party.sin_tenant")

    nifs = [str(i.get("valor", "")) for i in (identificadores or [])]
    candidatos = duplicados.buscar_cuentas_duplicadas(
        uow.db,
        tenant_id=tenant_id,
        nombre=nombre,
        identificadores=nifs,
        email=datos.get("email"),
        web=datos.get("web"),
    )
    concluyentes = [c for c in candidatos if c.concluyente]
    if concluyentes and not forzar:
        raise Conflicto(
            "Ya existe una cuenta que parece la misma",
            error_code="party.cuenta_duplicada",
            detalle={
                "candidatos": [c.a_dict() for c in candidatos],
                # Se dice cómo continuar: sin esto, quien recibe el 409 no sabe
                # si tiene que buscar la ficha existente o insistir.
                "como_continuar": "usa la cuenta existente, o repite con forzar=true",
            },
        )

    cuenta = Cuenta(
        tenant_id=tenant_id,
        nombre=nombre.strip(),
        clave_canonica=norm.clave_canonica_empresa(nombre),
        dominio=norm.dominio_de(datos.get("email")) or norm.dominio_de(datos.get("web")) or None,
        telefono=norm.normalizar_telefono(datos.get("telefono"), datos.get("pais", "ES")) or None,
        email=norm.normalizar_email(datos.get("email")) or None,
        **{k: v for k, v in datos.items() if k not in ("telefono", "email", "pais")},
    )
    uow.db.add(cuenta)
    uow.db.flush()

    for identificador in identificadores or []:
        _añadir_identificador(uow.db, cuenta, identificador)
    # Volcado antes de puntuar: la puntuación consulta los identificadores y las
    # direcciones, y con la sesión sin autoflush no vería los que se acaban de
    # añadir. El síntoma era una ficha recién creada CON identificador fiscal que
    # decía que le faltaba — y que por tanto entraba en la cola de revisión de
    # calidad sin motivo.
    uow.db.flush()

    _recalcular_calidad_cuenta(uow.db, cuenta)

    registrar(
        uow.db,
        accion="cuenta.creada",
        objeto="cuenta",
        objeto_id=cuenta.id,
        datos={
            "nombre": cuenta.nombre,
            "forzada": bool(concluyentes and forzar),
            "candidatos_descartados": [c.a_dict() for c in candidatos] if forzar else [],
        },
    )
    uow.emitir(
        "account.created",
        subject=("cuenta", cuenta.id),
        data={"cuenta_id": str(cuenta.id), "nombre": cuenta.nombre},
    )
    _indexar(uow.db, "cuenta", cuenta)
    return cuenta


def _indexar(db: Session, objeto: str, fila: Any) -> None:
    """Pone el registro en el índice de búsqueda.

    Se hace al escribir y no con una tarea nocturna: quien acaba de crear una
    cuenta la busca a los diez segundos, y un índice con un día de retraso se
    percibe —con razón— como que la búsqueda no funciona.
    """
    from services.party import indexacion

    {"cuenta": indexacion.indexar_cuenta, "contacto": indexacion.indexar_contacto}[objeto](db, fila)


def actualizar_cuenta(uow: UnidadDeTrabajo, cuenta_id: UUID, cambios: dict[str, Any]) -> Cuenta:
    """Actualiza una cuenta dejando historial campo a campo."""
    cuenta = _cuenta(uow.db, cuenta_id)
    anterior = cuenta.a_dict()

    if "nombre" in cambios and cambios["nombre"]:
        cuenta.clave_canonica = norm.clave_canonica_empresa(cambios["nombre"])
    if "telefono" in cambios:
        cambios["telefono"] = norm.normalizar_telefono(cambios["telefono"]) or None
    if "email" in cambios:
        cambios["email"] = norm.normalizar_email(cambios["email"]) or None
        cuenta.dominio = norm.dominio_de(cambios["email"]) or cuenta.dominio

    for campo, valor in cambios.items():
        if hasattr(cuenta, campo):
            setattr(cuenta, campo, valor)

    _recalcular_calidad_cuenta(uow.db, cuenta)
    registrar_cambios(
        uow.db, objeto="cuenta", objeto_id=cuenta.id, anterior=anterior, nuevo=cuenta.a_dict()
    )
    # Reindexar al editar: si no, la búsqueda sigue encontrando el nombre
    # viejo y no el nuevo, que es peor que no encontrar nada.
    _indexar(uow.db, "cuenta", cuenta)
    return cuenta


def _cuenta(db: Session, cuenta_id: UUID) -> Cuenta:
    cuenta = db.get(Cuenta, cuenta_id)
    # La cuenta fusionada se trata como inexistente en la API: quien la busque
    # debe ir a la superviviente. Se devuelve 404 y no 410 porque el 410 exige
    # garantizar que nunca volverá, y una fusión se puede deshacer.
    if cuenta is None or cuenta.deleted_at is not None:
        raise NoEncontrado("La cuenta no existe", error_code="party.cuenta_no_encontrada")
    return cuenta


def _añadir_identificador(
    db: Session, cuenta: Cuenta, datos: dict[str, Any]
) -> IdentificadorFiscal:
    valor = str(datos.get("valor", "")).strip()
    if not valor:
        raise ErrorValidacion(
            "El identificador fiscal no puede estar vacío", error_code="party.nif_vacio"
        )
    normalizado = norm.normalizar_identificador_fiscal(valor)
    pais = str(datos.get("pais", "ES")).upper()

    # La validación de forma solo se aplica donde se sabe hacer. Rechazar un
    # identificador extranjero porque no cumple el algoritmo español sería
    # impedir dar de alta a un cliente perfectamente real.
    if pais == "ES" and not norm.validar_nif_es(normalizado):
        raise ErrorValidacion(
            f"«{valor}» no es un NIF, NIE o CIF español válido",
            error_code="party.nif_invalido",
            detalle={"valor": valor},
        )

    identificador = IdentificadorFiscal(
        tenant_id=cuenta.tenant_id,
        cuenta_id=cuenta.id,
        tipo=str(datos.get("tipo", "nif")),
        pais=pais,
        valor=valor,
        valor_normalizado=normalizado,
        principal=bool(datos.get("principal", False)),
    )
    db.add(identificador)
    return identificador


def _recalcular_calidad_cuenta(db: Session, cuenta: Cuenta) -> None:
    """Puntúa la completitud de la ficha (CRM-01.01.04.05)."""
    tiene_nif = (
        db.execute(
            select(IdentificadorFiscal.id)
            .where(IdentificadorFiscal.cuenta_id == cuenta.id)
            .limit(1)
        ).first()
        is not None
    )
    tiene_direccion = (
        db.execute(
            select(Direccion.id)
            .where(Direccion.objeto == "cuenta", Direccion.objeto_id == cuenta.id)
            .limit(1)
        ).first()
        is not None
    )
    presentes = {
        "nombre": bool(cuenta.nombre),
        "identificador_fiscal": tiene_nif,
        "direccion": tiene_direccion,
        "telefono": bool(cuenta.telefono),
        "email": bool(cuenta.email),
        "web": bool(cuenta.web),
        "sector_codigo": bool(cuenta.sector_codigo),
        "owner_id": cuenta.owner_id is not None,
        "tamano": bool(cuenta.tamano),
    }
    cuenta.calidad, cuenta.calidad_faltan = norm.puntuar_calidad(presentes, norm.PESOS_CUENTA)


# ── Jerarquías ────────────────────────────────────────────────────────────


def enlazar_jerarquia(
    db: Session,
    *,
    cuenta_id: UUID,
    padre_id: UUID,
    jerarquia: str = "legal",
    rol: str | None = None,
) -> JerarquiaCuenta:
    """Cuelga una cuenta de otra dentro de una jerarquía concreta.

    Comprueba que no se forme un ciclo. Un ciclo en la jerarquía de cuentas hace
    que cualquier recorrido —consolidar importes, calcular visibilidad— no
    termine nunca, y el síntoma es una petición colgada, no un error claro.
    """
    # La comprobación de ciclos vive en el núcleo —la usan varios servicios, y
    # uno no puede importar de otro— y aquí solo se le dice cómo subir por los
    # padres de ESTA jerarquía.
    from crmcore.datos.jerarquia import comprobar_ciclo

    def _padre_de(id_cuenta: UUID) -> UUID | None:
        return db.execute(
            select(JerarquiaCuenta.padre_id).where(
                JerarquiaCuenta.cuenta_id == id_cuenta,
                JerarquiaCuenta.jerarquia == jerarquia,
            )
        ).scalar_one_or_none()

    comprobar_ciclo(_padre_de, hijo=cuenta_id, nuevo_padre=padre_id)

    cuenta = _cuenta(db, cuenta_id)
    existente = db.execute(
        select(JerarquiaCuenta).where(
            JerarquiaCuenta.cuenta_id == cuenta_id, JerarquiaCuenta.jerarquia == jerarquia
        )
    ).scalar_one_or_none()
    if existente:
        existente.padre_id = padre_id
        existente.rol = rol
        return existente

    enlace = JerarquiaCuenta(
        tenant_id=cuenta.tenant_id,
        jerarquia=jerarquia,
        cuenta_id=cuenta_id,
        padre_id=padre_id,
        rol=rol,
    )
    db.add(enlace)
    return enlace


def arbol_jerarquia(db: Session, raiz_id: UUID, *, jerarquia: str = "legal") -> dict[str, Any]:
    """Árbol completo desde una cuenta hacia abajo.

    Iterativo y con tope de profundidad: aunque `enlazar_jerarquia` impide los
    ciclos, una carga masiva por SQL directo podría crear uno, y este recorrido
    no puede ser el sitio donde eso se convierte en un proceso colgado.
    """
    from crmcore.config import get_settings

    tope = get_settings().proceso_max_profundidad * 3

    def _hijos(padre_id: UUID, nivel: int) -> list[dict[str, Any]]:
        if nivel > tope:
            return []
        filas = db.execute(
            select(JerarquiaCuenta.cuenta_id, JerarquiaCuenta.rol, Cuenta.nombre)
            .join(Cuenta, Cuenta.id == JerarquiaCuenta.cuenta_id)
            .where(
                JerarquiaCuenta.padre_id == padre_id,
                JerarquiaCuenta.jerarquia == jerarquia,
                Cuenta.deleted_at.is_(None),
            )
            .order_by(Cuenta.nombre)
        ).all()
        return [
            {
                "id": str(cid),
                "nombre": nombre,
                "rol": rol,
                "hijos": _hijos(cid, nivel + 1),
            }
            for cid, rol, nombre in filas
        ]

    raiz = _cuenta(db, raiz_id)
    return {
        "id": str(raiz.id),
        "nombre": raiz.nombre,
        "jerarquia": jerarquia,
        "hijos": _hijos(raiz_id, 1),
    }


# ── Contactos ─────────────────────────────────────────────────────────────


def crear_contacto(
    uow: UnidadDeTrabajo,
    *,
    nombre: str,
    apellidos: str | None = None,
    cuenta_id: UUID | None = None,
    rol: str | None = None,
    forzar: bool = False,
    **datos: Any,
) -> Contacto:
    """Da de alta un contacto y, si se indica, lo vincula a una cuenta."""
    tenant_id = uow.tenant_id
    if tenant_id is None:
        raise ErrorValidacion("Falta el tenant", error_code="party.sin_tenant")

    candidatos = duplicados.buscar_contactos_duplicados(
        uow.db,
        tenant_id=tenant_id,
        nombre=nombre,
        apellidos=apellidos,
        email=datos.get("email"),
    )
    if any(c.concluyente for c in candidatos) and not forzar:
        raise Conflicto(
            "Ya existe un contacto que parece el mismo",
            error_code="party.contacto_duplicado",
            detalle={
                "candidatos": [c.a_dict() for c in candidatos],
                "como_continuar": "usa el contacto existente, o repite con forzar=true",
            },
        )

    completo = " ".join(p for p in [nombre.strip(), (apellidos or "").strip()] if p)
    contacto = Contacto(
        tenant_id=tenant_id,
        nombre=nombre.strip(),
        apellidos=(apellidos or "").strip() or None,
        nombre_completo=completo,
        clave_canonica=norm.clave_canonica_persona(nombre, apellidos),
        email=norm.normalizar_email(datos.get("email")) or None,
        telefono=norm.normalizar_telefono(datos.get("telefono")) or None,
        movil=norm.normalizar_telefono(datos.get("movil")) or None,
        **{k: v for k, v in datos.items() if k not in ("email", "telefono", "movil")},
    )
    uow.db.add(contacto)
    uow.db.flush()

    if cuenta_id:
        vincular_contacto(
            uow.db, contacto_id=contacto.id, cuenta_id=cuenta_id, rol=rol, principal=False
        )

    # Mismo motivo que en la cuenta: el vínculo con la cuenta cuenta para la
    # puntuación y hay que volcarlo antes de mirarlo.
    uow.db.flush()
    _recalcular_calidad_contacto(uow.db, contacto)
    registrar(
        uow.db,
        accion="contacto.creado",
        objeto="contacto",
        objeto_id=contacto.id,
        datos={"nombre": completo, "cuenta_id": str(cuenta_id) if cuenta_id else None},
    )
    _indexar(uow.db, "contacto", contacto)
    return contacto


def vincular_contacto(
    db: Session,
    *,
    contacto_id: UUID,
    cuenta_id: UUID,
    rol: str | None = None,
    cargo: str | None = None,
    principal: bool = False,
) -> RelacionContactoCuenta:
    """Vincula un contacto con una cuenta (CRM-01.01.02.02)."""
    contacto = db.get(Contacto, contacto_id)
    cuenta = db.get(Cuenta, cuenta_id)
    if contacto is None or cuenta is None:
        raise NoEncontrado(
            "El contacto o la cuenta no existen", error_code="party.vinculo_no_encontrado"
        )

    existente = db.execute(
        select(RelacionContactoCuenta).where(
            RelacionContactoCuenta.contacto_id == contacto_id,
            RelacionContactoCuenta.cuenta_id == cuenta_id,
        )
    ).scalar_one_or_none()
    if existente is not None:
        existente.rol = rol or existente.rol
        existente.cargo = cargo or existente.cargo
        existente.hasta = None
        vinculo = existente
    else:
        vinculo = RelacionContactoCuenta(
            tenant_id=contacto.tenant_id,
            contacto_id=contacto_id,
            cuenta_id=cuenta_id,
            rol=rol,
            cargo=cargo,
        )
        db.add(vinculo)

    if principal:
        # Solo puede haber un principal vivo por cuenta, y el índice único
        # parcial lo garantiza: hay que bajar el anterior ANTES de subir este o
        # la base rechaza la operación.
        for otro in (
            db.execute(
                select(RelacionContactoCuenta).where(
                    RelacionContactoCuenta.cuenta_id == cuenta_id,
                    RelacionContactoCuenta.principal.is_(True),
                    RelacionContactoCuenta.hasta.is_(None),
                )
            )
            .scalars()
            .all()
        ):
            otro.principal = False
        db.flush()
        vinculo.principal = True

    db.flush()
    return vinculo


def cerrar_vinculo(db: Session, *, contacto_id: UUID, cuenta_id: UUID, motivo: str = "") -> None:
    """Cierra el vínculo sin borrarlo: la persona dejó esa empresa.

    Borrarlo dejaría sin sentido el histórico de la cuenta —quién firmó aquel
    contrato— y perdería el recorrido profesional del contacto.
    """
    from datetime import date

    vinculo = db.execute(
        select(RelacionContactoCuenta).where(
            RelacionContactoCuenta.contacto_id == contacto_id,
            RelacionContactoCuenta.cuenta_id == cuenta_id,
            RelacionContactoCuenta.hasta.is_(None),
        )
    ).scalar_one_or_none()
    if vinculo is None:
        raise NoEncontrado("No hay vínculo vivo entre esos dos", error_code="party.vinculo_no_vivo")
    vinculo.hasta = date.today()
    vinculo.principal = False
    registrar(
        db,
        accion="contacto.vinculo_cerrado",
        objeto="contacto",
        objeto_id=contacto_id,
        datos={"cuenta_id": str(cuenta_id)},
        motivo=motivo or None,
    )


def _recalcular_calidad_contacto(db: Session, contacto: Contacto) -> None:
    tiene_cuenta = (
        db.execute(
            select(RelacionContactoCuenta.id)
            .where(RelacionContactoCuenta.contacto_id == contacto.id)
            .limit(1)
        ).first()
        is not None
    )
    presentes = {
        "nombre": bool(contacto.nombre),
        "apellidos": bool(contacto.apellidos),
        "email": bool(contacto.email),
        "telefono": bool(contacto.telefono or contacto.movil),
        "cargo": bool(contacto.cargo),
        "cuenta": tiene_cuenta,
        "owner_id": contacto.owner_id is not None,
    }
    contacto.calidad, contacto.calidad_faltan = norm.puntuar_calidad(presentes, norm.PESOS_CONTACTO)


# ── Consentimientos ───────────────────────────────────────────────────────


def registrar_consentimiento(
    uow: UnidadDeTrabajo,
    *,
    contacto_id: UUID,
    finalidad: str,
    canal: str,
    concedido: bool,
    base_legal: str = "consentimiento",
    origen: str | None = None,
    texto_aceptado: str | None = None,
    evidencia: dict[str, Any] | None = None,
) -> Consentimiento:
    """Anota un consentimiento como fila NUEVA (CRM-01.01.02.06).

    Nunca se actualiza el anterior: la historia completa es lo que demuestra que
    en el momento del envío había permiso. Sobrescribir deja el sistema sin
    defensa ante una reclamación, que es justo cuando hace falta.
    """
    contacto = uow.db.get(Contacto, contacto_id)
    if contacto is None:
        raise NoEncontrado("El contacto no existe", error_code="party.contacto_no_encontrado")

    fila = Consentimiento(
        tenant_id=contacto.tenant_id,
        contacto_id=contacto_id,
        finalidad=finalidad,
        canal=canal,
        concedido=concedido,
        base_legal=base_legal,
        origen=origen,
        texto_aceptado=texto_aceptado,
        evidencia=evidencia or {},
    )
    uow.db.add(fila)
    registrar(
        uow.db,
        accion="contacto.consentimiento",
        objeto="contacto",
        objeto_id=contacto_id,
        datos={"finalidad": finalidad, "canal": canal, "concedido": concedido},
    )
    uow.emitir(
        "contact.consent.changed",
        subject=("contacto", contacto_id),
        data={
            "contacto_id": str(contacto_id),
            "finalidad": finalidad,
            "canal": canal,
            "concedido": concedido,
        },
    )
    return fila


def consentimiento_vigente(db: Session, contacto_id: UUID, *, finalidad: str, canal: str) -> bool:
    """Si HOY se puede contactar a esa persona por ese canal y esa finalidad.

    Tres cosas se comprueban, en este orden: el interruptor global de la ficha,
    la caducidad y el último apunte. El orden importa — `no_contactar` manda
    sobre cualquier consentimiento porque es la petición explícita de la persona.
    """
    contacto = db.get(Contacto, contacto_id)
    if contacto is None or contacto.no_contactar:
        return False

    ultimo = db.execute(
        select(Consentimiento)
        .where(
            Consentimiento.contacto_id == contacto_id,
            Consentimiento.finalidad == finalidad,
            Consentimiento.canal == canal,
        )
        .order_by(Consentimiento.fecha.desc())
        .limit(1)
    ).scalar_one_or_none()
    if ultimo is None:
        return False
    if ultimo.caduca_at and ultimo.caduca_at < datetime.now(timezone.utc):
        return False
    return bool(ultimo.concedido)


# ── Actividades ───────────────────────────────────────────────────────────


def crear_actividad(
    uow: UnidadDeTrabajo,
    *,
    tipo: str,
    asunto: str,
    objeto: str | None = None,
    objeto_id: UUID | None = None,
    **datos: Any,
) -> Actividad:
    """Crea una actividad y la cuelga de lo que corresponda.

    Si el objeto es una cuenta o un contacto, se rellenan además las columnas
    desnormalizadas: el timeline de una cuenta necesita traer también lo colgado
    de sus contactos y oportunidades sin recorrer el grafo en cada consulta.
    """
    tenant_id = uow.tenant_id
    if tenant_id is None:
        raise ErrorValidacion("Falta el tenant", error_code="party.sin_tenant")

    cuenta_id = datos.pop("cuenta_id", None)
    contacto_id = datos.pop("contacto_id", None)
    if objeto == "cuenta" and objeto_id:
        cuenta_id = objeto_id
    elif objeto == "contacto" and objeto_id:
        contacto_id = objeto_id
        # La cuenta se deriva del vínculo principal del contacto, para que la
        # actividad aparezca también en el timeline de la empresa.
        if cuenta_id is None:
            cuenta_id = uow.db.execute(
                select(RelacionContactoCuenta.cuenta_id)
                .where(
                    RelacionContactoCuenta.contacto_id == contacto_id,
                    RelacionContactoCuenta.hasta.is_(None),
                )
                .order_by(RelacionContactoCuenta.principal.desc())
                .limit(1)
            ).scalar_one_or_none()

    vence_at = datos.pop("vence_at", None)
    recordar_at = datos.pop("recordar_at", None)
    if vence_at and recordar_at is None:
        from crmcore.runtime import settings as rt

        from services.party.ajustes import ajustes

        horas = int(
            rt.efectivo("actividad_recordatorio_horas", uow.db)
            or ajustes().actividad_recordatorio_horas
        )
        if horas > 0:
            recordar_at = vence_at - timedelta(hours=horas)

    actividad = Actividad(
        tenant_id=tenant_id,
        tipo=tipo,
        asunto=asunto.strip(),
        objeto=objeto,
        objeto_id=objeto_id,
        cuenta_id=cuenta_id,
        contacto_id=contacto_id,
        vence_at=vence_at,
        recordar_at=recordar_at,
        **datos,
    )
    uow.db.add(actividad)
    uow.db.flush()
    return actividad


def completar_actividad(
    db: Session, actividad_id: UUID, *, resultado: str | None = None, por: UUID | None = None
) -> Actividad:
    actividad = db.get(Actividad, actividad_id)
    if actividad is None or actividad.deleted_at is not None:
        raise NoEncontrado("La actividad no existe", error_code="party.actividad_no_encontrada")
    if actividad.estado == "completada":
        raise Conflicto("Esa actividad ya está completada", error_code="party.actividad_completada")
    actividad.estado = "completada"
    actividad.completada_at = datetime.now(timezone.utc)
    actividad.resultado = resultado
    actividad.updated_by = por
    return actividad


# ── Vista 360 (CRM-01.01.05.01, .03) ──────────────────────────────────────


# Implementa CRM-01.01.02.08 (historial completo de interacciones unificado) y
# CRM-01.01.05.03 (perfil unificado consultable por API).
def timeline(
    db: Session,
    *,
    cuenta_id: UUID | None = None,
    contacto_id: UUID | None = None,
    limite: int = 50,
    desde: datetime | None = None,
) -> list[dict[str, Any]]:
    """Todo lo que ha pasado con una cuenta o un contacto, en orden.

    Hoy devuelve actividades y los hitos que el propio servicio conoce. Los de
    otros servicios —oportunidades ganadas, casos abiertos— llegan **por
    eventos**, no consultando sus bases: el timeline no puede depender de que
    ventas y soporte estén en pie, ni saltarse la propiedad de sus datos.

    Esa decisión tiene una consecuencia honesta: un hito cuyo evento se perdió no
    sale en el timeline. Por eso los eventos van por outbox y son at-least-once,
    y por eso hay una cola de fallidos que se puede reenviar.
    """
    if cuenta_id is None and contacto_id is None:
        raise ErrorValidacion(
            "Indica una cuenta o un contacto", error_code="party.timeline_sin_sujeto"
        )

    consulta = select(Actividad).where(Actividad.deleted_at.is_(None))
    if cuenta_id and contacto_id:
        consulta = consulta.where(
            or_(Actividad.cuenta_id == cuenta_id, Actividad.contacto_id == contacto_id)
        )
    elif cuenta_id:
        consulta = consulta.where(Actividad.cuenta_id == cuenta_id)
    else:
        consulta = consulta.where(Actividad.contacto_id == contacto_id)
    if desde:
        consulta = consulta.where(Actividad.created_at >= desde)

    actividades = (
        db.execute(consulta.order_by(Actividad.created_at.desc()).limit(limite)).scalars().all()
    )
    return [
        {
            "momento": a.created_at.isoformat(),
            "tipo": a.tipo,
            "titulo": a.asunto,
            "estado": a.estado,
            "objeto": a.objeto,
            "objeto_id": str(a.objeto_id) if a.objeto_id else None,
            "actor": str(a.created_by) if a.created_by else None,
            "origen": a.created_origen,
            "id": str(a.id),
        }
        for a in actividades
    ]


def vista_360(db: Session, cuenta_id: UUID) -> dict[str, Any]:
    """Perfil unificado de una cuenta, consultable por cualquier frontend."""
    cuenta = _cuenta(db, cuenta_id)

    contactos = db.execute(
        select(Contacto, RelacionContactoCuenta.rol, RelacionContactoCuenta.principal)
        .join(RelacionContactoCuenta, RelacionContactoCuenta.contacto_id == Contacto.id)
        .where(
            RelacionContactoCuenta.cuenta_id == cuenta_id,
            RelacionContactoCuenta.hasta.is_(None),
            Contacto.deleted_at.is_(None),
        )
        .order_by(RelacionContactoCuenta.principal.desc(), Contacto.nombre_completo)
    ).all()

    identificadores = (
        db.execute(select(IdentificadorFiscal).where(IdentificadorFiscal.cuenta_id == cuenta_id))
        .scalars()
        .all()
    )
    direcciones = (
        db.execute(
            select(Direccion).where(Direccion.objeto == "cuenta", Direccion.objeto_id == cuenta_id)
        )
        .scalars()
        .all()
    )

    return {
        "cuenta": {
            "id": str(cuenta.id),
            "nombre": cuenta.nombre,
            "estado": cuenta.estado,
            "roles": cuenta.roles,
            "sector": {"esquema": cuenta.sector_esquema, "codigo": cuenta.sector_codigo},
            "calidad": {"puntuacion": cuenta.calidad, "faltan": cuenta.calidad_faltan},
            "owner_id": str(cuenta.owner_id) if cuenta.owner_id else None,
        },
        "identificadores": [
            {"tipo": i.tipo, "pais": i.pais, "valor": i.valor, "verificado": i.verificado}
            for i in identificadores
        ],
        "direcciones": [
            {"tipo": d.tipo, "linea1": d.linea1, "ciudad": d.ciudad, "pais": d.pais}
            for d in direcciones
        ],
        "contactos": [
            {
                "id": str(c.id),
                "nombre": c.nombre_completo,
                "cargo": c.cargo,
                "email": c.email,
                "rol": rol,
                "principal": principal,
                "no_contactar": c.no_contactar,
            }
            for c, rol, principal in contactos
        ],
        "timeline": timeline(db, cuenta_id=cuenta_id, limite=20),
        # Las métricas de otros dominios (facturación, incidencias, NPS) llegan
        # cuando existan sus servicios. Se declara el hueco en vez de omitirlo:
        # un consumidor tiene que poder distinguir «no hay datos» de «este CRM
        # no lo tiene todavía».
        "metricas": {
            "disponibles": False,
            "motivo": "los servicios de ventas y soporte llegan en las fases 2 y 3",
        },
    }


# ── Derechos del interesado (CRM-07.03.01.03) ─────────────────────────────


def crear_solicitud_derechos(
    db: Session,
    *,
    tenant_id: UUID,
    email_solicitante: str,
    tipo: str,
    contacto_id: UUID | None = None,
    canal_entrada: str | None = None,
) -> SolicitudDerechos:
    """Registra una solicitud y calcula su plazo legal.

    El plazo se fija **al recibirla**, no al empezar a tramitarla: el reloj
    corre desde que llega, y empezar a contar cuando alguien la mira sería
    incumplir sin enterarse.
    """
    from crmcore.runtime import settings as rt

    from services.party.ajustes import ajustes

    dias = int(rt.efectivo("derechos_plazo_dias", db) or ajustes().derechos_plazo_dias)
    ahora = datetime.now(timezone.utc)

    solicitud = SolicitudDerechos(
        tenant_id=tenant_id,
        contacto_id=contacto_id,
        email_solicitante=norm.normalizar_email(email_solicitante),
        tipo=tipo,
        canal_entrada=canal_entrada,
        recibida_at=ahora,
        vence_at=ahora + timedelta(days=dias),
    )
    db.add(solicitud)
    registrar(
        db,
        accion="derechos.solicitud_recibida",
        objeto="solicitud_derechos",
        objeto_id=solicitud.id,
        datos={"tipo": tipo, "vence_at": solicitud.vence_at.isoformat()},
        tenant_id=tenant_id,
    )
    return solicitud
