/**
 * Cada pantalla declara qué capacidades del catálogo enseña
 * (CRM-07.04.05.05, CRM-07.04.05.02).
 *
 * La declaración vive en `modulos.ts` y se escribe en un minuto. Lo único que
 * hace caro declarar algo que no se enseña es que **se pinta en la pantalla**,
 * así que lo que se mide aquí es justo eso: que se pinte, y que no se pinte a
 * medias.
 */

import { describe, expect, it } from "vitest";

import { MODULOS } from "@/lib/modulos";

describe("la declaración de capacidades", () => {
  it("no repite un identificador dentro de un módulo", () => {
    for (const m of MODULOS) {
      const lista = m.capacidades ?? [];
      expect(new Set(lista).size, `${m.ruta} repite capacidades`).toBe(lista.length);
    }
  });

  it("no declara como capacidad de producto la de front de la propia pantalla", () => {
    // `capacidad` dice qué capacidad de FRONT es esta pantalla; `capacidades`
    // dice qué de producto se ve en ella. Mezclarlas haría que el informe
    // contara la pantalla como si enseñara su propia existencia.
    for (const m of MODULOS) {
      expect(m.capacidades ?? [], m.ruta).not.toContain(m.capacidad);
    }
  });

  it("usa identificadores con la forma del catálogo", () => {
    const forma = /^CRM-\d\d\.\d\d\.\d\d\.\d\d$/;
    for (const m of MODULOS) {
      for (const c of m.capacidades ?? []) {
        expect(forma.test(c), `${m.ruta}: «${c}»`).toBe(true);
      }
    }
  });

  it("una capacidad no se declara en dos módulos a la vez", () => {
    // Dos pantallas que dicen enseñar lo mismo son dos sitios donde mirar, y el
    // informe de cobertura contaría una capacidad como cubierta por partida
    // doble. Si de verdad se ve en las dos, la que manda es una y la otra
    // enlaza.
    const donde = new Map<string, string[]>();
    for (const m of MODULOS) {
      for (const c of m.capacidades ?? []) {
        donde.set(c, [...(donde.get(c) ?? []), m.ruta]);
      }
    }
    const repetidas = [...donde.entries()].filter(([, rutas]) => rutas.length > 1);
    expect(repetidas, JSON.stringify(repetidas)).toHaveLength(0);
  });

  it("la mayoría de los módulos ya declara lo que enseña", () => {
    // El tope del lado del servidor cuenta las que faltan; aquí lo que importa
    // es que el mecanismo esté puesto y no sea un campo que nadie rellena.
    const conDeclaracion = MODULOS.filter((m) => (m.capacidades?.length ?? 0) > 0);
    expect(conDeclaracion.length).toBeGreaterThanOrEqual(20);
  });
});
