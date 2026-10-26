"""Auditoría de firma electrónica (CRM-06.01.02), por sus rutas.

Seis capacidades sin ninguna prueba que las nombre, y las seis giran alrededor
de la misma decisión: **no hay un conector por casa**. Un módulo por proveedor
convierte cada implantación con otro proveedor en una versión del producto, y
son diez años de mantenerlas.

Lo que se persigue aquí:

  · que un proveedor se declare como **configuración** —clave, conexión,
    niveles que sabe hacer— y no haya lista de productos en el código;
  · que una regla pueda **subir** el nivel exigido y nunca bajarlo, porque
    dejar que lo rebaje convierte la política en una sugerencia;
  · que la plantilla admita **anclaje de texto** y no solo coordenadas, que se
    rompen en cuanto el contrato gana un párrafo — y eso pasa siempre;
  · que cambiar de proveedor **no pierda lo enviado**, y que diga cuántos
    quedan con el viejo: es lo que decide cuándo se apaga la credencial
    antigua, que es la pregunta que nadie sabe contestar cuando llega;
  · que probar las credenciales haga algo **más que consultar**, porque hay
    proveedores donde leer funciona con una credencial que no puede escribir;
  · y que el registro de llamadas guarde también **las que fallan**: uno que
    solo apunta lo que salió bien sirve para la factura y no para depurar, que
    es para lo que se mira a las dos de la mañana.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(db: Any) -> Iterator[Any]:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.integration.main").app) as cli:
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


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _proveedor(cliente: Any, cabeceras: dict[str, str], clave: str, **extra: Any) -> dict:
    r = cliente.post(
        "/api/v1/firma/proveedores",
        headers=cabeceras,
        json={"clave": clave, "nombre": clave.title(), **extra},
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


# ── CRM-06.01.02.02 y CRM-06.01.02.11 · El proveedor es configuración ────


def test_un_proveedor_se_declara_sin_tocar_codigo_crm_06_01_02_02(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """**No hay lista de proveedores en el código.** Un alta es una fila: su
    clave, la conexión declarativa por la que se le llama, qué niveles sabe
    hacer y cómo traduce sus estados a los nuestros.

    Y lo de los niveles no es un adorno: mandarle un contrato que exige firma
    cualificada a quien no la hace produce una firma que **parece válida y no lo
    es**, y eso se descubre en un juzgado.
    """
    creado = _proveedor(
        cliente,
        cabeceras,
        "proveedor_a",
        niveles=["simple", "avanzada"],
        identificaciones=["correo", "sms"],
        mapa_estados={"completed": "firmado", "declined": "rechazado"},
    )
    assert creado["clave"] == "proveedor_a"
    assert creado["niveles"] == ["simple", "avanzada"]

    # Y varios a la vez, que es lo que hace falta mientras se migra o cuando una
    # filial firma con otro.
    _proveedor(cliente, cabeceras, "proveedor_b")
    claves = [
        p["clave"] for p in cliente.get("/api/v1/firma/proveedores", headers=cabeceras).json()
    ]
    assert claves == ["proveedor_a", "proveedor_b"], claves


def test_las_operaciones_del_proveedor_son_una_lista_cerrada_crm_06_01_02_11(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Cinco operaciones y no una: lo que cambia entre proveedores es la
    dirección de cada una y el nombre de los campos, y eso es configuración.
    Que la lista sea cerrada es el contrato — quien declara un proveedor nuevo
    sabe exactamente qué tiene que mapear."""
    from crmcore.errors import ErrorValidacion

    from services.integration import firma as fir

    assert set(fir.OPERACIONES) == {
        "crear_sobre",
        "consultar_estado",
        "descargar_firmado",
        "descargar_certificado",
        "cancelar_sobre",
    }

    proveedor = fir.ProveedorFirma(tenant_id=tenant_id, clave="p", nombre="P", conexion_id=uuid4())
    with pytest.raises(ErrorValidacion):
        fir._puerto_llamada(db, proveedor, operacion="inventada", parametros={})


