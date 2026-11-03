/**
 * El árbol de navegación, en un solo sitio (CRM-07.04.01.03).
 *
 * Lo leen tres cosas —el panel lateral, la miga de pan de la barra superior y
 * la paleta de comandos— y por eso está aquí en vez de repetido en cada una.
 * Tres listas que tienen que coincidir acaban no coincidiendo, y la que se
 * queda corta siempre es la del buscador: una pantalla que existe, se ve en el
 * menú y no aparece al buscarla parece rota.
 *
 * Los **módulos funcionales** no se enumeran aquí: salen de `modulos.ts`, que
 * es la declaración de cobertura del catálogo. Duplicarlos habría sido la misma
 * trampa una planta más abajo.
 *
 * Los iconos son nombres de Material Symbols, los mismos de contecmind. Se
 * eligen por lo que la pantalla HACE y no por lo que se llama: un icono que
 * ilustra el nombre en vez de la función deja de ayudar en cuanto la pantalla
 * se renombra.
 */

import { puede, type Sesion } from "@/lib/sesion";

export interface Entrada {
  /** Camino en la aplicación. */
  a: string;
  /** Clave de traducción del rótulo. */
  clave: string;
  /** Nombre del símbolo de Material. */
  icono: string;
  /**
   * Permiso que hace falta para que tenga sentido enseñarla.
   *
   * Sin él, la entrada es para todo el mundo. Con él, quien no lo tenga **no la
   * ve**: ofrecer lo que no se puede hacer obliga a probarlo para descubrirlo, y
   * lo que se descubre es un error.
   */
  permiso?: string;
  /** Solo para quien opera la plataforma, no para una empresa. */
  solo_plataforma?: boolean;
  /**
   * Entrada que NO va en el ámbito de su área.
   *
   * Es una excepción y lleva su motivo escrito al lado, porque una excepción
   * sin motivo se copia. Hoy sólo hay una: las aprobaciones viven en
   * Automatización —que es de administrar— y son trabajo diario de cualquier
   * responsable, no algo que se configure.
   */
  ambito?: IdAmbito;
  /**
   * Recursos de la API que esta pantalla enseña.
   *
   * Solo lo declaran las pantallas escritas a mano: las de los módulos ya se
   * saben por su `listar`. Sirve para el informe de cobertura, que sin esto
   * contaba como «sin pantalla» todo lo que no fuera un módulo —proveedores,
   * cuadros de mando, inteligencia— y daba una lista de carencias inventada.
   */
  recursos?: string[];
}

/**
 * Los accesos de cabecera: lo que se usa varias veces al día.
 *
 * Van como pastillas y no dentro de una sección plegable porque una sección
 * plegada esconde justo lo que más se pulsa — y quien la pliega una vez la
 * tiene plegada para siempre.
 */
/**
 * Las áreas del producto. **Una sola taxonomía.**
 *
 * Antes había dos en paralelo: los «módulos», agrupados por su grupo del
 * catálogo, y las «pantallas transversales», agrupadas por otro criterio. Esa
 * división es de dónde viene el código, no de lo que hace, y a quien usa el
 * sistema no le dice nada: «Marketing» salía como grupo de módulos **y** como
 * pantalla suelta en otra sección, «Casos» como acceso rápido **y** dentro de
 * Servicio, «Plataforma» como grupo **y** como sección. Seis pantallas
 * aparecían dos veces con el mismo nombre en sitios distintos.
 *
 * Ahora cada pantalla está en un sitio y solo en uno, y el sitio es el dominio
 * de negocio: clientes, ventas, marketing, servicio, análisis, automatización y
 * configuración. Es lo que hacen las herramientas del mercado —Salesforce
 * agrupa por app, HubSpot por CRM/Marketing/Ventas/Servicio— y por un motivo:
 * quien entra sabe a qué viene, no de qué servicio salió la pantalla.
 *
 * Los módulos del catálogo se reparten por su grupo (`AREA_DE_GRUPO`), así que
 * añadir un módulo no exige tocar esta lista: aparece solo en su área.
 */
/**
 * Las dos entradas del producto.
 *
 * **Es el corte que faltaba.** Las siete áreas estaban bien pensadas y en una
 * sola taxonomía, pero colgaban todas del mismo menú: quien entraba a trabajar
 * veía, a la misma altura y con el mismo peso, «Cuentas» y «Modelo de datos».
 * Un comercial no configura objetos y un consultor no llama a clientes, y
 * ponerles las dos cosas delante obliga a los dos a leer el menú entero cada
 * vez para encontrar lo suyo.
 *
 * No son dos aplicaciones: es la **misma sesión y los mismos permisos**. Lo
 * único que cambia es qué se pone delante, que es de lo que iba el problema.
 */
