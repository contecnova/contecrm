"""Recuperación a un punto en el tiempo, por tenant, y pruebas de recuperación
(CRM-00.06.02.02, CRM-00.06.02.06).

Restaurar el clúster entero para arreglar lo que rompió un cliente es la opción
que existe en todas partes y que **no se usa nunca**: implica tirar abajo a los
demás por un error de uno. Lo que hace falta es poder volver atrás **un solo
tenant** hasta un momento concreto, y eso tiene una complicación que conviene
mirar de frente.

**El tiempo no es el mismo para todos los datos.** Restaurar las tablas del tenant
a las 10:00 no deshace los eventos que salieron entre las 10:00 y ahora: el
webhook ya llegó al ERP del cliente, el correo ya se mandó y la audiencia ya se
subió a la plataforma de anuncios. Una restauración que no dice eso deja al CRM
diciendo una cosa y al mundo otra.

Las decisiones:

**Se restaura sobre una copia, no encima.** Se levanta el estado de ese momento en
paralelo, alguien lo mira, y entonces se decide qué se trae. Restaurar directamente
sobre lo vivo convierte un error en dos.

**Se dice qué salió fuera en ese tramo.** Eventos publicados, correos enviados,
documentos firmados. Nada de eso se puede deshacer y, si no se dice, nadie lo tiene
en cuenta.

**Y una copia que nadie ha restaurado nunca no es una copia.** La prueba de
recuperación no es un trámite: es lo único que distingue una copia de un fichero
grande. Se hace periódicamente, se cronometra y **se guarda el resultado**, porque
lo que hay que poder enseñar en una auditoría —y lo que hay que saber en un
incidente— es cuánto se tarda de verdad.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué se puede restaurar. Cerrada porque cada cosa se recupera de una forma y con
# un riesgo distinto: los adjuntos viven fuera de la base y la auditoría no se
# restaura nunca —restaurarla sería borrar el rastro de lo que pasó—.
ALCANCES = ("datos", "configuracion", "adjuntos", "todo")

# Lo que NO se restaura jamás, y por qué. No es configurable.
NUNCA = {
    "auditoria": (
        "Restaurar la auditoría borraría el rastro de lo que pasó, incluido el "
        "incidente que motivó la restauración"
    ),
    "eventos_publicados": (
        "Ya salieron. Restaurar la tabla no los desmanda, y hacer creer que sí es "
        "peor que no restaurar"
    ),
    "claves": "Las claves de cifrado no viajan en una copia de datos",
}


# Cada cuánto se prueba una recuperación. Trimestral es el mínimo razonable: con
# una prueba al año, lo que se descubre es que el procedimiento lleva meses roto.
def _recuperacion_dias_entre_pruebas() -> int:
    """Tope del núcleo, antes `_recuperacion_dias_entre_pruebas() = 90`.

    Era una constante de módulo. Sale del `.env`, no de los ajustes en
    caliente: es un tope operativo del despliegue y «por cliente» no
    significaría nada.
    """
    from crmcore.config import get_settings

    return get_settings().recuperacion_dias_entre_pruebas


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def plan_de_restauracion(
    *,
    tenant_id: UUID,
    momento: datetime,
    alcance: str,
    copia_mas_antigua: datetime,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Prepara una restauración a un punto en el tiempo, **sin ejecutarla**.

    Lo primero que hace es comprobar que ese momento **existe**: pedir volver a
    hace seis meses cuando la retención son treinta días no falla al final del
    proceso, falla ahora.

    Y deja escrito que la restauración va **sobre una copia**. Restaurar
    directamente encima de lo vivo convierte un error en dos: si lo restaurado no
    era lo que se creía, ya no hay a dónde volver.
    """
    if alcance not in ALCANCES:
        raise ErrorValidacion(
            f"Alcance «{alcance}» desconocido",
            error_code="recuperacion.alcance_invalido",
            detalle={"admitidos": list(ALCANCES)},
        )
    momento_actual = ahora or _ahora()
    if momento > momento_actual:
        raise ErrorValidacion(
            "No se puede restaurar a un momento futuro",
            error_code="recuperacion.momento_futuro",
        )
    if momento < copia_mas_antigua:
        raise Conflicto(
            f"No hay copia de ese momento: la más antigua es de "
            f"{copia_mas_antigua.isoformat()}. Se dice ahora y no al final del proceso, "
            "que es cuando se descubre en la mayoría de los sistemas.",
            error_code="recuperacion.fuera_de_retencion",
        )

    return {
        "tenant_id": str(tenant_id),
        "momento": momento.isoformat(),
        "alcance": alcance,
        "sobre_una_copia": True,
        "no_se_restaura": [{"que": k, "porque": v} for k, v in NUNCA.items()],
        "que_pasa_ahora": (
            "Se levanta el estado de ese momento en paralelo. Nadie toca lo vivo hasta "
            "que una persona mire lo restaurado y decida qué se trae."
        ),
        "horas_de_diferencia": round((momento_actual - momento).total_seconds() / 3600, 1),
    }


