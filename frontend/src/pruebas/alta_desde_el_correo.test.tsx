/**
 * El enlace del correo del alta autoservicio, `/?alta=<token>`
 * (CRM-00.01.03.01).
 *
 * Hasta el 13-11-2026 el correo lo mandaba y ninguna pantalla lo leía. Lo que
 * no se puede romper: que abrir el enlace NO confirme —es de un solo uso y los
 * escáneres de correo lo abren—, que confirmar mande el token sin cookie, que
 * el éxito diga con qué organización se entra y lleve a entrar con ella
 * escrita, y que un enlace usado o caducado lo diga y no ofrezca reintentar.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos && "slug" in datos ? `${clave}:${String(datos.slug)}` : clave,
    i18n: { language: "es", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: unknown }) => children ?? null,
  initReactI18next: { type: "3rdParty", init: () => undefined },
}));

const llamadas: { ruta: string; opciones?: Record<string, unknown> }[] = [];
let contestar: () => unknown = () => ({});

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string, opciones?: Record<string, unknown>) => {
      llamadas.push({ ruta, opciones });
      return { datos: contestar(), version: null, retenidos: [], enmascarados: [] };
    }),
  };
});

import { ErrorApi } from "@/lib/api";
import { Entrar } from "@/paginas/Entrar";

const TOKEN = "token-del-alta-0123456789";

describe("confirmar el alta desde el correo", () => {
  beforeEach(() => {
    llamadas.length = 0;
    window.history.pushState({}, "", `/?alta=${TOKEN}`);
  });

  it("abrirla no confirma; pulsar confirma sin cookie y lleva a entrar", async () => {
    contestar = () => ({ tenant_id: "t1", slug: "acme", nombre: "ACME" });
    const usuario = userEvent.setup();
    render(<Entrar alEntrar={() => undefined} />);

    expect(
      screen.getByRole("heading", { name: "entrar.alta.titulo" }),
    ).toBeInTheDocument();
    expect(llamadas).toHaveLength(0);

    await usuario.click(
      screen.getByRole("button", { name: "entrar.alta.confirmar" }),
    );

    expect(
      await screen.findByText("entrar.alta.tuOrganizacion:acme"),
    ).toBeInTheDocument();
    expect(screen.getByText("entrar.alta.contrasena")).toBeInTheDocument();
    expect(llamadas).toHaveLength(1);
    expect(llamadas[0]!.ruta).toBe("/api/v1/alta/confirmar");
    expect(llamadas[0]!.opciones).toMatchObject({
      metodo: "POST",
      cuerpo: { token: TOKEN },
      sinCookie: true,
      encolable: false,
    });
    // El token gastado sale de la dirección.
    expect(window.location.search).toBe("");

    await usuario.click(
      screen.getByRole("button", { name: "entrar.alta.irAEntrar" }),
    );
    // La organización ya escrita: es lo que acaba de crear.
    expect(screen.getByLabelText("entrar.tenant")).toHaveValue("acme");
  });

  it("un enlace caducado lo dice y no deja reintentar con él", async () => {
    contestar = () => {
      throw new ErrorApi(
        422,
        "alta.enlace_caducado",
        "Datos no válidos",
        null,
        "Ese enlace ha caducado. Pida el alta otra vez.",
      );
    };
    render(<Entrar alEntrar={() => undefined} />);
    await userEvent.click(
      screen.getByRole("button", { name: "entrar.alta.confirmar" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "entrar.alta.errores.alta.enlace_caducado",
    );
    expect(
      screen.queryByRole("button", { name: "entrar.alta.confirmar" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "entrar.alta.irAEntrar" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(document.activeElement).toHaveTextContent(
        "entrar.alta.errores.alta.enlace_caducado",
      ),
    );
  });

  it("un enlace ya usado también, con su propio mensaje", async () => {
    contestar = () => {
      throw new ErrorApi(422, "alta.enlace_usado", "", null, "Ya se usó");
    };
    render(<Entrar alEntrar={() => undefined} />);
    await userEvent.click(
      screen.getByRole("button", { name: "entrar.alta.confirmar" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "entrar.alta.errores.alta.enlace_usado",
    );
  });

  it("sin red se puede reintentar", async () => {
    contestar = () => {
      throw new ErrorApi(0, "sin_red", "", null, "Failed to fetch");
    };
    render(<Entrar alEntrar={() => undefined} />);
    await userEvent.click(
      screen.getByRole("button", { name: "entrar.alta.confirmar" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "entrar.alta.errores.sin_red",
    );
    expect(
      screen.getByRole("button", { name: "entrar.alta.confirmar" }),
    ).toBeEnabled();
  });

  it("sin `?alta=` la entrada es la de siempre", () => {
    window.history.pushState({}, "", "/");
    render(<Entrar alEntrar={() => undefined} />);
    expect(
      screen.queryByRole("heading", { name: "entrar.alta.titulo" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("entrar.tenant")).toBeInTheDocument();
  });
});
