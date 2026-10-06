"""El gobierno de los módulos y el tipo de registro, enchufados
(CRM-00.04.01.05, CRM-00.04.04.03, CRM-00.04.04.10).

Tres circuitos abiertos en el mismo servicio, y los tres contestaban lo mismo que
contestarían si estuvieran bien:

**El tipo de registro no llegaba al `describe`.** `describe_para_tipo` estaba
escrita y no la llamaba nadie, así que un formulario de «cuenta pública» se
pintaba con los campos de la privada y con la lista de opciones entera. El
usuario elegía un valor que su tipo no admite y lo descubría al guardar — si es
que lo descubría.

**Nadie marcaba un elemento como modificado por el cliente.**
`modificado_por_cliente` solo lo ponía `marcar_modificado`, que no la llamaba
nadie. Con eso, **toda la lógica de no pisar el trabajo del cliente al actualizar
un módulo era inalcanzable**: no había conflictos, no había nada «respetado», y
la actualización pisaba los cambios. Lo peor es que el informe salía limpio.

**La telemetría contaba cero usos siempre.** `anotar_uso` tampoco la llamaba
nadie, así que *todo* salía en «sin usar» y la pregunta que responde —¿sobra la
mitad de este módulo?— tenía siempre la misma respuesta equivocada.

Y el prefijo del módulo asomaba por donde no debe: `desprefijar` existía para que
un menú no pusiera «facturacion__envios», y no se usaba en ningún sitio.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(db: Any) -> Any:
    """Pide `db` para que la sesión de la prueba esté montada antes de importar
    la aplicación: el servicio abre la suya y, sin compartir conexión, escribiría
    fuera de la transacción de la prueba."""
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.metadata.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


def _objeto_con_campos(cliente: Any, cabeceras: dict[str, str], nombre: str) -> None:
    r = cliente.post(
        "/api/v1/metadata/objetos",
        json={"nombre": nombre, "etiqueta": nombre.title(), "etiqueta_plural": nombre.title()},
        headers=cabeceras,
    )
    assert r.status_code in (200, 201), r.text
    for campo, restricciones in (
        ("segmento", {"opciones": ["pyme", "gran_cuenta", "publica"]}),
        ("presupuesto_publico", {}),
    ):
        r = cliente.post(
            f"/api/v1/metadata/objetos/{nombre}/campos",
            json={
                "nombre": campo,
                "etiqueta": campo.replace("_", " ").title(),
                "tipo": "lista" if restricciones else "texto",
                "restricciones": restricciones,
            },
            headers=cabeceras,
        )
        assert r.status_code in (200, 201), r.text


# ── El tipo de registro llega al describe (CRM-00.04.01.05) ───────────────


def test_sin_tipo_se_describe_el_objeto_entero(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Un objeto sin tipos configurados tiene que seguir funcionando igual que
    antes de que existieran."""
    _objeto_con_campos(cliente, cabeceras, "cuenta_a")

    salida = cliente.get("/api/v1/metadata/objetos/cuenta_a/describe", headers=cabeceras).json()
    assert salida["tipo_registro"] == ""
    assert {c["nombre"] for c in salida["campos"]} == {"segmento", "presupuesto_publico"}


