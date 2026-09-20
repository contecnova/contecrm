"""Mixins de configuración por dominio.

Cada módulo expone una clase `_FooSettings(BaseSettings)` con los campos de una
preocupación acotada (base de datos, bus, autenticación, límites…).
`crmcore.config.Settings` los compone por herencia múltiple.

Los mixins NO se instancian nunca por su cuenta: solo la clase hoja, que es la
que lleva el `model_config` con la carga de `.env`.

**Añadir un ajuste**: se pone el campo en el mixin que le corresponda, con
`Field(default, ge=…, le=…)` y un comentario que explique de dónde sale el
default. Nada de constantes de módulo ni literales sueltos en el código: un
número que cambia el comportamiento es configuración, y la configuración se
edita sin volver a desplegar.
"""

from crmcore.config_parts._almacen import _AlmacenSettings
from crmcore.config_parts._app import _AppSettings
from crmcore.config_parts._auth import _AuthSettings
from crmcore.config_parts._bus import _BusSettings
from crmcore.config_parts._db import _DbSettings
from crmcore.config_parts._documental import _DocumentalSettings
from crmcore.config_parts._intelligence import _IntelligenceSettings
from crmcore.config_parts._limits import _LimitsSettings
from crmcore.config_parts._obs import _ObsSettings
from crmcore.config_parts._security import _SecuritySettings
from crmcore.config_parts._servicio import _ServicioSettings
from crmcore.config_parts._tenancy import _TenancySettings

__all__ = [
    "_AlmacenSettings",
    "_AppSettings",
    "_AuthSettings",
    "_BusSettings",
    "_DbSettings",
    "_DocumentalSettings",
    "_IntelligenceSettings",
    "_LimitsSettings",
    "_ObsSettings",
    "_SecuritySettings",
    "_ServicioSettings",
    "_TenancySettings",
]
