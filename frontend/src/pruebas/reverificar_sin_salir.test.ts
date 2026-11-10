/**
 * Volver a verificarse sin salir (CRM-00.05.01.18).
 *
 * Hasta el 10-11-2026 una operación sensible que pedía reverificar acababa en
 * un error sin camino. Ahora `llamar` pregunta al diálogo registrado y, si la
 * persona se verifica, repite la operación una vez con la misma clave de
 * idempotencia; si cancela, llega el error de siempre.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { ErrorApi, llamar, registrarReverificacion } from "@/lib/api";

function respuesta(estado: number, cuerpo: unknown): Response {
  return new Response(JSON.stringify(cuerpo), {
    status: estado,
    headers: { "Content-Type": "application/json" },
  });
}

const pideReverificar = {
  status: 403,
  error_code: "stepup.requerido",
  title: "Hace falta volver a verificarse",
};

describe("una operación sensible pide reverificar", () => {
  afterEach(() => {
    registrarReverificacion(null);
    vi.unstubAllGlobals();
  });

  it("se verifica, y la operación se repite una vez con la misma clave", async () => {
    const claves: (string | null)[] = [];
    let veces = 0;
    vi.stubGlobal("fetch", (_url: string, opciones?: RequestInit) => {
      claves.push(new Headers(opciones?.headers).get("Idempotency-Key"));
      veces += 1;
      return Promise.resolve(
        veces === 1
          ? respuesta(403, pideReverificar)
          : respuesta(201, { id: "k1" }),
      );
    });
    const pedir = vi.fn(() => Promise.resolve(true));
    registrarReverificacion(pedir);

    const r = await llamar<{ id: string }>("/api/v1/claves-api", {
      metodo: "POST",
      cuerpo: { nombre: "x" },
    });

    expect(r.datos.id).toBe("k1");
    expect(pedir).toHaveBeenCalledTimes(1);
    expect(veces).toBe(2);
    expect(claves[0]).toBeTruthy();
    expect(claves[1]).toBe(claves[0]);
  });

  it("si cancela, llega el error de siempre y no se repite", async () => {
    let veces = 0;
    vi.stubGlobal("fetch", () => {
      veces += 1;
      return Promise.resolve(respuesta(403, pideReverificar));
    });
    registrarReverificacion(() => Promise.resolve(false));

    await expect(
      llamar("/api/v1/claves-api", { metodo: "POST", cuerpo: {} }),
    ).rejects.toBeInstanceOf(ErrorApi);
    expect(veces).toBe(1);
  });
});
