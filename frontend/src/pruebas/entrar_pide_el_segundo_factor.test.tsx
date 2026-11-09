/**
 * La pantalla de entrar pide el código del segundo factor cuando el servidor
 * lo exige, y lo manda (CRM-00.05.01.06, CRM-00.05.01.21).
 *
 * Hasta el 09-11-2026 no lo mandaba nunca: con el segundo factor exigido por
 * la empresa, por el rol o por el riesgo, nadie podía entrar desde el
 * navegador. Lo cazó el recorrido de las capacidades sin pantalla.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string) => clave,
    i18n: { language: "es", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: unknown }) => children ?? null,
  initReactI18next: { type: "3rdParty", init: () => undefined },
}));

const enviados: Record<string, unknown>[] = [];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(
      async (ruta: string, opciones?: { cuerpo?: Record<string, unknown> }) => {
        if (ruta !== "/api/v1/sesion/entrar")
          return { datos: [], retenidos: [] };
        const cuerpo = opciones?.cuerpo ?? {};
        enviados.push(cuerpo);
        if (!cuerpo.codigo_mfa) {
          throw new real.ErrorApi(
            401,
            "auth.mfa_requerida",
            "Falta el código",
            null,
          );
        }
        return { datos: {}, retenidos: [] };
      },
    ),
  };
});

describe("entrar con el segundo factor exigido", () => {
  beforeEach(() => {
    enviados.length = 0;
  });

  it("pide el código, lo manda con la huella y entra", async () => {
    const { Entrar } = await import("@/paginas/Entrar");
    const alEntrar = vi.fn();
    render(<Entrar alEntrar={alEntrar} />);

    const campos = document.querySelectorAll("input");
    for (const campo of campos) {
      if (campo.type === "password") await userEvent.type(campo, "secreta");
      else if (campo.type === "email")
        await userEvent.type(campo, "ana@ejemplo.com");
      else if (!campo.value) await userEvent.type(campo, "empresa");
    }
    await userEvent.click(
      document.querySelector('button[type="submit"]') as Element,
    );

    const codigo = await screen.findByLabelText("entrar.codigo");
    expect(alEntrar).not.toHaveBeenCalled();
    await userEvent.type(codigo, "123456");
    await userEvent.click(
      document.querySelector('button[type="submit"]') as Element,
    );

    await waitFor(() => expect(alEntrar).toHaveBeenCalled());
    const ultimo = enviados[enviados.length - 1] ?? {};
    expect(ultimo.codigo_mfa).toBe("123456");
    expect(typeof ultimo.huella_dispositivo).toBe("string");
  });
});
