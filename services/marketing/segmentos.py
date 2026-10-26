"""Motor de segmentos: condiciones anidadas, tamaño y supresiones
(CRM-02.01.01.01 a .06).

Reutiliza la gramática de condiciones de `crmcore.authz.abac`: los mismos
operadores que usan las políticas de acceso y el enrutamiento de leads. No es por
ahorrar código — es para que quien aprende a escribir una condición en el producto
la sepa escribir en todos los sitios, y para que el día que se añada un operador
lo tengan las tres cosas.

Lo que este módulo añade sobre esa gramática:

**Anidamiento con lógica booleana.** «(sector = construcción o sector = obra
pública) y no ha comprado en 12 meses» es la consulta normal en marketing. Con una
lista plana de condiciones solo se puede expresar «todo y» o «todo o», y entonces
el segmento se parte en tres que nadie mantiene iguales.

**Operadores temporales relativos.** «Hace menos de 30 días» tiene que evaluarse
cada vez, no guardarse como una fecha: guardada, el segmento «leads recientes»
sigue devolviendo los mismos de hace medio año.

**Las supresiones se aplican siempre, por encima del segmento.** Si fueran una
condición más, bastaría montar un segmento sin acordarse de ponerla para
escribirle a quien pidió que no se le escribiera.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.authz.abac import Condicion, a_sql
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy as hoy_del_cliente
from crmcore.logging import get_logger
from sqlalchemy import and_, not_, or_, select
from sqlalchemy.orm import Session

from services.marketing.modelos import MiembroSegmento, Segmento, Supresion

logger = get_logger(__name__)

# Combinadores del árbol. Tres y no dos: «no» hace falta para expresar «los que
# NO cumplen esto», y sin él hay que negar cada condición a mano — que con
# condiciones anidadas es exactamente donde se cuelan los errores.
COMBINADORES = ("y", "o", "no")


# Profundidad máxima del árbol. Existe porque una definición con anidamiento sin
# fin —por error o a propósito— puede hacer que la evaluación no termine, y el
# síntoma sería una petición que no responde. Siete niveles es mucho más de lo
# que nadie escribe a mano.
def _segmento_profundidad_maxima() -> int:
    """Antes `_segmento_profundidad_maxima() = 7`.

    Era una constante de módulo. Sale del `.env`, que es donde una instalación
    puede afinarla sin tocar código.
    """
    from crmcore.config import get_settings

    return get_settings().segmento_profundidad_maxima


# Operadores temporales relativos. Se evalúan **contra el momento de la
# consulta**, que es lo que hace que un segmento dinámico signifique hoy lo que
# dice. Guardar la fecha calculada haría que «leads recientes» devolviera siempre
# los mismos.
TEMPORALES = {
    "hace_menos_de_dias": lambda valor, hoy: hoy - timedelta(days=int(valor)),
    "hace_mas_de_dias": lambda valor, hoy: hoy - timedelta(days=int(valor)),
}


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ── Validación del árbol (CRM-02.01.01.02) ────────────────────────────────


def validar(definicion: dict[str, Any], *, profundidad: int = 0) -> None:
    """Comprueba el árbol antes de guardarlo.

    Se valida al guardar y no al evaluar: una definición rota que se descubre al
    lanzar la campaña ya ha costado el envío. Aquí falla el que la escribe, con
    el segmento delante.
    """
    if profundidad > _segmento_profundidad_maxima():
        raise ErrorValidacion(
            f"El árbol de condiciones pasa de {_segmento_profundidad_maxima()} niveles.",
            error_code="marketing.segmento_demasiado_anidado",
        )
    if not isinstance(definicion, dict) or not definicion:
        raise ErrorValidacion(
            "La definición del segmento está vacía.",
            error_code="marketing.segmento_sin_definicion",
        )

    if "op" in definicion:
        op = str(definicion.get("op"))
        if op not in COMBINADORES:
            raise ErrorValidacion(
                f"Combinador «{op}» no válido.",
                error_code="marketing.combinador_no_valido",
                detalle={"validos": list(COMBINADORES)},
            )
        hijos = definicion.get("hijos") or []
        if not hijos:
            raise ErrorValidacion(
                f"El combinador «{op}» no tiene condiciones dentro.",
                error_code="marketing.combinador_vacio",
            )
        if op == "no" and len(hijos) != 1:
            raise ErrorValidacion(
                "«no» niega exactamente una condición. Para negar varias, "
                "envuélvelas primero en un «y» o un «o».",
                error_code="marketing.no_con_varios_hijos",
            )
        for hijo in hijos:
            validar(hijo, profundidad=profundidad + 1)
        return

    if not definicion.get("atributo"):
        raise ErrorValidacion(
            "Una condición necesita un atributo.", error_code="marketing.condicion_sin_atributo"
        )


# ── Evaluación en memoria (CRM-02.01.01.01) ───────────────────────────────


def _valor_temporal(operador: str, valor: Any, hoy: date | None = None) -> Any:
    """El límite de un operador temporal, contado desde el día del cliente.

    `hoy` **se recibe**, no se mira el reloj aquí. Con `date.today()` el corte se
    calculaba en UTC: un segmento «leads de los últimos siete días» consultado a
    las 00:30 en Madrid contaba desde el día anterior, y el lead de ayer por la
    noche se quedaba fuera sin que nadie entendiera por qué. Es el mismo motivo
    por el que las funciones puras del producto reciben `hoy` en vez de
    buscárselo.
    """
    fn = TEMPORALES.get(operador)
    if fn is None:
        return valor
    if hoy is None:
        # **No se cae a UTC en silencio.** Caer sería volver al fallo con otro
        # nombre: el corte saldría del reloj del servidor y, de madrugada, un
        # día antes. Quien evalúa un segmento tiene la sesión a mano —viene de
        # una petición o de un trabajo con tenant—, así que esto es un olvido
        # de programación y se dice como tal.
        raise ErrorValidacion(
            f"El operador «{operador}» necesita saber qué día es hoy para el "
            "cliente. Pásalo con `fechas.hoy(db)`: calculado en UTC, de "
            "madrugada el corte se va un día atrás.",
            error_code="marketing.segmento_sin_dia",
        )
    return fn(valor, hoy)


def evalua(definicion: dict[str, Any], ambito: dict[str, Any], hoy: date | None = None) -> bool:
    """¿Este registro está en el segmento?

    Se usa para decidir sobre uno concreto —«¿este lead entra en el recorrido?»—
    mientras que `a_condicion_sql` decide sobre todos. Las dos parten de la
    **misma definición**: dos gramáticas para lo mismo es cómo se acaba con un
    recorrido que admite a alguien que el segmento no lista.
    """
    if "op" in definicion:
        op = definicion["op"]
        hijos = definicion.get("hijos") or []
        if op == "y":
            return all(evalua(h, ambito, hoy) for h in hijos)
        if op == "o":
            return any(evalua(h, ambito, hoy) for h in hijos)
        return not evalua(hijos[0], ambito, hoy)

    operador = str(definicion.get("operador", "="))
    valor = definicion.get("valor")
    if operador in TEMPORALES:
        limite = _valor_temporal(operador, valor, hoy)
        condicion = Condicion(
            atributo=str(definicion["atributo"]),
            operador=">=" if operador == "hace_menos_de_dias" else "<",
            valor=limite,
        )
        return condicion.evaluar(ambito)
    return Condicion(atributo=str(definicion["atributo"]), operador=operador, valor=valor).evaluar(
        ambito
    )


# ── Traducción a SQL (CRM-02.01.01.01, .04) ───────────────────────────────


def a_condicion_sql(
    definicion: dict[str, Any], columnas: dict[str, Any], hoy: date | None = None
) -> Any:
    """Traduce el árbol a un `WHERE`. Lanza si alguna parte no se puede.

    **Lanza en vez de omitir la condición que no sabe traducir.** Omitirla daría
    un segmento más grande que el pedido, y el error se descubriría al recibir la
    queja de alguien a quien no había que escribir. Un segmento que casi acierta
    no se detecta mirándolo.
    """
    if "op" in definicion:
        op = definicion["op"]
        hijos = [a_condicion_sql(h, columnas, hoy) for h in (definicion.get("hijos") or [])]
        if op == "y":
            return and_(*hijos)
        if op == "o":
            return or_(*hijos)
        return not_(hijos[0])

    atributo = str(definicion["atributo"])
    columna = columnas.get(atributo)
    if columna is None:
        raise ErrorValidacion(
            f"No se puede segmentar por «{atributo}» en este objeto.",
            error_code="marketing.atributo_no_segmentable",
            detalle={"segmentables": sorted(columnas)},
        )

    operador = str(definicion.get("operador", "="))
    valor = definicion.get("valor")
    if operador in TEMPORALES:
        limite = _valor_temporal(operador, valor, hoy)
        return columna >= limite if operador == "hace_menos_de_dias" else columna < limite

    traducida = a_sql(columna, operador, valor)
    if traducida is None:
        raise ErrorValidacion(
            f"El operador «{operador}» no tiene traducción a SQL y este segmento "
            "no se puede calcular sobre la base. Cámbialo o usa un atributo "
            "distinto.",
            error_code="marketing.operador_sin_traduccion",
        )
    return traducida


# ── Columnas segmentables por objeto ──────────────────────────────────────


def columnas_de(db: Session, tenant_id: UUID, objeto: str) -> dict[str, Any]:
    """Por qué se puede segmentar en cada objeto.

    Todo sale de `PerfilMarketing`, la proyección local: `marketing` no puede
    leer el esquema de `party` ni el de `sales`, y pedirles cien mil contactos
    por HTTP cada vez que alguien calcula el tamaño de un segmento no es una
    opción. Se replica por evento, igual que los tipos de cambio y el esquema del
    tenant.

    Incluye **los campos propios del tenant** (CRM-00.04.03.03): el campo que un
    consultor añadió en la implantación tiene que poder usarse para segmentar sin
    escribir código, o la promesa de la extensión sin código se queda a medias
    justo donde más se nota.
    """
    from crmcore import metamodelo

    from services.marketing.modelos import PerfilMarketing

    if objeto not in ("lead", "contacto", "cuenta"):
        raise ErrorValidacion(
            f"No se puede segmentar «{objeto}».",
            error_code="marketing.objeto_no_segmentable",
            detalle={"validos": ["lead", "contacto", "cuenta"]},
        )

    columnas = {
        f"{objeto}.{c.name}": getattr(PerfilMarketing, c.name)
        for c in PerfilMarketing.__table__.columns
        if c.name not in ("campos", "tenant_id", "objeto", "id")
    }
    for definicion in metamodelo.campos_de(db, tenant_id, objeto):
        nombre = str(definicion.get("nombre"))
        columnas[f"{objeto}.campos.{nombre}"] = metamodelo._columna(PerfilMarketing, definicion)
    columnas["_modelo"] = PerfilMarketing
    return columnas


# ── Segmentos ─────────────────────────────────────────────────────────────


def crear(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    objeto: str,
    definicion: dict[str, Any],
    dinamico: bool = True,
    excluye: list[UUID] | None = None,
    descripcion: str = "",
) -> Segmento:
    """Crea un segmento, validando su definición."""
    validar(definicion)
    # Se comprueba que se puede traducir **al crear**, no al usar: descubrir que
    # un segmento no se puede calcular el día del envío es descubrirlo tarde.
    # El día no cambia si se traduce o no, pero se pasa el de verdad igualmente:
    # dejarlo en blanco aquí obligaría a que el traductor tuviera un modo «me da
    # igual el día», y ese modo acabaría usándose donde sí importa.
    a_condicion_sql(
        definicion,
        columnas_de(uow.db, uow.tenant_id, objeto),
        hoy_del_cliente(uow.db),
    )

    if uow.db.execute(
        select(Segmento.id).where(Segmento.tenant_id == uow.tenant_id, Segmento.clave == clave)
    ).first():
        raise Conflicto(
            "Ya existe un segmento con esa clave", error_code="marketing.segmento_duplicado"
        )

    fila = Segmento(
        tenant_id=uow.tenant_id,
        clave=clave,
        nombre=nombre,
        descripcion=descripcion,
        objeto=objeto,
        definicion=definicion,
        dinamico=dinamico,
        excluye=[str(s) for s in (excluye or [])],
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _segmento(db: Session, tenant_id: UUID, segmento_id: UUID) -> Segmento:
    fila = db.execute(
        select(Segmento).where(Segmento.id == segmento_id, Segmento.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("El segmento no existe", error_code="marketing.segmento_no_encontrado")
    return fila


def _consulta_de(db: Session, segmento: Segmento) -> Any:
    columnas = columnas_de(db, segmento.tenant_id, segmento.objeto)
    modelo = columnas.pop("_modelo")
    # El día es el del CLIENTE: «altas de los últimos 30 días» calculado en UTC
    # a las 00:30 de Madrid corta por el día de ayer, y quien entró anoche no
    # recibe el envío.
    condicion = a_condicion_sql(segmento.definicion, columnas, hoy_del_cliente(db))
    # Se devuelve el identificador del objeto de origen y no el del perfil: quien
    # consume el segmento quiere el contacto, no nuestra copia de él.
    return select(modelo.objeto_id).where(
        modelo.tenant_id == segmento.tenant_id,
        modelo.objeto == segmento.objeto,
        # Los dados de baja en origen no entran. Siguen en la tabla para que un
        # segmento congelado pueda explicar a quién incluía, pero uno dinámico no
        # puede seguir seleccionando a quien ya no existe.
        modelo.baja.is_(False),
        condicion,
    )


def miembros(
    db: Session, tenant_id: UUID, segmento_id: UUID, *, limite: int = 10_000
) -> list[UUID]:
    """Quién está en el segmento ahora mismo.

    Para un segmento estático devuelve lo congelado; para uno dinámico lo
    calcula. Y en los dos casos **resta las exclusiones y las supresiones**: que
    un segmento congelado se libre de las supresiones sería exactamente el caso
    que la supresión existe para impedir, porque la baja pudo llegar después de
    congelarlo.
    """
    segmento = _segmento(db, tenant_id, segmento_id)

    if not segmento.dinamico:
        ids = list(
            db.execute(
                select(MiembroSegmento.objeto_id)
                .where(MiembroSegmento.segmento_id == segmento.id)
                .limit(limite)
            ).scalars()
        )
    else:
        ids = list(db.execute(_consulta_de(db, segmento).limit(limite)).scalars())

    for excluido in segmento.excluye or []:
        try:
            fuera = set(miembros(db, tenant_id, UUID(str(excluido)), limite=limite))
        except NoEncontrado:
            # Un segmento de exclusión borrado NO se ignora en silencio: si se
            # ignorara, el segmento pasaría a incluir a quien se excluía y nadie
            # lo notaría hasta el envío.
            raise ErrorValidacion(
                f"El segmento «{segmento.clave}» excluye a uno que ya no existe "
                f"({excluido}). Corrige la exclusión antes de usarlo.",
                error_code="marketing.exclusion_rota",
            ) from None
        ids = [i for i in ids if i not in fuera]

    return ids


def tamano(db: Session, tenant_id: UUID, segmento_id: UUID) -> dict[str, Any]:
    """Cuánta gente hay, en el momento de preguntarlo (CRM-02.01.01.04).

    Se devuelve **con la hora del cálculo**: un número sin fecha al lado se lee
    como actual aunque sea de hace tres semanas, y sobre eso se decide un envío.

    También se devuelve cuántos caen por supresión. Enseñar solo el total haría
    que alguien planificara un envío a diez mil y saliera a siete mil sin saber
    por qué faltan tres mil.
    """
    segmento = _segmento(db, tenant_id, segmento_id)
    ids = miembros(db, tenant_id, segmento_id, limite=1_000_000)
    bruto = len(ids)
    alcanzables, suprimidos = filtrar_suprimidos(db, tenant_id, segmento.objeto, ids)

    segmento.tamano = len(alcanzables)
    segmento.tamano_at = _ahora()
    return {
        "segmento": segmento.clave,
        "bruto": bruto,
        "alcanzables": len(alcanzables),
        "suprimidos": len(suprimidos),
        "calculado_at": segmento.tamano_at.isoformat(),
        "dinamico": segmento.dinamico,
        # Se dice si el número es una foto o el estado de ahora: un estático
        # devuelve lo que se congeló, y presentarlo igual que un dinámico haría
        # creer que el segmento se ha recalculado.
        "es_foto_congelada": not segmento.dinamico,
    }


def congelar(uow: UnidadDeTrabajo, segmento_id: UUID) -> dict[str, Any]:
    """Convierte un segmento dinámico en una lista fija (CRM-02.01.01.03).

    Se congela **antes de un envío**, no después: la pregunta «¿a quién se le
    mandó?» tiene que poder contestarse en junio con la lista de marzo, y un
    segmento dinámico en junio devuelve otra gente.
    """
    segmento = _segmento(uow.db, uow.tenant_id, segmento_id)
    ids = miembros(uow.db, uow.tenant_id, segmento_id, limite=1_000_000)

    for viejo in uow.db.execute(
        select(MiembroSegmento).where(MiembroSegmento.segmento_id == segmento.id)
    ).scalars():
        uow.db.delete(viejo)
    for objeto_id in ids:
        uow.db.add(
            MiembroSegmento(
                tenant_id=segmento.tenant_id, segmento_id=segmento.id, objeto_id=objeto_id
            )
        )
    segmento.dinamico = False
    segmento.tamano = len(ids)
    segmento.tamano_at = _ahora()
    uow.db.flush()

    registrar(
        uow.db,
        accion="marketing.segmento_congelado",
        objeto="segmento",
        objeto_id=segmento.id,
        datos={"clave": segmento.clave, "miembros": len(ids)},
        tenant_id=segmento.tenant_id,
    )
    return {"segmento": segmento.clave, "miembros": len(ids)}


# ── Supresiones (CRM-02.01.01.06) ─────────────────────────────────────────


def suprimir(
    uow: UnidadDeTrabajo,
    *,
    direccion: str,
    canal: str = "email",
    motivo: str = "baja",
    ambito: str = "global",
    detalle: str = "",
    contacto_id: UUID | None = None,
) -> Supresion:
    """Añade a alguien a la lista de a quién no se escribe.

    Se suprime **por dirección y no por identificador**: la misma persona puede
    estar en tres fichas duplicadas, y suprimir una sola dejaría que las otras
    dos le siguieran escribiendo — que es exactamente la queja que acaba en una
    denuncia.
    """
    direccion = direccion.strip().lower()
    if not direccion:
        raise ErrorValidacion(
            "Hace falta la dirección a suprimir.", error_code="marketing.supresion_sin_direccion"
        )
    fila = uow.db.execute(
        select(Supresion).where(
            Supresion.tenant_id == uow.tenant_id,
            Supresion.canal == canal,
            Supresion.direccion == direccion,
            Supresion.ambito == ambito,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = Supresion(tenant_id=uow.tenant_id, canal=canal, direccion=direccion, ambito=ambito)
        uow.db.add(fila)
    fila.motivo = motivo
    fila.detalle = detalle or fila.detalle
    fila.contacto_id = contacto_id or fila.contacto_id
    # Una queja por spam es irreversible desde la API: deshacerla con un clic
    # convierte la protección en una casilla.
    fila.permanente = fila.permanente or motivo == "queja"
    uow.db.flush()
    registrar(
        uow.db,
        accion="marketing.suprimido",
        objeto="supresion",
        objeto_id=fila.id,
        datos={"canal": canal, "motivo": motivo, "ambito": ambito},
        tenant_id=uow.tenant_id,
    )
    return fila


def levantar_supresion(uow: UnidadDeTrabajo, supresion_id: UUID, *, motivo: str) -> Supresion:
    """Quita una supresión, salvo que sea permanente."""
    fila = uow.db.get(Supresion, supresion_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "Supresión no encontrada", error_code="marketing.supresion_no_encontrada"
        )
    if fila.permanente:
        raise Conflicto(
            "Esa supresión es permanente: vino de una queja por spam y no se "
            "levanta desde aquí.",
            error_code="marketing.supresion_permanente",
        )
    if not (motivo or "").strip():
        raise ErrorValidacion(
            "Levantar una supresión exige un motivo escrito: es volver a "
            "escribir a alguien que había dicho que no.",
            error_code="marketing.levantar_sin_motivo",
        )
    uow.db.delete(fila)
    registrar(
        uow.db,
        accion="marketing.supresion_levantada",
        objeto="supresion",
        objeto_id=fila.id,
        datos={"direccion": fila.direccion, "motivo": motivo},
        tenant_id=uow.tenant_id,
    )
    return fila


def filtrar_suprimidos(
    db: Session,
    tenant_id: UUID,
    objeto: str,
    ids: list[UUID],
    *,
    canal: str = "email",
    ambito: str = "",
) -> tuple[list[UUID], list[UUID]]:
    """Separa a quién se puede escribir de a quién no.

    Se aplica **sobre la lista final**, después del segmento y de las
    exclusiones. Ponerlo como una condición del segmento haría que un segmento
    escrito sin acordarse de ella alcanzara a quien pidió no ser alcanzado.
    """
    if not ids:
        return [], []

    from services.marketing.modelos import PerfilMarketing

    filas = db.execute(
        select(PerfilMarketing.objeto_id, PerfilMarketing.email).where(
            PerfilMarketing.tenant_id == tenant_id,
            PerfilMarketing.objeto == objeto,
            PerfilMarketing.objeto_id.in_(ids),
        )
    ).all()
    por_id = {i: (e or "").strip().lower() for i, e in filas}

    consulta = select(Supresion.direccion).where(
        Supresion.tenant_id == tenant_id, Supresion.canal == canal
    )
    if ambito:
        consulta = consulta.where(Supresion.ambito.in_(("global", ambito)))
    else:
        consulta = consulta.where(Supresion.ambito == "global")
    suprimidas = set(db.execute(consulta).scalars())

    alcanzables, fuera = [], []
    for objeto_id in ids:
        direccion = por_id.get(objeto_id, "")
        # Sin dirección no se puede escribir: va a «fuera» y no a «alcanzables».
        # Contarlo como alcanzable infla la audiencia y después el envío sale
        # más pequeño de lo prometido sin explicación.
        if not direccion or direccion in suprimidas:
            fuera.append(objeto_id)
        else:
            alcanzables.append(objeto_id)
    return alcanzables, fuera


def solapamiento(db: Session, tenant_id: UUID, a_id: UUID, b_id: UUID) -> dict[str, Any]:
    """Cuánta gente comparten dos segmentos (CRM-02.01.01.07).

    La pregunta real que contesta no es de estadística: es «si lanzo las dos
    campañas esta semana, ¿a cuánta gente le van a llegar las dos?». Por eso se
    devuelve el número **y el porcentaje sobre cada uno**: mil personas comunes
    es mucho si uno de los segmentos tiene mil doscientos y poco si tiene cien
    mil.
    """
    unos = set(miembros(db, tenant_id, a_id, limite=1_000_000))
    otros = set(miembros(db, tenant_id, b_id, limite=1_000_000))
    comunes = unos & otros
    return {
        "a": _segmento(db, tenant_id, a_id).clave,
        "b": _segmento(db, tenant_id, b_id).clave,
        "tamano_a": len(unos),
        "tamano_b": len(otros),
        "comunes": len(comunes),
        "pct_de_a": round(100 * len(comunes) / len(unos), 1) if unos else None,
        "pct_de_b": round(100 * len(comunes) / len(otros), 1) if otros else None,
        "solo_a": len(unos - otros),
        "solo_b": len(otros - unos),
    }
