/**
 * La ficha de un periodo de previsión.
 *
 * El módulo listaba los periodos y ahí se acababa. Un periodo de previsión es
 * lo contrario de una fila: es **un número que alguien defiende en un comité**,
 * y lo que hace falta para defenderlo no se alcanzaba desde ninguna pantalla.
 *
 * Lo que se afirma es el dato que sólo puede venir de la respuesta de su ruta.
 * Validado plantando: quitar cada panel pone en rojo su prueba y sólo la suya.
 *
 * Los dos avisos incómodos tienen prueba propia a propósito, porque son los
 * que de verdad cambian una decisión: que ajustar **alejó** del real, y que
 * hay ventas empujadas **más de una vez**.
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
      let datos: unknown = {};
      if (ruta.endsWith("/ajustes"))
        datos = [
          {
            id: "aj-1",
            ambito: "equipo",
            categoria: "comprometido",
            bruto: "100000",
            ajustado: "130000",
            delta: "30000",
            motivo: "el cliente confirmó por teléfono",
            por: "u-1",
          },
        ];
      else if (ruta.endsWith("/acierto-ajustes"))
        datos = {
          medible: true,
          real: "95000",
          bruto: "100000",
          ajustado: "130000",
          error_sin_ajuste: "5000",
          error_con_ajuste: "35000",
        };
      else if (ruta.endsWith("/instantaneas"))
        datos = [
          {
            id: "f-1",
            etiqueta: "Semana 40",
            tomada_at: "2026-10-05T08:00:00+00:00",
            moneda: "EUR",
            totales: { comprometido: "80000", probable: "20000", _meta: "x" },
          },
        ];
      else if (ruta.endsWith("/deslizamiento"))
        datos = {
          periodo: "2026-Q4",
          oportunidades_con_cambio_de_fecha: 3,
          empujadas: 3,
          dias_empujados: 120,
          empujadas_mas_de_una_vez: 2,
          detalle: [
            { nombre: "Acme", dias_netos: 92, veces: 2 },
            { nombre: "Beta", dias_netos: 28, veces: 1 },
          ],
        };
      else if (ruta.includes("/desglose"))
        datos = {
          periodo: "2026-Q4",
          por: "familia",
          moneda: "EUR",
          grupos: { Licencias: { importe: "90000", ponderado: "54000", lineas: 4 } },
          grupos_sin_tipo_de_cambio: ["Servicios"],
        };
      else
        datos = {
          periodo: "2026-Q4",
          moneda: "EUR",
          total: "150000",
          ponderado: "90000",
          compromiso: "60000",
          oportunidades: 12,
          por_categoria: {
            comprometido: { importe: "60000", ponderado: "54000", oportunidades: 4 },
          },
          sin_tipo_de_cambio: [{ id: "x" }],
          aviso: "1 oportunidades no se han podido convertir a EUR y NO están sumadas",
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
  const { PeriodoDePrevision } = await import("@/paginas/PeriodoDePrevision");
  return render(
    <MemoryRouter initialEntries={["/m/prevision/periodo/2026-Q4"]}>
      <Routes>
        <Route path="/m/prevision/periodo/:clave" element={<PeriodoDePrevision />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("un periodo de previsión se puede defender", () => {
  beforeEach(() => {
    pedidas.length = 0;
  });

  it("pone el aviso de lo no convertido PEGADO al número", async () => {
    await montar();
    // Un total al que le faltan importes en silencio es peor que uno que
    // avisa, porque nadie lo cuestiona.
    await waitFor(() =>
      expect(
        screen.getByText(
          "1 oportunidades no se han podido convertir a EUR y NO están sumadas",
        ),
      ).toBeTruthy(),
    );
  });

  it("dice que ajustar ALEJÓ del real, no sólo que hubo ajuste", async () => {
    await montar();
    await waitFor(() =>
      expect(screen.getByText("el cliente confirmó por teléfono")).toBeTruthy(),
    );
    // El panel incómodo: con 35.000 de error ajustando y 5.000 sin tocar
    // nada, ajustar empeoró la previsión. Sin esta comparación nadie se
    // entera, porque al cerrar se mira el real contra el objetivo.
    expect(screen.getByText(/prevision.ajustarAlejo.*35000/)).toBeTruthy();
  });

  it("avisa de las empujadas MÁS DE UNA VEZ, no sólo de cuántas se movieron", async () => {
    await montar();
    await waitFor(() =>
      expect(screen.getByText(/prevision.masDeUnaVez.*"cuantas":2/)).toBeTruthy(),
    );
    expect(screen.getByText("Acme")).toBeTruthy();
  });

  it("desglosa y dice qué grupos se han quedado fuera por el cambio", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("Licencias")).toBeTruthy());
    // Un desglose al que le falta una familia entera por un tipo de cambio
    // que no estaba se lee como «esa familia no vendió nada».
    expect(screen.getByText(/prevision.gruposSinCambio.*Servicios/)).toBeTruthy();
  });

  it("enseña las fotos con cuándo se tomaron", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("Semana 40")).toBeTruthy());
    expect(screen.getByText("2026-10-05")).toBeTruthy();
  });
});
