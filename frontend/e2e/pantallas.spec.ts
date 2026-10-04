import { expect, test } from "@playwright/test";

import { abrir, desbordamiento, doblarApi, elementosVisibles } from "./apoyo";

/**
 * Las pantallas del front oficial se abren sin dejar la aplicación en blanco.
 *
 * **Lo que esto comprueba, y nada más**, dicho aquí para que un verde no se lea
 * como lo que no es:
 *
 *   1. La aplicación MONTA en esa ruta: hay marco, hay `main`, hay algo visible.
 *   2. Ningún error se lleva la pantalla entera por delante.
 *   3. Nada se sale del ancho de la ventana.
 *
 * **Lo que NO comprueba**: que cada pantalla enseñe lo que dice enseñar. Para
 * eso hace falta un doble que devuelva la forma correcta de cada llamada, y eso
 * es trabajo por pantalla que aquí no está hecho. El catálogo declara 53
 * capacidades de pantalla y esto cubre la primera condición de todas ellas, no
 * las 53.
 *
 * Por qué existe: montándolo apareció que **no había ninguna frontera de error
 * en todo el front**. Un `TypeError` al pintar cualquier pantalla dejaba el
 * `<body>` vacío —ni mensaje, ni menú, ni forma de volver— y eso es lo que
 * comprueba el punto 1. Antes de la frontera, `/estado` daba 0 elementos
 * visibles con la página entera en blanco.
 */

/** Las rutas fijas de `App.tsx`, cada una con su pantalla propia. */
const PANTALLAS: Array<{ ruta: string; nombre: string }> = [
  { ruta: "/", nombre: "Inicio" },
  { ruta: "/administracion", nombre: "Consola" },
  { ruta: "/estado", nombre: "Estado" },
  { ruta: "/cobertura", nombre: "Cobertura" },
  { ruta: "/chat", nombre: "Chat" },
  { ruta: "/recorrido", nombre: "Recorrido" },
  { ruta: "/procesos", nombre: "Procesos" },
  { ruta: "/aprobaciones", nombre: "Aprobaciones" },
  { ruta: "/explotacion", nombre: "Explotación" },
  { ruta: "/cuadros", nombre: "Cuadros" },
  { ruta: "/embudo", nombre: "Embudo" },
  { ruta: "/casos", nombre: "Casos" },
  { ruta: "/consola-agente", nombre: "Consola de agente" },
  { ruta: "/conocimiento", nombre: "Conocimiento" },
  { ruta: "/marketing", nombre: "Marketing" },
  { ruta: "/coste", nombre: "Coste" },
  { ruta: "/inteligencia", nombre: "Inteligencia" },
  { ruta: "/puesto", nombre: "Puesto" },
  { ruta: "/alm", nombre: "Almacén" },
  { ruta: "/rendimiento", nombre: "Rendimiento" },
  { ruta: "/suite", nombre: "Gobierno de la suite" },
  { ruta: "/ayuda", nombre: "Ayuda" },
];

/**
 * Mínimo de elementos visibles para no dar por buena una página en blanco.
 *
 * Tres es poco **a propósito**: lo que se caza es el cero —la aplicación
 * desmontada— y no se opina sobre cuánto tiene que pintar cada pantalla, porque
 * el doble de esta prueba no les da datos de verdad. Subirlo sin arreglar
 * primero el doble sería medir el doble y no la pantalla.
 */
const MINIMO_VISIBLE = 3;

for (const { ruta, nombre } of PANTALLAS) {
  test(`«${nombre}» monta y cabe (${ruta})`, async ({ page }) => {
    const doble = await doblarApi(page);
    await abrir(page, ruta);

    expect(
      doble.vistas(),
      "el doble no ha interceptado ni una llamada: la pantalla está pidiendo " +
        "datos a un servidor que no existe y lo que se mide es su pantalla de error",
    ).toBeGreaterThan(0);

    const visibles = await elementosVisibles(page);
    expect(
      visibles,
      `solo se ven ${visibles} elementos dentro de «main»: la aplicación se ha ` +
        "desmontado y la página está en blanco. Se cuentan con " +
        "`getClientRects()`, así que un menú oculto no la disfraza de llena.",
    ).toBeGreaterThanOrEqual(MINIMO_VISIBLE);

    const sobra = await desbordamiento(page);
    expect(
      sobra,
      `la pantalla se sale ${sobra} px del ancho de la ventana: aparece una ` +
        "barra horizontal y lo de la derecha no se alcanza",
    ).toBeLessThanOrEqual(0);
  });
}

test("el barrido recorre todas las pantallas declaradas", () => {
  // Un barrido que se queda corto contesta «ninguna rota» sin haber mirado.
  // Medido el 04-10-2026: 22 rutas fijas con pantalla propia en `App.tsx`.
  expect(PANTALLAS.length).toBeGreaterThanOrEqual(22);
});

test("sin frontera de error, una pantalla rota se lleva la aplicación entera", async ({
  page,
}) => {
  /**
   * Esto es lo que se arregló, y se comprueba que sigue arreglado.
   *
   * Se provoca el fallo de verdad —una respuesta con una forma que la pantalla
   * no espera— y se exige que quede **algo** en pie: la frontera enseña el
   * error y el marco sobrevive. Sin ella, el cuerpo entero quedaba vacío.
   */
  await page.route("**/*", async (route) => {
    const tipo = route.request().resourceType();
    if (tipo !== "xhr" && tipo !== "fetch") return route.continue();
    const url = route.request().url();
    if (/\/auth\/me(\?|$)/.test(url)) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          usuario: {
            id: "00000000-0000-0000-0000-00000000aaaa",
            nombre: "Ana",
            email: "a@b.c",
            es_plataforma: false,
          },
          tenant_id: "00000000-0000-0000-0000-00000000bbbb",
          roles: [],
          permisos: ["*:*"],
          suplantado_por: null,
        }),
      });
    }
    // Lo que rompe: donde la pantalla espera un objeto con campos, un número.
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "42",
    });
  });

  await page.goto("/estado", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("main", { timeout: 15_000 });

  const visibles = await elementosVisibles(page);
  expect(
    visibles,
    "con una respuesta imposible la aplicación se ha quedado en blanco: la " +
      "frontera de error no está haciendo su trabajo, y el usuario se queda " +
      "sin mensaje, sin menú y sin forma de volver",
  ).toBeGreaterThan(0);
});
