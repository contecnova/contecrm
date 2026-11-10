"""Ajustes propios del servicio de inteligencia.

Todos estos eran constantes de módulo, y todos son la misma clase de decisión:
**a partir de qué confianza nos fiamos de lo que dice un modelo**. Es justo lo
que cambia entre instalaciones y entre clientes de la misma instalación.

Un modelo de transcripción bueno en castellano peninsular no lo es con acento
chileno y ruido de taller; un cliente con poco volumen no puede esperar a tener
doscientos casos para entrenar; y en un sector regulado conviene exigir más
confianza antes de dejar que una extracción pise lo que escribió una persona.

Los valores por defecto están elegidos para **proponer mucho y decidir poco**:
una sugerencia que alguien descarta cuesta un clic, un dato que se mete solo y
está mal cuesta encontrarlo meses después.
"""

from __future__ import annotations

from functools import lru_cache

from crmcore.config import Settings
from crmcore.runtime.keys import ClaveAjuste, registrar_claves
from crmcore.runtime.settings import registrar_ajustes_servicio
from pydantic import Field, SecretStr


class AjustesIntelligence(Settings):
    """Configuración del servicio `intelligence`."""

    # ── Las credenciales de los proveedores ───────────────────────────────
    # `clave_del_proveedor=credencial,otra=otra`. Igual que `RUTAS_SERVICIOS`,
    # y por la misma razón: es un mapa de despliegue, no una lista en el código.
    #
    # **Vive en el `.env` y no en la base de datos** aunque el proveedor tenga
    # un `config` donde cabría. Un secreto guardado ahí se va con cada copia,
    # con cada volcado, con cada clonado a una demo y con cada exportación de
    # salida del tenant, y rotarlo obliga a repasar todos esos sitios. En el
    # fichero sólo está donde se despliega.
    #
    # Genérico a propósito: ni una variable por casa ni un `if` por proveedor.
    # Quien quiera añadir uno declara su dialecto, su dirección y su cabecera de
    # autenticación por la API, y pone aquí su credencial.
    ia_credenciales: SecretStr = SecretStr("")

    # ── Lo que hace falta para opinar ─────────────────────────────────────
    # Señales mínimas para dar una recomendación de siguiente mejor acción.
    # Con menos, la recomendación es el orden por defecto con otro nombre: no
    # se está recomendando nada, se está enseñando lo primero que había.
    ia_minimo_senales: int = Field(3, ge=1, le=50)

    # Caracteres mínimos de contexto para resumir o reescribir. Por debajo, el
    # modelo rellena con lo que le parece, que es exactamente lo que no se le
    # pide: resumir cuatro palabras es inventarse el resto.
    ia_minimo_contexto: int = Field(120, ge=1, le=10_000)

    # ── El índice de conocimiento (CRM-04.03.01.04, CRM-05.02.02.03) ──────
    # Dimensiones de los vectores que se piden al proveedor. Más da algo más de
    # precisión y ocupa más; cambiarlo obliga a reindexar, porque sólo se
    # comparan vectores del mismo modelo y tamaño.
    ia_dimensiones_vector: int = Field(768, ge=64, le=4_096)
    # Hasta cuántos caracteres de cada artículo o caso entran en su vector. Lo
    # que pasa de ahí no se encuentra, y el fragmento lo dice («recortado»).
    ia_caracteres_por_fragmento: int = Field(6_000, ge=200, le=100_000)
    # Cuántos resultados devuelve una búsqueda antes de filtrarlos.
    ia_resultados_indice: int = Field(10, ge=1, le=200)

    # ── Cuánta confianza basta ────────────────────────────────────────────
    # Para dar por buena una extracción de campos de un texto.
    ia_confianza_extraccion: float = Field(0.5, ge=0.0, le=1.0)
    # Para dar una transcripción por fiable. Más alto que la extracción porque
    # una palabra mal oída en una llamada se cita después como si se hubiera
    # dicho.
    ia_confianza_transcripcion: float = Field(0.75, ge=0.0, le=1.0)
    # Para actuar sobre lo que se ha entendido por voz.
    ia_confianza_voz: float = Field(0.7, ge=0.0, le=1.0)
    # Parecido mínimo para proponer un caso como «ya resuelto antes».
    ia_parecido_caso: float = Field(0.7, ge=0.0, le=1.0)

    # ── Cuánto se enseña ──────────────────────────────────────────────────
    # Casos parecidos que se sugieren. Más de un puñado no se miran.
    ia_casos_sugeridos: int = Field(5, ge=1, le=50)
    # Factores de una predicción que se enseñan. Una explicación con veinte
    # factores no explica nada: se lee la lista y se cierra.
    ia_factores_visibles: int = Field(5, ge=1, le=50)

    # ── Cuándo hay datos suficientes ──────────────────────────────────────
    # Casos mínimos para entrenar un clasificador, y por clase. Un modelo
    # entrenado con treinta casos acierta en los treinta y falla fuera.
    ia_minimo_casos_entreno: int = Field(200, ge=10, le=1_000_000)
    ia_minimo_por_clase: int = Field(30, ge=1, le=100_000)
    # Qué porcentaje se reserva para validar. Sin reservar nada, la precisión
    # que se mide es la de memorizar.
    ia_pct_validacion: int = Field(25, ge=5, le=50)

    # Envíos mínimos por rama para dar una prueba A/B por concluyente. 500 es
    # lo que hace falta para que una diferencia del 1 % no sea casualidad;
    # bajarlo produce ganadores que no ganan.
    ia_minimo_por_rama: int = Field(500, ge=1, le=1_000_000)

    # ── Cuánto se le deja contestar ───────────────────────────────────────
    # Tope de tokens de la respuesta. No es cosmético ni es el mismo caso que
    # los de arriba: la familia Anthropic **exige** `max_tokens` en cada
    # petición y la rechaza sin él, así que sin un valor aquí ese dialecto no
    # se puede usar. Cada proveedor puede poner el suyo en su `config`; esto es
    # lo que vale cuando no lo pone.
    #
    # Se lee en el puerto, que llama sin sesión de tenant, así que **no lleva
    # clave en caliente**: sale del `.env` y vale para todo el despliegue.
    ia_max_tokens_respuesta: int = Field(4096, ge=64, le=200_000)

    # Cuánto de un resultado se le enseña al agente iterativo en la vuelta
    # siguiente. Un listado de doscientas filas entra entero en la petición, y
    # en la quinta vuelta la petición es ese listado cinco veces: el bucle se
    # come el presupuesto antes de llegar al objetivo. Lo que pasa del tope se
    # recorta **diciéndolo**, para que el modelo no concluya que no había más.
    #
    # **Medido el 29-10-2026, y por eso sube de 2.000 a 20.000.** Una cuenta de
    # este producto ocupa **826 caracteres** —veintiocho campos— así que con el
    # tope anterior el agente veía DOS de sesenta y cinco. Y hacía lo correcto:
    # contestar que la lista venía cortada y que no podía concluir. Se reportó
    # como «Nexus no contesta a nada», y no era del modelo: era que no le
    # llegaban los datos.
    #
    # 20.000 son unas veinticuatro cuentas, que ya contesta una pregunta de
    # verdad, y veinte vueltas de ese tamaño siguen cabiendo de sobra en el
    # contexto de los modelos de hoy. Quien despliegue con uno pequeño lo baja:
    # para eso es un ajuste y no una constante.
    ia_caracteres_resultado_paso: int = Field(20_000, ge=200, le=200_000)

    # ── Modelos entrenados con el histórico del CRM (CRM-02.01.02.02, ─────
    # CRM-05.02.01.02, CRM-05.02.01.03, CRM-02.01.01.08)
    #
    # AUC mínimo, medido sobre el periodo apartado, para PUBLICAR un
    # clasificador. 0,5 es tirar una moneda; por debajo de esto el modelo se
    # guarda con sus métricas y no puntúa, y se dice.
    ia_auc_minimo_publicar: float = Field(0.6, ge=0.5, le=1.0)
    # Cuánto tiene que mejorar una regresión —importe, días hasta el cierre— al
    # «decir siempre la mediana» del entrenamiento, en % de error medio. Una
    # regresión que no le gana a la mediana es la mediana con decimales.
    ia_mejora_minima_regresion_pct: float = Field(5.0, ge=0.0, le=100.0)
    # Casos mínimos para una regresión (importe de lo ganado, días hasta el
    # cierre). Más bajo que el de un clasificador porque aquí no hay clases
    # que equilibrar; por debajo, el error medido depende de cuatro casos.
    ia_minimo_casos_regresion: int = Field(100, ge=10, le=1_000_000)
    # Cada cuántos días se reentrena un modelo programado.
    ia_reentreno_dias: int = Field(30, ge=1, le=365)
    # Cada cuánto mira el servicio si toca reentrenar alguno, en segundos.
    ia_reentreno_comprobar_s: int = Field(3600, ge=60, le=86_400)
    # Tope de registros que se leen del CRM para entrenar. Lo que pase se dice
    # («entrenado con los N más recientes»), no se recorta en silencio.
    ia_entreno_tope_registros: int = Field(20_000, ge=100, le=1_000_000)
    # Regularización de los modelos lineales. Sin ella, con pocas filas y una
    # categoría rara, un peso se dispara y la explicación dice que «ser de
    # Soria» vale más que todo lo demás junto.
    ia_regularizacion_l2: float = Field(1.0, ge=0.0, le=1_000.0)
    # Vueltas máximas del ajuste (Newton). Converge en menos de diez casi
    # siempre; el tope está para que un caso degenerado no se coma la CPU.
    ia_entreno_iteraciones: int = Field(25, ge=1, le=500)
    # Ventana de la propensión a compra: «compra en los próximos N días».
    ia_propension_horizonte_dias: int = Field(180, ge=7, le=1_095)
    # Categorías que se convierten en variable (origen, embudo…). Las demás
    # van juntas a «otros»: una categoría con tres casos no enseña nada y
    # dispara un peso.
    ia_categorias_maximas: int = Field(8, ge=1, le=50)
    # Casos mínimos de una categoría para que tenga variable propia.
    ia_minimo_por_categoria: int = Field(10, ge=1, le=10_000)
    # Cuántos días vale una predicción guardada antes de recalcularla.
    ia_prediccion_vigencia_dias: int = Field(7, ge=1, le=365)
    # Siguiente mejor oferta: cuentas con al menos dos productos que hacen
    # falta para recomendar por coocurrencia. Con menos, «los que compraron X
    # también compraron Y» es una anécdota.
    ia_nbo_minimo_cuentas: int = Field(10, ge=2, le=100_000)
    # Cuántas oportunidades ganadas se leen línea a línea para la siguiente
    # mejor oferta: son una llamada cada una.
    ia_nbo_tope_oportunidades: int = Field(2_000, ge=10, le=100_000)
    # Recomendaciones que se enseñan por cuenta.
    ia_nbo_recomendaciones: int = Field(3, ge=1, le=20)

    # ── Preguntas en lenguaje natural sobre los datos (CRM-05.02.02.04) ───
    # De qué servicios se ofrece el esquema al modelo. Sólo los que guardan
    # registros de negocio: las tablas de configuración no se preguntan así.
    ia_consulta_servicios: str = "sales,party,service,marketing"
    # Cuántos objetos se describen campo a campo en la petición al modelo: los
    # que más se parecen a la pregunta. Los demás van sólo por su nombre.
    ia_consulta_objetos_detallados: int = Field(4, ge=1, le=30)
    # Filas que se leen como mucho para contestar. Si hay más, la respuesta
    # se da sobre las leídas y se dice que es parcial.
    ia_consulta_tope_filas: int = Field(2_000, ge=50, le=100_000)
    # Filas de ejemplo que vuelven con la respuesta.
    ia_consulta_filas_devueltas: int = Field(50, ge=1, le=500)

    # ── El asistente con conocimiento y acciones (CRM-04.03.02.02) ────────
    # Fragmentos del índice que se le pasan al modelo por pregunta.
    ia_asistente_fragmentos: int = Field(5, ge=1, le=30)
    # Parecido mínimo de un fragmento para usarlo. Por debajo, se contesta
    # «no lo sé» antes de mandarle al modelo algo que no tiene que ver.
    ia_asistente_parecido_minimo: float = Field(0.3, ge=0.0, le=1.0)
    # Horas que vale una acción propuesta antes de poder confirmarla.
    ia_asistente_caducidad_horas: int = Field(24, ge=1, le=720)

    # ── Transcripción de llamadas y reuniones (CRM-01.02.01.05, .06) ──────
    # La conexión de `integration` que transcribe, y su operación. Vacía no
    # transcribe nada y lo dice: el proveedor es configuración (perfil sobre el
    # conector de la casa), no un módulo por casa.
    ia_transcripcion_conexion: str = ""
    ia_transcripcion_operacion: str = "transcribir"
    # Cómo le llega el audio al proveedor: un enlace firmado que descarga él, o
    # el contenido en base64 dentro de la petición. Lo decide el perfil.
    ia_transcripcion_envio: str = "enlace"
    # Tamaño máximo del audio que se acepta, en MB.
    ia_transcripcion_max_mb: int = Field(25, ge=1, le=500)
    # Caracteres de la transcripción que se mandan al modelo para resumir. Lo
    # que pasa de ahí no se resume, y el resumen lo dice.
    ia_transcripcion_caracteres_modelo: int = Field(60_000, ge=1_000, le=1_000_000)

    # ── Variantes de copy (CRM-02.04.01.04) ───────────────────────────────
    # Cuántas variantes se pueden pedir de una vez. Más de un puñado no se
    # revisan con cuidado, y revisar es lo que hace que esto valga.
    ia_variantes_maximas: int = Field(5, ge=1, le=20)

    # ── Evaluación de la IA contra el modelo real ─────────────────────────
    # Acierto mínimo por función. Por debajo, la ejecución lo marca y se avisa
    # por el sistema de avisos de la casa.
    ia_evaluacion_umbral: float = Field(0.9, ge=0.0, le=1.0)
    # Cada cuántas horas se pasa sola, por tenant. 0 la apaga.
    ia_evaluacion_cada_horas: int = Field(168, ge=0, le=8_760)
    # A quién más se avisa si baja (identificadores de usuario separados por
    # comas). Quien la pidió se avisa siempre.
    ia_evaluacion_avisar_a: str = ""
    # Cuántas ejecuciones se enseñan en la tendencia.
    ia_evaluacion_historial: int = Field(20, ge=2, le=200)
    # Cada cuánto mira el servicio a qué tenant le toca, en segundos.
    ia_evaluacion_comprobar_s: int = Field(3600, ge=60, le=86_400)
    # Cada cuánto se avanza una evaluación en curso, en segundos.
    ia_evaluacion_avance_s: int = Field(5, ge=1, le=3_600)
    # Casos por tanda: cada uno es una llamada al modelo de un par de segundos,
    # y la tanda corre dentro de la tarea de fondo del servicio.
    ia_evaluacion_casos_por_tanda: int = Field(4, ge=1, le=50)
    # Horas tras las que una ejecución que no terminó (el worker murió) deja de
    # bloquear la siguiente.
    ia_evaluacion_caducidad_horas: int = Field(6, ge=1, le=168)


