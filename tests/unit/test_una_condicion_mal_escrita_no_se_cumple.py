"""Una condición que no se puede evaluar **no se cumple**. En las cuatro vías.

El 26-10-2026, auditando el motor de procesos, salió esto: una condición sin
`atributo` se evaluaba a CIERTO. `resolver("@", …)` devuelve nulo, el valor por
defecto también es nulo, y el `=` los da por iguales. Así que una condición
escrita con las claves cambiadas —la errata que se comete de memoria— se
cumplía siempre.

Y **no estaba en un sitio: estaba en cuatro**, porque las cuatro comparten la
misma tabla de operadores y el mismo resolvedor:

  · el **motor de procesos** se iba siempre por la primera rama, con el `si_no`
    escrito al lado sin usarse nunca;
  · los **webhooks** entregaban TODO a una suscripción que pedía filtrar — que
    es mandarle al integrador datos que no pidió;
  · las **automatizaciones** se disparaban con cualquier registro, o sea mandar
    correos y cambiar datos que nadie pidió tocar;
  · y las **reglas de validación** saltaban con cualquier cosa, salvo que la
    condición se saltara entera y entonces decidían las demás solas.

Ninguna de las cuatro falla: todas devuelven algo plausible. Por eso esto es un
gate y no cuatro pruebas sueltas — lo que hay que impedir es que la quinta vía
nazca con el mismo agujero.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from uuid import uuid4

RAIZ = Path(__file__).resolve().parents[2]

# Las cuatro que evalúan condiciones de usuario. Es una lista CERRADA: si
# apareciera una quinta, el recorrido de abajo la encuentra y esto falla hasta
# que alguien la mire.
EVALUADORES = {
    "services/orchestrator/motor.py",
    "services/eventing/entrega.py",
    "services/automation/motor.py",
    "services/metadata/validacion.py",
}


def _ficheros_que_resuelven_atributos() -> set[str]:
    """Quién construye una referencia `@<atributo>` para compararla.

    Es la firma de este patrón: resolver un atributo que viene de un dato del
    tenant y pasarlo por la tabla de operadores.
    """
    encontrados: set[str] = set()
    for fichero in sorted(RAIZ.glob("services/*/*.py")):
        texto = fichero.read_text(encoding="utf-8")
        if 'resolver(f"@' in texto and "OPERADORES" in texto:
            encontrados.add(str(fichero.relative_to(RAIZ)))
    return encontrados


def test_el_recorrido_mira_de_verdad() -> None:
    """Sin esto, un recorrido que no encontrara ninguna diría que están todas
    bien, que es el mismo verde que no tener el problema."""
    vistos = _ficheros_que_resuelven_atributos()
    assert len(vistos) >= 4, f"sólo se ven {len(vistos)}: {sorted(vistos)}"
    assert "services/orchestrator/motor.py" in vistos


def test_no_ha_aparecido_una_quinta_via_sin_mirarla() -> None:
    """La lista sólo crece a mano, y crece habiendo comprobado que la nueva
    también trata la condición mal escrita como «no se cumple»."""
    nuevas = sorted(_ficheros_que_resuelven_atributos() - EVALUADORES)
    assert not nuevas, (
        "Hay sitios nuevos que evalúan condiciones de usuario y no constan "
        "aquí. Comprueba que una condición sin atributo o con un operador "
        "desconocido NO se cumpla, y añádelos a la lista:\n  " + "\n  ".join(nuevas)
    )


def test_los_cuatro_descartan_lo_que_no_pueden_evaluar() -> None:
    """Leído del código: los cuatro tienen que mirar el atributo antes de
    comparar. Sin esta comprobación, el día que alguien «simplifique» uno de
    ellos vuelve el agujero y no falla nada."""
    sin_mirar = []
    for ruta in sorted(EVALUADORES):
        texto = (RAIZ / ruta).read_text(encoding="utf-8")
        if 'str(condicion.get("atributo") or "").strip()' not in texto and (
            'str(condicion.get("atributo", "")).strip()' not in texto
        ):
            sin_mirar.append(ruta)
    assert not sin_mirar, (
        "Estos evalúan condiciones y no comprueban que haya atributo:\n  " + "\n  ".join(sin_mirar)
    )


# ── Y las cuatro, ejecutadas ──────────────────────────────────────────────


MAL_ESCRITA = {"variable": "importe", "operador": ">", "valor": 1000}


def test_el_motor_de_procesos_no_la_cumple() -> None:
    from services.orchestrator.motor import cumple_condicion

    assert cumple_condicion(MAL_ESCRITA, {"importe": 10}) is False
    assert cumple_condicion({}, {"importe": 10}) is False
    assert cumple_condicion({"atributo": "importe", "op": "parecido"}, {"importe": 10}) is False
    # Y la bien escrita sigue funcionando, que es la otra mitad: un guardián
    # que lo niegue todo también «arregla» el problema.
    assert cumple_condicion({"atributo": "importe", "op": ">", "valor": 5}, {"importe": 10}) is True


def test_un_webhook_con_la_condicion_mal_escrita_no_recibe_todo() -> None:
    """Entregar de más es mandarle al integrador datos de negocio que no pidió,
    y no deja rastro de que fuera un error: le llegan y los procesa."""
    from crmcore.events.envelope import crear_evento

    from services.eventing.entrega import coincide
    from services.eventing.modelos import Suscripcion

    evento = crear_evento(
        "opportunity.won", tenant_id=uuid4(), subject=("oportunidad", uuid4()), data={"importe": 10}
    )
    suscripcion = Suscripcion(
        tenant_id=evento.tenant_id,
        nombre="sólo las grandes",
        url="https://ejemplo/webhook",
        eventos=["opportunity.won"],
        condiciones=[MAL_ESCRITA],
    )
    assert coincide(suscripcion, evento) is False

    suscripcion.condiciones = [{"atributo": "importe", "op": ">", "valor": 5}]
    assert coincide(suscripcion, evento) is True


def test_una_automatizacion_con_la_condicion_mal_escrita_no_se_dispara() -> None:
    """Dispararse de más es mandar correos y cambiar registros que nadie pidió
    tocar, sobre todos los registros del tenant."""
    from services.automation.motor import _evaluar_lista

    cumple, decisiones = _evaluar_lista([MAL_ESCRITA], {"importe": 10}, combinacion="todas")
    assert cumple is False, decisiones

    # Y la bien escrita sí: un guardián que lo niegue todo también «arregla» el
    # problema, y deja la automatización sin dispararse nunca.
    cumple, _ = _evaluar_lista(
        [{"atributo": "importe", "op": ">", "valor": 5}], {"importe": 10}, combinacion="todas"
    )
    assert cumple is True


def test_una_regla_de_validacion_mal_escrita_no_salta_con_todo() -> None:
    """**Ojo con el sentido**: las condiciones de una regla de validación
    describen la situación PROHIBIDA, así que «se cumple» quiere decir «el
    registro es inválido». Una condición que no se puede evaluar no permite
    afirmar que la situación prohibida se dé, así que la regla no se incumple.

    Y la condición mal escrita **no se salta**: saltarla dejaba que las demás
    decidieran solas, que es otra forma de que la regla haga algo distinto de lo
    que dice.
    """
    from types import SimpleNamespace

    from services.metadata.validacion import _regla_incumplida

    mal = SimpleNamespace(condiciones=[MAL_ESCRITA], combinacion="todas")
    assert _regla_incumplida(mal, {"importe": 10}) is False

    bien = SimpleNamespace(
        condiciones=[{"atributo": "importe", "op": ">", "valor": 5}], combinacion="todas"
    )
    assert _regla_incumplida(bien, {"importe": 10}) is True


def _firma(nombre: str, fichero: str) -> Any:
    arbol = ast.parse((RAIZ / fichero).read_text(encoding="utf-8"))
    return next(n for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef) and n.name == nombre)


def test_el_simulador_no_tiene_su_propia_copia() -> None:
    """**Un simulador que no decide igual que el motor es peor que no tener
    simulador**: enseña un camino que luego no se recorre.

    Estaba duplicado, y se vio justo al arreglar lo de arriba: sólo se arregló
    una de las dos copias. Ahora la API llama a la del motor, y esto lo vigila.
    """
    api = (RAIZ / "services/orchestrator/api.py").read_text(encoding="utf-8")
    assert (
        "mtr.cumple_condicion(" in api
    ), "el simulador ha vuelto a evaluar las condiciones por su cuenta"
    assert "mtr.OPERADORES.get(" not in api, (
        "el simulador vuelve a tener su propia tabla de operadores: dos copias "
        "de la misma decisión acaban decidiendo distinto"
    )