def efectos_irreversibles(
    *, salidas: list[dict[str, Any]], desde: datetime, hasta: datetime
) -> dict[str, Any]:
    """Qué salió al mundo en el tramo que se va a deshacer.

    Es la parte que casi ningún sistema enseña y la que más falta hace: restaurar
    las tablas a las 10:00 no desmanda el correo de las 10:15 ni retira el webhook
    que ya llegó al ERP del cliente. Si no se dice, el CRM acaba diciendo una cosa
    y el mundo otra, y la diferencia la descubre alguien de fuera.
    """
    dentro = [
        s
        for s in salidas
        if isinstance(s.get("cuando"), datetime) and desde <= s["cuando"] <= hasta
    ]
    por_tipo: dict[str, int] = {}
    for salida in dentro:
        clave = str(salida.get("tipo") or "otro")
        por_tipo[clave] = por_tipo.get(clave, 0) + 1

    return {
        "hay": bool(dentro),
        "por_tipo": por_tipo,
        "total": len(dentro),
        "detalle": [
            {
                "tipo": s.get("tipo"),
                "referencia": s.get("referencia"),
                "cuando": s["cuando"].isoformat(),
            }
            for s in dentro[:50]
        ],
        "que_significa": (
            "En ese tramo no salió nada fuera: la restauración deja el mundo y el CRM "
            "diciendo lo mismo."
            if not dentro
            else f"{len(dentro)} cosas salieron fuera en ese tramo y **no se pueden "
            "deshacer**: correos entregados, eventos que ya recibieron sistemas de "
            "terceros, documentos firmados. Restaurar sin decirlo deja al CRM diciendo "
            "una cosa y al mundo otra."
        ),
        "que_hacer": (
            ""
            if not dentro
            else "Decidir una por una: avisar al destinatario, reenviar el evento "
            "corregido o asumirlo. Lo que no vale es ignorarlo."
        ),
    }


def registrar_prueba(
    *,
    tenant_id: UUID | None,
    inicio: datetime,
    fin: datetime,
    filas_comprobadas: int,
    diferencias: list[str],
    rto_comprometido_min: int,
) -> dict[str, Any]:
    """Anota una prueba de recuperación con **lo que tardó de verdad**.

    Una copia que nadie ha restaurado nunca no es una copia: es un fichero grande.
    Y el RTO que se promete en un contrato no vale nada si nadie lo ha
    cronometrado — casi siempre es más bajo que el real, porque se calculó
    contando solo la restauración y no lo que tarda alguien en darse cuenta, en
    decidir y en encontrar la copia.

    Si hay **diferencias** entre lo restaurado y lo que debería haber, la prueba
    **no pasa**, por pocas que sean: una copia que restaura el 99 % es una copia
    que pierde datos.
    """
    minutos = round((fin - inicio).total_seconds() / 60, 1)
    dentro = minutos <= rto_comprometido_min and not diferencias
    return {
        "tenant_id": str(tenant_id) if tenant_id else "(clúster)",
        "cuando": fin.isoformat(),
        "minutos": minutos,
        "rto_comprometido_min": rto_comprometido_min,
        "filas_comprobadas": filas_comprobadas,
        "diferencias": diferencias,
        "paso": dentro,
        "porque": (
            f"Restauró en {minutos} minutos frente a los {rto_comprometido_min} "
            "comprometidos, y lo restaurado coincide."
            if dentro
            else (
                f"Tardó {minutos} minutos y se prometen {rto_comprometido_min}. El RTO "
                "de un contrato que nadie ha cronometrado casi siempre es más bajo que "
                "el real."
                if minutos > rto_comprometido_min
                else f"Hay {len(diferencias)} diferencias entre lo restaurado y lo "
                "esperado. Una copia que restaura el 99 % es una copia que pierde datos."
            )
        ),
    }