export const AMBITOS = [
  { id: "trabajar", clave: "nav.ambitoTrabajar", icono: "work" },
  { id: "administrar", clave: "nav.ambitoAdministrar", icono: "settings" },
] as const;

export type IdAmbito = (typeof AMBITOS)[number]["id"];

export const AREAS = [
  { id: "clientes", clave: "nav.areaClientes", icono: "groups", ambito: "trabajar" },
  { id: "ventas", clave: "nav.areaVentas", icono: "trending_up", ambito: "trabajar" },
  { id: "marketing", clave: "nav.areaMarketing", icono: "campaign", ambito: "trabajar" },
  { id: "servicio", clave: "nav.areaServicio", icono: "support_agent", ambito: "trabajar" },
  { id: "analisis", clave: "nav.areaAnalisis", icono: "insights", ambito: "trabajar" },
  // ── Lo de administrar ───────────────────────────────────────────────────
  //
  // **Eran dos áreas y una era un cajón de sastre.** Medido el 03-11-2026:
  // «Automatización» tenía 2 entradas y «Configuración» 18 —desde «Usuarios y
  // permisos» hasta «Ayuda» y «Estado», que no configuran nada—, y las tres
  // pantallas de cumplimiento estaban repartidas entre las dos. Un árbol con
  // una rama de dieciocho hojas no es un árbol: es la lista de antes con un
  // título encima.
  //
  // Los temas son los del árbol de Setup de Salesforce, por lo mismo que el
  // resto del rediseño: Administration (personas y empresa), Platform Tools
  // (lo que se modela y lo que se automatiza), Environments (lo que se
  // despliega) y lo de gobierno aparte.
  { id: "usuarios", clave: "nav.areaUsuarios", icono: "manage_accounts", ambito: "administrar" },
  { id: "plataforma", clave: "nav.areaPlataforma", icono: "handyman", ambito: "administrar" },
  { id: "automatizacion", clave: "nav.areaAutomatizacion", icono: "bolt", ambito: "administrar" },
  { id: "entornos", clave: "nav.areaEntornos", icono: "layers", ambito: "administrar" },
  { id: "gobierno", clave: "nav.areaGobierno", icono: "gavel", ambito: "administrar" },
] as const;

export type IdArea = (typeof AREAS)[number]["id"];

/** El ámbito de un área. */
export function ambitoDelArea(id: IdArea): IdAmbito {
  return (AREAS.find((a) => a.id === id)?.ambito ?? "trabajar") as IdAmbito;
}

/**
 * A qué área va cada grupo del catálogo.
 *
 * Los cinco últimos son de administrar: cosas que se ajustan una vez y se
 * revisan de tarde en tarde, no trabajo diario. Meterlas entre las pantallas
 * de uso diario es parte de lo que hacía el menú ilegible.
 *
 * **Los grupos del catálogo se llaman igual que su área.** Antes los seis
 * módulos de plataforma —empresas, usuarios, objetos, contrato, procesos y
 * operación— compartían el grupo «Plataforma» y caían todos en la misma rama
 * del árbol, que es la mitad de por qué esa rama tenía dieciocho hojas. Y el
 * grupo sale además en el buscador, así que dos nombres distintos para lo
 * mismo obligaban a aprender dos taxonomías.
 */
export const AREA_DE_GRUPO: Record<string, IdArea> = {
  Clientes: "clientes",
  Ventas: "ventas",
  Marketing: "marketing",
  Servicio: "servicio",
  "Analítica": "analisis",
  "Usuarios y empresa": "usuarios",
  "Herramientas de plataforma": "plataforma",
  "Automatización": "automatizacion",
  "Entornos y despliegue": "entornos",
  "Gobierno y cumplimiento": "gobierno",
};

/**
 * Los accesos de cabecera: lo que se usa varias veces al día.
 *
 * Van como pastillas y fuera de las áreas porque son el punto de partida, no un
 * dominio. Y son pocos a propósito: una fila de pastillas con diez elementos
 * deja de ser un acceso rápido.
 */
