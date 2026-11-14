/**
 * El tablero de oportunidades dice cuándo no están todas, y deja seguir.
 *
 * Pedía `?limite=200` y pintaba lo que llegara como si fuera el embudo
 * entero: la doscientas una no estaba en ninguna columna y nada lo decía.
 * Aquí se comprueba en la pantalla de verdad que, con cursor, sale el aviso y
 * «cargar más» trae la siguiente página a su columna.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/lib/personas", () => ({
  usePersonas: () => ({}),
  nombreDe: (_p: unknown, id: unknown) => String(id ?? ""),
  inicialesDe: (n: string) => n.slice(0, 2).toUpperCase(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, o?: Record<string, unknown>) =>
      o ? `${clave} ${JSON.stringify(o)}` : clave,
  }),
}));

const llamar = vi.fn();
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  llamar: (...a: unknown[]) => llamar(...a),
}));

const { Pipeline } = await import("@/paginas/Pipeline");

const ETAPA = {
  id: "e1",
  clave: "nueva",
  nombre: "Nueva",
  orden: 1,
  probabilidad: 10,
  terminal: false,
  ganada: false,
};

function oportunidad(id: string, nombre: string) {
  return {
    id,
    nombre,
    codigo: null,
    importe: 0,
    moneda: "EUR",
    probabilidad: 10,
    etapa_id: "e1",
    estado: "abierta",
    fecha_cierre: null,
    cuenta_id: null,
    owner_id: null,
  };
}

describe("el tablero de oportunidades", () => {
  it("con cursor avisa de que hay más y «cargar más» las trae", async () => {
    llamar.mockImplementation(async (ruta: string) => {
      if (ruta.startsWith("/api/v1/pipelines"))
        return { datos: [{ id: "p1", nombre: "Ventas", por_defecto: true, etapas: [ETAPA] }] };
      if (ruta.includes("cursor=C1"))
        return { datos: { items: [oportunidad("2", "Segunda")], siguiente: null } };
      return { datos: { items: [oportunidad("1", "Primera")], siguiente: "C1" } };
    });
    render(
      <MemoryRouter>
        <Pipeline sesion={null} />
      </MemoryRouter>,
    );

    const aviso = await screen.findByRole("note");
    expect(aviso.textContent).toContain('listas.recortada {"count":1}');
    expect(screen.queryByText("Segunda")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "listas.cargarMas" }));

    expect(await screen.findByText("Segunda")).toBeTruthy();
    expect(screen.getByText("Primera")).toBeTruthy();
    expect(screen.queryByRole("note")).toBeNull();
  });
});
