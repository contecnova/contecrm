"""Golden record, reglas de supervivencia y linaje del dato
(CRM-01.01.04.06, CRM-01.01.04.07).

Cuando el mismo cliente llega del ERP, del formulario web y de un fichero de
marketing, alguien tiene que decidir qué dirección es la buena. Lo que casi todos
los CRM hacen es lo cómodo: **gana el último que escribió**. Y eso produce fichas
que cambian solas los martes por la noche, cuando pasa el proceso del ERP, sin que
nadie entienda por qué.

Las decisiones:

**La regla es por campo y está declarada.** El NIF lo sabe mejor el ERP; el móvil
lo sabe mejor quien acaba de hablar con el cliente. Una regla única para toda la
ficha obliga a elegir entre dos verdades y siempre se equivoca en la mitad.

**«Más reciente» no es cuándo llegó el mensaje, sino cuándo cambió el valor.**
Es la trampa que estropea casi todas las integraciones: un ERP que reenvía el
maestro entero cada noche trae mil valores «nuevos» que son idénticos a los de
ayer, y con la fecha de llegada como criterio pisan lo que un comercial corrigió
esta mañana.

**Lo que pierde no se tira: se anota.** Si el ERP dice una dirección y el
formulario dice otra, esa discrepancia es información — probablemente el cliente
se mudó y solo uno se enteró. Quedarse con una y olvidar la otra convierte un
dato útil en un misterio.

**Y un golden record sin linaje no se puede auditar.** La pregunta que llega
siempre es «¿por qué pone esto aquí?», y sin saber de qué sistema vino y cuándo,
la única respuesta honesta es «no lo sé» — que es la que hace que se deje de
confiar en la ficha.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import DateTime, Index, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Cómo se decide qué valor sobrevive. Lista cerrada: cada una se equivoca de una
# forma distinta, y con texto libre nadie podría decir por qué ganó lo que ganó.
ESTRATEGIAS = (
    "mayor_confianza",  # manda la fuente declarada como más fiable para ese campo
    "mas_reciente",  # el que CAMBIÓ después, no el que llegó después
    "mas_completo",  # entre un valor y un vacío, el valor
    "solo_si_falta",  # la fuente rellena huecos y no pisa nada
    "decide_una_persona",  # para lo que no se puede automatizar sin equivocarse
)

# Lo que escribe una persona no lo pisa ningún proceso automático, salvo que la
# regla diga expresamente lo contrario. Alguien que corrige un teléfono está
# diciendo que el otro estaba mal.
FUENTE_MANUAL = "manual"

# Cuánto se considera que un valor sigue siendo bueno si nadie lo confirma. Es un
# valor por defecto: lo suyo es declararlo por campo, porque un NIF no caduca y
# un cargo caduca en cuanto ascienden a esa persona.
DIAS_FRESCURA_POR_DEFECTO = 365


class LinajeValor(Base):
    """De qué sistema vino cada valor, cuándo llegó y cuándo cambió de verdad.

    Una fila por campo y fuente, no por escritura: guardar cada escritura de un
    maestro que se reenvía entero cada noche llenaría la tabla de filas idénticas
    y haría la consulta inservible justo cuando hace falta.
    """

    __tablename__ = "linaje_valores"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(40), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    campo: Mapped[str] = mapped_column(String(80), nullable=False)
    fuente: Mapped[str] = mapped_column(String(80), nullable=False)
    # El valor tal y como lo dio esa fuente, en texto. No es el valor bueno: es
    # lo que dijo ella, que es lo que hace falta para explicar una discrepancia.
    valor: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Las dos fechas, y la diferencia entre ellas es la idea entera de este
    # módulo: `recibido_at` es cuándo llegó el mensaje y `cambiado_at` cuándo
    # cambió el valor. Un ERP que reenvía el maestro cada noche mueve la primera
    # y no la segunda.
    recibido_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cambiado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Si este es el valor que ha ganado ahora mismo.
    gana: Mapped[bool] = mapped_column(
        Integer().with_variant(Integer, "postgresql"), nullable=False, default=0
    )
    confianza: Mapped[int] = mapped_column(Integer, nullable=False, default=50)

    __table_args__ = (
        Index("ix_linaje_registro", "tenant_id", "objeto", "objeto_id"),
        Index("ix_linaje_campo", "tenant_id", "objeto", "objeto_id", "campo"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _momento(candidato: dict[str, Any]) -> datetime:
    """Cuándo cambió el valor **de verdad**.

    Si la fuente no dice cuándo cambió, se usa cuándo llegó, y se marca: no es lo
    mismo y confundirlos es lo que hace que un maestro reenviado pise lo que
    alguien corrigió esta mañana.
    """
    cambiado = candidato.get("cambiado_at")
    if isinstance(cambiado, datetime):
        return cambiado if cambiado.tzinfo else cambiado.replace(tzinfo=timezone.utc)
    recibido = candidato.get("recibido_at")
    if isinstance(recibido, datetime):
        return recibido if recibido.tzinfo else recibido.replace(tzinfo=timezone.utc)
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def resolver_valor(
    *,
    campo: str,
    candidatos: list[dict[str, Any]],
    estrategia: str = "mayor_confianza",
    confianza_por_fuente: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Decide qué valor sobrevive para un campo, **y por qué**.

    Cada candidato es `{"fuente", "valor", "cambiado_at", "recibido_at"}`.

    El «por qué» va en la respuesta porque la pregunta que llega siempre es «¿por
    qué pone esto aquí?», y sin respuesta la gente deja de fiarse de la ficha —
    y cuando se deja de confiar en una ficha, se vuelve a la hoja de cálculo.

    Lo que pierde **se devuelve como discrepancia**, no se tira. Que el ERP y el
    formulario digan direcciones distintas probablemente significa que el cliente
    se mudó y solo uno se enteró: eso es información, no ruido.
    """
    if estrategia not in ESTRATEGIAS:
        raise ErrorValidacion(
            f"Estrategia de supervivencia «{estrategia}» desconocida",
            error_code="mdm.estrategia_invalida",
            detalle={"admitidas": list(ESTRATEGIAS)},
        )
    vivos = [c for c in candidatos if str(c.get("valor") or "").strip()]
    if not vivos:
        return {
            "valor": None,
            "fuente": None,
            "porque": "Ninguna fuente trae valor para este campo.",
            "discrepancias": [],
            "hay_que_decidir": False,
        }

    confianzas = dict(confianza_por_fuente or {})
    manual = [c for c in vivos if str(c.get("fuente")) == FUENTE_MANUAL]
    if manual and estrategia != "decide_una_persona":
        ganador = max(manual, key=_momento)
        return {
            "valor": ganador["valor"],
            "fuente": FUENTE_MANUAL,
            "porque": (
                "Lo escribió una persona. Ningún proceso automático lo pisa: quien "
                "corrige un teléfono a mano está diciendo que el otro estaba mal."
            ),
            "discrepancias": _discrepancias(ganador, vivos),
            "hay_que_decidir": False,
        }

    if estrategia == "decide_una_persona":
        distintos = {str(c.get("valor")) for c in vivos}
        return {
            "valor": vivos[0]["valor"] if len(distintos) == 1 else None,
            "fuente": vivos[0].get("fuente") if len(distintos) == 1 else None,
            "hay_que_decidir": len(distintos) > 1,
            "porque": (
                "Todas las fuentes dicen lo mismo."
                if len(distintos) == 1
                else f"«{campo}» está declarado para que lo decida una persona, y hay "
                f"{len(distintos)} valores distintos. Elegir automáticamente aquí es "
                "lo que produce fichas que cambian solas."
            ),
            "opciones": [{"fuente": c.get("fuente"), "valor": c.get("valor")} for c in vivos],
            "discrepancias": [],
        }

    if estrategia == "mas_reciente":
        ganador = max(vivos, key=_momento)
        sin_fecha_de_cambio = [c for c in vivos if not isinstance(c.get("cambiado_at"), datetime)]
        porque = f"Es el valor que cambió después ({_momento(ganador).date().isoformat()})."
        if sin_fecha_de_cambio:
            porque += (
                " Aviso: hay fuentes que no dicen cuándo cambió el valor, solo cuándo "
                "llegó el mensaje. No es lo mismo: un maestro reenviado cada noche "
                "trae valores idénticos con fecha nueva."
            )
    elif estrategia == "mas_completo":
        ganador = max(vivos, key=lambda c: len(str(c.get("valor") or "")))
        porque = "Entre un valor y uno más pobre, se queda el que trae más información."
    elif estrategia == "solo_si_falta":
        ganador = vivos[0]
        porque = (
            "Esta regla solo rellena huecos: si ya había valor, no se toca. Es la "
            "adecuada para una fuente de enriquecimiento, que sabe de muchos y no "
            "conoce a ninguno."
        )
    else:
        ganador = max(vivos, key=lambda c: (confianzas.get(str(c.get("fuente")), 50), _momento(c)))
        porque = (
            f"«{ganador.get('fuente')}» es la fuente declarada como más fiable para "
            f"«{campo}» (confianza {confianzas.get(str(ganador.get('fuente')), 50)})."
        )

    return {
        "valor": ganador["valor"],
        "fuente": ganador.get("fuente"),
        "porque": porque,
        "discrepancias": _discrepancias(ganador, vivos),
        "hay_que_decidir": False,
    }


