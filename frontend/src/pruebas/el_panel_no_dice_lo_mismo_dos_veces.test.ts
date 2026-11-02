/**
 * El panel de cabecera no enseña el mismo valor dos veces.
 *
 * El panel tiene dos sitios para marcar lo que un registro ES: las
 * **insignias** pegadas al nombre y la fila de **datos clave** de debajo. Las
 * insignias las escribe cada pantalla; los datos clave salen solos de las
 * `columnas` preferidas que el recurso declara en `recursos.ts`. Nadie cruzaba
 * las dos listas, así que el mismo valor salía arriba y abajo.
 *
 * **Medido el 02-11-2026**, en las tres fichas de a medida:
 *
 * - Cuenta: «activa» tres veces —insignia, dato clave y la tarjeta «Datos»—.
 * - Caso: «CS-00124», «en_curso» y «baja», las tres duplicadas.
 * - Oportunidad: «abierta» como chip y como «Estado abierta».
 *
 * No es sólo ruido: ver el mismo campo dos veces hace dudar de si son el mismo
 * campo, y en un CRM «estado» y «estado» pueden ser dos cosas distintas.
 *
 * Esta prueba lee el CÓDIGO y no la pantalla a propósito: lo que se vigila es
 * que nadie vuelva a escribir una insignia de un campo que ya es columna
 * preferida, y eso se ve antes de montar nada.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { RECURSOS_POR_MODULO } from "@/lib/recursos";

/** Las pantallas que pintan el panel con insignias escritas a mano. */
const PANTALLAS = ["Cuenta.tsx", "Caso.tsx", "Oportunidad.tsx", "Ficha.tsx"];

/** Lo que hay entre `distintivos={` y su llave de cierre. */
function bloqueDeDistintivos(fuente: string): string | null {
  const desde = fuente.indexOf("distintivos={");
  if (desde < 0) return null;
  let nivel = 0;
  for (let i = desde + "distintivos=".length; i < fuente.length; i += 1) {
    if (fuente[i] === "{") nivel += 1;
    else if (fuente[i] === "}") {
      nivel -= 1;
      if (nivel === 0) return fuente.slice(desde, i + 1);
    }
  }
  return null;
}

/** El `tipo="…"` que esa misma llamada le pasa al panel. */
function tipoDelPanel(fuente: string): string {
  return /<DatosClave[\s\S]{0,400}?tipo="([a-z_]+)"/.exec(fuente)?.[1] ?? "";
}

function columnasDe(objeto: string): string[] {
  // Por el `objeto` declarado y NO con `recursoDe`: ése cae en la primera
  // pestaña del módulo cuando no encuentra el objeto, así que devolvía las
  // columnas de otro recurso y la prueba miraba la lista equivocada.
  for (const recursos of Object.values(RECURSOS_POR_MODULO)) {
    const recurso = recursos.find((r) => r.objeto === objeto);
    if (recurso) return recurso.columnas ?? [];
  }
  return [];
}

describe("el panel de cabecera", () => {
  // Que el recorrido mire de verdad: si ninguna pantalla trae insignias, la
  // prueba pasaría sin haber comprobado nada.
  const revisadas: string[] = [];

  it.each(PANTALLAS)(
    "%s no repite en las insignias un dato clave",
    (archivo) => {
      const fuente = readFileSync(
        join(process.cwd(), "src", "paginas", archivo),
        "utf-8",
      );
      const bloque = bloqueDeDistintivos(fuente);
      if (bloque === null) return; // Esa pantalla no escribe insignias.
      const objeto = tipoDelPanel(fuente);
      expect(objeto, `${archivo}: no se ve el tipo del panel`).not.toBe("");
      const columnas = columnasDe(objeto);
      expect(
        columnas.length,
        `${archivo}: el recurso de «${objeto}» no declara columnas`,
      ).toBeGreaterThan(0);
      revisadas.push(archivo);

      const repetidos = columnas.filter((c) =>
        new RegExp(`\\.${c}\\b`).test(bloque),
      );
      expect(
        repetidos,
        `${archivo}: ${repetidos.join(", ")} sale como insignia y como dato clave`,
      ).toEqual([]);
    },
  );

  it("ha mirado alguna pantalla con insignias", () => {
    expect(revisadas.length).toBeGreaterThan(0);
  });
});
