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

const rotas = [];
const lista = [...caminos].sort();
for (const camino of lista) {
  errores.length = 0;
  await p.goto(APP + camino, { waitUntil: "domcontentloaded" }).catch(() => {});
  await p.waitForTimeout(1600);
  const txt = (await p.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ");
  const rota = /no se ha podido pintar|No se ha podido contactar/i.test(txt);
  if (rota || errores.length) {
    rotas.push(`${camino}\n     ${errores[0] ?? txt.slice(0, 120)}`);
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
  }
}
console.log(`recorridas: ${lista.length} pantallas`);
console.log(`ROTAS: ${rotas.length}`);
if (rotas.length) process.exitCode = 1;
console.log(rotas.map((r) => "  " + r).join("\n"));
await navegador.close();
