export default {
  app: {
    // ── Las aplicaciones ──────────────────────────────────────────────
    // Se trabaja dentro de una cada vez, y arriba sólo están sus pestañas.
    // Antes el menú ofrecía de golpe 24 módulos, ~35 pantallas y 211
    // pestañas dentro de ellas: para mirar tus oportunidades había que leer
    // cincuenta y nueve rótulos.
    ventas: "Ventas",
    servicio: "Servicio",
    marketing: "Marketing",
    analitica: "Analítica",
    lanzador: "Iniciador de aplicaciones",
    lanzadorAtajo: "Para ir a una pantalla por su nombre: ⌘K",
    todoLoQueHay: "Todo lo que hay",
    cuantasPestanas_one: "1 pantalla",
    cuantasPestanas_other: "{{count}} pantallas",
    masPestanas: "Más pestañas de esta aplicación",
    configuracion: "Configuración",
    irAConfiguracion: "Configuración",
    salirDeConfiguracion: "Volver al trabajo",
    cargando: "Cargando…",
    reintentar: "Reintentar",
    cerrarSesion: "Cerrar sesión",
    suplantado: "Estás viendo esto en nombre de otra persona",
    sinConexionAviso:
      "Sin conexión: ves lo último que se consultó y lo que guardes se enviará al volver la red.",
    sinConexionPendientes_one: "{{n}} cambio pendiente de enviar",
    sinConexionPendientes_other: "{{n}} cambios pendientes de enviar",
    sinConexionConflictos_one: "{{n}} conflicto por resolver",
    sinConexionConflictos_other: "{{n}} conflictos por resolver",
    sinConexionVer: "Ver",
    // «Entrar como» de soporte (CRM-00.01.02.06).
    suplantadoComo: "Estás dentro como {{quien}} por soporte: «{{motivo}}»",
    suplantadoPor: "(entraste tú, {{soporte}})",
    salirDeSuplantacion: "Salir y volver a mi sesión",
    salirDeSuplantacionFallo:
      "No se ha podido salir. Cierra la sesión si tienes prisa: la de soporte caduca sola.",
    tema: "Cambiar tema",
    densidad: "Densidad de la interfaz",
    // Dos textos y no uno: el botón dice A DÓNDE va, no dónde está. «Densidad
    // compacta» con la interfaz ya compacta no se sabe si es el estado o la
    // acción, y es el error más repetido en los interruptores.
    densidadCompacta: "Ver más en pantalla (compacta)",
    densidadComoda: "Ver con más aire (cómoda)",
    saltarAlContenido: "Saltar al contenido",
  },
  altas: {
    cuenta: "Cliente",
    contacto: "Contacto",
    oportunidad: "Oportunidad",
    lead: "Lead",
    actividad: "Actividad o tarea",
    caso: "Caso de soporte",
  },
  nav: {
    telefonia: "Telefonía",
    compensacionExterna: "Compensación externa",
    estados: "Estados de los objetos",
    embudos: "Embudos y etapas",
    metodologias: "Metodologías y playbooks",
    segregacion: "Segregación de funciones",
    slaProveedores: "SLA de proveedores",
    tcsec: "Clasificación TCSEC",
    controlesGrc: "Controles del GRC",
    revisionAccesos: "Revisión de accesos",
    organigrama: "Organigrama",
    historialAjustes: "Historial de la configuración",
    grupoEmpresas: "Grupo de empresas",
    consumoFacturacion: "Consumo para facturación",
    queCliente: "Cliente que estás mirando",
    crear: "Crear",
    crearQue: "Qué quieres dar de alta",
    areaClientes: "Clientes",
    areaVentas: "Ventas",
    areaMarketing: "Marketing",
    areaServicio: "Servicio",
    areaAnalisis: "Analítica",
    // Los cinco temas de Administrar. Eran dos —«Automatización» con 2
    // entradas y «Configuración» con 18— y se llaman como el árbol de Setup
    // de Salesforce, que es lo que ya conoce quien viene de un CRM.
    areaAutomatizacion: "Automatización",
    areaUsuarios: "Usuarios y empresa",
    areaPlataforma: "Herramientas de plataforma",
    areaEntornos: "Entornos y despliegue",
    areaGobierno: "Gobierno y cumplimiento",
    inicio: "Inicio",
    // «Administración», que es como se llama la pantalla. Decía «Consola de
    // administración» y en el iniciador sale al lado de «Consola de agente»,
    // que es para atender clientes: dos «consolas» seguidas no distinguen.
    consola: "Administración",
    estado: "Estado",
    // «Identidad y seguridad», como se llama la pantalla. Decía «Usuarios y
    // seguridad» y justo encima hay «Usuarios y permisos», que es OTRA
    // pantalla —el listado de usuarios y sus licencias—: dos entradas que
    // empiezan igual obligan a entrar en las dos para saber cuál es.
    seguridad: "Identidad y seguridad",
    plataforma: "Plataforma y cumplimiento",
    firma: "Pendiente de firma",
    cobertura: "Cobertura",
    recorrido: "Recorrido guiado",
    // «Editor de procesos», que es lo que es: el lienzo donde se escribe,
    // se valida y se simula un proceso. El rótulo decía lo CONTRARIO —los
    // procesos en curso son las instancias en ejecución, que están en
    // «Procesos y orquestación»—. Medido el 03-11-2026.
    procesos: "Editor de procesos",
    extensiones: "Extensiones y código propio",
    sandboxes: "Entornos de pruebas (sandboxes)",
    aprobacionesDoc: "Aprobar documentos",
    explotacion: "Preguntas publicadas",
    analisisCrm: "Embudo, cohortes y actividad",
    cuadros: "Paneles",
    casos: "Bandeja de casos",
    consolaAgente: "Consola de agente",
    canalesDeEntrada: "Canales de entrada",
    cicloDeVida: "Ciclo de vida del cliente",
    // «Despliegues y desvíos», que es la pregunta que contesta: qué hay
    // desplegado en cada entorno y qué se ha tocado a mano. Se llamaba
    // «Entornos y despliegues» y la de al lado «Entornos y despliegue», en
    // singular: dos entradas que empiezan igual obligan a entrar en las dos.
    entornos: "Despliegues y desvíos",
    sandboxApi: "Probar la API",
    canales: "Canales y consentimiento",
    menciones: "Mis menciones",
    loQueSigo: "Lo que sigo",
    vistoHacePoco: "Visto hace poco",
    // «Prospección» ya era el módulo de leads: dos entradas con el mismo
    // nombre en el mismo grupo obligan a entrar en las dos para saber cuál es
    // cuál. Ésta dice lo que contesta.
    prospeccion: "Plantillas y reuniones",
    cumplimiento: "Panel de cumplimiento",
    conocimiento: "Buscar en conocimiento",
    marketing: "Resumen de marketing",
    proveedores: "Proveedores",
    chat: "Chat",
    embudo: "Embudo de ventas",
    coste: "Coste",
    territorios: "Territorios",
    inteligencia: "Inteligencia",
    modelosPredictivos: "Modelos predictivos",
    evaluacionIa: "Evaluación de la IA",
    asistente: "Asistente IA",
    nexus: "Nexus",
    duplicados: "Duplicados",
    calidadDelDato: "Calidad del dato",
    sinConexion: "Sin conexión",
    importar: "Importar datos",
    transferirPropiedad: "Traspasar cartera",
    // «Calendario», como lo llama Salesforce. Al lado de «Actividades», que
    // es la misma materia en lista.
    calendario: "Calendario",
    archivos: "Archivos",
    puesto: "Puesto",
    // «Entornos y cambios», como se llama la pantalla. Decía «Entornos y
    // despliegue» y hay otra entrada «Entornos y despliegues»: en plural y
    // en singular, una al lado de la otra. Ésta va de llevarse configuración
    // de un entorno a otro; la otra, de qué hay desplegado en cada uno.
    // «Promoción entre entornos», que es lo que se hace aquí: llevarse una
    // configuración de desarrollo a pruebas, de pruebas a producción. Decía
    // «Entornos y despliegue», que es la pregunta de la entrada de al lado.
    alm: "Promoción entre entornos",
    rendimiento: "Rendimiento",
    // «Aplicaciones conectadas», que es como lo llama Salesforce y lo que
    // contesta: qué herramientas de la casa están enganchadas a este cliente,
    // quién entra en cada una y qué falta por aplicar. Decía «Suite» a secas,
    // que no contesta nada. Y no «Gobierno de la suite», que es el título de
    // la pantalla: al lado está «Gobierno de la IA» y las dos empezarían por
    // la misma palabra —lo cazó el guardián de los rótulos parecidos—.
    suite: "Aplicaciones conectadas",
    ayuda: "Ayuda",
    accesos: "Accesos",
    // El buscador del árbol de configuración. Dice que BUSCA UN AJUSTE y no
    // «buscar» a secas: arriba hay otro buscador que lleva a cualquier
    // pantalla, y dos cajas que dicen lo mismo y hacen cosas distintas se
    // prueban a ver cuál era.
    buscarAjuste: "Buscar un ajuste…",
    sinAjustes: "Ningún ajuste se llama «{{que}}».",
    // «Trabajar» y «Administrar», en infinitivo: nombran lo que se va a hacer,
    // no un sitio. «Operación» y «Configuración» nombrarían el sitio, y hay
    // que traducirlos mentalmente a lo que uno viene a hacer.
    ambitos: "A qué vienes",
    ambitoTrabajar: "Trabajar",
    ambitoAdministrar: "Administrar",
    grupoModulos: "Módulos",
    grupoTrabajo: "Trabajo",
    grupoAnalisis: "Análisis",
    grupoPlataforma: "Plataforma",
    grupoPantallas: "Pantallas",
    alternarPanel: "Mostrar u ocultar el menú",
    cerrarPanel: "Cerrar el menú",
    plegarPanel: "Plegar el menú",
    desplegarPanel: "Desplegar el menú",
    migas: "Dónde estás",
    abrirPaleta: "Buscar pantallas y módulos",
    cerrarPaleta: "Cerrar el buscador",
    buscarPlaceholder: "Buscar una pantalla o un módulo…",
    resultados: "Resultados",
    sinResultados: "Nada coincide con «{{consulta}}»",
    menuUsuario: "Tu cuenta",
    sesionDe: "Sesión iniciada como",
  },
  pipeline: {
    // «Embudo de ventas», como la entrada que lleva aquí. Se llamaba
    // «Tablero de ventas» y en el menú pone «Embudo de ventas»: quien lo
    // busca lo busca por «embudo», que es la palabra del oficio, y al llegar
    // encontraba otro nombre. Que sea un tablero lo cuenta la entradilla.
    titulo: "Embudo de ventas",
    entradilla:
      "Arrastra una oportunidad para cambiarla de etapa. Cada columna dice " +
      "cuántas hay y cuánto suman.",
    elegir: "Elegir pipeline",
    columnaVacia: "Nada en esta etapa",
    moverA: "Mover «{{oportunidad}}» a otra etapa",
    sinPipeline: "Todavía no hay ningún pipeline",
    sinPipelineDetalle:
      "Un pipeline son las etapas por las que pasa una venta. Sin él no se pueden " +
      "dar de alta oportunidades.",
    irAConfigurar: "Crear un pipeline",
  },

  acciones: {
    // El menú de lo que no se usa a diario. «Más» a secas y no «Más
    // acciones»: va al lado de botones que ya son acciones.
    mas: "Más",
    abrir: "Abrir",
    titulo: "Qué se puede hacer con esto",
    hecho: "Hecho",
    noSeDeshace:
      "Esto no se puede deshacer desde aquí. Sigue adelante solo si es lo que quieres.",
    entendido: "Lo entiendo, sigue",
    // El rótulo corto de las acciones que van a la vista en la cabecera de la
    // ficha (`destacadas` del recurso). El resumen del contrato es una frase
    // —«Mandar el presupuesto al cliente»— y como botón no cabe.
    destacada: {
      convertir: "Convertir",
      cerrar: "Cerrar el caso",
      enviar: "Enviar",
      responder: "Responder",
    },
  },
  inicio: {
    // Cuando las cuatro cajas de la portada salen vacías a la vez. Dice el
    // porqué —no te han asignado nada— y no «no hay datos», que es lo que
    // parecía y es falso: los hay, son de otros.
    nadaMio:
      "No tienes nada asignado todavía. Esta pantalla contesta «qué tengo yo hoy», así que te sale vacía; el trabajo del equipo sí está.",
    verDelEquipo: "Ver las oportunidades",
    empezar: "Dar de alta",
    saludo: "Hola, {{nombre}}",
    // Lo que había aquí —«{{pantallas}} pantallas a tu alcance»— describía el
    // producto, no el día de quien entra. Contar pantallas es una métrica
    // nuestra; a quien abre esto a primera hora no le dice nada.
    miDia: "Esto es lo que tienes hoy.",
    entradilla:
      "{{pantallas}} pantallas a tu alcance. Busca cualquiera con {{atajo}}.",
    vencidas: "Ya se ha pasado",
    nadaVencido: "Nada vencido. Bien.",
    hoy: "Para hoy",
    nadaHoy: "Nada vence hoy.",
    porDecidir: "Te toca decidir",
    nadaPorDecidir: "Nada espera tu decisión.",
    sinTitulo: "(sin título)",
    aprobar: "Aprobar",
    rechazar: "Rechazar",
    aprobarEsto: "Aprobar «{{titulo}}»",
    rechazarEsto: "Rechazar «{{titulo}}»",
    vaTarde: "va tarde",
    cierranEstaSemana: "Cierran esta semana",
    nadaCierra: "Ninguna de las tuyas cierra esta semana.",
    miEmbudo: "Mi embudo",
    etapa: "Etapa",
    importe: "Importe",
    verTodas: "Ver todas",
    verEmbudo: "Ver el embudo",
    sinRoles: "Sin roles asignados todavía",
    modulos: "Módulos del catálogo",
    modulosDetalle: "Cada uno enseña una sección del catálogo funcional.",
    herramientas: "Herramientas",
    verTodos: "Ver todos",
  },
  casos: {
    titulo: "Casos",
    entradilla:
      "Lo que va a incumplir se separa de lo que ya incumplió: lo primero se " +
      "puede salvar y lo segundo hay que explicarlo.",
    incumplidos: "Fuera de plazo",
    enRiesgo: "A punto de vencer",
    resto: "Con margen",
    // Se dice con qué antelación avisa: si no, ver un caso en «a punto de
    // vencer» y otro parecido fuera no tiene explicación posible.
    entradillaConUmbral:
      "Lo que va a incumplir se separa de lo que ya incumplió: lo primero se " +
      "puede salvar y lo segundo hay que explicarlo. Avisamos con {{horas}} h " +
      "de antelación.",
    ninguno: "Ninguno aquí",
    ningunoDetalle: "No hay casos abiertos. Nada que atender ahora mismo.",
    ningunoIncumplido: "Nada fuera de plazo.",
    ningunoEnRiesgo: "Nada a punto de vencer.",
    yMas: "y {{count}} más",
    escalado: "Escalado",
    incumplido: "incumplido",
    sinSla: "Sin plazo",
    vence: "vence en {{tiempo}}",
    vencidoHace: "vencido hace {{tiempo}}",
  },
  consolaAgente: {
    // Dos relojes distintos, rotulados distinto: un caso tiene plazo y una
    // conversación sólo antigüedad. «5 min» para los dos haría creer que
    // significan lo mismo.
    venceEn: "vence en {{minutos}} min",
    vencidoHace: "vencido hace {{minutos}} min",
    esperando: "esperando {{minutos}} min",
    sinReloj: "sin plazo",
    titulo: "Consola de agente",
    entradilla:
      "Una sola cola con todos los canales. Con una bandeja por canal, el correo " +
      "se mira dos veces al día y el chat todo el rato.",
    vacia: "No hay nada esperando",
    vaciaDetalle: "Cuando entre una conversación aparecerá aquí.",
    sinAsunto: "(sin asunto)",
  },
  avisos: {
    abrir: "Avisos",
    titulo: "Avisos",
    marcarTodas: "Marcar todo como leído",
    // El recuento se anuncia para quien no ve la pantalla: pulsar «marcar» y
    // que no pase nada audible es no saber si funcionó.
    sinLeer_one: "Queda 1 aviso sin leer",
    sinLeer_other: "Quedan {{count}} avisos sin leer",
    cargando: "Trayendo los avisos…",
    vacio: "No hay avisos. Cuando algo que sigues cambie, aparecerá aquí.",
  },
  marketing: {
    titulo: "Marketing",
    entradilla:
      "Segmentos y campañas. El recuento de un segmento lleva siempre su fecha: " +
      "un número sin fecha se lee como el de ahora.",
    segmentos: "Segmentos",
    campanas: "Campañas",
    sinSegmentos: "Todavía no hay segmentos",
    sinCampanas: "Todavía no hay campañas",
    sinCalcular: "sin calcular",
    calculado: "calculado el {{fecha}}",
    nuncaCalculado: "nunca calculado",
    dinamico: "dinámico",
    congelado: "foto congelada",
    miembros: "{{miembros}} miembros",
    sinMiembros: "sin miembros todavía",
  },
  entrar: {
    codigo: "Código del segundo factor",
    recordarEquipo:
      "Recordar este equipo, si tu empresa lo permite: no volverá a pedir el código aquí salvo que cambie algo (la red, el país o el tiempo sin entrar)",
    codigoPorQue:
      "Tu empresa exige el segundo factor: escribe el código de tu aplicación de autenticación.",
    olvidada: "¿No la recuerdas?",
    recuperarTitulo: "Recuperar el acceso",
    recuperarAyuda:
      "Te mandamos un enlace para poner una contraseña nueva. Vale una vez y caduca en media hora.",
    enlaceEnviado: "Si ese correo tiene cuenta, le hemos mandado el enlace.",
    mandarEnlace: "Mandarme el enlace",
    volver: "Volver a entrar",
    eligeNueva:
      "Elige una contraseña nueva. Al guardarla se cerrarán las sesiones abiertas.",
    contrasenaNueva: "Contraseña nueva",
    minimoDoce: "Al menos 12 caracteres.",
    guardarContrasena: "Guardar la contraseña",
    contrasenaCambiada: "Contraseña cambiada. Ya puedes entrar con ella.",
    conPasskey: "Entrar con una passkey",
    noSePudo: "No se ha podido entrar. Comprueba los datos.",
    llaveNoVale: "No se ha podido entrar con esa llave.",
    pie: "Acceso reservado a personal autorizado.",
    ver: "Ver la contraseña",
    ocultar: "Ocultar la contraseña",
    faltaTenant: "Dinos primero de qué organización eres.",
    o: "o",
    titulo: "Entrar",
    email: "Correo electrónico",
    tenant: "Organización",
    contrasena: "Contraseña",
    enviar: "Entrar",
    sso: "Entrar con el proveedor de mi organización",
    error: "No se ha podido iniciar sesión",
  },
  procesos: {
    titulo: "Editor de procesos",
    intro:
      "El diagrama y el JSON son la misma definición: se puede escribir el proceso a mano y abrirlo como diagrama, o moverlo en el lienzo y leerlo como código. Validar y simular no publican nada — un error descubierto aquí es un mensaje; descubierto en ejecución, un proceso a medias en producción.",
    clave: "Clave",
    nombre: "Nombre",
    validar: "Validar",
    simular: "Simular",
    guardarBorrador: "Guardar como borrador",
    publicar: "Publicar",
    abrir: "Abrir una versión guardada",
    nueva: "Nueva definición",
    guardada: "Guardada como versión {{version}}: {{estado}}.",
    publicarVersion: "Publicar la versión {{version}}",
    archivarVersion: "Archivar la versión {{version}}",
    valida: "La definición es válida.",
    lienzo: "Diagrama",
    codigo: "Definición",
    recorrido: "Recorrido simulado",
    jsonAMedias:
      "El JSON está a medias: el diagrama vuelve en cuanto sea válido.",
    mover: "Mover",
    variablesEjemplo: "Datos de ejemplo (JSON)",
    respuestasEjemplo: "Respuestas a las tareas humanas (JSON)",
    quienYCuanto: "Quién aprobaría y cuánto tardaría",
    quienYCuantoAyuda:
      "El recorrido dice por qué pasos iría. Esto dice por cuántas manos y en cuánto tiempo, que es lo que decide alguien. El plazo es el DECLARADO en la definición, no una predicción.",
    sinManos: "Este camino no pasa por ninguna tarea humana.",
    sinDueno: "sin dueño declarado",
    enHoras: "vence en {{horas}} h",
    sinPlazo: "sin plazo declarado",
    totalHoras: "Plazo declarado del camino: {{horas}} h",
    migrarAEsta: "Migrar las instancias en vuelo a esta versión",
    migracionTitulo: "Instancias en vuelo hacia la versión {{version}}",
    pasarian: "Pasarían a esta versión",
    migradas: "Ya siguen con esta versión",
    seQuedan: "Se quedan con su versión",
    instanciaEnPaso: "{{id}} · v{{version}} · en «{{paso}}»",
    instanciaMovida: "{{id}} · desde la v{{version}} · en «{{paso}}»",
    confirmarMigracion: "Migrar {{n}} a la versión {{version}}",
    plantillasTitulo: "Plantillas de flujo",
    plantillasAyuda:
      "Procesos de ejemplo por sector. Copiar crea un BORRADOR tuyo con clave nueva y lo abre aquí: lo ajustas y lo publicas. Mejorar la plantilla no cambia tus copias.",
    plantillasVacia: "La biblioteca está vacía en esta instalación.",
    cargarDeSerie: "Cargar las de serie",
    claveDeLaCopia: "Clave de la copia de «{{plantilla}}»",
    copiarComoBorrador: "Copiar como borrador",
    copiada:
      "Copiada como «{{clave}}»: {{estado}}. Ajústala y publícala cuando esté lista.",
  },
  miRevision: {
    titulo: "Revisión de accesos de tu gente",
    ayuda:
      "Confirma lo que siguen necesitando y retira lo que no. Retirar lo quita en el momento y pide motivo.",
    hasta: "hasta el {{fecha}}",
    vencio: "venció el {{fecha}}",
    tipos: { rol: "Rol", conjunto: "Conjunto de permisos" },
    fueraDePlazo: "fuera de plazo",
    confirmar: "Confirmar",
    retirar: "Retirar",
    motivo: "Por qué se retira",
    retirarYa: "Retirar el acceso",
    decisiones: { confirmado: "Confirmado", retirado: "Retirado" },
  },
  aprobaciones: {
    titulo: "Aprobaciones de documentos",
    intro:
      "Lo que espera tu decisión en el gestor documental. Va con tu identidad: nadie ve lo que espera la firma de otro.",
    nadaPendiente: "No hay nada esperando tu decisión.",
    organizacion:
      "Esta empresa está mapeada a la organización «{{organizacion}}» del gestor documental (estado: {{estado}}).",
    sinOrganizacion:
      "Esta empresa no está mapeada a ninguna organización del gestor documental, así que no se le pregunta nada: una bandeja vacía aquí no quiere decir que no haya nada pendiente.",
    sinCorpus:
      "Este despliegue no tiene corpus documental, así que no hay documentos que aprobar. Lo resuelve contecmind, y se enciende con DMS_ENABLED.",
    corpusCaido:
      "El gestor documental no responde en {{url}}, así que ahora mismo no se puede saber qué espera tu decisión. Los adjuntos de los registros siguen funcionando: son otra cosa.",
    estado: "Estado: {{estado}}",
    etapa: "Etapa {{n}}",
    noTeToca:
      "Aquí no te toca decidir. Quién firma y en qué orden lo lleva el gestor documental.",
    comentario: "Por qué (queda registrado con la decisión)",
    delegarEn: "Delegar en (identificador de la persona en el gestor)",
    confirmar: "Confirmar la decisión",
    enviando: "Enviando…",
    decidida:
      "Decidida. El gestor dice: {{estado}}. Aprobar no siempre acaba en «publicado»: si el reindexado del fichero falla, la versión queda aprobada, sigue publicada la anterior y la publicación se puede reintentar.",
    decision: {
      approved: "Aprobar",
      rejected: "Rechazar",
      delegated: "Delegar",
    },
    indexado: "En el gestor: {{estado}}",
    conAvisos: "indexado con {{n}} aviso(s): faltan figuras, tablas o pies",
    controlEstado:
      "Control documental: {{estado}} · versión en curso {{version}}",
    enCurso: "Aprobación en curso: {{estado}}",
    noLaNecesita: "Este documento no pasa por aprobación.",
    flujo: "Flujo de aprobación",
    flujoElQueToque: "El que corresponda",
    aprobadores: "Quién aprueba (opcional)",
    aprobadoresExigidos: "Quién aprueba (este flujo lo exige)",
    aprobadoresPista: "Identificadores en el gestor, separados por comas",
    faltanAprobadores:
      "Este flujo toma los aprobadores de la propia solicitud, así que hay que decir quiénes son.",
    pedir: "Pedir la aprobación",
  },
  ficha: {
    // La ruta de etapas de una ficha. Para quien no la ve: una lista
    // ordenada no dice de qué es, y «Prospección, Cualificación…» suelto
    // podría ser cualquier cosa.
    ruta: "Recorrido de {{campo}}",
    identificadores: "Identificadores técnicos",
    queHaCambiado: "Qué ha cambiado",
    sinCambios: "Sin cambios anotados",
    editar: "Editar",
    guardar: "Guardar cambios",
    eliminar: "Eliminar",
    eliminarDeVerdad: "Sí, eliminar",
    confirmarOperacion:
      "«{{accion}}», sobre este registro. Lo que cuelga de él —adjuntos, " +
      "comentarios, documentos— puede dejar de estar accesible desde aquí.",
    confirmarBorrado:
      "Se va a eliminar este registro. Lo que cuelga de él —adjuntos, comentarios, " +
      "documentos— deja de estar accesible desde aquí.",
    sinCamposEditables:
      "El contrato de este objeto no declara ningún campo que se pueda cambiar " +
      "después de crearlo.",
    secciones: "Secciones de la ficha",
    // Los nombres de Salesforce, y en su orden. «Relacionado» es lo que
    // cuelga del registro y «Detalles» son sus campos.
    relacionado: "Relacionado",
    detalles: "Detalles",
    actividad: "Actividad",
    // Para quien no ve la pantalla: la línea de encima del panel dice de qué
    // listado viene el registro y cuál es.
    deDonde: "De dónde viene este registro",
    datos: "Datos",
    adjuntos: "Adjuntos",
    comentarios: "Comentarios",
    documentos: "Documentos",
    subir: "Subir un fichero",
    subido: "Adjunto subido",
    subiendo: "Subiendo…",
    escribir: "Escribir un comentario",
    enviar: "Enviar",
    documentosIntro:
      "Estos documentos viven en el gestor documental. Aquí está el enlace y para qué está enlazado; el estado real —versión, aprobación, obsolescencia— es de allí.",
    buscarCorpus: "Traer un documento del corpus",
    buscarCorpusPista: "Busca por su contenido o por su título",
    buscar: "Buscar",
    buscando: "Buscando…",
    enlazar: "Enlazar aquí",
    aprobacion: "Aprobación de estos documentos",
    verAprobacion: "Ver aprobación",
    cerrar: "Cerrar",
    corpusSinResultados:
      "No hay ningún documento que puedas ver con eso. La búsqueda va con tu identidad, así que enseña lo que verías entrando al gestor.",
  },
  modulo: {
    // El menú del final de cada fila de un listado.
    abrir: "Abrir",
    editar: "Editar",
    // Encima del formulario de una fila sin ficha: «Revocar una clave» no
    // dice cuál, y con cincuenta en la lista eso es lo que hay que ver.
    sobreLaFila: "Sobre «{{nombre}}»",
    servicio: "Servicio",
    sinRegistros: "Aquí no hay nada todavía",
    sinRegistrosDetalle: "Da de alta el primero y aparecerá en esta lista.",
    desde: "Desde",
    hasta: "Hasta",
    eligePeriodo:
      "Elige el periodo: un informe sin fechas no es el de hoy, es el de ningún sitio.",
    rangoAlReves: "La fecha de inicio es posterior a la de fin.",
    escribeParaBuscar: "Escribe al menos {{minimo}} caracteres para buscar.",
    nuevo: "Nuevo",
    cancelar: "Cancelar",
    guardar: "Guardar",
    // Lo que el servidor devuelve UNA vez al dar de alta: el secreto de una
    // clave de API. Después sólo guarda su hash.
    unaVezTitulo: "Cópialo ahora: no se volverá a enseñar",
    unaVezAviso:
      "Este valor sólo se muestra esta vez. Guárdalo en un sitio seguro antes de cerrar este aviso: si se pierde, hay que crear otro.",
    unaVezCerrar: "Ya lo he copiado",
    filasCargadas: "{{cuantas}} filas cargadas",
    cargarMas: "Cargar más",
    seccion: "sección",
    // Era «Enseña {{cuantas}} capacidades del catálogo» y estaba debajo del
    // título, a lo ancho. Ahora es el rótulo de un desplegable a la derecha,
    // y tiene que caber en una esquina: una palabra que diga qué hay dentro
    // sin prometer trabajo. El recuento se ha ido dentro, donde está la lista
    // que cuenta — fuera decía «0 capacidades» en los módulos que aún no
    // declaran ninguna, que es justo lo contrario de lo que pasa.
    trazabilidad: "Trazabilidad",
    // Cuántas pestañas hay dentro del desplegable. Con la tira el número se
    // veía; escondiéndolas habría que adivinarlo.
    cuantasPestanas_one: "1 vista",
    cuantasPestanas_other: "{{count}} vistas",
    capacidades_one: "1 capacidad del catálogo",
    capacidades_other: "{{count}} capacidades del catálogo",
  },
  errores: {
    soloPlataformaDetalle:
      "Da de alta empresas y ve su consumo quien opera contecrm, no cada empresa " +
      "sobre las demás.",
    sinPermisoDetalle:
      "Si necesitas verlo, pídeselo a quien administra tu organización.",
    soloPlataforma:
      "Esto es de quien administra la plataforma, no de una empresa concreta.",
    generico: "Algo ha ido mal",
    sinPermiso: "No tienes permiso para esto",
    politica: "Una política de acceso lo impide",
    conflicto: "Alguien ha cambiado este registro mientras lo editabas",
    noEncontrado: "No existe",
    sinRed: "No se ha podido contactar con el servidor",
    encoladaSinConexion:
      "Sin conexión: el cambio se ha guardado en este dispositivo y se enviará al volver la red. Lo ves en «Sin conexión».",
    // Un fallo al PINTAR no es un fallo de red, y decirlo así manda a
    // mirar al sitio equivocado. El mensaje dice lo que se sabe —esta
    // pantalla— y lo que NO se ha perdido: el dato está, y lo demás del
    // producto sigue funcionando.
    pantalla:
      "Esta pantalla no se ha podido pintar. No es un problema de tus datos: siguen guardados, y el resto del producto funciona.",
    detalleTecnico: "Detalle técnico",
    // El identificador de la petición (CRM-00.02.04.07): lo que se pega a
    // soporte y lo que busca el audit trail.
    peticion: "Identificador de la petición",
    copiar: "Copiar",
    copiado: "Copiado",
    peticionAyuda:
      "Si escribes a soporte, pega este identificador: con él se encuentra esta petición en el registro.",
  },
  noExiste: {
    titulo: "Esa dirección no existe",
    detalle: "No hay ninguna pantalla en",
    volver: "Volver al inicio",
  },
  vacio: {
    titulo: "Aquí no hay nada todavía",
    detalle: "Cuando lo haya, aparecerá en esta lista.",
  },
  retenidos_uno: "Hay un campo que no puedes ver: {{campos}}",
  retenidos_otros: "Hay campos que no puedes ver: {{campos}}",
  // Tapado no es lo mismo que retenido, y por eso es otra frase: lo retenido
  // no viene y se ve el hueco; lo tapado viene y PARECE el dato. Sin decirlo,
  // alguien copia «··············tora» creyendo que es el nombre.
  enmascarados_uno:
    "Un campo se ve tapado y lo que muestra no es su valor: {{campos}}",
  enmascarados_otros:
    "Estos campos se ven tapados y lo que muestran no es su valor: {{campos}}",

  chat: {
    buscar: "Buscar en mis conversaciones",
    hallazgos: "{{cuantos}} resultados",
    quienEsta: "Quién está",
    vistoA: "visto {{cuando}}",
    miembros: "{{cuantos}} personas:",
    admin: "admin",
    queDeciaAntes: "Qué decía antes",
    sinVersiones: "No queda constancia de versiones anteriores",
    cerrar: "Cerrar",
    nueva: "Abrir una conversación",
    conAlguien: "Con alguien",
    unCanal: "Un canal",
    buscarPersona: "Buscar a alguien",
    nadieAsi: "Nadie con ese nombre",
    comoSeLlama: "Cómo se llama el canal",
    sinLeerAviso_one: "Chat: {{count}} mensaje sin leer",
    sinLeerAviso_other: "Chat: {{count}} mensajes sin leer",
    titulo: "Chat interno",
    intro:
      "Lo que se habla del trabajo, dentro del CRM. Una conversación puede colgar de un registro: la de esta oportunidad se abre desde su ficha, con el importe al lado.",
    conversaciones: "Conversaciones",
    crearCanal: "Crear el canal",
    sinConversaciones: "Todavía no estás en ninguna conversación.",
    eligeUna: "Elige una conversación",
    eligeUnaDetalle: "O crea un canal para lo que aún no tiene sitio.",
    escribe: "Escribe un mensaje. Menciona con @correo.",
    enviar: "Enviar",
    responder: "Responder en hilo",
    borrar: "Borrar",
    recuperar: "Recuperar",
    borrado: "Mensaje borrado",
    respondiendo: "Respondiendo en un hilo",
    reaccionar: "Reaccionar",
    editado: "editado",
    editadoVeces: "Corregido {{veces}} vez/veces",
    alguien: "Alguien",
    sobreEl: "Sobre un registro de tipo {{objeto}}",
    ultimoDe: "Último mensaje, de {{quien}}: {{texto}}",
  },

  proveedores: {
    titulo: "Proveedores",
    intro:
      "Si puedes encargarle esto hoy, si tiene los papeles y a quién llamar cuando falla.",
    cuenta: "Cuenta del proveedor",
    cuentaAyuda: "Identificador de la cuenta",
    sinProveedores: "Todavía no hay ningún proveedor",
    alta_documento: "Añadir documento",
    alta_homologacion: "Homologar en una categoría",
    alta_contacto: "Añadir contacto",
    homologaciones: "Homologaciones",
    contactos: "Contactos",
    guardia: "Guardia",
    guardar: "Guardar",
    comoSeCrea:
      "Un proveedor es una cuenta a la que se le ha dado ese papel. " +
      "Se marca desde la ficha de la cuenta, en «Dar papel de proveedor».",
    sinDatos: "No consta ningún documento",
    vencidos: "Vencidos",
    porVencer: "Vencen pronto",
    bloquea: "bloquea",
    enDias: "en {{dias}} días",
    sinFecha: "Sin fecha de caducidad",
    sinFechaPorque:
      "Nunca van a aparecer en una lista de vencidos, y por eso se quedan para siempre.",
  },
  puesto: {
    titulo: "Puesto de trabajo",
    intro:
      "Correo y calendario conectados: si está entrando algo y desde cuándo no.",
    sinConexiones: "No hay ninguna conexión",
    paradas: "Conexiones paradas",
    horas: "{{horas}} h sin sincronizar",
    sinMedir:
      "{{cuantas}} conexiones no se han medido: no cuentan como buenas.",
    factor: {
      titulo: "Tu segundo factor",
      sinSaber: "No se ha podido comprobar si tienes segundo factor.",
      puesto:
        "Tienes segundo factor. Al entrar se te pedirá el código de tu autenticador.",
      sinPoner:
        "Tu cuenta entra sólo con la contraseña. Un segundo factor es lo que impide que una contraseña filtrada sirva de algo.",
      activar: "Activar el segundo factor",
      quitar: "Quitar el segundo factor",
      comoSeApunta:
        "Apunta este código en tu autenticador (Google Authenticator, 1Password, el que uses) y escribe después el número de seis cifras que te dé.",
      abrirEnElAutenticador: "Abrirlo directamente en el autenticador",
      recuperacion:
        "Códigos de recuperación: guárdalos ahora, no se vuelven a enseñar",
      elCodigo: "El código de seis cifras",
      confirmar: "Confirmar",
    },
  },
  // La ficha emergente al entrar una llamada (CRM-04.02.01.05). En el marco.
  // Volver a verificarse sin salir (CRM-00.05.01.18): lo pide cualquier
  // operación sensible, desde cualquier pantalla.
  reverificar: {
    titulo: "Confirma que eres tú",
    porQue:
      "Esta operación es sensible —crear una clave, exportar, borrar en bloque, restaurar— y pide haber verificado tu identidad hace poco.",
    pideCodigo: "Escribe el código de tu app de autenticación y se hará.",
    codigo: "Código de 6 cifras de tu app de autenticación",
    confirmar: "Confirmar y seguir",
    cancelar: "Cancelar",
    sinApp:
      "No tienes activada la app de autenticación, así que no hay con qué verificarte sin volver a entrar. Actívala en tu puesto y vuelve a intentarlo.",
    irAlPuesto: "Activarla en mi puesto",
  },
};
