"""Deduplicar un lead en el momento en que entra (CRM-01.01.03.03).

Lo que se defiende:

* El alta manual responde **409 con los candidatos** cuando lo que entra ya
  está —mismo correo, mismo teléfono escrito de otra forma, o empresa y nombre
  casi iguales—, y `forzar` lo crea igual dejándolo auditado.
* Se mira también **entre los contactos del maestro**, por HTTP; y si `party`
  no contesta el alta **no se cae** y se dice que no se miró.
* La captura automática no pregunta: **marca** el lead nuevo como posible
  duplicado o **fusiona** lo que llega en el que ya había, sin perder nada.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import Conflicto, NoDisponible

from services.sales import captura, dedupe_leads
from services.sales import servicio as svc
from services.sales.modelos import Lead


class _Uow:
    def __init__(self, db: Any, tenant_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.emitidos: list[dict[str, Any]] = []

    def emitir(self, tipo: str, *, subject: Any, data: Any, **extra: Any) -> None:
        self.emitidos.append({"tipo": tipo, "data": data})


@pytest.fixture
def sin_party(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """`party` no contesta: la consulta a los contactos se apunta y falla."""
    llamadas: list[dict[str, Any]] = []

    def invocar(**kwargs: Any) -> dict[str, Any]:
        llamadas.append(kwargs)
        raise NoDisponible("sin party", error_code="interno.servicio_no_responde")

    monkeypatch.setattr("crmcore.http.interno.invocar", invocar)
    return llamadas


@pytest.mark.db
def test_el_mismo_correo_responde_409_con_el_candidato(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, sin_party: list[dict[str, Any]]
) -> None:
    uow = _Uow(db, tenant_id)
    primero = svc.crear_lead(uow, nombre="Ana", email="ana@acme.test")

    with pytest.raises(Conflicto) as exc:
        svc.crear_lead(uow, nombre="Ana P.", email="ANA@acme.test ")

    detalle = exc.value.detalle
    assert exc.value.error_code == "sales.lead_duplicado"
    assert detalle["candidatos"][0]["id"] == str(primero.id)
    assert detalle["candidatos"][0]["objeto"] == "lead"
    assert "email" in detalle["candidatos"][0]["senales"]
    assert "forzar" in detalle["como_continuar"]
    # Y dice que no pudo mirar los contactos: un «no hay» sobre la mitad de las
    # fuentes no es lo mismo que uno sobre las dos.
    assert detalle["contactos_consultados"] is False
    assert sin_party, "ni siquiera intentó preguntar a los contactos"


@pytest.mark.db
def test_forzar_lo_crea_y_queda_auditado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, sin_party: list[dict[str, Any]]
) -> None:
    from crmcore.audit.modelos import ApunteAuditoria
    from sqlalchemy import select

    uow = _Uow(db, tenant_id)
    svc.crear_lead(uow, nombre="Ana", email="ana@acme.test")
    segundo = svc.crear_lead(uow, nombre="Ana", email="ana@acme.test", forzar=True)

    assert db.query(Lead).count() == 2
    acciones = db.execute(
        select(ApunteAuditoria.accion).where(ApunteAuditoria.objeto_id == str(segundo.id))
    ).scalars()
    assert "lead.creado_forzado" in set(acciones)


@pytest.mark.db
def test_el_telefono_casa_aunque_se_escriba_distinto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, sin_party: list[dict[str, Any]]
) -> None:
    """Se guarda como llegó —«600 111 222»—; la igualdad contra la columna cruda
    no casaba nunca."""
    uow = _Uow(db, tenant_id)
    svc.crear_lead(uow, nombre="Luis", telefono="600 111 222")
    with pytest.raises(Conflicto) as exc:
        svc.crear_lead(uow, nombre="Otro nombre", telefono="+34 600-111-222")
    assert exc.value.detalle["candidatos"][0]["senales"] == ["telefono"]


@pytest.mark.db
def test_empresa_y_nombre_parecidos_proponen_y_sin_bloquear_por_debajo_del_umbral(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, sin_party: list[dict[str, Any]]
) -> None:
    uow = _Uow(db, tenant_id)
    svc.crear_lead(uow, nombre="Ana", apellidos="Pérez", empresa="Construcciones García S.L.")
    # Idéntico salvo la forma jurídica: misma clave, concluyente.
    with pytest.raises(Conflicto):
        svc.crear_lead(uow, nombre="Ana", apellidos="Perez", empresa="CONSTRUCCIONES GARCIA SA")

    # Otra persona de la misma empresa: no se bloquea.
    otro = svc.crear_lead(uow, nombre="Jorge", apellidos="Ruiz", empresa="Construcciones García")
    assert otro.id


@pytest.mark.db
def test_un_contacto_con_el_mismo_correo_tambien_bloquea(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ya es alguien que conocemos: entrar como lead nuevo hace que le llame un
    comercial que no sabe que es cliente."""
    contacto = uuid4()
    pedido: dict[str, Any] = {}

    def invocar(**kwargs: Any) -> dict[str, Any]:
        pedido.update(kwargs)
        return {
            "estado": 200,
            "ok": True,
            "datos": [
                {
                    "id": str(contacto),
                    "nombre": "Ana Pérez",
                    "similitud": 1.0,
                    "senales": ["email"],
                    "concluyente": True,
                }
            ],
        }

    monkeypatch.setattr("crmcore.http.interno.invocar", invocar)
    with pytest.raises(Conflicto) as exc:
        svc.crear_lead(_Uow(db, tenant_id), nombre="Ana", email="ana@cliente.test")

    candidato = exc.value.detalle["candidatos"][0]
    assert candidato == {
        "objeto": "contacto",
        "id": str(contacto),
        "nombre": "Ana Pérez",
        "similitud": 1.0,
        "senales": ["email"],
        "concluyente": True,
    }
    assert exc.value.detalle["contactos_consultados"] is True
    # Pregunta a la ruta de party, con el tenant y sólo el permiso de leer.
    assert pedido["ruta"] == "/api/v1/data-quality/contacts/duplicates"
    assert pedido["tenant_id"] == tenant_id
    assert pedido["permisos"] == ["contact:read"]
    assert pedido["parametros"]["email"] == "ana@cliente.test"


