/**
 * El sistema de diseño es el de contecmind, y se comprueba contra el suyo.
 *
 * El catálogo dice (`CRM-07.04.01.02`) que el sistema de diseño es **idéntico**
 * al de contecmind. El 29-09-2026 se midió y no lo era: de los 30 tokens que
 * los dos productos comparten, 26 tenían valor distinto en claro y 25 en
 * oscuro; solo coincidían 6 nombres. El enunciado llevaba siendo falso desde
 * que alguien tocó un color, y nada lo detectaba.
 *
 * Esto lo detecta. Lee el `index.css` de contecmind —el de verdad, en su
 * repositorio— y compara. Si allí cambia un color, esto se pone rojo y hay que
 * decidir: seguirlo o cambiar el enunciado. Lo que no puede volver a pasar es
 * que se separen en silencio.
 *
 * Tres cosas que esta prueba hace a propósito:
 *
 * **Solo los tokens COMUNES.** Los 33 propios de contecrm —gráficas, portal,
 * medidas de página— se quedan como están: son un superconjunto, no una
 * divergencia. contecmind no tiene gráficas y no tiene por qué opinar.
 *
 * **Dice cuántos ha comparado.** Una comprobación que no encuentra el fichero,
 * o que lo lee mal y saca cero tokens, pasaría en verde diciendo «ninguna
 * diferencia». Aquí se exige un suelo, medido: 58 pares comunes.
 *
 * **Y el contraste NO se mide aquí.** Ya lo hace `scripts/contraste.mjs`, que
 * corre en el mismo `npm run verificar`; al repintar se le añadieron `--ink` y
 * `--ink-muted`, que llevan la mayor parte del texto de la aplicación y no
 * estaban. Dos guardianes de la misma regla se separan, y el que se queda
 * atrás es el que engaña.
 *
 * Que hacía falta mirarlo lo demostró este cambio: la superficie
 * `--paper-lighter` de contecmind es más clara que la que había, y dejó
 * `--coral-text` en 4.13:1 y `--chart-pink-text` en 4.14:1. Los dos son tokens
 * propios de contecrm —gráficas, que contecmind no tiene— así que seguirle no
 * los arregla: hubo que aclararlos.
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// Con `new URL(..., import.meta.url).pathname` salía `/src/index.css`: bajo
// vitest la URL del módulo no es la del fichero en disco. Se resuelve como en
// `accesibilidad.test.ts`, que ya funcionaba.
const AQUI = join(dirname(fileURLToPath(import.meta.url)), "..", "index.css");
// El repositorio vecino. Se lee, nunca se escribe: una sesión, un repositorio.
const CONTECMIND = "/Users/oriolvallsanton/Code/contecmind/frontend/src/index.css";

// Medido el 29-09-2026: 58 pares (bloque, token) comunes a los dos ficheros.
// No es el número exacto para siempre —puede crecer— pero un suelo impide que
// una lectura rota devuelva cero y parezca que no hay diferencias.
const SUELO_DE_COMUNES = 50;

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

/** Tripleta `R G B`, o `null` si el valor es otra cosa (`rgb(var(--x))`, `rem`). */
function rgb(valor: string | undefined): [number, number, number] | null {
  if (!valor) return null;
  const partes = valor.split(" ");
  if (partes.length !== 3) return null;
  const [r, g, b] = partes.map((p) => Number(p));
  if (r === undefined || g === undefined || b === undefined) return null;
  if ([r, g, b].some((n) => !Number.isInteger(n) || n < 0 || n > 255)) return null;
  return [r, g, b];
}





describe("sistema de diseño (CRM-07.04.01.02)", () => {
  it("los tokens comunes valen lo mismo que en contecmind", () => {
    if (!existsSync(CONTECMIND)) {
      // Se dice en voz alta en vez de pasar en verde: sin el vecino delante,
      // esta comprobación no ha comprobado nada.
      throw new Error(
        `No está el index.css de contecmind en ${CONTECMIND}. Sin él esta ` +
          "prueba no compara nada, y pasar en verde sería mentir. Clona el " +
          "repositorio vecino o ajusta la ruta.",
      );
    }
    const aqui = leerTokens(AQUI);
    const alli = leerTokens(CONTECMIND);

    const comunes: string[] = [];
    const distintos: string[] = [];
    for (const [clave, valor] of aqui) {
      const suyo = alli.get(clave);
      if (suyo === undefined) continue;
      if (rgb(valor) === null || rgb(suyo) === null) continue;
      comunes.push(clave);
      if (valor !== suyo) distintos.push(`${clave}: aquí ${valor} · contecmind ${suyo}`);
    }

    expect(
      comunes.length,
      `solo se han comparado ${comunes.length} tokens comunes, menos del suelo ` +
        `de ${SUELO_DE_COMUNES}. La lectura se ha quedado corta y su resultado ` +
        "no significa nada.",
    ).toBeGreaterThanOrEqual(SUELO_DE_COMUNES);

    expect(
      distintos,
      `${distintos.length} de ${comunes.length} tokens comunes se han separado ` +
        "de contecmind. El catálogo dice que el sistema de diseño es idéntico " +
        "al suyo: o se sigue el cambio, o se cambia el enunciado y el manual a " +
        "la vez.\n  " + distintos.join("\n  "),
    ).toEqual([]);
  });

});
