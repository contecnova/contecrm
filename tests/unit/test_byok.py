"""Clave aportada y revocable por el cliente — BYOK/CMEK (CRM-00.01.04.09).

Lo que compra un cliente con BYOK no es cifrado: eso ya lo tiene. Compra
**poder apagarlo**. Estas pruebas defienden esa promesa y sus dos bordes:

  * Revocar deja los datos ilegibles **de verdad**, no con una bandera que un
    `UPDATE` puede quitar.
  * Y no hay ninguna vía por la que el material de la clave salga del sistema.
"""

from __future__ import annotations

import base64
import os
from typing import Any
from uuid import UUID

import pytest
from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.security import byok
from crmcore.security.cifrado import cifrar, descifrar


@pytest.fixture(autouse=True)
def _con_maestra() -> Any:
    """BYOK envuelve el material con la maestra del despliegue, así que sin
    maestra no hay sobre que guardar. Es la misma condición que en producción:
    el arranque avisa si falta."""
    from crmcore.config import limpiar_cache_settings

    os.environ["ENCRYPTION_KEY"] = "clave-maestra-de-pruebas-no-vale-para-produccion"
    limpiar_cache_settings()
    yield
    os.environ.pop("ENCRYPTION_KEY", None)
    limpiar_cache_settings()


@pytest.fixture
def byok_activo() -> Any:
    from crmcore.config import limpiar_cache_settings

    os.environ["BYOK_ENABLED"] = "true"
    limpiar_cache_settings()
    yield
    os.environ.pop("BYOK_ENABLED", None)
    limpiar_cache_settings()


def _material() -> bytes:
    return os.urandom(byok.MINIMO_BYTES)


# ── Alta y rotación ───────────────────────────────────────────────────────


