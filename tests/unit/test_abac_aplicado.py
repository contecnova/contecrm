"""ABAC aplicado de verdad (CRM-00.05.02.05, .17 a .21, .06).

El motor existía entero y **no lo llamaba nadie**: las políticas vivían en una
lista de Python, las tres de ejemplo desactivadas, y el único sitio que las
evaluaba era el explicador de permisos. El sistema sabía explicar una decisión
que no tomaba. Estas pruebas defienden que eso no vuelva a pasar, y sobre todo
las tres cosas que si se rompen dejan el ABAC peor que no tenerlo:

  * **La ficha y el listado dicen lo mismo.** Un registro que la lista enseña y
    la ficha niega —o al revés— es el fallo clásico de estos sistemas.
  * **Ante la duda, se deniega.** Al contrario que la compartición, que ante la
    duda comparte: una política ABAC restringe, así que no aplicarla enseña lo
    que no se debe.
  * **Se puede probar antes de activar.** Una política mal escrita no da un
    error: corta el acceso a gente que estaba trabajando, en silencio.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz import politicas as pol
from crmcore.authz.decision import campos_ocultos, decidir, filtro
from crmcore.errors import ErrorValidacion, Prohibido


@pytest.fixture(autouse=True)
def _sin_cache() -> Any:
    pol.invalidar()
    yield
    pol.invalidar()


USUARIO = UUID("01a0c000-0000-7000-8000-000000000001")


@pytest.fixture
def como_usuario(tenant_id: UUID) -> Any:
    """Ejecuta con una identidad concreta en el contexto.

    Hace falta porque el ámbito de una política lee del principal actual
    (`usuario.id`, `usuario.business_unit_id`), que es lo que permite escribir
    `registro.owner_id = @usuario.id` — la regla que pide casi todo despliegue.
    """
    from crmcore.tenancy.context import con_contexto

    with con_contexto(tenant_id=tenant_id, user_id=USUARIO):
        yield USUARIO


def _cuenta(tenant_id: UUID, nombre: str, owner_id: UUID) -> Any:
    """Una cuenta mínima pero válida. `clave_canonica` es NOT NULL."""
    from services.party.modelos import Cuenta

    return Cuenta(
        tenant_id=tenant_id,
        nombre=nombre,
        clave_canonica=nombre.lower().replace(" ", ""),
        owner_id=owner_id,
    )


def _guardar(db: Any, tenant_id: UUID, **kwargs: Any) -> Any:
    base = {
        "nombre": "solo_propias",
        "objeto": "cuenta",
        "acciones": ["read"],
        "condiciones": [{"atributo": "registro.owner_id", "operador": "=", "valor": "@usuario.id"}],
        "activa": True,
    }
    return pol.guardar(db, tenant_id=tenant_id, **{**base, **kwargs})


# ── Guardar: la gramática se valida antes, no al decidir ──────────────────


@pytest.mark.db
def test_un_operador_que_no_existe_se_rechaza_al_guardar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Se evaluaría como denegar, así que un error de escritura se convertiría
    en un corte de acceso silencioso el día que alguien la activara."""
    with pytest.raises(ErrorValidacion) as e:
        _guardar(
            db,
            tenant_id,
            condiciones=[{"atributo": "registro.x", "operador": "parecido_a", "valor": 1}],
        )
    assert e.value.error_code == "politica.operador_desconocido"


@pytest.mark.db
def test_una_politica_de_campos_sin_campos_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    with pytest.raises(ErrorValidacion) as e:
        _guardar(db, tenant_id, alcance="campos", campos=[])
    assert e.value.error_code == "politica.campos_vacios"