def estado_de_las_pruebas(
    *, pruebas: list[dict[str, Any]], ahora: datetime | None = None
) -> dict[str, Any]:
    """Si las pruebas de recuperación se están haciendo de verdad.

    **Sin ninguna prueba no se dice que todo esté bien**: se dice que no consta
    que la copia sirva. Es la diferencia entre un plan de continuidad y un
    documento con el nombre de un plan de continuidad.
    """
    momento = ahora or _ahora()
    if not pruebas:
        return {
            "medible": False,
            "al_dia": False,
            "porque": (
                "No consta ninguna prueba de recuperación. Eso no es que las copias "
                "estén bien: es que nadie ha comprobado que sirvan, y una copia sin "
                "restaurar nunca es un fichero grande."
            ),
        }

    ordenadas = sorted(
        (p for p in pruebas if isinstance(p.get("cuando"), datetime)),
        key=lambda p: p["cuando"],
    )
    ultima = ordenadas[-1] if ordenadas else None
    dias = (momento - ultima["cuando"]).days if ultima else None
    fallidas = [p for p in pruebas if not p.get("paso")]

    return {
        "medible": True,
        "pruebas": len(pruebas),
        "ultima_hace_dias": dias,
        "al_dia": dias is not None and dias <= _recuperacion_dias_entre_pruebas() and not fallidas,
        "fallidas": len(fallidas),
        "peor_tiempo_min": max((p.get("minutos") or 0) for p in pruebas),
        "que_significa": (
            f"La última prueba es de hace {dias} días y el plazo son "
            f"{_recuperacion_dias_entre_pruebas()}. Con una prueba al año, lo que se descubre es que el "
            "procedimiento llevaba meses roto."
            if dias is not None and dias > _recuperacion_dias_entre_pruebas()
            else (
                f"{len(fallidas)} pruebas no pasaron. Mientras haya una fallida, el plan "
                "de recuperación no está validado por mucho que las demás fueran bien."
                if fallidas
                else "Las pruebas están al día y todas pasaron."
            )
        ),
    }


def rpo_real(
    *, ultima_copia: datetime | None, rpo_comprometido_min: int, ahora: datetime | None = None
) -> dict[str, Any]:
    """Cuánto se perdería ahora mismo si el clúster desapareciera.

    Es el número que hay que poder mirar en cualquier momento, no el que pone el
    contrato. Y sin ninguna copia **no es cero**: es todo.
    """
    momento = ahora or _ahora()
    if ultima_copia is None:
        return {
            "medible": False,
            # **La misma forma, siempre.** Antes, sin copia, faltaban tres
            # campos: `se_perderia_min`, `rpo_comprometido_min` y `dentro`. Una
            # respuesta que cambia de forma según el caso obliga a cada cliente
            # a adivinar cuál le ha tocado, y el que no lo haga enseña un hueco
            # sin explicación justo en la pantalla que se mira el día del
            # incidente. Van a nulo, que es la respuesta: «no se sabe» no es lo
            # mismo que «cero», y es lo que dice `medible`.
            "se_perderia_min": None,
            "rpo_comprometido_min": rpo_comprometido_min,
            "dentro": None,
            "porque": (
                "No consta ninguna copia. El dato que se perdería no es cero: es todo lo "
                "que hay."
            ),
            "aviso": "",
        }
    minutos = round((momento - ultima_copia).total_seconds() / 60, 1)
    return {
        "medible": True,
        "se_perderia_min": minutos,
        "rpo_comprometido_min": rpo_comprometido_min,
        "dentro": minutos <= rpo_comprometido_min,
        "porque": (
            f"La última copia es de hace {minutos} minutos y se prometen "
            f"{rpo_comprometido_min}."
        ),
        "aviso": (
            ""
            if minutos <= rpo_comprometido_min
            else "Se está incumpliendo el RPO ahora mismo, no en teoría. Esto se mira "
            "antes de que pase algo, porque después ya no hay nada que decidir."
        ),
    }


def ventana_de_retencion(*, dias_retencion: int, dias_pedidos: int) -> dict[str, Any]:
    """Comprueba si se puede volver tan atrás como alguien pide.

    Se comprueba **al pedirlo**, no al ejecutarlo. Descubrir a mitad de una
    restauración que no hay copia de ese día es descubrirlo en el peor momento
    posible: cuando ya se ha dicho que se podía.
    """
    return {
        "se_puede": dias_pedidos <= dias_retencion,
        "retencion_dias": dias_retencion,
        "pedidos_dias": dias_pedidos,
        "porque": (
            f"La retención son {dias_retencion} días y se piden {dias_pedidos}. "
            "Descubrirlo a mitad de la restauración es descubrirlo cuando ya se ha dicho "
            "que se podía."
            if dias_pedidos > dias_retencion
            else "Hay copia de ese momento."
        ),
    }
