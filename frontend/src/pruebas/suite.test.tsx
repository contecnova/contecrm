/**
 * La consola de gobierno de la suite, PINTADA (CRM-00.01.07.06).
 *
 * Lo que esto cubre y el tipado no: que un aviso tenga salida. La pantalla
 * decía «hay 3 elementos en cuarentena» y ahí se acababa —ni cuáles, ni con
 * qué se mandaron, ni forma de reintentarlos— aunque las dos rutas llevaban en
 * el servidor desde el primer día. Un aviso sin salida enseña a quien lo lee a
 * dejar de mirarlo.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SuiteGobierno } from "@/paginas/Suite";

let respuestas: Record<string, unknown> = {};
const llamadas: { ruta: string; metodo?: string }[] = [];

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string, opciones?: { metodo?: string }) => {
    llamadas.push({ ruta, metodo: opciones?.metodo });
    const clave = Object.keys(respuestas)
      .filter((k) => ruta.startsWith(k))
      .sort((a, b) => b.length - a.length)[0];
    if (!clave) throw new Error(`sin respuesta preparada para ${ruta}`);
    return { datos: respuestas[clave] };
  }),
  salvoCancelacion: (fn: (e: unknown) => void) => fn,
}));

vi.mock("@/lib/permisos", () => ({
  usePuedeOperar: () => () => true,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

const PANEL_LIMPIO = {
  herramientas: [
    {
      herramienta: "contecmind",
      tipo: "contecmind",
      activa: true,
      estado: "al día",
      bajas_sin_aplicar: 0,
      ultimo_error: null,
    },
  ],
  cuarentena: 0,
  bajas_sin_aplicar: 0,
  en_verde: true,
  sin_herramientas: false,
};

const APARTADO = {
  id: "s-1",
  herramienta: "contecmind",
  objeto: "usuario",
  objeto_id: "u-1",
  operacion: "baja",
  intentos: 5,
  error: "HTTP 401: token caducado",
  carga: { email: "exempleado@cliente.com" },
  gravedad: "alta",
};

describe("la consola de gobierno de la suite", () => {
  beforeEach(() => {
    respuestas = {};
    llamadas.length = 0;
  });

  it("sin herramientas conectadas no dice «todo bien»", async () => {
    respuestas = {
      "/api/v1/suite/panel": {
        ...PANEL_LIMPIO,
        herramientas: [],
        sin_herramientas: true,
      },
    };
    render(<SuiteGobierno />);
    expect(await screen.findByText("suite.sinHerramientas")).toBeInTheDocument();
  });

  it("enseña las bajas sin aplicar como lo primero", async () => {
    respuestas = {
      "/api/v1/suite/panel": { ...PANEL_LIMPIO, bajas_sin_aplicar: 2 },
    };
    render(<SuiteGobierno />);
    expect(
      await screen.findByText(/suite\.bajasSinAplicar.*"cuantas":2/),
    ).toBeInTheDocument();
  });

  it("lo que está en cuarentena se ve, con lo que se mandó dentro", async () => {
    respuestas = {
      "/api/v1/suite/panel": { ...PANEL_LIMPIO, cuarentena: 1 },
      "/api/v1/suite/cuarentena": [APARTADO],
    };
    render(<SuiteGobierno />);
    // Sin esto, quien lo mira tiene que adivinar si el problema es el dato o la
    // herramienta.
    expect(
      await screen.findByText(/exempleado@cliente\.com/),
    ).toBeInTheDocument();
    expect(screen.getByText(/HTTP 401/)).toBeInTheDocument();
    // Una baja apartada es un acceso que sigue abierto: se marca.
    expect(screen.getByText("suite.esUnaBaja")).toBeInTheDocument();
  });

  it("el botón de reintentar llama a la ruta con el id de la sincronización", async () => {
    respuestas = {
      "/api/v1/suite/panel": { ...PANEL_LIMPIO, cuarentena: 1 },
      "/api/v1/suite/cuarentena": [APARTADO],
      "/api/v1/suite/cuarentena/s-1/reintentar": { id: "s-1", estado: "pendiente" },
    };
    render(<SuiteGobierno />);
    const boton = await screen.findByRole("button", { name: "suite.reintentar" });
    await userEvent.click(boton);

    await waitFor(() => {
      const reintento = llamadas.find((l) => l.ruta.endsWith("/reintentar"));
      // El `id` de la fila apartada, no el `objeto_id`: el segundo es el del
      // usuario y con él la ruta da 404. La pantalla no lo recibía siquiera.
      expect(reintento?.ruta).toBe("/api/v1/suite/cuarentena/s-1/reintentar");
      expect(reintento?.metodo).toBe("POST");
    });
  });

  it("cuando no hay nada apartado no pinta la tabla de cuarentena", async () => {
    respuestas = { "/api/v1/suite/panel": PANEL_LIMPIO };
    render(<SuiteGobierno />);
    await screen.findByText("contecmind");
    expect(screen.queryByRole("button", { name: "suite.reintentar" })).toBeNull();
    // Y no se pide: una llamada por si acaso en cada carga de la consola.
    expect(llamadas.some((l) => l.ruta.includes("cuarentena"))).toBe(false);
  });
});
