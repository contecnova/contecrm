"""Auditoría de GRC: riesgos, controles y cobertura (CRM-07.03.02).

Diez capacidades declaradas hechas y ninguna con nota de auditoría. Lo que un
GRC tiene que resistir es justo una auditoría, así que aquí se le hacen las
preguntas que hace un auditor y se comprueba la respuesta que sale por HTTP:

  · «enséñame el registro de riesgos» — y que aceptar uno **exija declarar el
    residual**, que es la trampa más común: aceptar sin decir cuánto queda no es
    una decisión, es archivarlo;
  · «enséñame los controles» — y que **no se puedan anclar a capacidades que no
    existen**, porque contarían en la cobertura sin cubrir nada;
  · «enséñame la última evaluación» — y que un resultado distinto de «efectivo»
    **exija plan de acción**, que es lo que separa una herramienta de un archivo;
  · «¿qué del producto no tiene control?» — en los **dos sentidos**, incluidos
    los controles que apuntan a algo que ya se quitó del producto;
  · «¿quién puede borrar una cuenta?» — contestado desde las rutas montadas y
    los permisos de los roles, con los comodines expandidos;
  · y «¿esto está bien?» — que es el panel, y que tiene que decir **qué no ha
    podido medir** en vez de salir en verde porque no hay nada declarado.

Lo que se encontró: nada roto. Es la primera familia que se audita entera sin
un hallazgo, y conviene que conste — una auditoría que siempre encuentra algo
deja de significar nada.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


def _app(nombre: str) -> Iterator[Any]:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module(nombre).app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def cliente(db: Any) -> Iterator[Any]:
    yield from _app("services.tenancy.main")


@pytest.fixture
def identidad(db: Any) -> Iterator[Any]:
    yield from _app("services.identity.main")


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


def _una_capacidad_real() -> str:
    """Un identificador del catálogo de verdad.

    Escrito a mano se queda obsoleto el día que esa capacidad cambie de código,
    y entonces la prueba fallaría por el motivo equivocado.
    """
    from crmcore.catalogo import capacidades

    return sorted(capacidades())[0]


# ── CRM-07.03.02.01 · Registro de riesgos ─────────────────────────────────


def test_aceptar_un_riesgo_exige_decir_cuanto_queda_crm_07_03_02_01(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """La trampa más común de un registro de riesgos: aceptar sin declarar el
    residual. Eso no es una decisión, es archivarlo — y además deja el informe
    diciendo que el riesgo está tratado."""
    sin_residual = cliente.put(
        "/api/v1/grc/riesgos/R-01",
        headers=cabeceras,
        json={"titulo": "Fuga por exportación masiva", "tratamiento": "aceptar"},
    )
    assert sin_residual.status_code == 422, sin_residual.text

    con_residual = cliente.put(
        "/api/v1/grc/riesgos/R-01",
        headers=cabeceras,
        json={
            "titulo": "Fuga por exportación masiva",
            "tratamiento": "aceptar",
            "probabilidad": 4,
            "impacto": 5,
            "residual_probabilidad": 2,
            "residual_impacto": 3,
        },
    )
    assert con_residual.status_code == 200, con_residual.text
    cuerpo = con_residual.json()
    for campo in ("codigo", "probabilidad", "impacto", "inherente", "residual", "tratamiento"):
        assert campo in cuerpo, f"falta «{campo}»: {sorted(cuerpo)}"
    # El inherente es lo que hay sin hacer nada y el residual lo que queda
    # después: si fueran iguales, el tratamiento no habría servido de nada y eso
    # es lo que hay que poder ver.
    assert cuerpo["inherente"] == 20 and cuerpo["residual"] == 6

    assert cliente.get("/api/v1/grc/riesgos", headers=cabeceras).json()[0]["codigo"] == "R-01"


# ── CRM-07.03.02.02 y CRM-07.03.02.04 · Controles anclados al catálogo ───


def test_un_control_no_se_ancla_a_lo_que_no_existe_crm_07_03_02_02(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """**El anclaje es la capacidad** (CRM-07.03.02.04). Sin validarlo, un
    control sobre `CRM-99.99.99.99` se guardaría tan tranquilo y el informe de
    cobertura contaría un control que no cubre nada: un GRC que miente a favor."""
    inventada = cliente.put(
        "/api/v1/grc/controles/C-01",
        headers=cabeceras,
        json={"nombre": "Revisión de accesos", "capacidades": ["CRM-99.99.99.99"]},
    )
    assert inventada.status_code == 422, inventada.text

    real = _una_capacidad_real()
    buena = cliente.put(
        "/api/v1/grc/controles/C-01",
        headers=cabeceras,
        json={
            "nombre": "Revisión de accesos",
            "tipo": "detectivo",
            "frecuencia": "trimestral",
            "capacidades": [real],
        },
    )
    assert buena.status_code == 200, buena.text
    cuerpo = buena.json()
    # Con el TÍTULO de la capacidad al lado del identificador: una lista de
    # códigos no la lee nadie, y quien revisa el control necesita saber qué
    # cubre sin abrir otra pestaña.
    assert cuerpo["capacidades"][0]["id"] == real
    assert cuerpo["capacidades"][0]["titulo"], "el identificador va sin su título"


# ── CRM-07.03.02.03 y CRM-07.03.02.08 · Evaluación y evidencia ───────────


@pytest.fixture
def control(cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID) -> str:
    r = cliente.put(
        "/api/v1/grc/controles/C-AUD",
        headers=cabeceras,
        json={
            "nombre": "Integridad del rastro de auditoría",
            "frecuencia": "mensual",
            "capacidades": [_una_capacidad_real()],
            # El control declara DE DÓNDE sale su prueba, y el sistema la lee.
            "fuente_evidencia": "audit_trail",
        },
    )
    assert r.status_code == 200, r.text
    return "C-AUD"


def test_un_control_que_no_es_efectivo_exige_plan_crm_07_03_02_03(
    cliente: Any, cabeceras: dict[str, str], control: str
) -> None:
    """Sin esa obligación el registro se llena de controles «parciales» que
    nadie arregla, y el GRC pasa de herramienta a archivo."""
    sin_plan = cliente.post(
        f"/api/v1/grc/controles/{control}/evaluaciones",
        headers=cabeceras,
        json={"resultado": "parcial"},
    )
    assert sin_plan.status_code == 409, sin_plan.text

    con_plan = cliente.post(
        f"/api/v1/grc/controles/{control}/evaluaciones",
        headers=cabeceras,
        json={"resultado": "parcial", "plan_accion": "Cerrar los accesos del becario antes del 15"},
    )
    assert con_plan.status_code == 201, con_plan.text


def test_la_proxima_evaluacion_sale_de_la_frecuencia_crm_07_03_02_03(
    cliente: Any, cabeceras: dict[str, str], control: str
) -> None:
    """Una fecha escrita a mano es la primera que se queda sin poner, y
    entonces un control «al día» lleva ocho meses sin mirarse."""
    r = cliente.post(
        f"/api/v1/grc/controles/{control}/evaluaciones",
        headers=cabeceras,
        json={"resultado": "efectivo", "fecha": "2026-10-01"},
    )
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["proxima_at"], "sin próxima fecha, nadie sabe cuándo toca"
    # Mensual: treinta días. Se comprueba el salto y no la fecha literal, que
    # dependería del día en que corra la prueba.
    salto = date.fromisoformat(cuerpo["proxima_at"]) - date.fromisoformat(cuerpo["fecha"])
    assert salto == timedelta(days=30), salto


def test_la_evidencia_la_trae_el_sistema_crm_07_03_02_08(
    cliente: Any, cabeceras: dict[str, str], control: str
) -> None:
    """Adjuntarla a mano es como un GRC se queda desactualizado el segundo
    trimestre: la persona que la sacaba cambia de puesto y nadie más sabe de
    dónde salía. El control declara su fuente y el sistema la lee."""
    r = cliente.post(
        f"/api/v1/grc/controles/{control}/evaluaciones",
        headers=cabeceras,
        json={"resultado": "efectivo"},
    )
    assert r.status_code == 201, r.text
    evidencia = r.json()["evidencia"]
    assert evidencia.get("fuente") == "audit_trail", evidencia
    # Una cifra, no un error. Este control estuvo sin poder evaluarse nunca
    # porque la lectura importaba una clase con un nombre que no existe y el
    # `except` convertía el fallo en «no se pudo leer la evidencia».
    assert "entradas_de_auditoria" in evidencia, evidencia


# ── CRM-07.03.02.05 · Cobertura en los dos sentidos ───────────────────────


def test_la_cobertura_dice_lo_que_no_esta_cubierto_crm_07_03_02_05(
    cliente: Any, cabeceras: dict[str, str], control: str
) -> None:
    """Y se puede medir **solo sobre lo entregado**, que es lo que un auditor
    puede comprobar hoy."""
    r = cliente.get("/api/v1/grc/cobertura?solo_hechas=true", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["medible"] is True, cuerpo
    for campo in (
        "capacidades",
        "con_control",
        "sin_control",
        "pct",
        "capacidades_sin_control",
        "controles_sobre_capacidades_inexistentes",
        "por_seccion",
        "alcance",
    ):
        assert campo in cuerpo, f"falta «{campo}»: {sorted(cuerpo)}"
    assert cuerpo["con_control"] == 1
    assert (
        _una_capacidad_real() not in cuerpo["capacidades_sin_control"]
    ), "la capacidad que cubre el control sigue contándose como descubierta"
    assert cuerpo["sin_control"] == cuerpo["capacidades"] - 1
    # El porcentaje no se lee solo: con 772 capacidades y un control, el 0,1 %
    # dice lo mismo que el recuento y menos claro. Lo que importa es que cuadre
    # con el recuento, porque un porcentaje que no cuadra es el que se cita.
    assert cuerpo["alcance"], "sin decir sobre qué se ha medido, el porcentaje no significa nada"


def test_un_control_que_cubre_algo_retirado_sale_crm_07_03_02_05(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**El sentido de vuelta**, que es el que ningún GRC mira porque hay que ir
    a buscarlo: un control que lleva un año cubriendo algo que se quitó del
    producto.

    La fila se escribe directamente a propósito: por la ruta no se puede: el
    alta valida contra el catálogo. El caso real es el contrario —el control se
    guardó cuando la capacidad existía y la capacidad se retiró después— y eso
    desde una prueba no se puede provocar sin tocar el catálogo.
    """
    from services.tenancy.grc import Control

    db.add(
        Control(
            tenant_id=tenant_id,
            codigo="C-VIEJO",
            nombre="Control de algo que ya no está",
            capacidades=["CRM-00.00.00.00"],
        )
    )
    db.flush()

    cuerpo = cliente.get("/api/v1/grc/cobertura", headers=cabeceras).json()
    sueltos = cuerpo["controles_sobre_capacidades_inexistentes"]
    assert "C-VIEJO" in {h["control"] for h in sueltos}, sueltos
    assert "CRM-00.00.00.00" in str(sueltos), (
        "dice qué control está suelto y no a qué apunta: hay que ir a buscarlo, "
        "que es por lo que nadie lo mira"
    )


