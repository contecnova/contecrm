"""Comentarios, hilos y menciones sobre registros (CRM-06.02.01.01).

Lo que se defiende aquí: **la conversación no se pierde y no miente**. Un
comentario retirado deja rastro de que existió, un editado se ve como editado, y
las menciones se derivan del texto para que editarlo cambie también a quién se
avisa.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.datos import comentarios as com
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido


def _mencion(usuario: UUID, nombre: str = "Ana") -> str:
    return f"@[{nombre}]({usuario})"


# ── Menciones ─────────────────────────────────────────────────────────────


def test_las_menciones_salen_del_texto_no_de_una_lista_aparte(db: Any, tenant_id: UUID) -> None:
    """Con dos fuentes de verdad, editar el texto quitando una mención seguiría
    notificando a quien ya no aparece."""
    ana, luis = uuid4(), uuid4()
    c = com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        cuerpo=f"Hablado con {_mencion(ana)} y {_mencion(luis, 'Luis')}",
    )
    assert c.menciones == [str(ana).lower(), str(luis).lower()]


def test_editar_el_texto_cambia_las_menciones(db: Any, tenant_id: UUID) -> None:
    ana, luis = uuid4(), uuid4()
    autor = uuid4()
    c = com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        cuerpo=_mencion(ana),
        autor_id=autor,
    )
    com.editar(db, c.id, cuerpo=_mencion(luis, "Luis"), por=autor)

    assert c.menciones == [str(luis).lower()]


def test_mencionar_dos_veces_a_la_misma_persona_es_un_solo_aviso(db: Any, tenant_id: UUID) -> None:
    ana = uuid4()
    c = com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        cuerpo=f"{_mencion(ana)} ... {_mencion(ana)}",
    )
    assert c.menciones == [str(ana).lower()]


def test_un_identificador_pegado_en_el_texto_no_es_una_mencion(db: Any, tenant_id: UUID) -> None:
    """Buscar el identificador dentro del cuerpo encontraría también el
    comentario donde alguien lo pegó como referencia."""
    alguien = uuid4()
    c = com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        cuerpo=f"El usuario problemático es {alguien}, mírale la sesión",
    )
    assert c.menciones == []


def test_demasiadas_menciones_se_rechazan(db: Any, tenant_id: UUID) -> None:
    """Sin tope, un solo comentario genera un aviso para toda la empresa — y
    quien lo recibe deja de leer los avisos para siempre."""
    from crmcore.runtime import settings as rt

    tope = int(rt.efectivo("comentario_max_menciones") or 20)
    cuerpo = " ".join(_mencion(uuid4(), f"P{i}") for i in range(tope + 1))
    with pytest.raises(ErrorValidacion) as exc:
        com.crear(db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=uuid4(), cuerpo=cuerpo)
    assert exc.value.error_code == "comentario.demasiadas_menciones"


def test_donde_me_mencionan_devuelve_solo_lo_mio(db: Any, tenant_id: UUID) -> None:
    ana, luis = uuid4(), uuid4()
    objeto = uuid4()
    com.crear(db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=objeto, cuerpo=_mencion(ana))
    com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=objeto,
        cuerpo=_mencion(luis, "Luis"),
    )
    db.flush()

    mios = com.donde_me_mencionan(db, tenant_id=tenant_id, usuario_id=ana)
    assert len(mios) == 1
    assert mios[0]["objeto_id"] == str(objeto)


# ── Hilos ─────────────────────────────────────────────────────────────────


def test_el_primer_comentario_es_la_raiz_de_su_hilo(db: Any, tenant_id: UUID) -> None:
    c = com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        cuerpo="¿Aprobamos el descuento?",
    )
    assert c.hilo_id == c.id


def test_las_respuestas_heredan_el_hilo(db: Any, tenant_id: UUID) -> None:
    objeto = uuid4()
    raiz = com.crear(
        db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=objeto, cuerpo="¿Aprobamos?"
    )
    r1 = com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=objeto,
        cuerpo="Sí",
        padre_id=raiz.id,
    )
    r2 = com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=objeto,
        cuerpo="Con condiciones",
        padre_id=r1.id,
    )

    assert r1.hilo_id == r2.hilo_id == raiz.id


def test_no_se_puede_responder_a_un_comentario_de_otro_registro(db: Any, tenant_id: UUID) -> None:
    """Partiría el hilo en dos fichas y dejaría media conversación invisible
    desde cada una."""
    raiz = com.crear(
        db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=uuid4(), cuerpo="Aquí"
    )
    with pytest.raises(Conflicto) as exc:
        com.crear(
            db,
            tenant_id=tenant_id,
            objeto_tipo="cuenta",
            objeto_id=uuid4(),
            cuerpo="Allí",
            padre_id=raiz.id,
        )
    assert exc.value.error_code == "comentario.padre_de_otro_objeto"


def test_la_conversacion_se_agrupa_por_hilos(db: Any, tenant_id: UUID) -> None:
    """Leída como lista plana no se entiende en cuanto hay dos temas a la vez."""
    objeto = uuid4()
    a = com.crear(db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=objeto, cuerpo="Tema A")
    com.crear(db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=objeto, cuerpo="Tema B")
    com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=objeto,
        cuerpo="Sobre A",
        padre_id=a.id,
    )
    db.flush()

    hilos = com.de_registro(db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=objeto)
    assert len(hilos) == 2
    assert sorted(len(h["mensajes"]) for h in hilos) == [1, 2]


def test_un_hilo_se_puede_dar_por_resuelto(db: Any, tenant_id: UUID) -> None:
    objeto = uuid4()
    raiz = com.crear(
        db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=objeto, cuerpo="¿Plazo?"
    )
    com.resolver(db, raiz.id, por=uuid4())
    db.flush()

    hilos = com.de_registro(db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=objeto)
    assert hilos[0]["resuelto"]
    assert (
        com.de_registro(
            db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=objeto, solo_sin_resolver=True
        )
        == []
    )


def test_resolver_algo_que_no_es_raiz_de_hilo_falla(db: Any, tenant_id: UUID) -> None:
    objeto = uuid4()
    raiz = com.crear(db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=objeto, cuerpo="A")
    respuesta = com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=objeto,
        cuerpo="B",
        padre_id=raiz.id,
    )
    with pytest.raises(NoEncontrado):
        com.resolver(db, respuesta.id)


# ── Edición y borrado ─────────────────────────────────────────────────────


def test_solo_el_autor_edita_su_comentario(db: Any, tenant_id: UUID) -> None:
    autor = uuid4()
    c = com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        cuerpo="Mío",
        autor_id=autor,
    )
    with pytest.raises(Prohibido):
        com.editar(db, c.id, cuerpo="Tuyo", por=uuid4())


def test_editar_deja_marca(db: Any, tenant_id: UUID) -> None:
    """Alguien contestó a lo que ponía antes; sin la marca, esa respuesta parece
    no venir a cuento."""
    autor = uuid4()
    c = com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        cuerpo="Primera",
        autor_id=autor,
    )
    com.editar(db, c.id, cuerpo="Segunda", por=autor)
    assert c.ediciones == 1 and c.editado_at is not None


def test_un_comentario_retirado_deja_rastro_pero_no_su_texto(db: Any, tenant_id: UUID) -> None:
    """Marcarlo y seguir mandando el texto sería un borrado de mentira:
    cualquiera que mire la respuesta de la API lo lee igual."""
    objeto = uuid4()
    c = com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=objeto,
        cuerpo="Algo de lo que alguien se arrepintió",
    )
    com.borrar(db, c.id, por=uuid4())
    db.flush()

    mensajes = com.de_registro(db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=objeto)[0][
        "mensajes"
    ]
    assert mensajes[0]["borrado"] is True
    assert mensajes[0]["cuerpo"] == ""
    assert mensajes[0]["cuando"]


def test_un_comentario_borrado_no_se_puede_volver_a_borrar_ni_editar(
    db: Any, tenant_id: UUID
) -> None:
    c = com.crear(db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=uuid4(), cuerpo="x")
    com.borrar(db, c.id)
    with pytest.raises(NoEncontrado):
        com.editar(db, c.id, cuerpo="y")


def test_un_comentario_vacio_se_rechaza(db: Any, tenant_id: UUID) -> None:
    with pytest.raises(ErrorValidacion):
        com.crear(db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=uuid4(), cuerpo="   ")


def test_los_internos_se_pueden_excluir_para_un_portal(db: Any, tenant_id: UUID) -> None:
    """La decisión de qué ve un externo no puede depender de que cada sitio se
    acuerde de filtrar."""
    objeto = uuid4()
    com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=objeto,
        cuerpo="No cobrar el extra, que ya se quejó",
        interno=True,
    )
    com.crear(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=objeto,
        cuerpo="Le confirmamos el plazo",
        interno=False,
    )
    db.flush()

    externos = com.de_registro(
        db, tenant_id=tenant_id, objeto_tipo="cuenta", objeto_id=objeto, incluir_internos=False
    )
    textos = [m["cuerpo"] for h in externos for m in h["mensajes"]]
    assert textos == ["Le confirmamos el plazo"]


# ── Avisos de mención ─────────────────────────────────────────────────────


def test_una_mencion_a_alguien_de_baja_no_genera_aviso(db: Any, tenant_id: UUID) -> None:
    """Sería un aviso que nadie va a leer, y quien lo escribió se quedaría
    esperando una respuesta que no llega. El motivo del descarte se registra:
    «¿por qué no le llegó?» es la pregunta que viene detrás."""
    from services.identity.modelos import Membresia, Usuario
    from services.identity.notificaciones import _activos

    activo = Usuario(email="viva@ejemplo.com", nombre="Viva", activo=True)
    baja = Usuario(email="baja@ejemplo.com", nombre="Baja", activo=False)
    db.add_all([activo, baja])
    db.flush()
    for u in (activo, baja):
        db.add(Membresia(tenant_id=tenant_id, usuario_id=u.id, activa=True))
    db.flush()

    assert _activos(db, [activo.id, baja.id], tenant_id) == [activo.id]


def test_el_orden_de_las_menciones_se_conserva(db: Any, tenant_id: UUID) -> None:
    """La lista se enseña; reordenarla haría que el mismo comentario se viera
    distinto en cada carga."""
    from services.identity.modelos import Membresia, Usuario
    from services.identity.notificaciones import _activos

    usuarios = []
    for i in range(3):
        u = Usuario(email=f"u{i}@ejemplo.com", nombre=f"U{i}", activo=True)
        db.add(u)
        usuarios.append(u)
    db.flush()
    for u in usuarios:
        db.add(Membresia(tenant_id=tenant_id, usuario_id=u.id, activa=True))
    db.flush()

    pedido = [usuarios[2].id, usuarios[0].id, usuarios[1].id]
    assert _activos(db, pedido, tenant_id) == pedido
