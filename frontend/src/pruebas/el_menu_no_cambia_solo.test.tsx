/**
 * El menú no puede cambiar solo entre una pantalla y la siguiente.
 *
 * Lo reportó el usuario así: «vas a cuentas y contactos y luego a proveedores y
 * aparecen más cosas en esa pantalla de menú». No era aleatorio. La superficie
 * —la lista de operaciones que publica el servidor y con la que se decide qué
 * se enseña— se resolvía con **un solo conjunto de rutas** y la regla «si está
 * vacío, no se esconde nada». Esa regla mezcla tres situaciones distintas:
 *
 * 1. Todavía no ha llegado → no se esconde nada, a propósito.
 * 2. Ha llegado y esta sesión no puede nada → hay que esconder.
 * 3. Ha llegado **incompleta** porque un servicio no contestó → de lo suyo no
 *    se sabe nada, y esconderlo es confundir «no te toca» con «no he podido
 *    preguntar».
 *
 * El caso 2 y el 3 se vivían como el mismo conjunto vacío, y el 3 es el que
 * hacía desaparecer pestañas enteras sin motivo visible.
 *
 * Cada prueba de aquí se validó **plantando el caso malo**: con la lógica
 * anterior en su sitio, las tres de abajo fallan.
 */

import { describe, expect, it } from "vitest";

import { porGrupoVisible, recursoVisible } from "@/lib/modulos";
import type { Visibilidad } from "@/lib/permisos";
import type { Sesion } from "@/lib/sesion";

const SESION = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "quien@ejemplo.test",
  permisos: ["*"],
  es_admin_plataforma: false,
} as unknown as Sesion;

function visto(parcial: Partial<Visibilidad>): Visibilidad {
  return { rutas: new Set<string>(), cargada: false, sinContestar: new Set<string>(), ...parcial };
}

const SUPRESIONES = { listar: "/api/v1/supresiones", servicio: "marketing" };

describe("qué enseña el menú según lo que se sabe", () => {
  it("mientras la superficie no ha llegado, no esconde nada", () => {
    // Deliberado: un menú que aparece a trozos mientras lo miras es peor que
    // uno con una entrada de más durante medio segundo.
    expect(recursoVisible(SESION, SUPRESIONES, visto({}))).toBe(true);
  });

  it("cuando ha llegado entera, manda ella", () => {
    // El conjunto vacío **con la superficie cargada** sí esconde: es el caso
    // del agente de soporte al que se le enseñaban los veintitrés módulos.
    expect(recursoVisible(SESION, SUPRESIONES, visto({ cargada: true }))).toBe(false);
    expect(
      recursoVisible(
        SESION,
        SUPRESIONES,
        visto({ cargada: true, rutas: new Set(["/api/v1/supresiones"]) }),
      ),
    ).toBe(true);
  });

  it("el servicio que no contestó no esconde lo suyo", () => {
    // ESTE es el fallo que se reportó. `marketing` no contesta → aporta cero
    // operaciones → sus rutas no están en el conjunto → sus pestañas se
    // escondían igual que las prohibidas. Y como la superficie se pide una vez
    // al entrar, el menú se quedaba mal para toda la sesión.
    const incompleta = visto({
      cargada: true,
      rutas: new Set(["/api/v1/accounts"]),
      sinContestar: new Set(["marketing"]),
    });
    expect(recursoVisible(SESION, SUPRESIONES, incompleta)).toBe(true);
    // Lo de los servicios que SÍ contestaron se sigue decidiendo con la
    // superficie: no contestar uno no abre el menú entero.
    expect(
      recursoVisible(SESION, { listar: "/api/v1/casos", servicio: "support" }, incompleta),
    ).toBe(false);
  });

  it("una colección repartida entre servicios basta con que uno conteste", () => {
    const recurso = {
      listar: "/api/v1/:servicio/plantillas",
      servicio: "marketing",
      por_servicio: ["marketing", "support"],
    };
    expect(
      recursoVisible(
        SESION,
        recurso,
        visto({ cargada: true, rutas: new Set(["/api/v1/support/plantillas"]) }),
      ),
    ).toBe(true);
    expect(recursoVisible(SESION, recurso, visto({ cargada: true }))).toBe(false);
  });
});

describe("la barra lateral y las pestañas deciden igual", () => {
  it("un servicio caído no borra sus módulos de la barra", () => {
    // La barra decide con el RESUMEN generado, no con la tabla entera. Si el
    // resumen no llevara el servicio de cada pestaña, aquí no habría forma de
    // distinguir y los módulos de ese servicio desaparecerían del menú aunque
    // las pestañas de dentro sí se enseñaran: las dos pantallas tienen que
    // contestar lo mismo.
    const todos = porGrupoVisible(SESION, visto({}));
    const conUnoCaido = porGrupoVisible(
      SESION,
      visto({ cargada: true, sinContestar: new Set(["marketing"]) }),
    );
    const cuenta = (m: Map<string, unknown[]>) =>
      [...m.values()].reduce((n, v) => n + v.length, 0);
    expect(cuenta(todos)).toBeGreaterThan(0);
    // No se exige que salgan TODOS —los de otros servicios sí se filtran—,
    // sino que los de marketing no se hayan perdido.
    const rutas = (m: Map<string, unknown[]>) =>
      [...m.values()].flat().map((x) => (x as { ruta: string }).ruta);
    expect(rutas(conUnoCaido)).toContain("segmentos");
    // Y el contraste, que es lo que hace que esta prueba mire: con la misma
    // superficie cargada pero **sin nadie callado**, «segmentos» sí se
    // esconde. Sin esta línea la prueba pasaba igual con la lógica vieja, que
    // enseñaba el menú entero siempre que el conjunto estuviera vacío.
    const conTodosContestando = porGrupoVisible(SESION, visto({ cargada: true }));
    expect(rutas(conTodosContestando)).not.toContain("segmentos");
  });
});
