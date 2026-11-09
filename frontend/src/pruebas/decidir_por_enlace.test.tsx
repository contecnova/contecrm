/**
 * La página pública para decidir una aprobación desde el correo
 * (CRM-00.03.05.12).
 *
 * Tres cosas que no se pueden romper: que abrirla NO decida —los escáneres de
 * correo abren los enlaces—, que pida a la API SIN cookie —una sesión caducada
 * en el navegador haría contestar «tu sesión ha caducado» a quien no necesita
 * ninguna— y que un enlace que no sirve se diga como tal, sin más detalle.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DecidirPorEnlace } from "@/paginas/DecidirPorEnlace";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

const TOKEN = "un-token-largo-de-prueba-0123456789";
let peticiones: { url: string; init: RequestInit }[] = [];

function responder(
  porRuta: Record<string, { status: number; cuerpo: unknown }>,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      peticiones.push({ url, init });
      const ruta = Object.keys(porRuta).find((r) => url.endsWith(r));
      const r = ruta ? porRuta[ruta]! : { status: 404, cuerpo: {} };
      return new Response(JSON.stringify(r.cuerpo), { status: r.status });
    }),
  );
}

const VISTA = {
  titulo: "Descuento del 22 % a Acme",
  objeto: "oportunidad",
  etapa: "Jefe",
  datos: { descuento_pct: 22, cuenta: "Acme" },
  caduca_at: "2026-11-12T10:00:00+00:00",
  decisiones: ["aprobar", "rechazar", "pedir_cambios"],
};

describe("decidir desde el correo", () => {
  beforeEach(() => {
    peticiones = [];
    window.history.pushState({}, "", `/decidir?t=${TOKEN}`);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("abrirla enseña qué se decide y no decide nada", async () => {
    responder({
      "/api/v1/enlace-de-aprobacion/ver": { status: 200, cuerpo: VISTA },
    });
    render(<DecidirPorEnlace />);
    expect(await screen.findByText(VISTA.titulo)).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(peticiones.map((p) => p.url)).toEqual([
      "/api/v1/enlace-de-aprobacion/ver",
    ]);
    // Sin cookie y con el token en el cuerpo, no en la dirección.
    expect(peticiones[0]!.init.credentials).toBe("omit");
    expect(JSON.parse(String(peticiones[0]!.init.body))).toEqual({
      token: TOKEN,
    });
  });

  it("pedir cambios exige decir cuáles; aprobar no", async () => {
    responder({
      "/api/v1/enlace-de-aprobacion/ver": { status: 200, cuerpo: VISTA },
      "/api/v1/enlace-de-aprobacion/decidir": {
        status: 200,
        cuerpo: { decision: "aprobar", estado: "aprobada" },
      },
    });
    const usuario = userEvent.setup();
    render(<DecidirPorEnlace />);
    await screen.findByText(VISTA.titulo);
    expect(
      screen.getByRole("button", { name: /decidirPorEnlace\.pedirCambios/ }),
    ).toBeDisabled();
    await usuario.click(
      screen.getByRole("button", { name: /decidirPorEnlace\.aprobar/ }),
    );
    expect(
      await screen.findByText("decidirPorEnlace.hecho.aprobar"),
    ).toBeInTheDocument();
    const decidir = peticiones.find((p) => p.url.endsWith("/decidir"))!;
    expect(decidir.init.credentials).toBe("omit");
    expect(JSON.parse(String(decidir.init.body))).toEqual({
      token: TOKEN,
      decision: "aprobar",
      comentario: "",
    });
  });

  it("un enlace que no sirve lo dice, sin más", async () => {
    responder({
      "/api/v1/enlace-de-aprobacion/ver": {
        status: 401,
        cuerpo: { error_code: "aprobacion.enlace_invalido" },
      },
    });
    render(<DecidirPorEnlace />);
    expect(
      await screen.findByText("decidirPorEnlace.invalido"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /aprobar/ }),
      ).not.toBeInTheDocument(),
    );
  });

  it("sin token ni siquiera pregunta", () => {
    window.history.pushState({}, "", "/decidir");
    responder({});
    render(<DecidirPorEnlace />);
    expect(screen.getByText("decidirPorEnlace.invalido")).toBeInTheDocument();
    expect(peticiones).toHaveLength(0);
  });
});
