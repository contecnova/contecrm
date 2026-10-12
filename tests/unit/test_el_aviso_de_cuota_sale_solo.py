"""Un aviso que hay que ir a mirar no es un aviso (`CRM-00.01.06.02`).

Cuarto barrido de la familia: 92 funciones sin llamante, 20 ajustes sin lector,
6 permisos que no gobernaban nada, y ahora los eventos. La pregunta útil no es
«qué se emite sin consumidor» —hay seis consumidores comodín, así que todo tiene
uno— sino **qué está declarado en el contrato publicado y no lo emite nadie**:
un integrador se suscribe y no le llega nada nunca.

Medido el 11-10-2026: 3 de 118 tipos declarados. `quota.threshold.reached` era
el grave, y es el patrón de siempre con las dos mitades construidas y sin unir:

  · `aviso_de_cercania` calcula desde hace tiempo si un tenant se acerca a un
    tope, y su resultado viajaba como un campo más del panel de consumo;
  · el evento está declarado en el Anexo B desde el principio;
  · nada los unía, así que el aviso **sólo existía si alguien abría la
    pantalla**.

Y el manual de usuario promete lo contrario, por escrito: «cuando te acercas a
uno se avisa antes, no cuando ya no cabe nada».
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

RAIZ = Path(__file__).resolve().parents[2]
DECLARAN = {"dominio.py", "catalogo.py"}

# ── Lo declarado y nunca emitido ──────────────────────────────────────────
#
# Lista CERRADA y nominal: sólo puede encoger.
#
#   11-10-2026  3  medición inicial
#   11-10-2026  2  `quota.threshold.reached` pasa a emitirse desde el barrido
#   12-10-2026  0  los dos de IA se emiten desde donde el hecho ocurre
#
# Está VACÍA, y vaciarla no es el final: el recorrido sigue puesto, y lo que
# vuelva a declararse sin emisor cae en `test_ningun_evento_nuevo...` sin que
# nadie tenga que acordarse.
SIN_EMISOR_HOY: set[str] = set()


def _declarados() -> dict[str, tuple[str, str]]:
    """Tipo → (constante, fichero), leídos del AST de quien los registra."""
    salida: dict[str, tuple[str, str]] = {}
    for carpeta in ("packages", "services"):
        for fichero in (RAIZ / carpeta).rglob("*.py"):
            if "__pycache__" in str(fichero):
                continue
            try:
                arbol = ast.parse(fichero.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:  # pragma: no cover
                continue
            for nodo in ast.walk(arbol):
                if not (
                    isinstance(nodo, ast.Assign)
                    and isinstance(nodo.value, ast.Call)
                    and getattr(nodo.value.func, "id", "") == "registrar"
                ):
                    continue
                for arg in nodo.value.args:
                    if isinstance(arg, ast.Call) and getattr(arg.func, "id", "") == "TipoEvento":
                        tipo = next(
                            (
                                k.value.value
                                for k in arg.keywords
                                if k.arg == "tipo" and isinstance(k.value, ast.Constant)
                            ),
                            None,
                        )
                        const = nodo.targets[0].id if isinstance(nodo.targets[0], ast.Name) else ""
                        if tipo:
                            salida[tipo] = (const, fichero.name)
    return salida


def _corpus() -> str:
    """Todo el producto menos los dos ficheros que declaran los tipos.

    Menos ésos porque son los que los nombran: contarlos haría que todo evento
    estuviera «emitido» por el hecho de estar declarado.
    """
    trozos = []
    for carpeta, exts in (
        ("services", (".py",)),
        ("packages", (".py",)),
        ("frontend/src", (".ts", ".tsx")),
    ):
        base = RAIZ / carpeta
        if not base.exists():
            continue
        for fichero in base.rglob("*"):
            if (
                fichero.suffix in exts
                and "__pycache__" not in str(fichero)
                and fichero.name not in DECLARAN
            ):
                trozos.append(fichero.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(trozos)


def _sin_emisor() -> set[str]:
    """Se busca la CADENA y también el nombre de la constante.

    Por el texto y no por el AST de las llamadas a `emitir`: la primera versión
    de este recorrido miraba el primer argumento posicional y marcó nueve, de
    los que seis eran falsos positivos — `opportunity.won` se emite dentro de un
    condicional y `activity.reminder` con argumento por nombre. Un recorrido que
    acusa de más no lo vuelve a mirar nadie.
    """
    corpus = _corpus()
    return {
        tipo
        for tipo, (const, _f) in _declarados().items()
        if tipo not in corpus and (not const or const not in corpus)
    }


def test_el_recorrido_mira_de_verdad() -> None:
    declarados = _declarados()
    assert len(declarados) >= 100, f"solo se ven {len(declarados)} tipos declarados"
    # Y uno que evidentemente se emite, para saber que el corpus se lee.
    assert "opportunity.won" not in _sin_emisor()


def test_ningun_evento_nuevo_se_declara_sin_que_nadie_lo_emita() -> None:
    """Un tipo en el contrato publicado que no emite nadie es una suscripción
    que no recibe nada: el integrador lo descubre esperando."""
    nuevos = sorted(_sin_emisor() - SIN_EMISOR_HOY)
    assert not nuevos, "Eventos declarados en el contrato que no emite nadie:\n  " + "\n  ".join(
        nuevos
    )


def test_los_que_se_arreglan_salen_de_la_lista() -> None:
    sobran = sorted(SIN_EMISOR_HOY - _sin_emisor())
    assert not sobran, "Ya se emiten y siguen apuntados:\n  " + "\n  ".join(sobran)


# ── El aviso, por el camino de verdad ─────────────────────────────────────


@pytest.fixture
def con_tope(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> Any:
    """Un tenant con un tope bajo y un medidor que lo roza."""
    from crmcore import consumo
    from crmcore.runtime import settings as rt

    rt.fijar(db, "quota_registros", 10, ambito="tenant", ambito_id=str(tenant_id))
    db.flush()
    consumo.limpiar_medidores()
    consumo.registrar_medidor("registros", lambda _db, _t: (9, "quota_registros"))
    try:
        yield
    finally:
        consumo.limpiar_medidores()


def _uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.mark.db
def test_al_acercarse_al_tope_se_emite_el_hecho(db: Any, tenant_id: UUID, con_tope: Any) -> None:
    """**Es el circuito que faltaba.** El cálculo estaba, el evento estaba
    declarado, y nada los unía."""
    from crmcore.consumo import avisar_de_los_que_se_acercan

    uow = _uow(db, tenant_id)
    salida = avisar_de_los_que_se_acercan(uow)

    assert salida["avisadas"] == 1
    tipos = [e.get("tipo") if isinstance(e, dict) else e.type for e in uow._pendientes]
    assert "quota.threshold.reached" in tipos, tipos


@pytest.mark.db
def test_lejos_del_tope_no_se_avisa(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Avisar de lo que va holgado es cómo se deja de leer los avisos."""
    from crmcore import consumo
    from crmcore.consumo import avisar_de_los_que_se_acercan
    from crmcore.runtime import settings as rt

    rt.fijar(db, "quota_registros", 1_000, ambito="tenant", ambito_id=str(tenant_id))
    db.flush()
    consumo.limpiar_medidores()
    consumo.registrar_medidor("registros", lambda _db, _t: (3, "quota_registros"))
    try:
        uow = _uow(db, tenant_id)
        assert avisar_de_los_que_se_acercan(uow)["avisadas"] == 0
        assert uow._pendientes == []
    finally:
        consumo.limpiar_medidores()


