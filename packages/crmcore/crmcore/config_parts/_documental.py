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
    #
    # Y `documents:write`, que no estaba: sin él, colocar un documento en la
    # carpeta de un registro da 403. Y no solo eso — en contecmind el rol que se
    # pide al canjear se RECORTA a lo que la aplicación tiene concedido, así que
    # sin escritura el token bajaba a «usuario» y ni siquiera se podía crear la
    # carpeta. Quien quiera un CRM que solo lea el corpus lo quita a sabiendas de
    # que entonces los documentos se colocan a mano en el gestor.
    dms_scopes: tuple[str, ...] = ("documents:read", "documents:search", "documents:write")

    # ── El árbol de carpetas del corpus ───────────────────────────────────
    # El área de contecmind donde vive el corpus de este CRM, POR SU NOMBRE.
    #
    # Por su nombre y no por su identificador, que es lo primero que uno
    # escribiría: el identificador de un área es **de un tenant**, y este fichero
    # es el mismo para todos los del despliegue. Un id fijo sería el del primero
    # y los demás apuntarían a un área que no existe o, peor, a una ajena. Un
    # nombre además sobrevive a copiar la configuración a otra instalación; un
    # identificador obliga a acordarse de cambiarlo, y nadie se acuerda.
    #
    # Se resuelve contra `GET /api/v1/areas` con el token del usuario, así que
    # la lista ya viene acotada a lo que esa persona puede leer.
    #
    # Vacío y con UNA sola área visible, se usa esa: en el caso normal no hay
    # nada que configurar. Vacío y con varias, se dice que hay que elegir y se
    # enseñan los nombres — adivinar ahí sería repartir los documentos del CRM
    # en el área que tocara ese día.
    dms_area_nombre: str = ""

    # Dónde cuelga la carpeta de cada registro, como plantilla. `{objeto}` es el
    # nombre de negocio del objeto —el mismo vocabulario que la papelera— y
    # `{registro}` su etiqueta legible.
    #
    # Es configuración y no código porque la organización del corpus es de cada
    # casa: unos quieren `Clientes / ACME`, otros `2026 / Clientes / ACME` y
    # otros una sola carpeta por departamento. Una jerarquía escrita a fuego
    # haría que la de uno sirviera y la del otro tuviera que pelearse con ella.
    #
    # Se resuelve UNA vez por registro y el identificador resultante se guarda
    # en el enlace: así, si alguien mueve o renombra la carpeta en contecmind,
    # el CRM sigue apuntando a la misma carpeta y no crea una nueva al lado.
    dms_carpeta_plantilla: str = "{objeto}/{registro}"

    # Plazo para las operaciones que piensan: el resumen y los conceptos de una
    # rama pasan por el modelo de lenguaje, y ese plazo no tiene nada que ver
    # con el de listar una carpeta.
    #
    # Generoso a propósito y **solo usable desde un trabajo de fondo**: en
    # contecmind el modelo de embeddings puede tardar minutos en cargar en frío,
    # así que un plazo que funciona en caliente y falla en frío no es un plazo.
    # Por eso el resumen no se pide desde una petición de usuario.
    dms_timeout_analisis_s: float = Field(600.0, ge=30.0, le=3_600.0)
