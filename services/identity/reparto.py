"""El repartidor: lo que hace que un aviso salga de verdad (CRM-06.02.01.02).

Las notificaciones se creaban, se agrupaban, respetaban la franja de silencio y
se leían en la bandeja. **No salía ninguna.** Esto lo arregla.

Vive en `identity` y no en el núcleo por una razón que decide todo el diseño:
entregar exige saber la dirección del destinatario, y las personas son de
`identity`. Un repartidor central tendría que leer su esquema, y ningún servicio
lee el de otro.

Cómo decide qué manda y a dónde:

  1. Toma las notificaciones vencidas que van por un canal que no es `app`.
  2. Resuelve la dirección de cada destinatario **en ese canal**: el correo sale
     de la ficha del usuario; el teléfono, de sus atributos de membresía, que es
     donde el tenant guarda lo suyo.
  3. Compone el mensaje con la plantilla del tenant si la tiene, y con los
     formatos del tenant siempre (CRM-00.01.04.07): un aviso con
     `2026-09-19T07:00:00+00:00` en mitad de una frase no lo lee nadie.
  4. Entrega por el transporte del canal y **anota el intento**, con su error si
     lo hubo.

Y dos cosas sobre lo que NO hace:

**No decide a quién avisar.** Eso ya está decidido cuando llega aquí: quién
sigue qué, qué canales quiere y si es de noche para él lo resolvió
`crmcore.datos.seguimiento` al crear la notificación. Mezclarlo aquí habría
hecho imposible probar una cosa sin la otra.

**No reintenta dentro del mismo intento.** Un fallo se anota con su próximo
intento y se sale. Reintentar en el momento tres veces contra un proveedor caído
multiplica por tres el tiempo del lote y no entrega ni uno más.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.logging import get_logger
from crmcore.notificaciones import Destino, Mensaje, transporte_de
from crmcore.notificaciones.entrega import anotar_resultado, registrar_intento, reintentables
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = get_logger(__name__)

# De qué campo sale la dirección de cada canal. `correo` está en la ficha del
# usuario porque es su identidad; los demás en los atributos de la membresía,
# que es donde el tenant guarda lo que es suyo y no de la persona.
ORIGEN_DIRECCION = {
    "correo": ("usuario", "email"),
    "sms": ("membresia", "telefono"),
    "push": ("membresia", "push_token"),
}


def _destino(db: Session, tenant_id: UUID, usuario_id: UUID, canal: str) -> Destino | None:
    """Resuelve a quién y a dónde. `None` si esa persona ya no está en el tenant.

    Que un usuario dado de baja no reciba avisos no es un detalle: es lo que
    impide que alguien que se fue de la empresa siga recibiendo movimientos de
    clientes en su correo personal.
    """
    from crmcore.i18n import resolver

    from services.identity.modelos import Membresia, Usuario

    membresia = (
        db.execute(
            select(Membresia).where(
                Membresia.tenant_id == tenant_id,
                Membresia.usuario_id == usuario_id,
                Membresia.activa.is_(True),
            )
        )
        .scalars()
        .first()
    )
    if membresia is None:
        return None

    usuario = db.get(Usuario, usuario_id)
    if usuario is None or not usuario.activo:
        return None

    fuente, campo = ORIGEN_DIRECCION.get(canal, ("usuario", "email"))
    if fuente == "usuario":
        direccion = str(getattr(usuario, campo, "") or "")
    else:
        direccion = str((membresia.atributos or {}).get(campo) or "")

    return Destino(
        usuario_id=usuario_id,
        direccion=direccion,
        nombre=usuario.nombre or "",
        idioma=resolver(db).idioma,
    )


def _mensaje(db: Session, notificacion: Any, canal: str) -> Mensaje:
    """Compone el texto del aviso, con los formatos del tenant.

    **No renderiza plantillas de `tenancy`.** La primera versión lo hacía, y es
    acoplamiento entre servicios: las plantillas son de `tenancy` y ningún
    servicio lee el esquema de otro. El título y el cuerpo los compone quien
    crea la notificación, que sí tiene sus plantillas a mano; aquí solo se
    localiza y se adapta al canal.

    La consecuencia honesta: **hoy no hay plantilla por canal**. El mismo texto
    va al correo y al SMS. Para tenerla habría que replicar las plantillas a
    cada esquema como se hace con los ajustes, y es una capacidad aparte que
    todavía no está — decirlo aquí es mejor que fingir que existe.
    """
    from crmcore import i18n

    loc = i18n.resolver(db)
    titulo = notificacion.titulo
    cuerpo = i18n.formatear_valores({"c": notificacion.cuerpo}, loc)["c"]

    if notificacion.agrupadas > 1:
        # Se dice cuántos hechos hay detrás. Sin esto, un aviso agrupado que
        # resume doce cambios parece uno solo y el destinatario no abre.
        titulo = f"{titulo} (+{notificacion.agrupadas - 1})"

    if canal == "sms":
        # El SMS no tiene asunto y se corta a 160 caracteres. Mandar el cuerpo
        # entero produce tres mensajes cortados a mitad de palabra, que es peor
        # que uno resumido.
        cuerpo = f"{titulo}. {cuerpo}".strip()[:160]
        titulo = ""

    return Mensaje(
        titulo=titulo,
        cuerpo=cuerpo,
        tipo=notificacion.tipo,
        prioridad=notificacion.prioridad,
        objeto_tipo=notificacion.objeto_tipo or "",
        objeto_id=str(notificacion.objeto_id) if notificacion.objeto_id else "",
        datos=dict(notificacion.datos or {}),
    )


def config_canal(db: Session, canal: str) -> dict[str, Any]:
    """Configuración del canal para este tenant, de los ajustes en caliente.

    Va por ajustes y no por una tabla propia porque ya existe la jerarquía
    —global → tier → tenant— y con ella un despliegue puede poner el SMTP común
    y un cliente concreto el suyo, sin código y sin una tabla más.
    """
    from crmcore.runtime import settings as rt

    valor = rt.efectivo(f"canal_{canal}", db, default={})
    return dict(valor) if isinstance(valor, dict) else {}


def entregar_una(db: Session, notificacion: Any) -> dict[str, str]:
    """Saca un aviso por todos sus canales. Devuelve el resultado de cada uno."""
    from datetime import datetime, timezone

    resultados: dict[str, str] = {}
    for canal in notificacion.canales or []:
        if canal == "app":
            # La bandeja se lee de la tabla: «entregarla» sería escribir en la
            # fila que ya está escrita.
            continue
        transporte = transporte_de(canal)
        if transporte is None:
            resultados[canal] = "sin transporte"
            logger.warning("reparto.canal_sin_transporte", canal=canal)
            continue

        destino = _destino(db, notificacion.tenant_id, notificacion.usuario_id, canal)
        if destino is None:
            # La persona ya no está en el tenant. No se reintenta y se dice: es
            # lo que impide que alguien que se fue siga recibiendo movimientos
            # de clientes en su correo.
            fila = registrar_intento(
                db,
                tenant_id=notificacion.tenant_id,
                notificacion_id=notificacion.id,
                usuario_id=notificacion.usuario_id,
                canal=canal,
                direccion="",
            )
            from crmcore.notificaciones import Resultado

            anotar_resultado(
                db, fila, Resultado(False, "el destinatario ya no está activo", reintentar=False)
            )
            resultados[canal] = fila.estado
            continue

        fila = registrar_intento(
            db,
            tenant_id=notificacion.tenant_id,
            notificacion_id=notificacion.id,
            usuario_id=notificacion.usuario_id,
            canal=canal,
            direccion=destino.direccion,
        )
        resultado = transporte.entregar(
            destino, _mensaje(db, notificacion, canal), config_canal(db, canal)
        )
        anotar_resultado(db, fila, resultado)
        resultados[canal] = fila.estado

    # La notificación se marca entregada cuando ya no queda nada por intentar,
    # haya salido o no. Dejarla pendiente porque un canal falló definitivamente
    # la haría volver en cada vuelta del repartidor para no hacer nada.
    if all(estado != "pendiente" for estado in resultados.values()):
        notificacion.entregada_at = datetime.now(timezone.utc)
    return resultados


def repartir_lote(db: Session, *, limite: int = 100) -> dict[str, int]:
    """Una vuelta del repartidor: lo nuevo y lo que toca reintentar."""
    from crmcore.datos.seguimiento import Notificacion, pendientes_de_entregar
    from crmcore.tenancy.context import con_contexto

    cuenta = {"nuevas": 0, "reintentos": 0, "entregadas": 0}

    for notificacion in pendientes_de_entregar(db, limite=limite):
        with con_contexto(tenant_id=notificacion.tenant_id, origen="notificaciones"):
            resultados = entregar_una(db, notificacion)
        cuenta["nuevas"] += 1
        cuenta["entregadas"] += sum(1 for e in resultados.values() if e == "entregada")

    for entrega in reintentables(db, limite=limite):
        notificacion = db.get(Notificacion, entrega.notificacion_id)
        if notificacion is None:
            entrega.estado = "descartada"
            entrega.ultimo_error = "la notificación ya no existe"
            continue
        with con_contexto(tenant_id=entrega.tenant_id, origen="notificaciones"):
            resultados = entregar_una(db, notificacion)
        cuenta["reintentos"] += 1
        cuenta["entregadas"] += sum(1 for e in resultados.values() if e == "entregada")

    db.commit()
    return cuenta
