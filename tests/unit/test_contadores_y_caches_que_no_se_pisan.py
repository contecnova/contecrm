"""Un contador de intentos que suma la base y una caché de claves por IP.

FUN-A-15 (auditoría 13-11-2026): el contador de logins fallidos se leía, se
sumaba en Python y se escribía el valor absoluto; veinte intentos en paralelo
leían el mismo N y escribían N+1, y el bloqueo llegaba tarde.

FUN-A-13: la caché de claves de API iba por secreto: validada desde una IP
permitida, la misma clave entraba desde cualquier IP durante el TTL.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest


def test_el_fallo_suma_sobre_lo_que_hay_en_la_base(db: Any, tenant_id: UUID) -> None:
    import sqlalchemy as sa

    from services.identity import servicio as svc
    from services.identity.modelos import Usuario

    usuario = Usuario(email="cuenta@empresa.example", nombre="C", activo=True)
    db.add(usuario)
    db.flush()
    # Otro intento en paralelo ya dejó 3 en la base; este objeto aún cree que 0.
    db.execute(sa.update(Usuario).where(Usuario.id == usuario.id).values(intentos_fallidos=3))
    usuario.intentos_fallidos = 0

    svc._anotar_fallo(db, usuario, maximo=5, minutos=15)

    en_base = db.execute(
        sa.select(Usuario.intentos_fallidos).where(Usuario.id == usuario.id)
    ).scalar_one()
    assert en_base == 4
    svc._anotar_fallo(db, usuario, maximo=5, minutos=15)
    bloqueado = db.execute(
        sa.select(Usuario.bloqueado_hasta).where(Usuario.id == usuario.id)
    ).scalar_one()
    assert bloqueado is not None, "al llegar al máximo se bloquea"


async def test_la_misma_clave_desde_otra_ip_vuelve_a_preguntar() -> None:
    from services.gateway import claves

    claves.limpiar_cache()
    preguntas: list[str] = []
    datos = {"clave_id": str(uuid4()), "tenant_id": str(uuid4()), "permisos": [], "rol": "x"}

    def responder(peticion: httpx.Request) -> httpx.Response:
        import json

        ip = json.loads(peticion.content)["ip"]
        preguntas.append(ip)
        if ip == "10.0.0.1":
            return httpx.Response(200, json=datos)
        return httpx.Response(401, json={"error_code": "auth.clave_invalida"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
        secreto = claves.PREFIJO + "secreto-de-prueba"
        await claves.principal_de_clave(cliente, secreto, ip="10.0.0.1", url_identity="http://i")
        await claves.principal_de_clave(cliente, secreto, ip="10.0.0.1", url_identity="http://i")
        from crmcore.errors import NoAutenticado

        with pytest.raises(NoAutenticado):
            await claves.principal_de_clave(
                cliente, secreto, ip="198.51.100.7", url_identity="http://i"
            )
    assert preguntas == ["10.0.0.1", "198.51.100.7"], "la caché no puede servir otra IP"
    claves.limpiar_cache()
