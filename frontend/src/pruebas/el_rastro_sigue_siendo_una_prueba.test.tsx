/**
 * «¿Cómo estaba esto el 3 de marzo?» y si el rastro todavía vale como prueba.
 *
 * El historial de campos dice qué cambió; no dice cómo era el conjunto, y
 * reconstruirlo a mano encadenando cambios sale mal en cuanto hay una fusión
 * por medio.
 *
 * **Y lo que de verdad importa es la comprobación de que cuadra.** Una
 * reconstrucción que no coincide con la tabla viva significa que alguien
 * escribió sin pasar por el rastro —un script de corrección, una migración, un
 * arreglo a mano un viernes— y a partir de ahí el rastro deja de ser una
 * prueba **sin que nadie se entere**, porque sigue contestando con la misma
 * seguridad. Por eso el no-cuadra se afirma aparte y en rojo.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pedidas: string[] = [];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      pedidas.push(ruta);
      const datos = ruta.endsWith("/cuadra")
        ? {
            cuadra: false,
            diferencias: [
              { campo: "importe", reconstruido: "1000", vivo: "2500" },
            ],
            que_significa:
              "Alguien ha escrito en la tabla sin pasar por el rastro.",
          }
        : {
            objeto: "oportunidad",
            objeto_id: "op-1",
            hasta: null,
            hechos: 12,
            estado: { importe: "1000" },
            hechos_compensados: 2,
            porque:
              "Los hechos compensados se aplican y se anulan, no se saltan.",
          };
      return { datos, version: null, retenidos: [], enmascarados: [] };
    }),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, args?: Record<string, unknown>) =>
      args ? `${clave}:${JSON.stringify(args)}` : clave,
  }),
}));

async function montar() {
  const { ComoEstabaEsto } = await import("@/paginas/Ficha");
  return render(
    <ComoEstabaEsto servicio="sales" objeto="oportunidad" objetoId="op-1" />,
  );
}

describe("el rastro sigue siendo una prueba", () => {
  beforeEach(() => {
    pedidas.length = 0;
  });

  it("no se pide hasta que alguien lo abre", async () => {
    await montar();
    // El rastro completo está encendido en muy pocos objetos a propósito:
    // pedirlo en cada ficha sería una llamada por registro abierto que casi
    // siempre contestaría «aquí no hay».
    expect(pedidas).toEqual([]);
  });

  it("al abrirlo, dice cuántos hechos y cuántos están compensados", async () => {
    await montar();
    await userEvent.click(screen.getByText("ficha.comoEstaba"));
    await waitFor(() =>
      expect(screen.getByText(/ficha.hechos.*"compensados":2/)).toBeTruthy(),
    );
  });

  it("AVISA en rojo de que la reconstrucción no cuadra, y de en qué", async () => {
    await montar();
    await userEvent.click(screen.getByText("ficha.comoEstaba"));
    await waitFor(() => expect(screen.getByText("ficha.noCuadra")).toBeTruthy());
    expect(
      screen.getByText("Alguien ha escrito en la tabla sin pasar por el rastro."),
    ).toBeTruthy();
    // Y en qué campo: sin la diferencia concreta, «no cuadra» no deja empezar
    // a buscar por ningún sitio.
    expect(screen.getByText("importe")).toBeTruthy();
    expect(screen.getByText(/≠ 2500/)).toBeTruthy();
  });
});
