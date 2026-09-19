"""Lo que de verdad hace una automatización (CRM-00.03.03.03).

El motor evaluaba condiciones y llamaba a unos ejecutores que **nadie
inyectaba**: las reglas se guardaban, se validaban, se simulaban y no hacían
nada. Aquí están.

**Casi nada se ejecuta aquí dentro.** Una automatización que crea una tarea o
asigna un lead está pidiendo escribir en el esquema de otro servicio, y los
permisos de base de datos lo impiden — deliberadamente, porque es lo que
mantiene la propiedad exclusiva del dato. Así que estos ejecutores **emiten
comandos** y el servicio dueño los atiende.

Eso hace la automatización **asíncrona**, y es lo correcto: quien guarda una
cuenta está esperando a que se guarde su cuenta, no a que terminen tres reglas
encadenadas. Lo que sí es síncrono es la traza — que la regla se disparó consta
antes de responder, aunque sus efectos lleguen un segundo después.

**Lo que no se puede ejecutar entero, no se ofrece.** `enviar_correo` estaba en
la lista de acciones admitidas y no había con qué enviar: una regla que lo usara
se habría guardado, validado y ejecutado «bien» sin que saliera ningún correo.
Está fuera hasta que exista el repartidor, y se dice en el error que devuelve
quien la intente usar.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.bus.comandos import Comando, emitir
from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)


def construir(uow: Any) -> dict[str, Any]:
    """Los ejecutores atados a la transacción en curso.

    Se construyen por ejecución y no una vez al arrancar porque cada uno necesita
    la unidad de trabajo de **esta** petición: encolar un comando fuera de ella
    lo mandaría aunque la transacción que lo provocó acabara deshaciéndose.
    """

    def _crear_registro(
        objeto: str = "", _contexto: Any = None, _tenant_id: UUID | None = None, **campos: Any
    ) -> dict[str, Any]:
        if not objeto:
            raise ErrorValidacion(
                "«crear_registro» necesita saber qué objeto crear",
                error_code="automatizacion.falta_objeto",
            )
        comando = Comando(
            accion="crear",
            objeto=objeto,
            tenant_id=_tenant_id or uow.tenant_id,
            datos=campos,
            origen_id=str(_contexto.profundidad) if _contexto else None,
        )
        emitir(uow, comando)
        return {"comando": comando.asunto, "objeto": objeto}

    def _actualizar_registro(
        objeto: str = "",
        registro_id: str = "",
        _contexto: Any = None,
        _tenant_id: UUID | None = None,
        **campos: Any,
    ) -> dict[str, Any]:
        if not objeto or not registro_id:
            raise ErrorValidacion(
                "«actualizar_registro» necesita el objeto y el identificador",
                error_code="automatizacion.falta_registro",
            )
        comando = Comando(
            accion="actualizar",
            objeto=objeto,
            tenant_id=_tenant_id or uow.tenant_id,
            registro_id=UUID(str(registro_id)),
            datos=campos,
        )
        emitir(uow, comando)
        return {"comando": comando.asunto, "registro_id": registro_id}

    def _asignar(
        objeto: str = "",
        registro_id: str = "",
        usuario_id: str = "",
        _contexto: Any = None,
        _tenant_id: UUID | None = None,
        **_extra: Any,
    ) -> dict[str, Any]:
        if not usuario_id:
            raise ErrorValidacion(
                "«asignar» necesita a quién", error_code="automatizacion.falta_usuario"
            )
        comando = Comando(
            accion="asignar",
            objeto=objeto,
            tenant_id=_tenant_id or uow.tenant_id,
            registro_id=UUID(str(registro_id)) if registro_id else None,
            datos={"owner_id": str(usuario_id)},
        )
        emitir(uow, comando)
        return {"comando": comando.asunto, "asignado_a": usuario_id}

    def _notificar(
        titulo: str = "",
        cuerpo: str = "",
        usuarios: Any = None,
        objeto: str = "",
        registro_id: str = "",
        _contexto: Any = None,
        _tenant_id: UUID | None = None,
        **_extra: Any,
    ) -> dict[str, Any]:
        if not titulo:
            raise ErrorValidacion(
                "Un aviso sin título no se puede leer",
                error_code="automatizacion.falta_titulo",
            )
        # Evento, no comando: la bandeja la construye quien sigue el registro, y
        # el consumidor de identidad ya sabe traducir esto. Un comando exigiría
        # que la automatización supiera a quién avisar, que es justo lo que el
        # seguimiento resuelve.
        uow.emitir(
            "automatizacion.aviso",
            subject=(objeto or "automatizacion", registro_id or (_tenant_id or uow.tenant_id)),
            data={
                "titulo": titulo,
                "cuerpo": cuerpo,
                "objeto_tipo": objeto or None,
                "objeto_id": registro_id or None,
                "menciones": [str(u) for u in (usuarios or [])],
            },
        )
        return {"aviso": titulo}

    def _lanzar_proceso(
        proceso: str = "",
        _contexto: Any = None,
        _tenant_id: UUID | None = None,
        **entrada: Any,
    ) -> dict[str, Any]:
        if not proceso:
            raise ErrorValidacion(
                "«lanzar_proceso» necesita saber cuál",
                error_code="automatizacion.falta_proceso",
            )
        comando = Comando(
            accion="lanzar",
            objeto="proceso",
            tenant_id=_tenant_id or uow.tenant_id,
            datos={"definicion": proceso, "entrada": entrada},
        )
        emitir(uow, comando)
        return {"comando": comando.asunto, "proceso": proceso}

    def _emitir_evento(
        tipo: str = "", _contexto: Any = None, _tenant_id: UUID | None = None, **datos: Any
    ) -> dict[str, Any]:
        if not tipo:
            raise ErrorValidacion(
                "«emitir_evento» necesita el tipo", error_code="automatizacion.falta_tipo"
            )
        from crmcore.events.catalogo import todos

        conocidos = {t.tipo for t in todos()}
        if tipo not in conocidos:
            # Se rechaza en vez de publicarlo: un evento que no está en el
            # catálogo no lo consume nadie, así que la regla parecería funcionar
            # y no haría nada. Y el Anexo B es el contrato con los integradores.
            raise ErrorValidacion(
                f"«{tipo}» no está en el catálogo de eventos",
                error_code="automatizacion.evento_desconocido",
                detalle={"conocidos": sorted(conocidos)[:40]},
            )
        uow.emitir(
            tipo,
            subject=("automatizacion", _tenant_id or uow.tenant_id),
            data=datos,
        )
        return {"evento": tipo}

    def _llamar_api(
        url: str = "",
        metodo: str = "POST",
        _contexto: Any = None,
        _tenant_id: UUID | None = None,
        **cuerpo: Any,
    ) -> dict[str, Any]:
        """Llamada saliente. Va por el guard de SSRF, como todas.

        Es la única acción que se ejecuta **aquí y ahora**: no hay otro servicio
        dueño de «internet». Con plazo corto, porque corre dentro de la petición
        que disparó la regla y quien está guardando una cuenta no puede esperar
        treinta segundos a que conteste un sistema ajeno.
        """
        import httpx
        from crmcore.red import cliente_seguro

        if not url:
            raise ErrorValidacion(
                "«llamar_api» necesita la URL", error_code="automatizacion.falta_url"
            )
        try:
            with cliente_seguro(timeout=5.0) as cli:
                respuesta = cli.request(metodo.upper(), url, json=cuerpo or None)
        except httpx.HTTPError as exc:
            raise ErrorValidacion(
                f"No se ha podido llamar a «{url}»: {exc}",
                error_code="automatizacion.api_inalcanzable",
            ) from exc
        return {"codigo_http": respuesta.status_code, "url": url}

    def _calcular(
        objeto: str = "",
        registro_id: str = "",
        campo: str = "",
        valor: Any = None,
        _contexto: Any = None,
        _tenant_id: UUID | None = None,
        **_extra: Any,
    ) -> dict[str, Any]:
        """Fija un campo calculado. Es `actualizar_registro` con un solo campo.

        Se mantiene como acción aparte porque en el editor de reglas es lo que la
        gente busca —«pon este valor en este campo»— y obligarles a encontrarlo
        dentro de «actualizar registro» hace que no lo usen.
        """
        if not campo:
            raise ErrorValidacion(
                "«calcular» necesita el campo", error_code="automatizacion.falta_campo"
            )
        return _actualizar_registro(
            objeto=objeto,
            registro_id=registro_id,
            _contexto=_contexto,
            _tenant_id=_tenant_id,
            **{campo: valor},
        )

    return {
        "crear_registro": _crear_registro,
        "actualizar_registro": _actualizar_registro,
        "asignar": _asignar,
        "notificar": _notificar,
        "lanzar_proceso": _lanzar_proceso,
        "emitir_evento": _emitir_evento,
        "llamar_api": _llamar_api,
        "calcular": _calcular,
    }
