/**
 * Los textos de las pantallas que se cargan cuando se abren.
 *
 * **Por qué están aparte.** El diccionario entero viajaba en el paquete de
 * entrada —el que el navegador descarga antes de pintar nada—, porque hace
 * falta para dibujar la pantalla de acceso. Eran 13,1 kB comprimidos de los
 * 93 del arranque, y el propio gate del presupuesto llevaba dos subidas de
 * tope diciendo que la forma correcta de quitarlo era ésta y no recortar
 * funcionalidad.
 *
 * Aquí están las diecisiete secciones que **sólo** usan pantallas diferidas:
 * medido fichero a fichero, no elegido a ojo. Las del marco, la entrada y las
 * pantallas que van de una pieza —inicio, módulos, fichas, puesto, casos— se
 * quedan en `es.ts`, porque si llegaran tarde se vería la clave en crudo.
 *
 * **Y se cargan ANTES que la pantalla, no a la vez.** Cada página diferida
 * espera este diccionario dentro de su propio `lazy`, así que no hay instante
 * en que una pantalla exista sin sus textos. Cargarlo en paralelo habría
 * dejado una ventana de milisegundos con `plataforma.titulo` escrito en la
 * cabecera.
 */

const pantallas = {
  // La telefonía conectada y sus llamadas (CRM-04.02.01.05, CRM-03.03.01.05).
  telefonia: {
    titulo: "Telefonía",
    entradilla:
      "La centralita del tenant, conectada sobre una conexión de Integraciones, y cada llamada registrada: quién, cómo terminó, cuánto duró, lo que recogió el IVR, su grabación y la actividad que dejó en la ficha.",
    perfil: "Perfil de telefonía",
    conectada: "Conectada sobre «{{nombre}}».",
    declarada: "declarada",
    falta: "falta",
    queFalta: "Falta: {{que}}",
    conexion: "Conexión",
    elige: "Elige una conexión",
    webhook: "Cómo se lee el aviso de la centralita (mapeo del conector)",
    ayudaWebhook:
      "La centralita manda cada cambio de una llamada a POST /api/v1/telefonia/avisos con una clave de API del tenant. Originar y transferir son operaciones declaradas en la conexión (originar_llamada y transferir_llamada).",
    jsonMal: "El mapeo no es un JSON válido.",
    guardar: "Guardar el perfil",
    guardado: "Perfil guardado.",
    llamadas: "Llamadas",
    sinLlamadas: "Todavía no hay ninguna llamada registrada.",
    cuando: "Cuándo",
    sentido: "Sentido",
    quien: "Quién",
    resultado: "Resultado",
    duracion: "Duración",
    ivr: "IVR",
    grabacion: "Grabación",
    actividad: "Actividad",
    sentidos: { entrante: "Entrante", saliente: "Saliente" },
    transferida: "Transferida a {{a}}",
    segundos: "{{n}} s",
    escuchar: "Escuchar",
    verActividad: "Ver actividad",
    sinActividad: "Aún no ha colgado",
  },
  // El motor externo de compensación (CRM-03.02.03.04).
  compensacionExterna: {
    titulo: "Compensación externa",
    entradilla:
      "Los hechos que se mandan al motor de comisiones —ventas ganadas, cobros, devoluciones y anulaciones, nunca la comisión—, lo que devuelve tal cual y lo que no cuadra con lo que calcula la casa.",
    motor: "Motor",
    conectado: "Conectado sobre «{{nombre}}».",
    declarada: "declarada",
    falta: "falta",
    conexion: "Conexión",
    elige: "Elige una conexión",
    usarComoMotor: "Usar como motor",
    motorGuardado: "Motor conectado.",
    periodo: "Periodo",
    desde: "Desde",
    hasta: "Hasta",
    recoger: "Recoger las ventas ganadas",
    recogidas:
      "{{nuevas}} nuevas, {{ya}} ya estaban, {{cambios}} cambiaron después de mandarlas.",
    enviar: "Mandar lo pendiente",
    enviados:
      "{{n}} mandados, {{calculados}} ya con cálculo, {{errores}} con error.",
    traer: "Traer el cálculo",
    conciliar: "Conciliar con la casa",
    conciliado:
      "{{cuadran}} de {{hechos}} cuadran con {{liquidaciones}} liquidaciones de la casa.",
    manual: "Cobro, devolución o anulación",
    tipo: "Tipo",
    referencia: "Referencia",
    fecha: "Fecha",
    importe: "Importe",
    motivo: "Motivo",
    darDeAlta: "Dar de alta",
    hechosTit: "Hechos",
    sinHechos: "Todavía no hay hechos para el motor.",
    estado: "Estado",
    delMotor: "Del motor",
    deLaCasa: "De la casa",
    diferencia: "Diferencia",
    provisional: "provisional",
    hechos: {
      cierre: "Venta ganada",
      anulacion: "Anulación",
      modificacion_importe: "Cambio de importe",
      cobro: "Cobro",
      devolucion: "Devolución (clawback)",
    },
    estados: {
      pendiente: "Pendiente",
      enviado: "Mandado",
      calculado: "Calculado",
      error: "Error",
    },
    que: {
      nuevo: "Dado de alta: queda pendiente de mandar.",
      actualizado: "Actualizado: queda pendiente de mandar.",
      ya_estaba: "Ya estaba mandado con el mismo importe.",
      cambio_tras_enviar:
        "Ya se mandó con otro importe: no se reescribe. Da de alta el cambio como su propio hecho.",
    },
  },
  sinConexion: {
    titulo: "Sin conexión",
    entradilla:
      "Lo que guardaste sin red está en este dispositivo y se envía solo al volver. Si otra persona cambió el mismo campo entre medias, decides tú qué valor se queda.",
    enviar: "Enviar ahora",
    conRed: "Hay conexión.",
    sinRed: "No hay conexión: lo pendiente se enviará al volver la red.",
    resultado:
      "Enviados: {{enviadas}} · en conflicto: {{conflictos}} · rechazados: {{rechazadas}}",
    conflictos: "Conflictos por resolver",
    conflictosAyuda:
      "Otra persona cambió el mismo campo mientras estabas sin red. Elige en cada campo qué valor se queda: nada se elige solo.",
    sinConflictos: "No hay conflictos.",
    cola: "Pendiente de enviar",
    colaAyuda:
      "Lo rechazado se queda aquí con su motivo hasta que lo descartes: nada se tira solo.",
    colaVacia: "No hay nada pendiente.",
    cuando: "Guardado",
    que: "Qué",
    campos: "Campos",
    estado: "Estado",
    campo: "Campo",
    loMio: "Lo mío",
    loSuyo: "Lo que hay en el servidor",
    aplicar: "Aplicar lo elegido",
    quedarmeConLoSuyo: "Quedarme con lo del servidor",
    descartar: "Descartar",
    tipos: { crear: "Alta", actualizar: "Cambio", borrar: "Borrado" },
    borradoEnConflicto:
      "Otra persona cambió este registro después de que lo leyeras. ¿Lo borras igualmente? Irá a la papelera y se podrá recuperar desde allí.",
    borrarIgualmente: "Borrarlo igualmente",
    estados: {
      pendiente: "Pendiente",
      enviando: "Enviando",
      rechazada: "Rechazado",
      conflicto: "En conflicto",
    },
  },
  alm: {
    paquete: {
      titulo: "Llevarse esta configuración a otro entorno",
      porQue:
        "Se lleva la CONFIGURACIÓN y nunca los datos: un paquete que arrastrara registros convertiría una promoción en una fuga, porque los datos de pruebas suelen ser copias anonimizadas a medias de clientes reales. Y se simula antes de aplicar: es un cambio de modelo de datos en producción.",
      exportar: "Exportar la configuración",
      exportando: "Exportando…",
      exportado:
        "Paquete listo: {{objetos}} objetos. Ahora se puede simular su instalación.",
      simular: "Simular la instalación",
      simulando: "Simulando…",
      aplicar: "Aplicar de verdad",
      aplicando: "Aplicando…",
    },
    titulo: "Entornos y cambios",
    intro: "Qué hay desplegado y qué tocó alguien a mano.",
    entorno: "Entorno",
    verDesvio: "Ver desvío",
    sinPaquete: "No hay ningún paquete desplegado",
    noComparado:
      "Sin comparar: {{tipos}}. De eso no se dice nada, no se ha mirado.",
    puesto: "Puesto aquí: {{paquete}} v{{version}} · {{git}}",
    sinGit: "sin referencia de repositorio (montado desde la consola)",
    tipo: "Tipo",
    clave: "Clave",
    quePaso: "Qué pasó",
  },
  ayuda: {
    titulo: "Ayuda",
    intro: "El manual, abierto por donde estás.",
    abrirCapitulo: "Abrir el capítulo de {{capitulo}}",
    sinCapitulo:
      "Esta pantalla todavía no tiene capítulo asociado en el manual.",
    otros: "Los dos manuales completos",
    manualUsuario: "Manual de usuario",
    manualTecnico: "Manual técnico",
  },
  cobertura: {
    titulo: "Cobertura de la interfaz",
    intro:
      "Qué del sistema enseña el front oficial, medido contra el contrato. Se calcula en vivo: un informe guardado se queda viejo en cuanto alguien añade una ruta.",
    publicadas: "Operaciones publicadas",
    conPantalla: "Con pantalla",
    deMaquina: "De máquina",
    enRecursos: "Repartidas en {{cuantos}} recursos.",
    sinPantalla: "Sin pantalla",
    operaciones: "operaciones",
    escondido: "Lo que el CRM hace y ninguna pantalla enseña",
    escondidoIntro:
      "Es la lista de potencia escondida en la API: capacidades construidas, probadas y documentadas que quien mira el producto concluye que no están.",
    todoEnsenado: "Todo lo publicado tiene pantalla.",
  },
  renovacionContrato: {
    titulo: "Renovación",
    ayuda:
      "Al llegar el preaviso se avisa y se abre una oportunidad de renovación en su embudo, enlazada con el contrato. La revisión periódica lo hace sola; aquí se revisa sólo este contrato.",
    revisar: "Revisar este contrato",
    vence: "Vence el {{fin}}; el preaviso es de {{dias}} días.",
    sinFin: "Sin fecha de fin: no se renueva ni avisa.",
    preavisoDado: "preaviso dado",
    oportunidad: "Oportunidad de renovación abierta:",
    abrirOportunidad: "abrirla en el embudo",
    noRevisado: "No se ha revisado: {{porque}}.",
    sinEmbudo:
      "El embudo de renovaciones «{{clave}}» no existe: no se abre ninguna.",
    aunNo: "Todavía no ha llegado el preaviso: no toca abrir la renovación.",
  },
  calidadDelDato: {
    titulo: "Calidad del dato",
    entradilla:
      "La ficha buena de cada cliente con de dónde sale cada valor, lo que dice el proveedor de datos, quién es la misma persona en cada canal, cuánto tienen que parecerse dos fichas y las direcciones en su forma normal.",
    irDuplicados: "Duplicados",
    objetos: { cuenta: "Cuentas", contacto: "Contactos", lead: "Leads" },
    // Golden record
    golden: "Ficha buena (golden record)",
    goldenAyuda:
      "Las fichas con más de una versión de la verdad —fusionadas o unidas por identidad—. En un lead, las fusionadas son las capturas que entraron en él y las unidas, los leads señalados como su duplicado. Componer aplica las reglas y guarda el resultado con su procedencia; aplicar lo escribe en la ficha.",
    sinCandidatas:
      "Ninguna ficha tiene todavía otra versión fusionada o unida: componerla devolvería lo que ya tiene.",
    ficha: "Ficha",
    fusionadas: "Fusionadas",
    unidas: "Unidas",
    compuesta: "Compuesta",
    nunca: "nunca",
    componer: "Componer",
    aplicar: "Aplicar a la ficha",
    campo: "Campo",
    valor: "Valor que gana",
    fuente: "Fuente",
    regla: "Regla",
    porque: "Por qué",
    otrasFuentes: "Lo que dicen las demás",
    aRevisar_one: "{{count}} campo por revisar: las fuentes no coinciden",
    aRevisar_other: "{{count}} campos por revisar: las fuentes no coinciden",
    aplicados_one: "Aplicado: {{count}} campo cambiado en la ficha",
    aplicados_other: "Aplicado: {{count}} campos cambiados en la ficha",
    sinCambios: "La ficha ya tenía los valores que ganan.",
    reglas: "Reglas de supervivencia",
    reglasAyuda:
      "Por campo: qué estrategia decide y cuánto se fía de cada fuente (0 a 100). El campo «*» es la regla por defecto del objeto; una fuente que no aparece vale 50.",
    objeto: "Objeto",
    estrategia: "Estrategia",
    confianzas: "Confianza por fuente",
    confianzasAyuda: "Una por línea: fuente=número. Por ejemplo erp=90",
    porDefecto: "* (por defecto del objeto)",
    guardarRegla: "Guardar la regla",
    quitar: "Quitar",
    sinReglas:
      "Sin reglas: gana la fuente de mayor confianza, y todas valen 50.",
    estrategias: {
      mayor_confianza: "La fuente más fiable",
      mas_reciente: "La que cambió después",
      mas_completo: "La más completa",
      solo_si_falta: "Sólo si falta",
      decide_una_persona: "Lo decide una persona",
    },
    // Identidad entre canales
    identidad: "La misma persona en cada canal",
    identidadAyuda:
      "Las señales —correo, teléfono, cookie, identificador de la app o del ERP— se anotan solas al guardar el contacto o cuando las trae otro canal. Aquí se proponen las parejas y se unen; unir no borra ninguna ficha y se puede deshacer.",
    barrer: "Anotar las señales de los contactos existentes",
    barrido: "{{senales}} señales anotadas de {{contactos}} contactos.",
    sinPropuestas:
      "Ninguna pareja de contactos comparte señales por encima del umbral.",
    pareja: "Pareja",
    senales: "Señales que coinciden",
    puntuacion: "Puntuación",
    unir: "Unir (se queda la primera)",
    unida:
      "Unidas: desde ahora una señal de cualquiera de las dos lleva a la primera.",
    umbralIdentidad: "Umbral para proponer: {{umbral}}",
    // Enriquecimiento
    enriquecimiento: "Proveedor de datos (enriquecimiento)",
    enriquecimientoAyuda:
      "Cada proveedor es una conexión y una operación del conector de Integraciones. Pedir guarda lo que contesta como propuesta; aplicar escribe lo elegido con el proveedor como procedencia. Sin elegir, sólo se rellenan huecos.",
    perfiles: "Proveedores declarados",
    sinPerfiles: "No hay ningún proveedor declarado.",
    nuevoPerfil: "Declarar un proveedor",
    clave: "Clave",
    nombre: "Nombre",
    conexion: "Conexión",
    sinConexionesInt:
      "No hay conexiones en Integraciones: declara primero la del proveedor.",
    operacion: "Operación",
    parametros: "Parámetros de la operación",
    parametrosAyuda:
      "Uno por línea: parámetro=campo de la ficha. Por ejemplo dominio=dominio",
    mapeo: "Qué campo de la respuesta va a cada campo",
    mapeoAyuda:
      "Uno por línea: campo de la ficha=campo de la respuesta. Por ejemplo sector_codigo=industria",
    confianza: "Confianza",
    coste: "Coste por consulta",
    guardarPerfil: "Guardar el proveedor",
    pedir: "Pedir",
    pedirPara: "Pedir para",
    elegirCuenta: "Elige una ficha",
    propuestas: "Propuestas por revisar",
    sinPropuestasEnr: "No hay propuestas pendientes.",
    actual: "Ahora",
    propuesto: "Propone",
    tipos: {
      hueco: "rellena un hueco",
      discrepancia: "contradice",
      igual: "igual",
    },
    aplicarElegidos: "Aplicar lo marcado",
    descartar: "Descartar",
    aplicada: "Aplicada a la ficha.",
    descartada: "Descartada.",
    // Umbrales
    umbrales: "Cuánto tienen que parecerse dos fichas",
    umbralesAyuda:
      "Por objeto. «Sugerir» avisa al dar de alta, «bloquear» impide el alta y «proponer» mete la pareja en la cola de duplicados. Vacío: sale del umbral general.",
    tiposUmbral: {
      sugerencia: "Sugerir",
      bloqueo: "Bloquear",
      propuesta: "Proponer",
    },
    filasUmbral: {
      cuenta: "Cuentas",
      contacto: "Contactos",
      leadLead: "Lead frente a otro lead",
      leadContacto: "Lead frente a un contacto",
    },
    general: "del general",
    propio: "propio",
    guardarUmbrales: "Guardar los umbrales",
    umbralesGuardados: "Umbrales guardados.",
    // Direcciones
    direcciones: "Direcciones normalizadas",
    direccionesAyuda:
      "Lo que entra se normaliza solo al guardarlo: espacios, abreviatura de vía, código postal con sus dígitos, país en ISO. Para lo que ya estaba, primero se mira qué cambiaría y después se aplica.",
    verCambios: "Ver qué cambiaría",
    aplicarCambios: "Aplicar a {{n}} direcciones",
    revisadas: "{{revisadas}} revisadas, {{n}} cambiarían.",
    aplicadas: "{{n}} direcciones normalizadas.",
    antes: "Antes",
    despues: "Después",
  },
  duplicados: {
    // El número en el botón: «ver más» a secas no dice si queda una o ochenta.
    verMas: "Ver {{cuantas}} más",
    cuantasQuedan: "Viendo {{vistas}} de {{total}}",
    titulo: "Duplicados por resolver",
    yaExiste: "¿Ya existe? Compruébalo antes de dar de alta",
    yaExisteAyuda:
      "Lo mismo que mira el alta, sin crear nada. La cola de abajo es de los duplicados que ya entraron; esto es para que no entre el siguiente.",
    nombreEmpresa: "Nombre de la empresa",
    nif: "NIF (opcional)",
    comprobar: "Comprobar",
    noSeParece: "No se parece a ninguna empresa que ya esté dada de alta.",
    noSeParecePersona:
      "No se parece a ningún contacto que ya esté dado de alta.",
    deQue: "Qué compruebas",
    deQueOpciones: { empresa: "Una empresa", persona: "Una persona" },
    nombrePersona: "Nombre",
    apellidos: "Apellidos (opcional)",
    email: "Correo (opcional)",
    entradilla:
      "Parejas que podrían ser la misma empresa, lo más probable primero y con QUÉ ha coincidido. Desde aquí se deciden: no es una lista para mirar.",
    buscar: "Buscar duplicados ahora",
    buscando: "Buscando…",
    soloPendientes: "Sólo las que faltan por decidir",
    resultadoBarrido:
      "Revisadas {{revisadas}} fichas, {{propuestas}} parejas nuevas.",
    ninguna: "No hay ninguna pareja por decidir",
    ningunaDetalle:
      "O no hay duplicados, o nadie ha pasado el barrido todavía. El botón de arriba lo pasa sobre todo el maestro, no sólo sobre lo que entre a partir de ahora.",
    probabilidad: "{{pct}} % de probabilidad",
    abrirFicha: "Abrir la ficha",
    seQuedaEsta: "Se queda ésta",
    eligeCual: "Elige cuál de las dos se queda para poder fusionarlas.",
    fusionar: "Fusionar",
    noSonLaMisma: "No son la misma",
    paraLuego: "Dejarlo para luego",
    porQueNoBorrar:
      "No hay «borrar ésta» a propósito: borrarla tiraría su histórico. Fusionar deja lo suyo en la que se queda.",
    confirmarTitulo: "Confirmar la fusión",
    queVaAPasar:
      "«{{absorbida}}» dejará de aparecer en las listas y todo lo suyo —contactos, oportunidades, casos y lo que se habló— pasará a «{{superviviente}}». Mezclar el histórico de dos clientes es difícil de deshacer.",
    siFusiona: "Sí, fusiónalas",
    mejorNo: "Mejor no",
    decision: {
      fusionar: "Fusionadas",
      no_es_duplicado: "No son la misma",
      descartar: "Dejada para luego",
    },
  },

  // Lo que dicen los modelos entrenados con el histórico, en la ficha del
  // lead, de la oportunidad y de la cuenta. Aquí y no en `es.ts`: las tres
  // fichas son pantallas diferidas y esperan a este diccionario.
  prediccion: {
    titulo: "Predicción con el histórico",
    recalcular: "Recalcular",
    cargando: "Calculando con el modelo publicado…",
    suman: "Lo que la sube",
    restan: "Lo que la baja",
    aporta: "Aporta {{n}} (en la escala del modelo)",
    entre: "entre {{min}} y {{max}}",
    declarado: "declarado: {{valor}}",
    declarada: "declarada: {{fecha}}",
    dias: "{{n}} días desde que se abrió",
    pasada:
      "Ya lleva más de lo que suelen tardar: esta fecha es hoy, no una previsión",
    auc: "AUC {{n}}",
    mae: "error medio {{n}}",
    aciertoTop: "acierta el {{n}}",
    modelo:
      "Modelo v{{version}} · {{medida}} medido en {{muestras}} casos que no vio al entrenar",
    tipos: {
      cierre: "Probabilidad de ganarla",
      importe: "Importe previsto",
      fecha_cierre: "Fecha real de cierre prevista",
      scoring_lead: "Probabilidad de convertir",
      propension: "Propensión a comprar",
      siguiente_oferta: "Siguiente mejor oferta",
    },
  },
  modelosPredictivos: {
    titulo: "Modelos predictivos",
    entradilla:
      "Modelos entrenados con el histórico de este CRM. Se miden contra lo más reciente, que el modelo no ha visto, y sólo se publican si superan el mínimo configurado. Con pocos datos no se entrenan: se dice.",
    sobre: "Puntúa: {{objeto}}",
    objetos: { lead: "leads", oportunidad: "oportunidades", cuenta: "cuentas" },
    que: {
      scoring_lead:
        "Probabilidad de que un lead acabe convertido, aprendida de los convertidos y los descartados.",
      cierre:
        "Probabilidad de ganar una oportunidad, con lo que se sabía cuando se abrió.",
      importe: "Importe al que se ganará, aprendido de las ventas ganadas.",
      fecha_cierre:
        "Días desde que se abre hasta que se cierra de verdad, ganada o perdida.",
      propension:
        "Probabilidad de que la cuenta compre en la ventana configurada.",
      siguiente_oferta:
        "Qué producto ofrecer, por lo que compraron las cuentas que compraron lo mismo.",
    },
    publicada: "Publicada · {{medida}} en {{muestras}} casos apartados",
    declarada:
      "La versión que puntúa es de pesos declarados a mano: no se usa para puntuar registros reales.",
    sinPublicar: "Ninguna versión publicada: aquí no se puntúa nada todavía.",
    ultimaVersion: "Última versión: v{{version}}, {{estado}}. {{notas}}",
    entrenar: "Entrenar ahora",
    entrenando: "Entrenando…",
    programar: "Reentrenar solo cada {{dias}} días",
    proxima: "Próximo reentreno: {{cuando}}",
    ultimoResultado: "la última vez: {{texto}}",
    noEntrenado: "No se ha entrenado",
    siPublicado: "Entrenada y publicada: v{{version}}",
    noPublicado: "Entrenada (v{{version}}) y NO publicada",
    reparto:
      "{{casos}} casos: {{entreno}} para entrenar y {{validacion}} para medir, desde el {{corte}}",
    casos: "{{casos}} casos con resultado conocido",
    segmento: "Segmento por propensión",
    segmentoAyuda:
      "Puntúa todas las cuentas —o los leads abiertos— con el modelo publicado y crea en marketing un segmento con los que pasan del mínimo, congelado hoy. Necesitas poder crear segmentos.",
    criterio: "Criterio",
    criterios: {
      propension: "Propensión a comprar (0 a 1)",
      valor_esperado: "Valor esperado (propensión × importe medio)",
      scoring_lead: "Probabilidad de convertir (leads, 0 a 1)",
    },
    minimo: "Mínimo",
    tope: "Como mucho",
    nombre: "Nombre del segmento",
    crearSegmento: "Crear el segmento",
    segmentoCreado:
      "Segmento creado: el modelo eligió {{previstos}} de {{candidatos}} y marketing congeló {{congelados}}.",
    abrirSegmento: "Abrir el segmento",
    versiones: "Versiones",
    versionesAyuda:
      "Todas, también las descartadas: el porqué está en el título de cada fila. Las de origen «declarado» se registraron con pesos tecleados.",
    sinVersiones: "Todavía no hay ninguna versión.",
    col: {
      modelo: "Modelo",
      version: "Versión",
      estado: "Estado",
      origen: "Origen",
      medida: "Medida en lo apartado",
      ejemplos: "Casos",
      ventana: "Datos",
      entrenado: "Entrenado",
    },
    estados: {
      activa: "Publicada",
      descartada: "No publicada",
      retirada: "Retirada",
      evaluada: "Evaluada",
      entrenando: "Entrenando",
    },
    origenes: { historico: "Histórico del CRM", declarado: "Declarado" },
  },
  // Transcripción y resumen de una llamada o reunión, con sus compromisos
  // (CRM-01.02.01.05, CRM-01.02.01.06).
  transcripcionReunion: {
    titulo: "Transcripción y resumen",
    ayuda:
      "Sube la grabación (queda como documento de la actividad), da el enlace o pega el texto. El modelo resume y propone los compromisos; cada uno se convierte en tarea cuando lo confirmas.",
    conProveedor:
      "Transcribe el proveedor de la empresa ({{envio}}); hasta {{mb}} MB.",
    envios: {
      enlace: "descarga el audio de un enlace firmado",
      contenido: "recibe el audio en la petición",
    },
    plantilla: "Proveedor de transcripción",
    urlBase: "Dirección (opcional, si no es la del proveedor)",
    instalar: "Instalar",
    instalarAyuda:
      "Da de alta la conexión en Integraciones con la forma de petición del proveedor. Su clave se pone después en la ficha de la conexión.",
    fuente: "Qué transcribir",
    fuentes: {
      audio: "Fichero de audio",
      enlace: "Enlace a la grabación",
      texto: "Texto ya transcrito",
    },
    base: "Base para grabar",
    bases: {
      consentimiento_de_todos: "Lo han aceptado todos",
      aviso_y_no_oposicion: "Se avisó y nadie se opuso",
      obligacion_legal: "Obligación legal de grabar",
    },
    fichero: "Grabación",
    enlace: "Enlace a la grabación",
    texto: "Transcripción",
    idioma: "Idioma",
    avisados: "Se avisó a todos los participantes de que se grababa",
    transcribir: "Transcribir y resumir",
    trabajando: "Transcribiendo y resumiendo…",
    minutos: "{{n}} min",
    confianza: "confianza {{pct}} %",
    sinConfianza: "confianza sin medir",
    compromisos: "Compromisos y próximos pasos",
    tipos: {
      compromiso: "Compromiso",
      proximo_paso: "Próximo paso",
      riesgo: "Riesgo",
      objecion: "Objeción",
      dato_del_cliente: "Dato del cliente",
    },
    citaNoLiteral: "Esta cita no aparece tal cual en lo transcrito.",
    asuntoTarea: "Asunto",
    vence: "Vence",
    crearTarea: "Confirmar y crear la tarea",
    confirmar: "Confirmar",
    descartar: "Descartar",
    descartada: "Descartado.",
    confirmada: "Confirmado.",
    tareaCreada: "Tarea creada con tu usuario.",
    abrirTarea: "Abrir la tarea",
    descartados: "{{n}} sin proponer (sin dueño o tipo desconocido)",
    verTexto: "Ver la transcripción",
  },
  // Variantes de copy generadas y revisadas (CRM-02.04.01.04).
  variantesCopy: {
    titulo: "Variantes con IA",
    ayuda:
      "El modelo propone versiones del texto; ninguna sale sin que alguien la apruebe. Las cifras, garantías y superlativos se marcan para comprobarlos.",
    base: "Texto base",
    objetivo: "Objetivo",
    ejemploObjetivo: "Que abran el correo los que no compraron este año",
    canal: "Canal",
    canales: {
      asunto: "Asunto de correo",
      email: "Cuerpo de correo",
      sms: "SMS",
      push: "Notificación",
      anuncio: "Anuncio",
      web: "Web",
      redes: "Redes sociales",
    },
    cuantas: "Cuántas",
    generar: "Generar variantes",
    generando: "Generando…",
    estados: {
      propuesta: "Propuesta",
      aprobada: "Aprobada",
      rechazada: "Rechazada",
    },
    ganadora: "Ganadora",
    reescrita: "Reescrita al aprobarla",
    texto: "Texto",
    afirmaciones: "Comprobar antes de aprobar:",
    aprobar: "Aprobar",
    motivo: "Motivo",
    rechazar: "Rechazar",
    elegir: "Elegir como ganadora",
  },
  asistente: {
    titulo: "Asistente IA",
    entradilla:
      "Pregunta a lo que la casa sabe —artículos, casos resueltos, lecciones— y contesta citando; si pides que haga algo, lo propone y no lo hace hasta que lo confirmes. Y pregunta a los datos: se ejecuta contra los listados del CRM con tus permisos y te enseña la consulta.",
    conocimiento: "Conocimiento y acciones",
    conocimientoAyuda:
      "Sólo contesta con lo que encuentra, citando. Si le pides que haga algo, lo propone y espera a que lo confirmes.",
    sabeDe:
      "Lo que tiene indexado, en fragmentos: {{fuentes}} (modelo {{modelos}}).",
    indiceVacio:
      "El índice de conocimiento está vacío: hasta que se indexen artículos, casos resueltos o lecciones, no tendrá con qué contestar.",
    misAcciones: "Lo que te ha propuesto hacer",
    puedesPedir: "Con tu rol puedes pedirle: {{acciones}}.",
    nadaQuePedir:
      "Con tu rol no puede proponerte ninguna acción: sólo contestar.",
    sinPropuestas: "Todavía no te ha propuesto nada.",
    caduca: "caduca el {{cuando}}",
    faltan: "Falta: {{campos}}. Vuelve a preguntar con ese dato.",
    estadoCorto: {
      propuesta: "Pendiente de tu confirmación",
      ejecutada: "Hecha",
      fallida: "Falló",
      descartada: "Descartada",
      caducada: "Caducada",
    },
    datos: "Pregunta a los datos",
    datosAyuda:
      "Se traduce a una consulta sobre los listados del CRM —nunca SQL— y se ejecuta con tus permisos.",
    pregunta: "Tu pregunta",
    ejemploConocimiento:
      "¿Qué aprendimos de las ventas perdidas por precio? · Crea una tarea para llamar mañana a…",
    ejemploDatos:
      "¿Cuántas oportunidades ganadas hay de más de 50.000 €? · Importe total por estado",
    preguntar: "Preguntar",
    pensando: "Pensando…",
    sinRespuesta: "Sin respuesta comprobable.",
    fuentes: {
      leccion: "Lección",
      articulo: "Artículo",
      caso_resuelto: "Caso resuelto",
    },
    propone: "Propone: {{accion}}",
    confirmar: "Confirmar y hacerlo",
    descartar: "Descartar",
    conTusPermisos: "Se hará con tu usuario y tus permisos.",
    campos: {
      asunto: "Asunto",
      cuerpo: "Detalle",
      vence_at: "Vence",
      objeto: "Cuelga de",
      objeto_id: "Identificador del registro",
      descripcion: "Descripción",
      prioridad: "Prioridad",
      cuenta_id: "Cuenta",
      empresa: "Empresa",
      nombre: "Nombre",
      apellidos: "Apellidos",
      email: "Email",
      telefono: "Teléfono",
    },
    estados: {
      ejecutada: "Hecho (respuesta {{codigo}}). Registro creado: {{id}}",
      fallida: "No se ha podido (respuesta {{codigo}}). {{detalle}}",
      descartada: "Descartada: no se ha hecho nada.",
    },
    entendido: "Entendido así:",
    parcial: "Parcial: se leyeron {{leidas}} de {{total}}",
    consultaHecha: "La consulta que se ha hecho",
    agregados: "Por grupo",
    grupo: "Grupo",
    valor: "Valor",
    filas: "Filas",
    filasDeEjemplo: "Filas devueltas",
    voz: {
      modo: "Modo voz",
      hablar: "Hablar",
      escuchando: "Escuchando…",
      terminar: "Terminar y preguntar",
      callar: "Dejar de leer",
      via: {
        navegador:
          "Dictado con el reconocimiento de voz del navegador; la respuesta se lee en voz alta.",
        grabacion:
          "Este navegador no reconoce voz: se graba y lo transcribe el proveedor de la empresa, sin guardar la grabación.",
        ninguna:
          "Este navegador no puede dictar ni grabar: escribe la pregunta y la respuesta se leerá en voz alta.",
      },
    },
  },
  preguntar: {
    titulo: "Nexus",
    entradilla:
      "Escribe lo que necesitas y el agente propone QUÉ haría para conseguirlo, paso a paso. Primero verás el plan; nada se ejecuta hasta que lo mandas, y lo que toca datos espera a que alguien lo autorice.",
    quienResponde: "Responde",
    modoIterativo: "decide sobre la marcha",
    quePides: "Qué quieres",
    ejemplo:
      "Por ejemplo: qué cuentas llevan más de dos meses sin contacto y tienen una oportunidad abierta.",
    planificar: "Preparar el plan",
    noEjecutaNada: "Esto no ejecuta nada todavía: devuelve el plan.",
    seguir: "Dar el siguiente paso",
    trabajando: "Trabajando…",
    tokens: "{{tokens}} tokens",
    sinPasos: "El agente no ha propuesto ningún paso para esto.",
    haPensado:
      "Ha decidido el siguiente paso con el resultado del anterior delante:",
    paroPorque: "Paró porque:",
    pidioLoQueNoTiene: "Ha pedido una herramienta que no tiene declarada:",
    autorizar: "Autorizar",
    rechazar: "No lo hagas",
    esperaAPersona_one: "Hay un paso esperando a que alguien lo autorice.",
    esperaAPersona_other:
      "Hay {{count}} pasos esperando a que alguien los autorice.",
    deshacer: "Deshacer lo hecho",
    noTodoSeDeshace:
      "Esto no se deshace del todo. No tiene vuelta atrás, y se quedará como está:",
    sinAgentes: "Todavía no hay ningún asistente al que preguntar",
    sinAgentesDetalle:
      "Aquí contesta un asistente, que es un agente de solo consulta. Se declara en Administración → Agentes autónomos, como «asistente conversacional», con las herramientas que puede usar y cuándo tiene que esperar a una persona. Los agentes que hacen una tarea concreta —proponer la respuesta de un caso, calificar un lead— no salen aquí: su sitio es la pantalla de ese trabajo, con el registro delante.",
  },

  orden: {
    trabajado: "{{minutos}} min trabajados",
    alterado:
      "El parte se ha TOCADO DESPUÉS DE FIRMAR: su huella ya no cuadra con lo que hay escrito. Una firma del cliente sobre un parte que cambió después no vale nada, y no se nota mirándolo — se ve igual de completo.",
    quienPaga: "Quién paga cada línea",
    porqueTresCestas:
      "Tres cestas y no dos: lo que paga el cliente, lo que se le reclama al fabricante y lo que NO SE SABE. Fundir la tercera es facturar de más o perder una reclamación.",
    cestas: "{{facturar}} a facturar · {{garantia}} a garantía",
    sinDeterminar:
      "{{cuantas}} línea(s) sin decidir quién las paga. Ni se facturan ni se reclaman hasta que alguien lo diga.",
    porDecidir: "por decidir",
    aGarantia: "garantía",
    aFacturar: "factura",
    parte: "El parte de trabajo",
    sinParte: "Todavía no hay parte",
    sinParteDetalle:
      "Sin parte no hay qué firmar ni qué facturar: es lo que deja constancia de lo que se hizo.",
    evidencias: "{{checklist}} puntos de checklist · {{evidencias}} evidencias",
    firmado: "Firmado por el cliente y conforme.",
    firmadoNoConforme:
      "Firmado, pero el cliente NO está conforme. Firmar es decir que estuvimos; conforme es otra cosa.",
    sinFirmar: "Sin firmar.",
    quienPuede: "Quién puede hacerla",
    porqueDescartados:
      "La lista de descartados es la mitad del valor: «nadie disponible» no se acciona, y «los tres con la competencia están fuera de zona» sí.",
    sinCandidatos: "No se ha podido calcular quién puede hacerla",
    competencias: "Competencias que pide: {{competencias}}",
    ninguna: "ninguna",
    nadieApto: "Ningún técnico cumple todo lo que pide esta orden.",
    aptos: "{{cuantos}} técnico(s) pueden hacerla.",
    verActivo: "Ver el activo sobre el que se trabaja",
  },
  prospeccion: {
    titulo: "Prospección",
    entradilla:
      "Qué plantillas funcionan de verdad, y a quién del equipo le toca la próxima reunión.",
    aQuienLeToca: "A quién le toca la próxima reunión",
    porqueBoton:
      "Va con botón y no se pide al abrir: pedirlo AVANZA el turno del equipo, y una pantalla que lo pidiera sola repartiría reuniones cada vez que alguien la mira.",
    equipo: "Equipo",
    pedirTurno: "A quién le toca",
    pidiendo: "Pidiendo…",
    leToca: "Le toca a {{usuario}}",
    turnoConsumido:
      "El turno se ha consumido: al siguiente le tocará a otro. Pulsar otra vez para «ver» se salta a alguien del equipo.",
    huecos: "{{cuantos}} huecos en los próximos días.",
    sinHuecos: "No tiene ningún hueco en los próximos días.",
    misHuecos: "Mis huecos para proponer una reunión",
    misHuecosAyuda:
      "Los tramos que has declarado en tu disponibilidad, de los próximos cinco días. Cada uno dice si se ha contrastado con tu calendario: uno sin contrastar es una propuesta, no una promesa.",
    verMisHuecos: "Ver mis huecos",
    misSinHuecos:
      "No tienes huecos en los próximos días: o no has declarado disponibilidad, o está desactivada, o está todo pasado de la antelación mínima.",
    contrastado: "contrastado con el calendario",
    sinContrastar: "sin contrastar",
    plantillas: "Qué plantillas funcionan",
    porqueConcluyente:
      "Una tasa sin su número de envíos es ruido: con nueve correos, un 33 % son tres respuestas. Las que se han usado pocas veces van aparte, no compitiendo con las demás.",
    sinMedir: "Todavía no hay con qué medir ninguna plantilla",
    sinMedirDetalle:
      "Hacen falta envíos registrados. Sin ellos, cualquier porcentaje que saliera aquí sería inventado.",
    ningunaConcluyente:
      "Ninguna plantilla se ha usado lo suficiente para sacar conclusiones",
    tasas: "{{respuesta}} % responden · {{reunion}} % acaban en reunión",
    sobre:
      "{{enviados}} enviados · {{respondidos}} respuestas · {{reuniones}} reuniones",
    pocasVeces:
      "{{cuantas}} plantilla(s) se han usado demasiado poco para decir nada de ellas:",
    envios: "{{enviados}} envíos",
  },
  activo: {
    cobertura: "Si lo paga la garantía",
    sinCobertura: "No se ha podido consultar la cobertura",
    noConcluyente:
      "NO SE PUEDE DETERMINAR si está cubierto. No es lo mismo que no estarlo: aquí todavía no se sabe quién paga.",
    cubierto: "Cubierto por garantía.",
    noCubierto: "No está cubierto.",
    hasta: "hasta el {{fecha}}",
    exclusiones: "{{cuantas}} exclusión(es) declaradas en esa garantía.",
    contador: "Lo que lleva andado",
    sinContador: "Este activo no lleva contador",
    lectura: "{{contador}} {{unidad}}",
    leidoEl: "leído el {{fecha}}",
    sinFechaDeLectura:
      "Sin fecha de lectura: no se sabe de cuándo es este número, y sobre un contador se decide un mantenimiento.",
    arbol: "De qué forma parte",
    porqueArbol:
      "Una avería en una bomba no se entiende sin saber de qué equipo es: un componente mirado solo lleva a cambiar la pieza y no la causa.",
    truncado: "(hay más componentes por debajo)",
    historial: "Qué le ha pasado",
    cadena:
      "El historial sigue la cadena de sustituciones: son {{equipos}} equipos. La avería de hoy puede venir del que estaba antes.",
    sinEventos: "No hay nada anotado todavía",
    deEquipoAnterior: "(del equipo al que sustituyó)",
  },
  archivos: {
    titulo: "Archivos",
    entradilla:
      "Todos los documentos del CRM, con el registro del que cuelga cada uno. " +
      "Hasta ahora sólo se veían desde su ficha, así que para encontrar uno " +
      "había que acordarse antes de a qué cliente pertenece.",
    buscar: "Buscar por nombre de fichero…",
    nombre: "Fichero",
    de: "Cuelga de",
    cuando: "Subido",
    tamano: "Tamaño",
    version: "v{{version}}",
    ninguno: "Todavía no hay documentos",
    ningunoPorque:
      "Los documentos se suben desde la ficha del registro al que acompañan: " +
      "una cuenta, una oportunidad, un caso.",
    registroBorrado: "el registro ya no existe",
    // Distinto del anterior a propósito: «ya no existe» sólo se dice de lo
    // que se ha podido mirar. De lo que no, se dice que no se sabe.
    registroSinMirar: "no se ha podido mirar",
    ningunoAsi: "Ningún fichero se llama así",
    ningunoAsiPorque:
      "Se busca por el nombre del fichero, no por su contenido ni por el " +
      "cliente. Prueba con menos letras.",
  },

  seguir: {
    seguir: "Seguir",
    siguiendo: "Siguiendo",
    dejar: "Dejar de seguir",
    // Al propietario se le silencia en vez de desuscribirle: no puede dejar
    // de ser responsable de su registro. Sin decirlo, el botón parece que no
    // hace caso.
    eresPropietario:
      "Eres el responsable: dejas de recibir avisos, pero sigues saliendo como su responsable.",
    noSePudo: "No se ha podido cambiar",
    // Lo que uno sigue, desde la barra de arriba.
    loQueSigo: "Lo que sigo",
    nadaSeguido: "No sigues nada todavía",
    nadaSeguidoPorque:
      "Se sigue desde la ficha de un registro, con el botón «Seguir». Lo que " +
      "sigues es lo que te avisa cuando cambia.",
    silenciadoAqui: "silenciado",
    motivoPropietario: "responsable",
    yaNoEsta: "Este registro ya no existe",
    // Distinto de lo anterior a propósito: «ya no existe» sólo se dice de lo
    // que se ha podido mirar. De lo que no, se dice que no se sabe.
    noSeHaPodidoMirar: "No se ha podido mirar este registro",
    dejado: "Has dejado de seguirlo",
    entradilla:
      "Lo que te avisa cuando cambia. Se sigue desde la ficha, con el botón " +
      "«Seguir»; de lo que eres responsable te llega aunque no lo sigas a mano.",
  },

  calendario: {
    titulo: "Calendario",
    entradilla:
      "El mes de un vistazo: lo que empieza ese día y lo que se le acaba el " +
      "plazo. Cuando las hay de las dos clases, las que sólo vencen van " +
      "marcadas con un reloj: una tarea no ocurre ese día, lo que pasa es que " +
      "se le acaba el plazo.",
    soloMias: "Sólo las mías",
    hoy: "Hoy",
    mesAnterior: "Mes anterior",
    mesSiguiente: "Mes siguiente",
    masDelDia: "+{{cuantas}}",
    soloVence: "Sólo vence ese día",
    ningunaEsteMes: "Nada apuntado este mes",
    ningunaPorque:
      "Ni una actividad con fecha en estas semanas. Se apuntan desde la ficha " +
      "del cliente o desde Actividades.",
    ningunaMiaPorque:
      "Ninguna asignada a ti este mes. Quita «Sólo las mías» para ver las del " +
      "equipo: puede que el mes sí tenga trabajo y no sea tuyo.",
    faltan:
      "Este mes trae más actividades de las que se han podido traer: se " +
      "enseñan {{cuantas}}, por vencimiento. Acota con «Sólo las mías» para " +
      "verlo entero.",
  },

  menciones: {
    titulo: "Dónde me han mencionado",
    entradilla:
      "De todo el CRM: en una cuenta, en una oportunidad o en un caso. Mencionar a " +
      "alguien ya funcionaba; lo que faltaba era el sitio donde se ven.",
    ninguna: "Nadie te ha mencionado",
    ningunaDeVerdad:
      "Cuando alguien te nombre en un comentario de cualquier registro, aparecerá aquí.",
    ningunaPeroMudos:
      "Ojo: algún servicio no ha contestado, así que esto puede no ser todo.",
    interno: "interno",
    abrir: "Abrir el registro",
  },
  canalesmk: {
    titulo: "Canales y consentimiento",
    entradilla:
      "Antes de mandar nada: si se le puede escribir a esa persona por ese canal, " +
      "y con qué reglas.",
    comprobar: "¿Se le puede escribir?",
    porqueComprobar:
      "El consentimiento es por canal y por destino, no global: alguien puede haber aceptado el correo y no el SMS, y tratarlo como una sola casilla es lo que convierte una baja en una denuncia.",
    canal: "Canal",
    elegirCanal: "Elige un canal",
    destino: "Teléfono, correo o identificador",
    ver: "Comprobar",
    comprobando: "Comprobando…",
    siSePuede: "Sí se le puede escribir por aquí.",
    noSePuede: "No se le puede escribir por aquí:",
    necesitaPlantilla:
      "Fuera de la ventana de 24 h sólo sale una plantilla APROBADA. Mandar una no aprobada no da error: el proveedor la descarta en silencio.",
    bajaCon:
      "Se da de baja contestando «{{palabra}}». Esa palabra tiene que ir en el mensaje.",
    calentando:
      "El dominio está calentando: hoy como mucho {{tope}} envíos. Pasarse quema la IP, y quemarla deja semanas sin que llegue nada por ese dominio — ni campañas ni facturas.",
    queLlega: "Qué llega de lo que mandamos",
    porqueLlega:
      "Un dominio que manda mucho y no abre nadie está cayendo en la carpeta de basura, y eso no se ve mirando los envíos.",
    mandados:
      "{{mandados}} mandados en {{dias}} días · {{rebotes}} rebotes duros · {{quejas}} quejas",
    apertura: "{{pct}} % de apertura",
    aperturaNoMedible: "Apertura: no hay con qué medirla todavía",
    declarados: "Los canales declarados",
    sinCanales: "No hay ningún canal declarado",
    sinCanalesDetalle:
      "Sin canales declarados no se puede mandar nada: un canal dice por dónde se sale y cómo se da de baja alguien por ahí.",
    activo: "activo",
    apagado: "apagado",
    sedaDeBajaCon: "baja: «{{palabra}}»",
    sinFormaDeBaja:
      "sin forma de baja declarada — por este canal no se puede mandar nada comercial",
  },
  // El sandbox de API con datos sintéticos y su consola (CRM-00.02.01.15).
  sandboxApi: {
    titulo: "Probar la API en un sandbox",
    entradilla:
      "Un entorno aparte con datos inventados y una clave que sólo lo abre a él: aquí se prueba una integración sin tocar los datos de la empresa.",
    nombrePorDefecto: "Pruebas de API",
    crear: "Crear un sandbox",
    crearAyuda:
      "Crea un tenant de pruebas, lo llena con datos generados del contrato de la API —no copiados— y emite una clave de API de ese tenant. Caduca solo.",
    nombre: "Nombre",
    objetos: "Colecciones a llenar",
    objetosAyuda: "accounts, contacts… (vacío: las de serie)",
    filas: "Filas por colección",
    filasAyuda: "vacío: las de serie",
    crearBoton: "Crear el sandbox",
    creando: "Creando…",
    creado:
      "Sandbox creado con {{filas}} filas sintéticas. Caduca el {{caduca}}.",
    datos: "Datos generados",
    objeto: "Colección",
    servicio: "Servicio",
    creadas: "Creadas",
    error: "Lo que falló",
    credencial: "Clave de API del sandbox",
    soloUnaVez:
      "Se enseña ahora y no se vuelve a poder leer. Ya está puesta en la consola de abajo.",
    sinCredencial: "El sandbox se ha creado, pero la clave no: {{motivo}}",
    consola: "Consola",
    consolaAyuda:
      "Cada llamada sale con la clave del sandbox y sin tu sesión: lo que se rompa aquí se rompe en datos inventados.",
    clave: "Clave del sandbox",
    metodo: "Método",
    rutaDelContrato: "Ruta del contrato",
    elegirRuta: "Elige una de las {{n}} rutas",
    cargandoContrato: "Cargando el contrato…",
    ruta: "Ruta (rellena los {parámetros})",
    cuerpo: "Cuerpo (JSON)",
    enviar: "Enviar",
    enviando: "Enviando…",
    respuesta: "Respuesta {{estado}} en {{ms}} ms",
  },
  entornos: {
    titulo: "Entornos y despliegues",
    entradilla:
      "La configuración se promociona por paquetes. Esto dice qué hay puesto en cada " +
      "entorno y qué se ha tocado a mano por encima.",
    esProduccion: "producción",
    cargando: "Preguntando…",
    sinDesplegar: "No hay ningún paquete desplegado en este entorno",
    puesto: "paquete «{{paquete}}» v{{version}} · promocionado desde {{desde}}",
    sinOrigen: "ningún entorno (se desplegó directamente)",
    huella: "huella {{huella}} · {{git}}",
    sinGit: "sin referencia de Git",
    sePuedeVolver: "Se puede volver atrás a lo anterior.",
    noSePuedeVolver:
      "NO se puede volver atrás: no hay un despliegue anterior al que volver. Contar con el rollback el día que haga falta sería contar con algo que no existe.",
    sinMedirDrift:
      "No se ha podido medir si alguien ha tocado este entorno a mano. No es lo mismo que estar limpio: es que no se sabe.",
    limpio:
      "Sin cambios a mano: {{comparado}} elementos comparados y todos cuadran.",
    tocadoAMano:
      "{{cuantos}} elemento(s) cambiados a mano por encima del paquete. El siguiente despliegue los va a pisar sin avisar.",
    desaparecido:
      "{{cuantos}} elemento(s) que el paquete declara y ya no están en el entorno.",
    noComparado:
      "{{cuantos}} no se han podido comparar, así que este resultado no cubre el entorno entero.",
  },
  presupuesto: {
    aprobacion: "Aprobación",
    costeCambiado: "El coste ha cambiado desde que se ofertó.",
    costeLinea: "{{referencia}}: {{antes}} al ofertar, {{hoy}} hoy",
    costeIgual: "El coste sigue siendo el de cuando se ofertó.",
    costeSinComparar:
      "{{cuantas}} líneas no se pueden comparar: no tienen coste o no son de catálogo.",
    version: "versión {{version}}",
    necesitaAprobacion: "Esto no se puede mandar sin que alguien lo apruebe:",
    umbrales: "umbral de descuento {{umbral}} % · margen mínimo {{minimo}} %",
    numeros: "Los números",
    descuentoYMargen: "{{descuento}} de descuento · margen {{margen}}",
    sinMargen: "sin calcular",
    porqueSinMargen:
      "Sin coste en las líneas no hay margen que calcular, y un descuento sin margen al lado no se puede valorar.",
    valido: "Válido hasta el {{fecha}}",
    queCambio: "Qué cambió respecto de la anterior",
    porqueCambios:
      "Mandar la tercera versión sin saber qué lleva distinto de la segunda es como se acaba regalando un descuento que nadie aprobó.",
    sinCambios: "No se ha podido comparar con la versión anterior",
    esLaPrimera: "Es la primera versión: no hay con qué compararla.",
    totalAntesDespues: "total {{antes}} → {{ahora}}",
    deA: "{{antes}} → {{ahora}}",
    cantidadDeA: "cantidad {{antes}} → {{ahora}}",
    descuentoDeA: "descuento {{antes}} % → {{ahora}} %",
    cambio: {
      anadida: "añadida",
      quitada: "quitada",
      modificada: "modificada",
    },
    documento: "Cómo va a salir",
    porqueDocumento:
      "La plantilla, la marca y el idioma salen de la configuración. Descubrir en el correo del cliente que salió con la marca equivocada no tiene arreglo.",
    verDocumento: "Ver el documento antes de mandarlo",
    conQueSale:
      "plantilla «{{plantilla}}» · marca {{marca}} · idioma {{idioma}}",
    sinMarca: "la de por defecto",
    lineasDelDocumento: "{{cuantas}} líneas en el documento",
  },
  articulo: {
    version: "versión {{version}}",
    quienLoVe: "Quién lo puede ver",
    audiencia: {
      publicado:
        "Publicado. Según su audiencia, esto puede estar en el portal del cliente: un procedimiento interno con nombres de clientes dentro publicado hacia fuera es el error que no se recoge.",
      borrador:
        "No publicado. Mientras esté así no llega a ningún portal ni a ningún cliente, pase lo que pase con su audiencia.",
      enRevision:
        "Hay una versión nueva en revisión. Su audiencia sigue viendo la versión {{version}}, la publicada, hasta que se publique la nueva.",
    },
    votos: "{{utiles}} lo encontraron útil · {{inutiles}} no",
    toca_revisar:
      "Pasó su fecha de revisión. No se oculta a propósito: ocultarlo deja al cliente sin respuesta y enseñarlo sin avisar le da una que puede estar vieja.",
    obsoleto: "Marcado como obsoleto.",
    daniño:
      "Este artículo está entre los DAÑINOS: lo ve mucha gente y la mayoría dice que no sirve. No es que no se use — es que alguien lo está siguiendo. Corregirlo va antes que escribir uno nuevo.",
    huerfano:
      "Nadie lo usa ni lo cita en ningún caso. Puede que sobre, o que no se encuentre.",
    idiomas: "En qué idiomas está",
    porqueIdiomas:
      "El fallo caro de una base multilingüe: se corrige el original, las traducciones se quedan como estaban, y el cliente de otro idioma lee el procedimiento viejo durante meses.",
    sinTraducciones: "Sólo está en su idioma original",
    alDia: "al día",
    porDetras: "{{cuantas}} versiones por detrás",
    desincronizadas:
      "{{cuantas}} traducción(es) se han quedado atrás. Una versión por detrás suele ser una errata; seis ya es otro artículo.",
    eficacia: "Si el conocimiento sirve",
    conjunto:
      "{{publicados}} publicados · {{daninos}} dañinos · {{huerfanos}} huérfanos · {{caducados}} caducados",
    deflexion: "{{pct}} % de deflexión aproximada",
    sinDeflexion: "Deflexión: no se puede estimar",
  },
  campana: {
    gasto: "{{gasto}} gastado ({{propio}} propio · {{hijos}} en tácticas)",
    sinPresupuesto: "sin presupuesto declarado",
    consumido: "{{pct}} % del presupuesto",
    sobrepasado:
      "Se ha pasado del presupuesto. Restante: {{restante}}. Lo que sigue gastándose no lo cubre nadie.",
    planVsReal: "Lo que prometió y lo que va",
    porquePlan:
      "Un número sin su objetivo al lado no dice nada: 400 clics es bueno si prometía 300 y malo si prometía 2.000.",
    sinObjetivos: "Esta campaña no declaró objetivos",
    deObjetivo: "{{real}} de {{objetivo}}",
    noComparable: "objetivo {{objetivo}} · el embudo no mide esto",
    coste: "Lo que ha costado",
    sinRendimiento: "Todavía no se puede calcular el rendimiento",
    porLead: "{{lead}} por lead · {{conversion}} por conversión",
    roi: "ROI {{pct}} %",
    roiNoMedible: "ROI: no se puede medir",
    embudo: "Por dónde va cada uno",
    sinEmbudo: "Esta campaña no tiene miembros todavía",
    miembros: "{{miembros}} dentro · {{excluidos}} excluidos por supresión",
    enEstado: "{{estado}}: {{cuantos}}",
    quienes: "Los {{cuantos}} en «{{estado}}»",
    evento: "Si apareció la gente",
    asistencia:
      "{{inscritos}} inscritos · {{asistieron}} asistieron · {{faltaron}} no aparecieron · aforo {{aforo}}",
    sinMarcar:
      "{{cuantos}} inscritos sin marcar. Una tasa de asistencia calculada ignorándolos es una tasa inventada.",
    tasa: "{{pct}} % de asistencia",
    tasaNoMedible: "Asistencia: no se puede medir",
  },
  grc: {
    titulo: "Panel de cumplimiento",
    entradilla:
      "El módulo de gobierno lista los riesgos y los controles. Esto contesta otra cosa: " +
      "si lo que hay se puede medir, qué no cuadra hoy y qué del producto no vigila nadie.",
    cobertura: "Cobertura",
    sinMedir: "sin medir",
    pct: "{{pct}} %",
    verificada: "Verificada: {{pct}} %",
    irAControles: "Controles del GRC",
    riesgosAbiertos: "Riesgos abiertos",
    controlesActivos: "Controles activos",
    controlesEvaluados: "Evaluados",
    urgente: "Lo que no cuadra hoy",
    nadaUrgente: "Nada pendiente: todo lo declarado está evaluado y en plazo",
    nadaQueMirar:
      "No hay nada que mirar todavía, que no es lo mismo que estar bien",
    informeCobertura: "Qué capacidades del producto tienen control",
    sinCobertura: "No se puede medir la cobertura todavía",
    alcance:
      "{{alcance}}: {{capacidades}} capacidades, {{con}} con control y {{sin}} sin ninguno",
    huerfanos:
      "{{cuantos}} control(es) apuntan a una capacidad que no existe en el catálogo. Constan como cobertura y no cubren nada: es peor que no tener control, porque nadie los echa de menos.",
    deTotal: "{{con}}/{{total}} · {{pct}} %",
    marcos: "De la norma al producto",
    porqueMarcos:
      "Un auditor pregunta por ISO 27001 A.9 y esto contesta qué controles responden y qué capacidades los sostienen. El camino de vuelta —de una capacidad a sus obligaciones— sale del mismo dato.",
    sinMarcos: "Ningún control declara a qué marco responde",
    control: "{{codigo}} ({{capacidades}} capacidades · {{resultado}})",
    sinEvaluar: "sin evaluar",
  },
  ciclovida: {
    titulo: "Ciclo de vida del cliente",
    entradilla:
      "Clonar, fusionar o partir un cliente saca sus datos de donde están protegidos. " +
      "Todo se simula antes, y aquí está lo simulado y lo hecho.",
    ventanaAbierta:
      "{{cuantas}} migración(es) con la ventana de solo lectura ABIERTA ahora mismo. Mientras lo esté, ese cliente no puede escribir.",
    hechas: "Lo que se ha hecho",
    porqueHechas:
      "Estas ya movieron datos. Una fallida se queda aquí con su motivo: saber qué se intentó es parte de saber qué hay.",
    sinHechas: "No se ha ejecutado ninguna operación sobre este cliente",
    movio: "{{bloques}} bloques · {{filas}} filas",
    conflictos: "{{cuantos}} conflicto(s) sin resolver",
    simuladas: "Lo que se ha simulado y no se ha hecho",
    porqueSimuladas:
      "Una simulada NO ha movido nada. Va aparte porque en una lista corrida ocupa una línea igual que una ejecutada, y eso se lee mal justo cuando importa.",
    sinSimuladas: "No hay simulaciones pendientes",
    sacaria: "sacaría {{bloques}} bloques · {{filas}} filas",
    migraciones: "Migraciones de modalidad de aislamiento",
    porqueMigraciones:
      "Cambiar de modalidad abre una ventana de solo lectura sobre los datos del cliente. Se verifican los recuentos a los dos lados antes de cerrarla.",
    sinMigraciones: "No hay ninguna migración registrada",
    deA: "{{desde}} → {{hacia}}",
    ventanaDesde: "solo lectura desde {{desde}} · {{minutos}} min previstos",
    ventanaPrevista: "{{minutos}} min de ventana previstos",
    diferencias: "{{cuantas}} diferencia(s) entre origen y destino",
    perfiles: "Preconfiguraciones por industria",
    porquePerfiles:
      "Lo que se le deja montado a un cliente nuevo. Se aplica sin pisar lo que ya haya: un perfil que sobreescribe es un perfil que nadie se atreve a aplicar dos veces.",
    sinPerfiles: "No hay ningún perfil de industria declarado",
  },
  canales: {
    titulo: "Por dónde entran los casos",
    entradilla:
      "Cada canal es una puerta declarada. Lo que decide no es cuántos han entrado: " +
      "es qué se ha tirado y por qué.",
    sinCanales: "No hay ningún canal de entrada declarado",
    sinCanalesDetalle:
      "Sin canales, los casos sólo se abren a mano. Un canal declara de dónde llega un mensaje y cómo se traduce en un caso.",
    escuchando: "escuchando",
    apagado: "apagado",
    cifras: "{{recibidos}} recibidos · {{descartados}} descartados",
    motivo: {
      trampa: "{{cuantos}} por la trampa",
      automatico: "{{cuantos}} respuestas automáticas",
      propio: "{{cuantos}} eco propio",
      tope: "{{cuantos}} pasados de tope",
      incompleto: "{{cuantos}} incompletos",
    },
    sinMotivo: "{{cuantos}} sin motivo apuntado",
    trampaManda:
      "La trampa es lo que más descarta en este canal. Revisa el campo: un descarte por trampa contesta «aceptado» a propósito, así que si está mal puesto se está comiendo mensajes de clientes y nadie lo va a notar.",
    tope: "Tope por hora",
    propia: "Dirección propia",
    sinPropia: "sin declarar",
    trampa: "Campo trampa",
    sinTrampa: "sin trampa",
    obligatorios: "Obligatorios",
    ninguno: "ninguno",
    sinEco:
      "Este canal de correo no declara su propia dirección, así que no puede cortar su propio eco: el buzón puede acabar contestándose a sí mismo.",
    mapea: "Traduce {{cuantos}} campos de entrada",
  },
  segmento: {
    dinamico: "dinámico",
    congeladoEtiqueta: "foto congelada",
    cuantos: "A cuánta gente le llega",
    sinRecuento: "No se ha podido calcular el tamaño ahora mismo",
    deLosCuales: "de {{bruto}} en bruto; {{suprimidos}} caen por supresión",
    calculado: "calculado el {{fecha}}",
    esFoto:
      "Este número es una foto: el segmento no se recalcula. Lo que ves es lo que se congeló.",
    congelar: "Congelar en una lista fija",
    congelando: "Congelando…",
    congelado: "Congelado con {{cuantos}} miembros. Deja de recalcularse.",
    porqueCongelar:
      "Se congela ANTES de un envío, no después: «¿a quién se le mandó?» tiene que poder contestarse en junio con la lista de marzo, y un segmento dinámico en junio devuelve otra gente.",
    solapamiento: "Cuánta gente comparte con otro",
    porqueSolape:
      "La pregunta no es de estadística: es «si lanzo las dos campañas esta semana, ¿a cuánta gente le llegan las dos?».",
    contra: "Contra qué segmento",
    elegirOtro: "Elige otro segmento",
    medir: "Medir",
    midiendo: "Midiendo…",
    pctDeCada: "{{a}} % de éste y {{b}} % del otro",
    solos: "{{a}} sólo en éste · {{b}} sólo en el otro",
    definicion: "Qué condiciones lo definen",
    porqueDefinicion:
      "Un segmento es una definición, no una lista. Guardar la lista parece más rápido y es lo que hace que a la semana esté desfasada sin que nadie lo sepa.",
    excluye: "Resta los miembros de {{cuantos}} segmento(s)",
    y: "y",
    o: "o",
    no: "ninguna de",
  },
  // Marketing › Segmentos › Nuevo: la definición montada con desplegables.
  constructorSegmento: {
    sinOtros: "No hay otros segmentos de {{objeto}} que restar.",
    eligeObjeto:
      "Elige primero sobre qué se segmenta —contacto, lead o cuenta— para ver por qué se puede filtrar.",
    quienCumpla: "Quien cumpla",
    deEstas: "de estas condiciones",
    modo: { y: "todas", o: "alguna", ninguna: "ninguna" },
    modoDe: "Cómo se combinan las condiciones del grupo {{numero}}",
    vacio: "Sin condiciones todavía.",
    anadirCondicion: "Añadir una condición",
    anadirGrupo: "Añadir un grupo",
    quitar: "Quitar",
    quitarCondicion: "Quitar la condición {{numero}}",
    quitarGrupo: "Quitar el grupo {{numero}}",
    elegirAtributo: "Elige un dato…",
    atributoDe: "Dato de la condición {{numero}}",
    operadorDe: "Comparación de la condición {{numero}}",
    valorDe: "Valor de la condición {{numero}}",
    separadosPorComas: "valores separados por comas",
    dias: "días",
    si: "sí",
    no: "no",
    op: {
      igual: "es",
      distinto: "no es",
      en: "es uno de",
      noEn: "no es ninguno de",
      mayor: "mayor que",
      mayorIgual: "mayor o igual que",
      menor: "menor que",
      menorIgual: "menor o igual que",
      vacio: "está vacío",
      noVacio: "tiene valor",
      haceMenosDeDias: "hace menos de (días)",
      haceMasDeDias: "hace más de (días)",
    },
    atributo: {
      nombre: "Nombre",
      email: "Correo",
      telefono: "Teléfono",
      estado: "Estado",
      sector: "Sector",
      empleados: "Empleados",
      facturacion: "Facturación anual",
      cargo: "Cargo",
      pais: "País",
      origen: "Origen",
      owner_id: "Propietario",
      cuenta_id: "Cuenta",
      alta_at: "Fecha de alta",
      ultima_actividad_at: "Última actividad",
    },
    objeto: { contacto: "contactos", lead: "leads", cuenta: "cuentas" },
    llegaria: "Llegaría a {{cuantos}} {{objeto}}",
    desglose:
      "de {{bruto}} en bruto; {{suprimidos}} caen por supresión o por no tener correo",
    calculando: "Calculando…",
    sinEstimacion:
      "Añade una condición completa para ver a cuánta gente llegaría.",
    perfiles:
      "Contado sobre {{cuantos}} {{objeto}}; el dato más viejo es del {{fecha}}.",
    sinPerfiles: "Todavía no hay {{objeto}} en los datos de marketing.",
    sincronizar: "Poner al día los datos",
    sincronizando: "Poniendo al día…",
    sincronizado: "Datos al día con cuentas, contactos y leads.",
    sincronizadoAMedias:
      "No se pudieron leer enteros: {{objetos}}. Esos se quedan como estaban.",
  },
  puntuacion: {
    titulo: "Por qué este lead tiene esta puntuación",
    interes: "Interés",
    encaje: "Encaje con el cliente ideal",
    umbralEs: "umbral: {{umbral}}",
    sinUmbral: "el modelo no declara umbral en este eje",
    sinFactores: "Ninguna regla ha sumado por este eje",
    gradoDesde: "{{grado}} (desde {{desde}} de encaje)",
    yaEsSql: "Ya es SQL: no hay escalón por encima.",
    inactividad: "Lo que se ha perdido por inactividad",
    perdidos:
      "{{puntos}} puntos de interés perdidos por inactividad. El encaje no decae: sale de quién es, no de lo que hace.",
    sinDecaer: "No ha perdido nada por inactividad.",
    reglaDecaimiento:
      "El modelo resta {{puntos}} puntos de interés cada {{dias}} días sin actividad, y nunca baja de {{minimo}}.",
    ultimaActividad: "Última actividad: {{fecha}}",
    sinActividad: "Sin ninguna actividad registrada.",
    tramos: "Los tramos de encaje",
    porqueTramos:
      "Un grado sin sus tramos es una letra. Con ellos se puede discutir si el tramo está bien puesto.",
    tramo: "{{grado}} desde {{desde}}",
  },
  conocimiento: {
    titulo: "Conocimiento",
    entradilla:
      "Lo publicado se distingue de lo que está en revisión: un artículo a medias " +
      "que se lee como bueno acaba pegado en una respuesta a un cliente.",
    buscar: "Buscar por título",
    sinResultados: "Ningún artículo coincide",
    enPortal: "En el portal",
    borrador: "borrador v{{version}}",
    vistas: "{{vistas}} vistas",
  },
  conversacion: {
    macro: "Respuesta rápida o macro",
    elegirMacro: "Elegir una…",
    macroOtroCanal: "{{nombre}} (de otro canal)",
    aplicarMacro: "Aplicar",
    aplicando: "Aplicando…",
    macroAplicada: "Aplicada «{{nombre}}»: la respuesta está en el hilo.",
    sinAsunto: "(sin asunto)",
    entradilla:
      "Todo lo que este cliente ha hablado con nosotros, por cualquier canal y " +
      "ordenado por tiempo. No agrupado por canal: agrupar es lo que hace que se " +
      "le pregunte tres veces lo mismo.",
    porBot: "la atiende el bot",
    sinHilo: "Sin mensajes todavía",
    sinHiloDetalle:
      "Esta conversación no está ligada a ningún cliente, así que no hay " +
      "historial que traer.",
    delCliente: "del cliente",
    nuestro: "nuestro",
    interna: "nota interna",
    soloLectura:
      "Puedes leer la conversación; responder necesita permiso de escritura.",
    respuesta: "Respuesta",
    esNotaInterna:
      "Es una nota interna (no se manda al cliente ni cuenta como primera respuesta)",
    responder: "Responder al cliente",
    dejarNota: "Dejar la nota",
    escalar: "Escalar a una persona",
    cambiarCanal: "Cambiar de canal",
    elegirCanal: "Elegir canal…",
    motivo: "Motivo",
    transferir: "Cambiar",
    transferirDetalle:
      "Cambiar de canal no abre una conversación nueva: el hilo se conserva.",
    hecho: {
      responder: "Mandado.",
      "escalar-a-humano": "Escalado a una persona con todo el contexto.",
      transferir: "Canal cambiado. El hilo sigue siendo el mismo.",
    },
  },
  // Lecciones aprendidas de las oportunidades cerradas (05-11-2026).
  tcsec: {
    titulo: "Clasificación TCSEC",
    entradilla:
      "Qué nivel de confianza alcanza esta instalación según los criterios TCSEC (D, C1, C2, B1, B2, B3, A1). Lo que se puede medir se mide ahora mismo sobre el sistema; lo demás lo atestigua una persona, con su evidencia.",
    medir: "Volver a medir",
    midiendo: "Midiendo…",
    descargar: "Descargar el informe",
    descargado: "Descargado {{fichero}}.",
    nivel: "Nivel alcanzado",
    escala: "Niveles TCSEC, de menos a más exigente",
    alcanzado: "La instalación alcanza {{nivel}}: {{nombre}}.",
    falta_one: "Para {{siguiente}} falta un requisito, marcado abajo.",
    falta_other:
      "Para {{siguiente}} faltan {{count}} requisitos, marcados abajo.",
    medidoEl: "Medido el {{fecha}}.",
    medido: "medido",
    atestiguado: "atestiguado",
    estados: {
      cumple: "Cumple",
      no_cumple: "No cumple",
      sin_medir: "Sin medir",
      no_implementado: "No implementado",
    },
    atestiguar: "Atestiguar",
    resultado: "Resultado",
    resultados: {
      efectivo: "Se cumple",
      parcial: "Se cumple en parte",
      inefectivo: "No se cumple",
      no_aplica: "No aplica",
    },
    evidencia: "Evidencia",
    evidenciaAyuda: "Qué se revisó y dónde está la prueba",
    plan: "Plan de acción",
    guardar: "Guardar la atestación",
    dejarEnGrc: "Dejar la medida en el GRC",
    enElGrc: "Medida guardada como evidencia de {{n}} controles TCSEC del GRC.",
    suControl: "Control {{codigo}}",
  },
  controlesGrc: {
    titulo: "Controles del GRC",
    entradilla:
      "Todo lo que hay en la aplicación, con su control: uno por familia del catálogo, uno por regla de segregación, uno por requisito TCSEC y el de la revisión de accesos. Cada uno con la evidencia que pone el sistema al evaluarlo.",
    instalar: "Instalar los de serie",
    instalados: "{{n}} controles de serie instalados o puestos al día.",
    sincronizar: "Traer la segregación",
    sincronizada:
      "{{reglas}} reglas en el GRC: {{abiertos}} hallazgos abiertos y {{evidencias}} excepciones como evidencia.",
    evaluar: "Evaluar los automáticos",
    trabajando: "Evaluando…",
    evaluados: "{{n}} controles: {{detalle}}.",
    anclada: "Cobertura anclada",
    ancladaAyuda:
      "Capacidades hechas con un control activo. Sube al instalar: dice lo declarado.",
    verificada: "Cobertura verificada",
    verificadaAyuda:
      "Capacidades cuyo control dio por buena una evaluación en plazo: dice lo comprobado.",
    deTotal: "{{n}} de {{total}} ({{pct}} %)",
    sinMedir: "sin medir",
    hallazgos: "Hallazgos abiertos",
    hallazgosAyuda: "Lo que un control ha encontrado mal y sigue sin resolver.",
    deSerie: "Controles de serie",
    instaladosDe: "{{n}} de {{total}}",
    deSerieAyuda: "Reinstalar trae los nuevos y no pisa lo ajustado.",
    controles: "Controles",
    origen: "Origen",
    todos: "Todos",
    origenes: {
      familia: "Familia del catálogo",
      segregacion: "Segregación",
      tcsec: "TCSEC",
      recertificacion: "Revisión de accesos",
      manual: "Escrito a mano",
    },
    irA: {
      familia: "Ver la cobertura",
      segregacion: "Ir a la regla",
      tcsec: "Ir al requisito",
      recertificacion: "Ir a las campañas",
    },
    control: "Control",
    ultima: "Última evaluación",
    capacidades: "Capacidades",
    activo: "Activo",
    activarControl: "Activar el control {{codigo}}",
    ajustado: "ajustado",
    ver: "ver",
    nuncaEvaluado: "Nunca evaluado",
    sinControles: "No hay controles con ese origen.",
    resultados: {
      efectivo: "Efectivo",
      parcial: "Parcial",
      inefectivo: "Inefectivo",
      no_aplica: "No aplica",
      sin_evaluar: "Sin poder medir",
    },
    hallazgosAbiertos: "Hallazgos abiertos",
    sinHallazgos: "Ningún hallazgo abierto.",
    riesgoDesde: "· riesgo {{riesgo}} · desde el {{fecha}}",
    evaluarEste: "Evaluar ahora",
    evaluadoComo: "Evaluado: {{resultado}}.",
    noEvaluado: "No se ha evaluado: {{motivo}}",
    cerrar: "Cerrar",
    fuente: "Fuente de evidencia",
    aMano: "la aporta una persona",
    frecuencia: "Frecuencia",
    marcos: "Marcos",
    ultimaEval: "Última evaluación",
    elDia: "el {{fecha}}; la siguiente toca el {{proxima}}",
    verEvidencia: "Ver la evidencia",
    evidencias: "Evidencias con caducidad",
    sinEvidencias: "Ninguna evidencia con caducidad.",
    abierto: "Abierto",
    cierres: { resuelto: "Resuelto", exceptuado: "Exceptuado" },
    hasta: "Vale hasta el {{fecha}}",
    caducada: "Caducó el {{fecha}}",
  },
  organigrama: {
    titulo: "Organigrama",
    entradilla:
      "Quién depende de quién. De aquí sale a quién le toca aprobar un presupuesto —el superior de quien lo envía— y quién revisa los accesos de cada persona. Cambiar el superior de alguien lo mueve con todo su equipo.",
    resumen:
      "{{personas}} personas · {{sinSuperior}} en activo sin superior · {{scim}} desde el directorio (SCIM) · {{mano}} ajustadas a mano.",
    externoManda:
      "Lo que manda el directorio por SCIM pisa lo ajustado a mano: si una persona llega del directorio con otro superior, gana el del directorio. Se cambia con el ajuste organigrama_externo_manda.",
    manoManda:
      "Lo ajustado a mano se queda aunque el directorio mande otro superior; lo que nadie ha tocado sigue al directorio. Se cambia con el ajuste organigrama_externo_manda.",
    truncado:
      "Se enseñan las {{tope}} primeras personas por nombre (ajuste organigrama_tope_personas): el árbol está incompleto.",
    arbol: "Árbol",
    buscar: "Buscar a una persona",
    nadieCoincide: "Nadie se llama así.",
    vacio: "Esta empresa aún no tiene personas.",
    enCirculo:
      "{{n}} personas forman un círculo (cada una depende de otra del mismo grupo) y no cuelgan de nadie: elige un superior para una de ellas.",
    directos: "{{n}} directos",
    baja: "De baja",
    deScim: "Del directorio",
    aMano: "Ajustado a mano",
    persona: "Persona",
    elige: "Elige a alguien en el árbol para ver o cambiar de quién depende.",
    fijadoEl: "Fijado el {{cuando}} por {{quien}}.",
    alguien: "alguien que ya no está",
    scimLoPisa:
      "Lo manda el directorio: cambiarlo aquí dura hasta su próximo envío.",
    scimNoLoPisa:
      "Lo manda el directorio; si lo cambias aquí, el directorio deja de poder cambiarlo.",
    superior: "Depende de",
    sinSuperior: "Nadie (raíz)",
    superiorAyuda:
      "No salen ni ella ni las {{n}} personas de su equipo: cualquiera de ellas cerraría un círculo.",
    guardar: "Guardar superior",
    colgada: "{{persona}} depende ahora de {{superior}}, con todo su equipo.",
    deRaiz: "{{persona}} ya no depende de nadie.",
    suEquipo: "Su equipo directo: {{n}}",
    sinEquipo: "Nadie depende directamente de esta persona.",
    moverA: "Pasar todo su equipo directo a",
    moverEquipo: "Mover el equipo",
    nadie: "Nadie (quedan de raíz)",
    equipoMovido: "Movidas {{n}} personas a {{destino}}.",
    dependeDe: "depende de {{superior}}",
  },
  revisionAccesos: {
    titulo: "Revisión de accesos",
    entradilla:
      "Cada responsable confirma o retira los accesos de su gente, con un plazo. Lo retirado se quita en el momento; lo no contestado a tiempo se marca y se avisa. El resultado es la evidencia del control de accesos del GRC.",
    control: "Su control en el GRC",
    loQueLeeElGrc:
      "El GRC lee la última campaña cerrada: «{{nombre}}», el {{fecha}} — {{confirmados}} confirmados, {{retirados}} retirados y {{vencidas}} sin contestar a tiempo.",
    grcSinCampana:
      "Todavía no hay ninguna campaña cerrada: el control de accesos del GRC sale como no efectivo.",
    nueva: "Lanzar una campaña",
    nuevaAyuda:
      "Una revisión por cada rol y conjunto de permisos de cada persona activa, para su superior. Quien no tiene superior va al revisor por defecto.",
    nombre: "Nombre de la campaña",
    nombreEjemplo: "Revisión del cuarto trimestre",
    plazo: "Plazo en días",
    plazoDefecto: "El de la empresa",
    revisor: "Revisor por defecto",
    revisorYo: "Yo mismo",
    lanzar: "Lanzar",
    lanzada:
      "Campaña lanzada: {{total}} accesos para {{responsables}} responsables, hasta el {{plazo}}.",
    campanas: "Campañas",
    sinCampanas: "No se ha lanzado ninguna campaña.",
    campana: "Campaña",
    plazoCol: "Plazo",
    avance: "Avance",
    avanceTexto:
      "{{confirmados}} confirmados · {{retirados}} retirados · {{pendientes}} pendientes ({{responsables}} responsables)",
    vencidas: "Fuera de plazo",
    estados: { abierta: "Abierta", cerrada: "Cerrada" },
    avisar: "Marcar y avisar lo vencido",
    avisadas: "Lo vencido está marcado y sus responsables avisados.",
    cerrar: "Cerrar",
    cerrada: "Campaña «{{nombre}}» cerrada.",
    detalle: "Por responsable",
    responsable: "{{nombre}} — {{n}} pendientes",
    tipos: { rol: "Rol", conjunto: "Conjunto de permisos" },
    decisiones: {
      pendiente: "Pendiente",
      confirmado: "Confirmado",
      retirado: "Retirado",
    },
    fueraDePlazo: "fuera de plazo",
  },
  historialAjustes: {
    titulo: "Historial de la configuración",
    entradilla:
      "Cada cambio de un ajuste, con su valor de antes y el de después, quién y cuándo. Compara dos versiones, mira qué cambió entre dos fechas y vuelve al valor de antes de un cambio: volver queda como un cambio más, no borra nada.",
    historial: "Cambios",
    ajuste: "Ajuste",
    todos: "Todos los ajustes con cambios",
    opcionClave_one: "{{clave}} · 1 cambio",
    opcionClave_other: "{{clave}} · {{count}} cambios",
    comparar: "Comparar las dos elegidas",
    compararAyuda:
      "Marca dos versiones del mismo ajuste para ver qué cambió entre ellas.",
    elegir: "Elegir para comparar",
    sinCambios: "Este ajuste no tiene cambios guardados",
    cuando: "Cuándo",
    ambito: "Ámbito",
    antes: "Antes",
    despues: "Después",
    tipo: "Tipo",
    volver: "Volver a antes",
    confirmarVolver:
      "¿Volver «{{clave}}» al valor que tenía antes de este cambio ({{valor}})? Se aplica a toda la empresa y queda en el historial.",
    vuelto: "«{{clave}}» ha vuelto a {{valor}}.",
    diferencias: "Diferencias en «{{clave}}»",
    entre: "Entre la versión del {{desde}} y la del {{hasta}}.",
    iguales: "Las dos versiones dejaron el mismo valor",
    entrada: "Entrada",
    valorEntero: "El valor entero",
    rango: "Qué cambió entre dos fechas",
    rangoAyuda:
      "Por ajuste, de dónde salió y dónde acabó. Lo que acabó igual que empezó no sale: no cambió nada.",
    desde: "Desde",
    hasta: "Hasta (vacío: ahora)",
    verRango: "Ver qué cambió",
    nadaEnRango: "No cambió nada en ese intervalo",
    nCambios: "Cambios",
    tipos: { cambio: "Cambio", vuelta_atras: "Vuelta atrás" },
    cambios: { cambiado: "Cambiado", anadido: "Añadido", quitado: "Quitado" },
    ambitos: {
      global: "Instalación",
      tier: "Tier",
      tenant: "Empresa",
      bu: "Unidad",
      usuario: "Persona",
    },
  },
  grupoEmpresas: {
    titulo: "Grupo de empresas",
    entradilla:
      "De qué empresa cuelga esta y cuáles cuelgan de ella, con su relación. Cada empresa hija decide qué ve su matriz —sólo cifras sumadas, nunca registros—, y lo que no comparte sale dicho, no como cero.",
    arbol: "Árbol",
    verArbolDe: "Ver el árbol de",
    sola: "Esta empresa no cuelga de ninguna ni tiene empresas hijas",
    comparteCon: "comparte con su matriz: {{que}}",
    noComparte: "no comparte nada con su matriz",
    queComparto: "Qué ve mi matriz de esta empresa",
    quecompartoAyuda:
      "Lo decide esta empresa y sólo ella: ni la matriz ni la plataforma pueden concederlo. Si cambia de matriz, se borra.",
    sinPadre: "Esta empresa no cuelga de ninguna: no hay con quién compartir.",
    guardarComparticion: "Guardar lo que comparto",
    compartidoGuardado: "Guardado lo que esta empresa comparte con su matriz.",
    agregado: "Lo que veo de mis empresas hijas",
    agregadoAyuda:
      "De cada empresa que cuelga de esta, sólo lo que ella ha compartido, y los totales del grupo.",
    sinHijas: "No cuelga ninguna empresa de esta",
    empresa: "Empresa",
    relacion: "Relación",
    noCompartido: "No compartido",
    sinLeer: "no se ha podido leer",
    totales: "Totales de lo compartido",
    noComparten: "No comparten nada: {{nombres}}",
    colgar: "Colgar una empresa de otra",
    colgarAyuda:
      "Sólo la plataforma. Al cambiar de matriz se borra lo que la empresa compartía: lo autorizó para la anterior.",
    cuelgaDe: "Cuelga de",
    deNinguna: "De ninguna",
    guardarColgar: "Guardar",
    colgada: "Jerarquía guardada.",
    relaciones: {
      matriz_filial: "Matriz–filial",
      franquicia: "Franquiciador–franquiciado",
      holding: "Holding",
    },
    compartible: { consumo: "Consumo", indicadores: "Indicadores" },
  },
  consumoFacturacion: {
    titulo: "Consumo para facturación",
    entradilla:
      "Lo que lleva gastado esta empresa en cada módulo, en un formato que entiende cualquier sistema de cobro —periodo, módulo, métrica, cantidad, unidad y tope—. Se descarga o se manda al sistema de facturación configurado, y cada envío dice cómo fue.",
    tomar: "Tomar el corte ahora",
    tomarYEnviar: "Tomar y enviar",
    tomado: "corte de {{periodo}} tomado",
    destino: "Sistema de facturación",
    destinoConfigurado:
      "Se manda a {{maquina}}, en {{formato}}, firmado como un webhook.",
    sinDestino:
      "No hay sistema de facturación configurado: los cortes se pueden descargar, pero no se mandan. Se configura en los ajustes «facturacion_destino_url» y «facturacion_destino_cabeceras».",
    periodicaSi:
      "Se toma un corte solo en cada vuelta de la tarea y se manda el del periodo al cerrarlo (hasta {{n}} intentos).",
    periodicaNo:
      "Los cortes periódicos están apagados (ajuste «facturacion_exportar_periodicamente»).",
    columnas: "Columnas: {{columnas}}",
    cortes: "Cortes",
    sinCortes: "Todavía no se ha tomado ningún corte",
    periodo: "Periodo",
    tomadoEl: "Tomado",
    origen: "Origen",
    filas: "Filas",
    envio: "Envío",
    incompleto: "Incompleto: sin leer {{modulos}}",
    intentos_one: "1 intento",
    intentos_other: "{{count}} intentos",
    enviar: "Enviar",
    reenviar: "Reenviar",
    csv: "CSV",
    json: "JSON",
    descargado: "Descargado {{fichero}}.",
    origenes: { manual: "A mano", programado: "Periódico" },
    estados: {
      pendiente: "Pendiente de enviar",
      enviado: "Enviado",
      fallido: "Falló el envío",
      sin_destino: "Sin destino configurado",
      abierto: "Periodo en curso",
    },
  },
  analisisCrm: {
    titulo: "Embudo, cohortes y actividad",
    entradilla:
      "Análisis calculados con los datos del CRM —del almacén analítico si está cargado, si no de cada módulo con tus permisos—, las fotos periódicas de un informe y la consulta al lake del cliente sin copiarlo.",
    objetos: {
      cuenta: "Cuentas",
      actividad: "Actividades",
      oportunidad: "Oportunidades",
      historial_etapas: "Historial de etapas",
      embudos: "Embudos",
    },
    deLaApi: "{{n}} leídas de la aplicación",
    delAlmacen: "{{n}} del almacén analítico",
    sinPermiso: "sin permiso para leerlas",
    noLeido: "no se han podido leer (respuesta {{codigo}})",
    recortado: "recortado al tope",
    embudo: "Embudo de ventas",
    embudoAyuda:
      "Cuántas oportunidades llegaron a cada etapa, qué parte pasó de la anterior y la mediana de días que tardaron. Llegar a una etapa cuenta como haber pasado por las anteriores; lo abierto no cuenta como perdido.",
    elegirEmbudo: "Embudo",
    sinEmbudo: "No hay ningún embudo de ventas que se pueda leer.",
    embudoResumen:
      "{{n}} oportunidades creadas desde el {{desde}}, {{abiertos}} siguen abiertas.",
    mayorCaida: "Donde más se pierde: «{{etapa}}» ({{pct}} % pasa).",
    etapa: "Etapa",
    llegaron: "Llegaron",
    conversion: "Pasan de la anterior",
    caidos: "Se quedaron",
    diasMediana: "Días (mediana)",
    cohortes: "Retención por cohorte",
    cohortesAyuda:
      "Cuentas agrupadas por cuándo se dieron de alta, y qué parte tuvo actividad u oportunidades en cada periodo siguiente.",
    periodo: "Agrupar por",
    periodos: { semana: "Semana", mes: "Mes", trimestre: "Trimestre" },
    periodoN: "+{{n}}",
    cohorte: "Cohorte",
    cuentas: "Cuentas",
    sinCohortes: "No hay cuentas con fecha de alta.",
    inmaduro: "El periodo aún no ha terminado",
    pocoSignificativo: "Menos de {{n}} cuentas: no da porcentaje",
    cohortesLeyenda:
      "Sin porcentaje: «…» es un periodo que no ha terminado; un número suelto es una cohorte de menos de {{n}} cuentas, que no da un porcentaje fiable.",
    actividad: "Actividad frente a resultados",
    actividadAyuda:
      "Por persona: actividades asignadas y oportunidades ganadas en la misma ventana de tiempo.",
    coeficiente:
      "Correlación {{fuerza}} ({{r}}) entre actividad y oportunidades ganadas, con {{n}} personas.",
    persona: "Persona",
    actividades: "Actividades",
    ganadas: "Ganadas",
    ventana: "Del {{desde}} al {{hasta}}.",
    sinPersonas:
      "Nadie tiene actividades ni oportunidades asignadas en la ventana.",
    instantaneas: "Instantáneas programadas",
    instantaneasAyuda:
      "Una foto de lo que dice el informe cada día, semana o mes, para poder contestar «¿cómo íbamos entonces?». Se guarda el resumen, no las filas.",
    sinInformes: "No hay informes definidos todavía.",
    informe: "Informe",
    cada: "Cada",
    periodicidades: {
      diaria: "Cada día",
      semanal: "Cada semana",
      mensual: "Cada mes",
    },
    hora: "Hora",
    horaEnZona: "Hora ({{zona}})",
    aLas: "a las {{h}} h",
    aLasEnZona: "a las {{h}} h ({{zona}})",
    programar: "Programar la instantánea",
    tomarAhora: "Tomar una ahora",
    programada: "Instantánea programada.",
    tomada: "Instantánea tomada.",
    quitada: "Programación quitada. Las instantáneas ya tomadas se quedan.",
    quitar: "Quitar",
    proxima: "Próxima: {{cuando}}",
    sinProgramar: "Este informe no tiene ninguna instantánea programada.",
    tendencia: "Tendencia",
    dia: "Día",
    filas: "Filas",
    puntos: "{{n}} instantáneas.",
    sinInstantaneas: "Sin instantáneas todavía.",
    federada: "Consulta al lake del cliente",
    federadaAyuda:
      "Se pregunta a la fuente declarada por su conexión, en lectura, con su tope de filas y su tiempo máximo. No se copia nada al CRM.",
    sinFuentes:
      "No hay ninguna fuente federada declarada. Se declaran en Informes › Fuentes federadas.",
    fuente: "Fuente",
    objeto: "Objeto",
    campos: "Campos",
    camposAyuda: "todos, o separados por comas",
    limite: "Filas (tope {{tope}})",
    consultar: "Consultar",
    resultadoFederado: "{{n}} filas en {{ms}} ms, consultadas el {{cuando}}.",
    recortadoA: "Recortado a {{n}}: la fuente tiene más.",
  },
  segregacion: {
    titulo: "Segregación de funciones",
    entradilla:
      "Qué permisos no pueden coincidir en una misma persona, qué roles los juntan, quién está hoy en conflicto y qué pasaría si se le da un rol a alguien.",
    deSerie: "Cargar las reglas de serie",
    cargadas: "Se han añadido {{n}} reglas.",
    suControl: "Su control preventivo en el GRC",
    matriz: "Reglas contra roles",
    matrizAyuda:
      "A: el rol da un lado de la regla. B: el otro. A+B: el rol da los dos, y cualquiera que lo tenga está en conflicto; se arregla en el rol.",
    sinReglas: "No hay reglas de segregación. Carga las de serie para empezar.",
    regla: "Regla",
    personas: "Personas en conflicto",
    celda: { a: "Da el lado A", b: "Da el lado B", ambos: "Da los dos lados" },
    niveles: { bajo: "Bajo", medio: "Medio", alto: "Alto", critico: "Crítico" },
    conflictos: "Quién está en conflicto hoy",
    sinConflictos: "Nadie tiene hoy permisos incompatibles.",
    exceptuado: "Con excepción vigente",
    exceptuar: "Aprobar una excepción",
    porQue: "Por {{a}} y por {{b}}",
    motivo: "Por qué se acepta",
    caduca: "Hasta cuándo",
    aprobar: "Aprobar",
    simulador: "Antes de dar un rol",
    simuladorAyuda:
      "Elige a la persona y los roles que le darías: dice qué reglas pasaría a incumplir. No cambia nada.",
    persona: "Persona",
    roles: "Roles que se le darían",
    comprobar: "Comprobar",
    limpio: "No aparece ningún conflicto nuevo.",
    nueva: "Nueva regla",
    editar: "Editar la regla",
    guardar: "Guardar la regla",
    cancelar: "Cancelar",
    guardada: "Regla {{codigo}} guardada.",
    campos: {
      codigo: "Código",
      nombre: "Nombre",
      descripcion: "Por qué no pueden coincidir",
      permisos_a: "Lado A: permisos",
      permisos_b: "Lado B: permisos que no pueden ir con los del lado A",
      nivel: "Gravedad",
      activa: "Activa",
    },
    excepciones: "Excepciones aprobadas",
    verCaducadas: "Ver también las caducadas",
    sinExcepciones: "No hay excepciones aprobadas.",
    hasta: "Hasta el {{fecha}}",
    caducada: "Caducó el {{fecha}}",
  },
  metodologias: {
    titulo: "Metodologías y playbooks",
    entradilla:
      "Qué hay que tener contestado para poder cerrar una venta —MEDDIC, BANT, SPIN, Challenger o la vuestra—, en qué embudo se aplica cada una y qué hacer en cada etapa.",
    lista: "Metodologías",
    nombreNueva: "Nombre de la metodología nueva",
    familia: "Basada en",
    familias: {
      meddic: "MEDDIC",
      bant: "BANT",
      spin: "SPIN",
      challenger: "Challenger",
      custom: "Propia, en blanco",
    },
    embudo: "Embudo",
    todos: "Todos los embudos",
    crear: "Crear metodología",
    nombre: "Nombre",
    activa: "Activa",
    criterios: "Lo que hay que tener contestado",
    pesoTotal:
      "Los pesos suman {{total}}; la puntuación es el porcentaje cubierto.",
    pregunta: "Pregunta o criterio",
    peso: "Peso",
    desdeEtapa: "Se pide desde",
    desdeElPrincipio: "El principio",
    quitarCriterio: "Quitar el criterio",
    anadirCriterio: "Añadir criterio",
    guardar: "Guardar la metodología",
    guardada: "Metodología guardada.",
    playbooks: "Qué hacer en cada etapa",
    playbooksAyuda:
      "Un paso por línea. Sale en la ficha de cada oportunidad que esté en esa etapa.",
    playbookDe: "Qué hacer en {{etapa}}",
    pasosDe: "Pasos de {{etapa}}",
    pasosEjemplo:
      "Confirmar quién firma\nEnviar el caso de un cliente parecido",
    guardarPasos: "Guardar los pasos",
    playbookGuardado: "Pasos de «{{etapa}}» guardados.",
  },
  embudos: {
    titulo: "Embudos y etapas",
    entradilla:
      "Cada embudo de venta con sus etapas: cuántas hay, cómo se llaman, su probabilidad, cuándo se considera estancada una oportunidad y qué campos tiene que tener para salir de cada una.",
    lista: "Embudos",
    porDefecto: "Por defecto",
    nuevoNombre: "Nombre del embudo nuevo",
    crear: "Crear embudo",
    etapasDe: "Etapas de {{embudo}}",
    ayuda:
      "Una etapa final cierra la venta: ganada o perdida. El embudo tiene que conservar una de cada.",
    orden: "Orden",
    nombre: "Nombre",
    probabilidad: "Prob. %",
    color: "Color",
    estancada: "Estancada (días)",
    final: "Final",
    ganada: "Ganada",
    criterios: "Para salir",
    subir: "Subir {{etapa}}",
    bajar: "Bajar {{etapa}}",
    nombreDe: "Nombre de la etapa {{etapa}}",
    probabilidadDe: "Probabilidad de {{etapa}}",
    colorDe: "Color de {{etapa}}",
    estancadaDe: "Días para que {{etapa}} esté estancada",
    finalDe: "{{etapa}} es final",
    ganadaDe: "{{etapa}} es ganada",
    quitar: "Quitar {{etapa}}",
    nuevaEtapa: "Nombre de la etapa nueva",
    anadir: "Añadir etapa",
    anadida: "Etapa añadida.",
    quitada: "Se ha quitado «{{etapa}}».",
    conOportunidades:
      "«{{etapa}}» tiene {{n}} oportunidades. ¿A qué etapa pasan?",
    moverA: "Elegir etapa",
    moverYQuitar: "Moverlas y quitar la etapa",
    cancelar: "Cancelar",
    guardar: "Guardar los cambios",
    guardado: "Guardado.",
  },
  cambioEstado: {
    cambiar: "Cambiar el estado",
    motivo: "Por qué pasa a «{{estado}}»",
    confirmar: "Cambiar",
    cancelar: "Cancelar",
  },
  estadosConf: {
    titulo: "Estados de los objetos",
    entradilla:
      "Cómo se llaman, en qué orden salen, de qué color, cuáles son propios de tu empresa y a cuáles se puede pasar desde cada uno. Los de fábrica no se borran: se desactivan.",
    ninguno: "Ningún objeto tiene estados configurables.",
    objetos: "Objetos",
    estadosDe: "Estados de {{objeto}}",
    deFabrica: "Los de fábrica",
    propia: "Configuración de tu empresa",
    obligatorios:
      "Tiene que quedar al menos un estado activo que signifique: {{lista}}.",
    orden: "Orden",
    clave: "Clave",
    nombre: "Nombre",
    color: "Color",
    significa: "Significa",
    final: "Final",
    activo: "Activo",
    motivo: "Pide motivo",
    subir: "Subir {{estado}}",
    bajar: "Bajar {{estado}}",
    nombreDe: "Nombre de {{estado}}",
    colorDe: "Color de {{estado}}",
    significaDe: "Qué significa {{estado}}",
    finalDe: "{{estado}} es final",
    activoDe: "{{estado}} está activo",
    motivoDe: "Pasar a {{estado}} pide motivo",
    anadir: "Añadir un estado",
    inicial: "Estado inicial",
    transiciones: "A qué se puede pasar desde cada estado",
    transicionesAyuda:
      "Cada fila es el estado de partida; marca los estados a los que se puede ir desde él.",
    desdeHasta: "Desde → a",
    deA: "De {{desde}} a {{hasta}}",
    guardar: "Guardar",
    volverAFabrica: "Volver a los de fábrica",
    guardado: "Guardado. Se aplica ya a todo lo que se mueva de estado.",
    restaurado: "Vuelven a ser los de fábrica.",
  },
  consejos: {
    titulo: "Lo que dicen las lecciones",
    ninguna:
      "Ninguna lección firmada viene a cuento todavía: ni de este cliente ni de ventas parecidas.",
    conIA: "Qué hacer y qué no, con IA",
    pidiendo: "Leyendo las lecciones…",
    iaSinNada:
      "La IA no ha sacado ningún consejo que pueda atribuir a una lección.",
    descartados:
      "{{n}} consejos de la IA se han descartado porque no salían de ninguna lección.",
    mismoCliente: "Del mismo cliente",
    parecidas: "Parecidas, de otros clientes",
    parecido: "se parece un {{n}} %",
    deLaLeccion: "de «{{titulo}}»",
    sinBusqueda:
      "No se han podido buscar las parecidas por significado: {{porque}}",
    momento: {
      creacion: "Al crearla",
      etapa: "Al cambiar de etapa",
      presupuesto: "Al mandar el presupuesto",
    },
    tipo: { haz: "Haz", no_hagas: "No hagas" },
  },
  leccion: {
    tipo: "Lección aprendida",
    verOportunidad: "Abrir la oportunidad",
    resultado: { perdida: "Perdida", ganada: "Ganada" },
    firmaObligatoria: "Post-mortem obligatorio sin firmar",
    senales: "En qué se apartó de las ganadas",
    sinSenales: "No se aparta de las ganadas en nada que el CRM pueda medir.",
    recorrido: "El recorrido",
    diasEn: "{{n}} días en «{{etapa}}»",
    enLasGanadas: "las ganadas, {{n}}",
    fechaMovida: "Fecha prevista movida",
    fechaRetrasada: "Retrasada",
    importeCambiado: "Importe cambiado",
    presupuestos: "Presupuestos",
    sinPresupuestos: "No se mandó ningún presupuesto.",
    margen: "margen {{n}} %",
    competencia: "Competencia",
    sinCompetencia: "No consta contra quién se competía.",
    gano: "ganó",
    decisores: "Quién decidía",
    sinNombre: "Contacto que no se puede ver",
    verContacto: "Ver el contacto",
    enContra: "en contra",
    aFavor: "a favor",
    sinDecisores: "No consta quién decidía.",
    actividad: "Actividad",
    sinActividad: "No hay actividad anotada en la oportunidad.",
    actividadTotal: "{{n}} actividades",
    diasSinContacto: "{{n}} días sin contacto antes de cerrarse",
    ganadasRef: "Las ganadas del mismo embudo",
    medianaDias: "Se cierran en {{n}} días (mediana)",
    estaTardo: "ésta, {{n}}",
    medianaDescuento: "Con un descuento del {{n}} % (mediana)",
    sobreGanadas: "Comparado con {{n}} ganadas",
    postmortem: "El post-mortem",
    postmortemDetalle:
      "Lo que leerán las oportunidades parecidas. La IA puede proponerlo con el expediente; tú lo corriges y lo firmas.",
    proponer: "Proponer con IA",
    proponiendo: "Leyendo el expediente…",
    quePaso: "Qué pasó",
    senalTemprana: "Qué señal temprana no vimos",
    queHariamos: "Qué haríamos distinto",
    factores: "Factores",
    firmar: "Firmar la lección",
    firmadaPor: "Firmada el {{fecha}}",
    propuestaIA: "Propuesto por la IA: revísalo antes de firmar.",
  },
  coste: {
    titulo: "Coste y capacidad",
    intro: "El margen de la oferta y qué se puede comprometer de verdad.",
    lineas: "Líneas de la oferta",
    calcular: "Calcular margen",
    verCapacidad: "Ver capacidad",
    margen: "Margen",
    necesitaAprobacion: "Por debajo del mínimo: necesita aprobación.",
    capacidad: "Capacidad del proveedor",
    libre: "Libre",
    enOfertas: "En ofertas abiertas",
    siSeGananTodas: "Libre si se ganan todas",
    contratada: "Capacidad contratada",
    comprometida: "Ya comprometida",
    enOfertasDato: "En ofertas abiertas (opcional)",
    plazoProveedor: "Plazo del proveedor, en días (vacío si no lo declara)",
    diasPropios: "Días de gestión y entrega nuestros (opcional)",
    verFecha: "Ver qué fecha se puede prometer",
    fechaPrometible: "Fecha que se le puede dar al cliente",
    noSePuedePrometer: "Todavía no se puede prometer una fecha.",
  },
  cuadros: {
    informeNoExiste: "El informe «{{clave}}» ya no existe.",
    descargar: "CSV",
    bajando: "Bajando…",
    bajado: "Descargado: {{filas}} fila(s) en CSV.",
    truncado: "Cortado por el tope de filas: no es el total.",
    camposRetirados: "No ves estos campos: {{campos}}.",
    titulo: "Cuadros de mando",
    // Toda pantalla dice para qué es. Éstas dos eran las únicas de 36 que no
    // lo decían, y una pantalla sin esa línea obliga a deducirlo del
    // contenido — que es justo lo que no se puede hacer cuando está vacía.
    entradilla:
      "Varios informes juntos, en el orden en que se miran. Cada uno dice de " +
      "cuándo son sus datos: un cuadro sin esa fecha se lee como si fuera de hoy.",
    elegir: "Elegir cuadro",
    ninguno: "Todavía no hay cuadros de mando",
    ningunoDetalle: "Un cuadro junta varios informes en una pantalla.",
    sinComponentes: "Este cuadro no tiene componentes",
    sinComponentesDetalle: "Añade uno apuntando a un informe.",
    ignoraFiltros: "No le afectan los filtros del cuadro",
    recibir: "Recibirlo",
    guardarRecibir: "Guardar",
    dejarDeRecibir: "Dejar de recibirlo",
    cada: "Cada",
    hora: "Hora",
    horaEnZona: "Hora ({{zona}})",
    canal: "Por",
    canales: {
      app: "La bandeja del CRM",
      correo: "Correo",
      push: "Notificación del móvil",
      sms: "SMS",
      webhook: "Webhook",
    },
    teLlega:
      "Te llega {{cada}} a las {{h}} h ({{zona}}) por {{canal}}. La próxima: {{cuando}}. Las cifras se calculan al abrirlo, con tus permisos.",
    noTeLlega:
      "No te llega solo. Elige cada cuánto, a qué hora y por dónde, y pulsa «Recibirlo».",
  },
  cuenta: {
    nuevoCaso: "Nuevo caso",
    jerarquia: "De qué grupo forma parte",
    jerarquiaAyuda:
      "Jerarquía «{{cual}}». No es la única: la legal no es la comercial ni la de facturación, y una empresa puede depender de la matriz para firmar y de la delegación de aquí para que la atiendan.",
    sinJerarquia: "No cuelga de ningún grupo",
    salud: "Cómo está este cliente",
    saludSirve: "Este número sirve para decidir.",
    saludNoSirve:
      "Este número NO sirve para decidir: no es fiable o no está vigente.",
    saludPuntuacion: "{{puntuacion}} · {{nivel}}",
    saludMedida: "Medida hace {{dias}} días.",
    linaje: "De dónde sale cada dato",
    linajeAyuda:
      "Qué fuente puso cada valor y cuál manda. Contesta «¿por qué pone esto si el ERP dice otra cosa?», que hoy se pregunta a quien montó la integración.",
    confianza: "confianza {{valor}}",
    obsoletos: "Lo que lleva sin confirmarse",
    sinObsoletos: "Nada lleva más de la cuenta sin confirmarse",
    sinConfirmar: "{{dias}} días sin confirmar (tope {{tope}})",
    verTodas: "Ver todas",
    timelineRecortada: "Se enseñan los últimos {{cuantos}}.",
    timelineEntera: "Se enseñan {{cuantos}} hitos.",
    verTodoLoQuePaso: "Ver todo lo que ha pasado",
    cargandoMas: "Cargando…",
    datos: "Datos",
    calidad: "Calidad del dato",
    faltan: "Falta por rellenar",
    metricas: "Métricas",
    timeline: "Lo que ha pasado",
    sinTimeline: "Todavía no hay actividad registrada con este cliente",
    contactos: "Contactos",
    sinContactos: "Ningún contacto asociado",
    oportunidades: "Oportunidades",
    sinOportunidades: "Ninguna oportunidad, ni abierta ni cerrada",
    casos: "Casos",
    sinCasos: "Ningún caso de soporte",
    noContactar: "No contactar",
    nuevaActividad: "Registrar actividad",
    nuevaOportunidad: "Nueva oportunidad",
    sinDato: "sin dato",
    sinMetricas:
      "Ninguna métrica ha llegado todavía desde los demás servicios.",
    sinDatoDe: "Sin dato de: {{metricas}}.",
    deHace: "de hace {{dias}} d",
    caducada:
      "El dato está caducado: se enseña con su antigüedad en vez de como si acabara de llegar.",
  },
  estado: {
    // Latencia p95/p99 por tipo de operación (CRM-08.01.01.01).
    latencia: {
      titulo: "Cuánto tarda cada tipo de operación",
      ayuda:
        "Percentil 95 y 99 de este mes, de la empresa que estás mirando, frente a su objetivo. El 95 dice cuánto espera casi todo el mundo; el 99, cuánto espera el que peor lo pasa.",
      servicio: "Servicio",
      todos: "Todos juntos",
      operacion: "Operación",
      peticiones: "Peticiones",
      p95: "p95",
      p99: "p99",
      ms: "{{ms}} ms",
      masDe: "más de {{ms}} ms",
      objetivo: "(objetivo {{ms}} ms)",
      pocas: "pocas para fiarse",
      tipo: {
        lectura: "Lectura",
        escritura: "Escritura",
        busqueda: "Búsqueda",
        exportacion: "Exportación",
        otra: "Otra",
      },
    },
    titulo: "Estado del servicio",
    entradilla:
      "Si el sistema va bien, y si no, qué parte. Lo dice el propio sistema " +
      "midiéndose: lo que no se ha podido medir sale como tal, no como «bien».",
    componente: "Componente",
    servicio: "Servicio",
    situacion: "Situación",
    detalle: "Detalle",
    compromisos: "Compromisos de servicio",
    compromisosIntro:
      "Lo prometido y lo medido, uno al lado del otro. Un compromiso que nadie compara con la realidad no lo comprueba nadie.",
    comprometido: "Comprometido",
    medido: "Medido",
    noSeMide: "no se mide desde aquí",
    slo: "Objetivo de servicio y presupuesto de error",
    sinMedicion:
      "{{cuantos}} sin medición: de ésos no se dice nada, no están en verde",
    objetivo: "{{objetivo}} % · {{minutos}} min de margen",
    consumo: "Consumo sobre lo contratado",
    entreServicios: "Entre servicios",
    contratosEnVerde:
      "Lo que cada servicio promete en sus eventos está llegando.",
    contratosRotos:
      "{{cuantos}} promesas entre servicios no se están cumpliendo.",
    sinRespuesta: "{{cuantos}} no han contestado",
    degradadas: "{{cuantas}} consultas van más lentas de lo que deberían.",
    presion: "Cuánto se está aplazando",
    presionNoMedible:
      "No se ha podido medir la presión. No es lo mismo que estar holgado: es que no se sabe.",
    presionEs: "presión {{presion}}",
    peorServicio:
      "Lo que se aplaza lo decide «{{servicio}}», que es el que peor va. No la media: con uno ahogado y trece holgados, la media sale tranquila y lo no crítico se difiere igual.",
    presionSinRespuesta:
      "{{cuantos}} servicio(s) no han contestado, así que esto no cubre la instalación entera.",
    interfaz: "Si la instalación necesita esta interfaz",
    interfazIndependiente:
      "Los {{cuantos}} servicios contestan y ninguno depende de la interfaz de referencia: se puede apagar sin perder ninguna operación.",
    interfazHallazgos:
      "{{cuantos}} hallazgo(s): sitios donde la instalación depende de la interfaz, o servicios que no han contestado y por eso no se pueden dar por independientes.",
    frenados: "A quién le ha bajado la cuota el freno automático",
    nadieObservado:
      "Todavía no se ha observado a ningún tenant en este proceso.",
    aCuota: "al {{pct}} % de su cuota",
    observado: "{{ventanas}} de {{minimo}} ventanas observadas",
  },
  ficha: {
    duplicar: "Duplicar",
    sinComentarios: "Todavía no ha escrito nadie",
    interno: "interno",
    editado: "editado",
    alguien: "Alguien",
    comentarioEnviado: "Comentario enviado",
    comoEstaba: "Cómo estaba esto en un momento dado",
    sinRastroCompleto:
      "Este objeto no tiene el rastro completo encendido, así que no hay nada que reconstruir. Encenderlo para todo multiplicaría la escritura por algo que casi nunca se consulta.",
    hechos: "{{cuantos}} hechos, {{compensados}} de ellos compensados.",
    cuadra: "La reconstrucción cuadra con lo que hay guardado.",
    noCuadra:
      "NO cuadra: alguien ha escrito en la tabla sin pasar por el rastro. A partir de aquí el rastro deja de ser una prueba.",
    preguntarSobreEsto: "Preguntar sobre este registro",
    tuPregunta: "Tu pregunta",
    ejemploPregunta: "¿Cuánto hemos facturado aquí este año?",
    preguntar: "Preguntar",
    conFiltro: "· filtrado por {{filtro}}",
  },
  firma: {
    conQue: "Con qué se firma",
    sinProveedor: "No hay ningún proveedor de firma configurado",
    sinProveedorPorque:
      "Sin proveedor no se puede mandar nada a firmar: se declara con su transporte, sus niveles y sus formas de identificar al firmante.",
    inactivo: "(inactivo)",
    niveles: "Niveles: {{cuales}}",
    identificaciones: "Identifica por: {{cuales}}",
    regla: "#{{prioridad}} {{nombre}} → {{proveedor}}, nivel mínimo {{nivel}}",
    sinNivelMinimo: "el que pida quien lo manda",
    apagada: "apagada",
    plantilla: "{{nombre}} ({{tipo}}) · {{nivel}} · vale {{dias}} días",
    ordenEstricto: "orden estricto",

    llamadas: {
      titulo: "Lo que el proveedor de firma cobró",
      porQue:
        "Qué se le pidió, qué contestó y cuánto costó cada llamada. Sirve para conciliar su factura y para desatascar un sobre parado, que son las dos veces que esto se mira.",
      soloFallidas: "Sólo las que fallaron",
      resumen: "{{cuantas}} llamadas, {{gasto}} en total.",
      deEllasFallidas: "De ellas {{fallidas}} fallaron, y cuestan {{gasto}}.",
      sinCoste: "sin coste anotado",
    },
    titulo: "Pendiente de firma",
    entradilla:
      "Qué contratos están parados, desde cuándo y por quién. Lo que lleva " +
      "más tiempo esperando, primero.",
    nadaEsperando: "No hay nada esperando una firma",
    nadaEsperandoDetalle:
      "Ningún sobre abierto. No es «todo firmado»: es que no hay nada en curso.",
    cuantos: "{{cuantos}} sobres esperando",
    diasParado: "{{dias}} d",
    firmados: "{{firmados}} de {{total}} firmado",
    nadieLoHaAbierto: "Nadie lo ha abierto",
    caducaEn: "caduca en {{dias}} d",
    esperandoA: "Esperando a",
    abrirSobre: "Abrir el sobre",
  },
  ia: {
    cuenta: "Cuenta",
    eligeCuenta: "Elige una cuenta…",
    cargando: "Cargando cuentas…",
    sinMedir: "Esta cuenta no tiene salud medida",
    queHacer: "Qué haría falta:",
    // La medida lleva su fecha: un 42 en rojo de hace tres meses no es una
    // alerta, es un recuerdo.
    medidaHace: "medida hace {{dias}} días",
    porQue: "Por qué",
    pocoFiable: "medida poco fiable",
    titulo: "Inteligencia artificial",
    intro: "Lo que propone, siempre con el porqué.",
    contribuciones: "Contribuciones del modelo",
    explicar: "Explicar la puntuación",
    noMedible: "No se puede explicar",
  },
  // La evaluación de la IA contra el modelo real (CRM-05.02.01.07).
  evaluacionIa: {
    titulo: "Evaluación de la IA",
    entradilla:
      "Un banco de casos con su respuesta buena, pasado contra el modelo real por el mismo camino que usan las funciones: el acierto de cada una, su tendencia y cada caso que falla con su porqué.",
    evaluarAhora: "Evaluar ahora",
    evaluando: "Evaluando… {{hechos}} de {{total}}",
    ultima: "Última evaluación",
    resumen:
      "{{aciertos}} de {{casos}} casos acertados · {{cuando}} · {{origen}}",
    modelo:
      "Modelo: {{modelos}} · coste {{coste}} · {{latencia}} ms de media por caso",
    nunca:
      "Todavía no se ha evaluado. El banco de serie trae {{casos}} casos y se guarda como tuyo la primera vez.",
    programada:
      "Se evalúa sola cada {{horas}} horas; avisa si una función baja del {{umbral}}. Próxima: {{proxima}}.",
    trasLaPrimera: "tras la primera",
    sinProgramar:
      "La evaluación programada está apagada (0 horas). El umbral de aviso es el {{umbral}}.",
    porFuncion: "Acierto por función",
    casosDe: "{{aciertos}} de {{casos}} casos",
    antes: "antes {{antes}}",
    latencia: "{{ms}} ms",
    sinEvaluar: "Sin evaluar todavía.",
    conJuez:
      "{{n}} caso(s) con un criterio que decide un modelo juez: no se puede medir por programa.",
    version: "Versión del prompt {{version}}",
    tendencia: "Tendencia del acierto",
    fecha: "Evaluación",
    acierto: "Acierto global",
    fallan: "Casos que fallan",
    ningunFallo: "Ningún caso falla en la última evaluación.",
    juez: "juez",
    banco: "Banco de casos",
    bancoAyuda:
      "Configuración de tu empresa: el producto trae los de serie y aquí se apagan los que no apliquen. Los propios se añaden por la API.",
    bancoVacio: "El banco se guarda la primera vez que se evalúa.",
    activar: "Evaluar «{{caso}}»",
    col: {
      funcion: "Función",
      caso: "Caso",
      origen: "Origen",
      juez: "Juez",
      activo: "Activo",
    },
    origenes: { manual: "a mano", programada: "programada" },
    origenesCaso: { serie: "De serie", propio: "Propio" },
  },
  modeloDatos: {
    probar: {
      titulo: "Probar un registro",
      ayuda:
        "Rellena los campos y mira qué contestaría el sistema al guardarlo: son las mismas reglas que al guardar de verdad, y no se guarda nada.",
      sinCampos: "Este objeto no tiene campos que se tecleen.",
      sinValor: "Sin valor",
      si: "Sí",
      no: "No",
      parcial: "Como un cambio (no exige los obligatorios que no rellenes)",
      boton: "Probar un registro",
      pasaria: "Pasaría: se guardaría tal cual.",
      noPasaria: "No pasaría: {{cuantos}} problemas.",
    },
    alPublicar: "Qué pasaría si publicas esto",
    sinCambiosQuePublicar:
      "No hay nada por publicar: lo guardado es lo que ya está en vigor.",
    deLaVersionALa: "De la versión {{de}} a la {{a}}.",
    anadidos: "{{cuantos}} campos nuevos",
    retirados: "{{cuantos}} campos retirados",
    cambiados: "{{cuantos}} campos cambiados",
    noSeHaPodidoContar:
      "No se ha podido contar a cuántos registros afecta. Eso NO es «no afecta a nadie»: antes de publicar, míralo.",
    afectaA:
      "Afecta a {{registros}} registros, de los que {{sin}} se quedarían sin rellenar.",
    publicarEsSeguro: "Sin avisos: publicar esto no deja nada a medias.",
    limites: "Cuánto sitio queda",
    camposDeTope: "{{campos}} campos de {{tope}}",
    campos: "Campos",
    camposAyuda:
      "Con las veces que se ha ESCRITO cada uno al lado, que es lo que " +
      "contesta «¿puedo quitarlo?». Leer mide quién mira; escribir mide si el " +
      "campo se rellena.",
    sinCampos: "Este objeto no tiene campos propios todavía",
    obligatorio: "Obligatorio",
    unico: "Único",
    soloLectura: "Solo lectura",
    deprecado: "Deprecado",
    nuncaEscrito: "nunca escrito",
    escrituras: "{{cuantas}} escrituras",
    materializado: "Columna real",
    sinUsar:
      "{{cuantos}} campos sin una sola escritura: son los candidatos a retirar.",
    reglas: "Validaciones",
    reglasAyuda:
      "Con el mensaje que verá quien las incumpla: es la mitad de la regla, y " +
      "sin él no se puede juzgar si está bien escrita.",
    sinReglas: "Sin validaciones declaradas",
    apagada: "Apagada",
    tipos: "Tipos de registro",
    tiposAyuda:
      "El mismo objeto visto de formas distintas, con sus campos y sus listas " +
      "recortadas. Partirlo en dos objetos rompe los informes.",
    sinTipos: "Un solo tipo de registro",
    porDefecto: "Por defecto",
    ocultos: "{{cuantos}} campos ocultos",
    publicaciones: "Qué se publicó y cuándo",
    publicacionesAyuda:
      "Cada versión del esquema, con quién la publicó y cuántos campos " +
      "llevaba: es a lo que se vuelve cuando algo deja de encajar.",
    camposEnPublicacion: "{{cuantos}} campos",
    calculado: "Se calcula",
    yaEstaEnLaApi: "Ya se lee y se escribe por la API",
    yaEstaEnLaApiAyuda:
      "Un campo añadido aquí entra solo en la API de este objeto: se lee, se " +
      "escribe, se valida y sale en su descripción sin que nadie toque " +
      "código. Las escrituras de al lado son la prueba, no una promesa: " +
      "cuentan las veces que ha entrado por la API de verdad.",
    diseno: "El formulario que te toca, y por qué ése",
    disenoAyuda:
      "Con varios diseños por rol, la pregunta que llega a soporte es siempre " +
      "«¿por qué yo veo otra pantalla?». Aquí sale cuál se te aplica y el " +
      "motivo.",
    sinDiseno: "Sin formulario diseñado",
    secciones: "{{cuantas}} secciones",
    ia: "Lo que la IA entiende de este objeto",
    iaAyuda:
      "Un campo sin describir no entra en el contexto, y quien pregunte por " +
      "él concluirá que el dato no existe. No es lo mismo que no exista a que " +
      "nadie lo haya explicado.",
    iaCobertura: "Explotable el {{pct}} % ({{explotables}} de {{campos}})",
    iaNoMedible: "Sin campos propios: no hay nada que describir",
    iaFuera:
      "Fuera del contexto: {{sensibles}} por sensibles y {{internos}} por internos.",
    iaSinDescribir: "Sin describir: {{campos}}",
    enInformes: "Y en informes",
    enInformesAyuda:
      "Los campos propios salen como dimensión o métrica sin modelar nada " +
      "aparte. Los personales y de categoría especial se quedan fuera, y se " +
      "dice cuáles.",
    enInformesCuantos:
      "{{cuantos}} campos de este objeto explotables en informes",
    enInformesFuera: "{{cuantos}} dejados fuera por sensibles",
    columna: "Campos que ya justifican una columna",
    columnaAyuda:
      "Materializar no es la norma: un cambio de tabla compartida por mil " +
      "empresas las bloquea a todas. Es la excepción, y se decide con una " +
      "medida, no con una intuición.",
    columnaNinguno:
      "Ninguno llega al umbral de {{umbral}} escrituras. El camino normal " +
      "—JSONB con índice— va bien aquí.",
    columnaEscrituras: "{{cuantas}} escrituras",
    estados: "La máquina de estados",
    estadosAyuda:
      "Por qué estados pasa un registro y desde cuál se puede ir a cuál. Sin " +
      "ella, cualquier estado puede saltar a cualquier otro y el histórico " +
      "deja de significar nada.",
    sinEstados: "Sin máquina de estados: cualquier valor vale",
    estadoVaA: "va a",
    estadoFinal: "es final",
    renombrar: "Renombrar y retirar sin romper nada",
    renombrarAyuda:
      "Renombrar un campo deja el viejo puesto y escribiendo en los dos, " +
      "para que lo que ya llama por el nombre antiguo siga funcionando. El " +
      "viejo se retira después, cuando se ve que nadie lo usa — y eso se ve " +
      "aquí, en las escrituras.",
    sePuedeRetirar: "{{cuantos}} se pueden retirar ya",
    noSePuedeRetirarTodavia:
      "Ninguno se puede retirar todavía: todos siguen recibiendo escrituras.",
    paquete: "Llevarse esta configuración a otro entorno",
    paqueteAyuda:
      "Se lleva la configuración, nunca los datos. Un paquete que arrastrara " +
      "registros convertiría una promoción a producción en una fuga.",
    paqueteDescargar: "Descargar el paquete",
    paqueteContiene: "{{objetos}} objetos y {{campos}} campos",
  },
  instancia: {
    version: "versión {{version}}",
    paradaEn: "parada en «{{paso}}»",
    grafico: "Por dónde va",
    graficoAyuda:
      "Sobre la definición con la que arrancó, no la publicada después: " +
      "pintarla sobre la nueva señalaría pasos que esta instancia no tiene. " +
      "Cada caja lleva su estado escrito, no sólo en el color.",
    sinDefinicion:
      "No se encuentra la definición de esta versión, así que no hay gráfico que pintar",
    estado: {
      actual: "aquí está",
      recorrido: "hecho",
      fallido: "falló",
      compensado: "deshecho",
      pendiente: "pendiente",
      no_recorrido: "no se pasó por aquí",
    },
    camino: "Qué pasó, en orden",
    caminoAyuda:
      "El estado de cada paso dice dónde está; esto dice en qué orden pasó. " +
      "Con un bucle por medio, un paso puede estar «hecho» por la tercera " +
      "vuelta y lo que importa es qué decidió en cada una.",
    sinRecorrido: "Todavía no ha ejecutado ningún paso",
    intento: "intento {{n}}",
    rescate: "Desatascar",
    rescateAyuda:
      "Tres herramientas y elegir entre ellas es el trabajo: reintentar " +
      "vuelve a ejecutar lo mismo —sirve si el fallo fue pasajero—, corregir " +
      "las variables arregla el dato, y saltar el paso es para cuando ese " +
      "paso no se va a poder completar nunca.",
    motivo: "Por qué",
    motivoCorto:
      "Hacen falta diez caracteres: esto cambia el curso de un proceso en " +
      "marcha y queda escrito para que alguien pueda revisarlo.",
    reintentar: "Reintentar",
    reintentarAyuda:
      "Vuelve a ejecutar el paso que falló. Sólo sirve si el fallo fue " +
      "pasajero: si la causa sigue ahí, volverá a fallar igual.",
    saltarA: "Saltar a",
    eligeDestino: "Elige a dónde",
    saltarAyuda:
      "Sólo los destinos que el propio paso declara. Saltar a cualquier otro " +
      "metería el registro en una rama por la que no pasó, y el histórico " +
      "diría que el proceso se siguió.",
    saltar: "Saltar el paso",
    variables: "Corregir variables (JSON)",
    variablesAyuda:
      "Lo que se escriba aquí se mezcla con lo que ya tiene. Es para un " +
      "proceso atascado por un dato mal cargado.",
    variablesMal: "Eso no es un JSON válido",
    corregir: "Corregir",
    hechoReintento: "Reintentado: vuelve a ejecutar el paso que falló.",
    hechoSalto: "Saltado. Queda apuntado de qué paso se salió y a cuál se fue.",
    hechoVariables: "Variables corregidas, con tu motivo en el registro.",
    atasco: "Dónde se atasca este proceso",
    atascoAyuda:
      "De todas sus ejecuciones, no sólo de ésta: lo siguiente que se quiere " +
      "saber delante de una instancia parada es si es ésta o si ese paso " +
      "para siempre. El tiempo de un paso humano se cuenta desde que se creó " +
      "la tarea hasta que alguien respondió.",
    ejecuciones:
      "{{cuantas}} ejecuciones · {{terminadas}} terminadas · {{falladas}} falladas",
    cuello: "Donde más se espera: «{{paso}}»",
    quienFrena: "Quién tarda más en responder:",
    quienFrenaUno: "{{quien}}, {{horas}} h de media en {{tareas}} tareas",
    ciclo: "De principio a fin: {{media}} h de media, {{mediana}} h de mediana",
    veces: "{{veces}} veces",
    espera: "espera {{media}} h de media, {{mediana}} de mediana",
    fallos: "{{cuantos}} fallos",
    pendientesAhora: "{{cuantas}} pendientes ahora",
  },
  // El SLA del proveedor frente al prometido (CRM-09.01.01.08).
  slaProveedores: {
    titulo: "SLA de proveedores",
    entradilla:
      "Lo que prometemos al cliente en cada derecho de servicio, contra lo que sostiene por contrato el proveedor que lo da. A sus tiempos se suman {{horas}} h nuestras de coordinar y desplazar: prometer su mismo tiempo es prometer uno que sólo existiría si nosotros no hiciéramos nada.",
    sinIntegracion:
      "Integración no ha contestado: no se sabe qué proveedores hay ni su plazo, y se compara sólo con los acuerdos guardados aquí.",
    nadaQueRevisar:
      "Ningún derecho de servicio tiene un proveedor detrás. Elige quién da cada uno en «Quién da cada derecho».",
    avisos:
      "Derechos con proveedor: {{n}}. Prometen lo que su proveedor no sostiene: {{no}}. Con un proveedor sin acuerdo guardado: {{sin}}.",
    todoBien: "Derechos con proveedor: {{n}}. Todos se sostienen con margen.",
    revision: "Lo prometido frente a lo que sostiene el proveedor",
    sinFilas: "Ningún derecho con proveedor",
    quienDa: "Quién da cada derecho",
    quienDaEste: "Quién da «{{derecho}}»",
    nosotros: "Lo damos nosotros",
    sinDerechos: "No hay derechos de servicio dados de alta",
    acuerdos: "Lo que sostiene cada proveedor",
    sinProveedores: "No hay proveedores de servicio",
    sinProveedoresDetalle:
      "Los proveedores se dan de alta en integración, con los encargos.",
    sinAcuerdo: "Sin acuerdo guardado",
    noExiste: "No consta en integración",
    sinDeclarar:
      "El proveedor no declara {{que}}: no es que lo tenga bien, es que no lo ha dicho.",
    horas: "{{v}} h",
    cambiar: "Cambiar",
    anadir: "Añadir acuerdo",
    quitar: "Quitar",
    editar: "Acuerdo de {{proveedor}}",
    resolucionVacia:
      "Si dejas la resolución vacía, vale el plazo que consta del proveedor en integración.",
    guardar: "Guardar",
    cancelar: "Cancelar",
    col: {
      derecho: "Derecho",
      proveedor: "Proveedor",
      prometido: "Prometido al cliente",
      sostiene: "Sostiene el proveedor",
      veredicto: "Veredicto",
      porque: "Por qué",
      sla: "SLA",
      plazo: "Plazo en integración",
    },
    veredicto: {
      se_sostiene: "Se sostiene",
      no_se_sostiene: "No se sostiene",
      sin_acuerdo: "Sin acuerdo",
      sin_compromiso: "Sin tiempos prometidos",
    },
    metrica: {
      respuesta_h: "respuesta {{v}} h",
      resolucion_h: "resolución {{v}} h",
      disponibilidad_pct: "disponibilidad {{v}} %",
      cobertura_horaria: "cobertura {{v}}",
    },
    nombre: {
      respuesta_h: "su tiempo de respuesta",
      resolucion_h: "su tiempo de resolución",
      disponibilidad_pct: "su disponibilidad",
      cobertura_horaria: "su cobertura horaria",
    },
    campo: {
      respuesta_h: "Respuesta (h)",
      resolucion_h: "Resolución (h)",
      disponibilidad_pct: "Disponibilidad (%)",
      cobertura_horaria: "Cobertura horaria",
    },
  },
  oportunidad: {
    nuevaOferta: "Nueva oferta",
    // Enviar a firma desde la oportunidad (CRM-03.03.02.07).
    firma: {
      titulo: "La firma",
      sinSobre: "Todavía no se ha mandado nada a firmar.",
      estado: "Sobre {{referencia}}: {{estado}}",
      verSobre: "Ver el sobre",
      sinConsultar:
        "No se ha podido preguntar al sobre ahora: se enseña el último estado guardado.",
      llevaA:
        "Cuando se complete la firma, la oportunidad pasará a «{{etapa}}».",
      soloMarca:
        "Este embudo no tiene etapa para una firma completada: se marcará la firma y la etapa no se moverá. Se configura en Administrar › Usuarios y empresa › Administración (firma_etapa_por_embudo).",
      noMovio: "La firma se completó y la etapa no se movió: {{motivo}}",
      enviar: "Enviar a firma",
      presupuesto: "Qué se firma",
      elUltimo: "El último presupuesto vivo",
      nombre: "Nombre del firmante",
      email: "Correo del firmante",
      otroFirmante: "Añadir otro firmante",
      mandarYa: "Mandarlo ya (si no, queda preparado sin mandar)",
      confirmar: "Crear el sobre",
      enviando: "Creando…",
      cancelar: "Cancelar",
      creado: "Sobre {{referencia}} creado: {{estado}}.",
      creadoSinMandar: "El sobre se ha creado y NO se ha mandado: {{motivo}}",
    },
    // La sección de la oportunidad cerrada que lleva a su lección.
    porQue: {
      titulo: "Por qué se cerró así",
      perdida: "Por qué se perdió",
      ganada: "Por qué se ganó",
      firmar: "Escribir y firmar el post-mortem",
      verLeccion: "Ver la lección",
      pendiente:
        "Falta el post-mortem: es obligatorio en las perdidas, y es lo que leerán las oportunidades parecidas.",
      sinSenales: "No se aparta de las ganadas en nada que el CRM pueda medir.",
    },
    queFalta: "Qué falta para poder cerrar",
    sinMetodologia:
      "No hay ninguna metodología de venta activa, así que no se puede decir qué falta.",
    cubiertos:
      "{{cubiertos}} de {{criterios}} criterios · {{puntuacion}} puntos",
    cualificada: "Tiene contestados todos los criterios.",
    cualificadaConHuecos:
      "Cualificada: tiene contestado al menos el {{pct}} % de los criterios. Lo que falta sigue abajo.",
    noCualificada: "Todavía no está cualificada para cerrarse:",
    siguientePaso: "Siguiente paso: {{paso}}",
    planConjunto: "El plan con el cliente",
    sinPlan:
      "No hay plan conjunto. No es un hueco: significa que no se ha acordado nada con el cliente sobre cómo llegar al cierre.",
    planSinCompartir:
      "Sin compartir con el cliente. Un plan que el cliente no ha visto no es un plan conjunto: es una lista nuestra con su nombre encima.",
    planCompartidoSinVer: "Compartido, y el cliente todavía no lo ha abierto.",
    planVisto: "El cliente lo vio el {{fecha}}.",
    pasosDelPlan: "{{hechos}} de {{pasos}} pasos hechos",
    retrasoNuestro:
      "{{cuantos}} paso(s) retrasados NUESTROS. Eso se empuja aquí dentro.",
    retrasoDelCliente:
      "{{cuantos}} paso(s) retrasados DEL CLIENTE. Esa conversación es con él.",
    retrasoConjunto: "{{cuantos}} paso(s) retrasados de los dos.",
    fechaNoCreible:
      "Con lo que queda por hacer, la fecha objetivo del plan ya no se sostiene.",
    sinEtapa: "sin etapa",
    bloqueada: "Bloqueada",
    ponderado: "{{valor}} ponderado al {{pct}} %",
    categoriaPrevision: "Cuenta en la previsión como",
    revisiones: "Las revisiones del deal",
    sinRevisiones:
      "No se ha revisado todavía. Se registra en Más › Registrar una revisión estructurada.",
    revisionDel: "Revisión del {{fecha}} · probabilidad declarada {{pct}} %",
    queSalirMal: "Qué puede salir mal",
    queFaltaSaber: "Qué falta por saber",
    acuerdo: "Acuerdo: {{titulo}} — {{responsable}}, para el {{fecha}}",
    enEstaEtapa_one: "Lleva 1 día en esta etapa",
    enEstaEtapa_other: "Lleva {{count}} días en esta etapa",
    lineas: "Qué se vende",
    margen: "Margen conocido: {{pct}} %",
    margenSinCoste:
      "Ninguna línea tiene coste: no se puede hablar de margen, y no es un cero.",
    margenIncompleto:
      "Sin contar {{cuales}}, que no tienen coste: el margen real no se sabe.",
    sinLineas: "Todavía no tiene líneas",
    porUnidad: "{{cantidad}} × {{precio}}",
    metricas: "Lo que esto vale",
    noCuentaComoArr:
      "No cuenta como ARR: {{tipos}} ({{puntual}}). Es ingreso puntual, no recurrente.",
    quienDecide: "Quién decide",
    sinRoles: "Nadie identificado todavía",
    hablado: "hablado",
    sinHablar: "sin hablar",
    enContra: "en contra",
    reparto: "Quién se lo lleva",
    sinReparto: "Sin reparto declarado: va entero al titular",
    creditoTotal: "Crédito repartido: {{total}} %",
    noCuadra: "NO cuadra",
    relacionadas: "De dónde viene y qué sale de aquí",
    contacto: "Contacto",
    laOtra: "la otra oportunidad",
    papel: {
      credito: "Crédito",
      overlay: "Overlay",
    },
    sentido: {
      sale_de_aqui: "sale de ésta",
      viene_de: "viene de otra",
    },
    movimientos: "Lo que se ha movido",
    sinMovimientos: "Ni el importe ni la fecha se han movido",
    deslizada: "{{dias}} días más tarde",
    sinMotivo:
      "Se movió sin motivo escrito: así no se puede discutir en un comité. Se escribe en Editar › Más campos › Motivo cambio.",
    campoMovido: {
      importe: "Importe",
      fecha_cierre: "Fecha de cierre",
    },
  },
  // Lo que se hace con varias filas a la vez (CRM-00.02.01.11).
  masivo: {
    titulo: "Con los elegidos",
    resultado: "Resultado del lote",
    elegidos_one: "1 elegido",
    elegidos_other: "{{count}} elegidos",
    actualizarCampo: "Actualizar un campo",
    borrar: "Borrar",
    quitarSeleccion: "Desmarcar todos",
    cerrar: "Cerrar",
    queCampo: "Qué campo",
    eligeCampo: "Elige un campo…",
    aplicarA_one: "Aplicar a 1",
    aplicarA_other: "Aplicar a {{count}}",
    confirmarBorrado_one:
      "Se manda 1 registro a la papelera. Si otro registro lo usa, no se borra y se dice.",
    confirmarBorrado_other:
      "Se mandan {{count}} registros a la papelera. Los que use otro registro no se borran, y se dice cuáles.",
    borrarN_one: "Borrar 1",
    borrarN_other: "Borrar {{count}}",
    informeActualizado: "Actualizados {{hechos}} de {{total}}.",
    informeBorrado: "A la papelera {{hechos}} de {{total}}.",
    fallidos_one: "1 no se ha podido:",
    fallidos_other: "{{count}} no se han podido:",
    fila: "Fila {{fila}}",
    noMostrados_one: "Y 1 más que no cabe aquí.",
    noMostrados_other: "Y {{count}} más que no caben aquí.",
    noSePudo: "No se ha podido hacer.",
    verificate:
      "Borrar en lote pide confirmar que eres tú, y no se ha confirmado: no se ha borrado nada. Vuelve a pulsarlo y confírmalo.",
  },
  // Duplicar un registro desde su ficha (CRM-07.01.01.07).
  duplicar: {
    desde: "Copia de un registro: revisa los datos antes de guardar.",
    sufijo: "(copia)",
  },
  // Importar con mapeo, simulación y reversión (CRM-07.01.01.08).
  importar: {
    titulo: "Importar datos",
    entradilla:
      "Sube un CSV, di a qué campo va cada columna, mira qué haría con cada fila y sólo entonces impórtalo. Una importación hecha se puede deshacer entera.",
    paso1: "1 · El fichero",
    queImportas: "Qué importas",
    objetos: { cuenta: "Cuentas", contacto: "Contactos" },
    fichero: "Fichero",
    leido: "«{{fichero}}»: {{filas}} filas y {{columnas}} columnas.",
    paso2: "2 · A qué campo va cada columna",
    mapeoAyuda:
      "Lo que se llama igual que un campo se propone solo. Los campos propios de tu empresa salen marcados; lo que dejes en «No importar» no se manda.",
    columna: "Columna del fichero",
    ejemplo: "Primera fila",
    destino: "Va a",
    destinoDe: "A qué campo va «{{columna}}»",
    sinCabecera: "(sin cabecera)",
    noImportar: "No importar",
    campoPropio: "{{campo}} (propio)",
    faltan: "Falta llevar alguna columna a: {{campos}}.",
    completarExistentes:
      "Completar las que ya existan (rellena huecos, no pisa lo que tienen)",
    simular: "Simular",
    importar: "Importar",
    primeroSimula: "Simula antes de importar",
    informeSimulado: "3 · Lo que haría (no se ha escrito nada)",
    informeHecho: "Importado",
    resumen:
      "{{total}} filas: {{creados}} se crean, {{actualizados}} se completan, {{omitidos}} se omiten porque ya existen y {{fallidos}} fallan.",
    sePuedeRevertir:
      "Queda en el historial de abajo: si algo no era lo que esperabas, se revierte entera.",
    porFila: "Fila a fila",
    fila: "Fila",
    nombre: "Nombre",
    queHaria: "Qué hace",
    motivo: "Por qué",
    acciones: {
      crear: "Crear",
      actualizar: "Completar",
      omitir: "Omitir",
      falla: "Falla",
    },
    noMostrados: "Y {{cuantos}} fallos más que no caben en la respuesta.",
    historial: "Importaciones hechas",
    historialAyuda:
      "Revertir manda a la papelera lo que creó y devuelve lo completado a como estaba. Si algo se ha tocado después, se avisa.",
    sinHistorial: "Todavía no se ha importado nada.",
    cuando: "Cuándo",
    que: "Qué",
    quien: "Quién",
    resultado: "Resultado",
    resultadoCorto:
      "{{creados}} creados · {{actualizados}} completados · {{fallidos}} fallidos",
    revertida: "Revertida el {{cuando}}",
    revertir: "Revertir",
    revertirTitulo: "Revertir «{{fichero}}»",
    revertirPlan:
      "Se mandarían a la papelera {{borrados}} y se devolverían a como estaban {{restaurados}}. {{ya}} ya no estaban.",
    revertirConflictos:
      "{{cuantos}} se han cambiado después de importarlos: revertirlos desharía ese trabajo.",
    revertirForzar: "Revertirlos igualmente",
    motivoRevertir: "Por qué se revierte",
    confirmarRevertir: "Revertir la importación",
  },
  // El traspaso de la cartera de una persona a otra (CRM-07.01.01.07).
  propiedad: {
    titulo: "Traspasar cartera",
    entradilla:
      "Lo que lleva una persona —cuentas, contactos, actividades, leads y oportunidades— pasa a otra. Se simula antes y se confirma con un motivo.",
    paso1: "1 · De quién y a quién",
    de: "De",
    a: "A",
    elige: "Elige una persona…",
    simular: "Simular el traspaso",
    mismaPersona: "El origen y el destino son la misma persona.",
    paso2: "2 · Lo que se movería",
    servicio: "Dónde",
    tipo: "Qué",
    cuantos: "Cuántos",
    servicios: { clientes: "Clientes", ventas: "Ventas" },
    nada: "Nada que mover",
    totalSimulado_one: "En total, 1 registro.",
    totalSimulado_other: "En total, {{count}} registros.",
    motivo: "Motivo del traspaso",
    motivoEjemplo: "Baja de la persona, cambio de cartera…",
    confirmar_one: "Traspasar 1 registro",
    confirmar_other: "Traspasar {{count}} registros",
    cambiaste: "Has cambiado la pareja: vuelve a simular antes de confirmar.",
    hecho: "Hecho: esto es lo que se ha movido",
    noContesta: "No ha contestado",
  },
  prevision: {
    moneda: "Moneda en la que se mira",
    // Por jerarquía (CRM-03.02.01.02).
    jerarquia: "Por jerarquía",
    jerarquiaAyuda:
      "Comercial, equipo, región y compañía. Cada rama suma lo de todo lo que cuelga de ella; el total de la compañía va aparte.",
    organigramaDe: "Organigrama de",
    porTerritorios: "los territorios",
    porMando: "la jerarquía de mando",
    niveles: {
      comercial: "Comercial",
      equipo: "Equipo",
      region: "Región",
      direccion: "Dirección",
    },
    compania: "Compañía: {{total}} en {{cuantas}} oportunidades.",
    sinOrganigrama: "No hay organigrama del que colgar la previsión.",
    fueraDelOrganigrama:
      "{{importe}} no cuelga de ninguna rama. Es de estas personas:",
    sinDueno: "Y {{importe}} es de oportunidades sin dueño.",
    cuantas: "{{cuantas}} oportunidades",
    total: "{{total}} · {{ponderado}} ponderado",
    ponderadoCorto: "{{valor}} ponderado",
    compromiso: "Comprometido: {{valor}}",
    ajustes: "Lo que ha tocado el responsable",
    ajustesAyuda:
      "Cada ajuste con su autor y su motivo. El motivo es la mitad del ajuste: " +
      "sin él no se puede juzgar si estaba bien hecho.",
    sinAjustes: "Nadie ha tocado el número calculado",
    acierto: "¿Acercaron al real?",
    contraReal: "Real {{real}} · sin ajustar {{bruto}} · ajustado {{ajustado}}",
    ajustarAcerco: "Ajustar acercó: error de {{error}}.",
    ajustarAlejo:
      "Ajustar ALEJÓ del real: error de {{conAjuste}} ajustando y {{sinAjuste}} sin tocar nada.",
    desglose: "Por dónde entra",
    agruparPor: "Agrupar por",
    porFamilia: "familia",
    porProducto: "producto",
    porTipo: "tipo de ingreso",
    sinDesglose: "Sin líneas que desglosar en este periodo",
    lineas: "{{cuantas}} líneas",
    gruposSinCambio:
      "Sin tipo de cambio y por tanto FUERA del desglose: {{grupos}}. No es que no vendieran.",
    fotos: "Cómo íbamos antes",
    fotosAyuda:
      "Cada foto con cuándo se tomó. Una previsión sin fotos no se puede " +
      "comparar consigo misma, y «¿cómo íbamos hace tres semanas?» es la " +
      "pregunta de todos los lunes.",
    sinFotos: "Todavía no se ha congelado ninguna foto",
    salto: "Qué ha cambiado entre dos fotos",
    saltoAyuda:
      "La diferencia entre dos totales no explica nada. Elige dos fotos y se separan las causas, cada una con cuántas oportunidades la forman. Salir de la foto no es perderse: va aparte.",
    saltoFaltanFotos:
      "Hacen falta al menos dos fotos del periodo para compararlas.",
    saltoDesde: "Desde la foto",
    saltoHasta: "Hasta la foto",
    variacion: "Variación del total: {{importe}}",
    oportunidadesN: "{{n}} oportunidad(es)",
    causas: {
      entradas: "Entran en la foto",
      ganadas: "Ganadas",
      perdidas: "Perdidas",
      salidas: "Salen de la foto (otro periodo o borradas)",
      variacion_de_importe: "Cambian de importe",
      deslizadas: "Cambian de fecha dentro del periodo",
    },
    deslizamiento: "Cuánto se ha movido",
    sinDeslizamiento: "Ninguna oportunidad ha cambiado de fecha",
    empujadas: "{{cuantas}} empujadas, {{dias}} días en total",
    masDeUnaVez:
      "{{cuantas}} se han empujado MÁS DE UNA VEZ. Eso no es un retraso: es una venta que no existe.",
    dias: "{{dias}} días",
    veces: "{{veces}} veces",
  },
  territorios: {
    titulo: "Mapa de territorios",
    intro:
      "Publicar y ver qué pasa significa que cientos de cuentas cambian de " +
      "dueño el lunes por la mañana, y deshacerlo no devuelve las " +
      "conversaciones que ya se tuvieron.",
    queSiPublico: "Qué pasaría si lo publicara",
    queSiPublicoAyuda:
      "Se prueba contra las cuentas de verdad, sin escribir nada. Lo que " +
      "importa no es cuántas cambian: es cuántas se quedan sin territorio y " +
      "cuántas quedan en solape.",
    simular: "Simular con mis cuentas",
    simulando: "Simulando…",
    simulado: "Simulado contra {{cuantas}} cuentas.",
    resultado:
      "{{cambian}} cambiarían de territorio y {{quedan}} se quedarían igual.",
    sinTerritorio:
      "{{cuantas}} cuentas se quedarían SIN territorio. Eso no es un hueco que se rellene solo.",
    solapes:
      "{{cuantos}} solapes: dos territorios con la misma prioridad. La asignación acabaría dependiendo del orden alfabético.",
    seguro: "Se puede publicar: ni solapes ni cuentas sin dueño.",
    noSeguro: "NO conviene publicar todavía: arregla lo de arriba primero.",
    mapa: "Los territorios",
    sinTerritorios: "Todavía no hay ningún territorio definido",
    criterios: "{{cuantos}} criterios",
    prioridadRepetida:
      "{{cuantas}} prioridades repetidas: ahí es donde salen los solapes.",
    excepciones: "Cuentas fuera de su territorio",
    excepcionesAyuda:
      "Con su motivo y con cuándo dejan de aplicarse. Una excepción que " +
      "caduca devuelve la cuenta a su territorio de origen sin avisar a nadie.",
    sinExcepciones: "Ninguna cuenta está fuera de su territorio",
    permanente: "sin fecha",
    vence: "vence en {{dias}} días",
    cuotas: "Cuotas y su prorrateo",
    cuotasAyuda:
      "Quien entra a mitad de periodo no tiene la cuota entera, y medirle " +
      "contra ella es garantizarle que no la cumple. El objetivo del plan va " +
      "al lado del efectivo: sin los dos delante, uno parece equivocado.",
    logradoDe: "{{logrado}} de {{objetivo}}",
    prorrateada: "Prorrateada: en el plan son {{plan}}.",
  },
  liquidacion: {
    periodo: "del {{desde}} al {{hasta}}",
    recortado:
      "Se han recortado {{cuanto}} por el tope del plan. No es que se haya vendido menos: es el techo.",
    lineas: "De dónde sale cada euro",
    lineasAyuda:
      "Con la base y el porcentaje de cada línea. Un comercial que no puede " +
      "desglosar su comisión no se la cree, y la discusión acaba en una hoja " +
      "de cálculo paralela que nadie concilia.",
    sinLineas: "Esta liquidación no tiene líneas",
    baseYPct: "{{base}} al {{pct}} %",
    reversion: "reversión",
    disputas: "Reclamaciones",
    sinDisputas: "Nadie ha reclamado nada",
    sinResolver: "Sin resolver todavía.",
  },
  caso: {
    derivar: {
      boton: "Derivar",
      titulo: "Derivar el caso",
      explicacion:
        "Pásalo a otro nivel, a ingeniería o a una cola interna. Sigue siendo el mismo caso del cliente: no se crea otro ni se reinicia el reloj.",
      cola: "Cola destino",
      elige: "Elige una cola…",
      opcion: "{{nombre}} · nivel {{nivel}}",
      sinColas:
        "No hay otra cola a la que derivarlo. Las colas se crean en Casos › Colas.",
      motivo: "Motivo",
      motivoAyuda: "Qué se espera del siguiente nivel",
      interno: "Interno: no se le enseña al cliente",
      confirmar: "Derivar",
      enviando: "Derivando…",
    },
    // Contestar al cliente por correo desde su caso: sale de verdad, por el
    // canal de la casa, y lo que no sale se dice.
    responder: {
      titulo: "Responder al cliente",
      para: "Para",
      paraAyuda: "Correo del cliente",
      asunto: "Asunto",
      asuntoAyuda: "Re: el asunto del caso y su código",
      mensaje: "Mensaje",
      enviar: "Enviar respuesta",
      enviando: "Enviando…",
      enviada: "Enviada a {{para}}. Queda en lo apuntado del caso.",
      enviadaDeSerie:
        "Enviada a {{para}}, con la plantilla de serie: la empresa no tiene la suya. Queda en lo apuntado del caso.",
      noSalio:
        "No ha salido: {{motivo}}. Queda apuntada en el caso como no enviada.",
    },
    escribirArticulo: "Escribir esto en la base de conocimiento",
    avisoResolucion:
      "La resolución viene copiada tal cual, y casi siempre lleva el nombre del cliente, su configuración y a veces sus credenciales. Quítalo ANTES de guardar: el artículo nace en borrador e interno, pero lo que escribas aquí es lo que alguien publicará.",
    tituloArticulo: "Título del artículo",
    cuerpoArticulo: "Cuerpo del artículo",
    guardarArticulo: "Crear en borrador",
    guardando: "Creando…",
    cancelar: "Cancelar",
    articuloCreado:
      "Creado «{{clave}}» en borrador e interno. Se publica desde Conocimiento, cuando alguien lo revise.",
    relacionado: "Con qué tiene que ver",
    sinRelaciones: "No se ha dicho sobre qué es",
    yaNoEsta: "Ya no está: lo han borrado",
    sinNombre: "No se ha podido saber cuál",
    rel: {
      cuenta_id: "Cliente",
      contacto_id: "Contacto",
      producto_id: "Producto",
      activo_id: "Activo instalado",
      contrato_id: "Contrato",
      pedido_id: "Pedido",
    },
    reloj: "El reloj",
    sinSla: "Este caso no tiene SLA asignado",
    sla: "{{clave}} · versión {{version}}",
    primeraVence: "Primera respuesta: vence {{cuando}}",
    incumplioPrimera: "Primera respuesta INCUMPLIDA",
    resolucionVence: "Resolución: vence {{cuando}}",
    incumplioResolucion: "Resolución INCUMPLIDA",
    relojParado:
      "Reloj PARADO desde {{desde}}: se espera al cliente. Al reanudar, los vencimientos se desplazan lo que dure la espera.",
    enPausa:
      "El reloj lleva {{horas}} h parado esperando al cliente. No es tiempo sin atender.",
    jerarquia: "De qué cuelga y qué cuelga de él",
    sinJerarquia: "Ni padre, ni hijos, ni duplicados",
    cuelgaDe: "Cuelga de",
    duplicadoDe: "Es duplicado de",
    colgadoDe: "Colgado de la incidencia masiva",
    yaNoExiste: "un caso que ya no está",
    hijos: "Casos hijo ({{cuantos}})",
    colgados: "Colgados de esta incidencia ({{cuantos}})",
    duplicados: "Duplicados de éste ({{cuantos}})",
    cierre: "Cómo acabó",
    sinCerrar: "Todavía abierto",
    ultimoCierre: "Reabierto. El último cierre fue:",
    aceptadoPorCliente: "El cliente lo ha dado por resuelto desde el portal.",
    pendienteDelCliente:
      "Cerrado por el agente y PENDIENTE de que el cliente lo dé por bueno ({{estado}}). No cuenta como cerrado.",
    reaperturas:
      "Se ha reabierto {{cuantas}} veces. Un caso cerrado tres veces no es un caso resuelto.",
    historial: "Qué le ha pasado",
    sinHistorial: "Sin eventos todavía",
    porQueAqui: "Por qué está aquí",
    sinAsignacion: "No consta cómo llegó a su cola",
    reglasMiradas:
      "Se miraron {{cuantas}} reglas antes. Si son cero, no hay ninguna que cubra este caso.",
    derecho: "Qué derecho lo cubre",
    horasSinLimite: "Horas: sin límite ({{consumidas}} consumidas)",
    horasRestantes: "Horas: quedan {{restantes}} de {{incluidas}}",
    casosSinLimite: "Casos: sin límite ({{consumidos}} abiertos)",
    casosRestantes: "Casos: quedan {{restantes}} de {{incluidos}}",
    vigenteHasta: "Vigente hasta {{cuando}}.",
    alAgotar: "Agotado. Al agotarse: {{que}}.",
  },
  sobre: {
    sinReferencia: "Sobre sin referencia",
    verificable:
      "Esta firma se puede verificar: están el hash de lo enviado y el de lo firmado.",
    noVerificable:
      "Esta firma NO se puede verificar: falta alguno de los dos hashes. El estado pone «firmado» igual.",
    firmantes: "Quién firma y en qué orden",
    sinFirmantes: "Este sobre no tiene firmantes",
    identificado: "Identificado por {{como}}",
    sinIdentificar:
      "Sin identificación: es una casilla marcada por alguien con acceso al correo.",
    prueba: "La prueba",
    selloTiempo: "Sello de tiempo",
    hashEnviado: "Hash de lo enviado",
    hashFirmado: "Hash de lo firmado",
    certificado: "Certificado",
    documentoFirmado: "Documento firmado",
    falta: "falta",
    eventos: "Qué ha pasado con el sobre",
    sinEventos: "Sin eventos todavía",
    // Las acciones del sobre según su estado (CRM-06.01.02.11).
    acciones: {
      titulo: "Qué hacer con el sobre",
      enviar: "Enviar a firmar",
      recordar: "Recordar a quien le toca",
      cancelar: "Cancelar el sobre",
      archivar: "Archivar el firmado",
      confirmarEnvio:
        "Al cliente le llega un correo y no se puede deshacer. ¿Lo mandamos?",
      siEnviar: "Sí, enviarlo",
      siCancelar: "Cancelar el sobre",
      volver: "Volver",
      motivo: "Por qué se cancela",
      documentoFirmado: "Documento firmado (identificador)",
      certificado: "Certificado (opcional)",
      sello: "Sello de tiempo (opcional)",
      enviado:
        "Enviado al proveedor: ahora está «{{estado}}» y vale hasta el {{caduca}}.",
      recordado: "Recordado a: {{quienes}}.",
      nadieQueRecordar: "No hay nadie a quien le toque firmar ahora.",
      cancelado: "Sobre cancelado.",
      archivado: "Firmado archivado y enlazado a {{n}} registro(s).",
      archivadoSinOrigen:
        "Firmado archivado, pero el sobre no cuelga de ningún registro: no saldrá en ninguna ficha.",
    },
  },
  plataforma: {
    titulo: "Plataforma y cumplimiento",
    entradilla:
      "Quién tocó qué, qué se salió de lo normal, qué datos personales trata " +
      "cada servicio y qué se puede recuperar.",
    servicio: "Servicio",
    deEsteServicio: "De «{{servicio}}»",
    auditoria: "Quién tocó qué",
    auditoriaAyuda:
      "El registro de accesos, cambios, exportaciones y acciones de " +
      "administración. Se consulta aquí en vez de exportarlo a otra " +
      "herramienta: «¿quién tocó esta cuenta?» se pregunta mientras se mira la " +
      "cuenta, y obligar a salir significa que casi nunca se responde.",
    volcarSiem: "Volcar al SIEM",
    filtroAccion: "Filtrar por acción",
    filtroObjeto: "Filtrar por objeto",
    filtroPeticion: "Identificador de petición",
    auditoriaDonde: "De qué servicio",
    auditoriaTodos: "Todos los servicios",
    auditoriaSinRespuesta:
      "No han contestado: {{servicios}}. La lista no los incluye.",
    entrarComo: {
      titulo: "Entrar como otra persona, por soporte",
      ayuda:
        "Entras con la sesión de una persona de la empresa que estás mirando en la barra, para ver lo que ella ve. El motivo queda en la auditoría del cliente y la sesión caduca sola. Arriba verás siempre de quién es y por qué, y desde ahí vuelves a la tuya.",
      persona: "Persona",
      elige: "Elige a quién…",
      motivo: "Motivo",
      motivoEjemplo: "Ticket 4312: no puede cerrar una oportunidad",
      motivoCorto:
        "El motivo tiene que tener al menos diez caracteres: es lo que hace defendible el acceso.",
      entrar: "Entrar como esta persona",
      reverificar:
        "Antes tienes que volver a verificar tu identidad con tu segundo factor (Identidad y seguridad).",
      sinFactor:
        "Para entrar como otra persona hace falta segundo factor, y tu cuenta no tiene ninguno configurado.",
    },
    filtrarPorPeticion: "Ver todo lo que escribió esta petición",
    enNombreDe: "en nombre de otra persona",
    sinApuntes: "Sin apuntes con ese filtro",
    anomalias: "Lo que se salió de lo normal",
    anomaliasAyuda:
      "Exportaciones y lecturas masivas de los últimos treinta días, con " +
      "cuántos registros salieron y si se bloquearon.",
    bloqueada: "Bloqueada",
    permitida: "Permitida",
    sinAnomalias: "Nada fuera de lo normal en los últimos treinta días",
    cumplimiento: "Datos personales y permisos",
    cumplimientoAyuda:
      "El registro de tratamiento de este servicio y quién puede hacer qué en " +
      "él, derivado de las rutas montadas y de los permisos reales.",
    tratamientos: "{{cuantos}} tratamientos declarados",
    tratamientoObjeto: "Dato",
    tratamientoFinalidad: "Finalidad",
    tratamientoBase: "Base legal",
    tratamientoPlazo: "Plazo de conservación",
    sinTratamiento:
      "{{cuantos}} objetos con datos personales y sin tratamiento declarado",
    ratCompleto:
      "Todo objeto con datos personales tiene su tratamiento declarado",
    permisos: "Permisos",
    sinRol: "{{cuantos}} permisos que exige alguna ruta y no tiene ningún rol",
    sinRuta: "{{cuantos}} permisos concedidos que ninguna ruta exige",
    recuperable: "Qué se puede recuperar",
    recuperableAyuda:
      "Lo que hay en la papelera de este servicio, lo primero lo que menos " +
      "tiempo le queda antes de purgarse.",
    diasParaPurga: "{{dias}} d",
    enCascada: "y {{cuantos}} registros colgando",
    papeleraVacia: "No hay nada borrado pendiente de purgar",
    restaurables: "Objetos restaurables: {{objetos}}",
    volverAtras: "Hasta dónde se puede volver atrás",
    volverAtrasAyuda:
      "Cuánto se perdería si el incidente fuera ahora, frente a lo " +
      "comprometido, y si la retención llega hasta donde se pide. Las dos " +
      "preguntas del día del incidente, que es el día en que nadie se pone a " +
      "buscarlas.",
    sePerderia: "Se perderían {{minutos}} min",
    comprometido: "(comprometido: {{minutos}} min)",
    noMedible: "No se puede medir",
    ventana: "Volver {{pedidos}} d atrás con {{retencion}} d de retención",
    volumen: "Qué va camino de dar problemas",
    volumenAyuda:
      "Las particiones que hay que crear antes de que hagan falta. Una que " +
      "falta no se nota hasta que la escritura falla, y entonces ya es un " +
      "incidente.",
    ultimaParticion: "Última partición que ya existe",
    faltaLaDeEsteMes: "Falta la partición de este mes",
    particionesPorCrear: "{{cuantas}} particiones por crear",
    boveda: "Tarjetas e identificadores fiscales",
    bovedaAyuda:
      "Si este despliegue puede sacar del CRM un número sensible y quedarse " +
      "sólo con una referencia.",
    conBoveda: "Hay bóveda: se puede tokenizar",
    sinBoveda: "No hay bóveda",
    politicasActivas: "{{cuantas}} políticas de acceso activas",
    sinAvisos: "El informe no levanta ningún aviso",
    comoSeCorta: "Cómo se corta cada tabla que crece",
    comoSeCortaAyuda:
      "Por tiempo y no por cliente: con dos mil clientes salen dos mil " +
      "particiones y el planificador tarda más en decidir que en ejecutar.",
    mesesEnCaliente: "{{meses}} meses en caliente",
    rastro: "Qué guarda su historia completa",
    rastroAyuda:
      "El rastro completo permite reconstruir un registro paso a paso. No está " +
      "encendido para todo, y eso es una decisión, no un hueco.",
    sinRastroCompleto: "Ninguno en este servicio",
  },
  recorrido: {
    titulo: "Recorrido por la solución",
    intro:
      "Cada paso lleva a una pantalla real, con el identificador del catálogo delante. Se construye desde los módulos, no de un guion aparte: un guion se queda viejo a la tercera pantalla que alguien añade.",
    cuantos: "{{modulos}} módulos en {{grupos}} áreas",
    cierre:
      "Lo que no aparece aquí, no está hecho. La hoja de estado del catálogo dice qué falta y en qué fase.",
  },
  rendimiento: {
    titulo: "Rendimiento",
    intro: "Cuánto hay, cuánto cabe y qué se está aplazando ahora mismo.",
    queSeAplaza: "Qué se está aplazando",
    sinRespuesta:
      "No han contestado: {{servicios}}. No cuentan como tranquilos.",
    limites: "Límites del plan",
    recurso: "Recurso",
    usado: "Usado",
    limite: "Límite",
    noConsta: "no consta",
  },
  seguridad: {
    aislamiento: "¿Qué impide que una empresa vea a otra?",
    campos: {
      titulo: "Campos que no se comportan como dice su clasificación",
      todosLosRoles: "todos los roles",
    },
    simulador: {
      permitido: "Sí podría",
      denegado: "No podría",
      concede: "concede",
      niega: "niega",
      rbac: "Por su rol: {{veredicto}} ({{permiso}})",
      abac: "Por los atributos: {{veredicto}}",
      contexto:
        "Evaluado con roles {{roles}} · unidad {{unidad}} · hora {{hora}}",
    },
    capaPuesta: "(puesta)",
    capaNoPuesta: "(NO está haciendo su trabajo)",
    noSeMideAqui: "no se mide desde aquí",
    aQuienLeToca: {
      titulo: "«No puedo entrar»: ¿por dónde le toca entrar?",
      porQue:
        "El usuario sabe su correo, no si su empresa usa Entra ID o Ping. Y el subdominio hereda del dominio padre, así que mirarlo a ojo falla justo en los casos raros, que son los que generan la incidencia.",
      correo: "Correo de quien no puede entrar",
      mirar: "Mirar",
      mirando: "Mirando…",
      entraPorSso: "Le toca entrar por SSO, con «{{nombre}}» ({{tipo}}).",
      entraPorContrasena:
        "A ese correo no le toca ningún proveedor: entra con contraseña del CRM.",
      sinContrasenaLocal:
        "Y no puede usar contraseña local: su dominio tiene el SSO forzado, así que no hay vía de escape.",
    },
    entrada: {
      titulo: "Cómo se entra en esta empresa",
      ayuda:
        "Con qué proveedor de identidad, si la contraseña local está cortada y quién se lo salta, si se aceptan aserciones que empiezan en el proveedor y si el segundo factor se le delega a él.",
      forzadoSi: "Esta empresa obliga a entrar por su proveedor de identidad.",
      forzadoNo:
        "La contraseña local sigue admitiéndose: quien se va del directorio puede seguir entrando por esa puerta.",
      sinProveedor: "No hay ningún proveedor de identidad declarado",
      sinProveedorPorque:
        "Sin proveedor se entra con contraseña local, así que dar de baja a alguien en el directorio de la empresa no le cierra el CRM.",
      apagado: "apagado",
      jitSi: "Da de alta al entrar por primera vez.",
      jitNo: "No da de alta solo: el usuario tiene que existir aquí antes.",
      idpInitiadoSi:
        "Acepta aserciones que empiezan en el proveedor. Sin petición nuestra que atarlas, una aserción robada se puede reenviar: conviene que esté así a propósito.",
      idpInitiadoNo: "Sólo acepta entradas que empiezan aquí.",
      mfaDelegada: "El segundo factor lo da por cumplido el proveedor",
      mfaAqui: "El segundo factor se pide aquí.",
      forzadoEnEste: "Este proveedor corta la contraseña local.",
      rescate: "se lo saltan",
      scimSi: "El aprovisionamiento automático está activo.",
      scimNo:
        "Sin aprovisionamiento automático: una baja en el directorio no cierra nada aquí.",
      politicas_one: "{{cuantas}} política de acceso por contexto.",
      politicas_other: "{{cuantas}} políticas de acceso por contexto.",
      politicas_zero:
        "Ninguna política de acceso por contexto: no se mira ni la IP, ni el dispositivo, ni la hora.",
      sinCierrePropagado_one:
        "{{cuantas}} de tus sesiones no se cerrará en el proveedor al salir.",
      sinCierrePropagado_other:
        "{{cuantas}} de tus sesiones no se cerrarán en el proveedor al salir.",
    },
    mio: {
      titulo: "Tu segundo factor",
      valeSolo: "Con «{{factor}}» podrías entrar sin contraseña.",
      noValeSolo: "Con «{{factor}}» no se puede quitar la contraseña.",
      entradaDeHoy: "Has entrado con: {{factores}}",
      passkeys: "{{cuantas}} passkeys registradas",
      sensibles: "Te pedirán verificarte otra vez para",
      inscribir_primero: "Inscribe un primer factor",
      inscribir_respaldo: "Inscribe un método de respaldo",
      inscribir_fuerte: "Inscribe un factor fuerte (passkey o aplicación)",
    },
    titulo: "Identidad y seguridad",
    entradilla:
      "Las preguntas que no son una tabla: quién no tiene segundo factor, qué " +
      "certificado caduca, quién tiene permisos incompatibles y por qué esta " +
      "persona ve esto.",
    mfa: {
      titulo: "Quién no tiene segundo factor",
      // El N al lado del porcentaje siempre: un 78 % sobre nueve personas no es
      // lo mismo que sobre novecientas, y sin el N se leen igual.
      resumen: "{{pct}} % lo tiene: {{con}} de {{total}} personas.",
      sinUsuarios: "Todavía no hay nadie a quien medir.",
      noObligatoria:
        "El segundo factor no es obligatorio en este tenant: quien no lo active, no lo tendrá.",
      canalesDebiles:
        "Hay canales débiles activos ({{canales}}): se interceptan sin tocar el dispositivo. " +
        "Cuentan como segundo factor y no protegen como una passkey.",
      todos: "Todo el mundo tiene segundo factor",
      todosDetalle: "No hay nadie con quien hablar.",
      // MFA obligatoria por rol (CRM-00.05.01.06).
      obligatoriaParaTodos:
        "La instalación exige segundo factor a todo el mundo, tenga el rol que tenga.",
      seQuedanFuera_one:
        "1 persona se quedaría fuera: se le exige segundo factor y todavía no lo tiene.",
      seQuedanFuera_other:
        "{{cuantas}} personas se quedarían fuera: se les exige segundo factor y todavía no lo tienen.",
      seLeExige: "se le exige",
      porRolTitulo: "A quién se le exige",
      porRolAyuda:
        "Elige los roles que tienen que entrar con segundo factor. A quien lleve alguno se le pedirá el código al entrar con contraseña; si aún no lo tiene configurado, no podrá entrar hasta hacerlo. Sin roles, manda el ajuste general de la instalación.",
      porRolNinguno: "Ningún rol: no se exige por rol.",
      anadirRol: "Añadir un rol…",
      quitarRol: "Quitar {{rol}}",
      guardar: "Guardar",
      guardando: "Guardando…",
      porRolGuardado:
        "Guardado. Se aplica en la próxima entrada de cada persona.",
      factoresQueCumplen:
        "Cumplen una aplicación de códigos (TOTP) o una passkey; el SMS y el correo cuentan si la empresa los tiene encendidos. No hay notificación push.",
    },
    // Segundo factor verificado por el proveedor del tenant (CRM-00.05.01.22).
    proveedor: {
      titulo: "Segundo factor con el proveedor de la empresa",
      ayuda:
        "Si la empresa ya usa Okta Verify, Twilio Verify, Duo o RSA, el código de esa aplicación sirve para entrar: el login se lo pregunta al proveedor. Se declara como perfil —dirección, autenticación, cuerpo y dónde contesta— y no hay código de ninguno. El código propio (TOTP) y los de recuperación siguen valiendo.",
      ninguno: "Ningún proveedor de segundo factor declarado.",
      nuevo: "Nuevo perfil",
      desdePlantilla: "Empezar desde una plantilla…",
      sinPlantilla: "En blanco",
      nombre: "Nombre",
      plantilla: "Plantilla",
      activo: "Activo",
      activoAyuda:
        "Uno activo por empresa. Activo, el login pregunta a este proveedor por el código.",
      url: "Dirección del proveedor",
      metodo: "Método",
      formato: "Formato del cuerpo",
      autenticacion: "Autenticación",
      autTipos: {
        ninguna: "Ninguna",
        basica: "Básica (usuario y secreto)",
        bearer: "Bearer (secreto)",
        cabecera: "Cabecera propia",
      },
      autUsuario: "Usuario de la autenticación básica",
      autCabecera: "Cabecera",
      autValor: "Valor de la cabecera ({{marca}} es el secreto)",
      secreto: "Secreto",
      secretoGuardado:
        "Hay un secreto guardado y no se enseña. Déjalo vacío para conservarlo.",
      secretoNuevo: "Se guarda cifrado y no se vuelve a enseñar.",
      variables: "Variables del perfil",
      camposPersona:
        "Datos de cada persona en el proveedor (separados por comas)",
      cuerpo: "Cuerpo (JSON con marcas: {{marcas}})",
      cabeceras: "Cabeceras extra (JSON)",
      respuestaCampo: "Campo de la respuesta que dice si vale",
      respuestaValidos: "Valores que significan «vale» (separados por comas)",
      jsonMal: "«{{campo}}» no es un JSON válido.",
      guardar: "Guardar el perfil",
      guardando: "Guardando…",
      guardado: "Perfil guardado.",
      cancelar: "Cancelar",
      editar: "Editar",
      borrar: "Borrar",
      borrarSeguro:
        "¿Borrar el perfil «{{nombre}}»? El login dejará de preguntar a este proveedor.",
      borrado: "Perfil borrado.",
      ultimaPrueba: "Última prueba",
      sinProbar: "sin probar",
      vale: "vale",
      noVale: "no vale",
      personas: "Quién es cada persona en el proveedor",
      personasAyuda:
        "Lo que este perfil necesita de cada persona. Sin estos datos, a esa persona no se le puede comprobar el código con el proveedor.",
      persona: "Persona",
      elegirPersona: "Elige una persona…",
      vincular: "Guardar sus datos",
      vinculado: "Datos guardados.",
      nadieVinculado: "Nadie tiene todavía sus datos apuntados.",
      probar: "Probar un código",
      probarAyuda:
        "Hace la misma llamada que el login, sin entrar. Enseña la petición con el secreto y el código tapados.",
      codigo: "Código",
      probando: "Probando…",
      resultadoVale: "El proveedor da el código por bueno.",
      resultadoNoVale: "El proveedor no da el código por bueno.",
      peticion: "Petición enviada",
      http: "HTTP {{estado}}",
    },
    certificados: {
      titulo: "Certificados del proveedor de identidad",
      porQue:
        "Un certificado que caduca no avisa: un sábado por la noche deja de validar " +
        "toda aserción y el lunes no entra nadie de la empresa.",
      ninguno: "Ningún certificado declarado",
      ningunoDetalle:
        "O no hay proveedor de identidad configurado, o ninguno ha registrado su certificado de firma.",
      sinFecha: "sin fecha",
      dias: "{{dias}} días",
      estado: {
        vigente: "vigente",
        por_caducar: "caduca pronto",
        caducado: "caducado",
        sin_fecha: "sin fecha",
      },
    },
    sod: {
      titulo: "Permisos incompatibles",
      porQue:
        "Calculado en vivo sobre {{reglas}} reglas y no guardado: una lista de " +
        "conflictos vieja es peor que ninguna, porque se actúa sobre ella.",
      sinReglas: "No hay reglas de incompatibilidad declaradas.",
      resumen:
        "{{conflictos}} conflictos sin excepción, sobre {{reglas}} reglas y los permisos de ahora.",
      irA: "Ver la segregación de funciones",
    },
    explicador: {
      titulo: "Por qué esta persona puede hacer esto",
      porQue:
        "Sin esto, la respuesta se busca leyendo roles, políticas y reglas de " +
        "compartición a la vez, y se contesta mal.",
      usuario: "Usuario",
      objeto: "Objeto",
      accion: "Acción",
      preguntar: "Preguntar",
    },
  },
  modulo: {
    entradilla: "Versión {{version}} · {{autor}} · {{estado}}",
    sinAutor: "sin autor declarado",
    manifiesto: "Qué declara",
    trae: "Trae {{objetos}} objetos y {{campos}} campos",
    espacioDeNombres:
      "Sus cosas viven bajo «{{prefijo}}», para que dos módulos no se pisen un objeto con el mismo nombre",
    dependeDe: "Depende de: {{cuales}}",
    sinDependencias: "No depende de ningún otro módulo",
    nucleo: "núcleo mínimo {{version}}",
    huella: "Huella {{huella}}…",
    sinHuella: "Sin huella: no se instaló desde el catálogo firmado",
    integridad: "¿Sigue siendo el que instalamos?",
    integro: "Lo instalado coincide con lo publicado",
    tocado: "Hay partes que ya no coinciden con lo publicado",
    tocadosAMano: "Tocado a mano: {{cuales}}",
    desaparecidos: "Ya no está: {{cuales}}",
    uso: "¿Se usa?",
    usados: "{{usados}} de {{elementos}} elementos se han usado alguna vez",
    sinUsar: "Sin usar nunca: {{cuales}}",
    ajustados: "Ajustados por el cliente: {{cuales}}",
    pantallas: "Qué aporta a la interfaz",
    sinPantallas: "Este módulo no declara ninguna pantalla",
    sinPantallasPorque:
      "El front oficial sólo pinta lo que el módulo declara. Sin superficie declarada, sus objetos se ven por el módulo genérico.",
    quitar: "¿Qué pierdo si lo quito?",
    verQuePasaria: "Ver qué pasaría al quitarlo",
    quitaria: "Se quitarían {{cuantos}} elementos del módulo",
    registros: "Registros por objeto: {{cuales}}",
    sinContar:
      "No se han podido contar los registros de {{cuales}}: no es que sean cero, es que no se sabe",
    ajustadosSePierden: "Lo que el cliente ajustó y se perdería: {{cuales}}",
    dependen:
      "No se puede quitar: {{cuales}} depende de este módulo. Quita antes ese, o déjalo.",
    borrarDatos: "Borrar también los registros de sus objetos",
    borrarDatosAviso:
      "Sin marcar, los registros se conservan y quedan sin pantalla que los enseñe. Marcado, se borran.",
    quitarDeVerdad: "Quitar el módulo",
  },
  suite: {
    // Alta del tenant en cascada (CRM-00.01.07.02).
    alta: {
      titulo: "Alta de la empresa en las herramientas",
      ayuda:
        "Da de alta a esta empresa en cada herramienta conectada y enseña en qué quedó en cada una. Sólo el alta de la empresa: las personas y los departamentos van por su lado.",
      boton: "Dar de alta en las herramientas",
      enviando: "Dando de alta…",
      resumen:
        "De {{total}} herramientas, {{aplicadas}} la tienen dada de alta y {{fallidas}} han fallado.",
      ninguna: "No hay ninguna herramienta conectada que gobierne la empresa.",
      inactiva: "herramienta apagada",
      estado: {
        sin_alta: "Sin alta",
        pendiente: "Pendiente",
        aplicado: "Dada de alta",
        fallido: "Ha fallado: se reintentará",
        cuarentena: "Apartada: necesita una persona",
      },
    },
    organigrama:
      "Áreas del cliente, definidas una vez y compartidas por las tres herramientas ({{cuantas}})",
    cuelgaDe: "Cuelga de {{de}}",
    mapeoDeRoles: "{{cuantos}} roles correspondidos",
    plan: "{{altas}} altas · {{bajas}} bajas · {{cambios}} cambios · {{sin_cambio}} sin tocar",
    bajasDelPlan: "Bajas: {{cuales}}",
    sinDireccion: "sin dirección declarada",
    ssoCompartido:
      "Proveedor de identidad compartido: se configura una vez y lo usan {{cuantas}} herramientas",
    noConecta: "Esto no conecta: ¿qué falta exactamente?",
    noConectaPorque:
      "«Error de autenticación» no dice si es la contraseña, el permiso, el inquilino o el reloj — y probándolo todo se acaba pidiendo permisos de administrador global «para descartar». Pega aquí lo que diga el proveedor y te decimos qué pasa.",
    codigoHttp: "Código que devuelve (401, 403, 429…)",
    mensajeDelProveedor: "Mensaje del proveedor, tal cual",
    alcancesConcedidos: "Alcances concedidos, separados por comas",
    alcancesNecesarios: "Alcances necesarios, separados por comas",
    queFalla: "Dime qué falla",
    mirando: "Mirando…",
    faltanEstos: "Faltan:",
    antesDeDesconectar: "Antes de desconectar: qué se queda y qué se va",
    antesDeDesconectarPorque:
      "No es simétrico, y por eso se enseña entero: las actividades registradas se quedan —son el histórico de la empresa— y la copia de su agenda se va, porque era suya.",
    porQueSeDesconecta: "Por qué se desconecta",
    motivoRevocacion: "La persona ha revocado el permiso",
    motivoBaja: "La persona se va de la empresa",
    motivoFinContrato: "Se acaba el contrato con la suite",
    seQueda: "Se queda en el CRM",
    seBorra: "Desaparece",
    saludSuites: "Correo, calendario y contactos de cada uno",
    saludSuitesAyuda:
      "Qué buzón lleva sin sincronizar y por qué, qué credenciales van a dejar " +
      "de funcionar y qué suscripciones hay que renovar. Las tres se preguntan " +
      "ANTES de que pase algo, que es cuando sirven.",
    queSabeHacer: "Qué sabe hacer cada suite",
    queSabeHacerAyuda:
      "Un perfil de suite es configuración, no código: lo que distingue a dos proveedores es lo que se declara aquí. Qué recursos trae, en qué sentido va cada uno, cómo se reanuda y qué entra de verdad.",
    quePerfil: "Qué suite",
    sinPerfiles: "No hay ninguna suite declarada",
    sinPerfilesPorque:
      "Un perfil se declara con su dirección, sus alcances y qué recursos trae. Sin ninguno no entra correo ni calendario de nadie, y eso no se nota: simplemente no llega nada.",
    perfilSinRecursos: "Este perfil no declara ningún recurso",
    perfilSinRecursosPorque:
      "Se puede guardar un perfil sin decir qué trae, y entonces se conecta y no sincroniza nada. No es un fallo de la conexión: es que no se le ha pedido nada.",
    leyendoCapacidades: "Leyendo qué trae…",
    criterioDeEntrada: "Entra",
    nuncaEntra: "No entra nunca",
    pedidoYNoPermitido: "Pedido por la persona y no permitido por la empresa",
    consentimientos_one: "{{cuantos}} persona ha conectado su cuenta",
    consentimientos_other: "{{cuantos}} personas han conectado su cuenta",
    preguntas: "Preguntas sobre la suite conectada",
    preguntasAyuda:
      "Tres preguntas que se hacen en un momento concreto y que el servidor contestaba desde el principio sin que hubiera dónde hacerlas.",
    deQuienEsEstaCuenta: "¿De quién es esta cuenta?",
    ejemploDireccion: "nombre@empresa.com",
    resolver: "Resolver",
    compartido: "buzón compartido",
    cuandoEstaLibre: "¿Cuándo está libre?",
    desde: "Desde",
    hasta: "Hasta",
    verHuecos: "Ver huecos",
    queEntrariaDe: "¿Qué entraría de un fichero?",
    comprobar: "Comprobar",
    entrarianDe: "Entrarían {{entrarian}} de {{filas}} filas",
    sinIdentificador_one: "{{cuantas}} fila sin identificador.",
    sinIdentificador_other: "{{cuantas}} filas sin identificador.",
    sePuedeSincronizar: "¿Se puede ya?",
    noSeHaPodido: "No se ha podido comprobar",
    sinRefresco: "sin refresco: caducará y dejará de entrar",
    sinConexiones: "Ninguna conexión de suite configurada",
    sinConexionesPorque:
      "No es «todo al día»: es que nadie ha conectado su correo ni su calendario.",
    paradas: "{{cuantas}} de {{total}} conexiones paradas",
    todasAlDia: "Las {{total}} conexiones están al día",
    horasParada: "{{horas}} h",
    enSondeo:
      "{{cuantas}} van por sondeo porque no se pudo renovar su suscripción: sus " +
      "cambios entran con retraso, no al instante.",
    sinMedir:
      "{{cuantas}} sin medir: de ésas no se dice nada, no se han mirado.",
    credenciales: "Credenciales",
    credencialesAlDia: "Ninguna de las {{revisados}} pide nada",
    credencialesSinRevisar:
      "Ninguna credencial que revisar: nadie ha autorizado todavía su correo ni su calendario.",
    suscripciones: "Suscripciones",
    suscripcionesAlDia: "Ninguna pendiente de renovar",
    sinCaducidadDeclarada:
      "sin caducidad declarada: no es «no caduca», es que no se sabe",
    comoUnTodo: "La suite, de una vez",
    comoUnTodoAyuda:
      "Qué cambiaría lo que está a punto de aplicarse, cómo ve el cliente la " +
      "suite entera y si las bajas se cerraron en TODAS las herramientas.",
    aAplicar: "{{cuantos}} cambios por aplicar · {{ya}} ya aplicados",
    identidad: "El cliente, para la suite: {{nombre}} ({{estado}})",
    quedanAbiertas: "{{cuantas}} herramientas con accesos todavía abiertos",
    todoCerrado: "Cerrado en las {{cuantas}} herramientas",
    titulo: "Gobierno de la suite",
    intro:
      "Las herramientas de la casa, quién entra en cada una y qué falta por aplicar.",
    sinHerramientas: "No hay herramientas conectadas",
    sinHerramientasPorque:
      "Un «todo bien» aquí haría creer que el cliente está en la suite cuando solo está en el CRM.",
    herramienta: "Herramienta",
    estado: "Estado",
    bajas: "Bajas sin aplicar",
    ultimoError: "Último error",
    bajasSinAplicar:
      "{{cuantas}} bajas sin aplicar: son accesos que siguen abiertos.",
    sinBajasPendientes: "No hay bajas pendientes de aplicar.",
    cuarentena: "{{cuantas}} elementos en cuarentena.",
    queSeMando: "Qué se mandó",
    intentos: "Intentos",
    esUnaBaja: "BAJA —",
    reintentar: "Volver a intentarlo",
    reintentando: "Reintentando…",
    noEsControlRemoto:
      "Esto no es un panel de control remoto: cada herramienta manda en lo suyo y aquí se ve lo que publica.",
  },
  // Decidir una aprobación desde el correo (CRM-00.03.05.12).
  decidirPorEnlace: {
    titulo: "Decidir una aprobación",
    entradilla:
      "Te han pedido una aprobación. Puedes decidirla aquí, sin entrar al CRM.",
    queSeDecide: "Qué se decide",
    etapa: "Etapa: {{etapa}}",
    caduca: "Este enlace sirve una sola vez y caduca el {{fecha}}.",
    tuDecision: "Tu decisión",
    comentario: "Comentario",
    comentarioAyuda:
      "Para pedir cambios hace falta decir cuáles; al aprobar o rechazar es opcional.",
    pideComentario: "Escribe qué cambios pides",
    aprobar: "Aprobar",
    rechazar: "Rechazar",
    pedirCambios: "Pedir cambios",
    unSoloUso:
      "La decisión queda registrada a tu nombre, como hecha desde el correo. No reenvíes este enlace: decide por ti.",
    invalido: "Este enlace ya no sirve",
    invalidoDetalle:
      "Puede que ya se haya usado, que haya caducado o que la aprobación ya no esté esperando tu decisión. Si todavía te toca decidir, la tienes en tu bandeja de aprobaciones del CRM.",
    hecho: {
      aprobar: "Has aprobado la solicitud.",
      rechazar: "Has rechazado la solicitud.",
      pedir_cambios: "Has pedido cambios.",
    },
    estadoAhora: "Ahora la aprobación está: {{estado}}.",
    estados: {
      pendiente: "pendiente de otras firmas",
      aprobada: "aprobada",
      rechazada: "rechazada",
      cambios_pedidos: "con cambios pedidos",
    },
  },
  // El editor de tablas de decisión (CRM-00.03.02.10).
  tablasDecision: {
    nueva: "Nueva tabla de decisión",
    entradilla:
      "La política escrita como datos: cada fila es una regla, cada columna de la izquierda una condición y cada una de la derecha lo que sale.",
    volver: "Tablas de decisión",
    validar: "Validar",
    guardar: "Guardar",
    guardada:
      "Tabla guardada. Los procesos que la usan ya deciden con esta versión.",
    validada: "La tabla está bien formada. Abajo, lo que dice el análisis.",
    conProblemas: "La tabla tiene problemas: abajo, cuáles.",
    general: "La tabla",
    nombre: "Nombre",
    clave: "Clave",
    claveAyuda: "Es como la llaman los procesos. No se puede cambiar después.",
    claveFija: "Es como la llaman los procesos: no se cambia.",
    politica: "Si casan varias reglas",
    politicas: {
      primera: "Gana la primera",
      unica: "Sólo puede casar una",
      prioridad: "Gana la de más prioridad",
      cualquiera: "Varias, si dicen lo mismo",
      todas: "Se acumulan todas",
    },
    politicasAyuda: {
      primera: "Gana la primera regla que case, en el orden de la tabla.",
      unica: "Si casan dos a la vez es un error de la tabla, y se dice.",
      prioridad: "Cada regla lleva su prioridad; a igualdad, la primera.",
      cualquiera: "Pueden casar varias, pero tienen que dar la misma salida.",
      todas:
        "Cada salida devuelve la lista de lo que dieron todas las que casan.",
    },
    activa: "Activa: los procesos pueden usarla",
    entradas: "Columnas de entrada",
    entradasAyuda:
      "Lo que se compara. La expresión dice de dónde sale el valor: @oportunidad.importe.",
    salidas: "Columnas de salida",
    salidasAyuda: "Lo que devuelve la tabla cuando casa una regla.",
    columnaClave: "Clave",
    columnaEtiqueta: "Rótulo",
    columnaExpresion: "Expresión",
    columnaTipo: "Tipo",
    sinTipo: "Sin declarar",
    tipos: {
      numero: "Número",
      texto: "Texto",
      booleano: "Sí / no",
      lista: "Lista",
      fecha: "Fecha",
    },
    quitarColumna: "Quitar la columna {{clave}}",
    anadir_entradas: "Añadir entrada",
    anadir_salidas: "Añadir salida",
    reglas: "Reglas",
    reglasAyuda:
      "Una fila por regla. Una casilla vacía es «cualquiera». Para comparar con otro dato del proceso, escribe @ruta.del.dato. Con «está en», separa los valores con comas.",
    reglaNombre: "Regla",
    reglaN: "Regla {{n}}",
    si: "Si {{columna}}",
    entonces: "→ {{columna}}",
    prioridad: "Prioridad",
    subir: "Subir",
    bajar: "Bajar",
    quitarRegla: "Quitar la regla {{n}}",
    anadirRegla: "Añadir regla",
    cualquiera: "cualquiera",
    anadirCondicion: "+ condición",
    anadirCondicionEn: "Añadir condición en {{columna}}",
    yAdemas: "+ y además",
    quitarCondicion: "Quitar la condición",
    operadorDe: "Comparación de {{columna}}",
    valorDe: "Valor de {{columna}}",
    salidaDe: "{{columna}} de la regla {{n}}",
    operadores: {
      "=": "=",
      "!=": "≠",
      ">": ">",
      ">=": "≥",
      "<": "<",
      "<=": "≤",
      en: "está en",
      contiene: "contiene",
      vacio: "está vacío",
      no_vacio: "no está vacío",
    },
    analisis: "Análisis",
    problemas: "Hay que arreglar esto antes de guardar:",
    sinAvisos: "Sin huecos, sin solapes y sin reglas que nunca casen.",
    huecos_one: "Un hueco: valores que ninguna regla cubre",
    huecos_other: "{{count}} huecos: valores que ninguna regla cubre",
    hueco: "{{entrada}}: de {{rango}}",
    sinRed:
      "Y no hay regla «en cualquier otro caso»: en esos valores la tabla no dará respuesta.",
    solapes_one: "Un solape",
    solapes_other: "{{count}} solapes",
    inalcanzables_one: "Una regla que nunca casará",
    inalcanzables_other: "{{count}} reglas que nunca casarán",
    tapada: "{{regla}}: la tapa siempre {{por}}",
    indecidibles: "El análisis no se pronuncia sobre: {{lista}}.",
    probar: "Probar",
    probarAyuda:
      "Con la tabla tal como está en pantalla, sin guardarla. Escribe unos datos y mira qué sale y por qué.",
    probarBoton: "Probar con estos datos",
    verdadero: "Sí",
    falso: "No",
    salio: "Qué sale",
    nadaSalio: "Nada: ninguna regla casa con estos datos.",
    porDefecto: "No casó ninguna regla.",
    acertaron: "Casan: {{lista}}. {{politica}}",
    porQue: "Por qué",
    resultado: "Resultado",
    explicacion: "Explicación",
    caso: "Casa",
    noCaso: "No casa",
    falloEn:
      "Falla en {{entrada}}: pide {{operador}} {{esperado}} y vale {{encontrado}}",
    vacio: "(vacío)",
    cumpleTodas: "Cumple todas sus condiciones",
  },
  // Los encargos en el portal del cliente (CRM-00.04.05.06).
  portalComunidad: {
    titulo: "Tu pregunta",
    cuerpo: "Cuéntala con detalle (opcional)",
    publicar: "Preguntar a la comunidad",
    enviando: "Enviando…",
    enviada: "Recibida. La verán los demás en cuanto la revisemos.",
    fallo: "No se ha podido publicar tu pregunta",
  },
  portalCierre: {
    pregunta: "Lo hemos dado por resuelto. ¿Lo está?",
    resolucion: "Lo que hicimos",
    si: "Sí, está resuelto",
    no: "No, sigue pasando",
    queSigue: "Qué sigue sin funcionar",
    queSigueAyuda:
      "Lo leerá quien lo retome: cuanto más concreto, menos te volveremos a preguntar.",
    enviarNo: "Reabrir mi petición",
    cancelar: "Cancelar",
    enviando: "Enviando…",
    aceptado: "Dado por resuelto por ti",
    fallo: "No se ha podido guardar tu respuesta",
  },
  portalEncargos: {
    titulo: "Vuestros envíos y encargos",
    cargando: "Cargando…",
    vacio: "No consta ningún encargo a nombre de tu empresa.",
    fallo: "No se ha podido cargar",
    verSeguimiento: "Ver por dónde va",
    ocultar: "Ocultar",
    prometido: "previsto para el {{cuando}}",
    vaTarde: "Va con retraso sobre lo previsto.",
    sinHitos: "Todavía no hay novedades de este encargo.",
    incidenciaAbierta: "Incidencia abierta: {{tipo}}",
    incidenciaCerrada: "Incidencia resuelta: {{tipo}}",
    sinNovedad: "Hace tiempo que no hay novedades: lo estamos mirando.",
  },
  // Marketing que sale de verdad: envíos por destinatario, salida por clase,
  // vista previa con spam, atribución, audiencias y el lienzo del recorrido.
  mk: {
    envios: {
      titulo: "Envíos programados",
      ayuda:
        "Cada persona a su hora local y por su canal, sacados de su historial real o de lo que pidió; sin historial suficiente, a la hora y por el canal por defecto, que son ajustes.",
      ninguno: "Todavía no hay nada programado.",
      resumen:
        "{{programados}} programados: {{personalizados}} a su hora, {{general}} a la hora general. {{omitidos}} omitidos.",
      despacharLosQueTocan: "Despachar los que tocan",
      despacharYa: "Despachar ya, sin esperar a su hora",
      despachados: "{{enviados}} enviados y {{fallidos}} fallidos.",
      persona: "Persona",
      cuando: "Cuándo",
      canal: "Canal y clase",
      porque: "Por qué esa hora y ese canal",
      estado: "Estado",
      salida: "Salió por",
      horaLocal: "{{hora}}:00 en {{zona}}",
      plantilla: "Plantilla",
      programar: "Programar el envío",
      programarAyuda:
        "Se programa a cada miembro de la campaña a su mejor hora y por su canal. Quien no se puede alcanzar queda omitido con su motivo.",
      programarBoton: "Programar a la mejor hora",
      programado:
        "{{programados}} programados: {{personalizados}} a su hora, {{general}} a la hora general y {{omitidos}} omitidos.",
      clase: { promocional: "Promocional", transaccional: "Transaccional" },
      como: {
        historial: "Por su historial",
        lo_dijo: "Lo pidió",
        por_defecto: "Por defecto",
        inmediato: "Inmediato",
      },
      estados: {
        programado: "Programado",
        enviado: "Enviado",
        fallido: "Fallido",
        omitido: "Omitido",
      },
    },
    salida: {
      titulo: "Por dónde sale cada clase",
      ayuda:
        "Lo promocional y lo transaccional comparten reputación si salen por el mismo sitio: una campaña con quejas hundiría la entrega de las facturas.",
      dominio: "Dominio",
      remitente: "Remitente",
      flujo: "Servidor",
      separados: "Cada clase sale por su dominio y su servidor.",
      origen: {
        propio: "propio de la clase",
        tenant: "el del canal de correo de la empresa",
        despliegue: "el del despliegue",
      },
    },
    vista: {
      titulo: "Vista previa con datos reales",
      ayuda:
        "Elige un contacto: el correo se monta con sus datos y los de su cuenta, y con las recomendaciones de su historial. Se pinta en cada cliente de correo configurado y se puntúa el spam regla a regla.",
      buscarContacto: "Buscar un contacto",
      contacto: "Contacto",
      sinContacto: "Sin contacto (campos vacíos)",
      sePuedeMandar: "A {{email}} se le puede mandar esta plantilla.",
      noSePuedeMandar: "A {{email}} NO se le puede mandar: {{motivos}}",
      asunto: "Asunto",
      sinDato: "Campos sin dato que saldrían vacíos: {{campos}}.",
      faltan: "Bloques que no existen: {{bloques}}.",
      clientes: "Clientes de correo",
      spam: "Puntuación de spam",
      puntos: "{{puntos}} puntos de {{umbral}} que llevan a basura",
      regla: "Qué ha visto",
      suma: "Suma",
      sinReglas: "Ninguna regla suma: no hay nada que corregir.",
      recomendaciones: "Recomendaciones",
      saleDe: "Sale por",
      veredicto: { bien: "Bien", dudoso: "Dudoso", basura: "A basura" },
      grupos: {
        estructura: "Estructura",
        texto_imagen: "Texto e imagen",
        enlaces: "Enlaces",
        cabeceras: "Cabeceras",
        autenticacion: "Autenticación",
      },
    },
    puntuacionFicha: {
      titulo: "Puntuación de marketing",
      puntuar: "Puntuar ahora",
      puntuando: "Puntuando…",
      porQue: "Por qué esta puntuación",
      sinNota: "Todavía no está puntuado con el modelo de marketing.",
      interes: "Interés",
      encaje: "Encaje",
      grado: "Grado",
      calificacion: { ninguno: "sin calificar", mql: "MQL", sql: "SQL" },
      pie: "Modelo {{modelo}} · calculado el {{fecha}} · {{perdidos}} puntos de interés perdidos por inactividad",
    },
    atribucion: {
      titulo: "Atribución de la venta",
      ayuda:
        "A qué campañas se atribuye la venta de este lead. Los modelos dan respuestas distintas sobre los mismos toques; el basado en datos mide cuánto cae la conversión si se quita cada campaña, sobre los caminos reales.",
      modelo: "Modelo",
      importe: "Importe",
      deSuOportunidad: "El de su oportunidad.",
      tecleado: "Tecleado: el lead no tiene oportunidad.",
      toques: "{{cuantos}} toques en la ventana.",
      sobreCaminos:
        "Calculado sobre {{caminos}} caminos, {{convertidos}} con conversión.",
      campana: "Campaña",
      peso: "Peso",
      modelos: {
        data_driven: "Basado en datos (Markov)",
        primer_toque: "Primer toque",
        ultimo_toque: "Último toque",
        lineal: "Lineal",
        en_u: "En U",
        en_w: "En W",
        decaimiento: "Por decaimiento",
      },
    },
    audiencia: {
      nueva: "Nueva audiencia publicitaria",
      intro:
        "Una audiencia que vive en una plataforma de anuncios, sincronizada con un segmento: sólo sube quien consintió esa finalidad, lo que sale va troceado y una baja aquí es una baja allí en la siguiente vuelta.",
      nombre: "Nombre",
      segmento: "Segmento",
      plataforma: "Plataforma (conexión)",
      plataformaAyuda:
        "Una conexión de Integraciones con tres operaciones declaradas: crear la audiencia, añadir miembros y quitar miembros.",
      finalidad: "Finalidad",
      crear: "Dar de alta",
      sincronizar: "Sincronizar",
      sincronizando: "Sincronizando…",
      estado: "Estado",
      miembros: "{{cuantos}} personas dentro",
      idExterno: "Identificador en la plataforma",
      ultima: "Última vuelta",
      reglas:
        "Por debajo de {{minimo}} personas no se sube nadie, y sólo va quien consintió «{{finalidad}}».",
      historial: "Historial de sincronizaciones",
      sinHistorial: "Todavía no se ha sincronizado.",
      cuando: "Cuándo",
      altas: "Altas",
      bajas: "Bajas",
      enSegmento: "En el segmento",
      sinConsentimiento: "Sin consentimiento",
      suprimidos: "Suprimidos",
      resultado: "Resultado",
      ok: "Bien",
      fallo: "Falló",
      estados: {
        borrador: "Sin sincronizar",
        sincronizada: "Sincronizada",
        pequena: "Demasiado pequeña",
        error: "Con error",
        pausada: "Retirada",
      },
    },
    recorrido: {
      nuevo: "Nuevo recorrido",
      intro:
        "El lienzo genera los nodos del recorrido; la prueba A/B aplica sola su ganadora cuando hay muestra y significación; y cada envío sale a la hora y por el canal de cada persona.",
      clave: "Clave",
      nombre: "Nombre",
      porCuenta:
        "Por cuenta: una sola persona de cada empresa a la vez dentro del recorrido",
      crear: "Crear y abrir el lienzo",
      entrada: "Cómo entra la gente",
      entradas: {
        manual: "A mano o por la API",
        api: "Por la API",
        segmento: "Todos los de un segmento, y los que vayan entrando",
        evento: "Cuando ocurre un evento",
      },
      segmento: "Segmento",
      evento: "Evento",
      elegir: "Elige…",
      saleSiCompra: "Sale en cuanto compra",
      noConvive:
        "Cede el paso a estos recorridos: quien esté en ellos no entra aquí, y quien entre en ellos sale de aquí.",
      entraPor: "Entra: {{como}}",
      embudo: "Por dónde pasa la gente",
      sinEmbudo: "Todavía no ha pasado nadie por ningún nodo.",
      caida: "cae {{pct}} %",
      dentroAhora: "{{cuantos}} dentro ahora",
      conversion: "{{pct}} % convierte",
      salieron: "{{cuantos}} salieron por {{motivo}}",
      motivosSalida: {
        conversion: "conversión",
        exclusion: "exclusión",
        otro_recorrido: "otro recorrido prioritario",
        fin: "llegar al final",
        manual: "salida manual",
        suprimido: "supresión",
        caducado: "caducar",
      },
      noConviveCon: "cede el paso a {{claves}}",
      guardar: "Guardar el lienzo",
      guardado: "Lienzo guardado. Si estaba publicado, vuelve a borrador.",
      publicar: "Publicar",
      publicado: "Publicado: versión {{version}}.",
      version: "Versión {{version}}",
      dentro: "{{cuantos}} personas dentro",
      lienzo: "Lienzo",
      lienzoAyuda:
        "Añade nodos por tipo, elige sus salidas a la derecha y colócalos con las flechas. Lo que se guarda son los nodos con su posición.",
      anadir: "Añadir",
      mover: "Mover",
      nodo: "Nodo",
      inicio: "Nodo de inicio",
      eligeNodo: "Elige un nodo en el lienzo.",
      plantilla: "Plantilla",
      sinPlantilla: "Sin plantilla (sólo avisa)",
      momento: "Cuándo sale",
      mejorHora: "A la mejor hora de cada persona",
      inmediato: "En cuanto se despache",
      siguiente: "Después va a",
      ninguno: "(fin del camino)",
      dias: "Días de espera",
      comportamiento: "Comportamiento",
      esperaDias: "Días que espera a que ocurra",
      siSi: "Si ocurre, va a",
      siNo: "Si no ocurre, va a",
      variante: "Variante",
      peso: "Peso",
      otraVariante: "Añadir otra variante",
      autoGanador:
        "Aplicar sola la ganadora cuando haya muestra y significación",
      quitar: "Quitar este nodo",
      prueba: "Prueba A/B · {{nodo}}",
      ganadora: "Gana «{{clave}}».",
      ganadoraCorta: "gana {{clave}}",
      yendoA: "Ganadora aplicada: el tráfico nuevo va a «{{clave}}».",
      sinGanadora: "Sin ganadora: se sigue repartiendo por pesos.",
      criterio:
        "Se exige un mínimo de {{minimo}} personas por variante y p < {{alfa}} (ahora p = {{p}}).",
      sinDatosPrueba: "Todavía no ha pasado nadie por esta prueba.",
      personas: "Personas",
      conversiones: "Conversiones",
      tasa: "Tasa",
      inscribir: "Meter a alguien",
      inscribirAyuda:
        "Entra si el recorrido está publicado, no estuvo antes, no está en uno excluyente y se le puede escribir.",
      inscribirPorCuenta:
        "Recorrido por cuenta: si ya hay alguien de su empresa dentro, no entra.",
      meter: "Meter en el recorrido",
      avanzar: "Avanzar los recorridos",
      entro: "Ha entrado.",
      noEntro: "No ha entrado: {{motivo}}.",
      avanzados: "{{movidos}} pasos dados y {{omitidos}} omitidos.",
      inscritos: "Quién está dentro",
      nadie: "Todavía no ha entrado nadie.",
      cuenta: "Cuenta",
      entroEl: "Entró",
      tipos: {
        accion: "Acción",
        espera: "Espera",
        decision: "Decisión",
        prueba: "Prueba A/B",
        salida: "Salida",
        fin: "Fin",
      },
      comportamientos: {
        abrio: "Abrió",
        clico: "Hizo clic",
        visito: "Visitó",
        compro: "Compró",
        respondio: "Respondió",
        no_respondio: "No respondió",
      },
      estados: {
        borrador: "Borrador",
        publicado: "Publicado",
        pausado: "Pausado",
        archivado: "Archivado",
      },
      estadosInscrito: {
        activo: "Activo",
        esperando: "Esperando",
        salido: "Salió",
        terminado: "Terminó",
      },
      motivos: {
        cuenta_ya_dentro: "ya hay alguien de su cuenta dentro",
        ya_estuvo: "ya estuvo en este recorrido",
        ya_dentro: "ya está dentro",
        en_recorrido_excluyente: "está en un recorrido que excluye a este",
        sin_direccion: "no tiene dirección a la que escribir",
        suprimido: "está suprimido",
      },
    },
  },
  // Paneles de ficha que abren colecciones que no tenían pantalla
  // (TOPE_SIN_PUERTA, 10-11-2026).
  repartoLead: {
    titulo: "Por qué cayó aquí y cómo llegó",
    abrir: "Ver",
    cerrar: "Cerrar",
    porQue: "El reparto",
    sinReparto:
      "Este lead no ha pasado por las reglas de reparto: se asignó a mano o entró antes de que hubiera reglas.",
    asignadoA: "Asignado a {{quien}}",
    aLaCola: "A la cola «{{cola}}»",
    resultado: {
      gana: "gana",
      no_encaja: "no encaja",
      sin_candidatos_disponibles: "sin nadie disponible",
    },
    comoLlego: "Sus toques, en orden",
    primero: "Primer toque",
    ultimo: "Último toque",
    sinToques:
      "No hay toques registrados: llegó sin rastro de campaña, o antes de que se guardaran.",
  },
  correoContacto: {
    titulo: "Lo que quiere recibir",
    preferencias: "Centro de preferencias",
    sinEmail:
      "Este contacto no tiene correo, así que no tiene centro de preferencias.",
    sinCategorias: "No hay categorías de preferencia declaradas en marketing.",
    obligatoria: "obligatoria",
    elegida: "elegido por la persona",
    porDefecto: "valor por defecto, no lo ha tocado",
    mejorHora: "A qué hora abre",
    abreA:
      "Suele abrir a las {{hora}}:00 ({{zona}}), sobre {{muestras}} aperturas.",
    sinHora:
      "Con {{muestras}} aperturas no se puede hablar de un hábito: no se recomienda ninguna hora.",
  },
  quienManda: {
    titulo: "Quién manda hoy sobre «{{objeto}}»",
    manda: "Manda {{dueno}}.",
    duenos: {
      heredado: "el sistema heredado",
      nuevo: "este CRM",
      ambos: "cualquiera de los dos sistemas",
    },
    seEscribeAqui: "se escribe aquí",
    noSeEscribeAqui: "aquí no se escribe",
    sinRegistro:
      "Resuelto con todas las reglas activas de este objeto y sin un registro concreto: con los datos de un registro real puede ganar otra regla con condiciones.",
  },
  herramientasMcp: {
    titulo: "Lo que ve un agente en esta exposición",
    ayuda:
      "El catálogo que recibe el agente por MCP, filtrado por los permisos de quien mira. Dos personas pueden ver catálogos distintos de la misma exposición.",
    detenida: "La exposición está detenida.",
    ninguna: "No hay ninguna herramienta publicada y activa.",
    confirmacion: "pide confirmación",
    ocultas: "{{n}} herramienta(s) no se ven con tus permisos.",
  },
  carpetaRegistro: {
    ver: "Ver la carpeta de este registro en el gestor",
    titulo: "La carpeta de este registro",
    sinCarpeta:
      "Todavía no tiene carpeta en el gestor: se crea al enlazar el primer documento. Mirar no la crea.",
    camino: "Carpeta abierta",
    buscarAqui: "Buscar sólo dentro de esta carpeta",
    buscar: "Buscar",
    sinResultados:
      "Nada dentro de esta carpeta. Lo que no puedes ver tampoco sale: es el permiso, no un fallo.",
    si: "sí",
    no: "no",
    acciones: {
      read: "Leer",
      write: "Escribir",
      delete: "Borrar",
      manage: "Gestionar",
    },
    motivos: {
      area: "por el área",
      no_area: "no tienes acceso al área",
      grant_here: "permiso dado en esta carpeta",
      grant_above: "permiso heredado de una carpeta de arriba",
      doc_allow: "permitido en el documento",
      doc_deny: "denegado en el documento",
    },
  },
  sePuedePublicar: {
    titulo: "¿Se puede publicar ya? (versión {{version}})",
    si: "Sí: todos los pasos están aprobados.",
    no: "Todavía no.",
    pendientes: "Faltan por decidir: {{pasos}}.",
    sinMirar:
      "Aprobados sin haber visto los cambios: {{pasos}}. Es una firma sobre algo que ya no es lo que se firmó.",
  },
  // Generar un documento desde la ficha (CRM-06.01.01.06).
  generarDocumento: {
    titulo: "Generar documento",
    porque:
      "Elige la plantilla y se rellena con los datos de este registro, su cuenta, su contacto y sus líneas. Revisa, completa lo que falte y sale un PDF que queda como adjunto del registro.",
    sinPlantillas: "No hay plantillas para este tipo de registro",
    sinPlantillasDetalle:
      "Se crean en Administrar › Entornos y despliegue › Operación, pestaña «Plantillas de documento».",
    plantilla: "Plantilla",
    elegir: "Elige una plantilla…",
    opcion: "{{nombre}} · {{idioma}} · v{{version}}",
    rellenar: "Rellenar con este registro",
    conQueSale:
      "Sale con la marca {{marca}}, en «{{idioma}}» y con {{lineas}} líneas.",
    marcaDelTenant: "de la empresa",
    faltan: "Faltan {{cuantos}}: {{cuales}}. Escríbelos antes de generar.",
    completo: "Están todos los datos.",
    falta: "Falta",
    aMano: "A mano",
    delRegistro: "de {{campo}}",
    generar: "Generar el PDF",
    generando: "Generando…",
    guardado: "Guardado como adjunto del registro:",
    archivado: "Archivado también en el corpus documental.",
    sinArchivar:
      "No se ha archivado en el corpus documental: {{motivo}}. El PDF está guardado igual.",
  },
  // Movidos desde es.ts el 10-11-2026: sólo los usan pantallas diferidas, y
  // en el diccionario de apertura pesaban en la primera descarga.
  explotacion: {
    // Publicar para el equipo y convertir en informe (10-11-2026).
    publicar: "Publicar para el equipo",
    retirar: "Dejar de publicar",
    publicando: "Guardando…",
    convertir: "Convertir en informe",
    convertirPorque:
      "Un informe no se rehace con cada pregunta: se congela con lo que digas aquí y se puede programar y mandar.",
    objeto: "Sobre qué",
    agruparPor: "Agrupar por",
    sinAgrupar: "Sin agrupar",
    periodo: "Por periodo",
    sinPeriodo: "Sin periodo",
    agregado: "Qué calcular",
    campo: "De qué campo",
    crearInforme: "Crear el informe",
    informeCreado: "Informe creado: «{{clave}}».",
    sinCampos:
      "La fuente todavía no está registrada: regístrala para saber qué objetos y campos se pueden usar.",
    agregados: {
      suma: "Suma",
      media: "Media",
      minimo: "Mínimo",
      maximo: "Máximo",
      cuenta: "Cuántos hay",
      cuenta_distinta: "Cuántos distintos",
    },
    dondeSeConstruyen: "¿Y dónde se hacen los informes y los cuadros?",
    dondeSeConstruyenPorque:
      "Preguntar se hace aquí. Construir informes, cuadros de mando y sus envíos se hace en contecintelligence, que es el producto que los tiene: se abre con tu identidad, así que ves lo mismo que verías aquí y nada más.",
    abrirConstructor: "Abrir el constructor",

    // La caja de preguntar y el alta de la fuente.
    placeholder:
      "Pregunta sobre tus datos: «¿cuántas oportunidades hay por etapa?»",
    preguntar: "Preguntar",
    ejemplos: "Prueba con una de estas:",
    recientes: "Lo último que se ha preguntado aquí:",
    pensando: "Pensando…",
    sinRespuesta: "No se ha podido responder a eso.",
    comoSeCalculo: "Cómo se ha calculado",
    registrar: "Registrar el CRM como fuente consultable",
    registrando: "Registrando…",
    registrarDetalle:
      "Da de alta los objetos del CRM en contecintelligence con una credencial de solo lectura. No hay nada que rellenar.",
    registroFallido: "No se ha podido registrar la fuente.",
    registroTarda:
      "El registro está tardando más de lo normal. Sigue en marcha: vuelve a esta pantalla en un minuto.",
    titulo: "Explotación",
    entradilla:
      "Preguntar sobre los datos del CRM sin salir de aquí. Las respuestas las " +
      "resuelve contecintelligence con tus permisos: nunca verás más de lo que " +
      "ves en las fichas.",
    noDisponible: "Ahora mismo no se puede preguntar",
    sigueFuncionando: "Esto sigue funcionando con normalidad",
    publicadas: "Preguntas publicadas",
    mias: "Mis preguntas sin publicar",
    sinPublicadas: "Todavía no hay preguntas publicadas",
    sinPublicadasDetalle:
      "Cuando una pregunta funcione bien, publícala para que la use todo el equipo.",
    sinMias: "No tienes preguntas guardadas",
    sinMiasDetalle: "Guarda una pregunta para no volver a escribirla.",
    guardar: "Guardar la pregunta",
    guardada: "Guardada en «Mis preguntas sin publicar»",
    noGuardada: "No se ha podido guardar la pregunta.",
    esInforme: "Es informe",
    vecesUsada: "Usada {{veces}} veces",
  },
  formulario: {
    // El 409 por duplicado y su salida (CRM-01.01.03.03).
    pareceDuplicado: "Ya existe algo que parece lo mismo.",
    coincide: "coincide en {{senales}} · {{parecido}} %",
    concluyente: "Casi seguro",
    sinMirarContactos:
      "No se ha podido mirar entre los contactos: el maestro de clientes no " +
      "ha contestado. Lo de arriba son sólo los leads.",
    esOtroCrearIgual: "Es otro, crearlo igual",
    separadoPorComas: "Separado por comas",
    suma: "Suma",
    quitarLinea: "Quitar la línea",
    // Estaba escrito en el código, en castellano y sin pasar por aquí: una
    // frase suelta que ninguna traducción alcanzaba.
    sinLineas: "Todavía no hay ninguna línea.",
    elegirRegistro: "Elegir en {{recurso}}…",
    buscarEnLista: "Buscar por nombre",
    elegirVarios: "Elegir uno o varios…",
    registroFueraDeLista: "Elegido (no está entre los primeros 200)",
    quitarEleccion: "Quitar lo elegido en {{campo}}",
    sinCoincidencias: "Nada coincide",
    cambiar: "Cambiar",
    identificadorAMano: "Pega aquí el identificador",
    sinContrato:
      "El contrato de esta operación no declara cuerpo, o no se ha podido leer.",
    masCampos: "Más campos ({{total}})",
    anadirValor: "Escribe y pulsa Intro",
    anadirA: "Añadir a {{campo}}",
    quitarValor: "Quitar «{{valor}}»",
    clave: "clave",
    valor: "valor",
    claveDe: "Clave de {{campo}}",
    valorDe: "Valor de {{campo}}",
    editarComoJson: "Editar como JSON",
    volverAPares: "Volver a clave y valor",
  },
  tabla: {
    columnas: "Columnas ({{visibles}} de {{total}})",
    // Las casillas para elegir filas y hacer algo con todas (CRM-00.02.01.11).
    elegirTodas: "Elegir todas las que se ven",
    elegirFila: "Elegir «{{nombre}}»",
    elegirColumnas: "Qué columnas se ven",
    masColumnas_one: "Hay 1 columna más, sin ningún dato en estas filas.",
    masColumnas_other:
      "Hay {{count}} columnas más, sin ningún dato en estas filas.",
    // El rótulo para quien no ve la flecha: dice qué hará el clic, y cuando ya
    // está ordenada, cómo está. «Ordenar por Importe» y «Importe, de menor a
    // mayor» contestan dos preguntas distintas.
    // La línea que Lightning pone bajo el nombre de la vista. «Elementos» y
    // no «filas»: una fila es de la tabla y un elemento es del listado, que es
    // lo que la persona está contando.
    // El menú del final de cada fila, y el lápiz de una celda.
    accionesDeFila: "Qué hacer con esta fila",
    editarCampo: "Cambiar {{campo}}",
    noSeGuardo: "No se guardó",
    buscarEnLaLista: "Buscar en esta lista",
    nadaConEso: "Ninguno de los {{total}} cargados lleva «{{que}}».",
    // Cuando hay búsqueda se dice de CUÁNTOS, porque busca en lo cargado:
    // «12 elementos» a secas haría creer que no hay más.
    cuantosDeCuantos: "{{cuantos}} de {{total}} cargados",
    // Buscado en el servidor: entre TODOS, no entre los cargados.
    cuantosConEso_one: "1 elemento con «{{que}}»",
    cuantosConEso_other: "{{count}} elementos con «{{que}}»",
    nadaConEsoEnTodos: "Ningún elemento lleva «{{que}}».",
    cuantosElementos_one: "1 elemento",
    cuantosElementos_other: "{{count}} elementos",
    ordenadoAsc: "Ordenado por {{columna}}, de menor a mayor",
    ordenadoDesc: "Ordenado por {{columna}}, de mayor a menor",
    ordenarPor: "Ordenar por {{columna}}",
    ordenAsc: "{{columna}}, de menor a mayor. Pulsa para invertir.",
    ordenDesc: "{{columna}}, de mayor a menor. Pulsa para quitar el orden.",
  },
  // Las credenciales de una conexión (CRM-00.01.04.08). Del secreto se dice
  // cuándo y quién, nunca el valor.
  credenciales: {
    titulo: "Credenciales de la conexión",
    tipo: "Autenticación: {{tipo}}.",
    sinCampos: "Este tipo no lleva credencial.",
    fijar: "Fijar credenciales",
    rotar: "Rotar credenciales",
    probar: "Probar la conexión",
    guardar: "Guardar cifradas",
    cancelar: "Cancelar",
    ninguna:
      "Todavía no se ha fijado ninguna credencial: la conexión no podrá llamar a nadie.",
    actual: "Versión {{version}}, fijada el {{cuando}} por {{quien}}.",
    nadie: "alguien que no consta",
    caduca: "Caduca el {{cuando}}.",
    sinCaducidad: "Sin caducidad declarada: nadie avisará de rotarla.",
    claves: "Lleva: {{claves}}. Los valores no se enseñan nunca.",
    ultimaPrueba: "Última prueba, {{cuando}}: {{detalle}}",
    pruebaBien: "La conexión responde: {{detalle}}",
    pruebaMal: "La conexión falla: {{detalle}}",
    fijada: "Credencial guardada, cifrada.",
    rotada:
      "Credencial rotada: la versión {{version}} sustituye a la anterior, que queda desactivada.",
    anteriores: "Versiones anteriores ({{n}})",
    anterior:
      "Versión {{version}}: fijada el {{cuando}} por {{quien}}, rotada el {{rotada}}.",
    caducaCampo: "Caduca el (opcional)",
    ayudaRotar:
      "Al guardar se crea una versión nueva y la anterior se desactiva. Lo que " +
      "escribas aquí no se vuelve a enseñar.",
    campos: {
      api_key: "Clave de API",
      usuario: "Usuario",
      contrasena: "Contraseña",
      token: "Token",
      client_id: "Identificador de cliente (client_id)",
      client_secret: "Secreto de cliente (client_secret)",
    },
  },
  // El archivo de histórico (CRM-07.03.01.02). Aquí y no en las pantallas
  // diferidas porque lo pinta también la ficha, que va de una pieza.
  archivo: {
    titulo: "Archivo de histórico",
    ayuda:
      "Lo viejo se archiva, no se borra: sale de la tabla viva, conserva su identificador y se sigue consultando. Cada clase se archiva a partir de sus días; vacío, los generales.",
    sinArchivo:
      "«{{servicio}}» no tiene archivo de histórico: no guarda nada que crezca lo bastante como para archivarlo.",
    clase: "Clase de dato",
    dias: "Archivar a partir de (días)",
    diasDe: "Días a partir de los cuales se archiva {{clase}}",
    guardarCriterio: "Guardar el criterio",
    criterioGuardado: "Criterio de {{clase}} guardado.",
    corte: "Corte",
    candidatas: "Hoy movería",
    yaArchivado: "Ya archivado",
    deA: "del {{desde}} al {{hasta}}",
    simular: "Simular",
    archivar: "Archivar",
    simulado:
      "Simulación: se archivarían {{n}} filas anteriores al {{corte}}. No se ha movido nada.",
    archivadas:
      "Archivadas {{n}} filas. {{bloqueo}} tenían bloqueo legal: no impide archivar, sólo destruir.",
    consultar: "Consultar lo archivado",
    buscarAyuda: "Identificador de un registro (vacío: lo último archivado)",
    nada: "No hay nada archivado con ese criterio.",
    hayMas: "Hay más: se enseñan las 50 más recientes.",
    deCuando: "del {{original}} · archivada el {{archivada}}",
    contenido: "Contenido archivado",
    devolver: "Devolver a la tabla viva",
    devuelto: "Devuelto a la tabla viva.",
    delRegistro: "Archivado de este registro",
  },
  // Notas, ficheros y conversaciones de la suite vinculados por referencia
  // (CRM-06.01.03.08, .09, .12). En la ficha, que va de una pieza.
  referenciasSuite: {
    titulo: "De la suite",
    ayuda:
      "Notas, ficheros y conversaciones que siguen en su sitio: aquí sólo se guarda el enlace, y al abrirlo se pregunta al origen si existe y si puedes verlo.",
    vincular: "Vincular",
    cancelar: "Cancelar",
    guardar: "Guardar el vínculo",
    tipo: "Qué es",
    tipos: {
      nota: "Nota",
      fichero: "Fichero",
      conversacion: "Conversación",
    },
    referencia: "Enlace o identificador en el origen",
    nombre: "Nombre",
    perfil: "Perfil de suite que sabe abrirla",
    sinPerfil: "Ninguno (no se podrá comprobar)",
    resumen: "Resumen escrito por ti (sólo conversaciones)",
    exportable: "El canal deja exportar el hilo",
    abrir: "Abrir",
    quitar: "Quitar el vínculo",
    vacio: "Nada vinculado todavía.",
    estados: {
      disponible: "Disponible: puedes verlo en el origen.",
      sin_acceso: "Existe, pero no tienes acceso en el origen.",
      no_existe: "Ya no está en el origen.",
      desaparecido: "Ya no está en el origen.",
      no_comprobable: "No se puede comprobar en el origen.",
      error: "El origen no ha contestado.",
    },
    irAlOrigen: "Ir al origen",
  },
  exportar: {
    boton: "Exportar",
    bajando: "Preparando…",
    deQue: "Exportar {{nombre}} a una hoja de cálculo",
    listo: "Fichero descargado",
    cortado:
      "Fichero descargado, pero CORTADO en {{cuantas}} filas: la lista es más " +
      "larga. Acota con un filtro antes de mandarlo a nadie.",
    noSePudo: "No se ha podido exportar",
    vuelveAVerificarte:
      "Exportar en masa pide confirmar que eres tú, y lo has cancelado. Vuelve " +
      "a pulsar Exportar y confírmalo: vale para los próximos {{minutos}} minutos.",
    sinSegundoFactor:
      "Exportar en masa exige un segundo factor y tu cuenta no tiene ninguno " +
      "configurado. Actívalo en tu puesto (Puesto › Seguridad) y vuelve.",
  },
  // Llamar desde la ficha y anotar al colgar (CRM-03.03.01.05).
  marcador: {
    titulo: "Llamar",
    numero: "Número",
    consiente: "La persona consiente que se grabe",
    llamar: "Llamar",
    enCurso:
      "Llamando a {{numero}}. Al colgar, la llamada se registra sola como actividad; anota aquí cómo fue.",
    noSalio: "La centralita no ha podido marcar: {{error}}",
    seGraba: "Se graba: avisa al empezar.",
    noSeGraba: "No se graba.",
    resultado: "Cómo fue",
    proxima: "Volver a llamar el",
    nota: "Qué se habló",
    anotar: "Anotar y cerrar",
    anotada: "Anotada.",
    resultados: {
      hablado: "Hablado",
      buzon: "Buzón de voz",
      no_contesta: "No contesta",
      numero_erroneo: "Número erróneo",
      persona_equivocada: "Persona equivocada",
      pide_que_no_le_llamen: "Pide que no le llamen",
      reprogramar: "Reprogramar",
    },
  },
  reunionEnLinea: {
    titulo: "Reunión en línea",
    crear: "Crear reunión en línea",
    confirmar: "Crear la sala",
    cancelar: "Cancelar",
    entrar: "Entrar en la reunión",
    creadaCon: "Creada con {{perfil}} el {{cuando}}.",
    credencial:
      "Quien tenga este enlace entra: compártelo en la cita, no en un aviso ni en una página pública.",
    noDisponible: "No se puede crear: {{motivo}}",
    conQue: "Se creará con {{perfil}}.",
    asunto: "Asunto",
    inicio: "Empieza",
    fin: "Termina",
    asistentes: "Asistentes (correos)",
    ejemploAsistentes: "ana@cliente.com, luis@cliente.com",
    organizador: "Cuenta que organiza (si la suite la pide)",
    ayuda:
      "La sala se crea ahora en la suite y el enlace queda guardado en la actividad.",
  },
  // ── Las vistas de lista ──────────────────────────────────────────────
  // El recorte con nombre de un listado. Sin ninguna guardada, el listado se
  // llama «Todo», que es exactamente lo que había antes: la lista completa,
  // sin tener que elegir nada.
  vistas: {
    todo: "Todo",
    queObjeto: "Qué se está mirando",
    queVista: "Qué vista",
    deTodos: "de todos",
    guardarComo: "Guardar esta vista…",
    borrarEsta: "Borrar «{{nombre}}»",
    comoSeLlama: "¿Cómo se llama esta vista?",
    // Se pregunta al guardar, no después: una vista guardada «para mí» que
    // luego resulta que la ve todo el mundo es la clase de sorpresa que hace
    // desconfiar de la función entera.
    paraTodos: "Que la vea todo el equipo",
    guardada: "Vista guardada.",
    noSeGuardo: "No se ha podido guardar la vista: {{motivo}}",
    confirmarBorrado: "¿Borrar la vista «{{nombre}}»? No se deshace.",
    // La compartida avisa aparte: borrarla deja sin su listado a quien la use.
    confirmarBorradoCompartida:
      "«{{nombre}}» la ve todo el equipo. Si la borras, se queda sin ella. No se deshace.",
  },
  consola: {
    eligeArea: "Elige un área de la lista",
    eligeAreaDetalle:
      "Cada área agrupa las operaciones de administración que publica un servicio.",
    titulo: "Administración",
    intro:
      "Todo lo que hay aquí sale del contrato de la API. No existe ninguna acción de esta consola que no sea una llamada publicada.",
    areas: "Áreas",
    operaciones: "Operaciones",
    metodo: "Método",
    ruta: "Ruta",
    permiso: "Permiso",
    quePuede: "Qué hace",
    sinPermiso: "Tu rol no concede este permiso",
    sinListado:
      "Esta área no publica un listado; sus operaciones necesitan un identificador.",
    incompleta_uno:
      "No ha contestado el servicio {{servicios}}, así que falta parte de la administración.",
    incompleta_otros:
      "No han contestado los servicios {{servicios}}, así que falta parte de la administración.",
    total: "{{total}} operaciones, {{administracion}} de administración",
  },
  llamadaEntrante: {
    titulo: "Llamada entrante",
    cerrar: "Cerrar el aviso de llamada",
    ivr: "Lo que ya dijo en el IVR (no se lo vuelvas a preguntar)",
    ultimoCaso: "Último caso: {{asunto}} ({{estado}})",
    ultimaInteraccion: "Lo último: {{asunto}}",
    abrirFicha: "Abrir su ficha",
    transferir: "Transferir",
    a: "A quién (persona, extensión o cola)",
    resumen: "Resumen para quien la recibe",
    pasar: "Transferir con el resumen",
    transferida: "Transferida a {{a}} con el resumen.",
  },
  // La reunión en línea de una actividad o de un registro (CRM-06.01.03.10).
  // Las resoluciones de una devolución y el abono (CRM-04.05.01.02).
  devolucion: {
    resoluciones: "Resoluciones: reparar, sustituir o abonar",
    sinResoluciones:
      "Todavía no hay ninguna. Se resuelve con «Reparar, sustituir o abonar», en las acciones de arriba.",
    col: {
      tipo: "Qué se hace",
      aCargo: "A cargo de",
      importe: "Importe",
      abono: "Estado del abono",
    },
    tipo: {
      reparacion: "Reparar",
      sustitucion: "Sustituir",
      abono: "Abonar",
      sin_accion: "Sin acción",
    },
    anotarAbono: "Anotar lo que contestó quien factura",
    referencia: "Referencia del abono emitido",
    motivoRechazo: "Motivo, si se rechazó",
    confirmarAbono: "Abono emitido",
    rechazarAbono: "Abono rechazado",
    abonoAnotado: "Anotado: el abono queda «{{estado}}».",
  },
  filtros: {
    anadir: "Filtrar",
    campo: "Campo",
    operador: "Condición",
    valor: "Valor",
    elegirCampo: "Elige un campo…",
    aplicar: "Aplicar",
    cancelar: "Cancelar",
    quitar: "Quitar el filtro de {{campo}}",
    quitarTodos: "Quitar todos",
    // Los rótulos dicen lo que hace la condición, no el operador: «desde» se
    // entiende sin saber que por debajo es un `>=`.
    desde: "desde",
    hasta: "hasta",
    desdeNumero: "al menos",
    hastaNumero: "como mucho",
    mayorQue: "más de",
    menorQue: "menos de",
    esIgual: "es",
    distintoDe: "no es",
    esAlgunoDe: "es alguno de",
    sinValor: "sin valor",
    conValor: "con valor",
  },
  // El editor de condiciones de una regla (CRM-00.04.03.05).
  condiciones: {
    escribeElObjetivo:
      "Escribe el objetivo para poder elegir entre sus campos propios.",
    sinCamposPropios:
      "«{{objeto}}» no tiene campos propios declarados: escribe el campo a mano.",
    ninguna: "Sin condiciones: la regla salta siempre que se dispare.",
    campoPropio: "Campo propio de la condición {{numero}}",
    elegirCampoPropio: "Campo propio…",
    atributo: "Campo de la condición {{numero}}",
    atributoEjemplo: "importe o campos.mi_campo",
    operador: "Operador de la condición {{numero}}",
    valor: "Valor de la condición {{numero}}",
    quitar: "Quitar la condición {{numero}}",
    quitarCorto: "Quitar",
    anadir: "Añadir una condición",
  },
  // `/abrir/:tipo/:id`: el enlace que llevan los avisos del chat.
  abrirRegistro: {
    titulo: "Abrir un registro",
    entradilla:
      "El enlace de un aviso lleva aquí y de aquí a la ficha del registro, en el módulo que lo enseña.",
    sinModulo: "No hay ninguna pantalla que enseñe «{{tipo}}».",
  },
  actividadDelRegistro: {
    titulo: "Lo que ha pasado",
    vacio:
      "Todavía no hay nada apuntado. Apunta la llamada, la reunión o la respuesta que diste.",
  },
  convertirLead: {
    titulo: "Convertir en cliente",
    entradilla:
      "Se propone lo que el lead ya dice. Revísalo y pulsa Convertir: se crean el cliente, el contacto y la oportunidad de una vez.",
    cliente: "Cliente",
    crearCliente: "Crear un cliente nuevo",
    yaCreada: "El cliente creado en el intento anterior",
    nombreCliente: "Nombre del cliente nuevo",
    yaExisten: "O usar uno que ya existe:",
    usar: "Usar «{{nombre}}»",
    contacto: "Contacto",
    crearContacto: "Crear el contacto",
    sinPersona: "El lead no tiene nombre de persona.",
    oportunidad: "Oportunidad",
    crearOportunidad: "Crear la oportunidad",
    nombreOportunidad: "Nombre de la oportunidad",
    importe: "Importe",
    cierre: "Fecha de cierre",
    convertir: "Convertir",
  },
  actividad: {
    llamada: "Llamada",
    email: "Correo",
    nota: "Nota",
    reunion: "Reunión",
    asunto: "Qué ha pasado",
    notas: "Detalle",
    guardar: "Apuntar",
    ejemplo: {
      llamada: "Llamada con compras: piden revisar plazos",
      email: "Enviada la oferta revisada",
      nota: "Cambian de responsable de compras en enero",
      reunion: "Visita a planta: revisión del plan de calidad",
    },
  },
  grafica: {
    leyenda: "Leyenda",
    verTabla: "Ver como tabla",
    verDibujo: "Ver como gráfica",
    sinDatos: "No hay datos que dibujar",
    otras: "Otras {{count}}",
  },
  medidor: {
    sinObjetivo: "Sin objetivo fijado: esto es una cifra, no un medidor.",
    cumplido: "Objetivo {{objetivo}} — cumplido",
    faltan: "Objetivo {{objetivo}} — faltan {{falta}}",
  },
  subcoleccion: {
    vacia: "Nada todavía",
    quitar: "Quitar",
    confirmarQuitar: "¿Quitar este elemento? No se deshace desde aquí.",
  },
  // El panel de IA de cada ficha: lo que estaba escondido en «Más».
  asistenteIA: {
    titulo: "Con IA",
    detalle: "Lo que propone es un borrador: no se guarda ni se manda sin ti.",
  },
  descargas: {
    bajado: "Bajado {{fichero}} ({{bytes}} caracteres).",
  },
};

export default pantallas;