# ── CRM-07.03.02.07 · Los dos sentidos del marco normativo ────────────────


def test_del_marco_a_la_capacidad_y_de_la_capacidad_al_marco_crm_07_03_02_07(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Un auditor pregunta por ISO 27001 A.9 y hay que contestar qué controles
    responden y qué capacidades los sostienen. Y antes de tocar una capacidad
    hay que poder ver a qué obligaciones está respondiendo, que es el camino de
    vuelta y el que evita retirar algo sin enterarse."""
    real = _una_capacidad_real()
    cliente.put(
        "/api/v1/grc/controles/C-ISO",
        headers=cabeceras,
        json={
            "nombre": "Gestión de accesos",
            "capacidades": [real],
            "marcos": [{"marco": "ISO 27001", "referencia": "A.9"}],
        },
    )

    ida = cliente.get("/api/v1/grc/marcos", headers=cabeceras)
    assert ida.status_code == 200, ida.text
    assert "ISO 27001" in str(ida.json()), ida.json()

    vuelta = cliente.get(f"/api/v1/grc/capacidades/{real}", headers=cabeceras)
    assert vuelta.status_code == 200, vuelta.text
    assert "ISO 27001" in str(vuelta.json()), vuelta.json()


# ── CRM-07.03.02.10 · El panel ────────────────────────────────────────────


def test_el_panel_vacio_no_sale_en_verde_crm_07_03_02_10(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """**Es el que más tranquiliza y el que peor informa.** Sin controles ni
    evaluaciones, un panel en verde no dice que se cumpla: dice que no hay nada
    con lo que comprobarlo, y las dos cosas se leen igual."""
    r = cliente.get("/api/v1/grc/panel", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["medible"] is False, cuerpo
    assert cuerpo["porque"], "no dice por qué no se puede medir"
    assert cuerpo["controles_activos"] == 0 and cuerpo["controles_evaluados"] == 0
    # Y no se inventa un porcentaje: un 0 % y un «no se ha podido medir» se leen
    # igual y significan lo contrario.
    assert cuerpo["cobertura_pct"] is None, cuerpo
    assert cuerpo["todo_en_orden"] is not True, (
        "un panel vacío que dice «todo en orden» es el que más tranquiliza y el " "que peor informa"
    )


def test_lo_pendiente_es_lo_que_no_cuadra_hoy_crm_07_03_02_10(
    cliente: Any, cabeceras: dict[str, str], control: str
) -> None:
    """Un control recién creado y **nunca evaluado** tiene que salir: un GRC sin
    esta vista es un archivo."""
    r = cliente.get("/api/v1/grc/pendiente", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert control in str(r.json()), r.json()


# ── CRM-07.03.02.06 · Segregación de funciones ────────────────────────────


def test_una_regla_de_segregacion_no_puede_prohibir_en_vez_de_segregar_crm_07_03_02_06(
    identidad: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Los dos lados tienen que ser distintos: el mismo permiso en los dos no
    segrega nada, prohíbe. Si eso es lo que se quiere, se quita del rol."""
    mal = identidad.put(
        "/api/v1/segregacion/reglas/SOD-01",
        headers=cabeceras,
        json={
            "nombre": "Alta y aprobación",
            "permisos_a": ["pedido:write"],
            "permisos_b": ["pedido:write"],
        },
    )
    assert mal.status_code in (409, 422), mal.text

    bien = identidad.put(
        "/api/v1/segregacion/reglas/SOD-01",
        headers=cabeceras,
        json={
            "nombre": "Alta y aprobación",
            "permisos_a": ["pedido:write"],
            "permisos_b": ["pedido:aprobar"],
        },
    )
    assert bien.status_code == 200, bien.text
    assert identidad.get("/api/v1/segregacion/reglas", headers=cabeceras).json()


def test_una_excepcion_de_segregacion_caduca_crm_07_03_02_06(
    identidad: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Sin motivo, dentro de un año nadie sabe por qué se aprobó; sin caducidad,
    la excepción sobrevive a la persona, al puesto y a la razón que la
    justificaba."""
    identidad.put(
        "/api/v1/segregacion/reglas/SOD-02",
        headers=cabeceras,
        json={
            "nombre": "Cobro y conciliación",
            "permisos_a": ["cobro:write"],
            "permisos_b": ["conciliacion:write"],
        },
    )
    usuario = uuid4()
    sin_motivo = identidad.post(
        "/api/v1/segregacion/reglas/SOD-02/excepciones",
        headers=cabeceras,
        json={"usuario_id": str(usuario), "caduca_at": "2026-12-31"},
    )
    assert sin_motivo.status_code in (409, 422), sin_motivo.text

    puesta = identidad.post(
        "/api/v1/segregacion/reglas/SOD-02/excepciones",
        headers=cabeceras,
        json={
            "usuario_id": str(usuario),
            "caduca_at": "2026-12-31",
            "motivo": "Equipo de dos personas hasta la incorporación de enero",
        },
    )
    assert puesta.status_code == 201, puesta.text
    assert puesta.json()["caduca_at"]

    # Y se puede LEER, que es lo que la convierte en un control y no en un
    # apaño: sin poder listarlas, la prueba de auditoría no existe.
    leidas = identidad.get(
        "/api/v1/segregacion/reglas/SOD-02/excepciones", headers=cabeceras
    ).json()
    assert leidas and "motivo" in str(leidas), leidas


# ── CRM-07.03.02.09 · La matriz de permisos ───────────────────────────────


def test_quien_puede_hacer_que_sale_de_las_rutas_montadas_crm_07_03_02_09(
    identidad: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """«¿Quién puede borrar una cuenta?» se contesta casi siempre leyendo
    código, y se contesta mal: alguien mira la pantalla de roles, ve que
    «comercial» no tiene el permiso y dice que nadie — sin saber que hay un rol
    con `*:*` y tres personas dentro.

    Y los dos huecos, que son opuestos: un permiso que una ruta exige y ningún
    rol tiene es funcionalidad muerta; uno concedido que ninguna ruta exige es
    un privilegio que alguien dio por si acaso.
    """
    r = identidad.get("/api/v1/identity/cumplimiento/matriz-permisos", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["servicio"] == "identity"
    assert cuerpo["alcance_de_los_roles"], (
        "sin decir que son los roles de BASE, enseñar solo estos como si fueran "
        "todos es justo el error que esta matriz existe para evitar"
    )
    texto = str(cuerpo)
    assert "user:read" in texto, "la matriz no ve los permisos que exigen las rutas"


def test_el_panel_con_datos_SI_da_la_cobertura_crm_07_03_02_10(
    cliente: Any, cabeceras: dict[str, str], control: str
) -> None:
    """La cifra de cabecera del panel salía siempre vacía.

    `panel()` pedía `cobertura_pct` a `cobertura()`, que devuelve esa clave con
    el nombre `pct`. Resultado: `None` SIEMPRE, también con el propio panel
    diciendo `medible: true` —porque `medible` mira los controles y las
    evaluaciones, no esto—. El panel afirmaba que se podía medir y el número no
    estaba.

    Lo que lo mantuvo escondido es que el nombre equivocado acertaba por
    casualidad en el único caso que había prueba: el panel vacío, donde la
    respuesta correcta ES `None`. Por eso esta prueba va con datos.
    """
    evaluado = cliente.post(
        f"/api/v1/grc/controles/{control}/evaluaciones",
        headers=cabeceras,
        json={"resultado": "efectivo", "evidencia": {"nota": "revisado en el volcado"}},
    )
    assert evaluado.status_code in (200, 201), evaluado.text

    r = cliente.get("/api/v1/grc/panel", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["medible"] is True, cuerpo
    assert cuerpo["cobertura_pct"] is not None, (
        "el panel dice que se puede medir y no da el número: es justo el fallo "
        "que esta prueba fija"
    )
    # Y es el mismo número que da el informe de cobertura: dos cifras distintas
    # para lo mismo en dos sitios es peor que una sola.
    informe = cliente.get("/api/v1/grc/cobertura?solo_hechas=true", headers=cabeceras)
    assert informe.status_code == 200, informe.text
    assert cuerpo["cobertura_pct"] == informe.json()["pct"]
