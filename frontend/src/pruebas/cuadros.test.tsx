/**
 * El cuadro de mando, PINTADO: los avisos y la descarga.
 *
 * Los dos avisos que se arreglaron hoy —«el objeto se lee incompleto» y «el
 * motor ha devuelto más columnas de las que este informe sabe nombrar»— venían
 * en la respuesta del servidor **desde hacía tiempo y el front no los pintaba
 * en ninguna parte**. Estaban en el JSON, que es exactamente igual que no
 * decirlos. Esto comprueba que ahora se leen en la pantalla.
 *
 * Y la descarga: existía en la API y no se podía pedir desde ninguna pantalla,
 * que es por lo que nadie notó durante semanas que reventaba.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Cuadros } from "@/paginas/Cuadros";

let respuestas: Record<string, unknown> = {};
const llamadas: { ruta: string; cuerpo?: unknown }[] = [];

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string, opciones?: { cuerpo?: unknown }) => {
    llamadas.push({ ruta, cuerpo: opciones?.cuerpo });
    // La clave MÁS LARGA que encaje, no la primera: `/api/v1/informes/i1/ejecutar`
    // empieza por `/api/v1/informes`, así que con la primera se devolvía la
    // LISTA de informes donde tocaba el resultado, y la pantalla se quedaba
    // cargando para siempre. La sonda daba por rota una pantalla que estaba
    // bien: exactamente lo que llevo toda la noche encontrando en otros sitios.
    const clave = Object.keys(respuestas)
      .filter((k) => ruta.startsWith(k))
      .sort((a, b) => b.length - a.length)[0];
    if (!clave) throw new Error(`sin respuesta preparada para ${ruta}`);
    return { datos: respuestas[clave] };
  }),
  ErrorApi: class extends Error {},
  filas: (x: unknown) => x,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

const CUADRO = {
  clave: "ventas",
  nombre: "Ventas",
  componentes: [{ tipo: "tabla", informe: "pipeline", titulo: "Pipeline" }],
};

describe("un componente de cuadro de mando", () => {
  beforeEach(() => {
    respuestas = {};
    llamadas.length = 0;
  });

  it("pinta el aviso de que el motor devolvió columnas que no sabe nombrar", async () => {
    respuestas = {
      "/api/v1/cuadros": [CUADRO],
      "/api/v1/informes": [{ id: "i1", clave: "pipeline" }],
      "/api/v1/informes/i1/ejecutar": {
        nombre: "Pipeline",
        columnas: ["nombre", "importe"],
        filas: [["ACME", 10, 3, 7]],
        incompleto: true,
        aviso_plan: "El motor ha devuelto 4 columnas y este informe solo sabe nombrar 2.",
      },
    };
    render(<Cuadros />);
    expect(
      await screen.findByText(/El motor ha devuelto 4 columnas/),
    ).toBeInTheDocument();
  });

  it("pinta el aviso de que el objeto se lee incompleto", async () => {
    respuestas = {
      "/api/v1/cuadros": [CUADRO],
      "/api/v1/informes": [{ id: "i1", clave: "pipeline" }],
      "/api/v1/informes/i1/ejecutar": {
        nombre: "Pipeline",
        columnas: ["nombre"],
        filas: [["ACME"]],
        incompleto: true,
        aviso_datos: "El listado de este objeto no pagina, así que las cifras no son el total.",
      },
    };
    render(<Cuadros />);
    expect(await screen.findByText(/las cifras no son el total/)).toBeInTheDocument();
  });

  it("cuando todo cuadra no enseña ningún aviso", async () => {
    respuestas = {
      "/api/v1/cuadros": [CUADRO],
      "/api/v1/informes": [{ id: "i1", clave: "pipeline" }],
      "/api/v1/informes/i1/ejecutar": {
        nombre: "Pipeline",
        columnas: ["nombre", "importe"],
        filas: [["ACME", 10]],
      },
    };
    render(<Cuadros />);
    await screen.findByText("Pipeline");
    expect(screen.queryByText(/El motor ha devuelto/)).toBeNull();
    expect(screen.queryByText(/no son el total/)).toBeNull();
  });

  it("el botón de descarga pide el CSV al servidor, no lo compone con lo pintado", async () => {
    respuestas = {
      "/api/v1/cuadros": [CUADRO],
      "/api/v1/informes": [{ id: "i1", clave: "pipeline" }],
      "/api/v1/informes/i1/ejecutar": {
        nombre: "Pipeline",
        columnas: ["nombre"],
        filas: [["ACME"]],
        export: { contenido: "nombre\nACME\n" },
      },
    };
    // jsdom no descarga ficheros: se sustituye lo justo para ver qué se pide.
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();

    render(<Cuadros />);
    const boton = await screen.findByRole("button", { name: /cuadros\.descargar/ });
    await userEvent.click(boton);

    const csv = llamadas.filter((l) => (l.cuerpo as { formato?: string })?.formato === "csv");
    expect(csv.length, "no pidió el CSV al servidor").toBe(1);
    expect(csv[0]?.ruta).toContain("/api/v1/informes/i1/ejecutar");
  });
});
