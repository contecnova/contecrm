/**
 * Con qué se firma (CRM-06.01.02.02, .05, .06, .08, .12).
 *
 * Las reglas y las plantillas de firma se podían escribir y **no leer**, que
 * es el mismo agujero que tenían las excepciones de campo. Importa el día de
 * una auditoría: una regla decide con qué proveedor y con qué nivel eIDAS sale
 * un documento, y «¿por qué este contrato se firmó con un clic?» no se podía
 * contestar sin mirar la base de datos.
 *
 * Lo que se exige aquí no es que pinte una lista: es el **orden** —por
 * prioridad, que es como se aplican— y que **las apagadas se vean**, porque
 * una regla apagada es justo lo que explica que algo dejara de pasar.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PendienteDeFirma } from "@/paginas/PendienteDeFirma";

let proveedores: unknown = [];
let reglas: unknown = { reglas: [], que_significa: "Sin reglas." };
let plantillas: unknown = { plantillas: [] };

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => {
    if (ruta.includes("/firma/proveedores")) return { datos: proveedores };
    if (ruta.includes("/firma/reglas")) return { datos: reglas };
    if (ruta.includes("/firma/plantillas")) return { datos: plantillas };
    if (ruta.includes("/firma/llamadas"))
      return { datos: { llamadas: [], cuantas: 0, coste_total: "0", fallidas: 0 } };
    return { datos: { sobres: [], cuantos: 0, medible: false } };
  }),
  salvoCancelacion: (f: (e: unknown) => void) => f,
  ErrorApi: class extends Error {},
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

const abrir = () =>
  render(
    <MemoryRouter>
      <PendienteDeFirma />
    </MemoryRouter>,
  );

describe("con qué se firma", () => {
  beforeEach(() => {
    proveedores = [
      {
        clave: "cualificada",
        nombre: "Firma cualificada",
        niveles: ["simple", "avanzada", "cualificada"],
        identificaciones: ["sms", "video", "certificado"],
        activo: true,
        solo_en_curso: false,
      },
    ];
    reglas = {
      que_significa: "Se aplican por prioridad, de menor a mayor.",
      reglas: [
        {
          id: "r2",
          nombre: "Contratos grandes",
          prioridad: 10,
          activa: true,
          proveedor: "cualificada",
          nivel_minimo: "cualificada",
          condiciones: [],
        },
        {
          id: "r1",
          nombre: "Acuses",
          prioridad: 90,
          activa: false,
          proveedor: "cualificada",
          nivel_minimo: null,
          condiciones: [],
        },
      ],
    };
    plantillas = {
      plantillas: [
        {
          clave: "contrato-marco",
          nombre: "Contrato marco",
          tipo_documento: "contrato",
          nivel: "cualificada",
          campos: 2,
          dias_validez: 30,
          orden_estricto: true,
          activa: true,
        },
      ],
    };
  });

  it("enseña los niveles eIDAS y cómo se identifica al firmante", async () => {
    abrir();
    const caja = await screen.findByTestId("firma-proveedores");
    expect(caja.textContent).toContain("cualificada");
    expect(caja.textContent).toContain("firma.identificaciones");
  });

  it("las reglas van por prioridad, que es como se aplican", async () => {
    abrir();
    const caja = await screen.findByTestId("firma-reglas");
    const grandes = caja.textContent?.indexOf("Contratos grandes") ?? -1;
    const acuses = caja.textContent?.indexOf("Acuses") ?? -1;
    expect(grandes).toBeGreaterThan(-1);
    expect(acuses).toBeGreaterThan(grandes);
  });

  it("una regla apagada se ve: es lo que explica que algo dejara de pasar", async () => {
    abrir();
    expect((await screen.findByTestId("firma-reglas")).textContent).toContain(
      "firma.apagada",
    );
  });

  it("la plantilla dice su plazo, que es por lo que un sobre caduca", async () => {
    abrir();
    expect((await screen.findByTestId("firma-plantillas")).textContent).toContain(
      "firma.plantilla",
    );
  });

  it("sin proveedor dice que no se puede mandar nada, no deja el hueco", async () => {
    proveedores = [];
    abrir();
    expect(await screen.findByText("firma.sinProveedor")).toBeInTheDocument();
  });
});
