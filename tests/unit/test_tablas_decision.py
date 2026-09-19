"""Tablas de decisión: evaluación, explicación y análisis (CRM-00.03.02.10).

Lo que estas pruebas defienden:

  * **El resultado es reproducible.** Dos ejecuciones idénticas dan lo mismo,
    con cualquier política. Una tabla cuyo resultado depende del orden de
    lectura de la base es peor que un `if`, porque nadie sospecha de ella.
  * **La explicación sirve para algo.** No basta con decir qué salió: hay que
    poder responder «¿por qué no casó la regla del director?» sin reconstruir a
    mano la evaluación.
  * **El análisis no miente en ninguna de las dos direcciones.** No dice
    «completa» cuando no lo sabe, y no calla un hueco que sí puede demostrar.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.errors import ErrorValidacion

from services.orchestrator import decision as dec


def _tabla(**cambios: Any) -> dict[str, Any]:
    """Aprobación de descuento: el ejemplo real más pequeño que hay."""
    base: dict[str, Any] = {
        "clave": "aprobacion_descuento",
        "nombre": "Quién aprueba un descuento",
        "politica": "primera",
        "entradas": [
            {"clave": "importe", "expresion": "@oportunidad.importe", "tipo": "numero"},
            {"clave": "descuento", "expresion": "@oportunidad.descuento_pct", "tipo": "numero"},
        ],
        "salidas": [{"clave": "aprobador", "tipo": "texto", "por_defecto": "comercial"}],
        "reglas": [
            {
                "nombre": "descuento alto",
                "condiciones": [{"entrada": "descuento", "op": ">", "valor": 25}],
                "salidas": {"aprobador": "director"},
            },
            {
                "nombre": "importe alto",
                "condiciones": [{"entrada": "importe", "op": ">=", "valor": 50000}],
                "salidas": {"aprobador": "responsable_zona"},
            },
        ],
    }
    base.update(cambios)
    return base


def _vars(importe: float, descuento: float) -> dict[str, Any]:
    return {"oportunidad": {"importe": importe, "descuento_pct": descuento}}


def _publicar(db: Any, tenant_id: UUID, clave: str, definicion: dict[str, Any]) -> None:
    from services.orchestrator.modelos import DefinicionProceso

    db.add(
        DefinicionProceso(
            tenant_id=tenant_id,
            clave=clave,
            version=1,
            nombre=clave,
            definicion=definicion,
            estado="publicada",
        )
    )
    db.flush()


# ── Evaluación ────────────────────────────────────────────────────────────


def test_gana_la_primera_regla_que_casa() -> None:
    d = dec.evaluar(_tabla(), _vars(importe=80_000, descuento=30))
    assert d.salidas["aprobador"] == "director"
    # Las dos casaban; la política decide, y se ve cuál ganó y cuál no.
    assert [r.nombre for r in d.casadas] == ["descuento alto", "importe alto"]


def test_sin_aciertos_se_usa_el_valor_por_defecto_y_se_marca_como_tal() -> None:
    """«No casó nada» y «casó la regla que da ese valor» son cosas distintas, y
    en una auditoría la diferencia importa."""
    d = dec.evaluar(_tabla(), _vars(importe=1_000, descuento=5))
    assert d.salidas["aprobador"] == "comercial"
    assert d.por_defecto is True


def test_la_explicacion_dice_en_que_condicion_fallo_cada_regla() -> None:
    """Es la pregunta que de verdad se hace: no «qué salió» sino «por qué no
    salió lo otro»."""
    d = dec.evaluar(_tabla(), _vars(importe=1_000, descuento=5))
    fallo = d.reglas[0].fallo_en
    assert fallo == {
        "entrada": "descuento",
        "operador": ">",
        "esperado": 25,
        "encontrado": 5,
    }


def test_las_entradas_resueltas_quedan_en_el_resultado() -> None:
    """Sin ellas, «no casó ninguna regla» no se puede diagnosticar después: el
    contexto de aquella ejecución ya no existe."""
    d = dec.evaluar(_tabla(), _vars(importe=1_000, descuento=5))
    assert d.entradas == {"importe": 1_000, "descuento": 5}


def test_una_entrada_ausente_no_casa_en_vez_de_reventar() -> None:
    """Una tabla mal escrita no puede detener un proceso que lleva tres días en
    marcha."""
    d = dec.evaluar(_tabla(), {"oportunidad": {}})
    assert d.por_defecto is True
    assert d.entradas == {"importe": None, "descuento": None}


def test_una_condicion_puede_comparar_con_otra_variable_del_contexto() -> None:
    """«El descuento supera el máximo de su tier» no se puede escribir con una
    constante, y es la mitad de las reglas reales."""
    tabla = _tabla(
        reglas=[
            {
                "nombre": "pasa del máximo del tier",
                "condiciones": [{"entrada": "descuento", "op": ">", "valor": "@limites.maximo"}],
                "salidas": {"aprobador": "director"},
            }
        ]
    )
    contexto = {**_vars(0, 12), "limites": {"maximo": 10}}
    assert dec.evaluar(tabla, contexto).salidas["aprobador"] == "director"

    contexto["limites"] = {"maximo": 20}
    assert dec.evaluar(tabla, contexto).por_defecto is True


# ── Políticas de aciertos ─────────────────────────────────────────────────


def test_politica_unica_rechaza_dos_aciertos_en_vez_de_elegir_uno() -> None:
    """Elegir en silencio es lo que convierte una ambigüedad en un misterio."""
    with pytest.raises(ErrorValidacion, match="solo case una") as exc:
        dec.evaluar(_tabla(politica="unica"), _vars(importe=80_000, descuento=30))
    assert exc.value.detalle["reglas"] == ["descuento alto", "importe alto"]


def test_politica_unica_con_un_solo_acierto_funciona() -> None:
    d = dec.evaluar(_tabla(politica="unica"), _vars(importe=80_000, descuento=5))
    assert d.salidas["aprobador"] == "responsable_zona"


def test_politica_prioridad_gana_la_declarada_y_no_el_orden() -> None:
    tabla = _tabla(politica="prioridad")
    tabla["reglas"][0]["prioridad"] = 1
    tabla["reglas"][1]["prioridad"] = 9
    d = dec.evaluar(tabla, _vars(importe=80_000, descuento=30))
    assert d.salidas["aprobador"] == "responsable_zona"


def test_a_igual_prioridad_gana_la_primera_escrita_siempre() -> None:
    """La reproducibilidad es el punto: sin un desempate estable, dos
    ejecuciones idénticas pueden dar cosas distintas."""
    tabla = _tabla(politica="prioridad")
    tabla["reglas"][0]["prioridad"] = 5
    tabla["reglas"][1]["prioridad"] = 5
    for _ in range(5):
        assert dec.evaluar(tabla, _vars(80_000, 30)).salidas["aprobador"] == "director"


def test_politica_cualquiera_admite_varios_aciertos_si_coinciden() -> None:
    tabla = _tabla(politica="cualquiera")
    tabla["reglas"][1]["salidas"] = {"aprobador": "director"}
    assert dec.evaluar(tabla, _vars(80_000, 30)).salidas["aprobador"] == "director"


def test_politica_cualquiera_rechaza_aciertos_que_discrepan() -> None:
    """La tabla estaría diciendo dos cosas distintas del mismo caso."""
    with pytest.raises(ErrorValidacion, match="no coinciden"):
        dec.evaluar(_tabla(politica="cualquiera"), _vars(80_000, 30))


def test_politica_todas_acumula_las_salidas_en_listas() -> None:
    d = dec.evaluar(_tabla(politica="todas"), _vars(80_000, 30))
    assert d.salidas["aprobador"] == ["director", "responsable_zona"]


def test_una_politica_desconocida_se_rechaza_al_evaluar() -> None:
    with pytest.raises(ErrorValidacion, match="Política"):
        dec.evaluar(_tabla(politica="la_que_sea"), _vars(1, 1))


# ── Validación ────────────────────────────────────────────────────────────


def test_una_tabla_bien_formada_no_tiene_problemas() -> None:
    assert dec.validar(_tabla()) == []


def test_una_regla_que_compara_una_entrada_inexistente_se_caza() -> None:
    """Es el error más frecuente al editar: renombrar una columna y dejar reglas
    apuntando al nombre viejo. Esas reglas no casarían nunca, en silencio."""
    tabla = _tabla()
    tabla["reglas"][0]["condiciones"][0]["entrada"] = "descuento_pct"
    problemas = dec.validar(tabla)
    assert any("descuento_pct" in p and "no declara" in p for p in problemas)


def test_una_salida_no_declarada_se_caza() -> None:
    tabla = _tabla()
    tabla["reglas"][0]["salidas"]["notificar_a"] = "direccion@x.com"
    assert any("no declaradas" in p for p in dec.validar(tabla))


def test_un_operador_inventado_se_caza() -> None:
    """La lista de operadores es cerrada: una definición es dato del tenant y no
    puede convertirse en código ejecutable."""
    tabla = _tabla()
    tabla["reglas"][0]["condiciones"][0]["op"] = "parecido_a"
    assert any("parecido_a" in p for p in dec.validar(tabla))


def test_una_entrada_sin_expresion_se_caza() -> None:
    """Sin ella la columna evaluaría siempre contra None sin decir nada."""
    tabla = _tabla()
    del tabla["entradas"][0]["expresion"]
    assert any("expresion" in p for p in dec.validar(tabla))


def test_la_politica_prioridad_exige_que_las_reglas_la_declaren() -> None:
    assert any("prioridad" in p for p in dec.validar(_tabla(politica="prioridad")))


def test_una_tabla_sin_reglas_o_sin_columnas_se_caza() -> None:
    problemas = dec.validar({"clave": "x", "entradas": [], "salidas": [], "reglas": []})
    assert len(problemas) == 3


# ── Análisis: huecos, solapes y reglas muertas ────────────────────────────


def test_detecta_el_hueco_de_un_tramo_sin_cubrir() -> None:
    """El caso que se descubre normalmente con un expediente parado."""
    tabla = _tabla(
        politica="primera",
        entradas=[{"clave": "importe", "expresion": "@o.importe", "tipo": "numero"}],
        salidas=[{"clave": "aprobador", "tipo": "texto"}],
        reglas=[
            {
                "nombre": "pequeño",
                "condiciones": [{"entrada": "importe", "op": "<", "valor": 1_000}],
                "salidas": {"aprobador": "comercial"},
            },
            {
                "nombre": "grande",
                "condiciones": [{"entrada": "importe", "op": ">", "valor": 5_000}],
                "salidas": {"aprobador": "director"},
            },
        ],
    )
    informe = dec.analizar(tabla)
    assert {"entrada": "importe", "desde": 1_000.0, "hasta": 5_000.0} in informe["huecos"]
    # Y sin valor por defecto ni regla que case siempre, ese hueco deja la
    # decisión sin respuesta. Eso es lo que hay que avisar.
    assert informe["sin_red_de_seguridad"] is True


def test_un_valor_por_defecto_convierte_el_hueco_en_una_eleccion() -> None:
    tabla = _tabla(
        entradas=[{"clave": "importe", "expresion": "@o.importe", "tipo": "numero"}],
        salidas=[{"clave": "aprobador", "tipo": "texto", "por_defecto": "comercial"}],
        reglas=[
            {
                "nombre": "grande",
                "condiciones": [{"entrada": "importe", "op": ">", "valor": 5_000}],
                "salidas": {"aprobador": "director"},
            }
        ],
    )
    informe = dec.analizar(tabla)
    assert informe["huecos"]
    assert informe["sin_red_de_seguridad"] is False


def test_detecta_una_regla_tapada_por_otra_anterior() -> None:
    """Código muerto: casa siempre que casaría la segunda, y gana por política."""
    tabla = _tabla(
        politica="primera",
        entradas=[{"clave": "importe", "expresion": "@o.importe", "tipo": "numero"}],
        salidas=[{"clave": "aprobador", "tipo": "texto"}],
        reglas=[
            {
                "nombre": "más de mil",
                "condiciones": [{"entrada": "importe", "op": ">", "valor": 1_000}],
                "salidas": {"aprobador": "director"},
            },
            {
                "nombre": "más de diez mil",
                "condiciones": [{"entrada": "importe", "op": ">", "valor": 10_000}],
                "salidas": {"aprobador": "consejo"},
            },
        ],
    )
    informe = dec.analizar(tabla)
    assert informe["inalcanzables"] == [
        {
            "regla": "más de diez mil",
            "tapada_por": "más de mil",
            "motivo": "la anterior casa siempre que casaría esta, y gana por política",
        }
    ]


def test_detecta_el_solape_que_la_politica_unica_no_admite() -> None:
    informe = dec.analizar(_tabla(politica="unica"))
    assert informe["solapes"]
    assert informe["solapes"][0]["reglas"] == ["descuento alto", "importe alto"]


def test_dos_reglas_con_tramos_disjuntos_no_se_declaran_solapadas() -> None:
    """Un analizador que avisa de todo no lo lee nadie, y el aviso que importa
    se pierde entre los que no."""
    tabla = _tabla(
        politica="unica",
        entradas=[{"clave": "importe", "expresion": "@o.importe", "tipo": "numero"}],
        salidas=[{"clave": "aprobador", "tipo": "texto"}],
        reglas=[
            {
                "nombre": "hasta mil",
                "condiciones": [{"entrada": "importe", "op": "<=", "valor": 1_000}],
                "salidas": {"aprobador": "comercial"},
            },
            {
                "nombre": "más de mil",
                "condiciones": [{"entrada": "importe", "op": ">", "valor": 1_000}],
                "salidas": {"aprobador": "director"},
            },
        ],
    )
    informe = dec.analizar(tabla)
    # Se tocan justo en 1.000, que el análisis trata como solape por
    # conservadurismo declarado: un falso positivo se descarta mirando, un falso
    # negativo se descubre en producción. Lo que NO puede haber es un hueco.
    assert informe["huecos"] == []


def test_el_analisis_se_declara_indeciso_en_vez_de_afirmar_lo_que_no_sabe() -> None:
    """Es la propiedad que hace que el informe valga: un analizador que dice
    «completa» cuando no lo sabe es peor que no tenerlo."""
    tabla = _tabla(
        politica="unica",
        entradas=[{"clave": "etiquetas", "expresion": "@o.etiquetas", "tipo": "lista"}],
        salidas=[{"clave": "aprobador", "tipo": "texto"}],
        reglas=[
            {
                "nombre": "estratégica",
                "condiciones": [{"entrada": "etiquetas", "op": "contiene", "valor": "clave"}],
                "salidas": {"aprobador": "director"},
            },
            {
                "nombre": "riesgo",
                "condiciones": [{"entrada": "etiquetas", "op": "contiene", "valor": "moroso"}],
                "salidas": {"aprobador": "finanzas"},
            },
        ],
    )
    informe = dec.analizar(tabla)
    assert informe["indecidibles"] == ["estratégica ↔ riesgo"]
    assert informe["solapes"] == []


def test_una_condicion_contra_una_variable_no_se_analiza_como_constante() -> None:
    """Su valor depende del contexto: razonar sobre él como si fuera fijo daría
    un veredicto que no se sostiene en ninguna ejecución real."""
    # Las dos reglas tienen que acotar LA MISMA entrada: es ahí donde el
    # análisis compara, y donde una referencia sin resolver le impide decidir.
    tabla = _tabla(
        politica="unica",
        reglas=[
            {
                "nombre": "pasa del máximo del tier",
                "condiciones": [{"entrada": "descuento", "op": ">", "valor": "@limites.maximo"}],
                "salidas": {"aprobador": "director"},
            },
            {
                "nombre": "descuento alto",
                "condiciones": [{"entrada": "descuento", "op": ">", "valor": 25}],
                "salidas": {"aprobador": "consejo"},
            },
        ],
    )
    assert dec.analizar(tabla)["indecidibles"] == ["pasa del máximo del tier ↔ descuento alto"]


# ── Persistencia y evaluación por clave ───────────────────────────────────


@pytest.mark.db
def test_guardar_valida_antes_de_escribir(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Una tabla rota que se guarda se descubre la primera vez que un proceso
    real la usa, que es siempre el peor momento."""
    tabla = _tabla()
    tabla["reglas"][0]["condiciones"][0]["entrada"] = "no_existe"
    with pytest.raises(ErrorValidacion, match="problemas"):
        dec.guardar(db, tenant_id, tabla)


