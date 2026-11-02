/**
 * Ninguna pantalla escribe su propio color.
 *
 * El sistema de diseño está en los tokens: `bg-paper`, `text-ink`,
 * `border-ink-dim`, `text-accent`. Una pantalla que escribe `#0d1220` deja de
 * responder al tema, se queda fuera del gate de contraste —que comprueba los
 * tokens en claro y en oscuro— y se separa del resto en cuanto la paleta
 * cambia, sin que nadie lo decida.
 *
 * **Medido el 02-11-2026**: la pantalla de entrada tenía **12 colores propios,
 * 18 bloques de estilo en línea, 13 tamaños de letra y tres radios** —10, 12 y
 * 20 contra los 4 del sistema—, copiados a mano de contecflow. Su propio
 * comentario lo decía —«hoy el CRM se ve como contecmind y su puerta como
 * contecflow»— y dejaba la decisión pendiente. Era la primera pantalla que ve
 * cualquiera, era oscura siempre aunque el tema fuera claro, y ningún gate la
 * miraba porque ninguno mira colores que no son tokens.
 *
 * La regla se pone **ahora que está en cero**, que es cuando se puede poner
 * sin excepciones. Los sitios donde un color literal sí tiene sentido quedan
 * fuera del recorrido a propósito y con su motivo:
 *
 * - `lib/navegacion.ts` — el color de cada objeto, que en Lightning es parte
 *   del producto: una cuenta es malva y un candidato naranja.
 * - `embebido/` — el widget que se inyecta en una página de otro, donde los
 *   tokens de esta aplicación no existen.
 *
 * Un color CALCULADO sí vale: `style={{ background: s.color }}` pinta la serie
 * de una gráfica con la paleta categórica, y eso es un dato, no una decisión
 * de estilo escrita a mano.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const RAIZ = resolve(process.cwd(), "src");
/** Donde vive lo que se ve. El resto tiene sus motivos, arriba. */
const MIRADOS = ["paginas", "componentes"];

function fuentes(): string[] {
  const salida: string[] = [];
  for (const carpeta of MIRADOS) {
    (function recorrer(dir: string) {
      for (const entrada of readdirSync(dir)) {
        const ruta = join(dir, entrada);
        if (statSync(ruta).isDirectory()) {
          recorrer(ruta);
          continue;
        }
        if (/\.(ts|tsx)$/.test(entrada)) salida.push(ruta);
      }
    })(join(RAIZ, carpeta));
  }
  return salida;
}

/** Sin comentarios: cuentan la historia del arreglo y nombran lo prohibido. */
function sinComentarios(texto: string): string {
  return texto.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

describe("una pantalla", () => {
  const revisadas = fuentes();

  it("mira de verdad las pantallas y los componentes", () => {
    // Un recorrido que no recoge nada contesta «ninguna» sin haber mirado.
    expect(revisadas.length).toBeGreaterThan(60);
  });

  it("no escribe ningún color en hexadecimal", () => {
    const fuera: string[] = [];
    for (const ruta of revisadas) {
      const texto = sinComentarios(readFileSync(ruta, "utf-8"));
      for (const m of texto.matchAll(/#[0-9a-fA-F]{3,8}\b/g)) {
        fuera.push(`${ruta.replace(RAIZ, "src")}: ${m[0]}`);
      }
    }
    expect(
      fuera,
      "un color escrito a mano no responde al tema y no lo mira el gate de " +
        "contraste:\n  " + fuera.join("\n  "),
    ).toEqual([]);
  });

  it("no escribe ningún color literal en rgb o hsl", () => {
    const fuera: string[] = [];
    for (const ruta of revisadas) {
      const texto = sinComentarios(readFileSync(ruta, "utf-8"));
      // `rgb(var(--algo))` SÍ vale: es el token. Lo que no vale es el número.
      for (const m of texto.matchAll(/\b(rgba?|hsla?)\(\s*[\d.]/g)) {
        fuera.push(`${ruta.replace(RAIZ, "src")}: ${m[0]}…`);
      }
    }
    expect(
      fuera,
      "lo mismo que el hexadecimal, con otra sintaxis:\n  " + fuera.join("\n  "),
    ).toEqual([]);
  });
});
