/**
 * Qué campo se edita en una línea y cuál en un área.
 *
 * Dos criterios fallaron antes, los dos por decidir sobre `maxLength`, y los
 * dos se vieron en pantalla a la primera mirada:
 *
 *   · **«área cuando el tope pasa de 400»** convertía `web` en un cuadro de
 *     cinco líneas —la columna es `String(500)`— con `telefono` y `email` al
 *     lado en una sola. Medido: de los trece campos con tope mayor que 400,
 *     **once son de una línea**, así que acertaba en dos de trece.
 *   · **«área cuando NO hay tope»** convirtió casi todo el formulario en áreas:
 *     `nombre`, `apellidos`, `nombre_completo`, `tratamiento`… Medido el
 *     26-10-2026 sobre el contrato de `party`: de 402 propiedades de texto,
 *     **sólo 40 llevan `maxLength`, el 9 %**. Los esquemas de salida y los de
 *     actualización no lo propagan.
 *
 * La conclusión es que **`maxLength` no sirve para decidir esto**, porque casi
 * nunca está. Lo que decide es el nombre del campo, con una lista de raíces
 * medida sobre las 229 columnas `Text` del modelo —las que de verdad llevan
 * prosa— que cubre 193 de ellas, el 84 %. Y por defecto, una línea: un campo de
 * prosa en una línea molesta; un nombre de pila en un área de cinco líneas hace
 * el formulario inusable.
 *
 * Se prueba con las formas que el contrato manda de verdad, copiadas del
 * OpenAPI de `party`, no inventadas.
 */

import { describe, expect, it } from "vitest";

import { camposDe } from "@/lib/contrato";

/** Un contrato mínimo con el cuerpo de una operación de alta. */
function contratoCon(propiedades: Record<string, unknown>) {
  return {
    paths: {
      "/api/v1/cosas": {
        post: {
          requestBody: {
            content: { "application/json": { schema: { $ref: "#/components/schemas/Crear" } } },
          },
        },
      },
    },
    components: {
      schemas: {
        Crear: { type: "object", properties: propiedades, required: [] },
      },
    },
  } as never;
}

function tipoDe(propiedad: unknown): string {
  const campos = camposDe(contratoCon({ x: propiedad }), "/api/v1/cosas", "post");
  return campos[0]?.tipo ?? "";
}

function tipoDeCampo(nombre: string, propiedad: unknown): string {
  const campos = camposDe(contratoCon({ [nombre]: propiedad }), "/api/v1/cosas", "post");
  return campos[0]?.tipo ?? "";
}

describe("el tipo de un campo de texto", () => {
  it("por defecto es una línea, haya tope o no", () => {
    // **El caso que se vio en pantalla**: el formulario de contacto entero
    // —nombre, apellidos, nombre completo, tratamiento— en áreas de cinco
    // líneas, porque ninguno de esos esquemas lleva `maxLength`.
    for (const campo of ["nombre", "apellidos", "nombre_completo", "tratamiento", "cargo"]) {
      expect(tipoDeCampo(campo, { type: "string" }), campo).toBe("texto");
      expect(
        tipoDeCampo(campo, { anyOf: [{ type: "string" }, { type: "null" }] }),
        campo,
      ).toBe("texto");
    }
    // Y `web`, que es `String(500)`: una URL, no una descripción.
    expect(tipoDeCampo("web", { anyOf: [{ type: "string", maxLength: 500 }, { type: "null" }] })).toBe(
      "texto",
    );
    expect(tipoDeCampo("codigo", { type: "string", maxLength: 40 })).toBe("texto");
  });

  it("es un área cuando el nombre dice que ahí va prosa", () => {
    // Las raíces salen de medir las columnas `Text` del modelo, no de elegir a
    // ojo. En una línea de una sola altura no se ve lo que se escribe.
    for (const campo of [
      "descripcion",
      "notas",
      "cuerpo",
      "motivo",
      "motivo_rechazo",
      "observaciones",
      "causa_raiz",
      "detalle_tecnico",
    ]) {
      expect(tipoDeCampo(campo, { type: "string" }), campo).toBe("texto_largo");
    }
  });

  it("y también cuando el tope es grande de verdad", () => {
    // 1.000 o más es un motivo escrito, no un nombre. Es la única vez que
    // `maxLength` decide, y decide hacia el área.
    expect(tipoDeCampo("x", { type: "string", maxLength: 1000 })).toBe("texto_largo");
    expect(tipoDeCampo("x", { type: "string", maxLength: 999 })).toBe("texto");
  });

  it("un formato conocido manda sobre todo lo demás", () => {
    // Una fecha no es ni línea ni área: es un selector de fecha.
    expect(tipoDe({ type: "string", format: "date" })).toBe("fecha");
    expect(tipoDe({ type: "string", format: "date-time" })).toBe("fecha");
  });

  it("y los demás tipos siguen donde estaban", () => {
    // El control de que esto no haya tocado nada más al cambiar el criterio.
    expect(tipoDe({ type: "integer" })).toBe("numero");
    expect(tipoDe({ type: "boolean" })).toBe("booleano");
    expect(tipoDe({ type: "object" })).toBe("objeto");
    expect(tipoDe({ type: "array", items: { type: "string" } })).toBe("etiquetas");
    expect(tipoDe({ type: "array", items: { enum: ["a", "b"] } })).toBe("lista_multiple");
  });
});

describe("lo que ocupa el ancho entero", () => {
  it("un campo de una línea no se lleva las dos columnas", () => {
    // Era la otra mitad de lo mismo: `web` no sólo salía como área, sino
    // ocupando el formulario de lado a lado, con `telefono` y `email` debajo
    // en media columna cada uno. El ancho se da por el tipo, así que al
    // arreglar el tipo se arregla el ancho — y esto lo deja fijado.
    const campos = camposDe(
      contratoCon({
        web: { type: "string", maxLength: 500 },
        telefono: { type: "string" },
        notas: { type: "string" },
      }),
      "/api/v1/cosas",
      "post",
    );
    const porNombre = Object.fromEntries(campos.map((c) => [c.nombre, c.tipo]));
    expect(porNombre.web).toBe("texto");
    expect(porNombre.telefono).toBe("texto");
    expect(porNombre.notas).toBe("texto_largo");
  });
});
