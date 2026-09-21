/**
 * El único sitio por el que este front habla con el CRM (CRM-07.04.04.01).
 *
 * Tres promesas que no son de estilo: la idempotencia en las escrituras, el
 * control de concurrencia con `ETag`, y que el token de sesión **no pase por
 * ningún almacén que pueda leer un script**.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { ErrorApi, llamar } from "@/lib/api";

function respuesta(cuerpo: unknown, init: ResponseInit = {}) {
  return new Response(cuerpo === null ? null : JSON.stringify(cuerpo), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("escrituras", () => {
  it("toda escritura lleva clave de idempotencia", async () => {
    // Quien reintenta no es la persona: es el navegador, el móvil que recupera
    // cobertura o el usuario dando dos veces al botón.
    const fetchFalso = vi.fn().mockResolvedValue(respuesta({ id: "1" }));
    vi.stubGlobal("fetch", fetchFalso);

    await llamar("/api/v1/tenants", { metodo: "POST", cuerpo: { nombre: "ACME" } });

    const cabeceras = fetchFalso.mock.calls[0]![1].headers as Record<string, string>;
    expect(cabeceras["Idempotency-Key"]).toBeTruthy();
  });

  it("una lectura NO la lleva", async () => {
    const fetchFalso = vi.fn().mockResolvedValue(respuesta([]));
    vi.stubGlobal("fetch", fetchFalso);

    await llamar("/api/v1/tenants");

    const cabeceras = fetchFalso.mock.calls[0]![1].headers as Record<string, string>;
    expect(cabeceras["Idempotency-Key"]).toBeUndefined();
  });

  it("reintentar la misma operación reutiliza la clave", async () => {
    // Una respuesta nueva por llamada: un `Response` solo se puede leer una
    // vez, y reutilizarlo hace fallar la segunda por un motivo que no tiene
    // nada que ver con lo que se está comprobando.
    const fetchFalso = vi.fn().mockImplementation(async () => respuesta({ id: "1" }));
    vi.stubGlobal("fetch", fetchFalso);

    await llamar("/api/v1/tenants", { metodo: "POST", idempotencia: "k-1" });
    await llamar("/api/v1/tenants", { metodo: "POST", idempotencia: "k-1" });

    const claves = fetchFalso.mock.calls.map(
      (c) => (c[1].headers as Record<string, string>)["Idempotency-Key"],
    );
    expect(claves).toEqual(["k-1", "k-1"]);
  });

  it("la versión que se edita viaja en If-Match", async () => {
    const fetchFalso = vi.fn().mockResolvedValue(respuesta({ id: "1" }));
    vi.stubGlobal("fetch", fetchFalso);

    await llamar("/api/v1/tenants/1", { metodo: "PATCH", version: '"v3"' });

    const cabeceras = fetchFalso.mock.calls[0]![1].headers as Record<string, string>;
    expect(cabeceras["If-Match"]).toBe('"v3"');
  });
});

describe("la sesión no pasa por el almacenamiento del navegador", () => {
  it("las llamadas van con la cookie, no con una cabecera guardada", async () => {
    // Un XSS con el token en `localStorage` es una sesión robada; con cookie
    // `HttpOnly`, no. Por eso `credentials` y ninguna cabecera de autorización.
    const fetchFalso = vi.fn().mockResolvedValue(respuesta([]));
    vi.stubGlobal("fetch", fetchFalso);

    await llamar("/api/v1/tenants");

    const opciones = fetchFalso.mock.calls[0]![1];
    expect(opciones.credentials).toBe("include");
    expect((opciones.headers as Record<string, string>).Authorization).toBeUndefined();
  });
});

describe("errores", () => {
  it("un Problem Details se convierte en un error con código", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        respuesta(
          { title: "Una política de acceso lo impide", error_code: "abac.denegado", detalle: { politica: "p" } },
          { status: 403 },
        ),
      ),
    );

    const fallo = await llamar("/api/v1/tenants").catch((e) => e);
    expect(fallo).toBeInstanceOf(ErrorApi);
    expect(fallo.codigo).toBe("abac.denegado");
    expect(fallo.esPoliticaDeAcceso).toBe(true);
  });

  it("un 412 se reconoce como conflicto de versión", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuesta({}, { status: 412 })));
    const fallo = await llamar("/api/v1/tenants/1", { metodo: "PATCH" }).catch((e) => e);
    expect(fallo.esConflictoDeVersion).toBe(true);
  });

  it("un cuerpo que no es JSON no rompe el cliente", async () => {
    // Casi siempre es la página de error de un proxy por delante del gateway.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<html>502</html>", { status: 502, headers: { "Content-Type": "text/html" } }),
      ),
    );
    const fallo = await llamar("/api/v1/tenants").catch((e) => e);
    expect(fallo).toBeInstanceOf(ErrorApi);
    expect(fallo.estado).toBe(502);
  });
});

describe("lo que el servidor retiene", () => {
  it("los campos retenidos llegan a quien pinta", async () => {
    // Sin esto no se distingue «este campo está vacío» de «este campo no te lo
    // doy», y eso cambia lo que hace el usuario: rellenarlo o pedir acceso.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        respuesta([{ id: "1" }], {
          headers: {
            "Content-Type": "application/json",
            "X-Campos-Retenidos": "nif, telefono",
          },
        }),
      ),
    );
    const { retenidos } = await llamar("/api/v1/accounts");
    expect(retenidos).toEqual(["nif", "telefono"]);
  });
});
