/**
 * Una campaña: qué prometió, qué está pasando y qué costó cada cosa.
 *
 * Lo que se afirma aquí es lo que el servidor ya decía y ninguna pantalla
 * enseñaba:
 *
 *  · que un objetivo declarado sobre algo que el embudo **no mide** salga como
 *    «no comparable» y no contra cero. Contra cero se lee como un fracaso;
 *  · que el **ROI sólo aparezca cuando se puede medir**: sin ingresos
 *    atribuidos, un 0 % y un «no se sabe» se leen igual y son lo contrario;
 *  · que los inscritos **sin marcar** de un evento vayan delante de la tasa,
 *    porque una tasa calculada ignorándolos es una tasa inventada;
 *  · y que el embudo se pueda **pinchar**: dice cuántos hay en cada estado, y
 *    lo que hace falta para trabajar es quiénes.
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

let rendimiento: Record<string, unknown>;
let evento: Record<string, unknown> | null;
const pedidas: string[] = [];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      pedidas.push(ruta);
      if (ruta.includes("/consumo"))
        return {
          datos: {
            campana: "Renovaciones Q4",
            presupuesto: "10000.00",
            gasto: "4000.00",
            gasto_propio: "3000.00",
            gasto_descendientes: "1000.00",
            restante: "6000.00",
            consumido_pct: 40,
            sobrepasado: false,
            sin_presupuesto: false,
            hijos_presupuestados_de_mas: [],
          },
        };
      if (ruta.includes("/rendimiento")) return { datos: rendimiento };
      if (ruta.includes("/embudo"))
        return {
          datos: {
            campana: "Renovaciones Q4",
            miembros: 320,
            excluidos: 12,
            embudo: { objetivo: 320, abierto: 180, clicado: 40 },
            conversion_pct: 3.1,
          },
        };
      if (ruta.includes("/evento")) {
        if (evento === null) throw new Error("no es un evento");
        return { datos: evento };
      }
      if (ruta.includes("/miembros"))
        return {
          datos: [
            {
              objeto: "contacto",
              objeto_id: "c-1",
              estado: "clicado",
              fuente_alta: "segmento",
              asistio: null,
              alta_at: null,
              estado_at: null,
            },
          ],
        };
      return { datos: {} };
    }),
  };
});

const { Campana } = await import("@/paginas/Campana");

function montar() {
  return render(
    <MemoryRouter initialEntries={["/m/campanas/campana/c-1"]}>
      <Routes>
        <Route path="/m/campanas/campana/:id" element={<Campana />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  pedidas.length = 0;
  evento = null;
  rendimiento = {
    campana: "Renovaciones Q4",
    gasto: "4000.00",
    leads: 40,
    convertidos: 8,
    coste_por_lead: "100.00",
    coste_por_conversion: "500.00",
    ingresos_atribuidos: "20000.00",
    roi_pct: 400,
    roi_medible: true,
    plan_vs_real: {
      clicado: { objetivo: 300, real: 40 },
      asistencia: { objetivo: 50, real: null },
    },
    aviso: "",
  };
  vi.clearAllMocks();
});

describe("el plan contra el real", () => {
  it("pone el objetivo al lado del número", async () => {
    montar();
    await screen.findByText("campana.planVsReal");
    expect(
      screen.getByText('campana.deObjetivo:{"real":40,"objetivo":300}'),
    ).toBeInTheDocument();
  });

  it("un objetivo que el embudo no mide NO se compara contra cero", async () => {
    montar();
    await screen.findByText("campana.planVsReal");
    expect(
      screen.getByText('campana.noComparable:{"objetivo":50}'),
    ).toBeInTheDocument();
    // Y en concreto, no aparece como «0 de 50», que se lee como un fracaso.
    expect(
      screen.queryByText('campana.deObjetivo:{"real":0,"objetivo":50}'),
    ).not.toBeInTheDocument();
  });
});

describe("el ROI", () => {
  it("sale cuando se puede medir", async () => {
    montar();
    await screen.findByText('campana.roi:{"pct":400}');
  });

  it("y cuando no, lo dice en vez de poner un cero", async () => {
    rendimiento = {
      ...rendimiento,
      ingresos_atribuidos: null,
      roi_pct: null,
      roi_medible: false,
      aviso: "Sin ingresos atribuidos no se puede calcular el ROI.",
    };
    montar();
    await screen.findByText("campana.roiNoMedible");
    expect(
      screen.getByText("Sin ingresos atribuidos no se puede calcular el ROI."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/campana\.roi:/)).not.toBeInTheDocument();
  });
});

describe("el embudo", () => {
  it("separa el gasto propio del de las tácticas", async () => {
    montar();
    await screen.findByText(
      'campana.gasto:{"gasto":"4000.00","propio":"3000.00","hijos":"1000.00"}',
    );
  });

  it("se pincha y enseña QUIÉNES, no sólo cuántos", async () => {
    montar();
    await screen.findByText('campana.enEstado:{"estado":"clicado","cuantos":40}');

    await userEvent.click(
      screen.getByText('campana.enEstado:{"estado":"clicado","cuantos":40}'),
    );

    expect(await screen.findByText("c-1")).toBeInTheDocument();
    // Y de dónde salió: uno metido a mano y uno del segmento no se tratan igual.
    expect(screen.getByText("segmento")).toBeInTheDocument();
    expect(pedidas.some((r) => r.includes("/miembros?estado=clicado"))).toBe(true);
  });
});

describe("el evento", () => {
  it("no se pinta si la campaña no es un evento", async () => {
    montar();
    await screen.findByText("campana.embudo");
    expect(screen.queryByText("campana.evento")).not.toBeInTheDocument();
  });

  it("avisa de los sin marcar antes de dar la tasa", async () => {
    evento = {
      campana: "Feria",
      aforo: 200,
      inscritos: 150,
      asistieron: 90,
      no_aparecieron: 20,
      sin_marcar: 40,
      tasa_asistencia_pct: null,
      medible: false,
    };
    montar();
    await screen.findByText("campana.evento");
    expect(screen.getByText('campana.sinMarcar:{"cuantos":40}')).toBeInTheDocument();
    expect(screen.getByText("campana.tasaNoMedible")).toBeInTheDocument();
  });

  it("con todos marcados da la tasa", async () => {
    evento = {
      campana: "Feria",
      aforo: 200,
      inscritos: 150,
      asistieron: 120,
      no_aparecieron: 30,
      sin_marcar: 0,
      tasa_asistencia_pct: 80,
      medible: true,
    };
    montar();
    await screen.findByText('campana.tasa:{"pct":80}');
    expect(screen.queryByText(/campana\.sinMarcar/)).not.toBeInTheDocument();
  });
});
