/**
 * Por dónde entran los casos, y qué se queda por el camino.
 *
 * Lo que se afirma aquí es lo que hace útil la pantalla: que el descarte salga
 * **con su motivo**. El total solo no se puede accionar — no distingue el
 * anti-bucle haciendo su trabajo de una trampa comiéndose correos de clientes,
 * y la trampa descarta contestando «aceptado» a propósito, así que un falso
 * positivo no deja rastro de ningún lado.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

let canales: unknown[];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async () => ({ datos: { items: canales } })),
  };
});

const { CanalesDeEntrada } = await import("@/paginas/CanalesDeEntrada");

const CORREO = {
  id: "c-1",
  clave: "soporte",
  nombre: "Soporte por correo",
  tipo: "correo",
  activo: true,
  recibidos: 1240,
  descartados: 300,
  descartados_por: { automatico: 280, propio: 20 },
  mapeo: { asunto: "subject", cuerpo: "body" },
  obligatorios: ["body"],
  campo_trampa: "web_site",
  max_por_hora: 200,
  direccion_propia: "soporte@nosotros.com",
};

beforeEach(() => {
  canales = [CORREO];
  vi.clearAllMocks();
});

describe("el desglose del descarte", () => {
  it("dice cuántos por cada motivo, no sólo el total", async () => {
    render(<CanalesDeEntrada />);
    await screen.findByText("Soporte por correo");

    expect(
      screen.getByText('canales.cifras:{"recibidos":1240,"descartados":300}'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('canales.motivo.automatico:{"cuantos":280}'),
    ).toBeInTheDocument();
    expect(screen.getByText('canales.motivo.propio:{"cuantos":20}')).toBeInTheDocument();
    // Y los motivos que no han pasado no se pintan a cero: un cero se lee como
    // «medido y vale cero», y aquí significa que no ha ocurrido.
    expect(screen.queryByText(/canales\.motivo\.trampa/)).not.toBeInTheDocument();
  });

  it("avisa cuando la trampa es lo que más descarta", async () => {
    canales = [{ ...CORREO, descartados: 300, descartados_por: { trampa: 280, propio: 20 } }];
    render(<CanalesDeEntrada />);
    await screen.findByText("Soporte por correo");
    expect(screen.getByText("canales.trampaManda")).toBeInTheDocument();
  });

  it("no avisa cuando el que manda es el anti-bucle, que es su trabajo", async () => {
    render(<CanalesDeEntrada />);
    await screen.findByText("Soporte por correo");
    expect(screen.queryByText("canales.trampaManda")).not.toBeInTheDocument();
  });

  it("lo que no tiene motivo apuntado se declara, no se reparte a ojo", async () => {
    // Un canal anterior a la medida: tiene el total y no el desglose.
    canales = [{ ...CORREO, descartados: 300, descartados_por: {} }];
    render(<CanalesDeEntrada />);
    await screen.findByText("Soporte por correo");
    expect(screen.getByText('canales.sinMotivo:{"cuantos":300}')).toBeInTheDocument();
  });

  it("un canal sin descartes no enseña desglose vacío", async () => {
    canales = [{ ...CORREO, recibidos: 10, descartados: 0, descartados_por: {} }];
    render(<CanalesDeEntrada />);
    await screen.findByText("Soporte por correo");
    expect(screen.queryByText(/canales\.sinMotivo/)).not.toBeInTheDocument();
  });
});

describe("las defensas del canal", () => {
  it("van delante, porque son lo que explica el número", async () => {
    render(<CanalesDeEntrada />);
    await screen.findByText("Soporte por correo");

    expect(screen.getByText("canales.tope")).toBeInTheDocument();
    expect(screen.getByText("200")).toBeInTheDocument();
    expect(screen.getByText("soporte@nosotros.com")).toBeInTheDocument();
    expect(screen.getByText("web_site")).toBeInTheDocument();
  });

  it("un canal de correo sin dirección propia no puede cortar su eco, y se dice", async () => {
    canales = [{ ...CORREO, direccion_propia: "" }];
    render(<CanalesDeEntrada />);
    await screen.findByText("Soporte por correo");
    expect(screen.getByText("canales.sinEco")).toBeInTheDocument();
  });

  it("y en un canal que no es de correo, no se avisa de eso", async () => {
    canales = [{ ...CORREO, tipo: "api", direccion_propia: "" }];
    render(<CanalesDeEntrada />);
    await screen.findByText("Soporte por correo");
    expect(screen.queryByText("canales.sinEco")).not.toBeInTheDocument();
  });
});

describe("el estado del canal", () => {
  it("distingue el que escucha del que está apagado", async () => {
    canales = [CORREO, { ...CORREO, id: "c-2", nombre: "Formulario", activo: false }];
    render(<CanalesDeEntrada />);
    await screen.findByText("Formulario");
    expect(screen.getByText("canales.escuchando")).toBeInTheDocument();
    expect(screen.getByText("canales.apagado")).toBeInTheDocument();
  });

  it("sin canales lo dice, y dice qué significa no tener ninguno", async () => {
    canales = [];
    render(<CanalesDeEntrada />);
    expect(await screen.findByText("canales.sinCanales")).toBeInTheDocument();
    expect(screen.getByText("canales.sinCanalesDetalle")).toBeInTheDocument();
  });
});
