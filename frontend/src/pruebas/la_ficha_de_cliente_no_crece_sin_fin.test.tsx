/**
 * La ficha de cliente: cajas que no se descuadran y listas que dicen la verdad.
 *
 * Un cliente con recorrido tiene cientos de cosas que enseñar, y la pantalla
 * crecía con ellas: la línea de tiempo estiraba el alto de la página, las otras
 * dos columnas se quedaban vacías debajo durante miles de píxeles, y la
 * cabecera —con quién se está— quedaba fuera de la vista.
 *
 * Lo que estas pruebas fijan, que es lo que se rompe al retocar la maqueta:
 *
 *   · las tres columnas acaban a la misma altura y **cada caja recorre lo
 *     suyo**. Dos intentos antes fallaron: una barra por columna —que no dice
 *     a qué tarjeta pertenece— y un número fijo de filas sin barras, que
 *     dejaba la caja del centro estirada y medio vacía;
 *   · un panel recortado dice `20+`, no `20`. «Este cliente tiene veinte
 *     casos» y «se enseñan veinte de los que tenga» no son lo mismo, y de la
 *     segunda lectura salen decisiones distintas;
 *   · **todos** los paneles ofrecen ir al listado entero. Si uno lo ofrece y
 *     el de al lado no, quien lo usa no sabe si es que no se puede o es que no
 *     hay más;
 *   · y el enlace lleva a la PESTAÑA, no sólo al módulo: los contactos viven
 *     dentro del módulo de cuentas.
 */

import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const CUENTA = {
  cuenta: {
    id: "c1",
    nombre: "Componentes Delta",
    sector: { codigo: "industria" },
    estado: "activa",
    roles: [],
    calidad: { puntuacion: 80, faltan: [] },
  },
  contactos: [{ id: "p1", nombre: "Ana Quintana", cargo: "Compras", email: "a@x.test" }],
  identificadores: [],
  metricas: { metricas: [], sin_dato: [] },
  // Exactamente el tope del servidor: es la señal de que puede haber más.
  timeline: Array.from({ length: 20 }, (_, i) => ({
    tipo: "llamada",
    asunto: `Hito ${i}`,
    momento: "2026-10-27T20:00:00Z",
  })),
};

const OPORTUNIDADES = Array.from({ length: 9 }, (_, i) => ({
  id: `o${i}`,
  nombre: `Oportunidad ${i}`,
  importe: 1000,
  moneda: "EUR",
  estado: "abierta",
  fecha_cierre: null,
}));

const CASOS = Array.from({ length: 20 }, (_, i) => ({
  id: `k${i}`,
  codigo: `CS-${i}`,
  asunto: `Caso ${i}`,
  estado: "nuevo",
  prioridad: "baja",
}));

/** Casos viene recortado —el servidor devuelve cursor—, oportunidades no. */
async function montar() {
  vi.resetModules();
  vi.doMock("@/lib/api", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/api");
    return {
      ...real,
      llamar: async (ruta: string) => {
        if (ruta.includes("/360")) return { datos: CUENTA };
        if (ruta.includes("/opportunities")) {
          return { datos: { items: OPORTUNIDADES, siguiente: null } };
        }
        if (ruta.includes("/casos")) {
          return { datos: { items: CASOS, siguiente: "cursor-de-la-siguiente" } };
        }
        return { datos: [] };
      },
    };
  });
  // La superficie decide qué acciones se ofrecen; aquí no se está probando
  // eso, y sin ella la pantalla no llega ni a pintar.
  vi.doMock("@/lib/permisos", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/permisos");
    return { ...real, useSuperficie: () => ({ superficie: null, tiene: () => true }) };
  });
  vi.doMock("react-router-dom", async () => {
    const real = await vi.importActual<Record<string, unknown>>("react-router-dom");
    return { ...real, useParams: () => ({ id: "c1" }) };
  });
  const { Cuenta } = await import("@/paginas/Cuenta");
  return render(
    <MemoryRouter>
      <Cuenta />
    </MemoryRouter>,
  );
}