# ── Cuáles se pueden afinar POR CLIENTE y cuáles no ───────────────────────
#
# Sólo llevan clave en caliente las que se leen donde hay sesión. Las demás
# —el parecido de un caso, la confianza de una transcripción o de la voz, los
# mínimos para entrenar y los envíos por rama de una prueba A/B— se calculan en
# funciones puras, sin base de datos: son cálculo, no consulta, y meterles una
# sesión para leer un número sería pagar una consulta por llamada.
#
# Ésas salen del `.env` y valen para todo el despliegue. **No se les declara
# clave a propósito**: un ajuste que la consola deja poner por tenant y que
# luego no se aplica es peor que no tenerlo — quien lo pone cree que ya está.
registrar_claves(
    [
        ClaveAjuste(
            clave="ia_minimo_senales",
            tipo="int",
            descripcion="Señales mínimas para dar una recomendación",
            minimo=1,
            maximo=50,
            campo_settings="ia_minimo_senales",
        ),
        ClaveAjuste(
            clave="ia_minimo_contexto",
            tipo="int",
            descripcion="Caracteres mínimos de contexto para resumir o reescribir",
            minimo=1,
            maximo=10_000,
            campo_settings="ia_minimo_contexto",
        ),
        ClaveAjuste(
            clave="ia_confianza_extraccion",
            tipo="float",
            descripcion="Confianza mínima para dar por buena una extracción",
            minimo=0.0,
            maximo=1.0,
            campo_settings="ia_confianza_extraccion",
        ),
        ClaveAjuste(
            clave="ia_factores_visibles",
            tipo="int",
            descripcion="Cuántos factores de una predicción se enseñan",
            minimo=1,
            maximo=50,
            campo_settings="ia_factores_visibles",
        ),
        # Los de los modelos entrenados con el histórico: se leen al entrenar
        # y al puntuar, que tienen sesión, así que sí se pueden afinar por
        # cliente desde la consola.
        ClaveAjuste(
            clave="ia_auc_minimo_publicar",
            tipo="float",
            descripcion="AUC mínimo, medido en el periodo apartado, para publicar un clasificador",
            minimo=0.5,
            maximo=1.0,
            campo_settings="ia_auc_minimo_publicar",
        ),
        ClaveAjuste(
            clave="ia_mejora_minima_regresion_pct",
            tipo="float",
            descripcion="Cuánto tiene que mejorar una regresión a «decir siempre la mediana» (%)",
            minimo=0.0,
            maximo=100.0,
            campo_settings="ia_mejora_minima_regresion_pct",
        ),
        ClaveAjuste(
            clave="ia_reentreno_dias",
            tipo="int",
            descripcion="Cada cuántos días se reentrena un modelo programado",
            minimo=1,
            maximo=365,
            campo_settings="ia_reentreno_dias",
        ),
        ClaveAjuste(
            clave="ia_propension_horizonte_dias",
            tipo="int",
            descripcion="Ventana de la propensión a compra, en días",
            minimo=7,
            maximo=1_095,
            campo_settings="ia_propension_horizonte_dias",
        ),
        ClaveAjuste(
            clave="ia_prediccion_vigencia_dias",
            tipo="int",
            descripcion="Días que vale una predicción guardada antes de recalcularla",
            minimo=1,
            maximo=365,
            campo_settings="ia_prediccion_vigencia_dias",
        ),
        ClaveAjuste(
            clave="ia_nbo_minimo_cuentas",
            tipo="int",
            descripcion="Cuentas con dos o más productos necesarias para la siguiente mejor oferta",
            minimo=2,
            maximo=100_000,
            campo_settings="ia_nbo_minimo_cuentas",
        ),
        ClaveAjuste(
            clave="ia_consulta_tope_filas",
            tipo="int",
            descripcion="Filas que se leen como mucho al contestar una pregunta sobre los datos",
            minimo=50,
            maximo=100_000,
            campo_settings="ia_consulta_tope_filas",
        ),
        ClaveAjuste(
            clave="ia_transcripcion_conexion",
            tipo="str",
            descripcion="Conexión de integración que transcribe audio (su id)",
            campo_settings="ia_transcripcion_conexion",
        ),
        ClaveAjuste(
            clave="ia_transcripcion_operacion",
            tipo="str",
            descripcion="Operación de esa conexión que transcribe",
            campo_settings="ia_transcripcion_operacion",
        ),
        ClaveAjuste(
            clave="ia_transcripcion_envio",
            tipo="str",
            descripcion="Cómo le llega el audio al proveedor de transcripción",
            opciones=("enlace", "contenido"),
            campo_settings="ia_transcripcion_envio",
        ),
        ClaveAjuste(
            clave="ia_transcripcion_max_mb",
            tipo="int",
            descripcion="Tamaño máximo del audio que se transcribe (MB)",
            minimo=1,
            maximo=500,
            campo_settings="ia_transcripcion_max_mb",
        ),
        ClaveAjuste(
            clave="ia_transcripcion_caracteres_modelo",
            tipo="int",
            descripcion="Caracteres de la transcripción que se mandan al modelo para resumir",
            minimo=1_000,
            maximo=1_000_000,
            campo_settings="ia_transcripcion_caracteres_modelo",
        ),
        ClaveAjuste(
            clave="ia_variantes_maximas",
            tipo="int",
            descripcion="Variantes de copy que se pueden pedir de una vez",
            minimo=1,
            maximo=20,
            campo_settings="ia_variantes_maximas",
        ),
        ClaveAjuste(
            clave="ia_evaluacion_umbral",
            tipo="float",
            descripcion="Acierto mínimo por función en la evaluación de la IA; por debajo se avisa",
            minimo=0.0,
            maximo=1.0,
            campo_settings="ia_evaluacion_umbral",
        ),
        ClaveAjuste(
            clave="ia_evaluacion_cada_horas",
            tipo="int",
            descripcion="Cada cuántas horas se evalúa la IA sola (0 la apaga)",
            minimo=0,
            maximo=8_760,
            campo_settings="ia_evaluacion_cada_horas",
        ),
        ClaveAjuste(
            clave="ia_evaluacion_avisar_a",
            tipo="str",
            descripcion="Usuarios (ids separados por comas) a los que se avisa si la IA baja del umbral",
            campo_settings="ia_evaluacion_avisar_a",
        ),
        ClaveAjuste(
            clave="ia_evaluacion_historial",
            tipo="int",
            descripcion="Evaluaciones de la IA que se enseñan en la tendencia",
            minimo=2,
            maximo=200,
            campo_settings="ia_evaluacion_historial",
        ),
        ClaveAjuste(
            clave="ia_evaluacion_casos_por_tanda",
            tipo="int",
            descripcion="Casos de la evaluación de la IA que se pasan en cada tanda",
            minimo=1,
            maximo=50,
            campo_settings="ia_evaluacion_casos_por_tanda",
        ),
        ClaveAjuste(
            clave="ia_evaluacion_caducidad_horas",
            tipo="int",
            descripcion="Horas tras las que una evaluación de la IA sin terminar deja de bloquear",
            minimo=1,
            maximo=168,
            campo_settings="ia_evaluacion_caducidad_horas",
        ),
        ClaveAjuste(
            clave="ia_asistente_parecido_minimo",
            tipo="float",
            descripcion="Parecido mínimo de un fragmento del conocimiento para usarlo",
            minimo=0.0,
            maximo=1.0,
            campo_settings="ia_asistente_parecido_minimo",
        ),
    ]
)


def credencial_de(clave_proveedor: str) -> str:
    """La credencial de ese proveedor, del `.env`. Cadena vacía si no la hay.

    Vacía y no un error: hay proveedores que no llevan credencial —uno propio
    en la red interna, por ejemplo— y hacer obligatorio lo que no lo es obliga
    a inventarse un valor. Si hace falta y no está, quien se queja es el
    proveedor, con su propio 401, que dice más que un error nuestro adivinando.
    """
    crudo = ajustes().ia_credenciales.get_secret_value()
    for trozo in crudo.replace("\n", "").split(","):
        if "=" not in trozo:
            continue
        nombre, _, valor = trozo.partition("=")
        if nombre.strip() == clave_proveedor:
            return valor.strip()
    return ""


@lru_cache(maxsize=1)
def ajustes() -> AjustesIntelligence:
    return AjustesIntelligence()


registrar_ajustes_servicio(ajustes)
