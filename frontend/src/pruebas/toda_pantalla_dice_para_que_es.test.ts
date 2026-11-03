/**
 * Toda pantalla con cabecera dice para qué es.
 *
 * La cabecera tiene dos partes: el **título**, que la nombra, y la
 * **entradilla**, que dice qué pregunta contesta. Sin la segunda hay que
 * deducirlo del contenido — que es justo lo que no se puede hacer cuando la
 * pantalla está vacía, que es cuando más falta hace.
 *
 * **Medido el 03-11-2026**: de 36 pantallas con cabecera, dos no la tenían
 * —«Cuadros de mando» y «Estado del servicio»—. Dos de 36 no parece mucho, y
 * son las dos que alguien abre sin saber qué va a encontrar.
 *
 * La excepción legítima está declarada abajo con su motivo: una cabecera que
 * acompaña a un estado vacío, donde el propio vacío explica qué pasa y
 * repetirlo arriba sería decirlo dos veces.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const PAGINAS = resolve(process.cwd(), "src", "paginas");

/**
 * Cabeceras que no llevan entradilla a propósito.
 *
 * El `Pipeline` pinta una cabecera escueta cuando NO hay ningún pipeline
 * configurado, y debajo un vacío con su explicación y su botón. Ahí la
 * entradilla sobraría: diría lo mismo dos veces, una encima de la otra.
 */
const SIN_ENTRADILLA_A_PROPOSITO: Record<string, string> = {
  "Pipeline.tsx": "la cabecera del caso «no hay ningún pipeline», que ya lo explica el vacío de debajo",
};

/** Cada `<CabeceraPagina …/>` entero, contando llaves para no cortarlo. */
function cabeceras(fuente: string): string[] {
  const salida: string[] = [];
  for (const m of fuente.matchAll(/<CabeceraPagina\b/g)) {
    let nivel = 0;
    let j = m.index + "<CabeceraPagina".length;
    while (j < fuente.length) {
      const c = fuente[j];
      if (c === "{") nivel += 1;
      else if (c === "}") nivel -= 1;
      else if (nivel === 0 && fuente.startsWith("/>", j)) {
        salida.push(fuente.slice(m.index, j + 2));
        break;
      }
      j += 1;
    }
  }
  return salida;
}

describe("toda pantalla", () => {
  const ficheros = readdirSync(PAGINAS).filter((n) => n.endsWith(".tsx"));

  it("se han leído las pantallas", () => {
    // Sin esto, «ninguna sin entradilla» sería el resultado de no mirar.
    expect(ficheros.length).toBeGreaterThan(30);
  });

  it("dice para qué es, y no sólo cómo se llama", () => {
    const mudas: string[] = [];
    let miradas = 0;
    for (const nombre of ficheros) {
      const fuente = readFileSync(join(PAGINAS, nombre), "utf-8");
      const todas = cabeceras(fuente);
      if (todas.length === 0) continue;
      miradas += 1;
      const conEntradilla = todas.filter((c) => c.includes("entradilla")).length;
      if (conEntradilla === todas.length) continue;
      if (nombre in SIN_ENTRADILLA_A_PROPOSITO && conEntradilla > 0) continue;
      mudas.push(`${nombre}: ${todas.length - conEntradilla} cabecera(s) sin entradilla`);
    }
    expect(miradas, "no se ha mirado ninguna cabecera").toBeGreaterThan(25);
    expect(
      mudas,
      "una pantalla que no dice para qué es obliga a deducirlo del " +
        "contenido, y eso no se puede cuando está vacía:\n  " + mudas.join("\n  "),
    ).toEqual([]);
  });
});