function caja(titulo: string): HTMLElement {
  const rotulo = screen.getByText(titulo);
  const seccion = rotulo.closest("section");
  if (!seccion) throw new Error(`«${titulo}» no está dentro de una caja`);
  return seccion;
}

describe("la ficha de cliente", () => {
  it("cada caja recorre lo suyo, y ninguna columna se lleva la barra", async () => {
    await montar();
    await screen.findByText("Hito 0");

    // La lista de cada panel se recorre dentro de su tarjeta…
    for (const titulo of ["cuenta.oportunidades", "cuenta.casos"]) {
      const lista = caja(titulo).querySelector("ul");
      expect(lista!.className, `${titulo} no se recorre sola`).toMatch(/overflow-y-auto/);
    }
    expect(caja("cuenta.timeline").querySelector("ol")!.className).toMatch(/overflow-y-auto/);

    // …y ninguna columna se lleva una barra que recorra VARIAS tarjetas. La
    // de datos sí la puede llevar: son tres cajas cortas que no se recortan.
    const relacionados = caja("cuenta.casos").closest("aside")!;
    expect(relacionados.className, "la columna se lleva la barra").not.toMatch(
      /overflow-y-auto/,
    );
  });

  it("se enseña todo lo que ha llegado: lo que no cabe se alcanza con la barra", async () => {
    await montar();
    await screen.findByText("Hito 0");
    // Recortar en el cliente dejaría la caja medio vacía en una pantalla alta.
    expect(within(caja("cuenta.casos")).getAllByText(/^Caso \d+$/)).toHaveLength(20);
    expect(within(caja("cuenta.timeline")).getAllByText(/^Hito \d+$/)).toHaveLength(20);
  });

  it("una lista recortada dice que lo está, y una completa no", async () => {
    await montar();
    await screen.findByText("Hito 0");

    // Casos: 20 devueltos y cursor → hay más.
    expect(within(caja("cuenta.casos")).getByText("20+")).toBeInTheDocument();
    // Oportunidades: 9 y sin cursor → son nueve, y no lleva el «+».
    expect(within(caja("cuenta.oportunidades")).getByText("9")).toBeInTheDocument();
    expect(within(caja("cuenta.oportunidades")).queryByText("9+")).toBeNull();
  });

  it("todos los paneles llevan al listado entero, no sólo el recortado", async () => {
    await montar();
    await screen.findByText("Hito 0");

    for (const titulo of ["cuenta.contactos", "cuenta.oportunidades", "cuenta.casos"]) {
      const enlace = within(caja(titulo)).getByText("cuenta.verTodas");
      expect(enlace, `${titulo} no ofrece ver todas`).toBeInTheDocument();
      // Y filtrado por este cliente: llevar al listado entero sin filtrar
      // obliga a buscarlo otra vez.
      expect(enlace.getAttribute("href")).toContain("cuenta_id=c1");
    }

    // Los contactos viven DENTRO del módulo de cuentas, así que el enlace
    // tiene que decir también la pestaña.
    const contactos = within(caja("cuenta.contactos")).getByText("cuenta.verTodas");
    expect(contactos.getAttribute("href")).toMatch(/[?&]r=/);
  });

  it("la línea de tiempo dice que viene cortada y deja pedir el resto", async () => {
    await montar();
    await screen.findByText("Hito 0");
    const linea = caja("cuenta.timeline");
    expect(within(linea).getByText(/cuenta.timelineRecortada/)).toBeInTheDocument();
    expect(
      within(linea).getByRole("button", { name: "cuenta.verTodoLoQuePaso" }),
    ).toBeInTheDocument();
    // Y lo que aparezca al pulsarlo se anuncia: si no, quien no ve la pantalla
    // no se entera de que han salido hitos por encima del foco.
    expect(linea.querySelector('[role="status"]')).not.toBeNull();
  });
});
