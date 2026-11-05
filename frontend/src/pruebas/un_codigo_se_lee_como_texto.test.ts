/**
 * Un código de opción se lee como texto, también dentro de una lista.
 *
 * La ficha de una lección enseñaba «competidor,decisor_en_contra» como dato
 * clave: la lista pegada por `String()` y los códigos en crudo.
 */
import { describe, expect, it } from "vitest";

import { escalar, nombreDelRegistro, rotuloDeOpcion } from "@/lib/formato";

describe("escalar", () => {
  it("separa las listas y escribe los códigos como texto, todos igual", () => {
    expect(escalar(["competidor", "decisor_en_contra"])).toBe(
      "Competidor, Decisor en contra",
    );
    expect(escalar([])).toBe("—");
  });

  it("un código suelto se lee; una palabra suelta no se toca", () => {
    expect(escalar("descuento_tardio")).toBe("Descuento tardío");
    // Puede ser un nombre o un identificador corto: no se le cambia nada.
    expect(escalar("acme")).toBe("acme");
  });

  it("las siglas se quedan como vienen", () => {
    expect(rotuloDeOpcion("B2B")).toBe("B2B");
    expect(rotuloDeOpcion("EUR")).toBe("EUR");
  });
});

describe("el nombre de un registro", () => {
  it("es el completo cuando lo hay: el de pila no distingue a dos Silvias", () => {
    expect(
      nombreDelRegistro({
        nombre: "Silvia",
        nombre_completo: "Silvia Mas Roig",
      }),
    ).toBe("Silvia Mas Roig");
  });
});
