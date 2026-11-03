/**
 * En un registro se puede escribir, y llega.
 *
 * **Medido el 03-11-2026 haciendo el trabajo de verdad**: se abre un caso y se
 * busca dónde dejar una nota. No hay. Cero cajas de texto, dos pestañas
 * —«Relacionado» y «Detalles»— y un menú «Más» con una sola opción,
 * «Eliminar». Un agente de soporte no podía escribir en un caso.
 *
 * Y no era que faltara: `/api/v1/comentarios/{tipo}/{id}` está publicada,
 * contesta, y es de donde salen las menciones. La conversación vivía como una
 * función **privada de la ficha genérica**, así que la llevaba 1 de las 15
 * pantallas de registro.
 *
 * Donde sí existía, tampoco llegaba: mandaba `{texto}` y la ruta espera
 * `{cuerpo}`. Escribir un comentario contestaba **422** — se escribía, se
 * pulsaba enviar y no pasaba nada.
 *
 * Esto vigila las tres cosas, porque las tres se pueden romper sin que se vea:
 * que la conversación la ponga la barra de pestañas —la pieza que comparten
 * todas—, que ninguna ficha se la pinte por su cuenta, y que al enviar viaje
 * el campo que la ruta espera.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

let enviados: { ruta: string; cuerpo: unknown }[] = [];
let hilos: unknown[] = [];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string, opciones?: { metodo?: string; cuerpo?: unknown }) => {
      if ((opciones?.metodo ?? "GET") !== "GET") {
        enviados.push({ ruta, cuerpo: opciones?.cuerpo });
        return { datos: {} };
      }
      return { datos: hilos };
    }),
  };
});

const { Comentarios } = await import("@/componentes/Comentarios");

beforeEach(() => {
  enviados = [];
  hilos = [];
  vi.clearAllMocks();
});

describe("escribir en un registro", () => {
  it("manda el campo que la ruta espera, no otro", async () => {
    render(<Comentarios tipo="caso" id="c-1" />);
    await screen.findByPlaceholderText("ficha.escribir");

    await userEvent.type(screen.getByPlaceholderText("ficha.escribir"), "No contesta el cliente");
    await userEvent.click(screen.getByRole("button", { name: "ficha.enviar" }));

    await waitFor(() => expect(enviados).toHaveLength(1));
    expect(enviados[0]?.ruta).toBe("/api/v1/comentarios/caso/c-1");
    // `cuerpo`, no `texto`. Con `texto` la ruta contesta 422 y el comentario
    // se pierde sin que la pantalla diga nada.
    expect(enviados[0]?.cuerpo).toMatchObject({ cuerpo: "No contesta el cliente" });
  });

  it("no manda nada en blanco", async () => {
    render(<Comentarios tipo="caso" id="c-1" />);
    await screen.findByPlaceholderText("ficha.escribir");
    // Un comentario vacío es una fila vacía en la conversación de alguien.
    expect(screen.getByRole("button", { name: "ficha.enviar" })).toBeDisabled();
    expect(enviados).toEqual([]);
  });
});

describe("la conversación la lleva la barra de pestañas", () => {
  it("y ninguna ficha se la pinta por su cuenta", () => {
    const barra = readFileSync(
      resolve(process.cwd(), "src", "componentes", "PestanasDeFicha.tsx"),
      "utf-8",
    );
    expect(barra).toContain("<Comentarios");

    const dir = resolve(process.cwd(), "src", "paginas");
    const fichas = readdirSync(dir).filter(
      (f) => f.endsWith(".tsx") && readFileSync(join(dir, f), "utf-8").includes("<DatosClave"),
    );
    // Cuántas se han recorrido: si el filtro dejara de casar, esto daría
    // verde sin mirar ninguna.
    expect(fichas.length).toBeGreaterThan(10);
    for (const f of fichas) {
      expect(
        readFileSync(join(dir, f), "utf-8"),
        `${f} se pinta su propia conversación`,
      ).not.toContain("<Comentarios");
    }
  });

  it("y toda ficha con pestañas le dice de qué registro son", () => {
    // Sin `tipo`, la barra no sabe si ese objeto admite conversación y no la
    // ofrece: la pestaña desaparece en silencio. Pasó con la oportunidad y
    // el presupuesto, que sí la admiten.
    const dir = resolve(process.cwd(), "src", "paginas");
    const conBarra = readdirSync(dir).filter(
      (f) => f.endsWith(".tsx") && readFileSync(join(dir, f), "utf-8").includes("<PestanasDeFicha"),
    );
    expect(conBarra.length).toBeGreaterThan(8);
    const mudas: string[] = [];
    for (const f of conBarra) {
      const fuente = readFileSync(join(dir, f), "utf-8");
      const bloque = fuente.slice(fuente.indexOf("<PestanasDeFicha"));
      if (!bloque.slice(0, bloque.indexOf("/>")).includes("tipo=")) mudas.push(f);
    }
    expect(mudas, `fichas que no dicen su tipo a la barra: ${mudas.join(", ")}`).toEqual([]);
  });
});
