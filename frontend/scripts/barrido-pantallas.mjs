/**
 * Abre TODAS las pantallas contra la pila local y dice cuáles revientan.
 *
 *     ./setup.sh arrancar
 *     node frontend/scripts/barrido-pantallas.mjs
 *
 * **Por qué existe.** El 01-11-2026 se encontraron dos pantallas muertas —la
 * ficha de cualquier oportunidad con metodología activa y `/inteligencia`— y
 * las dos llevaban rotas quién sabe cuánto. Las dos por lo mismo: el front da
 * por hecha una forma que el servidor no manda, React tira el árbol entero y
 * la frontera de error se come la pantalla.
 *
 * Nada de lo que ya había lo caza:
 *
 * - **TypeScript no**, porque el tipo se declara en el `llamar<T>` y ya: es
 *   una promesa sobre datos de red, no una comprobación.
 * - **Los gates tampoco**: la pantalla existe, monta en una prueba con dobles
 *   —que inventan la forma, y por eso la confirman— y tiene su ruta.
 * - **Y el barrido de humo tampoco**, porque el servidor contesta 200.
 *
 * Sólo lo encuentra abrirlas de verdad, con datos de verdad. Esto lo hace en
 * noventa segundos. NO es un gate: necesita la pila levantada y datos
 * sembrados, así que no puede correr en `preflight`. Se pasa cuando se toca el
 * front a lo ancho.
 *
 * Los destinos salen del propio producto —`navegacion.ts` y `modulos.ts`— y no
 * de una lista a mano, que se quedaría corta a la primera pantalla nueva. De
 * cada listado abre además **su primera ficha**, que es donde estaba el fallo
 * de verdad.
 */
import { chromium } from "playwright";
import { readFileSync } from "node:fs";

const APP = process.env.CRM_URL ?? "http://localhost:15173";
// Las que imprime `./setup.sh arrancar`. Por entorno para poder apuntar a otra
// instalación sin tocar el fichero.
const EMPRESA = process.env.CRM_EMPRESA ?? "plataforma";
const USUARIO = process.env.CRM_USUARIO ?? "plataforma@contecrm.dev";
const CLAVE = process.env.CRM_CLAVE ?? "Plataforma2026.crm";
const SRC = new URL("../src/", import.meta.url).pathname;

// Los destinos, sacados del propio producto y no de una lista a mano.
const nav = readFileSync(`${SRC}lib/navegacion.ts`, "utf8");
const caminos = new Set(["/"]);
for (const m of nav.matchAll(/\ba:\s*"(\/[^"]*)"/g)) caminos.add(m[1]);
const mods = readFileSync(`${SRC}lib/modulos.ts`, "utf8");
for (const m of mods.matchAll(/ruta:\s*"([a-z-]+)",\s*\n\s*titulo:/g)) caminos.add(`/m/${m[1]}`);

const navegador = await chromium.launch();
const ctx = await navegador.newContext({ viewport: { width: 1440, height: 900 }, locale: "es-ES" });
const p = await ctx.newPage();
const errores = [];
p.on("pageerror", (e) => errores.push(String(e).slice(0, 160)));

await p.goto(APP, { waitUntil: "networkidle" });
await p.fill('input[autocomplete="organization"]', EMPRESA);
await p.fill('input[type="email"]', USUARIO);
await p.fill('input[autocomplete="current-password"]', CLAVE);
await p.click('button[type="submit"]:visible');
await p.waitForTimeout(3000);
if (/entrar/.test(new URL(p.url()).pathname)) {
  // Ruidoso a propósito: si la entrada falla en silencio, lo que viene después
  // mide la pantalla de entrada y sale «ninguna rota».
  console.error(`NO SE HA ENTRADO en ${APP} con ${USUARIO}. Sin sesión, este barrido no mira nada.`);
  process.exit(1);
}

/**
 * Texto que es el dato en crudo y no una palabra de nadie.
 *
 * `null`, `undefined` y `[object Object]` son lo que sale cuando un valor
 * vacío o compuesto llega a la pantalla sin pasar por el formateador de la
 * casa. **Medido el 02-11-2026**: la pestaña «Detalles» de un caso enseñaba
 * «Motivo: null», «Padre: null», «Contacto ID: null», porque `String(null)`
 * da «null» y los valores compuestos no filtraban los huecos.
 *
 * Se mira con los límites de palabra puestos: «anular» lleva «null» dentro y
 * es castellano. Y se mira en TODAS las pantallas, no sólo en la que se vio,
 * porque el formateador es el mismo para las 58.
 */
const EN_CRUDO = /\bnull\b|\bundefined\b|\[object Object\]/;

/**
 * La escala tipográfica, medida en la PANTALLA.
 *
 * Hay una prueba que lee el código y vigila las tres formas de escribir un
 * tamaño. No basta: se le escapó un 9 px escondido tras una constante
 * —`fontSize={LETRA_GRAFICA}`— y lo cazó plantar el caso malo, no la prueba.
 * Contra cualquier indirección sólo vale mirar lo que el navegador pinta.
 *
 * Los iconos no cuentan: son una ligadura dibujada y su tamaño es el del
 * dibujo, no el de una letra.
 */
