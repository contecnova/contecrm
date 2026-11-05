/**
 * La ruta de etapas no es un indicador: se pulsa y se mueve.
 *
 * Lo pidió quien lo usa el 05-11-2026 mirando una oportunidad: «clicando en
 * alguno de estos deberíamos poder movernos». Hasta entonces la ruta decía
 * dónde estabas y no dejaba ir: cambiar de etapa —el gesto más repetido del
 * día en una oportunidad— había que hacerlo entrando en el formulario de
 * edición. Cuatro clics para lo que en Lightning es uno.
 *
 * Dos cosas que fija esto, y las dos importan:
 *
 *   · se puede pulsar lo que NO es la etapa de ahora;
 *   · la de ahora **no** es un botón. Pulsar donde ya estás no hace nada, y un
 *     botón que no hace nada enseña a desconfiar de los de al lado.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

const { DatosClave } = await import("@/componentes/DatosClave");

const PASOS = ["cualificacion", "negociacion", "ganada"];

function pintar(alElegir?: (paso: string) => void) {
  return render(
    <MemoryRouter>
      <DatosClave
        recurso={{ nombre: "Oportunidades", listar: "/api/v1/opportunities" } as never}
        tipo="oportunidad"
        nombre="Migración de planta"
        fila={{ id: "01a17edf-0000-0000-0000-000000000001", etapa: "negociacion" }}
        seguible={false}
        recorrido={{ campo: "etapa", pasos: PASOS, alElegir }}
      />
    </MemoryRouter>,
  );
}

describe("la ruta de etapas", () => {
  it("mueve al pulsar un paso que no es el actual", async () => {
    const movido: string[] = [];
    pintar((paso) => {
      movido.push(paso);
    });

    await userEvent.click(screen.getByRole("button", { name: "Ganada" }));
    expect(movido).toEqual(["ganada"]);
  });

  it("y el paso de ahora no es un botón", () => {
    pintar(() => {});
    // «Negociación» es donde está: se ve, y no se puede pulsar.
    expect(screen.getByText("Negociación")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Negociación" })).toBeNull();
  });

  it("y sin forma de mover, la ruta se pinta igual y no se pulsa", () => {
    // Hay objetos cuya etapa no se cambia desde aquí. La ruta sigue valiendo
    // para leer dónde está, que es para lo que nació.
    pintar(undefined);
    expect(screen.getByText("Ganada")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ganada" })).toBeNull();
  });
});
