/**
 * Convertir un lead en cliente, contacto y oportunidad sin salir de su ficha.
 *
 * Medido el 10-11-2026 (tarea T02): la acción del contrato pedía un cliente que
 * ya existiera, así que la conversión de un lead de una empresa nueva no se
 * podía terminar desde la ficha. `ConvertirLead` crea lo que falta, en orden y
 * por las rutas de cada servicio. Se vigilan las dos decisiones que importan:
 *
 *   · si no hay cliente con ese nombre, se crea y **el contacto cuelga de él**;
 *   · si ya hay uno que se llama exactamente así, se usa y **no se crea otro**,
 *     que es el duplicado que más cuesta deshacer después.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const enviado: { ruta: string; cuerpo: Record<string, unknown> }[] = [];
let resultadosDeBusqueda: {
  objeto: string;
  registro_id: string;
  titulo: string;
}[] = [];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(
      async (
        ruta: string,
        opciones?: { metodo?: string; cuerpo?: unknown },
      ) => {
        if ((opciones?.metodo ?? "GET") === "GET") {
          return { datos: { resultados: resultadosDeBusqueda }, version: null };
        }
        enviado.push({
          ruta,
          cuerpo: (opciones?.cuerpo ?? {}) as Record<string, unknown>,
        });
        if (ruta === "/api/v1/accounts")
          return { datos: { id: "cuenta-nueva" } };
        if (ruta === "/api/v1/contacts")
          return { datos: { id: "contacto-nuevo" } };
        return { datos: { cuenta_id: "c", oportunidad_id: "op-1" } };
      },
    ),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, args?: Record<string, unknown>) =>
      args ? `${clave}:${JSON.stringify(args)}` : clave,
  }),
}));

const LEAD = { nombre: "Laura", apellidos: "Medina", empresa: "Talleres Pons" };

async function montar() {
  const { ConvertirLead } = await import("@/componentes/ConvertirLead");
  return render(
    <MemoryRouter initialEntries={["/m/leads/lead/l-1"]}>
      <Routes>
        <Route
          path="/m/leads/lead/:id"
          element={
            <ConvertirLead
              leadId="l-1"
              lead={LEAD}
              alCancelar={() => undefined}
            />
          }
        />
        <Route
          path="/m/oportunidades/oportunidad/:id"
          element={<p>ficha de la oportunidad</p>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("convertir un lead de una vez", () => {
  beforeEach(() => {
    enviado.length = 0;
    resultadosDeBusqueda = [];
  });

  it("sin cliente con ese nombre, lo crea, cuelga de él el contacto y convierte", async () => {
    await montar();
    fireEvent.click(
      await screen.findByRole("button", { name: "convertirLead.convertir" }),
    );

    await screen.findByText("ficha de la oportunidad");
    expect(enviado.map((e) => e.ruta)).toEqual([
      "/api/v1/accounts",
      "/api/v1/contacts",
      "/api/v1/leads/l-1/convertir",
    ]);
    expect(enviado[0]!.cuerpo).toMatchObject({ nombre: "Talleres Pons" });
    expect(enviado[1]!.cuerpo).toMatchObject({
      nombre: "Laura",
      apellidos: "Medina",
      cuenta_id: "cuenta-nueva",
    });
    expect(enviado[2]!.cuerpo).toMatchObject({
      cuenta_id: "cuenta-nueva",
      contacto_id: "contacto-nuevo",
      crear_oportunidad: true,
      nombre_oportunidad: "Talleres Pons",
    });
  });

  it("si ya hay un cliente que se llama así, lo usa y no crea otro", async () => {
    resultadosDeBusqueda = [
      {
        objeto: "oportunidad",
        registro_id: "op-9",
        titulo: "Talleres Pons — línea 2",
      },
      {
        objeto: "cuenta",
        registro_id: "cuenta-que-ya-estaba",
        titulo: "Talleres  pons",
      },
    ];
    await montar();
    // Sale elegido sin tocar nada: es el que se llama exactamente así.
    await waitFor(() =>
      expect(
        screen.getByRole("radio", {
          name: /convertirLead\.usar.*Talleres\s+pons/,
        }),
      ).toBeChecked(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "convertirLead.convertir" }),
    );

    await screen.findByText("ficha de la oportunidad");
    expect(enviado.map((e) => e.ruta)).not.toContain("/api/v1/accounts");
    expect(enviado.at(-1)!.cuerpo).toMatchObject({
      cuenta_id: "cuenta-que-ya-estaba",
    });
  });
});
