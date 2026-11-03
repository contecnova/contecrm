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
// El `titulo:` puede no ir en la línea siguiente —si alguien deja ahí un
// comentario explicando el nombre, por ejemplo—, así que entre los dos se
// admite cualquier cosa que no sea otra `ruta:`. **Medido el 03-11-2026**:
// con el patrón pegado, poner un comentario encima de un título hizo que el
// barrido pasara de 58 pantallas a 57 y dejara una sin mirar en silencio. Lo
// delató el recuento, que por eso se imprime y por eso tiene suelo.
for (const m of mods.matchAll(/ruta:\s*"([a-z-]+)",[\s\S]{0,400}?titulo:/g)) {
  caminos.add(`/m/${m[1]}`);
}

const navegador = await chromium.launch();
const ctx = await navegador.newContext({ viewport: { width: 1440, height: 900 }, locale: "es-ES" });
const p = await ctx.newPage();
const errores = [];
p.on("pageerror", (e) => errores.push(String(e).slice(0, 160)));

/**
 * Lo que contesta la API, que es donde empieza una pantalla muerta.
 *
 * **Medido el 02-11-2026**: `/menciones` y `/territorios` llevaban muertas —un
 * 422 por mandar `limite` a una ruta que no lo declara—, sin `h1` y con el
 * error ocupando la pantalla entera. Este barrido decía «ROTAS: 0», porque
 * buscaba DOS TEXTOS concretos —«no se ha podido pintar», «No se ha podido
 * contactar»— y el de estas era otro. Un guardián que busca el texto del
 * fallo que ya conoce no caza el siguiente.
 *
 * **Qué cuenta y qué no**, que es la parte fina:
 *
 * - **400, 404, 422 y 5xx sí**: el front pidió algo mal o el servidor se cayó.
 *   Ninguna pantalla sana los provoca.
 * - **401 y 403 no**: son la respuesta correcta a pedir lo que no te toca, y
 *   las pantallas de plataforma las provocan a propósito.
 * - **409 tampoco.** Es «el estado no lo permite», que es una respuesta de
 *   negocio. Medido el 02-11-2026 en `/cuadros`: contesta 409 con «el CRM
 *   todavía no está registrado como fuente en contecintelligence, se publica
 *   desde Explotación», que es exactamente lo que hay que decir. Contarlo
 *   habría puesto en rojo una pantalla que funciona, y un guardián que grita
 *   por lo correcto se acaba ignorando.
 * - **Un 503 sí cuenta, pero se vuelve a mirar antes de decirlo.** El 503 de
 *   esta pila es «el gateway no ha podido conectar con el servicio», y eso
 *   pasa aquí por la ráfaga del propio barrido, no por la pantalla. Medido el
 *   03-11-2026 contra la pila local y **sin front por medio**: 300 peticiones
 *   concurrentes a `/api/v1/localizacion` dieron 185 respuestas y **115
 *   conexiones que ni llegaron a abrirse**. Con una sola pasada, el barrido
 *   acusaba a una pantalla distinta cada vez —`/m/casos`, `/m/canal`,
 *   `/cobertura`— por un fallo que no era de ninguna.
 *
 *   Así que se recorre otra vez **esa** pantalla. Si a la segunda contesta,
 *   no es una rota; y se dice cuántas lo necesitaron, porque una pila que
 *   falla una de cada tres conexiones es un dato que no se puede tapar.
 */
const CUENTAN = (e) => e === 400 || e === 404 || e === 422 || e >= 500;
let api = [];
p.on("response", (r) => {
  const u = r.url();
  if (!u.includes("/api/")) return;
  if (CUENTAN(r.status())) {
    api.push(`${r.status()} ${u.replace(APP, "").split("?")[0]}`);
  }
});

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

/**
 * El suelo de pantallas.
 *
 * Un barrido que se queda corto contesta «ninguna rota» sin haber mirado, y
 * eso ya pasó: un comentario entre `ruta:` y `titulo:` dejó una pantalla
 * fuera y el recorrido siguió en verde. El suelo no persigue el número
 * exacto —una pantalla nueva entra sola— sino que el patrón deje de casar.
 */
const SUELO = 55;

