"""Lo que el 09-11-2026 se medía simulado y se construyó de verdad.

- CRM-09.01.01.08: el SLA del proveedor sale del acuerdo GUARDADO y se compara
  solo con lo que prometen los derechos de servicio que ese proveedor da.
- CRM-03.03.02.07: enviar a firma desde la oportunidad crea el sobre con el
  origen puesto, y la firma completada lleva la oportunidad a la etapa que su
  embudo tenga configurada —sin configurar, sólo se marca—.
- CRM-03.03.02.10: la revisión de renovaciones abre una oportunidad de
  renovación por contrato, enlazada, en el embudo configurado.
- CRM-04.01.01.08 y CRM-04.05.01.02: derivar un caso y anotar el abono, por
  HTTP, que es como los piden sus pantallas.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.fechas import hoy
from starlette.testclient import TestClient

from tests.unit.test_reverificacion_y_mfa_adaptativa import _cabeceras

pytestmark = pytest.mark.db


def _cliente(servicio: str, monkeypatch: Any) -> Any:
    import importlib

    from crmcore.config import get_settings
    from crmcore.tareas import RelevoDeTareas

    async def _no_correr(self: Any) -> None:
        return None

    monkeypatch.setattr(RelevoDeTareas, "correr", _no_correr)
    monkeypatch.setenv("OUTBOX_ENABLED", "false")
    get_settings.cache_clear()
    modulo = importlib.import_module(f"services.{servicio}.main")
    return TestClient(modulo.app)


def _integracion_falsa(monkeypatch: Any, respuestas: dict[tuple[str, str], Any]) -> list[dict]:
    """`invocar` sustituido: devuelve lo plantado por (método, ruta) y apunta
    cada llamada para poder afirmar lo que recibió el otro lado."""
    import crmcore.http.interno as interno

    llamadas: list[dict] = []

    def _falso(**kw: Any) -> dict[str, Any]:
        llamadas.append(kw)
        clave = (kw["metodo"], kw["ruta"])
        if clave not in respuestas:
            return {"estado": 404, "ok": False, "datos": {"detail": "no plantado"}}
        r = respuestas[clave]
        # Una tupla es (código, cuerpo); lo demás es el cuerpo de un 200.
        if isinstance(r, tuple):
            return {"estado": r[0], "ok": r[0] < 400, "datos": r[1]}
        return {"estado": 200, "ok": True, "datos": r}

    monkeypatch.setattr(interno, "invocar", _falso)
    return llamadas


# ── CRM-09.01.01.08 ───────────────────────────────────────────────────────


def test_el_sla_del_proveedor_sale_de_lo_guardado_y_avisa(
    monkeypatch: Any, tenant_id: UUID, db: Any
) -> None:
    from crmcore.config import get_settings

    _integracion_falsa(
        monkeypatch,
        {
            ("GET", "/api/v1/proveedores-servicio"): {
                "items": [
                    {"clave": "tecnicos-sur", "nombre": "Técnicos del Sur", "plazo_horas": 48}
                ]
            }
        },
    )
    cab = _cabeceras(tenant_id)
    try:
        with _cliente("service", monkeypatch) as cli:
            sla = cli.post(
                "/api/v1/sla",
                headers=cab,
                json={
                    "clave": "oro",
                    "nombre": "Oro",
                    "horas_primera_respuesta": 4,
                    "horas_resolucion": 24,
                },
            )
            assert sla.status_code in (200, 201), sla.text
            derecho = cli.post(
                "/api/v1/entitlements",
                headers=cab,
                json={
                    "clave": f"e{uuid4().hex[:6]}",
                    "nombre": "Soporte oro",
                    "sla_clave": "oro",
                    "vigente_desde": str(hoy()),
                },
            )
            assert derecho.status_code == 201, derecho.text
            eid = derecho.json()["id"]

            # Sin proveedor detrás, nada que revisar.
            vacia = cli.get("/api/v1/sla-proveedores/revision", headers=cab)
            assert vacia.status_code == 200, vacia.text
            assert vacia.json()["revisados"] == 0

            asignado = cli.put(
                f"/api/v1/sla-proveedores/entitlements/{eid}/proveedor",
                headers=cab,
                json={"proveedor_clave": "tecnicos-sur"},
            )
            assert asignado.status_code == 200, asignado.text

            # Con el proveedor y sin acuerdo de respuesta: su plazo de
            # integración (48 h) vale como resolución, y no llega a 24.
            r = cli.get("/api/v1/sla-proveedores/revision", headers=cab).json()
            fila = r["filas"][0]
            assert r["integracion_respondio"] is True
            assert fila["del_proveedor"] == {"resolucion_h": 48.0}
            assert fila["veredicto"] == "no_se_sostiene"
            assert fila["sin_declarar"] == ["respuesta_h"]
            assert r["hay_avisos"] is True

            guardado = cli.put(
                "/api/v1/sla-proveedores/acuerdos/tecnicos-sur",
                headers=cab,
                json={"respuesta_h": 2, "resolucion_h": 12},
            )
            assert guardado.status_code == 200, guardado.text
            acuerdos = cli.get("/api/v1/sla-proveedores/acuerdos", headers=cab).json()
            assert [a["proveedor_clave"] for a in acuerdos] == ["tecnicos-sur"]

            # 2 + 1 h nuestra ≤ 4 y 12 + 1 ≤ 24: ahora sí se sostiene.
            r = cli.get("/api/v1/sla-proveedores/revision", headers=cab).json()
            assert r["filas"][0]["veredicto"] == "se_sostiene", r
            assert r["hay_avisos"] is False

            maximo = cli.post(
                "/api/v1/sla-proveedores/maximo-que-se-puede-prometer",
                headers=cab,
                json={"proveedor_clave": "tecnicos-sur", "del_proveedor": {"respuesta_h": 99}},
            )
            assert maximo.status_code == 200, maximo.text
            # Lo guardado manda sobre lo tecleado.
            assert maximo.json()["maximo"]["respuesta_h"] == 3.0

            comparado = cli.post(
                "/api/v1/sla-proveedores/comparar",
                headers=cab,
                json={
                    "prometido_al_cliente": {"respuesta_h": 4},
                    "del_proveedor": {"respuesta_h": 8},
                },
            )
            assert comparado.status_code == 200, comparado.text
            assert comparado.json()["se_sostiene"] is False

            assert (
                cli.delete("/api/v1/sla-proveedores/acuerdos/tecnicos-sur", headers=cab).status_code
                == 204
            )
    finally:
        get_settings.cache_clear()


def test_si_integracion_no_contesta_se_dice(monkeypatch: Any, db: Any, tenant_id: UUID) -> None:
    from services.service import proveedores_sla as psla
    from services.service.entitlements import Entitlement
    from services.service.modelos import DefinicionSLA

    db.add(
        DefinicionSLA(
            tenant_id=tenant_id, clave="plata", nombre="Plata", version=1, horas_primera_respuesta=8
        )
    )
    db.add(
        Entitlement(
            tenant_id=tenant_id,
            clave="e1",
            nombre="Soporte",
            sla_clave="plata",
            proveedor_clave="nadie",
            vigente_desde=hoy(db),
        )
    )
    db.flush()
    salida = psla.revisar(db, tenant_id, proveedores=None)
    assert salida["integracion_respondio"] is False
    fila = salida["filas"][0]
    # No se sabe si existe: no se afirma que no.
    assert fila["proveedor_existe"] is None
    assert fila["veredicto"] == "sin_acuerdo"


# ── CRM-03.03.02.07 ───────────────────────────────────────────────────────


def _embudo_con_dos_etapas(uow: UnidadDeTrabajo) -> tuple[Any, Any, Any]:
    from services.sales.modelos import Etapa, Pipeline

    embudo = Pipeline(tenant_id=uow.tenant_id, clave=f"p{uuid4().hex[:6]}", nombre="Ventas")
    uow.db.add(embudo)
    uow.db.flush()
    abierta = Etapa(
        tenant_id=uow.tenant_id,
        pipeline_id=embudo.id,
        clave="propuesta",
        nombre="Propuesta",
        orden=1,
    )
    firmada = Etapa(
        tenant_id=uow.tenant_id, pipeline_id=embudo.id, clave="firmado", nombre="Firmado", orden=2
    )
    uow.db.add_all([abierta, firmada])
    uow.db.flush()
    return embudo, abierta, firmada


def test_la_firma_completada_mueve_la_etapa_solo_si_el_embudo_lo_dice(
    db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    from crmcore.runtime import settings as rt

    from services.sales import firma_oportunidad as fop
    from services.sales.servicio import crear_oportunidad_nueva

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    embudo, abierta, firmada = _embudo_con_dos_etapas(uow)
    op = crear_oportunidad_nueva(
        uow, nombre="Licencias", pipeline_id=embudo.id, etapa_id=abierta.id
    )

    # Sin configurar: sólo se marca, como antes.
    salida = fop.aplicar_estado(uow, op, estado="completed", sobre_id="s-1")
    assert salida == {"estado": "completado", "etapa_movida_a": None}
    assert op.etapa_id == abierta.id
    assert op.campos["firma_estado"] == "completado"

    real = rt.efectivo

    def _efectivo(clave: str, *a: Any, **k: Any) -> Any:
        if clave == "firma_etapa_por_embudo":
            return {embudo.clave: "firmado"}
        if clave == "exigir_criterios_salida":
            return False
        return real(clave, *a, **k)

    monkeypatch.setattr(rt, "efectivo", _efectivo)
    salida = fop.aplicar_estado(uow, op, estado="completed", sobre_id="s-2")
    assert salida["etapa_movida_a"] == "Firmado"
    assert op.etapa_id == firmada.id
    # Y una vez por sobre: el evento repetido no la vuelve a mover.
    assert fop.aplicar_estado(uow, op, estado="completed", sobre_id="s-2")["etapa_movida_a"] is None


def test_enviar_a_firma_desde_la_oportunidad_por_http(
    monkeypatch: Any, tenant_id: UUID, db: Any
) -> None:
    from crmcore.config import get_settings

    llamadas = _integracion_falsa(
        monkeypatch,
        {
            ("POST", "/api/v1/firma/sobres"): (
                201,
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "referencia": "FIR-1",
                    "estado": "borrador",
                },
            ),
            ("POST", "/api/v1/firma/sobres/11111111-1111-1111-1111-111111111111/enviar"): {
                "estado": "enviado"
            },
            ("GET", "/api/v1/firma/sobres/11111111-1111-1111-1111-111111111111/evidencia"): {
                "estado": "completado"
            },
        },
    )
    cab = _cabeceras(tenant_id)
    try:
        with _cliente("sales", monkeypatch) as cli:
            embudo = cli.post(
                "/api/v1/pipelines",
                headers=cab,
                json={"clave": f"p{uuid4().hex[:8]}", "nombre": "Ventas", "por_defecto": True},
            ).json()
            cli.post(
                f"/api/v1/pipelines/{embudo['id']}/etapas",
                headers=cab,
                json={"clave": "nueva", "nombre": "Nueva", "orden": 1, "probabilidad": 10},
            )
            oid = cli.post(
                "/api/v1/opportunities", headers=cab, json={"nombre": "Firma", "importe": "100"}
            ).json()["id"]

            # Sin presupuesto no hay nada que firmar, y se dice.
            sin = cli.post(
                f"/api/v1/opportunities/{oid}/enviar-a-firma",
                headers=cab,
                json={"firmantes": [{"nombre": "Ana", "email": "ana@ejemplo.es"}]},
            )
            assert sin.status_code == 422, sin.text
            assert "presupuesto" in sin.text

            pre = cli.post(
                "/api/v1/presupuestos",
                headers=cab,
                json={
                    "oportunidad_id": oid,
                    "lineas": [
                        {"descripcion": "Licencia", "cantidad": 1, "precio_unitario": "100"}
                    ],
                },
            )
            assert pre.status_code in (200, 201), pre.text

            enviado = cli.post(
                f"/api/v1/opportunities/{oid}/enviar-a-firma",
                headers=cab,
                json={"firmantes": [{"nombre": "Ana", "email": "ana@ejemplo.es"}]},
            )
            assert enviado.status_code == 201, enviado.text
            assert enviado.json()["estado"] == "enviado"
            creado = next(c for c in llamadas if c["ruta"] == "/api/v1/firma/sobres")
            assert creado["cuerpo"]["objeto_origen"] == "oportunidad"
            assert creado["cuerpo"]["objeto_origen_id"] == oid
            assert creado["cuerpo"]["documento_id"].startswith("presupuesto:")

            # La ficha pregunta al sobre: completado, y sin etapa configurada
            # sólo se marca.
            firma = cli.get(f"/api/v1/opportunities/{oid}/firma", headers=cab)
            assert firma.status_code == 200, firma.text
            assert firma.json()["estado"] == "completado"
            assert firma.json()["consultado"] is True
            assert firma.json()["etapa_tras_firma"] is None
    finally:
        get_settings.cache_clear()


# ── CRM-03.03.02.10 ───────────────────────────────────────────────────────


def test_un_contrato_en_preaviso_abre_una_renovacion_enlazada_una_vez(
    db: Any, tenant_id: UUID
) -> None:
    from services.sales import presupuestos as pre
    from services.sales.modelos import Oportunidad

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    embudo, _, _ = _embudo_con_dos_etapas(uow)
    embudo.por_defecto = True
    db.flush()
    dia = hoy(db)
    contrato = pre.crear_contrato(
        uow,
        cuenta_id=uuid4(),
        inicio=dia - timedelta(days=300),
        fin=dia + timedelta(days=10),
        importe=Decimal("1200"),
        titulo="Mantenimiento",
        preaviso_dias=30,
    )
    salida = pre.revisar_renovaciones(uow, tenant_id)
    assert len(salida["oportunidades"]) == 1
    op = db.get(Oportunidad, UUID(salida["oportunidades"][0]["oportunidad_id"]))
    assert op.importe == Decimal("1200")
    assert op.pipeline_id == embudo.id
    assert op.fecha_cierre == contrato.fin
    assert op.campos["renovacion_de_contrato_id"] == str(contrato.id)
    assert contrato.oportunidad_renovacion_id == op.id

    # La revisión corre cada hora: la segunda pasada no abre otra.
    assert pre.revisar_renovaciones(uow, tenant_id)["oportunidades"] == []


def test_un_embudo_de_renovaciones_que_no_existe_se_dice(
    db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    from crmcore.runtime import settings as rt

    from services.sales import presupuestos as pre

    real = rt.efectivo
    monkeypatch.setattr(
        rt,
        "efectivo",
        lambda clave, *a, **k: "no-existe"
        if clave == "renovacion_embudo"
        else real(clave, *a, **k),
    )
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    dia = hoy(db)
    pre.crear_contrato(
        uow, cuenta_id=uuid4(), inicio=dia - timedelta(days=30), fin=dia + timedelta(days=5)
    )
    salida = pre.revisar_renovaciones(uow, tenant_id)
    assert salida["oportunidades"] == []
    assert salida["embudo_no_encontrado"] == "no-existe"


def test_la_revision_de_renovaciones_esta_programada() -> None:
    from services.sales.main import _tareas

    assert "sales.renovaciones" in [t.nombre for t in _tareas()]


# ── CRM-04.01.01.08 y CRM-04.05.01.02, por HTTP ──────────────────────────


def test_derivar_un_caso_y_anotar_el_abono_por_http(
    monkeypatch: Any, tenant_id: UUID, db: Any
) -> None:
    from crmcore.config import get_settings

    cab = _cabeceras(tenant_id)
    try:
        with _cliente("service", monkeypatch) as cli:
            cola = cli.post(
                "/api/v1/colas",
                headers=cab,
                json={"clave": "nivel2", "nombre": "Segundo nivel", "nivel": 2},
            )
            assert cola.status_code == 201, cola.text
            caso = cli.post("/api/v1/casos", headers=cab, json={"asunto": "No arranca"})
            assert caso.status_code in (200, 201), caso.text
            cid = caso.json()["id"]

            derivado = cli.post(
                f"/api/v1/escalado/derivar/{cid}",
                headers=cab,
                json={"cola_destino": "nivel2", "motivo": "Revisar firmware", "interno": True},
            )
            assert derivado.status_code == 200, derivado.text
            ficha = cli.get(f"/api/v1/casos/{cid}", headers=cab).json()
            assert ficha["equipo"] == "nivel2"
            assert ficha["campos"]["interno"] is True

            dev = cli.post(
                "/api/v1/devoluciones",
                headers=cab,
                json={
                    "motivo": "llego_roto",
                    "comprado_el": str(hoy()),
                    "lineas": [{"concepto": "Bomba", "cantidad": 1}],
                },
            )
            assert dev.status_code in (200, 201), dev.text
            did = dev.json()["id"]
            assert (
                cli.post(f"/api/v1/devoluciones/{did}/autorizar", headers=cab, json={}).status_code
                == 200
            )
            assert (
                cli.post(f"/api/v1/devoluciones/{did}/recibir", headers=cab, json={}).status_code
                == 200
            )
            res = cli.post(
                f"/api/v1/devoluciones/{did}/resolver",
                headers=cab,
                json={"tipo": "abono", "importe": "120"},
            )
            assert res.status_code == 201, res.text
            detalle = cli.get(f"/api/v1/devoluciones/{did}", headers=cab).json()
            rid = detalle["resoluciones"][0]["id"]
            assert detalle["resoluciones"][0]["estado_abono"] == "solicitado"

            abono = cli.post(
                f"/api/v1/devoluciones/resoluciones/{rid}/abono",
                headers=cab,
                json={"confirmado": True, "referencia": "AB-77"},
            )
            assert abono.status_code == 200, abono.text
            assert abono.json()["estado_abono"] == "confirmado"
    finally:
        get_settings.cache_clear()


def test_borrar_un_caso_no_impide_abrir_el_siguiente(db: Any, tenant_id: UUID) -> None:
    """El código se contaba sin los borrados: borrar uno hacía que el siguiente
    pidiera su código y el alta daba 409 para siempre (medido el 09-11-2026)."""
    from datetime import datetime, timezone

    from services.service import servicio as svc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    primero = svc.abrir_caso(uow, asunto="Uno")
    segundo = svc.abrir_caso(uow, asunto="Dos")
    segundo.deleted_at = datetime.now(timezone.utc)
    db.flush()
    tercero = svc.abrir_caso(uow, asunto="Tres")
    assert len({primero.codigo, segundo.codigo, tercero.codigo}) == 3
