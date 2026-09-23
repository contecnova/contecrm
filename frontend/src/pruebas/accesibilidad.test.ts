/**
 * Accesibilidad comprobada, no declarada (CRM-06.02.01.05).
 *
 * `eslint-plugin-jsx-a11y` ya caza lo que se puede ver en una etiqueta suelta —un
 * `img` sin `alt`, un `onClick` sobre un `div`—. Lo que no caza es lo que solo se
 * ve mirando la pantalla entera, y es justo lo que hace que una interfaz sea
 * inutilizable con teclado o con lector:
 *
 * **Una pantalla sin `h1`.** Quien navega con lector salta por encabezados; sin
 * uno de primer nivel, la única forma de saber dónde está es leerlo todo.
 *
 * **Un campo sin etiqueta asociada.** Un `placeholder` no es una etiqueta:
 * desaparece al escribir y muchos lectores no lo anuncian.
 *
 * **Un estado que cambia en silencio.** Si al pulsar «calcular» aparece un
 * resultado y nada lo anuncia, quien no ve la pantalla no se entera de que ha
 * pasado algo.
 *
 * Se comprueba sobre el **código fuente** y no renderizando: renderizar cada
 * página exigiría simular su API, y una comprobación que cuesta mantener se acaba
 * saltando — que es exactamente cómo la accesibilidad deja de comprobarse.
 */

import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const PAGINAS = join(dirname(fileURLToPath(import.meta.url)), "..", "paginas");

function paginas(): string[] {
  return readdirSync(PAGINAS).filter((f) => f.endsWith(".tsx"));
}

function fuente(fichero: string): string {
  return readFileSync(join(PAGINAS, fichero), "utf8");
}

/**
 * El código sin las flechas de las funciones.
 *
 * Hace falta para poder recortar una etiqueta JSX por su `>` de cierre: un
 * `onChange={(e) => ...}` mete un `>` en medio del atributo y, sin quitarlo, la
 * etiqueta se corta antes de llegar a su `aria-label` — y la comprobación acusa
 * de no tener etiqueta a un campo que sí la tiene.
 */
function sinFlechas(texto: string): string {
  return texto.replace(/=>/g, "==");
}