const rotas = [];
// Las que fallaron sólo por una conexión caída y a la segunda contestaron.
const reintentadas = [];
const crudas = [];
const letraFuera = [];
let textosMirados = 0;
const dobleVacio = [];
const monoEnFrases = [];
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
  api = [];
  // **Se espera a que la red calle**, no sólo un rato fijo. Con 1.600 ms a
  // secas la medida salía distinta en cada pasada —5.252 textos mirados en
  // una y 3.148 en la siguiente—, porque las pantallas con muchos datos se
  // medían a medio pintar. Una pantalla a medio pintar da «ninguna fuera» con
  // el mismo verde que una que está bien. Lo delató el contador de mirados,
  // que está aquí justo para eso.
  //
  // El `catch` es necesario: una pantalla que refresca sola nunca llega a
  // `networkidle`, y entonces manda el plazo.
  await p.goto(APP + camino, { waitUntil: "networkidle", timeout: 15_000 })
    .catch(() => p.goto(APP + camino, { waitUntil: "domcontentloaded" }).catch(() => {}));
  await p.waitForTimeout(1200);
  const txt = (await p.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ");
  /**
   * Una pantalla MUERTA es la que no llega a pintarse, y eso se reconoce por
   * la marca y no por el texto: el texto cambia con cada fallo nuevo.
   *
   * La alerta SOLA no basta. `/cuadros` enseña una alerta correcta —falta
   * publicar la descripción del CRM— y la pantalla funciona: tiene su título,
   * su selector y sus cuadros. Lo que delata a una muerta es que **la alerta
   * es todo lo que hay**: en `/territorios` no había ni `h1`.
   */
  const estado = await p.evaluate(() => {
    const main = document.querySelector("main");
    if (!main) return { alerta: false, h1: false };
    return {
      alerta: [...main.querySelectorAll('[role="alert"]')].some(
        (e) => e.getClientRects().length > 0,
      ),
      h1: Boolean(main.querySelector("h1")),
    };
  });
  if (errores.length || api.length || (estado.alerta && !estado.h1)) {
    // Si lo ÚNICO que falló fueron 503, se vuelve a mirar: ese código aquí
    // es «el gateway no ha podido conectar», y lo provoca la ráfaga de este
    // mismo barrido. Lo demás no se reintenta: un 404 o una excepción de JS
    // no se arreglan solos, y reintentarlos sería esconderlos.
    const soloCaida =
      errores.length === 0 &&
      !(estado.alerta && !estado.h1) &&
      api.length > 0 &&
      api.every((e) => e.startsWith("503"));
    let perdona = false;
    if (soloCaida) {
      api = [];
      errores.length = 0;
      await p.goto(APP + camino, { waitUntil: "networkidle", timeout: 15_000 })
        .catch(() => p.goto(APP + camino, { waitUntil: "domcontentloaded" }).catch(() => {}));
      await p.waitForTimeout(1200);
      perdona = errores.length === 0 && api.length === 0;
      if (perdona) reintentadas.push(camino);
    }
    if (!perdona) {
      const porque =
        errores[0] ?? api[0] ?? `la alerta es todo lo que hay: ${txt.slice(0, 90)}`;
      rotas.push(`${camino}\n     ${porque}`);
    }
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
  /**
   * Dos vacíos de caja grande en la misma pantalla.
   *
   * El vacío tiene dos formas: la de PANTALLA —tarjeta con icono grande y
   * texto centrado, 180 px— para cuando no hay nada que hacer ahí, y la de
   * SECCIÓN —una línea— para cuando es un bloque de una pantalla que sí
   * tiene más cosas.
   *
   * **Medido el 03-11-2026**: `/entornos` pintaba cuatro de las grandes
   * seguidas, 760 px de nada, porque el vacío iba dentro de un bucle por
   * entorno; `/ciclo-de-vida` tres, y su primer dato caía a 945 px. Cuatro
   * «no hay nada» seguidos no dicen «no tienes nada»: dicen «esto está
   * vacío», que es otra cosa y desanima igual.
   *
   * Se cuentan por su marca y no por su alto: contando por alto y texto, la
   * primera versión de esta medida dio por vacíos bloques que no lo eran.
   */
  const vaciosGrandes = await p.evaluate(
    () =>
      [...document.querySelectorAll('main [data-vacio="pantalla"]')].filter(
        (e) => e.getClientRects().length > 0,
      ).length,
  );
  if (vaciosGrandes > 1) {
    dobleVacio.push(`${camino}\n     ${vaciosGrandes} vacíos de caja grande seguidos`);
  }

  /**
   * Una frase en monoespaciada.
   *
   * La letra de máquina es para lo que se lee carácter a carácter: un
   * identificador, un código, un hash, una cifra que se alinea en columna.
   * Una frase en castellano, no. **Medido el 03-11-2026**: 42 pantallas y 472
   * textos salían así, y lo que salía era «sin medir», «escuchando»,
   * «Apertura: no hay con qué medirla todavía».
   *
   * Lo que SÍ es código se reconoce por su elemento —`code`, `pre`,
   * `textarea`, `input`— y no por una lista de excepciones: los permisos de
   * `/seguridad` y los alcances de OAuth de `/suite` se pasaron a `<code>`
   * por eso, y de paso un lector de pantalla los anuncia como lo que son.
   *
   * Con espacios y sin ningún dígito: así pasan «0/61 · 0 %» y «25 vistas»,
   * que son cifras, y no pasa «sin declarar».
   */
  const frasesEnMono = await p.evaluate(() => {
    const fuera = [];
    for (const e of document.querySelectorAll("main *")) {
      if (e.getClientRects().length === 0 || e.children.length) continue;
      if (e.closest("code, pre, textarea, input")) continue;
      const t = (e.textContent || "").trim();
      if (!t || !/\s/.test(t) || /\d/.test(t)) continue;
      if (!/mono/i.test(getComputedStyle(e).fontFamily)) continue;
      fuera.push(t.slice(0, 44));
    }
    return [...new Set(fuera)];
  });
  if (frasesEnMono.length) {
    monoEnFrases.push(`${camino}\n     ${frasesEnMono.join(" · ")}`);
  }

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
    api = [];
    await enlace.click().catch(() => {});
    await p.waitForTimeout(1800);
    const t2 = (await p.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ");
    const enFicha = await p.evaluate(() => {
      const main = document.querySelector("main");
      if (!main) return { alerta: false, h1: false };
      return {
        alerta: [...main.querySelectorAll('[role="alert"]')].some(
          (e) => e.getClientRects().length > 0,
        ),
        h1: Boolean(main.querySelector("h1")),
      };
    });
    if (errores.length || api.length || (enFicha.alerta && !enFicha.h1)) {
      rotas.push(
        `${camino} → ficha ${new URL(p.url()).pathname}\n     ${errores[0] ?? api[0] ?? t2.slice(0, 120)}`,
      );
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
if (!soloEstas.length && lista.length < SUELO) {
  console.error(
    `SOLO ${lista.length} destinos, y hay al menos ${SUELO}: el patrón que los ` +
      "saca de `navegacion.ts` y `modulos.ts` ha dejado de casar, así que este " +
      "barrido no está mirando lo que cree.",
  );
  process.exitCode = 1;
}
console.log(`ROTAS: ${rotas.length}`);
// Se dice SIEMPRE, también cuando es cero: «ninguna lo necesitó» y «no se
// mira» se leen igual si sólo se imprime cuando hay alguna.
console.log(
  `CON LA CONEXIÓN CAÍDA Y BIEN AL SEGUNDO INTENTO: ${reintentadas.length}` +
    (reintentadas.length ? ` — ${reintentadas.join(", ")}` : ""),
);
console.log(`CON EL DATO EN CRUDO: ${crudas.length}`);
console.log(`CON LETRA FUERA DE LA ESCALA: ${letraFuera.length} (de ${textosMirados} textos mirados)`);
console.log(`CON VARIOS VACÍOS DE CAJA GRANDE: ${dobleVacio.length}`);
console.log(`CON UNA FRASE EN LETRA DE MÁQUINA: ${monoEnFrases.length}`);
if (
  rotas.length ||
  crudas.length ||
  letraFuera.length ||
  dobleVacio.length ||
  monoEnFrases.length
) {
  process.exitCode = 1;
}
console.log(
  [...rotas, ...crudas, ...letraFuera, ...dobleVacio, ...monoEnFrases]
    .map((r) => "  " + r)
    .join("\n"),
);
await navegador.close();
