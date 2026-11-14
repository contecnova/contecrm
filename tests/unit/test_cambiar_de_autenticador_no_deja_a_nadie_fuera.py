"""Cambiar de autenticador no toca el activo hasta confirmar el nuevo (SEC-20).

`/mfa/iniciar` escribía el secreto y los códigos de recuperación nuevos encima
de los activos: si el escaneo salía mal, la cuenta se quedaba con un secreto
sin confirmar y sin sus códigos de recuperación de siempre.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.authz.principal import Principal
from crmcore.errors import NoAutenticado


def _usuario_con_mfa(db: Any) -> Any:
    from services.identity import servicio as svc
    from services.identity.modelos import Usuario

    usuario = Usuario(
        email="mfa@empresa.example",
        nombre="M",
        activo=True,
        mfa_activo=True,
        mfa_secreto=svc.generar_secreto_totp(),
        mfa_recuperacion=["hash-viejo"],
    )
    db.add(usuario)
    db.flush()
    return usuario


def test_iniciar_no_toca_el_activo_y_activar_lo_cambia(
    db: Any, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.identity import api
    from services.identity import servicio as svc

    usuario = _usuario_con_mfa(db)
    viejo = usuario.mfa_secreto
    # La reverificación de SEC-4 tiene sus propias pruebas; aquí se da por hecha.
    monkeypatch.setattr(svc, "exigir_reverificacion_si_tiene_factor", lambda *a, **k: None)
    yo = Principal(id=usuario.id, tenant_id=tenant_id, tipo="usuario")

    iniciada = api.iniciar_mfa(db, yo)
    assert usuario.mfa_secreto == viejo, "el activo no puede cambiar antes de confirmar"
    assert usuario.mfa_recuperacion == ["hash-viejo"]

    with pytest.raises(NoAutenticado):
        api.activar_mfa(api.ActivarMfa(codigo="000000"), db, yo)
    assert usuario.mfa_secreto == viejo, "un código malo no puede dejar a nadie fuera"

    api.activar_mfa(api.ActivarMfa(codigo=svc.codigo_totp(iniciada.secreto)), db, yo)
    assert usuario.mfa_secreto == iniciada.secreto
    assert usuario.mfa_secreto_pendiente is None
    assert usuario.mfa_recuperacion != ["hash-viejo"]
