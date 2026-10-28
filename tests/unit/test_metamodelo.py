"""Extensión sin código de punta a punta (CRM-00.04.03).

Lo que se prueba aquí no es que se pueda definir un campo —eso ya estaba— sino
que ese campo **sirva**: que la API lo valide, que se pueda filtrar por él, que
salga como columna para un BI, que viaje a los flujos y que se pueda retirar
sabiendo si alguien lo usaba.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore import metamodelo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado


def _publicar(
    db: Any, tenant_id: UUID, objeto: str, campos: list[dict[str, Any]], version: int = 1
) -> None:
    metamodelo.aplicar_esquema(
        db, tenant_id=tenant_id, objeto=objeto, campos=campos, version=version
    )


CAMPOS = [
    {"nombre": "obra", "tipo": "texto", "restricciones": {"max_longitud": 10}},
    {"nombre": "presupuesto", "tipo": "moneda", "restricciones": {"minimo": 0}},
    {"nombre": "visita", "tipo": "fecha"},
    {"nombre": "activo_obra", "tipo": "booleano"},
    {"nombre": "fase", "tipo": "lista", "restricciones": {"opciones": ["previa", "obra", "fin"]}},
]


# ── Validación automática (CRM-00.04.03.02) ───────────────────────────────


@pytest.mark.db
def test_un_campo_no_definido_se_rechaza(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Aceptarlo convertiría una errata en un dato que se guarda, no sale en
    ningún formulario y no lo encuentra nadie; al año, la mitad del JSONB sería
    basura que nadie se atreve a borrar porque no se sabe quién la puso."""
    _publicar(db, tenant_id, "cuenta", CAMPOS)
    with pytest.raises(ErrorValidacion) as e:
        metamodelo.validar(db, tenant_id, "cuenta", {"obr": "Torre"})
    assert e.value.error_code == "metamodelo.campos_invalidos"
    assert e.value.errores[0]["motivo"] == "desconocido"
    # Y se dice qué campos SÍ existen: sin eso, quien recibe el error prueba a
    # ciegas.
    assert "obra" in e.value.errores[0]["definidos"]


