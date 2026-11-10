/**
 * Lo que la pantalla ofrece lo decide el servidor, no lo que tenga cargado.
 *
 * Tres fricciones medidas el 10-11-2026 con las tareas del día:
 *
 * - **Elegir un cliente** filtraba las doscientas primeras filas: con más
 *   clientes, el que se buscaba no salía. Ahora lo escrito se busca en el
 *   servidor (`?buscar=`), y si el listado no sabe buscar se filtra lo cargado.
 * - **La prioridad del caso** era una caja de texto. Es una lista que decide la
 *   empresa (un vocabulario), y el formulario la pide a ese vocabulario.
 * - **El desplegable de estado** ofrecía «Enviado» en el presupuesto y el
 *   servidor lo rechazaba: no ofrece lo que tiene su propia acción.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CambioDeEstado } from "@/componentes/CambioDeEstado";
import { Formulario } from "@/componentes/Formulario";
import { Tabla } from "@/componentes/Tabla";
import { ErrorApi, llamar } from "@/lib/api";
import type { CampoEsquema } from "@/lib/contrato";

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...real, llamar: vi.fn() };
});

const PRIMERAS = {
  items: [
    { id: "c1", nombre: "Componentes Miño" },
    { id: "c2", nombre: "Forjas Alcañiz" },
  ],
};

function campo(p: Partial<CampoEsquema>): CampoEsquema {
  return {
    nombre: "x",
    tipo: "texto",
    obligatorio: true,
    titulo: "X",
    descripcion: "",
    opciones: [],
    maximo: null,
    formato: "",
    subcampos: [],
    referencia: "",
    ...p,
  } as CampoEsquema;
}

function montar(campos: CampoEsquema[], alEnviar = vi.fn()) {
  render(
    <MemoryRouter>
      <Formulario campos={campos} textoEnviar="Crear" alEnviar={alEnviar} />
    </MemoryRouter>,
  );
  return alEnviar;
}

const CUENTA = campo({
  nombre: "cuenta_id",
  titulo: "Cuenta",
  referencia: "cuenta",
});

async function buscar(texto: string) {
  fireEvent.click(await screen.findByRole("combobox"));
  const buscador = await screen.findByRole("textbox", {
    name: /buscarEnLista|Buscar/,
  });
  fireEvent.change(buscador, { target: { value: texto } });
  return buscador;
}

beforeEach(() => vi.mocked(llamar).mockReset());

/** Lo que contesta la API según la ruta pedida. */
function contestar(fn: (ruta: string) => Promise<unknown>) {
  vi.mocked(llamar).mockImplementation(((...a: unknown[]) =>
    fn(String(a[0]))) as never);
}

describe("elegir un registro", () => {
  it("encuentra en el servidor lo que no estaba entre las primeras filas", async () => {
    contestar(
      async (ruta: string) =>
        ({
          datos: ruta.includes("buscar=zuera")
            ? { items: [{ id: "c9", nombre: "Talleres Zuera" }] }
            : PRIMERAS,
        }) as never,
    );
    const alEnviar = montar([CUENTA]);
    await buscar("zuera");

    expect(
      await screen.findByRole("option", { name: "Talleres Zuera" }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("option", { name: "Talleres Zuera" }));
    // Elegido de la búsqueda, el campo sabe cómo se llama aunque no esté en
    // las primeras filas.
    expect(screen.getByRole("combobox").textContent).toContain(
      "Talleres Zuera",
    );
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));
    await waitFor(() =>
      expect(alEnviar).toHaveBeenCalledWith(
        expect.objectContaining({ cuenta_id: "c9" }),
      ),
    );
  });

  it("si el listado no sabe buscar, filtra lo cargado", async () => {
    contestar(async (ruta: string) => {
      if (ruta.includes("buscar="))
        throw new ErrorApi(422, "listado.sin_busqueda", "No", null);
      return { datos: PRIMERAS } as never;
    });
    montar([CUENTA]);
    await buscar("forj");
    await waitFor(() =>
      expect(
        vi
          .mocked(llamar)
          .mock.calls.some(([r]) => String(r).includes("buscar=")),
      ).toBe(true),
    );
    expect(
      await screen.findByRole("option", { name: "Forjas Alcañiz" }),
    ).toBeTruthy();
    expect(screen.getAllByRole("option")).toHaveLength(1);
  });
});

