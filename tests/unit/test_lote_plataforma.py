"""Empuje sin webhook, cacheo invalidable, consultas degradadas y versionado de
la configuración (CRM-00.02.02.10, CRM-00.02.04.05, CRM-00.06.01.07,
CRM-00.01.04.02).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

# ── Empuje sin exponer endpoint ───────────────────────────────────────────


@pytest.fixture(autouse=True)
def _limpio() -> Any:
    from crmcore.obs import consultas

    from services.gateway import empuje

    empuje.reiniciar()
    consultas.reiniciar()
    yield
    empuje.reiniciar()
    consultas.reiniciar()


def test_se_reanuda_desde_donde_se_quedo() -> None:
    """Sin esto, cada corte de red —que en un móvil es cada túnel— pierde los
    eventos de ese hueco y el cliente no sabe cuántos ni cuáles."""
    from services.gateway import empuje

    tenant = uuid4()
    primero = empuje.publicar(tenant, {"tipo": "cuenta.creada"})
    empuje.publicar(tenant, {"tipo": "cuenta.actualizada"})

    pendientes = empuje.pendientes(tenant, desde=primero)
    assert [e["tipo"] for _, e in pendientes] == ["cuenta.actualizada"]


def test_se_avisa_del_hueco_en_vez_de_saltarlo() -> None:
    """Un cliente que cree haberlo recibido todo y no lo ha recibido toma
    decisiones sobre datos incompletos."""
    from services.gateway import empuje

    tenant = uuid4()
    for _ in range(600):  # la cola guarda 500
        empuje.publicar(tenant, {"tipo": "x"})

    assert empuje.hueco(tenant, desde=5) is True
    assert empuje.hueco(tenant, desde=599) is False


def test_un_tenant_no_ve_los_eventos_de_otro() -> None:
    from services.gateway import empuje

    uno, otro = uuid4(), uuid4()
    empuje.publicar(uno, {"tipo": "cuenta.creada"})
    assert empuje.pendientes(otro, desde=0) == []


# ── Caché invalidable por evento ──────────────────────────────────────────


@pytest.mark.db
def test_la_clave_cambia_cuando_pasa_el_evento_que_la_invalida(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una caché con caducidad sirve una respuesta vieja todo el plazo que le
    quede, y el usuario ve su propio cambio desaparecer."""
    from crmcore.cache.respuestas import Politica, clave, invalidar_por_evento

    politica = Politica(nombre="listado_cuentas", ttl_s=60, invalida_con=("cuenta.creada",))
    usuario = uuid4()
    antes = clave(politica, tenant_id=tenant_id, usuario_id=usuario, partes={"pagina": 1})

    invalidar_por_evento("cuenta.creada", tenant_id)

    despues = clave(politica, tenant_id=tenant_id, usuario_id=usuario, partes={"pagina": 1})
    assert antes != despues


