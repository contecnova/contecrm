/**
 * Siete escalones de letra, y ninguno por debajo de 12 px.
 *
 * **Medido el 02-11-2026 en las 58 pantallas**: se usaban once tamaños —32,
 * 22, 20, 18, 16, 14, 12, 11, 10, 9,6 y 9 px—, con saltos de un píxel entre
 * 10, 11 y 12. Eso no es una escala: nadie puede decidir entre 10 y 11, así
 * que se elige al azar y cada pantalla sale de un tamaño distinto. Una
 * llegaba a usar nueve a la vez.
 *
 * Y lo peor no era el número: **el 77 % del texto estaba en 10 u 11 px** —508
 * usos de `text-3xs` y 458 de `text-2xs` de 1.257—, que no se lee cómodo en
 * un escritorio. Lightning no baja de 12 y su cuerpo es 13.
 *
 * Tres formas de escribir un tamaño, y las tres se vigilan, porque tapar una
 * sola deja las otras dos abiertas:
 *
 * 1. una clase de la escala  → sólo las siete
 * 2. una clase arbitraria `text-[13px]` → ninguna
 * 3. un número en un SVG o en un estilo → ninguno por debajo de 12,
 *    **y el que se esconde tras una constante**, que es por donde se escapó
 *    la primera versión de esta prueba
 *
 * El tamaño que se VE lo mide el barrido de pantallas, que es otra cosa: aquí
 * se mira lo que se escribe.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

/** Los siete escalones, con su papel. Si cambian, cambian aquí y en el tema. */
const ESCALA = [
  "rotulo", // 12 — rótulos, metadatos, lo secundario
  "dato", // 13 — el cuerpo
  "titulin", // 14 — encabezado pequeño
  "titulo", // 16 — encabezado de sección
  "grande", // 20 — encabezado de bloque
  "pagina", // 24 — el título de la pantalla
  "hero", // 32 — la cifra que se mira de lejos
];

/** El mínimo del sistema. Dos auditorías anteriores lo pusieron en 8,8 y en 10. */
const MINIMO_PX = 12;

const RAIZ = resolve(process.cwd(), "src");

function fuentes(): string[] {
  const salida: string[] = [];
  (function recorrer(dir: string) {
    for (const entrada of readdirSync(dir)) {
      const ruta = join(dir, entrada);
      if (statSync(ruta).isDirectory()) {
        if (entrada !== "pruebas") recorrer(ruta);
        continue;
      }
      if (/\.(ts|tsx|css)$/.test(entrada)) salida.push(ruta);
    }
  })(RAIZ);
  return salida;
}

