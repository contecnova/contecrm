"""Aislamiento de la caché y del almacén de ficheros.

Cubre CRM-00.01.01.07 (namespacing obligatorio de claves de caché por tenant y
purga selectiva) y CRM-00.01.01.08 (prefijo por tenant en el almacén, URLs
firmadas y purga).

Son dos de las vías más silenciosas por las que un cliente acaba viendo el dato
de otro: ni la caché ni el almacén de ficheros pasan por RLS, así que el
aislamiento tiene que ser **estructural** —imposible de expresar mal— y no un
convenio que alguien recuerde seguir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore import cache as cch
from crmcore.errors import ErrorValidacion


@pytest.fixture(autouse=True)
def cache_limpia() -> Any:
    cch.reset_cache()
    yield
    cch.reset_cache()


# ── Caché ─────────────────────────────────────────────────────────────────


def test_la_clave_lleva_siempre_el_tenant_delante() -> None:
    t = uuid4()
    clave = cch.clave_de("ajustes", "sla", tenant_id=t)
    assert clave.startswith(f"crm:t{t}:")


def test_dos_tenants_no_comparten_clave() -> None:
    """Es el fallo que este módulo existe para hacer imposible: una clave sin
    tenant sirve la respuesta del primero que pregunte a todos los demás."""
    a, b = uuid4(), uuid4()
    assert cch.clave_de("ajustes", "sla", tenant_id=a) != cch.clave_de(
        "ajustes", "sla", tenant_id=b
    )


def test_sin_tenant_y_sin_global_falla_en_vez_de_caer_a_una_clave_global() -> None:
    """Caer a global «por si acaso» sería exactamente el agujero. Un fallo al
    escribir el código es infinitamente más barato que un dato cruzado."""
    with pytest.raises(ErrorValidacion) as exc:
        cch.clave_de("ajustes", "sla")
    assert exc.value.error_code == "cache.sin_tenant"


def test_una_entrada_global_no_admite_tenant() -> None:
    with pytest.raises(ErrorValidacion) as exc:
        cch.clave_de("metadatos", "paises", tenant_id=uuid4(), global_=True)
    assert exc.value.error_code == "cache.global_con_tenant"


def test_un_espacio_de_nombres_no_declarado_se_rechaza() -> None:
    """Con el espacio libre, cada sitio inventa el suyo y al mes nadie sabe qué
    hay en la caché ni qué purga cada cosa."""
    with pytest.raises(ErrorValidacion) as exc:
        cch.clave_de("lo_que_sea", "x", tenant_id=uuid4())
    assert exc.value.error_code == "cache.espacio_desconocido"


def test_las_partes_se_limpian_para_que_no_colisionen() -> None:
    """Un valor con dos puntos podría partir la clave y hacer que dos entradas
    distintas compartan sitio."""
    t = uuid4()
    a = cch.clave_de("consulta", "a:b", "c", tenant_id=t)
    b = cch.clave_de("consulta", "a", "b:c", tenant_id=t)
    assert a != b


def test_guardar_y_leer(monkeypatch: pytest.MonkeyPatch) -> None:
    from crmcore.cache.base import fijar, obtener

    t = uuid4()
    fijar("conteo", "leads", valor=42, tenant_id=t)
    assert obtener("conteo", "leads", tenant_id=t) == 42


def test_lo_guardado_por_un_tenant_no_lo_lee_el_otro() -> None:
    from crmcore.cache.base import fijar, obtener

    a, b = uuid4(), uuid4()
    fijar("conteo", "leads", valor=42, tenant_id=a)
    assert obtener("conteo", "leads", tenant_id=b) is None


def test_purgar_un_tenant_invalida_todo_lo_suyo_de_golpe() -> None:
    from crmcore.cache.base import fijar, obtener

    t = uuid4()
    for i in range(5):
        fijar("consulta", f"q{i}", valor=i, tenant_id=t)

    cch.purgar_tenant(t)

    assert all(obtener("consulta", f"q{i}", tenant_id=t) is None for i in range(5))


def test_purgar_un_tenant_no_toca_a_los_demas() -> None:
    from crmcore.cache.base import fijar, obtener

    a, b = uuid4(), uuid4()
    fijar("consulta", "q", valor="de a", tenant_id=a)
    fijar("consulta", "q", valor="de b", tenant_id=b)

    cch.purgar_tenant(a)

    assert obtener("consulta", "q", tenant_id=a) is None
    assert obtener("consulta", "q", tenant_id=b) == "de b"


def test_la_purga_es_o1_no_recorre_las_claves() -> None:
    """Recorrer el espacio de claves sería O(N) sobre toda la instancia y, con
    `KEYS`, además bloquearía a Redis entero: un cliente dándose de baja
    congelaría el sistema para todos los demás.

    Se comprueba por su efecto observable: purgar solo cambia la generación, y
    las entradas siguen físicamente ahí hasta que el TTL las recoja.
    """
    from crmcore.cache.base import fijar, get_cache

    t = uuid4()
    fijar("consulta", "q", valor=1, tenant_id=t)
    antes = len(get_cache()._datos)  # type: ignore[attr-defined]

    generacion = cch.purgar_tenant(t)

    assert generacion == 1
    assert len(get_cache()._datos) == antes  # type: ignore[attr-defined]


def test_el_ttl_se_capa_contra_el_maximo() -> None:
    """Una entrada con un TTL enorme mantiene ocupada la memoria de lo que una
    purga ya invalidó — la purga no borra: hace inalcanzable."""
    from crmcore.cache.base import fijar, get_cache
    from crmcore.config import get_settings

    t = uuid4()
    fijar("consulta", "larga", valor=1, ttl_s=10_000_000, tenant_id=t)
    caduca, _ = get_cache()._datos[cch.clave_de("consulta", "larga", tenant_id=t)]  # type: ignore[attr-defined]

    import time

    assert caduca - time.monotonic() <= get_settings().cache_ttl_max_s + 1


def test_una_entrada_caducada_se_retira_al_leerla() -> None:
    """Sin esto, una clave que nadie vuelve a pedir se queda en memoria hasta que
    el proceso muere."""
    from crmcore.cache.base import fijar, get_cache, obtener

    t = uuid4()
    fijar("prueba", "efimera", valor=1, ttl_s=1, tenant_id=t)
    clave = cch.clave_de("prueba", "efimera", tenant_id=t)
    get_cache()._datos[clave] = (0.0, 1)  # type: ignore[attr-defined]

    assert obtener("prueba", "efimera", tenant_id=t) is None
    assert clave not in get_cache()._datos  # type: ignore[attr-defined]


# ── Almacén de ficheros ───────────────────────────────────────────────────


@pytest.fixture
def almacen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    import os

    from crmcore.almacen import reset_almacen
    from crmcore.config import limpiar_cache_settings

    monkeypatch.setitem(os.environ, "STORAGE_LOCAL_PATH", str(tmp_path / "almacen"))
    limpiar_cache_settings()
    reset_almacen()
    yield
    reset_almacen()
    limpiar_cache_settings()


def test_cada_tenant_escribe_bajo_su_propio_prefijo(db: Any, tenant_id: UUID, almacen: Any) -> None:
    from crmcore.datos import adjuntos as adj

    fila = adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre="x.pdf",
        datos=b"contenido",
    )
    assert fila.uri.startswith(f"local://{tenant_id}/")


def test_purgar_un_tenant_borra_sus_ficheros_y_solo_los_suyos(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, almacen: Any
) -> None:
    """Es lo que hace que la baja de un cliente sea de verdad. Y funciona porque
    el prefijo es obligatorio: sin él habría que recorrer la tabla de adjuntos, y
    lo que no estuviera en ella se quedaría en el almacén para siempre."""
    from crmcore.almacen import get_almacen, purgar_tenant
    from crmcore.datos import adjuntos as adj

    mio = adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre="mio.pdf",
        datos=b"del primero",
    )
    ajeno = adj.subir(
        db,
        tenant_id=otro_tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre="ajeno.pdf",
        datos=b"del segundo",
    )

    assert purgar_tenant(str(tenant_id)) == 1

    assert not get_almacen().existe(mio.uri)
    assert get_almacen().existe(ajeno.uri)


def test_purgar_un_prefijo_con_traversal_se_rechaza(tmp_path: Path) -> None:
    """De todas las operaciones del almacén, esta es en la que equivocarse es
    irreversible."""
    from crmcore.almacen import AlmacenLocal

    a = AlmacenLocal(tmp_path / "base")
    (tmp_path / "fuera").mkdir()
    (tmp_path / "fuera" / "importante.txt").write_text("no tocar")

    with pytest.raises(ValueError):
        a.borrar_prefijo("../fuera")
    assert (tmp_path / "fuera" / "importante.txt").exists()


def test_purgar_un_prefijo_que_no_existe_no_es_un_error(tmp_path: Path) -> None:
    from crmcore.almacen import AlmacenLocal

    assert AlmacenLocal(tmp_path / "base").borrar_prefijo("nadie") == 0


# ── Registro de invalidadores ─────────────────────────────────────────────


@pytest.fixture
def registro_aislado() -> Any:
    """Guarda el registro y lo restaura.

    Vaciarlo sin más lo dejaría vacío para el resto de la sesión: los
    invalidadores se apuntan al importar su módulo, y un módulo ya importado no
    vuelve a ejecutarse. Las pruebas siguientes pasarían sin comprobar nada.
    """
    from crmcore.cache import registro

    guardado = registro.instantanea()
    yield registro
    registro.restaurar(guardado)


def test_purgar_llama_a_los_invalidadores_registrados(registro_aislado: Any) -> None:
    """La purga vacía la caché compartida; las cachés en proceso de cada módulo
    solo se enteran por el registro. Sin él, dar de baja a un cliente dejaba a
    cada réplica sirviendo sus ajustes desde memoria como si nada."""
    registro_aislado.limpiar_registro()
    llamados: list[str | None] = []
    registro_aislado.registrar("prueba", lambda t: llamados.append(t))

    t = uuid4()
    cch.purgar_tenant(t)

    assert llamados == [str(t)]


def test_un_invalidador_que_falla_no_detiene_a_los_demas(registro_aislado: Any) -> None:
    """Si el segundo de cinco revienta, los tres siguientes seguirían sirviendo
    dato purgado — que es justo lo que esto viene a evitar."""
    registro_aislado.limpiar_registro()
    llamados: list[str] = []

    def revienta(_t: str | None) -> None:
        raise RuntimeError("el de en medio")

    registro_aislado.registrar("uno", lambda t: llamados.append("uno"))
    registro_aislado.registrar("dos", revienta)
    registro_aislado.registrar("tres", lambda t: llamados.append("tres"))

    bien = registro_aislado.invalidar_todos("x")

    assert sorted(llamados) == ["tres", "uno"]
    assert bien == 2


def test_los_ajustes_registran_su_invalidador() -> None:
    """Es el consumidor real: la jerarquía de ajustes cachea en proceso."""
    from crmcore.cache import registro
    from crmcore.runtime import settings as rt  # noqa: F401 — al importarse, se registra

    assert "runtime.settings" in registro._invalidadores