@pytest.mark.db
def test_los_tipos_se_normalizan_al_escribir(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Si cada lector convirtiera por su cuenta, dos lectores discreparían —uno
    leyendo "10" y otro 10— y el filtro no encontraría lo que la ficha enseña."""
    _publicar(db, tenant_id, "cuenta", CAMPOS)
    salida = metamodelo.validar(
        db,
        tenant_id,
        "cuenta",
        {"presupuesto": "1500.50", "activo_obra": "true", "visita": "2026-03-01T10:00:00"},
    )
    assert salida["presupuesto"] == 1500.5
    assert salida["activo_obra"] is True
    assert salida["visita"] == "2026-03-01"


@pytest.mark.db
def test_las_restricciones_declaradas_se_aplican(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _publicar(db, tenant_id, "cuenta", CAMPOS)
    with pytest.raises(ErrorValidacion) as e:
        metamodelo.validar(
            db, tenant_id, "cuenta", {"obra": "x" * 40, "presupuesto": -1, "fase": "otra"}
        )
    motivos = {f["motivo"] for f in e.value.errores}
    assert motivos == {"longitud", "rango", "opcion"}


@pytest.mark.db
def test_un_obligatorio_solo_se_exige_al_crear(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """En una actualización solo llegan los campos que se tocan: exigir los
    obligatorios que no vienen rechazaría un cambio de teléfono por un campo que
    el registro ya tiene relleno."""
    campos = [{"nombre": "obra", "tipo": "texto", "obligatorio": True}]
    _publicar(db, tenant_id, "cuenta", campos)
    with pytest.raises(ErrorValidacion):
        metamodelo.validar(db, tenant_id, "cuenta", {})
    assert metamodelo.validar(db, tenant_id, "cuenta", {}, parcial=True) == {}


@pytest.mark.db
def test_un_campo_deprecado_se_lee_pero_no_se_escribe(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que permite retirar un campo sin romper de golpe una integración
    que aún lo manda: se ignora el valor y se avisa, en vez de cortarle el alta."""
    _publicar(db, tenant_id, "cuenta", [{"nombre": "viejo", "tipo": "texto", "deprecado": True}])
    assert metamodelo.validar(db, tenant_id, "cuenta", {"viejo": "x"}) == {}


@pytest.mark.db
def test_sin_esquema_publicado_no_se_acepta_cualquier_cosa(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«No hay esquema» y «acepta lo que sea» son cosas distintas."""
    with pytest.raises(ErrorValidacion):
        metamodelo.validar(db, tenant_id, "cuenta", {"lo_que_sea": 1})
    # Y no mandar nada es correcto: un tenant sin campos propios es lo normal.
    assert metamodelo.validar(db, tenant_id, "cuenta", {}) == {}


# ── Filtro y orden con tipo (CRM-00.04.03.03) ─────────────────────────────


@pytest.mark.db
def test_el_filtro_numerico_compara_como_numero(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin castear, JSONB compara texto y `"9" > "10"` es cierto. Un filtro
    «mayor que 10» que devuelve el de 9 es peor que no tener filtro, porque el
    que lo usa se lo cree."""
    from sqlalchemy import select

    from services.party.modelos import Cuenta

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    for nombre, valor in (("Nueve", 9), ("Diez", 10), ("Cien", 100)):
        db.add(
            Cuenta(
                tenant_id=tenant_id,
                nombre=nombre,
                clave_canonica=nombre.lower(),
                campos={"presupuesto": valor},
            )
        )
    db.flush()

    condicion = metamodelo.condicion(
        db, Cuenta, tenant_id, "cuenta", campo_nombre="presupuesto", op=">", valor=10
    )
    nombres = {
        c.nombre
        for c in db.execute(
            select(Cuenta).where(Cuenta.tenant_id == tenant_id, condicion)
        ).scalars()
    }
    assert nombres == {"Cien"}


@pytest.mark.db
def test_no_se_filtra_por_un_campo_que_no_existe(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.party.modelos import Cuenta

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    with pytest.raises(ErrorValidacion) as e:
        metamodelo.condicion(
            db, Cuenta, tenant_id, "cuenta", campo_nombre="inventado", op="=", valor=1
        )
    assert e.value.error_code == "metamodelo.campo_desconocido"


@pytest.mark.db
def test_cada_operador_declarado_filtra_lo_que_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Los diez operadores, uno a uno y **recorriendo la lista declarada**.

    Que un operador esté implementado no lo prueba: están los diez, porque uno
    que faltara reventaría con `KeyError`. Lo que no se veía es un operador que
    filtra **mal** — `>=` que se comporta como `>`, `empieza` que busca por
    dentro—, y eso no da error: devuelve otras filas. Un listado que enseña las
    filas equivocadas es peor que uno que falla, porque se usa.

    La lista se recorre de `OPERADORES_FILTRO` y no se escribe aquí: una
    escrita a mano se queda corta el día que alguien añada un operador, y justo
    ése sería el que entra sin probar.
    """
    from sqlalchemy import select

    from services.party.modelos import Cuenta

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    for nombre, obra, presupuesto in (
        ("Alfa", "puente", 10),
        ("Beta", "puerto", 20),
        ("Gamma", None, 30),
    ):
        db.add(
            Cuenta(
                tenant_id=tenant_id,
                nombre=nombre,
                clave_canonica=nombre.lower(),
                campos={"presupuesto": presupuesto}
                if obra is None
                else {"obra": obra, "presupuesto": presupuesto},
            )
        )
    db.flush()

    def quienes(**kw: Any) -> set[str]:
        cond = metamodelo.condicion(db, Cuenta, tenant_id, "cuenta", **kw)
        return {
            c.nombre
            for c in db.execute(select(Cuenta).where(Cuenta.tenant_id == tenant_id, cond)).scalars()
        }

    # Lo que tiene que devolver cada uno, con los datos de arriba delante.
    esperado: dict[str, tuple[dict[str, Any], set[str]]] = {
        "=": ({"campo_nombre": "presupuesto", "op": "=", "valor": 20}, {"Beta"}),
        "!=": ({"campo_nombre": "presupuesto", "op": "!=", "valor": 20}, {"Alfa", "Gamma"}),
        ">": ({"campo_nombre": "presupuesto", "op": ">", "valor": 20}, {"Gamma"}),
        # El que más se confunde con el de al lado: si `>=` se comportara como
        # `>`, Beta desaparecería y nadie lo notaría.
        ">=": ({"campo_nombre": "presupuesto", "op": ">=", "valor": 20}, {"Beta", "Gamma"}),
        "<": ({"campo_nombre": "presupuesto", "op": "<", "valor": 20}, {"Alfa"}),
        "<=": ({"campo_nombre": "presupuesto", "op": "<=", "valor": 20}, {"Alfa", "Beta"}),
        "contiene": ({"campo_nombre": "obra", "op": "contiene", "valor": "uert"}, {"Beta"}),
        # Y éste, al revés: `empieza` que buscara por dentro traería Beta.
        "empieza": ({"campo_nombre": "obra", "op": "empieza", "valor": "puen"}, {"Alfa"}),
        "en": (
            {"campo_nombre": "presupuesto", "op": "en", "valor": [10, 30]},
            {"Alfa", "Gamma"},
        ),
        "vacio": ({"campo_nombre": "obra", "op": "vacio", "valor": None}, {"Gamma"}),
    }

    # Ninguno sin su caso: si alguien añade un operador y no lo pone aquí, esto
    # lo dice en vez de dejarlo entrar sin probar.
    faltan = sorted(set(metamodelo.OPERADORES_FILTRO) - set(esperado))
    assert not faltan, f"operadores declarados y sin caso de prueba: {faltan}"

    for op, (argumentos, quien) in esperado.items():
        assert quienes(**argumentos) == quien, f"el operador «{op}» filtra otra cosa"


@pytest.mark.db
def test_la_gramatica_de_operadores_esta_cerrada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una gramática abierta sobre JSONB acaba siendo SQL interpolado, y ahí es
    donde entra la inyección."""
    from services.party.modelos import Cuenta

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    with pytest.raises(ErrorValidacion) as e:
        metamodelo.condicion(
            db, Cuenta, tenant_id, "cuenta", campo_nombre="obra", op="; DROP TABLE", valor="x"
        )
    assert e.value.error_code == "metamodelo.operador_no_admitido"


@pytest.mark.db
def test_el_indice_es_parcial_por_tenant(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Un índice global sobre una expresión JSONB indexaría las filas de los mil
    tenants para servir las consultas de uno, y crecería con todos."""
    campos = [{"nombre": "presupuesto", "tipo": "moneda", "indexado": True}]
    sentencias = metamodelo.sql_de_indices("cuentas", tenant_id, campos)
    assert len(sentencias) == 1
    assert "::numeric" in sentencias[0]
    assert f"WHERE tenant_id = '{tenant_id}'" in sentencias[0]


@pytest.mark.db
def test_un_campo_sin_marcar_no_crea_indice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un índice que sobra no falla nada: solo hace más lenta cada escritura de
    la tabla para siempre, que es la forma más cara de no enterarse."""
    assert metamodelo.sql_de_indices("cuentas", tenant_id, CAMPOS) == []


@pytest.mark.db
def test_un_nombre_raro_no_llega_al_ddl(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """En DDL no hay parámetros: lo que se cuela, se ejecuta."""
    with pytest.raises(ErrorValidacion) as e:
        metamodelo.sql_de_indices(
            "cuentas",
            tenant_id,
            [{"nombre": "x'; DROP TABLE cuentas--", "tipo": "texto", "indexado": True}],
        )
    assert e.value.error_code == "metamodelo.nombre_no_indexable"


# ── Vista tipada para BI (CRM-00.04.03.04) ────────────────────────────────


@pytest.mark.db
def test_la_vista_proyecta_cada_campo_con_su_tipo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que permite que Power BI o un SELECT de sistemas lean los campos de
    la implantación sin saber que por debajo es JSONB."""
    sentencia = metamodelo.sql_de_vista("cuentas", "cuenta", tenant_id, CAMPOS)
    assert '"presupuesto"' in sentencia and "::numeric" in sentencia
    assert '"visita"' in sentencia and "::date" in sentencia
    assert '"activo_obra"' in sentencia and "::boolean" in sentencia
    assert f"WHERE tenant_id = '{tenant_id}'" in sentencia


@pytest.mark.db
def test_la_vista_se_puede_crear_y_consultar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from sqlalchemy import text

    from services.party.modelos import Cuenta

    db.add(
        Cuenta(
            tenant_id=tenant_id,
            nombre="Con campos",
            clave_canonica="con-campos",
            campos={"presupuesto": 1200, "obra": "Torre"},
        )
    )
    db.flush()
    metamodelo.sincronizar_vista(db, "cuentas", "cuenta", tenant_id, CAMPOS)

    nombre = metamodelo.nombre_de_vista("cuenta", tenant_id)
    fila = db.execute(text(f'SELECT "obra", "presupuesto" FROM {nombre}')).first()  # noqa: S608
    assert fila[0] == "Torre"
    assert float(fila[1]) == 1200.0


# ── Réplica del esquema ───────────────────────────────────────────────────


@pytest.mark.db
def test_un_evento_viejo_no_pisa_el_esquema_bueno(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La entrega es at-least-once y no garantiza orden: sin comparar versión,
    un evento reenviado devolvería al tenant campos que ya había quitado."""
    _publicar(db, tenant_id, "cuenta", CAMPOS, version=5)
    metamodelo.aplicar_esquema(db, tenant_id=tenant_id, objeto="cuenta", campos=[], version=2)
    assert len(metamodelo.campos_de(db, tenant_id, "cuenta")) == len(CAMPOS)


@pytest.mark.db
def test_el_esquema_es_por_tenant(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _publicar(db, tenant_id, "cuenta", CAMPOS)
    assert metamodelo.campos_de(db, otro_tenant_id, "cuenta") == []


# ── Uso y trazabilidad (CRM-00.04.03.12) ──────────────────────────────────


@pytest.mark.db
def test_el_uso_se_cuenta_al_escribir(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Leer mide quién mira; escribir mide si el campo se rellena, que es la
    pregunta de quien se plantea retirarlo."""
    from crmcore.metamodelo import UsoCampo
    from sqlalchemy import select

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    metamodelo.validar_y_anotar(db, tenant_id, "cuenta", {"obra": "Torre"})
    metamodelo.validar_y_anotar(db, tenant_id, "cuenta", {"obra": "Nave"})
    db.flush()

    fila = db.execute(
        select(UsoCampo).where(UsoCampo.tenant_id == tenant_id, UsoCampo.campo == "obra")
    ).scalar_one()
    assert fila.escrituras == 2


@pytest.mark.db
def test_un_campo_vacio_no_cuenta_como_uso(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Contar los vacíos haría que todo campo pareciera usado y la métrica no
    serviría para decidir nada."""
    from crmcore.metamodelo import UsoCampo
    from sqlalchemy import func, select

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    metamodelo.validar_y_anotar(db, tenant_id, "cuenta", {"obra": None})
    db.flush()
    assert db.execute(select(func.count()).select_from(UsoCampo)).scalar_one() == 0


# ── Publicación, previsualización y paquetes ──────────────────────────────


@pytest.fixture
def objeto_con_campos(db: Any, tenant_id: UUID) -> Any:
    from services.metadata.modelos import CampoDefinido, ObjetoDefinido

    objeto = ObjetoDefinido(
        tenant_id=tenant_id, nombre="cuenta", etiqueta="Cuenta", origen="estandar"
    )
    db.add(objeto)
    db.flush()
    db.add(
        CampoDefinido(
            tenant_id=tenant_id,
            objeto_id=objeto.id,
            nombre="obra",
            etiqueta="Obra",
            tipo="texto",
        )
    )
    db.flush()
    return objeto


@pytest.mark.db
def test_publicar_dos_veces_lo_mismo_no_hace_nada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, objeto_con_campos: Any
) -> None:
    """Una publicación vacía subiría la versión y mandaría un evento a todos los
    servicios para no cambiar nada."""
    from services.metadata import publicacion

    publicacion.publicar(db, tenant_id, "cuenta")
    with pytest.raises(Conflicto) as e:
        publicacion.publicar(db, tenant_id, "cuenta")
    assert e.value.error_code == "metadata.sin_cambios"


@pytest.mark.db
def test_la_previsualizacion_avisa_de_los_registros_sin_rellenar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, objeto_con_campos: Any
) -> None:
    """Quien añade un campo obligatorio a un objeto con ochenta mil registros no
    lo sabe hasta que alguien no puede guardar uno viejo."""
    from services.metadata import publicacion
    from services.metadata.modelos import CampoDefinido
    from services.party.modelos import Cuenta

    db.add(Cuenta(tenant_id=tenant_id, nombre="Vieja", clave_canonica="vieja"))
    db.add(
        CampoDefinido(
            tenant_id=tenant_id,
            objeto_id=objeto_con_campos.id,
            nombre="cif_obra",
            etiqueta="CIF",
            tipo="texto",
            obligatorio=True,
        )
    )
    db.flush()

    salida = publicacion.previsualizar(db, tenant_id, "cuenta")
    assert "cif_obra" in salida["anadidos"]
    assert salida["registros_sin_rellenar"]["cif_obra"] == 1
    assert salida["seguro"] is False


@pytest.mark.db
def test_un_objeto_del_que_no_se_sabe_la_tabla_lo_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«No se ha podido contar» y «no afecta a nadie» son cosas distintas, y la
    diferencia es justo la que importa antes de publicar."""
    from services.metadata import publicacion
    from services.metadata.modelos import ObjetoDefinido

    db.add(ObjetoDefinido(tenant_id=tenant_id, nombre="proyecto_obra", etiqueta="Obra"))
    db.flush()
    salida = publicacion.previsualizar(db, tenant_id, "proyecto_obra")
    assert salida["registros"] is None
    assert any("no es fiable" in a for a in salida["avisos"])


@pytest.mark.db
def test_el_paquete_lleva_configuracion_y_nunca_datos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, objeto_con_campos: Any
) -> None:
    """Un paquete que arrastrara registros convertiría una promoción a
    producción en una fuga."""
    from services.metadata import publicacion
    from services.party.modelos import Cuenta

    db.add(Cuenta(tenant_id=tenant_id, nombre="Secreta", clave_canonica="secreta"))
    db.flush()

    paquete = publicacion.exportar_paquete(db, tenant_id)
    texto = str(paquete)
    assert "Secreta" not in texto
    assert paquete["objetos"][0]["campos"][0]["nombre"] == "obra"


@pytest.mark.db
def test_instalar_simula_por_defecto(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID, objeto_con_campos: Any
) -> None:
    """Un paquete es un cambio de modelo de datos en producción, y el error más
    caro es pulsar el botón creyendo que aún se estaba mirando."""
    from sqlalchemy import func, select

    from services.metadata import publicacion
    from services.metadata.modelos import ObjetoDefinido

    paquete = publicacion.exportar_paquete(db, tenant_id)
    antes = db.execute(
        select(func.count())
        .select_from(ObjetoDefinido)
        .where(ObjetoDefinido.tenant_id == otro_tenant_id)
    ).scalar_one()

    salida = publicacion.instalar_paquete(db, otro_tenant_id, paquete)
    assert salida["simulado"] is True
    assert "cuenta" in salida["objetos_nuevos"]
    db.flush()
    despues = db.execute(
        select(func.count())
        .select_from(ObjetoDefinido)
        .where(ObjetoDefinido.tenant_id == otro_tenant_id)
    ).scalar_one()
    assert antes == despues


@pytest.mark.db
def test_un_campo_con_otro_tipo_no_se_pisa(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID, objeto_con_campos: Any
) -> None:
    """Sobrescribir la configuración que alguien ajustó en producción con la de
    un entorno de pruebas es la forma habitual de perder dos semanas de trabajo
    de un consultor."""
    from services.metadata import publicacion
    from services.metadata.modelos import CampoDefinido, ObjetoDefinido

    otro = ObjetoDefinido(tenant_id=otro_tenant_id, nombre="cuenta", etiqueta="Cuenta")
    db.add(otro)
    db.flush()
    db.add(
        CampoDefinido(
            tenant_id=otro_tenant_id,
            objeto_id=otro.id,
            nombre="obra",
            etiqueta="Obra",
            tipo="numero",
        )
    )
    db.flush()

    paquete = publicacion.exportar_paquete(db, tenant_id)
    salida = publicacion.instalar_paquete(db, otro_tenant_id, paquete, simular=False)
    assert salida["conflictos"][0]["campo"] == "cuenta.obra"
    assert salida["conflictos"][0]["aqui"] == "numero"


@pytest.mark.db
def test_un_paquete_de_otro_formato_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.metadata import publicacion

    with pytest.raises(ErrorValidacion) as e:
        publicacion.instalar_paquete(db, tenant_id, {"formato": 99, "objetos": []})
    assert e.value.error_code == "metadata.paquete_no_soportado"


@pytest.mark.db
def test_la_trazabilidad_dice_si_se_puede_retirar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, objeto_con_campos: Any
) -> None:
    """Sin esto, la respuesta es siempre «no lo sé» y por si acaso no se quita
    nada: así acaba un modelo con trescientos campos."""
    from services.metadata import publicacion

    salida = publicacion.trazabilidad(db, tenant_id, "cuenta")
    campo = salida["campos"][0]
    assert campo["campo"] == "obra"
    assert campo["escrituras"] == 0
    assert campo["se_puede_retirar"] is True
    assert "obra" in salida["sin_usar"]


@pytest.mark.db
def test_un_objeto_inexistente_no_se_traza(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    from services.metadata import publicacion

    with pytest.raises(NoEncontrado):
        publicacion.trazabilidad(db, tenant_id, "no_existe")


@pytest.mark.db
def test_materializar_se_decide_con_una_medida(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin número, cada cliente que note su lista lenta pediría columna, y
    acabaríamos con el ALTER TABLE de siempre disfrazado de optimización."""
    from crmcore.metamodelo import UsoCampo

    from services.metadata import publicacion

    db.add(UsoCampo(tenant_id=tenant_id, objeto="cuenta", campo="obra", escrituras=50_000))
    db.add(UsoCampo(tenant_id=tenant_id, objeto="cuenta", campo="nota", escrituras=3))
    db.flush()

    salida = publicacion.candidatos_a_materializar(db, tenant_id, "cuenta")
    assert [c["campo"] for c in salida["candidatos"]] == ["obra"]


# ── Punta a punta por la API de negocio (CRM-00.04.03.02, .05) ────────────


@pytest.mark.db
def test_una_cuenta_se_crea_con_sus_campos_propios(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La prueba que justifica el bloque: definir el campo y usarlo, sin una
    línea de código por campo."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.party import servicio as party

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    cuenta = party.crear_cuenta(
        uow, nombre="Constructora", campos={"obra": "Torre", "presupuesto": "1500"}
    )
    assert cuenta.campos["presupuesto"] == 1500.0


@pytest.mark.db
def test_una_errata_en_un_campo_propio_corta_el_alta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.db.uow import UnidadDeTrabajo

    from services.party import servicio as party

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    with pytest.raises(ErrorValidacion):
        party.crear_cuenta(uow, nombre="Constructora", campos={"presupesto": 1500})


@pytest.mark.db
def test_actualizar_un_campo_no_borra_los_demas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Mandar solo el campo que cambia es lo natural desde un formulario, y
    reemplazar borraría en silencio todos los demás."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.party import servicio as party

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    cuenta = party.crear_cuenta(
        uow, nombre="Constructora", campos={"obra": "Torre", "presupuesto": 1500}
    )
    party.actualizar_cuenta(uow, cuenta.id, {"campos": {"presupuesto": 2000}})
    assert cuenta.campos == {"obra": "Torre", "presupuesto": 2000.0}


@pytest.mark.db
def test_los_campos_propios_viajan_en_el_evento(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin ellos, un flujo no puede condicionar por un campo de la implantación:
    `automation` no lee el esquema de `party`, así que si el dato no va en el
    evento, para el flujo no existe (CRM-00.04.03.05)."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.party import servicio as party

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    party.crear_cuenta(uow, nombre="Constructora", campos={"obra": "Torre"})

    evento = [e for e in uow._pendientes if e["tipo"] == "account.created"][0]
    assert evento["data"]["campos"] == {"obra": "Torre"}


def test_una_condicion_de_flujo_puede_mirar_un_campo_propio() -> None:
    """El resolutor de rutas ya soporta `@campos.obra`; lo que faltaba era que
    el dato llegara. Con las dos cosas, la automatización por campo de
    implantación funciona sin escribir nada."""
    from services.orchestrator.motor import resolver

    valores = {"cuenta_id": str(uuid4()), "campos": {"obra": "Torre"}}
    assert resolver("@campos.obra", valores) == "Torre"


# ── Informes y exportación (CRM-00.04.03.06, .08) ─────────────────────────


@pytest.mark.db
def test_el_modelo_semantico_dice_que_se_puede_sumar_y_que_no(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Si cada herramienta dedujera el papel por su cuenta, una acabaría
    ofreciendo «sumar» sobre un código postal, que es un número que no se suma."""
    from services.analytics import modelo_semantico as sem

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    salida = sem.modelo_de(db, tenant_id, ["cuenta"])
    roles = {c["nombre"]: c["rol"] for c in salida["objetos"][0]["campos"]}
    assert roles["presupuesto"] == "metrica"
    assert roles["fase"] == "dimension"
    assert roles["visita"] == "temporal"


@pytest.mark.db
def test_el_modelo_semantico_apunta_a_la_vista_tipada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que hace que sea usable sin modelar nada: las columnas ya vienen
    con su tipo y no hay que saber que por debajo hay JSONB."""
    from crmcore import metamodelo as mm

    from services.analytics import modelo_semantico as sem

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    salida = sem.modelo_de(db, tenant_id, ["cuenta"])
    assert salida["objetos"][0]["vista"] == mm.nombre_de_vista("cuenta", tenant_id)


@pytest.mark.db
def test_un_campo_personal_no_se_ofrece_como_dimension(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Acabaría en un cuadro de mando que alguien comparte por correo, y el
    enmascaramiento por rol de la API no llega hasta ahí. Y se dice cuál se ha
    dejado fuera: omitirlo haría que alguien buscara un campo que existe, no lo
    encontrara y concluyera que el sistema no lo tiene."""
    from services.analytics import modelo_semantico as sem

    _publicar(
        db,
        tenant_id,
        "cuenta",
        [
            {"nombre": "dni_contacto", "tipo": "texto", "sensibilidad": "personal"},
            {"nombre": "obra", "tipo": "texto"},
        ],
    )
    salida = sem.modelo_de(db, tenant_id, ["cuenta"])
    nombres = {c["nombre"] for c in salida["objetos"][0]["campos"]}
    assert nombres == {"obra"}
    assert salida["excluidos_por_sensibilidad"] == ["cuenta.dni_contacto"]


@pytest.mark.db
def test_el_modelo_semantico_no_lleva_datos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Mandar valores convertiría una descripción de esquema en una copia del
    CRM fuera de su sitio."""
    from services.analytics import modelo_semantico as sem
    from services.party.modelos import Cuenta

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    db.add(
        Cuenta(
            tenant_id=tenant_id,
            nombre="Secreta",
            clave_canonica="secreta",
            campos={"obra": "Confidencial"},
        )
    )
    db.flush()
    salida = sem.modelo_de(db, tenant_id, ["cuenta"])
    assert "Confidencial" not in str(salida)
    assert salida["contiene_datos"] is False


@pytest.mark.db
def test_la_exportacion_incluye_los_campos_propios(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Quien exporta no tiene por qué saber cuáles vienen con el producto y
    cuáles añadió su consultor."""
    from crmcore.datos.masivas import columnas_exportables, exportar
    from sqlalchemy import select

    from services.party.modelos import Cuenta

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    db.add(
        Cuenta(
            tenant_id=tenant_id,
            nombre="Constructora",
            clave_canonica="constructora",
            campos={"obra": "Torre", "presupuesto": 1500},
        )
    )
    db.flush()

    columnas = columnas_exportables(db, tenant_id, "cuenta", ["nombre"])
    assert "obra" in columnas and "presupuesto" in columnas

    filas = exportar(
        db,
        select(Cuenta).where(Cuenta.tenant_id == tenant_id),
        columnas=columnas,
        limite=10,
    )
    assert filas[0]["obra"] == "Torre"
    assert filas[0]["nombre"] == "Constructora"


@pytest.mark.db
def test_las_columnas_exportadas_no_cambian_de_orden(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una exportación cuyas columnas cambian de orden entre dos descargas rompe
    cualquier hoja de cálculo que la consuma."""
    from crmcore.datos.masivas import columnas_exportables

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    una = columnas_exportables(db, tenant_id, "cuenta", ["nombre"])
    otra = columnas_exportables(db, tenant_id, "cuenta", ["nombre"])
    assert una == otra
    assert una[0] == "nombre"


@pytest.mark.db
def test_la_importacion_recoge_los_campos_propios_del_fichero(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Ignorarlas dejaría fuera precisamente los campos que el cliente añadió
    porque le importaban, y el importador que «funciona» sería el que pierde la
    mitad del fichero."""
    from crmcore.datos.masivas import PlanImportacion, importar

    _publicar(db, tenant_id, "cuenta", CAMPOS)
    vistas: list[dict[str, Any]] = []

    plan = PlanImportacion(
        objeto="cuenta",
        validar=lambda fila: [],
        buscar_existente=lambda db_, fila: None,
        crear=lambda db_, fila: vistas.append(fila) or object(),
        actualizar=lambda db_, actual, fila: actual,
        tenant_id=tenant_id,
    )
    importar(
        db,
        [{"nombre": "Constructora", "obra": "Torre", "presupuesto": "1500"}],
        plan,
        simular=False,
    )
    assert vistas[0]["campos"] == {"obra": "Torre", "presupuesto": "1500"}
    assert "obra" not in vistas[0]
