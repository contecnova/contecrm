/**
 * Una liquidación de comisión, euro a euro.
 *
 * El listado enseñaba el total y el estado. Delante de una liquidación la
 * pregunta no es cuánto: es **por qué ese número y no otro**. Un comercial que
 * no puede desglosar su comisión no se la cree, y la discusión acaba en una
 * hoja de cálculo paralela que nadie concilia.
 *
 * Los tres avisos que se afirman aquí son los que cambian la conversación:
 * lo recortado por el tope, la reversión y la reclamación sin resolver.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pedidas: string[] = [];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      pedidas.push(ruta);
      return {
        datos: {
          id: "l-1",
          estado: "aprobada",
          desde: "2026-10-01",
          hasta: "2026-12-31",
          total: "8400.00",
          moneda: "EUR",
          recortado_por_tope: "1600.00",
          plan_aplicado: { nombre: "Plan 2026" },
          pago_referencia: null,
          pagada_at: null,
          lineas: [
            {
              id: "li-1",
              origen: "oportunidad",
              origen_id: "o-1",
              concepto: "Acme — cierre",
              base: "120000.00",
              porcentaje: "7.00",
              importe: "8400.00",
              explicacion: "7 % del importe funcional al cerrarse en el tramo alto",
              reversion_de: null,
            },
            {
              id: "li-2",
              origen: "oportunidad",
              origen_id: "o-2",
              concepto: "Beta — devolución",
              base: "20000.00",
              porcentaje: "7.00",
              importe: "-1400.00",
              explicacion: "Se revierte por devolución dentro del plazo",
              reversion_de: "l-0",
            },
          ],
          disputas: [
            {
              id: "d-1",
              estado: "abierta",
              motivo: "El tramo alto debería aplicarse desde 100.000, no desde 130.000",
              resolucion: null,
              importe_reclamado: "900.00",
            },
          ],
        },
        version: null,
        retenidos: [],
        enmascarados: [],
      };
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
  const { Liquidacion } = await import("@/paginas/Liquidacion");
  return render(
    <MemoryRouter initialEntries={["/m/canal/liquidacion/l-1"]}>
      <Routes>
        <Route path="/m/canal/liquidacion/:id" element={<Liquidacion />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("una comisión se puede discutir", () => {
  beforeEach(() => {
    pedidas.length = 0;
  });

  it("explica de dónde sale cada euro, con su base y su porcentaje", async () => {
    await montar();
    await waitFor(() =>
      expect(
        screen.getByText("7 % del importe funcional al cerrarse en el tramo alto"),
      ).toBeTruthy(),
    );
    // UNA línea de base y porcentaje POR CADA línea de la liquidación: es lo
    // que prueba que el desglose se pinta entero y no sólo la primera fila.
    // No se busca el número crudo porque el importe sale formateado —miles y
    // moneda—, y afirmar sobre «120000» comprobaría el formateador, no esto.
    expect(screen.getAllByText(/liquidacion.baseYPct/)).toHaveLength(2);
  });

  it("avisa de lo recortado por el tope, que no es haber vendido menos", async () => {
    await montar();
    // Sin esto, una liquidación con techo aplicado parece simplemente más
    // baja, y quien la cobra no sabe que le han quitado algo. Son dos
    // conversaciones distintas.
    await waitFor(() =>
      expect(screen.getByText(/liquidacion.recortado.*1600/)).toBeTruthy(),
    );
  });

  it("marca la reversión, que si no se lee como un error de cálculo", async () => {
    await montar();
    await waitFor(() =>
      expect(screen.getByText("liquidacion.reversion")).toBeTruthy(),
    );
    expect(screen.getByText("Se revierte por devolución dentro del plazo")).toBeTruthy();
  });

  it("dice que una reclamación sigue sin resolver", async () => {
    await montar();
    await waitFor(() =>
      expect(
        screen.getByText(
          "El tramo alto debería aplicarse desde 100.000, no desde 130.000",
        ),
      ).toBeTruthy(),
    );
    // Una disputa abierta y una resuelta se ven igual si sólo sale el motivo,
    // y sin la resolución la misma reclamación vuelve el trimestre siguiente.
    expect(screen.getByText("liquidacion.sinResolver")).toBeTruthy();
  });
});
