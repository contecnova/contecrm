/**
 * Un módulo abre por la pestaña que declara, y todos la declaran.
 *
 * Antes abría por `recursos[0]`, y ese orden lo escribió el catálogo. Medido
 * en el navegador sobre los 25 módulos, con sesión de administrador:
 *
 * - «Campañas» abría en la **papelera**.
 * - «Casos» en «Satisfacción del periodo», que no enseña nada hasta elegir un
 *   rango de fechas; los casos eran la pestaña 5 de 13.
 * - «Prospección» en «Cadencias» (los leads, la 3ª), «Actividades» en
 *   «Plantillas» (la 3ª), «Previsión» en «Territorios», «Tenants y unidades»
 *   en «Compromisos».
 *
 * De 24 módulos con más de una pestaña, **uno** abría por sus registros.
 *
 * El gate no comprueba CUÁL se eligió —eso es criterio— sino que haya
 * exactamente una elegida: lo que falla solo es la ausencia de decisión.
 *
 * Validado plantando el caso malo por partida doble: quitando el `principal`
 * de «Casos» falla la primera prueba nombrando el módulo, y poniéndoselo
 * también a «Encuestas» falla la segunda.
 */

import { describe, expect, it } from "vitest";

import { MODULOS } from "@/lib/modulos";
import {
  RECURSOS_POR_MODULO,
  pestanaPrincipal,
  recursosDe,
} from "@/lib/recursos";

describe("un módulo abre por lo suyo", () => {
  it("todo módulo con más de una pestaña declara cuál es la suya", () => {
    const conVarias = Object.entries(RECURSOS_POR_MODULO).filter(
      ([, r]) => r.length > 1,
    );
    expect(conVarias.length).toBeGreaterThan(20); // que haya mirado de verdad

    const sinDeclarar = conVarias
      .filter(([, r]) => !r.some((x) => x.principal))
      .map(
        ([ruta, r]) =>
          `${ruta} (${r.length} pestañas, abriría en «${r[0]!.nombre}»)`,
      );
    expect(sinDeclarar).toEqual([]);
  });

  it("ninguno declara dos", () => {
    const dobles = Object.entries(RECURSOS_POR_MODULO)
      .map(
        ([ruta, r]) =>
          [ruta, r.filter((x) => x.principal).map((x) => x.nombre)] as const,
      )
      .filter(([, n]) => n.length > 1)
      .map(([ruta, n]) => `${ruta}: ${n.join(", ")}`);
    expect(dobles).toEqual([]);
  });

  it("la papelera no puede ser la principal de nadie", () => {
    // El caso concreto que lo destapó. La papelera se pinta como icono al
    // final de la fila, así que además de absurda era invisible: la pestaña
    // marcada no estaba entre las que se leen.
    const rutas = Object.keys(RECURSOS_POR_MODULO);
    expect(rutas.length).toBeGreaterThan(20);
    const malas = rutas.filter((ruta) =>
      /papelera/i.test(recursosDe(ruta)[pestanaPrincipal(ruta)]?.nombre ?? ""),
    );
    expect(malas).toEqual([]);
  });

  it("cada módulo del menú abre por una pestaña que existe y se puede leer", () => {
    let mirados = 0;
    const rotos: string[] = [];
    for (const m of MODULOS) {
      const pestanas = recursosDe(m.ruta);
      if (pestanas.length === 0) continue;
      mirados += 1;
      const elegida = pestanas[pestanaPrincipal(m.ruta)];
      if (!elegida) rotos.push(`${m.ruta}: índice fuera de la lista`);
      // Una pestaña con icono se pinta SÓLO como icono, al final: no sirve de
      // portada porque quien entra no lee su nombre en ningún sitio.
      else if (elegida.icono)
        rotos.push(`${m.ruta}: «${elegida.nombre}» sólo se pinta como icono`);
    }
    expect(mirados).toBeGreaterThan(20);
    expect(rotos).toEqual([]);
  });
});
