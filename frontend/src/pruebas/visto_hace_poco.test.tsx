/**
 * «Visto hace poco»: volver a donde se estaba sin buscarlo otra vez.
 *
 * **El hueco, medido el 03-11-2026** comparando con Salesforce: allí lo
 * primero que sale al pinchar el buscador es lo último que has abierto, y la
 * vista por defecto de cada objeto es ésa. Aquí la paleta con la caja vacía
 * enseñaba las 61 pantallas por orden de declaración — útil para descubrir el
 * producto y para nada más, porque quien la abre ya sabe a dónde va.
 *
 * Lo que se vigila, que es lo que se puede romper sin que se note:
 *
 *  · **Se apunta desde el panel de datos clave**, no desde cada pantalla. Hay
 *    catorce fichas con ese panel; llamarlo a mano en las catorce son catorce
 *    ocasiones de olvidarlo, y una ficha que no se apunta se ve exactamente
 *    igual que una que sí.
 *  · **Una vez por registro abierto**, no una por repintado. Una ficha que
 *    termina de cargar y rellena su título repintaría, y con el nombre entre
 *    las dependencias apuntaría dos veces.
 *  · **El fallo no se propaga.** Es un apunte de conveniencia: lo que no puede
 *    pasar es que la ficha que se ha venido a ver no se pinte por esto.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";

import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let llamadas: { ruta: string; metodo: string; cuerpo?: unknown }[] = [];
let falla = false;

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(
      async (ruta: string, opciones?: { metodo?: string; cuerpo?: unknown }) => {
        llamadas.push({
          ruta,
          metodo: opciones?.metodo ?? "GET",
          cuerpo: opciones?.cuerpo,
        });
        if (falla) throw new Error("no contesta");
        return { datos: { items: [] } };
      },
    ),
  };
});

const { anotarVisto, ultimosVistos } = await import("@/lib/vistos");

// **Cada prueba, con SU registro.** `anotarVisto` colapsa dos visitas al
// mismo registro dentro de treinta segundos —son la misma visita, y así se
// evitan los remontajes del marco y el doble disparo del modo estricto—, y
// esa ventana vive en el módulo, compartida por todo el fichero. Reutilizando
// el mismo identificador, la segunda prueba no apuntaba nada y fallaba por un
// motivo que no era el suyo.
beforeEach(() => {
  llamadas = [];
  falla = false;
  vi.clearAllMocks();
});

describe("apuntar una visita", () => {
  it("manda el tipo, el identificador y el nombre con el que se vio", async () => {
    anotarVisto("cuenta", "manda-1", "Ibérica");
    await waitFor(() => expect(llamadas).toHaveLength(1));
    expect(llamadas[0]).toMatchObject({
      ruta: "/api/v1/vistos",
      metodo: "POST",
      cuerpo: { objeto_tipo: "cuenta", objeto_id: "manda-1", nombre: "Ibérica" },
    });
  });

  it("sin registro no se apunta nada", () => {
    anotarVisto("cuenta", "", "Ibérica");
    anotarVisto("", "c-1", "Ibérica");
    expect(llamadas).toEqual([]);
  });

  it("un fallo no se propaga: la ficha no se puede caer por el historial", async () => {
    falla = true;
    // Sin `await` y sin `catch` del que llama: si `anotarVisto` dejara
    // escapar la promesa rechazada, esto sería un fallo no capturado.
    expect(() => anotarVisto("cuenta", "falla-1", "Ibérica")).not.toThrow();
    await waitFor(() => expect(llamadas).toHaveLength(1));
  });

  it("dos visitas al mismo registro seguidas son una", async () => {
    // **Medido con el barrido el 03-11-2026**: 57 apuntes para 17 registros,
    // más de tres por registro. No eran visitas de nadie —eran remontajes del
    // marco y el doble disparo de efectos del modo estricto—, y eran tres
    // escrituras donde hace falta una.
    anotarVisto("cuenta", "repe-1", "Ibérica");
    await waitFor(() => expect(llamadas).toHaveLength(1));
    anotarVisto("cuenta", "repe-1", "Ibérica");
    anotarVisto("cuenta", "repe-1", "Ibérica");
    await new Promise((r) => setTimeout(r, 50));
    expect(llamadas).toHaveLength(1);
    // Y otro registro SÍ se apunta: la ventana es por registro, no un
    // silenciador general.
    anotarVisto("cuenta", "repe-2", "Otra");
    await waitFor(() => expect(llamadas).toHaveLength(2));
  });

  it("al pedirlos se dice cuántos, porque la lista de la paleta es corta", async () => {
    await ultimosVistos(8);
    expect(llamadas[0]?.ruta).toBe("/api/v1/vistos?limite=8");
  });
});

describe("quién lo apunta", () => {
  it("el panel de datos clave, y ninguna ficha por su cuenta", () => {
    const panel = readFileSync(
      resolve(process.cwd(), "src", "componentes", "DatosClave.tsx"),
      "utf-8",
    );
    expect(panel).toContain("anotarVisto(");
    // Y **no** con el nombre entre las dependencias: con él, la ficha que
    // termina de cargar y rellena su título apunta dos veces.
    expect(panel).toMatch(/\}, \[tipo, idDelRegistro\]/);

    const dir = resolve(process.cwd(), "src", "paginas");
    const conPanel = readdirSync(dir).filter(
      (f) =>
        f.endsWith(".tsx") &&
        readFileSync(join(dir, f), "utf-8").includes("<DatosClave"),
    );
    // Cuántas se han recorrido: si el filtro dejara de casar, esto daría
    // verde sin haber mirado ninguna.
    expect(conPanel.length).toBeGreaterThan(10);
    for (const f of conPanel) {
      expect(
        readFileSync(join(dir, f), "utf-8"),
        `${f} apunta la visita por su cuenta`,
      ).not.toContain("anotarVisto");
    }
  });

  it("y la paleta los enseña con la caja vacía", () => {
    const paleta = readFileSync(
      resolve(process.cwd(), "src", "componentes", "Paleta.tsx"),
      "utf-8",
    );
    expect(paleta).toContain("ultimosVistos(");
    // Delante de las pantallas: es a donde va quien abre la paleta sin saber
    // todavía qué va a escribir.
    expect(paleta).toContain("return [...recientes, ...destinos]");
  });
});

describe("el panel de datos clave", () => {
  it("apunta la visita una sola vez por registro", async () => {
    const { DatosClave } = await import("@/componentes/DatosClave");
    const { rerender } = render(
      <DatosClave
        recurso={undefined}
        tipo="cuenta"
        nombre="Ibérica"
        fila={{ id: "panel-1", nombre: "Ibérica" }}
      />,
    );
    await waitFor(() =>
      expect(llamadas.filter((l) => l.ruta === "/api/v1/vistos")).toHaveLength(1),
    );

    // El mismo registro con el nombre ya cargado: no se vuelve a apuntar.
    rerender(
      <DatosClave
        recurso={undefined}
        tipo="cuenta"
        nombre="Ibérica Levante"
        fila={{ id: "panel-1", nombre: "Ibérica Levante" }}
      />,
    );
    expect(llamadas.filter((l) => l.ruta === "/api/v1/vistos")).toHaveLength(1);

    // Otro registro sí.
    rerender(
      <DatosClave
        recurso={undefined}
        tipo="cuenta"
        nombre="Otra"
        fila={{ id: "panel-2", nombre: "Otra" }}
      />,
    );
    await waitFor(() =>
      expect(llamadas.filter((l) => l.ruta === "/api/v1/vistos")).toHaveLength(2),
    );
  });
});
