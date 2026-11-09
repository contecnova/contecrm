/**
 * Una casilla enseña el valor de ahora y manda lo que enseña.
 *
 * **Medido el 09-11-2026** apagando una automatización desde su ficha: la
 * acción «Activar o desactivar una regla» pide un único booleano obligatorio,
 * `activa`. La casilla salía sin marcar aunque la regla estuviera encendida
 * —no se sabía en qué estado estaba— y, sin tocarla, el formulario mandaba
 * `{}`: el valor era `undefined`, el JSON se lo comía y el servidor contestaba
 * 422 «activa: Falta este campo». O sea que **no había forma de apagar una
 * regla** desde la pantalla sin marcar y desmarcar la casilla antes.
 *
 * Lo que fija esta prueba:
 *   · con el registro delante, la casilla sale como está el registro;
 *   · sin tocarla, se manda ese valor; desmarcada, se manda `false`, no nada.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Accion } from "@/lib/acciones";

const enviadas: Array<{ ruta: string; cuerpo: unknown }> = [];

vi.mock("@/lib/api", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...real,
    llamar: vi.fn(async (ruta: string, opciones?: { cuerpo?: unknown }) => {
      enviadas.push({ ruta, cuerpo: opciones?.cuerpo });
      return {
        datos: { hecho: true },
        version: null,
        retenidos: [],
        enmascarados: [],
      };
    }),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

vi.mock("@/lib/contrato", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/contrato")>();
  return {
    ...real,
    contratoDe: vi.fn(async () => ({
      paths: {
        "/api/v1/automatizaciones/{regla_id}/activar": {
          post: {
            requestBody: {
              required: true,
              content: {
                "application/json": {
                  schema: {
                    type: "object",
                    required: ["activa"],
                    properties: {
                      activa: { type: "boolean", title: "Activa" },
                    },
                  },
                },
              },
            },
          },
        },
      },
    })),
  };
});

const { Acciones } = await import("@/componentes/Acciones");

const ACTIVAR: Accion = {
  clave: "activar",
  nombre: "Activar o desactivar una regla",
  ruta: "/api/v1/automatizaciones/r1/activar",
  plantilla: "/api/v1/automatizaciones/{regla_id}/activar",
  metodo: "post",
  permiso: null,
};

/** El botón de enviar del formulario; el de la barra lo ofrece el menú. */
function enviar(): HTMLElement {
  const boton = screen
    .getAllByRole("button", { name: ACTIVAR.nombre })
    .find((b) => b.getAttribute("type") === "submit");
  if (!boton) throw new Error("sin botón de enviar");
  return boton;
}

function Montada({ registro }: { registro: Record<string, unknown> | null }) {
  return (
    <Acciones
      acciones={[ACTIVAR]}
      servicio="automation"
      alTerminar={() => {}}
      abierta={ACTIVAR}
      alCambiarAbierta={() => {}}
      registro={registro}
    />
  );
}

describe("la casilla de una acción", () => {
  beforeEach(() => {
    enviadas.length = 0;
  });

  it("sale como está el registro y, sin tocarla, manda ese valor", async () => {
    render(<Montada registro={{ id: "r1", activa: true }} />);
    const casilla = await screen.findByRole("checkbox", { name: "Activa" });
    expect(casilla).toBeChecked();
    await userEvent.click(enviar());
    await waitFor(() => expect(enviadas).toHaveLength(1));
    expect(enviadas[0]?.cuerpo).toEqual({ activa: true });
  });

  it("desmarcada manda false, no un cuerpo vacío", async () => {
    render(<Montada registro={null} />);
    const casilla = await screen.findByRole("checkbox", { name: "Activa" });
    expect(casilla).not.toBeChecked();
    await userEvent.click(enviar());
    await waitFor(() => expect(enviadas).toHaveLength(1));
    expect(enviadas[0]?.cuerpo).toEqual({ activa: false });
  });
});
