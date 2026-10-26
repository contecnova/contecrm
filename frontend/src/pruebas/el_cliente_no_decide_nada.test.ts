/**
 * Lo que el cliente hace y lo que no decide (CRM-07.04.02).
 *
 * La regla de este front es que **no decide**: pinta lo que declaran la
 * superficie, los permisos efectivos y las políticas del servidor. Si decidiera
 * él, bastaría con abrir las herramientas del navegador para «concederse» una
 * acción.
 *
 * Lo que se fija aquí son las cuatro cosas del cliente que, si fallan, no se
 * notan hasta que ya ha pasado algo:
 *
 *   · **la clave de idempotencia** (CRM-07.04.02.06): sin ella, un botón
 *     pulsado dos veces —o una red lenta y un reintento— crean dos registros,
 *     y el segundo se descubre semanas después en un informe descuadrado;
 *   · **el `If-Match`**: dos personas editando el mismo registro, y la segunda
 *     pisa a la primera sin que ninguna se entere;
 *   · **la sesión en cookie y nunca en un almacén que pueda leer un script**
 *     (CRM-07.04.02.03): un XSS con el token en `localStorage` es una sesión
 *     robada;
 *   · y que un error del servidor **llegue con su explicación** y no como «ha
 *     fallado algo» (CRM-07.04.01.07): el `Problem Details` trae el motivo, y
 *     perderlo convierte cada incidencia en una llamada a soporte.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorApi, llamar } from "@/lib/api";

type Llamada = { url: string; init: RequestInit };

let llamadas: Llamada[] = [];

function responder(cuerpo: unknown, estado = 200, cabeceras: Record<string, string> = {}) {
  return vi.fn(async (url: string, init: RequestInit) => {
    llamadas.push({ url, init });
    return {
      ok: estado < 400,
      status: estado,
      headers: new Headers(cabeceras),
      text: async () => (cuerpo === undefined ? "" : JSON.stringify(cuerpo)),
    } as unknown as Response;
  });
}

beforeEach(() => {
  llamadas = [];
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function cabecerasDe(i: number): Record<string, string> {
  return (llamadas[i]?.init.headers ?? {}) as Record<string, string>;
}

describe("las escrituras", () => {
  it("llevan clave de idempotencia, y cada una la suya", async () => {
    // Sin ella, un botón pulsado dos veces crea dos registros y el segundo se
    // descubre semanas después, en un informe que no cuadra.
    vi.stubGlobal("fetch", responder({ id: "1" }, 201));
    await llamar("/api/v1/cosas", { metodo: "POST", cuerpo: { a: 1 } });
    await llamar("/api/v1/cosas", { metodo: "POST", cuerpo: { a: 2 } });

    const una = cabecerasDe(0)["Idempotency-Key"];
    const otra = cabecerasDe(1)["Idempotency-Key"];
    expect(una).toBeTruthy();
    expect(otra).toBeTruthy();
    // Dos altas distintas son dos claves distintas: con la misma, la segunda
    // se tomaría por un reintento de la primera y no se crearía nada.
    expect(una).not.toBe(otra);
  });

  it("la clave se puede fijar, para que un reintento sea un reintento", async () => {
    // Es la otra mitad: quien reintenta a propósito manda la misma clave, y el
    // servidor devuelve lo que ya hizo en vez de hacerlo otra vez.
    vi.stubGlobal("fetch", responder({ id: "1" }, 201));
    await llamar("/api/v1/cosas", { metodo: "POST", cuerpo: {}, idempotencia: "la-misma" });
    await llamar("/api/v1/cosas", { metodo: "POST", cuerpo: {}, idempotencia: "la-misma" });
    expect(cabecerasDe(0)["Idempotency-Key"]).toBe("la-misma");
    expect(cabecerasDe(1)["Idempotency-Key"]).toBe("la-misma");
  });

  it("una lectura no lleva clave de idempotencia", async () => {
    // Ponerla en un `GET` no rompe nada y es ruido: la clave significa «esto
    // escribe», y usarla donde no escribe le quita el significado.
    vi.stubGlobal("fetch", responder([]));
    await llamar("/api/v1/cosas");
    expect(cabecerasDe(0)["Idempotency-Key"]).toBeUndefined();
  });

  it("la versión que se edita viaja como If-Match", async () => {
    // Dos personas editando el mismo registro: sin esto, la segunda pisa a la
    // primera y ninguna se entera.
    vi.stubGlobal("fetch", responder({ id: "1" }));
    await llamar("/api/v1/cosas/1", { metodo: "PATCH", cuerpo: {}, version: 'W/"3"' });
    expect(cabecerasDe(0)["If-Match"]).toBe('W/"3"');
  });

  it("y la versión vuelve del ETag, para poder editar lo que se acaba de leer", async () => {
    vi.stubGlobal("fetch", responder({ id: "1" }, 200, { ETag: 'W/"7"' }));
    const r = await llamar("/api/v1/cosas/1");
    expect(r.version).toBe('W/"7"');
  });
});

describe("la sesión", () => {
  it("va en cookie y no en un almacén que pueda leer un script", async () => {
    // Un XSS con el token en `localStorage` es una sesión robada; con cookie
    // `HttpOnly`, no. Lo que se comprueba es que las peticiones manden las
    // credenciales del navegador y que no haya token en ninguna cabecera.
    vi.stubGlobal("fetch", responder([]));
    await llamar("/api/v1/cosas");
    expect(llamadas[0]?.init.credentials).toBe("include");
    expect(JSON.stringify(cabecerasDe(0))).not.toMatch(/Authorization|Bearer/i);
  });
});

describe("un error del servidor", () => {
  it("llega con su explicación, no como «ha fallado algo»", async () => {
    // El `Problem Details` trae el motivo y el código estable. Perderlo por el
    // camino convierte cada incidencia en una llamada a soporte.
    vi.stubGlobal(
      "fetch",
      responder(
        {
          title: "Datos no válidos",
          detail: "El NIF no es válido",
          status: 422,
          error_code: "party.nif_invalido",
        },
        422,
      ),
    );
    await expect(llamar("/api/v1/cosas", { metodo: "POST", cuerpo: {} })).rejects.toThrow(ErrorApi);

    try {
      await llamar("/api/v1/cosas", { metodo: "POST", cuerpo: {} });
    } catch (e) {
      const fallo = e as ErrorApi;
      expect(fallo.estado).toBe(422);
      // El código estable, que es con lo que una pantalla decide qué hacer: por
      // el estado no vale, porque 409 lo usan tres cosas distintas que no se
      // arreglan igual.
      expect(fallo.codigo).toBe("party.nif_invalido");
      // Y **la frase del servidor**, aparte del título. El título es genérico
      // —«Datos no válidos» no dice qué dato— y la explicación es lo
      // accionable: es lo que pinta el componente de error.
      expect(fallo.explicacion).toContain("NIF");
      expect(fallo.titulo).toBe("Datos no válidos");
    }
  });

  it("un cuerpo que no es JSON no se traga el error", async () => {
    // Un 502 de un proxy devuelve HTML. Si eso reventara al parsear, lo que se
    // vería es un error del cliente en vez del del servidor, y se buscaría en
    // el sitio equivocado.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return {
          ok: false,
          status: 502,
          headers: new Headers(),
          text: async () => "<html>Bad Gateway</html>",
        } as unknown as Response;
      }),
    );
    await expect(llamar("/api/v1/cosas")).rejects.toThrow(ErrorApi);
  });
});

// ── CRM-07.04.02.05 · La interfaz no decide permisos ─────────────────────

describe("la interfaz no decide permisos", () => {
  it("lee los permisos efectivos que le da el servidor", async () => {
    // Si decidiera ella, bastaría con abrir las herramientas del navegador para
    // «concederse» una acción. Lo que hace es LEER lo que el servidor declara,
    // y el servidor vuelve a comprobarlo en cada llamada.
    const { puede } = await import("@/lib/sesion");
    const sesion = { permisos: ["cuenta:read"] } as never;
    expect(puede(sesion, "cuenta:read")).toBe(true);
    expect(puede(sesion, "cuenta:write")).toBe(false);
  });

  it("entiende los comodines igual que el servidor", async () => {
    // Si los entendiera distinto, la pantalla ofrecería acciones que el
    // servidor rechaza —o escondería las que sí puede—, y las dos cosas se
    // leen como que el producto va mal.
    const { puede } = await import("@/lib/sesion");
    expect(puede({ permisos: ["*:*"] } as never, "lo-que-sea:write")).toBe(true);
    expect(puede({ permisos: ["cuenta:*"] } as never, "cuenta:write")).toBe(true);
    expect(puede({ permisos: ["*:read"] } as never, "cuenta:read")).toBe(true);
    expect(puede({ permisos: ["cuenta:*"] } as never, "oportunidad:write")).toBe(false);
  });

  it("sin sesión no se puede nada, y sin permiso declarado no se pide nada", async () => {
    // Lo segundo importa: una acción que no declara permiso es pública dentro
    // del producto, y tratarla como prohibida la escondería para todos.
    const { puede } = await import("@/lib/sesion");
    expect(puede(null, "cuenta:read")).toBe(false);
    expect(puede(null, null)).toBe(true);
  });
});

// ── CRM-07.04.02.04 · Cabeceras de seguridad ─────────────────────────────

describe("las cabeceras del front", () => {
  it("la CSP no admite eval ni estilos en línea", async () => {
    // `unsafe-eval` y `unsafe-inline` son las dos puertas por las que un XSS
    // deja de ser un susto y pasa a ejecutar: con ellas, la CSP está puesta y
    // no protege, que es peor que no tenerla porque tranquiliza.
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    // Desde la raíz del proyecto: en el entorno de pruebas `import.meta.url` no
    // es una URL de fichero y resolverlo contra ella revienta con un error que
    // no tiene nada que ver con lo que se mide.
    const conf = readFileSync(resolve(process.cwd(), "nginx.conf"), "utf-8");
    const linea = conf.split("\n").find((l) => l.includes("Content-Security-Policy")) ?? "";
    expect(linea).toBeTruthy();
    expect(linea).not.toContain("unsafe-eval");
    expect(linea).not.toContain("unsafe-inline");
    // Y lo que impide que a alguien le encajen la consola dentro de otra
    // página para robarle los clics.
    expect(linea).toContain("frame-ancestors 'none'");
    // Que un formulario no pueda enviarse a otro sitio es lo que evita que un
    // XSS se lleve lo que alguien acaba de escribir.
    expect(linea).toContain("form-action 'self'");
  });
});

describe("los campos que el servidor retiene", () => {
  it("se leen de la cabecera, para poder decir cuáles faltan", async () => {
    // Un registro al que le faltan campos por permisos no se pinta igual que
    // uno completo: sin esto, el usuario ve huecos y cree que el dato no está.
    vi.stubGlobal(
      "fetch",
      responder({ id: "1" }, 200, { "X-Campos-Retenidos": "facturacion, margen" }),
    );
    const r = await llamar("/api/v1/cosas/1");
    expect(r.retenidos).toEqual(["facturacion", "margen"]);
  });
});
