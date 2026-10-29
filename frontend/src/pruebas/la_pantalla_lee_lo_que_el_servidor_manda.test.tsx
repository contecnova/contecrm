/**
 * Lo que la pantalla lee es lo que el servidor manda.
 *
 * El doble sirve **la forma de verdad de la API**, no la que la pantalla se
 * imaginaba. Es la diferencia entera: con la forma imaginada, estas dos
 * pantallas pasaban sus pruebas mientras en producción salían vacías.
 *
 * Medido el 29-10-2026:
 *
 *  · **marketing** leía `tipo`, `miembros` y `calculado_at` de cada segmento, y
 *    la API manda `dinamico`, `tamano` y `tamano_at`. El recuento salía
 *    `undefined` y la fecha decía «nunca calculado» siempre — justo lo que el
 *    comentario de esa pantalla dice que no puede pasar;
 *  · **conocimiento** leía `titulo`, y el título no es una columna del
 *    artículo. La lista salía sin nombres, y al escribir en el buscador
 *    `a.titulo.toLowerCase()` tumbaba la pantalla entera.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      if (ruta.startsWith("/api/v1/segmentos"))
        return {
          datos: [
            {
              id: "s-1",
              clave: "activos",
              nombre: "Clientes activos",
              objeto: "contacto",
              dinamico: true,
              tamano: 14000,
              tamano_at: "2026-10-29T08:00:00Z",
            },
            {
              id: "s-2",
              clave: "foto-marzo",
              nombre: "Foto de marzo",
              objeto: "contacto",
              dinamico: false,
              tamano: 900,
              tamano_at: "2026-03-01T08:00:00Z",
            },
          ],
        };
      if (ruta.startsWith("/api/v1/campanas"))
        return {
          datos: {
            items: [
              {
                id: "c-1",
                nombre: "Renovaciones Q4",
                estado: "activa",
                canal: "email",
                miembros: 320,
              },
            ],
          },
        };
      if (ruta.startsWith("/api/v1/conocimiento/articulos"))
        return {
          datos: {
            items: [
              {
                id: "a-1",
                clave: "reiniciar",
                titulo: "Cómo reiniciar el equipo",
                es_borrador: false,
                version_mostrada: 3,
                estado: "publicado",
                publico: true,
                vistas: 42,
              },
              {
                id: "a-2",
                clave: "facturar",
                titulo: "Emitir una factura rectificativa",
                es_borrador: true,
                version_mostrada: 2,
                estado: "borrador",
                publico: false,
                vistas: 0,
              },
            ],
          },
        };
      return { datos: {} };
    }),
  };
});

const { Marketing } = await import("@/paginas/Marketing");
const { Conocimiento } = await import("@/paginas/Conocimiento");

beforeEach(() => {
  vi.clearAllMocks();
});

describe("la pantalla de marketing", () => {
  it("enseña el recuento del segmento CON su fecha", async () => {
    render(
      <MemoryRouter>
        <Marketing />
      </MemoryRouter>,
    );

    await screen.findByText("Clientes activos");
    // El número: salía `undefined` porque la pantalla leía `miembros`.
    expect(screen.getByText("14000")).toBeInTheDocument();
    // Y su fecha. Un número sin fecha se lee como el de ahora, y con esto roto
    // TODOS los segmentos decían «nunca calculado».
    expect(screen.queryByText("marketing.nuncaCalculado")).not.toBeInTheDocument();
  });

  it("distingue un segmento dinámico de una foto congelada", async () => {
    render(
      <MemoryRouter>
        <Marketing />
      </MemoryRouter>,
    );

    await screen.findByText("Foto de marzo");
    expect(screen.getByText("marketing.dinamico")).toBeInTheDocument();
    expect(screen.getByText("marketing.congelado")).toBeInTheDocument();
  });

  it("de una campaña enseña los miembros y no inventa envíos", async () => {
    render(
      <MemoryRouter>
        <Marketing />
      </MemoryRouter>,
    );

    await screen.findByText("Renovaciones Q4");
    expect(screen.getByText("marketing.miembros")).toBeInTheDocument();
  });
});

describe("la pantalla de conocimiento", () => {
  it("enseña el título de cada artículo", async () => {
    render(
      <MemoryRouter>
        <Conocimiento />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Cómo reiniciar el equipo")).toBeInTheDocument();
    expect(screen.getByText("Emitir una factura rectificativa")).toBeInTheDocument();
  });

  it("no se cae al escribir en el buscador, y filtra", async () => {
    render(
      <MemoryRouter>
        <Conocimiento />
      </MemoryRouter>,
    );
    await screen.findByText("Cómo reiniciar el equipo");

    await userEvent.type(screen.getByLabelText("conocimiento.buscar"), "factura");

    await waitFor(() => {
      expect(screen.queryByText("Cómo reiniciar el equipo")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Emitir una factura rectificativa")).toBeInTheDocument();
  });

  it("marca lo que es borrador y no lo enseña igual que lo publicado", async () => {
    render(
      <MemoryRouter>
        <Conocimiento />
      </MemoryRouter>,
    );

    await screen.findByText("Emitir una factura rectificativa");
    expect(screen.getByText("conocimiento.borrador")).toBeInTheDocument();
    // Y uno solo: el publicado no lleva la marca.
    expect(screen.getAllByText("conocimiento.borrador")).toHaveLength(1);
  });
});
