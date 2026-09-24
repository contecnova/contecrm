/**
 * Gate: todo token `*-text` llega a 4.5:1 contra la peor superficie de su tema.
 *
 * El sistema separa RELLENO y TEXTO en dos tokens porque WCAG 2 les pide cosas
 * distintas y opuestas: como texto, el color va contra la superficie y necesita
 * 4.5:1 (1.4.3); como relleno, lo que necesita 4.5:1 es la tinta que va encima,
 * y él solo 3:1 (1.4.11). El amarillo lo deja claro — #f9ab00 sobre blanco da
 * 1.93:1 como texto y es un relleno perfectamente bueno.
 *
 * Esa separación se sostenía a mano: cada vez que alguien tocaba un color había
 * que acordarse de medir. `index.css` llevaba meses diciendo que esto lo volvía
 * a comprobar `e2e/a11y-contraste.spec.ts`, y ese fichero NO EXISTE. Un
 * comentario que promete una comprobación que no está es peor que no decir
 * nada: quien lo lee deja de mirar.
 *
 * Se mide contra `paper-lighter`, la superficie más clara en oscuro y la más
 * oscura en claro, o sea el peor caso de las cinco: las superficies se anidan
 * —un modal sobre una tarjeta sobre la página— y nada en el código impide
 * ninguna combinación.
 */
import { readFileSync } from "node:fs";

const MINIMO = 4.5;
const css = readFileSync("src/index.css", "utf8");

function bloque(selector) {
  const i = css.indexOf(selector);
  if (i < 0) throw new Error(`No encuentro el bloque \`${selector}\` en src/index.css`);
  const fin = css.indexOf("\n}", i);
  const tokens = new Map();
  for (const m of css.slice(i, fin).matchAll(/--([a-z0-9-]+):\s*(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})\s*;/g)) {
    tokens.set(m[1], [Number(m[2]), Number(m[3]), Number(m[4])]);
  }
  return tokens;
}

const canal = (v) => (v / 255 <= 0.03928 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
const luz = ([r, g, b]) => 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b);
const razon = (a, b) => {
  const [hi, lo] = [luz(a), luz(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
const hex = ([r, g, b]) => "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");

const fallos = [];
let medidos = 0;
for (const [tema, selector] of [["claro", ":root {"], ["oscuro", ".dark {"]]) {
  const tokens = bloque(selector);
  const peor = tokens.get("paper-lighter");
  if (!peor) throw new Error(`El tema ${tema} no declara \`--paper-lighter\``);
  for (const [nombre, valor] of tokens) {
    if (!nombre.endsWith("-text")) continue;
    medidos += 1;
    const r = razon(valor, peor);
    if (r < MINIMO) {
      fallos.push(
        `  ${tema}: --${nombre} (${hex(valor)}) da ${r.toFixed(2)}:1 sobre ` +
          `paper-lighter (${hex(peor)}), y el mínimo es ${MINIMO}:1`,
      );
    }
  }
  // Un `-text` por cada relleno: si alguien añade una familia y se olvida de la
  // variante, `text-<familia>` cae al relleno y nadie lo nota hasta que hay un
  // texto ilegible en producción.
  for (const nombre of tokens.keys()) {
    if (/-text$/.test(nombre) || /^(paper|ink|viz|shadow|page|panel|barra|portal)/.test(nombre)) continue;
    if (!tokens.has(`${nombre}-text`)) {
      fallos.push(`  ${tema}: --${nombre} es un relleno sin su variante --${nombre}-text`);
    }
  }
}

if (fallos.length > 0) {
  console.error("\nTokens de texto que no llegan al contraste mínimo:\n");
  console.error(fallos.join("\n"));
  console.error(
    "\nEl token base es el RELLENO; la variante `-text` es el mismo tono movido\n" +
      "en luminosidad hasta pasar el mínimo. No se baja el mínimo.\n",
  );
  process.exit(1);
}
console.log(`contraste: ${medidos} tokens de texto, todos ≥ ${MINIMO}:1`);
