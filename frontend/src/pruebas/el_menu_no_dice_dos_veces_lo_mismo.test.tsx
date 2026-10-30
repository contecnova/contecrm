/**
 * En un área no puede haber dos entradas con el mismo rótulo.
 *
 * Lo metí yo: añadí a Ventas una entrada `nav.prospeccion` titulada
 * «Prospección» sin ver que el módulo de leads del catálogo ya se titulaba
 * «Prospección» y caía en el mismo área. El menú quedó con la palabra dos
 * veces, a doscientos píxeles una de otra, y la única forma de saber cuál es
 * cuál era entrar en las dos.
 *
 * Pasa porque el menú se arma de **dos fuentes** —el catálogo de módulos y las
 * entradas transversales de `navegacion.ts`— que no se miran entre sí. Nadie
 * que añada una entrada va a recordar repasar los 24 títulos del catálogo.
 *
 * Validado plantando el caso malo: con `nav.prospeccion` de vuelta en
 * «Prospección», esta prueba falla y nombra el área y las dos rutas.
 */

import { describe, expect, it } from "vitest";

import es from "@/i18n/es";
import { porGrupoVisible } from "@/lib/modulos";
import { menuDe } from "@/lib/navegacion";
import type { Sesion } from "@/lib/sesion";

const TODO = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "quien@ejemplo.test",
  permisos: ["*"],
  es_admin_plataforma: true,
} as unknown as Sesion;

/**
 * El rótulo que acaba leyendo la persona, y si hubo que traducirlo.
 *
 * Los módulos entran con su título literal y las transversales con su clave de
 * traducción; se comparan después de resolver, porque lo que choca en pantalla
 * son las palabras, no las claves.
 *
 * Devuelve también `traducido` porque la primera versión de esta prueba
 * caminaba `es.translation`, que no existe —`es.ts` exporta el objeto pelado—,
 * así que toda clave volvía sin resolver y dos entradas no podían chocar
 * jamás. Pasó en verde con el caso malo plantado. Ahora la prueba cuenta
 * cuántas resolvió y se cae si esa cuenta baja.
 */
function rotulo(clave: string): { texto: string; traducido: boolean } {
  const partes = clave.split(".");
  let nodo: unknown = es;
  for (const p of partes) {
    if (typeof nodo !== "object" || nodo === null)
      return { texto: clave, traducido: false };
    nodo = (nodo as Record<string, unknown>)[p];
  }
  return typeof nodo === "string"
    ? { texto: nodo, traducido: true }
    : { texto: clave, traducido: false };
}

describe("el menú no dice dos veces lo mismo", () => {
  it("ningún área repite un rótulo", () => {
    const menu = menuDe(porGrupoVisible(TODO), () => true);
    expect(menu.length).toBeGreaterThan(0);

    let entradas = 0;
    let traducidas = 0;
    const choques: string[] = [];
    for (const area of menu) {
      entradas += area.entradas.length;
      const porRotulo = new Map<string, string[]>();
      for (const e of area.entradas) {
        const { texto, traducido } = rotulo(e.clave);
        if (traducido) traducidas += 1;
        porRotulo.set(texto, [...(porRotulo.get(texto) ?? []), e.a]);
      }
      for (const [r, rutas] of porRotulo) {
        if (rutas.length > 1)
          choques.push(`${area.id}: «${r}» en ${rutas.join(" y ")}`);
      }
    }

    // Cuántas ha mirado y cuántas resolvió de verdad: un menú vacío, o uno
    // cuyas claves no se traducen, no puede pasar por limpio.
    expect(entradas).toBeGreaterThan(40);
    expect(traducidas).toBeGreaterThan(20);
    expect(choques).toEqual([]);
  });

  it("ninguna ruta sale dos veces en todo el menú", () => {
    const menu = menuDe(porGrupoVisible(TODO), () => true);
    const vistas = new Map<string, string[]>();
    for (const area of menu) {
      for (const e of area.entradas)
        vistas.set(e.a, [...(vistas.get(e.a) ?? []), area.id]);
    }
    const repes = [...vistas]
      .filter(([, a]) => a.length > 1)
      .map(([r, a]) => `${r}: ${a.join(", ")}`);
    expect(repes).toEqual([]);
  });
});
