/**
 * Un campo propio se ELIGE en las condiciones de una regla (CRM-00.04.03.05).
 *
 * **Medido el 09-11-2026** en Procesos y orquestación › Automatizaciones ›
 * Nuevo: «Condiciones» era un editor de clave y valor, y un campo
 * personalizado sólo se podía usar tecleando `campos.<nombre>` de memoria.
 *
 * Lo que fija esta prueba:
 *   · con el objetivo escrito, se piden los campos de ESE objeto y se ofrecen
 *     en un desplegable;
 *   · elegir uno escribe `campos.<nombre>` en la condición y se manda en la
 *     gramática del motor —`{atributo, op, valor}`—, como lista;
 *   · un objeto sin nada declarado lo dice en vez de enseñar un desplegable
 *     vacío.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Formulario } from "@/componentes/Formulario";
import type { CampoEsquema } from "@/lib/contrato";

const pedidas: string[] = [];

vi.mock("@/lib/api", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      pedidas.push(ruta);
      if (ruta.includes("/objetos/homologacion/describe")) {
        return {
          datos: {
            campos: [
              { nombre: "norma", etiqueta: "Norma aplicable", activo: true },
              { nombre: "vieja", etiqueta: "Retirada", deprecado: true },
            ],
          },
          version: null,
          retenidos: [],
          enmascarados: [],
        };
      }
      throw new real.ErrorApi(404, "metadata.objeto_no_encontrado", "No", null);
    }),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

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

const CAMPOS = [
  campo({ nombre: "objetivo", titulo: "Objetivo" }),
  campo({ nombre: "condiciones", titulo: "Condiciones", tipo: "objeto" }),
];

describe("las condiciones de una regla", () => {
  beforeEach(() => {
    pedidas.length = 0;
  });

  it("ofrecen los campos propios del objetivo y mandan campos.<nombre>", async () => {
    const alEnviar = vi.fn();
    render(
      <MemoryRouter>
        <Formulario campos={CAMPOS} textoEnviar="Crear" alEnviar={alEnviar} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("editor-condiciones")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Objetivo"), "homologacion");
    await userEvent.click(screen.getByText("condiciones.anadir"));
    const elegir = await screen.findByLabelText(
      /condiciones\.campoPropio/,
      {},
      { timeout: 2000 },
    );
    // Sólo los activos: un campo retirado no se ofrece para reglas nuevas.
    expect(screen.queryByRole("option", { name: "Retirada" })).toBeNull();
    await userEvent.selectOptions(elegir, "campos.norma");
    await userEvent.type(
      screen.getByLabelText(/condiciones\.valor/),
      "ECE R10",
    );
    await userEvent.click(screen.getByText("Crear"));
    expect(alEnviar).toHaveBeenCalledWith({
      objetivo: "homologacion",
      condiciones: [{ atributo: "campos.norma", op: "=", valor: "ECE R10" }],
    });
    // Una petición por objeto escrito, no una por letra.
    expect(pedidas.filter((r) => r.includes("/describe"))).toEqual([
      "/api/v1/metadata/objetos/homologacion/describe",
    ]);
  });

  it("sin campos propios declarados lo dice, y se sigue pudiendo escribir", async () => {
    render(
      <MemoryRouter>
        <Formulario campos={CAMPOS} textoEnviar="Crear" alEnviar={vi.fn()} />
      </MemoryRouter>,
    );
    await userEvent.type(screen.getByLabelText("Objetivo"), "oportunidad");
    await waitFor(
      () =>
        expect(
          screen.getByText(/condiciones\.sinCamposPropios/),
        ).toBeInTheDocument(),
      { timeout: 2000 },
    );
    await userEvent.click(screen.getByText("condiciones.anadir"));
    expect(screen.queryByLabelText(/condiciones\.campoPropio/)).toBeNull();
    expect(screen.getByLabelText(/condiciones\.atributo/)).toBeInTheDocument();
  });

  it("sin objetivo en el formulario no se cambia el editor de siempre", () => {
    render(
      <MemoryRouter>
        <Formulario
          campos={[
            campo({
              nombre: "condiciones",
              titulo: "Condiciones",
              tipo: "objeto",
            }),
          ]}
          textoEnviar="Crear"
          alEnviar={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("editor-condiciones")).toBeNull();
  });
});