def test_el_tipo_esconde_sus_campos_y_recorta_sus_listas(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Sin esto, el formulario de «cuenta pública» se pinta con los campos de la
    privada y con la lista entera: el usuario elige un valor que su tipo no
    admite y lo descubre al guardar."""
    _objeto_con_campos(cliente, cabeceras, "cuenta_b")
    r = cliente.put(
        "/api/v1/metadata/objetos/cuenta_b/tipos/publica",
        json={
            "nombre": "Administración pública",
            "campos_ocultos": ["presupuesto_publico"],
            "valores_lista": {"segmento": ["publica"]},
        },
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text

    salida = cliente.get(
        "/api/v1/metadata/objetos/cuenta_b/describe?tipo=publica", headers=cabeceras
    ).json()
    assert salida["tipo_registro"] == "publica"
    nombres = [c["nombre"] for c in salida["campos"]]
    assert "presupuesto_publico" not in nombres
    segmento = next(c for c in salida["campos"] if c["nombre"] == "segmento")
    assert segmento["restricciones"]["opciones"] == ["publica"]


def test_un_tipo_que_no_existe_no_se_cae_a_describirlo_todo(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Devolver el objeto entero ante una clave mal escrita pinta un formulario
    con campos que ese tipo no usa, y nadie se entera."""
    _objeto_con_campos(cliente, cabeceras, "cuenta_c")

    r = cliente.get("/api/v1/metadata/objetos/cuenta_c/describe?tipo=no_existe", headers=cabeceras)
    assert r.status_code == 404, r.text
    assert r.json()["error_code"] == "metadata.tipo_registro_no_encontrado"


# ── El gobierno del módulo (CRM-00.04.04.03, CRM-00.04.04.10) ─────────────


def _elemento(db: Any, tenant_id: UUID, *, seccion: str = "objetos", clave: str) -> Any:
    from services.metadata.modulos import ElementoModulo, ModuloInstalado

    db.add(
        ModuloInstalado(
            tenant_id=tenant_id,
            clave="facturacion",
            nombre="Facturación",
            version="1.0.0",
            estado="instalado",
            huella="x",
        )
    )
    fila = ElementoModulo(
        tenant_id=tenant_id,
        modulo="facturacion",
        seccion=seccion,
        clave=clave,
        gobierno="fijo",
        definicion={},
    )
    db.add(fila)
    db.flush()
    return fila


def test_describir_un_objeto_del_modulo_cuenta_como_uso(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """La telemetría contaba cero siempre, así que todo salía en «sin usar» y la
    pregunta que responde tenía siempre la misma respuesta equivocada."""
    fila = _elemento(db, tenant_id, clave="facturacion__envio")
    assert fila.usos == 0
    # Montar el objeto ya son usos: editarlo es usarlo. Lo que se mide aquí es
    # que **describirlo** sume uno más, que es la señal que de verdad dice si el
    # objeto se abre — es lo que llama el front para pintar el formulario.
    _objeto_con_campos(cliente, cabeceras, "facturacion__envio")
    db.refresh(fila)
    antes = fila.usos

    cliente.get("/api/v1/metadata/objetos/facturacion__envio/describe", headers=cabeceras)
    db.refresh(fila)
    assert fila.usos == antes + 1
    assert fila.ultimo_uso_at is not None


def test_editar_un_objeto_del_modulo_lo_marca_como_tocado(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Sin esta marca, actualizar el módulo pisa el trabajo del cliente **y el
    informe de la actualización sale limpio**."""
    fila = _elemento(db, tenant_id, clave="facturacion__envio")
    _objeto_con_campos(cliente, cabeceras, "facturacion__envio")
    assert fila.modificado_por_cliente is False

    r = cliente.post(
        "/api/v1/metadata/objetos/facturacion__envio/campos",
        json={"nombre": "recargo", "etiqueta": "Recargo", "tipo": "numero"},
        headers=cabeceras,
    )
    assert r.status_code in (200, 201), r.text
    db.refresh(fila)
    assert fila.modificado_por_cliente is True


def test_un_valor_de_lista_del_modulo_tambien_cuenta(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """Las listas son una sección del módulo como las demás. Enganchar solo el
    camino de los objetos diría la verdad en uno y mentiría en el otro, que es
    peor que no medir — porque entonces parece medido."""
    fila = _elemento(db, tenant_id, seccion="taxonomias", clave="facturacion__motivos")

    r = cliente.post(
        "/api/v1/metadata/listas/facturacion__motivos",
        json={"valor": "impago", "etiqueta": "Impago"},
        headers=cabeceras,
    )
    assert r.status_code in (200, 201), r.text
    db.refresh(fila)
    assert fila.modificado_por_cliente is True
    assert fila.usos == 1


def test_lo_que_no_viene_de_un_modulo_no_anota_nada(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """La mayoría de los objetos los creó el cliente a mano y no llevan prefijo.
    Contarlos como uso de un módulo inventaría la telemetría."""
    from sqlalchemy import event, func, select

    from services.metadata.modulos import ElementoModulo

    _objeto_con_campos(cliente, cabeceras, "cuenta_propia")

    # Y **ni siquiera se pregunta**. Sin el corte por prefijo la consulta se
    # lanza igual y no encuentra nada, así que el efecto sería el mismo y esta
    # prueba pasaría con el corte y sin él: lo que cambia es que `describe` —el
    # camino más caliente, el que llama el front para pintar cada formulario— se
    # llevaría una consulta de más en cada petición. Por eso se mide la
    # consulta, y no solo el efecto.
    consultas: list[str] = []

    def _anotar(conn: Any, cursor: Any, sentencia: str, *resto: Any) -> None:
        if "elementos_modulo" in sentencia:
            consultas.append(sentencia)

    motor = db.get_bind()
    event.listen(motor, "before_cursor_execute", _anotar)
    try:
        cliente.get("/api/v1/metadata/objetos/cuenta_propia/describe", headers=cabeceras)
    finally:
        event.remove(motor, "before_cursor_execute", _anotar)

    assert consultas == [], "se consulta la tabla de elementos para algo que no es de un módulo"
    total = db.execute(select(func.count()).select_from(ElementoModulo)).scalar_one()
    assert total == 0


def test_el_prefijo_no_se_le_ensena_a_nadie(db: Any, tenant_id: UUID) -> None:
    """Una entrada de menú que pone «facturacion__envios» es el prefijo asomando
    por donde no debe. Está para que dos módulos no se pisen, no para leerlo."""
    from services.metadata.modulos import superficie_de_modulos, telemetria

    _elemento(db, tenant_id, seccion="pantallas", clave="facturacion__envios")

    superficie = superficie_de_modulos(db, tenant_id)
    assert superficie["pantallas"][0]["nombre"] == "envios"
    # La clave larga sigue estando: es la que identifica.
    assert superficie["pantallas"][0]["clave"] == "facturacion__envios"

    sin_usar = telemetria(db, tenant_id, "facturacion")["sin_usar"]
    assert sin_usar[0]["nombre"] == "envios"


def test_de_que_modulo_es_cada_cosa() -> None:
    """Deducirlo del prefijo es lo que permite enganchar una vez y que valga para
    todas las secciones."""
    from services.metadata.modulos import de_que_modulo

    assert de_que_modulo("facturacion__envios") == ("facturacion", "envios")
    assert de_que_modulo("cuenta") == ("", "cuenta")
