/**
 * Una lista que el servidor corta lo dice, y se puede seguir con el cursor.
 *
 * El tablero pedía `?limite=200` y pintaba lo que llegaba como si fuera todo.
 * Aquí se prueba la pieza común (`useListaPaginada` + `<AvisoDeRecorte>`): el
 * aviso sale sólo cuando el servidor devuelve cursor, «cargar más» pide con
 * ESE cursor y acumula, y el fallo de la segunda página no borra la primera.
 *
 * Validada plantando el caso malo: sustituyendo en vez de acumular en
 * `cargarMas`, la segunda prueba falla.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AvisoDeRecorte } from "@/componentes/Estados";
import { useListaPaginada } from "@/lib/paginado";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, o?: Record<string, unknown>) =>
      o ? `${clave} ${JSON.stringify(o)}` : clave,
  }),
}));

const llamar = vi.fn();
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  llamar: (...a: unknown[]) => llamar(...a),
}));

function Lista() {
  const lista = useListaPaginada<{ id: string }>("/api/v1/cosas?limite=2");
  if (lista.fallo) return <p>fallo</p>;
  if (!lista.filas) return <p>cargando</p>;
  return (
    <div>
      <ul>
        {lista.filas.map((f) => (
          <li key={f.id}>{f.id}</li>
        ))}
      </ul>
      {lista.falloAlCargarMas ? <p>fallo al cargar más</p> : null}
      {lista.hayMas ? (
        <AvisoDeRecorte
          cuantas={lista.filas.length}
          alCargarMas={lista.cargarMas}
          cargando={lista.cargandoMas}
        />
      ) : null}
    </div>
  );
}

function pagina(ids: string[], siguiente: string | null) {
  return {
    datos: { items: ids.map((id) => ({ id })), siguiente, hay_mas: siguiente !== null },
  };
}

describe("una lista por páginas", () => {
  beforeEach(() => llamar.mockReset());

  it("sin cursor, no avisa de nada", async () => {
    llamar.mockResolvedValueOnce(pagina(["a", "b"], null));
    render(<Lista />);
    expect(await screen.findByText("b")).toBeTruthy();
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("con cursor, avisa y «cargar más» pide con él y acumula", async () => {
    llamar
      .mockResolvedValueOnce(pagina(["a", "b"], "C1"))
      .mockResolvedValueOnce(pagina(["c"], null));
    render(<Lista />);

    const aviso = await screen.findByRole("note");
    expect(aviso.textContent).toContain('listas.recortada {"count":2}');

    await userEvent.click(screen.getByRole("button", { name: "listas.cargarMas" }));

    expect(await screen.findByText("c")).toBeTruthy();
    // Las de antes siguen: se acumula, no se salta de página.
    expect(screen.getByText("a")).toBeTruthy();
    expect(llamar.mock.calls[1]?.[0]).toBe("/api/v1/cosas?limite=2&cursor=C1");
    // Y sin más cursor, el aviso se va.
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("si falla la segunda página, la primera se queda", async () => {
    llamar
      .mockResolvedValueOnce(pagina(["a", "b"], "C1"))
      .mockRejectedValueOnce(new Error("caído"));
    render(<Lista />);
    await screen.findByRole("note");

    await userEvent.click(screen.getByRole("button", { name: "listas.cargarMas" }));

    expect(await screen.findByText("fallo al cargar más")).toBeTruthy();
    expect(screen.getByText("a")).toBeTruthy();
    // Se puede volver a intentar: el cursor sigue ahí.
    expect(screen.getByRole("button", { name: "listas.cargarMas" })).toBeTruthy();
  });
});
