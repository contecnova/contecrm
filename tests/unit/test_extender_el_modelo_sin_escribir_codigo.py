"""Auditoría del modelo de datos configurable y de lo que ve quien lo pinta.

Diez capacidades sin ninguna prueba que las nombre, de tres familias que cuentan
una sola cosa: **un consultor extiende el CRM sin escribir código, y cualquier
frontend pinta lo que salga sin saber nada del CRM**.

  · **objetos y campos propios** (CRM-00.04.01.01, .02): diecinueve tipos de
    campo, y cada uno con su conversión y sus restricciones. Un tipo que no
    valida es una columna de texto con nombre bonito;
  · **las validaciones declarativas** (CRM-00.04.01.06): de campo, de registro
    y de transición de estado. Las tres, porque cada una tapa lo que las otras
    dos dejan pasar;
  · **el describe** (CRM-00.04.01.08, CRM-00.02.03.06): campos, reglas, layouts
    y permisos en una llamada. Es lo que evita que cada frontend duplique las
    reglas — y las duplique mal, y se entere el cliente;
  · **el ensayo** (CRM-00.02.03.07): validar sin guardar, para que el formulario
    avise antes de mandar en vez de contestar un 422 que nadie sabe pintar;
  · **la previsualización del cambio de esquema** (CRM-00.04.03.09): quien añade
    un campo obligatorio a un objeto con ochenta mil registros no sabe que los
    ochenta mil se quedan sin rellenar, y no lo sabe hasta que alguien intenta
    guardar uno viejo;
  · **los paquetes entre entornos** (CRM-00.04.03.10): exportar de pruebas e
    instalar en producción, simulando primero y sin pisar lo que alguien ajustó;
  · y **la materialización** (CRM-00.04.03.11), que se decide con una medida y
    no con una intuición.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def objeto(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> Any:
    """Un objeto propio del tenant con un par de campos."""
    from services.metadata.modelos import CampoDefinido, ObjetoDefinido

    fila = ObjetoDefinido(
        tenant_id=tenant_id,
        nombre="proyecto_obra",
        etiqueta="Proyecto de obra",
        etiqueta_plural="Proyectos de obra",
        origen="propio",
    )
    db.add(fila)
    db.flush()
    db.add_all(
        [
            CampoDefinido(
                tenant_id=tenant_id,
                objeto_id=fila.id,
                nombre="referencia",
                etiqueta="Referencia",
                tipo="texto",
                obligatorio=True,
                restricciones={"max_longitud": 10},
            ),
            CampoDefinido(
                tenant_id=tenant_id,
                objeto_id=fila.id,
                nombre="presupuesto",
                etiqueta="Presupuesto",
                tipo="moneda",
                restricciones={"min": 0},
            ),
        ]
    )
    db.flush()
    return fila


def _campos(db: Any, objeto: Any) -> list[Any]:
    from sqlalchemy import select

    from services.metadata.modelos import CampoDefinido

    return list(
        db.execute(select(CampoDefinido).where(CampoDefinido.objeto_id == objeto.id))
        .scalars()
        .all()
    )


# ── CRM-00.04.01.01 · Objetos propios, ciudadanos de primera ──────────────


def test_un_objeto_propio_vive_en_la_misma_tabla_que_los_estandar_crm_00_04_01_01(
    db: Any, objeto: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Para un frontend headless no hay diferencia**, y esa uniformidad es lo
    que hace que un objeto propio sea ciudadano de primera y no un apaño. Si
    vivieran en dos sitios, la mitad de las pantallas tendría que saber de cuál
    de los dos viene cada cosa."""
    from services.metadata.api import _objeto
    from services.metadata.modelos import ObjetoDefinido

    assert _objeto(db, tenant_id, "proyecto_obra").id == objeto.id
    assert objeto.origen == "propio"
    # El estándar se guarda igual: lo que cambia es el origen, no la tabla.
    db.add(
        ObjetoDefinido(tenant_id=tenant_id, nombre="cuenta", etiqueta="Cuenta", origen="estandar")
    )
    db.flush()
    assert _objeto(db, tenant_id, "cuenta").__class__ is ObjetoDefinido