@pytest.mark.db
def test_un_contacto_con_el_mismo_telefono_bloquea_el_lead(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """En el maestro el teléfono no bloquea —una centralita—; para un lead sí:
    quien deja su teléfono en un formulario deja el suyo."""

    def invocar(**kwargs: Any) -> dict[str, Any]:
        return {
            "estado": 200,
            "ok": True,
            "datos": [
                {
                    "id": str(uuid4()),
                    "nombre": "Luis",
                    "similitud": 1.0,
                    "senales": ["telefono"],
                    "concluyente": False,
                }
            ],
        }

    monkeypatch.setattr("crmcore.http.interno.invocar", invocar)
    resultado = dedupe_leads.buscar(db, tenant_id, {"nombre": "Luis", "telefono": "600111222"})
    assert resultado.concluyentes and resultado.concluyentes[0].objeto == "contacto"


# ── La captura automática ────────────────────────────────────────────────


def _canal(db: Any, tenant_id: UUID) -> str:
    canal, secreto = captura.crear_canal(
        db,
        tenant_id=tenant_id,
        clave="web",
        nombre="Web",
        mapeo={"email": "correo", "nombre": "nombre", "telefono": "tel"},
        obligatorios=["correo"],
        campo_trampa="apellido2",
    )
    db.flush()
    return secreto


@pytest.mark.db
def test_la_captura_marca_el_duplicado_y_no_pierde_el_lead(
    db: Any,
    tenant_id: UUID,
    contexto_tenant: UUID,
    sin_party: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(captura, "_modo_dedupe", lambda db: "marcar")
    uow = _Uow(db, tenant_id)
    secreto = _canal(db, tenant_id)
    previo = svc.crear_lead(uow, nombre="Ana", email="ana@acme.test")

    salida = captura.recibir(
        uow,
        tenant_id=tenant_id,
        clave="web",
        secreto=secreto,
        entrada={"correo": "ana@acme.test", "nombre": "Ana"},
    )

    nuevo = db.get(Lead, UUID(salida["lead_id"]))
    assert nuevo is not None and nuevo.id != previo.id
    assert nuevo.duplicado_de_id == previo.id
    assert nuevo.duplicado_detalle["objeto"] == "lead"
    recepcion = captura.recepciones(db)[0]
    assert recepcion["resultado"] == "creado"
    assert "posible duplicado" in recepcion["detalle"]


@pytest.mark.db
def test_la_captura_fusiona_en_el_que_ya_habia(
    db: Any,
    tenant_id: UUID,
    contexto_tenant: UUID,
    sin_party: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(captura, "_modo_dedupe", lambda db: "fusionar")
    uow = _Uow(db, tenant_id)
    secreto = _canal(db, tenant_id)
    previo = svc.crear_lead(uow, nombre="Ana", email="ana@acme.test")

    salida = captura.recibir(
        uow,
        tenant_id=tenant_id,
        clave="web",
        secreto=secreto,
        entrada={"correo": "ana@acme.test", "nombre": "Ana", "tel": "600111222"},
    )

    assert salida["lead_id"] == str(previo.id)
    assert db.query(Lead).count() == 1
    db.refresh(previo)
    # Rellena huecos, y lo que llegó queda anotado con su canal.
    assert previo.telefono == "600111222"
    assert previo.campos["capturas_fusionadas"][0]["canal"] == "web"
    assert captura.recepciones(db)[0]["resultado"] == "fusionado"


@pytest.mark.db
def test_lo_fusionado_cuenta_para_el_tope(
    db: Any,
    tenant_id: UUID,
    contexto_tenant: UUID,
    sin_party: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un robot que repite el mismo envío no crea leads, pero sí escribe."""
    monkeypatch.setattr(captura, "_modo_dedupe", lambda db: "fusionar")
    uow = _Uow(db, tenant_id)
    secreto = _canal(db, tenant_id)
    canal = db.query(captura.CanalCaptura).one()
    canal.max_por_hora = 2
    svc.crear_lead(uow, nombre="Ana", email="ana@acme.test")
    for _ in range(3):
        captura.recibir(
            uow,
            tenant_id=tenant_id,
            clave="web",
            secreto=secreto,
            entrada={"correo": "ana@acme.test"},
        )
    resultados = [r["resultado"] for r in captura.recepciones(db)]
    assert resultados.count("fusionado") == 2
    assert resultados.count("descartado_tope") == 1


@pytest.mark.db
def test_el_maestro_devuelve_el_telefono_como_senal_sin_bloquear(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La ruta que pregunta `sales`: el teléfono sale como señal, y no es
    concluyente en el maestro."""
    from services.party import duplicados
    from services.party.modelos import Contacto

    db.add(
        Contacto(
            tenant_id=tenant_id,
            nombre="Luis",
            nombre_completo="Luis",
            clave_canonica="luis",
            telefono="+34600111222",
        )
    )
    db.flush()
    candidatos = duplicados.buscar_contactos_duplicados(
        db, tenant_id=tenant_id, nombre="Otro", telefono="600 111 222"
    )
    assert [c.senales for c in candidatos] == [("telefono",)]
    assert candidatos[0].concluyente is False
