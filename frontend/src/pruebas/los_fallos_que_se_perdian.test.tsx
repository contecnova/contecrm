/**
 * Fallos que se perdían y una voz que hablaba otro idioma (auditoría
 * 13-11-2026, UX-29, UX-30 y UX-31).
 *
 *   · UX-29: simular el mapa de territorios fallaba en silencio si el mapa ya
 *     estaba cargado: el error iba a un sitio que sólo se pintaba con el mapa
 *     vacío;
 *   · UX-30: en ALM, el fallo al pedir los entornos se tragaba y el
 *     desplegable con uno solo se leía como «sólo hay uno»;
 *   · UX-31: la voz del asistente seguía la localización del tenant, no el
 *     idioma en que están escritos los textos.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { idiomaDeVoz } from "@/lib/formato";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

async function conApi(
  responder: (ruta: string, opciones?: { metodo?: string }) => unknown,
) {
  vi.resetModules();
  vi.doMock("@/lib/api", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/api");
    return {
      ...real,
      llamar: async (ruta: string, opciones?: { metodo?: string }) => ({
        datos: await responder(ruta, opciones),
        version: null,
        retenidos: [],
        enmascarados: [],
      }),
    };
  });
  const { ErrorApi } = await import("@/lib/api");
  return ErrorApi;
}

describe("UX-29: simular con el mapa ya cargado", () => {
  it("el fallo de simular se dice junto al botón y se puede reintentar", async () => {
    let falla = true;
    const ErrorApi = await conApi((ruta) => {
      if (ruta.startsWith("/api/v1/territorios/simular")) {
        if (falla)
          throw new ErrorApi(503, "simular.caido", "No disponible", null, "El simulador no contesta");
        return {
          cuentas: 1,
          cambian: [],
          se_quedan: 1,
          sin_territorio: [],
          solapes: [],
          seguro_publicar: true,
        };
      }
      if (ruta.startsWith("/api/v1/territorios/excepciones")) return null;
      if (ruta.startsWith("/api/v1/territorios"))
        return { items: [{ id: "t-1", clave: "norte", nombre: "Norte", prioridad: 1, criterios: [] }] };
      if (ruta.startsWith("/api/v1/accounts")) return { items: [{ id: "a-1" }] };
      return null;
    });
    const { Territorios } = await import("@/paginas/Territorios");
    const u = userEvent.setup();
    render(
      <MemoryRouter>
        <Territorios />
      </MemoryRouter>,
    );
    await screen.findByText("Norte");
    await u.click(screen.getByRole("button", { name: "territorios.simular" }));

    // Con el mapa a la vista —no en una pantalla de error que lo tape—.
    expect(await screen.findByText("El simulador no contesta")).toBeInTheDocument();
    expect(screen.getByText("Norte")).toBeInTheDocument();

    falla = false;
    await u.click(screen.getByRole("button", { name: "app.reintentar" }));
    expect(await screen.findByText("territorios.seguro")).toBeInTheDocument();
    expect(screen.queryByText("El simulador no contesta")).toBeNull();
  });
});

describe("UX-30: los entornos de ALM", () => {
  it("si no se pueden pedir, se dice y se puede reintentar", async () => {
    let falla = true;
    const ErrorApi = await conApi((ruta) => {
      if (ruta === "/api/v1/entornos") {
        if (falla) throw new ErrorApi(0, "", "", null, "");
        return { items: [{ nombre: "pruebas", orden: 1, es_produccion: false }] };
      }
      return {};
    });
    const { Alm } = await import("@/paginas/Alm");
    const u = userEvent.setup();
    render(
      <MemoryRouter>
        <Alm />
      </MemoryRouter>,
    );
    const aviso = await screen.findByRole("alert");
    expect(aviso).toHaveTextContent("cargaSecundaria.falloDe");

    falla = false;
    await u.click(screen.getByRole("button", { name: "app.reintentar" }));
    expect(await screen.findByRole("option", { name: "pruebas" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("UX-31: el idioma de la voz", () => {
  it("es el de los textos; la localización sólo afina la variante del mismo idioma", () => {
    // Un tenant en Portugal con la interfaz en castellano: se habla castellano.
    expect(idiomaDeVoz("es", "pt-PT")).toBe("es");
    // En México, castellano de México: la variante sí ayuda a reconocer.
    expect(idiomaDeVoz("es", "es-MX")).toBe("es-MX");
    expect(idiomaDeVoz("es-ES", "es-AR")).toBe("es-AR");
    expect(idiomaDeVoz("", "en-US")).toBe("es");
  });
});
