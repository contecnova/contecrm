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


def exigir_contacto(db: Session, contacto_id: UUID) -> Contacto:
    """El contacto, o 404. Misma razón que `exigir_cuenta`."""
    contacto = db.get(Contacto, contacto_id)
    if contacto is None or contacto.deleted_at is not None:
        raise NoEncontrado("El contacto no existe", error_code="party.contacto_no_encontrado")
    return contacto


def exigir_cuenta(db: Session, cuenta_id: UUID) -> Cuenta:
    """La cuenta, o 404. Pública porque la usan las rutas de subrecursos.

    Un subrecurso de algo que no existe —o que no es tuyo— tiene que responder
    404 igual que el recurso padre. Si no, el mismo identificador da 404 en un
    sitio y 200 en otro, y esa diferencia es por donde se cuelan las fugas
    cuando alguien añade un dato nuevo al subrecurso.
    """
    return _cuenta(db, cuenta_id)


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

    # La validación de forma se aplica **donde se sabe hacer**, que ya son diez
    # países y no uno (CRM-01.01.01.06). Rechazar un identificador extranjero
    # porque no cumple el algoritmo español sería impedir dar de alta a un
    # cliente perfectamente real.
    #
    # `None` significa «no sabemos comprobarlo» y NO bloquea: bloquear lo que no
    # se sabe validar deja al cliente sin forma de continuar. Se guarda y queda
    # pendiente de verificar contra el registro oficial, que es otra cosa.
    from services.party import fiscal

    veredicto, motivo = fiscal.validar(valor, pais, str(datos.get("tipo", "")))
    if veredicto is False:
        raise ErrorValidacion(
            f"«{valor}» no es un identificador fiscal válido de {pais}: {motivo}",
            error_code="party.nif_invalido",
            detalle={"valor": valor, "pais": pais, "motivo": motivo},
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


# ── Equipo de cuenta (CRM-01.01.01.10) ────────────────────────────────────

# Roles del equipo. Lista cerrada a propósito: es lo que permite preguntar «¿qué
# cuentas llevo como técnico?» y que la respuesta signifique lo mismo en toda la
# instalación. Con texto libre, cada comercial escribe el suyo y a los tres
# meses hay «tecnico», «Técnico» y «tec.» conviviendo.
ROLES_EQUIPO = ("owner", "kam", "tecnico", "soporte", "financiero", "otro")
ACCESOS_EQUIPO = ("lectura", "escritura")


def añadir_al_equipo(
    uow: UnidadDeTrabajo,
    *,
    cuenta_id: UUID,
    usuario_id: UUID,
    rol: str,
    acceso: str = "lectura",
    desde: Any = None,
    hasta: Any = None,
) -> Any:
    """Suma a alguien al equipo de una cuenta.

    El **propietario no se añade aquí**: es la columna `owner_id` de la cuenta y
    tener dos sitios donde vive «quién es el dueño» acaba con los dos diciendo
    cosas distintas. Se puede registrar con rol `owner` para dejar constancia de
    que el dueño forma parte del equipo, pero lo que decide la propiedad sigue
    siendo la cuenta.
    """
    from services.party.modelos import MiembroEquipoCuenta

    if rol not in ROLES_EQUIPO:
        raise ErrorValidacion(
            f"Rol de equipo desconocido: «{rol}»",
            error_code="party.rol_equipo_invalido",
            detalle={"admitidos": list(ROLES_EQUIPO)},
        )
    if acceso not in ACCESOS_EQUIPO:
        raise ErrorValidacion(
            f"Acceso desconocido: «{acceso}»",
            error_code="party.acceso_equipo_invalido",
            detalle={"admitidos": list(ACCESOS_EQUIPO)},
        )
    if desde and hasta and hasta < desde:
        # Un intervalo al revés no da error al guardar y deja a la persona sin
        # ver nada nunca. Se rechaza aquí, que es donde se puede explicar.
        raise ErrorValidacion(
            "La fecha de fin es anterior a la de inicio",
            error_code="party.vigencia_invalida",
        )

    cuenta = exigir_cuenta(uow.db, cuenta_id)
    existente = uow.db.execute(
        select(MiembroEquipoCuenta).where(
            MiembroEquipoCuenta.cuenta_id == cuenta_id,
            MiembroEquipoCuenta.usuario_id == usuario_id,
            MiembroEquipoCuenta.rol == rol,
        )
    ).scalar_one_or_none()
    if existente is not None:
        # Repetir el alta actualiza la vigencia y el acceso en vez de fallar: es
        # lo que hace quien renueva a alguien en el equipo, y obligarle a borrar
        # y volver a crear pierde la fecha de alta original.
        existente.acceso = acceso
        existente.desde = desde
        existente.hasta = hasta
        uow.db.flush()
        miembro = existente
    else:
        miembro = MiembroEquipoCuenta(
            tenant_id=cuenta.tenant_id,
            cuenta_id=cuenta_id,
            usuario_id=usuario_id,
            rol=rol,
            acceso=acceso,
            desde=desde,
            hasta=hasta,
        )
        uow.db.add(miembro)
        uow.db.flush()

    registrar(
        uow.db,
        accion="cuenta.equipo_añadido",
        objeto="cuenta",
        objeto_id=cuenta_id,
        datos={"usuario_id": str(usuario_id), "rol": rol, "acceso": acceso},
    )
    # El evento importa porque pertenecer al equipo **da visibilidad**: quien
    # audite quién puede ver qué necesita ver esta alta, y sin evento solo
    # constaría en una tabla que nadie mira.
    uow.emitir(
        "account.team.added",
        subject=("cuenta", cuenta_id),
        data={"cuenta_id": str(cuenta_id), "usuario_id": str(usuario_id), "rol": rol},
    )
    return miembro


def quitar_del_equipo(uow: UnidadDeTrabajo, *, cuenta_id: UUID, miembro_id: UUID) -> None:
    """Saca a alguien del equipo. Borra la fila: no es un dato histórico.

    La alternativa —marcarla inactiva— tendría sentido si alguien fuera a
    consultar el equipo de hace dos años, y nadie lo hace. Lo que sí queda es el
    apunte de auditoría, que es donde se busca «¿desde cuándo dejó de ver esto?».
    """
    from services.party.modelos import MiembroEquipoCuenta

    miembro = uow.db.get(MiembroEquipoCuenta, miembro_id)
    if miembro is None or miembro.cuenta_id != cuenta_id:
        raise NoEncontrado(
            "Ese miembro no está en el equipo de esta cuenta",
            error_code="party.miembro_equipo_no_existe",
        )
    datos = {"usuario_id": str(miembro.usuario_id), "rol": miembro.rol}
    uow.db.delete(miembro)
    uow.db.flush()

    registrar(
        uow.db,
        accion="cuenta.equipo_retirado",
        objeto="cuenta",
        objeto_id=cuenta_id,
        datos=datos,
    )
    uow.emitir(
        "account.team.removed",
        subject=("cuenta", cuenta_id),
        data={"cuenta_id": str(cuenta_id), **datos},
    )


def equipo_de_cuenta(db: Session, cuenta_id: UUID, *, solo_vigentes: bool = False) -> list[Any]:
    """El equipo de una cuenta.

    Por defecto devuelve **todos**, vigentes o no: quien administra el equipo
    necesita ver al que entra el mes que viene y al que salió ayer, o no puede
    corregir una fecha mal puesta. `solo_vigentes` es para quien pregunta «quién
    lleva esto hoy».
    """
    from datetime import date

    from sqlalchemy import or_

    from services.party.modelos import MiembroEquipoCuenta

    consulta = select(MiembroEquipoCuenta).where(MiembroEquipoCuenta.cuenta_id == cuenta_id)
    if solo_vigentes:
        hoy = date.today()
        consulta = consulta.where(
            or_(MiembroEquipoCuenta.desde.is_(None), MiembroEquipoCuenta.desde <= hoy),
            or_(MiembroEquipoCuenta.hasta.is_(None), MiembroEquipoCuenta.hasta >= hoy),
        )
    return list(db.execute(consulta.order_by(MiembroEquipoCuenta.rol)).scalars().all())


# ── Relaciones no jerárquicas entre cuentas (CRM-01.01.01.04) ─────────────

# Tipos conocidos, con su inversa. La inversa se declara y no se deduce: no toda
# relación es simétrica, y adivinarla produce etiquetas absurdas en la ficha del
# otro lado —«es cliente de» donde debería decir «es proveedor de»—.
#
# `otro` existe para lo que el tenant no tenga previsto, con su etiqueta libre:
# una lista cerrada sin escape obliga a forzar la relación real dentro de un
# tipo que no es, y entonces la lista deja de significar nada.
TIPOS_RELACION = {
    "partner": "partner",
    "competidor": "competidor",
    "proveedor": "cliente",
    "cliente": "proveedor",
    "prescriptor": "prescrito_por",
    "prescrito_por": "prescriptor",
    "filial_operativa": "matriz_operativa",
    "matriz_operativa": "filial_operativa",
    "otro": "otro",
}


def relacionar_cuentas(
    uow: UnidadDeTrabajo,
    *,
    cuenta_id: UUID,
    relacionada_id: UUID,
    tipo: str,
    tipo_inverso: str | None = None,
    nota: str = "",
) -> Any:
    """Crea una relación no jerárquica entre dos cuentas.

    **No implica pertenencia ni consolidación**: que A sea partner de B no hace
    que los números de A sumen en B. Esa es toda la diferencia con la jerarquía,
    y por eso son dos tablas y no una con un campo `tipo`.

    Se crea **una sola fila**, no dos. Guardar las dos direcciones obligaría a
    mantenerlas sincronizadas al editar y al borrar, y el día que una se quede
    huérfana la ficha de una cuenta dice que es partner de otra que no lo dice.
    La consulta devuelve las relaciones en las dos direcciones.
    """
    from services.party.modelos import RelacionCuenta

    if cuenta_id == relacionada_id:
        raise ErrorValidacion(
            "Una cuenta no se puede relacionar consigo misma",
            error_code="party.relacion_reflexiva",
        )
    if tipo not in TIPOS_RELACION:
        raise ErrorValidacion(
            f"Tipo de relación desconocido: «{tipo}»",
            error_code="party.tipo_relacion_invalido",
            detalle={"admitidos": sorted(TIPOS_RELACION)},
        )

    exigir_cuenta(uow.db, cuenta_id)
    exigir_cuenta(uow.db, relacionada_id)

    # Las dos direcciones cuentan como la misma relación: si ya existe al revés,
    # se actualiza esa. Crear la simétrica dejaría dos filas diciendo lo mismo y
    # la ficha enseñaría la relación dos veces.
    from sqlalchemy import and_, or_

    existente = (
        uow.db.execute(
            select(RelacionCuenta).where(
                or_(
                    and_(
                        RelacionCuenta.cuenta_id == cuenta_id,
                        RelacionCuenta.relacionada_id == relacionada_id,
                    ),
                    and_(
                        RelacionCuenta.cuenta_id == relacionada_id,
                        RelacionCuenta.relacionada_id == cuenta_id,
                    ),
                ),
                RelacionCuenta.tipo == tipo,
            )
        )
        .scalars()
        .first()
    )
    if existente is not None:
        existente.notas = nota or existente.notas
        uow.db.flush()
        return existente

    relacion = RelacionCuenta(
        tenant_id=uow.tenant_id,
        cuenta_id=cuenta_id,
        relacionada_id=relacionada_id,
        tipo=tipo,
        tipo_inverso=tipo_inverso or TIPOS_RELACION[tipo],
        notas=nota,
    )
    uow.db.add(relacion)
    uow.db.flush()

    registrar(
        uow.db,
        accion="cuenta.relacionada",
        objeto="cuenta",
        objeto_id=cuenta_id,
        datos={"relacionada_id": str(relacionada_id), "tipo": tipo},
    )
    return relacion


def relaciones_de_cuenta(db: Session, cuenta_id: UUID) -> list[dict[str, Any]]:
    """Las relaciones de una cuenta, **en las dos direcciones**.

    Una sola fila describe la relación, así que la ficha de la otra cuenta tiene
    que verla igual pero al revés: donde una dice «es proveedor de», la otra dice
    «es cliente de». Se resuelve aquí y no duplicando filas.
    """
    from sqlalchemy import or_

    from services.party.modelos import Cuenta as _Cuenta
    from services.party.modelos import RelacionCuenta

    filas = (
        db.execute(
            select(RelacionCuenta).where(
                or_(
                    RelacionCuenta.cuenta_id == cuenta_id,
                    RelacionCuenta.relacionada_id == cuenta_id,
                )
            )
        )
        .scalars()
        .all()
    )

    salida: list[dict[str, Any]] = []
    for fila in filas:
        directa = fila.cuenta_id == cuenta_id
        otra_id = fila.relacionada_id if directa else fila.cuenta_id
        otra = db.get(_Cuenta, otra_id)
        salida.append(
            {
                "id": str(fila.id),
                "cuenta_id": str(otra_id),
                "cuenta_nombre": otra.nombre if otra else "",
                "tipo": fila.tipo if directa else (fila.tipo_inverso or fila.tipo),
                # Se dice si la fila se guardó en este sentido o en el contrario.
                # Sin esto, quien quiera borrarla desde la ficha de la otra
                # cuenta no sabe qué identificador pasar.
                "sentido": "directa" if directa else "inversa",
                "nota": fila.notas or "",
            }
        )
    return salida


def desrelacionar_cuentas(uow: UnidadDeTrabajo, *, cuenta_id: UUID, relacion_id: UUID) -> None:
    """Quita una relación. Vale desde cualquiera de las dos fichas."""
    from services.party.modelos import RelacionCuenta

    relacion = uow.db.get(RelacionCuenta, relacion_id)
    if relacion is None or cuenta_id not in (relacion.cuenta_id, relacion.relacionada_id):
        raise NoEncontrado(
            "Esa relación no existe o no es de esta cuenta",
            error_code="party.relacion_no_existe",
        )
    datos = {"relacionada_id": str(relacion.relacionada_id), "tipo": relacion.tipo}
    uow.db.delete(relacion)
    uow.db.flush()
    registrar(
        uow.db,
        accion="cuenta.desrelacionada",
        objeto="cuenta",
        objeto_id=cuenta_id,
        datos=datos,
    )


# ── Verificación contra registros externos ────────────────────────────────

# Cuánto vale un veredicto antes de volver a preguntar. Un NIF verificado hace
# tres años no es un NIF verificado; uno verificado esta mañana no hace falta
# volver a preguntarlo y gastar cuota del registro.
DIAS_VEREDICTO_VIGENTE = 90


def verificar_identificador_fiscal(
    uow: UnidadDeTrabajo, *, cuenta_id: UUID, identificador_id: UUID
) -> dict[str, Any]:
    """Comprueba un identificador contra el registro oficial configurado.

    **Si el registro no contesta, no se degrada el dato.** Se conserva el
    veredicto anterior y se devuelve `no_concluyente`. Poner «desconocido»
    encima de un «válido» porque hoy hubo un timeout convertiría cada incidencia
    de red en una pérdida de información.
    """
    from datetime import datetime, timezone

    from crmcore.datos import verificacion as verif

    exigir_cuenta(uow.db, cuenta_id)
    identificador = uow.db.get(IdentificadorFiscal, identificador_id)
    if identificador is None or identificador.cuenta_id != cuenta_id:
        raise NoEncontrado(
            "Ese identificador no es de esta cuenta",
            error_code="party.identificador_no_existe",
        )

    veredicto = verif.verificar(
        uow.db,
        tipo="fiscal",
        valor=identificador.valor_normalizado,
        pais=identificador.pais,
        extra={"tipo": identificador.tipo},
    )

    if not veredicto.no_concluyente:
        identificador.verificado = veredicto.estado == "valido"
        identificador.verificado_at = datetime.now(timezone.utc)
        identificador.verificacion_detalle = veredicto.detalle[:2000]
        registrar(
            uow.db,
            accion="cuenta.identificador_verificado",
            objeto="cuenta",
            objeto_id=cuenta_id,
            datos={"identificador": identificador.valor_normalizado, "estado": veredicto.estado},
        )
        uow.db.flush()

    return {
        "identificador": identificador.valor,
        "pais": identificador.pais,
        **veredicto.a_dict(),
        # Se devuelve también lo que dice la comprobación de forma, que siempre
        # está disponible: sin ella, un `no_concluyente` parecería que no se sabe
        # nada del identificador, y sí se sabe si está bien construido.
        "forma": _forma_de(identificador),
    }


def _forma_de(identificador: IdentificadorFiscal) -> dict[str, Any]:
    from services.party import fiscal

    veredicto, motivo = fiscal.validar(identificador.valor, identificador.pais, identificador.tipo)
    return {"valido": veredicto, "motivo": motivo}


def geocodificar(
    uow: UnidadDeTrabajo, *, objeto: str, objeto_id: UUID, direccion_id: UUID
) -> dict[str, Any]:
    """Pone coordenadas a una dirección con el geocodificador configurado.

    Las coordenadas solo se escriben si el veredicto es concluyente **y** trae
    las dos. Escribir una latitud sin longitud deja un punto en el meridiano de
    Greenwich, que es un sitio muy concreto y casi nunca el correcto.
    """
    from datetime import datetime, timezone
    from decimal import Decimal, InvalidOperation

    from crmcore.datos import verificacion as verif

    direccion = uow.db.get(Direccion, direccion_id)
    if direccion is None or direccion.objeto != objeto or direccion.objeto_id != objeto_id:
        raise NoEncontrado(
            "Esa dirección no es de este registro", error_code="party.direccion_no_existe"
        )

    veredicto = verif.verificar(
        uow.db,
        tipo="direccion",
        valor=", ".join(
            p
            for p in (
                direccion.linea1,
                direccion.linea2,
                direccion.codigo_postal,
                direccion.ciudad,
                direccion.provincia,
            )
            if p
        ),
        pais=direccion.pais,
        extra={
            "linea1": direccion.linea1 or "",
            "codigo_postal": direccion.codigo_postal or "",
            "ciudad": direccion.ciudad or "",
            "pais": direccion.pais,
        },
    )

    latitud = veredicto.datos.get("latitud")
    longitud = veredicto.datos.get("longitud")
    if not veredicto.no_concluyente and latitud is not None and longitud is not None:
        try:
            direccion.latitud = Decimal(str(latitud))
            direccion.longitud = Decimal(str(longitud))
            direccion.geocodificada_at = datetime.now(timezone.utc)
            uow.db.flush()
        except (InvalidOperation, ValueError):
            # El geocodificador devolvió algo que no es un número. Se anota y se
            # deja la dirección como estaba: media coordenada es peor que
            # ninguna.
            logger.warning(
                "party.geocodificacion_invalida",
                direccion=str(direccion_id),
                latitud=str(latitud)[:40],
                longitud=str(longitud)[:40],
            )
            veredicto.no_concluyente = True
            veredicto.detalle = "el geocodificador devolvió coordenadas no numéricas"

    return {
        "direccion_id": str(direccion_id),
        "latitud": float(direccion.latitud) if direccion.latitud is not None else None,
        "longitud": float(direccion.longitud) if direccion.longitud is not None else None,
        **veredicto.a_dict(),
    }