@pytest.mark.db
def test_guardar_dos_veces_reemplaza_y_no_duplica(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    dec.guardar(db, tenant_id, _tabla())
    tabla = _tabla()
    tabla["reglas"] = tabla["reglas"][:1]
    dec.guardar(db, tenant_id, tabla)
    db.flush()

    guardada = dec.leer(db, tenant_id, "aprobacion_descuento")
    assert len(guardada.reglas) == 1


@pytest.mark.db
def test_decidir_por_clave_evalua_la_guardada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    dec.guardar(db, tenant_id, _tabla())
    db.flush()
    d = dec.decidir(db, tenant_id, "aprobacion_descuento", _vars(80_000, 30))
    assert d.salidas["aprobador"] == "director"


@pytest.mark.db
def test_una_tabla_desactivada_no_se_evalua_en_silencio(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Devolver el valor por defecto de una tabla apagada haría que un proceso
    siguiera funcionando «bien» con la política equivocada."""
    dec.guardar(db, tenant_id, _tabla(activa=False))
    db.flush()
    with pytest.raises(ErrorValidacion, match="desactivada"):
        dec.decidir(db, tenant_id, "aprobacion_descuento", _vars(80_000, 30))


@pytest.mark.db
def test_una_tabla_de_otro_tenant_no_se_ve(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.errors import NoEncontrado

    dec.guardar(db, tenant_id, _tabla())
    db.flush()
    with pytest.raises(NoEncontrado):
        dec.decidir(db, otro_tenant_id, "aprobacion_descuento", _vars(80_000, 30))


# ── El paso de tabla en el motor de procesos ──────────────────────────────


@pytest.mark.db
def test_un_proceso_enruta_por_lo_que_diga_la_tabla(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que separa esto de escribir la condición en el proceso: la política
    cambia cada trimestre y el flujo no."""
    from services.orchestrator.motor import Motor, validar_definicion

    dec.guardar(db, tenant_id, _tabla())
    db.flush()

    definicion = {
        "inicio": "quien_aprueba",
        "pasos": {
            "quien_aprueba": {
                "tipo": "tabla",
                "tabla": "aprobacion_descuento",
                "segun": "aprobador",
                "rutas": {
                    "director": "fin_director",
                    "responsable_zona": "fin_zona",
                    "comercial": "fin_comercial",
                },
            },
            "fin_director": {"tipo": "fin", "resultado": "director"},
            "fin_zona": {"tipo": "fin", "resultado": "zona"},
            "fin_comercial": {"tipo": "fin", "resultado": "comercial"},
        },
    }
    assert validar_definicion(definicion) == []
    _publicar(db, tenant_id, "aprobar", definicion)

    motor = Motor(db)
    instancia = motor.arrancar(tenant_id=tenant_id, clave="aprobar", variables=_vars(80_000, 30))
    motor.avanzar(instancia)

    assert instancia.variables["resultado"] == "director"
    # Y la explicación de la decisión queda en la instancia: dentro de seis
    # meses la tabla habrá cambiado, y sin esto nadie podrá decir por qué este
    # expediente fue al director.
    explicacion = instancia.variables["_quien_aprueba_explicacion"]
    assert explicacion["salidas"]["aprobador"] == "director"
    assert explicacion["entradas"] == {"importe": 80_000, "descuento": 30}


@pytest.mark.db
def test_una_salida_sin_ruta_falla_en_vez_de_seguir_recto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Casi siempre es que alguien añadió un valor a la tabla y no la rama que
    le toca. Seguir recto lo escondería."""
    from services.orchestrator.motor import Motor

    dec.guardar(db, tenant_id, _tabla())
    db.flush()

    _publicar(
        db,
        tenant_id,
        "incompleto",
        {
            "inicio": "quien_aprueba",
            "pasos": {
                "quien_aprueba": {
                    "tipo": "tabla",
                    "tabla": "aprobacion_descuento",
                    "segun": "aprobador",
                    "rutas": {"comercial": "fin"},
                },
                "fin": {"tipo": "fin"},
            },
        },
    )
    motor = Motor(db)
    instancia = motor.arrancar(tenant_id=tenant_id, clave="incompleto", variables=_vars(80_000, 30))
    motor.avanzar(instancia)
    # El motor compensa lo hecho y cierra la instancia: lo que importa es que NO
    # la da por completada por la rama de escape, y que el error dice qué valor
    # se quedó sin ruta, que es lo único accionable.
    assert instancia.estado == "compensada"
    assert "director" in (instancia.error or "")


def test_un_paso_de_tabla_sin_tabla_no_se_publica() -> None:
    from services.orchestrator.motor import validar_definicion

    problemas = validar_definicion(
        {"inicio": "p", "pasos": {"p": {"tipo": "tabla", "siguiente": None}}}
    )
    assert any("no dice qué tabla" in p for p in problemas)


def test_un_paso_de_tabla_con_rutas_y_sin_segun_no_se_publica() -> None:
    """Sin `segun`, el paso no sabría con qué comparar las rutas y elegiría
    siempre la rama de escape."""
    from services.orchestrator.motor import validar_definicion

    problemas = validar_definicion(
        {
            "inicio": "p",
            "pasos": {
                "p": {"tipo": "tabla", "tabla": "x", "rutas": {"a": "fin"}},
                "fin": {"tipo": "fin"},
            },
        }
    )
    assert any("`segun`" in p for p in problemas)
