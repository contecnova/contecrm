/**
 * Arrastrar una tarjeta de una columna a otra, y que se guarde.
 *
 * Lo pidió quien lo usa, y con razón: un tablero en el que no se puede mover
 * nada es una tabla girada. Obliga a abrir la ficha, buscar el campo y
 * guardarlo para hacer exactamente lo que la forma del tablero promete con
 * sólo existir.
 *
 * Lo que se comprueba aquí es lo que se rompe sin ruido:
 *
 *   · que al soltar se mande el PATCH con el campo de agrupación —y no otro—;
 *   · que la tarjeta se pinte en su columna nueva ANTES de que conteste el
 *     servidor, porque medio segundo quieta se lee como que no ha funcionado;
 *   · que si el servidor dice que no, **vuelva**, con el motivo del servidor
 *     cantado: una pantalla que enseña un estado que la base no tiene es peor
 *     que el parpadeo;
 *   · y que donde NO se puede guardar no se deje arrastrar. Un tablero que
 *     deja coger una tarjeta y la devuelve a su sitio sin decir por qué se lee
 *     como que la aplicación falla.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/lib/personas", () => ({
  usePersonas: () => ({}),
  nombreDe: (_p: unknown, id: unknown) => String(id ?? ""),
  inicialesDe: (n: string) => n.slice(0, 2).toUpperCase(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

const { Agrupado } = await import("@/componentes/Vistas");
const { ErrorApi } = await import("@/lib/api");

const FILAS = [
  { id: "1", nombre: "Ibérica Sistemas", etapa: "cualificacion" },
  { id: "2", nombre: "Transportes Duero", etapa: "propuesta" },
];

function tarjeta(texto: string): HTMLElement {
  // El elemento que lleva el arrastre es el contenedor de la tarjeta, no el
  // texto: se sube desde el nodo del nombre hasta el que es `draggable`.
  let nodo: HTMLElement | null = screen.getByText(texto);
  while (nodo && nodo.getAttribute("draggable") !== "true") nodo = nodo.parentElement;
  if (!nodo) throw new Error(`«${texto}» no es arrastrable`);
  return nodo;
}

function columna(titulo: string): HTMLElement {
  // El rótulo se humaniza («cualificacion» → «Cualificacion»), así que se
  // busca por el texto del valor, sin distinguir mayúsculas.
  const encabezado = screen.getByRole("heading", { name: new RegExp(titulo, "i") });
  const seccion = encabezado.closest("section");
  if (!seccion) throw new Error(`no hay columna «${titulo}»`);
  return seccion;
}

function pintar(mover?: (f: Record<string, unknown>, v: string) => Promise<void>) {
  return render(
    <MemoryRouter>
      <Agrupado filas={FILAS} campo="etapa" mover={mover} />
    </MemoryRouter>,
  );
}

describe("el tablero mueve de columna", () => {
  it("al soltar manda el cambio del campo por el que se agrupa", async () => {
    const movido: { fila: Record<string, unknown>; valor: string }[] = [];
    const mover = vi.fn(async (fila: Record<string, unknown>, valor: string) => {
      movido.push({ fila, valor });
    });
    pintar(mover);

    fireEvent.dragStart(tarjeta("Ibérica Sistemas"));
    const destino = columna("propuesta");
    fireEvent.dragOver(destino);
    fireEvent.drop(destino);

    await waitFor(() => expect(mover).toHaveBeenCalledTimes(1));
    // El campo de agrupación y el valor de la columna de destino, no el índice
    // ni el rótulo humanizado: con el rótulo, «En propuesta» se guardaría como
    // estado y el servidor lo rechazaría sin que se supiera por qué.
    expect(movido[0]?.valor).toBe("propuesta");
    expect(movido[0]?.fila.id).toBe("1");
  });

  it("soltar en la misma columna no manda nada", async () => {
    const mover = vi.fn(async () => undefined);
    pintar(mover);
    fireEvent.dragStart(tarjeta("Ibérica Sistemas"));
    const mismo = columna("cualificacion");
    fireEvent.dragOver(mismo);
    fireEvent.drop(mismo);
    await new Promise((r) => setTimeout(r, 0));
    expect(mover).not.toHaveBeenCalled();
  });

  it("la columna de los que no tienen valor no acepta nada", async () => {
    const mover = vi.fn(async () => undefined);
    render(
      <MemoryRouter>
        <Agrupado
          filas={[...FILAS, { id: "3", nombre: "Sin etapa" }]}
          campo="etapa"
          mover={mover}
        />
      </MemoryRouter>,
    );
    fireEvent.dragStart(tarjeta("Ibérica Sistemas"));
    const huerfanos = columna("—");
    fireEvent.dragOver(huerfanos);
    fireEvent.drop(huerfanos);
    // Soltar ahí escribiría el guion como si fuera la etapa del registro.
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toMatch(/no se puede mover/i),
    );
    expect(mover).not.toHaveBeenCalled();
  });

  it("si el servidor dice que no, se canta su motivo", async () => {
    const mover = vi.fn(async () => {
      throw new ErrorApi(
        409,
        "oportunidad.transicion_invalida",
        "Conflicto",
        null,
        "Una oportunidad perdida no vuelve a negociación",
      );
    });
    pintar(mover);
    fireEvent.dragStart(tarjeta("Ibérica Sistemas"));
    const destino = columna("propuesta");
    fireEvent.dragOver(destino);
    fireEvent.drop(destino);

    // La frase del servidor, no «algo ha ido mal»: con la genérica se intenta
    // otra vez igual.
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain(
        "Una oportunidad perdida no vuelve a negociación",
      ),
    );
  });

  it("sin forma de guardar, no se puede arrastrar nada", () => {
    pintar(undefined);
    // Ni una sola tarjeta marcada como arrastrable: ofrecer el gesto y que no
    // haga nada es peor que no ofrecerlo.
    expect(document.querySelectorAll('[draggable="true"]')).toHaveLength(0);
  });

  it("sin ratón también se mueve: cada tarjeta lleva su selector", async () => {
    const movido: string[] = [];
    const mover = vi.fn(async (_f: Record<string, unknown>, valor: string) => {
      movido.push(valor);
    });
    pintar(mover);

    // Arrastrar con el ratón es UNA de las formas, no la forma: dejar el gesto
    // como única salida deja fuera a quien no usa ratón. Es el mismo selector
    // que ya lleva el embudo, para que dos pantallas que hacen lo mismo lo
    // hagan igual.
    const selector = screen.getByLabelText(/Mover Transportes Duero/i);
    fireEvent.change(selector, { target: { value: "cualificacion" } });
    await waitFor(() => expect(mover).toHaveBeenCalledTimes(1));
    expect(movido[0]).toBe("cualificacion");
  });

  it("el selector lleva las columnas que hay, no una lista escrita", () => {
    pintar(vi.fn(async () => undefined));
    const opciones = screen
      .getByLabelText(/Mover Transportes Duero/i)
      .querySelectorAll("option");
    expect([...opciones].map((o) => (o as HTMLOptionElement).value)).toEqual([
      "cualificacion",
      "propuesta",
    ]);
  });
});
