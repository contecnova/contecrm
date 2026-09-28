"""La cuota de registros, aplicada donde pasan todas las altas.

**Por módulo**, según lo decidido: 10.000 cuentas aquí, 50.000 contactos allá.
Cada servicio cuenta lo suyo en su esquema, así el alta no depende de una lectura
entre servicios y **el mensaje puede decir qué se ha agotado** — que con un tope
global no se puede.

**Se engancha al volcado de la sesión y no a cada ruta**, y es la excepción
razonada a «declaración explícita por ruta»: los registros no se crean por una
puerta única —cada servicio tiene las suyas, y algunas altas llegan por el bus o
por una importación masiva—, así que repartir la comprobación por las rutas
garantiza que la próxima se olvide. Lo que **sí** es explícito es **qué cuenta
como registro**: sólo los modelos que un servicio declara. Una fila de auditoría,
una entrega de aviso o un apunte de consumo no son «registros del cliente», y
contarlos le agotaría la cuota con nuestro propio ruido.

**Y la omisión deja pasar**, por partida doble: sin tope declarado no se cuenta
nada, y un modelo que nadie declare no consume cuota. Un fallo al declarar tiene
que dejar pasar de más, nunca cortar de menos.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Modelos que cuentan como «registro del cliente» en este proceso. Los declara
# cada servicio al arrancar; lo que no esté aquí no consume cuota.
_CONTABLES: dict[type, str] = {}


def declarar_contable(modelo: type, nombre: str = "") -> type:
    """Dice que las filas de este modelo son registros del cliente.

    Se devuelve el modelo para poder usarlo como decorador. Declarar dos veces el
    mismo es inocuo: en un proceso que importe varios servicios —las pruebas—
    pasaría, y fallar ahí no protegería de nada.
    """
    _CONTABLES[modelo] = nombre or getattr(modelo, "__tablename__", modelo.__name__)
    return modelo


def contables_declarados() -> dict[str, str]:
    return {m.__name__: n for m, n in _CONTABLES.items()}


def limpiar_declarados() -> None:
    """Para las pruebas: el registro es del proceso y vive entre casos."""
    _CONTABLES.clear()


def registros_guardados(db: Any, tenant_id: UUID) -> dict[str, int]:
    """Cuántos registros tiene este tenant aquí, por modelo.

    Se cuentan las filas. Un contador aparte se desincroniza el primer día que
    algo se borra por otra vía —una purga, una fusión, una baja— y entonces el
    cliente ve una cuota agotada que no se corresponde con lo que tiene.
    """
    from sqlalchemy import func, select

    salida: dict[str, int] = {}
    for modelo, nombre in _CONTABLES.items():
        salida[nombre] = int(
            db.execute(
                select(func.count()).select_from(modelo).where(modelo.tenant_id == tenant_id)
            ).scalar_one()
        )
    return salida


def _al_volcar(sesion: Any, _contexto: Any, _instancias: Any) -> None:
    """Comprueba la cuota antes de que la sesión escriba las altas nuevas.

    Sólo mira `session.new`: modificar o borrar nunca puede agotar una cuota, y
    recorrer todo lo tocado en cada volcado costaría en el camino de cualquier
    escritura.
    """
    from crmcore.cuotas import exigir, tope

    nuevos: dict[UUID, int] = {}
    for obj in sesion.new:
        if type(obj) not in _CONTABLES:
            continue
        tenant_id = getattr(obj, "tenant_id", None)
        if tenant_id is None:
            continue
        nuevos[tenant_id] = nuevos.get(tenant_id, 0) + 1

    for tenant_id, cuantos in nuevos.items():
        # El tope se lee una vez por tenant y se sale pronto: sin cuota
        # declarada, una escritura normal no paga ni una consulta de más.
        if tope(sesion, tenant_id, "cuota_registros") <= 0:
            continue
        exigir(
            sesion,
            tenant_id,
            clave="cuota_registros",
            metrica="registros",
            contar=lambda t=tenant_id: sum(registros_guardados(sesion, t).values()),
            entrantes=cuantos,
        )


def instalar_guard_cuota() -> None:
    """Engancha la comprobación al volcado de la sesión.

    Lo llama el arranque del servicio, igual que los otros dos guards. Si no se
    llamara, la cuota de registros no se aplicaría y **nada fallaría** — que es
    exactamente la avería que esta noche ha salido seis veces, así que hay una
    prueba que comprueba que el arranque lo instala.
    """
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    if not event.contains(Session, "before_flush", _al_volcar):
        event.listen(Session, "before_flush", _al_volcar)
