/**
 * La IA de asistencia está en la ficha de lo suyo (auditoría 13-11-2026,
 * COB-2).
 *
 * El hallazgo decía que resumen de cuenta, próximos pasos, respuesta de
 * soporte, resumen de conversación y sentimiento no tenían pantalla. Medido el
 * 14-11-2026: las cinco rutas de `intelligence` (`/ia/asistencia/…` y
 * `/ia/conversacion/…`) **no se llaman desde el navegador a propósito**: piden
 * los hechos, las señales o los mensajes en el cuerpo, y reunirlos aquí sería
 * lógica de negocio en el front. Cada servicio dueño los reúne y las llama
 * desde una ruta del registro:
 *
 *   · `POST /accounts/{id}/resumen-ia`          (party → resumen-cuenta)
 *   · `POST /opportunities/{id}/proximos-pasos-ia` (sales → proximos-pasos)
 *   · `POST /casos/{id}/respuesta-sugerida`     (service → respuesta-soporte)
 *   · `POST /conversaciones/{id}/resumen-ia`    (service → conversacion/resumen)
 *   · `POST /conversaciones/{id}/intencion`     (service → conversacion/senal)
 *
 * Y esas, por ser `POST` sobre el registro con `ia:usar`, son las que
 * `<AsistenteIA>` enseña en la ficha. Esta prueba fija ese camino: si una deja
 * de salir en la ficha de su objeto, falla nombrándola.
 */
import { describe, expect, it } from "vitest";

import { esDeIA } from "@/componentes/AsistenteIA";
import { accionesDe } from "@/lib/acciones";
import type { Operacion, Superficie } from "@/lib/superficie";

function operacion(ruta: string, resumen: string): Operacion {
  return {
    metodo: "POST",
    ruta,
    resumen,
    etiquetas: [],
    permiso: "ia:usar",
    administracion: false,
    solo_plataforma: false,
    servicio: "",
  } as unknown as Operacion;
}

const SUPERFICIE = {
  operaciones: [
    operacion("/api/v1/accounts/{cuenta_id}/resumen-ia", "Resumir esta cuenta con IA"),
    operacion(
      "/api/v1/opportunities/{oportunidad_id}/proximos-pasos-ia",
      "Qué hacer ahora con esta oportunidad, y por qué",
    ),
    operacion(
      "/api/v1/casos/{caso_id}/respuesta-sugerida",
      "Sugerir una respuesta para este caso",
    ),
    operacion(
      "/api/v1/conversaciones/{conversacion_id}/resumen-ia",
      "Resumir esta conversación",
    ),
    operacion(
      "/api/v1/conversaciones/{conversacion_id}/intencion",
      "Qué quiere el cliente y cómo está",
    ),
  ],
} as unknown as Superficie;

const todo = () => true;

describe("la IA de asistencia sale en la ficha de su objeto", () => {
  it.each([
    ["/api/v1/accounts", "c1", ["resumen-ia"]],
    ["/api/v1/opportunities", "o1", ["proximos-pasos-ia"]],
    ["/api/v1/casos", "k1", ["respuesta-sugerida"]],
    ["/api/v1/conversaciones", "v1", ["intencion", "resumen-ia"]],
  ])("%s", (base, id, claves) => {
    const deIA = accionesDe(SUPERFICIE, base, id, todo).filter(esDeIA);
    expect(deIA.map((a) => a.clave).sort()).toEqual(claves);
    // Con el id del registro puesto: es la ruta que se llama.
    for (const a of deIA) expect(a.ruta).toContain(`/${id}/`);
  });

  it("sin el permiso no se ofrece", () => {
    expect(
      accionesDe(SUPERFICIE, "/api/v1/accounts", "c1", (p) => p !== "ia:usar"),
    ).toEqual([]);
  });
});
