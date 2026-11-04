/**
 * Dos columnas de la misma lista no pueden llamarse igual.
 *
 * **Medido el 03-11-2026** mirando la pantalla de Segmentos: la tabla salía
 * con `Clave · Nombre · Objeto · Tamaño · Tamaño`. Una enseñaba `0` y la otra
 * `03/11/2026, 23:18` — una fecha bajo un rótulo que dice «Tamaño»—.
 *
 * Son `tamano` y `tamano_at`, y el humanizador quita el `_at` porque en las
 * otras ciento y pico columnas eso es justo lo que se quiere: «Vence at» se
 * lee «Vence». El caso estaba **documentado y dado por aceptable** —«un caso
 * en 106 columnas declaradas»—, y de aceptable no tenía nada: dos columnas
 * con el mismo nombre obligan a leer los datos para saber cuál es cuál, que
 * es exactamente lo que una cabecera viene a evitar.
 *
 * Esto no vigila ese caso: vigila **todos**. La excepción se arregla donde se
 * arreglan las excepciones —`DE_SISTEMA`, con su nombre escrito—, y la
 * siguiente colisión sale aquí en vez de en una captura de pantalla.
 */

import { describe, expect, it } from "vitest";

import { humanizar } from "@/lib/formato";
import { MODULOS } from "@/lib/modulos";
import { recursosDe } from "@/lib/recursos";

describe("las columnas declaradas de cada lista", () => {
  it("no repiten rótulo dentro de la misma lista", () => {
    const choques: string[] = [];
    let miradas = 0;

    for (const modulo of MODULOS) {
      for (const recurso of recursosDe(modulo.ruta)) {
        const columnas = recurso.columnas ?? [];
        if (columnas.length < 2) continue;
        const porRotulo = new Map<string, string[]>();
        for (const campo of columnas) {
          miradas += 1;
          const rotulo = humanizar(campo);
          porRotulo.set(rotulo, [...(porRotulo.get(rotulo) ?? []), campo]);
        }
        for (const [rotulo, campos] of porRotulo) {
          if (campos.length > 1) {
            choques.push(
              `${modulo.ruta} · ${recurso.nombre}: «${rotulo}» para ${campos.join(" y ")}`,
            );
          }
        }
      }
    }

    // Cuántas ha mirado: un recorrido que no encuentra columnas diría que no
    // hay choques sin haber comparado nada. Son más de cien declaradas.
    expect(miradas).toBeGreaterThan(100);
    expect(
      choques,
      "columnas de la misma lista con el mismo rótulo:\n  " + choques.join("\n  "),
    ).toEqual([]);
  });

  it("y el humanizador sigue quitando el «_at» donde no choca", () => {
    // La regla general no se toca: lo que se arregla es la excepción. Si esto
    // dejara de cumplirse, el arreglo habría sido dejar «Vence at» en las
    // ciento y pico columnas que están bien.
    expect(humanizar("vence_at")).toBe("Vence");
    expect(humanizar("inicio_at")).toBe("Inicio");
    // Y la excepción, con su nombre propio.
    expect(humanizar("tamano_at")).toBe("Calculado");
    expect(humanizar("tamano")).toBe("Tamaño");
  });
});
