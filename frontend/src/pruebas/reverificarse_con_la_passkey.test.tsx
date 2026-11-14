/**
 * Volver a verificarse con la passkey, sin salir (auditoría 13-11-2026, UX-28).
 *
 * El diálogo sólo pedía el código de la app: quien tenía únicamente passkeys
 * leía «no tienes con qué verificarte» y tenía que salir y volver a entrar.
 * Lo que fija esto:
 *
 *   · se ofrece lo que la persona TIENE, según `/factores/nivel`;
 *   · con la llave se firma el reto de reverificar y la operación sigue;
 *   · cancelar el diálogo del sistema no es un fallo;
 *   · sin ninguno de los dos se dice, en vez de pedir un código imposible.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const pedidas: { ruta: string; cuerpo?: unknown }[] = [];
let abrir: (() => Promise<boolean>) | null = null;

async function montar(
  nivel: { tiene_app: boolean; tiene_passkey: boolean },
  firmar: () => Promise<unknown> = async () => ({ id: "mia" }),
) {
  vi.resetModules();
  pedidas.length = 0;
  abrir = null;
  vi.doMock("@/lib/api", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/api");
    return {
      ...real,
      registrarReverificacion: (f: (() => Promise<boolean>) | null) => {
        abrir = f;
      },
      llamar: async (ruta: string, opciones?: { cuerpo?: unknown }) => {
        pedidas.push({ ruta, cuerpo: opciones?.cuerpo });
        if (ruta.endsWith("/factores/nivel")) return { datos: nivel };
        if (ruta.endsWith("/passkeys/reverificar"))
          return { datos: { challenge: "reto" } };
        return { datos: { usar_este_token: true } };
      },
    };
  });
  vi.doMock("@/lib/webauthn", () => ({
    admitePasskeys: () => true,
    firmarConPasskey: firmar,
  }));
  const { Reverificacion } = await import("@/componentes/Reverificacion");
  render(
    <MemoryRouter>
      <Reverificacion />
    </MemoryRouter>,
  );
  await waitFor(() => expect(abrir).not.toBeNull());
  let resultado: Promise<boolean> = Promise.resolve(false);
  act(() => {
    resultado = abrir!();
  });
  return () => resultado;
}

describe("reverificarse con la passkey", () => {
  it("quien sólo tiene passkey firma y la operación sigue", async () => {
    const resultado = await montar({ tiene_app: false, tiene_passkey: true });
    const boton = await screen.findByRole("button", {
      name: "reverificar.conLlave",
    });
    await waitFor(() => expect(boton).toHaveFocus());
    // No se le pide un código que no tiene con qué generar.
    expect(screen.queryByLabelText("reverificar.codigo")).toBeNull();

    await userEvent.setup().click(boton);
    expect(await resultado()).toBe(true);
    expect(pedidas.map((p) => p.ruta)).toEqual([
      "/api/v1/factores/nivel",
      "/api/v1/auth/passkeys/reverificar",
      "/api/v1/auth/passkeys/reverificar/confirmar",
    ]);
    expect(pedidas.at(-1)?.cuerpo).toEqual({ respuesta: { id: "mia" } });
  });

  it("con las dos, se ofrecen las dos", async () => {
    await montar({ tiene_app: true, tiene_passkey: true });
    expect(
      await screen.findByRole("button", { name: "reverificar.conLlave" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("reverificar.codigo")).toBeInTheDocument();
    expect(screen.getByText("reverificar.oCodigo")).toBeInTheDocument();
  });

  it("cancelar el diálogo del sistema no es un fallo", async () => {
    await montar({ tiene_app: false, tiene_passkey: true }, async () => {
      throw new DOMException("cancelado", "NotAllowedError");
    });
    await userEvent
      .setup()
      .click(
        await screen.findByRole("button", { name: "reverificar.conLlave" }),
      );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "reverificar.conLlave" }),
      ).toBeEnabled(),
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(pedidas.some((p) => p.ruta.endsWith("/confirmar"))).toBe(false);
  });

  it("sin app ni passkey se dice, sin pedir nada", async () => {
    await montar({ tiene_app: false, tiene_passkey: false });
    expect(
      await screen.findByText("reverificar.sinFactor"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("reverificar.codigo")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "reverificar.conLlave" }),
    ).toBeNull();
  });
});
