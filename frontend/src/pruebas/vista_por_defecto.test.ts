/**
 * Con qué vista se abre un listado: **con la tabla**.
 *
 * Estuvo al revés hasta el 01-11-2026, y el argumento de entonces era bueno:
 * una tabla de catorce columnas del mismo tamaño no destaca ninguna, y una
 * tarjeta lleva delante el nombre del registro. Lo que ese argumento no miró
 * es **cuánto se ve**: medido en la bandeja de casos a 1440×900, en tarjetas
 * caben nueve registros antes de desplazarse y en tabla más de veinte. Quien
 * abre una lista de 104 casos no viene a ojear nueve. Y una tarjeta no se
 * puede ordenar: «¿cuál es el más antiguo?» obliga a leerlas una a una.
 *
 * Las tarjetas no se quitan —siguen en el selector y se recuerdan por
 * pestaña—, así que lo que se vigila aquí sigue siendo lo mismo: que **la
 * elección de quien mira mande sobre el valor por defecto**. Es la parte que
 * podría dejar de cumplirse sin que nadie lo note.
 */

import { beforeEach, describe, expect, it } from "vitest";

import { vistaPorDefecto, vistaRecordada } from "@/componentes/Vistas";

describe("con qué vista se abre un listado", () => {
  it("con la tabla, y sin mirar las filas para decidirlo", () => {
    // Cuentas, casos, oportunidades y apuntes de auditoría: todos igual.
    // Antes dependía de si el registro tenía con qué titularse, y eso hacía
    // que dos listas del mismo producto no se parecieran en nada.
    //
    // Ya ni recibe las filas: un parámetro que no se usa invita a creer que
    // la decisión aún depende de ellas, y lo que hay que poder afirmar es que
    // **no cambia sola cuando llegan los datos**. Una pantalla que salta de
    // una forma a otra mientras la miras hace dudar de lo que enseña.
    expect(vistaPorDefecto()).toBe("tabla");
    expect(vistaPorDefecto.length).toBe(0);
  });
});

describe("lo que el usuario eligió", () => {
  beforeEach(() => localStorage.clear());

  it("no se sabe distinguir de «no ha dicho nada» si no se devuelve nulo", () => {
    expect(vistaRecordada("cuentas.Cuentas")).toBeNull();
    localStorage.setItem("contecrm.vista", JSON.stringify({ "cuentas.Cuentas": "tabla" }));
    // Quien eligió tabla la quiere: devolver «tabla» también cuando nadie ha
    // elegido hacía imposible cambiar el valor por defecto sin pisarle la
    // elección a quien sí eligió.
    expect(vistaRecordada("cuentas.Cuentas")).toBe("tabla");
  });

  it("un valor que no existe no se cree", () => {
    localStorage.setItem("contecrm.vista", JSON.stringify({ "x.Y": "mosaico" }));
    expect(vistaRecordada("x.Y")).toBeNull();
  });

  it("y un almacenamiento roto no rompe la pantalla", () => {
    localStorage.setItem("contecrm.vista", "{no es json");
    expect(vistaRecordada("x.Y")).toBeNull();
  });
});
