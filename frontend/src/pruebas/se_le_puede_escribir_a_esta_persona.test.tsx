/**
 * Por qué canales se le puede escribir a alguien, y con qué reglas.
 *
 * Lo que se afirma aquí:
 *
 *  · que un «no se puede» venga **con sus motivos**, uno por regla. A secas
 *    deja a quien escribe el mensaje sin saber qué arreglar;
 *  · que la **ventana de WhatsApp** se diga: fuera de ella sólo sale plantilla
 *    aprobada, y mandar una no aprobada no da error — el proveedor la descarta
 *    en silencio;
 *  · que el **tope de calentamiento** salga sólo cuando lo hay. `null` es «ese
 *    dominio no está calentando», no «el tope es cero»;
 *  · y que un canal **sin palabra de baja declarada** se señale, porque por ahí
 *    no se puede mandar nada comercial.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

let canales: unknown[];
let comprobacion: Record<string, unknown>;

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      if (ruta.includes("/comprobar")) return { datos: comprobacion };
      return { datos: canales };
    }),
  };
});

const { Canales } = await import("@/paginas/Canales");

async function comprobar() {
  render(<Canales />);
  await screen.findByText("canalesmk.declarados");
  await userEvent.selectOptions(screen.getByLabelText("canalesmk.canal"), "boletin");
  await userEvent.type(screen.getByLabelText("canalesmk.destino"), "ana@cliente.test");
  await userEvent.click(screen.getByText("canalesmk.ver"));
}

beforeEach(() => {
  canales = [
    {
      id: "c-1",
      clave: "boletin",
      nombre: "Boletín",
      tipo: "email",
      activo: true,
      como_se_da_de_baja: "unsubscribe",
    },
    {
      id: "c-2",
      clave: "avisos",
      nombre: "Avisos por SMS",
      tipo: "sms",
      activo: false,
      como_se_da_de_baja: "",
    },
  ];
  comprobacion = {
    se_puede_mandar: false,
    motivos: ["No hay consentimiento para «email» en este destino"],
    canal: "email",
    necesita_plantilla: false,
    ventana_abierta: true,
    como_se_da_de_baja: "unsubscribe",
    calentamiento: null,
  };
  vi.clearAllMocks();
});

describe("la comprobación", () => {
  it("un «no se puede» viene con sus motivos", async () => {
    await comprobar();
    expect(await screen.findByText("canalesmk.noSePuede")).toBeInTheDocument();
    expect(
      screen.getByText("No hay consentimiento para «email» en este destino"),
    ).toBeInTheDocument();
  });

  it("y un «sí se puede» no inventa motivos", async () => {
    comprobacion = { ...comprobacion, se_puede_mandar: true, motivos: [] };
    await comprobar();
    expect(await screen.findByText("canalesmk.siSePuede")).toBeInTheDocument();
    expect(screen.queryByText("canalesmk.noSePuede")).not.toBeInTheDocument();
  });

  it("fuera de la ventana de WhatsApp avisa de que sólo vale plantilla aprobada", async () => {
    comprobacion = {
      ...comprobacion,
      se_puede_mandar: true,
      motivos: [],
      necesita_plantilla: true,
      ventana_abierta: false,
    };
    await comprobar();
    expect(await screen.findByText("canalesmk.necesitaPlantilla")).toBeInTheDocument();
  });

  it("enseña con qué palabra se da de baja, porque va en el mensaje", async () => {
    await comprobar();
    expect(
      await screen.findByText('canalesmk.bajaCon:{"palabra":"unsubscribe"}'),
    ).toBeInTheDocument();
  });

  it("el tope de calentamiento sale sólo cuando lo hay", async () => {
    await comprobar();
    expect(screen.queryByText(/canalesmk\.calentando/)).not.toBeInTheDocument();
  });

  it("y cuando lo hay, sale con el número", async () => {
    comprobacion = { ...comprobacion, calentamiento: { tope_hoy: 5000, dia: 3 } };
    await comprobar();
    expect(
      await screen.findByText('canalesmk.calentando:{"tope":5000}'),
    ).toBeInTheDocument();
  });

  it("no comprueba nada sin canal y sin destino", async () => {
    render(<Canales />);
    await screen.findByText("canalesmk.declarados");
    expect(screen.getByText("canalesmk.ver")).toBeDisabled();
  });
});

describe("los canales declarados", () => {
  it("cada uno enseña su palabra de baja", async () => {
    render(<Canales />);
    await screen.findByText("canalesmk.declarados");
    expect(
      screen.getByText('canalesmk.sedaDeBajaCon:{"palabra":"unsubscribe"}'),
    ).toBeInTheDocument();
  });

  it("uno sin forma de baja se señala: por ahí no sale nada comercial", async () => {
    render(<Canales />);
    await screen.findByText("canalesmk.declarados");
    expect(screen.getByText("canalesmk.sinFormaDeBaja")).toBeInTheDocument();
  });

  it("y se distingue el activo del apagado", async () => {
    render(<Canales />);
    await screen.findByText("canalesmk.declarados");
    expect(screen.getByText("canalesmk.activo")).toBeInTheDocument();
    expect(screen.getByText("canalesmk.apagado")).toBeInTheDocument();
  });
});
