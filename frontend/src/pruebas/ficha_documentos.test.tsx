/**
 * El panel de aprobación de un documento, PINTADO.
 *
 * Es el mismo componente que usa la pantalla de aprobaciones, a propósito: dos
 * implementaciones de lo mismo acaban discrepando justo en el matiz que
 * importa. Aquí se comprueba que en la ficha enseña lo que debe.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AprobacionDeDocumento } from "@/paginas/Aprobaciones";

let respuestas: Record<string, unknown> = {};

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => {
    const clave = Object.keys(respuestas)
      .filter((k) => ruta.startsWith(k))
      .sort((a, b) => b.length - a.length)[0];
    if (!clave) throw new Error(`sin respuesta preparada para ${ruta}`);
    return { datos: respuestas[clave] };
  }),
  salvoCancelacion: (fn: (e: unknown) => void) => fn,
}));

vi.mock("@/lib/permisos", () => ({ usePuedeOperar: () => () => true }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

describe("el panel de aprobación de un documento", () => {
  beforeEach(() => {
    respuestas = {};
  });

  it("enseña el estado del documento en el gestor, con sus avisos", async () => {
    respuestas = {
      "/api/v1/documentos/ficha/d1": {
        status: "ready",
        mime_type: "application/pdf",
        partial_warnings: [{ que: "tablas" }, { que: "figuras" }],
      },
      "/api/v1/documentos/aprobacion/d1": {
        control_state: "draft",
        current_version_no: 2,
        puedo_pedir: true,
        solicitud: null,
      },
      "/api/v1/documentos/aprobaciones/flujos": { items: [] },
    };
    render(<AprobacionDeDocumento documentoId="d1" />);
    // Que se indexó CON AVISOS se dice: «indexado» a secas cuando faltan la
    // mitad de las tablas hace creer que la búsqueda lo encuentra todo.
    expect(await screen.findByText(/aprobaciones\.conAvisos/)).toBeInTheDocument();
  });

  it("si el flujo exige aprobadores, no deja pedirla sin decir quiénes", async () => {
    respuestas = {
      "/api/v1/documentos/ficha/d2": { status: "ready" },
      "/api/v1/documentos/aprobacion/d2": {
        control_state: "draft",
        current_version_no: 1,
        puedo_pedir: true,
        solicitud: null,
      },
      "/api/v1/documentos/aprobaciones/flujos": {
        items: [{ id: "f1", name: "Contratos", exige_aprobadores: true }],
      },
    };
    const { default: userEvent } = await import("@testing-library/user-event");
    render(<AprobacionDeDocumento documentoId="d2" />);

    const flujo = await screen.findByLabelText(/aprobaciones\.flujo/);
    await userEvent.selectOptions(flujo, "f1");

    expect(screen.getByRole("button", { name: /aprobaciones\.pedir/ })).toBeDisabled();
    expect(screen.getByText(/aprobaciones\.faltanAprobadores/)).toBeInTheDocument();
  });

  it("con una aprobación en curso lo dice y no ofrece pedir otra", async () => {
    respuestas = {
      "/api/v1/documentos/ficha/d3": { status: "ready" },
      "/api/v1/documentos/aprobacion/d3": {
        control_state: "in_review",
        current_version_no: 3,
        puedo_pedir: true,
        solicitud: { id: "s1", status: "pending" },
      },
      "/api/v1/documentos/aprobaciones/flujos": { items: [] },
    };
    render(<AprobacionDeDocumento documentoId="d3" />);
    expect(await screen.findByText(/aprobaciones\.enCurso/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /aprobaciones\.pedir/ })).toBeNull();
  });
});
