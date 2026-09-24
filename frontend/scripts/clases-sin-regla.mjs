/**
 * Gate: ninguna clase de color escrita en el front puede quedarse sin regla.
 *
 * Tailwind solo emite las utilidades que encuentra en el código Y que existen
 * en su configuración. Una clase que NO existe —`bg-paper-sunk` cuando el token
 * se llama `paper-light`, o `text-danger-text` cuando la escala `textColor` ya
 * añade el sufijo— no da error en ningún sitio: se escribe, pasa el `tsc`, pasa
 * el `eslint`, construye, y el elemento sale sin fondo o sin color. Nadie se
 * entera hasta que alguien abre esa pantalla y ve una caja transparente.
 *
 * Así aparecieron 21 usos repartidos en seis ficheros: quince de `bg-paper-sunk`
 * —cabeceras de tabla, burbujas del chat, carriles de progreso, el portal
 * entero—, dieciocho de `border-line` y seis de `text-*-text`.
 *
 * El gate compara lo escrito contra el CSS construido. Necesita `dist`, así que
 * corre DESPUÉS de `vite build`.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const DIST = "dist/assets";
const FAMILIAS = "bg|text|border|ring|fill|stroke|shadow|divide|placeholder|outline|decoration";

function ficherosTsx(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? ficherosTsx(join(dir, e.name)) : e.name.endsWith(".tsx") || e.name.endsWith(".ts") ? [join(dir, e.name)] : [],
  );
}

const css = readdirSync(DIST)
  .filter((f) => f.endsWith(".css"))
  .map((f) => readFileSync(join(DIST, f), "utf8"))
  .join("\n");
if (!css) {
  console.error("No hay CSS construido en " + DIST + ": este gate va después de `vite build`.");
  process.exit(1);
}

// Dentro de un `className`, no en cualquier cadena: `transition: "border-color
// 0.15s"` es una propiedad CSS, no una utilidad, y sin esta restricción el gate
// la denunciaría.
const escritas = new Map();
const utilidad = new RegExp(`(?<![\\w-])((?:${FAMILIAS})-[a-z][a-z0-9-]*)(?:/\\d+)?(?![\\w-])`, "g");
for (const f of ficherosTsx("src")) {
  for (const linea of readFileSync(f, "utf8").split("\n")) {
    if (!/class[nN]ame|\bcn\(|"(?:[a-z-]+ )+[a-z-]+"/.test(linea)) continue;
    for (const m of linea.matchAll(utilidad)) {
      if (!escritas.has(m[1])) escritas.set(m[1], new Set());
      escritas.get(m[1]).add(f);
    }
  }
}

const sinRegla = [...escritas].filter(([u]) => {
  // La utilidad aparece como selector: `.bg-x{…}` sin variante, o
  // `.hover\:bg-x:hover{…}` con ella.
  const escapada = u.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return !new RegExp(`[.\\\\:]${escapada}(\\\\/\\d+)?(?![\\w-])`).test(css);
});

if (sinRegla.length > 0) {
  console.error("\nClases de color sin regla en el CSS construido:\n");
  for (const [u, fs] of sinRegla) console.error(`  ${u}\n      ${[...fs].join("\n      ")}`);
  console.error(
    "\nO el token no existe en `tailwind.config.js`, o el nombre está mal escrito.\n" +
      "Estos elementos se están pintando SIN color.\n",
  );
  process.exit(1);
}
console.log(`clases de color: ${escritas.size} distintas, todas con regla`);
