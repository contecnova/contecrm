/**
 * Modelos entrenados con el histórico y el asistente que actúa
 * (CRM-02.01.02.02, CRM-05.02.01.02, CRM-05.02.01.03, CRM-02.01.01.08,
 * CRM-04.03.02.02, CRM-05.02.02.04).
 *
 * Lo que fijan, en el orden en que duele si se rompe:
 *
 *   · la ficha enseña el número CON lo que lo sube y lo que lo baja, y cuando
 *     no hay modelo dice el porqué en vez de un número;
 *   · entrenar dice si se publicó o no, y por qué;
 *   · la acción del asistente NO se hace al preguntar: se ve, se puede
 *     corregir, y sólo confirmar la manda — con los argumentos corregidos;
 *   · la pregunta a los datos enseña la consulta que se hizo.
 *
 * Los rótulos se comprueban por su clave de traducción, como en el resto.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

type Doble = (
  ruta: string,
  opciones?: { metodo?: string; cuerpo?: unknown },
) => unknown;

const pedidas: { ruta: string; metodo: string; cuerpo?: unknown }[] = [];

async function con(doble: Doble) {
  vi.resetModules();
  pedidas.length = 0;
  vi.doMock("@/lib/api", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/api");
    return {
      ...real,
      llamar: async (
        ruta: string,
        opciones?: { metodo?: string; cuerpo?: unknown },
      ) => {
        pedidas.push({
          ruta,
          metodo: (opciones?.metodo ?? "GET").toUpperCase(),
          cuerpo: opciones?.cuerpo,
        });
        return { datos: doble(ruta, opciones) };
      },
    };
  });
}

describe("predicción en la ficha", () => {
  it("enseña el número con lo que lo sube y lo que lo baja, y el porqué de lo que no hay", async () => {
    await con(() => ({
      predicciones: [
        {
          tipo: "propension",
          hay: true,
          valor: 0.34,
          factores: [
            {
              variable: "abiertas",
              etiqueta: "Abiertas",
              valor: 3,
              aporta: 0.95,
            },
            {
              variable: "perdidas",
              etiqueta: "Perdidas",
              valor: 6,
              aporta: -0.1,
            },
          ],
          modelo: { version: 1, metricas: { auc: 0.64, muestras: 107 } },
        },
        {
          tipo: "siguiente_oferta",
          hay: false,
          porque: "No hay bastantes cuentas.",
        },
      ],
    }));
    const { PrediccionDelRegistro } =
      await import("@/componentes/PrediccionDelRegistro");
    render(<PrediccionDelRegistro objeto="cuenta" id="c1" />);
    expect(await screen.findByText("34 %")).toBeTruthy();
    expect(screen.getByText("Abiertas: 3").className).toContain(
      "chip-dato--si",
    );
    expect(screen.getByText("Perdidas: 6").className).toContain(
      "chip-dato--mal",
    );
    expect(screen.getByText("No hay bastantes cuentas.")).toBeTruthy();
    expect(pedidas[0]?.ruta).toBe("/api/v1/ia/predictivo/cuenta/c1");

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "prediccion.recalcular" }));
    await waitFor(() =>
      expect(pedidas.at(-1)?.ruta).toContain("recalcular=true"),
    );
  });
});

describe("modelos predictivos", () => {
  it("entrenar dice si se publicó y por qué", async () => {
    await con((ruta) => {
      if (ruta.endsWith("/versiones"))
        return { versiones: [], entrenables: { cierre: "oportunidad" } };
      if (ruta.endsWith("/programaciones")) return [];
      if (ruta.endsWith("/entrenar"))
        return {
          tipo: "cierre",
          entrenado: true,
          publicado: false,
          version: 10,
          porque: ["AUC 0.38, por debajo del mínimo 0.60."],
          metricas: { auc: 0.38, muestras: 114 },
          casos: 458,
          entreno: 344,
          validacion: 114,
          corte: "2026-09-10",
        };
      return {};
    });
    const { ModelosPredictivos } = await import("@/paginas/ModelosPredictivos");
    render(
      <MemoryRouter>
        <ModelosPredictivos />
      </MemoryRouter>,
    );
    await userEvent
      .setup()
      .click(
        await screen.findByRole("button", {
          name: /modelosPredictivos.entrenar/,
        }),
      );
    expect(
      await screen.findByText("modelosPredictivos.noPublicado"),
    ).toBeTruthy();
    expect(
      screen.getByText("AUC 0.38, por debajo del mínimo 0.60."),
    ).toBeTruthy();
    expect(
      pedidas.some(
        (p) => p.metodo === "POST" && p.ruta.endsWith("/cierre/entrenar"),
      ),
    ).toBe(true);
  });
});

describe("asistente", () => {
  it("propone sin hacer, y confirma con los argumentos corregidos", async () => {
    await con((ruta, opciones) => {
      if (ruta.endsWith("/conversar"))
        return {
          texto: "Defender el valor antes del descuento [1].",
          respondida: true,
          fuentes: [
            { n: 1, fuente: "leccion", id: "l1", titulo: "Serie corta" },
          ],
          porque: "",
          accion_propuesta: {
            id: "a1",
            accion: "crear_tarea",
            nombre: "Crear una tarea",
            argumentos: { asunto: "Llamar" },
            campos: { asunto: { tipo: "texto", obligatorio: true } },
            ruta: "POST /api/v1/activities",
            porque: "",
            estado: "propuesta",
            faltan: [],
            codigo_respuesta: null,
            resultado: {},
          },
        };
      if (ruta.includes("/acciones/"))
        return {
          id: "a1",
          accion: "crear_tarea",
          nombre: "Crear una tarea",
          argumentos: (
            opciones?.cuerpo as { argumentos: Record<string, string> }
          ).argumentos,
          campos: { asunto: { tipo: "texto" } },
          ruta: "POST /api/v1/activities",
          porque: "",
          estado: "ejecutada",
          faltan: [],
          codigo_respuesta: 201,
          resultado: { id: "t1" },
        };
      return {};
    });
    const { Asistente } = await import("@/paginas/Asistente");
    render(
      <MemoryRouter>
        <Asistente />
      </MemoryRouter>,
    );
    const u = userEvent.setup();
    const [caja] = await screen.findAllByLabelText("asistente.pregunta");
    await u.type(caja!, "Crea una tarea");
    await u.click(
      screen.getAllByRole("button", { name: /asistente.preguntar/ })[0]!,
    );
    expect(await screen.findByText("Serie corta")).toBeTruthy();
    // Propuesta a la vista, y NADA ejecutado todavía.
    expect(screen.getByText("asistente.propone")).toBeTruthy();
    expect(pedidas.some((p) => p.ruta.includes("/acciones/"))).toBe(false);

    const asunto = screen.getByDisplayValue("Llamar");
    await u.clear(asunto);
    await u.type(asunto, "Llamar a Ebro");
    await u.click(screen.getByRole("button", { name: /asistente.confirmar/ }));
    await waitFor(() =>
      expect(pedidas.at(-1)).toMatchObject({
        ruta: "/api/v1/ia/asistente/acciones/a1",
        metodo: "POST",
        cuerpo: { confirmar: true, argumentos: { asunto: "Llamar a Ebro" } },
      }),
    );
    expect(await screen.findByText("asistente.estados.ejecutada")).toBeTruthy();
  });

  it("la pregunta a los datos enseña la consulta que se hizo", async () => {
    await con((ruta) =>
      ruta.endsWith("/preguntar-datos")
        ? {
            interpretacion: "Ganadas de más de 50.000",
            ejecutado: true,
            respuesta: "Hay 115 registros.",
            total: 115,
            leidas: 115,
            parcial: false,
            filas: [],
            consulta: {
              metodo: "GET",
              ruta: "/api/v1/opportunities",
              parametros: { estado: "ganada", importe__mayor: 50000 },
            },
          }
        : {},
    );
    const { Asistente } = await import("@/paginas/Asistente");
    render(
      <MemoryRouter>
        <Asistente />
      </MemoryRouter>,
    );
    const u = userEvent.setup();
    const cajas = await screen.findAllByLabelText("asistente.pregunta");
    await u.type(cajas[1]!, "cuántas ganadas");
    await u.click(
      screen.getAllByRole("button", { name: /asistente.preguntar/ })[1]!,
    );
    expect(await screen.findByText("Hay 115 registros.")).toBeTruthy();
    expect(
      screen.getByText(
        "GET /api/v1/opportunities?estado=ganada&importe__mayor=50000",
      ),
    ).toBeTruthy();
  });
});