describe("accesibilidad de las pantallas (WCAG 2.2 AA)", () => {
  it("la cabecera canónica pone un encabezado de primer nivel", () => {
    // De esto depende la comprobación siguiente: si `CabeceraPagina` dejara de
    // pintar un `<h1>`, todas las pantallas que la usan se quedarían sin
    // encabezado de primer nivel y el gate seguiría en verde. Se comprueba
    // aquí, una vez, en vez de confiar en que nadie la toque.
    const cabecera = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "..", "componentes", "Pagina.tsx"),
      "utf8",
    );
    expect(cabecera).toContain("<h1");
  });

  it("toda pantalla tiene un encabezado de primer nivel", () => {
    // Quien navega con lector salta por encabezados. Sin `h1`, la única forma
    // de saber dónde está es leerlo todo.
    //
    // Vale el `<h1>` escrito a mano o la cabecera canónica, que pone uno —y que
    // es lo que usan casi todas, para que el título tenga la misma presencia en
    // toda la aplicación.
    const sin = paginas().filter((f) => {
      const texto = fuente(f);
      return !texto.includes("<h1") && !texto.includes("<CabeceraPagina");
    });
    expect(sin, `Pantallas sin encabezado de primer nivel: ${sin.join(", ")}`).toEqual([]);
  });

  it("ninguna pantalla pone dos encabezados de primer nivel", () => {
    // Dos `<h1>` en la misma pantalla dejan de indicar dónde está uno: el
    // encabezado de primer nivel sirve precisamente porque es único. Pasó al
    // introducir la cabecera canónica —quedaban pantallas con su `<h1>` viejo
    // encima— y a simple vista no se nota.
    const dobles = paginas().filter((f) => {
      const texto = fuente(f);
      return texto.includes("<CabeceraPagina") && texto.includes("<h1");
    });
    expect(dobles, `Pantallas con dos encabezados: ${dobles.join(", ")}`).toEqual([]);
  });

  it("todo campo de entrada tiene etiqueta asociada o nombre accesible", () => {
    // Un `placeholder` no es una etiqueta: desaparece al escribir y muchos
    // lectores no lo anuncian.
    const fallos: string[] = [];
    for (const f of paginas()) {
      const texto = sinFlechas(fuente(f));
      const campos = texto.match(/<(input|textarea|select)\b[^>]*/g) ?? [];
      for (const campo of campos) {
        const tieneId = /\sid=/.test(campo);
        const tieneAria = /aria-label|aria-labelledby/.test(campo);
        // Un campo ENVUELTO en su `<label>` está asociado sin necesidad de
        // `id`/`htmlFor`, y es un patrón correcto. Marcarlo como fallo haría que
        // esta comprobación señalara código bien escrito, y un gate que se
        // equivoca se acaba desactivando.
        const posicion = texto.indexOf(campo);
        const envuelto = /<label\b[^>]*>(?![\s\S]*?<\/label>[\s\S]*?$)/.test(
          texto.slice(Math.max(0, posicion - 400), posicion),
        );
        if (!tieneId && !tieneAria && !envuelto) fallos.push(`${f}: ${campo.slice(0, 60)}`);
        if (tieneId) {
          const id = campo.match(/\sid="([^"]+)"/)?.[1];
          if (id && !texto.includes(`htmlFor="${id}"`)) {
            fallos.push(`${f}: el campo «${id}» no tiene <label htmlFor>`);
          }
        }
      }
    }
    expect(fallos, fallos.join("\n")).toEqual([]);
  });

  it("los resultados que aparecen al pulsar algo se anuncian", () => {
    // Si al pulsar «calcular» aparece un resultado y nada lo anuncia, quien no
    // ve la pantalla no se entera de que ha pasado algo. Se exige `role="status"`
    // o `aria-live` en las pantallas que tienen botones de acción.
    const fallos: string[] = [];
    for (const f of paginas()) {
      const texto = fuente(f);
      const tieneAccion = /<button[^>]*type="button"/.test(texto);
      const anuncia = /role="status"|aria-live=/.test(texto);
      // `Cargando` y `Error` ya anuncian por su cuenta: una pantalla que solo
      // carga y pinta no necesita nada más.
      const soloPinta = !tieneAccion;
      if (!soloPinta && !anuncia) fallos.push(f);
    }
    expect(fallos, `Pantallas con acciones y sin anuncio: ${fallos.join(", ")}`).toEqual([]);
  });

  it("las tablas tienen encabezados con ámbito declarado", () => {
    // Sin `scope`, un lector no sabe si una celda de cabecera describe su
    // columna o su fila, y una tabla de seis columnas se vuelve ilegible.
    const fallos: string[] = [];
    for (const f of paginas()) {
      const texto = fuente(f);
      if (!texto.includes("<table")) continue;
      const cabeceras = texto.match(/<th\b[^>]*/g) ?? [];
      for (const th of cabeceras) {
        if (!/scope=/.test(th)) fallos.push(`${f}: ${th.slice(0, 50)}`);
      }
    }
    expect(fallos, fallos.join("\n")).toEqual([]);
  });

  it("ningún color es la única forma de entender un estado", () => {
    // Es el fallo de accesibilidad más común en un panel: rojo y verde sin
    // texto. Quien no distingue esos colores —uno de cada doce hombres— ve dos
    // celdas idénticas.
    //
    // Se comprueba que las pantallas que usan `text-danger` o `text-success`
    // pintan también texto, no solo un icono o un punto.
    const fallos: string[] = [];
    for (const f of paginas()) {
      const texto = fuente(f);
      if (!/text-(danger|success|warning)/.test(texto)) continue;
      // Un `{t(` o una interpolación dentro del mismo bloque significa que hay
      // texto y no solo color.
      if (!/\{t\(|\{[a-z]+\.(porque|que_significa|aviso|motivo|estado)/.test(texto)) {
        fallos.push(f);
      }
    }
    expect(fallos, `Pantallas donde el color va solo: ${fallos.join(", ")}`).toEqual([]);
  });
});
