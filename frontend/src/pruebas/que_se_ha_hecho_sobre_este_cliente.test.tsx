/**
 * Qué se ha hecho sobre los datos de un cliente, y qué pasaría si se hiciera.
 *
 * Lo que se afirma aquí es lo que distingue esta pantalla de un listado:
 *
 *  · que lo **simulado** vaya aparte de lo **hecho**. Una simulada no ha
 *    movido nada, y en una lista corrida ocupa una línea igual que una
 *    ejecutada — que es exactamente el sitio donde eso se lee mal;
 *  · que una **ventana de solo lectura abierta** salga arriba y avisando: es
 *    lo único de esta pantalla que pasa ahora mismo, y mientras esté abierta
 *    ese cliente no puede escribir;
 *  · que una operación fallida enseñe **su motivo**, y una migración
 *    verificada **sus diferencias**: «verificada» con diferencias no está
 *    bien, está medida.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

let operaciones: unknown[];
let migraciones: unknown[];
let perfiles: unknown[];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      if (ruta.startsWith("/api/v1/ciclo-vida/operaciones"))
        return { datos: { items: operaciones } };
      if (ruta.startsWith("/api/v1/aislamiento/migraciones"))
        return { datos: { items: migraciones } };
      return { datos: perfiles };
    }),
  };
});

const { CicloDeVidaDelCliente } = await import("@/paginas/CicloDeVidaDelCliente");

const SIMULADA = {
  id: "o-1",
  tipo: "clonado",
  uso: "sandbox",
  estado: "simulada",
  origen_id: "t-1",
  destino_id: null,
  bloques: ["configuracion", "catalogo"],
  plan: { recuentos: { cuentas: 120, contactos: 400 }, avisos: ["Sin anonimizar"] },
  conflictos: [],
  motivo_fin: "",
  created_at: "2026-10-29T08:00:00Z",
  terminada_at: null,
};

const EJECUTADA = {
  ...SIMULADA,
  id: "o-2",
  estado: "ejecutada",
  terminada_at: "2026-10-29T09:00:00Z",
};

beforeEach(() => {
  operaciones = [SIMULADA, EJECUTADA];
  migraciones = [];
  perfiles = [];
  vi.clearAllMocks();
});

describe("lo simulado y lo hecho", () => {
  it("van en secciones distintas", async () => {
    render(<CicloDeVidaDelCliente />);
    await screen.findByText("ciclovida.hechas");
    expect(screen.getByText("ciclovida.simuladas")).toBeInTheDocument();
    // La ejecutada cuenta lo que MOVIÓ; la simulada, lo que SACARÍA.
    expect(
      screen.getByText('ciclovida.movio:{"bloques":2,"filas":520}'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('ciclovida.sacaria:{"bloques":2,"filas":520}'),
    ).toBeInTheDocument();
  });

  it("sin ninguna ejecutada lo dice, en vez de enseñar las simuladas ahí", async () => {
    operaciones = [SIMULADA];
    render(<CicloDeVidaDelCliente />);
    expect(await screen.findByText("ciclovida.sinHechas")).toBeInTheDocument();
    expect(screen.queryByText("ciclovida.sinSimuladas")).not.toBeInTheDocument();
  });

  it("una fallida enseña su motivo", async () => {
    operaciones = [
      { ...EJECUTADA, estado: "fallida", motivo_fin: "El destino ya tenía datos" },
    ];
    render(<CicloDeVidaDelCliente />);
    await screen.findByText("ciclovida.hechas");
    expect(screen.getByText("El destino ya tenía datos")).toBeInTheDocument();
  });

  it("los avisos del plan se pintan en la simulación, que es cuando sirven", async () => {
    render(<CicloDeVidaDelCliente />);
    await screen.findByText("ciclovida.simuladas");
    expect(screen.getByText("Sin anonimizar")).toBeInTheDocument();
  });

  it("los conflictos sin resolver se señalan", async () => {
    operaciones = [{ ...EJECUTADA, conflictos: [{ que: "claves repetidas" }] }];
    render(<CicloDeVidaDelCliente />);
    await screen.findByText("ciclovida.hechas");
    expect(screen.getByText('ciclovida.conflictos:{"cuantos":1}')).toBeInTheDocument();
  });
});

describe("las migraciones de modalidad", () => {
  it("una ventana abierta avisa arriba", async () => {
    migraciones = [
      {
        id: "m-1",
        desde: "compartido",
        hacia: "dedicado",
        estado: "en_ventana",
        ventana_minutos: 10,
        solo_lectura_desde: "2026-10-29T10:00:00Z",
        solo_lectura_hasta: null,
        diferencias: [],
        motivo_fin: "",
        created_at: "2026-10-29T09:00:00Z",
        terminada_at: null,
      },
    ];
    render(<CicloDeVidaDelCliente />);
    expect(
      await screen.findByText('ciclovida.ventanaAbierta:{"cuantas":1}'),
    ).toBeInTheDocument();
  });

  it("una cerrada no avisa, y enseña sus diferencias si las tiene", async () => {
    migraciones = [
      {
        id: "m-2",
        desde: "compartido",
        hacia: "dedicado",
        estado: "verificada",
        ventana_minutos: 10,
        solo_lectura_desde: null,
        solo_lectura_hasta: null,
        diferencias: [{ tabla: "cuentas", origen: 120, destino: 119 }],
        motivo_fin: "",
        created_at: "2026-10-29T09:00:00Z",
        terminada_at: null,
      },
    ];
    render(<CicloDeVidaDelCliente />);
    await screen.findByText("ciclovida.migraciones");
    expect(screen.queryByText(/ciclovida\.ventanaAbierta/)).not.toBeInTheDocument();
    // «Verificada» con diferencias no está bien: está medida.
    expect(
      screen.getByText('ciclovida.diferencias:{"cuantas":1}'),
    ).toBeInTheDocument();
  });

  it("sin migraciones lo dice", async () => {
    render(<CicloDeVidaDelCliente />);
    expect(await screen.findByText("ciclovida.sinMigraciones")).toBeInTheDocument();
  });
});

describe("los perfiles de industria", () => {
  it("se listan con su clave", async () => {
    perfiles = [
      { clave: "industrial", nombre: "Industrial", descripcion: "Pipelines de proyecto" },
    ];
    render(<CicloDeVidaDelCliente />);
    expect(await screen.findByText("Industrial")).toBeInTheDocument();
    expect(screen.getByText("industrial")).toBeInTheDocument();
  });
});
