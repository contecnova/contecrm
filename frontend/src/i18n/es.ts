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
    tema: "Cambiar tema",
    densidad: "Densidad de la interfaz",
    // Dos textos y no uno: el botón dice A DÓNDE va, no dónde está. «Densidad
    // compacta» con la interfaz ya compacta no se sabe si es el estado o la
    // acción, y es el error más repetido en los interruptores.
    densidadCompacta: "Ver más en pantalla (compacta)",
    densidadComoda: "Ver con más aire (cómoda)",
    saltarAlContenido: "Saltar al contenido",
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
  medidor: {
    sinObjetivo: "Sin objetivo fijado: esto es una cifra, no un medidor.",
    cumplido: "Objetivo {{objetivo}} — cumplido",
    faltan: "Objetivo {{objetivo}} — faltan {{falta}}",
  },
  grafica: {
    verTabla: "Ver como tabla",
    verDibujo: "Ver como gráfica",
    sinDatos: "No hay datos que dibujar",
    otras: "Otras {{count}}",
  },
  formulario: {
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
  altas: {
    cuenta: "Cliente",
    contacto: "Contacto",
    oportunidad: "Oportunidad",
    lead: "Lead",
    actividad: "Actividad o tarea",
    caso: "Caso de soporte",
  },
  nav: {
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
    nexus: "Nexus",
    duplicados: "Duplicados",
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
      "Exportar en masa pide volver a verificar tu identidad. Hazlo desde tu " +
      "perfil y vuelve: vale para los próximos {{minutos}} minutos.",
    sinSegundoFactor:
      "Exportar en masa exige un segundo factor y tu cuenta no tiene ninguno " +
      "configurado. Se configura desde tu perfil.",
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

  tabla: {
    columnas: "Columnas ({{visibles}} de {{total}})",
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
    cuantosElementos_one: "1 elemento",
    cuantosElementos_other: "{{count}} elementos",
    ordenadoAsc: "Ordenado por {{columna}}, de menor a mayor",
    ordenadoDesc: "Ordenado por {{columna}}, de mayor a menor",
    ordenarPor: "Ordenar por {{columna}}",
    ordenAsc: "{{columna}}, de menor a mayor. Pulsa para invertir.",
    ordenDesc: "{{columna}}, de mayor a menor. Pulsa para quitar el orden.",
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
  },
  subcoleccion: {
    vacia: "Nada todavía",
    quitar: "Quitar",
    confirmarQuitar: "¿Quitar este elemento? No se deshace desde aquí.",
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
  explotacion: {
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
    esInforme: "Es informe",
    vecesUsada: "Usada {{veces}} veces",
  },
  entrar: {
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
  },
  aprobaciones: {
    titulo: "Aprobaciones de documentos",
    intro:
      "Lo que espera tu decisión en el gestor documental. Va con tu identidad: nadie ve lo que espera la firma de otro.",
    nadaPendiente: "No hay nada esperando tu decisión.",
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
  // El panel de IA de cada ficha: lo que estaba escondido en «Más».
  asistenteIA: {
    titulo: "Con IA",
    detalle: "Lo que propone es un borrador: no se guarda ni se manda sin ti.",
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
    // Un fallo al PINTAR no es un fallo de red, y decirlo así manda a
    // mirar al sitio equivocado. El mensaje dice lo que se sabe —esta
    // pantalla— y lo que NO se ha perdido: el dato está, y lo demás del
    // producto sigue funcionando.
    pantalla:
      "Esta pantalla no se ha podido pintar. No es un problema de tus datos: siguen guardados, y el resto del producto funciona.",
    detalleTecnico: "Detalle técnico",
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
};
