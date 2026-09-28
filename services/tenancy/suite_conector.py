"""El transporte que lleva el estado deseado a cada herramienta
(CRM-00.01.07.08).

**Lo genérico es el suelo.** Una herramienta cualquiera se conecta declarando
dirección, credencial y el mapeo de campos y de roles: no hace falta escribir
código, y por tanto un cliente con una herramienta que no conocemos no obliga a
tocar el producto. Los conectores nativos van **encima**, y solo para lo que el
genérico no alcanza: leer el estado remoto en su formato, entender su código de
error o aprovechar una operación en bloque que ahorre mil llamadas.

Dos cosas que hacen que esto sea operable y no un `POST` optimista:

**Toda salida pasa por el guard de red.** Aquí viajan datos de personas y una
credencial de administración; una dirección apuntando a la red interna
convertiría el empuje en una forma de hablar con lo que no se alcanza desde
fuera. El guard revalida cada salto, no solo el primero.

**Nunca lanza hacia arriba.** Devuelve el resultado, y la cola decide si
reintenta o aparta. Una excepción que suba desde un envío detendría el proceso de
todos los demás objetos del lote por culpa de uno.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from crmcore.logging import get_logger
from sqlalchemy.orm import Session

from services.tenancy.suite import (
    HerramientaConectada,
    SincronizacionSuite,
    anotar_resultado,
    pendientes,
)

logger = get_logger(__name__)


@dataclass(slots=True)
class Resultado:
    ok: bool
    detalle: str = ""
    identificador_externo: str = ""


class Conector(Protocol):
    """Lo que tiene que saber hacer un conector."""

    tipo: str

    def aplicar(self, herramienta: HerramientaConectada, fila: SincronizacionSuite) -> Resultado:
        """Aplica un cambio. **Nunca lanza.**"""
        ...

    def leer_estado(
        self, herramienta: HerramientaConectada, objeto: str
    ) -> dict[str, dict[str, Any]] | None:
        """El estado remoto para reconciliar, o `None` si no sabe leerlo.

        `None` y `{}` son cosas distintas: el diccionario vacío dice «allí no hay
        nada», y eso llevaría a reencolarlo todo. `None` dice «no se ha podido
        leer», y entonces la reconciliación se salta en vez de inventarse una
        divergencia que no se ha comprobado.
        """
        ...


_CONECTORES: dict[str, Conector] = {}


def registrar(conector: Conector) -> Conector:
    _CONECTORES[conector.tipo] = conector
    return conector


def conector_de(tipo: str) -> Conector | None:
    return _CONECTORES.get(tipo) or _CONECTORES.get("generico")


# ── Transporte genérico declarativo ───────────────────────────────────────

# Rutas por defecto. Son una convención razonable y **se pueden redefinir** en el
# mapeo de la herramienta: fijarlas sin salida obligaría a que toda herramienta
# se pareciese a la que teníamos delante al escribir esto.
RUTAS = {
    ("tenant", "alta"): ("PUT", "/organizaciones/{id_externo}"),
    ("tenant", "actualizacion"): ("PUT", "/organizaciones/{id_externo}"),
    ("tenant", "baja"): ("DELETE", "/organizaciones/{id_externo}"),
    ("usuario", "alta"): ("PUT", "/usuarios/{id_externo}"),
    ("usuario", "actualizacion"): ("PUT", "/usuarios/{id_externo}"),
    ("usuario", "baja"): ("DELETE", "/usuarios/{id_externo}"),
    ("unidad", "alta"): ("PUT", "/unidades/{id_externo}"),
    ("unidad", "actualizacion"): ("PUT", "/unidades/{id_externo}"),
    ("unidad", "baja"): ("DELETE", "/unidades/{id_externo}"),
}


class ConectorGenerico:
    """HTTP declarativo: dirección, credencial y mapeo, sin código por producto."""

    tipo = "generico"

    def _ruta(
        self, herramienta: HerramientaConectada, fila: SincronizacionSuite
    ) -> tuple[str, str]:
        rutas = (herramienta.mapeo_campos or {}).get("_rutas") or {}
        clave = f"{fila.objeto}.{fila.operacion}"
        if clave in rutas:
            metodo, plantilla = str(rutas[clave]).split(" ", 1)
            return metodo.upper(), plantilla
        return RUTAS[(fila.objeto, fila.operacion)]

    # Los tokens vivos, uno por herramienta y compartido por todas sus llamadas.
    #
    # Sin esto, un alta en cascada de doscientos usuarios haría doscientos
    # inicios de sesión: ese coste aparece el día que alguien sincroniza de
    # verdad, no el día que se configura con tres.
    #
    # En memoria del proceso y no en la base: es un secreto de corta vida, y
    # guardarlo le alargaría la vida justo lo que dura una fila. Si el proceso
    # se reinicia se vuelve a entrar, que cuesta una llamada.
    _tokens: dict[str, str] = {}

    def _token(
        self, herramienta: HerramientaConectada, credenciales: dict[str, Any], *, renovar: bool
    ) -> str:
        """El token con el que llamar, entrando si hace falta.

        Se admiten las dos formas porque las dos existen: un token escrito a
        mano —hay herramientas con credenciales de larga vida— y entrar con
        usuario y contraseña.

        Lo segundo hace falta más de lo que parece: **contecmind emite tokens de
        quince minutos**. Un token guardado en la configuración funciona el
        cuarto de hora en que alguien monta la integración —justo cuando la
        prueba y la da por buena— y después da 401 para siempre, disfrazado de
        credencial mal puesta. Quien lo mire buscará en el sitio equivocado.
        """
        from crmcore.red import guard_url

        clave = str(herramienta.id)
        if not renovar and self._tokens.get(clave):
            return self._tokens[clave]

        ruta = str((herramienta.mapeo_campos or {}).get("_ruta_login") or "")
        usuario = str(credenciales.get("usuario") or "")
        secreto = str(credenciales.get("clave") or "")
        if not (ruta and usuario and secreto):
            # Sin con qué entrar, vale lo escrito a mano. Y si tampoco hay nada,
            # se llama sin autenticación: que conteste el otro lado, que su
            # mensaje dirá más que uno inventado aquí.
            return str(credenciales.get("token") or "")

        with guard_url.cliente_seguro(timeout=20.0) as cliente:
            respuesta = cliente.post(
                herramienta.base_url.rstrip("/") + ruta,
                json={"email": usuario, "password": secreto},
            )
        respuesta.raise_for_status()
        cuerpo = respuesta.json() or {}
        token = str(cuerpo.get("access_token") or cuerpo.get("token") or "")
        self._tokens[clave] = token
        return token

    def aplicar(self, herramienta: HerramientaConectada, fila: SincronizacionSuite) -> Resultado:
        from crmcore.red import guard_url
        from crmcore.security.cifrado import descifrar_dict

        try:
            metodo, plantilla = self._ruta(herramienta, fila)
        except KeyError:
            return Resultado(
                ok=False,
                detalle=(
                    f"No hay ruta declarada para {fila.objeto}.{fila.operacion} en "
                    f"«{herramienta.nombre}». Declárala en el mapeo o usa un conector."
                ),
            )

        id_externo = fila.identificador_externo or fila.objeto_id
        url = herramienta.base_url.rstrip("/") + plantilla.format(
            id_externo=id_externo, tenant=herramienta.identificador_externo
        )

        try:
            credenciales = descifrar_dict(herramienta.credenciales or {})
            extra = {
                str(k): str(v)
                for k, v in (((herramienta.mapeo_campos or {}).get("_cabeceras")) or {}).items()
            }

            def _llamar(*, renovar: bool) -> Any:
                cabeceras = {"Content-Type": "application/json", **extra}
                token = self._token(herramienta, credenciales, renovar=renovar)
                if token:
                    cabeceras["Authorization"] = f"Bearer {token}"
                with guard_url.cliente_seguro(timeout=20.0) as cliente:
                    return cliente.request(
                        metodo,
                        url,
                        json=None if metodo == "DELETE" else dict(fila.carga),
                        headers=cabeceras,
                    )

            respuesta = _llamar(renovar=False)
            # UN 401 SE REINTENTA UNA VEZ, y sólo el 401. Es lo que pasa cuando el
            # token ha vencido, y renovarlo lo arregla. **Un 403 no se reintenta
            # nunca**: ahí el token vale y lo que no vale es lo que esa credencial
            # puede hacer, así que reintentar sería un bucle sobre un permiso mal
            # configurado. Mezclar los dos convierte un error de configuración en
            # una tormenta de peticiones.
            #
            # Una sola vez, además: si tras renovar sigue diciendo 401, el problema
            # no es la caducidad y hay que verlo, no insistir.
            if respuesta.status_code == 401:
                respuesta = _llamar(renovar=True)
            if respuesta.status_code >= 400:
                # El cuerpo se recorta y se guarda: sin él, «HTTP 422» no le dice
                # a nadie qué campo no le gustó a la otra herramienta.
                return Resultado(
                    ok=False,
                    detalle=f"HTTP {respuesta.status_code}: {respuesta.text[:300]}",
                )
            externo = ""
            try:
                externo = str((respuesta.json() or {}).get("id") or "")
            except Exception:  # noqa: BLE001 — una respuesta sin JSON no es un fallo
                externo = ""
            return Resultado(ok=True, identificador_externo=externo)
        except Exception as exc:  # noqa: BLE001 — el contrato es no lanzar
            return Resultado(ok=False, detalle=f"{type(exc).__name__}: {str(exc)[:300]}")

    def leer_estado(
        self, herramienta: HerramientaConectada, objeto: str
    ) -> dict[str, dict[str, Any]] | None:
        """Lee el estado remoto si la herramienta declara cómo listarlo.

        Si no lo declara, devuelve `None` y la reconciliación se salta para esa
        herramienta **diciéndolo**. Dar por buena la sincronización porque no se
        puede comprobar es exactamente el error que este módulo existe para
        evitar.
        """
        from crmcore.red import guard_url
        from crmcore.security.cifrado import descifrar_dict

        listados = (herramienta.mapeo_campos or {}).get("_listados") or {}
        plantilla = listados.get(objeto)
        if not plantilla:
            return None
        try:
            credenciales = descifrar_dict(herramienta.credenciales or {})
            cabeceras = {}
            if credenciales.get("token"):
                cabeceras["Authorization"] = f"Bearer {credenciales['token']}"
            url = herramienta.base_url.rstrip("/") + str(plantilla).format(
                tenant=herramienta.identificador_externo
            )
            with guard_url.cliente_seguro(timeout=30.0) as cliente:
                respuesta = cliente.get(url, headers=cabeceras)
            if respuesta.status_code >= 400:
                return None
            cuerpo = respuesta.json()
            elementos = cuerpo if isinstance(cuerpo, list) else (cuerpo.get("items") or [])
            clave = (herramienta.mapeo_campos or {}).get("_clave_remota", "id_externo")
            return {str(e.get(clave)): e for e in elementos if isinstance(e, dict)}
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "suite.lectura_remota_fallida", herramienta=herramienta.nombre, error=str(exc)[:200]
            )
            return None


registrar(ConectorGenerico())


# ── Conectores nativos ────────────────────────────────────────────────────


class ConectorContecmind(ConectorGenerico):
    """Encima del genérico, no en su lugar.

    Hereda todo el transporte y solo cambia lo que de verdad es distinto: las
    rutas propias del gestor documental y la clave con la que identifica a sus
    usuarios. Reescribir el transporte entero por producto es lo que hace que
    mantener cinco conectores sea imposible.
    """

    tipo = "contecmind"

    def _ruta(
        self, herramienta: HerramientaConectada, fila: SincronizacionSuite
    ) -> tuple[str, str]:
        # Las rutas de aprovisionamiento de contecmind, por NUESTRO identificador.
        #
        # Aquí ponía `/api/v1/admin/organizations/{id_externo}`,
        # `/admin/users/{id_externo}` y `/admin/departments/{id_externo}`, y
        # **ninguna de las tres existe**: lo suyo es `/admin/users` con `POST` y
        # `/{user_id}` con `PATCH`, y las organizaciones se llaman `tenants`. O
        # sea que dar de alta un tenant del CRM nunca provisionó nada en el
        # gestor documental. Es el quinto desajuste de ruta con este vecino, y
        # como los otros cuatro no lo cazó ninguna prueba: nadie había ejecutado
        # el camino entero.
        #
        # Se direcciona por el identificador NUESTRO y con `PUT` a propósito. Un
        # aprovisionamiento que no se puede reintentar no es un
        # aprovisionamiento: es una apuesta. Con el id del otro lado habría que
        # buscar antes de crear, y entre la búsqueda y el alta hay una carrera
        # que no se cierra desde fuera — dos altas a la vez crean dos usuarios.
        propias = {
            ("tenant", "alta"): ("PUT", "/api/v1/admin/tenants/by-external/{id_externo}"),
            ("tenant", "actualizacion"): ("PUT", "/api/v1/admin/tenants/by-external/{id_externo}"),
            ("usuario", "alta"): ("PUT", "/api/v1/admin/users/by-external/{id_externo}"),
            ("usuario", "actualizacion"): ("PUT", "/api/v1/admin/users/by-external/{id_externo}"),
            ("usuario", "baja"): ("DELETE", "/api/v1/admin/users/by-external/{id_externo}"),
            ("unidad", "alta"): ("PUT", "/api/v1/admin/departments/by-external/{id_externo}"),
            (
                "unidad",
                "actualizacion",
            ): ("PUT", "/api/v1/admin/departments/by-external/{id_externo}"),
            ("unidad", "baja"): ("DELETE", "/api/v1/admin/departments/by-external/{id_externo}"),
        }
        clave = (fila.objeto, fila.operacion)
        if clave in propias:
            return propias[clave]
        return super()._ruta(herramienta, fila)


class ConectorContecintelligence(ConectorGenerico):
    """Igual: encima del genérico, cambiando solo sus rutas."""

    tipo = "contecintelligence"

    def _ruta(
        self, herramienta: HerramientaConectada, fila: SincronizacionSuite
    ) -> tuple[str, str]:
        propias = {
            ("tenant", "alta"): ("PUT", "/api/v1/organizations/{id_externo}"),
            ("tenant", "actualizacion"): ("PUT", "/api/v1/organizations/{id_externo}"),
            ("usuario", "alta"): ("PUT", "/api/v1/organizations/{tenant}/members/{id_externo}"),
            ("usuario", "actualizacion"): (
                "PUT",
                "/api/v1/organizations/{tenant}/members/{id_externo}",
            ),
            ("usuario", "baja"): (
                "DELETE",
                "/api/v1/organizations/{tenant}/members/{id_externo}",
            ),
        }
        clave = (fila.objeto, fila.operacion)
        if clave in propias:
            return propias[clave]
        return super()._ruta(herramienta, fila)


registrar(ConectorContecmind())
registrar(ConectorContecintelligence())


# ── Aplicar la cola ───────────────────────────────────────────────────────


def aplicar_pendientes(
    db: Session, tenant_id: UUID, *, herramienta: str | None = None, tope: int = 100
) -> dict[str, Any]:
    """Aplica lo que toca, con la baja primero.

    Va por lotes con tope porque una cola de diez mil no puede ejecutarse dentro
    de una petición HTTP: se procesa un lote y se vuelve. Sin tope, el primer
    tenant grande que reconcilie deja el servicio sin hilos.
    """
    from services.tenancy.suite import herramientas as _herramientas

    por_nombre = {h.nombre: h for h in _herramientas(db, tenant_id, solo_activas=False)}
    aplicadas, fallidas, saltadas = 0, 0, 0

    for fila in pendientes(db, tenant_id, herramienta=herramienta, limite=tope):
        conectada = por_nombre.get(fila.herramienta)
        if conectada is None or not conectada.activa:
            # Una herramienta desactivada no es un fallo del objeto: se salta sin
            # gastarle intentos, porque si no acabaría en cuarentena por algo que
            # no tiene nada que ver con él.
            saltadas += 1
            continue
        conector = conector_de(conectada.tipo)
        if conector is None:  # pragma: no cover — siempre hay genérico
            saltadas += 1
            continue
        resultado = conector.aplicar(conectada, fila)
        anotar_resultado(
            db,
            fila,
            ok=resultado.ok,
            detalle=resultado.detalle,
            identificador_externo=resultado.identificador_externo,
        )
        if resultado.ok:
            aplicadas += 1
        else:
            fallidas += 1

    return {
        "aplicadas": aplicadas,
        "fallidas": fallidas,
        "saltadas_por_herramienta_inactiva": saltadas,
        "quedan": len(pendientes(db, tenant_id, herramienta=herramienta, limite=tope + 1)),
    }


def reconciliar_con_remoto(db: Session, tenant_id: UUID, herramienta: str) -> dict[str, Any]:
    """Lee el estado remoto y lo compara con el deseado.

    Cuando el conector no sabe leer, **se dice** en vez de dar por buena la
    sincronización: «no se ha podido comprobar» y «está todo bien» son cosas
    distintas, y confundirlas es el motivo por el que nadie se fía de los
    paneles de sincronización.
    """
    from services.tenancy.suite import _herramienta, reconciliar

    conectada = _herramienta(db, tenant_id, herramienta)
    conector = conector_de(conectada.tipo)
    remoto: dict[str, dict[str, Any]] = {}
    ilegibles: list[str] = []
    for objeto in conectada.objetos or []:
        leido = conector.leer_estado(conectada, str(objeto)) if conector else None
        if leido is None:
            ilegibles.append(str(objeto))
            continue
        remoto.update(leido)

    if ilegibles and not remoto:
        return {
            "herramienta": herramienta,
            "medible": False,
            "motivo": (
                f"«{herramienta}» no declara cómo listar {', '.join(ilegibles)}, así "
                "que no se puede comprobar si está sincronizada. Declara `_listados` "
                "en su mapeo o usa un conector que sepa leerlo."
            ),
        }

    salida = reconciliar(db, tenant_id, herramienta, remoto)
    salida["medible"] = True
    salida["objetos_ilegibles"] = ilegibles
    return salida