@pytest.mark.db
def test_el_material_no_se_guarda_en_claro(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """El sobre es lo único que hay en la base. Sin la maestra del despliegue no
    sirve de nada, así que una copia de la base filtrada tampoco."""
    material = _material()
    fila = byok.registrar(db, tenant_id=tenant_id, material=material)
    db.flush()

    assert base64.b64encode(material).decode() not in fila.sobre
    assert fila.sobre.startswith("enc:v1:")
    # Y la huella identifica la clave sin revelarla.
    assert fila.huella == byok.huella_de(material)


@pytest.mark.db
def test_un_material_debil_se_rechaza_en_vez_de_estirarlo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Estirar entropía que no existe da una falsa sensación de fortaleza: el
    cliente cree que aporta una clave y aporta una contraseña."""
    with pytest.raises(ErrorValidacion, match="al menos"):
        byok.registrar(db, tenant_id=tenant_id, material=b"corta")


@pytest.mark.db
def test_rotar_deja_viva_la_anterior_hasta_que_se_recifre(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin esto, rotar exigiría una ventana de parada del tamaño de la base."""
    byok.registrar(db, tenant_id=tenant_id, material=_material())
    segunda = byok.registrar(db, tenant_id=tenant_id, material=_material())
    db.flush()

    assert segunda.version == 2
    assert byok.activa(db, tenant_id).version == 2
    estados = {c["version"]: c["estado"] for c in byok.historial(db, tenant_id)}
    assert estados == {1: "activa", 2: "activa"}


# ── Cifrado con la clave del cliente ──────────────────────────────────────


@pytest.mark.db
def test_con_byok_el_valor_se_cifra_con_la_clave_del_tenant(
    byok_activo: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    byok.registrar(db, tenant_id=tenant_id, material=_material())
    db.commit()

    cifrado = cifrar("secreto del cliente", proposito="credenciales", db=db)
    assert descifrar(cifrado, proposito="credenciales", db=db) == "secreto del cliente"


@pytest.mark.db
def test_la_clave_de_un_tenant_no_descifra_lo_de_otro(
    byok_activo: Any, db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es la propiedad que hace que BYOK signifique algo: si las dos claves
    descifraran lo mismo, revocar una no dejaría nada ilegible."""
    from crmcore.errors import ErrorInterno
    from crmcore.tenancy.context import con_contexto

    byok.registrar(db, tenant_id=tenant_id, material=_material())
    byok.registrar(db, tenant_id=otro_tenant_id, material=_material())
    db.commit()

    cifrado = cifrar("de A", proposito="credenciales", db=db)
    with con_contexto(tenant_id=otro_tenant_id), pytest.raises(ErrorInterno):
        descifrar(cifrado, proposito="credenciales", db=db)


@pytest.mark.db
def test_un_tenant_sin_byok_usa_la_maestra_como_siempre(
    byok_activo: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Encender BYOK en el despliegue no puede romper a los tenants que no lo
    usan: la mayoría no lo usará nunca."""
    cifrado = cifrar("normal", proposito="general", db=db)
    assert descifrar(cifrado, proposito="general", db=db) == "normal"


# ── Revocación ────────────────────────────────────────────────────────────


@pytest.mark.db
def test_revocar_exige_confirmacion_explicita(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es la operación de este sistema que menos vuelta atrás tiene: una llamada
    mal dirigida deja ilegibles los datos de un cliente."""
    byok.registrar(db, tenant_id=tenant_id, material=_material())
    db.flush()
    with pytest.raises(ErrorValidacion, match="[Cc]onfirmar"):
        byok.revocar(db, tenant_id=tenant_id, motivo="fin de contrato", confirmado=False)


@pytest.mark.db
def test_revocar_exige_un_motivo(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Dentro de un año alguien preguntará por qué estos datos no se leen."""
    byok.registrar(db, tenant_id=tenant_id, material=_material())
    db.flush()
    with pytest.raises(ErrorValidacion, match="por qué"):
        byok.revocar(db, tenant_id=tenant_id, motivo="   ", confirmado=True)


@pytest.mark.db
def test_revocar_borra_el_sobre_y_no_solo_lo_marca(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Dejar el material con una bandera de «revocada» convierte la garantía en
    un `UPDATE` de distancia, y quien compra BYOK compra justo lo contrario."""
    byok.registrar(db, tenant_id=tenant_id, material=_material())
    byok.registrar(db, tenant_id=tenant_id, material=_material())
    db.flush()

    byok.revocar(db, tenant_id=tenant_id, motivo="el cliente se va", confirmado=True)
    db.flush()

    for clave in byok.historial(db, tenant_id):
        assert clave["estado"] == "revocada"
    from sqlalchemy import select

    filas = (
        db.execute(select(byok.ClaveTenant).where(byok.ClaveTenant.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    # Todas, no solo la última: dejar viva una versión antigua haría que el dato
    # cifrado con ella siguiera legible y la revocación sería un gesto.
    assert all(f.sobre == "" for f in filas)
    # La huella sobrevive: es lo que permite demostrar qué clave estaba activa.
    assert all(f.huella for f in filas)


@pytest.mark.db
def test_tras_revocar_el_dato_cifrado_ya_no_se_lee(
    byok_activo: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La prueba que justifica toda la funcionalidad."""
    byok.registrar(db, tenant_id=tenant_id, material=_material())
    db.commit()
    cifrado = cifrar("credencial del ERP", proposito="credenciales", db=db)
    assert descifrar(cifrado, proposito="credenciales", db=db) == "credencial del ERP"

    byok.revocar(db, tenant_id=tenant_id, motivo="orden judicial", confirmado=True)
    db.commit()

    with pytest.raises(byok.ClaveRevocada):
        descifrar(cifrado, proposito="credenciales", db=db)


@pytest.mark.db
def test_tras_revocar_no_se_cae_a_la_maestra(
    byok_activo: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Caer a la maestra sería seguir descifrando datos que el cliente mandó
    hacer ilegibles: exactamente lo contrario de lo que compró."""
    byok.registrar(db, tenant_id=tenant_id, material=_material())
    db.commit()
    byok.revocar(db, tenant_id=tenant_id, motivo="baja", confirmado=True)
    db.commit()

    with pytest.raises(byok.ClaveRevocada):
        cifrar("algo nuevo", proposito="general", db=db)


@pytest.mark.db
def test_no_se_puede_registrar_una_clave_nueva_despues_de_revocar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Aceptarla daría a entender que lo revocado se recupera, y no se recupera:
    los datos viejos siguen ilegibles."""
    byok.registrar(db, tenant_id=tenant_id, material=_material())
    db.flush()
    byok.revocar(db, tenant_id=tenant_id, motivo="baja", confirmado=True)
    db.flush()

    with pytest.raises(Conflicto, match="revoc"):
        byok.registrar(db, tenant_id=tenant_id, material=_material())


@pytest.mark.db
def test_revocar_dos_veces_se_rechaza(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    byok.registrar(db, tenant_id=tenant_id, material=_material())
    db.flush()
    byok.revocar(db, tenant_id=tenant_id, motivo="baja", confirmado=True)
    db.flush()
    with pytest.raises(Conflicto, match="ya estaba"):
        byok.revocar(db, tenant_id=tenant_id, motivo="otra vez", confirmado=True)


@pytest.mark.db
def test_revocar_sin_clave_propia_dice_que_no_hay(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.errors import NoEncontrado

    with pytest.raises(NoEncontrado):
        byok.revocar(db, tenant_id=tenant_id, motivo="x", confirmado=True)


# ── Replicación entre servicios ───────────────────────────────────────────


@pytest.mark.db
def test_registrar_emite_el_evento_que_replica_la_clave(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin replicar, la clave viviría solo en `tenancy`, los demás servicios
    seguirían cifrando con la maestra y revocar no dejaría ilegible nada — el
    único modo de fallo inaceptable de esta funcionalidad."""
    from crmcore.bus.modelos import EventoSaliente
    from sqlalchemy import select

    byok.registrar(db, tenant_id=tenant_id, material=_material())
    db.flush()

    evento = (
        db.execute(select(EventoSaliente).where(EventoSaliente.tipo == byok.CLAVE_CAMBIADA))
        .scalars()
        .one()
    )
    assert evento.sobre["data"]["estado"] == "activa"
    assert evento.sobre["data"]["sobre"].startswith("enc:v1:")


@pytest.mark.db
def test_el_evento_de_la_clave_no_sale_a_los_webhooks(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un webhook con el sobre de la clave en el cuerpo es justo lo que este
    módulo existe para evitar."""
    from crmcore.events.catalogo import obtener, publicos

    byok._declarar_evento()
    assert obtener(byok.CLAVE_CAMBIADA).publico is False
    assert byok.CLAVE_CAMBIADA not in {t.tipo for t in publicos()}


@pytest.mark.db
def test_consumir_la_revocacion_la_aplica_en_este_servicio(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    import asyncio

    byok.registrar(db, tenant_id=tenant_id, material=_material())
    db.commit()

    asyncio.run(
        byok.consumir_clave(
            {
                "tenant_id": str(tenant_id),
                "data": {"version": 1, "estado": "revocada", "sobre": "", "motivo": "baja"},
            }
        )
    )
    db.expunge_all()
    assert byok.esta_revocada(db, tenant_id)


# ── Lo que nunca sale ─────────────────────────────────────────────────────


def test_ninguna_ruta_devuelve_el_material_de_la_clave() -> None:
    """Una API que puede leer la clave del cliente convierte todo el BYOK en
    decoración: quien comprometa esa ruta tiene lo mismo que tendría sin BYOK.

    Se comprueba sobre el código y no ejecutando, porque lo que hay que impedir
    es que alguien **escriba** esa ruta, no que devuelva algo concreto hoy.
    """
    import ast
    from pathlib import Path

    ruta = Path(__file__).resolve().parents[2] / "services" / "tenancy" / "api_byok.py"
    arbol = ast.parse(ruta.read_text(encoding="utf-8"), str(ruta))

    culpables: list[str] = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.FunctionDef):
            continue
        # `generar` es la única excepción y es legítima: el material se crea en
        # el momento, se devuelve una vez y no se guarda en claro en ningún
        # sitio. Devolver uno GUARDADO es lo que no puede existir.
        if nodo.name == "generar":
            continue
        cuerpo = ast.unparse(nodo)
        if "material_base64" in cuerpo and "return" in cuerpo.split("material_base64")[0][-200:]:
            culpables.append(nodo.name)
        if "_desenvolver" in cuerpo or ".sobre" in cuerpo:
            culpables.append(f"{nodo.name} (lee el sobre)")

    assert not culpables, (
        "Estas rutas pueden sacar el material de la clave del sistema: "
        f"{culpables}. Una API que puede leer la clave del cliente convierte "
        "todo el BYOK en decoración."
    )


def test_generar_material_da_suficiente_entropia() -> None:
    assert len(byok.generar_material()) >= byok.MINIMO_BYTES
    assert byok.generar_material() != byok.generar_material()
