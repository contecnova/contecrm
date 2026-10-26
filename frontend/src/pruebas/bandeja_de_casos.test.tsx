/**
 * La bandeja de casos: lo que la pantalla tiene que decir y lo que no
 * (CRM-07.04.03.17).
 *
 * El escenario general ya comprueba que la fila llega. Aquí van las dos cosas
 * que se pueden romper sin que eso falle, y que mienten al que atiende:
 *
 *   · un caso **ya incumplido** enseñando una cuenta atrás. Pasa en cuanto el
 *     motor de SLA mueve la fecha de vencimiento después de marcarlo, y
 *     «vence en 48 h» sobre un caso incumplido niega el incumplimiento;
 *   · un montón recortado que **parece completo**. El servidor devuelve los
 *     primeros de cada montón con su total aparte; si la pantalla no dice
 *     cuántos quedan fuera, la lista se lee como «esto es todo».
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const BANDEJA = {
  riesgo_horas: 4,
  ahora: "2026-10-26T09:00:00Z",
  incumplidos: {
    total: 9,
    casos: [
      {
        id: "c1",
        codigo: "C-1",
        asunto: "Marcado por el motor",
        estado: "nuevo",
        prioridad: "alta",
        severidad: "media",
        cuenta_id: null,
        equipo: null,
        // Vence dentro de 48 h y aun así incumplió: el motor lo marcó y
        // después le movieron la fecha.
        vence_resolucion_at: "2099-01-01T00:00:00Z",
        incumplio_resolucion: true,
      },
    ],
  },
  en_riesgo: { total: 0, casos: [] },
  resto: { total: 0, casos: [] },
};

async function montar(datos: unknown = BANDEJA) {
  vi.resetModules();
  vi.doMock("@/lib/api", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/api");
    return { ...real, llamar: async () => ({ retenidos: [], version: null, datos }) };
  });
  const { Casos } = await import("@/paginas/Casos");
  return render(
    <MemoryRouter>
      <Casos />
    </MemoryRouter>,
  );
}

describe("la bandeja", () => {
  it("un caso incumplido no enseña cuenta atrás", async () => {
    const { container } = await montar();
    await screen.findByText("Marcado por el motor");

    // Lo dice incumplido…
    expect(container.textContent).toContain("casos.incumplido");
    // …y NO dice «vence en», que sobre un caso incumplido es negar el hecho.
    expect(container.textContent).not.toContain("casos.vence");
  });

  it("dice cuántos quedan fuera del montón", async () => {
    const { container } = await montar();
    await screen.findByText("Marcado por el motor");
    // 9 en total y 1 devuelto: la lista no puede leerse como «esto es todo».
    expect(container.textContent).toContain("casos.yMas");
  });

  it("se puede entrar al caso desde la bandeja", async () => {
    // Una bandeja de la que no se puede entrar a trabajar es un informe.
    await montar();
    const enlace = await screen.findByRole("link", { name: /Marcado por el motor/ });
    expect(enlace.getAttribute("href")).toContain("/m/casos/caso/c1");
  });

  it("sin casos abiertos lo dice, y no deja la pantalla en blanco", async () => {
    const { container } = await montar({
      riesgo_horas: 4,
      ahora: "2026-10-26T09:00:00Z",
      incumplidos: { total: 0, casos: [] },
      en_riesgo: { total: 0, casos: [] },
      resto: { total: 0, casos: [] },
    });
    expect(await screen.findByText("casos.ninguno")).toBeInTheDocument();
    // Y no se pintan los tres montones vacíos, que parecerían un error de carga.
    expect(container.textContent).not.toContain("casos.incumplidos");
  });

  it("dice con cuánta antelación avisa", async () => {
    // Sin eso, ver un caso en «a punto de vencer» y otro parecido fuera no
    // tiene explicación posible, y acaba en una pregunta a soporte.
    const { container } = await montar();
    await screen.findByText("Marcado por el motor");
    expect(container.textContent).toContain("casos.entradillaConUmbral");
  });
});
