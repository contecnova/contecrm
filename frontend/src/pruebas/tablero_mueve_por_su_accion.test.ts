/**
 * El tablero «Por columnas» de Oportunidades no dejaba arrastrar (09-11-2026):
 * agrupa por `etapa` y la etapa se cambia con `POST …/etapa {etapa_id}`, no con
 * el PATCH. Al soltar hay que saber el `etapa_id` de la columna, y dos embudos
 * pueden tener etapas que se llaman igual.
 */
import { describe, expect, it } from "vitest";

import { idDeLaColumna } from "@/componentes/Vistas";

const fila = (
  id: string,
  etapa: string,
  etapa_id: string,
  pipeline_id: string,
) => ({
  id,
  etapa,
  etapa_id,
  pipeline: pipeline_id === "p1" ? "Ventas" : "Servicios",
  pipeline_id,
});

describe("el identificador de la columna a la que se suelta", () => {
  const filas = [
    fila("a", "Cualificación", "e1", "p1"),
    fila("b", "Negociación", "e2", "p1"),
    fila("c", "Negociación", "e9", "p2"),
  ];

  it("es el de la etapa de su mismo embudo", () => {
    expect(idDeLaColumna(filas, filas[0]!, "etapa", "Negociación")).toBe("e2");
  });

  it("no lo inventa si en su embudo no hay ninguna con ese nombre", () => {
    const otra = fila("d", "Cualificación", "e7", "p3");
    expect(
      idDeLaColumna([...filas, otra], otra, "etapa", "Negociación"),
    ).toBeNull();
  });
});