@pytest.mark.db
def test_guardar_sube_la_version_y_deja_la_anterior(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin histórico, «¿por qué no veía esto el mes pasado?» no tiene respuesta:
    la tabla viva solo enseña el estado de hoy."""
    from sqlalchemy import func, select

    _guardar(db, tenant_id, descripcion="primera")
    fila = _guardar(db, tenant_id, descripcion="segunda")
    db.flush()

    assert fila.version == 2
    cuantas = db.execute(
        select(func.count())
        .select_from(pol.VersionPoliticaAbac)
        .where(pol.VersionPoliticaAbac.politica_id == fila.id)
    ).scalar_one()
    assert cuantas == 2


@pytest.mark.db
def test_guardar_emite_el_evento_de_replica(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La decisión se toma donde está el dato, así que la política tiene que
    llegar al esquema de todos los servicios."""
    from crmcore.bus.modelos import EventoSaliente
    from sqlalchemy import select

    _guardar(db, tenant_id)
    db.flush()

    tipos = list(db.execute(select(EventoSaliente.tipo)).scalars().all())
    assert pol.POLITICA_CAMBIADA in tipos


@pytest.mark.db
def test_replicar_dos_veces_deja_el_mismo_estado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La entrega es at-least-once."""
    import asyncio

    from sqlalchemy import func, select

    mensaje = {
        "data": {
            "tenant_id": str(tenant_id),
            "borrada": False,
            "politica": {
                "nombre": "replicada",
                "objeto": "cuenta",
                "acciones": ["read"],
                "condiciones": [],
                "alcance": "registro",
                "activa": True,
                "version": 3,
            },
        }
    }
    asyncio.run(pol.consumir_politica(mensaje))
    asyncio.run(pol.consumir_politica(mensaje))

    cuantas = db.execute(
        select(func.count())
        .select_from(pol.PoliticaAbac)
        .where(pol.PoliticaAbac.nombre == "replicada")
    ).scalar_one()
    assert cuantas == 1


# ── Decidir sobre un registro ─────────────────────────────────────────────


@pytest.mark.db
def test_sin_politicas_no_se_restringe_nada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El ABAC restringe; lo que autoriza de base es el permiso del rol."""
    assert decidir(
        db, objeto="cuenta", accion="read", registro={"owner_id": str(uuid4())}
    ).permitido


@pytest.mark.db
def test_una_politica_desactivada_no_decide(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Que se pueda escribir sin que aplique es lo que hace que alguien se
    atreva a escribirla."""
    _guardar(db, tenant_id, activa=False)
    db.flush()
    assert decidir(
        db, objeto="cuenta", accion="read", registro={"owner_id": str(uuid4())}
    ).permitido


@pytest.mark.db
def test_la_politica_deniega_y_dice_por_que(db: Any, tenant_id: UUID, como_usuario: UUID) -> None:
    _guardar(db, tenant_id)
    db.flush()

    decision = decidir(db, objeto="cuenta", accion="read", registro={"owner_id": str(uuid4())})
    assert decision.permitido is False
    # La explicación lleva la política y la condición: «no tienes permiso» a
    # secas es el ticket de soporte más caro de cualquier CRM.
    assert "solo_propias" in decision.explicacion()
    assert "owner_id" in decision.explicacion()


@pytest.mark.db
def test_exigir_corta_con_403_y_la_explicacion_dentro(
    db: Any, tenant_id: UUID, como_usuario: UUID
) -> None:
    from crmcore.authz.decision import exigir

    _guardar(db, tenant_id)
    db.flush()

    with pytest.raises(Prohibido) as e:
        exigir(db, objeto="cuenta", accion="read", registro={"owner_id": str(uuid4())})
    assert e.value.error_code == "abac.denegado"
    assert e.value.detalle["politica"] == "solo_propias"


# ── El listado y la ficha dicen lo mismo ──────────────────────────────────


@pytest.mark.db
def test_el_listado_filtra_lo_mismo_que_niega_la_ficha(
    db: Any, como_usuario: UUID, tenant_id: UUID
) -> None:
    """Es la promesa central. Un registro que la lista enseña y la ficha niega
    —o al revés— es el fallo clásico de estos sistemas, y sale de tener dos
    gramáticas para la misma regla."""
    from sqlalchemy import select

    from services.party.modelos import Cuenta

    mia = _cuenta(tenant_id, "Mía S.L.", como_usuario)
    ajena = _cuenta(tenant_id, "Ajena S.L.", uuid4())
    db.add_all([mia, ajena])
    db.flush()
    _guardar(db, tenant_id)
    db.flush()

    condicion = filtro(db, Cuenta, objeto="cuenta", tenant_id=tenant_id)
    assert condicion is not None
    vistos = {c.id for c in db.execute(select(Cuenta).where(condicion)).scalars().all()}

    # Lo que el listado enseña es exactamente lo que la ficha permite.
    assert mia.id in vistos
    assert ajena.id not in vistos
    assert decidir(db, objeto="cuenta", accion="read", registro=mia).permitido is True
    assert decidir(db, objeto="cuenta", accion="read", registro=ajena).permitido is False


@pytest.mark.db
def test_una_condicion_de_contexto_que_no_se_cumple_vacia_el_listado(
    db: Any, como_usuario: UUID, tenant_id: UUID
) -> None:
    """No se traduce a SQL y no hace falta: o son las cuatro de la tarde para
    toda la consulta, o no lo son para ninguna fila."""
    from sqlalchemy import select

    from services.party.modelos import Cuenta

    db.add(_cuenta(tenant_id, "Cualquiera S.L.", como_usuario))
    db.flush()
    _guardar(
        db,
        tenant_id,
        nombre="horario_imposible",
        condiciones=[{"atributo": "contexto.hora", "operador": ">", "valor": 99}],
    )
    db.flush()

    condicion = filtro(db, Cuenta, objeto="cuenta", tenant_id=tenant_id)
    assert condicion is not None
    assert db.execute(select(Cuenta).where(condicion)).scalars().all() == []


@pytest.mark.db
def test_una_condicion_sobre_una_columna_que_no_existe_no_enseña_nada(
    db: Any, como_usuario: UUID, tenant_id: UUID
) -> None:
    """Ante la duda se DENIEGA, al revés que en compartición.

    Dejarla pasar enseñaría filas que la política niega, y el síntoma sería que
    la ficha y el listado dicen cosas distintas del mismo registro.
    """
    from sqlalchemy import select

    from services.party.modelos import Cuenta

    db.add(_cuenta(tenant_id, "Cualquiera S.L.", como_usuario))
    db.flush()
    _guardar(
        db,
        tenant_id,
        nombre="campo_inventado",
        condiciones=[{"atributo": "registro.no_existe_esta_columna", "operador": "=", "valor": 1}],
    )
    db.flush()

    condicion = filtro(db, Cuenta, objeto="cuenta", tenant_id=tenant_id)
    assert condicion is not None
    assert db.execute(select(Cuenta).where(condicion)).scalars().all() == []


# ── Políticas por campo ───────────────────────────────────────────────────


@pytest.mark.db
def test_una_politica_de_campos_esconde_el_campo_y_no_el_registro(
    db: Any, como_usuario: UUID, tenant_id: UUID
) -> None:
    """Es distinto de la sensibilidad: aquella dice «este rol no ve nunca el
    NIF», y esto dice «el margen de las cuentas de otro no se ve»."""
    _guardar(
        db,
        tenant_id,
        nombre="margen_solo_del_dueño",
        alcance="campos",
        campos=["ingresos_anuales"],
    )
    db.flush()

    mio = campos_ocultos(db, objeto="cuenta", registro={"owner_id": str(como_usuario)})
    ajeno = campos_ocultos(db, objeto="cuenta", registro={"owner_id": str(uuid4())})

    assert mio == set()
    assert ajeno == {"ingresos_anuales"}


# ── Motor externo ─────────────────────────────────────────────────────────


def test_el_motor_externo_puede_restringir_pero_nunca_ampliar() -> None:
    """Si pudiera ampliar, bastaría apuntar la configuración a un servicio que
    diga «sí» a todo para saltarse las políticas del tenant."""
    from crmcore.authz.abac import Decision
    from crmcore.authz.motor_externo import combinar

    denegada = Decision(permitido=False, politica_decisiva="interna")
    permitida = Decision(permitido=True)

    # El externo dice sí y el interno no: manda el interno.
    assert combinar(denegada, Decision(permitido=True)).permitido is False
    # El externo dice no y el interno sí: manda el externo.
    assert (
        combinar(permitida, Decision(permitido=False, politica_decisiva="ext")).permitido is False
    )
    # Sin motor externo, no cambia nada.
    assert combinar(permitida, None).permitido is True


def test_sin_motor_externo_configurado_no_se_consulta() -> None:
    """Y que no conteste no puede abrir el acceso: quien llama sigue con el
    motor de dentro, que tiene la misma política replicada."""
    from crmcore.authz.motor_externo import configurado, consultar

    assert configurado() is False
    assert consultar(objeto="cuenta", accion="read", ambito={}) is None


def test_la_politica_se_publica_con_su_semantica_dentro() -> None:
    """Quien escriba el traductor a Rego o Cedar la necesita delante: una nota
    en un manual aparte es una nota que no se lee."""
    from crmcore.authz.abac import Condicion, Politica
    from crmcore.authz.motor_externo import publicar

    salida = publicar(
        [
            Politica(
                nombre="solo_propias",
                objeto="cuenta",
                acciones=frozenset({"read"}),
                condiciones=(Condicion("registro.owner_id", "=", "@usuario.id"),),
            )
        ],
        tenant="t1",
    )
    assert salida["semantica"]["efecto"] == "restringir"
    assert salida["semantica"]["operador_desconocido"] == "denegar"
    assert salida["politicas"][0]["condiciones"][0]["valor"] == "@usuario.id"


def test_un_identificador_en_texto_y_uno_en_uuid_son_el_mismo() -> None:
    """La regla más común del sistema —`registro.owner_id = @usuario.id`—
    comparaba una cadena con un UUID y **nunca** era cierta.

    El registro llega serializado y el usuario viene del principal. Sin igualar
    los tipos, esa política habría denegado siempre, en silencio y sin error:
    el peor modo de fallo posible en permisos.
    """
    from crmcore.authz.abac import Condicion

    usuario = uuid4()
    condicion = Condicion("registro.owner_id", "=", "@usuario.id")
    ambito = {"registro": {"owner_id": str(usuario)}, "usuario": {"id": usuario}}
    assert condicion.evaluar(ambito) is True

    # Y no se iguala lo que no toca: convertir todo a texto para comparar haría
    # que 5 > 10 fuera cierto, que es cambiar una regla por otra sin decirlo.
    numeros = Condicion("registro.n", ">", 10)
    assert numeros.evaluar({"registro": {"n": 5}}) is False
    assert numeros.evaluar({"registro": {"n": 50}}) is True


@pytest.mark.db
def test_el_explicador_mira_las_politicas_guardadas_y_no_una_lista_de_ejemplo(
    db: Any, como_usuario: UUID, tenant_id: UUID
) -> None:
    """Mientras miraba la lista de ejemplo —con las tres desactivadas—
    contestaba siempre «permitido por ABAC», que es peor que no contestar."""
    from crmcore.authz.politicas import cargar

    assert cargar(db, tenant_id) == []
    _guardar(db, tenant_id)
    db.flush()
    cargadas = cargar(db, tenant_id)
    assert [p.nombre for p in cargadas] == ["solo_propias"]


# ── Ocultos frente a bloqueados (CRM-00.05.02.09) ─────────────────────────


@pytest.mark.db
def test_un_registro_bloqueado_se_ve_existir_sin_detalle(
    db: Any, como_usuario: UUID, tenant_id: UUID
) -> None:
    """Esconder del todo hace que los recuentos mientan: la ficha dice «5
    oportunidades», el listado enseña 3, y quien lo ve concluye que el sistema
    ha perdido dos. Bloqueado, el recuento cuadra."""
    from crmcore.authz.decision import bloqueados
    from sqlalchemy import select

    from services.party.modelos import Cuenta

    mia = _cuenta(tenant_id, "Mía S.L.", como_usuario)
    ajena = _cuenta(tenant_id, "Ajena S.L.", uuid4())
    db.add_all([mia, ajena])
    db.flush()
    _guardar(
        db,
        tenant_id,
        nombre="solo_las_mias_con_marca",
        alcance="bloqueado",
        campos=["id", "nombre"],
    )
    db.flush()

    condicion, visibles = bloqueados(db, Cuenta, objeto="cuenta", tenant_id=tenant_id)
    assert visibles == ("id", "nombre")

    marcadas = {c.id for c in db.execute(select(Cuenta).where(condicion)).scalars().all()}
    # Lo bloqueado es lo que NO cumple la política. Sin negar la condición se
    # bloquearía justo lo que se puede ver, y el listado seguiría teniendo el
    # mismo número de filas — que es lo que lo hace difícil de notar.
    assert marcadas == {ajena.id}


@pytest.mark.db
def test_una_politica_de_bloqueo_sin_campos_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un registro bloqueado del que no se ve nada es un registro escondido con
    otro nombre."""
    with pytest.raises(ErrorValidacion) as e:
        _guardar(db, tenant_id, nombre="bloqueo_mudo", alcance="bloqueado", campos=[])
    assert e.value.error_code == "politica.bloqueo_sin_campos"


# ── Dimensiones de restricción (CRM-00.05.02.08) ──────────────────────────


def test_las_dimensiones_comparan_el_atributo_que_toca() -> None:
    """Escritas a mano, la mitad acaba comparando el campo equivocado y el
    resultado es una política que restringe de más o de menos sin que nadie
    sepa cuál."""
    from crmcore.authz.politicas import politica_por_dimension

    politica = politica_por_dimension("unidad_de_negocio", objeto="cuenta")
    condicion = politica["condiciones"][0]
    assert condicion["atributo"] == "registro.business_unit_id"
    assert condicion["valor"] == "@usuario.business_unit_id"


def test_una_dimension_que_no_existe_se_rechaza() -> None:
    from crmcore.authz.politicas import politica_por_dimension

    with pytest.raises(ErrorValidacion) as e:
        politica_por_dimension("color_favorito", objeto="cuenta")
    assert e.value.error_code == "politica.dimension_desconocida"


@pytest.mark.db
def test_un_registro_sin_el_atributo_no_lo_ve_nadie(
    db: Any, como_usuario: UUID, tenant_id: UUID
) -> None:
    """En una restricción, el dato que falta no puede abrir la puerta."""
    from crmcore.authz.politicas import guardar, politica_por_dimension
    from sqlalchemy import select

    from services.party.modelos import Cuenta

    sin_unidad = _cuenta(tenant_id, "Sin unidad S.L.", como_usuario)
    db.add(sin_unidad)
    db.flush()
    plantilla = politica_por_dimension("unidad_de_negocio", objeto="cuenta")
    guardar(db, tenant_id=tenant_id, activa=True, **plantilla)
    db.flush()

    condicion = filtro(db, Cuenta, objeto="cuenta", tenant_id=tenant_id)
    assert db.execute(select(Cuenta).where(condicion)).scalars().all() == []
