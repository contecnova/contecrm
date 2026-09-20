"""Captura de leads desde fuera: formularios, chat y tablets (CRM-01.01.03.02).

La importación masiva y la API ya estaban. Faltaba lo que llega **desde fuera
sin credencial de usuario**: el formulario de la web, el chat, la tablet de una
feria.

Y eso es un solo mecanismo, no tres. Lo que estas pruebas defienden:

  * Que un canal declarado traduce lo que llega **sin poder escribir de más**.
  * Que un endpoint público no se convierte en un problema: clave, trampa y tope.
  * Que lo descartado **se ve**, porque «no me llegó el lead del formulario» es
    la pregunta que más veces se hace de esto.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.errors import ErrorValidacion, NoEncontrado

from services.sales import captura
from services.sales.modelos import Lead


class _Uow:
    def __init__(self, db: Any, tenant_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.emitidos: list[dict[str, Any]] = []

    def emitir(self, tipo: str, *, subject: Any, data: Any, **extra: Any) -> None:
        self.emitidos.append({"tipo": tipo, "data": data})


def _canal(db: Any, tenant_id: UUID, **extra: Any) -> tuple[Any, str]:
    base: dict[str, Any] = {
        "clave": "web",
        "nombre": "Formulario de la web",
        "mapeo": {"email": "correo", "nombre": "nombre_completo", "empresa": "compania"},
        "fijos": {"origen": "formulario web"},
        "obligatorios": ["correo"],
        "campo_trampa": "apellido2",
    }
    base.update(extra)
    return captura.crear_canal(db, tenant_id=tenant_id, **base)


# ── El canal declarado ────────────────────────────────────────────────────


@pytest.mark.db
def test_el_secreto_no_se_guarda_en_claro(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Si la base se filtra, las claves de los formularios de todos los tenants
    no vienen en ella."""
    canal, secreto = _canal(db, tenant_id)
    assert secreto not in canal.secreto_hash
    assert len(canal.secreto_hash) == 64


