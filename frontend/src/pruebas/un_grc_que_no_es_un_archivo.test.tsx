/**
 * El panel de GRC: qué no cuadra hoy, y de qué no se sabe nada.
 *
 * Lo que se afirma aquí es lo que separa un GRC de un archivo:
 *
 *  · que un panel **sin con qué medir no salga en verde**. Es el que más
 *    tranquiliza y el que peor informa: «cumple» y «no hay nada con lo que
 *    comprobarlo» se pintan igual y significan lo contrario;
 *  · que la cobertura **no se invente un 0 %** cuando no se puede medir;
 *  · que lo urgente venga **con su porqué**, no con un color;
 *  · y que un control que apunta a una capacidad **que no existe** se señale:
 *    consta como cobertura y no cubre nada, que es peor que no tenerlo.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

let panel: Record<string, unknown>;
let cobertura: Record<string, unknown>;
let marcos: Record<string, unknown>;

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      if (ruta.startsWith("/api/v1/grc/panel")) return { datos: panel };
      if (ruta.startsWith("/api/v1/grc/cobertura")) return { datos: cobertura };
      return { datos: marcos };
    }),
  };
});

const { Gobierno } = await import("@/paginas/Gobierno");

const CON_DATOS = {
  generado_at: "2026-10-30T08:00:00Z",
  riesgos_abiertos: 3,
  controles_activos: 12,
  controles_evaluados: 9,
  cobertura_pct: 64.5,
  lo_que_urge: [
    {
      que: "Control C-AUD evaluado como «no efectivo»",
      por_que_urge: "Está declarado y no protege: peor que no tenerlo, porque consta",
      orden: 2,
    },
  ],
  medible: true,
  porque: "Hay controles declarados y evaluaciones con las que comprobarlo.",
  todo_en_orden: false,
};

const VACIO = {
  ...CON_DATOS,
  riesgos_abiertos: 0,
  controles_activos: 0,
  controles_evaluados: 0,
  cobertura_pct: null,
  lo_que_urge: [],
  medible: false,
  porque: "No hay controles declarados ni evaluaciones: no se puede comprobar nada.",
  todo_en_orden: false,
};

beforeEach(() => {
  panel = { ...CON_DATOS };
  cobertura = {
    medible: true,
    alcance: "solo capacidades hechas",
    capacidades: 778,
    con_control: 502,
    sin_control: 276,
    pct: 64.5,
    por_seccion: { "00": { total: 120, con_control: 80, pct: 66.67 } },
    capacidades_sin_control: ["CRM-01.01.01.01"],
    controles_sobre_capacidades_inexistentes: [],
  };
  marcos = {};
  vi.clearAllMocks();
});

describe("el panel vacío", () => {
  it("no sale en verde: dice que no se puede medir", async () => {
    panel = { ...VACIO };
    cobertura = { medible: false, motivo: "No hay ningún control declarado" };
    render(<Gobierno />);
    await screen.findByText(VACIO.porque);
    // Y la cobertura no se inventa un cero.
    expect(screen.getByText("grc.sinMedir")).toBeInTheDocument();
    expect(screen.queryByText(/grc\.pct/)).not.toBeInTheDocument();
  });

  it("y «nada pendiente» se dice distinto de «nada que mirar»", async () => {
    panel = { ...VACIO };
    cobertura = { medible: false, motivo: "No hay ningún control declarado" };
    render(<Gobierno />);
    await screen.findByText("grc.urgente");
    expect(screen.getByText("grc.nadaQueMirar")).toBeInTheDocument();
    expect(screen.queryByText("grc.nadaUrgente")).not.toBeInTheDocument();
  });

  it("con datos y sin nada urgente, sí dice que no hay pendientes", async () => {
    panel = { ...CON_DATOS, lo_que_urge: [], todo_en_orden: true };
    render(<Gobierno />);
    await screen.findByText("grc.urgente");
    expect(screen.getByText("grc.nadaUrgente")).toBeInTheDocument();
  });
});

describe("lo urgente", () => {
  it("viene con su porqué, no con un color", async () => {
    render(<Gobierno />);
    await screen.findByText("Control C-AUD evaluado como «no efectivo»");
    expect(
      screen.getByText(/peor que no tenerlo, porque consta/),
    ).toBeInTheDocument();
  });

  it("con datos, el aviso de «no medible» no aparece", async () => {
    render(<Gobierno />);
    await screen.findByText("grc.urgente");
    expect(screen.queryByText(CON_DATOS.porque)).not.toBeInTheDocument();
  });
});

describe("el informe de cobertura", () => {
  it("da el alcance con sus números", async () => {
    render(<Gobierno />);
    await screen.findByText("grc.informeCobertura");
    expect(
      screen.getByText(
        'grc.alcance:{"alcance":"solo capacidades hechas","capacidades":778,"con":502,"sin":276}',
      ),
    ).toBeInTheDocument();
  });

  it("señala los controles que apuntan a una capacidad que no existe", async () => {
    cobertura = {
      ...cobertura,
      controles_sobre_capacidades_inexistentes: [
        { control: "C-X", capacidad: "CRM-99.99.99.99" },
      ],
    };
    render(<Gobierno />);
    await screen.findByText("grc.informeCobertura");
    expect(screen.getByText('grc.huerfanos:{"cuantos":1}')).toBeInTheDocument();
  });

  it("sin huérfanos no avisa de nada", async () => {
    render(<Gobierno />);
    await screen.findByText("grc.informeCobertura");
    expect(screen.queryByText(/grc\.huerfanos/)).not.toBeInTheDocument();
  });
});

describe("el mapeo a marcos", () => {
  it("enseña la referencia con sus controles y su última evaluación", async () => {
    marcos = {
      "ISO 27001": {
        referencias: {
          "A.9": {
            controles: [
              {
                codigo: "C-AUD",
                nombre: "Integridad del rastro",
                activo: true,
                capacidades: [{ id: "CRM-07.03.02.08", titulo: "Evidencias" }],
                ultima_evaluacion: { resultado: "efectivo" },
              },
            ],
          },
        },
      },
    };
    render(<Gobierno />);
    await screen.findByText("ISO 27001");
    expect(screen.getByText("A.9")).toBeInTheDocument();
    expect(
      screen.getByText(
        /grc\.control:\{"codigo":"C-AUD","capacidades":1,"resultado":"efectivo"\}/,
      ),
    ).toBeInTheDocument();
  });

  it("un control sin evaluar lo dice, en vez de dejarlo en blanco", async () => {
    marcos = {
      "ISO 27001": {
        referencias: {
          "A.9": {
            controles: [
              {
                codigo: "C-NUE",
                nombre: "Recién declarado",
                activo: true,
                capacidades: [],
                ultima_evaluacion: null,
              },
            ],
          },
        },
      },
    };
    render(<Gobierno />);
    await screen.findByText("ISO 27001");
    expect(
      screen.getByText(
        /grc\.control:\{"codigo":"C-NUE","capacidades":0,"resultado":"grc.sinEvaluar"\}/,
      ),
    ).toBeInTheDocument();
  });

  it("sin ningún marco declarado lo dice", async () => {
    render(<Gobierno />);
    expect(await screen.findByText("grc.sinMarcos")).toBeInTheDocument();
  });
});
