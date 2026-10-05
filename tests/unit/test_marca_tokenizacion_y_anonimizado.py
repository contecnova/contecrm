"""Marca de origen, tokenización y anonimizado, EJERCITADOS
(CRM-00.05.03.04, CRM-00.05.03.05, CRM-00.05.03.07).

Tres módulos de `crmcore` que **no importaba nadie**, y uno de ellos duplicado
peor en otro sitio:

**La marca de origen.** El audit trail dice quién exportó; la marca dice de dónde
salió este fichero, que es otra pregunta y se hace en otro momento: cuando la hoja
con la cartera de clientes aparece en el ordenador de un competidor, el audit
trail de quien la perdió no está disponible. La salida de datos más grande del
producto —la exportación de un tenant— salía **sin marcar**.

**La tokenización.** El caso real no es que alguien decida guardar tarjetas: es
que un integrador manda el número en un campo de texto libre —«forma de pago:
4111…»— y ahí se queda. Un campo de notas con una tarjeta dentro mete al sistema
en el alcance de PCI igual que una columna dedicada. La comprobación existía y no
la llamaba nadie.

**El anonimizado.** Había dos implementaciones de la misma regla y la que se usaba
era la peor: devolvía dieciséis caracteres hexadecimales para todo, así que un
correo anonimizado no era un correo y ninguna pantalla con validación funcionaba
en el entorno de pruebas. La que conserva la forma estaba escrita y sin llamante.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


# ── Marca de origen (CRM-00.05.03.07) ─────────────────────────────────────


def test_la_marca_no_lleva_el_identificador_de_quien_exporta_en_claro() -> None:
    """El fichero puede acabar en cualquier mano, y eso es un dato de la
    plantilla del cliente. Resumido sigue sirviendo para cotejarlo contra el
    audit trail, que es para lo que hace falta."""
    from crmcore.seguridad import marca

    usuario = uuid4()
    sello = marca.firma(tenant_id=uuid4(), usuario_id=usuario)

    assert str(usuario) not in str(sello)
    # Y tampoco un trozo reconocible: `traza[:32]` de un identificador en claro
    # seguiría llevándolo dentro, y la comprobación de longitud no lo notaría.
    assert usuario.hex[:8] not in sello["traza"]
    assert len(sello["traza"]) == 32
    assert all(c in "0123456789abcdef" for c in sello["traza"])
    assert sello["origen"] == "contecrm"


def test_la_marca_del_csv_va_arriba_y_no_rompe_la_carga() -> None:
    """Con `#` delante: Excel la enseña como una fila más. Al final sería
    invisible en un fichero de mil filas."""
    from crmcore.seguridad import marca

    linea = marca.cabecera_csv(marca.firma(tenant_id=uuid4(), usuario_id=uuid4()))
    assert linea.startswith("# ")
    assert linea.endswith("\n")
    assert "traza=" in linea


# ── Tokenización (CRM-00.05.03.04) ────────────────────────────────────────


def _esquema(db: Any, tenant_id: UUID, campos: list[dict[str, Any]]) -> None:
    from crmcore.metamodelo import EsquemaTenant

    db.add(EsquemaTenant(tenant_id=tenant_id, objeto="cuenta", campos=campos))
    db.flush()


def test_un_numero_de_tarjeta_en_un_campo_libre_no_se_guarda(db: Any, tenant_id: UUID) -> None:
    """No es que alguien decida guardar tarjetas: es que llegan en un campo de
    texto y ahí se quedan, metiendo al sistema entero en el alcance."""
    from crmcore.errors import ErrorValidacion
    from crmcore.metamodelo import validar_y_anotar

    _esquema(db, tenant_id, [{"nombre": "nota", "tipo": "texto_largo", "activo": True}])

    with pytest.raises(ErrorValidacion) as fallo:
        validar_y_anotar(db, tenant_id, "cuenta", {"nota": "forma de pago: 4111 1111 1111 1111"})
    assert fallo.value.error_code == "tokenizacion.numero_en_claro"
    assert fallo.value.detalle["campos"] == ["nota"]
    # Sin bóveda, el mensaje dice otra cosa: no es un paso que falta, es que ese
    # dato no puede entrar aquí de ninguna forma.
    assert fallo.value.detalle["hay_boveda"] is False
    assert "no puede entrar" in str(fallo.value)


def test_un_codigo_largo_que_no_es_una_tarjeta_pasa(db: Any, tenant_id: UUID) -> None:
    """Un aviso que salta con cualquier número largo se ignora a la semana. Por
    eso se comprueba Luhn: un código de pedido de dieciséis dígitos no es una
    tarjeta."""
    from crmcore.metamodelo import validar_y_anotar

    _esquema(db, tenant_id, [{"nombre": "nota", "tipo": "texto_largo", "activo": True}])

    salida = validar_y_anotar(db, tenant_id, "cuenta", {"nota": "pedido 1234567890123456"})
    assert salida["nota"] == "pedido 1234567890123456"


def test_con_boveda_el_mensaje_dice_que_falta_tokenizar(db: Any, tenant_id: UUID) -> None:
    """Con bóveda es un paso que falta; sin ella es que el dato no entra. Son dos
    cosas distintas para quien lo lee."""
    from crmcore.errors import ErrorValidacion
    from crmcore.metamodelo import validar_y_anotar
    from crmcore.security import tokenizacion

    _esquema(db, tenant_id, [{"nombre": "nota", "tipo": "texto_largo", "activo": True}])
    tokenizacion.registrar_boveda(lambda **_: "tok_1", lambda **_: "4111111111111111")
    try:
        with pytest.raises(ErrorValidacion) as fallo:
            validar_y_anotar(db, tenant_id, "cuenta", {"nota": "pago con 4111 1111 1111 1111"})
        assert fallo.value.detalle["hay_boveda"] is True
        assert "tokenízalo" in str(fallo.value)
    finally:
        tokenizacion.registrar_boveda(None, None)  # type: ignore[arg-type]


# ── Anonimizado (CRM-00.05.03.05) ─────────────────────────────────────────


def test_el_valor_falso_conserva_la_forma_del_campo() -> None:
    """Un correo anonimizado tiene que seguir siendo un correo: si no, ninguna
    pantalla con validación funciona en el entorno de pruebas."""
    from services.tenancy import sandboxes as sbx

    salida = sbx.anonimizar_fila(
        fila={"email": "ana@cliente.example", "telefono": "+34600111222", "nota": "lo que sea"},
        reglas={"email": "seudonimizar", "telefono": "seudonimizar", "nota": "seudonimizar"},
        semilla="sal-de-pruebas",
    )["fila"]

    assert "@" in salida["email"]
    assert salida["email"] != "ana@cliente.example"
    assert salida["telefono"].startswith("+")
    assert salida["telefono"] != "+34600111222"


def test_el_mismo_valor_da_el_mismo_sustituto_dentro_del_entorno() -> None:
    """Si «Ana Pérez» sale distinta en dos tablas, el entorno no sirve para
    probar nada que cruce datos — que es casi todo lo que se prueba."""
    from services.tenancy import sandboxes as sbx

    uno = sbx.anonimizar_fila(
        fila={"email": "ana@cliente.example"}, reglas={"email": "seudonimizar"}, semilla="s1"
    )["fila"]
    dos = sbx.anonimizar_fila(
        fila={"email": "ana@cliente.example"}, reglas={"email": "seudonimizar"}, semilla="s1"
    )["fila"]
    assert uno["email"] == dos["email"]


def test_dos_entornos_no_se_pueden_cruzar() -> None:
    """Con la misma sal en todos, juntar dos copias con campos distintos
    anonimizados devolvería el registro entero."""
    from crmcore.seguridad.anonimizar import sal_de_entorno

    from services.tenancy import sandboxes as sbx

    pruebas = sal_de_entorno("pruebas", "secreto")
    formacion = sal_de_entorno("formacion", "secreto")
    assert pruebas != formacion

    a = sbx.anonimizar_fila(
        fila={"email": "ana@cliente.example"}, reglas={"email": "seudonimizar"}, semilla=pruebas
    )["fila"]
    b = sbx.anonimizar_fila(
        fila={"email": "ana@cliente.example"}, reglas={"email": "seudonimizar"}, semilla=formacion
    )["fila"]
    assert a["email"] != b["email"]


def test_un_campo_vacio_se_queda_vacio() -> None:
    """Inventar un correo donde no había ninguno cambiaría los recuentos de
    completitud, y alguien concluiría que pruebas tiene mejores datos que
    producción."""
    from services.tenancy import sandboxes as sbx

    salida = sbx.anonimizar_fila(
        fila={"email": "", "telefono": None},
        reglas={"email": "seudonimizar", "telefono": "seudonimizar"},
        semilla="s1",
    )["fila"]
    assert salida["email"] == ""
    assert salida["telefono"] is None


def test_el_sustituto_de_un_vacio_sigue_siendo_vacio() -> None:
    """La misma decisión, comprobada en el módulo del núcleo.

    Está en los dos sitios a propósito —el de `sandboxes` corta antes— y por eso
    hacen falta las dos pruebas: con una sola, quitar cualquiera de los dos
    guardas no cambia nada y la prueba no se entera de que queda uno solo.
    """
    from crmcore.seguridad.anonimizar import seudonimo

    assert seudonimo("", sal="s1", forma="email") == ""
    assert seudonimo(None, sal="s1", forma="email") is None


def test_una_regla_desconocida_vacia_el_campo() -> None:
    """El silencio por defecto tiene que ser el seguro, no el cómodo."""
    from services.tenancy import sandboxes as sbx

    salida = sbx.anonimizar_fila(
        fila={"email": "ana@cliente.example"},
        reglas={"email": "lo_que_sea"},
        semilla="s1",
    )
    assert salida["fila"]["email"] is None
    assert salida["avisos"]
