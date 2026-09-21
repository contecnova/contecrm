"""Tipos de registro, límites del esquema, renombrados seguros y lista de IP
(CRM-00.04.01.05, CRM-00.04.01.09, CRM-00.04.01.10, CRM-00.02.04.04).

Cuatro cosas que aparecen en el mismo momento: cuando el cliente lleva un año
configurando y el esquema empieza a pesar.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.authz import credenciales
from crmcore.errors import Conflicto, ErrorValidacion, Prohibido

from services.metadata import gobierno


def _objeto(db: Any, tenant_id: UUID, nombre: str = "cuenta") -> Any:
    from services.metadata.modelos import ObjetoDefinido

    fila = ObjetoDefinido(
        tenant_id=tenant_id, nombre=nombre, etiqueta=nombre, etiqueta_plural=nombre
    )
    db.add(fila)
    db.flush()
    return fila


def _campo(db: Any, tenant_id: UUID, objeto_id: UUID, nombre: str) -> None:
    from services.metadata.modelos import CampoDefinido

    db.add(
        CampoDefinido(
            tenant_id=tenant_id, objeto_id=objeto_id, nombre=nombre, etiqueta=nombre, tipo="texto"
        )
    )
    db.flush()


# ── Tipos de registro ─────────────────────────────────────────────────────


@pytest.mark.db
def test_solo_puede_haber_un_tipo_por_defecto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Dos por defecto dejarían el alta sin saber cuál usar, y el que gane
    dependería del orden de la consulta — que cambia sin avisar."""
    objeto = _objeto(db, tenant_id)
    gobierno.guardar_tipo(
        db,
        tenant_id=tenant_id,
        objeto_id=objeto.id,
        clave="empresa",
        nombre="Empresa",
        por_defecto=True,
    )
    gobierno.guardar_tipo(
        db,
        tenant_id=tenant_id,
        objeto_id=objeto.id,
        clave="publica",
        nombre="Pública",
        por_defecto=True,
    )
    db.flush()

    from sqlalchemy import select

    por_defecto = [
        f.clave
        for f in db.execute(
            select(gobierno.TipoRegistro).where(gobierno.TipoRegistro.por_defecto.is_(True))
        ).scalars()
    ]
    assert por_defecto == ["publica"]


@pytest.mark.db
def test_un_tipo_esconde_campos_y_acota_listas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    objeto = _objeto(db, tenant_id)
    tipo = gobierno.guardar_tipo(
        db,
        tenant_id=tenant_id,
        objeto_id=objeto.id,
        clave="publica",
        nombre="Pública",
        campos_ocultos=["nif"],
        valores_lista={"sector": ["administracion"]},
    )

    class _C:
        def __init__(self, nombre: str) -> None:
            self.nombre = nombre

    vista = gobierno.describe_para_tipo([_C("nif"), _C("sector")], tipo)
    assert vista[0] == {"nombre": "nif", "oculto": True, "opciones": None}
    assert vista[1]["opciones"] == ["administracion"]


def test_sin_tipo_se_ven_todos_los_campos() -> None:
    """Un objeto sin tipos configurados tiene que seguir funcionando igual que
    antes de que esto existiera."""

    class _C:
        def __init__(self, nombre: str) -> None:
            self.nombre = nombre

    vista = gobierno.describe_para_tipo([_C("a"), _C("b")], None)
    assert all(v["oculto"] is False for v in vista)


# ── Límites del esquema ───────────────────────────────────────────────────


