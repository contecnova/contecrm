"""Un aviso por push no enseña el dato en la pantalla de bloqueo
(`CRM-02.03.02.03`).

Auditado el 05-10-2026. La capacidad constaba `hecho` y el canal `push` estaba
declarado, con su consentimiento y su forma de darse de baja. Lo que **no**
ocurría es lo que `movil.preparar_push` decidía: esa función estaba escrita,
probada y sin que la llamara nadie, así que el aviso salía por push con el
cuerpo entero y con sus `datos` — el nombre del cliente y el importe, en una
pantalla que ve cualquiera que coja el teléfono y que pasa por los servidores
de un tercero por el camino.

Lo que va es **qué ha pasado y dónde mirarlo**. El dato lo enseña la aplicación
después de identificar a quien la abre.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from crmcore.errors import ErrorValidacion

from services.identity.reparto import _mensaje


def _aviso(**kw):
    base = dict(
        id=uuid4(),
        tipo="caso.asignado",
        titulo="Ana Pérez · factura de 12.400 €",
        cuerpo="La cuenta Ana Pérez tiene una factura vencida de 12.400 €",
        prioridad="alta",
        objeto_tipo="caso",
        objeto_id=uuid4(),
        datos={"cliente": "Ana Pérez", "importe": "12400"},
        plantilla=None,
        idioma="es",
        agrupadas=1,
        tenant_id=uuid4(),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_por_push_no_viaja_ni_el_cuerpo_ni_los_datos(db) -> None:
    mensaje = _mensaje(db, _aviso(), canal="push")
    assert mensaje.cuerpo == "", "el cuerpo del aviso sale en la pantalla de bloqueo"
    assert "cliente" not in mensaje.datos
    assert "importe" not in mensaje.datos
    # Lo que sí lleva: dónde mirarlo.
    assert mensaje.datos.get("objeto") == "caso"
    assert mensaje.datos.get("objeto_id")


def test_el_titulo_del_push_se_corta_a_sesenta() -> None:
    """Más llega truncado a media palabra, que se lee peor que un resumen."""
    from crmcore.movil import preparar_push

    with pytest.raises(ErrorValidacion) as fallo:
        preparar_push(tipo="x", objeto="caso", objeto_id=uuid4(), titulo_corto="a" * 61)
    assert fallo.value.error_code == "movil.push_largo"


def test_por_los_demas_canales_el_aviso_sigue_llevando_lo_suyo(db) -> None:
    """La protección es del push y no de todo: vaciar el cuerpo en correo
    dejaría avisos en blanco, que es el fallo contrario."""
    mensaje = _mensaje(db, _aviso(), canal="correo")
    assert "12.400" in mensaje.cuerpo
    assert mensaje.datos.get("cliente") == "Ana Pérez"