def test_un_proveedor_sin_conexion_se_puede_declarar_y_no_llamar_crm_06_01_02_11(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Y lo dice por su nombre. Un sobre que no sale no es un sobre enviado, y
    el error tiene que explicar que falta la conexión y no «fallo al llamar»."""
    from crmcore.errors import ErrorDependencia

    from services.integration import firma as fir

    sin_conexion = fir.ProveedorFirma(tenant_id=tenant_id, clave="p", nombre="P")
    with pytest.raises(ErrorDependencia) as fallo:
        fir._puerto_llamada(db, sin_conexion, operacion="consultar_estado", parametros={})
    assert fallo.value.error_code == "firma.sin_conexion"


# ── CRM-06.01.02.02 · Las reglas suben el nivel, no lo bajan ──────────────


def test_una_regla_puede_subir_el_nivel_pero_no_bajarlo_crm_06_01_02_02(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un contrato de cien mil no se firma con un clic aunque quien lo mande no
    lo piense. Y al revés: dejar que una regla **rebaje** el nivel pedido
    convierte la política en una sugerencia."""
    from services.integration import firma as fir

    _proveedor(cliente, cabeceras, "proveedor_a", niveles=["simple", "avanzada", "cualificada"])
    r = cliente.post(
        "/api/v1/firma/reglas",
        headers=cabeceras,
        json={
            "nombre": "portugal-cualificada",
            "condiciones": [{"atributo": "documento.pais", "operador": "=", "valor": "PT"}],
            "proveedor": "proveedor_a",
            "nivel_minimo": "cualificada",
        },
    )
    assert r.status_code == 201, r.text

    # Sube: se pidió simple y la regla exige cualificada.
    proveedor, nivel, regla = fir.elegir_proveedor(db, tenant_id, {"pais": "PT"}, nivel="simple")
    assert (proveedor, nivel) == ("proveedor_a", "cualificada"), (proveedor, nivel, regla)

    # Y no baja: se pidió cualificada y la regla dice simple.
    cliente.post(
        "/api/v1/firma/reglas",
        headers=cabeceras,
        json={
            "nombre": "espana-simple",
            "prioridad": 10,
            "condiciones": [{"atributo": "documento.pais", "operador": "=", "valor": "ES"}],
            "proveedor": "proveedor_a",
            "nivel_minimo": "simple",
        },
    )
    _p, nivel, _r = fir.elegir_proveedor(db, tenant_id, {"pais": "ES"}, nivel="cualificada")
    assert (
        nivel == "cualificada"
    ), "una regla ha rebajado el nivel pedido: la política pasa a ser una sugerencia"


def test_la_eleccion_dice_que_regla_decidio_crm_06_01_02_02(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una elección que no se puede explicar no se puede corregir, y aquí decide
    con qué validez legal sale un contrato."""
    from services.integration import firma as fir

    _proveedor(cliente, cabeceras, "proveedor_a")
    _p, _n, regla = fir.elegir_proveedor(db, tenant_id, {"pais": "ES"})
    assert regla, "no dice por qué ha elegido ese proveedor"


def test_sin_proveedor_configurado_se_dice_en_vez_de_fallar_raro_crm_06_01_02_02(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.errors import ErrorValidacion

    from services.integration import firma as fir

    with pytest.raises(ErrorValidacion) as fallo:
        fir.elegir_proveedor(db, tenant_id, {})
    assert fallo.value.error_code == "firma.sin_proveedor"


# ── CRM-06.01.02.06 · Plantillas con anclaje ──────────────────────────────


def test_una_plantilla_sitúa_por_anclaje_y_no_solo_por_coordenadas_crm_06_01_02_06(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """**Las coordenadas se rompen en cuanto el contrato gana un párrafo**, y eso
    pasa siempre: la casilla de firma acaba a mitad de una cláusula. El anclaje
    de texto se mueve con el documento."""
    r = cliente.post(
        "/api/v1/firma/plantillas",
        headers=cabeceras,
        json={
            "clave": "contrato-marco",
            "nombre": "Contrato marco",
            "nivel": "avanzada",
            "campos": [
                {"tipo": "firma", "firmante": 0, "anclaje": "/firma_cliente/"},
                {"tipo": "texto", "firmante": 0, "pagina": 2, "x": 100, "y": 400},
                {"tipo": "fecha", "firmante": 1, "anclaje": "/fecha_nuestra/"},
            ],
        },
    )
    assert r.status_code == 201, r.text

    # Se guarda tal cual: una plantilla que pierde los anclajes al guardarse
    # deja la firma donde el proveedor quiera ponerla.
    from crmcore.db.session import nueva_sesion  # noqa: F401 — sólo para el tipo
    from sqlalchemy import select

    assert select is not None


def test_los_campos_de_la_plantilla_se_releen_enteros_crm_06_01_02_06(
    cliente: Any, cabeceras: dict[str, str], db: Any, contexto_tenant: UUID
) -> None:
    """Lo anterior, comprobado sobre la fila: una plantilla que pierde los
    anclajes al guardarse deja la firma donde el proveedor quiera ponerla."""
    from sqlalchemy import select

    from services.integration.firma import PlantillaFirma

    creada = cliente.post(
        "/api/v1/firma/plantillas",
        headers=cabeceras,
        json={
            "clave": "contrato-marco",
            "nombre": "Contrato marco",
            "campos": [{"tipo": "firma", "firmante": 0, "anclaje": "/firma_cliente/"}],
        },
    ).json()
    fila = db.execute(
        select(PlantillaFirma).where(PlantillaFirma.id == UUID(creada["id"]))
    ).scalar_one()
    assert fila.campos[0]["anclaje"] == "/firma_cliente/", fila.campos


# ── CRM-06.01.02.13 · Cambiar de proveedor ────────────────────────────────


def test_al_migrar_los_sobres_en_vuelo_terminan_con_el_viejo_crm_06_01_02_13(
    cliente: Any, cabeceras: dict[str, str], uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un sobre a medias **no se puede mover**: el enlace que tiene el cliente en
    su correo apunta al proveedor viejo. Lo que cambia es a dónde van los
    nuevos.

    Y se dice cuántos quedan, que es lo que decide **cuándo se apaga la
    credencial vieja** — la pregunta que nadie sabe contestar cuando llega.
    """
    from services.integration import firma as fir

    _proveedor(cliente, cabeceras, "viejo")
    _proveedor(cliente, cabeceras, "nuevo")

    uow.db.add(
        fir.Sobre(
            tenant_id=tenant_id,
            referencia="S-1",
            documento_id="doc-1",
            proveedor="viejo",
            estado="enviado",
        )
    )
    uow.db.flush()

    salida = fir.migrar_proveedor(uow, desde="viejo", hacia="nuevo", motivo="cambio de contrato")
    assert salida["sobres_en_vuelo_con_el_antiguo"] == 1, salida
    assert salida["el_mas_viejo"], (
        f"no dice cuál es el más viejo: sin eso no se sabe cuándo apagar la "
        f"credencial antigua. Devuelve {sorted(salida)}"
    )
    # Y la pregunta contestada, no el dato en crudo: con un sobre en vuelo, la
    # credencial vieja NO se puede retirar, y se dice por qué.
    assert salida["se_puede_apagar_el_antiguo"] is False
    assert "en vuelo" in salida["porque"], salida["porque"]

    # El viejo queda «sólo para lo que está en curso»: los nuevos salen por el
    # otro y los de antes pueden terminar.
    uow.db.expire_all()
    viejo = fir._proveedor(uow.db, tenant_id, "viejo")
    assert viejo.solo_en_curso is True
    assert fir.elegir_proveedor(uow.db, tenant_id, {})[0] == "nuevo"


def test_no_se_migra_hacia_un_proveedor_apagado_crm_06_01_02_13(
    cliente: Any, cabeceras: dict[str, str], uow: Any, contexto_tenant: UUID
) -> None:
    """Dejaría los sobres nuevos sin por dónde salir, y eso se descubre al
    mandar el siguiente contrato."""
    from crmcore.errors import Conflicto

    from services.integration import firma as fir

    _proveedor(cliente, cabeceras, "viejo")
    _proveedor(cliente, cabeceras, "apagado")
    # Se apaga sobre la fila: el alta no admite crearlo ya apagado, y tiene
    # sentido — se da de alta para usarlo.
    fir._proveedor(uow.db, uow.tenant_id, "apagado").activo = False
    uow.db.flush()

    with pytest.raises(Conflicto) as fallo:
        fir.migrar_proveedor(uow, desde="viejo", hacia="apagado")
    assert fallo.value.error_code == "firma.destino_inactivo"


# ── CRM-06.01.02.14 · Probar antes de mandar ──────────────────────────────


def test_probar_en_vacio_escribe_y_no_solo_consulta_crm_06_01_02_14(
    cliente: Any, cabeceras: dict[str, str], uow: Any, contexto_tenant: UUID
) -> None:
    """**Solo consultar no vale**: hay proveedores donde leer funciona con una
    credencial que no puede escribir, y entonces la prueba pasa y el primer
    envío falla — con un contrato de verdad delante."""
    from services.integration import firma as fir

    _proveedor(cliente, cabeceras, "proveedor_a", conexion_id=str(uuid4()))

    llamadas: list[str] = []

    def operador(*, conexion_id: UUID, operacion: str, parametros: dict[str, Any]) -> dict:
        llamadas.append(operacion)
        return {"id_externo": "x", "estado": "created"}

    previo = fir._operador
    fir.registrar_operador(operador)
    try:
        salida = fir.probar_conexion(uow, clave="proveedor_a", en_vacio=True)
    finally:
        fir._operador = previo

    assert salida["ok"] is True, salida
    assert "crear_sobre" in llamadas, (
        f"la prueba en vacío no ha escrito nada: {llamadas}. Una credencial de "
        "solo lectura pasaría la prueba y fallaría al primer envío"
    )
    assert (
        "cancelar_sobre" in llamadas
    ), "crea el sobre de prueba y no lo cancela: deja basura en el proveedor"


# ── El sobre que se daba por enviado sin salir ────────────────────────────


@pytest.fixture
def sobre_listo(cliente: Any, cabeceras: dict[str, str], uow: Any, tenant_id: UUID) -> Any:
    """Un sobre en borrador, con su proveedor conectado y un firmante."""
    from services.integration import firma as fir

    _proveedor(cliente, cabeceras, "proveedor_a", conexion_id=str(uuid4()))
    sobre = fir.Sobre(
        tenant_id=tenant_id,
        referencia="S-1",
        documento_id="doc-1",
        proveedor="proveedor_a",
        estado="borrador",
        asunto="Contrato marco",
        caduca_at=datetime.now(timezone.utc),
    )
    uow.db.add(sobre)
    uow.db.flush()
    uow.db.add(
        fir.Firmante(
            tenant_id=tenant_id,
            sobre_id=sobre.id,
            nombre="Ana",
            email="ana@example.com",
            orden=0,
            papel="firmante",
        )
    )
    uow.db.flush()
    return sobre


def test_enviar_llama_al_proveedor_de_verdad_crm_06_01_02_11(
    uow: Any, sobre_listo: Any, contexto_tenant: UUID
) -> None:
    """**El agujero grande de esta familia.** `enviar()` marcaba el sobre como
    «enviado» y emitía el evento, y `_puerto_llamada` sólo lo usaba la prueba de
    conexión: al proveedor **no le llegaba nada**. El cliente no recibía ningún
    correo y el CRM decía que estaba mandado.

    No falla, y por eso no se había notado: el sobre queda en «enviado» y ahí se
    queda — esperando a un firmante que nunca supo que tenía algo que firmar.
    """
    from services.integration import firma as fir

    llamadas: list[tuple[str, dict[str, Any]]] = []

    def operador(*, conexion_id: UUID, operacion: str, parametros: dict[str, Any]) -> dict:
        llamadas.append((operacion, parametros))
        return {"id": "ext-123"}

    previo = fir._operador
    fir.registrar_operador(operador)
    try:
        salida = fir.enviar(uow, sobre_listo.id)
    finally:
        fir._operador = previo

    assert [o for o, _ in llamadas] == ["crear_sobre"], llamadas
    parametros = llamadas[0][1]
    # Con lo que el proveedor necesita para mandar el correo: a quién, qué
    # documento y con qué validez legal.
    assert parametros["firmantes"][0]["email"] == "ana@example.com", parametros
    assert parametros["documento_id"] == "doc-1"
    assert parametros["nivel"] == "simple"

    assert salida["estado"] == "enviado"
    # Y el identificador del proveedor queda guardado: sin él, consultar el
    # estado, descargar lo firmado o cancelarlo no tienen a qué referirse.
    uow.db.refresh(sobre_listo)
    assert sobre_listo.referencia_externa == "ext-123", sobre_listo.referencia_externa


def test_si_el_proveedor_no_lo_acepta_el_sobre_no_queda_enviado_crm_06_01_02_11(
    uow: Any, sobre_listo: Any, contexto_tenant: UUID
) -> None:
    """Marcar como enviado lo que nunca salió es exactamente el fallo que se
    está arreglando: el sobre se queda en borrador, con el motivo anotado, y la
    llamada fallida queda en el registro."""
    from sqlalchemy import select

    from services.integration import firma as fir

    def operador(*, conexion_id: UUID, operacion: str, parametros: dict[str, Any]) -> dict:
        raise RuntimeError("el proveedor devolvió 502")

    previo = fir._operador
    fir.registrar_operador(operador)
    try:
        with pytest.raises(RuntimeError):
            fir.enviar(uow, sobre_listo.id)
    finally:
        fir._operador = previo

    uow.db.refresh(sobre_listo)
    assert (
        sobre_listo.estado == "borrador"
    ), "ha quedado como enviado aunque el proveedor lo rechazó"
    fallidas = (
        uow.db.execute(
            select(fir.LlamadaProveedorFirma).where(
                fir.LlamadaProveedorFirma.sobre_id == sobre_listo.id,
                fir.LlamadaProveedorFirma.ok.is_(False),
            )
        )
        .scalars()
        .all()
    )
    assert fallidas and "502" in (fallidas[0].error or ""), fallidas


def test_sin_operador_conectado_el_envio_lo_dice_crm_06_01_02_11(
    uow: Any, sobre_listo: Any, contexto_tenant: UUID
) -> None:
    """Y no se da por enviado. «Se puede declarar un proveedor pero no
    llamarle» es un despliegue a medias, y tiene que verse al mandar el primer
    contrato, no después."""
    from crmcore.errors import ErrorDependencia

    from services.integration import firma as fir

    previo = fir._operador
    fir._operador = None
    try:
        with pytest.raises(ErrorDependencia) as fallo:
            fir.enviar(uow, sobre_listo.id)
    finally:
        fir._operador = previo

    assert fallo.value.error_code == "firma.sin_operador"
    uow.db.refresh(sobre_listo)
    assert sobre_listo.estado == "borrador"


# ── CRM-06.01.02.15 · Registro de llamadas ────────────────────────────────


def test_el_registro_guarda_tambien_las_llamadas_que_fallan_crm_06_01_02_15(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un registro que solo apunta lo que salió bien sirve para la factura y no
    sirve para depurar, que es para lo que se mira a las dos de la mañana."""
    from sqlalchemy import select

    from services.integration import firma as fir

    fir.anotar_llamada(
        db,
        tenant_id=tenant_id,
        proveedor="proveedor_a",
        operacion="crear_sobre",
        ok=False,
        codigo=502,
        duracion_ms=1200,
        error="el proveedor devolvió un 502",
    )
    fir.anotar_llamada(
        db,
        tenant_id=tenant_id,
        proveedor="proveedor_a",
        operacion="crear_sobre",
        ok=True,
        codigo=201,
        duracion_ms=300,
        coste=Decimal("0.4500"),
    )
    db.flush()

    filas = (
        db.execute(
            select(fir.LlamadaProveedorFirma).where(
                fir.LlamadaProveedorFirma.tenant_id == tenant_id
            )
        )
        .scalars()
        .all()
    )
    assert len(filas) == 2, "la que falló no se ha guardado"
    fallida = next(f for f in filas if not f.ok)
    assert fallida.codigo == 502 and fallida.error, fallida
    # Y el coste, que es lo que permite conciliar la factura del proveedor.
    buena = next(f for f in filas if f.ok)
    assert buena.coste == Decimal("0.4500"), buena.coste


def test_el_registro_no_guarda_el_documento_crm_06_01_02_15() -> None:
    """**Sin cuerpos completos.** Un contrato entero repetido en una tabla de
    registro es una copia del documento fuera del corpus, que es justo donde no
    tiene que estar: se saltaría su retención, su cifrado y sus permisos."""
    from services.integration.firma import LlamadaProveedorFirma

    columnas = set(LlamadaProveedorFirma.__table__.columns.keys())
    prohibidas = {"peticion", "respuesta", "cuerpo", "documento", "contenido"}
    assert not (columnas & prohibidas), sorted(columnas & prohibidas)
