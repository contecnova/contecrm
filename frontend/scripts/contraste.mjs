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
 *
 * Y mide además lo que va ENCIMA de un relleno y el anillo de foco, que es lo
 * que se le escapaba. Medido el 13-11-2026: el blanco del botón primario daba
 * 3,56:1 sobre el acento de oscuro (2,68:1 en su hover) y el anillo de foco,
 * `ring-accent/40`, entre 1,64 y 1,82:1 contra las superficies. Los dos pasaban
 * este gate porque no eran `-text`. Ahora son tokens —`--on-accent` y
 * `--focus-ring`— y aquí se miden; y como un token medido no sirve si el código
 * no lo usa, se busca también la tinta escrita a mano sobre el acento y se
 * comprueba la regla del foco.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const MINIMO = 4.5;
// Lo que pide WCAG 1.4.11 a un componente o a un indicador de foco.
const MINIMO_NO_TEXTO = 3;
// El anillo se pinta sobre cualquiera de las cinco, y la peor para un azul no
// es la misma en los dos temas: se miden todas.
const SUPERFICIES = ["paper", "paper-dark", "paper-light", "paper-lighter", "paper-sunk"];
// Otro CSS en lugar del de verdad, para comprobar que el gate falla con
// valores malos sin tocar `src/index.css`: `node scripts/contraste.mjs otro.css`.
const RUTA_CSS = process.argv[2] ?? "src/index.css";
const css = readFileSync(RUTA_CSS, "utf8");

function bloque(selector) {
  const i = css.indexOf(selector);
  if (i < 0) throw new Error(`No encuentro el bloque \`${selector}\` en ${RUTA_CSS}`);
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
    // Los `-text` y, ADEMÁS, los dos que llevan texto sin llamarse así.
    //
    // `textColor.ink.DEFAULT` resuelve a `--ink` y `textColor.ink.muted` a
    // `--ink-muted` en `tailwind.config.js`: son los colores del cuerpo y de
    // las etiquetas, o sea la mayor parte del texto de la aplicación, y este
    // gate no los miraba. Se descubrió al repintar la paleta a la de
    // contecmind, cuando hizo falta medir los dos temas enteros.
    //
    // `--ink-faint` NO entra: `textColor.ink.faint` resuelve a
    // `--ink-faint-text`, así que la clase `text-ink-faint` —143 usos medidos—
    // usa la variante accesible, y `--ink-faint` queda de relleno para bordes.
    if (!nombre.endsWith("-text") && nombre !== "ink" && nombre !== "ink-muted") continue;
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
  // texto ilegible en producción. `on-` y `focus-` no son rellenos —son la
  // tinta que va encima de uno y el anillo de foco— y se miden abajo.
  for (const nombre of tokens.keys()) {
    if (/-text$/.test(nombre) || /^(paper|ink|viz|shadow|page|panel|barra|portal|on-|focus-)/.test(nombre)) continue;
    if (!tokens.has(`${nombre}-text`)) {
      fallos.push(`  ${tema}: --${nombre} es un relleno sin su variante --${nombre}-text`);
    }
  }

  // La tinta sobre el acento, contra el relleno y contra su hover: el botón
  // primario pasa por los dos, y en oscuro el hover ACLARA, así que una tinta
  // clara que llegara en reposo podría no llegar al pasar por encima.
  const tinta = tokens.get("on-accent");
  if (!tinta) {
    fallos.push(`  ${tema}: falta --on-accent, la tinta que va sobre el acento`);
  } else {
    for (const relleno of ["accent", "accent-soft"]) {
      const valor = tokens.get(relleno);
      if (!valor) continue;
      medidos += 1;
      const r = razon(tinta, valor);
      if (r < MINIMO) {
        fallos.push(
          `  ${tema}: --on-accent (${hex(tinta)}) da ${r.toFixed(2)}:1 sobre ` +
            `--${relleno} (${hex(valor)}), y el mínimo es ${MINIMO}:1`,
        );
      }
    }
  }

  const anillo = tokens.get("focus-ring");
  if (!anillo) {
    fallos.push(`  ${tema}: falta --focus-ring, el color del anillo de foco`);
  } else {
    for (const superficie of SUPERFICIES) {
      const valor = tokens.get(superficie);
      if (!valor) continue;
      medidos += 1;
      const r = razon(anillo, valor);
      if (r < MINIMO_NO_TEXTO) {
        fallos.push(
          `  ${tema}: --focus-ring (${hex(anillo)}) da ${r.toFixed(2)}:1 contra ` +
            `--${superficie} (${hex(valor)}), y el mínimo es ${MINIMO_NO_TEXTO}:1`,
        );
      }
    }
  }
}

