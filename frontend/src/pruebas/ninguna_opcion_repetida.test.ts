/**
 * Ninguna opción del menú aparece dos veces.
 *
 * Lo reportó el usuario: «se replican opciones o hay duplicadas, vamos fatal».
 * Había dos formas distintas de que pasara y las dos habían pasado:
 *
 * - **Dentro de un módulo**: tres pestañas de «Cuentas» —planes de cuenta,
 *   estado financiero y cambios de empresa— se añadieron sin ver que ya
 *   estaban, porque el fichero tiene dos mil líneas y las pestañas de un
 *   módulo no están ordenadas por nada.
 * - **Entre módulos**: «Supresiones» salía en «Segmentación» y en «Contenido y
 *   gobierno». La misma ruta, la misma lista, dos sitios desde los que
 *   editarla. Si el registro es el mismo, es la misma pantalla.
 *
 * Este gate se valida plantando el caso malo: duplicar cualquier pestaña lo
 * pone rojo.
 */

import { describe, expect, it } from "vitest";

import { RECURSOS_POR_MODULO } from "@/lib/recursos";

/**
 * Rutas que SÍ pueden salir en más de un módulo, con su motivo.
 *
 * Va al revés que una lista de permitidos genérica: aquí cada excepción se
 * escribe con el porqué, porque una lista de «estos valen» se queda corta en
 * cuanto alguien añade el siguiente y nadie se entera de que debía mirarla.
 * Hoy está vacía, y eso también es un dato: no ha hecho falta ninguna.
 */
const REPETIR_ADREDE: Record<string, string> = {};

describe("el menú no repite opciones", () => {
  it("lee la tabla entera", () => {
    // Si un cambio de formato dejara la tabla vacía, todo lo de abajo pasaría
    // sin mirar nada. Se fija el suelo medido hoy.
    const total = Object.values(RECURSOS_POR_MODULO).reduce((n, v) => n + v.length, 0);
    expect(Object.keys(RECURSOS_POR_MODULO).length).toBeGreaterThanOrEqual(25);
    expect(total).toBeGreaterThanOrEqual(200);
  });

  it("dentro de un módulo no hay dos pestañas iguales", () => {
    const repetidas: string[] = [];
    for (const [modulo, pestanas] of Object.entries(RECURSOS_POR_MODULO)) {
      for (const campo of ["nombre", "listar"] as const) {
        const vistos = new Set<string>();
        for (const p of pestanas) {
          const valor = p[campo];
          if (vistos.has(valor)) repetidas.push(`${modulo}: ${campo} «${valor}» dos veces`);
          vistos.add(valor);
        }
      }
    }
    expect(repetidas).toEqual([]);
  });

  it("dos pestañas de un módulo no declaran el mismo tipo de registro", () => {
    // La ficha resuelve qué pestaña abre una fila **por su `objeto`**, así que
    // con dos iguales gana la primera y la segunda abre la ficha equivocada:
    // pide el id de un registro contra la ruta del otro y contesta «no
    // existe». Reportado así, abriendo una fila de «Estado financiero».
    //
    // Medido el 29-10-2026: cuatro módulos lo tenían. Las cuatro pestañas
    // segundas habían tomado prestado el `objeto` del recurso padre —el
    // financiero de los planes, la interacción del canal, la fuente federada
    // de la tabla, la ejecución programada del registro recibido— y las cuatro
    // son OTRO registro, con su propia ruta de detalle.
    //
    // La forma de arreglarlo es **no declararlo**: sin `objeto`, se deriva de
    // la ruta que lista, que es única, y la ficha resuelve su ruta real con el
    // contrato. Declarar uno inventado sería una segunda lista que mantener.
    const repetidos: string[] = [];
    for (const [modulo, pestanas] of Object.entries(RECURSOS_POR_MODULO)) {
      const vistos = new Map<string, string>();
      for (const p of pestanas) {
        // El `objeto` DE LA PESTAÑA. El de `abre: {...}` es otra cosa: dice a
        // qué registro lleva una fila —un documento que vence abre a su
        // proveedor— y ahí repetirlo es lo correcto.
        if (!p.objeto) continue;
        const antes = vistos.get(p.objeto);
        if (antes) {
          repetidos.push(`${modulo}: «${antes}» y «${p.nombre}» dicen ser «${p.objeto}»`);
        }
        vistos.set(p.objeto, p.nombre);
      }
    }
    expect(repetidos).toEqual([]);
  });

  it("el mismo registro no se edita desde dos módulos", () => {
    const donde = new Map<string, string[]>();
    for (const [modulo, pestanas] of Object.entries(RECURSOS_POR_MODULO)) {
      for (const p of pestanas) {
        donde.set(p.listar, [...(donde.get(p.listar) ?? []), `${modulo}·${p.nombre}`]);
      }
    }
    const repetidas = [...donde.entries()]
      .filter(([ruta, sitios]) => sitios.length > 1 && !REPETIR_ADREDE[ruta])
      .map(([ruta, sitios]) => `${ruta} → ${sitios.join(", ")}`);
    expect(repetidas).toEqual([]);
  });
});
