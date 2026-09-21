"""Anonimización, marca de agua, SIEM y consulta del audit trail
(CRM-00.05.03.05, CRM-00.05.03.07, CRM-00.05.04.04, CRM-00.05.04.05).

Cuatro piezas de la misma idea: el dato sale del sistema por sitios que no son
un ataque —una copia de preproducción, un CSV que alguien reenvía, un volcado al
SIEM, una consulta de soporte— y en todos hay que saber qué salió y de dónde.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.seguridad import anonimizar, marca, siem

# ── Anonimización ─────────────────────────────────────────────────────────


def test_el_mismo_valor_da_siempre_el_mismo_seudonimo() -> None:
    """Sin consistencia, el correo de un contacto sería distinto en la tabla de
    contactos y en la de actividades, las relaciones se romperían y el entorno
    no serviría — que es como acaban reponiendo los datos reales."""
    sal = "sal-de-pruebas"
    uno = anonimizar.seudonimo("ana@acme.example", sal=sal, forma="email")
    otro = anonimizar.seudonimo("ana@acme.example", sal=sal, forma="email")
    assert uno == otro


def test_dos_entornos_dan_valores_distintos() -> None:
    """Si la sal fuera la misma, juntar dos copias con campos distintos
    anonimizados devolvería el registro entero."""
    uno = anonimizar.seudonimo("ana@acme.example", sal="pre", forma="email")
    otro = anonimizar.seudonimo("ana@acme.example", sal="uat", forma="email")
    assert uno != otro


def test_el_seudonimo_conserva_la_forma() -> None:
    """Un entorno donde los correos son «xxx» no sirve para probar el envío de
    correos, que es justo lo que se prueba ahí."""
    correo = anonimizar.seudonimo("ana@acme.example", sal="s", forma="email")
    assert "@" in str(correo) and str(correo).endswith(".invalid")


def test_el_vacio_se_queda_vacio() -> None:
    """Inventar un correo donde no había cambiaría los recuentos de completitud
    y alguien concluiría que preproducción tiene mejores datos que producción."""
    assert anonimizar.seudonimo(None, sal="s") is None
    assert anonimizar.seudonimo("", sal="s") == ""


def test_los_campos_a_anonimizar_salen_del_modelo() -> None:
    """De una lista aparte se quedarían desfasados, y el campo nuevo entraría
    con dato real sin que nadie lo decidiera."""
    from services.party.modelos import Cuenta

    campos = anonimizar.campos_sensibles(Cuenta)
    assert campos, "la cuenta declara campos sensibles y no se han encontrado"


def test_anonimizar_no_toca_la_fila_original() -> None:
    """Hacerlo sobre un objeto de SQLAlchemy lo marcaría como sucio y el
    siguiente flush escribiría los valores anónimos EN PRODUCCIÓN."""
    from services.party.modelos import Cuenta

    original = {"nombre": "ACME", "telefono": "+34600111222"}
    salida = anonimizar.anonimizar_fila(original, Cuenta, sal="s", campos=["telefono"])
    assert original["telefono"] == "+34600111222"
    assert salida["telefono"] != "+34600111222"


# ── Marca de agua ─────────────────────────────────────────────────────────


def test_la_marca_no_lleva_el_usuario_en_claro() -> None:
    """El fichero puede acabar en manos de cualquiera, y el identificador en
    claro es un dato de la plantilla del cliente."""
    usuario = uuid4()
    datos = marca.firma(tenant_id=uuid4(), usuario_id=usuario)
    assert str(usuario) not in str(datos)
    assert datos["traza"]


def test_la_marca_va_dentro_del_fichero_y_arriba() -> None:
    """El nombre se cambia y la cabecera HTTP se pierde en cuanto alguien lo
    reenvía, que es justo el momento en el que hace falta."""
    datos = marca.firma(tenant_id=uuid4(), usuario_id=uuid4())
    csv = marca.cabecera_csv(datos)
    assert csv.startswith("# ") and "contecrm" in csv


def test_un_texto_se_marca_arriba_y_abajo() -> None:
    """Un recorte de las primeras líneas es lo más habitual al pegar un
    fragmento en un correo, y uno del final también."""
    datos = marca.firma(tenant_id=uuid4(), usuario_id=None)
    salida = marca.marcar_texto("fila1\nfila2", datos)
    assert salida.startswith("#") and salida.rstrip().endswith(datos["traza"])


# ── SIEM y retención ──────────────────────────────────────────────────────


@pytest.mark.db
def test_el_volcado_lleva_secuencia_y_hash(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Es lo que permite a quien lo reciba comprobar que no falta nada por el
    camino."""
    from crmcore.audit import registrar

    registrar(db, accion="cuenta.creada", objeto="cuenta", tenant_id=tenant_id)
    db.flush()

    lineas = list(
        siem.a_jsonl(
            db,
            tenant_id,
            desde=datetime.now(timezone.utc) - timedelta(hours=1),
            hasta=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    assert len(lineas) == 1
    import json

    apunte = json.loads(lineas[0])
    assert apunte["sequence"] and apunte["hash"] and apunte["previous_hash"]
    # Nombres neutros: el adaptador de cualquier SIEM a esto son veinte líneas,
    # y escribir el formato de uno ataría la instalación a ese uno.
    assert set(apunte) >= {"timestamp", "action", "actor", "ip"}


@pytest.mark.db
def test_purgar_deja_constancia_del_corte(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Quien verifique la cadena a partir de ahí encuentra el punto y el motivo,
    en vez de un hueco que parece manipulación."""
    from crmcore.audit import registrar
    from crmcore.audit.modelos import ApunteAuditoria

    for _ in range(3):
        registrar(db, accion="cuenta.creada", objeto="cuenta", tenant_id=tenant_id)
    db.flush()
    # Se envejecen para que entren en la ventana de purga.
    for apunte in db.query(ApunteAuditoria).all():
        apunte.created_at = datetime.now(timezone.utc) - timedelta(days=400)
    db.flush()

    salida = siem.purgar(db, tenant_id, dias_retencion=365)
    db.flush()

    assert salida["borrados"] == 3
    quedan = db.query(ApunteAuditoria).all()
    assert len(quedan) == 1
    assert quedan[0].accion == "auditoria.purgada"
    assert quedan[0].datos["apuntes_borrados"] == 3


@pytest.mark.db
def test_una_retencion_de_cero_dias_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.errors import Conflicto

    with pytest.raises(Conflicto):
        siem.purgar(db, tenant_id, dias_retencion=0)


@pytest.mark.db
def test_la_consulta_filtra_por_lo_que_se_pregunta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«¿Quién tocó esta cuenta?» se pregunta mientras se mira la cuenta, y
    obligar a salir a otra herramienta significa que casi nunca se responde."""
    from crmcore.audit import registrar

    registrar(db, accion="cuenta.creada", objeto="cuenta", tenant_id=tenant_id)
    registrar(db, accion="lead.creado", objeto="lead", tenant_id=tenant_id)
    db.flush()

    solo_cuentas = siem.consultar(db, tenant_id, objeto="cuenta")
    assert [a["accion"] for a in solo_cuentas] == ["cuenta.creada"]
