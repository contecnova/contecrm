"""Las siete secciones del portal, servidas (`CRM-04.03.02.01`).

Medido el 04-10-2026: el portal anunciaba **ocho** secciones y servía **una**.
El cliente pintaba siete botones que no llevaban a ninguna parte, que es
justamente lo contrario de para lo que existe `secciones_de` — cuyo comentario
decía «para que el portal no pinte botones que…».

El 05-10-2026 se sirven siete y la octava se retira del anuncio: `facturas` no
existe en el producto —no hay entidad, ni tabla, ni servicio que las guarde,
porque la facturación vive en el ERP del cliente— y anunciar una sección para la
que no hay datos es una promesa que no puede cumplir nadie.

Tres las sirve `service`; contratos y pedidos los sirve `sales` y los contactos
`party`, cada uno lo suyo. Lo que lo hace posible sin copiar tablas ajenas es
que la sesión del portal lleva sus secciones **firmadas** en el token.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoAutenticado

from services.service import portal as prt


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


class _Acceso:
    """Un acceso de portal sin pasar por la tabla: lo que leen estas funciones
    son cuatro campos, y montarlo entero mediría el alta, no esto."""

    def __init__(self, tenant_id: UUID, *, cuenta_id: UUID | None = None) -> None:
        self.tenant_id = tenant_id
        self.contacto_id = uuid4()
        self.cuenta_id = cuenta_id
        self.nivel = "admin"
        self.secciones: list[str] = []


# ── Conocimiento: la audiencia manda, y en el servidor ────────────────────


def _articulo(
    uow: UnidadDeTrabajo, *, audiencia: str, canales: list[str], estado: str = "publicado"
) -> Any:
    from services.service.conocimiento import Articulo

    fila = Articulo(
        tenant_id=uow.tenant_id,
        clave=f"art-{uuid4().hex[:8]}",
        audiencia=audiencia,
        canales=canales,
        estado=estado,
        version_publicada=1,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_un_articulo_interno_no_se_le_ensena_a_un_cliente(uow: UnidadDeTrabajo) -> None:
    """El que explica cómo escalar al fabricante, con el teléfono del comercial
    de zona. Filtrarlo en el front funciona hasta que alguien mira la respuesta
    de la API."""
    interno = _articulo(uow, audiencia="interno", canales=["portal"])
    publico = _articulo(uow, audiencia="publico", canales=["portal"])
    vistos = {a["id"] for a in prt.mi_conocimiento(uow.db, _Acceso(uow.tenant_id))}
    assert str(publico.id) in vistos
    assert str(interno.id) not in vistos


def test_un_articulo_de_partner_tampoco(uow: UnidadDeTrabajo) -> None:
    """«Partner» está por encima de «cliente» en la escala, y el portal del
    cliente no es el del partner."""
    de_partner = _articulo(uow, audiencia="partner", canales=["portal"])
    vistos = {a["id"] for a in prt.mi_conocimiento(uow.db, _Acceso(uow.tenant_id))}
    assert str(de_partner.id) not in vistos


def test_publicado_para_el_chatbot_no_es_publicado_para_el_portal(uow: UnidadDeTrabajo) -> None:
    """Tratarlos igual publica en el sitio equivocado sin que nadie lo decida."""
    solo_chatbot = _articulo(uow, audiencia="publico", canales=["chatbot"])
    vistos = {a["id"] for a in prt.mi_conocimiento(uow.db, _Acceso(uow.tenant_id))}
    assert str(solo_chatbot.id) not in vistos


def test_un_borrador_no_sale_aunque_sea_publico(uow: UnidadDeTrabajo) -> None:
    borrador = _articulo(uow, audiencia="publico", canales=["portal"], estado="borrador")
    vistos = {a["id"] for a in prt.mi_conocimiento(uow.db, _Acceso(uow.tenant_id))}
    assert str(borrador.id) not in vistos


# ── Comunidad: lo que está en moderación no se lee ────────────────────────


def _hilo(uow: UnidadDeTrabajo, *, estado: str, autor: UUID | None = None) -> Any:
    fila = prt.HiloComunidad(
        tenant_id=uow.tenant_id,
        titulo=f"hilo {uuid4().hex[:6]}",
        estado=estado,
        autor_contacto_id=autor,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_lo_que_esta_en_moderacion_no_sale_ni_siendo_tuyo(uow: UnidadDeTrabajo) -> None:
    """Un foro que enseña lo que todavía no ha pasado por moderación es un foro
    moderado a toro pasado: lo que escriba alguien se lee antes de que nadie lo
    mire."""
    acceso = _Acceso(uow.tenant_id)
    mio_sin_moderar = _hilo(uow, estado="moderacion", autor=acceso.contacto_id)
    abierto = _hilo(uow, estado="abierto")
    vistos = {h["id"] for h in prt.mis_hilos(uow.db, acceso)}
    assert str(abierto.id) in vistos
    assert str(mio_sin_moderar.id) not in vistos


# ── Activos: por empresa, nunca por contacto ──────────────────────────────


def test_los_activos_van_por_empresa(uow: UnidadDeTrabajo) -> None:
    """Un equipo instalado es de la empresa, no de quien abrió el caso: atarlo
    al contacto haría que al irse esa persona su sucesor no viera la máquina que
    tiene delante."""
    from services.service.activos import ActivoInstalado

    mia = uuid4()
    otra = uuid4()
    for cuenta, nombre in ((mia, "la mía"), (otra, "la de otro")):
        uow.db.add(ActivoInstalado(tenant_id=uow.tenant_id, cuenta_id=cuenta, nombre=nombre))
    uow.db.flush()
    salida = prt.mis_activos(uow.db, _Acceso(uow.tenant_id, cuenta_id=mia))
    assert [a["nombre"] for a in salida] == ["la mía"]


def test_sin_empresa_no_se_devuelve_una_lista_vacia_sino_que_se_dice(
    uow: UnidadDeTrabajo,
) -> None:
    """Una lista vacía se lee como «no tenéis nada instalado», y lo que pasa es
    que el acceso está mal dado."""
    with pytest.raises(ErrorValidacion) as fallo:
        prt.mis_activos(uow.db, _Acceso(uow.tenant_id, cuenta_id=None))
    assert fallo.value.error_code == "portal.acceso_sin_empresa"


# ── Las secciones viajan firmadas, para que todos puedan comprobarlas ─────


def test_el_token_del_portal_lleva_las_secciones() -> None:
    """El portal lo sirven varios servicios y ninguno puede leer la tabla de
    accesos, que es de `service`. Sin esto, la comprobación de sección sólo se
    hacía en el dueño del acceso y en los demás no se hacía."""
    import jwt
    from crmcore.config import get_settings
    from crmcore.http.portal_deps import emitir_token_portal

    token, _ = emitir_token_portal(
        acceso_id=uuid4(),
        tenant_id=uuid4(),
        nivel="admin",
        cuenta_id=uuid4(),
        secciones=["casos", "pedidos"],
    )
    s = get_settings()
    carga = jwt.decode(token, s.secret_key.get_secret_value(), algorithms=[s.jwt_algorithm])
    assert carga["secciones"] == ["casos", "pedidos"]
    assert "permisos" not in carga, "un token de portal con permisos sirve para el CRM entero"


def test_una_seccion_que_el_acceso_no_tiene_se_corta() -> None:
    from crmcore.http.portal_deps import SesionPortal

    sesion = SesionPortal(acceso_id=uuid4(), tenant_id=uuid4(), nivel="propio", secciones=["casos"])
    sesion.exigir_seccion("casos")  # no lanza
    with pytest.raises(NoAutenticado) as fallo:
        sesion.exigir_seccion("pedidos")
    assert fallo.value.error_code == "portal.seccion_no_incluida"


def test_las_facturas_ya_no_se_anuncian() -> None:
    """No hay entidad, ni tabla, ni servicio que las guarde: la facturación vive
    en el ERP del cliente. Anunciar una sección para la que no hay datos es una
    promesa que no puede cumplir nadie, y el cliente la descubre pulsando."""
    todas = {s for ss in prt.SECCIONES_POR_NIVEL.values() for s in ss}
    assert "facturas" not in todas
