"""El motor de procesos: durabilidad, decisiones, tareas humanas y compensación.

Estas pruebas cubren CRM-00.03.02.01 (reanudable), .03 (saga orquestada),
.05 (compensaciones), .09 (tareas humanas), .11 (instancia consultable) y
.16 (límites de ejecución).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from services.orchestrator.modelos import DefinicionProceso, InstanciaProceso, PasoEjecutado
from services.orchestrator.motor import Motor, validar_definicion


def _publicar(db: Any, tenant_id: UUID, clave: str, definicion: dict[str, Any]) -> DefinicionProceso:
    fila = DefinicionProceso(
        tenant_id=tenant_id,
        clave=clave,
        version=1,
        nombre=clave,
        definicion=definicion,
        estado="publicada",
    )
    db.add(fila)
    db.flush()
    return fila


# ── Validación ────────────────────────────────────────────────────────────


def test_validacion_detecta_paso_inexistente() -> None:
    problemas = validar_definicion(
        {
            "inicio": "a",
            "pasos": {"a": {"tipo": "decision", "si_no": "no_existe"}},
        }
    )
    assert any("no existe" in p for p in problemas)


def test_validacion_detecta_paso_inalcanzable() -> None:
    problemas = validar_definicion(
        {
            "inicio": "a",
            "pasos": {
                "a": {"tipo": "fin", "resultado": "ok"},
                "huerfano": {"tipo": "fin", "resultado": "ok"},
            },
        }
    )
    assert any("huerfano" in p and "alcanzable" in p for p in problemas)


def test_validacion_acepta_definicion_correcta() -> None:
    assert (
        validar_definicion(
            {
                "inicio": "a",
                "pasos": {
                    "a": {"tipo": "servicio", "operacion": "op", "siguiente": "b"},
                    "b": {"tipo": "fin", "resultado": "ok"},
                },
            }
        )
        == []
    )


# ── Ejecución ─────────────────────────────────────────────────────────────


def test_proceso_lineal_se_completa(db: Any, tenant_id: UUID) -> None:
    llamadas: list[dict[str, Any]] = []

    def crear_pedido(**kw: Any) -> dict[str, Any]:
        llamadas.append(kw)
        return {"id": "PED-1", "importe": 1000}

    _publicar(
        db,
        tenant_id,
        "venta",
        {
            "inicio": "crear",
            "pasos": {
                "crear": {
                    "tipo": "servicio",
                    "operacion": "crear_pedido",
                    "entrada": {"oportunidad_id": "@oportunidad_id"},
                    "salida": "pedido",
                    "siguiente": "fin",
                },
                "fin": {"tipo": "fin", "resultado": "completado"},
            },
        },
    )

    motor = Motor(db, invocadores={"crear_pedido": crear_pedido})
    instancia = motor.arrancar(tenant_id=tenant_id, clave="venta", variables={"oportunidad_id": "OP-9"})
    motor.avanzar(instancia)

    assert instancia.estado == "completada"
    assert instancia.variables["pedido"]["id"] == "PED-1"
    assert llamadas[0]["oportunidad_id"] == "OP-9"
    # La clave de idempotencia llega al invocado: es lo que permite que un
    # reintento tras una caída no duplique el efecto.
    assert "_idempotencia" in llamadas[0]


def test_decision_elige_rama_por_importe(db: Any, tenant_id: UUID) -> None:
    _publicar(
        db,
        tenant_id,
        "aprobacion",
        {
            "inicio": "decidir",
            "pasos": {
                "decidir": {
                    "tipo": "decision",
                    "condiciones": [
                        {
                            "si": {"atributo": "importe", "op": ">", "valor": 50000},
                            "entonces": "fin_grande",
                        }
                    ],
                    "si_no": "fin_pequeno",
                },
                "fin_grande": {"tipo": "fin", "resultado": "grande"},
                "fin_pequeno": {"tipo": "fin", "resultado": "pequeno"},
            },
        },
    )
    motor = Motor(db)

    grande = motor.arrancar(tenant_id=tenant_id, clave="aprobacion", variables={"importe": 80000})
    motor.avanzar(grande)
    pequeno = motor.arrancar(tenant_id=tenant_id, clave="aprobacion", variables={"importe": 100})
    motor.avanzar(pequeno)

    assert grande.variables["resultado"] == "grande"
    assert pequeno.variables["resultado"] == "pequeno"


def test_tarea_humana_detiene_y_reanuda(db: Any, tenant_id: UUID) -> None:
    """CRM-00.03.02.09: el proceso espera a una persona sin consumir nada."""
    from crmcore.ids import nuevo_id
    from services.orchestrator.modelos import TareaHumana

    _publicar(
        db,
        tenant_id,
        "descuento",
        {
            "inicio": "aprobar",
            "pasos": {
                "aprobar": {
                    "tipo": "humano",
                    "titulo": "Aprobar descuento de @pct%",
                    "asignada_rol": "responsable_ventas",
                    "vence_en_horas": 48,
                    "rutas": {"aprobar": "fin_ok", "rechazar": "fin_no"},
                },
                "fin_ok": {"tipo": "fin", "resultado": "aprobado"},
                "fin_no": {"tipo": "fin", "resultado": "rechazado"},
            },
        },
    )
    motor = Motor(db)
    instancia = motor.arrancar(tenant_id=tenant_id, clave="descuento", variables={"pct": 25})
    motor.avanzar(instancia)

    assert instancia.estado == "esperando_humano"
    tarea = db.query(TareaHumana).filter_by(instancia_id=instancia.id).one()
    # El título se interpola con las variables: quien lo ve en la bandeja
    # entiende qué aprueba sin abrir el proceso.
    assert tarea.titulo == "Aprobar descuento de 25%"
    assert tarea.vence_at is not None

    usuario = nuevo_id()
    motor.responder_tarea(tarea, respuesta="aprobar", usuario_id=usuario, comentario="vale")
    motor.avanzar(instancia)

    assert instancia.estado == "completada"
    assert instancia.variables["resultado"] == "aprobado"
    assert instancia.variables["aprobar_respuesta"] == "aprobar"
    assert instancia.variables["aprobar_por"] == str(usuario)


def test_respuesta_no_valida_se_rechaza(db: Any, tenant_id: UUID) -> None:
    from crmcore.errors import ErrorValidacion
    from crmcore.ids import nuevo_id
    from services.orchestrator.modelos import TareaHumana

    _publicar(
        db,
        tenant_id,
        "p",
        {
            "inicio": "t",
            "pasos": {
                "t": {"tipo": "humano", "titulo": "x", "rutas": {"si": "f"}},
                "f": {"tipo": "fin", "resultado": "ok"},
            },
        },
    )
    motor = Motor(db)
    instancia = motor.arrancar(tenant_id=tenant_id, clave="p")
    motor.avanzar(instancia)
    tarea = db.query(TareaHumana).filter_by(instancia_id=instancia.id).one()

    with pytest.raises(ErrorValidacion) as exc:
        motor.responder_tarea(tarea, respuesta="quizas", usuario_id=nuevo_id())
    assert exc.value.error_code == "tarea.respuesta_invalida"


# ── Saga y compensación ───────────────────────────────────────────────────


def test_saga_compensa_en_orden_inverso(db: Any, tenant_id: UUID) -> None:
    """CRM-00.03.02.05: al fallar el tercer paso, se deshacen los dos primeros.

    Es el caso que el catálogo pone como pregunta de verificación: pedido creado
    en el CRM pero rechazado en el ERP.
    """
    hechos: list[str] = []

    def reservar_stock(**_kw: Any) -> dict[str, Any]:
        hechos.append("reservar_stock")
        return {"reserva": "R-1"}

    def crear_pedido(**_kw: Any) -> dict[str, Any]:
        hechos.append("crear_pedido")
        return {"id": "PED-1"}

    def enviar_erp(**_kw: Any) -> dict[str, Any]:
        hechos.append("enviar_erp")
        raise RuntimeError("el ERP ha rechazado el pedido: cliente bloqueado")

    def liberar_stock(**_kw: Any) -> dict[str, Any]:
        hechos.append("liberar_stock")
        return {}

    def anular_pedido(**_kw: Any) -> dict[str, Any]:
        hechos.append("anular_pedido")
        return {}

    _publicar(
        db,
        tenant_id,
        "order_to_cash",
        {
            "inicio": "reservar",
            "pasos": {
                "reservar": {
                    "tipo": "servicio",
                    "operacion": "reservar_stock",
                    "salida": "reserva",
                    "compensacion": {"operacion": "liberar_stock", "entrada": {"r": "@reserva"}},
                    "siguiente": "pedido",
                },
                "pedido": {
                    "tipo": "servicio",
                    "operacion": "crear_pedido",
                    "salida": "pedido",
                    "compensacion": {"operacion": "anular_pedido", "entrada": {"p": "@pedido.id"}},
                    "siguiente": "erp",
                },
                "erp": {"tipo": "servicio", "operacion": "enviar_erp", "siguiente": "fin"},
                "fin": {"tipo": "fin", "resultado": "ok"},
            },
        },
    )

    motor = Motor(
        db,
        invocadores={
            "reservar_stock": reservar_stock,
            "crear_pedido": crear_pedido,
            "enviar_erp": enviar_erp,
            "liberar_stock": liberar_stock,
            "anular_pedido": anular_pedido,
        },
    )
    instancia = motor.arrancar(tenant_id=tenant_id, clave="order_to_cash")
    motor.avanzar(instancia)

    assert instancia.estado == "compensada"
    # Orden inverso: primero se anula el pedido (último hecho), luego se libera
    # el stock. Al revés dejaría el stock libre con un pedido vivo apuntándolo.
    assert hechos == [
        "reservar_stock",
        "crear_pedido",
        "enviar_erp",
        "anular_pedido",
        "liberar_stock",
    ]
    assert "cliente bloqueado" in (instancia.error or "")


def test_compensacion_incompleta_deja_la_instancia_fallida(db: Any, tenant_id: UUID) -> None:
    """Si una compensación falla, se sigue con las demás y se marca fallida.

    Parar en la primera compensación fallida dejaría los pasos anteriores sin
    deshacer: más efectos vivos y menos rastro de cuáles.
    """
    hechos: list[str] = []

    def paso_a(**_kw: Any) -> dict[str, Any]:
        hechos.append("a")
        return {}

    def paso_b(**_kw: Any) -> dict[str, Any]:
        raise RuntimeError("falla b")

    def comp_a(**_kw: Any) -> dict[str, Any]:
        hechos.append("comp_a")
        raise RuntimeError("la compensación también falla")

    _publicar(
        db,
        tenant_id,
        "frágil",
        {
            "inicio": "a",
            "pasos": {
                "a": {
                    "tipo": "servicio",
                    "operacion": "paso_a",
                    "compensacion": {"operacion": "comp_a"},
                    "siguiente": "b",
                },
                "b": {"tipo": "servicio", "operacion": "paso_b", "siguiente": "fin"},
                "fin": {"tipo": "fin", "resultado": "ok"},
            },
        },
    )
    motor = Motor(
        db, invocadores={"paso_a": paso_a, "paso_b": paso_b, "comp_a": comp_a}
    )
    instancia = motor.arrancar(tenant_id=tenant_id, clave="frágil")
    motor.avanzar(instancia)

    assert instancia.estado == "fallida"
    assert "compensación incompleta" in (instancia.error or "")
    assert hechos == ["a", "comp_a"]


# ── Durabilidad y límites ─────────────────────────────────────────────────


def test_el_estado_sobrevive_a_un_motor_nuevo(db: Any, tenant_id: UUID) -> None:
    """CRM-00.03.02.01: otro proceso retoma la instancia donde estaba.

    Se simula la caída usando un motor distinto, que es lo que de verdad pasa
    cuando el worker muere y otro recoge la instancia: no comparte nada en
    memoria, solo lo que hay en la base.
    """
    from services.orchestrator.modelos import TareaHumana

    _publicar(
        db,
        tenant_id,
        "largo",
        {
            "inicio": "esperar_persona",
            "pasos": {
                "esperar_persona": {
                    "tipo": "humano",
                    "titulo": "Revisar",
                    "rutas": {"listo": "fin"},
                },
                "fin": {"tipo": "fin", "resultado": "ok"},
            },
        },
    )
    primer_motor = Motor(db, worker_id="worker-1")
    instancia = primer_motor.arrancar(tenant_id=tenant_id, clave="largo", variables={"x": 1})
    primer_motor.avanzar(instancia)
    instancia_id = instancia.id
    db.commit()

    # El worker muere aquí. Otro, sin nada en memoria, recoge la instancia.
    db.expire_all()
    otro_motor = Motor(db, worker_id="worker-2")
    recuperada = db.get(InstanciaProceso, instancia_id)
    assert recuperada is not None
    assert recuperada.estado == "esperando_humano"
    assert recuperada.variables["x"] == 1

    tarea = db.query(TareaHumana).filter_by(instancia_id=instancia_id).one()
    from crmcore.ids import nuevo_id

    otro_motor.responder_tarea(tarea, respuesta="listo", usuario_id=nuevo_id())
    otro_motor.avanzar(recuperada)
    assert recuperada.estado == "completada"


def test_limite_de_pasos_corta_un_bucle(db: Any, tenant_id: UUID) -> None:
    """CRM-00.03.02.16: un proceso que se repite no consume el sistema."""
    import os

    from crmcore.config import limpiar_cache_settings

    os.environ["PROCESO_MAX_PASOS"] = "5"
    limpiar_cache_settings()
    try:
        _publicar(
            db,
            tenant_id,
            "bucle",
            {
                "inicio": "vuelta",
                "pasos": {"vuelta": {"tipo": "decision", "si_no": "vuelta"}},
            },
        )
        motor = Motor(db)
        instancia = motor.arrancar(tenant_id=tenant_id, clave="bucle")
        motor.avanzar(instancia, max_pasos=1000)

        assert instancia.estado == "fallida"
        assert "bucle" in (instancia.error or "").lower()
    finally:
        os.environ.pop("PROCESO_MAX_PASOS", None)
        limpiar_cache_settings()


def test_historial_registra_cada_paso(db: Any, tenant_id: UUID) -> None:
    """CRM-00.03.02.11: se puede responder «¿por dónde va y qué hizo?»."""

    def op(**_kw: Any) -> dict[str, Any]:
        return {"ok": True}

    _publicar(
        db,
        tenant_id,
        "trazado",
        {
            "inicio": "uno",
            "pasos": {
                "uno": {"tipo": "servicio", "operacion": "op", "siguiente": "dos"},
                "dos": {"tipo": "servicio", "operacion": "op", "siguiente": "fin"},
                "fin": {"tipo": "fin", "resultado": "ok"},
            },
        },
    )
    motor = Motor(db, invocadores={"op": op})
    instancia = motor.arrancar(tenant_id=tenant_id, clave="trazado")
    motor.avanzar(instancia)

    pasos = (
        db.query(PasoEjecutado)
        .filter_by(instancia_id=instancia.id)
        .order_by(PasoEjecutado.created_at)
        .all()
    )
    assert [p.paso for p in pasos] == ["uno", "dos", "fin"]
    assert all(p.resultado == "ok" for p in pasos)


def test_sin_reintentos_declarados_no_se_reintenta(db: Any, tenant_id: UUID) -> None:
    """Un paso sin `reintentos` falla a la primera y compensa.

    Fija la regresión encontrada al escribir esta suite: el motor contaba los
    intentos con una consulta antes de volcar el fallo a la base, así que veía
    cero y reintentaba incluso lo declarado sin reintentos.
    """
    intentos: list[int] = []

    def siempre_falla(**_kw: Any) -> dict[str, Any]:
        intentos.append(1)
        raise RuntimeError("no hay manera")

    _publicar(
        db,
        tenant_id,
        "sin_reintentos",
        {
            "inicio": "a",
            "pasos": {
                "a": {"tipo": "servicio", "operacion": "siempre_falla", "siguiente": "fin"},
                "fin": {"tipo": "fin", "resultado": "ok"},
            },
        },
    )
    motor = Motor(db, invocadores={"siempre_falla": siempre_falla})
    instancia = motor.arrancar(tenant_id=tenant_id, clave="sin_reintentos")
    motor.avanzar(instancia)

    assert len(intentos) == 1
    # Sin compensaciones declaradas no hay nada que deshacer, así que termina
    # compensada (recorrió la pila y no había nada) en vez de fallida.
    assert instancia.estado in ("compensada", "fallida")


def test_reintentos_agotan_y_luego_compensan(db: Any, tenant_id: UUID) -> None:
    """`reintentos: 2` = tres intentos en total, y después se compensa."""
    intentos: list[int] = []

    def inestable(**_kw: Any) -> dict[str, Any]:
        intentos.append(1)
        raise RuntimeError("el sistema externo no responde")

    _publicar(
        db,
        tenant_id,
        "con_reintentos",
        {
            "inicio": "a",
            "pasos": {
                "a": {
                    "tipo": "servicio",
                    "operacion": "inestable",
                    "reintentos": 2,
                    "siguiente": "fin",
                },
                "fin": {"tipo": "fin", "resultado": "ok"},
            },
        },
    )
    motor = Motor(db, invocadores={"inestable": inestable})
    instancia = motor.arrancar(tenant_id=tenant_id, clave="con_reintentos")

    # Cada vuelta del worker es un intento: entre uno y otro el motor programa
    # el despertar con backoff, y es el planificador quien vuelve a llamarlo.
    for _ in range(4):
        if instancia.estado != "ejecutando":
            break
        motor.avanzar(instancia)

    assert len(intentos) == 3, f"esperaba 3 intentos, hubo {len(intentos)}"
    assert instancia.estado in ("compensada", "fallida")


def test_ruta_de_error_evita_la_compensacion(db: Any, tenant_id: UUID) -> None:
    """`al_fallar` es un camino de negocio, no una excepción: no compensa."""

    def falla(**_kw: Any) -> dict[str, Any]:
        raise RuntimeError("el ERP rechaza")

    compensado: list[str] = []

    def compensar(**_kw: Any) -> dict[str, Any]:
        compensado.append("x")
        return {}

    _publicar(
        db,
        tenant_id,
        "con_ruta_error",
        {
            "inicio": "a",
            "pasos": {
                "a": {
                    "tipo": "servicio",
                    "operacion": "falla",
                    "compensacion": {"operacion": "compensar"},
                    "al_fallar": "revision_manual",
                    "siguiente": "fin",
                },
                "revision_manual": {"tipo": "fin", "resultado": "a_revision"},
                "fin": {"tipo": "fin", "resultado": "ok"},
            },
        },
    )
    motor = Motor(db, invocadores={"falla": falla, "compensar": compensar})
    instancia = motor.arrancar(tenant_id=tenant_id, clave="con_ruta_error")
    motor.avanzar(instancia)
    motor.avanzar(instancia)

    assert instancia.variables.get("resultado") == "a_revision"
    assert compensado == [], "una ruta de error declarada no debe disparar la compensación"
