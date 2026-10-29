/**
 * Por qué este lead tiene esta puntuación.
 *
 * Lo que se afirma aquí es lo que hace que el número se accione:
 *
 *  · que los **dos ejes salgan separados**. Sumarlos borra la diferencia que
 *    decide a quién se llama: un director de compras callado y un estudiante
 *    muy activo pueden dar el mismo total y no se hace lo mismo con los dos;
 *  · que cada eje lleve **su umbral al lado**. «62» no dice si falta mucho;
 *  · que se diga **qué le falta** para el escalón siguiente, y que lo que falta
 *    de encaje NO se gana con actividad — es lo que cambia qué se hace con el
 *    lead;
 *  · que el **decaimiento** se enseñe aparte y con su regla. Sin él, un lead
 *    que hizo muchas cosas y tiene poco interés parece un scoring roto.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

let explicacion: Record<string, unknown>;

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async () => ({ datos: explicacion })),
  };
});

const { PuntuacionDeLead } = await import("@/paginas/PuntuacionDeLead");

const BASE = {
  lead_id: "l-1",
  modelo: "estandar v3",
  interes: 30,
  encaje: 60,
  grado: "B",
  calificacion: "mql",
  por_interes: [{ eje: "interes", regla: "descargó el comparativo", puntos: 30 }],
  por_encaje: [{ eje: "encaje", regla: "sector objetivo", puntos: 60 }],
  perdido_por_inactividad: 0,
  ultima_actividad_at: "2026-10-20T09:00:00Z",
  calculado_at: "2026-10-29T08:00:00Z",
  umbrales: {
    mql: { interes: 20, encaje: 50 },
    sql: { interes: 70, encaje: 50 },
  },
  grados: [
    { desde: 80, grado: "A" },
    { desde: 50, grado: "B" },
    { desde: 0, grado: "C" },
  ],
  decaimiento: { puntos: 10, cada_dias: 30, interes_minimo: 5, solo_afecta_a: "interes" },
  le_falta: {
    hasta: "sql",
    alcanzable: true,
    interes: 40,
    encaje: 0,
    que_significa: "Le faltan 40 de interés para «sql», y eso se gana con actividad.",
  },
  aviso: "",
};

function montar() {
  return render(
    <MemoryRouter initialEntries={["/m/segmentos/lead/l-1/puntuacion"]}>
      <Routes>
        <Route
          path="/m/segmentos/lead/:id/puntuacion"
          element={<PuntuacionDeLead />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  explicacion = { ...BASE };
  vi.clearAllMocks();
});

describe("los dos ejes", () => {
  it("salen separados, cada uno con su desglose", async () => {
    montar();
    await screen.findByText("puntuacion.interes");
    expect(screen.getByText("puntuacion.encaje")).toBeInTheDocument();
    expect(screen.getByText("descargó el comparativo")).toBeInTheDocument();
    expect(screen.getByText("sector objetivo")).toBeInTheDocument();
    // Y los dos números, sin sumar: 30 y 60, nunca 90.
    expect(screen.getByText("30")).toBeInTheDocument();
    expect(screen.getByText("60")).toBeInTheDocument();
    expect(screen.queryByText("90")).not.toBeInTheDocument();
  });

  it("cada eje lleva su umbral al lado", async () => {
    montar();
    await screen.findByText("puntuacion.interes");
    expect(screen.getByText('puntuacion.umbralEs:{"umbral":20}')).toBeInTheDocument();
    expect(screen.getByText('puntuacion.umbralEs:{"umbral":50}')).toBeInTheDocument();
  });

  it("si el modelo no declara umbral en un eje, lo dice en vez de poner cero", async () => {
    explicacion = {
      ...BASE,
      umbrales: { mql: { interes: null, encaje: 50 }, sql: { interes: 70, encaje: 50 } },
    };
    montar();
    await screen.findByText("puntuacion.interes");
    expect(screen.getByText("puntuacion.sinUmbral")).toBeInTheDocument();
  });
});

describe("qué le falta", () => {
  it("dice cuánto y que el interés se gana con actividad", async () => {
    montar();
    expect(
      await screen.findByText(
        "Le faltan 40 de interés para «sql», y eso se gana con actividad.",
      ),
    ).toBeInTheDocument();
  });

  it("un SQL no tiene escalón por encima, y se dice", async () => {
    explicacion = { ...BASE, calificacion: "sql", le_falta: null };
    montar();
    expect(await screen.findByText("puntuacion.yaEsSql")).toBeInTheDocument();
  });

  it("un escalón sin umbral declarado se enseña como aviso, no como meta", async () => {
    explicacion = {
      ...BASE,
      le_falta: {
        hasta: "sql",
        alcanzable: false,
        que_significa:
          "El modelo no declara umbral de «sql», así que ningún lead llega a serlo por puntuación.",
      },
    };
    const { container } = montar();
    await screen.findByText(/El modelo no declara umbral/);
    expect(container.querySelector(".border-warning\\/40")).not.toBeNull();
  });
});

describe("el decaimiento", () => {
  it("va aparte, con su regla y diciendo que el encaje no decae", async () => {
    explicacion = { ...BASE, perdido_por_inactividad: 25 };
    montar();
    await screen.findByText("puntuacion.inactividad");
    expect(screen.getByText('puntuacion.perdidos:{"puntos":25}')).toBeInTheDocument();
    expect(
      screen.getByText(
        'puntuacion.reglaDecaimiento:{"puntos":10,"dias":30,"minimo":5}',
      ),
    ).toBeInTheDocument();
  });

  it("sin pérdida lo dice, en vez de dejar el hueco en blanco", async () => {
    montar();
    await screen.findByText("puntuacion.inactividad");
    expect(screen.getByText("puntuacion.sinDecaer")).toBeInTheDocument();
  });
});

describe("el grado", () => {
  it("sale con el tramo desde el que se gana, no como una letra suelta", async () => {
    montar();
    await screen.findByText('puntuacion.gradoDesde:{"grado":"B","desde":50}');
    // Y los tres tramos, de mayor a menor, que es como se aplican.
    expect(screen.getByText('puntuacion.tramo:{"grado":"A","desde":80}')).toBeInTheDocument();
    expect(screen.getByText('puntuacion.tramo:{"grado":"C","desde":0}')).toBeInTheDocument();
  });
});

describe("el modelo desfasado", () => {
  it("se avisa: comparar dos leads puntuados con modelos distintos no vale", async () => {
    explicacion = {
      ...BASE,
      aviso: "Calculado con una versión anterior del modelo; vuelve a puntuarlo.",
    };
    montar();
    expect(
      await screen.findByText(/versión anterior del modelo/),
    ).toBeInTheDocument();
  });
});
