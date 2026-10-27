/**
 * Todas las tarjetas de una fila miden lo mismo.
 *
 * Lo reportó quien la usa: en una fila de tres, la de la derecha salía más
 * baja. La causa es que la altura la ponía el contenido —una cuenta sin
 * responsable no pinta esa línea, y son doce píxeles menos— así que dos
 * tarjetas iguales en todo lo demás acababan con el borde a distinta altura.
 *
 * Y son iguales **en toda la rejilla**, no sólo dentro de su fila: el primer
 * arreglo igualó las de cada fila y dejó una fila entera más baja que la
 * siguiente, que es exactamente el mismo defecto una escala más arriba.
 *
 * No es estética. Un borde que no cuadra con el de al lado se lee como que a
 * esa ficha le falta algo, y lo que le falta es un dato que puede estar vacío
 * a propósito: el ojo lo interpreta como un defecto del registro cuando es un
 * defecto de la rejilla.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/lib/personas", () => ({
  usePersonas: () => ({}),
  nombreDe: (_p: unknown, id: unknown) => String(id ?? ""),
  inicialesDe: (n: string) => n.slice(0, 2).toUpperCase(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

const { Tarjetas } = await import("@/componentes/Vistas");

const FILAS = [
  // Con responsable: una línea más que la siguiente.
  { id: "1", nombre: "Ibérica Sistemas S.A.", estado: "activa", owner_id: "ana" },
  { id: "2", nombre: "Transportes Duero, S.A.U.", estado: "activa" },
];

describe("la rejilla de tarjetas", () => {
  it("estira todas a la altura de la fila", () => {
    const { container } = render(
      <MemoryRouter>
        <Tarjetas filas={FILAS} columnas={["nombre", "estado"]} />
      </MemoryRouter>,
    );

    const rejilla = container.querySelector("ul");
    // Las dos, y hacen cosas distintas: `items-stretch` iguala dentro de la
    // fila y `auto-rows-fr` iguala las filas entre sí. Con sólo la primera,
    // una fila sin responsables sale más baja que la de debajo.
    expect(rejilla?.className).toContain("items-stretch");
    expect(rejilla?.className, "las filas no se igualan entre sí").toContain("auto-rows-fr");

    // Hijos DIRECTOS de la rejilla: dentro de cada tarjeta hay otra `<ul>`
    // con las pastillas de estado, así que un `querySelectorAll("li")` devuelve
    // cuatro y la prueba estaría mirando otra cosa.
    const celdas = [...(rejilla?.children ?? [])] as HTMLElement[];
    expect(celdas).toHaveLength(2);
    for (const celda of celdas) {
      expect(celda.className, "la celda no ocupa el alto de la fila").toContain("h-full");
      const tarjeta = celda.firstElementChild as HTMLElement;
      // `h-full` sobre la tarjeta, y `flex-col` para poder empujar el pie: sin
      // los dos, la celda se estira y la tarjeta de dentro no.
      expect(tarjeta.className).toContain("h-full");
      expect(tarjeta.className).toContain("flex-col");
    }
  });

  it("y la fila que sí tiene responsable lo pega abajo", () => {
    render(
      <MemoryRouter>
        <Tarjetas filas={FILAS} columnas={["nombre", "estado"]} />
      </MemoryRouter>,
    );
    // Con `mt-auto`, en una fila de tres los avatares quedan alineados entre sí
    // en vez de a distinta altura cada uno.
    const pie = screen.getByText("ana").closest("p");
    expect(pie?.className).toContain("mt-auto");
  });
});