@pytest.mark.db
def test_el_hecho_lleva_con_qué_decidir(db: Any, tenant_id: UUID, con_tope: Any) -> None:
    """Un aviso que dice «te acercas» y no dice a qué ni cuánto queda obliga a
    entrar a mirarlo, que es justo lo que esto viene a evitar."""
    from crmcore.consumo import avisar_de_los_que_se_acercan

    uow = _uow(db, tenant_id)
    avisar_de_los_que_se_acercan(uow)
    evento = uow._pendientes[0]
    datos = evento["data"] if isinstance(evento, dict) else evento.data
    for campo in ("tenant_id", "cuota", "consumido", "limite", "pct", "metrica", "periodo"):
        assert campo in datos, f"falta «{campo}»: {sorted(datos)}"
    assert datos["consumido"] == 9
    assert datos["limite"] == 10


@pytest.mark.db
def test_la_clave_de_deduplicacion_lleva_el_periodo(
    db: Any, tenant_id: UUID, con_tope: Any
) -> None:
    """Es lo que hace que avisar sea una vez por periodo y no una por vuelta del
    barrido: el tenant sigue por encima del umbral durante días."""
    from crmcore.consumo import avisar_de_los_que_se_acercan
    from crmcore.cuotas import periodo_actual

    uow = _uow(db, tenant_id)
    avisar_de_los_que_se_acercan(uow)
    evento = uow._pendientes[0]
    clave = evento["dedup_key"] if isinstance(evento, dict) else evento.dedup_key
    assert periodo_actual(db) in clave, clave
    assert str(tenant_id) in clave


def test_el_barrido_del_nucleo_lo_llama() -> None:
    """Sin llamante, esto sería una función más escrita y sin enchufar — que es
    exactamente de lo que viene este barrido."""
    fuente = (RAIZ / "packages/crmcore/crmcore/service.py").read_text(encoding="utf-8")
    cuerpo = fuente.split("def _barridos_del_nucleo(")[1].split("\ndef ")[0]
    assert "avisar_de_los_que_se_acercan" in cuerpo
    assert "aviso_de_cuotas" in cuerpo


def test_la_lista_de_tenants_sale_de_su_propia_tabla() -> None:
    """No se le pide a `tenancy`: es de otro servicio y no se lee desde aquí.
    Además la buena es más corta — un tenant sin cuotas fijadas no puede
    acercarse a ningún tope."""
    fuente = (RAIZ / "packages/crmcore/crmcore/service.py").read_text(encoding="utf-8")
    cuerpo = fuente.split("def _tenants_con_cuota(")[1].split("\n    def ")[0]
    assert "AjusteRuntime" in cuerpo
    assert "quota_%" in cuerpo
