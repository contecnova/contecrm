"""El esquema del tenant, replicado y aplicado en cada servicio
(CRM-00.04.03.02, .03, .04).

El servicio `metadata` es donde se **definen** los campos que cada cliente añade
en su implantación. Este módulo es lo que hace que esa definición **sirva para
algo** en el servicio que guarda el dato: que la API los valide, que se puedan
filtrar y ordenar, y que un BI externo los lea como columnas.

Sin esto, «añadir un campo por configuración» es una media verdad: el campo se
guarda, sí, pero acepta cualquier cosa, no se puede buscar por él y no sale en
ningún informe. Cada eslabón que falte devuelve al cliente al mismo sitio —pedir
desarrollo—, que es justo lo que se quería evitar.

**Por qué replicado y no consultado.** `party` no puede leer el esquema de
`metadata` —lo impide el gate de arquitectura— y preguntárselo por HTTP en cada
escritura pondría el alta de una cuenta a depender de que otro servicio esté en
pie, además de duplicar la latencia. Se replica por evento, igual que los ajustes
en caliente, las claves de tenant y los tipos de cambio.

**Por qué JSONB y no una columna por campo.** Añadir una columna es un `ALTER
TABLE`: con mil tenants en la misma tabla, el campo que uno añade bloquea a los
novecientos noventa y nueve restantes. En JSONB el esquema de cada tenant es
suyo. Lo que se pierde —tipado e índices— se recupera aquí: índices de expresión
declarados por campo y una vista tipada por tenant. Cuando el volumen justifique
la columna real, existe el camino (CRM-00.04.03.11), pero como excepción medida y
no como norma.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.errors import ErrorValidacion
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

ESQUEMA_CAMBIADO = "metadata.schema.changed"


class EsquemaTenant(Base):
    """Copia local del esquema de un objeto para un tenant.

    Una fila por objeto y tenant, con la lista de campos dentro. Podría ser una
    fila por campo; se ha elegido así porque la consulta real es siempre «dame
    todos los campos de este objeto» y una fila evita el `N` del recorrido en el
    camino más caliente del sistema: cada escritura de cada registro.
    """

    __tablename__ = "esquemas_tenant"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(80), nullable=False)
    # Versión del esquema, que sube con cada cambio. Es lo que permite descartar
    # un evento que llega tarde: la entrega es at-least-once y no garantiza
    # orden, así que sin esto un evento viejo reenviado pisaría el esquema bueno.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    campos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    actualizado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("tenant_id", "objeto", name="uq_esquema_tenant"),)


# ── Lectura ───────────────────────────────────────────────────────────────


def campos_de(db: Session, tenant_id: UUID, objeto: str) -> list[dict[str, Any]]:
    """Los campos personalizados de un objeto en este tenant.

    Devuelve lista vacía si no hay esquema replicado, y eso **no** es un error:
    un tenant que no ha añadido ningún campo es el caso normal. Lo que sí sería
    un error es tratar «no hay esquema» como «acepta cualquier cosa», y por eso
    la validación distingue los dos casos.
    """
    fila = db.execute(
        select(EsquemaTenant).where(
            EsquemaTenant.tenant_id == tenant_id, EsquemaTenant.objeto == objeto
        )
    ).scalar_one_or_none()
    if fila is None:
        return []
    return [c for c in (fila.campos or []) if isinstance(c, dict)]


def campo(db: Session, tenant_id: UUID, objeto: str, nombre: str) -> dict[str, Any] | None:
    for definicion in campos_de(db, tenant_id, objeto):
        if definicion.get("nombre") == nombre:
            return definicion
    return None


# ── Validación y normalización (CRM-00.04.03.02) ──────────────────────────

# Cómo se guarda cada tipo dentro del JSONB. Se normaliza al escribir y no al
# leer: si cada lector convirtiera por su cuenta, dos lectores acabarían
# discrepando —uno leyendo "10" y otro 10— y el filtro no encontraría lo que la
# ficha enseña.
_NUMERICOS = {"numero", "moneda", "porcentaje"}
_TEXTOS = {"texto", "texto_largo", "email", "telefono", "url", "cifrado"}


def _a_decimal(valor: Any, nombre: str) -> float:
    try:
        return float(Decimal(str(valor)))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ErrorValidacion(
            f"«{nombre}» tiene que ser un número.",
            error_code="metamodelo.tipo_invalido",
            errores=[{"campo": nombre, "motivo": "tipo", "mensaje": "se esperaba un número"}],
        ) from exc


def _a_booleano(valor: Any, nombre: str) -> bool:
    if isinstance(valor, bool):
        return valor
    texto = str(valor).strip().lower()
    if texto in {"true", "1", "si", "sí", "yes"}:
        return True
    if texto in {"false", "0", "no"}:
        return False
    raise ErrorValidacion(
        f"«{nombre}» tiene que ser verdadero o falso.",
        error_code="metamodelo.tipo_invalido",
        errores=[{"campo": nombre, "motivo": "tipo", "mensaje": "se esperaba un booleano"}],
    )


def _a_fecha(valor: Any, nombre: str, con_hora: bool) -> str:
    texto = str(valor).strip()
    try:
        if con_hora:
            datetime.fromisoformat(texto.replace("Z", "+00:00"))
        else:
            date.fromisoformat(texto[:10])
    except ValueError as exc:
        raise ErrorValidacion(
            f"«{nombre}» tiene que ser una fecha ISO.",
            error_code="metamodelo.tipo_invalido",
            errores=[{"campo": nombre, "motivo": "tipo", "mensaje": "formato de fecha"}],
        ) from exc
    # Se guarda en texto ISO y no como objeto: JSONB no tiene tipo fecha, y
    # guardarlo ISO es lo que hace que ordenar por texto ordene bien de verdad.
    return texto if con_hora else texto[:10]


def normalizar_valor(definicion: dict[str, Any], valor: Any) -> Any:
    """Convierte un valor al tipo declarado, o explica por qué no puede."""
    nombre = str(definicion.get("nombre", ""))
    tipo = str(definicion.get("tipo", "texto"))
    if valor is None:
        return None

    if tipo in _NUMERICOS:
        return _a_decimal(valor, nombre)
    if tipo == "booleano":
        return _a_booleano(valor, nombre)
    if tipo == "fecha":
        return _a_fecha(valor, nombre, con_hora=False)
    if tipo == "fecha_hora":
        return _a_fecha(valor, nombre, con_hora=True)
    if tipo == "lista_multiple":
        if not isinstance(valor, list):
            raise ErrorValidacion(
                f"«{nombre}» admite varios valores y tiene que llegar como lista.",
                error_code="metamodelo.tipo_invalido",
                errores=[{"campo": nombre, "motivo": "tipo", "mensaje": "se esperaba una lista"}],
            )
        return [str(v) for v in valor]
    if tipo == "json":
        return valor
    if tipo in _TEXTOS or tipo in {"lista", "lookup", "geolocalizacion", "fichero"}:
        return str(valor)
    return valor


def _comprobar_restricciones(definicion: dict[str, Any], valor: Any) -> list[dict[str, Any]]:
    """Las restricciones declaradas del campo, ya con el valor normalizado."""
    nombre = str(definicion.get("nombre", ""))
    tipo = str(definicion.get("tipo", "texto"))
    r = definicion.get("restricciones") or {}
    fallos: list[dict[str, Any]] = []

    if valor is None:
        return fallos

    if tipo in _TEXTOS:
        maximo = r.get("max_longitud")
        if maximo and len(str(valor)) > int(maximo):
            fallos.append(
                {
                    "campo": nombre,
                    "motivo": "longitud",
                    "mensaje": f"máximo {maximo} caracteres",
                }
            )
        patron = r.get("patron")
        if patron:
            import re

            if not re.fullmatch(str(patron), str(valor)):
                fallos.append(
                    {"campo": nombre, "motivo": "patron", "mensaje": "no cumple el formato"}
                )

    if tipo in _NUMERICOS:
        if r.get("minimo") is not None and valor < float(r["minimo"]):
            fallos.append({"campo": nombre, "motivo": "rango", "mensaje": f"mínimo {r['minimo']}"})
        if r.get("maximo") is not None and valor > float(r["maximo"]):
            fallos.append({"campo": nombre, "motivo": "rango", "mensaje": f"máximo {r['maximo']}"})

    if tipo in {"lista", "lista_multiple"}:
        opciones = {str(o) for o in (r.get("opciones") or [])}
        if opciones:
            candidatos = valor if isinstance(valor, list) else [valor]
            fuera = [str(v) for v in candidatos if str(v) not in opciones]
            if fuera:
                fallos.append(
                    {
                        "campo": nombre,
                        "motivo": "opcion",
                        "mensaje": f"valor no permitido: {', '.join(fuera)}",
                        "opciones": sorted(opciones),
                    }
                )
    return fallos


def validar(
    db: Session,
    tenant_id: UUID,
    objeto: str,
    valores: dict[str, Any] | None,
    *,
    parcial: bool = False,
) -> dict[str, Any]:
    """Valida y normaliza los campos personalizados de una escritura.

    Lo que hace que esto valga: **un campo que no está definido se rechaza**.
    Aceptarlo convertiría una errata —`fecha_visita` escrito `fecha_vista`— en un
    dato que se guarda, no sale en ningún formulario y no lo encuentra nadie; y
    al cabo de un año la mitad del JSONB sería basura que nadie se atreve a
    borrar porque no se sabe quién la puso.

    `parcial=True` para actualizaciones: solo se miran los campos que llegan, y
    los obligatorios que no vengan se dan por ya presentes en el registro.
    """
    valores = dict(valores or {})
    definiciones = {str(c.get("nombre")): c for c in campos_de(db, tenant_id, objeto)}

    fallos: list[dict[str, Any]] = []
    salida: dict[str, Any] = {}

    desconocidos = sorted(set(valores) - set(definiciones))
    if desconocidos:
        fallos.append(
            {
                "campo": desconocidos[0],
                "motivo": "desconocido",
                "mensaje": (
                    "No existe en el esquema de este objeto. Si es un campo "
                    "nuevo, defínelo primero en configuración."
                ),
                "campos": desconocidos,
                "definidos": sorted(definiciones),
            }
        )

    for nombre, definicion in definiciones.items():
        presente = nombre in valores
        if presente and definicion.get("solo_lectura"):
            fallos.append(
                {"campo": nombre, "motivo": "solo_lectura", "mensaje": "no se puede escribir"}
            )
            continue
        if presente and definicion.get("deprecado"):
            # Deprecado se LEE pero no se escribe: es lo que permite retirar un
            # campo sin romper de golpe una integración que aún lo manda. Se
            # ignora el valor y se avisa, en vez de fallar y cortarle el alta.
            logger.warning(
                "metamodelo.campo_deprecado", objeto=objeto, campo=nombre, tenant=str(tenant_id)
            )
            continue

        if not presente:
            if definicion.get("valor_defecto") is not None and not parcial:
                salida[nombre] = definicion["valor_defecto"]
            elif definicion.get("obligatorio") and not parcial:
                fallos.append(
                    {"campo": nombre, "motivo": "obligatorio", "mensaje": "es obligatorio"}
                )
            continue

        bruto = valores[nombre]
        if bruto is None:
            if definicion.get("obligatorio"):
                fallos.append(
                    {"campo": nombre, "motivo": "obligatorio", "mensaje": "no puede quedar vacío"}
                )
            else:
                salida[nombre] = None
            continue

        try:
            valor = normalizar_valor(definicion, bruto)
        except ErrorValidacion as exc:
            fallos.extend(exc.errores or [])
            continue
        fallos.extend(_comprobar_restricciones(definicion, valor))
        salida[nombre] = valor

    if fallos:
        raise ErrorValidacion(
            f"Los campos propios de «{objeto}» no son válidos",
            error_code="metamodelo.campos_invalidos",
            errores=fallos,
        )
    return salida


class UsoCampo(Base):
    """Cuántas veces se ha escrito cada campo personalizado (CRM-00.04.03.12).

    Vive en el esquema de **cada servicio** y no solo en `metadata`, porque quien
    ve pasar las escrituras es el servicio dueño del dato: `metadata` define el
    campo y no lo guarda nunca. Una tabla central obligaría a que `party`
    escribiera en el esquema de otro, que es justo lo que no se hace aquí.

    `metadata` la reúne pidiéndola por evento, igual que el inventario documental
    para el certificado de destrucción. Un servicio que no conteste sale como «no
    ha contestado» y no como cero: la diferencia entre «ese campo no lo usa
    nadie» y «no lo he podido comprobar» es toda la que importa antes de retirar
    un campo.
    """

    __tablename__ = "uso_campos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(80), nullable=False)
    campo: Mapped[str] = mapped_column(String(80), nullable=False)
    escrituras: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultima_escritura_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    materializado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (UniqueConstraint("tenant_id", "objeto", "campo", name="uq_uso_campo"),)


def anotar_uso(db: Session, tenant_id: UUID, objeto: str, campos: dict[str, Any]) -> None:
    """Cuenta una escritura por cada campo que llega con valor.

    Se cuenta al escribir y no al leer: leer mide quién mira, escribir mide si el
    campo se rellena, que es la pregunta de quien se plantea retirarlo. Va en la
    misma transacción de la escritura y **no falla nunca**: perder una
    estadística es aceptable; tumbar un alta por ella, no.
    """
    presentes = [k for k, v in (campos or {}).items() if v not in (None, "", [], {})]
    if not presentes:
        return
    # En un SAVEPOINT, no solo en un `try`. Lo de aquí escribe en la MISMA sesión
    # que el alta, y un fallo de la base la deja envenenada: el `except` atrapa
    # el primer error y la siguiente instrucción del alta muere igual con
    # `PendingRollbackError`, con un mensaje que no menciona la causa. Que es
    # exactamente lo que este bloque decía impedir y no impedía.
    from crmcore.db.al_margen import al_margen

    with al_margen(db, "metamodelo.uso_no_anotado", objeto=objeto, tenant=str(tenant_id)):
        for nombre in presentes:
            fila = db.execute(
                select(UsoCampo).where(
                    UsoCampo.tenant_id == tenant_id,
                    UsoCampo.objeto == objeto,
                    UsoCampo.campo == nombre,
                )
            ).scalar_one_or_none()
            if fila is None:
                fila = UsoCampo(tenant_id=tenant_id, objeto=objeto, campo=nombre, escrituras=0)
                db.add(fila)
                # Se vacía en el acto: el contador se busca por SQL, y sin esto
                # dos escrituras en la misma transacción no verían la fila
                # recién añadida e intentarían insertarla otra vez, reventando
                # contra la restricción única. El alta se caía por culpa de una
                # estadística. Ahora, además, el bloque entero va en un
                # SAVEPOINT: si la restricción salta de todas formas, se deshace
                # solo esto y el alta sigue.
                db.flush()
            fila.escrituras += 1
            fila.ultima_escritura_at = func.now()


def validar_y_anotar(
    db: Session,
    tenant_id: UUID,
    objeto: str,
    valores: dict[str, Any] | None,
    *,
    parcial: bool = False,
) -> dict[str, Any]:
    """Lo que llama un servicio en su camino de escritura: valida y cuenta.

    Se ofrece junto para que no haya un camino que valide sin contar: el conteo
    es lo que después permite decir si un campo se puede retirar, y una
    estadística con huecos lleva a retirar algo que sí se usaba.
    """
    salida = validar(db, tenant_id, objeto, valores, parcial=parcial)
    anotar_uso(db, tenant_id, objeto, salida)
    return salida


# ── Filtro y orden (CRM-00.04.03.03) ──────────────────────────────────────

# Los operadores que se admiten sobre un campo personalizado. Cerrados a
# propósito: una gramática abierta sobre JSONB acaba siendo SQL interpolado, y
# ahí es donde entra la inyección. Cada operador se traduce a una expresión
# construida por SQLAlchemy, nunca a texto concatenado.
OPERADORES_FILTRO = ("=", "!=", ">", ">=", "<", "<=", "contiene", "empieza", "en", "vacio")


def _columna(modelo: Any, definicion: dict[str, Any]) -> Any:
    """La expresión SQL del campo, con el casteo de su tipo declarado.

    El casteo es lo que separa un filtro que funciona de uno que miente: sin él,
    JSONB compara **texto**, y `"9" > "10"` es cierto. Un filtro «importe mayor
    que 10» que devuelve el de 9 es peor que no tener filtro, porque el que lo
    usa se lo cree.
    """
    nombre = str(definicion.get("nombre"))
    tipo = str(definicion.get("tipo", "texto"))
    texto = modelo.campos[nombre].astext
    if tipo in _NUMERICOS:
        return texto.cast(Numeric)
    if tipo == "booleano":
        from sqlalchemy import Boolean

        return texto.cast(Boolean)
    if tipo == "fecha":
        from sqlalchemy import Date

        return texto.cast(Date)
    if tipo == "fecha_hora":
        return texto.cast(DateTime(timezone=True))
    return texto


def condicion(
    db: Session,
    modelo: Any,
    tenant_id: UUID,
    objeto: str,
    *,
    campo_nombre: str,
    op: str,
    valor: Any,
) -> Any:
    """Traduce un filtro sobre un campo personalizado a una condición SQL."""
    definicion = campo(db, tenant_id, objeto, campo_nombre)
    if definicion is None:
        raise ErrorValidacion(
            f"«{campo_nombre}» no es un campo de «{objeto}» en este tenant.",
            error_code="metamodelo.campo_desconocido",
            detalle={"definidos": [c["nombre"] for c in campos_de(db, tenant_id, objeto)]},
        )
    if op not in OPERADORES_FILTRO:
        raise ErrorValidacion(
            f"Operador «{op}» no admitido.",
            error_code="metamodelo.operador_no_admitido",
            detalle={"admitidos": list(OPERADORES_FILTRO)},
        )

    columna = _columna(modelo, definicion)
    if op == "vacio":
        return columna.is_(None)
    if op == "en":
        lista = valor if isinstance(valor, list) else [valor]
        return columna.in_([normalizar_valor(definicion, v) for v in lista])
    if op == "contiene":
        return modelo.campos[str(campo_nombre)].astext.ilike(f"%{valor}%")
    if op == "empieza":
        return modelo.campos[str(campo_nombre)].astext.ilike(f"{valor}%")

    normalizado = normalizar_valor(definicion, valor)
    return {
        "=": columna == normalizado,
        "!=": columna != normalizado,
        ">": columna > normalizado,
        ">=": columna >= normalizado,
        "<": columna < normalizado,
        "<=": columna <= normalizado,
    }[op]


def orden(
    db: Session, modelo: Any, tenant_id: UUID, objeto: str, campo_nombre: str, *, desc: bool = False
) -> Any:
    definicion = campo(db, tenant_id, objeto, campo_nombre)
    if definicion is None:
        raise ErrorValidacion(
            f"«{campo_nombre}» no es un campo de «{objeto}» en este tenant.",
            error_code="metamodelo.campo_desconocido",
        )
    columna = _columna(modelo, definicion)
    return columna.desc() if desc else columna.asc()


# ── Índices de expresión (CRM-00.04.03.03) ────────────────────────────────


def _nombre_indice(tabla: str, tenant_id: UUID, campo_nombre: str) -> str:
    """Nombre determinista y corto. Postgres corta a 63 caracteres, y dos
    índices que colisionen al truncarse dejan uno sin crear en silencio."""
    import hashlib

    firma = hashlib.sha1(f"{tabla}:{tenant_id}:{campo_nombre}".encode()).hexdigest()[:12]
    return f"ix_cp_{firma}"


def _expresion_indice(definicion: dict[str, Any]) -> str:
    tipo = str(definicion.get("tipo", "texto"))
    nombre = str(definicion.get("nombre"))
    # El nombre del campo se valida antes de llegar aquí (solo identificadores),
    # pero se comprueba igual: esto acaba en DDL, y en DDL no hay parámetros.
    if not nombre.replace("_", "").isalnum():
        raise ErrorValidacion(
            f"Nombre de campo no indexable: «{nombre}»",
            error_code="metamodelo.nombre_no_indexable",
        )
    acceso = f"(campos ->> '{nombre}')"
    if tipo in _NUMERICOS:
        return f"({acceso}::numeric)"
    if tipo == "fecha":
        return f"({acceso}::date)"
    if tipo == "fecha_hora":
        return f"({acceso}::timestamptz)"
    return acceso


def sql_de_indices(tabla: str, tenant_id: UUID, campos: list[dict[str, Any]]) -> list[str]:
    """Las sentencias de índice para los campos marcados como indexables.

    **Parcial por tenant** (`WHERE tenant_id = …`), y ese es el punto: un índice
    global sobre una expresión JSONB indexaría las filas de los mil tenants para
    servir a las consultas de uno, y crecería con todos ellos. Parcial, cada
    tenant paga solo lo suyo y el índice no existe para quien no lo pidió.
    """
    salida = []
    for definicion in campos:
        if not definicion.get("indexado"):
            continue
        nombre = _nombre_indice(tabla, tenant_id, str(definicion.get("nombre")))
        expresion = _expresion_indice(definicion)
        # DOS pares de paréntesis, y no es cosmético: un índice por EXPRESIÓN
        # los exige. Con uno solo, Postgres lee `campos` como una columna y se
        # atasca en el `->>` — «syntax error at or near "->>"». Las sentencias
        # eran inválidas desde el primer día y nadie se enteró porque **no las
        # ejecutaba nadie**: `sincronizar_indices` no tenía llamante. Se vio al
        # enchufarla, que es exactamente para lo que sirve enchufarla.
        salida.append(
            f"CREATE INDEX IF NOT EXISTS {nombre} ON {tabla} ({expresion}) "
            f"WHERE tenant_id = '{tenant_id}'"
        )
    return salida


def sql_de_retirada(tabla: str, tenant_id: UUID, campos_retirados: list[str]) -> list[str]:
    """Y los que hay que quitar. Un índice que sobra no falla nada: solo hace
    más lenta cada escritura de la tabla para siempre, que es la forma más cara
    de no enterarse."""
    return [
        f"DROP INDEX IF EXISTS {_nombre_indice(tabla, tenant_id, nombre)}"
        for nombre in campos_retirados
    ]


def sincronizar_indices(
    db: Session, tabla: str, tenant_id: UUID, campos: list[dict[str, Any]], retirados: list[str]
) -> dict[str, int]:
    """Crea y retira los índices que el esquema declara.

    No usa `CONCURRENTLY` porque eso exige estar fuera de transacción y aquí se
    corre dentro de la que aplica el esquema. El índice parcial de un tenant se
    construye sobre sus filas, no sobre las de todos, así que el bloqueo es
    proporcional a ese tenant y no a la tabla entera — que era el motivo real
    por el que `CONCURRENTLY` haría falta.
    """
    creados = 0
    for sentencia in sql_de_indices(tabla, tenant_id, campos):
        db.execute(text(sentencia))
        creados += 1
    quitados = 0
    for sentencia in sql_de_retirada(tabla, tenant_id, retirados):
        db.execute(text(sentencia))
        quitados += 1
    return {"creados": creados, "retirados": quitados}


# ── Vista tipada para BI (CRM-00.04.03.04) ────────────────────────────────

_CAST_VISTA = {
    "numero": "numeric",
    "moneda": "numeric",
    "porcentaje": "numeric",
    "booleano": "boolean",
    "fecha": "date",
    "fecha_hora": "timestamptz",
}


def nombre_de_vista(objeto: str, tenant_id: UUID) -> str:
    return f"v_{objeto}_{str(tenant_id).replace('-', '')[:12]}"


def sql_de_vista(
    tabla: str,
    objeto: str,
    tenant_id: UUID,
    campos: list[dict[str, Any]],
    *,
    columnas_base: tuple[str, ...] = ("id", "tenant_id", "created_at", "updated_at"),
) -> str:
    """Una vista que proyecta cada campo personalizado como columna tipada.

    Es lo que permite que Power BI, Metabase o un `SELECT` de alguien de sistemas
    lean los campos de la implantación **sin saber que por debajo es JSONB** y
    sin que nadie escriba `->>` ni recuerde castear. Sin ella, «el campo está en
    la base de datos» es cierto y a la vez inútil: está, pero en un formato que
    ninguna herramienta de informes entiende sola.

    Es una vista y no una tabla materializada a propósito: una materializada se
    queda vieja, y un informe que enseña el dato de ayer presentándolo como el de
    hoy es peor que uno que tarda un segundo más.
    """
    proyecciones = list(columnas_base)
    for definicion in campos:
        if not definicion.get("activo", True):
            continue
        nombre = str(definicion.get("nombre"))
        if not nombre.replace("_", "").isalnum():
            continue
        cast = _CAST_VISTA.get(str(definicion.get("tipo", "texto")))
        acceso = f"campos ->> '{nombre}'"
        expresion = f"({acceso})::{cast}" if cast else f"({acceso})"
        proyecciones.append(f'{expresion} AS "{nombre}"')

    return (
        f"CREATE OR REPLACE VIEW {nombre_de_vista(objeto, tenant_id)} AS "
        f"SELECT {', '.join(proyecciones)} FROM {tabla} WHERE tenant_id = '{tenant_id}'"
    )


def sincronizar_vista(
    db: Session,
    tabla: str,
    objeto: str,
    tenant_id: UUID,
    campos: list[dict[str, Any]],
    **kw: Any,
) -> str:
    """Rehace la vista del tenant. Idempotente.

    Se tira y se vuelve a crear en vez de usar solo `CREATE OR REPLACE` cuando
    cambia el número de columnas: Postgres rechaza reemplazar una vista si las
    columnas no coinciden, y quitar un campo cambia la lista. Fallar ahí dejaría
    la vista congelada en el esquema de antes sin que nadie se enterase.
    """
    db.execute(text(f"DROP VIEW IF EXISTS {nombre_de_vista(objeto, tenant_id)}"))
    sentencia = sql_de_vista(tabla, objeto, tenant_id, campos, **kw)
    db.execute(text(sentencia))
    return sentencia


# ── Réplica del esquema ───────────────────────────────────────────────────


# ── Qué tabla guarda cada objeto, EN ESTE PROCESO ─────────────────────────
#
# Hace falta para aplicar el esquema de verdad. `sincronizar_indices` y
# `sincronizar_vista` estaban escritas, probadas y **sin que las llamara nadie**,
# así que un campo a medida declarado por un tenant se guardaba y se validaba, y
# no recibía **ni índice ni vista**:
#
#   * filtrar u ordenar por él recorría la tabla entera, y eso no da un error:
#     da una pantalla que tarda más cada mes;
#   * y la vista tipada del tenant —`v_oportunidad_01a0cd88…`— no existía,
#     mientras el motor de informes la nombra como entidad de respaldo cuando no
#     hay fuente externa registrada. Ese camino moría con «Table with name
#     v_oportunidad_… does not exist», que es exactamente el fallo que ya se
#     cazó una vez por el otro lado.
#
# El registro es **por proceso** porque cada servicio guarda lo suyo: el evento
# de esquema llega a los catorce y sólo el dueño de la tabla puede crear su
# índice. Los demás lo replican para validar y no tocan nada.
_TABLA_DEL_OBJETO: dict[str, str] = {}
_MODELO_DEL_OBJETO: dict[str, type] = {}


def declarar_tabla(objeto: str, tabla: str, modelo: type | None = None) -> None:
    """Dice qué tabla —y qué modelo— guarda este objeto en este servicio.

    Lo apuntan solos `montar_listado` y `montar_ficha`, que ya reciben el modelo
    y el objeto juntos. Declarar dos veces el mismo es inocuo.

    El modelo se guarda además de la tabla porque hay dos cosas que necesitan
    saber de este objeto y necesitan cosas distintas: el esquema físico necesita
    el **nombre** de la tabla (acaba en DDL, donde no hay parámetros) y la
    sincronización del móvil necesita la **clase**, para leer la versión del
    registro sin escribir SQL a mano.
    """
    if objeto and tabla:
        _TABLA_DEL_OBJETO.setdefault(str(objeto), str(tabla))
    if objeto and modelo is not None:
        _MODELO_DEL_OBJETO.setdefault(str(objeto), modelo)


def tabla_del_objeto(objeto: str) -> str:
    """La tabla de este objeto en este proceso, o cadena vacía si no es suyo."""
    return _TABLA_DEL_OBJETO.get(str(objeto), "")


def modelo_del_objeto(objeto: str) -> type | None:
    """La clase de este objeto en este proceso, o `None` si no es suyo."""
    return _MODELO_DEL_OBJETO.get(str(objeto))


def tablas_declaradas() -> dict[str, str]:
    return dict(_TABLA_DEL_OBJETO)


def aplicar_esquema_fisico(
    db: Session, *, tenant_id: UUID, objeto: str, campos: list[dict[str, Any]]
) -> dict[str, Any]:
    """Crea los índices y la vista del tenant para este objeto. **Idempotente.**

    Si este proceso no es el dueño de la tabla, no hace nada y lo dice: no es un
    fallo, es que ese objeto vive en otro servicio y el esquema le llegó por el
    bus igual que a todos.

    Un fallo aquí **no tumba la réplica del esquema**: la validación con los
    campos nuevos es lo urgente —el consultor tiene al cliente delante— y un
    índice que no se pudo crear se vuelve a intentar en la publicación
    siguiente. Lo que no se hace es callarlo.
    """
    tabla = tabla_del_objeto(objeto)
    if not tabla:
        return {"aplicado": False, "porque": "este servicio no guarda ese objeto"}

    anterior = db.execute(
        select(EsquemaTenant).where(
            EsquemaTenant.tenant_id == tenant_id, EsquemaTenant.objeto == objeto
        )
    ).scalar_one_or_none()
    nombres = {str(c.get("nombre") or "") for c in campos}
    retirados = [
        str(c.get("nombre") or "")
        for c in list((anterior.campos if anterior else []) or [])
        if str(c.get("nombre") or "") and str(c.get("nombre")) not in nombres
    ]
    try:
        indices = sincronizar_indices(db, tabla, tenant_id, campos, retirados)
        sincronizar_vista(db, tabla, objeto, tenant_id, campos)
    except Exception as exc:  # noqa: BLE001 — el esquema replicado es lo urgente
        logger.error(
            "metamodelo.esquema_fisico_fallido",
            objeto=objeto,
            tabla=tabla,
            error=str(exc)[:300],
        )
        return {"aplicado": False, "porque": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {
        "aplicado": True,
        "tabla": tabla,
        "vista": nombre_de_vista(objeto, tenant_id),
        **indices,
    }


def aplicar_esquema(
    db: Session,
    *,
    tenant_id: UUID,
    objeto: str,
    campos: list[dict[str, Any]],
    version: int,
) -> EsquemaTenant | None:
    """Escribe el esquema replicado, descartando lo que llega tarde.

    La entrega es at-least-once y no garantiza orden, así que un evento viejo
    reenviado podría pisar el esquema bueno y devolver al tenant campos que ya
    había quitado. Comparar la versión es lo que lo impide, y por eso la versión
    la pone el productor y no el reloj.
    """
    fila = db.execute(
        select(EsquemaTenant).where(
            EsquemaTenant.tenant_id == tenant_id, EsquemaTenant.objeto == objeto
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = EsquemaTenant(tenant_id=tenant_id, objeto=objeto, version=version, campos=campos)
        db.add(fila)
        db.flush()
        return fila
    if version < fila.version:
        logger.info(
            "metamodelo.evento_tardio",
            objeto=objeto,
            recibida=version,
            actual=fila.version,
        )
        return None
    fila.version = version
    fila.campos = campos
    fila.actualizado_at = datetime.now(tz=None).astimezone()
    return fila


async def consumir_esquema(mensaje: Any) -> None:
    """Aplica en ESTE servicio un cambio de esquema hecho en `metadata`.

    Lo registra `crear_servicio` en todos. Un servicio que no lo consumiera
    seguiría validando con los campos de ayer: rechazaría el campo nuevo que el
    consultor acaba de crear —con el cliente delante— o aceptaría uno que ya se
    ha retirado.
    """
    if isinstance(mensaje, dict):
        datos = mensaje.get("data") if isinstance(mensaje.get("data"), dict) else mensaje
        tenant = mensaje.get("tenant_id") or (datos or {}).get("tenant_id")
    else:
        datos = getattr(mensaje, "data", None) or {}
        tenant = getattr(mensaje, "tenant_id", None)
    if not tenant or not datos:
        return
    objeto = str(datos.get("objeto") or "")
    if not objeto:
        return

    from crmcore.db.uow import unidad_de_trabajo

    with unidad_de_trabajo(sistema=True) as uow:
        campos = list(datos.get("campos") or [])
        # EL ORDEN IMPORTA: primero el físico, que necesita saber qué campos
        # había antes para retirar los índices de los que ya no están. Después
        # la réplica, que pisa `campos` con los nuevos.
        fisico = aplicar_esquema_fisico(
            uow.db, tenant_id=UUID(str(tenant)), objeto=objeto, campos=campos
        )
        aplicada = aplicar_esquema(
            uow.db,
            tenant_id=UUID(str(tenant)),
            objeto=objeto,
            campos=campos,
            version=int(datos.get("version") or 0),
        )
        if aplicada is not None and fisico.get("aplicado"):
            logger.info(
                "metamodelo.esquema_aplicado",
                objeto=objeto,
                vista=fisico.get("vista"),
                indices=fisico.get("creados"),
                retirados=fisico.get("retirados"),
            )


from crmcore.contratos import Consumo, declarar_consumo  # noqa: E402

# Contrato dirigido por el consumidor (CRM-00.03.01.03): sin `campos` y
# `version` la réplica no puede hacer nada, y sin `objeto` no sabría a qué
# aplicarlo.
declarar_consumo(
    Consumo(
        consumidor="todos-los-servicios",
        evento=ESQUEMA_CAMBIADO,
        campos=("objeto", "campos", "version"),
        motivo=(
            "Replicar el esquema del tenant para validar, filtrar e indexar sus "
            "campos propios sin llamar a «metadata» en cada escritura"
        ),
    )
)
