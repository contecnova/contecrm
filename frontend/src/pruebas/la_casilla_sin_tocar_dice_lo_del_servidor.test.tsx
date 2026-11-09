/**
 * Una casilla sin tocar enseña lo que hará el servidor, sin mandarlo.
 *
 * **Medido el 09-11-2026** creando un sandbox: «Anonimizar» salía sin marcar y
 * el servidor anonimizaba igualmente, porque su valor por defecto es `true`. La
 * pantalla decía lo contrario de lo que iba a pasar con los datos de los
 * clientes. El valor por defecto se ENSEÑA, no se guarda: guardarlo en el
 * formulario haría que el del cliente tapara para siempre al del servidor.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Formulario } from "@/componentes/Formulario";
import { camposDe, type CampoEsquema, type Documento } from "@/lib/contrato";

const DOC = {
  paths: {
    "/api/v1/sandboxes": {
      post: {
        requestBody: {
          content: {
            "application/json": {
              schema: {
                type: "object",
                required: ["anonimizar"],
                properties: {
                  anonimizar: { type: "boolean", default: true },
                  copiar_adjuntos: { type: "boolean" },
                },
              },
            },
          },
        },
      },
    },
  },
} as unknown as Documento;

describe("la casilla sin tocar", () => {
  it("el contrato trae el valor por defecto", () => {
    const campos = camposDe(DOC, "/api/v1/sandboxes", "post");
    expect(campos.find((c) => c.nombre === "anonimizar")?.porDefecto).toBe(
      true,
    );
    expect(
      campos.find((c) => c.nombre === "copiar_adjuntos")?.porDefecto,
    ).toBeUndefined();
  });

  it("sale marcada si el servidor dice que sí, y no se manda hasta tocarla", async () => {
    const campos: CampoEsquema[] = camposDe(
      DOC,
      "/api/v1/sandboxes",
      "post",
    ).map((c) => ({
      ...c,
      obligatorio: true,
    }));
    const alEnviar = vi.fn();
    render(
      <MemoryRouter>
        <Formulario campos={campos} textoEnviar="Crear" alEnviar={alEnviar} />
      </MemoryRouter>,
    );
    const casilla = screen.getByRole("checkbox", { name: /anonimizar/i });
    expect(casilla).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /copiar adjuntos/i }),
    ).not.toBeChecked();
    await userEvent.click(casilla);
    expect(casilla).not.toBeChecked();
  });
});