export const ACCESOS: Entrada[] = [
  { a: "/", clave: "nav.inicio", icono: "home" },
  { a: "/puesto", clave: "nav.puesto", icono: "desk" },
  // El chat va aquí y no en un área porque no trata de un dominio: se habla de
  // clientes, de ventas y de casos desde el mismo sitio. Estaba escrito, tenía
  // ruta en el router y no salía en ningún menú, así que solo lo encontraba
  // quien supiera teclear la dirección.
  { a: "/chat", clave: "nav.chat", icono: "forum", recursos: ["chat"] },
  // Aquí arriba y no en un área, por lo mismo que el chat: te mencionan en una
  // cuenta, en una oportunidad y en un caso, y buscarlas por área sería tener
  // que mirar tres sitios.
  { a: "/menciones", clave: "nav.menciones", icono: "alternate_email" },
];

/**
 * Las pantallas que no salen del catálogo, cada una en su área.
 *
 * Los rótulos las distinguen de su módulo hermano cuando lo tienen: «Bandeja de
 * casos» es la vista de trabajo ordenada por plazo y «Casos y SLA» es el módulo
 * con sus catálogos. Antes las dos se llamaban «Casos» y estaban en sitios
 * distintos del menú.
 */
export const TRANSVERSALES: (Entrada & { area: IdArea })[] = [
  // Qué contratos están parados y por quién. Va en **Ventas** y no en
  // Automatización, que es donde vive el motor de firma: quien persigue una
  // firma es quien cierra la venta, y la busca al lado de sus oportunidades.
  // Colocarla por donde está implementada en vez de por donde se usa es lo que
  // hace que no se encuentre — y además habría necesitado una excepción de
  // ámbito, que es justo la señal de que el sitio está mal elegido.
  { area: "ventas", a: "/pendiente-de-firma", clave: "nav.firma", icono: "draw", permiso: "integracion:read" , recursos: ["firma"] },
  { area: "ventas", a: "/embudo", clave: "nav.embudo", icono: "view_kanban", permiso: "opportunity:read" , recursos: ["pipeline"] },
  { area: "ventas", a: "/coste", clave: "nav.coste", icono: "payments", permiso: "opportunity:read" , recursos: ["coste"] },
  // En Ventas y sin `ambito` propio: quien decide un mapa de territorios es
  // quien lleva el equipo comercial, no quien administra el sistema, y Ventas
  // entera vive en «trabajar». Se probó marcarlo «administrar» y el gate de
  // las dos entradas lo rechazó con razón: un área que aparece en las dos
  // deja de significar nada, y la excepción de las aprobaciones —la única que
  // hay— está justificada porque aprobar un descuento ES trabajo diario.
  { area: "ventas", a: "/territorios", clave: "nav.territorios", icono: "map", permiso: "forecast:read" , recursos: ["territorios"] },
  // Sin `recursos`: no lista cadencias ni plantillas, contesta cuáles
  // funcionan y a quién le toca la próxima reunión.
  { area: "ventas", a: "/prospeccion", clave: "nav.prospeccion", icono: "forward_to_inbox", permiso: "lead:read" },

  // Las parejas que podrían ser la misma ficha, con los botones para
  // decidirlas. Va en Clientes y no en Configuración: quien resuelve un
  // duplicado es quien conoce a los dos clientes, no quien administra.
  { area: "clientes", a: "/duplicados", clave: "nav.duplicados", icono: "join_inner", permiso: "account:write" },

  { area: "marketing", a: "/marketing", clave: "nav.marketing", icono: "insights", permiso: "campaign:read"  },
  // Sin `recursos`: no lista ninguna colección del módulo de canales, lo que
  // hace es contestar si se le puede escribir a alguien por uno de ellos.
  { area: "marketing", a: "/canales", clave: "nav.canales", icono: "forum", permiso: "campaign:read" },

  { area: "servicio", a: "/casos", clave: "nav.casos", icono: "confirmation_number", permiso: "case:read"  },
  { area: "servicio", a: "/consola-agente", clave: "nav.consolaAgente", icono: "headset_mic", permiso: "case:read" , recursos: ["consola-agente"] },
  { area: "servicio", a: "/conocimiento", clave: "nav.conocimiento", icono: "menu_book", permiso: "conocimiento:read" , recursos: ["conocimiento"] },
  // En Servicio y no en Administración: quien mira si la trampa de un canal se
  // está comiendo correos de clientes es quien atiende, no quien configura.
  { area: "servicio", a: "/canales-de-entrada", clave: "nav.canalesDeEntrada", icono: "inbox", permiso: "case:read" , recursos: ["canales-servicio"] },

  { area: "analisis", a: "/cuadros", clave: "nav.cuadros", icono: "dashboard", permiso: "informe:read" , recursos: ["cuadros-mando", "informes"] },
  { area: "analisis", a: "/explotacion", clave: "nav.explotacion", icono: "query_stats", permiso: "informe:read" , recursos: ["explotacion"] },
  { area: "analisis", a: "/rendimiento", clave: "nav.rendimiento", icono: "speed"  },
  { area: "analisis", a: "/inteligencia", clave: "nav.inteligencia", icono: "neurology", permiso: "ia:usar"  },

  // ── Automatización ──────────────────────────────────────────────────────
  { area: "automatizacion", a: "/procesos", clave: "nav.procesos", icono: "account_tree", permiso: "proceso:read"  },
  // La única excepción de ámbito del producto: vive en Automatización, que es
  // de administrar, y es trabajo diario de cualquier responsable. Aprobar un
  // descuento no es configurar nada, y esconderlo detrás de «Administrar» es
  // garantizar que las aprobaciones se queden esperando.
  { area: "automatizacion", ambito: "trabajar", a: "/aprobaciones", clave: "nav.aprobacionesDoc", icono: "approval" , recursos: ["documentos"] },

  // ── Usuarios y empresa ──────────────────────────────────────────────────
  // Las personas, lo que pueden hacer y bajo qué empresa. Es el nodo
  // «Administration» del árbol de Salesforce.
  //
  // Las cuatro preguntas de seguridad que el módulo genérico no puede contestar
  // porque no son tablas: quién no tiene segundo factor, qué certificado del
  // IdP caduca, quién tiene permisos incompatibles y por qué esta persona ve
  // esto. `user:read` porque es lo que exigen sus extremos.
  { area: "usuarios", a: "/seguridad", clave: "nav.seguridad", icono: "shield_person", permiso: "user:read" , recursos: ["factores", "sso-gobierno", "segregacion", "roles"] },
  { area: "usuarios", a: "/administracion", clave: "nav.consola", icono: "tune", permiso: "tenant:read"  },
  // Quién entra en cada herramienta de la casa y qué falta por aplicar. Va con
  // las personas y no con la automatización, que es donde estaba: lo que se
  // mira aquí son accesos, no un motor. Y el rótulo decía «Suite» a secas,
  // que no contesta nada.
  { area: "usuarios", a: "/suite", clave: "nav.suite", icono: "sync_alt", permiso: "integration:read" , recursos: ["suite"] },

  // ── Herramientas de plataforma ──────────────────────────────────────────
  // Lo que se modela y lo que se publica: el nodo «Platform Tools».

  // ── Entornos y despliegue ───────────────────────────────────────────────
  { area: "entornos", a: "/alm", clave: "nav.alm", icono: "swap_horiz", permiso: "metadata:read" , recursos: ["entornos"] },
  { area: "entornos", a: "/entornos", clave: "nav.entornos", icono: "difference", permiso: "metadata:read" },
  // En Configuración y con permiso de tenant: quien clona, fusiona o migra un
  // cliente no es quien vende ni quien atiende.
  { area: "entornos", a: "/ciclo-de-vida", clave: "nav.cicloDeVida", icono: "swap_horiz", permiso: "tenant:read" },
  // Si la plataforma responde, y desde cuándo no. No es configuración —no se
  // ajusta nada aquí—, pero sí es la pregunta de quien despliega.
  { area: "entornos", a: "/estado", clave: "nav.estado", icono: "monitor_heart" },

  // ── Gobierno y cumplimiento ─────────────────────────────────────────────
  // Las tres pantallas de cumplimiento, juntas por primera vez: estaban
  // repartidas entre «Gobierno» (el módulo, con los registros), «Panel de
  // cumplimiento» (si eso se puede medir) y «Plataforma y cumplimiento» (el
  // rastro y la privacidad), en dos ramas distintas del menú.
  //
  // El audit trail, las anomalías de exportación, el registro de tratamiento,
  // la matriz de permisos y la papelera: rutas que el producto publica desde
  // el primer día y a las que no se llegaba desde ninguna pantalla. Medido
  // sobre el contrato: 477 colecciones GET sin un solo botón, 170 de ellas la
  // misma ruta repetida en los catorce servicios.
  { area: "gobierno", a: "/plataforma", clave: "nav.plataforma", icono: "shield_lock", permiso: "tenant:read" , recursos: ["grc"] },
  // Al lado del módulo «Riesgos y controles» y no en vez de él: aquel lista
  // los riesgos y los controles —los registros— y éste contesta si eso que
  // hay se puede medir y qué no cuadra hoy. Sin `recursos`, porque no enseña
  // ninguna de sus dos colecciones: decir que sí lo contaría como enseñado y
  // mandaría aquí a quien busca un riesgo concreto.
  { area: "gobierno", a: "/cumplimiento", clave: "nav.cumplimiento", icono: "verified_user", permiso: "tenant:read" },
];

