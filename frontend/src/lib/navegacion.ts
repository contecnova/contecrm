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

export interface Entrada {
  /** Camino en la aplicación. */
  a: string;
  /** Clave de traducción del rótulo. */
  clave: string;
  /** Nombre del símbolo de Material. */
  icono: string;
}

export interface Seccion {
  /** Identificador estable: es lo que se guarda al plegar la sección. */
  id: string;
  /** Clave de traducción del rótulo de la sección. */
  clave: string;
  entradas: Entrada[];
}

/**
 * Los accesos de cabecera: lo que se usa varias veces al día.
 *
 * Van como pastillas y no dentro de una sección plegable porque una sección
 * plegada esconde justo lo que más se pulsa — y quien la pliega una vez la
 * tiene plegada para siempre.
 */
export const ACCESOS: Entrada[] = [
  { a: "/", clave: "nav.inicio", icono: "home" },
  { a: "/puesto", clave: "nav.puesto", icono: "desk" },
  { a: "/consola-agente", clave: "nav.consolaAgente", icono: "headset_mic" },
  { a: "/casos", clave: "nav.casos", icono: "confirmation_number" },
];

export const SECCIONES: Seccion[] = [
  {
    id: "trabajo",
    clave: "nav.grupoTrabajo",
    entradas: [
      { a: "/recorrido", clave: "nav.recorrido", icono: "route" },
      { a: "/marketing", clave: "nav.marketing", icono: "campaign" },
      { a: "/proveedores", clave: "nav.proveedores", icono: "local_shipping" },
      { a: "/conocimiento", clave: "nav.conocimiento", icono: "menu_book" },
    ],
  },
  {
    id: "analisis",
    clave: "nav.grupoAnalisis",
    entradas: [
      { a: "/cuadros", clave: "nav.cuadros", icono: "dashboard" },
      { a: "/explotacion", clave: "nav.explotacion", icono: "query_stats" },
      { a: "/rendimiento", clave: "nav.rendimiento", icono: "speed" },
      { a: "/coste", clave: "nav.coste", icono: "payments" },
      { a: "/inteligencia", clave: "nav.inteligencia", icono: "neurology" },
    ],
  },
  {
    id: "plataforma",
    clave: "nav.grupoPlataforma",
    entradas: [
      { a: "/administracion", clave: "nav.consola", icono: "settings" },
      { a: "/procesos", clave: "nav.procesos", icono: "account_tree" },
      { a: "/suite", clave: "nav.suite", icono: "sync_alt" },
      { a: "/alm", clave: "nav.alm", icono: "layers" },
      { a: "/cobertura", clave: "nav.cobertura", icono: "fact_check" },
      { a: "/estado", clave: "nav.estado", icono: "monitor_heart" },
      { a: "/ayuda", clave: "nav.ayuda", icono: "help" },
    ],
  },
];

/** Todas las entradas fijas, sin los módulos. Para la paleta y la miga de pan. */
export function todasLasEntradas(): Entrada[] {
  return [...ACCESOS, ...SECCIONES.flatMap((s) => s.entradas)];
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
