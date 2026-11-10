/**
 * Lo que la pantalla de explotación prometía y no hacía (CRM-05.01.04.03,
 * CRM-05.01.04.06), medido el 10-11-2026 en vivo contra contecintelligence:
 *
 *   - Una pregunta ambigua («¿Cuántas cuentas hay?») vuelve como aclaración,
 *     con opciones. Se enseñaba el motivo y «Sin resultados», y las opciones
 *     —la salida— no aparecían.
 *   - La lista vacía decía «Guarda una pregunta para no volver a escribirla» y
 *     no había con qué guardarla.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RespuestaAnalitica } from "@/componentes/RespuestaAnalitica";
import { llamar } from "@/lib/api";
import { Explotacion } from "@/paginas/Explotacion";

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => {
    if (ruta.includes("/explotacion/diagnostico"))
      return {
        datos: {
          puede_preguntar: true,
          problemas: [],
          sigue_funcionando: [],
          no_funciona: [],
          url_publica: "https://ci.test",
          fuente_id: "f-1",
        },
      };
    if (ruta.includes("/explotacion/preguntas")) return { datos: [] };
    if (ruta.includes("/analitica/token")) return { datos: { token: "t" } };
    return { datos: [] };
  }),
  salvoCancelacion: (f: (e: unknown) => void) => f,
  ErrorApi: class extends Error {},
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

afterEach(() => vi.unstubAllGlobals());

describe("la aclaración de una pregunta ambigua", () => {
  it("enseña las opciones y pulsar una la devuelve", () => {
    const alAclarar = vi.fn();
    render(
      <RespuestaAnalitica
        payload={{
          type: "aclaracion",
          title: "",
          data: [],
          preguntas: [
            {
              texto: "¿A qué tipo de cuentas te refieres?",
              opciones: ["Cuentas de cliente", "Cuentas contables"],
            },
          ],
        }}
        alAclarar={alAclarar}
      />,
    );
    expect(
      screen.getByText("¿A qué tipo de cuentas te refieres?"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Sin resultados.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Cuentas de cliente" }));
    expect(alAclarar).toHaveBeenCalledWith("Cuentas de cliente");
  });
});

describe("guardar una pregunta que ha funcionado", () => {
  it("la guarda con su texto y su título", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          text: "Importe por etapa",
          payload: {
            type: "table",
            title: "Importe por etapa",
            data: [{ etapa: "Negociación", total: 3 }],
          },
        }),
      })),
    );
    render(<Explotacion />);
    const caja = await screen.findByRole("textbox", {
      name: "explotacion.placeholder",
    });
    fireEvent.change(caja, { target: { value: "¿Importe por etapa?" } });
    fireEvent.click(
      screen.getByRole("button", { name: "explotacion.preguntar" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /explotacion\.guardar$/ }),
    );
    await waitFor(() =>
      expect(llamar).toHaveBeenCalledWith("/api/v1/explotacion/preguntas", {
        metodo: "POST",
        cuerpo: {
          clave: "importe-por-etapa",
          titulo: "Importe por etapa",
          pregunta: "¿Importe por etapa?",
        },
      }),
    );
  });
});
