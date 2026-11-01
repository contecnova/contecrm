/**
 * Ordenar un menú no puede ser esconder la mitad.
 *
 * El 01-11-2026 se quitó la barra lateral del trabajo diario y se sustituyó
 * por la forma de Salesforce: una aplicación cada vez con **sus** pestañas
 * arriba, un lanzador para ir a las demás y una puerta aparte para la
 * configuración. El motivo está medido: el menú ofrecía de golpe 24 módulos
 * del catálogo, ~35 pantallas a mano y 211 pestañas dentro de ellas, con
 * «Cuentas y contactos» y «Contrato de la API» a la misma altura.
 *
 * El riesgo de un cambio así no es que quede feo: es que **algo deje de tener
 * camino**. Y pasó mientras se hacía — al quitar la barra lateral se fue con
 * ella el interruptor «Trabajar / Administrar», y la configuración entera se
 * quedó sin ninguna forma de llegar hasta que se puso el engranaje. No lo
 * cazó ninguna prueba porque no había ninguna que mirase esto.
 *
 * Esta la hay. Recorre TODO lo que el producto declara y exige que cada cosa
 * tenga al menos un camino, contando cuántas ha recorrido: una comprobación
 * que no mira nada parece verde.
 */

import { describe, expect, it } from "vitest";

import {
  APLICACIONES,
  areasDeConfiguracion,
  areasDeTrabajo,
  pestanasDe,
  pestanasDeTodas,
} from "@/lib/aplicaciones";
import { porGrupoVisible } from "@/lib/modulos";
import { ACCESOS, AREAS, TRANSVERSALES, menuDe } from "@/lib/navegacion";

/** El menú de quien lo puede ver todo: lo que se audita es el diseño, no un perfil. */
function menuCompleto(ambito?: "trabajar" | "administrar") {
  return menuDe(porGrupoVisible(null), () => true, ambito);
}

/** Todo camino que se alcanza desde las aplicaciones y su lanzador. */
function alcanzableTrabajando(): Set<string> {
  const menu = menuCompleto("trabajar");
  return new Set(
    [
      ...APLICACIONES.flatMap((app) => pestanasDe(app, menu)),
      ...pestanasDeTodas(menu),
    ].map((e) => e.a),
  );
}

/** Todo camino que se alcanza desde el árbol de configuración. */
function alcanzableConfigurando(): Set<string> {
  return new Set(menuCompleto("administrar").flatMap((a) => a.entradas.map((e) => e.a)));
}

/**
 * Lo que NO necesita estar en una aplicación, con su motivo.
 *
 * Escrito como excepciones y no como lista de los que sí: una lista de los que
 * cumplen se queda corta en cuanto alguien añade una pantalla, y se queda
 * corta en silencio.
 */
const TIENE_SU_PROPIO_SITIO: Record<string, string> = {
  "/": "Es la portada, y es pestaña de todas las aplicaciones.",
  "/puesto": "Pestaña de todas las aplicaciones, y además está en el menú de la persona.",
  "/chat": "Tiene su icono fijo en la barra de arriba: se habla de clientes, de ventas y de casos desde el mismo sitio, así que no es de un dominio.",
  "/menciones": "Igual que el chat: te mencionan en una cuenta, en una oportunidad y en un caso.",
};

describe("toda área está detrás de exactamente una puerta", () => {
  it("o es de una aplicación, o es de configuración, pero no de las dos ni de ninguna", () => {
    const deAplicacion = APLICACIONES.flatMap((a) => a.areas);
    const deConfiguracion = areasDeConfiguracion();
    expect(AREAS.length).toBeGreaterThan(0);

    // **Toda área de trabajo está en una aplicación.** Ésta es la que falla
    // cuando alguien añade un área y no la reparte: antes se calculaba por
    // descarte y el olvido se volvía «configuración» sin que nadie lo
    // decidiera, así que la prueba daba verde con un área huérfana.
    for (const id of areasDeTrabajo()) {
      const cuantas = APLICACIONES.filter((a) => a.areas.includes(id)).length;
      expect(cuantas, `el área de trabajo «${id}» está en ${cuantas} aplicaciones`).toBe(1);
    }

    for (const area of AREAS) {
      const puertas =
        (deAplicacion.includes(area.id) ? 1 : 0) + (deConfiguracion.includes(area.id) ? 1 : 0);
      expect(puertas, `el área «${area.id}» sale por ${puertas} puertas, y tiene que ser una`).toBe(1);
    }
    // Y ninguna aplicación se queda sin área: una puerta que no lleva a
    // ninguna parte es peor que no tenerla.
    for (const app of APLICACIONES) {
      expect(app.areas.length, `la aplicación «${app.id}» no tiene áreas`).toBeGreaterThan(0);
    }
  });
});

describe("ninguna pantalla se ha quedado sin camino", () => {
  it("las del catálogo y las escritas a mano, todas", () => {
    const trabajando = alcanzableTrabajando();
    const configurando = alcanzableConfigurando();
    const todas = [...ACCESOS, ...TRANSVERSALES, ...menuCompleto().flatMap((a) => a.entradas)];
    const caminos = [...new Set(todas.map((e) => e.a))];

    // Cuántas se han recorrido de verdad: sin esto, un fallo que dejara la
    // lista vacía daría verde.
    expect(caminos.length).toBeGreaterThan(40);

    const perdidas = caminos.filter(
      (a) => !trabajando.has(a) && !configurando.has(a) && !(a in TIENE_SU_PROPIO_SITIO),
    );
    expect(perdidas, `sin ningún camino: ${perdidas.join(", ")}`).toEqual([]);
  });

  it("y las excepciones no se escriben sin motivo", () => {
    for (const [camino, motivo] of Object.entries(TIENE_SU_PROPIO_SITIO)) {
      expect(motivo.length, `«${camino}» está exenta sin explicar por qué`).toBeGreaterThan(30);
    }
  });
});

describe("la configuración sigue teniendo puerta", () => {
  it("hay pantallas detrás de ella, así que el engranaje tiene a dónde llevar", () => {
    // Si esto se quedara vacío, el engranaje no se pintaría —no se ofrece una
    // puerta a una pantalla vacía— y la configuración desaparecería sin que
    // nada fallara. Que es exactamente lo que pasó mientras se hacía el
    // cambio.
    expect(alcanzableConfigurando().size).toBeGreaterThan(5);
  });
});
