/**
 * Un botón no enseña el código de la capacidad.
 *
 * Los resúmenes del contrato llevan a veces el identificador de la capacidad
 * que los respalda: «Comprobar un contenido antes de mandarlo
 * (CRM-02.04.01.03)». En el OpenAPI está bien —quien integra lo lee y la
 * trazabilidad lo cita—, y en un botón es ruido: a quien comprueba un
 * contenido, `CRM-02.04.01.03` no le dice nada y le ocupa media mitad del
 * rótulo.
 *
 * Se vio el 04-11-2026, el día que esos resúmenes salieron por primera vez
 * como botones de una pantalla de módulo. **Medido: 43 de 2.452 resúmenes lo
 * llevan.** Se quita al rotular y no en los servicios, justo para que el
 * código siga en el contrato.
 */

import { describe, expect, it } from "vitest";

import { comoRotulo } from "@/lib/formato";
import { accionesDeColeccion } from "@/lib/acciones";
import type { Superficie } from "@/lib/superficie";

describe("el rótulo de una operación", () => {
  it("quita el código de la capacidad, solo o en lista", () => {
    expect(comoRotulo("Comprobar un contenido antes de mandarlo (CRM-02.04.01.03)")).toBe(
      "Comprobar un contenido antes de mandarlo",
    );
    // Los que respaldan más de una capacidad, en sus dos formas.
    expect(comoRotulo("Planificar un cambio de modalidad (CRM-00.01.01.04, CRM-00.01.03.10)")).toBe(
      "Planificar un cambio de modalidad",
    );
    expect(comoRotulo("Declarar dónde vive un tipo de dato (CRM-00.01.05.01, .02)")).toBe(
      "Declarar dónde vive un tipo de dato",
    );
  });

  it("y no toca lo que no lo lleva", () => {
    // La regla general no se puede comer un paréntesis cualquiera: muchos
    // resúmenes los usan para aclarar, y quitarlos los dejaría a medias.
    expect(comoRotulo("Fijar un acuerdo de canal")).toBe("Fijar un acuerdo de canal");
    expect(comoRotulo("Abrir sesión como otro usuario (soporte)")).toBe(
      "Abrir sesión como otro usuario (soporte)",
    );
    expect(comoRotulo("")).toBe("");
    expect(comoRotulo(null)).toBe("");
  });

  it("y el botón que sale de la superficie ya viene limpio", () => {
    // Por donde se construye el botón de verdad, no sólo por el ayudante: el
    // rótulo se arma en `accionesDeColeccion`, y una regla escrita al lado que
    // nadie llama no quita nada de ninguna pantalla.
    const superficie = {
      operaciones: [
        {
          metodo: "POST",
          ruta: "/api/v1/reglas-contenido/comprobar",
          resumen: "Comprobar un contenido antes de mandarlo (CRM-02.04.01.03)",
          permiso: null,
          exige_cuerpo: true,
          exige_datos: false,
        },
      ],
      objetos: {},
    } as unknown as Superficie;

    const acciones = accionesDeColeccion(superficie, "/api/v1/reglas-contenido", () => true);
    expect(acciones).toHaveLength(1);
    expect(acciones[0]?.nombre).toBe("Comprobar un contenido antes de mandarlo");
  });
});
