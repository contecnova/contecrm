/**
 * «No has entrado» y «el sistema no responde» se leen igual y significan lo
 * contrario.
 *
 * Lo vio quien la usa, en la consola del navegador: `GET /api/v1/auth/me` →
 * **502**, y en pantalla el formulario de entrada como si nada. El arranque
 * se tragaba cualquier error y devolvía «no hay sesión», así que el gateway
 * caído, un contenedor reiniciándose o el túnel cortado salían exactamente
 * igual que no haber entrado: con su formulario, invitando a teclear una
 * contraseña en un sistema que no puede contestar. Y al enviarla, otro error
 * opaco — porque la contraseña no es lo que está mal.
 *
 * Son tres respuestas y antes eran dos.
 */

import { describe, expect, it, vi } from "vitest";

const llamar = vi.fn();
vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...real, llamar: (...args: unknown[]) => llamar(...args) };
});

const { cargarEntrada, cargarSesion } = await import("@/lib/sesion");
// `ErrorApi` DESPUÉS del mock y por importación dinámica: con el `import`
// estático de arriba, el módulo se evalúa antes de que el mock se registre y
// la prueba acaba con una clase distinta de la que ve `sesion.ts`. El
// `instanceof` de dentro daba falso y un 401 salía como «caído», que es lo
// contrario de lo que esta prueba defiende — y costó un rato verlo porque el
// fallo que enseñaba era el error escapándose, no la comparación.
const { ErrorApi } = await import("@/lib/api");

const YO = {
  usuario: { id: "u1", nombre: "Ana", email: "ana@example.com", es_plataforma: false },
  tenant_id: "t1",
  roles: ["comercial"],
  permisos: ["cuenta:read"],
  suplantado_por: null,
};

// **Sin `beforeEach` que limpie el espía, y es deliberado.** Cada prueba pone
// su propia implementación, así que no hay nada que arrastrar. Tanto
// `mockReset` como `mockClear` borran los resultados guardados del espía, y
// entre ellos están las promesas RECHAZADAS de la prueba anterior: al
// borrarlas sin que nadie las haya consumido, Vitest las cuenta como fallo de
// la prueba siguiente y señala la línea donde se construyó el error. Seis en
// rojo por la limpieza, no por el código — y el mensaje no se parecía en nada
// a la causa.

describe("qué se sabe de quién entra", () => {
  it("dentro, cuando el servidor contesta quién eres", async () => {
    llamar.mockResolvedValue({ datos: YO, version: null, retenidos: [] });
    const entrada = await cargarEntrada();
    expect(entrada.estado).toBe("dentro");
    if (entrada.estado === "dentro") {
      expect(entrada.sesion.email).toBe("ana@example.com");
      expect(entrada.sesion.permisos).toEqual(["cuenta:read"]);
    }
  });

  it("fuera, con 401: eso es la pantalla de entrada, no un error", async () => {
    llamar.mockRejectedValue(new ErrorApi(401, "auth.sin_sesion", "No autenticado", {}));
    expect((await cargarEntrada()).estado).toBe("fuera");
  });

  it("fuera también con 403", async () => {
    llamar.mockRejectedValue(new ErrorApi(403, "auth.prohibido", "Prohibido", {}));
    expect((await cargarEntrada()).estado).toBe("fuera");
  });

  it("CAÍDO con 502, que es lo que se vio en el navegador", async () => {
    // El caso que motivó todo esto. Antes salía como «fuera».
    llamar.mockRejectedValue(new ErrorApi(502, "gateway.sin_servicio", "Bad Gateway", {}));
    const entrada = await cargarEntrada();
    expect(entrada.estado).toBe("caido");
    if (entrada.estado === "caido") {
      // Y con el error dentro, para que la pantalla pueda decir qué pasó en vez
      // de un «algo ha ido mal» genérico.
      expect((entrada.error as InstanceType<typeof ErrorApi>).estado).toBe(502);
    }
  });

  it("y caído también con 503 y con un fallo de red", async () => {
    llamar.mockRejectedValue(new ErrorApi(503, "x", "No disponible", {}));
    expect((await cargarEntrada()).estado).toBe("caido");
    // Un fallo de red no llega como `ErrorApi`: llega como lo que lance `fetch`.
    llamar.mockRejectedValue(new TypeError("Failed to fetch"));
    expect((await cargarEntrada()).estado).toBe("caido");
  });

  it("un 500 del servidor tampoco es «no has entrado»", async () => {
    llamar.mockRejectedValue(new ErrorApi(500, "interno.no_previsto", "Error interno", {}));
    expect((await cargarEntrada()).estado).toBe("caido");
  });
});

describe("el envoltorio de siempre", () => {
  it("devuelve la sesión o nada, para quien ya está dentro", async () => {
    llamar.mockResolvedValue({ datos: YO, version: null, retenidos: [] });
    expect((await cargarSesion())?.email).toBe("ana@example.com");
    llamar.mockRejectedValue(new ErrorApi(502, "x", "Bad Gateway", {}));
    // Nada, no una excepción: las pantallas que ya están dentro recogen el
    // fallo en su propio estado, y obligarlas a distinguir las tres respuestas
    // sería repetir la misma decisión en cada una.
    expect(await cargarSesion()).toBeNull();
  });
});
