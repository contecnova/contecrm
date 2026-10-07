"""Compromisos de servicio por tier: RPO, RTO y disponibilidad.

Están en la configuración y no en un documento porque un compromiso que solo
vive en un PDF no lo comprueba nadie. Aquí los lee el sistema —para avisar
cuando la última copia pasa del RPO— y la API los publica, así que el número que
se le enseña al cliente es el mismo que el que se vigila.

**Los valores por defecto son deliberadamente conservadores.** Un RPO de cinco
minutos escrito sin la infraestructura que lo sostenga es una promesa incumplida
el día que haga falta; uno de veinticuatro horas con copia diaria es cierto, y
subirlo es una decisión de negocio con coste, que es como debe tomarse.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class _ServicioSettings(BaseSettings):
    # ── RPO: cuánto dato se puede perder ──────────────────────────────────
    # Minutos de datos en riesgo. Con copia diaria, el RPO real es de hasta
    # 24 h; bajarlo exige archivado continuo del WAL, que es otra
    # infraestructura y otro coste.
    rpo_minutos_estandar: int = Field(1_440, ge=1, le=10_080)
    rpo_minutos_premium: int = Field(240, ge=1, le=10_080)
    rpo_minutos_enterprise: int = Field(15, ge=1, le=10_080)

    # ── RTO: cuánto se tarda en volver ────────────────────────────────────
    # Minutos hasta el servicio restablecido. Incluye restaurar los datos Y
    # levantar el sistema: medir solo la restauración es la trampa clásica —el
    # `pg_restore` tarda diez minutos y el servicio vuelve a la hora.
    rto_minutos_estandar: int = Field(480, ge=1, le=10_080)
    rto_minutos_premium: int = Field(120, ge=1, le=10_080)
    rto_minutos_enterprise: int = Field(30, ge=1, le=10_080)

    # ── Disponibilidad comprometida ───────────────────────────────────────
    # Porcentaje mensual. 99,5 % son 3 h 39 min de parada al mes; 99,9 %, 43 min.
    # Prometer 99,99 % (4 min) exige multi-región activo-activo: si no está
    # montado, el número es falso.
    disponibilidad_estandar: float = Field(99.5, ge=90.0, le=100.0)
    disponibilidad_premium: float = Field(99.9, ge=90.0, le=100.0)
    disponibilidad_enterprise: float = Field(99.95, ge=90.0, le=100.0)

    # ── Latencia comprometida ─────────────────────────────────────────────
    # Percentil 95 en milisegundos. El p95 y no la media: la media la arregla un
    # montón de respuestas rápidas mientras el 5 % de los usuarios espera cuatro
    # segundos, y son esos los que llaman. Por encima de este número, la
    # petición cuenta como gastada del presupuesto aunque haya devuelto 200:
    # para quien la espera, cuatro segundos son un error.
    latencia_p95_ms_estandar: int = Field(2_000, ge=50, le=60_000)
    latencia_p95_ms_premium: int = Field(1_000, ge=50, le=60_000)
    latencia_p95_ms_enterprise: int = Field(500, ge=50, le=60_000)

    # Días del periodo sobre el que se cuenta el presupuesto de error. Mensual
    # por defecto porque es el periodo en el que se firman los compromisos.
    slo_dias_periodo: int = Field(30, ge=1, le=365)
    # Latencia objetivo con la que se mide la presión del sistema
    # (CRM-08.01.01.06). No es el SLO contratado —ese depende del tier y vive en
    # `tenancy`—: es el punto a partir del cual este proceso se considera
    # saturado y empieza a aplazar lo diferible. Por eso es un ajuste de
    # despliegue y no de tenant.
    slo_latencia_objetivo_ms: int = Field(500, ge=50, le=30_000)

    # Aviso cuando la última copia supera este porcentaje del RPO. Al 80 % queda
    # margen para reaccionar; al 100 % el aviso llega cuando ya se ha incumplido.
    rpo_aviso_pct: int = Field(80, ge=10, le=100)

    # ── Tareas periódicas ─────────────────────────────────────────────────
    #
    # contecrm tenía workers de cola y **nada que hiciera «cada N minutos, barre
    # esto»**. Seis funciones estaban escritas, probadas y sin llamador: los
    # recordatorios vencidos no se emitían nunca, los informes programados no
    # salían, y tres tablas de estados caducados crecían sin techo.
    #
    # Los intervalos son ajustes y no constantes porque el ritmo que le conviene
    # a un despliegue de tres tenants no es el de uno de trescientos.
    tarea_recordatorios_intervalo_s: int = Field(60, ge=5, le=3_600)
    tarea_reverificaciones_intervalo_s: int = Field(3_600, ge=60, le=86_400)
    tarea_informes_intervalo_s: int = Field(300, ge=30, le=86_400)
    tarea_purgas_intervalo_s: int = Field(3_600, ge=60, le=86_400)

    # Y el interruptor de TODOS los relevos de tareas, no de uno. Encendido en
    # producción, que es donde las tareas tienen que correr.
    #
    # Existe por las pruebas, y no es una concesión: un relevo abre su propia
    # sesión cada segundo, y en una prueba esa sesión comparte la conexión con
    # la de la prueba. Sus `RELEASE SAVEPOINT` se cruzan con los de la
    # transacción del test y revientan la siguiente consulta con «savepoint
    # sa_savepoint_N does not exist» — en otra prueba, varios ficheros más
    # allá, que es lo que lo hacía parecer aleatorio.
    #
    # Lo mismo que ya se resolvió con `OUTBOX_ENABLED` para el relevo del
    # outbox. Aquello tapó una vía y dejó la otra abierta: hay SIETE sitios que
    # arrancan un `RelevoDeTareas`, y ninguno lo miraba.
    tareas_relevo_enabled: bool = True

    # ── El programador de integraciones ───────────────────────────────────
    #
    # Mismo agujero que arriba, un escalón más abajo: el conector declarativo
    # estaba completo y **solo lo disparaba una ruta a mano**. Una integración
    # que hay que ejecutar pulsando un botón no es una integración; es una
    # pantalla. Y por eso las decisiones que la gobiernan —cuándo avanzar la
    # marca, cómo reintentar, a qué ritmo traer la primera carga— estaban
    # escritas, probadas y sin que las llamara nadie.
    #
    # Cada cuánto MIRA el programador si hay algo que toca. Lo que decide si
    # toca es la cadencia de cada operación, que es configuración suya.
    tarea_integraciones_intervalo_s: int = Field(60, ge=5, le=3_600)
    # Suelo de la cadencia que puede declarar una operación. Existe porque el
    # proveedor de enfrente tiene cuota: una operación puesta «cada minuto»
    # contra una API que admite sesenta llamadas por hora bloquea la aplicación
    # entera —a todos los clientes, no solo al que se pasó—.
    integracion_cadencia_minima_minutos: int = Field(5, ge=1, le=1_440)
    # Cuántas operaciones ejecuta como mucho en una vuelta. Sin tope, un tenant
    # con doscientas vencidas a la vez monopoliza el relevo y los demás no
    # corren.
    integracion_max_por_vuelta: int = Field(20, ge=1, le=500)
    # Cuánto se guarda un registro recibido que ya se procesó. Lo que entra es
    # una copia de datos de un sistema ajeno: guardarla para siempre es
    # acumular datos personales de los que no somos responsables.
    integracion_registros_retencion_dias: int = Field(30, ge=1, le=3_650)
    # Qué operación declarada atiende un pedido que sale hacia el ERP. Es un
    # ajuste y no una constante porque la clave la pone quien declara la
    # conexión: en un cliente se llamará «pedido.crear» y en otro «sales_order».
    # Un nombre fijo en el código obligaría a que todos la llamaran igual, que
    # es pedirle al cliente que se adapte a nuestro vocabulario interno.
    integracion_operacion_pedidos: str = Field("pedido.crear", min_length=1, max_length=120)