/**
 * El menú de ayuda: la interrogación de la barra de arriba.
 *
 * **No son configuración y estaban dentro de ella.** «Ayuda», «Recorrido
 * guiado» y «Cobertura» hablan del producto —cómo se usa, qué sabe hacer—, no
 * del cliente ni de su ajuste, y vivían en la misma rama que «Usuarios y
 * permisos» y «Promoción entre entornos». Quien busca ayuda no entra en la
 * configuración a buscarla, y quien configura se las encuentra en medio.
 *
 * Van donde las pone Salesforce: la interrogación de la barra, al lado del
 * engranaje. Y se abren desde donde uno esté, que es cuando hacen falta.
 */
export const AYUDA: Entrada[] = [
  { a: "/ayuda", clave: "nav.ayuda", icono: "help" },
  { a: "/recorrido", clave: "nav.recorrido", icono: "route" },
  { a: "/cobertura", clave: "nav.cobertura", icono: "fact_check" },
];

/** Todas las entradas fijas, sin los módulos. Para la paleta y la miga de pan. */
export function todasLasEntradas(): Entrada[] {
  return [...ACCESOS, ...TRANSVERSALES, ...AYUDA];
}

/**
 * ¿Le toca a esta persona?
 *
 * Se usa en el menú **y en el buscador**: encontrar por búsqueda una pantalla
 * que el menú esconde es peor que no esconderla, porque parece que el sistema
 * se contradice.
 */
