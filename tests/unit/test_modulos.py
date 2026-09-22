"""Módulos verticales (CRM-00.04.04).

Lo que decide si los módulos funcionan a los dos años es la **actualización**: el
cliente habrá tocado lo que el módulo trajo, y una actualización que pise sus
cambios se deja de instalar. La mitad de estas pruebas van detrás de eso.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado

from services.metadata import modulos as mod

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def logistica() -> dict[str, Any]:
    return json.loads((RAIZ / "docs" / "modulos" / "logistica.json").read_text())


def _simple(**kw: Any) -> dict[str, Any]:
    base = {
        "formato": 1,
        "clave": "demo",
        "nombre": "Demo",
        "version": "1.0.0",
        "descripcion": "Un módulo de prueba",
        "contenido": {
            "objetos": [{"clave": "cosa", "gobierno": "fijo", "etiqueta": "Cosa"}],
            "plantillas": [
                {"clave": "aviso", "gobierno": "editable", "asunto": "Hola", "cuerpo": "…"}
            ],
            "datos_semilla": [{"clave": "inicial", "gobierno": "semilla", "valor": 1}],
            "pantallas": [{"clave": "lista", "gobierno": "editable", "titulo": "Cosas"}],
        },
    }
    base.update(kw)
    return base


# ── El módulo de ejemplo (CRM-00.04.04.11) ────────────────────────────────


def test_el_modulo_de_ejemplo_es_valido(logistica: dict[str, Any]) -> None:
    """Un ejemplo que no valida no sirve de plantilla para escribir los demás."""
    avisos = mod.validar_manifiesto(logistica)
    # Sin firmar es lo único que se le reprocha, y es correcto: va en el repo.
    assert avisos == [
        "El módulo no está firmado: no se puede comprobar que sea el que escribió su autor."
    ]


def test_el_ejemplo_trae_lo_que_caracteriza_un_sector(logistica: dict[str, Any]) -> None:
    """Objetos, taxonomía de incidencias, estados, flujo, pantallas y conector:
    si faltara alguno, el módulo dejaría un hueco que el cliente tendría que
    rellenar a mano — que es lo que los módulos vienen a evitar."""
    contenido = logistica["contenido"]
    assert {"objetos", "taxonomias", "estados", "flujos", "pantallas", "conectores"} <= set(
        contenido
    )
    assert contenido["pantallas"][1]["audiencia"] == "cliente"


# ── Manifiesto (CRM-00.04.04.01) ──────────────────────────────────────────


def test_una_seccion_desconocida_se_rechaza() -> None:
    """Ignorarla instalaría un módulo a medias que parece completo, y el cliente
    descubriría lo que falta el día que lo necesite."""
    with pytest.raises(ErrorValidacion) as e:
        mod.validar_manifiesto(_simple(contenido={"inventada": []}))
    assert e.value.error_code == "metadata.seccion_desconocida"


def test_una_clave_de_modulo_rara_no_pasa() -> None:
    """Va prefijando todo lo que trae y acaba en nombres de tabla y de API."""
    with pytest.raises(ErrorValidacion) as e:
        mod.validar_manifiesto(_simple(clave="Módulo Raro"))
    assert e.value.error_code == "metadata.clave_modulo_invalida"


def test_un_modulo_sin_version_no_se_admite() -> None:
    """Sin versión no se puede actualizar ni revertir."""
    manifiesto = _simple()
    del manifiesto["version"]
    with pytest.raises(ErrorValidacion) as e:
        mod.validar_manifiesto(manifiesto)
    assert e.value.error_code == "metadata.modulo_sin_version"


def test_lo_dudoso_avisa_en_vez_de_rechazar() -> None:
    """Rechazar por algo dudoso deja módulos correctos sin instalar."""
    manifiesto = _simple()
    del manifiesto["descripcion"]
    manifiesto["contenido"].pop("pantallas")
    avisos = mod.validar_manifiesto(manifiesto)
    assert any("descripción" in a for a in avisos)
    assert any("no aparecerán en el front" in a for a in avisos)


# ── Espacio de nombres (CRM-00.04.04.03) ──────────────────────────────────


def test_todo_va_prefijado() -> None:
    """Sin prefijo, dos módulos que llamen «envio» a cosas distintas se pisan, y
    el segundo que se instale rompe al primero."""
    assert mod.prefijar("logistica", "expedicion") == "logistica__expedicion"
    # Prefijar dos veces no duplica el prefijo.
    assert mod.prefijar("logistica", "logistica__expedicion") == "logistica__expedicion"
    assert mod.desprefijar("logistica", "logistica__expedicion") == "expedicion"


def test_las_versiones_se_comparan_por_numero() -> None:
    """Como texto, «1.10» es menor que «1.9» y una actualización se saltaría sin
    avisar."""
    assert mod._comparar_versiones("1.10.0", "1.9.0") == 1
    assert mod._comparar_versiones("2.0.0", "2.0.0") == 0
    assert mod._comparar_versiones("1.0.0", "1.0.1") == -1


# ── Instalar (CRM-00.04.04.02) ────────────────────────────────────────────


@pytest.mark.db
def test_instalar_simula_por_defecto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Instalar es un cambio de modelo de datos en producción, y el error más
    caro es pulsar el botón creyendo que aún se estaba mirando."""
    salida = mod.instalar(uow, _simple())
    db.flush()
    assert salida["simulado"] is True
    assert mod.instalados(db, tenant_id) == []


