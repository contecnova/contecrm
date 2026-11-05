/**
 * Una ficha cuya lectura es una lista la enseña como tabla, y no ofrece editar.
 *
 * `GET /colas/{clave}` devuelve lo que espera en esa cola —una lista de
 * casos—, no la cola. La ficha la pintaba campo a campo por posición:
 * «0 · Caso ID: … +4», «1 · Caso ID: … +4». Y su «Editar» se habría rellenado
 * con esa lista. Visto en la pantalla el 05-11-2026.
 *
 * Validada plantando el caso malo: sin la rama de `contenido`, falla.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/permisos", () => ({
  useSuperficie: () => ({
    superficie: {
      operaciones: [],
      objetos: { adjuntos: [], comentarios: [], documentos: [], actividades: [] },
    },
    tiene: () => true,
  }),
  usePuedeOperar: () => () => true,
  useVisibilidad: () => ({ rutas: new Set<string>(), cargada: false, sinContestar: new Set<string>() }),
}));

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => ({
      datos: /\/colas\/entrada$/.test(ruta)
        ? [
            { caso_id: "c-1", codigo: "CS-00928", asunto: "Discrepancia en el albarán" },
            { caso_id: "c-2", codigo: "CS-01209", asunto: "Consumo por encima de lo previsto" },
          ]
        : [],
      version: null,
      retenidos: [],
      enmascarados: [],
    })),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

describe("una lectura que es una lista", () => {
  it("se pinta como tabla y la ficha no ofrece editarla", async () => {
    const { Ficha } = await import("@/paginas/Ficha");
    render(
      <MemoryRouter initialEntries={["/m/casos/cola/entrada"]}>
        <Routes>
          <Route path="/m/:ruta/:tipo/:id" element={<Ficha />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("CS-00928")).toBeInTheDocument());
    expect(screen.getByText("CS-01209")).toBeInTheDocument();
    expect(screen.getAllByRole("table").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "ficha.editar" })).toBeNull();
  });
});
