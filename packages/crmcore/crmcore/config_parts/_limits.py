"""Límites, cuotas y resiliencia: lo que impide que un tenant tumbe a los demás."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class _LimitsSettings(BaseSettings):
    # ── Topes del núcleo que estaban escritos en el código ────────────────
    #
    # Veinticinco constantes de módulo repartidas por `crmcore`. Son todas
    # operativas —profundidades, colas, ventanas, tamaños—, no decisiones de
    # negocio, así que van al `.env` y valen para todo el despliegue: una
    # profundidad de jerarquía o un tamaño de cola no significan nada «por
    # cliente», y declararlas por tenant crearía ajustes que no se aplican.
    #
    # Lo que SÍ cambia entre despliegues: una instalación con mil usuarios y
    # un bus modesto no quiere los mismos topes que una con cincuenta mil.

    # Profundidad máxima de una jerarquía de usuarios al resolver quién ve qué.
    # No es un gusto: es la barrera contra un ciclo —A manda a B y B a A— que
    # colgaría la resolución de permisos.
    jerarquia_profundidad_maxima: int = Field(12, ge=1, le=100)
    # Lo mismo para el árbol de carpetas documentales.
    carpeta_profundidad_maxima: int = Field(8, ge=1, le=50)
    # Y para el árbol de una fórmula de campo calculado. Un tope bajo evita que
    # una fórmula pegada desde una hoja de cálculo tumbe el servicio.
    formula_max_nodos: int = Field(200, ge=1, le=10_000)

    # Cada cuánto el consumidor del bus reclama los mensajes que otro dejó a
    # medias, y a partir de cuánta inactividad se consideran abandonados.
    bus_reclamo_cada_s: float = Field(30.0, ge=1.0, le=3600.0)
    bus_reclamo_inactivo_ms: int = Field(60_000, ge=1_000, le=3_600_000)

    # Cuándo se declara que la cola está caída, y cuántos minutos sin latido
    # del relevo bastan para decir que está parado.
    cola_caida_desde: int = Field(5_000, ge=1, le=10_000_000)
    relevo_parado_min: int = Field(15, ge=1, le=1_440)

    # Cuántos errores se devuelven de una operación masiva, y cuántos se
    # guardan. Devolver todos convierte la respuesta en un volcado que nadie
    # lee; guardar todos llena la tabla con el primer fichero mal formado.
    masivas_errores_devueltos: int = Field(200, ge=1, le=100_000)
    trabajos_errores_guardados: int = Field(500, ge=1, le=100_000)

    # Meses que se quedan en la partición caliente antes de archivar.
    particion_meses_en_caliente: int = Field(13, ge=1, le=120)
    # Cada cuánto hay que probar que una copia de seguridad se restaura. Una
    # copia que nunca se ha restaurado no es una copia: es una esperanza.
    recuperacion_dias_entre_pruebas: int = Field(90, ge=1, le=3650)

    # Margen con el que se renueva una credencial antes de que caduque.
    credencial_margen_s: float = Field(30.0, ge=1.0, le=3600.0)

    # Qué hace falta para que una firma manuscrita cuente como firma y no como
    # un toque accidental en la pantalla.
    firma_duracion_minima_ms: int = Field(300, ge=1, le=60_000)
    firma_puntos_minimos: int = Field(12, ge=2, le=10_000)

    # Ventana de validez de la firma interna entre servicios. Corta a
    # propósito: es lo que acota una petición robada en tránsito.
    firma_interna_ventana_s: int = Field(30, ge=1, le=3600)

    # Cuánto cuerpo de petición se guarda en el registro. Guardar todo es
    # guardar datos personales en los logs sin retención.
    log_tope_cuerpo: int = Field(4096, ge=0, le=1_048_576)

    # Cuánto vale una reverificación de segundo factor antes de volver a
    # pedirla.
    reverificacion_validez_min: int = Field(15, ge=1, le=1_440)

    # Con cuántos días de antelación se avisa de que la cola del móvil lleva
    # sin sincronizar.
    movil_dias_aviso_cola: int = Field(7, ge=1, le=365)

    # Cuántas muestras de consulta lenta se guardan para el análisis.
    obs_max_muestras: int = Field(30, ge=1, le=10_000)

    # El control de presión: desde qué ocupación del pool se empieza a frenar,
    # cuánta cola por worker se tolera y cuánto se puede bajar de golpe.
    # Bajar demasiado de una vez produce un vaivén peor que la congestión.
    presion_pool_desde: float = Field(0.70, ge=0.0, le=1.0)
    presion_cola_por_worker: int = Field(200, ge=1, le=100_000)
    presion_bajada_maxima: float = Field(0.15, ge=0.0, le=1.0)

    # Cuánto se cachean los ajustes en caliente. Va aquí y no como ajuste en
    # caliente a propósito: leerlo de la base sería preguntarle a la caché
    # cuánto dura la caché.
    ajustes_ttl_cache_s: float = Field(30.0, ge=0.0, le=3600.0)

    # ── Los últimos que vivían en el código ───────────────────────────────
    # Filas a partir de las cuales un cambio de entorno se trata como masivo y
    # pide confirmación aparte.
    cambio_umbral_masivo: int = Field(500, ge=1, le=10_000_000)
    # Entregas fallidas seguidas tras las que se desactiva un webhook. Alto a
    # propósito: desactivarlo a la tercera deja al integrador sin eventos por
    # un corte de diez minutos.
    webhook_fallos_para_desactivar: int = Field(20, ge=1, le=10_000)
    # Cuántas veces por encima de lo normal cuenta como anomalía de tráfico, y
    # cuántos minutos se frena a quien la provoca.
    anomalia_factor: float = Field(3.0, ge=1.0, le=1_000.0)
    anomalia_minutos_freno: int = Field(5, ge=1, le=1_440)
    # Cuánto se cachean las claves de API en el gateway.
    claves_ttl_cache_s: float = Field(30.0, ge=0.0, le=3600.0)
    # Coste máximo de una consulta a la superficie, y días que vive un sandbox.
    superficie_coste_maximo: int = Field(50, ge=1, le=100_000)
    sandbox_dias: int = Field(30, ge=1, le=3650)
    # Dígitos mínimos para dar un teléfono por marcable.
    telefono_minimo_digitos: int = Field(7, ge=1, le=30)
    # Antelación del aviso de caducidad de un activo de marketing y de un
    # acuerdo comercial con proveedor.
    activo_dias_preaviso: int = Field(30, ge=1, le=365)
    acuerdo_dias_preaviso: int = Field(30, ge=1, le=365)
    # Rebotes blandos seguidos tras los que se suprime una dirección. Un rebote
    # blando es temporal —buzón lleno—; cinco seguidos ya no lo son.
    rebotes_blandos_para_suprimir: int = Field(5, ge=1, le=1_000)
    # Interacciones mínimas para decir a qué hora conviene escribir a alguien.
    # Con menos, lo que sale es la hora a la que se mandó el último correo.
    momento_minimo_interacciones: int = Field(8, ge=1, le=10_000)
    # Profundidad máxima de un segmento anidado.
    segmento_profundidad_maxima: int = Field(7, ge=1, le=50)
    # A partir de cuántos campos por sección el diseñador avisa de que la
    # pantalla va a ser ilegible.
    disenador_aviso_campos: int = Field(15, ge=1, le=200)
    # Caracteres mínimos de una descripción semántica para que sirva de algo.
    semantica_minimo_descripcion: int = Field(25, ge=1, le=10_000)
    # Minutos que un worker bloquea un trabajo, y cuántos coge de una vez.
    worker_bloqueo_min: int = Field(5, ge=1, le=1_440)
    worker_lote: int = Field(20, ge=1, le=10_000)
    # Candidatos que se reverifican de una tacada.
    reverificacion_tope: int = Field(50, ge=1, le=100_000)
    # Días sin tocar un plan conjunto tras los que se avisa.
    plan_dias_sin_tocar: int = Field(21, ge=1, le=3650)
    # Duración mínima de una cadencia, en días.
    cadencia_minimo_dias: int = Field(30, ge=1, le=3650)
    # Abandono máximo tolerado en el marcador, en porcentaje. Lo fija la ley en
    # varios países; por eso se puede ajustar pero no quitar.
    marcador_abandono_maximo_pct: float = Field(3.0, ge=0.0, le=100.0)
    # Puntuación a partir de la cual un riesgo de GRC es alto.
    grc_umbral_riesgo_alto: int = Field(12, ge=1, le=1_000)
    # Intentos de sincronización de la suite antes de rendirse.
    suite_max_intentos: int = Field(5, ge=1, le=1_000)
    # Similitud por defecto para encolar un duplicado cuando el tenant no la
    # ha fijado.
    duplicados_umbral_defecto: float = Field(0.72, ge=0.0, le=1.0)
    # Puntuación a partir de la cual se PROPONE una fusión de identidades y a
    # partir de la cual se ejecuta sola. La segunda es destructiva, y por eso
    # está muy por encima: por debajo decide una persona.
    identidad_umbral_propuesta: int = Field(80, ge=1, le=10_000)
    identidad_umbral_automatico: int = Field(150, ge=1, le=10_000)

    # ── Analítica ─────────────────────────────────────────────────────────
    # Filas por vuelta del cargador y vueltas máximas. El producto de los dos
    # es el techo de una carga: subir el primero va más rápido y ocupa más
    # memoria; subir el segundo alarga la carga sin ocupar más.
    carga_filas_por_vuelta: int = Field(200, ge=1, le=100_000)
    carga_vueltas_maximas: int = Field(50, ge=1, le=100_000)
    # Margen con el que se renueva la credencial del almacén analítico.
    analitica_margen_credencial_s: float = Field(30.0, ge=1.0, le=3600.0)
    # Personas mínimas para enseñar una cohorte. Por debajo, el dato agregado
    # deja de ser agregado: con dos personas, «el 50 % se dio de baja» es «una».
    cohorte_minimo: int = Field(5, ge=1, le=10_000)
    # Cuánto se espera a que una fuente externa devuelva una muestra.
    fuente_plazo_muestra_s: float = Field(15.0, ge=0.1, le=600.0)
    # Techo de filas de un informe y de una métrica. Una consulta sin techo
    # tumba el almacén y de paso el panel de quien la lanzó.
    informe_tope_filas: int = Field(50_000, ge=1, le=10_000_000)
    metrica_tope_filas: int = Field(5_000, ge=1, le=10_000_000)

    # Fallos seguidos tras los que una tarea de fondo se declara averiada.
    tarea_fallos_para_averia: int = Field(3, ge=1, le=1_000)

    # ── Rate limiting (CRM-00.01.06.01) ───────────────────────────────────
    rate_limit_enabled: bool = True
    # Ventana de conteo. Una ventana corta reacciona antes a una ráfaga; una
    # larga tolera mejor el tráfico a golpes de un proceso por lotes.
    rate_limit_ventana_s: int = Field(60, ge=1, le=3600)
    # Topes por dimensión. Se aplican TODOS: el más restrictivo manda. Están
    # separados porque el abuso tiene formas distintas — un usuario con un
    # bucle, una integración mal configurada, un tenant entero desbocado.
    rate_limit_por_usuario: int = Field(600, ge=0, le=1_000_000)
    rate_limit_por_api_key: int = Field(3_000, ge=0, le=1_000_000)
    rate_limit_por_tenant: int = Field(6_000, ge=0, le=10_000_000)
    rate_limit_por_ip: int = Field(1_200, ge=0, le=1_000_000)

    # ── Tamaños de petición y respuesta ───────────────────────────────────
    max_body_mb: int = Field(25, ge=1, le=1024)
    # Tope de elementos en una operación masiva (CRM-00.02.01.11). Por encima,
    # la API obliga a usar el camino asíncrono con job id, que es el que tiene
    # progreso, reanudación e informe parcial.
    bulk_max_items: int = Field(1_000, ge=1, le=100_000)
    # Tope de operaciones en una petición compuesta (CRM-00.02.01.13).
    # Más que eso es una carga masiva, y para eso está el camino masivo con su
    # trabajo diferido y su informe parcial.
    #
    # (30-09-2026: el valor por defecto pasa de 25 a 20, que es el que la API
    # aplicaba de verdad —`compuesto.py` llevaba un 20 escrito mientras este
    # ajuste decía 25 y no lo leía nadie—. Quien lo tenga puesto en su `.env`
    # sigue mandando: ahora, por fin, de verdad.)
    composite_max_ops: int = Field(20, ge=1, le=500)

    # Página máxima que se puede pedir. Sin tope, un `limit=1000000` es una
    # denegación de servicio escrita por el propio cliente sin querer.
    page_max_size: int = Field(200, ge=1, le=10_000)
    page_default_size: int = Field(50, ge=1, le=1_000)

    # ── Trabajos asíncronos (CRM-00.02.01.12) ─────────────────────────────
    # Elementos que admite una operación masiva por el camino diferido. Es dos
    # órdenes de magnitud más que el síncrono porque aquí no hay nadie
    # esperando: el límite ya no es la paciencia de un navegador, sino lo que
    # cabe razonablemente en el JSONB de una fila.
    trabajo_max_items: int = Field(100_000, ge=1, le=5_000_000)
    # Elementos que procesa un worker entre commit y commit. Es la unidad de
    # reanudación: una tanda grande amortiza el viaje a la base, y una pequeña
    # pierde menos trabajo cuando el proceso muere a mitad.
    trabajo_tanda: int = Field(200, ge=1, le=10_000)
    # Trabajos que un worker se lleva por vuelta.
    trabajo_lote: int = Field(5, ge=1, le=100)
    # Cuánto retiene un worker un trabajo antes de que otro pueda recuperarlo.
    # Se renueva en cada tanda, así que basta con que supere lo que tarda UNA
    # tanda, no el trabajo entero.
    trabajo_bloqueo_min: int = Field(5, ge=1, le=120)
    # Cuánto se conserva un trabajo terminado. Guarda la entrada completa, que
    # en una importación son los datos que subió el cliente: conservarla «por si
    # acaso» pasado el plazo es justo lo que el plazo impide.
    trabajo_retencion_h: int = Field(72, ge=1, le=8_760)
    # Espera del worker cuando no hay nada que hacer. Es la latencia máxima
    # entre aceptar un trabajo y empezarlo.
    trabajo_espera_vacio_s: float = Field(2.0, ge=0.1, le=60.0)

    # ── Tiempos ───────────────────────────────────────────────────────────
    # Timeout de una llamada entre servicios. Corto: encadenar tres llamadas
    # con timeouts largos convierte un servicio lento en una caída general.
    http_interno_timeout_s: float = Field(10.0, ge=0.5, le=300.0)
    # Timeout de una llamada a un sistema externo (ERP, firma, telefonía).
    # Más largo porque no controlamos su latencia, pero acotado igual.
    http_externo_timeout_s: float = Field(30.0, ge=1.0, le=600.0)
    # Una petición que pasa de aquí se corta y devuelve 504. Existe para que
    # una consulta patológica no retenga una conexión del pool indefinidamente.
    request_timeout_s: float = Field(60.0, ge=1.0, le=900.0)

    # ── Circuit breaker (CRM-00.01.06.03) ─────────────────────────────────
    circuit_breaker_enabled: bool = True
    # Fallos consecutivos que abren el circuito.
    cb_umbral_fallos: int = Field(5, ge=1, le=1000)
    # Tiempo que permanece abierto antes de dejar pasar una petición de prueba.
    cb_reposo_s: int = Field(30, ge=1, le=3600)

    # ── Degradación bajo carga (CRM-00.01.06.04) ──────────────────────────
    degradacion_enabled: bool = True
    # Presión (0..1) a partir de la cual se difiere lo no crítico: recálculos,
    # enriquecimientos, informes programados. Se difiere, no se pierde.
    #
    # El nombre dice «pool» porque el pool de conexiones era la única señal
    # cuando se declaró, y sigue siendo la que avisa antes. Hoy la presión las
    # combina —pool, latencia y cola— y este umbral gobierna la combinada. Se
    # mantiene el nombre para no romper el `.env` de quien ya lo tenga puesto.
    #
    # (30-09-2026: el valor por defecto pasa de 0.85 a 0.6, que es el que el
    # sistema aplicaba de verdad —`admite()` llevaba un 0.6 escrito mientras
    # este ajuste decía 0.85 y no lo leía nadie—. Poner 0.85 al enchufarlo habría
    # hecho que empezara a diferir más tarde que hasta ahora.)
    degradacion_umbral_pool: float = Field(0.6, ge=0.1, le=1.0)
    # Y el de lo NORMAL, que es más alto: una escritura que alguien está
    # haciendo delante de la pantalla solo se corta cuando ya no hay más
    # remedio. Estaba escrito en el código —un 0.9— junto al otro; los dos
    # umbrales deciden lo mismo y tenían dos vidas distintas, una configurable
    # que no se leía y otra escrita que sí.
    degradacion_umbral_normal: float = Field(0.9, ge=0.1, le=1.0)

    # ── Motor de procesos (CRM-00.03.02.16) ───────────────────────────────
    # Topes que impiden un proceso desbocado. Sin ellos, una automatización que
    # se dispara a sí misma consume el sistema entero.
    proceso_max_pasos: int = Field(1_000, ge=1, le=1_000_000)
    proceso_max_profundidad: int = Field(10, ge=1, le=100)
    proceso_max_duracion_h: int = Field(720, ge=1, le=8760)
    # Cadena máxima de automatizaciones que se disparan unas a otras
    # (CRM-00.03.03.06).
    automatizacion_max_cascada: int = Field(5, ge=1, le=100)

    # ── Colaboración (CRM-06.02.01.01) ────────────────────────────────────
    # Longitud máxima de un comentario. 10.000 caracteres son unas tres páginas:
    # de sobra para explicar un caso, y un tope que impide que alguien pegue un
    # contrato entero en una nota y lo convierta en la fila más pesada de la
    # tabla.
    comentario_max_caracteres: int = Field(10_000, ge=100, le=1_000_000)
    # Menciones por comentario. Sin tope, un solo comentario puede generar un
    # aviso para toda la empresa.
    comentario_max_menciones: int = Field(20, ge=1, le=500)

    # ── Caché (CRM-00.01.01.07) ───────────────────────────────────────────
    # `memoria` o `redis`. En memoria vale para desarrollo y para las pruebas;
    # con más de una réplica deja de valer, porque cada proceso tendría la suya
    # y una purga en uno no alcanzaría a los demás. El arranque avisa.
    cache_backend: str = Field("memoria", pattern="^(memoria|redis)$")
    cache_url: str = ""
    # TTL por defecto de una entrada. Cinco minutos: suficiente para absorber la
    # ráfaga de una pantalla que pide lo mismo diez veces, y lo bastante corto
    # para que un dato cambiado desde otra vía no se quede pegado.
    cache_ttl_s: int = Field(300, ge=1, le=86_400)
    # Tope duro. Una entrada con un TTL enorme mantiene ocupada la memoria de lo
    # ya invalidado por una purga, que no borra: hace inalcanzable.
    cache_ttl_max_s: int = Field(3_600, ge=1, le=604_800)
    # Segundos que cada proceso recuerda la generación de un tenant sin volver a
    # preguntarla. Durante esa ventana una réplica puede seguir sirviendo lo
    # purgado: es el precio explícito de no pagar un viaje de red por lectura.
    cache_ttl_generacion_s: int = Field(5, ge=0, le=300)

    # ── Búsqueda (CRM-00.01.01.09) ────────────────────────────────────────
    # Configuración de texto de Postgres, que decide cómo se derivan las
    # palabras. Con la equivocada, «facturas» no encuentra «factura» y la
    # búsqueda parece rota sin que nada falle. Va por tenant porque un cliente
    # portugués no busca igual que uno español.
    busqueda_idioma: str = "spanish"
    # Resultados por consulta. Más de una pantalla no se mira, y pedir mil
    # obliga a Postgres a ordenar mil por relevancia para tirar novecientos.
    busqueda_max_resultados: int = Field(20, ge=1, le=200)

    # ── Máquinas de estado (CRM-00.04.01.07) ──────────────────────────────
    # Transiciones que este tenant QUITA de las que el código admite. Solo
    # quita: añadir un estado que el código no conoce dejaría el registro en un
    # limbo que ningún `if` sabe manejar.
    #
    #     {"oportunidad": {"perdida": ["abierta"]}}
    #
    # significa «aquí una oportunidad perdida no se reabre». Vacío por defecto:
    # el producto no decide por el cliente qué procesos son válidos en su casa.
    transiciones_prohibidas: dict[str, dict[str, list[str]]] = Field(default_factory=dict)

    # ── Control de flujo en automatizaciones (CRM-00.03.03.04) ────────────
    # Vueltas máximas de un `para_cada`. Una automatización que recorre una
    # colección no puede colgar la petición que la disparó: guardar una
    # oportunidad con seiscientas líneas dispararía seiscientas acciones y el
    # usuario vería un formulario congelado sin saber por qué.
    #
    # Cuando se corta se DICE en la traza: una iteración que se queda a medias
    # en silencio es peor que no tenerla, porque el resultado parcial parece
    # completo.
    automatizacion_max_vueltas: int = Field(200, ge=1, le=10_000)
    # Anidamiento máximo de ramas y bucles. Tres niveles cubren todo lo que
    # alguien construye en una interfaz; más que eso es un proceso, y para eso
    # está el motor de procesos, que sabe reanudar y compensar.
    automatizacion_max_anidamiento: int = Field(3, ge=1, le=10)

    # ── Gobierno del esquema (CRM-00.04.01.09) ────────────────────────────
    # Campos activos por objeto. Ciento cincuenta es mucho más de lo que
    # necesita cualquier objeto bien modelado y bastante menos de donde empieza
    # a doler: a partir de doscientos, la ficha, el listado, la exportación y
    # las migraciones se degradan a la vez.
    #
    # El techo no está para fastidiar: está para que la conversación ocurra
    # antes de que el sistema vaya mal, y no después.
    metadata_max_campos: int = Field(150, ge=10, le=1_000)
    # Desde qué porcentaje se avisa. Al 80 % queda margen para replantear el
    # modelo; al 100 % el aviso llega cuando ya no se puede añadir nada.
    metadata_aviso_pct: int = Field(80, ge=10, le=100)

    # ── Plazos de negocio que estaban escritos en el código ───────────────
    #
    # Los cuatro se leían con `rt.efectivo(...) or <número>` y su clave no
    # estaba declarada en ninguna parte: leerla devolvía `None`, así que
    # mandaba el número de al lado, y fijarla se rechazaba. El valor por
    # defecto de cada uno es EXACTAMENTE el que usaba el código, para que
    # enchufar la configuración no cambie ningún comportamiento.
    devolucion_ventana_dias: int = Field(30, ge=1, le=3_650)
    expediente_plazo_dias: int = Field(30, ge=1, le=3_650)
    telemetria_silencio_min: int = Field(120, ge=1, le=10_080)
    # Guardar el cuerpo de lo que entra por los canales. Apagado: es dato
    # personal, y acumularlo sin finalidad declarada no se defiende.
    canal_guardar_contenido: bool = False
    # 0 = sin tope, que es lo que había.
    licencias_maximas: int = Field(0, ge=0, le=1_000_000)

    # ── Casos (CRM-04.01.01.10) ───────────────────────────────────────────
    # Días durante los que un caso cerrado se puede reabrir. Pasado el plazo se
    # abre uno nuevo enlazado: reabrir un caso de hace ocho meses falsea todos
    # los indicadores del periodo en que se cerró, y esos números ya están en un
    # informe que alguien miró. 0 = sin límite, que se desaconseja.
    caso_reapertura_dias: int = Field(30, ge=0, le=3650)

    # ── Servicio de campo (CRM-04.04.01) ──────────────────────────────────
    # Velocidad media con la que se estima el tiempo de viaje entre visitas. Es
    # un ajuste porque en ciudad son 20 y en carretera comarcal 70, y una
    # constante haría que la jornada de un equipo cupiera y la del otro no.
    campo_velocidad_media_kmh: int = Field(35, ge=5, le=130)
    # Con cuánta antelación se avisa de una garantía que vence. Es la lista con
    # la que se vende la extensión, y sobre todo la que evita la llamada en la
    # que se descubre que venció hace un mes.
    garantia_preaviso_dias: int = Field(90, ge=1, le=730)

    # ── Transporte gRPC (CRM-00.02.01.03) ─────────────────────────────────
    # Si se levanta el puerto gRPC. Apagado por defecto: una superficie abierta
    # que nadie usa es una superficie que nadie mira.
    grpc_activo: bool = False
    grpc_direccion: str = "0.0.0.0:50051"
    # Tamaño máximo de mensaje. El de gRPC por defecto son 4 MiB, y subirlo sin
    # pensarlo convierte un `List` mal filtrado en una respuesta que no cabe en
    # la memoria de nadie.
    grpc_mensaje_max_bytes: int = Field(4 * 1024 * 1024, ge=64 * 1024, le=256 * 1024 * 1024)
    # Elementos y segundos que aguanta un flujo abierto. Un `Watch` retiene una
    # conexión mientras dura: sin tope, el cliente que lo abre y se va de
    # vacaciones deja esa conexión ocupada hasta que alguien mira por qué el
    # pool está lleno.
    grpc_elementos_por_flujo: int = Field(10_000, ge=1, le=10_000_000)
    grpc_segundos_por_flujo: int = Field(300, ge=5, le=86_400)

    # ── Retención para el ETag (CRM-00.02.01.09) ──────────────────────────
    # Cuánto cuerpo se guarda en memoria antes de mandarlo, para poder sacarle
    # la versión y añadir el `ETag`. Pasado el tope se suelta lo que haya y el
    # resto va directo, sin cabecera: una exportación de cien megas no vale una
    # cabecera de treinta bytes, y multiplicada por las peticiones a la vez es
    # la memoria del servicio.
    #
    # 2 MiB cubre de sobra cualquier respuesta de objeto o listado paginado,
    # que es donde el ETag sirve para algo.
    etag_retencion_max_bytes: int = Field(2 * 1024 * 1024, ge=64 * 1024, le=64 * 1024 * 1024)

    # ── Cuotas por módulo (CRM-00.01.06.02) ───────────────────────────────
    #
    # Todas abren por omisión: **0 es sin límite**, y es el valor por defecto a
    # propósito. Un despliegue que no ha configurado cuotas no puede quedarse sin
    # poder trabajar porque a alguien se le olvidara declararlas, y un fallo al
    # declarar una ruta tiene que dejar pasar de más, nunca cortar de menos.
    #
    # Van por módulo y no en un tope global: así el alta no depende de una
    # lectura entre servicios y, sobre todo, **el mensaje puede decir qué se ha
    # agotado**. «Has llegado al límite» no dice si sobran contactos o correos.
    cuota_correos_mes: int = Field(0, ge=0, le=100_000_000)
    cuota_sms_mes: int = Field(0, ge=0, le=100_000_000)
    cuota_workflows_mes: int = Field(0, ge=0, le=100_000_000)
    cuota_registros: int = Field(0, ge=0, le=1_000_000_000)