@pytest.mark.db
def test_el_limite_dice_el_porcentaje_y_no_solo_el_numero(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nadie sabe si 140 campos son muchos, y todo el mundo entiende «vas por el
    70 %»."""
    from crmcore.config import limpiar_cache_settings

    monkeypatch.setenv("METADATA_MAX_CAMPOS", "10")
    limpiar_cache_settings()
    objeto = _objeto(db, tenant_id)
    for i in range(8):
        _campo(db, tenant_id, objeto.id, f"campo_{i}")

    estado = gobierno.limites(db, tenant_id, objeto.id)
    limpiar_cache_settings()

    assert estado["campos"] == 8
    assert estado["pct"] == 80.0
    assert estado["en_aviso"] is True


@pytest.mark.db
def test_pasado_el_tope_no_se_puede_añadir_y_el_error_dice_cuál(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Has llegado al límite» sin decir cuál obliga a buscarlo, y quien lo lee
    está justo en mitad de configurar algo."""
    from crmcore.config import limpiar_cache_settings

    monkeypatch.setenv("METADATA_MAX_CAMPOS", "10")
    limpiar_cache_settings()
    objeto = _objeto(db, tenant_id)
    for i in range(10):
        _campo(db, tenant_id, objeto.id, f"campo_{i}")

    with pytest.raises(Conflicto) as e:
        gobierno.exigir_hueco(db, tenant_id, objeto.id)
    limpiar_cache_settings()
    assert e.value.error_code == "metadata.tope_de_campos"
    assert e.value.detalle["tope"] == 10


# ── Renombrado seguro ─────────────────────────────────────────────────────


@pytest.mark.db
def test_durante_el_renombrado_los_dos_nombres_funcionan(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Renombrar de golpe rompe a quien manda el nombre viejo, y en un CRM con
    integraciones eso es siempre alguien."""
    gobierno.anunciar_renombrado(
        db, tenant_id=tenant_id, objeto="cuenta", desde="telefono", hasta="telefono_principal"
    )
    db.flush()

    salida = gobierno.traducir_entrada(db, tenant_id, "cuenta", {"telefono": "+34600"})
    assert salida == {"telefono_principal": "+34600"}


@pytest.mark.db
def test_si_vienen_los_dos_manda_el_nuevo(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Quien ya se ha migrado no puede verse pisado por un campo viejo que su
    cliente sigue mandando por inercia."""
    gobierno.anunciar_renombrado(
        db, tenant_id=tenant_id, objeto="cuenta", desde="telefono", hasta="telefono_principal"
    )
    db.flush()

    salida = gobierno.traducir_entrada(
        db, tenant_id, "cuenta", {"telefono": "viejo", "telefono_principal": "nuevo"}
    )
    assert salida == {"telefono_principal": "nuevo"}


@pytest.mark.db
def test_no_se_retira_el_viejo_mientras_se_use(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Se comprueba con el contador y no con una fecha: el día que toca siempre
    hay alguien usándolo."""
    gobierno.anunciar_renombrado(
        db, tenant_id=tenant_id, objeto="cuenta", desde="telefono", hasta="telefono_principal"
    )
    db.flush()
    gobierno.traducir_entrada(db, tenant_id, "cuenta", {"telefono": "+34600"})
    db.flush()

    with pytest.raises(Conflicto) as e:
        gobierno.completar_renombrado(db, tenant_id=tenant_id, objeto="cuenta", desde="telefono")
    assert e.value.error_code == "esquema.viejo_todavia_en_uso"


@pytest.mark.db
def test_sin_usos_el_viejo_se_retira(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    gobierno.anunciar_renombrado(
        db, tenant_id=tenant_id, objeto="cuenta", desde="telefono", hasta="telefono_principal"
    )
    db.flush()
    cambio = gobierno.completar_renombrado(
        db, tenant_id=tenant_id, objeto="cuenta", desde="telefono"
    )
    assert cambio.estado == "completado"


@pytest.mark.db
def test_renombrar_a_si_mismo_se_rechaza(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    with pytest.raises(ErrorValidacion):
        gobierno.anunciar_renombrado(db, tenant_id=tenant_id, objeto="cuenta", desde="x", hasta="x")


# ── Lista de IP por credencial ────────────────────────────────────────────


def test_la_lista_entiende_redes_y_no_solo_direcciones() -> None:
    """Comparar cadenas hacía que `10.0.0.0/8` no casara nunca con `10.1.2.3`:
    quien declaraba una red se quedaba sin acceso y acababa quitando la lista."""
    credenciales.comprobar("10.1.2.3", ["10.0.0.0/8"])
    with pytest.raises(Prohibido):
        credenciales.comprobar("80.1.2.3", ["10.0.0.0/8"])


def test_sin_lista_no_hay_restriccion() -> None:
    """Una clave recién creada sin lista tiene que funcionar, o nadie podría
    empezar a usarla."""
    credenciales.comprobar("", [])
    credenciales.comprobar("1.2.3.4", None)


def test_con_lista_declarada_la_falta_de_ip_CORTA() -> None:
    """Era el agujero: `and ip` hacía que sin dirección no se comprobara nada, y
    una llamada detrás de un proxy que la suprime se saltaba la lista entera.
    Una restricción que se desactiva omitiendo un dato no es una restricción."""
    with pytest.raises(Prohibido) as e:
        credenciales.comprobar("", ["10.0.0.0/8"])
    assert e.value.error_code == "credencial.sin_ip"


def test_una_red_mal_escrita_no_es_un_comodin() -> None:
    """Tratarla así convertiría un error de tecleo en una lista vacía, que deja
    entrar a cualquiera con la clave."""
    with pytest.raises(Prohibido):
        credenciales.comprobar("1.2.3.4", ["no-es-una-red"])


def test_la_lista_se_valida_al_guardarla() -> None:
    """Descubrir una red mal escrita en la primera llamada deja la integración
    caída y a nadie mirando, porque quien la configuró ya se fue."""
    assert credenciales.validar_lista(["10.0.0.0/8"]) == []
    assert credenciales.validar_lista(["chorizo"]) != []


def test_permitir_toda_internet_se_avisa_pero_no_se_prohibe() -> None:
    """Hay despliegues donde es legítimo durante una migración, y prohibirlo
    llevaría a desactivar la lista entera, que es peor."""
    problemas = credenciales.validar_lista(["0.0.0.0/0"])
    assert problemas and "no restringe nada" in problemas[0]