describe("una lista que decide la empresa", () => {
  it("ofrece los valores activos del vocabulario, en su orden y con su rótulo", async () => {
    contestar(async (ruta: string) => {
      if (ruta !== "/api/v1/service/vocabularios/prueba_prioridades")
        return { datos: [] };
      return {
        datos: [
          { valor: "urgente", etiqueta: "Urgente", orden: 50, activo: true },
          { valor: "baja", etiqueta: "Baja", orden: 10, activo: true },
          { valor: "retirada", etiqueta: "Retirada", orden: 20, activo: false },
        ],
      } as never;
    });
    montar([
      campo({
        nombre: "prioridad",
        titulo: "Prioridad",
        tipo: "lista",
        vocabulario: "service/prueba_prioridades",
      }),
    ]);
    const lista = await screen.findByLabelText("Prioridad");
    await waitFor(() =>
      expect(
        [...(lista as HTMLSelectElement).options].map((o) => o.text),
      ).toEqual(["—", "Baja", "Urgente"]),
    );
  });
});

describe("el desplegable de estado", () => {
  it("no ofrece lo que se hace con su acción", async () => {
    contestar(
      async (ruta: string) =>
        ({
          datos: ruta.endsWith("/estados")
            ? { items: [{ objeto: "presupuesto" }] }
            : {
                estados: [
                  {
                    clave: "borrador",
                    nombre: "Borrador",
                    color: "",
                    activo: true,
                  },
                  {
                    clave: "enviado",
                    nombre: "Enviado",
                    color: "",
                    activo: true,
                  },
                  {
                    clave: "en_pausa",
                    nombre: "En pausa",
                    color: "",
                    activo: true,
                  },
                ],
                transiciones: { borrador: ["enviado", "en_pausa"] },
                exigen_motivo: [],
                con_su_camino: { enviado: "se manda con «Enviar»" },
              },
        }) as never,
    );
    render(
      <CambioDeEstado
        servicio="sales"
        objeto="presupuesto"
        ruta="/api/v1/presupuestos/p1"
        estado="borrador"
        alCambiar={vi.fn()}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Borrador/ }));
    const destinos = screen.getAllByRole("option").map((o) => o.textContent);
    expect(destinos).toEqual(["En pausa"]);
  });
});

describe("el buscador de una lista", () => {
  const filas = [
    { id: "1", nombre: "Talleres Zuera" },
    { id: "2", nombre: "Forjas Alcañiz" },
  ];

  it("con el servidor buscando, no vuelve a filtrar lo que le llega", () => {
    const alCambiar = vi.fn();
    render(
      <MemoryRouter>
        <Tabla
          filas={filas}
          ocupaLaPantalla
          busqueda={{ valor: "zuera", alCambiar, enServidor: true }}
        />
      </MemoryRouter>,
    );
    // Las dos: el servidor ya decidió cuáles casan (busca también en campos
    // que la tabla no enseña), y filtrar encima escondería las que no lo dicen
    // en una columna visible.
    expect(screen.getByText("Forjas Alcañiz")).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "zuera t" },
    });
    expect(alCambiar).toHaveBeenCalledWith("zuera t");
  });

  it("si el listado no sabe buscar, busca en lo cargado", () => {
    render(
      <MemoryRouter>
        <Tabla
          filas={filas}
          ocupaLaPantalla
          busqueda={{ valor: "zuera", alCambiar: vi.fn(), enServidor: false }}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByText("Forjas Alcañiz")).toBeNull();
    expect(screen.getByText("Talleres Zuera")).toBeTruthy();
  });
});
