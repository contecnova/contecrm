/**
 * El gráfico y el código son la misma cosa, y esto lo defiende.
 *
 * Lo que se comprueba es lo que haría falso el «intercambiables»: que una
 * definición escrita a mano —sin posiciones— se abra bien, y que el diagrama
 * enseñe TODOS los caminos que el proceso tiene.
 */

import { describe, expect, it } from "vitest";

import { aristas, colocar, conPosiciones, porCapas, salidas, type Definicion } from "@/lib/grafo";

const PROCESO: Definicion = {
  inicio: "recibir",
  pasos: {
    recibir: { tipo: "servicio", siguiente: "decidir" },
    decidir: {
      tipo: "decision",
      condiciones: [{ entonces: "aprobar" }],
      si_no: "rechazar",
      al_fallar: "avisar",
    },
    aprobar: { tipo: "humano", rutas: { si: "terminar", no: "rechazar" } },
    rechazar: { tipo: "fin" },
    avisar: { tipo: "fin" },
    terminar: { tipo: "fin" },
  },
};

describe("las salidas de un paso", () => {
  it("recoge todos los tipos de enlace", () => {
    // Si aquí faltara uno, el diagrama enseñaría un proceso con menos caminos
    // de los que tiene, y el que falta sería justo el que nadie revisa.
    expect(salidas(PROCESO.pasos!.decidir!).map((s) => s.hasta).sort()).toEqual([
      "aprobar",
      "avisar",
      "rechazar",
    ]);
  });

  it("las rutas de una tarea humana también son salidas", () => {
    expect(salidas(PROCESO.pasos!.aprobar!).map((s) => s.etiqueta).sort()).toEqual(["no", "si"]);
  });

  it("un paso final no tiene salidas", () => {
    expect(salidas(PROCESO.pasos!.rechazar!)).toEqual([]);
  });
});

describe("de código a gráfico", () => {
  it("una definición sin posiciones se coloca sola", () => {
    // Sin esto, «intercambiables» sería falso: se podría ir del gráfico al
    // código pero no al revés.
    const nodos = colocar(PROCESO);
    expect(nodos).toHaveLength(6);
    expect(nodos.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))).toBe(true);
  });

  it("las capas ordenan por distancia al inicio", () => {
    const capas = porCapas(PROCESO);
    expect(capas.get("recibir")).toBe(0);
    expect(capas.get("decidir")).toBe(1);
    expect(capas.get("aprobar")).toBe(2);
  });

  it("un paso inalcanzable se coloca igual, no se esconde", () => {
    // Esconderlo haría imposible arreglarlo desde el propio editor.
    const con = { ...PROCESO, pasos: { ...PROCESO.pasos, huerfano: { tipo: "fin" } } };
    expect(colocar(con).map((n) => n.nombre)).toContain("huerfano");
  });

  it("se dibujan todas las aristas", () => {
    expect(aristas(PROCESO)).toHaveLength(6);
  });
});

describe("de gráfico a código", () => {
  it("guardar posiciones no toca la definición", () => {
    const nodos = colocar(PROCESO);
    const guardada = conPosiciones(PROCESO, nodos);
    expect(guardada.pasos).toEqual(PROCESO.pasos);
    expect(guardada.inicio).toBe(PROCESO.inicio);
    expect(Object.keys(guardada.grafico!.posiciones!)).toHaveLength(6);
  });

  it("una posición guardada manda sobre la automática", () => {
    // Añadir un paso nuevo a un proceso ya colocado no puede reordenar todo lo
    // demás: es lo que hace que nadie vuelva a tocar el diagrama.
    const conPos = conPosiciones(PROCESO, [
      { nombre: "recibir", tipo: "servicio", x: 500, y: 300, esInicio: true },
    ]);
    const recibir = colocar(conPos).find((n) => n.nombre === "recibir");
    expect([recibir?.x, recibir?.y]).toEqual([500, 300]);
  });
});