def test_el_nombre_de_api_de_un_objeto_es_unico_por_tenant_crm_00_04_01_01(
    db: Any, objeto: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Es lo que aparece en las URLs y en las integraciones de terceros.** Dos
    objetos con el mismo nombre de API en un tenant harían que `/proyecto_obra`
    apuntara a uno u otro según el orden de la consulta."""
    from sqlalchemy.exc import IntegrityError

    from services.metadata.modelos import ObjetoDefinido

    db.add(ObjetoDefinido(tenant_id=tenant_id, nombre="proyecto_obra", etiqueta="Otro"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ── CRM-00.04.01.02 · Los diecinueve tipos de campo ───────────────────────


def test_cada_tipo_declarado_tiene_quien_lo_valide_crm_00_04_01_02() -> None:
    """**Un tipo que no valida es una columna de texto con nombre bonito.** Lo
    que se mira aquí es que la lista de tipos que la API admite y la lista de
    validadores no se separen: declarar un tipo nuevo y olvidar su validador
    deja pasar cualquier cosa sin que falle nada.
    """
    from typing import get_args

    from services.metadata.esquemas import TIPOS_CAMPO
    from services.metadata.validacion import VALIDADORES

    tipos = set(get_args(TIPOS_CAMPO))
    assert len(tipos) >= 19, sorted(tipos)
    # Los que pasan tal cual son **una lista corta y con motivo**: estructuras
    # que el CRM no interpreta (json, fichero, cifrado) y los derivados
    # (fórmula, lookup), que los calcula o resuelve otro.
    sin_validador = tipos - set(VALIDADORES)
    assert sin_validador <= {"json", "fichero", "cifrado", "formula", "lookup"}, sorted(
        sin_validador
    )


@pytest.mark.parametrize(
    ("tipo", "bueno", "malo"),
    [
        ("numero", "12.5", "doce"),
        ("moneda", "1000", "mil euros"),
        ("booleano", "si", "quizas"),
        ("fecha", "2026-10-26", "26 de octubre"),
        ("email", "quien@ejemplo.com", "quien-arroba-ejemplo"),
        ("url", "https://ejemplo.com", "javascript:alert(1)"),
        ("lista_multiple", ["a"], "a"),
        ("geolocalizacion", {"lat": 41.4, "lon": 2.1}, {"lat": 999, "lon": 2.1}),
    ],
)
def test_el_tipo_convierte_y_rechaza_crm_00_04_01_02(tipo: str, bueno: Any, malo: Any) -> None:
    """Uno por familia de tipo. **Lo que importa no es que acepte lo bueno sino
    que rechace lo malo**: un validador que acepta todo pasa la prueba de lo
    bueno igual de bien."""
    from types import SimpleNamespace

    from services.metadata.validacion import _Invalido, validar_campo

    campo = SimpleNamespace(
        nombre="x",
        etiqueta="X",
        tipo=tipo,
        obligatorio=False,
        restricciones={"opciones": ["a", "b"]} if tipo == "lista_multiple" else {},
    )
    validar_campo(campo, bueno)
    with pytest.raises(_Invalido):
        validar_campo(campo, malo)


# ── CRM-00.04.01.06 · Validaciones declarativas, en los tres niveles ──────


def test_el_campo_obligatorio_y_sus_restricciones_crm_00_04_01_06(
    db: Any, objeto: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Nivel campo. Y el mensaje lleva la **etiqueta**, no el nombre de API:
    quien lo lee es una persona rellenando un formulario, y «custom_ref_01 es
    obligatorio» no le dice cuál de las casillas le falta."""
    from services.metadata.validacion import validar_registro

    _, errores = validar_registro(_campos(db, objeto), {})
    assert [e["campo"] for e in errores] == ["referencia"]
    assert "«Referencia»" in errores[0]["mensaje"], errores[0]["mensaje"]

    _, largos = validar_registro(_campos(db, objeto), {"referencia": "x" * 50})
    assert largos, "la restricción de longitud no se aplica"


def test_un_campo_que_no_existe_se_avisa_en_vez_de_ignorarse_crm_00_04_01_06(
    db: Any, objeto: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Un campo mal escrito que se ignora en silencio es un dato que el
    cliente cree haber guardado y no está.** Se entera meses después, cuando lo
    busca para algo."""
    from services.metadata.validacion import validar_registro

    _, errores = validar_registro(_campos(db, objeto), {"referencia": "R-1", "refrencia": "R-1"})
    assert [e["motivo"] for e in errores] == ["desconocido"]
    assert "refrencia" in errores[0]["mensaje"]


def test_la_regla_de_registro_cruza_dos_campos_crm_00_04_01_06(
    db: Any, objeto: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Nivel registro: lo que un campo por sí solo no puede saber. Las
    condiciones describen la situación **prohibida**, que es al revés de lo que
    uno espera y se hace así porque el mensaje se escribe junto a ella."""
    from services.metadata.modelos import ReglaValidacion
    from services.metadata.validacion import validar_registro

    regla = ReglaValidacion(
        tenant_id=tenant_id,
        objeto_id=objeto.id,
        nombre="presupuesto_sin_referencia",
        # El atributo se llama «atributo» en las cuatro familias que evalúan
        # condiciones —procesos, webhooks, automatizaciones y esto—, y una sin
        # él cuenta como NO cumplida en las cuatro.
        condiciones=[{"atributo": "presupuesto", "op": ">", "valor": 0}],
        combinacion="todas",
        mensaje="Un presupuesto por encima de cero exige referencia de obra",
        activa=True,
    )
    db.add(regla)
    db.flush()

    campos = _campos(db, objeto)
    _, incumple = validar_registro(
        campos, {"referencia": "R-1", "presupuesto": 100}, reglas=[regla]
    )
    assert any(e["motivo"].startswith("regla:") for e in incumple), incumple

    _, cumple = validar_registro(campos, {"referencia": "R-1", "presupuesto": 0}, reglas=[regla])
    assert not [e for e in cumple if e["motivo"].startswith("regla:")]


def test_el_tenant_restringe_transiciones_pero_no_las_inventa_crm_00_04_01_06(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Nivel transición, y **la asimetría que lo hace configurable sin hacerlo
    frágil**: quitar una transición que el código admite es seguro; añadir una
    que el código no conoce dejaría el registro en un limbo que nadie programó,
    porque hay un `if estado == …` en quince sitios.
    """
    from crmcore.datos import estados as est
    from crmcore.errors import Conflicto, ErrorValidacion
    from crmcore.runtime import settings as rt

    est.registrar_maquina(
        est.Maquina(
            objeto="proyecto_obra_pruebas",
            transiciones={
                "abierta": frozenset({"ganada", "perdida"}),
                "perdida": frozenset({"abierta"}),
            },
            inicial="abierta",
            finales=frozenset({"ganada"}),
            exigen_motivo=frozenset({"perdida"}),
        )
    )

    # Lo que el código admite, pasa — con su motivo, porque perder es de las
    # cosas que alguien pregunta meses después.
    est.comprobar("proyecto_obra_pruebas", desde="abierta", hasta="perdida", motivo="precio", db=db)
    with pytest.raises(ErrorValidacion) as sin_motivo:
        est.comprobar("proyecto_obra_pruebas", desde="abierta", hasta="perdida", db=db)
    assert sin_motivo.value.error_code == "estados.motivo_requerido"

    # Un estado que no existe se distingue de «no puedes ir ahí»: casi siempre
    # es una errata o una integración desactualizada.
    with pytest.raises(ErrorValidacion) as errata:
        est.comprobar("proyecto_obra_pruebas", desde="abierta", hasta="ganda", db=db)
    assert errata.value.error_code == "estados.estado_desconocido"

    # Y el tenant quita «de perdida se vuelve a abierta».
    rt.fijar(
        db,
        "transiciones_prohibidas",
        {"proyecto_obra_pruebas": {"perdida": ["abierta"]}},
        ambito="tenant",
        ambito_id=str(tenant_id),
    )
    db.flush()
    with pytest.raises(Conflicto) as quitada:
        est.comprobar("proyecto_obra_pruebas", desde="perdida", hasta="abierta", db=db)
    # **Dice que es configuración y no producto**: sin eso, quien administra el
    # tenant no sabe si cambiar un ajuste o pedir un cambio de producto.
    assert quitada.value.detalle["restringida_por_configuracion"] is True


# ── CRM-00.04.01.08 y CRM-00.02.03.06 · El describe ───────────────────────


@pytest.fixture
def principal(tenant_id: UUID) -> Any:
    """Quien pregunta: de este tenant y con permiso de lectura sobre todo."""
    from types import SimpleNamespace

    return SimpleNamespace(
        tenant_id=tenant_id,
        id=uuid4(),
        permisos={"proyecto_obra:read", "proyecto_obra:write"},
        tiene=lambda clave: clave in {"proyecto_obra:read", "proyecto_obra:write"},
    )


def test_el_describe_trae_todo_lo_que_hace_falta_para_pintar_crm_00_04_01_08(
    db: Any, objeto: Any, principal: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Campos, reglas, layouts y **los permisos de quien pregunta**, en una
    llamada. Es lo que permite a cualquier frontend renderizar formularios y
    listas sin saber nada del CRM ni duplicar las reglas — y duplicarlas es como
    acaban divergiendo del servidor, que se entera el cliente.
    """
    from services.metadata.api import describe

    salida = describe("proyecto_obra", db, principal, tipo="")
    assert salida.objeto.nombre == "proyecto_obra"
    assert {c.nombre for c in salida.campos} == {"referencia", "presupuesto"}

    # Lo que distingue un describe útil de una lista de columnas: viene el
    # TIPO, si es obligatorio y sus restricciones. Sin eso el formulario pinta
    # cajas de texto y deja que el servidor diga que no.
    referencia = next(c for c in salida.campos if c.nombre == "referencia")
    assert referencia.tipo == "texto"
    assert referencia.obligatorio is True
    assert referencia.restricciones.get("max_longitud") == 10
    # Y la etiqueta, que es lo que ve la persona.
    assert referencia.etiqueta == "Referencia"

    # Los permisos de quien pregunta, resueltos aquí: sin ellos cada frontend
    # tendría que deducir si enseña el botón de borrar, y lo deduciría distinto.
    assert salida.permisos == {"read": True, "write": True, "delete": False, "export": False}


def test_un_campo_desactivado_no_se_describe_crm_00_02_03_06(
    db: Any, objeto: Any, principal: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Si siguiera describiéndose, el formulario lo pintaría y alguien lo
    rellenaría. Desactivar un campo que sigue apareciendo no desactiva nada."""
    from services.metadata.api import describe

    campo = next(c for c in _campos(db, objeto) if c.nombre == "presupuesto")
    campo.activo = False
    db.flush()

    salida = describe("proyecto_obra", db, principal, tipo="")
    assert {c.nombre for c in salida.campos} == {"referencia"}


def test_el_describe_de_un_objeto_que_no_existe_lo_dice_crm_00_02_03_06(
    db: Any, principal: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Y no devuelve un objeto vacío, que un frontend pintaría como un
    formulario sin campos — indistinguible de uno que aún no se ha configurado.
    """
    from crmcore.errors import NoEncontrado

    from services.metadata.api import describe

    with pytest.raises(NoEncontrado) as fallo:
        describe("no_existe", db, principal, tipo="")
    assert fallo.value.error_code == "metadata.objeto_no_encontrado"


# ── CRM-00.02.03.07 · Validar sin guardar ─────────────────────────────────


def test_el_ensayo_usa_las_mismas_reglas_y_no_escribe_crm_00_02_03_07(
    db: Any, objeto: Any, principal: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Las mismas** reglas que al guardar, en la misma llamada de código: un
    frontend puede enseñar los errores antes de enviar sin reimplementarlas, que
    es justo como acaban divergiendo del servidor.

    Y no escribe nada: un «ensayo» que deja rastro no es un ensayo.
    """
    from sqlalchemy import func, select

    from services.metadata.api import validar
    from services.metadata.esquemas import ValidarRegistro
    from services.metadata.modelos import CampoDefinido

    antes = db.execute(select(func.count()).select_from(CampoDefinido.__table__)).scalar_one()

    mal = validar("proyecto_obra", ValidarRegistro(datos={}), db, principal)
    assert mal.valido is False
    assert [e["campo"] for e in mal.errores] == ["referencia"]

    bien = validar("proyecto_obra", ValidarRegistro(datos={"referencia": "R-1"}), db, principal)
    assert bien.valido is True
    # Devuelve los valores ya convertidos: el frontend ve lo mismo que se
    # guardaría, no una copia de lo que mandó.
    assert bien.valores["referencia"] == "R-1"

    db.flush()
    assert (
        db.execute(select(func.count()).select_from(CampoDefinido.__table__)).scalar_one() == antes
    )


def test_el_ensayo_puede_cortar_cuando_se_le_pide_crm_00_02_03_07(
    db: Any, objeto: Any, principal: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Informar y exigir son dos cosas, y las dos hacen falta.** Lo pide quien
    importa en bloque: una importación que recibe «válido: false» y sigue
    adelante mete el registro malo igual, y quien lo revisa después ya no sabe
    cuál era."""
    from crmcore.errors import ErrorValidacion

    from services.metadata.api import validar
    from services.metadata.esquemas import ValidarRegistro

    with pytest.raises(ErrorValidacion):
        validar("proyecto_obra", ValidarRegistro(datos={}, exigir=True), db, principal)


def test_en_parcial_no_se_exige_lo_que_no_viene_crm_00_02_03_07(
    db: Any, objeto: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """En una actualización parcial **el valor que falta es el que ya está
    guardado, no un hueco**. Exigirlo obligaría a cada PATCH a reenviar el
    registro entero, y entonces dos personas editando campos distintos se pisan
    la una a la otra."""
    from services.metadata.validacion import validar_registro

    _, errores = validar_registro(_campos(db, objeto), {"presupuesto": 10}, parcial=True)
    assert errores == [], errores


# ── CRM-00.04.03.09 · Qué pasaría al publicar ─────────────────────────────


def test_la_previsualizacion_dice_a_quien_rompe_crm_00_04_03_09(
    db: Any, objeto: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Quien añade un campo obligatorio a un objeto con ochenta mil registros
    no sabe que los ochenta mil se quedan sin rellenar** — y no lo sabe hasta
    que alguien intenta guardar uno viejo y no puede. Esto lo dice antes, que es
    la diferencia entre una decisión y una sorpresa.
    """
    from services.metadata import publicacion as pub

    primera = pub.previsualizar(db, tenant_id, "proyecto_obra")
    assert primera["version_actual"] == 0
    assert primera["version_al_publicar"] == 1
    assert set(primera["anadidos"]) == {"referencia", "presupuesto"}
    assert primera["hay_cambios"] is True


def test_un_cambio_de_tipo_se_avisa_porque_no_convierte_crm_00_04_03_09(
    db: Any, objeto: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Lo que se publicó y lo que hay ahora se comparan campo a campo. **Los
    valores ya guardados no se convierten**: un campo que pasa de texto a número
    deja de validar para todo lo que había, y eso no falla al publicar — falla
    la próxima vez que alguien guarda un registro viejo.
    """
    from crmcore.db.uow import UnidadDeTrabajo

    from services.metadata import publicacion as pub

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    pub.publicar(db, tenant_id, "proyecto_obra") if False else None
    pub.publicar(uow.db, tenant_id, "proyecto_obra")
    db.flush()

    campo = next(c for c in _campos(db, objeto) if c.nombre == "presupuesto")
    campo.tipo = "texto"
    db.flush()

    salida = pub.previsualizar(db, tenant_id, "proyecto_obra")
    assert "presupuesto" in salida["cambiados"], salida
    assert any("cambia de tipo" in a for a in salida["avisos"]), salida["avisos"]
    assert salida["seguro"] is False


def test_lo_que_no_se_puede_contar_se_dice_crm_00_04_03_09(
    db: Any, objeto: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**«No se ha podido contar» y «no afecta a nadie» son cosas distintas**, y
    la diferencia es justo la que importa antes de publicar. Un objeto propio no
    tiene tabla conocida en este servicio, así que el recuento se declara no
    fiable en vez de devolver un cero tranquilizador."""
    from services.metadata import publicacion as pub

    salida = pub.previsualizar(db, tenant_id, "proyecto_obra")
    assert salida["registros"] is None
    assert any("no se ha podido contar" in a.lower() for a in salida["avisos"]), salida["avisos"]


# ── CRM-00.04.03.10 · Paquetes entre entornos ─────────────────────────────


def test_el_paquete_lleva_configuracion_y_nunca_datos_crm_00_04_03_10(
    db: Any, objeto: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Un paquete que arrastrara registros convertiría una promoción a
    producción en una fuga**: los datos de pruebas suelen ser copias
    anonimizadas a medias de clientes reales."""
    from services.metadata import publicacion as pub

    paquete = pub.exportar_paquete(db, tenant_id, ["proyecto_obra"])
    assert paquete["formato"] == pub.FORMATO_PAQUETE
    assert [o["nombre"] for o in paquete["objetos"]] == ["proyecto_obra"]
    assert {c["nombre"] for c in paquete["objetos"][0]["campos"]} == {"referencia", "presupuesto"}
    # Ni una clave que huela a registros.
    assert not (set(paquete) & {"registros", "filas", "datos"}), sorted(paquete)


def test_instalar_simula_por_defecto_crm_00_04_03_10(
    db: Any, objeto: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Instalar de verdad tiene que pedirse.** Un paquete es un cambio de
    modelo de datos en producción, y el error más caro de quien lo maneja es
    pulsar el botón creyendo que todavía estaba mirando.
    """
    from sqlalchemy import select

    from services.metadata import publicacion as pub
    from services.metadata.modelos import ObjetoDefinido

    paquete = pub.exportar_paquete(db, tenant_id, ["proyecto_obra"])

    ensayo = pub.instalar_paquete(db, otro_tenant_id, paquete)
    db.flush()
    assert ensayo["simulado"] is True
    assert ensayo["objetos_nuevos"] == ["proyecto_obra"]
    suyos = (
        db.execute(select(ObjetoDefinido).where(ObjetoDefinido.tenant_id == otro_tenant_id))
        .scalars()
        .all()
    )
    assert suyos == [], "el ensayo ha escrito"

    de_verdad = pub.instalar_paquete(db, otro_tenant_id, paquete, simular=False)
    db.flush()
    assert de_verdad["simulado"] is False
    suyos = (
        db.execute(select(ObjetoDefinido).where(ObjetoDefinido.tenant_id == otro_tenant_id))
        .scalars()
        .all()
    )
    assert [o.nombre for o in suyos] == ["proyecto_obra"]
    # Instalar no publica: el cambio no llega a los demás servicios hasta que
    # alguien lo decide.
    assert "Publicar" in de_verdad["siguiente_paso"]


def test_lo_que_ya_existe_con_otro_tipo_no_se_pisa_crm_00_04_03_10(
    db: Any, objeto: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Sobrescribir la configuración que alguien ajustó en producción con la
    de un entorno de pruebas es la forma habitual de perder dos semanas de
    trabajo de un consultor.** Se informa y se deja fuera."""
    from services.metadata import publicacion as pub
    from services.metadata.modelos import CampoDefinido, ObjetoDefinido

    paquete = pub.exportar_paquete(db, tenant_id, ["proyecto_obra"])

    suyo = ObjetoDefinido(tenant_id=otro_tenant_id, nombre="proyecto_obra", etiqueta="El suyo")
    db.add(suyo)
    db.flush()
    db.add(
        CampoDefinido(
            tenant_id=otro_tenant_id,
            objeto_id=suyo.id,
            nombre="presupuesto",
            etiqueta="Presupuesto",
            tipo="texto",  # aquí es texto; en el paquete es moneda
        )
    )
    db.flush()

    salida = pub.instalar_paquete(db, otro_tenant_id, paquete, simular=False)
    db.flush()
    assert salida["conflictos"], salida
    choque = salida["conflictos"][0]
    assert choque["campo"] == "proyecto_obra.presupuesto"
    assert (choque["aqui"], choque["en_el_paquete"]) == ("texto", "moneda")

    # Y no lo ha tocado.
    suyo_campo = next(c for c in _campos(db, suyo) if c.nombre == "presupuesto")
    assert suyo_campo.tipo == "texto"


def test_un_paquete_de_otro_formato_no_se_instala_crm_00_04_03_10(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Instalar a ciegas un formato que no se entiende deja el esquema a medias,
    que es el estado del que nadie sabe salir."""
    from crmcore.errors import ErrorValidacion

    from services.metadata import publicacion as pub

    with pytest.raises(ErrorValidacion) as fallo:
        pub.instalar_paquete(db, tenant_id, {"formato": 99, "objetos": []})
    assert fallo.value.error_code == "metadata.paquete_no_soportado"


# ── CRM-00.04.03.11 · Materializar se decide con una medida ───────────────


def test_materializar_se_decide_con_una_medida_crm_00_04_03_11(
    db: Any, objeto: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Un `ALTER TABLE` en una tabla compartida por mil tenants los bloquea a
    todos**, así que el JSONB con índice de expresión es el camino normal y esto
    es la excepción. Sin un número, cada cliente que note su lista lenta pediría
    columna, y acabaríamos con el `ALTER TABLE` de siempre disfrazado de
    optimización.
    """
    from crmcore.metamodelo import UsoCampo

    from services.metadata import publicacion as pub

    db.add(
        UsoCampo(tenant_id=tenant_id, objeto="proyecto_obra", campo="referencia", escrituras=50_000)
    )
    db.add(
        UsoCampo(tenant_id=tenant_id, objeto="proyecto_obra", campo="presupuesto", escrituras=12)
    )
    db.flush()

    salida = pub.candidatos_a_materializar(db, tenant_id, "proyecto_obra")
    assert [c["campo"] for c in salida["candidatos"]] == ["referencia"]
    assert salida["umbral"] == 10_000
    # El umbral es un parámetro, no una constante escondida: una instalación
    # pequeña materializa antes que una grande.
    estrecho = pub.candidatos_a_materializar(db, tenant_id, "proyecto_obra", minimo_escrituras=10)
    assert {c["campo"] for c in estrecho["candidatos"]} == {"referencia", "presupuesto"}
    # Y el orden importa: primero el que más se escribe.
    assert [c["campo"] for c in estrecho["candidatos"]] == ["referencia", "presupuesto"]
