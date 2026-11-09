/**
 * El cliente ve sus encargos en el portal (CRM-00.04.05.06).
 *
 * Se piden con SU sesión —el token del portal—, sin pasar ninguna cuenta: la
 * cuenta sale del token en el servidor. Y el seguimiento de cada uno se abre
 * en el sitio, con sus hitos y sus incidencias.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pedidas: { ruta: string; auth: string }[] = [];
let respuestas: Record<string, unknown> = {};

vi.stubGlobal(
  "fetch",
  vi.fn(async (url: string, init?: RequestInit) => {
    const ruta = String(url);
    const cabeceras = (init?.headers ?? {}) as Record<string, string>;
    pedidas.push({ ruta, auth: cabeceras.Authorization ?? "" });
    const clave = Object.keys(respuestas)
      .filter((k) => ruta.includes(k))
      .sort((a, b) => b.length - a.length)[0];
    const cuerpo = clave ? respuestas[clave] : [];
    return {
      ok: true,
      status: 200,
      json: async () => cuerpo,
      text: async () => JSON.stringify(cuerpo),
    } as unknown as Response;
  }),
);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

const { Portal } = await import("@/paginas/Portal");

describe("los encargos en el portal", () => {
  beforeEach(() => {
    pedidas.length = 0;
    window.history.replaceState({}, "", "/portal?t=enlace-del-correo");
    respuestas = {
      "/portal/sesion": {
        token: "tk-portal",
        nivel: "cuenta",
        secciones: ["casos", "encargos"],
      },
      "/portal/mi/encargos": [
        {
          id: "e-1",
          referencia: "TESTIGO-E1",
          referencia_transportista: "GLS-9",
          proveedor: "mensajeria",
          estado: "en_entrega",
          prometido_para: "2026-11-01T10:00:00Z",
          completado_at: null,
          va_tarde: true,
        },
      ],
      "/portal/mi/encargos/e-1/seguimiento": {
        hitos: [
          {
            estado: "en_entrega",
            descripcion: "TESTIGO-en-reparto",
            lugar: "Madrid",
            at: "2026-11-02T09:00:00Z",
          },
        ],
        incidencias: [
          { tipo: "retraso", abierta: true, descripcion: "Ausente" },
        ],
        va_tarde: true,
        sin_novedad: false,
      },
    };
  });

  it("lista los suyos con su token y abre el seguimiento", async () => {
    render(<Portal />);
    expect(await screen.findByText(/TESTIGO-E1/)).toBeInTheDocument();
    expect(screen.getByText("portalEncargos.vaTarde")).toBeInTheDocument();
    const lista = pedidas.find((p) => p.ruta.endsWith("/portal/mi/encargos"));
    // Con su sesión, y sin ninguna cuenta en la dirección: la pone el token.
    expect(lista?.auth).toBe("Bearer tk-portal");
    expect(lista?.ruta).not.toContain("cuenta_id");

    await userEvent.click(screen.getByText("portalEncargos.verSeguimiento"));
    expect(await screen.findByText(/TESTIGO-en-reparto/)).toBeInTheDocument();
    expect(
      screen.getByText(/portalEncargos\.incidenciaAbierta.*Ausente/),
    ).toBeInTheDocument();
  });

  it("sin la sección, ni se piden", async () => {
    respuestas["/portal/sesion"] = {
      token: "tk-portal",
      nivel: "propio",
      secciones: ["casos"],
    };
    render(<Portal />);
    await waitFor(() =>
      expect(pedidas.some((p) => p.ruta.includes("/portal/mi/casos"))).toBe(
        true,
      ),
    );
    expect(pedidas.some((p) => p.ruta.includes("/mi/encargos"))).toBe(false);
  });
});
