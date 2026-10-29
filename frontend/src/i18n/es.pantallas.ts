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
  duplicados: {
    titulo: "Duplicados por resolver",
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

  conocimiento: {
    titulo: "Conocimiento",
    entradilla:
      "Lo publicado se distingue de lo que está en revisión: un artículo a medias " +
      "que se lee como bueno acaba pegado en una respuesta a un cliente.",
    buscar: "Buscar por título",
    sinResultados: "Ningún artículo coincide",
    enPortal: "En el portal",
    vistas: "{{vistas}} vistas",
  },
  conversacion: {
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
  },
  cuadros: {
    informeNoExiste: "El informe «{{clave}}» ya no existe.",
    descargar: "CSV",
    bajando: "Bajando…",
    bajado: "Descargado: {{filas}} fila(s) en CSV.",
    truncado: "Cortado por el tope de filas: no es el total.",
    camposRetirados: "No ves estos campos: {{campos}}.",
    titulo: "Cuadros de mando",
    elegir: "Elegir cuadro",
    ninguno: "Todavía no hay cuadros de mando",
    ningunoDetalle: "Un cuadro junta varios informes en una pantalla.",
    sinComponentes: "Este cuadro no tiene componentes",
    sinComponentesDetalle: "Añade uno apuntando a un informe.",
    ignoraFiltros: "No le afectan los filtros del cuadro",
  },
  cuenta: {
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
    titulo: "Estado del servicio",
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
  },
  ficha: {
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
  modeloDatos: {
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
      contexto: "Evaluado con roles {{roles}} · unidad {{unidad}} · hora {{hora}}",
    },
    capaPuesta: "(puesta)",
    capaNoPuesta: "(NO está haciendo su trabajo)",
    noSeMideAqui: "no se mide desde aquí",
    excepciones: {
      titulo: "Y éstos, ¿por qué están permitidos?",
      porQue:
        "Los conflictos que alguien aprobó, con el motivo que escribió y hasta cuándo valen. El alta los exige: si no se pueden leer, son papeleo.",
      verCaducadas: "Ver también las caducadas",
      ninguna: "No hay ninguna excepción aprobada",
      ningunaDetalle:
        "Todo conflicto que aparezca arriba lo es de verdad: nadie lo ha autorizado.",
      hasta: "Vale hasta el {{fecha}}",
      caducada: "Caducó el {{fecha}}",
    },
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
      sinReglas: "No hay reglas de incompatibilidad",
      sinReglasDetalle:
        "Sin reglas no hay conflictos que encontrar. Se declaran en segregación de funciones.",
      ninguna: "Nadie tiene hoy permisos incompatibles",
      ningunaDetalle:
        "Con las reglas declaradas hoy, y sobre los permisos efectivos de ahora.",
      conExcepcion: "con excepción vigente",
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
  },
  suite: {
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
};

export default pantallas;