/** Sin comentarios: cuentan la historia del arreglo y nombran lo prohibido. */
function sinComentarios(texto: string): string {
  return texto.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

describe("la escala tipográfica", () => {
  const revisados = fuentes();

  it("mira de verdad el árbol del front", () => {
    // Un recorrido que no recoge nada contesta «ninguno fuera» sin haber
    // mirado, que es el peor verde que hay.
    expect(revisados.length).toBeGreaterThan(80);
  });

  it("no usa ninguna clase de tamaño fuera de los siete escalones", () => {
    const fuera: string[] = [];
    for (const ruta of revisados) {
      const texto = sinComentarios(readFileSync(ruta, "utf-8"));
      for (const m of texto.matchAll(
        /(?<![\w-])text-([a-z0-9]+(?:-[a-z]+)?)(?![\w-])/g,
      )) {
        const nombre = m[1] ?? "";
        // `text-ink`, `text-accent`… son colores: los vigila `contraste.mjs`.
        if (
          !/^(3xs|2xs|xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl|7xl|8xl|9xl|md|sm-h|md-em|xl-em)$/.test(
            nombre,
          )
        ) {
          continue;
        }
        fuera.push(`${ruta.replace(RAIZ, "src")}: text-${nombre}`);
      }
    }
    expect(
      fuera,
      "tamaños de la escala vieja de Tailwind, que ya no existe en el tema:\n  " +
        fuera.join("\n  "),
    ).toEqual([]);
  });

  it("no inventa tamaños arbitrarios", () => {
    const fuera: string[] = [];
    for (const ruta of revisados) {
      const texto = sinComentarios(readFileSync(ruta, "utf-8"));
      for (const m of texto.matchAll(/(?<![\w-])text-\[[^\]]+\]/g)) {
        fuera.push(`${ruta.replace(RAIZ, "src")}: ${m[0]}`);
      }
    }
    expect(
      fuera,
      "un tamaño entre corchetes es un escalón nuevo que nadie decidió:\n  " +
        fuera.join("\n  "),
    ).toEqual([]);
  });

  it("no escribe ningún número de letra por debajo del mínimo", () => {
    // Lo que no puede llevar clase: un `<text>` de SVG y un estilo en línea.
    const fuera: string[] = [];
    for (const ruta of revisados) {
      const texto = sinComentarios(readFileSync(ruta, "utf-8"));
      for (const m of texto.matchAll(/fontSize[:=]\s*\{?\s*(\d+(?:\.\d+)?)/g)) {
        if (Number(m[1]) < MINIMO_PX)
          fuera.push(`${ruta.replace(RAIZ, "src")}: ${m[0].trim()}`);
      }
      // Y el número escondido tras una constante. Con `fontSize={LETRA}` la
      // regla de arriba no ve ningún número: **cazado plantando el caso malo**
      // —se bajó `LETRA_GRAFICA` a 9 y la prueba siguió verde—, que es
      // justamente el fallo que esta prueba existe para evitar.
      for (const m of texto.matchAll(
        /const\s+[A-Z_]*(?:LETRA|FUENTE|TEXTO)[A-Z_]*\s*=\s*(\d+(?:\.\d+)?)/g,
      )) {
        if (Number(m[1]) < MINIMO_PX)
          fuera.push(`${ruta.replace(RAIZ, "src")}: ${m[0].trim()}`);
      }
      for (const m of texto.matchAll(/font-size:\s*(\d+(?:\.\d+)?)px/g)) {
        if (Number(m[1]) < MINIMO_PX)
          fuera.push(`${ruta.replace(RAIZ, "src")}: ${m[0].trim()}`);
      }
      // Y en `rem`, que es como se escriben los tokens de la celda.
      for (const m of texto.matchAll(/font-size:\s*(\d*\.?\d+)rem/g)) {
        if (Number(m[1]) * 16 < MINIMO_PX)
          fuera.push(`${ruta.replace(RAIZ, "src")}: ${m[0].trim()}`);
      }
      for (const m of texto.matchAll(
        /--celda-texto[a-z-]*:\s*(\d*\.?\d+)rem/g,
      )) {
        if (Number(m[1]) * 16 < MINIMO_PX)
          fuera.push(`${ruta.replace(RAIZ, "src")}: ${m[0].trim()}`);
      }
    }
    expect(
      fuera,
      `letra por debajo de ${MINIMO_PX} px, que es el mínimo del sistema:\n  ` +
        fuera.join("\n  "),
    ).toEqual([]);
  });

  it("no inventa radios de esquina fuera de la escala", () => {
    // La misma idea que con la letra, y por el mismo motivo: Lightning tiene
    // **dos** radios —4 px para todo y 8 px para lo que flota— y esa falta de
    // escala ES el aspecto. Lo que no puede haber es un `rounded-[14px]`
    // suelto, que es un tercer radio que nadie decidió.
    //
    // Los NOMBRES de Tailwind sí valen: la escala se redefine en el tema, así
    // que `rounded-xl` escrito en cualquier pantalla mide lo que toca sin
    // tocarla. Un reemplazo se olvida de la pantalla que nadie abrió.
    const fuera: string[] = [];
    for (const ruta of revisados) {
      const texto = sinComentarios(readFileSync(ruta, "utf-8"));
      for (const m of texto.matchAll(
        /(?<![\w-])rounded(?:-[a-z]+)?-\[[^\]]+\]/g,
      )) {
        fuera.push(`${ruta.replace(RAIZ, "src")}: ${m[0]}`);
      }
      for (const m of texto.matchAll(/border-radius:\s*(\d+(?:\.\d+)?)px/g)) {
        const px = Number(m[1]);
        // La barra de desplazamiento del navegador no es una caja del
        // sistema: su pulgar lleva el radio que lo hace parecer un pulgar.
        if (
          /scrollbar/.test(texto.slice(Math.max(0, m.index - 220), m.index))
        ) {
          continue;
        }
        if (px !== 0 && px !== 4 && px !== 8 && px !== 9999) {
          fuera.push(`${ruta.replace(RAIZ, "src")}: ${m[0].trim()}`);
        }
      }
    }
    expect(
      fuera,
      "un radio entre corchetes es un escalón nuevo que nadie decidió:\n  " +
        fuera.join("\n  "),
    ).toEqual([]);
  });

  it("el tema declara exactamente esos siete y ningún otro", () => {
    const config = readFileSync(
      resolve(process.cwd(), "tailwind.config.js"),
      "utf-8",
    );
    const bloque = /fontSize:\s*\{([\s\S]*?)\n {4}\},/.exec(config);
    expect(bloque, "no se encuentra la escala en el tema").not.toBeNull();
    const declarados = [
      ...(bloque?.[1] ?? "").matchAll(/^\s{6}([a-z]+):/gm),
    ].map((m) => m[1] ?? "");
    expect(declarados.sort()).toEqual([...ESCALA].sort());
  });
});