@pytest.mark.db
def test_un_canal_no_puede_escribir_el_propietario_ni_la_campana(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin esta comprobación, una petición pública podría asignarse leads o
    imputarlos a la campaña de otro."""
    with pytest.raises(ErrorValidacion, match="no puede escribir"):
        _canal(db, tenant_id, mapeo={"owner_id": "usuario"})


@pytest.mark.db
def test_rotar_el_secreto_invalida_el_anterior(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El secreto viaja en el HTML de una página pública, así que se filtra:
    rotarlo es una operación normal, no una emergencia."""
    canal, viejo = _canal(db, tenant_id)
    db.flush()
    nuevo = captura.rotar_secreto(db, canal.id)

    uow = _Uow(db, tenant_id)
    assert nuevo != viejo
    with pytest.raises(NoEncontrado):
        captura.recibir(
            uow, tenant_id=tenant_id, clave="web", secreto=viejo, entrada={"correo": "a@b.test"}
        )


# ── Recepción ─────────────────────────────────────────────────────────────


@pytest.mark.db
def test_un_envio_correcto_crea_el_lead(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    uow = _Uow(db, tenant_id)
    _canal(db, tenant_id)
    db.flush()

    salida = captura.recibir(
        uow,
        tenant_id=tenant_id,
        clave="web",
        secreto=_secreto_de(db, tenant_id),
        entrada={
            "correo": "ana@ejemplo.test",
            "nombre_completo": "Ana",
            "compania": "ACME",
            "utm": {"utm_source": "google"},
        },
    )

    assert salida["lead_id"]
    lead = db.query(Lead).one()
    assert lead.email == "ana@ejemplo.test"
    assert lead.empresa == "ACME"
    # El origen lo pone el CANAL, no quien rellena el formulario: si viniera de
    # la petición, cualquiera podría imputar sus leads a la campaña que
    # quisiera.
    assert lead.origen == "formulario web"


@pytest.mark.db
def test_lo_que_no_encaja_en_un_campo_se_conserva(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El formulario de un cliente pregunta cosas que este CRM no conoce, y
    tirarlas obligaría a mirar el correo de aviso para saber qué pidió el
    interesado."""
    uow = _Uow(db, tenant_id)
    _canal(db, tenant_id)
    db.flush()

    captura.recibir(
        uow,
        tenant_id=tenant_id,
        clave="web",
        secreto=_secreto_de(db, tenant_id),
        entrada={"correo": "a@b.test", "metros_cuadrados": 320, "plazo": "Q3"},
    )

    lead = db.query(Lead).one()
    assert lead.campos["metros_cuadrados"] == 320
    assert lead.campos["plazo"] == "Q3"


@pytest.mark.db
def test_un_lead_sin_forma_de_contactar_se_descarta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Solo ensucia el embudo y las métricas de conversión."""
    uow = _Uow(db, tenant_id)
    _canal(db, tenant_id, obligatorios=[])
    db.flush()

    salida = captura.recibir(
        uow,
        tenant_id=tenant_id,
        clave="web",
        secreto=_secreto_de(db, tenant_id),
        entrada={"nombre_completo": "Ana"},
    )
    assert salida["lead_id"] is None
    assert db.query(Lead).count() == 0


@pytest.mark.db
def test_faltar_un_obligatorio_se_descarta_y_se_dice_cual(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    uow = _Uow(db, tenant_id)
    _canal(db, tenant_id)
    db.flush()
    captura.recibir(
        uow,
        tenant_id=tenant_id,
        clave="web",
        secreto=_secreto_de(db, tenant_id),
        entrada={"nombre_completo": "Ana"},
    )
    recepcion = captura.recepciones(db)[0]
    assert recepcion["resultado"] == "descartado_incompleto"
    assert "correo" in recepcion["detalle"]


# ── Las tres protecciones ─────────────────────────────────────────────────


@pytest.mark.db
def test_la_trampa_descarta_sin_decir_que_es_una_trampa(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Se descarta con la misma respuesta que un envío bueno. Un error le diría
    al robot qué tiene que cambiar para la próxima."""
    uow = _Uow(db, tenant_id)
    _canal(db, tenant_id)
    db.flush()

    bueno = captura.recibir(
        uow,
        tenant_id=tenant_id,
        clave="web",
        secreto=_secreto_de(db, tenant_id),
        entrada={"correo": "a@b.test"},
    )
    robot = captura.recibir(
        uow,
        tenant_id=tenant_id,
        clave="web",
        secreto=_secreto_de(db, tenant_id),
        entrada={"correo": "spam@b.test", "apellido2": "soy un robot"},
    )

    assert bueno["recibido"] == robot["recibido"] is True
    assert robot["lead_id"] is None
    assert db.query(Lead).count() == 1


@pytest.mark.db
def test_un_canal_sin_clave_valida_no_dice_si_existe(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Mismo error para «no existe», «está apagado» y «clave mala»:
    distinguirlos convierte el endpoint en un oráculo que dice qué canales tiene
    un tenant."""
    uow = _Uow(db, tenant_id)
    _canal(db, tenant_id)
    db.flush()

    for clave, secreto in (("web", "mala"), ("inventado", "mala")):
        with pytest.raises(NoEncontrado, match="desconocido"):
            captura.recibir(
                uow,
                tenant_id=tenant_id,
                clave=clave,
                secreto=secreto,
                entrada={"correo": "a@b.test"},
            )


@pytest.mark.db
def test_un_canal_apagado_no_recibe(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    uow = _Uow(db, tenant_id)
    canal, _s = _canal(db, tenant_id)
    canal.activo = False
    db.flush()
    with pytest.raises(NoEncontrado):
        captura.recibir(
            uow,
            tenant_id=tenant_id,
            clave="web",
            secreto=_secreto_de(db, tenant_id),
            entrada={"correo": "a@b.test"},
        )


@pytest.mark.db
def test_pasado_el_tope_por_hora_se_descarta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La clave se filtra siempre —va en el HTML de una página pública— y esto
    es lo que acota el daño."""
    uow = _Uow(db, tenant_id)
    _canal(db, tenant_id, max_por_hora=2)
    db.flush()
    secreto = _secreto_de(db, tenant_id)

    for i in range(4):
        captura.recibir(
            uow,
            tenant_id=tenant_id,
            clave="web",
            secreto=secreto,
            entrada={"correo": f"a{i}@b.test"},
        )

    assert db.query(Lead).count() == 2
    descartadas = captura.recepciones(db, solo_descartadas=True)
    assert all(r["resultado"] == "descartado_tope" for r in descartadas)


@pytest.mark.db
def test_un_canal_de_otro_tenant_no_sirve(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sería la fuga más fácil de explotar: la misma clave de canal desde otro
    tenant metiendo leads en el CRM del vecino."""
    uow = _Uow(db, otro_tenant_id)
    _canal(db, tenant_id)
    db.flush()
    with pytest.raises(NoEncontrado):
        captura.recibir(
            uow,
            tenant_id=otro_tenant_id,
            clave="web",
            secreto=_secreto_de(db, tenant_id),
            entrada={"correo": "a@b.test"},
        )


# ── Lo descartado se ve ───────────────────────────────────────────────────


@pytest.mark.db
def test_lo_descartado_queda_registrado_con_lo_que_llego(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que convierte «no me llegó el lead del formulario» en una pregunta
    contestable. Y guardar la entrada permite recuperar a mano un lead
    descartado por error."""
    uow = _Uow(db, tenant_id)
    _canal(db, tenant_id)
    db.flush()

    captura.recibir(
        uow,
        tenant_id=tenant_id,
        clave="web",
        secreto=_secreto_de(db, tenant_id),
        entrada={"nombre_completo": "Ana", "telefono_movil": "600"},
    )

    descartada = captura.recepciones(db, solo_descartadas=True)[0]
    assert descartada["entrada"]["nombre_completo"] == "Ana"
    assert descartada["detalle"]


@pytest.mark.db
def test_las_estadisticas_del_canal_cuentan_las_dos_cosas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    uow = _Uow(db, tenant_id)
    canal, _s = _canal(db, tenant_id)
    db.flush()
    secreto = _secreto_de(db, tenant_id)

    captura.recibir(
        uow, tenant_id=tenant_id, clave="web", secreto=secreto, entrada={"correo": "a@b.test"}
    )
    captura.recibir(uow, tenant_id=tenant_id, clave="web", secreto=secreto, entrada={"nada": "x"})

    db.refresh(canal)
    assert canal.recibidos == 1 and canal.descartados == 1
    assert canal.ultimo_at is not None


# El secreto solo se conoce al crear el canal, así que las pruebas lo rotan para
# volver a tenerlo. Es exactamente lo que tendría que hacer un administrador que
# lo perdió, y probarlo así comprueba de paso que rotar funciona.
def _secreto_de(db: Any, tenant_id: UUID) -> str:
    from sqlalchemy import select

    canal = db.execute(
        select(captura.CanalCaptura).where(
            captura.CanalCaptura.tenant_id == tenant_id, captura.CanalCaptura.clave == "web"
        )
    ).scalar_one()
    if not hasattr(canal, "_secreto_prueba"):
        canal._secreto_prueba = captura.rotar_secreto(db, canal.id)
    return canal._secreto_prueba
