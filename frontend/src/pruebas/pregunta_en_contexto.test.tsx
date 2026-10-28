/**
 * Preguntar sobre el registro que se está mirando (CRM-05.01.04.09).
 *
 * La pregunta se hace delante del dato, que es donde se le ocurre a alguien:
 * obligar a irse a la pantalla de explotación y volver a escribir de qué
 * cuenta se habla es como se deja de preguntar.
 *
 * Lo que se exige aquí es lo único que no se negocia: **que el filtro se
 * vea**. El servidor lo añade —no lo sugiere— y devuelve la pregunta tal como
 * quedó, porque un número que parece de toda la empresa y es de una cuenta no
 * cuadra con nada en la reunión siguiente, y para cuando se descubre ya se ha
 * dicho en voz alta.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PreguntarSobreEsto } from "@/paginas/Ficha";

const llamar = vi.fn(async () => ({
  datos: {
    pregunta: "¿Cuánto hemos facturado aquí este año? (cuenta = Industrias del Ter)",
    filtro: "cuenta_id = 01a1…",
  },
}));

vi.mock("@/lib/api", () => ({
  llamar: (...args: unknown[]) => llamar(...(args as [])),
  salvoCancelacion: (f: (e: unknown) => void) => f,
  subir: vi.fn(),
  ErrorApi: class extends Error {},
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

describe("preguntar sobre este registro", () => {
  it("enseña el filtro con el que se contestó, no sólo la respuesta", async () => {
    render(<PreguntarSobreEsto objeto="cuenta" objetoId="01a1" />);
    await userEvent.type(
      screen.getByRole("textbox"),
      "¿Cuánto hemos facturado aquí?",
    );
    await userEvent.click(screen.getByRole("button", { name: /ficha\.preguntar/ }));
    const salida = await screen.findByTestId("pregunta-en-contexto");
    expect(salida.textContent).toContain("ficha.conFiltro");
    expect(salida.textContent).toContain("cuenta_id");
  });

  it("no pregunta en vacío: sin texto, el botón no deja", () => {
    render(<PreguntarSobreEsto objeto="cuenta" objetoId="01a1" />);
    expect(screen.getByRole("button", { name: /ficha\.preguntar/ })).toBeDisabled();
  });

  it("manda el registro que se está mirando, no sólo la pregunta", async () => {
    llamar.mockClear();
    render(<PreguntarSobreEsto objeto="oportunidad" objetoId="op-9" />);
    await userEvent.type(screen.getByRole("textbox"), "¿Y el margen?");
    await userEvent.click(screen.getByRole("button", { name: /ficha\.preguntar/ }));
    const [, opciones] = llamar.mock.calls[0] as unknown as [string, { cuerpo: unknown }];
    expect(opciones.cuerpo).toMatchObject({ objeto: "oportunidad", registro_id: "op-9" });
  });
});
