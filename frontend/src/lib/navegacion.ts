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
export const AREAS = [
  { id: "clientes", clave: "nav.areaClientes", icono: "groups" },
  { id: "ventas", clave: "nav.areaVentas", icono: "trending_up" },
  { id: "marketing", clave: "nav.areaMarketing", icono: "campaign" },
  { id: "servicio", clave: "nav.areaServicio", icono: "support_agent" },
  { id: "analisis", clave: "nav.areaAnalisis", icono: "insights" },
  { id: "automatizacion", clave: "nav.areaAutomatizacion", icono: "bolt" },
  { id: "configuracion", clave: "nav.areaConfiguracion", icono: "settings" },
] as const;

export type IdArea = (typeof AREAS)[number]["id"];

/**
 * A qué área va cada grupo del catálogo.
 *
 * `Gobierno` y `Plataforma` caen en configuración: son cosas que se ajustan una
 * vez y se revisan de tarde en tarde, no trabajo diario. Meterlas entre las
 * pantallas de uso diario es parte de lo que hacía el menú ilegible.
 */
export const AREA_DE_GRUPO: Record<string, IdArea> = {
  Clientes: "clientes",
  Ventas: "ventas",
  Marketing: "marketing",
  Servicio: "servicio",
  "Analítica": "analisis",
  Gobierno: "configuracion",
  Plataforma: "configuracion",
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
  { area: "clientes", a: "/proveedores", clave: "nav.proveedores", icono: "local_shipping", permiso: "party:read" },

  { area: "ventas", a: "/embudo", clave: "nav.embudo", icono: "view_kanban", permiso: "opportunity:read" },
  { area: "ventas", a: "/coste", clave: "nav.coste", icono: "payments", permiso: "opportunity:read" },

  { area: "marketing", a: "/marketing", clave: "nav.marketing", icono: "insights", permiso: "campaign:read" },
  { area: "marketing", a: "/recorrido", clave: "nav.recorrido", icono: "route", permiso: "campaign:read" },

  { area: "servicio", a: "/casos", clave: "nav.casos", icono: "confirmation_number", permiso: "case:read" },
  { area: "servicio", a: "/consola-agente", clave: "nav.consolaAgente", icono: "headset_mic", permiso: "case:read" },
  { area: "servicio", a: "/conocimiento", clave: "nav.conocimiento", icono: "menu_book", permiso: "conocimiento:read" },

  { area: "analisis", a: "/cuadros", clave: "nav.cuadros", icono: "dashboard", permiso: "informe:read" },
  { area: "analisis", a: "/explotacion", clave: "nav.explotacion", icono: "query_stats", permiso: "informe:read" },
  { area: "analisis", a: "/rendimiento", clave: "nav.rendimiento", icono: "speed" },
  { area: "analisis", a: "/inteligencia", clave: "nav.inteligencia", icono: "neurology", permiso: "ia:usar" },

  { area: "automatizacion", a: "/procesos", clave: "nav.procesos", icono: "account_tree", permiso: "proceso:read" },
  { area: "automatizacion", a: "/suite", clave: "nav.suite", icono: "sync_alt", permiso: "integration:read" },

  { area: "configuracion", a: "/administracion", clave: "nav.consola", icono: "tune", permiso: "tenant:read" },
  { area: "configuracion", a: "/alm", clave: "nav.alm", icono: "layers", permiso: "metadata:read" },
  { area: "configuracion", a: "/cobertura", clave: "nav.cobertura", icono: "fact_check" },
  { area: "configuracion", a: "/estado", clave: "nav.estado", icono: "monitor_heart" },
  { area: "configuracion", a: "/ayuda", clave: "nav.ayuda", icono: "help" },
];

/** Todas las entradas fijas, sin los módulos. Para la paleta y la miga de pan. */
export function todasLasEntradas(): Entrada[] {
  return [...ACCESOS, ...TRANSVERSALES];
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
    Plataforma: "tenancy",
    Clientes: "groups",
    Ventas: "trending_up",
    Marketing: "campaign",
    Servicio: "support_agent",
    "Analítica": "insights",
    Gobierno: "gavel",
  };
  // `folder` y no un icono al azar: un grupo nuevo del catálogo tiene que salir
  // con algo neutro, no con el icono del grupo anterior por descuido.
  return POR_GRUPO[grupo] ?? "folder";
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

export function menuDe(
  modulosPorGrupo: Map<string, { ruta: string; titulo: string; grupo: string }[]>,
  visible: (entrada: Entrada) => boolean,
): AreaPintada[] {
  const porArea = new Map<IdArea, Entrada[]>();
  for (const [grupo, modulos] of modulosPorGrupo) {
    const area = AREA_DE_GRUPO[grupo] ?? "configuracion";
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
    entradas: porArea.get(a.id) ?? [],
  })).filter((a) => a.entradas.length > 0);
}
