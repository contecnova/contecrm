/**
 * El buscador de la barra no va encajado.
 *
 * Lo dijo quien lo usa el 04-11-2026: «"Buscar una pantalla o un módulo"
 * debería tener un par de puntos más de margen arriba y un punto más abajo,
 * queda muy encajado».
 *
 * Medido antes de tocar nada, a 1440 px: la barra mide 48 px y el buscador 40,
 * empezando en el píxel 4. Cuatro píxeles de aire arriba y cuatro abajo, para
 * la caja más grande de la barra. Con 52 son seis y seis.
 *
 * Esto fija la relación, no el número: lo que no puede volver a pasar es que
 * la barra crezca o el buscador engorde hasta dejarlo pegado otra vez. Y el
 * tope por arriba también cuenta: esta barra está fija en todas las pantallas
 * y cada píxel suyo es un píxel menos de listado.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(process.cwd(), "src", "index.css"), "utf-8");

function pixeles(variable: string): number {
  const m = new RegExp(`--${variable}:\\s*(\\d+)px`).exec(css);
  if (!m) throw new Error(`no se declara --${variable}`);
  return Number(m[1]);
}

describe("la barra de arriba", () => {
  it("deja aire alrededor del buscador", () => {
    const barra = pixeles("barra-h");
    // El buscador es un control de 40 px de alto (`h-10` de la escala).
    const buscador = 40;
    const aire = (barra - buscador) / 2;
    expect(aire, "el buscador va encajado en la barra").toBeGreaterThanOrEqual(6);
  });

  it("y no se come la pantalla", () => {
    // El otro lado: «que respire» se cumpliría con una barra de 80 px, y eso
    // son dos filas de listado menos en todas las pantallas, siempre.
    expect(pixeles("barra-h")).toBeLessThanOrEqual(56);
  });
});