def _discrepancias(ganador: dict[str, Any], vivos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lo que dicen las demás fuentes y no ha ganado."""
    return [
        {
            "fuente": c.get("fuente"),
            "valor": c.get("valor"),
            "porque_importa": (
                "Dos sistemas dicen cosas distintas del mismo cliente. Suele ser que "
                "algo cambió y solo uno se enteró: merece una revisión, no un olvido."
            ),
        }
        for c in vivos
        if str(c.get("valor")) != str(ganador.get("valor"))
    ]


def componer_golden(
    *,
    campos: dict[str, list[dict[str, Any]]],
    reglas: dict[str, dict[str, Any]],
    confianza_por_fuente: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Compone la ficha buena a partir de lo que dice cada sistema.

    Devuelve también **qué hay que revisar**: los campos donde las fuentes no se
    ponen de acuerdo y los que esperan una decisión humana. Un golden record que
    solo enseña el resultado esconde justo la información que un responsable de
    datos necesita.
    """
    valores: dict[str, Any] = {}
    explicacion: dict[str, Any] = {}
    a_revisar: list[dict[str, Any]] = []

    for campo, candidatos in campos.items():
        regla = dict(reglas.get(campo) or {})
        salida = resolver_valor(
            campo=campo,
            candidatos=candidatos,
            estrategia=str(regla.get("estrategia") or "mayor_confianza"),
            confianza_por_fuente=confianza_por_fuente,
        )
        valores[campo] = salida["valor"]
        explicacion[campo] = {"fuente": salida["fuente"], "porque": salida["porque"]}
        if salida["discrepancias"] or salida["hay_que_decidir"]:
            a_revisar.append(
                {
                    "campo": campo,
                    "hay_que_decidir": salida["hay_que_decidir"],
                    "discrepancias": salida["discrepancias"],
                    "opciones": salida.get("opciones", []),
                }
            )

    return {
        "valores": valores,
        "de_donde_sale_cada_uno": explicacion,
        "a_revisar": a_revisar,
        "limpio": not a_revisar,
    }


def anotar_linaje(
    uow: UnidadDeTrabajo,
    *,
    objeto: str,
    objeto_id: UUID,
    campo: str,
    fuente: str,
    valor: Any,
    cambiado_at: datetime | None = None,
    confianza: int = 50,
    gana: bool = False,
) -> LinajeValor:
    """Guarda de dónde viene un valor.

    Una fila por campo y fuente: si se guardara cada escritura, un maestro que se
    reenvía entero cada noche llenaría la tabla de filas idénticas y la consulta
    sería inservible justo el día que hace falta.

    Y `cambiado_at` **solo se mueve cuando el valor cambia de verdad**. Es la
    diferencia entre «esta fuente sigue diciendo lo mismo» y «esta fuente lo ha
    cambiado», y confundirlas es lo que hace que un reenvío pise una corrección.
    """
    texto = "" if valor is None else str(valor)
    fila = uow.db.execute(
        select(LinajeValor).where(
            LinajeValor.tenant_id == uow.tenant_id,
            LinajeValor.objeto == objeto,
            LinajeValor.objeto_id == objeto_id,
            LinajeValor.campo == campo,
            LinajeValor.fuente == fuente,
        )
    ).scalar_one_or_none()

    if fila is None:
        fila = LinajeValor(
            tenant_id=uow.tenant_id,
            objeto=objeto,
            objeto_id=objeto_id,
            campo=campo,
            fuente=fuente,
            cambiado_at=cambiado_at or _ahora(),
        )
        uow.db.add(fila)
    elif fila.valor != texto:
        fila.cambiado_at = cambiado_at or _ahora()

    fila.valor = texto
    fila.recibido_at = _ahora()
    fila.confianza = confianza
    fila.gana = gana
    uow.db.flush()
    return fila


def historia_de(
    db: Session, tenant_id: UUID, *, objeto: str, objeto_id: UUID, campo: str | None = None
) -> dict[str, Any]:
    """De dónde sale cada valor de esta ficha.

    Es la respuesta a «¿por qué pone esto aquí?». Sin ella, la única contestación
    honesta es «no lo sé», y esa es la que hace que alguien se abra una hoja de
    cálculo al lado del CRM.
    """
    condiciones = [
        LinajeValor.tenant_id == tenant_id,
        LinajeValor.objeto == objeto,
        LinajeValor.objeto_id == objeto_id,
    ]
    if campo:
        condiciones.append(LinajeValor.campo == campo)
    filas = list(db.execute(select(LinajeValor).where(*condiciones)).scalars().all())

    por_campo: dict[str, list[dict[str, Any]]] = {}
    for fila in filas:
        por_campo.setdefault(fila.campo, []).append(
            {
                "fuente": fila.fuente,
                "valor": fila.valor,
                "gana": bool(fila.gana),
                "cambio_el_valor": fila.cambiado_at.isoformat() if fila.cambiado_at else None,
                "ultimo_mensaje": fila.recibido_at.isoformat(),
                "confianza": fila.confianza,
            }
        )

    return {
        "objeto": objeto,
        "objeto_id": str(objeto_id),
        "campos": por_campo,
        "medible": bool(filas),
        "que_significa": (
            "No hay linaje anotado de esta ficha. Eso no quiere decir que los datos "
            "sean malos: quiere decir que nadie puede explicar de dónde salen."
            if not filas
            else "Cada valor con el sistema que lo trajo, cuándo cambió de verdad y "
            "cuándo llegó el último mensaje que lo confirmaba."
        ),
    }


def valores_obsoletos(
    db: Session,
    tenant_id: UUID,
    *,
    objeto: str,
    objeto_id: UUID,
    dias_por_campo: dict[str, int] | None = None,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Qué valores llevan demasiado sin que nadie los confirme
    (CRM-01.01.04.09, la mitad de detección).

    El plazo es **por campo** porque un NIF no caduca y un cargo caduca en cuanto
    a esa persona la ascienden. Y un campo del que no hay linaje **no cuenta como
    fresco**: no se ha verificado nunca, que es distinto de estar al día.
    """
    momento = ahora or _ahora()
    plazos = dict(dias_por_campo or {})
    filas = list(
        db.execute(
            select(LinajeValor).where(
                LinajeValor.tenant_id == tenant_id,
                LinajeValor.objeto == objeto,
                LinajeValor.objeto_id == objeto_id,
            )
        )
        .scalars()
        .all()
    )

    viejos: list[dict[str, Any]] = []
    for fila in filas:
        dias_tope = plazos.get(fila.campo, DIAS_FRESCURA_POR_DEFECTO)
        edad = (
            momento - fila.recibido_at.replace(tzinfo=fila.recibido_at.tzinfo or timezone.utc)
        ).days
        if edad >= dias_tope:
            viejos.append(
                {
                    "campo": fila.campo,
                    "fuente": fila.fuente,
                    "dias_sin_confirmar": edad,
                    "tope": dias_tope,
                }
            )

    return {
        "obsoletos": sorted(viejos, key=lambda v: -v["dias_sin_confirmar"]),
        "campos_con_linaje": sorted({f.campo for f in filas}),
        "aviso": (
            ""
            if filas
            else "Esta ficha no tiene linaje de ningún campo. No se puede decir que "
            "esté al día: se puede decir que nunca se ha verificado, que no es lo "
            "mismo."
        ),
        "plazo_por_defecto_dias": DIAS_FRESCURA_POR_DEFECTO,
    }


def confirmar_frescura(
    uow: UnidadDeTrabajo, *, objeto: str, objeto_id: UUID, campo: str, fuente: str
) -> dict[str, Any]:
    """Alguien ha comprobado que este valor sigue siendo bueno.

    Mueve `recibido_at` y **no** `cambiado_at`: confirmar no es cambiar. Mover las
    dos haría que el dato pareciera recién actualizado cuando lo único que ha
    pasado es que alguien lo miró — y eso falsea todos los informes de antigüedad.
    """
    fila = uow.db.execute(
        select(LinajeValor).where(
            LinajeValor.tenant_id == uow.tenant_id,
            LinajeValor.objeto == objeto,
            LinajeValor.objeto_id == objeto_id,
            LinajeValor.campo == campo,
            LinajeValor.fuente == fuente,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise ErrorValidacion(
            f"No hay linaje de «{campo}» desde «{fuente}»: no se puede confirmar lo que "
            "no consta de dónde vino.",
            error_code="mdm.sin_linaje",
        )
    fila.recibido_at = _ahora()
    uow.db.flush()
    return {
        "campo": campo,
        "fuente": fuente,
        "confirmado_at": fila.recibido_at.isoformat(),
        "el_valor_no_ha_cambiado": True,
        "porque": (
            "Confirmar no es cambiar. Si se moviera también la fecha de cambio, el "
            "dato parecería recién actualizado y todos los informes de antigüedad "
            "dirían algo falso."
        ),
    }


def caducidad_declarada(dias_por_campo: dict[str, int]) -> dict[str, Any]:
    """Comprueba que los plazos de frescura tienen sentido.

    Un plazo de cero días significa «siempre obsoleto», y lo que produce es una
    cola de excepciones con todo dentro — que nadie mira, que es peor que no
    tenerla.
    """
    problemas = [
        {"campo": campo, "problema": "el plazo es 0 o negativo: todo saldría obsoleto"}
        for campo, dias in dias_por_campo.items()
        if dias <= 0
    ]
    eternos = [campo for campo, dias in dias_por_campo.items() if dias > 3650]
    return {
        "valido": not problemas,
        "problemas": problemas,
        "practicamente_eternos": eternos,
        "aviso": (
            ""
            if not eternos
            else f"{len(eternos)} campos con más de diez años de plazo. Es legítimo "
            "para un NIF; para cualquier otra cosa equivale a no comprobarlo nunca."
        ),
    }
