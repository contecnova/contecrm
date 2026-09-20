"""Identificadores, relaciones, direcciones y verificación externa.

Cubre `CRM-01.01.01.04` (relaciones no jerárquicas), `CRM-01.01.01.05`
(geocodificación), `CRM-01.01.01.06` (identificadores de varios países) y
`CRM-01.01.04.10` (estado de verificación).

Las cuatro pedían lo mismo con palabras distintas —mandar un dato fuera y
guardar qué contestaron— y por eso comparten un solo verificador configurable.
Lo que estas pruebas defienden por encima de todo es la distinción entre **no
válido** y **no comprobado**: confundirlos es cómo un sistema acaba bloqueando
facturas porque el servicio del ministerio estaba caído.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import ErrorValidacion, NoEncontrado

from services.party import fiscal
from services.party import servicio as svc
from services.party.modelos import Cuenta, Direccion, IdentificadorFiscal, RelacionCuenta


class _Uow:
    def __init__(self, db: Any, tenant_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.emitidos: list[dict[str, Any]] = []

    def emitir(self, tipo: str, *, subject: Any, data: Any, **extra: Any) -> None:
        self.emitidos.append({"tipo": tipo, "data": data})


def _cuenta(db: Any, tenant_id: UUID, nombre: str = "ACME") -> Cuenta:
    fila = Cuenta(tenant_id=tenant_id, nombre=nombre, clave_canonica=nombre.lower())
    db.add(fila)
    db.flush()
    return fila


# ── Identificadores fiscales de varios países ─────────────────────────────


@pytest.mark.parametrize(
    "valor,pais",
    [
        ("B12345674", "ES"),
        ("12345678Z", "ES"),
        ("502011378", "PT"),
        ("BE0776091951", "BE"),
        ("DE136695976", "DE"),
        ("IT00000000000", "IT"),
    ],
)
def test_identificadores_validos_de_varios_paises(valor: str, pais: str) -> None:
    """Antes solo se validaba el español. Un CRM que opera en tres países y solo
    comprueba uno da una falsa sensación de calidad: el maestro parece limpio
    porque el 60 % de las fichas ni se comprueban."""
    assert fiscal.validar(valor, pais)[0] is True


def test_el_prefijo_de_pais_se_admite_escrito_o_no() -> None:
    """Un identificador intracomunitario se escribe «ESB12345674» y también
    «B12345674». La primera versión de esto solo quitaba el prefijo cuando NO
    coincidía con el país declarado, y el caso normal es justo el contrario: los
    identificadores bien escritos salían inválidos, que es el peor error posible
    en una validación."""
    assert fiscal.validar("ESB12345674", "ES")[0] is True
    assert fiscal.validar("B12345674", "ES")[0] is True
    assert fiscal.validar("PT502011378", "PT")[0] is True


def test_un_digito_de_control_malo_se_rechaza() -> None:
    assert fiscal.validar("B12345678", "ES")[0] is False
    assert fiscal.validar("502011379", "PT")[0] is False


def test_lo_que_no_se_sabe_validar_devuelve_none_y_no_falso() -> None:
    """Es la distinción que importa: decir «inválido» de un identificador de un
    país sin algoritmo bloquearía altas legítimas, y el cliente no tendría forma
    de continuar."""
    veredicto, motivo = fiscal.validar("X1234567", "MX")
    assert veredicto is None
    assert "no sabemos validar" in motivo


def test_un_pais_con_formato_pero_sin_algoritmo_solo_confirma_la_forma() -> None:
    """Afirmar más de lo que se puede comprobar es mentir. Se dice exactamente
    qué se ha comprobado."""
    veredicto, motivo = fiscal.validar("12345678", "FI")
    assert veredicto is None
    assert "sin dígito de control" in motivo


@pytest.mark.db
def test_un_identificador_extranjero_no_se_bloquea_por_no_saber_validarlo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Bloquear lo que no se sabe validar deja al cliente sin forma de
    continuar. Se guarda y queda pendiente de verificar, que es otra cosa."""
    uow = _Uow(db, tenant_id)
    cuenta = svc.crear_cuenta(
        uow,
        nombre="Cliente mexicano",
        identificadores=[{"tipo": "otro", "pais": "MX", "valor": "XAXX010101000"}],
    )
    db.flush()
    assert db.query(IdentificadorFiscal).filter_by(cuenta_id=cuenta.id).count() == 1


