/**
 * Un área del menú con dieciocho entradas no es un área: es la lista de antes
 * con un título encima.
 *
 * **Medido el 03-11-2026**, antes de tocar nada. El menú de Administrar tenía
 * dos áreas:
 *
 * - **«Automatización»**, con 2 entradas.
 * - **«Configuración»**, con 18 — «Administración», «Identidad y seguridad»,
 *   «Plataforma y cumplimiento», «Promoción entre entornos», «Recorrido
 *   guiado», «Cobertura», «Panel de cumplimiento», «Despliegues y desvíos»,
 *   «Ciclo de vida del cliente», «Estado», «Ayuda» y los seis módulos de
 *   plataforma—. Dos de ellas, «Estado» y «Ayuda», no configuran nada.
 *
 * Agrupar no sirve de nada si un grupo se queda con el 90 % de las entradas:
 * quien busca sigue leyendo dieciocho rótulos, y encima se los ha encontrado
 * detrás de un desplegable.
 *
 * El techo es **10**, no un número redondo elegido por gusto: el área más
 * poblada del producto es «Ventas» con 9 —cinco pantallas y cuatro módulos—,
 * y ese reparto está razonado en `navegacion.ts`. Diez deja un hueco para la
 * siguiente y avisa en cuanto una empieza a convertirse en el cajón de antes.
 *
 * Y un suelo de **2**: un área con una sola entrada es un título que no
 * agrupa nada, y obliga a abrir un desplegable para ver un enlace. «Clientes»
 * fue exactamente eso mientras tuvo sólo «Duplicados».
 */

import { describe, expect, it } from "vitest";

import { MODULOS } from "@/lib/modulos";
import { AREAS, menuDe } from "@/lib/navegacion";

const TECHO = 10;
const SUELO = 2;

/**
 * El menú con TODO el catálogo dentro, sin filtrar por permisos.
 *
 * No `porGrupoVisible(null)`: ésa quita los módulos que una sesión sin
 * permisos no vería —hoy cuatro— y lo que se audita aquí es el **reparto
 * declarado**, no lo que ve un perfil. Con ella, un área de dos entradas
 * parecía de una y el suelo saltaba por un motivo que no era el suyo.
 */
function todosLosGrupos() {
  const grupos = new Map<string, typeof MODULOS>();
  for (const m of MODULOS) grupos.set(m.grupo, [...(grupos.get(m.grupo) ?? []), m]);
  return grupos;
}

function menuCompleto() {
  return menuDe(todosLosGrupos(), () => true);
}

describe("ningún área del menú", () => {
  it("se queda con más entradas de las que se pueden leer de un vistazo", () => {
    const menu = menuCompleto();
    // Cuántas se han recorrido: un menú vacío daría verde sin mirar nada.
    expect(menu.length).toBe(AREAS.length);
    expect(menu.length).toBeGreaterThan(5);

    const pasadas = menu
      .filter((a) => a.entradas.length > TECHO)
      .map((a) => `«${a.id}» con ${a.entradas.length} entradas`);
    expect(
      pasadas,
      `un área por encima de ${TECHO} vuelve a ser la lista de antes:\n  ` +
        pasadas.join("\n  "),
    ).toEqual([]);
  });

  it("ni es un título con un solo enlace debajo", () => {
    const menu = menuCompleto();
    const solitarias = menu
      .filter((a) => a.entradas.length < SUELO)
      .map((a) => `«${a.id}» con ${a.entradas.length}`);
    expect(
      solitarias,
      `un área no agrupa nada con menos de ${SUELO} entradas:\n  ` +
        solitarias.join("\n  "),
    ).toEqual([]);
  });

  it("y las dos puertas reparten de verdad: ninguna con una sola área", () => {
    // El reparto en temas se puede deshacer sin querer devolviendo todos los
    // grupos a la misma área, y entonces las dos pruebas de arriba seguirían
    // pasando mientras hubiera menos de diez entradas. Esto lo caza.
    for (const ambito of ["trabajar", "administrar"] as const) {
      const areas = menuDe(todosLosGrupos(), () => true, ambito);
      expect(
        areas.length,
        `el ámbito «${ambito}» tiene ${areas.length} área(s)`,
      ).toBeGreaterThan(1);
    }
  });
});
