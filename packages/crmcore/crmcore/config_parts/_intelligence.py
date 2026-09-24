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
    ci_scopes: list[str] = Field(default_factory=lambda: ["chat:ask", "sources:read"])