@pytest.mark.db
def test_un_identificador_mal_construido_si_se_bloquea(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    uow = _Uow(db, tenant_id)
    with pytest.raises(ErrorValidacion, match="no es un identificador fiscal"):
        svc.crear_cuenta(
            uow,
            nombre="Con NIF malo",
            identificadores=[{"tipo": "cif", "pais": "ES", "valor": "B12345678"}],
        )


# ── Relaciones no jerárquicas ─────────────────────────────────────────────


@pytest.mark.db
def test_relacionar_dos_cuentas(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    uow = _Uow(db, tenant_id)
    una, otra = _cuenta(db, tenant_id, "Una"), _cuenta(db, tenant_id, "Otra")
    relacion = svc.relacionar_cuentas(
        uow, cuenta_id=una.id, relacionada_id=otra.id, tipo="proveedor"
    )
    assert relacion.tipo == "proveedor"
    # La inversa se declara y no se deduce: adivinarla produce etiquetas
    # absurdas en la ficha del otro lado.
    assert relacion.tipo_inverso == "cliente"


@pytest.mark.db
def test_la_relacion_se_lee_al_reves_desde_la_otra_ficha(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Se guarda **una sola fila**. Dos obligarían a sincronizarlas, y el día que
    una se quede huérfana las dos fichas se contradicen."""
    uow = _Uow(db, tenant_id)
    una, otra = _cuenta(db, tenant_id, "Una"), _cuenta(db, tenant_id, "Otra")
    svc.relacionar_cuentas(uow, cuenta_id=una.id, relacionada_id=otra.id, tipo="proveedor")
    db.flush()

    assert db.query(RelacionCuenta).count() == 1

    desde_una = svc.relaciones_de_cuenta(db, una.id)
    desde_otra = svc.relaciones_de_cuenta(db, otra.id)
    assert desde_una[0]["tipo"] == "proveedor" and desde_una[0]["sentido"] == "directa"
    assert desde_otra[0]["tipo"] == "cliente" and desde_otra[0]["sentido"] == "inversa"
    assert desde_una[0]["cuenta_nombre"] == "Otra"


@pytest.mark.db
def test_una_cuenta_no_se_relaciona_consigo_misma(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    uow = _Uow(db, tenant_id)
    una = _cuenta(db, tenant_id, "Una")
    with pytest.raises(ErrorValidacion, match="consigo misma"):
        svc.relacionar_cuentas(uow, cuenta_id=una.id, relacionada_id=una.id, tipo="partner")


@pytest.mark.db
def test_relacionar_al_reves_no_duplica(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Las dos direcciones son la misma relación. Crear la simétrica dejaría dos
    filas diciendo lo mismo y la ficha la enseñaría dos veces."""
    uow = _Uow(db, tenant_id)
    una, otra = _cuenta(db, tenant_id, "Una"), _cuenta(db, tenant_id, "Otra")
    svc.relacionar_cuentas(uow, cuenta_id=una.id, relacionada_id=otra.id, tipo="partner")
    svc.relacionar_cuentas(uow, cuenta_id=otra.id, relacionada_id=una.id, tipo="partner")
    db.flush()

    assert db.query(RelacionCuenta).count() == 1


@pytest.mark.db
def test_un_tipo_de_relacion_inventado_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    uow = _Uow(db, tenant_id)
    una, otra = _cuenta(db, tenant_id, "Una"), _cuenta(db, tenant_id, "Otra")
    with pytest.raises(ErrorValidacion, match="Tipo de relación"):
        svc.relacionar_cuentas(uow, cuenta_id=una.id, relacionada_id=otra.id, tipo="enemigo_intimo")


@pytest.mark.db
def test_se_puede_quitar_la_relacion_desde_cualquiera_de_las_dos_fichas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    uow = _Uow(db, tenant_id)
    una, otra = _cuenta(db, tenant_id, "Una"), _cuenta(db, tenant_id, "Otra")
    relacion = svc.relacionar_cuentas(
        uow, cuenta_id=una.id, relacionada_id=otra.id, tipo="competidor"
    )
    db.flush()

    svc.desrelacionar_cuentas(uow, cuenta_id=otra.id, relacion_id=relacion.id)
    assert db.query(RelacionCuenta).count() == 0


@pytest.mark.db
def test_no_se_puede_quitar_la_relacion_de_otras_cuentas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    uow = _Uow(db, tenant_id)
    una, otra = _cuenta(db, tenant_id, "Una"), _cuenta(db, tenant_id, "Otra")
    tercera = _cuenta(db, tenant_id, "Tercera")
    relacion = svc.relacionar_cuentas(uow, cuenta_id=una.id, relacionada_id=otra.id, tipo="partner")
    db.flush()

    with pytest.raises(NoEncontrado):
        svc.desrelacionar_cuentas(uow, cuenta_id=tercera.id, relacion_id=relacion.id)


# ── El verificador externo ────────────────────────────────────────────────


def _configurar(db: Any, tenant_id: UUID, clave: str, config: dict[str, Any]) -> None:
    from crmcore.runtime import settings as rt

    rt.fijar(db, clave, config, ambito="tenant", ambito_id=str(tenant_id))
    db.flush()


@pytest.mark.db
def test_sin_verificador_configurado_el_veredicto_es_no_concluyente(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """No es «inválido»: es que no lo sabemos. Confundirlos es cómo un sistema
    acaba bloqueando facturas porque nadie configuró el verificador."""
    from crmcore.datos import verificacion as verif

    veredicto = verif.verificar(db, tipo="fiscal", valor="B12345674", pais="ES")
    assert veredicto.no_concluyente is True
    assert veredicto.estado == "desconocido"


@pytest.mark.db
def test_el_verificador_interpreta_la_respuesta_con_el_mapeo_declarado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """Es lo que evita un cliente por proveedor: uno devuelve `{"valid": true}`,
    otro `{"status": "OK"}` y otro un 200 vacío."""
    from crmcore.datos import verificacion as verif

    _configurar(
        db,
        tenant_id,
        "verificador_fiscal",
        {
            "url": "https://registro.test/comprobar",
            "mapeo": {"campo": "resultado.estado", "valido": ["OK", "ACTIVO"]},
            "conservar": {"razon_social": "resultado.nombre"},
        },
    )
    _fingir_respuesta(monkeypatch, {"resultado": {"estado": "OK", "nombre": "ACME S.L."}})

    veredicto = verif.verificar(db, tipo="fiscal", valor="B12345674", pais="ES")
    assert veredicto.estado == "valido"
    assert veredicto.no_concluyente is False
    assert veredicto.datos == {"razon_social": "ACME S.L."}


@pytest.mark.db
def test_un_campo_que_no_esta_en_la_respuesta_no_concluye_nada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """O cambió el contrato del servicio o el mapeo está mal. En ninguno de los
    dos casos se puede concluir, y afirmar «inválido» sería inventárselo."""
    from crmcore.datos import verificacion as verif

    _configurar(
        db,
        tenant_id,
        "verificador_fiscal",
        {"url": "https://registro.test/x", "mapeo": {"campo": "no.existe"}},
    )
    _fingir_respuesta(monkeypatch, {"otra_cosa": True})

    veredicto = verif.verificar(db, tipo="fiscal", valor="B12345674", pais="ES")
    assert veredicto.no_concluyente is True


@pytest.mark.db
def test_si_el_verificador_no_contesta_no_se_concluye(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """Verificar es una mejora del dato: un alta de cliente no puede fallar
    porque un servicio externo esté caído."""
    from crmcore.datos import verificacion as verif

    _configurar(db, tenant_id, "verificador_fiscal", {"url": "https://registro.test/x"})

    class _Cliente:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_a: Any) -> None:
            return None

        def request(self, *_a: Any, **_k: Any) -> Any:
            raise TimeoutError("no contesta")

        def get(self, *_a: Any, **_k: Any) -> Any:
            raise TimeoutError("no contesta")

    monkeypatch.setattr("crmcore.red.cliente_seguro", lambda **_k: _Cliente())
    veredicto = verif.verificar(db, tipo="fiscal", valor="B12345674", pais="ES")
    assert veredicto.no_concluyente is True
    assert "no respondió" in veredicto.detalle


@pytest.mark.db
def test_no_se_conserva_nada_que_no_se_haya_pedido(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """La respuesta de un servicio externo puede traer datos personales que
    nadie pidió, y guardarla entera «por si acaso» es exactamente lo que un
    registro de tratamiento no puede justificar."""
    from crmcore.datos import verificacion as verif

    _configurar(db, tenant_id, "verificador_fiscal", {"url": "https://registro.test/x"})
    _fingir_respuesta(monkeypatch, {"valid": True, "administrador": "Ana Pérez", "dni": "X"})

    veredicto = verif.verificar(db, tipo="fiscal", valor="B12345674", pais="ES")
    assert veredicto.datos == {}


@pytest.mark.db
def test_un_fallo_del_registro_no_borra_el_veredicto_anterior(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """Poner «desconocido» encima de un «válido» porque hoy hubo un timeout
    convertiría cada incidencia de red en una pérdida de información."""
    uow = _Uow(db, tenant_id)
    cuenta = svc.crear_cuenta(
        uow,
        nombre="ACME",
        identificadores=[{"tipo": "cif", "pais": "ES", "valor": "B12345674"}],
    )
    db.flush()
    identificador = db.query(IdentificadorFiscal).filter_by(cuenta_id=cuenta.id).one()
    identificador.verificado = True
    db.flush()

    # Sin verificador configurado: el resultado es no concluyente.
    salida = svc.verificar_identificador_fiscal(
        uow, cuenta_id=cuenta.id, identificador_id=identificador.id
    )
    assert salida["no_concluyente"] is True
    db.refresh(identificador)
    assert identificador.verificado is True


@pytest.mark.db
def test_la_respuesta_incluye_siempre_la_comprobacion_de_forma(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin ella, un `no_concluyente` parecería que no se sabe nada del
    identificador, y sí se sabe si está bien construido."""
    uow = _Uow(db, tenant_id)
    cuenta = svc.crear_cuenta(
        uow,
        nombre="ACME",
        identificadores=[{"tipo": "cif", "pais": "ES", "valor": "B12345674"}],
    )
    db.flush()
    identificador = db.query(IdentificadorFiscal).filter_by(cuenta_id=cuenta.id).one()

    salida = svc.verificar_identificador_fiscal(
        uow, cuenta_id=cuenta.id, identificador_id=identificador.id
    )
    assert salida["forma"]["valido"] is True


# ── Geocodificación ───────────────────────────────────────────────────────


@pytest.mark.db
def test_geocodificar_pone_las_coordenadas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    direccion = Direccion(
        tenant_id=tenant_id,
        objeto="cuenta",
        objeto_id=cuenta.id,
        linea1="Gran Vía 1",
        ciudad="Bilbao",
        pais="ES",
    )
    db.add(direccion)
    db.flush()

    _configurar(
        db,
        tenant_id,
        "verificador_direccion",
        {
            "url": "https://geo.test/buscar",
            "conservar": {"latitud": "lat", "longitud": "lon"},
        },
    )
    _fingir_respuesta(monkeypatch, {"lat": 43.2630, "lon": -2.9350})

    salida = svc.geocodificar(uow, objeto="cuenta", objeto_id=cuenta.id, direccion_id=direccion.id)
    assert salida["latitud"] == pytest.approx(43.263, rel=1e-4)
    db.refresh(direccion)
    assert direccion.geocodificada_at is not None


@pytest.mark.db
def test_media_coordenada_no_se_escribe(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """Escribir una latitud sin longitud deja un punto en el meridiano de
    Greenwich, que es un sitio muy concreto y casi nunca el correcto."""
    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    direccion = Direccion(
        tenant_id=tenant_id, objeto="cuenta", objeto_id=cuenta.id, linea1="X", pais="ES"
    )
    db.add(direccion)
    db.flush()

    _configurar(
        db,
        tenant_id,
        "verificador_direccion",
        {"url": "https://geo.test/x", "conservar": {"latitud": "lat", "longitud": "lon"}},
    )
    _fingir_respuesta(monkeypatch, {"lat": 43.26})

    svc.geocodificar(uow, objeto="cuenta", objeto_id=cuenta.id, direccion_id=direccion.id)
    db.refresh(direccion)
    assert direccion.latitud is None and direccion.longitud is None


@pytest.mark.db
def test_unas_coordenadas_que_no_son_numeros_no_se_escriben(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    direccion = Direccion(
        tenant_id=tenant_id, objeto="cuenta", objeto_id=cuenta.id, linea1="X", pais="ES"
    )
    db.add(direccion)
    db.flush()

    _configurar(
        db,
        tenant_id,
        "verificador_direccion",
        {"url": "https://geo.test/x", "conservar": {"latitud": "lat", "longitud": "lon"}},
    )
    _fingir_respuesta(monkeypatch, {"lat": "no soy un número", "lon": "yo tampoco"})

    salida = svc.geocodificar(uow, objeto="cuenta", objeto_id=cuenta.id, direccion_id=direccion.id)
    assert salida["no_concluyente"] is True
    db.refresh(direccion)
    assert direccion.latitud is None


@pytest.mark.db
def test_no_se_geocodifica_la_direccion_de_otro_registro(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    direccion = Direccion(
        tenant_id=tenant_id, objeto="cuenta", objeto_id=uuid4(), linea1="X", pais="ES"
    )
    db.add(direccion)
    db.flush()

    with pytest.raises(NoEncontrado):
        svc.geocodificar(uow, objeto="cuenta", objeto_id=cuenta.id, direccion_id=direccion.id)


# ── Nada de proveedores en el código ──────────────────────────────────────


def test_el_verificador_no_lleva_codigo_de_ningun_proveedor() -> None:
    """Con un cliente por proveedor, cada cliente con uno distinto es una
    versión del producto que hay que mantener, probar y desplegar."""
    from pathlib import Path

    fuente = (
        Path(__file__).resolve().parents[2] / "packages/crmcore/crmcore/datos/verificacion.py"
    ).read_text(encoding="utf-8")
    for proveedor in ("google", "mapbox", "here", "nominatim", "zerobounce", "numverify"):
        assert proveedor not in fuente.lower(), f"aparece «{proveedor}»"


def _fingir_respuesta(monkeypatch: Any, cuerpo: dict[str, Any]) -> None:
    """Sustituye la salida de red por una respuesta fija.

    Se toca `cliente_seguro` y no `httpx` para que el guard de SSRF siga siendo
    parte del camino real en producción: lo que se finge es el otro extremo, no
    la protección.
    """

    class _Respuesta:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return cuerpo

    class _Cliente:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_a: Any) -> None:
            return None

        def request(self, *_a: Any, **_k: Any) -> Any:
            return _Respuesta()

        def get(self, *_a: Any, **_k: Any) -> Any:
            return _Respuesta()

    monkeypatch.setattr("crmcore.red.cliente_seguro", lambda **_k: _Cliente())


@pytest.mark.db
def test_un_veredicto_reciente_no_se_vuelve_a_preguntar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """Muchos registros oficiales tienen cuota, y gastarla repitiendo lo que ya
    se sabe deja sin comprobar lo que no."""
    from datetime import datetime, timezone

    uow = _Uow(db, tenant_id)
    cuenta = svc.crear_cuenta(
        uow,
        nombre="ACME",
        identificadores=[{"tipo": "cif", "pais": "ES", "valor": "B12345674"}],
    )
    db.flush()
    identificador = db.query(IdentificadorFiscal).filter_by(cuenta_id=cuenta.id).one()
    identificador.verificado = True
    identificador.verificado_at = datetime.now(timezone.utc)
    db.flush()

    llamadas = {"n": 0}

    def _contar(*_a: Any, **_k: Any) -> Any:
        llamadas["n"] += 1
        raise AssertionError("no debería haber preguntado")

    monkeypatch.setattr("crmcore.datos.verificacion.verificar", _contar)
    salida = svc.verificar_identificador_fiscal(
        uow, cuenta_id=cuenta.id, identificador_id=identificador.id
    )

    assert llamadas["n"] == 0
    assert salida["estado"] == "valido"
    # Se dice que viene de antes: devolver lo guardado sin decirlo haría creer
    # que el registro acaba de confirmarlo.
    assert salida["desde_cache"] is True


@pytest.mark.db
def test_con_forzar_se_vuelve_a_preguntar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    from datetime import datetime, timezone

    uow = _Uow(db, tenant_id)
    cuenta = svc.crear_cuenta(
        uow,
        nombre="ACME",
        identificadores=[{"tipo": "cif", "pais": "ES", "valor": "B12345674"}],
    )
    db.flush()
    identificador = db.query(IdentificadorFiscal).filter_by(cuenta_id=cuenta.id).one()
    identificador.verificado = True
    identificador.verificado_at = datetime.now(timezone.utc)
    db.flush()

    _configurar(
        db,
        tenant_id,
        "verificador_fiscal",
        {"url": "https://registro.test/x", "mapeo": {"campo": "valid"}},
    )
    _fingir_respuesta(monkeypatch, {"valid": False})

    salida = svc.verificar_identificador_fiscal(
        uow, cuenta_id=cuenta.id, identificador_id=identificador.id, forzar=True
    )
    assert salida["desde_cache"] is False
    assert salida["estado"] == "invalido"


@pytest.mark.db
def test_un_veredicto_viejo_caduca_y_se_vuelve_a_preguntar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un NIF verificado hace tres años no es un NIF verificado. Sin caducidad,
    el estado es una opinión sin fecha."""
    from datetime import datetime, timedelta, timezone

    uow = _Uow(db, tenant_id)
    cuenta = svc.crear_cuenta(
        uow,
        nombre="ACME",
        identificadores=[{"tipo": "cif", "pais": "ES", "valor": "B12345674"}],
    )
    db.flush()
    identificador = db.query(IdentificadorFiscal).filter_by(cuenta_id=cuenta.id).one()
    identificador.verificado = True
    identificador.verificado_at = datetime.now(timezone.utc) - timedelta(
        days=svc.DIAS_VEREDICTO_VIGENTE + 1
    )
    db.flush()

    # Sin verificador configurado: se intenta preguntar y sale no concluyente.
    salida = svc.verificar_identificador_fiscal(
        uow, cuenta_id=cuenta.id, identificador_id=identificador.id
    )
    assert salida["desde_cache"] is False
    assert salida["no_concluyente"] is True
