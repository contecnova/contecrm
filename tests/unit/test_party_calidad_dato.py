"""Calidad del dato: normalización, duplicados y fusión.

Cubre CRM-01.01.04.01 (detección), .02 (coincidencia difusa), .03 (fusión con
reparentado) y .04 (normalización), además de CRM-01.01.02.06 (consentimientos)
y CRM-01.01.05.01 (timeline).

Es la parte del CRM donde un fallo silencioso hace más daño: un duplicado no
detectado ensucia el maestro para siempre, y una fusión equivocada obliga a
reconstruir a mano contratos, actividades y facturación.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from services.party import duplicados
from services.party import normalizacion as norm
from services.party.modelos import Actividad, Contacto, Cuenta, IdentificadorFiscal

# ── Normalización (sin base de datos) ─────────────────────────────────────


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Construcciones García, S.L.", "CONSTRUCCIONES GARCIA SL"),
        ("Construcciones Garcia, S. L.", "Construcciones García S.A."),
        ("García e Hijos", "Hijos de García"),
        ("ACME Ibérica SLU", "acme iberica"),
    ],
)
def test_la_clave_canonica_junta_la_misma_empresa(a: str, b: str) -> None:
    """CRM-01.01.04.04: formas jurídicas, acentos y orden no distinguen.

    El caso de «S.L.» fija una regresión: al quitar la puntuación quedaban dos
    palabras de una letra que no estaban en la lista de formas jurídicas, así
    que la clave salía `construcciones garcia l s` y NO casaba con la misma
    empresa escrita sin puntos.
    """
    assert norm.clave_canonica_empresa(a) == norm.clave_canonica_empresa(b)


def test_la_clave_canonica_no_junta_empresas_distintas() -> None:
    assert norm.clave_canonica_empresa("Talleres López") != norm.clave_canonica_empresa(
        "Talleres Lorenzo"
    )


@pytest.mark.parametrize(
    "telefono", ["600 11 22 33", "+34 600112233", "0034600112233", "600-11-22-33"]
)
def test_los_telefonos_se_normalizan_a_e164(telefono: str) -> None:
    assert norm.normalizar_telefono(telefono, "ES") == "+34600112233"


def test_un_pais_desconocido_no_inventa_prefijo() -> None:
    """Un prefijo inventado da un número válido que llama a otro sitio.

    Es peor que dejarlo sin normalizar: nada avisa, y alguien acaba llamando.
    """
    assert norm.normalizar_telefono("600112233", "XX") == "600112233"


def test_los_dominios_genericos_no_identifican_una_empresa() -> None:
    """Dos clientes distintos pueden tener los dos una dirección de gmail."""
    assert norm.dominio_de("ana@acme.es") == "acme.es"
    assert norm.dominio_de("ana@gmail.com") == ""


def test_el_correo_no_pierde_la_etiqueta_ni_los_puntos() -> None:
    """Normalizar `ana.perez+crm@` a `anaperez@` juntaría buzones distintos.

    Esa equivalencia solo vale en algunos proveedores; aplicarla en general junta
    dos buzones reales de un dominio corporativo.
    """
    assert norm.normalizar_email("Ana.Perez+CRM@Acme.ES") == "ana.perez+crm@acme.es"


@pytest.mark.parametrize(
    ("valor", "valido"),
    [("12345678Z", True), ("12345678A", False), ("A58818501", True), ("X1234567L", True)],
)
def test_validacion_de_forma_del_nif(valor: str, valido: bool) -> None:
    assert norm.validar_nif_es(valor) is valido


# ── Detección de duplicados (con base de datos) ───────────────────────────


def _cuenta(db: Any, tenant_id: UUID, nombre: str, **extra: Any) -> Cuenta:
    cuenta = Cuenta(
        tenant_id=tenant_id,
        nombre=nombre,
        clave_canonica=norm.clave_canonica_empresa(nombre),
        **extra,
    )
    db.add(cuenta)
    db.flush()
    return cuenta


def test_el_mismo_identificador_fiscal_es_concluyente(db: Any, tenant_id: UUID) -> None:
    """CRM-01.01.04.01: dos entidades con el mismo NIF son la misma entidad."""
    cuenta = _cuenta(db, tenant_id, "Talleres López, S.L.")
    db.add(
        IdentificadorFiscal(
            tenant_id=tenant_id,
            cuenta_id=cuenta.id,
            tipo="cif",
            pais="ES",
            valor="A58818501",
            valor_normalizado="A58818501",
        )
    )
    db.flush()

    candidatos = duplicados.buscar_cuentas_duplicadas(
        db,
        tenant_id=tenant_id,
        # Nombre completamente distinto: lo que decide es el identificador.
        nombre="Otra Cosa Totalmente Distinta",
        identificadores=["A-58818501"],
    )
    assert len(candidatos) == 1
    assert candidatos[0].concluyente is True
    assert candidatos[0].senales == ("identificador_fiscal",)


def test_un_nombre_parecido_se_propone_pero_no_bloquea(db: Any, tenant_id: UUID) -> None:
    """Una clave canónica igual es un CANDIDATO, no una prueba.

    Es la regla que evita el peor error posible: fusionar dos clientes que no
    eran el mismo. «Construcciones García S.L.» y «Construcciones García S.A.»
    pueden ser dos sociedades del mismo grupo.
    """
    _cuenta(db, tenant_id, "Construcciones García, S.L.")

    candidatos = duplicados.buscar_cuentas_duplicadas(
        db, tenant_id=tenant_id, nombre="Construcciones Garcia SA"
    )
    assert candidatos, "debería proponerse como candidato"
    # Dos señales, no una: el parecido del nombre **y** que las formas jurídicas
    # son distintas. La segunda se añadió después de escribir esta prueba y la
    # expectativa se quedó vieja — pedía exactamente `("nombre",)`, así que
    # fallaba por la mejora. Se pide más que antes, no menos.
    assert set(candidatos[0].senales) == {"nombre", "forma_juridica_distinta"}
    # Y lo que de verdad comprueba esta prueba: que se propone **y no bloquea**.
    # «S.L.» y «S.A.» son dos NIF y dos contabilidades, y fusionarlas es caro de
    # deshacer.
    assert candidatos[0].concluyente is False


def test_no_se_propone_una_cuenta_sin_parecido(db: Any, tenant_id: UUID) -> None:
    _cuenta(db, tenant_id, "Talleres López, S.L.")
    assert (
        duplicados.buscar_cuentas_duplicadas(
            db, tenant_id=tenant_id, nombre="Consultoría Marítima del Norte"
        )
        == []
    )


def test_las_cuentas_ya_fusionadas_no_se_proponen(db: Any, tenant_id: UUID) -> None:
    """Proponer una ficha ya absorbida llevaría a fusionar en cadena hacia atrás."""
    viva = _cuenta(db, tenant_id, "ACME Ibérica, S.L.")
    absorbida = _cuenta(db, tenant_id, "ACME Iberica SL")
    absorbida.fusionada_en_id = viva.id
    db.flush()

    candidatos = duplicados.buscar_cuentas_duplicadas(
        db, tenant_id=tenant_id, nombre="ACME Iberica"
    )
    assert [c.id for c in candidatos] == [viva.id]


def test_el_correo_es_concluyente_para_un_contacto(db: Any, tenant_id: UUID) -> None:
    """Dos personas no comparten buzón."""
    contacto = Contacto(
        tenant_id=tenant_id,
        nombre="Ana",
        apellidos="Pérez",
        nombre_completo="Ana Pérez",
        clave_canonica=norm.clave_canonica_persona("Ana", "Pérez"),
        email="ana.perez@acme.es",
    )
    db.add(contacto)
    db.flush()

    candidatos = duplicados.buscar_contactos_duplicados(
        db, tenant_id=tenant_id, nombre="Anita", apellidos="P.", email="Ana.Perez@ACME.es"
    )
    assert len(candidatos) == 1 and candidatos[0].concluyente


# ── Fusión ────────────────────────────────────────────────────────────────


def test_la_fusion_reparenta_todo_lo_que_colgaba(db: Any, tenant_id: UUID) -> None:
    """CRM-01.01.04.03: nada puede quedarse colgando de la ficha absorbida.

    Una actividad huérfana no da ningún síntoma: simplemente desaparece del
    historial del cliente, y nadie lo nota hasta que hace falta.
    """
    superviviente = _cuenta(db, tenant_id, "ACME Ibérica, S.L.", email="info@acme.es")
    absorbida = _cuenta(db, tenant_id, "ACME Iberica SL", telefono="+34600112233")

    db.add(
        IdentificadorFiscal(
            tenant_id=tenant_id,
            cuenta_id=absorbida.id,
            tipo="cif",
            pais="ES",
            valor="A58818501",
            valor_normalizado="A58818501",
        )
    )
    db.add(
        Actividad(
            tenant_id=tenant_id,
            tipo="llamada",
            asunto="Llamada de seguimiento",
            cuenta_id=absorbida.id,
        )
    )
    db.flush()

    fusion = duplicados.fusionar_cuentas(
        db,
        superviviente_id=superviviente.id,
        absorbida_id=absorbida.id,
        motivo="son la misma empresa, cargadas dos veces",
    )
    db.flush()

    assert fusion.relaciones_movidas.get("actividades") == 1
    assert fusion.relaciones_movidas.get("identificadores_fiscales") == 1

    actividad = db.query(Actividad).one()
    assert actividad.cuenta_id == superviviente.id

    # El hueco del superviviente se rellena con lo que sí tenía la absorbida.
    assert superviviente.telefono == "+34600112233"
    # Y lo que ya tenía no se pisa.
    assert superviviente.email == "info@acme.es"
    # La absorbida sigue existiendo, apuntando a su superviviente.
    assert absorbida.fusionada_en_id == superviviente.id


def test_la_fusion_de_contactos_propaga_el_no_contactar(db: Any, tenant_id: UUID) -> None:
    """Si UNA de las dos fichas pidió no ser contactada, la fusionada tampoco.

    Equivocarse aquí significa escribir a alguien que pidió expresamente que no
    se le escriba, que es de los pocos errores de un CRM con consecuencias
    legales inmediatas.
    """
    a = Contacto(
        tenant_id=tenant_id,
        nombre="Ana",
        apellidos="Pérez",
        nombre_completo="Ana Pérez",
        clave_canonica="ana perez",
        email="ana@acme.es",
        no_contactar=False,
    )
    b = Contacto(
        tenant_id=tenant_id,
        nombre="Ana",
        apellidos="Pérez García",
        nombre_completo="Ana Pérez García",
        clave_canonica="ana garcia perez",
        no_contactar=True,
    )
    db.add_all([a, b])
    db.flush()

    duplicados.fusionar_contactos(
        db, superviviente_id=a.id, absorbido_id=b.id, motivo="misma persona"
    )
    db.flush()
    assert a.no_contactar is True


def test_no_se_puede_fusionar_dos_veces(db: Any, tenant_id: UUID) -> None:
    from crmcore.errors import Conflicto

    a = _cuenta(db, tenant_id, "Uno SL")
    b = _cuenta(db, tenant_id, "Uno S.L.")
    c = _cuenta(db, tenant_id, "Uno, Sociedad Limitada")
    duplicados.fusionar_cuentas(db, superviviente_id=a.id, absorbida_id=b.id, motivo="x")
    db.flush()

    with pytest.raises(Conflicto) as exc:
        duplicados.fusionar_cuentas(db, superviviente_id=c.id, absorbida_id=b.id, motivo="y")
    assert exc.value.error_code == "party.ya_fusionada"


def test_deshacer_una_fusion_restaura_los_campos(db: Any, tenant_id: UUID) -> None:
    a = _cuenta(db, tenant_id, "Uno SL", email="uno@acme.es")
    b = _cuenta(db, tenant_id, "Uno S.L.", email="dos@acme.es", telefono="+34600000000")
    fusion = duplicados.fusionar_cuentas(
        db, superviviente_id=a.id, absorbida_id=b.id, motivo="prueba"
    )
    db.flush()
    assert b.fusionada_en_id == a.id

    duplicados.deshacer_fusion(db, fusion.id, motivo="era un error, son dos sociedades")
    db.flush()
    assert b.fusionada_en_id is None
    assert b.email == "dos@acme.es"
