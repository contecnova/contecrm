/**
 * El enlace del correo del portal de partner (CRM-03.04.01.02).
 *
 * Lo que no se puede romper: que abrir la página NO canjee —el enlace es de un
 * solo uso y los escáneres de correo lo abren—, que el canje vaya sin cookie y
 * con el tenant y el token del enlace, que un enlace usado o caducado se diga
 * como tal y deje pedir otro, y que con la sesión que devuelve el canje el
 * partner vea sus registros y registre uno, con la sesión en la cabecera y sin
 * cookie (COB-14).
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PortalPartner } from "@/paginas/PortalPartner";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

const TENANT = "8d0f6f2e-2b55-4a37-9a51-6f0f1d1c0a01";
const TOKEN = "token-de-prueba-0123456789";
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

describe("portal de partner desde el correo", () => {
  beforeEach(() => {
    peticiones = [];
    window.history.pushState(
      {},
      "",
      `/portal-partner?tenant=${TENANT}&t=${TOKEN}`,
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("abrirla no canjea; pulsar canjea sin cookie y confirma el acceso", async () => {
    responder({
      "/api/v1/portal-partner/canjear": {
        status: 200,
        cuerpo: {
          token: "sesion-del-partner",
          caduca_en_s: 3600,
          acceso_id: "a",
          partner_id: "p",
          nivel: "comercial",
        },
      },
      "/api/v1/portal-partner/mis-registros": {
        status: 200,
        cuerpo: { registros: [] },
      },
    });
    render(<PortalPartner />);
    expect(
      screen.getByRole("heading", { level: 1, name: "portalPartner.titulo" }),
    ).toBeInTheDocument();
    expect(peticiones).toHaveLength(0);

    await userEvent.click(
      screen.getByRole("button", { name: /portalPartner\.entrar/ }),
    );

    expect(
      await screen.findByText("portalPartner.confirmado"),
    ).toBeInTheDocument();
    // Con la sesión se piden sus registros: en la cabecera y sin cookie.
    expect(
      await screen.findByText("portalPartner.sinRegistros"),
    ).toBeInTheDocument();
    expect(peticiones.map((p) => p.url)).toEqual([
      "/api/v1/portal-partner/canjear",
      "/api/v1/portal-partner/mis-registros",
    ]);
    const lista = peticiones[1]!.init;
    expect(lista.credentials).toBe("omit");
    expect((lista.headers as Record<string, string>).Authorization).toBe(
      "Bearer sesion-del-partner",
    );
    expect(peticiones[0]!.init.method).toBe("POST");
    expect(peticiones[0]!.init.credentials).toBe("omit");
    expect(JSON.parse(String(peticiones[0]!.init.body))).toEqual({
      tenant: TENANT,
      token: TOKEN,
    });
    // El token gastado sale de la dirección.
    expect(window.location.search).toBe("");
    // Y el foco va al resultado.
    await waitFor(() =>
      expect(document.activeElement).toHaveTextContent(
        "portalPartner.confirmado",
      ),
    );
  });

  it("registrar una oportunidad exige NIF o dominio y recarga la lista", async () => {
    responder({
      "/api/v1/portal-partner/canjear": {
        status: 200,
        cuerpo: { token: "s", caduca_en_s: 3600, acceso_id: "a", partner_id: "p", nivel: "" },
      },
      "/api/v1/portal-partner/mis-registros": {
        status: 200,
        cuerpo: { registros: [] },
      },
      "/api/v1/portal-partner/registros": {
        status: 201,
        cuerpo: { id: "r1", estado: "pendiente", hay_conflicto: false },
      },
    });
    const usuario = userEvent.setup();
    render(<PortalPartner />);
    await usuario.click(
      screen.getByRole("button", { name: /portalPartner\.entrar/ }),
    );
    await screen.findByText("portalPartner.sinRegistros");

    await usuario.type(screen.getByLabelText("portalPartner.cliente"), "Cliente Uno");
    const registrar = screen.getByRole("button", {
      name: "portalPartner.enviarRegistro",
    });
    // Sin NIF ni dominio no se envía, y el motivo está escrito junto a los campos.
    expect(registrar).toBeDisabled();
    expect(screen.getByText("portalPartner.identificador")).toBeInTheDocument();

    await usuario.type(screen.getByLabelText("portalPartner.nif"), "B12345678");
    await usuario.click(registrar);

    expect(await screen.findByRole("status")).toHaveTextContent(
      "portalPartner.registrado",
    );
    const alta = peticiones.find((p) =>
      p.url.endsWith("/api/v1/portal-partner/registros"),
    )!;
    expect(alta.init.method).toBe("POST");
    expect(JSON.parse(String(alta.init.body))).toMatchObject({
      cliente_nombre: "Cliente Uno",
      nif: "B12345678",
      dominio: null,
    });
    // Y la lista se vuelve a pedir.
    await waitFor(() =>
      expect(
        peticiones.filter((p) => p.url.endsWith("/mis-registros")),
      ).toHaveLength(2),
    );
  });

  it("un enlace usado o caducado se dice, y deja pedir otro", async () => {
    responder({
      "/api/v1/portal-partner/canjear": {
        status: 401,
        cuerpo: {
          error_code: "partners.enlace_no_valido",
          title: "No autenticado",
          detail: "Enlace no válido",
        },
      },
      "/api/v1/portal-partner/entrar": {
        status: 200,
        cuerpo: { enviado: true },
      },
    });
    const usuario = userEvent.setup();
    render(<PortalPartner />);
    await usuario.click(
      screen.getByRole("button", { name: /portalPartner\.entrar/ }),
    );
    expect(await screen.findByText("portalPartner.invalido")).toBeInTheDocument();
    expect(
      screen.getByText("portalPartner.invalidoDetalle"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /portalPartner\.entrar/ }),
    ).not.toBeInTheDocument();

    await usuario.type(
      screen.getByLabelText("portalPartner.email"),
      "ana@partner.es",
    );
    await usuario.click(
      screen.getByRole("button", { name: "portalPartner.mandar" }),
    );
    expect(await screen.findByText("portalPartner.pedido")).toBeInTheDocument();
    const pedir = peticiones[1]!;
    expect(pedir.url).toBe("/api/v1/portal-partner/entrar");
    expect(pedir.init.credentials).toBe("omit");
    expect(JSON.parse(String(pedir.init.body))).toEqual({
      tenant: TENANT,
      email: "ana@partner.es",
    });
  });

  it("un fallo que no es del enlace se enseña y deja reintentar", async () => {
    responder({
      "/api/v1/portal-partner/canjear": {
        status: 429,
        cuerpo: {
          error_code: "limite",
          title: "Demasiadas peticiones",
          detail: "Demasiados intentos desde esta conexión.",
        },
      },
    });
    render(<PortalPartner />);
    await userEvent.click(
      screen.getByRole("button", { name: /portalPartner\.entrar/ }),
    );
    // Con la frase del servidor (sale también en el detalle técnico).
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Demasiados intentos desde esta conexión.",
    );
    expect(
      screen.getByRole("button", { name: /portalPartner\.entrar/ }),
    ).toBeEnabled();
  });

  it("sin token ni tenant en el enlace no llama a nada y lo explica", () => {
    window.history.pushState({}, "", "/portal-partner");
    responder({});
    render(<PortalPartner />);
    expect(screen.getByText("portalPartner.invalido")).toBeInTheDocument();
    expect(screen.getByText("portalPartner.incompleto")).toBeInTheDocument();
    expect(screen.queryByLabelText("portalPartner.email")).not.toBeInTheDocument();
    expect(peticiones).toHaveLength(0);
  });
});
