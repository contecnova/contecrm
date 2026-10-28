/**
 * La suite por su DECLARACIÓN, no sólo por sus consecuencias
 * (CRM-00.01.07.01, .04, .05, .08, .09, .11, .13).
 *
 * La consola enseñaba cuántas altas hubo y cuántas están en cuarentena —el
 * resultado— y no de qué sale: con qué dirección está declarada cada
 * herramienta, qué rol de aquí es qué rol de allí, qué áreas comparte el
 * cliente y si el proveedor de identidad es uno para las tres.
 *
 * Importa por una razón concreta: un mapeo de roles que no se puede mirar no
 * se puede revisar, y es justo donde se cuela que alguien entre de
 * administrador en el gestor documental por ser comercial aquí.
 *
 * Y dos que son de leer antes de hacer: **qué** se aplicaría —un «32 cambios»
 * no se puede aprobar— y si la baja se puede certificar o qué queda abierto.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SuiteGobierno } from "@/paginas/Suite";

const PANEL = {
  tenant: { id: "t1", nombre: "Industrias del Ter", estado: "activo" },
  herramientas: [
    {
      herramienta: "contecmind",
      tipo: "documental",
      activa: true,
      estado: "ok",
      por_estado: { aplicado: 4 },
      bajas_sin_aplicar: 0,
      ultimo_error: "",
      direccion: "https://mind.interno:8080",
      mapeo_roles: { comercial: "lector", direccion: "editor" },
    },
  ],
  cuarentena: 0,
  bajas_sin_aplicar: 0,
  en_verde: true,
  sin_herramientas: false,
};

const IDENTIDAD = {
  tenant: { id: "t1", nombre: "Industrias del Ter", estado: "activo" },
  organizacion: [
    { id: "u1", codigo: "iberia", nombre: "Iberia", padre: null, activa: true },
    { id: "u2", codigo: "calidad", nombre: "Calidad", padre: "Iberia", activa: true },
  ],
};

const SIMULACION = {
  herramientas: [
    {
      herramienta: "contecmind",
      altas: ["usuario:ana"],
      bajas: ["usuario:jordi"],
      cambios: [],
      sin_cambio: 3,
    },
  ],
  total_a_aplicar: 2,
  ya_aplicadas: 11,
};

const CIERRE = {
  abiertas: ["contecintelligence"],
  cerradas: ["contecmind"],
  completo: false,
  certificado:
    "NO se puede certificar la destrucción: hay herramientas donde el dato sigue.",
  que_hacer: "Cerrar contecintelligence y volver a pedirlo.",
};

let sso: unknown = { hay_proveedor: true, herramientas: ["contecmind", "contecintelligence"] };

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => {
    if (ruta.includes("/suite/panel")) return { datos: PANEL };
    if (ruta.includes("/suite/identidad")) return { datos: IDENTIDAD };
    if (ruta.includes("/suite/simular")) return { datos: SIMULACION };
    if (ruta.includes("/suite/certificado-de-cierre")) return { datos: CIERRE };
    if (ruta.includes("/suite/historial")) return { datos: [] };
    if (ruta.includes("/proveedores-identidad/suite")) return { datos: sso };
    if (ruta.includes("/suite/cuarentena")) return { datos: [] };
    // Las tres de salud, con la FORMA que mandan. Devolverles `{}` tumba el
    // render entero —les piden `.length`— y entonces estas pruebas fallarían
    // por un motivo que no es el suyo, que es el error más caro de depurar.
    if (ruta.includes("/suites/salud"))
      return { datos: { total: 0, paradas: [], sin_medir: [] } };
    if (ruta.includes("/suites/credenciales/salud"))
      return { datos: { revisados: 0, que_piden_algo: [] } };
    if (ruta.includes("/suites/suscripciones/por-renovar"))
      return { datos: { por_renovar: [], sin_caducidad_declarada: [], aviso: "" } };
    return { datos: {} };
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

describe("la suite por su declaración", () => {
  beforeEach(() => {
    sso = { hay_proveedor: true, herramientas: ["contecmind", "contecintelligence"] };
  });

  it("enseña el organigrama que comparten las tres herramientas", async () => {
    render(<SuiteGobierno />);
    const areas = await screen.findByTestId("suite-organigrama");
    expect(areas.textContent).toContain("Iberia");
    expect(areas.textContent).toContain("Calidad");
  });

  it("enseña el mapeo de roles, que es donde se cuela un permiso de más", async () => {
    render(<SuiteGobierno />);
    const filas = await screen.findByTestId("suite-herramientas");
    expect(filas.textContent).toContain("comercial → lector");
    expect(filas.textContent).toContain("direccion → editor");
  });

  it("enseña con qué dirección está declarada cada herramienta", async () => {
    render(<SuiteGobierno />);
    const filas = await screen.findByTestId("suite-herramientas");
    expect(filas.textContent).toContain("https://mind.interno:8080");
  });

  it("dice si el proveedor de identidad es uno para todas", async () => {
    render(<SuiteGobierno />);
    expect((await screen.findByTestId("suite-sso")).textContent).toContain(
      "suite.ssoCompartido",
    );
  });

  it("sin proveedor, dice POR QUÉ en vez de dejar el hueco", async () => {
    sso = {
      hay_proveedor: false,
      porque: "Este tenant no tiene proveedor de identidad activo.",
    };
    render(<SuiteGobierno />);
    expect((await screen.findByTestId("suite-sso")).textContent).toContain(
      "no tiene proveedor de identidad activo",
    );
  });

  it("dice QUÉ se aplicaría, no sólo cuántos", async () => {
    render(<SuiteGobierno />);
    const plan = await screen.findByTestId("suite-simulacion");
    expect(plan.textContent).toContain("contecmind");
    expect(plan.textContent).toContain("suite.plan");
  });

  it("saca las bajas del plan aparte: una baja sin aplicar es un acceso abierto", async () => {
    render(<SuiteGobierno />);
    const plan = await screen.findByTestId("suite-simulacion");
    expect(plan.textContent).toContain("usuario:jordi");
  });

  it("no da por cerrado lo que no se puede certificar", async () => {
    render(<SuiteGobierno />);
    const cert = await screen.findByTestId("suite-certificado");
    expect(cert.textContent).toContain("NO se puede certificar");
    expect(cert.textContent).toContain("Cerrar contecintelligence");
    expect(cert.className).toContain("text-warning");
  });
});
