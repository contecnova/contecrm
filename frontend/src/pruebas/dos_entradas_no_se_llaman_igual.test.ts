/**
 * Dos entradas del menú no pueden llamarse casi igual.
 *
 * **Medido el 03-11-2026** en el menú de Administrar, que tiene veinte
 * entradas:
 *
 * - **«Entornos y despliegue»** y **«Entornos y despliegues»**. Una en
 *   singular y otra en plural, una al lado de la otra. La primera lleva a
 *   llevarse configuración de un entorno a otro; la segunda, a ver qué hay
 *   desplegado en cada uno. Nadie puede saber cuál es cuál sin entrar en las
 *   dos.
 * - **«Usuarios y permisos»** y **«Usuarios y seguridad»**. La primera es el
 *   listado de usuarios y sus licencias; la segunda, el gobierno de la
 *   identidad —segundo factor, SSO, segregación—.
 *
 * Es la queja que abrió el rediseño: «mil opciones que muchas son inútiles».
 * No lo eran: eran pantallas distintas con nombres que se pisaban.
 *
 * **Por qué esta regla y no «la pantalla se llama como su entrada»**, que era
 * lo primero que se intentó: ésa no se puede escribir sin equivocarse. El
 * menú abrevia a propósito —«Coste» lleva a «Coste y capacidad»— y eso está
 * bien; y «Procesos en curso» llevando al «Editor de procesos» comparte la
 * palabra «procesos» y aun así dice lo contrario. Ninguna regla mecánica
 * separa las dos cosas. Ésta sí es objetiva: compara los rótulos entre ellos.
 */

import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const RAIZ = resolve(process.cwd(), "src");

/** Los textos por su clave ENTERA: `pipeline.titulo`, no `titulo`. */
function textosPorClave(): Map<string, string> {
  const mapa = new Map<string, string>();
  for (const fichero of ["es.ts", "es.pantallas.ts"]) {
    const fuente = readFileSync(join(RAIZ, "i18n", fichero), "utf-8");
    let grupo = "";
    for (const linea of fuente.split("\n")) {
      const abre = /^ {2}([a-zA-Z0-9_]+): \{/.exec(linea);
      if (abre?.[1]) {
        grupo = abre[1];
        continue;
      }
      const par = /^ {4}([a-zA-Z0-9_]+): "([^"]+)",/.exec(linea);
      if (par?.[1] && par[2] && grupo) mapa.set(`${grupo}.${par[1]}`, par[2]);
    }
  }
  return mapa;
}

/** Cada entrada de navegación, con su rótulo ya en castellano. */
function entradas(): { a: string; rotulo: string }[] {
  const nav = readFileSync(join(RAIZ, "lib", "navegacion.ts"), "utf-8");
  const textos = textosPorClave();
  const salida: { a: string; rotulo: string }[] = [];
  for (const bloque of nav.matchAll(/\{[^{}]*\}/g)) {
    const a = /\ba:\s*"([^"]*)"/.exec(bloque[0]);
    const clave = /\bclave:\s*"([^"]+)"/.exec(bloque[0]);
    if (!a?.[1] || !clave?.[1]) continue;
    const rotulo = textos.get(clave[1]);
    if (rotulo) salida.push({ a: a[1], rotulo });
  }
  // Y los módulos, que comparten el mismo menú.
  const mods = readFileSync(join(RAIZ, "lib", "modulos.ts"), "utf-8");
  for (const m of mods.matchAll(/ruta:\s*"([a-z-]+)",\s*\n\s*titulo:\s*"([^"]+)"/g)) {
    if (m[1] && m[2]) salida.push({ a: `/m/${m[1]}`, rotulo: m[2] });
  }
  return salida;
}

/** Sin tildes, sin signos y en minúscula: sólo las palabras. */
function llano(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9 ]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Parejas que se parecen tanto que hay que entrar para distinguirlas:
 * la misma frase salvo el plural, o una que es el principio de la otra.
 *
 * Lo que NO cuenta es compartir una palabra: «Casos» y «Bandeja de casos»
 * comparten «casos» y se distinguen de sobra, porque «bandeja» dice qué es.
 */
function seConfunden(a: string, b: string): boolean {
  const x = llano(a);
  const y = llano(b);
  if (x === y) return true;
  // Sólo cambia una «s» al final de la última palabra.
  const sinPlural = (s: string) => s.replace(/s\b/g, "");
  if (sinPlural(x) === sinPlural(y)) return true;
  // Una empieza por la otra y lo que sobra no llega a una palabra entera.
  const [corta, larga] = x.length <= y.length ? [x, y] : [y, x];
  if (larga.startsWith(corta) && larga.slice(corta.length).trim().length < 3) {
    return true;
  }
  // Mismo número de palabras y el mismo principio, cambiando sólo la última:
  // «Usuarios y permisos» y «Usuarios y seguridad». En una lista los dos
  // empiezan igual, así que hay que leerlos enteros para distinguirlos.
  //
  // La longitud importa: sin ella, «Casos» y «Bandeja de casos» saltarían, y
  // ésos se distinguen de sobra porque «bandeja» dice qué es.
  const px = x.split(" ");
  const py = y.split(" ");
  if (px.length >= 3 && px.length === py.length) {
    const igualesAlPrincipio = px.slice(0, -1).join(" ") === py.slice(0, -1).join(" ");
    if (igualesAlPrincipio) return true;
  }
  return false;
}

describe("dos entradas del menú", () => {
  const todas = entradas();

  it("se han leído las entradas de verdad", () => {
    // Sin esto, «ninguna se confunde» sería el resultado de no haber mirado.
    expect(todas.length, "no se han leído entradas").toBeGreaterThan(40);
  });

  it("no se llaman tan parecido que haya que entrar para distinguirlas", () => {
    const parecidas: string[] = [];
    for (let i = 0; i < todas.length; i += 1) {
      for (let j = i + 1; j < todas.length; j += 1) {
        const uno = todas[i];
        const otro = todas[j];
        if (!uno || !otro || uno.a === otro.a) continue;
        if (seConfunden(uno.rotulo, otro.rotulo)) {
          parecidas.push(`«${uno.rotulo}» → ${uno.a}   y   «${otro.rotulo}» → ${otro.a}`);
        }
      }
    }
    expect(
      parecidas,
      "dos entradas que se llaman casi igual obligan a entrar en las dos:\n  " +
        parecidas.join("\n  "),
    ).toEqual([]);
  });
});