export function entradaVisible(sesion: Sesion | null, entrada: Entrada): boolean {
  if (entrada.solo_plataforma && !sesion?.es_admin_plataforma) return false;
  return puede(sesion, entrada.permiso);
}

/** Icono por defecto de un módulo funcional, según su grupo del catálogo. */
export function iconoDeGrupo(grupo: string): string {
  const POR_GRUPO: Record<string, string> = {
    Clientes: "groups",
    Ventas: "trending_up",
    Marketing: "campaign",
    Servicio: "support_agent",
    "Analítica": "insights",
    "Usuarios y empresa": "manage_accounts",
    "Herramientas de plataforma": "handyman",
    "Automatización": "bolt",
    "Entornos y despliegue": "layers",
    "Gobierno y cumplimiento": "gavel",
  };
  // `folder` y no un icono al azar: un grupo nuevo del catálogo tiene que salir
  // con algo neutro, no con el icono del grupo anterior por descuido.
  return POR_GRUPO[grupo] ?? "folder";
}

/**
 * El color del cuadrado del icono, por módulo.
 *
 * **Es lo más reconocible de Salesforce y es lo que aquí no había.** Allí cada
 * objeto tiene el suyo —las cuentas malva, los candidatos naranja, las
 * oportunidades amarillo, los casos ámbar— y sirve para algo concreto: en una
 * pestaña, en una ficha o en un resultado de búsqueda, el color dice QUÉ es
 * antes de leer una palabra. Aquí todos los iconos eran el mismo azul del
 * acento, así que el cuadrado no distinguía nada y sólo era decoración.
 *
 * Los valores son los de su paleta de objetos. Van por MÓDULO y no por grupo:
 * dentro de Clientes, las cuentas y los proveedores son dos cosas distintas y
 * en Salesforce tienen color distinto.
 *
 * Lo que no está en esta tabla cae en el azul del acento, que es lo que había:
 * un módulo nuevo sale neutro en vez de heredar el color del de al lado.
 */
const COLOR_POR_MODULO: Record<string, string> = {
  cuentas: "#7F8DE1", // Cuentas y Contactos, malva
  proveedores: "#A094ED",
  leads: "#F88962", // Candidatos, naranja
  oportunidades: "#FCB95B", // amarillo
  prevision: "#5CA5A5",
  canal: "#56AADF",
  actividades: "#6BBF59",
  casos: "#F2CF5B", // ámbar
  postventa: "#E8A33D",
  campo: "#8C9BA5",
  omnicanal: "#54698D",
  conocimiento: "#58A8D4",
  campanas: "#F49756",
  segmentos: "#C77FBE",
  canales: "#9D8CE3",
  contenido: "#71B8A0",
  explotacion: "#4BC076",
  ia: "#9A77CF",
};

