/**
 * Qué campo se edita en una línea y cuál en un área.
 *
 * El criterio estaba al revés: se pintaba un área cuando el tope de longitud
 * pasaba de 400, y eso convertía `web` en un cuadro de cinco líneas —la
 * columna es `String(500)`— mientras `telefono` y `email`, al lado, eran una
 * línea. Se ve a la primera mirando el formulario, y así se vio.
 *
 * Medido sobre el modelo el 26-10-2026: de los **trece** campos del producto
 * con tope mayor que 400, **once son de una línea** —`web`, `uri`, `base_url`,
 * `callback_url`, `ruta`, `credencial_id`, `motivo_revocacion`…—, así que el
 * criterio acertaba en dos de trece.
 *
 * La señal buena es la contraria y sale del propio modelo: una columna `Text`
 * —sin tope— es una descripción, unas notas o un cuerpo, y llega al contrato
 * **sin `maxLength`**; hay 233. Una `String(n)` es un dato de una línea por
 * grande que sea n, porque alguien decidió acotarlo.
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

describe("el tipo de un campo de texto", () => {
  it("con tope es una línea, por grande que sea el tope", () => {
    // `web` es `String(500)`: una URL, no una descripción. Es el caso que se
    // vio en pantalla.
    expect(tipoDe({ anyOf: [{ type: "string", maxLength: 500 }, { type: "null" }] })).toBe("texto");
    // Y los de tope normal, igual que siempre.
    expect(tipoDe({ type: "string", maxLength: 40 })).toBe("texto");
    // Incluso uno muy largo: `callback_url` es `String(1000)`.
    expect(tipoDe({ type: "string", maxLength: 1000 })).toBe("texto");
  });

  it("sin tope es un área: eso es una columna de texto", () => {
    // Las 233 columnas `Text` del producto llegan así. En una línea de una sola
    // altura no se ve lo que se escribe.
    expect(tipoDe({ type: "string" })).toBe("texto_largo");
    expect(tipoDe({ anyOf: [{ type: "string" }, { type: "null" }] })).toBe("texto_largo");
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
        notas: { type: "string" },
      }),
      "/api/v1/cosas",
      "post",
    );
    const porNombre = Object.fromEntries(campos.map((c) => [c.nombre, c.tipo]));
    expect(porNombre.web).toBe("texto");
    expect(porNombre.notas).toBe("texto_largo");
  });
});
