"""Particionado y archivado de los objetos de alto volumen (CRM-08.01.01.04).

Hay tres o cuatro tablas en cualquier CRM que crecen sin parar y no paran nunca:
actividades, eventos, auditoría, líneas de histórico. El resto se queda en unos
cientos de miles de filas y no da problemas jamás.

Lo que pasa con esas tres, y siempre en el mismo orden: primero las consultas se
ponen lentas, después los índices no caben en memoria, después el `VACUUM` tarda
más que la ventana de mantenimiento, y al final una consulta que iba bien durante
dos años deja de ir en una semana sin que nadie haya cambiado nada.

Las decisiones:

**Se particiona por tiempo, no por tenant.** Por tenant parece natural y es un
error caro: con dos mil tenants salen dos mil particiones, el planificador tarda
más en decidir que en ejecutar, y un tenant grande sigue teniendo su partición
enorme. Por mes, las consultas normales —que casi siempre miran los últimos
días— tocan una o dos.

**Lo viejo se archiva, no se borra.** Un CRM al que alguien pregunta por una
llamada de hace tres años y contesta que no existe deja de ser el registro de la
empresa. Se mueve a almacenamiento frío y se dice dónde está.

**Y archivar exige saber qué se puede archivar.** Lo que está bajo obligación
legal de conservación, en un litigio o en una solicitud de acceso pendiente **no
se toca**: mover eso a frío es cumplir el plazo de retención por accidente y
romper otra obligación a la vez.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from crmcore.errors import ErrorValidacion, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Las tablas que crecen sin parar. Declarada porque particionar todo «por si
# acaso» multiplica las particiones sin ganar nada: el resto de tablas se queda
# en cientos de miles de filas para siempre.
DE_ALTO_VOLUMEN = {
    "actividades": "Una por cada correo, llamada y reunión de cada comercial",
    "eventos_salida": "Uno por cada cambio de cada registro",
    "auditoria": "Una línea por cada operación de cada usuario",
    "elementos_buzon": "Uno por cada correo y cita sincronizados",
    "lecturas_telemetria": "Una por cada medida de cada dispositivo",
}

# Cómo se corta. `tenant` está fuera a propósito: con dos mil tenants salen dos
# mil particiones, el planificador tarda más en decidir que en ejecutar, y el
# tenant grande sigue teniendo su partición enorme.
ESTRATEGIAS = ("mes", "trimestre", "anio")

# Meses que se quedan en caliente por defecto. Trece para que el «mismo mes del
# año pasado» siga siendo una consulta rápida: es la comparación que más se hace
# y la que peor sienta que tarde.
MESES_EN_CALIENTE = 13

# Lo que impide archivar una fila, pase lo que pase.
RETENCIONES = {
    "obligacion_legal": "Hay una obligación de conservación que aún no ha vencido",
    "litigio": "Está bajo retención por un litigio: moverlo es destruir prueba",
    "solicitud_pendiente": "Hay una solicitud de acceso o portabilidad sin resolver",
    "investigacion": "Forma parte de una investigación interna abierta",
}


def _hoy(db: Any = None) -> date:
    """El día de hoy **donde está el cliente**, si hay sesión con la que saberlo.

    Sin sesión cae a UTC, que es lo que hacía antes: no empeora nada y deja
    claro dónde falta el dato. Quien la tenga a mano está obligado a pasarla —
    hay un gate que lo mira—, porque entre medianoche y las dos de la mañana en
    Madrid la respuesta sin sesión es **la de ayer**.
    """
    from crmcore.fechas import hoy as _hoy_del_cliente

    return _hoy_del_cliente(db)


def plan_de_particion(
    *, tabla: str, estrategia: str, meses_en_caliente: int = MESES_EN_CALIENTE
) -> dict[str, Any]:
    """Cómo se corta una tabla de alto volumen, y por qué así.

    Se rechaza particionar lo que no lo necesita: cada partición tiene su coste
    de planificación, y trocear una tabla de cincuenta mil filas la hace más
    lenta, no más rápida.
    """
    if tabla not in DE_ALTO_VOLUMEN:
        raise ErrorValidacion(
            f"«{tabla}» no está declarada como tabla de alto volumen. Particionar lo que "
            "no crece la hace más lenta: cada partición tiene coste de planificación.",
            error_code="particion.tabla_no_procede",
            detalle={"de_alto_volumen": sorted(DE_ALTO_VOLUMEN)},
        )
    if estrategia not in ESTRATEGIAS:
        raise ErrorValidacion(
            f"Estrategia «{estrategia}» desconocida",
            error_code="particion.estrategia_invalida",
            detalle={
                "admitidas": list(ESTRATEGIAS),
                "por_que_no_por_tenant": (
                    "Con dos mil tenants salen dos mil particiones y el planificador "
                    "tarda más en decidir que en ejecutar"
                ),
            },
        )
    return {
        "tabla": tabla,
        "por_que_crece": DE_ALTO_VOLUMEN[tabla],
        "estrategia": estrategia,
        "meses_en_caliente": meses_en_caliente,
        "porque_por_tiempo": (
            "Las consultas normales miran los últimos días, así que tocan una o dos "
            "particiones. Particionar por tenant dejaría al tenant grande con su "
            "partición enorme igual."
        ),
        "indice_por_tenant": True,
        "porque_el_indice": (
            "El aislamiento sigue siendo por tenant: lo que cambia es cómo se guarda, "
            "no quién ve qué."
        ),
    }


def particiones_a_crear(
    *, ultima_existente: date, meses_por_delante: int = 3, hoy: date | None = None
) -> dict[str, Any]:
    """Qué particiones hay que crear antes de que hagan falta.

    **Por delante, siempre.** Una partición que se crea cuando llega la primera
    fila de ese mes es una partición que se crea a las 00:00 del día 1, dentro de
    la transacción de un usuario, y con un bloqueo de tabla. Eso es un incidente
    con fecha conocida.
    """
    momento = hoy or _hoy()
    objetivo = momento + timedelta(days=31 * meses_por_delante)
    este_mes = date(momento.year, momento.month, 1)
    faltan: list[str] = []
    cursor = date(ultima_existente.year, ultima_existente.month, 1)
    while cursor < objetivo:
        cursor = date(cursor.year + (cursor.month // 12), (cursor.month % 12) + 1, 1)
        # `>=` y no `>`. Con `>` el mes EN CURSO nunca entraba en la lista, así
        # que «urgente» —que preguntaba si el primero que falta es el mes en
        # curso— no podía saltar jamás: la condición era inalcanzable y el aviso
        # que existe para que no te pille el día 1 no existía. Salió al darle
        # puerta; mientras no la tuvo, nadie pudo verlo.
        if cursor >= este_mes:
            faltan.append(cursor.isoformat()[:7])

    # Urgente si falta la del mes en curso o la del siguiente: la del mes en
    # curso es un incidente ocurriendo, y la del siguiente es uno con fecha.
    siguiente = date(este_mes.year + (este_mes.month // 12), (este_mes.month % 12) + 1, 1)
    return {
        "faltan": faltan,
        "urgente": bool(faltan) and faltan[0] <= siguiente.isoformat()[:7],
        "ya_falta_la_de_este_mes": bool(faltan) and faltan[0] == este_mes.isoformat()[:7],
        "porque": (
            "Se crean por delante. Crear la partición cuando llega la primera fila del "
            "mes significa crearla a las 00:00 del día 1, dentro de la transacción de un "
            "usuario y con un bloqueo de tabla: un incidente con fecha conocida."
        ),
    }


def se_puede_archivar(*, fila: dict[str, Any], hoy: date | None = None) -> dict[str, Any]:
    """Si una fila se puede mover a frío, **y qué lo impide**.

    Lo que está bajo obligación legal, en un litigio o con una solicitud de acceso
    pendiente no se toca. Moverlo a frío es cumplir el plazo de retención por
    accidente y romper otra obligación a la vez — y la que se rompe suele ser la
    cara.
    """
    momento = hoy or _hoy()
    impedimentos = [
        {"motivo": clave, "porque": RETENCIONES[clave]} for clave in RETENCIONES if fila.get(clave)
    ]
    fecha = fila.get("fecha")
    if isinstance(fecha, str):
        fecha = date.fromisoformat(fecha)
    antiguedad_meses = (
        (momento.year - fecha.year) * 12 + momento.month - fecha.month
        if isinstance(fecha, date)
        else None
    )
    if antiguedad_meses is None:
        return {
            "puede": False,
            "porque": (
                "La fila no tiene fecha. Archivar por antigüedad lo que no dice cuándo "
                "pasó es archivar al azar."
            ),
        }

    bastante_vieja = antiguedad_meses >= MESES_EN_CALIENTE
    return {
        "puede": bastante_vieja and not impedimentos,
        "antiguedad_meses": antiguedad_meses,
        "impedimentos": impedimentos,
        "porque": (
            f"Tiene {antiguedad_meses} meses y se conservan {MESES_EN_CALIENTE} en " "caliente."
            if not bastante_vieja
            else (
                "Hay retenciones activas: moverlo sería cumplir el plazo por accidente y "
                "romper otra obligación a la vez."
                if impedimentos
                else "Se puede mover a frío."
            )
        ),
    }


def archivar(
    *, filas: list[dict[str, Any]], destino: str, hoy: date | None = None
) -> dict[str, Any]:
    """Prepara el archivado, **sin borrar nada**.

    Lo archivado **se sigue pudiendo consultar** y se dice dónde está. Un CRM al
    que alguien pregunta por una llamada de hace tres años y contesta que no
    existe deja de ser el registro de la empresa, y eso pasa el día que se
    confunde archivar con borrar.
    """
    if not destino.strip():
        raise ErrorValidacion(
            "Archivar sin decir a dónde es borrar con otro nombre",
            error_code="archivado.sin_destino",
        )
    momento = hoy or _hoy()
    mueven, se_quedan = [], []
    for fila in filas:
        veredicto = se_puede_archivar(fila=fila, hoy=momento)
        (mueven if veredicto["puede"] else se_quedan).append(
            {"id": fila.get("id"), "porque": veredicto["porque"]}
        )

    return {
        "se_mueven": len(mueven),
        "se_quedan": len(se_quedan),
        "detalle_de_los_que_se_quedan": se_quedan[:20],
        "destino": destino,
        "se_borra_algo": False,
        "sigue_consultable": True,
        "porque": (
            "Lo archivado se sigue consultando, más despacio y diciendo dónde está. "
            "Confundir archivar con borrar es como un CRM deja de ser el registro de la "
            "empresa."
        ),
    }


def exigir_no_retenido(*, fila: dict[str, Any]) -> None:
    """Corta un borrado sobre algo que está retenido.

    Se comprueba aquí y no en el proceso de limpieza: el proceso de limpieza corre
    de noche y lo que borra por error se descubre semanas después, cuando alguien
    lo pide para un juicio.
    """
    activos = [k for k in RETENCIONES if fila.get(k)]
    if activos:
        raise Prohibido(
            "No se puede borrar: " + ", ".join(RETENCIONES[k] for k in activos),
            error_code="archivado.retenido",
            detalle={"retenciones": activos},
        )


def salud_del_volumen(
    *, tablas: list[dict[str, Any]], umbral_filas: int = 50_000_000
) -> dict[str, Any]:
    """Qué tabla va camino de dar problemas, **antes de darlos**.

    El aviso útil no es «esta tabla es grande»: es **a qué ritmo crece**. Una
    tabla de cien millones de filas estable no molesta a nadie; una de diez que
    dobla cada trimestre es un incidente dentro de nueve meses, y esos nueve meses
    son justo el tiempo que hace falta para arreglarlo con calma.
    """
    avisos: list[dict[str, Any]] = []
    for tabla in tablas:
        filas = int(tabla.get("filas") or 0)
        crecimiento = float(tabla.get("crecimiento_mensual_pct") or 0)
        particionada = bool(tabla.get("particionada"))
        meses_para_el_umbral = None
        if crecimiento > 0 and filas:
            meses_para_el_umbral = 0
            proyeccion = float(filas)
            while proyeccion < umbral_filas and meses_para_el_umbral < 120:
                proyeccion *= 1 + crecimiento / 100
                meses_para_el_umbral += 1
        if (filas >= umbral_filas or (meses_para_el_umbral or 999) <= 12) and not particionada:
            avisos.append(
                {
                    "tabla": tabla.get("nombre"),
                    "filas": filas,
                    "crecimiento_mensual_pct": crecimiento,
                    "meses_para_el_umbral": meses_para_el_umbral,
                    "que_hacer": "Particionar por tiempo antes de que haga falta",
                }
            )

    return {
        "avisos": avisos,
        "medible": bool(tablas),
        "que_significa": (
            "No hay datos de volumen: sin ellos no se puede anticipar nada, solo " "reaccionar."
            if not tablas
            else (
                "Ninguna tabla va camino de dar problemas en el próximo año."
                if not avisos
                else f"{len(avisos)} tablas llegan al umbral en menos de un año. El aviso "
                "útil no es que sean grandes: es el ritmo al que crecen, y esos meses son "
                "justo el tiempo que hace falta para arreglarlo con calma."
            )
        ),
    }
