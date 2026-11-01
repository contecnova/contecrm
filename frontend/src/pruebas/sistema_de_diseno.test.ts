/**
 * El sistema de diseño es el de Salesforce Lightning, y no se separa de él en
 * silencio.
 *
 * **Hasta el 01-11-2026 era el de contecmind**, y esta prueba lo comparaba
 * contra su `index.css` de verdad. Funcionó: el 29-09 destapó que de los 30
 * tokens comunes, 26 valían distinto. Lo que no podía detectar es que el
 * sistema entero fuera el equivocado — los valores de contecmind son los de
 * Google Workspace, y eso es lo que hacía que el producto se viera como una
 * consola de administración y no como un CRM.
 *
 * El encargo fue literal: «lo que te he pedido es que copies el diseño de
 * Salesforce». Así que ahora los valores son los de Lightning, el enunciado
 * del catálogo lo dice (`CRM-07.04.01.02`) y lo que se vigila aquí es **que
 * sigan siendo los suyos**.
 *
 * Contra una tabla y no contra el fichero del vecino, porque el vecino ya no
 * es la fuente: Lightning se publica como sistema, no vive en este disco. La
 * tabla lleva los valores que de verdad definen el aspecto —no los 58 tokens—
 * y cada uno dice para qué es, de modo que cambiarlo obligue a decir qué deja
 * de parecerse.
 *
 * **El contraste NO se mide aquí.** Lo hace `scripts/contraste.mjs`, que corre
 * en el mismo `npm run verificar` y mide los 40 tokens de texto en los dos
 * temas contra la superficie más desfavorable. Dos guardianes de la misma
 * regla se separan, y el que se queda atrás es el que engaña. Al repintar
 * encontró cuatro que no llegaban —`--accent-text`, `--accent-glow-text`,
 * `--success-text` y `--ink-faint-text`— y se bajaron hasta pasar.
 *
 * **Lo que queda pendiente, dicho:** el tema OSCURO sigue siendo el de
 * contecmind. Lightning no publica uno, así que hacerlo es diseñarlo, no
 * copiarlo. Y la pantalla de entrada sigue siendo la de contecflow.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// Con `new URL(..., import.meta.url).pathname` salía `/src/index.css`: bajo
// vitest la URL del módulo no es la del fichero en disco. Se resuelve como en
// `accesibilidad.test.ts`, que ya funcionaba.
const AQUI = join(dirname(fileURLToPath(import.meta.url)), "..", "index.css");

/**
 * Los valores que definen el aspecto, y para qué es cada uno.
 *
 * Son los de Salesforce Lightning Design System. Están aquí y no sólo en el
 * CSS para que cambiarlos tenga que ser deliberado: el CSS se edita sin
 * pensar, una tabla que dice «esto es de Salesforce» no.
 */
const LIGHTNING: Array<[string, string, string]> = [
  [":root|--paper", "255 255 255", "paneles y tarjetas"],
  [":root|--paper-dark", "243 243 243", "el lienzo, #f3f3f3"],
  [":root|--ink", "24 24 24", "el cuerpo del texto, #181818"],
  [":root|--ink-muted", "68 68 68", "etiquetas y apoyo, #444444"],
  [":root|--ink-dim", "201 201 201", "bordes y separadores, #c9c9c9"],
  [":root|--accent", "1 118 211", "el azul de la marca, #0176d3"],
  [":root|--accent-soft", "1 68 134", "su hover, #014486"],
  [":root|--success", "46 132 74", "#2e844a"],
  [":root|--warning", "254 147 57", "#fe9339"],
  [":root|--danger", "234 0 30", "#ea001e"],
];

type Tokens = Map<string, string>;

/** `bloque|token` -> `R G B`, tal como está escrito. */
function leerTokens(ruta: string): Tokens {
  const salida: Tokens = new Map();
  let bloque = "?";
  for (const linea of readFileSync(ruta, "utf8").split("\n")) {
    const cabecera = /^\s*([.:][\w\-[\]='"]+.*?)\s*\{/.exec(linea);
    if (cabecera?.[1]) {
      bloque = cabecera[1].trim();
      continue;
    }
    const decl = /(--[\w-]+)\s*:\s*([^;]+);/.exec(linea);
    if (decl?.[1] && decl[2]) {
      salida.set(`${bloque}|${decl[1]}`, decl[2].trim().replace(/\s+/g, " "));
    }
  }
  return salida;
}

describe("sistema de diseño (CRM-07.04.01.02)", () => {
  it("los tokens que definen el aspecto son los de Salesforce Lightning", () => {
    const aqui = leerTokens(AQUI);
    const distintos: string[] = [];
    for (const [clave, esperado, porque] of LIGHTNING) {
      const valor = aqui.get(clave);
      if (valor !== esperado) {
        distintos.push(`${clave} (${porque}): aquí «${valor ?? "no está"}», Lightning «${esperado}»`);
      }
    }
    expect(
      distintos,
      `${distintos.length} de ${LIGHTNING.length} tokens se han separado de Lightning. ` +
        "El catálogo dice que el sistema de diseño es el suyo: o se vuelve al " +
        "valor, o se cambia el enunciado y el manual a la vez.\n  " +
        distintos.join("\n  "),
    ).toEqual([]);
  });

  it("y el radio es el suyo: 4 px para todo, 8 px para lo que flota", () => {
    // Lightning casi no tiene escala, y esa falta de escala ES el aspecto:
    // cajas rectas, nada con forma de pastilla. Con la escala de Material
    // —8/12/16/24— el mismo marcado se veía redondeado.
    const config = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "..", "tailwind.config.js"), "utf8");
    const radios = /borderRadius:\s*\{([\s\S]*?)\n {6}\}/.exec(config)?.[1] ?? "";
    expect(radios, "no se ha podido leer la escala de radios").not.toBe("");
    expect(radios).toMatch(/DEFAULT:\s*"0\.25rem"/);
    expect(radios).toMatch(/lg:\s*"0\.25rem"/);
    expect(radios).toMatch(/xl:\s*"0\.5rem"/);
  });
});
