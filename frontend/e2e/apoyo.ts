import type { Page, Route } from "@playwright/test";

/**
 * El doble de la API, y las trampas que tiene montarlo.
 *
 * Esto nace de un aviso de contecpos, donde un barrido llevaba 83 rutas en
 * verde **sin haber mirado una sola pantalla**. Cuatro fallos encadenados, y
 * los dos primeros se evitan aquí:
 *
 * **Se filtra por `resourceType`, no por trozos de la dirección.** Allí el
 * doble interceptaba «la dirección contiene /agenda/» y la dirección de la
 * propia pantalla también lo contiene, así que servía `[]` **como documento**:
 * la página entera era el texto «[]». Sin error, con texto visible y cabiendo
 * en pantalla — tres comprobaciones verdes sobre una pantalla que no existía.
 * Distinguir el documento de la llamada de datos es un hecho que da el
 * navegador, no una suposición sobre cómo son las direcciones.
 *
 * **La aplicación tiene que MONTAR.** Allí no montaba porque faltaba servir un
 * fichero, y se quedaba en la pantalla de «Arrancando…» — que tiene un `<h1>`,
 * así que hasta la comprobación del título pasaba. Aquí `abrir()` espera a que
 * la pantalla de carga desaparezca y a que el marco esté puesto, y falla si no.
 */

/** Quién dice ser quien entra. Sin esto, toda pantalla es la de entrada. */
const YO = {
  usuario: {
    id: "00000000-0000-0000-0000-00000000aaaa",
    nombre: "Ana Prueba",
    email: "ana@ejemplo.com",
    es_plataforma: false,
  },
  tenant_id: "00000000-0000-0000-0000-00000000bbbb",
  roles: ["administrador"],
  // Con todos los permisos a propósito: lo que se mide es si la pantalla pinta,
  // y un 403 por falta de permiso la dejaría vacía por el motivo equivocado.
  permisos: ["*:*"],
  suplantado_por: null,
};

/** Respuesta vacía pero con la FORMA que espera cada tipo de llamada. */
function cuerpoPara(url: string): unknown {
  if (/\/superficie(\?|$)/.test(url)) return { servicios: [], operaciones: [] };
  if (/\/auth\/me(\?|$)/.test(url)) return YO;
  // Los listados devuelven una página, no una lista pelada: servir `[]` donde
  // se espera `{items, total}` hace que la pantalla reviente al leer `.items`,
  // y el fallo parece de la pantalla cuando es del doble.
  if (/\/api\/v1\//.test(url)) return { items: [], total: 0, siguiente: null };
  return {};
}

/**
 * Intercepta SOLO las llamadas de datos y deja pasar el documento y lo estático.
 *
 * Se cuentan las interceptadas para poder exigir que hubo alguna: un doble que
 * no intercepta nada deja la pantalla pidiendo a un servidor que no está, y la
 * prueba mide una pantalla de error.
 */
export async function doblarApi(page: Page): Promise<{ vistas: () => number }> {
  let vistas = 0;
  await page.route("**/*", async (route: Route) => {
    const peticion = route.request();
    const tipo = peticion.resourceType();
    const url = peticion.url();

    // EL DOCUMENTO Y LO ESTÁTICO, INTACTOS. Interceptarlos es el fallo que
    // convirtió «[]» en una página entera.
    if (tipo !== "xhr" && tipo !== "fetch") return route.continue();
    if (!url.includes("/api/v1/") && !url.includes("/config.json")) {
      return route.continue();
    }

    vistas += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(cuerpoPara(url)),
    });
  });
  return { vistas: () => vistas };
}

/**
 * Abre una pantalla y **se asegura de que la aplicación ha montado**.
 *
 * No vale con que cargue: hay que salir de «Arrancando…» y que el marco esté
 * puesto. Sin esto, todas las pantallas se verifican contra la misma pantalla
 * de carga y el barrido sale verde sin haber visto ninguna.
 */
export async function abrir(page: Page, ruta: string): Promise<void> {
  await page.goto(ruta, { waitUntil: "domcontentloaded" });
  // El marco solo se pinta con sesión resuelta: su presencia demuestra las dos
  // cosas a la vez, que arrancó y que no se quedó en la pantalla de entrada.
  // Treinta segundos y no quince: este barrido corre dentro del preflight, con
  // otros cinco gates compitiendo por la máquina, y lo que se mide no es la
  // velocidad de arranque sino si la pantalla monta. Un plazo corto convierte
  // una máquina ocupada en un fallo de pantalla, que manda a buscar al sitio
  // equivocado.
  await page.waitForSelector("nav, [role='navigation'], main", { timeout: 30_000 });
  await page.waitForFunction(
    () => !/arrancando|cargando/i.test(document.body.innerText.slice(0, 200)),
    { timeout: 30_000 },
  );
}

/**
 * Cuántos elementos se VEN de verdad.
 *
 * `innerText` cuenta texto de elementos con `display:none`, así que una pantalla
 * vacía con un menú oculto sale llena y la comprobación está siempre verde. Lo
 * que se cuenta aquí tiene caja: `getClientRects().length > 0`.
 */
export async function elementosVisibles(page: Page): Promise<number> {
  return page.evaluate(() => {
    let n = 0;
    for (const el of document.querySelectorAll("main *")) {
      if ((el as HTMLElement).getClientRects().length > 0) n += 1;
    }
    return n;
  });
}

/** Cuánto se sale del ancho de la ventana, en píxeles. Cero es lo correcto. */
export async function desbordamiento(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}
