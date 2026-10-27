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
    titulo: "Entornos y cambios",
    intro: "Qué hay desplegado y qué tocó alguien a mano.",
    entorno: "Entorno",
    verDesvio: "Ver desvío",
    sinPaquete: "No hay ningún paquete desplegado",
    noComparado: "Sin comparar: {{tipos}}. De eso no se dice nada, no se ha mirado.",
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
    sinCapitulo: "Esta pantalla todavía no tiene capítulo asociado en el manual.",
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
    soloLectura: "Puedes leer la conversación; responder necesita permiso de escritura.",
    respuesta: "Respuesta",
    esNotaInterna: "Es una nota interna (no se manda al cliente ni cuenta como primera respuesta)",
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
    sinMetricas: "Ninguna métrica ha llegado todavía desde los demás servicios.",
    sinDatoDe: "Sin dato de: {{metricas}}.",
    deHace: "de hace {{dias}} d",
    caducada: "El dato está caducado: se enseña con su antigüedad en vez de como si acabara de llegar.",
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
  },
  firma: {
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
    sinUsar: "{{cuantos}} campos sin una sola escritura: son los candidatos a retirar.",
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
    sinTratamiento: "{{cuantos}} objetos con datos personales y sin tratamiento declarado",
    ratCompleto: "Todo objeto con datos personales tiene su tratamiento declarado",
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
    sinRespuesta: "No han contestado: {{servicios}}. No cuentan como tranquilos.",
    limites: "Límites del plan",
    recurso: "Recurso",
    usado: "Usado",
    limite: "Límite",
    noConsta: "no consta",
  },
  seguridad: {
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
      ningunaDetalle: "Con las reglas declaradas hoy, y sobre los permisos efectivos de ahora.",
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
  suite: {
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
    sinMedir: "{{cuantas}} sin medir: de ésas no se dice nada, no se han mirado.",
    credenciales: "Credenciales",
    credencialesAlDia: "Ninguna de las {{revisados}} pide nada",
    credencialesSinRevisar:
      "Ninguna credencial que revisar: nadie ha autorizado todavía su correo ni su calendario.",
    suscripciones: "Suscripciones",
    suscripcionesAlDia: "Ninguna pendiente de renovar",
    sinCaducidadDeclarada: "sin caducidad declarada: no es «no caduca», es que no se sabe",
    titulo: "Gobierno de la suite",
    intro: "Las herramientas de la casa, quién entra en cada una y qué falta por aplicar.",
    sinHerramientas: "No hay herramientas conectadas",
    sinHerramientasPorque:
      "Un «todo bien» aquí haría creer que el cliente está en la suite cuando solo está en el CRM.",
    herramienta: "Herramienta",
    estado: "Estado",
    bajas: "Bajas sin aplicar",
    ultimoError: "Último error",
    bajasSinAplicar: "{{cuantas}} bajas sin aplicar: son accesos que siguen abiertos.",
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
