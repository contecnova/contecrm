/**
 * Un presupuesto, antes de mandarlo.
 *
 * Lo que se afirma aquí:
 *
 *  · que «necesita aprobación» venga **con sus motivos** y con el umbral y el
 *    margen mínimo al lado. A secas se lee como burocracia;
 *  · que el **margen vaya pegado al descuento**: un 30 % sobre 60 de margen y
 *    sobre 12 son dos conversaciones distintas y en la lista los dos son 30 %;
 *  · que una **primera versión** diga que no hay con qué compararla, en vez de
 *    enseñar una comparación vacía que se lee como «no ha cambiado nada»;
 *  · y que el documento enseñe **con qué marca e idioma** va a salir.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

let presupuesto: Record<string, unknown>;
let politica: Record<string, unknown>;
let cambios: Record<string, unknown>;

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      if (ruta.includes("/politica-descuento")) return { datos: politica };
      if (ruta.includes("/cambios")) return { datos: cambios };
      if (ruta.includes("/documento"))
        return {
          datos: {
            plantilla: "oferta-estandar",
            marca: "Contecnova",
            idioma: "es",
            numero: "PRE-2026-0042",
            version: 2,
            fecha: "2026-10-30",
            valido_hasta: "2026-11-30",
            titulo: "Renovación",
            moneda: "EUR",
            lineas: [{ descripcion: "Licencias", total: "1000.00" }],
            subtotal: "1000.00",
            descuento_total: "300.00",
            total: "700.00",
            notas: "",
            condiciones: "Pago a 30 días",
          },
        };
      return { datos: presupuesto };
    }),
  };
});

const { Presupuesto } = await import("@/paginas/Presupuesto");

function montar() {
  return render(
    <MemoryRouter initialEntries={["/m/oportunidades/presupuesto/p-1"]}>
      <Routes>
        <Route path="/m/oportunidades/presupuesto/:id" element={<Presupuesto />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  presupuesto = {
    id: "p-1",
    numero: "PRE-2026-0042",
    version: 2,
    titulo: "Renovación",
    estado: "borrador",
    moneda: "EUR",
    subtotal: "1000.00",
    descuento_total: "300.00",
    total: "700.00",
    margen_pct: 12,
    valido_hasta: "2026-11-30",
    marca: "Contecnova",
    idioma: "es",
    motivo_aprobacion: null,
  };
  politica = {
    necesita_aprobacion: true,
    motivos: ["El descuento del 30 % pasa del 25 % declarado"],
    descuento_maximo: 30,
    margen_pct: 12,
    umbral_descuento: 25,
    margen_minimo: 20,
  };
  cambios = {
    version: 2,
    primera: false,
    total_antes: "1000.00",
    total_ahora: "700.00",
    cambios: [
      { linea: "Licencias", cambio: "cantidad", cantidad_antes: "10", cantidad_ahora: "7" },
      { linea: "Soporte", cambio: "quitada", total: "200.00" },
    ],
  };
  vi.clearAllMocks();
});

describe("la aprobación", () => {
  it("viene con sus motivos y con los umbrales al lado", async () => {
    montar();
    await screen.findByText("presupuesto.necesitaAprobacion");
    expect(
      screen.getByText("El descuento del 30 % pasa del 25 % declarado"),
    ).toBeInTheDocument();
    expect(
      screen.getByText('presupuesto.umbrales:{"umbral":25,"minimo":20}'),
    ).toBeInTheDocument();
  });

  it("si no hace falta, no se avisa de nada", async () => {
    politica = { ...politica, necesita_aprobacion: false, motivos: [] };
    montar();
    await screen.findByText("presupuesto.numeros");
    expect(screen.queryByText("presupuesto.necesitaAprobacion")).not.toBeInTheDocument();
  });
});

describe("los números", () => {
  it("el margen va pegado al descuento", async () => {
    montar();
    await screen.findByText(
      'presupuesto.descuentoYMargen:{"descuento":"300.00","margen":"12 %"}',
    );
  });

  it("sin coste en las líneas lo dice, en vez de enseñar un margen de cero", async () => {
    presupuesto = { ...presupuesto, margen_pct: null };
    montar();
    await screen.findByText("presupuesto.porqueSinMargen");
    expect(
      screen.getByText(
        'presupuesto.descuentoYMargen:{"descuento":"300.00","margen":"presupuesto.sinMargen"}',
      ),
    ).toBeInTheDocument();
  });
});

describe("qué cambió", () => {
  it("enseña el total antes y después, y línea a línea", async () => {
    montar();
    await screen.findByText(
      'presupuesto.totalAntesDespues:{"antes":"1000.00","ahora":"700.00"}',
    );
    expect(screen.getByText("Licencias")).toBeInTheDocument();
    expect(screen.getByText("Soporte")).toBeInTheDocument();
    expect(
      screen.getByText('presupuesto.deA:{"antes":"10","ahora":"7"}'),
    ).toBeInTheDocument();
  });

  it("una primera versión lo dice, en vez de enseñar una comparación vacía", async () => {
    cambios = { version: 1, primera: true, cambios: [] };
    montar();
    await screen.findByText("presupuesto.esLaPrimera");
    expect(screen.queryByText(/presupuesto\.totalAntesDespues/)).not.toBeInTheDocument();
  });
});

describe("el documento", () => {
  it("no se pide solo: se pide cuando se va a mirar", async () => {
    montar();
    await screen.findByText("presupuesto.documento");
    expect(screen.getByText("presupuesto.verDocumento")).toBeInTheDocument();
  });

  it("y enseña con qué marca e idioma va a salir", async () => {
    montar();
    await screen.findByText("presupuesto.verDocumento");
    await userEvent.click(screen.getByText("presupuesto.verDocumento"));
    expect(
      await screen.findByText(
        'presupuesto.conQueSale:{"plantilla":"oferta-estandar","marca":"Contecnova","idioma":"es"}',
      ),
    ).toBeInTheDocument();
  });
});
