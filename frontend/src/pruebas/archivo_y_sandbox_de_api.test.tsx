/**
 * El archivo de histórico (CRM-07.03.01.02) y el sandbox de API
 * (CRM-00.02.01.15), pintados con la forma que manda el servidor.
 *
 * Lo que se fija:
 *
 * - Archivar manda la CLASE y `simular: false`, y simular manda `simular:
 *   true`: un botón que archiva cuando dice simular es el fallo caro.
 * - El criterio se guarda con PUT por clase, con los días tecleados.
 * - Lo archivado de un registro se pide por `relacionado_con` con su id, y un
 *   servicio sin archivo no pinta nada en la ficha.
 * - La consola llama con la clave del sandbox y SIN la sesión (`credentials:
 *   "omit"`): con la cookie delante se probaría como uno mismo, en la empresa
 *   real.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const llamadas: { ruta: string; opciones?: Record<string, unknown> }[] = [];
let respuestas: Record<string, unknown> = {};

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string, opciones?: Record<string, unknown>) => {
    llamadas.push({ ruta, opciones });
    const clave = Object.keys(respuestas)
      .sort((a, b) => b.length - a.length)
      .find((k) => ruta.includes(k));
    return { datos: clave ? respuestas[clave] : {} };
  }),
  filas: (d: unknown) =>
    Array.isArray(d) ? d : ((d as { items?: unknown[] })?.items ?? []),
  salvoCancelacion: (f: (e: unknown) => void) => f,
  ErrorApi: class extends Error {},
}));

vi.mock("@/lib/permisos", () => ({
  useSuperficie: () => ({ superficie: null, tiene: () => true }),
}));

vi.mock("@/lib/contrato", () => ({
  contratoDe: vi.fn(async () => ({
    paths: {
      "/api/v1/accounts": { get: {}, post: {} },
      "/api/v1/accounts/{cuenta_id}": { get: {}, patch: {} },
    },
  })),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, v?: Record<string, unknown>) =>
      v ? `${clave} ${JSON.stringify(v)}` : clave,
  }),
}));

import {
  ArchivadoDelRegistro,
  ArchivoDelServicio,
} from "@/componentes/Archivo";
import { SandboxDeApi } from "@/paginas/SandboxDeApi";

beforeEach(() => {
  llamadas.length = 0;
  respuestas = {};
});

describe("archivo de histórico", () => {
  it("simula, archiva por clase y guarda el criterio con PUT", async () => {
    respuestas = {
      "/volumen/archivo/clases": {
        hay_archivo: true,
        clases: [
          {
            clase: "actividades",
            descripcion: "Actividades completadas",
            tabla: "actividades",
            campo_fecha: "completada_at",
            dias: 730,
            corte: "2024-11-09",
            candidatas: 12,
          },
        ],
      },
      "/volumen/archivo/archivar": {
        clase: "actividades",
        candidatas: 12,
        archivadas: 12,
        simulado: false,
        bajo_bloqueo_legal: 0,
        corte: "2024-11-09",
      },
    };
    render(<ArchivoDelServicio servicio="party" puedeVer />);
    await screen.findByText("Actividades completadas");

    fireEvent.click(screen.getByRole("button", { name: "archivo.simular" }));
    await waitFor(() =>
      expect(
        llamadas.some(
          (l) =>
            l.ruta === "/api/v1/party/volumen/archivo/archivar" &&
            JSON.stringify(l.opciones?.cuerpo) ===
              JSON.stringify({ clase: "actividades", simular: true }),
        ),
      ).toBe(true),
    );

    fireEvent.click(screen.getByRole("button", { name: /archivo\.archivar/ }));
    await waitFor(() =>
      expect(
        llamadas.some(
          (l) =>
            l.ruta.endsWith("/archivo/archivar") &&
            JSON.stringify(l.opciones?.cuerpo) ===
              JSON.stringify({ clase: "actividades", simular: false }),
        ),
      ).toBe(true),
    );

    const dias = screen.getByRole("spinbutton");
    fireEvent.change(dias, { target: { value: "1095" } });
    fireEvent.click(
      screen.getByRole("button", { name: "archivo.guardarCriterio" }),
    );
    await waitFor(() =>
      expect(llamadas.find((l) => l.opciones?.metodo === "PUT")).toMatchObject({
        ruta: "/api/v1/party/volumen/archivo/clases/actividades",
        opciones: { cuerpo: { dias: 1095 } },
      }),
    );
  });

  it("lo archivado de un registro se pide por relacionado_con y se puede devolver", async () => {
    respuestas = {
      "/volumen/archivo?": {
        hay_archivo: true,
        cuantas: 1,
        hay_mas: false,
        filas: [
          {
            clase: "actividades",
            tabla: "actividades",
            registro_id: "a1",
            fecha_original: "2021-03-01T00:00:00Z",
            archivada_at: "2026-11-09T10:00:00Z",
            contenido: { asunto: "Llamada de 2021" },
          },
        ],
      },
    };
    render(<ArchivadoDelRegistro servicio="party" id="c-123" />);
    await screen.findAllByText("Llamada de 2021");
    expect(llamadas[0]?.ruta).toContain("relacionado_con=c-123");
    fireEvent.click(screen.getByRole("button", { name: /archivo\.devolver/ }));
    await waitFor(() =>
      expect(
        llamadas.some(
          (l) =>
            l.ruta === "/api/v1/party/volumen/desarchivar/a1" &&
            l.opciones?.metodo === "POST",
        ),
      ).toBe(true),
    );
  });

  it("un servicio sin archivo no pinta nada en la ficha", async () => {
    respuestas = {
      "/volumen/archivo?": { hay_archivo: false, filas: [], cuantas: 0 },
    };
    const { container } = render(
      <ArchivadoDelRegistro servicio="metadata" id="x" />,
    );
    await waitFor(() => expect(llamadas.length).toBe(1));
    expect(container.textContent).toBe("");
  });
});

describe("sandbox de API", () => {
  it("crea el sandbox, pone la clave en la consola y llama sin la sesión", async () => {
    respuestas = {
      "/api/v1/servicios": [{ servicio: "party" }],
      "/integracion/sandbox": {
        sandbox_id: "s1",
        tenant_sandbox_id: "t1",
        filas: 20,
        caduca_at: "2026-12-09T00:00:00Z",
        alcance: "Sólo el sandbox",
        objetos: [
          {
            objeto: "accounts",
            servicio: "party",
            creadas: 10,
            pedidas: 10,
            error: "",
          },
          {
            objeto: "contacts",
            servicio: "party",
            creadas: 10,
            pedidas: 10,
            error: "",
          },
        ],
        credencial: {
          secreto: "crm_secreto_de_prueba",
          prefijo: "crm_secreto",
        },
      },
    };
    const fetchFalso = vi.fn(
      async () => new Response(JSON.stringify({ items: [] }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchFalso);

    render(<SandboxDeApi />);
    fireEvent.click(
      screen.getByRole("button", { name: /sandboxApi\.crearBoton/ }),
    );
    await screen.findByText("crm_secreto_de_prueba");
    expect(
      llamadas.find((l) => l.ruta === "/api/v1/integracion/sandbox")?.opciones,
    ).toMatchObject({ metodo: "POST" });

    // La ruta se elige del contrato.
    const rutas = await screen.findByRole("combobox", {
      name: "sandboxApi.rutaDelContrato",
    });
    await screen.findByRole("option", { name: "/api/v1/accounts" });
    fireEvent.change(rutas, { target: { value: "/api/v1/accounts" } });
    fireEvent.click(screen.getByRole("button", { name: /sandboxApi\.enviar/ }));

    await waitFor(() => expect(fetchFalso).toHaveBeenCalled());
    const [url, init] = fetchFalso.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe("/api/v1/accounts");
    expect(init.credentials).toBe("omit");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer crm_secreto_de_prueba",
    );
    await screen.findByText(/sandboxApi\.respuesta/);
    vi.unstubAllGlobals();
  });
});
