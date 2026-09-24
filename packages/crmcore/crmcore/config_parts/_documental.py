"""Gestión documental delegada en contecmind (RT-5).

El corpus documental de la empresa —contratos, procedimientos, certificados—
lo resuelve **contecmind**, usado de forma frontless: las pantallas son de
contecrm y el versionado, la aprobación, la obsolescencia y la búsqueda las pone
él. Es la misma decisión que con contecintelligence para la explotación del
dato, y por el mismo motivo: ya existe, lleva en producción y reescribirlo aquí
sería mantener dos veces lo mismo peor.

**Lo que NO se delega, y es la diferencia con contecintelligence.** El adjunto
que cuelga de un registro —la foto de una visita, el PDF firmado de una
oportunidad— sigue en contecrm. Cuelga del registro, sigue su papelera, su
retención y su baja de tenant, y tiene que poder subirse aunque el gestor
documental no responda. Que un comercial no pueda adjuntar una foto porque
contecmind está caído sería una regresión, no una integración.

Así que esto es una dependencia **de una capa**, no de todo: sin contecmind hay
CRM y hay adjuntos; lo que no hay es corpus documental.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings


class _DocumentalSettings(BaseSettings):
    # Dirección del contecmind que atiende a este despliegue. Puede ser el que
    # levante la propia pila o uno ya en marcha en otra máquina, que es lo
    # normal en una instalación con varias soluciones de la casa.
    dms_base_url: str = ""
    # Credencial de aplicación. **No baja nunca al navegador**: con ella se
    # canjea en el servidor un token corto por usuario, igual que con
    # contecintelligence. La credencial puede representar a todos los tenants.
    dms_client_id: str = ""
    dms_client_secret: SecretStr | None = None

    # Si el corpus documental está activo en este despliegue. Apagarlo es una
    # decisión válida —una instalación que solo quiere adjuntar ficheros a sus
    # registros— y entonces no se exige nada de lo anterior. Lo que no vale es
    # tenerlo encendido y sin configurar.
    dms_enabled: bool = False
    # Comprobar al arrancar que responde. Es el momento en que el fallo le llega
    # a quien está desplegando y no a un usuario tres días después.
    dms_comprobar_al_arrancar: bool = True
    # Si un contecmind que no responde impide arrancar. **Apagado**: el CRM
    # operativo no puede depender del gestor documental. Se avisa alto y el
    # corpus queda degradado.
    dms_exigir_al_arrancar: bool = False
    dms_timeout_s: float = Field(15.0, ge=1.0, le=120.0)
    # Vida del token de usuario que se canjea contra el gestor. Corta: viaja al
    # navegador y su único trabajo es abrir un documento o hacer una búsqueda.
    dms_token_ttl_s: int = Field(300, ge=30, le=3_600)
    # Ámbitos que se piden al canjear. Lista y no literal en el código para que
    # una instalación pueda acotarlos más sin tocar nada.
    #
    # **Los DOS, y no por comodidad.** contecmind comprueba los alcances en cada
    # petición, y separa abrir un documento (`documents:read`) de buscar en el
    # corpus (`documents:search`). Con sólo el primero, la ficha de un documento
    # funciona y el buscador devuelve 403 — que es justo el fallo que peor se
    # diagnostica, porque la mitad de la pantalla va bien. Quien quiera acotar,
    # que quite `documents:search` a sabiendas de que apaga el buscador.
    dms_scopes: tuple[str, ...] = ("documents:read", "documents:search")
