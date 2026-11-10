/**
 * Las aplicaciones: cuatro puertas en vez de un menú de cincuenta y nueve.
 *
 * **El problema, medido el 01-11-2026.** El producto ofrecía de un vistazo 24
 * módulos del catálogo, ~35 pantallas escritas a mano y 211 pestañas dentro de
 * ellas —23 en Procesos, 19 en Operación, 16 en Gobierno de la IA—. Todo
 * colgando de una barra lateral de 29 entradas en la que convivían «Cuentas y
 * contactos» y «Contrato de la API». Quien entra a mirar sus oportunidades
 * tiene que leer cincuenta y nueve rótulos para encontrar uno.
 *
 * **La forma de resolverlo es la de Salesforce**, y se copia a propósito
 * porque es la que la gente de un CRM ya conoce:
 *
 * 1. Se trabaja dentro de **una aplicación** cada vez —Ventas, Servicio,
 *    Marketing, Analítica—, y lo que se ve arriba son **sus** pestañas. Lo de
 *    las otras no está escondido: está en otra puerta.
 * 2. El **lanzador** lleva a cualquier aplicación y a cualquier pantalla
 *    escribiendo su nombre, que es lo que se hace cuando ya sabes qué buscas.
 * 3. **La configuración no es una aplicación**: es la otra puerta, y vive
 *    aparte con su propio árbol. Mezclarla con el trabajo diario es la mitad
 *    de lo que hacía ilegible el menú.
 *
 * **Nada de esto es una lista nueva.** Las áreas y su ámbito ya estaban en
 * `navegacion.ts`, razonadas, y lo único que se añade aquí es qué áreas forman
 * cada aplicación. Dos listas escritas a mano acaban diciendo cosas distintas,
 * y hay un gate que comprueba que de toda área sale exactamente una puerta.
 */

import {
  AREAS,
  type AreaPintada,
  type Entrada,
  type IdArea,
} from "@/lib/navegacion";

export interface Aplicacion {
  id: string;
  /** Clave de traducción del nombre. */
  clave: string;
  /** Nombre del símbolo de Material. */
  icono: string;
  /** Las áreas de `navegacion.ts` que entran en esta aplicación. */
  areas: IdArea[];
  /**
   * Las pestañas que van primero, por su camino y en este orden; las demás
   * siguen en el de sus áreas.
   *
   * Lo que no cabe se va a «Más», y en Ventas las entradas de Clientes van
   * detrás de las diez de Ventas: **Cuentas quedaba en «Más»** —medido el
   * 10-11-2026 a 1440 px, la decimotercera de veinte—, siendo con lo que más
   * se trabaja. No se mueve de área —Ventas tiene su tope de diez—: sólo cambia
   * el orden de la barra de esta aplicación.
   */
  delante?: string[];
}

/**
 * Las aplicaciones de trabajo.
 *
 * **Clientes va dentro de Ventas** y no como aplicación propia: las cuentas y
 * los contactos son con lo que trabaja quien vende, y en Salesforce viven en
 * la aplicación de ventas por la misma razón. Tenerlos aparte obligaba a
 * cambiar de sitio para mirar la cuenta de la oportunidad que tienes abierta.
 */
export const APLICACIONES: Aplicacion[] = [
  {
    id: "ventas",
    clave: "app.ventas",
    icono: "trending_up",
    areas: ["ventas", "clientes"],
    // Como en Salesforce: oportunidades, leads y cuentas, lo primero.
    delante: ["/m/oportunidades", "/m/leads", "/m/cuentas"],
  },
  {
    id: "servicio",
    clave: "app.servicio",
    icono: "support_agent",
    areas: ["servicio"],
  },
  {
    id: "marketing",
    clave: "app.marketing",
    icono: "campaign",
    areas: ["marketing"],
  },
  {
    id: "analitica",
    clave: "app.analitica",
    icono: "insights",
    areas: ["analisis"],
  },
];

/**
 * Las áreas de configuración: las que YA se declaran así en `navegacion.ts`.
 *
 * Sale del `ambito` del área y **no por descarte** de las que están en una
 * aplicación. Por descarte parecía más robusto —«lo que no es de trabajo es de
 * configuración»— y era justo al revés: un área que alguien olvidara meter en
 * una aplicación se convertía en configuración sola, sin que nadie lo
 * decidiera, y encima se colaba como pestaña de TODAS las aplicaciones por la
 * regla de las transversales. Un olvido se volvía una decisión silenciosa.
 *
 * Cazado plantando el caso malo: quitando «Clientes» de la aplicación de
 * Ventas, el guardián seguía en verde. Ahora falla y dice cuál se ha quedado
 * sin puerta.
 */