@pytest.mark.db
def test_instalar_de_verdad_deja_sus_elementos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    salida = mod.instalar(uow, _simple(), aplicar=True)
    db.flush()
    assert salida["creados"] == 4
    assert mod.instalados(db, tenant_id)[0]["clave"] == "demo"


@pytest.mark.db
def test_no_se_instala_dos_veces(db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any) -> None:
    mod.instalar(uow, _simple(), aplicar=True)
    db.flush()
    with pytest.raises(Conflicto) as e:
        mod.instalar(uow, _simple(), aplicar=True)
    assert e.value.error_code == "metadata.modulo_ya_instalado"


# ── Dependencias (CRM-00.04.04.05) ────────────────────────────────────────


@pytest.mark.db
def test_faltan_todas_las_dependencias_a_la_vez(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Instalar, fallar, corregir y repetir cinco veces es la experiencia que
    hace que nadie quiera instalar módulos."""
    manifiesto = _simple(requiere={"nucleo": 99, "modulos": {"base": "1.0.0", "otro": "2.0.0"}})
    salida = mod.instalar(uow, manifiesto, aplicar=True)
    assert salida["simulado"] is True
    assert len(salida["dependencias_que_faltan"]) == 3
    assert salida["se_puede_instalar"] is False


@pytest.mark.db
def test_una_version_insuficiente_de_otro_modulo_se_detecta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    mod.instalar(uow, _simple(clave="base", version="1.0.0"), aplicar=True)
    db.flush()
    salida = mod.instalar(
        uow,
        _simple(clave="encima", requiere={"modulos": {"base": "2.0.0"}}),
        aplicar=True,
    )
    assert "al menos la 2.0.0" in salida["dependencias_que_faltan"][0]


# ── Actualizar sin pisar al cliente (CRM-00.04.04.04) ─────────────────────


@pytest.mark.db
def test_lo_editable_que_el_cliente_toco_no_se_toca(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Es suyo desde que lo tocó, y ese es el trato."""
    mod.instalar(uow, _simple(), aplicar=True)
    db.flush()
    mod.marcar_modificado(db, tenant_id, modulo="demo", seccion="plantillas", clave="demo__aviso")
    db.flush()

    nueva = _simple(version="1.1.0")
    nueva["contenido"]["plantillas"][0]["asunto"] = "Otra cosa"
    salida = mod.actualizar(uow, nueva, aplicar=True)
    db.flush()

    from sqlalchemy import select

    fila = db.execute(
        select(mod.ElementoModulo).where(mod.ElementoModulo.clave == "demo__aviso")
    ).scalar_one()
    assert fila.definicion["asunto"] == "Hola"
    assert any(r["clave"] == "demo__aviso" for r in salida["respetados"])


@pytest.mark.db
def test_lo_fijo_que_el_cliente_toco_avisa_y_no_se_pisa_sin_pedirlo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Pisarlo en silencio es cómo se pierde la confianza en las
    actualizaciones."""
    mod.instalar(uow, _simple(), aplicar=True)
    db.flush()
    mod.marcar_modificado(db, tenant_id, modulo="demo", seccion="objetos", clave="demo__cosa")
    db.flush()

    nueva = _simple(version="1.1.0")
    nueva["contenido"]["objetos"][0]["etiqueta"] = "Cosa nueva"

    plan = mod.actualizar(uow, nueva)
    assert plan["conflictos"][0]["clave"] == "demo__cosa"

    mod.actualizar(uow, nueva, aplicar=True)
    db.flush()
    from sqlalchemy import select

    fila = db.execute(
        select(mod.ElementoModulo).where(mod.ElementoModulo.clave == "demo__cosa")
    ).scalar_one()
    assert fila.definicion["etiqueta"] == "Cosa"

    mod.actualizar(uow, _simple(version="1.2.0"), aplicar=True, forzar_fijos=True)
    db.flush()
    db.refresh(fila)
    assert fila.modificado_por_cliente is False


@pytest.mark.db
def test_lo_semilla_se_crea_una_vez_y_ya_esta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Actualizarlo sería reescribir datos que el cliente lleva un año usando."""
    mod.instalar(uow, _simple(), aplicar=True)
    db.flush()
    nueva = _simple(version="1.1.0")
    nueva["contenido"]["datos_semilla"][0]["valor"] = 999
    salida = mod.actualizar(uow, nueva, aplicar=True)
    db.flush()

    from sqlalchemy import select

    fila = db.execute(
        select(mod.ElementoModulo).where(mod.ElementoModulo.clave == "demo__inicial")
    ).scalar_one()
    assert fila.definicion["valor"] == 1
    assert any("semilla" in r["motivo"] for r in salida["respetados"])


@pytest.mark.db
def test_lo_que_la_version_nueva_no_trae_queda_huerfano_y_se_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Borrarlo se llevaría por delante los registros que cuelgan de él sin que
    nadie lo hubiera decidido."""
    mod.instalar(uow, _simple(), aplicar=True)
    db.flush()
    nueva = _simple(version="1.1.0")
    nueva["contenido"]["objetos"] = []
    salida = mod.actualizar(uow, nueva, aplicar=True)
    assert salida["huerfanos"][0]["clave"] == "demo__cosa"


@pytest.mark.db
def test_no_se_actualiza_a_una_version_anterior(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    mod.instalar(uow, _simple(version="2.0.0"), aplicar=True)
    db.flush()
    with pytest.raises(Conflicto) as e:
        mod.actualizar(uow, _simple(version="1.0.0"), aplicar=True)
    assert e.value.error_code == "metadata.version_no_posterior"


@pytest.mark.db
def test_actualizar_algo_no_instalado_falla(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    with pytest.raises(NoEncontrado):
        mod.actualizar(uow, _simple(version="2.0.0"), aplicar=True)


# ── Desinstalar (CRM-00.04.04.09) ─────────────────────────────────────────


@pytest.mark.db
def test_desinstalar_dice_que_pasa_con_los_datos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Un «desinstalado correctamente» que deja doscientos mil registros
    huérfanos es peor que no poder desinstalar."""
    mod.instalar(uow, _simple(), aplicar=True)
    db.flush()
    salida = mod.desinstalar(uow, "demo", contar_registros=lambda o: 1234)
    assert salida["simulado"] is True
    assert salida["registros_por_objeto"]["demo__cosa"] == 1234
    assert "CONSERVAN" in salida["que_pasa_con_los_datos"]


@pytest.mark.db
def test_lo_que_no_se_puede_contar_se_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """No se supone que son cero."""
    mod.instalar(uow, _simple(), aplicar=True)
    db.flush()
    salida = mod.desinstalar(uow, "demo")
    assert salida["no_se_han_podido_contar"] == ["demo__cosa"]


@pytest.mark.db
def test_no_se_desinstala_si_otro_modulo_depende(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    mod.instalar(uow, _simple(clave="base"), aplicar=True)
    db.flush()
    mod.instalar(
        uow, _simple(clave="encima", requiere={"modulos": {"base": "1.0.0"}}), aplicar=True
    )
    db.flush()
    salida = mod.desinstalar(uow, "base", aplicar=True)
    assert salida["simulado"] is True
    assert salida["modulos_que_dependen"] == ["encima"]
    assert salida["se_puede_desinstalar"] is False


@pytest.mark.db
def test_desinstalar_de_verdad_quita_los_elementos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    mod.instalar(uow, _simple(), aplicar=True)
    db.flush()
    salida = mod.desinstalar(uow, "demo", aplicar=True)
    db.flush()
    assert salida["quitados"] == 4
    assert mod.instalados(db, tenant_id)[0]["estado"] == "desinstalado"


# ── Catálogo y firma (CRM-00.04.04.08) ────────────────────────────────────


@pytest.mark.db
def test_no_se_republica_la_misma_version(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Reescribir una publicada dejaría a quien ya la instaló con un contenido
    distinto del que consta."""
    mod.publicar(db, _simple())
    db.flush()
    with pytest.raises(Conflicto) as e:
        mod.publicar(db, _simple())
    assert e.value.error_code == "metadata.version_ya_publicada"


@pytest.mark.db
def test_el_catalogo_dice_si_esta_firmado(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Un módulo sin firma puede haber sido modificado por cualquiera entre quien
    lo escribió y quien lo instala."""
    mod.publicar(db, _simple(clave="sinfirma"))
    mod.publicar(db, _simple(clave="confirma"), firma="xxx", revisado_por="Ana")
    db.flush()

    por_clave = {m["clave"]: m for m in mod.catalogo(db)}
    assert por_clave["sinfirma"]["firmado"] is False
    assert "Sin firma" in por_clave["sinfirma"]["aviso"]
    assert por_clave["confirma"]["revisado"] is True


@pytest.mark.db
def test_la_integridad_compara_con_lo_publicado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    manifiesto = _simple()
    mod.publicar(db, manifiesto)
    mod.instalar(uow, manifiesto, aplicar=True)
    db.flush()
    assert mod.comprobar_integridad(db, tenant_id, "demo")["coincide"] is True

    tocado = copy.deepcopy(manifiesto)
    tocado["contenido"]["objetos"][0]["etiqueta"] = "Cambiado por alguien"
    otro = _simple(clave="tocado")
    otro["contenido"] = tocado["contenido"]
    mod.instalar(uow, otro, aplicar=True)
    db.flush()
    salida = mod.comprobar_integridad(db, tenant_id, "tocado")
    assert salida["medible"] is False  # no está publicado: se dice, no se da por bueno


# ── Pantallas (CRM-00.04.04.07) ───────────────────────────────────────────


@pytest.mark.db
def test_las_pantallas_salen_de_la_superficie(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any, logistica: dict[str, Any]
) -> None:
    """El front oficial pinta lo que la superficie declara, así que un módulo
    añade pantallas declarándolas."""
    mod.instalar(uow, logistica, aplicar=True)
    db.flush()
    salida = mod.superficie_de_modulos(db, tenant_id)
    claves = {p["clave"] for p in salida["pantallas"]}
    assert claves == {"logistica__expediciones", "logistica__seguimiento_cliente"}


@pytest.mark.db
def test_un_modulo_desinstalado_no_deja_pantallas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Servirlas dejaría un menú con entradas que llevan a un 404, que es peor
    que no tener la entrada."""
    mod.instalar(uow, _simple(), aplicar=True)
    db.flush()
    mod.desinstalar(uow, "demo", aplicar=True)
    db.flush()
    assert mod.superficie_de_modulos(db, tenant_id)["pantallas"] == []


# ── Telemetría (CRM-00.04.04.10) ──────────────────────────────────────────


@pytest.mark.db
def test_la_telemetria_dice_que_sobra(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Un módulo con quince objetos de los que se usan dos no está completo, está
    inflado."""
    mod.instalar(uow, _simple(), aplicar=True)
    db.flush()
    mod.anotar_uso(db, tenant_id, modulo="demo", seccion="objetos", clave="demo__cosa")
    db.flush()

    salida = mod.telemetria(db, tenant_id, "demo")
    assert salida["usados"] == 1
    assert {e["clave"] for e in salida["sin_usar"]} == {
        "demo__aviso",
        "demo__inicial",
        "demo__lista",
    }


@pytest.mark.db
def test_un_modulo_recien_puesto_no_es_concluyente(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Tratarlo igual llevaría a recortar lo que aún nadie ha tenido tiempo de
    abrir."""
    mod.instalar(uow, _simple(), aplicar=True)
    db.flush()
    salida = mod.telemetria(db, tenant_id, "demo")
    assert salida["concluyente"] is False
    assert "todavía es pronto" in salida["aviso"]
