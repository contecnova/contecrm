"""Publicar el esquema, previsualizar el cambio, empaquetarlo y rastrearlo
(CRM-00.04.03.09, .10, .11, .12).

Lo que separa una implantación cómoda de una que acaba pidiendo desarrollo no es
poder definir un campo: es lo que pasa **alrededor** del cambio.

* Quien añade un campo obligatorio a un objeto con ochenta mil registros no sabe
  que los ochenta mil se quedan sin rellenar hasta que alguien no puede guardar.
  Por eso se previsualiza antes.
* Quien lo configura lo hace en un entorno de pruebas y después tiene que
  repetirlo a mano en producción, a menudo de memoria. Por eso se empaqueta.
* Quien encuentra un campo raro dos años después no sabe quién lo puso ni si se
  usa. Por eso se rastrea.

Y publicar es un acto explícito: mientras se está configurando, el esquema **no**
se replica. Si cada campo a medio definir viajara a todos los servicios, el
cliente vería su formulario cambiar mientras el consultor todavía está pensando.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from crmcore.metamodelo import ESQUEMA_CAMBIADO, UsoCampo
from sqlalchemy import (
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.metadata.modelos import CampoDefinido, ObjetoDefinido

logger = get_logger(__name__)


class PublicacionEsquema(Base, TimestampMixin):
    """Cada publicación del esquema de un objeto, con lo que se publicó.

    Guardar la foto entera y no solo el número de versión es lo que permite
    volver atrás sin reconstruir nada, y lo que hace que «qué había antes del
    martes» sea una consulta y no una arqueología.
    """

    __tablename__ = "publicaciones_esquema"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    campos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    publicado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    nota: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "objeto", "version", name="uq_publicacion_esquema"),
    )


# ── Publicar (CRM-00.04.03.02) ────────────────────────────────────────────


def _definicion(campo: CampoDefinido) -> dict[str, Any]:
    """La forma en que un campo viaja a los demás servicios.

    Se manda lo que hace falta para **validar, filtrar e indexar**, y no el
    modelo entero: la etiqueta y la ayuda son de presentación y las pide el
    `describe` quien las necesita. Mandar de más engorda cada evento y ata la
    réplica a cambios que no le afectan.
    """
    return {
        "nombre": campo.nombre,
        "tipo": campo.tipo,
        "obligatorio": campo.obligatorio,
        "unico": campo.unico,
        "solo_lectura": campo.solo_lectura,
        "deprecado": campo.deprecado,
        "activo": campo.activo,
        "valor_defecto": campo.valor_defecto,
        "restricciones": campo.restricciones or {},
        "sensibilidad": campo.sensibilidad,
        "indexado": bool((campo.restricciones or {}).get("indexado")),
    }


def esquema_actual(db: Session, tenant_id: UUID, objeto: str) -> list[dict[str, Any]]:
    fila = db.execute(
        select(ObjetoDefinido).where(
            ObjetoDefinido.tenant_id == tenant_id, ObjetoDefinido.nombre == objeto
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("El objeto no existe", error_code="metadata.objeto_no_encontrado")
    campos = (
        db.execute(
            select(CampoDefinido)
            .where(CampoDefinido.objeto_id == fila.id, CampoDefinido.activo.is_(True))
            .order_by(CampoDefinido.orden, CampoDefinido.nombre)
        )
        .scalars()
        .all()
    )
    return [_definicion(c) for c in campos]


def ultima_publicacion(db: Session, tenant_id: UUID, objeto: str) -> PublicacionEsquema | None:
    return db.execute(
        select(PublicacionEsquema)
        .where(PublicacionEsquema.tenant_id == tenant_id, PublicacionEsquema.objeto == objeto)
        .order_by(PublicacionEsquema.version.desc())
        .limit(1)
    ).scalar_one_or_none()


def publicar(
    db: Session, tenant_id: UUID, objeto: str, *, por: UUID | None = None, nota: str = ""
) -> dict[str, Any]:
    """Congela el esquema y lo emite a todos los servicios.

    Publicar es explícito porque configurar no lo es: mientras alguien define
    campos, el esquema a medias no puede viajar. Si viajara, el cliente vería su
    formulario cambiar mientras el consultor todavía está pensando, y una
    validación a medio escribir rechazaría altas buenas.
    """
    campos = esquema_actual(db, tenant_id, objeto)
    anterior = ultima_publicacion(db, tenant_id, objeto)
    if anterior is not None and anterior.campos == campos:
        raise Conflicto(
            "No hay nada que publicar: el esquema es idéntico al publicado.",
            error_code="metadata.sin_cambios",
            detalle={"version": anterior.version},
        )

    version = (anterior.version + 1) if anterior else 1

    from crmcore.db.uow import UnidadDeTrabajo

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    # Antes de congelar nada: si este esquema rompe el contrato protobuf que ya
    # tiene alguien integrado, se para aquí. Publicar y descubrirlo después
    # obligaría a despublicar, y mientras tanto el contrato malo ya salió.
    from services.metadata import contrato_rpc

    contrato = contrato_rpc.sincronizar(uow, objeto=objeto, campos=campos)

    fila = PublicacionEsquema(
        tenant_id=tenant_id,
        objeto=objeto,
        version=version,
        campos=campos,
        publicado_por=por,
        nota=nota,
    )
    db.add(fila)
    db.flush()

    uow.emitir(
        ESQUEMA_CAMBIADO,
        subject=("objeto", objeto),
        data={
            "objeto": objeto,
            "cambio": "publicacion",
            "campos": campos,
            "version": version,
            # Los números del contrato protobuf VAN CON EL ESQUEMA. Sin ellos,
            # cada servicio los recalcularía al servir por gRPC y le saldrían
            # otros: un número reutilizado no rompe nada visible —el mensaje se
            # decodifica y el valor entra en el campo equivocado—, y nadie se
            # entera hasta que alguien pregunta por qué ese cliente tiene una
            # zona que no existe. El número es el contrato; el orden es
            # cosmético.
            "numeros_rpc": contrato.get("numeros") or {},
        },
        dedup_key=f"esquema:{tenant_id}:{objeto}:{version}",
    )
    uow.volcar()

    registrar(
        db,
        accion="metadata.esquema_publicado",
        objeto="objeto",
        objeto_id=fila.id,
        datos={"objeto": objeto, "version": version, "campos": len(campos), "nota": nota},
        tenant_id=tenant_id,
    )
    return {
        "objeto": objeto,
        "version": version,
        "campos": len(campos),
        # Qué números tienen los campos en el contrato binario y qué se queda
        # fuera. Va en la respuesta porque quien publica es quien tiene que
        # enterarse de que su campo cifrado no sale por gRPC — no el integrador
        # tres semanas después.
        "contrato_rpc": {
            "numeros": contrato["numeros"],
            "campos_nuevos": contrato["campos_nuevos"],
            "campos_que_no_salen": contrato["campos_que_no_salen"],
        },
    }


# ── Previsualizar el cambio (CRM-00.04.03.09) ─────────────────────────────

# Tablas donde vive cada objeto estándar. Hace falta para poder contar registros
# afectados, y está aquí y no deducido del nombre porque un plural mal adivinado
# daría un «cero registros afectados» tranquilizador y falso.
TABLAS = {
    "cuenta": "cuentas",
    "contacto": "contactos",
    "lead": "leads",
    "oportunidad": "oportunidades",
    "actividad": "actividades",
}


def _tabla_de(nombre: str) -> Any:
    """Una tabla anónima con lo justo para contar: identificador y JSONB.

    Basta con declarar las dos columnas que se consultan; SQLAlchemy no
    necesita el modelo entero y esto evita que `metadata` tenga que importar los
    modelos de otro servicio —que además no puede—.
    """
    from sqlalchemy import column, table
    from sqlalchemy.dialects.postgresql import JSONB as _JSONB
    from sqlalchemy.dialects.postgresql import UUID as _PgUUID

    # El tipo de `tenant_id` va declarado: sin él, SQLAlchemy lo enlaza como
    # texto y Postgres rechaza `uuid = varchar` con un error que no dice nada de
    # lo que pasa de verdad.
    return table(nombre, column("tenant_id", _PgUUID(as_uuid=True)), column("campos", _JSONB))


def previsualizar(db: Session, tenant_id: UUID, objeto: str) -> dict[str, Any]:
    """Qué pasaría al publicar: a cuántos afecta y qué se rompe.

    Quien añade un campo obligatorio a un objeto con ochenta mil registros no
    sabe que los ochenta mil se quedan sin rellenar — y no lo sabe hasta que
    alguien intenta guardar uno viejo y no puede. Esta llamada lo dice antes,
    que es la diferencia entre una decisión y una sorpresa.
    """
    campos = esquema_actual(db, tenant_id, objeto)
    anterior = ultima_publicacion(db, tenant_id, objeto)
    previos = {c["nombre"]: c for c in (anterior.campos if anterior else [])}
    actuales = {c["nombre"]: c for c in campos}

    anadidos = sorted(set(actuales) - set(previos))
    retirados = sorted(set(previos) - set(actuales))
    cambiados = sorted(n for n in set(previos) & set(actuales) if previos[n] != actuales[n])

    tabla = TABLAS.get(objeto)
    total = None
    sin_rellenar: dict[str, int] = {}
    avisos: list[str] = []

    if tabla is None:
        # Se dice, en vez de devolver ceros: «no se ha podido contar» y «no
        # afecta a nadie» son cosas distintas, y la diferencia es justo la que
        # importa antes de publicar.
        avisos.append(
            f"No se ha podido contar los registros de «{objeto}»: este servicio "
            "no sabe en qué tabla vive. El recuento de afectados no es fiable."
        )
    else:
        # Se construye con las primitivas de SQLAlchemy y no con texto: aquí el
        # nombre de la tabla sale de una tabla cerrada y sería seguro, pero el
        # gate que prohíbe componer SQL a mano existe porque el siguiente que
        # copie este patrón interpolará algo que venga de una petición. Una
        # excepción «segura» es exactamente cómo se pierde la garantía.
        destino = _tabla_de(tabla)
        total = int(
            db.execute(
                select(func.count()).select_from(destino).where(destino.c.tenant_id == tenant_id)
            ).scalar_one()
            or 0
        )
        for nombre in anadidos + cambiados:
            definicion = actuales[nombre]
            if not definicion.get("obligatorio"):
                continue
            faltan = int(
                db.execute(
                    select(func.count())
                    .select_from(destino)
                    .where(
                        destino.c.tenant_id == tenant_id,
                        destino.c.campos[nombre].astext.is_(None),
                    )
                ).scalar_one()
                or 0
            )
            if faltan:
                sin_rellenar[nombre] = faltan
                avisos.append(
                    f"«{nombre}» es obligatorio y {faltan} registros no lo tienen: "
                    "no se podrán guardar hasta rellenarlo."
                )

    for nombre in retirados:
        uso = db.execute(
            select(UsoCampo).where(
                UsoCampo.tenant_id == tenant_id,
                UsoCampo.objeto == objeto,
                UsoCampo.campo == nombre,
            )
        ).scalar_one_or_none()
        if uso is not None and uso.escrituras:
            avisos.append(
                f"«{nombre}» se retira y se ha escrito {uso.escrituras} veces. "
                "Los valores guardados dejan de verse en la API."
            )

    for nombre in cambiados:
        if previos[nombre].get("tipo") != actuales[nombre].get("tipo"):
            avisos.append(
                f"«{nombre}» cambia de tipo ({previos[nombre]['tipo']} → "
                f"{actuales[nombre]['tipo']}). Los valores ya guardados **no** se "
                "convierten y pueden dejar de validar."
            )

    return {
        "objeto": objeto,
        "version_actual": anterior.version if anterior else 0,
        "version_al_publicar": (anterior.version + 1) if anterior else 1,
        "anadidos": anadidos,
        "retirados": retirados,
        "cambiados": cambiados,
        "registros": total,
        "registros_sin_rellenar": sin_rellenar,
        "avisos": avisos,
        "hay_cambios": bool(anadidos or retirados or cambiados),
        "seguro": not avisos,
    }


# ── Paquetes entre entornos (CRM-00.04.03.10) ─────────────────────────────

FORMATO_PAQUETE = 1


def exportar_paquete(
    db: Session, tenant_id: UUID, objetos: list[str] | None = None
) -> dict[str, Any]:
    """Empaqueta el esquema para llevarlo a otro entorno.

    Lo que se lleva es **la configuración, nunca los datos**. Un paquete que
    arrastrara registros convertiría una promoción a producción en una fuga: los
    datos de pruebas suelen ser copias anonimizadas a medias de clientes reales.
    """
    consulta = select(ObjetoDefinido).where(ObjetoDefinido.tenant_id == tenant_id)
    if objetos:
        consulta = consulta.where(ObjetoDefinido.nombre.in_(objetos))

    salida = []
    for objeto in db.execute(consulta.order_by(ObjetoDefinido.nombre)).scalars():
        salida.append(
            {
                "nombre": objeto.nombre,
                "etiqueta": objeto.etiqueta,
                "etiqueta_plural": objeto.etiqueta_plural,
                "descripcion": objeto.descripcion,
                "origen": objeto.origen,
                "icono": objeto.icono,
                "estados": objeto.estados or {},
                "campos": esquema_actual(db, tenant_id, objeto.nombre),
            }
        )
    return {
        "formato": FORMATO_PAQUETE,
        "generado_at": datetime.now(timezone.utc).isoformat(),
        # El tenant de origen va dentro para poder decir de dónde salió, pero NO
        # se usa al instalar: instalar en el tenant que dice el fichero sería
        # dejar que un paquete decidiera a quién le cambia el esquema.
        "origen_tenant": str(tenant_id),
        "objetos": salida,
    }


def _hash(paquete: dict[str, Any]) -> str:
    import hashlib

    copia = {k: v for k, v in paquete.items() if k not in ("generado_at", "origen_tenant")}
    return hashlib.sha256(json.dumps(copia, sort_keys=True, default=str).encode()).hexdigest()


def instalar_paquete(
    db: Session,
    tenant_id: UUID,
    paquete: dict[str, Any],
    *,
    simular: bool = True,
    por: UUID | None = None,
) -> dict[str, Any]:
    """Instala un paquete de esquema en este tenant.

    `simular=True` es el valor por defecto **a propósito**: instalar de verdad
    tiene que pedirse. Un paquete es un cambio de modelo de datos en producción,
    y el error más caro que puede cometer quien lo maneja es pulsar el botón
    creyendo que todavía estaba mirando.

    Lo que ya existe y difiere **no se pisa en silencio**: se informa y se deja
    fuera salvo que se pida explícitamente. Sobrescribir la configuración que
    alguien ajustó en producción con la de un entorno de pruebas es la forma
    habitual de perder dos semanas de trabajo de un consultor.
    """
    if int(paquete.get("formato") or 0) != FORMATO_PAQUETE:
        raise ErrorValidacion(
            f"Formato de paquete no soportado: {paquete.get('formato')}",
            error_code="metadata.paquete_no_soportado",
            detalle={"soportado": FORMATO_PAQUETE},
        )

    nuevos: list[str] = []
    conflictos: list[dict[str, Any]] = []
    campos_nuevos: list[str] = []

    for definicion in paquete.get("objetos") or []:
        nombre = str(definicion.get("nombre") or "")
        if not nombre:
            continue
        existente = db.execute(
            select(ObjetoDefinido).where(
                ObjetoDefinido.tenant_id == tenant_id, ObjetoDefinido.nombre == nombre
            )
        ).scalar_one_or_none()

        if existente is None:
            nuevos.append(nombre)
            if not simular:
                existente = ObjetoDefinido(
                    tenant_id=tenant_id,
                    nombre=nombre,
                    etiqueta=str(definicion.get("etiqueta") or nombre),
                    etiqueta_plural=str(definicion.get("etiqueta_plural") or ""),
                    descripcion=str(definicion.get("descripcion") or ""),
                    origen=str(definicion.get("origen") or "propio"),
                    icono=str(definicion.get("icono") or ""),
                    estados=definicion.get("estados") or {},
                )
                db.add(existente)
                db.flush()

        actuales = (
            {
                c.nombre: c
                for c in db.execute(
                    select(CampoDefinido).where(CampoDefinido.objeto_id == existente.id)
                ).scalars()
            }
            if existente is not None
            else {}
        )

        for campo in definicion.get("campos") or []:
            nombre_campo = str(campo.get("nombre") or "")
            if not nombre_campo:
                continue
            actual = actuales.get(nombre_campo)
            if actual is None:
                campos_nuevos.append(f"{nombre}.{nombre_campo}")
                if not simular and existente is not None:
                    db.add(
                        CampoDefinido(
                            tenant_id=tenant_id,
                            objeto_id=existente.id,
                            nombre=nombre_campo,
                            etiqueta=str(campo.get("etiqueta") or nombre_campo),
                            tipo=str(campo.get("tipo") or "texto"),
                            obligatorio=bool(campo.get("obligatorio")),
                            unico=bool(campo.get("unico")),
                            solo_lectura=bool(campo.get("solo_lectura")),
                            valor_defecto=campo.get("valor_defecto"),
                            restricciones=campo.get("restricciones") or {},
                            sensibilidad=str(campo.get("sensibilidad") or "interno"),
                        )
                    )
            elif actual.tipo != campo.get("tipo"):
                conflictos.append(
                    {
                        "campo": f"{nombre}.{nombre_campo}",
                        "aqui": actual.tipo,
                        "en_el_paquete": campo.get("tipo"),
                        "motivo": (
                            "El campo ya existe con otro tipo. No se toca: cambiar "
                            "el tipo no convierte los valores ya guardados."
                        ),
                    }
                )

    if not simular:
        db.flush()
        registrar(
            db,
            accion="metadata.paquete_instalado",
            objeto="objeto",
            objeto_id=None,
            datos={
                "hash": _hash(paquete),
                "origen": paquete.get("origen_tenant"),
                "objetos_nuevos": nuevos,
                "campos_nuevos": len(campos_nuevos),
                "conflictos": len(conflictos),
                "por": str(por) if por else None,
            },
            tenant_id=tenant_id,
        )

    return {
        "simulado": simular,
        "hash": _hash(paquete),
        "objetos_nuevos": nuevos,
        "campos_nuevos": campos_nuevos,
        "conflictos": conflictos,
        # Publicar es un paso aparte: instalar deja la configuración puesta pero
        # no la hace efectiva en el resto de servicios hasta que alguien decide.
        "siguiente_paso": "Publicar cada objeto para que el cambio llegue a los servicios",
    }


# ── Uso y trazabilidad (CRM-00.04.03.12) ──────────────────────────────────


def trazabilidad(db: Session, tenant_id: UUID, objeto: str) -> dict[str, Any]:
    """Quién puso cada campo, cuándo, y si se usa.

    Sin esto, la respuesta a «¿puedo quitar este campo?» es siempre «no lo sé», y
    por si acaso no se quita nada: es como un modelo de datos acaba con
    trescientos campos de los que nadie recuerda la mitad.
    """
    fila = db.execute(
        select(ObjetoDefinido).where(
            ObjetoDefinido.tenant_id == tenant_id, ObjetoDefinido.nombre == objeto
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("El objeto no existe", error_code="metadata.objeto_no_encontrado")

    usos = {
        u.campo: u
        for u in db.execute(
            select(UsoCampo).where(UsoCampo.tenant_id == tenant_id, UsoCampo.objeto == objeto)
        ).scalars()
    }
    campos = (
        db.execute(
            select(CampoDefinido)
            .where(CampoDefinido.objeto_id == fila.id)
            .order_by(CampoDefinido.nombre)
        )
        .scalars()
        .all()
    )

    salida = []
    for campo in campos:
        uso = usos.get(campo.nombre)
        salida.append(
            {
                "campo": campo.nombre,
                "tipo": campo.tipo,
                "creado_at": campo.created_at.isoformat() if campo.created_at else None,
                "creado_por": str(campo.created_by) if getattr(campo, "created_by", None) else None,
                "deprecado": campo.deprecado,
                "escrituras": uso.escrituras if uso else 0,
                "ultima_escritura_at": (
                    uso.ultima_escritura_at.isoformat() if uso and uso.ultima_escritura_at else None
                ),
                "materializado": bool(uso and uso.materializado),
                # La recomendación va explícita porque es la conversación real, y
                # se distingue «nunca se ha escrito» de «no se sabe»: un campo
                # creado ayer sin escrituras no es un campo muerto.
                "se_puede_retirar": (uso is None or uso.escrituras == 0) and not campo.deprecado,
            }
        )
    return {
        "objeto": objeto,
        "campos": salida,
        "sin_usar": [c["campo"] for c in salida if c["escrituras"] == 0],
        "publicaciones": [
            {
                "version": p.version,
                "at": p.created_at.isoformat() if p.created_at else None,
                "por": str(p.publicado_por) if p.publicado_por else None,
                "nota": p.nota,
                "campos": len(p.campos or []),
            }
            for p in db.execute(
                select(PublicacionEsquema)
                .where(
                    PublicacionEsquema.tenant_id == tenant_id,
                    PublicacionEsquema.objeto == objeto,
                )
                .order_by(PublicacionEsquema.version.desc())
            ).scalars()
        ],
    }


# ── Materializar a columna real (CRM-00.04.03.11) ─────────────────────────


def candidatos_a_materializar(
    db: Session, tenant_id: UUID, objeto: str, *, minimo_escrituras: int = 10_000
) -> dict[str, Any]:
    """Qué campos justifican una columna de verdad.

    Materializar **no** es la norma: un `ALTER TABLE` en una tabla compartida por
    mil tenants los bloquea a todos, así que el JSONB con índice de expresión es
    el camino normal y esto es la excepción. La excepción se decide con una
    medida y no con una intuición, que es el motivo de este endpoint: sin número,
    cada cliente que note su lista lenta pediría columna, y acabaríamos con el
    `ALTER TABLE` de siempre disfrazado de optimización.
    """
    usos = (
        db.execute(
            select(UsoCampo)
            .where(
                UsoCampo.tenant_id == tenant_id,
                UsoCampo.objeto == objeto,
                UsoCampo.escrituras >= minimo_escrituras,
                UsoCampo.materializado.is_(False),
            )
            .order_by(UsoCampo.escrituras.desc())
        )
        .scalars()
        .all()
    )
    return {
        "objeto": objeto,
        "umbral": minimo_escrituras,
        "candidatos": [{"campo": u.campo, "escrituras": u.escrituras} for u in usos],
        "como_se_hace": (
            "Se añade la columna nullable (no bloquea), se rellena por lotes "
            "desde el JSONB, se crea el índice y solo entonces se empieza a leer "
            "de ella. En ese orden: al revés, la columna se lee vacía mientras se "
            "rellena y las listas salen incompletas sin que falle nada."
        ),
        "por_que_no_siempre": (
            "Un ALTER TABLE en una tabla compartida por mil tenants los bloquea a "
            "todos. El JSONB con índice de expresión es el camino normal; esto es "
            "la excepción, y se decide con una medida."
        ),
    }