export function areasDeConfiguracion(): IdArea[] {
  return AREAS.filter((a) => a.ambito === "administrar").map((a) => a.id);
}

/** Las áreas de trabajo: las demás, y cada una tiene que estar en una aplicación. */
export function areasDeTrabajo(): IdArea[] {
  return AREAS.filter((a) => a.ambito !== "administrar").map((a) => a.id);
}

/**
 * Las pestañas de una aplicación, en el orden en el que se pintan.
 *
 * Primero «Inicio», que es donde se empieza, y después las entradas de sus
 * áreas en el orden en el que ya estaban. No se reordenan por nombre: el orden
 * de `navegacion.ts` está pensado —lo más usado primero— y alfabetizarlo
 * pondría «Actividades» delante de «Oportunidades». La excepción la declara la
 * aplicación (`delante`): lo que no puede quedar en «Más».
 */
export function pestanasDe(app: Aplicacion, menu: AreaPintada[]): Entrada[] {
  const suyas = app.areas
    .map((id) => menu.find((a) => a.id === id))
    .filter((a): a is AreaPintada => Boolean(a));
  const todas = suyas.flatMap((a) => a.entradas);
  // Las que la aplicación pone delante, si están (y si se ven: lo que no está
  // en el menú de esta sesión no aparece por declararlo aquí).
  const primeras = (app.delante ?? [])
    .map((camino) => todas.find((e) => e.a === camino))
    .filter((e): e is Entrada => Boolean(e));
  return [...primeras, ...todas.filter((e) => !primeras.includes(e))];
}

/**
 * Las pantallas de trabajo que NO son de ningún dominio.
 *
 * Son las que viven en un área de configuración pero están marcadas como
 * trabajo diario. Hoy hay una —las aprobaciones, que viven en Automatización
 * porque ahí está el motor, y son trabajo de cualquier responsable— y por
 * definición no pertenecen a Ventas ni a Servicio: se aprueba un descuento, un
 * contrato y un gasto desde el mismo sitio.
 *
 * Así que van de pestaña en **todas** las aplicaciones, como «Inicio».
 *
 * Esto no es una excepción escrita a mano: sale de cruzar las dos cosas que el
 * producto ya declara —el área de la entrada y su ámbito— y recoge sola a la
 * siguiente que alguien marque igual. Se descubrió porque el guardián de
 * caminos la encontró **sin ninguna puerta**: no salía trabajando, porque su
 * área no es de ninguna aplicación, ni configurando, porque su ámbito no es
 * ése. Estaba escrita, enlazada y sin forma de llegar.
 */
export function pestanasDeTodas(menu: AreaPintada[]): Entrada[] {
  const deConfiguracion = new Set(areasDeConfiguracion());
  return menu
    .filter((a) => deConfiguracion.has(a.id))
    .flatMap((a) => a.entradas);
}

/**
 * En qué aplicación está un camino.
 *
 * Devuelve `null` cuando el camino no es de ninguna —la portada, el chat, las
 * menciones, una pantalla de configuración—, y entonces manda la aplicación
 * que el usuario tenía elegida. Una portada que cambia sola de aplicación
 * según desde dónde llegues no deja saber nunca en cuál estás.
 */
export function aplicacionDelCamino(
  camino: string,
  menu: AreaPintada[],
): Aplicacion | null {
  for (const app of APLICACIONES) {
    const pestanas = pestanasDe(app, menu);
    // Por el prefijo más largo: `/m/casos` y `/m/casos/caso/1` son la misma
    // pestaña, y `/canales` no puede ganarle a `/canales-de-entrada`.
    const casa = pestanas
      .filter((e) => camino === e.a || camino.startsWith(e.a + "/"))
      .sort((x, y) => y.a.length - x.a.length)[0];
    if (casa) return app;
  }
  return null;
}

const CLAVE_APP = "contecrm.aplicacion";

/** La aplicación en la que se estaba. Se recuerda, como la recuerda Salesforce. */
export function aplicacionRecordada(): Aplicacion {
  try {
    const id = localStorage.getItem(CLAVE_APP);
    const app = APLICACIONES.find((a) => a.id === id);
    if (app) return app;
  } catch {
    // Un almacenamiento bloqueado no puede dejar la aplicación sin arrancar.
  }
  return APLICACIONES[0]!;
}

export function recordarAplicacion(app: Aplicacion): void {
  try {
    localStorage.setItem(CLAVE_APP, app.id);
  } catch {
    // Igual: se pierde la preferencia, no la navegación.
  }
}
