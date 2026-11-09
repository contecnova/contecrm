/**
 * Un rechazo con `detalle.problemas` enseña cada motivo a la vista: el de una
 * combinación de productos que no se vende junta decía «no se puede» sin decir
 * cuáles (09-11-2026).
 */
import { describe, expect, it } from "vitest";

import { problemasDe } from "@/componentes/Estados";

describe("los problemas del rechazo", () => {
  it("dice qué choca con qué y por qué", () => {
    expect(
      problemasDe({
        problemas: [
          {
            tipo: "incompatible",
            producto: "SEN-01",
            otro: "SEN-02",
            motivo: "Mismo bus.",
          },
          "Texto suelto",
        ],
      }),
    ).toEqual(["SEN-01 · SEN-02: Mismo bus.", "Texto suelto"]);
  });

  it("sin problemas no pinta nada", () => {
    expect(problemasDe(null)).toEqual([]);
    expect(problemasDe({ otra: 1 })).toEqual([]);
  });
});
