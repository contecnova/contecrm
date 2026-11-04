/**
 * Una acción de colección que pide datos abre su formulario, no desaparece.
 *
 * La pantalla de un módulo deducía sus botones del contrato, igual que la
 * ficha, pero con una regla de más: descartaba toda acción que pidiera cuerpo,
 * «porque un botón que siempre da 422 es peor que no tener botón». El motivo
 * es bueno y la conclusión no: lo que pide datos no sobra, pide formulario —y
 * el formulario ya existía, en la ficha, sacado del `requestBody` del OpenAPI.
 *
 * **Medido el 04-11-2026** sobre los trece contratos: de las 98 acciones de
 * colección que caen en una pantalla de módulo se ofrecían **14**. De las 84
 * descartadas, 71 rutas distintas, y **50 no aparecían en ningún fichero del
 * front**: no se alcanzaban por ninguna vía. «A qué proveedor iría este
 * encargo», «Comprobar un contenido antes de mandarlo», «Dónde duele si un
 * proveedor falla mañana». Pantallas de módulo sin un solo botón, que es como
 * se encontró recorriendo el producto.
 *
 * Lo que fija esta prueba:
 *   · la que pide cuerpo SE OFRECE, y la que pide parámetros de URL no —de esa
 *     el formulario no se puede sacar, y volvería el 422—;
 *   · al pulsarla se abre el formulario con los campos que declara el contrato
 *     y lo que se escribe viaja en el cuerpo;
 *   · la que no pide nada sigue costando UN clic, que es lo que costaba antes.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { accionesDeColeccion } from "@/lib/acciones";
import type { Superficie } from "@/lib/superficie";

const enviadas: Array<{ ruta: string; cuerpo: unknown }> = [];

vi.mock("@/lib/api", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...real,
    llamar: vi.fn(async (ruta: string, opciones?: { cuerpo?: unknown }) => {
      enviadas.push({ ruta, cuerpo: opciones?.cuerpo });
      return { datos: { hecho: true }, version: null, retenidos: [], enmascarados: [] };
    }),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

// El contrato del servicio, con la forma que tiene de verdad: `requestBody`
// con su esquema. Los campos los saca `camposDe` de verdad, sin doble.
vi.mock("@/lib/contrato", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/contrato")>();
  return {
    ...real,
    contratoDe: vi.fn(async () => ({
      paths: {
        "/api/v1/proveedores-servicio/simular": {
          post: {
            requestBody: {
              required: true,
              content: {
                "application/json": {
                  schema: {
                    type: "object",
                    required: ["encargo"],
                    properties: {
                      encargo: { type: "string", title: "Encargo" },
                    },
                  },
                },
              },
            },
          },
        },
        "/api/v1/proveedores-servicio/recalcular": { post: {} },
        // Cuerpo abierto a propósito: lo que lleva un encargo lo pone el
        // sector, no este contrato.
        "/api/v1/proveedores-servicio/abierta": {
          post: {
            requestBody: {
              required: true,
              content: {
                "application/json": {
                  schema: { type: "object", title: "Datos" },
                },
              },
            },
          },
        },
      },
    })),
  };
});

const SUPERFICIE = {
  operaciones: [
    {
      metodo: "POST",
      ruta: "/api/v1/proveedores-servicio/simular",
      resumen: "A qué proveedor iría este encargo",
      permiso: null,
      exige_cuerpo: true,
      exige_datos: false,
    },
    {
      metodo: "POST",
      ruta: "/api/v1/proveedores-servicio/recalcular",
      resumen: "Recalcular ahora",
      permiso: null,
      exige_cuerpo: false,
      exige_datos: false,
    },
    {
      metodo: "POST",
      ruta: "/api/v1/proveedores-servicio/abierta",
      resumen: "Simular con datos libres",
      permiso: null,
      exige_cuerpo: true,
      exige_datos: false,
    },
    {
      metodo: "POST",
      ruta: "/api/v1/proveedores-servicio/informe",
      resumen: "Informe con parámetros en la URL",
      permiso: null,
      exige_cuerpo: false,
      exige_datos: true,
    },
  ],
  objetos: {},
} as unknown as Superficie;

const todas = () => true;

describe("las acciones de una colección", () => {
  beforeEach(() => {
    enviadas.length = 0;
  });

  it("incluyen la que pide cuerpo y dejan fuera la que pide parámetros de URL", () => {
    const acciones = accionesDeColeccion(SUPERFICIE, "/api/v1/proveedores-servicio", todas);
    const rutas = acciones.map((a) => a.ruta);

    // Las dos que se pueden resolver: una con formulario y otra sin él.
    expect(rutas).toContain("/api/v1/proveedores-servicio/simular");
    expect(rutas).toContain("/api/v1/proveedores-servicio/recalcular");
    // Y la que no: sus datos van en la URL, el formulario sale del cuerpo, y
    // ofrecerla sería el 422 de siempre.
    expect(rutas).not.toContain("/api/v1/proveedores-servicio/informe");
    expect(acciones).toHaveLength(3);
  });

  it("al pulsar la que pide datos se abre su formulario y lo escrito viaja en el cuerpo", async () => {
    const { Acciones } = await import("@/componentes/Acciones");
    const acciones = accionesDeColeccion(SUPERFICIE, "/api/v1/proveedores-servicio", todas);
    render(
      <Acciones
        acciones={acciones}
        servicio="service"
        alTerminar={() => {}}
      />,
    );

    await userEvent.click(
      await screen.findByRole("button", { name: "A qué proveedor iría este encargo" }),
    );

    // El campo que declara el contrato, no uno inventado.
    const campo = await screen.findByLabelText(/Encargo/);
    await userEvent.type(campo, "ENC-7");
    // El de ENVIAR, dentro del formulario. El botón que lo abrió lleva el
    // mismo rótulo —es el nombre de la acción— y buscar «cualquier botón que
    // se llame así» acabaría pulsando el de arriba otra vez.
    const formulario = campo.closest("form");
    expect(formulario).not.toBeNull();
    await userEvent.click(
      within(formulario as HTMLFormElement).getByRole("button", {
        name: /iría este encargo/,
      }),
    );

    await waitFor(() => expect(enviadas).toHaveLength(1));
    expect(enviadas[0]).toEqual({
      ruta: "/api/v1/proveedores-servicio/simular",
      cuerpo: { encargo: "ENC-7" },
    });
  });

  it("la de cuerpo abierto pide ese cuerpo, y lo manda tal cual", async () => {
    // Su esquema no declara ni una propiedad —es un objeto abierto a
    // propósito—, y eso salía como «cero campos»: el botón mandaba `{}`, o sea
    // «a qué proveedor iría este encargo» sin encargo. Ahora se pide, y lo
    // escrito viaja como el cuerpo entero, no metido dentro de una llave.
    const { Acciones } = await import("@/componentes/Acciones");
    const acciones = accionesDeColeccion(SUPERFICIE, "/api/v1/proveedores-servicio", todas);
    render(<Acciones acciones={acciones} servicio="service" alTerminar={() => {}} />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Simular con datos libres" }),
    );
    // Lo pinta como pares clave/valor, que para un cuerpo abierto es mejor que
    // un cuadro de JSON: nadie tiene que acertar con las comillas.
    const clave = (await screen.findAllByLabelText(/formulario\.claveDe.*Datos/))[0];
    await userEvent.type(clave, "peso_kg");
    // Al escribir la primera clave aparece la fila vacía siguiente, así que
    // hay dos casillas de valor: la de este par es la primera.
    const valores = await screen.findAllByLabelText(/formulario\.valorDe.*Datos/);
    await userEvent.type(valores[0], "14");
    const formulario = clave.closest("form");
    await userEvent.click(
      within(formulario as HTMLFormElement).getByRole("button", {
        name: /Simular con datos libres/,
      }),
    );

    await waitFor(() => expect(enviadas).toHaveLength(1));
    expect(enviadas[0]).toEqual({
      ruta: "/api/v1/proveedores-servicio/abierta",
      cuerpo: { peso_kg: "14" },
    });
  });

  it("la que no pide nada se hace con un solo clic", async () => {
    const { Acciones } = await import("@/componentes/Acciones");
    const acciones = accionesDeColeccion(SUPERFICIE, "/api/v1/proveedores-servicio", todas);
    render(
      <Acciones acciones={acciones} servicio="service" alTerminar={() => {}} />,
    );

    const boton = await screen.findByRole("button", { name: "Recalcular ahora" });
    // Se espera a que los campos estén medidos: antes de eso el botón abre,
    // que es el comportamiento seguro.
    await waitFor(async () => {
      await userEvent.click(boton);
      expect(enviadas).toHaveLength(1);
    });
    expect(enviadas[0]).toEqual({
      ruta: "/api/v1/proveedores-servicio/recalcular",
      cuerpo: {},
    });
  });
});
