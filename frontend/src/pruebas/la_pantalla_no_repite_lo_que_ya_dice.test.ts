/**
 * Lo que el servicio explica sobre una pantalla sólo se pinta si **añade
 * algo**.
 *
 * Sobre cada listado se pintaba el `summary` y el primer párrafo de la
 * `description` del contrato. La intención era buena —una pestaña que se llama
 * «Duplicados» y enseña una caja de búsqueda no dice qué hace— pero nadie midió
 * cuántas veces no añadía nada. Medido el 01-11-2026 sobre los 13 contratos de
 * esta instalación: **62 de 214** resúmenes repetían el nombre de la pestaña
 * que está tres centímetros más arriba, y **131 de 835** descripciones eran
 * plantilla generada.
 *
 * En «Cuentas y contactos» caían las dos a la vez: debajo del título «Cuentas»
 * ponía «Listar cuentas», y debajo «Paginación por cursor: estable aunque se
 * creen o borren filas entre páginas» — la estrategia de paginación, a un
 * comercial, ocupando 50 px de los 476 que había que bajar para ver un dato.
 *
 * Esto NO se vigila con una lista de frases prohibidas: la plantilla siguiente
 * entra por donde la lista no mira. Las dos señales son estructurales, y lo que
 * se prueba aquí es que siguen siéndolo.
 */

import { describe, expect, it } from "vitest";

import { propositoDe } from "@/lib/contrato";

/** Un contrato de mentira con lo justo para que la regla tenga qué mirar. */
function contrato(
  operaciones: Record<string, { summary?: string; description?: string }>,
): Parameters<typeof propositoDe>[0] {
  const paths: Record<string, Record<string, unknown>> = {};
  for (const [ruta, op] of Object.entries(operaciones)) paths[ruta] = { get: op };
  return { paths } as Parameters<typeof propositoDe>[0];
}

describe("el resumen que repite el rótulo de la pestaña", () => {
  it("no se pinta, aunque lleve un verbo delante", () => {
    const doc = contrato({ "/cuentas": { summary: "Listar cuentas" } });
    expect(propositoDe(doc, "/cuentas", "get", "Cuentas").resumen).toBe("");
  });

  it("tampoco cuando sólo coincide la raíz de la palabra", () => {
    // «Listar migraciones de aislamiento» bajo «Migraciones de aislamiento».
    const doc = contrato({ "/m": { summary: "Listar migraciones de aislamiento" } });
    expect(propositoDe(doc, "/m", "get", "Migraciones de aislamiento").resumen).toBe("");
  });

  it("ni cuando el rótulo dice MÁS que el resumen", () => {
    // La pestaña «Encargos: cumplimiento por proveedor» ya contiene entero el
    // resumen «Cumplimiento por proveedor».
    const doc = contrato({ "/e": { summary: "Cumplimiento por proveedor" } });
    expect(
      propositoDe(doc, "/e", "get", "Encargos: cumplimiento por proveedor").resumen,
    ).toBe("");
  });

  it("y el que SÍ aporta se queda entero", () => {
    const doc = contrato({
      "/t": { summary: "Lo prometido a este tenant, y lo medido al lado" },
    });
    expect(propositoDe(doc, "/t", "get", "Compromisos").resumen).toBe(
      "Lo prometido a este tenant, y lo medido al lado",
    );
  });

  it("sin rótulo no se esconde nada: es la pantalla la que decide comparar", () => {
    const doc = contrato({ "/cuentas": { summary: "Listar cuentas" } });
    expect(propositoDe(doc, "/cuentas", "get").resumen).toBe("Listar cuentas");
  });
});

describe("la descripción que el contrato repite", () => {
  // La misma frase cambiando sólo el nombre de la entidad: es lo que genera
  // una plantilla, y es exactamente lo que había en el contrato de tenancy.
  const plantilla = (que: string) =>
    `Paginado por cursor. Devuelve ${que} del tenant en curso, de lo más reciente a lo más antiguo.`;

  it("no se pinta cuando aparece en tres sitios del mismo contrato", () => {
    const doc = contrato({
      "/a": { summary: "A", description: plantilla("declaraciones de aislamiento") },
      "/b": { summary: "B", description: plantilla("residencias del dato") },
      "/c": { summary: "C", description: plantilla("reglas de convivencia") },
    });
    expect(propositoDe(doc, "/a", "get", "A").detalle).toBe("");
  });

  it("pero sí cuando sólo hay dos pantallas hermanas que la comparten", () => {
    // Dos pueden compartir una explicación legítima. Cinco, no.
    const doc = contrato({
      "/a": { summary: "A", description: plantilla("declaraciones de aislamiento") },
      "/b": { summary: "B", description: plantilla("residencias del dato") },
    });
    expect(propositoDe(doc, "/a", "get", "A").detalle).not.toBe("");
  });

  it("y la escrita a mano se queda aunque el contrato tenga plantilla al lado", () => {
    const aMano =
      "Los rechazos importan tanto como las ejecuciones: muchos por permisos " +
      "significan que el catálogo y lo que el agente puede no coinciden.";
    const doc = contrato({
      "/a": { summary: "A", description: plantilla("declaraciones") },
      "/b": { summary: "B", description: plantilla("residencias") },
      "/c": { summary: "C", description: plantilla("reglas") },
      "/d": { summary: "Qué han hecho los agentes", description: aMano },
    });
    expect(propositoDe(doc, "/d", "get", "Agentes: uso").detalle).toBe(aMano);
  });

  it("una frase corta no se juzga: no hay suficiente para distinguirla", () => {
    const doc = contrato({
      "/a": { summary: "A", description: "En vivo." },
      "/b": { summary: "B", description: "En vivo." },
      "/c": { summary: "C", description: "En vivo." },
    });
    expect(propositoDe(doc, "/a", "get", "A").detalle).toBe("En vivo.");
  });
});