@pytest.mark.db
def test_un_evento_que_no_invalida_esta_politica_no_la_toca(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.cache.respuestas import Politica, clave, invalidar_por_evento

    politica = Politica(nombre="listado", ttl_s=60, invalida_con=("cuenta.creada",))
    antes = clave(politica, tenant_id=tenant_id, usuario_id=None, partes={})
    invalidar_por_evento("lead.creado", tenant_id)
    assert clave(politica, tenant_id=tenant_id, usuario_id=None, partes={}) == antes


@pytest.mark.db
def test_dos_usuarios_no_comparten_entrada(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Cachear sin el usuario en la clave sirve a uno lo que otro puede ver: la
    misma fuga que no separar por tenant, pero dentro de casa."""
    from crmcore.cache.respuestas import Politica, clave

    politica = Politica(nombre="listado", ttl_s=60, por_usuario=True)
    uno = clave(politica, tenant_id=tenant_id, usuario_id=uuid4(), partes={})
    otro = clave(politica, tenant_id=tenant_id, usuario_id=uuid4(), partes={})
    assert uno != otro


def test_se_ve_qué_politicas_solo_caducan() -> None:
    """Una caché que se creyó invalidada por evento y solo caduca es la que
    sirve datos viejos sin que nadie entienda por qué."""
    from crmcore.cache.respuestas import Politica, politicas_sin_invalidacion

    politicas = [
        Politica(nombre="con", ttl_s=60, invalida_con=("x",)),
        Politica(nombre="sin", ttl_s=60),
    ]
    assert politicas_sin_invalidacion(politicas) == ["sin"]


# ── Consultas degradadas ──────────────────────────────────────────────────


def test_dos_consultas_iguales_con_valores_distintos_son_la_misma() -> None:
    """Contarlas por separado esconde justo la que se repite."""
    from crmcore.obs.consultas import forma

    a = forma("SELECT * FROM cuentas WHERE id = 42 AND nombre = 'ACME'")
    b = forma("SELECT * FROM cuentas WHERE id = 99 AND nombre = 'OTRA'")
    assert a == b


def test_una_lista_in_no_multiplica_las_formas() -> None:
    """La misma consulta con 3 y con 300 identificadores serían dos formas
    distintas, y la que se repite quedaría repartida entre cientos de filas."""
    from crmcore.obs.consultas import forma

    assert forma("SELECT 1 WHERE id IN (1,2,3)") == forma("SELECT 1 WHERE id IN (7,8,9,10,11)")


def test_se_detecta_la_que_empeora_con_el_volumen() -> None:
    """Una consulta sana tarda parecido con mil filas y con cien mil porque usa
    índice; una que no lo usa tarda proporcionalmente más."""
    from crmcore.obs import consultas

    # Coste por fila constante: sana.
    for filas in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100) * 3:
        consultas.anotar("SELECT * FROM sana WHERE x = 1", filas * 0.1, filas)
    # Coste por fila creciente: degradada.
    for filas in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100) * 3:
        consultas.anotar("SELECT * FROM mala WHERE y = 1", filas * filas * 0.01, filas)

    malas = [d["consulta"] for d in consultas.degradadas()]
    assert any("mala" in c for c in malas)
    assert not any("sana" in c for c in malas)


def test_el_informe_ordena_por_tiempo_total_y_no_por_media() -> None:
    """Una consulta de 2 ms que corre cien mil veces cuesta más que una de 900
    ms que corre dos, y es la que hay que arreglar primero."""
    from crmcore.obs import consultas

    for _ in range(1000):
        consultas.anotar("SELECT a", 2.0, 1)
    consultas.anotar("SELECT b", 900.0, 1)

    assert "SELECT a" in consultas.informe()[0]["consulta"]


# ── Versionado de la configuración ────────────────────────────────────────


@pytest.mark.db
def test_cada_cambio_guarda_el_valor_anterior(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Con solo el nuevo, deshacer exige reconstruir el histórico hacia atrás y
    confiar en que no falte ningún apunte."""
    from crmcore.runtime import settings as rt
    from crmcore.runtime.versiones import historial

    rt.fijar(db, "idioma", "es", ambito="tenant", ambito_id=str(tenant_id))
    rt.fijar(db, "idioma", "fr", ambito="tenant", ambito_id=str(tenant_id))
    db.flush()

    apuntes = historial(db, tenant_id, clave="idioma")
    assert apuntes[0]["antes"] == "es"
    assert apuntes[0]["despues"] == "fr"


@pytest.mark.db
def test_volver_atras_es_un_cambio_mas_y_no_un_borrado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Hacer desaparecer el apunte original dejaría el histórico contando una
    historia que no pasó."""
    from crmcore.runtime import settings as rt
    from crmcore.runtime.versiones import historial, volver_a

    rt.fijar(db, "idioma", "es", ambito="tenant", ambito_id=str(tenant_id))
    rt.fijar(db, "idioma", "fr", ambito="tenant", ambito_id=str(tenant_id))
    db.flush()
    version = historial(db, tenant_id, clave="idioma")[0]

    volver_a(db, UUID(version["id"]), tenant_id=tenant_id)
    db.flush()

    apuntes = historial(db, tenant_id, clave="idioma")
    assert apuntes[0]["tipo"] == "vuelta_atras"
    assert len(apuntes) >= 3


@pytest.mark.db
def test_el_diff_no_saca_lo_que_acabo_igual_que_empezo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Alguien que subió un umbral y lo bajó en la misma tarde no cambió nada, y
    sacarlo manda a investigar un cambio que no existe."""
    from crmcore.runtime import settings as rt
    from crmcore.runtime.versiones import diff

    desde = datetime.now(timezone.utc) - timedelta(minutes=5)
    rt.fijar(db, "idioma", "fr", ambito="tenant", ambito_id=str(tenant_id))
    rt.fijar(db, "idioma", "es", ambito="tenant", ambito_id=str(tenant_id))
    rt.fijar(db, "idioma", "fr", ambito="tenant", ambito_id=str(tenant_id))
    db.flush()

    cambios = diff(db, tenant_id, desde=desde)
    # De None a "fr": sí cambió. Lo que no sale es un ajuste que volvió a su
    # valor de partida.
    assert [c["clave"] for c in cambios] == ["idioma"]
    assert cambios[0]["despues"] == "fr"


@pytest.mark.db
def test_el_historial_no_depende_de_como_estén_colocadas_las_filas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Varios cambios en UNA transacción llevan el mismo `created_at`.

    `now()` de Postgres devuelve la hora de inicio de la transacción, no la del
    momento: un lote de ajustes de plataforma —que es literalmente lo que este
    fichero prueba— escribe todos sus apuntes con la marca idéntica. Con el
    empate sin resolver, el orden lo decide la colocación física de las filas, y
    eso depende de lo que haya en la tabla.

    Medido el 12-10-2026 con la suite entera en un proceso: el histórico salía
    **al revés** y `volver_a` deshacía el cambio equivocado. En aislamiento
    pasaba, porque con la tabla casi vacía las filas salen en el orden en que se
    insertaron.

    Lo que se comprueba aquí no es el orden de dos apuntes: es que **los tres**
    lleven la misma marca de tiempo y aun así salgan en orden. Con dos, un
    desempate roto acierta la mitad de las veces.

    **Esta prueba sola no basta, y conviene saberlo.** Quitando el desempate
    sigue pasando en aislamiento, porque con la tabla casi vacía Postgres
    devuelve las filas en el orden en que se insertaron. Lo que de verdad fija
    el arreglo es `test_el_orden_del_historial_es_total`, que mira que la
    consulta no deje empates posibles. Ésta es la que reproduce el síntoma; la
    otra es la que impide que vuelva.
    """
    from crmcore.runtime import settings as rt
    from crmcore.runtime.versiones import historial

    for valor in ("es", "fr", "de"):
        rt.fijar(db, "idioma", valor, ambito="tenant", ambito_id=str(tenant_id))
    db.flush()

    apuntes = historial(db, tenant_id, clave="idioma")
    marcas = {a["cuando"] for a in apuntes}
    assert len(marcas) == 1, (
        "los tres apuntes tendrían que compartir `created_at` —es la hora de "
        f"inicio de la transacción—; si no, esta prueba no comprueba nada: {marcas}"
    )
    assert [(a["antes"], a["despues"]) for a in apuntes] == [
        ("fr", "de"),
        ("es", "fr"),
        (None, "es"),
    ], apuntes


@pytest.mark.db
def test_deshacer_con_varios_cambios_en_la_misma_transaccion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La consecuencia, que es la que se ve: `volver_a` toma el apunte del
    histórico, y con el orden al revés deshacía el PRIMER cambio — cuyo valor
    anterior es `None`, que ningún ajuste admite."""
    from crmcore.runtime import settings as rt
    from crmcore.runtime.versiones import historial, volver_a

    for valor in ("es", "fr", "de"):
        rt.fijar(db, "idioma", valor, ambito="tenant", ambito_id=str(tenant_id))
    db.flush()

    ultimo = historial(db, tenant_id, clave="idioma")[0]
    volver_a(db, UUID(ultimo["id"]), tenant_id=tenant_id)
    db.flush()

    assert rt.efectivo("idioma", db) == "fr", "deshacer el último cambio no ha vuelto a «fr»"


@pytest.mark.db
def test_el_orden_del_historial_es_total(db: Any) -> None:
    """La consulta no puede dejar empates, pase lo que pase con las filas.

    Es lo único que se puede comprobar de forma determinista: hacer que Postgres
    devuelva un empate en el orden «malo» depende de cómo estén colocadas las
    filas, y eso no se controla desde una prueba — por eso el síntoma sólo salía
    con la suite entera y la tabla llena.

    Así que se mira el mecanismo: que el `ORDER BY` incluya una columna **única**
    detrás de `created_at`. Con eso el orden es total y deja de depender de nada
    más.
    """
    from crmcore.runtime.versiones import VersionAjuste, historial

    compilada = str(
        historial.__globals__["select"](VersionAjuste)
        .order_by(VersionAjuste.created_at.desc(), VersionAjuste.id.desc())
        .compile(db.bind)
    )
    assert "ORDER BY" in compilada

    # Y lo que importa: la consulta de verdad ordena por las dos.
    import inspect

    fuente = inspect.getsource(historial)
    assert "created_at.desc()" in fuente and "id.desc()" in fuente, (
        "el histórico ha vuelto a ordenar sólo por `created_at`, que empata "
        "entre cambios de la misma transacción"
    )

    # El `diff` usa la misma tabla y colapsa por clave: con empate se quedaría
    # con el primero que saliera en vez de con el último.
    from crmcore.runtime.versiones import diff

    assert "VersionAjuste.id" in inspect.getsource(diff)
