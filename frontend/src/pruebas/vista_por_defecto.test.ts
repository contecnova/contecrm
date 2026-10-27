/**
 * Con qué vista se abre un listado.
 *
 * **Tarjetas, siempre que se pueda.** Una tabla enseña catorce columnas del
 * mismo tamaño y no destaca ninguna; una tarjeta lleva delante el nombre del
 * registro, y eso es lo que convierte una lista en algo que se ojea.
 *
 * Lo que se vigila aquí es lo que haría que ese «siempre» no se cumpliera sin
 * que se note: que la elección del usuario siga mandando sobre el valor por
 * defecto, y que la única excepción —un registro sin nada que poner de
 * titular— se decida mirando los datos y no una lista escrita a mano.
 */

import { beforeEach, describe, expect, it } from "vitest";

import { vistaPorDefecto, vistaRecordada } from "@/componentes/Vistas";

describe("con qué vista se abre un listado", () => {
  it("con tarjetas, que es lo que se ojea", () => {
    expect(vistaPorDefecto([{ nombre: "Ferrosa Montajes", tier: "oro" }])).toBe("tarjetas");
    // También con otros titulares: un caso lleva «asunto» y un artículo
    // «titulo», y los tres se leen igual de bien en una tarjeta.
    expect(vistaPorDefecto([{ asunto: "No funciona el acceso" }])).toBe("tarjetas");
    expect(vistaPorDefecto([{ codigo: "OPP-2026-00123" }])).toBe("tarjetas");
  });

  it("y con tabla solo si no hay nada que poner de titular", () => {
    // Un apunte de auditoría: en tarjeta sería una caja con un identificador
    // dentro, que se lee peor que una fila.
    const auditoria = [
      { id: "01a1", ocurrido_at: "2026-10-27T09:00:00Z", accion: "cuenta.creada" },
      { id: "01a2", ocurrido_at: "2026-10-27T09:01:00Z", accion: "cuenta.editada" },
    ];
    expect(vistaPorDefecto(auditoria)).toBe("tabla");
  });

  it("una fila sin nombre no convierte al resto en una tabla", () => {
    const contactos = [
      { nombre: "Ana", email: "ana@example.com" },
      { nombre: "", email: "sin.nombre@example.com" },
      { nombre: "Luis", email: "luis@example.com" },
    ];
    expect(vistaPorDefecto(contactos)).toBe("tarjetas");
  });

  it("una lista vacía se abre en tarjetas, no en tabla", () => {
    // Mientras no llegan los datos no hay nada que decidir, y abrir en tabla
    // haría que la pantalla saltara de una vista a otra al cargar.
    expect(vistaPorDefecto([])).toBe("tarjetas");
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
