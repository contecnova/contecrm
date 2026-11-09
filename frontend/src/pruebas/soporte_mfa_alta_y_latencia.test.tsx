/**
 * Cinco capacidades que estaban servidas a medias y ahora tienen su sitio
 * (CRM-00.02.04.07, CRM-00.05.01.06, CRM-00.01.07.02, CRM-08.01.01.01,
 * CRM-00.01.02.06).
 *
 * Lo que se fija es lo que el tipado no ve:
 *
 * - el identificador de la petición **llega a la pantalla de error** y se puede
 *   copiar, venga en el cuerpo o sólo en la cabecera;
 * - la MFA por rol se guarda con los roles elegidos, y lo que se enseña
 *   después es lo que dice el servidor —cuántos se quedarían fuera—;
 * - el alta en cascada enseña el estado de CADA herramienta, también la que
 *   falló, y el resumen se cuenta sobre ese estado;
 * - la latencia por operación pinta lo medido frente a su objetivo, con el N;
 * - salir de la suplantación cierra la de soporte ANTES de renovar la propia.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Error as Fallo } from "@/componentes/Estados";
import { ErrorApi, problema } from "@/lib/api";
import { volverASesionPropia } from "@/lib/sesion";
import { LatenciaPorOperacion, type Slo } from "@/paginas/Estado";
import { ExigirPorRol } from "@/paginas/Seguridad";
import { AltaEnCascada } from "@/paginas/Suite";

let respuestas: Record<string, unknown> = {};
const llamadas: { ruta: string; metodo?: string; cuerpo?: unknown }[] = [];

vi.mock("@/lib/api", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...real,
    llamar: vi.fn(
      async (
        ruta: string,
        opciones?: { metodo?: string; cuerpo?: unknown },
      ) => {
        llamadas.push({
          ruta,
          metodo: opciones?.metodo,
          cuerpo: opciones?.cuerpo,
        });
        const clave = Object.keys(respuestas)
          .filter((k) => ruta.startsWith(k))
          .sort((a, b) => b.length - a.length)[0];
        if (!clave) throw new Error(`sin respuesta preparada para ${ruta}`);
        return { datos: respuestas[clave] };
      },
    ),
    salvoCancelacion: (fn: (e: unknown) => void) => fn,
  };
});

vi.mock("@/lib/permisos", () => ({ usePuedeOperar: () => () => true }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

beforeEach(() => {
  respuestas = {};
  llamadas.length = 0;
});

describe("el identificador de la petición", () => {
  it("sale del cuerpo y, si no lo trae, de la cabecera", () => {
    expect(
      problema(500, { request_id: "del-cuerpo" }, "de-cabecera").requestId,
    ).toBe("del-cuerpo");
    expect(problema(502, { detail: "proxy" }, "uno, otro").requestId).toBe(
      "uno",
    );
  });

  it("se ve en la pantalla de error y se puede copiar", async () => {
    const copiar = vi.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText: copiar } });
    const error = new ErrorApi(404, "x", "No", null, "", [], "01a1-peticion");
    render(<Fallo error={error} />);
    expect(screen.getByText("01a1-peticion")).toBeTruthy();
    await userEvent.click(
      screen.getByRole("button", { name: /errores.copiar/ }),
    );
    expect(copiar).toHaveBeenCalledWith("01a1-peticion");
  });
});

describe("MFA obligatoria por rol", () => {
  it("guarda los roles elegidos y enseña lo que devuelve el servidor", async () => {
    respuestas = {
      "/api/v1/factores/obligatoria-por-rol": {
        mfa_obligatoria_roles: ["admin"],
        exigida_sin_factor: 2,
      },
    };
    const alGuardar = vi.fn();
    render(
      <ExigirPorRol
        exigidos={[]}
        disponibles={["admin", "comercial"]}
        puedeCambiar
        alGuardar={alGuardar}
      />,
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "seguridad.mfa.anadirRol" }),
      "admin",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "seguridad.mfa.guardar" }),
    );
    await waitFor(() => expect(alGuardar).toHaveBeenCalled());
    const put = llamadas.find((l) => l.metodo === "PUT");
    expect(put?.ruta).toBe("/api/v1/factores/obligatoria-por-rol");
    expect(put?.cuerpo).toEqual({ roles: ["admin"] });
    expect(alGuardar.mock.calls[0]?.[0]).toMatchObject({
      exigida_sin_factor: 2,
    });
  });
});

describe("alta del tenant en cascada", () => {
  it("dice en qué quedó cada herramienta, también la que falló", async () => {
    const fila = (
      herramienta: string,
      estado: string,
      error: string | null,
    ) => ({
      herramienta,
      activa: true,
      estado,
      intentos: estado === "sin_alta" ? 0 : 1,
      ultimo_error: error,
      aplicado_at: null,
      reintentar_at: null,
    });
    respuestas = {
      "/api/v1/suite/provisionar/tenant": {
        sin_herramientas: false,
        estado: [
          fila("contecmind", "aplicado", null),
          fila("contecintelligence", "fallido", "Connection refused"),
        ],
      },
    };
    render(<AltaEnCascada alTerminar={() => undefined} />);
    await userEvent.click(
      await screen.findByRole("button", { name: "suite.alta.boton" }),
    );
    await waitFor(() =>
      expect(
        llamadas.some(
          (l) => l.metodo === "POST" && l.ruta.endsWith("?aplicar=true"),
        ),
      ).toBe(true),
    );
    expect(await screen.findByText("Connection refused")).toBeTruthy();
    expect(
      screen.getByText(
        `suite.alta.resumen:${JSON.stringify({ aplicadas: 1, fallidas: 1, total: 2 })}`,
      ),
    ).toBeTruthy();
  });
});

describe("latencia por tipo de operación", () => {
  it("pinta p95 y p99 frente a su objetivo y marca las pocas muestras", () => {
    const op = {
      operacion: "lectura",
      peticiones: 12,
      medible: true,
      pocas_muestras: true,
      p95_ms: 640,
      p95_por_encima_de_ms: null,
      p99_ms: null,
      p99_por_encima_de_ms: 60000,
      objetivo_p95_ms: 500,
      objetivo_p99_ms: 1500,
      cumple_p95: false,
      cumple_p99: false,
    };
    const slo = {
      tier: "estandar",
      servicios_medibles: 1,
      sin_medicion: [],
      presupuesto_agotado_en: [],
      se_puede_desplegar: true,
      que_significa: "",
      servicios: [
        {
          servicio: "party",
          objetivo_pct: 99.5,
          latencia_objetivo_ms: 2000,
          presupuesto_minutos: 216,
          operaciones: [op],
        },
      ],
      operaciones: [op],
    } as Slo;
    render(<LatenciaPorOperacion slo={slo} />);
    expect(
      screen.getByText(`estado.latencia.ms:${JSON.stringify({ ms: 640 })}`),
    ).toBeTruthy();
    expect(
      screen.getByText(
        `estado.latencia.masDe:${JSON.stringify({ ms: 60000 })}`,
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        `estado.latencia.objetivo:${JSON.stringify({ ms: 500 })}`,
      ),
    ).toBeTruthy();
    expect(screen.getByText("estado.latencia.pocas")).toBeTruthy();
  });
});

describe("salir de la suplantación", () => {
  it("cierra la de soporte antes de renovar la propia", async () => {
    respuestas = { "/api/v1/sesion/": {} };
    const ir = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign: ir },
      writable: true,
    });
    await volverASesionPropia();
    expect(llamadas.map((l) => l.ruta)).toEqual([
      "/api/v1/sesion/volver",
      "/api/v1/sesion/renovar",
    ]);
    expect(ir).toHaveBeenCalledWith("/");
  });
});