export function colorDeModulo(ruta: string): string | null {
  return COLOR_POR_MODULO[ruta] ?? null;
}

/**
 * El menú tal como se pinta: un área, y dentro sus módulos y sus pantallas.
 *
 * Aquí se funden las dos listas —lo que sale del catálogo y lo que no— en una
 * sola. Quien mira no distingue si una pantalla es un «módulo» o una
 * «transversal», y no tiene por qué: lo que distingue es si trata de clientes o
 * de ventas.
 */
export interface AreaPintada {
  id: IdArea;
  clave: string;
  icono: string;
  entradas: Entrada[];
}

/**
 * El ámbito en el que se enseña una entrada: el suyo si lo declara, si no el
 * de su área.
 */
export function ambitoDe(entrada: Entrada, area: IdArea): IdAmbito {
  return entrada.ambito ?? ambitoDelArea(area);
}

/**
 * A qué ámbito pertenece un camino, para saber qué pestaña marcar.
 *
 * Se deriva del camino y **no se guarda en un estado**: si fuera estado, abrir
 * un enlace directo a una pantalla de configuración dejaría marcada la pestaña
 * de trabajar, y quien lo viera pensaría que el menú está roto. Lo desconocido
 * cae en «trabajar», que es donde está casi todo y donde se entra.
 */
export function ambitoDelCamino(
  camino: string,
  grupoDelModulo?: (ruta: string) => string | undefined,
): IdAmbito {
  // Los módulos del catálogo (`/m/<ruta>`) **también tienen ámbito**, y hasta
  // el 27-10-2026 no se miraban: sólo se buscaba entre las pantallas a medida,
  // así que `/m/tenants` o `/m/modelo` caían en «trabajar» por descarte. El
  // efecto era de los que se sufren: estando en Administrar, abrir cualquier
  // módulo de administración cambiaba la pestaña a Trabajar, y como el destino
  // de esa pestaña es la portada, el siguiente clic te sacaba del sitio donde
  // estabas trabajando. Lo contó quien lo usaba, no una prueba.
  //
  // El grupo se pide como función en vez de importar el catálogo de módulos:
  // este fichero lo carga el marco entero y ese catálogo pesa.
  const modulo = /^\/m\/([^/]+)/.exec(camino);
  if (modulo && grupoDelModulo) {
    const grupo = grupoDelModulo(modulo[1] ?? "");
    if (grupo) return ambitoDelArea(AREA_DE_GRUPO[grupo] ?? "plataforma");
  }
  const entrada = TRANSVERSALES.filter((e) => camino.startsWith(e.a)).sort(
    (a, b) => b.a.length - a.a.length,
  )[0];
  if (entrada) return ambitoDe(entrada, entrada.area);
  return "trabajar";
}

export function menuDe(
  modulosPorGrupo: Map<string, { ruta: string; titulo: string; grupo: string }[]>,
  visible: (entrada: Entrada) => boolean,
  ambito?: IdAmbito,
): AreaPintada[] {
  const porArea = new Map<IdArea, Entrada[]>();
  for (const [grupo, modulos] of modulosPorGrupo) {
    const area = AREA_DE_GRUPO[grupo] ?? "plataforma";
    const previas = porArea.get(area) ?? [];
    porArea.set(area, [
      ...previas,
      // Sin icono por entrada: dentro de un área todas compartirían el icono
      // del área, que repetido doce veces no distingue nada y solo ensucia. El
      // icono va en la cabecera del área, que es donde sí orienta.
      ...modulos.map((m) => ({ a: `/m/${m.ruta}`, clave: m.titulo, icono: "" })),
    ]);
  }
  for (const entrada of TRANSVERSALES) {
    if (!visible(entrada)) continue;
    porArea.set(entrada.area, [...(porArea.get(entrada.area) ?? []), entrada]);
  }
  return AREAS.map((a) => ({
    id: a.id,
    clave: a.clave,
    icono: a.icono,
    // El filtro va por ENTRADA y no por área: si fuera por área, la excepción
    // de las aprobaciones no existiría —se iría entera con Automatización— y
    // el campo `ambito` de `Entrada` sería decorativo.
    entradas: (porArea.get(a.id) ?? []).filter(
      (e) => !ambito || ambitoDe(e, a.id) === ambito,
    ),
  })).filter((a) => a.entradas.length > 0);
}
