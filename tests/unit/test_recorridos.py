"""Recorridos, plantillas y preferencias (CRM-02.02.02, CRM-02.03.01).

Un recorrido es un proceso que recorren miles de personas a la vez, cada una por
su sitio. Lo que decide si sirve o se convierte en una queja es **salir a
tiempo**: las pruebas van detrás de eso y de los otros cuatro sitios donde el
marketing automatizado se rompe en silencio.

  * la oferta de bienvenida a quien ya compró,
  * los tres recorridos a la vez sobre la misma persona,
  * la prueba A/B decidida con treinta personas,
  * el correo sin bloque de baja,
  * y el botón que da de baja de todo, incluidas las facturas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado

from services.marketing import correo as cor
from services.marketing import recorridos as rec


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


NODOS = {
    "bienvenida": {"tipo": "accion", "accion": "email", "siguiente": "esperar"},
    "esperar": {"tipo": "espera", "dias": 3, "siguiente": "fin"},
    "fin": {"tipo": "fin"},
}


def _alcanzable(uow: UnidadDeTrabajo, email: str = "") -> UUID:
    """Un contacto con dirección: sin perfil no se le puede escribir, y eso es
    correcto — pero entonces la prueba mediría otra cosa."""
    from services.marketing.modelos import PerfilMarketing

    quien = uuid4()
    uow.db.add(
        PerfilMarketing(
            tenant_id=uow.tenant_id,
            objeto="contacto",
            objeto_id=quien,
            email=email or f"{quien.hex[:8]}@cliente.com",
        )
    )
    uow.db.flush()
    return quien


def _recorrido(uow: UnidadDeTrabajo, **kw: Any) -> rec.Recorrido:
    base: dict[str, Any] = {
        "clave": "bienvenida",
        "nombre": "Bienvenida",
        "nodos": NODOS,
        "inicio": "bienvenida",
    }
    base.update(kw)
    fila, _ = rec.crear(uow, **base)
    return fila


def _publicado(uow: UnidadDeTrabajo, **kw: Any) -> rec.Recorrido:
    fila = _recorrido(uow, **kw)
    rec.publicar(uow, fila.id)
    return fila


# ── Validación del lienzo (CRM-02.02.02.01) ───────────────────────────────


def test_un_recorrido_sin_nodos_no_lleva_a_nadie() -> None:
    with pytest.raises(ErrorValidacion) as e:
        rec.validar({"nodos": {}, "inicio": "x"})
    assert e.value.error_code == "recorrido.sin_nodos"


def test_un_destino_que_no_existe_se_caza() -> None:
    """Descubrirlo en ejecución son diez mil personas paradas a mitad de camino."""
    with pytest.raises(ErrorValidacion) as e:
        rec.validar({"nodos": {"a": {"tipo": "accion", "siguiente": "fantasma"}}, "inicio": "a"})
    assert e.value.error_code == "recorrido.destino_no_existe"


def test_una_decision_por_comportamiento_sin_plazo_se_rechaza() -> None:
    """Nadie «no ha abierto» hasta que se decide cuándo se deja de esperar."""
    with pytest.raises(ErrorValidacion) as e:
        rec.validar(
            {
                "nodos": {
                    "d": {
                        "tipo": "decision",
                        "comportamiento": "abrio",
                        "rutas": {"si": "f", "no": "f"},
                    },
                    "f": {"tipo": "fin"},
                },
                "inicio": "d",
            }
        )
    assert e.value.error_code == "recorrido.decision_sin_plazo"


def test_los_pesos_de_una_prueba_tienen_que_sumar_cien() -> None:
    with pytest.raises(ErrorValidacion) as e:
        rec.validar(
            {
                "nodos": {
                    "p": {
                        "tipo": "prueba",
                        "variantes": [
                            {"clave": "a", "peso": 40, "siguiente": "f"},
                            {"clave": "b", "peso": 40, "siguiente": "f"},
                        ],
                    },
                    "f": {"tipo": "fin"},
                },
                "inicio": "p",
            }
        )
    assert e.value.error_code == "recorrido.pesos_no_suman"


def test_sin_salidas_declaradas_se_avisa() -> None:
    """Sin ellas, quien compre seguirá recibiendo la oferta de bienvenida hasta el
    último paso."""
    avisos = rec.validar({"nodos": NODOS, "inicio": "bienvenida"})
    assert any("salidas declaradas" in a for a in avisos)


def test_un_nodo_al_que_no_llega_nadie_avisa_pero_no_rompe() -> None:
    """Montando un lienzo es normal tener un trozo suelto a mitad; publicarlo con
    nodos muertos es otra cosa, y hay que verlo."""
    avisos = rec.validar(
        {
            "nodos": {**NODOS, "huerfano": {"tipo": "fin"}},
            "inicio": "bienvenida",
        }
    )
    assert any("no llega nadie" in a for a in avisos)


# ── Entrar (CRM-02.02.02.02) ──────────────────────────────────────────────


def test_no_se_entra_en_un_borrador(uow: UnidadDeTrabajo) -> None:
    """Entrar en un borrador es recibir un recorrido a medio montar."""
    fila = _recorrido(uow)
    with pytest.raises(Conflicto) as e:
        rec.entrar(uow, fila.id, objeto_id=uuid4())
    assert e.value.error_code == "recorrido.no_publicado"


def test_no_se_entra_dos_veces(uow: UnidadDeTrabajo) -> None:
    """Quien recorrió la bienvenida no la necesita otra vez."""
    fila = _publicado(uow)
    quien = _alcanzable(uow)
    assert rec.entrar(uow, fila.id, objeto_id=quien)["entro"] is True
    segunda = rec.entrar(uow, fila.id, objeto_id=quien)
    assert segunda["entro"] is False
    assert segunda["motivo"] in ("ya_estuvo", "ya_dentro")


def test_un_recorrido_excluyente_impide_entrar(uow: UnidadDeTrabajo) -> None:
    """Sin esto, quien pasa de captación a cliente recibe las dos cosas a la vez."""
    captacion = _publicado(uow, clave="captacion", nombre="Captación")
    cliente = _publicado(uow, clave="cliente", nombre="Cliente nuevo", excluye_si_en=["captacion"])
    quien = _alcanzable(uow)
    rec.entrar(uow, captacion.id, objeto_id=quien)
    salida = rec.entrar(uow, cliente.id, objeto_id=quien)
    assert salida["motivo"] == "en_recorrido_excluyente"


def test_un_suprimido_no_entra(uow: UnidadDeTrabajo) -> None:
    """Quien pidió no ser alcanzado no lo es, por mucho que el recorrido lo diga."""
    from services.marketing.segmentos import suprimir

    fila = _publicado(uow)
    quien = _alcanzable(uow, "baja@cliente.com")
    suprimir(uow, direccion="baja@cliente.com", motivo="baja", canal="email")
    assert rec.entrar(uow, fila.id, objeto_id=quien)["motivo"] == "suprimido"


def test_sin_direccion_no_se_dice_suprimido(uow: UnidadDeTrabajo) -> None:
    """Decir «suprimido» a quien no tiene correo manda a buscar una baja que no
    existe, cuando lo que falta es la dirección."""
    fila = _publicado(uow)
    assert rec.entrar(uow, fila.id, objeto_id=uuid4())["motivo"] == "sin_direccion"


def test_por_cuenta_solo_entra_uno(uow: UnidadDeTrabajo) -> None:
    """Cuatro personas de la misma empresa recibiendo la misma secuencia es cuatro
    veces el mismo mensaje en la misma reunión."""
    fila = _publicado(uow, por_cuenta=True)
    cuenta = uuid4()
    assert rec.entrar(uow, fila.id, objeto_id=_alcanzable(uow), cuenta_id=cuenta)["entro"] is True
    segunda = rec.entrar(uow, fila.id, objeto_id=_alcanzable(uow), cuenta_id=cuenta)
    assert segunda["motivo"] == "cuenta_ya_dentro"


# ── Salidas (CRM-02.02.02.07) ─────────────────────────────────────────────


def test_quien_compra_sale_en_el_paso_siguiente(uow: UnidadDeTrabajo) -> None:
    """Es la razón de que la salida se compruebe antes de cada paso y no solo al
    entrar: alguien que compra a mitad tiene que dejar de recibir la oferta de
    bienvenida ya, no al final."""
    fila = _publicado(
        uow,
        salidas=[
            {
                "motivo": "conversion",
                "condiciones": [{"atributo": "persona.compro", "operador": "=", "valor": True}],
            }
        ],
    )
    quien = _alcanzable(uow)
    rec.entrar(uow, fila.id, objeto_id=quien)
    rec.anotar_comportamiento(uow, objeto_id=quien, que="compro")
    salida = rec.avanzar(uow, uow.tenant_id)
    assert [s["motivo"] for s in salida["salidos"]] == ["conversion"]


def test_el_tope_de_dias_saca_a_quien_se_quedo_dentro(uow: UnidadDeTrabajo) -> None:
    """Un recorrido sin tope deja gente dentro años, recibiendo un paso que
    alguien añadió al final sin pensar en ellos."""
    fila = _publicado(uow, dias_maximos=10)
    quien = _alcanzable(uow)
    rec.entrar(uow, fila.id, objeto_id=quien)
    from sqlalchemy import select

    dentro = uow.db.execute(select(rec.EnRecorrido)).scalars().one()
    dentro.entro_at = datetime.now(timezone.utc) - timedelta(days=30)
    uow.db.flush()
    salida = rec.avanzar(uow, uow.tenant_id)
    assert [s["motivo"] for s in salida["salidos"]] == ["caducado"]


def test_no_se_sale_dos_veces(uow: UnidadDeTrabajo) -> None:
    fila = _publicado(uow)
    quien = _alcanzable(uow)
    entrada = rec.entrar(uow, fila.id, objeto_id=quien)
    rec.salir(uow, UUID(entrada["en_recorrido_id"]), motivo="manual")
    with pytest.raises(Conflicto):
        rec.salir(uow, UUID(entrada["en_recorrido_id"]), motivo="manual")


# ── Comportamiento (CRM-02.02.02.03) ──────────────────────────────────────


def test_un_clic_se_anota_en_todos_los_recorridos(uow: UnidadDeTrabajo) -> None:
    """El mismo clic resuelve la rama de los tres, y anotarlo en uno solo dejaría
    a los otros dos esperando un comportamiento que ya ocurrió."""
    uno = _publicado(uow, clave="a", nombre="A")
    otro = _publicado(uow, clave="b", nombre="B")
    quien = _alcanzable(uow)
    rec.entrar(uow, uno.id, objeto_id=quien)
    rec.entrar(uow, otro.id, objeto_id=quien)
    assert rec.anotar_comportamiento(uow, objeto_id=quien, que="clico")["anotado_en"] == 2


def test_un_comportamiento_inventado_se_rechaza(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion):
        rec.anotar_comportamiento(uow, objeto_id=uuid4(), que="bailo")


def test_responder_despierta_a_quien_estaba_esperando(uow: UnidadDeTrabajo) -> None:
    """Esperar al plazo cuando la respuesta ya está es hacer esperar cinco días a
    quien contestó en cinco minutos."""
    fila = _publicado(uow)
    quien = _alcanzable(uow)
    rec.entrar(uow, fila.id, objeto_id=quien)
    rec.avanzar(uow, uow.tenant_id)  # ejecuta la acción
    rec.avanzar(uow, uow.tenant_id)  # entra en la espera

    from sqlalchemy import select

    dentro = uow.db.execute(select(rec.EnRecorrido)).scalars().one()
    assert dentro.estado == "esperando"
    lejos = dentro.despertar_at
    rec.anotar_comportamiento(uow, objeto_id=quien, que="abrio")
    assert dentro.despertar_at < lejos


# ── Ejecutar y omitir (CRM-02.02.02.04) ───────────────────────────────────


def test_un_suprimido_a_mitad_no_para_el_recorrido(uow: UnidadDeTrabajo) -> None:
    """Pararlo dejaría a la persona atascada en un nodo para siempre, y volver a
    meterla después sería imposible sin tocar la base a mano."""
    from services.marketing.segmentos import suprimir

    fila = _publicado(uow)
    quien = _alcanzable(uow, "fuera@cliente.com")
    rec.entrar(uow, fila.id, objeto_id=quien)
    suprimir(uow, direccion="fuera@cliente.com", motivo="baja", canal="email")
    salida = rec.avanzar(uow, uow.tenant_id)
    assert [o["motivo"] for o in salida["omitidos"]] == ["suprimido"]
    assert salida["movidos"]


def test_la_variante_es_estable_para_la_misma_persona(uow: UnidadDeTrabajo) -> None:
    """Con `random`, reintentar un paso movería a alguien de la rama A a la B y su
    historial diría dos cosas distintas."""
    fila = rec.EnRecorrido(
        tenant_id=uow.tenant_id,
        recorrido_id=uuid4(),
        objeto_id=uuid4(),
        nodo_actual="p",
    )
    variantes = [
        {"clave": "a", "peso": 50, "siguiente": "f"},
        {"clave": "b", "peso": 50, "siguiente": "f"},
    ]
    primera = rec._variante(fila, "p", variantes)
    segunda = rec._variante(fila, "p", variantes)
    assert primera["clave"] == segunda["clave"]


def test_sin_pendientes_no_se_dice_que_todo_va_bien(uow: UnidadDeTrabajo) -> None:
    assert rec.avanzar(uow, uow.tenant_id)["medible"] is False


# ── Analítica (CRM-02.02.02.08) ───────────────────────────────────────────


def test_el_embudo_cuenta_gente_y_no_pasos(uow: UnidadDeTrabajo) -> None:
    """Un bucle haría que un nodo tuviera más pasos que personas y el embudo
    saldría al revés."""
    fila = _publicado(uow)
    for _ in range(3):
        rec.entrar(uow, fila.id, objeto_id=_alcanzable(uow))
    rec.avanzar(uow, uow.tenant_id)
    salida = rec.embudo(uow.db, uow.tenant_id, fila.id)
    primero = salida["nodos"][0]
    assert primero["nodo"] == "bienvenida"
    assert primero["personas"] == 3


def test_el_embudo_avisa_si_hay_ramas(uow: UnidadDeTrabajo) -> None:
    """Fingir que hay un solo camino daría un embudo que no describe a nadie."""
    fila = _publicado(
        uow,
        clave="con-ramas",
        nombre="Con ramas",
        nodos={
            "d": {
                "tipo": "decision",
                "comportamiento": "abrio",
                "espera_dias": 2,
                "rutas": {"si": "f", "no": "f2"},
            },
            "f": {"tipo": "fin"},
            "f2": {"tipo": "fin"},
        },
        inicio="d",
    )
    assert rec.embudo(uow.db, uow.tenant_id, fila.id)["tiene_ramas"] is True


def test_sin_nadie_dentro_el_embudo_no_es_medible(uow: UnidadDeTrabajo) -> None:
    fila = _publicado(uow)
    assert rec.embudo(uow.db, uow.tenant_id, fila.id)["medible"] is False


def test_con_pocos_datos_no_hay_ganadora(uow: UnidadDeTrabajo) -> None:
    """Con treinta personas por rama la diferencia que se ve es ruido, y elegir por
    ella consolida una variante peor con la confianza de haberla medido."""
    fila = _publicado(uow)
    salida = rec.resultado_prueba(uow.db, uow.tenant_id, fila.id, "p", minimo=100)
    assert salida["ganadora"] is None
    assert salida["concluyente"] is False
    assert "ruido" in salida["aviso"]


# ── Plantillas de correo (CRM-02.03.01.01) ────────────────────────────────


def _bloque(uow: UnidadDeTrabajo, clave: str, **kw: Any) -> cor.BloqueCorreo:
    base: dict[str, Any] = {"nombre": clave, "tipo": "texto", "contenido": {"html": "x"}}
    base.update(kw)
    fila = cor.BloqueCorreo(tenant_id=uow.tenant_id, clave=clave, **base)
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _plantilla(uow: UnidadDeTrabajo, **kw: Any) -> cor.PlantillaMarketing:
    base: dict[str, Any] = {
        "clave": "oferta",
        "nombre": "Oferta",
        "asunto": "Hola {{nombre}}",
        "clase": "promocional",
        "bloques": [{"bloque": "cuerpo"}],
        "categoria": "novedades",
    }
    base.update(kw)
    fila = cor.PlantillaMarketing(tenant_id=uow.tenant_id, **base)
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_el_bloque_obligatorio_se_anade_aunque_se_olvide(uow: UnidadDeTrabajo) -> None:
    """El de baja lo es por ley, y confiar en que quien monta la plantilla lo
    arrastre es cómo se manda una campaña sin él."""
    _bloque(uow, "cuerpo")
    _bloque(uow, "baja", tipo="pie", obligatorio_en_promocional=True)
    _plantilla(uow)
    salida = cor.componer(uow.db, uow.tenant_id, "oferta")
    assert salida["anadidos_por_obligacion"] == ["baja"]
    assert {b["clave"] for b in salida["bloques"]} == {"cuerpo", "baja"}


def test_un_bloque_que_falta_no_se_ignora(uow: UnidadDeTrabajo) -> None:
    """La plantilla saldría con un hueco y nadie sabría de dónde salió."""
    _plantilla(uow)
    salida = cor.componer(uow.db, uow.tenant_id, "oferta")
    assert salida["bloques_que_faltan"] == ["cuerpo"]
    assert salida["componible"] is False


def test_lo_transaccional_no_lleva_el_bloque_de_baja(uow: UnidadDeTrabajo) -> None:
    """Ofrecer darse de baja de una factura produce clientes que no reciben su
    factura."""
    _bloque(uow, "cuerpo")
    _bloque(uow, "baja", tipo="pie", obligatorio_en_promocional=True)
    _plantilla(uow, clave="factura", clase="transaccional", categoria=None)
    salida = cor.componer(uow.db, uow.tenant_id, "factura")
    assert salida["anadidos_por_obligacion"] == []


def test_los_tokens_sin_dato_se_dicen_antes_de_mandar(uow: UnidadDeTrabajo) -> None:
    """Un «Hola {{nombre}}» sin sustituir dice en voz alta que el correo es
    automático, y lo reciben todos a la vez."""
    _bloque(uow, "cuerpo")
    _plantilla(uow)
    composicion = cor.componer(uow.db, uow.tenant_id, "oferta")
    salida = cor.comprobar_tokens(composicion, {})
    assert salida["sin_datos"] == ["nombre"]
    assert salida["listo"] is False
    assert cor.comprobar_tokens(composicion, {"nombre": "Ana"})["listo"] is True


# ── Preferencias (CRM-02.03.01.05) ────────────────────────────────────────


def _categoria(uow: UnidadDeTrabajo, clave: str, **kw: Any) -> cor.CategoriaPreferencia:
    base: dict[str, Any] = {"nombre": clave, "obligatoria": False, "por_defecto": False}
    base.update(kw)
    fila = cor.CategoriaPreferencia(tenant_id=uow.tenant_id, clave=clave, **base)
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_darse_de_baja_no_es_todo_o_nada(uow: UnidadDeTrabajo) -> None:
    """Quien solo quiere dejar la newsletter y encuentra un botón que le saca de
    todo marca el correo como basura, y eso no se deshace."""
    _categoria(uow, "novedades", por_defecto=True)
    _categoria(uow, "facturas", obligatoria=True)
    cor.fijar_preferencias(uow, email="a@b.c", elecciones={"novedades": False})
    centro = cor.centro_de_preferencias(uow.db, uow.tenant_id, "a@b.c")
    por_clave = {c["clave"]: c for c in centro["categorias"]}
    assert por_clave["novedades"]["acepta"] is False
    assert por_clave["facturas"]["acepta"] is True


def test_una_categoria_obligatoria_no_se_apaga(uow: UnidadDeTrabajo) -> None:
    """Dejar creer que se apagó el aviso de facturación produce la queja de «sigo
    recibiendo lo que quité»."""
    _categoria(uow, "facturas", obligatoria=True)
    salida = cor.fijar_preferencias(uow, email="a@b.c", elecciones={"facturas": False})
    assert salida["obligatorias_ignoradas"] == ["facturas"]
    assert salida["guardadas"] == []


def test_la_obligatoria_se_marca_como_tal_y_no_como_casilla_apagada(
    uow: UnidadDeTrabajo,
) -> None:
    """Enseñar una casilla que no se puede desmarcar se lee como un engaño."""
    _categoria(uow, "facturas", obligatoria=True)
    centro = cor.centro_de_preferencias(uow.db, uow.tenant_id, "a@b.c")
    assert centro["categorias"][0]["obligatoria"] is True


def test_una_plantilla_sin_categoria_no_se_manda(uow: UnidadDeTrabajo) -> None:
    """Una promocional sin categoría no se puede rechazar por categorías, así que
    darle paso equivaldría a un canal que nadie puede apagar."""
    salida = cor.puede_recibir(uow.db, uow.tenant_id, "a@b.c", None)
    assert salida["permitido"] is False
    assert "darse de baja" in salida["motivo"]


def test_sin_eleccion_manda_el_valor_por_defecto(uow: UnidadDeTrabajo) -> None:
    _categoria(uow, "novedades", por_defecto=False)
    assert cor.puede_recibir(uow.db, uow.tenant_id, "a@b.c", "novedades")["permitido"] is False


def test_la_comprobacion_previa_junta_todo(uow: UnidadDeTrabajo) -> None:
    """La que se olvida es siempre la misma —las preferencias— y el resultado es un
    correo a quien se dio de baja."""
    _bloque(uow, "cuerpo")
    _plantilla(uow)
    _categoria(uow, "novedades", por_defecto=True)
    cor.fijar_preferencias(uow, email="a@b.c", elecciones={"novedades": False})
    salida = cor.comprobar_envio(uow.db, uow.tenant_id, email="a@b.c", plantilla_clave="oferta")
    assert salida["se_puede_mandar"] is False
    assert any("baja" in m for m in salida["motivos"])


# ── Separación de dominios (CRM-02.03.01.07) ──────────────────────────────


def test_sin_dominios_separados_se_avisa() -> None:
    """El día que la entrega se hunda, nadie sabrá por qué."""
    salida = cor.remitente_para("promocional", config={})
    assert salida["separados"] is False
    assert "reputación" in salida["aviso"]


def test_con_dominios_separados_no_hay_aviso() -> None:
    salida = cor.remitente_para(
        "transaccional",
        config={
            "dominio_promocional": "news.acme.com",
            "dominio_transaccional": "avisos.acme.com",
        },
    )
    assert salida["separados"] is True
    assert salida["dominio"] == "avisos.acme.com"
    assert salida["aviso"] == ""


def test_una_clase_inventada_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion):
        cor.remitente_para("spam")


def test_un_recorrido_que_no_existe_da_404(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(NoEncontrado):
        rec.embudo(uow.db, uow.tenant_id, uuid4())
