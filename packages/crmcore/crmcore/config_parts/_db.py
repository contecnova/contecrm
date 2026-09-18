"""Base de datos: conexión, pool y aislamiento en el motor."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class _DbSettings(BaseSettings):
    # ── Conexión ──────────────────────────────────────────────────────────
    # Un servicio se conecta SIEMPRE con un rol propio, sin permisos sobre los
    # esquemas de los demás (CRM-00.03.01.02). `deploy/crear-bases.sh` crea un
    # rol y un esquema por servicio; esta URL apunta al suyo.
    #
    # El default es el de desarrollo local que levanta `docker-compose.yml`.
    # En producción viene del entorno y `crmcore.config` exige que no sea este.
    database_url: str = "postgresql+psycopg://contecrm:contecrm_dev_only@localhost:5432/contecrm"

    # URL con el rol administrador, usada SOLO por las migraciones. Separarlas
    # es lo que permite que el rol de la aplicación no tenga DDL: si el proceso
    # que atiende peticiones no puede crear ni alterar tablas, una inyección no
    # puede alterarlas tampoco.
    database_admin_url: str = ""

    # Esquema propio del servicio. Vacío = se deriva de `service_name`.
    # Explicitarlo sirve para los servicios que comparten esquema en un
    # despliegue pequeño (un solo proceso, varios dominios).
    db_schema: str = ""

    # ── Pool ──────────────────────────────────────────────────────────────
    # El total de conexiones simultáneas por proceso es `pool_size + overflow`.
    # Defaults conservadores para un servicio de API: la mayoría de peticiones
    # retienen la conexión milisegundos. Un servicio con trabajos largos
    # (importaciones, orquestador) sube estos valores en su `.env`.
    db_pool_size: int = Field(10, ge=1, le=200)
    db_max_overflow: int = Field(10, ge=0, le=200)
    db_pool_timeout_s: int = Field(30, ge=1, le=300)
    # Recicla conexiones antes de que un proxy o el propio Postgres las cierre
    # por inactividad; media hora va por debajo de los timeouts habituales.
    db_pool_recycle_s: int = Field(1800, ge=60, le=86_400)
    # Fallar rápido si Postgres no responde, en vez de bloquear el worker el
    # tiempo por defecto del TCP del sistema (75 s o más). Un worker colgado es
    # lo que convierte una base caída en un sistema que "se queda pensando".
    db_connect_timeout_s: int = Field(5, ge=1, le=60)

    # ── Aislamiento en el motor (RLS) ─────────────────────────────────────
    # Row-Level Security activa. Es la garantía dura de CRM-00.01.02.01: aunque
    # una consulta olvide el filtro de tenant, el motor no devuelve filas
    # ajenas.
    #
    # Va a `true` por defecto, al revés que en contecmind, donde nació apagada
    # para no cambiar el comportamiento de un sistema ya en producción. Aquí no
    # hay nada en producción todavía, así que el default puede ser el correcto
    # desde el principio.
    #
    # AVISO HONESTO: un rol SUPERUSER o con BYPASSRLS se salta RLS aunque esté
    # FORCE. Con `rls_enabled=true` el arranque comprueba que el rol de conexión
    # no los tiene y se niega a arrancar si los tiene (ver `crmcore.db.session`).
    rls_enabled: bool = True

    # Guard de tenant en la capa ORM: segunda red, independiente de RLS, que
    # inyecta el filtro de tenant en todo SELECT/UPDATE/DELETE de un modelo con
    # `tenant_id`. Se puede apagar para una consulta administrativa legítima,
    # pero apagarlo globalmente en producción deja el sistema con una sola red.
    tenant_guard_enabled: bool = True

    # Aplicar migraciones al arrancar. En desarrollo es cómodo; en producción se
    # deja en false y las aplica un paso aparte, para que dos réplicas no migren
    # a la vez (mismo criterio que contecpos).
    db_migrate_on_boot: bool = False
