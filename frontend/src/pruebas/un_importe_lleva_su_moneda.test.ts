/**
 * Un importe se escribe con la moneda del registro, y sin ella no se inventa.
 *
 * **Medido el 02-11-2026** en la ficha de una oportunidad: el panel de
 * cabecera decía «Importe 117.693» y la tarjeta de tres centímetros más abajo
 * «117.693 €». El mismo dato, en la misma pantalla, con dos formatos. El
 * panel usaba el formateador genérico, que no sabe de monedas; la tarjeta
 * usaba el de dinero, al que la pantalla le pasaba `op.moneda`.
 *
 * Ahora `escalar` acepta la moneda del registro. Lo que NO hace es ponerle una
 * por defecto: una cifra con el símbolo equivocado —pesos escritos como
 * euros— es peor que una cifra sin símbolo, y la moneda no se adivina del
 * idioma. Un tenant mexicano con precios en dólares existe.
 */

import { describe, expect, it } from "vitest";

import { escalar, trozos } from "@/lib/formato";

describe("un importe", () => {
  it("lleva la moneda del registro cuando la hay", () => {
    const escrito = escalar("117693", "importe", "EUR");
    expect(escrito).toContain("€");
    // Y sigue siendo la misma cifra, con los separadores de la localización.
    expect(escrito.replace(/\D/g, "")).toBe("117693");
  });

  it("respeta una moneda que no es la de casa", () => {
    expect(escalar("1000", "importe", "USD")).toMatch(/\$|USD/);
  });

  it("sin moneda sale la cifra, no un símbolo inventado", () => {
    const escrito = escalar("117693", "importe");
    expect(escrito).not.toContain("€");
    expect(escrito.replace(/\D/g, "")).toBe("117693");
  });

  it("sin dato sale una raya, nunca la palabra «null»", () => {
    // `String(null)` da «null», y eso llegaba a la pantalla por los valores
    // compuestos: la pestaña «Detalles» de un caso enseñaba «Motivo: null»,
    // «Padre: null», «Contacto ID: null». Quien lo lee no sabe si es un hueco
    // o un valor que alguien escribió a mano.
    expect(escalar(null, "motivo")).toBe("—");
    expect(escalar(undefined, "motivo")).toBe("—");
  });

  it("un valor compuesto tampoco escribe «null» dentro", () => {
    // El caso real: el cierre de un caso llega como objeto con sus huecos.
    const piezas = trozos({ motivo: null, reaperturas: 2 }, "cierre");
    expect(piezas.map((p) => p.texto).join(" · ")).not.toContain("null");
  });

  it("un número que no es dinero no se vuelve dinero por llevar moneda", () => {
    // `probabilidad` no es un importe. Si la moneda se aplicara a todo, un
    // 25 % saldría como «25 €».
    expect(escalar(25, "probabilidad", "EUR")).not.toContain("€");
  });
});
