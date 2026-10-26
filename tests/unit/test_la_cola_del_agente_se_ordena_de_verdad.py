"""La consola decía que ordenaba por espera y no lo hacía.

El punto de la omnicanalidad no es tener cinco bandejas bonitas: es **una sola
cola**, para que lo que lleva más esperando se atienda antes venga por donde
venga. Con una bandeja por canal, el correo se mira dos veces al día y el chat
todo el rato, y quien escribe por correo espera el doble sin que nadie lo haya
decidido.

La pantalla mezclaba las dos listas, sí — pero daba a **todas** las
conversaciones la misma urgencia, una constante enorme. O sea que siempre iban
al final, y entre ellas quedaban por orden de llegada de la consulta. Su propio
comentario decía lo contrario.

Se ordena ahora en el servidor, que es donde están los datos y lo que hace que
una consola empotrada —esto se publica para empotrarse— vea el mismo orden que
la oficial. Dos agentes con dos consolas no pueden atender en orden distinto.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db

AHORA = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def _caso(db: Any, tenant_id: UUID, agente: UUID, asunto: str, *, horas: float | None):
    from services.service.modelos import Caso

    fila = Caso(
        tenant_id=tenant_id,
        asunto=asunto,
        codigo=asunto.upper(),
        estado="nuevo",
        owner_id=agente,
        vence_resolucion_at=(AHORA + timedelta(hours=horas) if horas is not None else None),
    )
    db.add(fila)
    return fila


def _conversacion(db: Any, tenant_id: UUID, agente: UUID, asunto: str, *, horas_espera: float):
    from services.service.omnicanal import Conversacion

    fila = Conversacion(
        tenant_id=tenant_id,
        agente_id=agente,
        asunto=asunto,
        estado="abierta",
        canal_actual="chat",
        ultimo_mensaje_at=AHORA - timedelta(hours=horas_espera),
    )
    db.add(fila)
    return fila


@pytest.fixture
def agente(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> UUID:
    return uuid4()


def _cola(db: Any, tenant_id: UUID, agente: UUID) -> list[dict[str, Any]]:
    from services.service import omnicanal

    return omnicanal.consola(db, tenant_id, agente)["cola"]


def test_lo_vencido_va_primero(db: Any, tenant_id: UUID, agente: UUID) -> None:
    """Lo que ya incumplió no espera. Sale en negativo, así que encabeza."""
    _caso(db, tenant_id, agente, "pronto", horas=2)
    _caso(db, tenant_id, agente, "tarde", horas=-5)
    db.flush()

    assert [f["asunto"].split(" · ")[-1] for f in _cola(db, tenant_id, agente)][0] == "tarde"
    assert _cola(db, tenant_id, agente)[0]["vencido"] is True


def test_una_conversacion_que_lleva_mas_esperando_va_antes(
    db: Any, tenant_id: UUID, agente: UUID
) -> None:
    """**El fallo.** Todas llevaban la misma urgencia, así que entre ellas
    quedaban por orden de llegada de la consulta: la que llevaba tres días
    esperando podía salir detrás de la de hace cinco minutos."""
    _conversacion(db, tenant_id, agente, "reciente", horas_espera=0.1)
    _conversacion(db, tenant_id, agente, "vieja", horas_espera=72)
    db.flush()

    asuntos = [f["asunto"] for f in _cola(db, tenant_id, agente) if f["tipo"] == "conversacion"]
    assert asuntos == ["vieja", "reciente"]


def test_lo_que_tiene_plazo_va_antes_que_lo_que_no(db: Any, tenant_id: UUID, agente: UUID) -> None:
    """No se inventa un cambio de moneda entre «minutos para vencer» y «minutos
    esperando»: son dos cosas distintas. Lo que tiene un compromiso con fecha va
    primero, y lo demás después por antigüedad."""
    _conversacion(db, tenant_id, agente, "vieja", horas_espera=72)
    _caso(db, tenant_id, agente, "con_plazo", horas=48)
    db.flush()

    cola = _cola(db, tenant_id, agente)
    assert [f["tipo"] for f in cola] == ["caso", "conversacion"]


def test_lo_que_no_sabemos_cuanto_espera_va_al_final(
    db: Any, tenant_id: UUID, agente: UUID
) -> None:
    """No es urgente: es desconocido. Colarlo arriba taparía lo que sí sabemos
    que corre."""
    _conversacion(db, tenant_id, agente, "sin_fecha", horas_espera=0).ultimo_mensaje_at = None
    _conversacion(db, tenant_id, agente, "con_espera", horas_espera=10)
    db.flush()

    asuntos = [f["asunto"] for f in _cola(db, tenant_id, agente) if f["tipo"] == "conversacion"]
    assert asuntos == ["con_espera", "sin_fecha"]


def test_el_canal_viaja_para_poder_etiquetarlo(db: Any, tenant_id: UUID, agente: UUID) -> None:
    """El canal es una etiqueta, no una pestaña — pero tiene que verse: quien
    atiende no contesta igual un chat que un correo."""
    _conversacion(db, tenant_id, agente, "una", horas_espera=1)
    _caso(db, tenant_id, agente, "otro", horas=1)
    db.flush()

    canales = {f["canal"] for f in _cola(db, tenant_id, agente)}
    assert canales == {"chat", "caso"}


def test_la_cola_lleva_el_identificador_para_poder_abrirlo(
    db: Any, tenant_id: UUID, agente: UUID
) -> None:
    """Una consola de la que no se puede entrar a trabajar es un informe."""
    caso = _caso(db, tenant_id, agente, "uno", horas=1)
    db.flush()

    fila = next(f for f in _cola(db, tenant_id, agente) if f["tipo"] == "caso")
    assert fila["id"] == str(caso.id)


def test_las_dos_listas_de_siempre_siguen_estando(db: Any, tenant_id: UUID, agente: UUID) -> None:
    """La cola se añade; no se quitan `mis_casos` ni `mis_conversaciones`. Esto
    se publica para empotrarse, y quitarle un campo a un contrato publicado
    rompe a quien ya lo usa sin avisar."""
    from services.service import omnicanal

    _caso(db, tenant_id, agente, "uno", horas=1)
    db.flush()
    salida = omnicanal.consola(db, tenant_id, agente)
    assert "mis_casos" in salida and "mis_conversaciones" in salida and "cola" in salida
