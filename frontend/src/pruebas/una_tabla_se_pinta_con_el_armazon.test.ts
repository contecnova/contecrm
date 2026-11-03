/**
 * Una tabla se pinta con el armazón de la casa, no a mano.
 *
 * `Rejilla` es el recuadro, la cabecera y el cuerpo de una tabla en un sitio.
 * Existe porque estaba copiado **cinco veces** y ya había empezado a
 * separarse: dos copias usaban un tamaño de letra y dos otro, y las celdas
 * tenían tonos distintos sin que nadie lo hubiera decidido.
 *
 * **Volvió a pasar.** Medido el 03-11-2026, quedaban tres `<table>` escritas
 * a mano fuera del armazón, con **tres tamaños distintos para lo mismo**: la
 * tabla de resultados analíticos en `text-dato`, las líneas de un formulario
 * en `text-titulo` y la de un listado con el token de densidad —que es el
 * único que responde al modo cómodo—. Y las tres con la cabecera en texto
 * normal, no en las versalitas de Lightning.
 *
 * Las líneas de un formulario no cabían en el armazón porque llevan un pie
 * con las sumas, así que `Rejilla` tiene pie: una tabla con totales es un
 * caso común, y sin él cada sitio que lo necesite se vuelve a escribir entero.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const RAIZ = resolve(process.cwd(), "src");

/**
 * Dónde sí vale escribir `<table>`, con su motivo.
 *
 * Es una lista de excepciones y no de permitidos: así, una tabla nueva entra
 * vigilada y no al revés.
 */
const A_MANO_A_PROPOSITO: Record<string, string> = {
  "componentes/Rejilla.tsx": "es el armazón: aquí vive la única `<table>` del producto",
};

function fuentes(): string[] {
  const salida: string[] = [];
  for (const carpeta of ["paginas", "componentes"]) {
    (function recorrer(dir: string) {
      for (const entrada of readdirSync(dir)) {
        const ruta = join(dir, entrada);
        if (statSync(ruta).isDirectory()) {
          recorrer(ruta);
          continue;
        }
        if (/\.tsx$/.test(entrada)) salida.push(ruta);
      }
    })(join(RAIZ, carpeta));
  }
  return salida;
}

describe("una tabla", () => {
  const revisadas = fuentes();

  it("se han leído las pantallas y los componentes", () => {
    // Sin esto, «ninguna a mano» sería el resultado de no haber mirado.
    expect(revisadas.length).toBeGreaterThan(60);
  });

  it("se pinta con el armazón y no escribiendo `<table>`", () => {
    const aMano: string[] = [];
    for (const ruta of revisadas) {
      const relativa = ruta.replace(`${RAIZ}/`, "");
      if (relativa in A_MANO_A_PROPOSITO) continue;
      const texto = readFileSync(ruta, "utf-8")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/^\s*\/\/.*$/gm, "");
      if (/<table\b/.test(texto)) aMano.push(relativa);
    }
    expect(
      aMano,
      "tablas escritas a mano: se separan del resto en cuanto alguien toca " +
        "una, y ya pasó con tres tamaños de letra distintos:\n  " +
        aMano.join("\n  "),
    ).toEqual([]);
  });
});
