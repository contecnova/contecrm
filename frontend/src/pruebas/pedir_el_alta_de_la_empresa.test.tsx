/**
 * Pedir el alta de una empresa desde la pantalla de entrar (auditoría
 * 13-11-2026, COB-15).
 *
 * `POST /alta` existía y el enlace que manda ya se confirmaba aquí, pero no
 * había dónde PEDIRLO. Lo que fija esto:
 *
 *   · se llega desde «Entrar», que es la única pantalla que ve quien no tiene
 *     cuenta;
 *   · se manda lo que pide el contrato, sin cookie y sin cola;
 *   · el resultado no dice si el identificador estaba libre —la ruta tampoco—;
 *   · lo que el servidor rechaza (la forma del identificador) se dice con su
 *     frase.
 */
import { render, screen } from "@testing-library/react";
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

const llamadas: { ruta: string; opciones?: Record<string, unknown> }[] = [];
let contestar: () => unknown = () => ({ enviado: true });

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

async function rellenar() {
  const u = userEvent.setup();
  render(<Entrar alEntrar={() => undefined} />);
  await u.click(screen.getByRole("button", { name: "entrar.pedirAlta.abrir" }));
  await u.type(screen.getByLabelText("entrar.pedirAlta.empresa"), "ACME Industrial");
  await u.type(screen.getByLabelText("entrar.pedirAlta.slug"), " acme ");
  await u.type(screen.getByLabelText("entrar.pedirAlta.nombre"), "Ana Pérez");
  await u.type(screen.getByLabelText("entrar.pedirAlta.email"), "ana@acme.es");
  await u.click(screen.getByRole("button", { name: "entrar.pedirAlta.enviar" }));
}

describe("pedir el alta de una empresa", () => {
  beforeEach(() => {
    llamadas.length = 0;
    contestar = () => ({ enviado: true });
    window.history.pushState({}, "", "/");
  });

  it("manda lo que pide el contrato y dice que llegará un enlace", async () => {
    await rellenar();
    expect(await screen.findByText("entrar.pedirAlta.enviado")).toBeInTheDocument();
    expect(llamadas).toHaveLength(1);
    expect(llamadas[0]!.ruta).toBe("/api/v1/alta");
    expect(llamadas[0]!.opciones).toMatchObject({
      metodo: "POST",
      cuerpo: {
        slug: "acme",
        nombre_empresa: "ACME Industrial",
        nombre: "Ana Pérez",
        email: "ana@acme.es",
      },
      sinCookie: true,
      encolable: false,
    });
    // El resultado recibe el foco: el formulario ha desaparecido.
    expect(screen.getByRole("status")).toHaveFocus();
  });

  it("lo que rechaza el servidor se dice con su frase", async () => {
    contestar = () => {
      throw new ErrorApi(
        422,
        "tenant.slug_invalido",
        "Datos no válidos",
        null,
        "El identificador debe tener entre 2 y 63 caracteres",
      );
    };
    await rellenar();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "El identificador debe tener entre 2 y 63 caracteres",
    );
    expect(screen.queryByText("entrar.pedirAlta.enviado")).toBeNull();
  });
});
