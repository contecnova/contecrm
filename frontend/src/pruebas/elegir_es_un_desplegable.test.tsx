/**
 * Elegir una cosa u otra se hace en un desplegable (pedido el 05-11-2026).
 *
 * El selector de registros era un buscador con la lista siempre abierta
 * debajo, y la lista múltiple un muro de casillas: con el formulario cerrado
 * ya ocupaban media pantalla. Aquí se vigila lo que se ve antes de tocar nada
 * —un campo, sin lista— y que abierto se pueda buscar y elegir con el teclado.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Formulario } from "@/componentes/Formulario";
import type { CampoEsquema } from "@/lib/contrato";

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async () => ({
      datos: {
        items: [
          { id: "c1", nombre: "Componentes Miño" },
          { id: "c2", nombre: "Forjas Alcañiz" },
          { id: "c3", nombre: "Plásticos Ebro" },
        ],
      },
    })),
  };
});

function campo(p: Partial<CampoEsquema>): CampoEsquema {
  return {
    nombre: "x",
    tipo: "texto",
    obligatorio: true,
    titulo: "X",
    descripcion: "",
    opciones: [],
    maximo: null,
    formato: "",
    subcampos: [],
    referencia: "",
    ...p,
  } as CampoEsquema;
}

function montar(campos: CampoEsquema[], alEnviar = vi.fn()) {
  render(
    <MemoryRouter>
      <Formulario campos={campos} textoEnviar="Crear" alEnviar={alEnviar} />
    </MemoryRouter>,
  );
  return alEnviar;
}

describe("elegir un registro", () => {
  it("cerrado es un campo, sin ninguna lista a la vista", async () => {
    montar([
      campo({ nombre: "cuenta_id", titulo: "Cuenta", referencia: "cuenta" }),
    ]);
    const desplegable = await screen.findByRole("combobox");
    expect(desplegable.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.queryByText("Forjas Alcañiz")).toBeNull();
  });

  it("abierto se busca, se elige con el teclado y enseña lo elegido", async () => {
    const alEnviar = montar([
      campo({ nombre: "cuenta_id", titulo: "Cuenta", referencia: "cuenta" }),
    ]);
    fireEvent.click(await screen.findByRole("combobox"));
    // Sin traducciones cargadas, el rótulo es su clave.
    const buscador = await screen.findByRole("textbox", {
      name: /buscarEnLista|Buscar por nombre/,
    });
    fireEvent.change(buscador, { target: { value: "forj" } });
    expect(screen.getAllByRole("option")).toHaveLength(1);
    fireEvent.keyDown(buscador, { key: "Enter" });
    // Se cierra y el campo dice el nombre, no el identificador.
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    expect(screen.getByRole("combobox").textContent).toContain(
      "Forjas Alcañiz",
    );
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));
    await waitFor(() =>
      expect(alEnviar).toHaveBeenCalledWith(
        expect.objectContaining({ cuenta_id: "c2" }),
      ),
    );
  });
});

describe("elegir varias opciones", () => {
  it("es un desplegable con el texto legible, no un muro de casillas", () => {
    montar([
      campo({
        nombre: "factores",
        titulo: "Factores",
        tipo: "lista_multiple",
        opciones: ["precio", "descuento_tardio", "B2B"],
      }),
    ]);
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Factores" }));
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
    // Legible, y la sigla como viene.
    expect(screen.getByText("Descuento tardío")).toBeTruthy();
    expect(screen.getByText("B2B")).toBeTruthy();
    fireEvent.click(screen.getByText("Descuento tardío"));
    expect(
      screen.getByRole("button", { name: "Factores" }).textContent,
    ).toContain("Descuento tardío");
  });
});
