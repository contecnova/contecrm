/**
 * El menú «Más» de la barra no se sale de la pantalla.
 *
 * Lo dijo quien lo usa el 04-11-2026: «siempre se corta el menú de Más a la
 * derecha». El botón vive pegado al borde derecho de la barra y el panel se
 * abría hacia la derecha, así que las pestañas salían recortadas —«Proveedores»
 * a medias, «Aprobar doc…»—.
 *
 * Y el matiz que puso, que es el que convierte esto en dos arreglos y no uno:
 * **hay que tener en cuenta la longitud de lo que aparece, porque si no se
 * cortará igual.** Abrir hacia el otro lado resuelve un borde y deja el
 * contrario: «Aprobar documentos pendientes de firma» en una ventana estrecha
 * se saldría por la izquierda exactamente igual. Por eso el panel lleva además
 * un tope de ancho atado a la ventana, y el nombre largo parte en dos líneas.
 *
 * Medido abriéndolo en el producto a 1440, 1100 y 820 px: el panel queda
 * dentro en los tres.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { MenuDeAcciones } from "@/componentes/MenuDeAcciones";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

const OPCIONES = [
  { clave: "a", nombre: "Proveedores", alElegir: () => {} },
  { clave: "b", nombre: "Aprobar documentos pendientes de firma", alElegir: () => {} },
];

function panelDe(contenedor: HTMLElement): HTMLElement {
  const panel = contenedor.querySelector<HTMLElement>("div.absolute");
  if (!panel) throw new Error("el menú no ha abierto ningún panel");
  return panel;
}

describe("el panel de un menú de acciones", () => {
  it("abre hacia la izquierda cuando se le pide, y hacia la derecha si no", async () => {
    const { container, rerender } = render(
      <MenuDeAcciones opciones={OPCIONES} etiqueta="mas" />,
    );
    await userEvent.click(screen.getByRole("button", { name: "mas" }));
    expect(panelDe(container).className).toMatch(/\bleft-0\b/);

    rerender(<MenuDeAcciones opciones={OPCIONES} etiqueta="mas" haciaLaIzquierda />);
    expect(panelDe(container).className).toMatch(/\bright-0\b/);
  });

  it("y nunca puede ser más ancho que la ventana", async () => {
    // El tope va atado a `100vw`: sin él, abrir hacia un lado sólo cambia por
    // qué borde se sale.
    const { container } = render(
      <MenuDeAcciones opciones={OPCIONES} etiqueta="mas" haciaLaIzquierda />,
    );
    await userEvent.click(screen.getByRole("button", { name: "mas" }));
    expect(panelDe(container).className).toMatch(/max-w-\[min\(.*100vw.*\)\]/);
  });
});

describe("el «Más» de la barra de aplicación", () => {
  it("pide que se abra hacia la izquierda", () => {
    // Por el fichero: montar la barra entera exige el menú resuelto, la
    // superficie y medir anchos con `ResizeObserver`, y lo que aquí decide es
    // una línea. Lo que el panel hace con la bandera lo fija la prueba de
    // arriba, que sí lo monta.
    const fuente = readFileSync(
      resolve(process.cwd(), "src", "componentes", "BarraDeAplicacion.tsx"),
      "utf-8",
    );
    const bloque = fuente.slice(fuente.indexOf("<MenuDeAcciones"));
    expect(bloque.slice(0, bloque.indexOf("/>"))).toMatch(/haciaLaIzquierda/);
  });
});
