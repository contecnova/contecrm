/**
 * La paleta encuentra registros, no sólo pantallas.
 *
 * El manual prometía desde el primer día que la búsqueda mira a la vez en
 * cuentas, contactos, oportunidades, casos y documentos. `GET /api/v1/buscar`
 * lo hacía y **nadie la llamaba**: quien escribía «Acme» aquí encontraba la
 * pantalla de cuentas y luego tenía que buscar Acme dentro.
 *
 * Lo que fija esta prueba:
 *
 *   · se pide al servidor, con lo escrito;
 *   · los registros van **debajo** de las pantallas. La paleta se abre casi
 *     siempre para ir a un sitio, y ponerlos delante cambiaría lo que hace el
 *     `Intro` de quien ya la tiene en los dedos;
 *   · un resultado de un tipo que no vive en ningún módulo **no se enlaza**:
 *     una fila que lleva a una pantalla que no existe es peor que una de menos;
 *   · y un fallo de la búsqueda no rompe la paleta, que es lo que se vino a
 *     usar en el noventa por ciento de los casos.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

const pedidas: string[] = [];
let resultados: unknown[] = [];
let falla = false;

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => {
    pedidas.push(ruta);
    if (falla) throw new Error("no se ha podido buscar");
    return { datos: { resultados, servicios_sin_responder: [] } };
  }),
}));

vi.mock("@/lib/permisos", () => ({ usePermitidas: () => undefined }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

const { Paleta } = await import("@/componentes/Paleta");

function abrir() {
  return render(
    <MemoryRouter>
      <Paleta abierta sesion={null} alCerrar={() => undefined} />
    </MemoryRouter>,
  );
}

describe("la paleta busca registros", () => {
  beforeEach(() => {
    pedidas.length = 0;
    resultados = [];
    falla = false;
  });

  it("pide al servidor lo que se escribe", async () => {
    resultados = [
      { objeto: "cuenta", registro_id: "c1", titulo: "Acme Ibérica", subtitulo: "Cliente" },
    ];
    abrir();
    await userEvent.type(screen.getByRole("textbox"), "acme");
    await waitFor(() =>
      expect(pedidas.some((r) => r.includes("/api/v1/buscar?q=acme"))).toBe(true),
    );
    expect(await screen.findByText("Acme Ibérica")).toBeInTheDocument();
  });

  it("los registros van debajo de las pantallas", async () => {
    resultados = [
      { objeto: "cuenta", registro_id: "c1", titulo: "Acme Ibérica", subtitulo: "" },
    ];
    abrir();
    // «cuentas» casa con la pantalla de cuentas Y con el registro.
    await userEvent.type(screen.getByRole("textbox"), "cuentas");
    await screen.findByText("Acme Ibérica");
    const filas = [...document.querySelectorAll("li")].map((n) => n.textContent ?? "");
    // La paleta se abre para ir a un sitio: poner los registros delante
    // cambiaría lo que hace el Intro de quien ya la tiene en los dedos.
    expect(filas.findIndex((f) => f.includes("Acme Ibérica"))).toBeGreaterThan(0);
  });

  it("con una sola letra no se pregunta: sería una consulta por pulsación", async () => {
    abrir();
    await userEvent.type(screen.getByRole("textbox"), "a");
    await new Promise((r) => setTimeout(r, 300));
    expect(pedidas.some((r) => r.includes("/api/v1/buscar"))).toBe(false);
  });

  it("un tipo que no vive en ningún módulo no se enlaza", async () => {
    resultados = [
      { objeto: "cuenta", registro_id: "c1", titulo: "Acme Ibérica", subtitulo: "" },
      { objeto: "cosa_inventada", registro_id: "x1", titulo: "TESTIGO-sin-modulo", subtitulo: "" },
    ];
    abrir();
    await userEvent.type(screen.getByRole("textbox"), "acme");
    expect(await screen.findByText("Acme Ibérica")).toBeInTheDocument();
    // Llevaría a una pantalla que no existe.
    expect(screen.queryByText("TESTIGO-sin-modulo")).toBeNull();
  });

  it("si la búsqueda falla, las pantallas siguen estando", async () => {
    falla = true;
    abrir();
    await userEvent.type(screen.getByRole("textbox"), "cuentas");
    await waitFor(() => expect(pedidas.length).toBeGreaterThan(0));
    // Lo que se vino a hacer en el noventa por ciento de los casos: la lista
    // de pantallas sigue ahí, filtrada por lo escrito.
    expect(document.querySelectorAll("li").length).toBeGreaterThan(0);
  });
});
