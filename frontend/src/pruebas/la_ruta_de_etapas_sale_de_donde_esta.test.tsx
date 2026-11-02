/**
 * La ruta de etapas del panel de cabecera, y de dónde saca sus pasos.
 *
 * Es la pieza que define la ficha de una oportunidad en Salesforce: una etapa
 * suelta dice dónde estás; la ruta dice además cuánto queda y qué viene
 * después. Aquí se pintaba leyendo el contrato —una lista cerrada con al menos
 * tres valores— y eso dejaba fuera justo al objeto que la necesita:
 *
 * **Medido el 02-11-2026.** `EditarOportunidad` no declara `etapa`: la etapa se
 * cambia por un extremo aparte, con el identificador de una etapa del pipeline,
 * y los pipelines son configuración de cada tenant. Así que `campoDeEtapa` no
 * encontraba nada y la ficha de una oportunidad salía con «Etapa: Análisis
 * técnico» como un campo más, mientras el comentario de esa pantalla decía que
 * el panel pintaba la ruta.
 *
 * Desde hoy el panel acepta los pasos de quien los conoce, y los datos mandan
 * sobre el contrato: una lista configurada por el tenant es más concreta que
 * una lista cerrada del esquema.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

// El contrato no se usa en estas pruebas: lo que se mide es de dónde salen los
// pasos, y pedirlo metería una llamada que no cambia el resultado.
vi.mock("@/lib/contrato", () => ({
  contratoDe: () => Promise.resolve({}),
  camposDe: () => [],
  fichaDe: () => "",
}));

const RECURSO = {
  nombre: "Oportunidades",
  servicio: "sales",
  listar: "/api/v1/opportunities",
  columnas: ["etapa", "importe"],
} as never;

const PASOS = ["Cualificación", "Análisis técnico", "Oferta presentada"];

async function pintar(recorrido?: { campo: string; pasos: string[] }) {
  const { DatosClave } = await import("@/componentes/DatosClave");
  return render(
    <DatosClave
      recurso={RECURSO}
      tipo="oportunidad"
      nombre="Automatización de control de calidad"
      fila={{ etapa: "Análisis técnico", importe: "117693" }}
      recorrido={recorrido}
    />,
  );
}

describe("la ruta de etapas", () => {
  it("se pinta con los pasos que trae la pantalla", async () => {
    await pintar({ campo: "etapa", pasos: PASOS });
    const ruta = screen.getByRole("list", { name: /ficha\.ruta/ });
    expect(ruta).toBeInTheDocument();
    // Los tres pasos, y marcado el que toca.
    for (const paso of PASOS) {
      expect(screen.getByText(paso)).toBeInTheDocument();
    }
    expect(
      screen.getByText("Análisis técnico").closest("li"),
    ).toHaveAttribute("aria-current", "step");
  });

  it("la etapa no sale ADEMÁS como un dato clave suelto", async () => {
    // Si no, el mismo valor aparece dos veces en el mismo panel: una como
    // recorrido y otra como par etiqueta/valor debajo.
    await pintar({ campo: "etapa", pasos: PASOS });
    expect(screen.queryByText("Etapa")).toBeNull();
  });

  it("sin pasos no se inventa ninguna ruta", async () => {
    // Un pipeline que no se ha podido leer —sin permiso, o el servicio
    // caído— deja la ficha como estaba: la etapa como un dato más. Media
    // ruta es peor que ninguna.
    await pintar();
    expect(screen.queryByRole("list", { name: /ficha\.ruta/ })).toBeNull();
    expect(screen.getByText("Etapa")).toBeInTheDocument();
  });

  it("con menos de tres pasos tampoco: eso es un interruptor", async () => {
    await pintar({ campo: "etapa", pasos: ["Análisis técnico", "Ganada"] });
    expect(screen.queryByRole("list", { name: /ficha\.ruta/ })).toBeNull();
  });
});
