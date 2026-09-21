/**
 * La interfaz no decide permisos: lee lo que dice el servidor.
 *
 * Lo que se comprueba aquí es que los comodines se expandan **igual que en el
 * servidor**. Una interfaz que no los expandiera escondería media aplicación
 * justo al administrador, que es quien los tiene.
 */

import { describe, expect, it } from "vitest";

import { puede, type Sesion } from "@/lib/sesion";

function sesion(permisos: string[], admin = false): Sesion {
  return {
    usuario_id: "u1",
    nombre: "Quien sea",
    email: "quien@ejemplo.test",
    tenant_id: "t1",
    roles: [],
    permisos,
    es_admin_plataforma: admin,
    suplantado_por: null,
  };
}

describe("permisos", () => {
  it("sin permiso declarado, la operación se ofrece", () => {
    // Una operación que no declara permiso la protege el servidor por otra vía;
    // esconderla aquí sería inventarse una restricción que no existe.
    expect(puede(sesion([]), null)).toBe(true);
  });

  it("sin sesión no se ofrece nada que pida permiso", () => {
    expect(puede(null, "tenant:write")).toBe(false);
  });

  it("el comodín total lo concede todo", () => {
    expect(puede(sesion(["*:*"]), "tenant:write")).toBe(true);
  });

  it("el comodín por objeto y por acción también", () => {
    expect(puede(sesion(["tenant:*"]), "tenant:write")).toBe(true);
    expect(puede(sesion(["*:read"]), "tenant:read")).toBe(true);
  });

  it("un permiso de otro objeto no vale", () => {
    expect(puede(sesion(["account:write"]), "tenant:write")).toBe(false);
  });

  it("el administrador de plataforma lo puede todo", () => {
    expect(puede(sesion([], true), "tenant:write")).toBe(true);
  });
});
