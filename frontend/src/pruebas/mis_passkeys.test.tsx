/**
 * Dar de alta y quitar las passkeys propias (CRM-00.05.01.23).
 *
 * Lo que no se puede romper: que el alta sean las dos llamadas del servidor
 * con la llave del navegador en medio —y el nombre en la segunda—; que si la
 * persona no se reverifica (SEC-4) se le diga por qué y no salga un error
 * crudo; que cancelar el diálogo del sistema no se pinte como un fallo; y que
 * quitar pregunte antes, con el foco en «Cancelar», y borre la que es.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MisPasskeys } from "@/componentes/MisPasskeys";
import { ErrorApi } from "@/lib/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos && "nombre" in datos ? `${clave}:${String(datos.nombre)}` : clave,
  }),
}));

const llamadas: { ruta: string; opciones?: Record<string, unknown> }[] = [];
let respuestas: Record<string, () => unknown> = {};

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string, opciones?: Record<string, unknown>) => {
      llamadas.push({ ruta, opciones });
      const clave = `${String(opciones?.metodo ?? "GET")} ${ruta}`;
      const responder = respuestas[clave];
      if (!responder) throw new Error(`sin respuesta para ${clave}`);
      return { datos: responder(), version: null, retenidos: [], enmascarados: [] };
    }),
  };
});

const crearPasskey = vi.fn();
vi.mock("@/lib/webauthn", () => ({
  admitePasskeys: () => true,
  crearPasskey: (opciones: unknown) => crearPasskey(opciones),
}));

const LLAVES = [
  {
    id: "11111111-1111-1111-1111-111111111111",
    nombre: "Portátil",
    creada_at: "2026-11-01T09:00:00+00:00",
    ultimo_uso_at: null,
  },
];

describe("mis passkeys", () => {
  beforeEach(() => {
    llamadas.length = 0;
    respuestas = {};
    crearPasskey.mockReset();
  });

  it("lista las que hay, con su nombre y si se han usado", () => {
    render(<MisPasskeys passkeys={LLAVES} alCambiar={() => undefined} />);
    expect(screen.getByText("Portátil")).toBeInTheDocument();
    expect(screen.getByText(/seguridad\.passkeys\.sinUsar/)).toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: "seguridad.passkeys.titulo" }),
    ).toBeInTheDocument();
  });

  it("dar de alta: opciones, llave del navegador y guardarla con su nombre", async () => {
    const opciones = { challenge: "abc", rp: { id: "crm" } };
    const firmada = { id: "cred", response: {} };
    respuestas = {
      "POST /api/v1/auth/passkeys": () => opciones,
      "POST /api/v1/auth/passkeys/confirmar": () => ({ id: "n", nombre: "Móvil" }),
    };
    crearPasskey.mockResolvedValue(firmada);
    const alCambiar = vi.fn();
    const usuario = userEvent.setup();
    render(<MisPasskeys passkeys={[]} alCambiar={alCambiar} />);

    await usuario.type(
      screen.getByLabelText("seguridad.passkeys.nombre"),
      "  Móvil ",
    );
    await usuario.click(
      screen.getByRole("button", { name: "seguridad.passkeys.anadir" }),
    );

    expect(
      await screen.findByText("seguridad.passkeys.anadida:Móvil"),
    ).toBeInTheDocument();
    expect(crearPasskey).toHaveBeenCalledWith(opciones);
    expect(llamadas.map((l) => l.ruta)).toEqual([
      "/api/v1/auth/passkeys",
      "/api/v1/auth/passkeys/confirmar",
    ]);
    expect(llamadas[1]!.opciones?.cuerpo).toEqual({
      respuesta: firmada,
      nombre: "Móvil",
    });
    // Un alta a medias no se encola sin red: el reto caduca en minutos.
    expect(llamadas.every((l) => l.opciones?.encolable === false)).toBe(true);
    expect(alCambiar).toHaveBeenCalledTimes(1);
  });

  it("sin reverificarse no se añade, y se dice por qué", async () => {
    respuestas = {
      "POST /api/v1/auth/passkeys": () => {
        throw new ErrorApi(401, "stepup.requerido", "Reverifícate", null);
      },
    };
    const alCambiar = vi.fn();
    render(<MisPasskeys passkeys={LLAVES} tieneApp alCambiar={alCambiar} />);
    await userEvent.click(
      screen.getByRole("button", { name: "seguridad.passkeys.anadir" }),
    );
    expect(
      await screen.findByText("seguridad.passkeys.faltaVerificarte"),
    ).toBeInTheDocument();
    expect(crearPasskey).not.toHaveBeenCalled();
    expect(alCambiar).not.toHaveBeenCalled();
  });

  it("sin la app, explica cómo verificarse con la passkey", async () => {
    respuestas = {
      "POST /api/v1/auth/passkeys": () => {
        throw new ErrorApi(401, "stepup.requerido", "Reverifícate", null);
      },
    };
    render(
      <MisPasskeys passkeys={LLAVES} tieneApp={false} alCambiar={() => undefined} />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "seguridad.passkeys.anadir" }),
    );
    expect(
      await screen.findByText("seguridad.passkeys.faltaVerificarteSinApp"),
    ).toBeInTheDocument();
  });

  it("cancelar el diálogo del sistema no es un fallo ni guarda nada", async () => {
    respuestas = { "POST /api/v1/auth/passkeys": () => ({ challenge: "x" }) };
    crearPasskey.mockRejectedValue(new DOMException("no", "NotAllowedError"));
    render(<MisPasskeys passkeys={[]} alCambiar={() => undefined} />);
    await userEvent.click(
      screen.getByRole("button", { name: "seguridad.passkeys.anadir" }),
    );
    expect(
      await screen.findByText("seguridad.passkeys.cancelada"),
    ).toBeInTheDocument();
    expect(llamadas.map((l) => l.ruta)).toEqual(["/api/v1/auth/passkeys"]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("un fallo del servidor al guardar se enseña con su frase", async () => {
    respuestas = {
      "POST /api/v1/auth/passkeys": () => ({ challenge: "x" }),
      "POST /api/v1/auth/passkeys/confirmar": () => {
        throw new ErrorApi(
          401,
          "passkey.registro_no_valido",
          "No autenticado",
          null,
          "Esa llave no se ha podido comprobar",
        );
      },
    };
    crearPasskey.mockResolvedValue({ id: "c" });
    render(<MisPasskeys passkeys={[]} alCambiar={() => undefined} />);
    await userEvent.click(
      screen.getByRole("button", { name: "seguridad.passkeys.anadir" }),
    );
    expect(
      await screen.findByText(/Esa llave no se ha podido comprobar/),
    ).toBeInTheDocument();
  });

  it("quitar pregunta antes, con el foco en cancelar, y borra la que es", async () => {
    respuestas = {
      [`DELETE /api/v1/auth/passkeys/${LLAVES[0]!.id}`]: () => undefined,
    };
    const alCambiar = vi.fn();
    const usuario = userEvent.setup();
    render(<MisPasskeys passkeys={LLAVES} tieneApp={false} alCambiar={alCambiar} />);

    await usuario.click(
      screen.getByRole("button", {
        name: "seguridad.passkeys.quitarLa:Portátil",
      }),
    );
    const pregunta = screen.getByRole("alertdialog");
    // Es la última llave y no hay app: el aviso lo dice.
    expect(pregunta).toHaveTextContent("seguridad.passkeys.avisoUltima");
    expect(document.activeElement).toHaveTextContent("modulo.cancelar");
    expect(llamadas).toHaveLength(0);

    await usuario.click(
      screen.getAllByRole("button", {
        name: "seguridad.passkeys.quitarLa:Portátil",
      })[1]!,
    );
    await waitFor(() => expect(alCambiar).toHaveBeenCalledTimes(1));
    expect(llamadas[0]!.ruta).toBe(`/api/v1/auth/passkeys/${LLAVES[0]!.id}`);
    expect(llamadas[0]!.opciones?.metodo).toBe("DELETE");
    expect(
      screen.getByText("seguridad.passkeys.quitada:Portátil"),
    ).toBeInTheDocument();
  });

  it("cancelar el borrado no llama a nada", async () => {
    render(<MisPasskeys passkeys={LLAVES} alCambiar={() => undefined} />);
    await userEvent.click(
      screen.getByRole("button", {
        name: "seguridad.passkeys.quitarLa:Portátil",
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "modulo.cancelar" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(llamadas).toHaveLength(0);
  });
});
