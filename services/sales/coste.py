"""Lo que nos cuesta y lo que podemos comprometer
(CRM-09.02.01.01 a .09).

Un CRM sabe poner precio a lo que se vende y, si no sabe lo que cuesta, **no
puede decir el margen** — que es lo único que un responsable aprueba o rechaza de
verdad. Aprobar por porcentaje de descuento es aprobar a ciegas: un 5 % sobre algo
que se compra caro pierde dinero y un 30 % sobre algo que se compra bien no.

Las decisiones:

**La tarifa de coste va en el mismo motor de precios.** Un motor paralelo para
costes acabaría con dos formas de escalar por volumen y dos maneras de resolver la
vigencia, y una de las dos se quedaría atrás. Lo único que cambia es el sentido.

**El coste se congela al ofertar.** Si la tarifa del proveedor sube en octubre y la
oferta de septiembre se recalcula sola, el margen que alguien aprobó deja de
existir sin que nadie se entere. Cambia la tarifa, se avisa, y la oferta se queda
como estaba hasta que una persona decida.

**Comparar proveedores no es comparar precios.** El más barato que llega dos
semanas tarde o que no está homologado no es una opción: es un incumplimiento con
descuento.

**La capacidad comprometida se descuenta.** Una cuota que solo mira lo contratado
y no lo ya comprometido deja vender tres veces lo mismo, y eso se descubre en la
semana de la entrega.

**Y el plazo del proveedor decide la fecha que se promete.** Al revés —prometer
una fecha y luego buscar quién la cumpla— es exactamente el orden que produce los
retrasos.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

SENTIDOS = ("venta", "coste")

# Cómo se reparte cuando varios proveedores pueden servir lo mismo. Declarado y
# no improvisado: sin regla, reparte quien monta la oferta y cada uno lo hace de
# una manera — normalmente con el de siempre.
REPARTOS = ("menor_coste", "mas_capacidad_libre", "por_acuerdo", "menor_plazo")

# Por debajo de qué margen se pide aprobación. Es un valor por defecto del
# módulo; el tope real sale de la política de descuentos del tenant, que ya
# existe.
MARGEN_MINIMO_PCT = Decimal("15")


def _hoy() -> date:
    return datetime.now(timezone.utc).date()


def _pct(numerador: Decimal, denominador: Decimal) -> Decimal:
    if denominador == 0:
        return Decimal(0)
    return (numerador / denominador * Decimal(100)).quantize(Decimal("0.01"))


# ── Margen de la oferta (CRM-09.02.01.02) ─────────────────────────────────


def margen_de_linea(
    *, precio_venta: Decimal, coste: Decimal | None, cantidad: Decimal = Decimal(1)
) -> dict[str, Any]:
    """El margen de una línea, **o por qué no se puede calcular**.

    Sin coste **no se devuelve cero ni se omite el margen**: se dice que no se
    sabe. Un margen en blanco se lee como «no hay margen» o como «no importa»,
    según quien mire, y las dos lecturas son peores que la verdad.
    """
    if coste is None:
        return {
            "calculable": False,
            "porque": (
                "No hay coste para esta línea. No es margen cero: es que no se sabe lo "
                "que cuesta, y aprobar un descuento sobre eso es aprobar a ciegas."
            ),
            "que_hacer": "Declarar la tarifa del proveedor o pedirle oferta.",
        }
    venta = Decimal(precio_venta) * Decimal(cantidad)
    coste_total = Decimal(coste) * Decimal(cantidad)
    margen = venta - coste_total
    return {
        "calculable": True,
        "venta": str(venta),
        "coste": str(coste_total),
        "margen": str(margen),
        "margen_pct": str(_pct(margen, venta)),
        "en_perdidas": margen < 0,
    }


def margen_de_oferta(
    *, lineas: list[dict[str, Any]], margen_minimo_pct: Decimal = MARGEN_MINIMO_PCT
) -> dict[str, Any]:
    """El margen de la oferta entera, diciendo **qué líneas no se pueden medir**.

    Una oferta en la que faltan costes no tiene «un margen aproximado»: tiene un
    margen desconocido. Enseñar la media de lo que sí se sabe es la forma más
    elegante de mentir en una hoja de aprobación.
    """
    medibles = [x for x in lineas if x.get("coste") is not None]
    sin_coste = [x for x in lineas if x.get("coste") is None]

    venta = sum(
        (
            Decimal(str(x.get("precio_venta") or 0)) * Decimal(str(x.get("cantidad") or 1))
            for x in lineas
        ),
        Decimal(0),
    )
    venta_medible = sum(
        (
            Decimal(str(x.get("precio_venta") or 0)) * Decimal(str(x.get("cantidad") or 1))
            for x in medibles
        ),
        Decimal(0),
    )
    coste = sum(
        (
            Decimal(str(x.get("coste") or 0)) * Decimal(str(x.get("cantidad") or 1))
            for x in medibles
        ),
        Decimal(0),
    )
    margen = venta_medible - coste
    pct = _pct(margen, venta_medible)

    return {
        "completo": not sin_coste,
        "lineas_sin_coste": [x.get("referencia") for x in sin_coste],
        "venta_total": str(venta),
        "venta_con_coste_conocido": str(venta_medible),
        "coste": str(coste),
        "margen": str(margen),
        "margen_pct": str(pct),
        "necesita_aprobacion": bool(medibles) and pct < margen_minimo_pct,
        "porque": (
            f"El margen conocido es del {pct} % y el mínimo sin aprobación es "
            f"{margen_minimo_pct} %."
            if medibles
            else "No hay ninguna línea con coste: no se puede hablar de margen."
        ),
        "aviso": (
            ""
            if not sin_coste
            else f"{len(sin_coste)} líneas no tienen coste. Este margen es el de las "
            "demás: enseñar la media de lo que sí se sabe como si fuera el margen de la "
            "oferta es la forma elegante de mentir en una hoja de aprobación."
        ),
    }


# ── Congelar el coste (CRM-09.02.01.03) ───────────────────────────────────


def congelar_coste(
    *, lineas: list[dict[str, Any]], momento: datetime | None = None
) -> dict[str, Any]:
    """Fija el coste de cada línea en el momento de ofertar.

    Es la decisión que más se agradece meses después. Si la oferta recalculara el
    coste cada vez que se abre, el margen que alguien aprobó en septiembre habría
    desaparecido en octubre sin que nadie tocara nada — y la aprobación pasaría a
    referirse a unos números que ya no existen.
    """
    cuando = momento or datetime.now(timezone.utc)
    return {
        "congelado_at": cuando.isoformat(),
        "lineas": [
            {
                "referencia": linea.get("referencia"),
                "coste_congelado": str(linea.get("coste"))
                if linea.get("coste") is not None
                else None,
                "tarifa": linea.get("tarifa"),
                "proveedor_id": str(linea["proveedor_id"]) if linea.get("proveedor_id") else None,
            }
            for linea in lineas
        ],
        "porque": (
            "El coste queda fijado con la oferta. Recalcularlo al abrirla haría que el "
            "margen aprobado desapareciera sin que nadie tocara nada."
        ),
    }


def revisar_costes_congelados(
    *, lineas_congeladas: list[dict[str, Any]], costes_hoy: dict[str, Decimal]
) -> dict[str, Any]:
    """Compara lo congelado con la tarifa de hoy y **avisa sin reescribir**.

    Reescribir la oferta sería lo cómodo y es lo peor: el comercial la manda
    creyendo que lleva los números que aprobó su jefe. Lo que se hace es avisar,
    con cuánto ha cambiado el margen, y que decida una persona.
    """
    cambios: list[dict[str, Any]] = []
    for linea in lineas_congeladas:
        referencia = str(linea.get("referencia"))
        congelado = linea.get("coste_congelado")
        actual = costes_hoy.get(referencia)
        if congelado is None or actual is None:
            continue
        if Decimal(str(congelado)) != Decimal(str(actual)):
            diferencia = Decimal(str(actual)) - Decimal(str(congelado))
            cambios.append(
                {
                    "referencia": referencia,
                    "coste_en_la_oferta": str(congelado),
                    "coste_hoy": str(actual),
                    "diferencia": str(diferencia),
                    "peor": diferencia > 0,
                }
            )

    peores = [c for c in cambios if c["peor"]]
    return {
        "hay_cambios": bool(cambios),
        "cambios": cambios,
        "la_oferta_se_ha_tocado": False,
        "porque": (
            "La oferta se queda como está. Reescribirla sería mandarle al cliente unos "
            "números que su jefe no aprobó — y el comercial ni se enteraría."
        ),
        "que_hacer": (
            ""
            if not peores
            else f"{len(peores)} líneas cuestan más que cuando se ofertó. Revisar el "
            "margen antes de firmar: el que se aprobó ya no es el que hay."
        ),
    }


# ── Comparar proveedores (CRM-09.02.01.04) ────────────────────────────────


def comparar_proveedores(
    *, ofertas: list[dict[str, Any]], fecha_necesaria: date | None = None
) -> dict[str, Any]:
    """Compara opciones por **coste, plazo y riesgo**, no solo por precio.

    El más barato que llega dos semanas tarde no es la opción barata: es un
    incumplimiento con descuento. Y el que no está homologado directamente no es
    una opción, por mucho que su número sea el mejor.

    Se devuelven **todas** con su motivo de descarte, no solo la ganadora: quien
    decide necesita poder explicar por qué no eligió la más barata, normalmente a
    alguien que solo ha visto esa columna.
    """
    evaluadas: list[dict[str, Any]] = []
    for oferta in ofertas:
        motivos: list[str] = []
        if not oferta.get("homologado"):
            motivos.append(
                "No está homologado para esto. No es una opción cara ni barata: no es "
                "una opción."
            )
        if (
            fecha_necesaria
            and oferta.get("fecha_entrega")
            and oferta["fecha_entrega"] > fecha_necesaria
        ):
            motivos.append(
                f"Entrega el {oferta['fecha_entrega'].isoformat()} y hace falta para el "
                f"{fecha_necesaria.isoformat()}. El más barato que llega tarde es un "
                "incumplimiento con descuento."
            )
        if oferta.get("documentos_vencidos"):
            motivos.append("Tiene documentación obligatoria vencida.")

        evaluadas.append(
            {
                "proveedor_id": str(oferta.get("proveedor_id")),
                "nombre": oferta.get("nombre"),
                "coste": str(oferta.get("coste")),
                "fecha_entrega": (
                    oferta["fecha_entrega"].isoformat() if oferta.get("fecha_entrega") else None
                ),
                "viable": not motivos,
                "motivos_de_descarte": motivos,
            }
        )

    viables = [e for e in evaluadas if e["viable"]]
    mejor = min(viables, key=lambda e: Decimal(e["coste"])) if viables else None
    todas = sorted(evaluadas, key=lambda e: Decimal(e["coste"]))
    mas_barata = todas[0] if todas else None

    return {
        "opciones": todas,
        "elegida": mejor,
        "hay_alguna": bool(viables),
        "aviso": (
            ""
            if not mejor or not mas_barata or mejor["proveedor_id"] == mas_barata["proveedor_id"]
            else f"La más barata es «{mas_barata['nombre']}» y no se puede usar: "
            + " ".join(mas_barata["motivos_de_descarte"])
        ),
        "porque": (
            "No hay ninguna opción viable: todas están descartadas por homologación, "
            "plazo o papeles."
            if not viables
            else "Entre las que sí se pueden usar, la de menor coste."
        ),
    }


# ── Petición de oferta (CRM-09.02.01.05) ──────────────────────────────────


def preparar_peticion(
    *,
    proveedores: list[UUID],
    lineas: list[dict[str, Any]],
    fecha_limite: date,
    oportunidad_id: UUID | None,
    hoy: date | None = None,
) -> dict[str, Any]:
    """Prepara una petición de oferta ligada a lo que la motiva.

    **Ligada a la oportunidad** a propósito: una petición suelta no se puede
    cerrar nunca, porque nadie sabe si aquello se ganó o se perdió, y acaba en una
    lista de cosas abiertas que nadie limpia.

    Y con **fecha límite real**: sin ella, la respuesta llega cuando el cliente ya
    ha decidido, y entonces el precio que se le dio se puso a ojo.
    """
    if not proveedores:
        raise ErrorValidacion(
            "Una petición sin proveedores no se manda a ninguna parte",
            error_code="rfq.sin_proveedores",
        )
    if not lineas:
        raise ErrorValidacion(
            "Una petición sin líneas pide un precio de nada",
            error_code="rfq.sin_lineas",
        )
    momento = hoy or _hoy()
    if fecha_limite <= momento:
        raise ErrorValidacion(
            "La fecha límite ya ha pasado: la respuesta llegaría cuando el cliente ya "
            "haya decidido, y el precio que se le dio se habrá puesto a ojo.",
            error_code="rfq.fecha_pasada",
        )
    return {
        "proveedores": [str(p) for p in proveedores],
        "lineas": lineas,
        "fecha_limite": fecha_limite.isoformat(),
        "oportunidad_id": str(oportunidad_id) if oportunidad_id else None,
        "aviso": (
            ""
            if oportunidad_id
            else "Esta petición no está ligada a ninguna oportunidad. No se podrá "
            "cerrar nunca: nadie sabrá si aquello se ganó o se perdió."
        ),
    }


def recoger_respuestas(
    *,
    pedidas_a: list[UUID],
    respuestas: list[dict[str, Any]],
    fecha_limite: date,
    hoy: date | None = None,
) -> dict[str, Any]:
    """Qué ha contestado cada proveedor, y **quién no ha contestado**.

    Lo segundo es lo que casi nunca se enseña y lo que más se necesita: si tres de
    cinco no han contestado, la comparación no es entre cinco opciones, es entre
    dos — y decidir sin saberlo es creer que se ha comparado el mercado.
    """
    momento = hoy or _hoy()
    contestaron = {str(r.get("proveedor_id")) for r in respuestas}
    faltan = [str(p) for p in pedidas_a if str(p) not in contestaron]
    fuera_de_plazo = [
        str(r.get("proveedor_id"))
        for r in respuestas
        if r.get("recibida_el") and r["recibida_el"] > fecha_limite
    ]
    return {
        "respuestas": len(respuestas),
        "sin_contestar": faltan,
        "fuera_de_plazo": fuera_de_plazo,
        "plazo_cerrado": momento > fecha_limite,
        "que_significa": (
            f"Han contestado {len(respuestas)} de {len(pedidas_a)}."
            + (
                f" Faltan {len(faltan)}: la comparación no es entre {len(pedidas_a)} "
                "opciones, es entre las que hay, y decidir sin saberlo es creer que se "
                "ha comparado el mercado."
                if faltan
                else ""
            )
        ),
    }


# ── Capacidad comprometida (CRM-09.02.01.06) ──────────────────────────────


def capacidad_disponible(
    *, contratada: Decimal, ya_comprometida: Decimal, en_ofertas_abiertas: Decimal = Decimal(0)
) -> dict[str, Any]:
    """Cuánto queda de verdad con este proveedor.

    Una cuota que solo mira lo contratado y no lo **ya comprometido** deja vender
    tres veces lo mismo, y eso se descubre en la semana de la entrega, cuando ya
    no hay margen para nada.

    Y se enseña aparte lo que está **en ofertas abiertas**: todavía no es un
    compromiso, pero si se ganan todas tampoco cabe — y esa conversación es mejor
    tenerla antes de mandar la cuarta oferta.
    """
    libre = Decimal(contratada) - Decimal(ya_comprometida)
    libre_si_todo_se_gana = libre - Decimal(en_ofertas_abiertas)
    return {
        "contratada": str(contratada),
        "comprometida": str(ya_comprometida),
        "libre": str(libre),
        "en_ofertas_abiertas": str(en_ofertas_abiertas),
        "libre_si_se_ganan_todas": str(libre_si_todo_se_gana),
        "sobrevendida": libre < 0,
        "aviso": (
            "Ya hay comprometido más de lo contratado. Eso no es un riesgo futuro: es "
            "una entrega que va a fallar."
            if libre < 0
            else (
                "Si se ganaran todas las ofertas abiertas no cabría. Conviene hablarlo "
                "antes de mandar la siguiente, no después."
                if libre_si_todo_se_gana < 0
                else ""
            )
        ),
    }


def reservar(
    *, disponible: Decimal, cantidad: Decimal, permitir_exceso: bool = False
) -> dict[str, Any]:
    """Compromete capacidad, **o se niega a hacerlo**.

    Dejar reservar por encima de lo disponible «porque ya se arreglará» es lo que
    convierte un problema de planificación en una llamada al cliente el día de la
    entrega. Se puede forzar, y entonces queda dicho que se forzó.
    """
    if Decimal(cantidad) <= 0:
        raise ErrorValidacion("No se reserva una cantidad de cero", error_code="capacidad.cero")
    if Decimal(cantidad) > Decimal(disponible) and not permitir_exceso:
        raise Conflicto(
            f"Se piden {cantidad} y quedan {disponible}. Reservar por encima «porque ya "
            "se arreglará» convierte un problema de planificación en una llamada al "
            "cliente el día de la entrega.",
            error_code="capacidad.insuficiente",
            detalle={"disponible": str(disponible), "pedido": str(cantidad)},
        )
    exceso = max(Decimal(0), Decimal(cantidad) - Decimal(disponible))
    return {
        "reservado": str(cantidad),
        "queda": str(Decimal(disponible) - Decimal(cantidad)),
        "forzado": exceso > 0,
        "aviso": (
            ""
            if exceso == 0
            else f"Se ha reservado {exceso} por encima de lo disponible. Queda anotado: "
            "alguien ha decidido comprometerlo sabiendo que no cabe."
        ),
    }


# ── Plazo del proveedor (CRM-09.02.01.07) ─────────────────────────────────


def fecha_que_se_puede_prometer(
    *,
    plazo_proveedor_dias: int | None,
    dias_propios: int = 2,
    desde: date | None = None,
    festivos: list[date] | None = None,
) -> dict[str, Any]:
    """Qué fecha se le puede dar al cliente con este proveedor detrás.

    Este es el orden correcto: **primero se mira el plazo y después se promete**.
    Al revés —prometer y luego buscar quién lo cumpla— es exactamente lo que
    produce los retrasos, y además deja al comercial en una posición imposible.

    Si el proveedor no declara plazo **no se inventa uno**: se dice que no se
    puede prometer fecha todavía, que es incómodo y es verdad.
    """
    inicio = desde or _hoy()
    if plazo_proveedor_dias is None:
        return {
            "se_puede_prometer": False,
            "porque": (
                "El proveedor no declara plazo. No se inventa una fecha: prometer sin "
                "saber es el origen de casi todos los retrasos, y el que da la cara "
                "después es el comercial."
            ),
            "que_hacer": "Pedírselo antes de mandar la oferta.",
        }

    dias = int(plazo_proveedor_dias) + int(dias_propios)
    fecha = inicio + timedelta(days=dias)
    for festivo in sorted(festivos or []):
        if inicio < festivo <= fecha:
            fecha += timedelta(days=1)

    return {
        "se_puede_prometer": True,
        "fecha": fecha.isoformat(),
        "dias_del_proveedor": plazo_proveedor_dias,
        "dias_propios": dias_propios,
        "porque": (
            f"{plazo_proveedor_dias} días del proveedor más {dias_propios} de gestión y "
            "entrega por nuestra parte. Prometer solo los suyos sería prometer un plazo "
            "que existiría si nosotros no hiciéramos nada."
        ),
    }


# ── Reparto entre proveedores (CRM-09.02.01.08) ───────────────────────────


def repartir(
    *, candidatos: list[dict[str, Any]], cantidad: Decimal, regla: str = "menor_coste"
) -> dict[str, Any]:
    """Reparte una cantidad entre los proveedores que pueden servirla.

    La regla **se declara**. Sin regla reparte quien monta la oferta, y cada uno lo
    hace de una manera — normalmente con el de siempre, que es como se llega a
    depender de uno sin que nadie lo haya decidido.

    Y si no cabe entera **se dice cuánto falta**, en vez de repartir lo que hay y
    dejar el resto sin asignar sin avisar.
    """
    if regla not in REPARTOS:
        raise ErrorValidacion(
            f"Regla de reparto «{regla}» desconocida",
            error_code="reparto.regla_invalida",
            detalle={"admitidas": list(REPARTOS)},
        )
    viables = [
        c for c in candidatos if c.get("homologado") and Decimal(str(c.get("libre") or 0)) > 0
    ]
    if regla == "menor_coste":
        viables.sort(key=lambda c: Decimal(str(c.get("coste") or 0)))
    elif regla == "mas_capacidad_libre":
        viables.sort(key=lambda c: -Decimal(str(c.get("libre") or 0)))
    elif regla == "menor_plazo":
        viables.sort(key=lambda c: int(c.get("plazo_dias") or 9999))
    else:
        viables.sort(key=lambda c: -int(c.get("cuota_acordada_pct") or 0))

    pendiente = Decimal(cantidad)
    reparto: list[dict[str, Any]] = []
    for candidato in viables:
        if pendiente <= 0:
            break
        toca = min(pendiente, Decimal(str(candidato.get("libre") or 0)))
        reparto.append(
            {
                "proveedor_id": str(candidato.get("id")),
                "nombre": candidato.get("nombre"),
                "cantidad": str(toca),
                "coste_unitario": str(candidato.get("coste")),
            }
        )
        pendiente -= toca

    return {
        "regla": regla,
        "reparto": reparto,
        "sin_asignar": str(pendiente),
        "cabe_entero": pendiente <= 0,
        "porque": (
            f"Repartido por «{regla}», que es la regla declarada. Sin regla reparte "
            "quien monta la oferta, y acaba siendo siempre el mismo proveedor sin que "
            "nadie lo haya decidido."
        ),
        "aviso": (
            ""
            if pendiente <= 0
            else f"Faltan {pendiente} por asignar: no cabe entre los proveedores "
            "homologados con capacidad libre. Repartir lo que hay y callar el resto es "
            "como se descubre en la entrega."
        ),
    }


# ── Rappels y escalados (CRM-09.02.01.09) ─────────────────────────────────


def rappel_estimado(
    *, compra_acumulada: Decimal, tramos: list[dict[str, Any]], cerrado: bool = False
) -> dict[str, Any]:
    """Cuánto se recuperará del proveedor a final de año, y **de quién es**.

    Dos cosas que se hacen mal casi siempre:

    **Contarlo antes de tiempo.** Un rappel estimado no es dinero: depende de
    llegar al tramo, y si el año se tuerce no llega. Se marca como estimado hasta
    que se cierra el periodo.

    **Y aplicarlo al margen de la oferta que lo generó.** El rappel es del volumen
    del año, no de una venta; repartirlo hacia atrás hace que una oferta parezca
    rentable por algo que todavía no ha pasado. Se imputa al periodo, y ahí se
    queda.
    """
    aplicables = [
        t
        for t in sorted(tramos, key=lambda x: Decimal(str(x.get("desde") or 0)))
        if Decimal(str(compra_acumulada)) >= Decimal(str(t.get("desde") or 0))
    ]
    tramo = aplicables[-1] if aplicables else None
    importe = (
        Decimal(str(compra_acumulada)) * Decimal(str(tramo.get("pct") or 0)) / Decimal(100)
        if tramo
        else Decimal(0)
    )
    siguiente = next(
        (
            t
            for t in sorted(tramos, key=lambda x: Decimal(str(x.get("desde") or 0)))
            if Decimal(str(t.get("desde") or 0)) > Decimal(str(compra_acumulada))
        ),
        None,
    )

    return {
        "tramo_actual": tramo,
        "importe": str(importe.quantize(Decimal("0.01"))),
        "es_estimado": not cerrado,
        "falta_para_el_siguiente": (
            str(Decimal(str(siguiente["desde"])) - Decimal(str(compra_acumulada)))
            if siguiente
            else None
        ),
        "se_imputa_a": "el periodo, no a las ofertas que lo generaron",
        "porque": (
            "Un rappel estimado no es dinero: depende de llegar al tramo, y si el año "
            "se tuerce no se llega. Y repartirlo hacia atrás haría que una oferta "
            "pareciera rentable por algo que todavía no ha pasado."
            if not cerrado
            else "El periodo está cerrado: este importe ya es firme."
        ),
    }
