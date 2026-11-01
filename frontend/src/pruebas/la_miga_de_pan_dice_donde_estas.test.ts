/**
 * La miga de pan dice dónde estás, y para eso tiene que caber.
 *
 * Medido el 01-11-2026 a 1440×900, en la ficha de una cuenta: la barra
 * superior enseñaba «In… > Cuentas y… > C…». Los tres tramos recortados, y el
 * último —el único que distingue esta pantalla de otra— reducido a **una
 * letra**.
 *
 * No era un problema de proporciones: la barra está llena de verdad. Lo único
 * «libre» que hay a 1440 son 92 px, y son los huecos entre controles. Así que
 * la miga no gana sitio ajustando pesos; lo gana quitando lo que no dice nada.
 *
 * Dos cosas, las dos medidas:
 *
 * - **«Inicio» fuera de la ficha.** Está en todas las migas, no distingue
 *   ninguna pantalla de otra y al logo de la esquina se llega igual.
 * - **El buscador tenía `flex-basis: 0`**, así que no encogía nunca y todo el
 *   recorte caía sobre la miga. Con una base real lo reparten: a 1440 la miga
 *   se lee entera, y a 1024 se queda con 113 px en vez de con 0.
 *
 * Lo segundo es de maqueta y se comprueba en el navegador. Lo primero es de
 * producto y se comprueba aquí.
 */

import { describe, expect, it } from "vitest";

import { derivarMigas } from "@/componentes/BarraSuperior";

/** El doble de i18n: devuelve la clave, que es lo que hace el de las pruebas. */
const t = (clave: string) => clave;

const rotulos = (camino: string) => derivarMigas(camino, t).map((m) => m.rotulo);

describe("cuántos tramos y cuáles", () => {
  it("en la portada, uno y sin enlace: ya estás ahí", () => {
    expect(derivarMigas("/", t)).toEqual([{ rotulo: "nav.inicio" }]);
  });

  it("en un listado, «Inicio» y el módulo", () => {
    // Dos tramos caben de sobra, y desde el listado volver a la portada es un
    // salto que alguien hace.
    const migas = derivarMigas("/m/cuentas", t);
    expect(migas.map((m) => m.rotulo)).toEqual(["nav.inicio", "Cuentas y contactos"]);
    expect(migas[1]?.a).toBe("/m/cuentas");
  });

  it("en una ficha, el módulo y el registro — sin «Inicio»", () => {
    // Lo que se recortaba. Tres tramos no caben a 1440, y el que sobra es el
    // que está en todas las pantallas.
    expect(rotulos("/m/cuentas/cuenta/01a18224-4ae5-7c36-b7d5-2d9ab390e2c0")).toEqual([
      "Cuentas y contactos",
      "Cuenta",
    ]);
  });

  it("y desde la ficha se vuelve al listado, que es el paso anterior de verdad", () => {
    const migas = derivarMigas("/m/cuentas/cuenta/01a18224", t);
    expect(migas[0]?.a).toBe("/m/cuentas");
    // El último no lleva enlace: es donde estás.
    expect(migas[migas.length - 1]?.a).toBeUndefined();
  });
});

describe("lo que NO se enseña", () => {
  it("el identificador del registro, que no le dice nada a nadie", () => {
    const camino = "/m/cuentas/cuenta/01a18224-4ae5-7c36-b7d5-2d9ab390e2c0";
    expect(rotulos(camino).join(" ")).not.toContain("01a18224");
  });

  it("y el tipo sale escrito como se lee, no como viene en la ruta", () => {
    expect(rotulos("/m/postventa/orden_de_trabajo/1")).toContain("Orden de trabajo");
  });
});