const ESCALA = ["12px", "13px", "14px", "16px", "20px", "24px", "32px"];

const rotas = [];
const crudas = [];
const letraFuera = [];
let textosMirados = 0;
// `CRM_SOLO=/procesos,/m/cuentas` recorta el barrido a lo que se nombre. Son
// quince minutos enteros, y perseguir un fallo en una pantalla concreta con
// eso convierte cada intento en una espera. No cambia nada de lo que mide.
const soloEstas = (process.env.CRM_SOLO ?? "")
  .split(",")
  .map((x) => x.trim())
  .filter(Boolean);
const lista = soloEstas.length ? soloEstas : [...caminos].sort();
for (const camino of lista) {
  errores.length = 0;
  await p.goto(APP + camino, { waitUntil: "domcontentloaded" }).catch(() => {});
  await p.waitForTimeout(1600);
  const txt = (await p.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ");
  const rota = /no se ha podido pintar|No se ha podido contactar/i.test(txt);
  if (rota || errores.length) {
    rotas.push(`${camino}\n     ${errores[0] ?? txt.slice(0, 120)}`);
  }
  const letra = await p.evaluate((escala) => {
    const vistos = new Map();
    let mirados = 0;
    for (const e of document.querySelectorAll("main *")) {
      if (e.getClientRects().length === 0 || e.children.length) continue;
      if (!(e.textContent || "").trim()) continue;
      const cs = getComputedStyle(e);
      if (/Material Symbols/.test(cs.fontFamily)) continue;
      mirados += 1;
      if (escala.includes(cs.fontSize)) continue;
      if (!vistos.has(cs.fontSize)) {
        vistos.set(cs.fontSize, (e.textContent || "").trim().slice(0, 30));
      }
    }
    return { mirados, fuera: [...vistos].map(([t, q]) => `${t} «${q}»`) };
  }, ESCALA);
  // **Cuántos ha mirado, no sólo cuántos ha encontrado.** Una pantalla que
  // todavía no ha pintado nada da cero textos fuera de la escala con el mismo
  // verde que una que está bien, y eso ya pasó: con un 9 px plantado a
  // propósito, este barrido contestó «ninguna» mientras una sonda suelta lo
  // veía. Se suman y se dicen al final.
  textosMirados += letra.mirados;
  if (letra.fuera.length) {
    letraFuera.push(`${camino}\n     ${letra.fuera.join(" · ")}`);
  }

  const crudo = EN_CRUDO.exec(txt);
  if (crudo) {
    const desde = Math.max(0, crudo.index - 50);
    crudas.push(`${camino}\n     …${txt.slice(desde, crudo.index + 60)}…`);
  }
  // Y la primera ficha del listado, que es donde estaba el fallo de verdad.
  const enlace = await p.$("main tbody tr a");
  if (enlace) {
    errores.length = 0;
    await enlace.click().catch(() => {});
    await p.waitForTimeout(1800);
    const t2 = (await p.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ");
    if (/no se ha podido pintar|No se ha podido contactar/i.test(t2) || errores.length) {
      rotas.push(`${camino} → ficha ${new URL(p.url()).pathname}\n     ${errores[0] ?? t2.slice(0, 120)}`);
    }
    // Y en la ficha se recorren además SUS pestañas: el dato en crudo estaba
    // en «Detalles», que no sale hasta que alguien la pulsa.
    //
    // **Por su rótulo y no por «cualquier `nav` dentro de `main`».** Con el
    // selector ancho se pulsaba todo botón de todo `nav` —paginación, menús,
    // selectores—, a 900 ms cada uno: el barrido pasó de tres minutos a más
    // de quince, y cada clic dejaba el navegador donde le parecía. Medido el
    // 02-11-2026 al perseguir por qué el barrido no veía un 9 px que una
    // sonda suelta sobre la misma pantalla sí veía.
    const pestanas = await p.$$('main nav[aria-label="Secciones de la ficha"] button');
    for (const boton of pestanas.slice(0, 6)) {
      await boton.click().catch(() => {});
      await p.waitForTimeout(600);
      const t3 = (await p.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ");
      const c3 = EN_CRUDO.exec(t3);
      if (c3) {
        const desde = Math.max(0, c3.index - 50);
        crudas.push(`${camino} → ficha\n     …${t3.slice(desde, c3.index + 60)}…`);
        break;
      }
    }
  }
}
console.log(`recorridas: ${lista.length} pantallas`);
console.log(`ROTAS: ${rotas.length}`);
console.log(`CON EL DATO EN CRUDO: ${crudas.length}`);
console.log(`CON LETRA FUERA DE LA ESCALA: ${letraFuera.length} (de ${textosMirados} textos mirados)`);
if (rotas.length || crudas.length || letraFuera.length) process.exitCode = 1;
console.log([...rotas, ...crudas, ...letraFuera].map((r) => "  " + r).join("\n"));
await navegador.close();
