"""Integración con contecintelligence (RT-4).

La explotación del dato la resuelve contecintelligence, así que **es una
dependencia de despliegue**, no una integración opcional. O la pila lo levanta,
o se le da la dirección de uno ya en marcha y alcanzable.

Todo lo de aquí se comprueba al arrancar. Descubrir que falta la dirección
cuando alguien abre el primer informe significa que el fallo aparece delante de
un usuario, días después de desplegar y lejos de quien puede arreglarlo.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings

# ── Lo que contecrm necesita poder hacer en contecintelligence ───────────────
#
# Una sola lista, y aquí, porque estaba escrita **dos veces y las dos cortas**:
# en el valor por defecto de `ci_scopes` y en `scripts/alta_explotacion.py`,
# que es quien da de alta la aplicación al otro lado. Las dos decían
# `["chat:ask", "sources:read"]`.
#
# Con eso, el alta de la aplicación salía de **solo lectura**, y después el
# trabajo que registra el CRM como fuente pedía un token con `sources:write`
# que contecintelligence no podía emitir: contestaba
#
#     403 · «este token está acotado y no alcanza a esta operación
#            (alcances: sources:read)»
#
# y la fuente no se registraba nunca. Sin fuente registrada **el área de
# análisis entera queda muerta**: los cuadros de mando salen como cajas de
# error y no se puede ni preguntar ni ejecutar un informe. Encontrado el
# 30-10-2026, y lo que lo destapó no fue leer el código: fue dejar de tirar el
# cuerpo del 403 al guardar el fallo.
#
# Cada alcance con para qué es, para que quitar uno obligue a decir qué deja
# de funcionar:
ALCANCES_DEL_CRM = (
    "chat:ask",  # preguntar en lenguaje natural desde Explotación
    "sources:read",  # ver qué fuentes hay dadas de alta
    "sources:write",  # registrar el propio CRM como fuente consultable
    "query:run",  # ejecutar un informe: el plan lo resuelve el otro lado
)


class _IntelligenceSettings(BaseSettings):
    # Dirección del contecintelligence que atiende a este despliegue. Puede ser
    # el que levanta la propia pila (`http://contecintelligence:8000`) o uno ya
    # en marcha en otra máquina.
    ci_base_url: str = ""
    # Credencial de aplicación. **No baja nunca al navegador**: con ella se
    # canjea, en el servidor, un token corto por usuario. La credencial puede
    # representar a todos los tenants; si llegara al navegador sería la llave
    # de todos.
    # La dirección con la que **contecintelligence** ve a este CRM. No es la
    # misma que `ci_base_url` al revés ni `public_base_url`: desde su contenedor,
    # `localhost` es él mismo, y una fuente dada de alta con esa dirección se
    # consulta a sí misma. Sin esto no se puede registrar la fuente, que es el
    # paso sin el cual preguntar no devuelve nada.
    ci_url_del_crm: str = ""
    # La dirección con la que **este CRM se ve a sí mismo**, para recorrer su
    # propia superficie al dar de alta la fuente.
    #
    # Es la cuarta esquina de un cuadro que ya tenía tres: CI desde el
    # servidor (`ci_base_url`), CI desde el navegador (`ci_url_publica`), el
    # CRM desde CI (`ci_url_del_crm`)… y faltaba el CRM desde el CRM.
    #
    # Hasta el 30-10-2026 el worker que registra la fuente usaba
    # `ci_url_del_crm` también para esto. En un despliegue donde todo vive en
    # la misma red de Docker las dos direcciones coinciden y nadie lo nota;
    # **en cuanto no coinciden —que es justo para lo que existe ese ajuste— el
    # alta no puede completarse nunca**. Pasaba con la pila local: los
    # servicios corren en la máquina y contecintelligence en un contenedor, así
    # que la dirección que vale para uno no resuelve para el otro, el trabajo
    # fallaba con «[Errno 8] nodename nor servname provided» y la pantalla se
    # limitaba a repetir «el CRM no está registrado como fuente» sin decir que
    # lo había intentado.
    #
    # Vacía se cae a `ci_url_del_crm`, que es como se comportaba: un despliegue
    # existente no tiene que tocar nada.
    url_interna_del_crm: str = ""
    # La dirección de contecintelligence **desde el navegador**. Es distinta de
    # `ci_base_url`, que es la de servidor a servidor: en un despliegue con
    # contenedores, `http://contecintelligence:8000` no existe para el navegador
    # de nadie. Sin esto, la pantalla de explotación no puede preguntar aunque
    # todo lo demás esté bien.
    ci_url_publica: str = ""
    ci_client_id: str = ""
    ci_client_secret: SecretStr | None = None

    # Si la explotación está activa en este despliegue. Apagarla es una decisión
    # válida —una instalación que solo usa el CRM operativo— y entonces no se
    # exige nada de lo anterior. Lo que no vale es tenerla encendida y sin
    # configurar.
    ci_enabled: bool = True
    # Comprobar al arrancar que responde. Encendido: es el momento en que el
    # fallo le llega a quien está desplegando.
    ci_comprobar_al_arrancar: bool = True
    # Si un contecintelligence que no responde impide arrancar. **Apagado**: el
    # CRM operativo no puede depender de la herramienta de consulta. Se avisa
    # bien alto y la explotación queda degradada, que es lo que dice
    # CRM-05.01.04.08.
    ci_obligatorio_para_arrancar: bool = False

    # Plazo de las llamadas al canje. Corto: pasa en el camino de abrir una
    # pantalla, y una espera larga ahí se percibe como que el CRM va lento.
    ci_timeout_s: float = Field(10.0, ge=0.5, le=120.0)
    # Vida del token que baja al navegador. Minutos, no horas: nombra a una
    # persona y unos alcances, y viaja por la red del cliente.
    ci_token_ttl_s: int = Field(600, ge=60, le=3_600)
    # Alcances que se piden por defecto. Los mínimos para preguntar y ver las
    # fuentes; ampliarlos es una decisión consciente y va por configuración.
    # Los alcances que se piden al canjear un token de USUARIO para la pantalla
    # de explotación: preguntar y ver de qué fuentes. El registro de la fuente y
    # la ejecución de informes piden los suyos aparte, porque son otra cosa.
    ci_scopes: list[str] = Field(default_factory=lambda: list(ALCANCES_DEL_CRM))

    # Cuánto se le da al REGISTRO de la fuente, que no es una llamada: recorre la
    # superficie del CRM entero, pide una muestra de cada listado para medir su
    # forma y lee el contrato de cada servicio para sacar el vocabulario. Son del
    # orden de sesenta peticiones.
    #
    # Iba con el plazo de una llamada normal —treinta segundos, escrito a fuego
    # en el código— y se agotaba a medias: la fuente anterior ya estaba borrada y
    # la nueva sin crear, así que el CRM se quedaba apuntando a una fuente que ya
    # no existía y todo informe contestaba «Fuente no encontrada».
    ci_timeout_registro_s: float = Field(300.0, ge=30.0, le=1800.0)

    # Si la IA aplicada sirve (barrido del 10-11-2026). Porcentaje de propuestas
    # de la extracción de una transcripción que se corrigen a partir del que
    # «no merece la pena» —revisar cansa más que escribir—; era un 40 en
    # `transcripcion.calidad_de_la_extraccion`.
    transcripcion_correccion_maxima_pct: float = Field(40.0, ge=0.0, le=100.0)
    # Porcentaje de casos parecidos sugeridos que el agente usa por debajo del
    # cual las sugerencias «no sirven»; era un 15 en
    # `caso_semantico.aprender_de_lo_usado`.
    caso_parecido_uso_minimo_pct: float = Field(15.0, ge=0.0, le=100.0)
