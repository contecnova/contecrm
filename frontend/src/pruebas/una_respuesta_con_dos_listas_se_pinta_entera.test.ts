/**
 * Una respuesta con varias listas se pinta entera, no como una fila.
 *
 * El listado saca sus filas sin que nadie se lo explique: si es un array, ése;
 * si trae `items`, ése; y si trae **una sola** propiedad que sea un array
 * —`{partners: […]}`—, ésa. Con dos no adivina, y hace bien: elegir mal
 * enseñaría la lista equivocada.
 *
 * Lo que faltaba era qué pasa entonces, y lo que pasaba era peor que esconder:
 * pintaba **una fila con el objeto entero**, una columna por propiedad y las
 * filas de verdad apelotonadas dentro de una celda.
 *
 * **Medido el 04-11-2026** llamando a las pestañas declaradas contra un
 * servidor de verdad: diez caían ahí. «Entradas sin atribuir» salía con tres
 * columnas —«Interacciones», «Interlocutores frecuentes», «Cuantas»— y cuatro
 * interacciones dentro de la primera. El dato estaba y no se podía leer.
 *
 * Ahora: la pestaña declara cuál es su listado (`clave_lista`) y las demás se
 * pintan debajo, cada una con su nombre. Comprobado en el producto: esa misma
 * pestaña enseña 4 interacciones con sus columnas y 1 interlocutor frecuente.
 */

import { describe, expect, it } from "vitest";

import { otrasListas } from "@/paginas/Modulo";
import { comoFilas } from "@/paginas/Consola";
import { MODULOS } from "@/lib/modulos";
import { recursosDe } from "@/lib/recursos";

const DOS_LISTAS = {
  interacciones: [
    { id: "i1", canal: "correo" },
    { id: "i2", canal: "web" },
  ],
  interlocutores_frecuentes: [{ interlocutor: "ana@ejemplo.com", veces: 4 }],
  cuantas: 2,
};

describe("una respuesta con varias listas", () => {
  it("usa la declarada como listado", () => {
    expect(comoFilas(DOS_LISTAS, "interacciones")).toHaveLength(2);
    expect(comoFilas(DOS_LISTAS, "interlocutores_frecuentes")).toHaveLength(1);
  });

  it("y sin declarar sigue sin adivinar, que es lo correcto", () => {
    // No se cambia esa regla: con dos listas, elegir una al azar enseñaría la
    // equivocada. Lo que se añade es poder decirlo, no adivinar mejor.
    expect(comoFilas(DOS_LISTAS)).toEqual([DOS_LISTAS]);
  });

  it("y las que no son el listado se enseñan aparte, no se pierden", () => {
    const extra = otrasListas(DOS_LISTAS, "interacciones");
    expect(extra).toHaveLength(1);
    expect(extra[0]?.clave).toBe("interlocutores_frecuentes");
    expect(extra[0]?.filas).toHaveLength(1);
  });

  it("no inventa secciones en el caso normal", () => {
    // Más de doscientas pestañas traen una sola lista. Ahí no hay nada que
    // enseñar aparte, y una sección vacía debajo de cada listado sería ruido.
    expect(otrasListas({ items: [{ id: 1 }] })).toEqual([]);
    expect(otrasListas([{ id: 1 }])).toEqual([]);
    expect(otrasListas({ partners: [{ id: 1 }], cuantos: 1 })).toEqual([]);
    // Y una lista vacía tampoco pinta sección: una tabla sin filas bajo el
    // listado no dice nada que el listado no diga.
    expect(otrasListas({ a: [{ id: 1 }], b: [] }, "a")).toEqual([]);
  });

  it("las pestañas que lo declaran lo declaran a una lista con nombre", () => {
    // Que la declaración exista y no esté vacía. Cuál es la correcta lo
    // comprueba `test_las_pestanas_de_la_consola_contestan.py` contra el
    // servidor: aquí no hay respuestas que mirar.
    let declaradas = 0;
    for (const modulo of MODULOS) {
      for (const recurso of recursosDe(modulo.ruta)) {
        if (!recurso.clave_lista) continue;
        declaradas += 1;
        expect(recurso.clave_lista).toMatch(/^[a-z][a-z0-9_]*$/);
      }
    }
    expect(declaradas).toBeGreaterThanOrEqual(10);
  });

  it("un diccionario de registros con la misma forma es una lista, y cada fila guarda su clave", () => {
    // «Ajustes»: 91 umbrales salían como una fila de 91 columnas.
    const filas = comoFilas({
      oidc_cache_ttl_s: { valor: 300, origen: "entorno", tipo: "int" },
      busqueda_idioma: { valor: "es", origen: "tenant", tipo: "str" },
    });
    expect(filas).toHaveLength(2);
    expect(filas[0]).toMatchObject({ clave: "oidc_cache_ttl_s", valor: 300 });
  });

  it("un resumen que mezcla formas sigue siendo una fila", () => {
    const resumen = { total: 12, por_canal: { web: 3 }, por_mes: { "2026-10": 9 } };
    expect(comoFilas(resumen)).toHaveLength(1);
    expect(comoFilas({ solo: { valor: 1 } })).toHaveLength(1);
    // Todo registros, pero de formas distintas: es un resumen, no una lista.
    expect(comoFilas({ por_canal: { web: 3 }, por_mes: { "2026-10": 9 } })).toHaveLength(1);
  });
});
