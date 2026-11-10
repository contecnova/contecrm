/**
 * Cómo se ve un formulario, que es de lo que más se usa en un CRM.
 *
 * El contenido estaba bien —se genera del contrato, las referencias se buscan
 * en vez de teclearse, las listas se escriben una a una—, y aun así era
 * desagradable de rellenar. Mirándolo renderizado, cuatro cosas concretas:
 *
 *   · **una sola columna a ochocientos píxeles de ancho**: un email ocupaba lo
 *     mismo que una descripción y un alta de treinta campos se iba al doble de
 *     largo;
 *   · campos con **más alto y más radio que un botón**, así que parecían
 *     pulsables;
 *   · **la ayuda debajo del campo**, cuando sirve para decidir qué poner, no
 *     para comprobarlo después;
 *   · y un **asterisco rojo en cada obligatorio** dentro del grupo donde todos
 *     lo son, que no distingue nada y sólo mete ruido.
 *
 * Lo que se vigila aquí es la estructura, no el aspecto: que el rótulo, la
 * ayuda y el campo salgan en ese orden, y que lo que necesita el ancho entero
 * lo ocupe.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Formulario } from "@/componentes/Formulario";
import type { CampoEsquema } from "@/lib/contrato";

function campo(p: Partial<CampoEsquema>): CampoEsquema {
  return {
    nombre: "x",
    tipo: "texto",
    obligatorio: false,
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

function montar(campos: CampoEsquema[]) {
  return render(
    <MemoryRouter>
      <Formulario campos={campos} textoEnviar="Crear" alEnviar={vi.fn()} />
    </MemoryRouter>,
  );
}

describe("el formulario", () => {
  it("se reparte en dos columnas cuando hay sitio", () => {
    const { container } = montar([
      campo({ nombre: "a", titulo: "A", obligatorio: true }),
      campo({ nombre: "b", titulo: "B", obligatorio: true }),
    ]);
    // La rejilla la pone la hoja de estilos; aquí se comprueba que el
    // formulario la pide. Una sola columna es puro recorrido visual.
    expect(container.querySelector(".rejilla-formulario")).not.toBeNull();
  });

  it("lo que necesita el ancho entero lo ocupa", () => {
    // Un texto largo o una lista de líneas en media columna se convierten en
    // una caja estrecha con scroll, que es peor que no partir el formulario.
    const { container } = montar([
      campo({ nombre: "corto", titulo: "Corto", obligatorio: true }),
      campo({
        nombre: "notas",
        titulo: "Notas",
        tipo: "texto_largo",
        obligatorio: true,
      }),
    ]);
    const anchos = container.querySelectorAll(".campo-ancho");
    expect(anchos).toHaveLength(1);
    expect(anchos[0]!.textContent).toContain("Notas");
  });

  it("la ayuda va ANTES del campo, no después", () => {
    // Debajo llega cuando ya se ha escrito: «el nombre comercial con el que
    // factura» sirve para decidir qué poner.
    const { container } = montar([
      campo({
        nombre: "nombre",
        titulo: "Nombre",
        obligatorio: true,
        descripcion: "El nombre comercial con el que factura.",
      }),
    ]);
    const celda = container.querySelector(".rejilla-formulario > div")!;
    const orden = [...celda.children].map((e) => e.tagName.toLowerCase());
    expect(orden.slice(0, 3)).toEqual(["label", "p", "input"]);
  });

  it("no hay asteriscos en el grupo de obligatorios", () => {
    // Los obligatorios van en su propio grupo y los opcionales en otro: marcar
    // cada uno con un asterisco rojo no distingue nada, porque en el primer
    // grupo lo llevan todos.
    const { container } = montar([
      campo({ nombre: "a", titulo: "A", obligatorio: true }),
      campo({ nombre: "b", titulo: "B", obligatorio: true }),
    ]);
    expect(container.textContent).not.toContain("*");
  });

  it("lo opcional sigue separado y plegado", () => {
    // Es lo que hace que un alta generada de un contrato con cuarenta campos
    // se pueda rellenar: lo imprescindible delante.
    montar([
      campo({ nombre: "a", titulo: "A", obligatorio: true }),
      campo({ nombre: "web", titulo: "Web" }),
    ]);
    expect(screen.getByLabelText("A")).toBeInTheDocument();
    expect(screen.queryByLabelText("Web")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { expanded: false })).toBeInTheDocument();
  });

  it("el campo sigue atado a su rótulo y a su ayuda", () => {
    // Lo visual no puede llevarse por delante lo accesible: sin `for` y sin
    // `aria-describedby`, quien usa un lector de pantalla oye una caja suelta.
    montar([
      campo({
        nombre: "email",
        titulo: "Email",
        obligatorio: true,
        descripcion: "El de trabajo.",
      }),
    ]);
    const caja = screen.getByLabelText("Email");
    expect(caja).toBeInTheDocument();
    const descrito = caja.getAttribute("aria-describedby");
    expect(descrito).toBeTruthy();
    expect(document.getElementById(descrito!)?.textContent).toContain(
      "El de trabajo.",
    );
  });
});

describe("un formulario sin campos obligatorios", () => {
  it("enseña los campos delante, no un recuadro vacío", () => {
    // **Medido el 03-11-2026** pulsando «Editar» en una oportunidad: el
    // `PATCH` del contrato declara TODOS los campos opcionales —se manda lo
    // que se cambia—, así que la lista de delante salía vacía y la ficha
    // enseñaba un recuadro con «Más campos (29)», «Guardar cambios» y **ni un
    // solo campo que tocar**.
    const campos = [
      { nombre: "nombre", tipo: "string", obligatorio: false },
      { nombre: "importe", tipo: "number", obligatorio: false },
      { nombre: "notas", tipo: "string", obligatorio: false },
    ] as unknown as Parameters<typeof Formulario>[0]["campos"];

    const { container } = render(
      <Formulario
        campos={campos}
        recurso={
          {
            nombre: "Oportunidades",
            listar: "/x",
            servicio: "sales",
            columnas: ["nombre", "importe"],
          } as never
        }
        textoEnviar="Guardar"
        alEnviar={() => undefined}
      />,
    );

    // Delante, las columnas preferidas que el recurso ya declara.
    const delante = container.querySelectorAll(".rejilla-formulario")[0];
    expect(delante?.querySelectorAll("input, select, textarea").length).toBe(2);
    // Y el resto, detrás, dicho con su número.
    expect(screen.getByText(/formulario\.masCampos/)).toBeInTheDocument();
  });

  it("y si el recurso no declara columnas, los enseña todos", () => {
    // Un formulario que no enseña nada no es un formulario: antes que
    // esconderlo todo, se enseña todo.
    const campos = [
      { nombre: "a", tipo: "string", obligatorio: false },
      { nombre: "b", tipo: "string", obligatorio: false },
    ] as unknown as Parameters<typeof Formulario>[0]["campos"];

    const { container } = render(
      <Formulario
        campos={campos}
        textoEnviar="Guardar"
        alEnviar={() => undefined}
      />,
    );
    const delante = container.querySelectorAll(".rejilla-formulario")[0];
    expect(delante?.querySelectorAll("input, select, textarea").length).toBe(2);
    expect(screen.queryByText(/formulario\.masCampos/)).toBeNull();
  });

  it("en un alta, con los obligatorios van las preferidas y lo que ya viene relleno", () => {
    // Medido el 10-11-2026 (tarea T03): el alta de una oportunidad era
    // «Nombre» y nada más, con el importe y la fecha detrás de «Más campos»;
    // y el cliente que traía el enlace quedaba puesto pero escondido.
    const campos = [
      { nombre: "nombre", tipo: "string", obligatorio: true },
      { nombre: "importe", tipo: "number", obligatorio: false },
      { nombre: "cuenta_id", tipo: "string", obligatorio: false },
      { nombre: "notas", tipo: "string", obligatorio: false },
    ] as unknown as Parameters<typeof Formulario>[0]["campos"];

    const { container } = render(
      <Formulario
        campos={campos}
        recurso={
          {
            nombre: "Oportunidades",
            listar: "/x",
            servicio: "sales",
            columnas: ["nombre", "importe"],
          } as never
        }
        delante={["cuenta_id"]}
        valores={{ cuenta_id: "c-1" }}
        textoEnviar="Guardar"
        alEnviar={() => undefined}
      />,
    );

    const delante = container.querySelectorAll(".rejilla-formulario")[0];
    // nombre (obligatorio), importe (preferida) y cuenta_id (viene relleno).
    expect(
      delante?.querySelectorAll(
        "input:not([type=hidden]), select, textarea, [role=combobox]",
      ).length,
    ).toBe(3);
    expect(screen.getByText(/formulario\.masCampos/)).toBeInTheDocument();
  });

  it("lo que el recurso pide delante en el alta va delante, aunque no sea columna", () => {
    // Medido el 10-11-2026 (tarea T02): los apellidos y el correo de un lead
    // iban detrás de «Más campos», y había que abrirlo en cada alta.
    const campos = [
      { nombre: "nombre", tipo: "string", obligatorio: false },
      { nombre: "apellidos", tipo: "string", obligatorio: false },
      { nombre: "email", tipo: "string", obligatorio: false },
      { nombre: "web", tipo: "string", obligatorio: false },
    ] as unknown as Parameters<typeof Formulario>[0]["campos"];

    const { container } = render(
      <Formulario
        campos={campos}
        recurso={
          {
            nombre: "Candidatos",
            listar: "/x",
            servicio: "sales",
            columnas: ["nombre"],
            alta: ["apellidos", "email"],
          } as never
        }
        textoEnviar="Guardar"
        alEnviar={() => undefined}
      />,
    );
    const delante = container.querySelectorAll(".rejilla-formulario")[0];
    expect(
      [...(delante?.querySelectorAll("input") ?? [])].map((e) => e.id),
    ).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/apellidos/),
        expect.stringMatching(/email/),
      ]),
    );
    expect(delante?.querySelectorAll("input").length).toBe(3);
  });
});
