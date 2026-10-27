/**
 * De quién son los datos que se están viendo.
 *
 * Hasta el 27-10-2026 la consola de plataforma no necesitaba decirlo porque
 * las pantallas de negocio enseñaban **todos los clientes a la vez**, sin
 * avisar: medido contra la instalación local, 97 de cada 100 cuentas eran de
 * otro cliente. Acotada la sesión al tenant propio, hace falta poder mirar el
 * de un cliente concreto — y que la pantalla diga cuál.
 *
 * Lo que fija esta prueba:
 *
 *   · el selector sólo sale a quien opera la plataforma;
 *   · la elección viaja en TODAS las llamadas. Con ella sólo en algunas, media
 *     pantalla hablaría de un cliente y la otra media del propio;
 *   · vive en la PESTAÑA (`sessionStorage`): recargar la mantiene —si no, cada
 *     F5 devolvería a mitad de trabajo— y cerrarla la olvida, que es lo
 *     correcto para algo que da acceso a datos de otro;
 *   · y mirar a otro se ve: va en color de aviso, porque es un estado del que
 *     hay que acordarse de salir.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

beforeEach(() => {
  sessionStorage.clear();
});

describe("qué cliente se está mirando", () => {
  it("la elección viaja en la cabecera de todas las llamadas", async () => {
    const vistas: Record<string, string>[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, opciones: { headers: Record<string, string> }) => {
        vistas.push(opciones.headers);
        return {
          ok: true,
          status: 200,
          headers: new Headers(),
          text: async () => "{}",
        } as unknown as Response;
      }),
    );
    const { llamar, mirarTenant } = await import("@/lib/api");

    await llamar("/api/v1/accounts");
    expect(vistas[0]?.["X-CRM-Tenant-Mirado"]).toBeUndefined();

    mirarTenant("01a1-el-de-ficosa");
    await llamar("/api/v1/accounts");
    await llamar("/api/v1/contacts");
    // En las DOS: con ella sólo en algunas, media pantalla hablaría de un
    // cliente y la otra media del propio.
    expect(vistas[1]?.["X-CRM-Tenant-Mirado"]).toBe("01a1-el-de-ficosa");
    expect(vistas[2]?.["X-CRM-Tenant-Mirado"]).toBe("01a1-el-de-ficosa");
  });

  it("se olvida al cerrar la pestaña, no al recargar", async () => {
    const { mirarTenant, tenantMirado } = await import("@/lib/api");
    mirarTenant("01a1-otro");
    // `sessionStorage` y no `localStorage`: recargar la pestaña mantiene lo
    // elegido; cerrarla lo olvida.
    expect(sessionStorage.getItem("crm.tenant_mirado")).toBe("01a1-otro");
    expect(localStorage.getItem("crm.tenant_mirado")).toBeNull();
    expect(tenantMirado()).toBe("01a1-otro");

    mirarTenant("");
    expect(tenantMirado()).toBe("");
  });

  it("si no se puede guardar, no se finge que se ha cambiado", async () => {
    const { mirarTenant, tenantMirado } = await import("@/lib/api");
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new Error("almacenamiento bloqueado");
    };
    try {
      mirarTenant("01a1-otro");
      // Ventana privada, almacenamiento bloqueado: se mira el propio tenant,
      // que es lo seguro.
      expect(tenantMirado()).toBe("");
    } finally {
      Storage.prototype.setItem = original;
    }
  });
});
