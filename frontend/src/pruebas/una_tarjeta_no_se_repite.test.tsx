/**
 * Una tarjeta no enseña dos veces el mismo dato.
 *
 * Visto en `/m/casos`: la tarjeta se titulaba «Discrepancia en el albarán —
 * Componentes Delta» y justo debajo ponía «Asunto: Discrepancia en el albarán
 * — Componentes Del…». El mismo texto dos veces, la segunda recortado, y
 * gastando una de las cinco líneas útiles de la tarjeta.
 *
 * La causa era un nombre de campo escrito a mano: las dos llamadas a
 * `camposDeTarjeta` le pasaban la cadena `"nombre"`, así que sólo se excluía
 * ese campo. Un caso no tiene `nombre` —se titula por `asunto`—, y lo mismo
 * `titulo`, `razon_social`, `clave`, `codigo`, `email`, `slug` y
 * `nombre_completo`: ocho de los nueve campos con los que se titula algo.
 *
 * Validado plantando el caso malo: volviendo `campoDelNombre` a devolver
 * siempre `"nombre"`, las dos primeras pruebas fallan.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Tarjetas } from "@/componentes/Vistas";
import { campoDelNombre, nombreDelRegistro } from "@/lib/formato";

const CASOS = [
  {
    id: "1",
    asunto: "Discrepancia en el albarán",
    estado: "en_curso",
    codigo: "CS-00124",
  },
  {
    id: "2",
    asunto: "Vibración anómala en la prensa",
    estado: "nuevo",
    codigo: "CS-01447",
  },
];

describe("una tarjeta no se repite", () => {
  it("el campo del que sale el título no se pinta otra vez", () => {
    render(<Tarjetas filas={CASOS} />);
    // El título, una vez por tarjeta y no dos.
    expect(screen.getAllByText("Discrepancia en el albarán")).toHaveLength(1);
    expect(screen.getAllByText("Vibración anómala en la prensa")).toHaveLength(
      1,
    );
    // Y su etiqueta no aparece: no hay ninguna fila «Asunto».
    expect(screen.queryByText("Asunto")).toBeNull();
  });

  it("dice de qué campo salió el nombre, no sólo cuál es", () => {
    // Los nueve campos de la lista, cada uno comprobado: una lista de los que
    // SÍ se queda corta al primero nuevo, así que se recorre entera.
    const casos: [Record<string, unknown>, string][] = [
      [{ nombre: "Ferrosa" }, "nombre"],
      [{ nombre_completo: "Ana Ruiz" }, "nombre_completo"],
      [{ asunto: "No arranca" }, "asunto"],
      [{ titulo: "Guía rápida" }, "titulo"],
      [{ razon_social: "Ferrosa S.L." }, "razon_social"],
      [{ clave: "2026-Q1" }, "clave"],
      [{ codigo: "OPP-00123" }, "codigo"],
      [{ email: "ana@ejemplo.test" }, "email"],
      [{ slug: "guia-rapida" }, "slug"],
    ];
    expect(casos).toHaveLength(9);
    for (const [fila, esperado] of casos) {
      expect(campoDelNombre(fila)).toBe(esperado);
      expect(nombreDelRegistro(fila)).toBe(String(Object.values(fila)[0]));
    }
    // Sin ninguno de los nueve, no hay campo del que titular.
    expect(campoDelNombre({ cantidad: 3 })).toBe("");
    expect(nombreDelRegistro({ cantidad: 3 })).toBe("");
  });

  it("una lista mezclada excluye el titular de cada fila", () => {
    // Unos contactos traen el nombre y otros sólo el correo: hay que quitar
    // los dos campos, no el del primero.
    const mezcla = [
      { id: "1", nombre_completo: "Ana Ruiz", telefono: "600" },
      { id: "2", email: "luis@ejemplo.test", telefono: "601" },
    ];
    render(<Tarjetas filas={mezcla} />);
    expect(screen.getAllByText("Ana Ruiz")).toHaveLength(1);
    expect(screen.getAllByText("luis@ejemplo.test")).toHaveLength(1);
    expect(screen.queryByText("Nombre completo")).toBeNull();
    expect(screen.queryByText("Email")).toBeNull();
    // Y lo que no es titular sí se enseña.
    expect(screen.getAllByText("Telefono").length).toBeGreaterThan(0);
  });
});
