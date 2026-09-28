"""La cuota de espacio por tenant se aplica de verdad (CRM-00.01.06.02).

Del catálogo de cuotas —almacenamiento, registros, llamadas API, correos,
workflows y tokens de IA— tres ya se aplicaban: el rate limiting por
`LimitesMiddleware`, el gasto de IA por `exigir_presupuesto`, y el **tamaño de
un fichero suelto** aquí mismo. Lo que no existía era el **total**: un tenant
podía subir un millón de ficheros de 24 MB uno detrás de otro sin que nada
dijera nada.

Las dos mitades, y la segunda importa tanto como la primera: **que corte cuando
toca y que NO corte cuando no toca**. Sin la segunda, «aplicar la cuota» se
puede implementar como «cortar», y eso sale en verde.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.datos import adjuntos as adj
from crmcore.errors import CuotaAgotada

# EN CADA PUSH. Aquí se comprueba que lo que ocupa un tenant no cuente contra
# la cuota de otro, y eso no lo cubre el barrido de fugas: no es que se vean
# datos ajenos, es que a un cliente se le bloquean las subidas por lo que sube
# otro. Se nota al instante y no hay forma de deducirlo. Son tres segundos.
pytestmark = [pytest.mark.db, pytest.mark.despliegue]


def _fijar_tope(db: Any, tenant_id: UUID, mb: int) -> None:
    """El tope, por el mismo camino que lo pondría un administrador."""
    from crmcore.runtime import settings as rt

    rt.fijar(db, "cuota_almacenamiento_mb", mb, ambito="tenant", ambito_id=str(tenant_id))
    db.commit()


def _subir(db: Any, tenant_id: UUID, datos: bytes, nombre: str = "fichero.pdf") -> Any:
    return adj.subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo="cuenta",
        objeto_id=uuid4(),
        nombre=nombre,
        datos=datos,
    )


# ── La mitad que corta ────────────────────────────────────────────────────


def test_al_pasarse_del_tope_no_se_sube(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    _fijar_tope(db, tenant_id, 1)  # 1 MB

    _subir(db, tenant_id, b"x" * 700_000, "primero.pdf")
    db.commit()

    with pytest.raises(CuotaAgotada) as excinfo:
        _subir(db, tenant_id, b"y" * 700_000, "segundo.pdf")

    assert excinfo.value.error_code == "cuota.almacenamiento"
    # Con los números dentro: «cuota agotada» a secas obliga a llamar para saber
    # cuánto queda y por cuánto se ha pasado.
    detalle = excinfo.value.detalle
    assert detalle["limite"] == 1
    assert detalle["consumido"] > 0
    # Qué ajuste hay que tocar para subirlo: sin esto, quien recibe el error
    # tiene que averiguar a qué clave corresponde «almacenamiento».
    assert detalle["ajuste"] == "cuota_almacenamiento_mb"


def test_el_que_cabe_justo_entra(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """El borde. Rechazar lo que cabe exacto es tan incorrecto como dejar pasar
    lo que no cabe, y es el error que se cuela al escribir `>=` donde va `>`."""
    _fijar_tope(db, tenant_id, 1)
    fila = _subir(db, tenant_id, b"z" * (1024 * 1024))
    assert fila.tamano == 1024 * 1024


# ── La mitad que NO corta ─────────────────────────────────────────────────


def test_sin_tope_declarado_se_sube_sin_limite(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La omisión abre, nunca cierra.

    Un despliegue que no ha configurado cuotas no puede quedarse sin poder subir
    nada porque a alguien se le olvidara declararlas. Es la regla de la casa para
    todas las cuotas y es la que evita que un fallo de declaración corte el
    producto entero.
    """
    for i in range(4):
        _subir(db, tenant_id, b"q" * 500_000, f"grande-{i}.pdf")
        db.commit()
    assert adj.espacio_ocupado(db, tenant_id) == 2_000_000


def test_un_tope_a_cero_es_sin_limite(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Cero y «pequeño» son cosas distintas: cero significa sin límite, y
    confundirlos dejaría a un tenant sin poder subir ni un byte."""
    _fijar_tope(db, tenant_id, 0)
    fila = _subir(db, tenant_id, b"w" * 900_000)
    assert fila.tamano == 900_000


def test_por_debajo_del_tope_no_estorba(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    _fijar_tope(db, tenant_id, 10)
    for i in range(3):
        _subir(db, tenant_id, b"a" * 100_000, f"pequeno-{i}.pdf")
        db.commit()
    assert adj.espacio_ocupado(db, tenant_id) == 300_000


# ── El tope es de este tenant, no de la instalación ───────────────────────


def test_lo_que_ocupa_otro_tenant_no_cuenta(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sumar lo de todos dejaría a un cliente sin espacio por lo que sube otro,
    que es la peor forma posible de agotar una cuota."""
    _fijar_tope(db, tenant_id, 1)

    for i in range(3):
        _subir(db, otro_tenant_id, b"v" * 500_000, f"del-otro-{i}.pdf")
        db.commit()

    assert adj.espacio_ocupado(db, tenant_id) == 0
    fila = _subir(db, tenant_id, b"m" * 900_000)
    assert fila.tamano == 900_000


# ── El ocupado se suma de las filas, no de un contador ────────────────────


def test_borrar_un_adjunto_libera_espacio(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Por qué no hay contador.

    Un contador aparte se desincroniza el primer día que una fila desaparece por
    otra vía —una purga, una baja, un borrado en cascada— y entonces el cliente
    paga por espacio que no ocupa, o se le deja pasar del tope. Sumando las
    filas, la cuenta es verdad por construcción.
    """
    _fijar_tope(db, tenant_id, 1)
    fila = _subir(db, tenant_id, b"p" * 900_000)
    db.commit()
    assert adj.espacio_ocupado(db, tenant_id) == 900_000

    db.delete(fila)
    db.commit()

    assert adj.espacio_ocupado(db, tenant_id) == 0
    # Y vuelve a caber lo que antes no cabía.
    nuevo = _subir(db, tenant_id, b"n" * 900_000)
    assert nuevo.tamano == 900_000
