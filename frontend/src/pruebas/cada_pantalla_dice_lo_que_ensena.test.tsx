/**
 * Cada pantalla declara qué capacidades del catálogo enseña
 * (CRM-07.04.05.05, CRM-07.04.05.02).
 *
 * La declaración se escribe en un minuto. Lo único que hace caro declarar algo
 * que no se enseña es que **se pinta en la pantalla**, así que lo que se mide
 * aquí es justo eso: que se pinte, y que no se pinte a medias.
 *
 * Vive en `capacidades.ts` y no en `modulos.ts` porque ese otro fichero lo
 * importa el marco y viaja en lo que se descarga antes de pintar nada; esta
 * lista sólo la pinta la cabecera de un módulo, plegada.
 */

import { describe, expect, it } from "vitest";

import { CAPACIDADES_POR_MODULO } from "@/lib/capacidades";
import { MODULOS } from "@/lib/modulos";

/** Lo que declara este módulo, o nada si no declara. */
const declaradas = (ruta: string): readonly string[] => CAPACIDADES_POR_MODULO[ruta] ?? [];

describe("la declaración de capacidades", () => {
  it("no repite un identificador dentro de un módulo", () => {
    for (const m of MODULOS) {
      const lista = declaradas(m.ruta);
      expect(new Set(lista).size, `${m.ruta} repite capacidades`).toBe(lista.length);
    }
  });

  it("no declara como capacidad de producto la de front de la propia pantalla", () => {
    // `capacidad` dice qué capacidad de FRONT es esta pantalla; `capacidades`
    // dice qué de producto se ve en ella. Mezclarlas haría que el informe
    // contara la pantalla como si enseñara su propia existencia.
    for (const m of MODULOS) {
      expect(declaradas(m.ruta), m.ruta).not.toContain(m.capacidad);
    }
  });

  it("usa identificadores con la forma del catálogo", () => {
    const forma = /^CRM-\d\d\.\d\d\.\d\d\.\d\d$/;
    for (const m of MODULOS) {
      for (const c of declaradas(m.ruta)) {
        expect(forma.test(c), `${m.ruta}: «${c}»`).toBe(true);
      }
    }
  });

  it("una capacidad no se declara en dos módulos a la vez", () => {
    // Y ninguna declara para una ruta que no existe: un módulo que se renombra
    // dejaría su lista huérfana y nadie la pintaría nunca.
    // Dos pantallas que dicen enseñar lo mismo son dos sitios donde mirar, y el
    // informe de cobertura contaría una capacidad como cubierta por partida
    // doble. Si de verdad se ve en las dos, la que manda es una y la otra
    // enlaza.
    const donde = new Map<string, string[]>();
    for (const m of MODULOS) {
      for (const c of declaradas(m.ruta)) {
        donde.set(c, [...(donde.get(c) ?? []), m.ruta]);
      }
    }
    const repetidas = [...donde.entries()].filter(([, rutas]) => rutas.length > 1);
    expect(repetidas, JSON.stringify(repetidas)).toHaveLength(0);

    const rutas = new Set(MODULOS.map((m) => m.ruta));
    const huerfanas = Object.keys(CAPACIDADES_POR_MODULO).filter((r) => !rutas.has(r));
    expect(huerfanas, huerfanas.join(", ")).toHaveLength(0);
  });

  it("la mayoría de los módulos ya declara lo que enseña", () => {
    // El tope del lado del servidor cuenta las que faltan; aquí lo que importa
    // es que el mecanismo esté puesto y no sea un campo que nadie rellena.
    const conDeclaracion = MODULOS.filter((m) => declaradas(m.ruta).length > 0);
    expect(conDeclaracion.length).toBeGreaterThanOrEqual(20);
  });
});
