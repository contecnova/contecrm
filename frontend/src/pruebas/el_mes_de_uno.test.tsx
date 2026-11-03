/**
 * El calendario, y lo que lo distingue de una lista ordenada por fecha.
 *
 * Tres cosas, y las tres son las que se pueden hacer mal sin que se note:
 *
 *  · **Se pregunta por la rejilla entera, no por el mes.** Las casillas de los
 *    días de antes y de después existen en la pantalla; si no se piden, salen
 *    vacías con la misma cara que un día sin nada. «No hay» y «no se ha
 *    mirado» se leen igual y significan lo contrario — y un calendario se usa
 *    para decidir que hay hueco.
 *
 *  · **El reloj sólo sale cuando distingue algo.** Marca las que sólo vencen,
 *    y eso informa únicamente si hay también de las que empiezan. Medido en el
 *    navegador el 03-11-2026: ninguna actividad del mes traía principio, así
 *    que el reloj salía en las ciento y pico. Una marca que llevan todos es
 *    decoración.
 *
 *  · **Un mes recortado se dice.** El servidor pagina, y quedarse con lo que
 *    cupo sin avisar enseña un mes a medias con cara de estar entero.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

/** Lo que se ha pedido al servidor, para poder mirar el rango. */
let pedidas: string[] = [];
let paginas: { items: unknown[]; siguiente: string | null; hay_mas: boolean }[] = [];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      pedidas.push(ruta);
      const pagina = paginas.shift() ?? { items: [], siguiente: null, hay_mas: false };
      return { datos: pagina };
    }),
  };
});

const { Calendario } = await import("@/paginas/Calendario");

/** Una actividad del mes en curso, con el día que se le diga. */
function actividad(id: string, dia: number, conPrincipio: boolean) {
  const hoy = new Date();
  const cuando = new Date(hoy.getFullYear(), hoy.getMonth(), dia, 10, 0, 0).toISOString();
  return {
    id,
    tipo: "reunion",
    asunto: `Asunto ${id}`,
    estado: "pendiente",
    prioridad: "normal",
    cuenta_id: "c-1",
    objeto: "cuenta",
    objeto_id: "c-1",
    vence_at: cuando,
    inicio_at: conPrincipio ? cuando : null,
    fin_at: null,
  };
}

function pintar() {
  return render(
    <MemoryRouter>
      <Calendario />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  pedidas = [];
  paginas = [];
  vi.clearAllMocks();
});

describe("el calendario", () => {
  it("pregunta por la rejilla entera, no sólo por el mes", async () => {
    paginas = [{ items: [actividad("a", 10, false)], siguiente: null, hay_mas: false }];
    pintar();
    await screen.findByText("Asunto a");

    expect(pedidas).toHaveLength(1);
    const url = new URL(`http://x${pedidas[0]}`);
    const desde = new Date(url.searchParams.get("vence_at__desde") ?? "");
    const hasta = new Date(url.searchParams.get("vence_at__hasta") ?? "");
    const hoy = new Date();
    const primeroDelMes = new Date(hoy.getFullYear(), hoy.getMonth(), 1);
    const siguienteMes = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 1);

    // Empieza ANTES del día 1 salvo que el día 1 caiga en lunes, y acaba
    // DESPUÉS del último salvo que el mes termine en domingo. En los dos casos
    // la rejilla son seis semanas, así que el rango dura 42 días exactos: eso
    // es lo que se afirma, y no hace falta saber en qué día cae el mes.
    const dias = Math.round((hasta.getTime() - desde.getTime()) / 86_400_000);
    expect(dias).toBe(42);
    expect(desde.getTime()).toBeLessThanOrEqual(primeroDelMes.getTime());
    expect(hasta.getTime()).toBeGreaterThanOrEqual(siguienteMes.getTime());
  });

  it("el reloj del vencimiento no sale cuando lo llevarían todas", async () => {
    // Las tres sólo vencen: la marca no separaría nada.
    paginas = [
      {
        items: [actividad("a", 5, false), actividad("b", 6, false), actividad("c", 7, false)],
        siguiente: null,
        hay_mas: false,
      },
    ];
    const { container } = pintar();
    await screen.findByText("Asunto a");
    // Se han pintado las tres: una lista vacía daría verde sin mirar.
    expect(screen.getByText("Asunto b")).toBeInTheDocument();
    expect(container.textContent).not.toContain("calendario.soloVence");
  });

  it("y sí sale cuando hay de las dos clases", async () => {
    paginas = [
      {
        items: [actividad("a", 5, false), actividad("b", 6, true)],
        siguiente: null,
        hay_mas: false,
      },
    ];
    const { container } = pintar();
    await screen.findByText("Asunto a");
    expect(screen.getByText("Asunto b")).toBeInTheDocument();
    // Una sola vez: la que sólo vence, no la que empieza.
    const marcas = [...container.querySelectorAll(".sr-only")].filter(
      (e) => e.textContent === "calendario.soloVence",
    );
    expect(marcas).toHaveLength(1);
  });

  it("un mes que no cabe entero lo dice, en vez de enseñarlo a medias", async () => {
    // Cinco páginas y en la última el servidor sigue diciendo que hay más.
    paginas = Array.from({ length: 5 }, (_, i) => ({
      items: [actividad(`p${i}`, i + 1, false)],
      siguiente: "cursor",
      hay_mas: true,
    }));
    pintar();
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("calendario.faltan"),
    );
    // Y dice cuántas se están enseñando: «faltan algunas» sin el número no
    // deja saber si falta una o la mitad.
    expect(screen.getByRole("status").textContent).toContain('"cuantas":5');
    expect(pedidas).toHaveLength(5);
  });

  it("sin nada en la rejilla lo dice, y distinto si el filtro es «sólo las mías»", async () => {
    paginas = [{ items: [], siguiente: null, hay_mas: false }];
    pintar();
    expect(await screen.findByText("calendario.ningunaEsteMes")).toBeInTheDocument();
    expect(screen.getByText("calendario.ningunaPorque")).toBeInTheDocument();
  });

  it("una actividad lleva al registro del que cuelga", async () => {
    paginas = [{ items: [actividad("a", 12, false)], siguiente: null, hay_mas: false }];
    const { container } = pintar();
    await screen.findByText("Asunto a");
    const enlace = within(container).getByText("Asunto a").closest("a");
    expect(enlace).toHaveAttribute("href", "/m/cuentas/cuenta/c-1");
  });
});