// ── Que el código use los tokens medidos ─────────────────────────────────
//
// El anillo se pinta en una sola regla, `*:focus-visible`. Con transparencia
// el color que se ve es la mezcla con la superficie, no el token, y la medida
// de arriba deja de valer: `ring-accent/40` era exactamente eso.
const sinComentarios = (texto) => texto.replace(/\/\*[\s\S]*?\*\//g, "");
const foco = /\*:focus-visible\s*\{([^}]*)\}/.exec(sinComentarios(css));
if (!foco) {
  fallos.push(`  falta la regla \`*:focus-visible\` en ${RUTA_CSS}`);
} else if (!/(^|\s)ring-focus(?![\w/-])/.test(foco[1])) {
  fallos.push(
    "  `*:focus-visible` no pinta el anillo con `ring-focus` opaco: " +
      foco[1].replace(/\s+/g, " ").trim(),
  );
}

// Tinta escrita a mano sobre el relleno de acento. `text-white`, o un papel
// usado como tinta, dan un color fijo en un tema y otro en el otro, y así es
// como el botón primario se quedó en 3,56:1. Se mira por línea en el código y
// por bloque en el CSS, donde un `@apply` se reparte en varias líneas. Sólo el
// relleno opaco: `bg-accent/10` es un tinte, y lo que va encima es
// `text-accent`, que ya mide el gate de los `-text`.
const RELLENO = /(?:^|[\s"'`:])bg-accent(?:-soft)?(?![\w/-])/;
const A_MANO = /(?:^|[\s"'`:])text-(?:white|black|paper[\w-]*)(?![\w/-])/;
const trozosDe = (ruta, texto) =>
  ruta.endsWith(".css")
    ? sinComentarios(texto).split("}")
    : texto.split("\n").map((linea) => linea.replace(/\/\/.*$/, ""));
const indice = join("src", "index.css");
for (const fichero of readdirSync("src", { recursive: true })) {
  const ruta = join("src", String(fichero));
  if (!/\.(tsx?|css)$/.test(ruta) || /\.test\.tsx?$/.test(ruta)) continue;
  // Si se mide otro CSS, ése ocupa el lugar de `index.css`.
  const texto = ruta === indice ? css : readFileSync(ruta, "utf8");
  for (const trozo of trozosDe(ruta, texto)) {
    if (RELLENO.test(trozo) && A_MANO.test(trozo)) {
      fallos.push(
        `  ${ruta}: tinta a mano sobre el acento (usa \`text-on-accent\`): ` +
          trozo.replace(/\s+/g, " ").trim().slice(0, 140),
      );
    }
  }
}

if (fallos.length > 0) {
  console.error("\nContraste por debajo del mínimo, o tokens medidos que el código no usa:\n");
  console.error(fallos.join("\n"));
  console.error(
    "\nEl token base es el RELLENO; la variante `-text` es el mismo tono movido\n" +
      "en luminosidad hasta pasar el mínimo, y `--on-accent` la tinta que va\n" +
      "encima. No se baja el mínimo.\n",
  );
  process.exit(1);
}
console.log(
  `contraste: ${medidos} pares en los dos temas —texto y tinta sobre acento ≥ ${MINIMO}:1, ` +
    `anillo de foco ≥ ${MINIMO_NO_TEXTO}:1— y ninguna tinta a mano sobre el acento`,
);
