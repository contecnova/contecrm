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

vi.mock("@/lib/api", async (importOriginal) => {
  // `ErrorApi` sale del módulo de verdad: `Estados.tsx` hace
  // `error instanceof ErrorApi`, y con el módulo mockeado entero esa clase no
  // existe — la pantalla reventaba al pintar un fallo, no al pedirlo.
  const real = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...real,
    llamar: vi.fn(async (ruta: string, opciones?: { metodo?: string }) => {
      llamadas.push({ ruta, metodo: opciones?.metodo });
      const clave = Object.keys(respuestas)
        .filter((k) => ruta.startsWith(k))
        .sort((a, b) => b.length - a.length)[0];
      if (!clave) throw new Error(`sin respuesta preparada para ${ruta}`);
      return { datos: respuestas[clave] };
    }),
    salvoCancelacion: (fn: (e: unknown) => void) => fn,
  };
});

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

/**
 * Las tres rutas del panel de salud, que se piden siempre que se monta la
 * pantalla. Van con la forma EXACTA del servidor —un sobre, no una lista—,
 * porque leerlas como listas es justo el fallo que tuvo este panel: el
 * `.filter` sobre un objeto revienta dentro del `.then`, el `.catch` se lo
 * traga y el panel sale con sus rótulos y nada debajo.
 */
const SALUD_DE_SUITES = {
  "/api/v1/suites/salud": {
    total: 0,
    paradas: [],
    sin_medir: [],
    en_sondeo: [],
    todo_bien: false,
  },
  "/api/v1/suites/credenciales/salud": { revisados: 0, que_piden_algo: [] },
  "/api/v1/suites/suscripciones/por-renovar": {
    por_renovar: [],
    sin_caducidad_declarada: [],
    aviso: "",
  },
};

describe("la consola de gobierno de la suite", () => {
  beforeEach(() => {
    respuestas = { ...SALUD_DE_SUITES };
    llamadas.length = 0;
  });

  it("sin herramientas conectadas no dice «todo bien»", async () => {
    respuestas = {
      ...SALUD_DE_SUITES,
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
      ...SALUD_DE_SUITES,
      "/api/v1/suite/panel": { ...PANEL_LIMPIO, bajas_sin_aplicar: 2 },
    };
    render(<SuiteGobierno />);
    expect(
      await screen.findByText(/suite\.bajasSinAplicar.*"cuantas":2/),
    ).toBeInTheDocument();
  });

  it("lo que está en cuarentena se ve, con lo que se mandó dentro", async () => {
    respuestas = {
      ...SALUD_DE_SUITES,
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
      ...SALUD_DE_SUITES,
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

  it("el panel de salud lee el sobre que manda el servidor, no una lista", async () => {
    // El fallo que esto caza ya pasó: el panel leía las dos rutas como arrays
    // y hacía `.filter` sobre el objeto. Reventaba dentro del `.then`, el
    // `.catch` se lo tragaba y las dos columnas salían con su rótulo y nada
    // debajo — sin error en consola y sin 500.
    respuestas = {
      ...SALUD_DE_SUITES,
      "/api/v1/suite/panel": PANEL_LIMPIO,
      "/api/v1/suites/credenciales/salud": {
        revisados: 3,
        que_piden_algo: [
          {
            consentimiento_id: "c-1",
            usuario_id: "u-1",
            perfil: "microsoft",
            recurso: "correo",
            se_rompera_sola: true,
            renovar: false,
            avisar: false,
            fiable: true,
            porque: "Quedan 300 días. Y no hay token de refresco",
          },
        ],
      },
      "/api/v1/suites/suscripciones/por-renovar": {
        por_renovar: [
          { id: "s-9", recurso: "calendario", usuario_id: "u-1", caduca_at: null },
        ],
        sin_caducidad_declarada: ["s-7"],
        aviso: "1 suscripciones no dicen cuándo caducan.",
      },
    };
    render(<SuiteGobierno />);

    // La bomba de relojería, con su porqué: «error de autenticación» a secas
    // es el mensaje que atasca una implantación una semana.
    expect(await screen.findByText(/microsoft · correo/)).toBeInTheDocument();
    expect(screen.getByText(/no hay token de refresco/)).toBeInTheDocument();
    // Y la suscripción por renovar, que la pantalla pintaba vacía.
    expect(screen.getByText(/calendario/)).toBeInTheDocument();
    expect(screen.getByText(/1 suscripciones no dicen/)).toBeInTheDocument();
  });

  it("cuando no hay nada apartado no pinta la tabla de cuarentena", async () => {
    respuestas = { ...SALUD_DE_SUITES, "/api/v1/suite/panel": PANEL_LIMPIO };
    render(<SuiteGobierno />);
    await screen.findByText("contecmind");
    expect(screen.queryByRole("button", { name: "suite.reintentar" })).toBeNull();
    // Y no se pide: una llamada por si acaso en cada carga de la consola.
    expect(llamadas.some((l) => l.ruta.includes("cuarentena"))).toBe(false);
  });
});
