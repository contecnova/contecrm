/**
 * Lo que no se deshace no se pulsa de paso.
 *
 * Medido en el navegador sobre ocho fichas —cuentas, oportunidades, casos,
 * conocimiento, servicio de campo, proveedores, segmentos y campañas—: en las
 * **ocho** «Eliminar» era el segundo botón de la barra, en rojo, delante de
 * cualquier acción útil. Y la de una cuenta apilaba siete botones del mismo
 * peso en dos filas, cinco de más de dieciocho caracteres y el más largo de
 * cuarenta y uno:
 *
 *     [Editar] [Eliminar] [Añadir una dirección]
 *     [Colgar la cuenta de otra en una jerarquía] [Fusionar esta cuenta con otra]
 *     [Relacionar esta cuenta con otra] [Sumar a alguien al equipo de la cuenta]
 *
 * Siete cosas igual de destacadas no destacan ninguna, y la más fácil de
 * pulsar sin querer era la única que no se puede retirar.
 *
 * Ahora la barra es `[Editar] [Más ▾]`, y dentro del menú lo destructivo va al
 * final y separado por una raya. Medido después en el navegador: seis opciones
 * en el menú, «Fusionar esta cuenta con otra» y «Eliminar» las dos últimas, y
 * el contenido de la ficha empieza cien píxeles más arriba.
 *
 * Validada plantando el caso malo: devolviendo el `btn-danger` a la barra,
 * falla; y quitando la marca `destructiva`, falla el orden.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BotonesDeRegistro } from "@/componentes/Edicion";
import {
  MenuDeAcciones,
  type OpcionDeMenu,
} from "@/componentes/MenuDeAcciones";

const EXTRA: OpcionDeMenu[] = [
  { clave: "a", nombre: "Añadir una dirección", alElegir: () => {} },
  {
    clave: "b",
    nombre: "Fusionar esta cuenta con otra",
    alElegir: () => {},
    destructiva: true,
  },
  {
    clave: "c",
    nombre: "Sumar a alguien al equipo de la cuenta",
    alElegir: () => {},
  },
];

function barra(extra = EXTRA, alBorrar = () => {}) {
  return render(
    <BotonesDeRegistro
      puedeEditar
      puedeBorrar
      alEditar={() => {}}
      alBorrar={alBorrar}
      extra={extra}
    />,
  );
}

describe("lo que no se deshace no está a mano", () => {
  it("la barra sólo lleva editar y el menú: nada destructivo fuera", () => {
    barra();
    const fuera = screen.getAllByRole("button");
    expect(fuera).toHaveLength(2); // editar y el disparador del menú
    for (const b of fuera) {
      expect(b.className).not.toContain("btn-danger");
      expect(b.textContent).not.toMatch(/elimin|borrar|fusionar/i);
    }
  });

  it("dentro del menú, lo destructivo va al final", () => {
    barra();
    fireEvent.click(
      screen.getByRole("button", { name: /acciones\.mas|acciones\.titulo/ }),
    );
    const items = within(screen.getByRole("menu")).getAllByRole("menuitem");
    const nombres = items.map((i) => i.textContent);
    // Las cuatro no destructivas primero, las dos que no se deshacen al final.
    expect(nombres).toEqual([
      "Añadir una dirección",
      "Sumar a alguien al equipo de la cuenta",
      "Fusionar esta cuenta con otra",
      "ficha.eliminar",
    ]);
    // Y en rojo, que es lo que las distingue de un vistazo.
    expect(items[2]!.className).toContain("text-danger");
    expect(items[3]!.className).toContain("text-danger");
    expect(items[0]!.className).not.toContain("text-danger");
  });

  it("borrar sigue estando: se mueve, no se quita", () => {
    const alBorrar = vi.fn();
    barra(EXTRA, alBorrar);
    fireEvent.click(
      screen.getByRole("button", { name: /acciones\.mas|acciones\.titulo/ }),
    );
    fireEvent.click(screen.getByRole("menuitem", { name: "ficha.eliminar" }));
    expect(alBorrar).toHaveBeenCalledOnce();
  });

  it("Escape cierra el menú y devuelve el foco al botón", () => {
    render(
      <MenuDeAcciones opciones={EXTRA}>
        <button type="button">Editar</button>
      </MenuDeAcciones>,
    );
    const disparador = screen.getByRole("button", { name: "acciones.mas" });
    fireEvent.click(disparador);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(disparador);
  });

  it("sin nada que ofrecer no se pinta un menú vacío", () => {
    render(
      <BotonesDeRegistro
        puedeEditar
        puedeBorrar={false}
        alEditar={() => {}}
        alBorrar={() => {}}
      />,
    );
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "acciones.mas" })).toBeNull();
  });

  it("la acción destacada del recurso sale a la vista y no se repite en el menú", () => {
    // Convertir un lead, cerrar un caso, enviar una oferta: quedaban entre
    // «Archivar» y «Borrar», a dos clics (tareas T02, T05 y T10, 10-11-2026).
    const alConvertir = vi.fn();
    render(
      <BotonesDeRegistro
        puedeEditar
        puedeBorrar={false}
        alEditar={() => {}}
        alBorrar={() => {}}
        destacadas={["convertir"]}
        extra={[
          {
            clave: "/api/v1/leads/l-1/archivar",
            nombre: "Archivar leads",
            alElegir: () => {},
          },
          {
            clave: "/api/v1/leads/l-1/convertir",
            nombre: "Convertir el lead en cuenta, contacto y oportunidad",
            alElegir: alConvertir,
          },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Convertir/ }));
    expect(alConvertir).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: "acciones.titulo" }));
    const menu = screen.getByRole("menu");
    expect(within(menu).queryByText(/Convertir el lead/)).toBeNull();
    expect(within(menu).getByText("Archivar leads")).toBeInTheDocument();
  });
});
