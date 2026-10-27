/**
 * Una medida no es un listado, y se enseña encima del suyo.
 *
 * De las colecciones publicadas sin pantalla, **96 de 157 eran esto**: un
 * `GET` que devuelve un objeto con cuatro cifras y una frase que dice qué
 * significan —el presupuesto de IA gastado este mes, cuánto se lleva consumido
 * de lo contratado, si los avisos de anomalía sirven de algo—. No caben como
 * pestaña, y hacerle una pantalla a cada una serían noventa y seis pantallas
 * de un párrafo.
 *
 * Lo que fija esta prueba, que es lo que se rompe sin ruido:
 *
 *   · las cifras se enseñan, y la frase del servidor con ellas. Un número sin
 *     su explicación se interpreta mal, y la frase la escribe quien sabe cómo
 *     se calculó;
 *   · **lo que no es concluyente se marca.** Estas respuestas traen `medible`
 *     o `concluyente` justo para eso, y pintar sus ceros como una medida es la
 *     forma de que alguien decida sobre algo que nadie ha medido;
 *   · que una medida no se pueda leer **no deja sin ver el listado**, que es a
 *     lo que se venía.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

const llamadas: string[] = [];
let respuestas: Record<string, unknown> = {};
let fallan = new Set<string>();

vi.mock("@/lib/api", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      llamadas.push(ruta);
      if ([...fallan].some((f) => ruta.includes(f))) throw new Error("no se puede leer");
      const clave = Object.keys(respuestas).find((k) => ruta.startsWith(k));
      if (!clave) throw new Error(`sin respuesta para ${ruta}`);
      return { datos: respuestas[clave] };
    }),
    filas: (datos: unknown) =>
      Array.isArray(datos) ? datos : ((datos as { items?: unknown[] })?.items ?? []),
    siguientePagina: () => "",
  };
});

vi.mock("@/lib/personas", () => ({
  usePersonas: () => ({}),
  nombreDe: (_p: unknown, id: unknown) => String(id ?? ""),
  inicialesDe: (n: string) => n.slice(0, 2).toUpperCase(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

const { Medidas } = await import("@/paginas/Modulo");

function pintar(rutas: string[]) {
  return render(
    <MemoryRouter>
      <Medidas rutas={rutas} />
    </MemoryRouter>,
  );
}

describe("las medidas que acompañan a un listado", () => {
  beforeEach(() => {
    llamadas.length = 0;
    respuestas = {};
    fallan = new Set();
  });

  it("enseña las cifras con la frase del servidor", async () => {
    respuestas["/api/v1/ia/presupuesto"] = {
      gastado: "128",
      presupuesto: 500,
      agotado: false,
      que_significa: "TESTIGO-queda margen este mes",
    };
    pintar(["/api/v1/ia/presupuesto"]);
    expect(await screen.findByText("TESTIGO-queda margen este mes")).toBeInTheDocument();
    expect(screen.getByText("128")).toBeInTheDocument();
    expect(screen.getByText("500")).toBeInTheDocument();
  });

  it("lo que no es concluyente se marca, no se pinta como una medida", async () => {
    respuestas["/api/v1/ia/calidad"] = {
      propuestas: 0,
      sin_juzgar: 0,
      medible: false,
      aviso: "TESTIGO-nadie ha marcado qué hizo con los borradores",
    };
    const { container } = pintar(["/api/v1/ia/calidad"]);
    const aviso = await screen.findByText(/TESTIGO-nadie ha marcado/);
    // En el tono de aviso y no en el de dato: un cero que parece medido es
    // peor que no enseñarlo.
    expect(aviso.className).toMatch(/warning/);
    // Y `medible` no se pinta como si fuera una cifra más.
    expect(container.textContent).not.toMatch(/medible/i);
  });

  it("una medida que no se puede leer no deja sin ver las demás", async () => {
    respuestas["/api/v1/ia/presupuesto"] = { gastado: 7, que_significa: "TESTIGO-va bien" };
    fallan.add("/api/v1/ia/calidad");
    pintar(["/api/v1/ia/calidad", "/api/v1/ia/presupuesto"]);
    expect(await screen.findByText("TESTIGO-va bien")).toBeInTheDocument();
  });

  it("sin ninguna medida legible no deja un hueco con marco", async () => {
    fallan.add("/api/v1/ia/calidad");
    const { container } = pintar(["/api/v1/ia/calidad"]);
    await waitFor(() => expect(llamadas.length).toBeGreaterThan(0));
    // Ni recuadro ni la rejilla que los coloca: un hueco con marco se lee
    // como un dato que falta, y un contenedor vacío deja su espacio en blanco
    // entre la cabecera y el listado.
    expect(container.querySelectorAll("section")).toHaveLength(0);
    expect(container.innerHTML).toBe("");
  });
});
