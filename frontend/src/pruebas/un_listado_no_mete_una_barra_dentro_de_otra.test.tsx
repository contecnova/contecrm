/**
 * El listado de un módulo se recorre con la página, no dentro de una caja.
 *
 * `.lista-acotada` corta una lista a 28rem y le pone barra propia. Existe por
 * una razón buena —si una pantalla enseña varias listas, ninguna puede
 * empujar a las demás fuera de la vista— y su excepción estaba escrita, con
 * todas las letras, en DOS sitios:
 *
 * > «NO se usa cuando la pantalla ES la lista —un listado de módulo, la cola
 * > de duplicados, la búsqueda en conocimiento—: ahí no hay nada a lo que
 * > dejar sitio, y meter una barra dentro de la página es peor.»
 *
 * En `index.css` y otra vez en `Rejilla.tsx`. **No estaba implementada en
 * ninguno de los dos.** `Rejilla` ponía la clase a todas las tablas sin
 * preguntar, así que los 53 listados del producto se cortaban a 448 px con una
 * barra dentro de otra. Medido el 01-11-2026 en Cuentas a 1440×900: caja de
 * 446 px con 1.504 px de contenido, 14 filas visibles de las 50 cargadas y
 * 110 px de página en blanco debajo. Quitado el tope: 19 filas y la lista
 * sigue al desplazar la página.
 *
 * Una regla escrita dos veces y cumplida cero es la forma más silenciosa de
 * que algo esté mal: todo el que la lee cree que está hecha. Por eso se prueba
 * **el comportamiento**, no el comentario.
 */

import { render } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { Tabla } from "@/componentes/Tabla";

const FILAS = [
  { nombre: "Ficosa", estado: "activa" },
  { nombre: "Componentes Delta", estado: "activa" },
];

/** El recuadro de la tabla: el que lleva —o no— el tope de alto. */
function recuadro(contenedor: HTMLElement): HTMLElement {
  const tabla = contenedor.querySelector("table");
  if (!tabla) throw new Error("no se ha pintado ninguna tabla");
  const caja = tabla.parentElement;
  if (!caja) throw new Error("la tabla no tiene recuadro");
  return caja;
}

describe("una tabla que ES la pantalla", () => {
  it("no se corta ni lleva barra propia", () => {
    const { container } = render(
      <Tabla filas={FILAS} columnas={["nombre", "estado"]} ocupaLaPantalla />,
    );
    expect(recuadro(container).className).not.toContain("lista-acotada");
  });
});

describe("una tabla de apoyo dentro de otra pantalla", () => {
  it("sigue acotada, que es lo que impide que tape a las de debajo", () => {
    // Por defecto, y a propósito: lo normal es ser la tabla de apoyo, y el
    // fallo caro es el contrario —una cola de cien trabajos dejando los
    // paneles siguientes a dos pantallas de distancia.
    const { container } = render(<Tabla filas={FILAS} columnas={["nombre", "estado"]} />);
    expect(recuadro(container).className).toContain("lista-acotada");
  });
});

describe("el listado de módulo", () => {
  it("se lo dice a la tabla, que es lo único que ella no puede saber", () => {
    // La pieza que se pudre: `Tabla` ya sabe hacerlo, pero sólo lo hace si la
    // pantalla se lo pide. Si alguien reescribe este listado y no pasa la
    // bandera, vuelve la barra dentro de la barra sin que nada se queje.
    const fuente = fs.readFileSync(
      path.join(process.cwd(), "src/paginas/Modulo.tsx"),
      "utf8",
    );
    const tablas = fuente.match(/<Tabla\b[\s\S]*?\/>/g) ?? [];
    expect(tablas.length).toBeGreaterThan(0);
    for (const tabla of tablas) {
      expect(tabla, "el listado del módulo tiene que pasar `ocupaLaPantalla`").toMatch(
        /\bocupaLaPantalla\b/,
      );
    }
  });
});
