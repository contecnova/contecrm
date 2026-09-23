/**
 * La consola se construye desde el contrato, y esto lo defiende.
 *
 * Lo que se comprueba no es que agrupe bonito: es que **no haya forma de pintar
 * una acción que no venga de la superficie**, que es lo que hace comprobable
 * —y no solo declarada— la promesa de que la consola está replicada al 100 %
 * por API (CRM-07.01.01.01).
 */

import { describe, expect, it } from "vitest";

import {
  acciones,
  areasDeAdministracion,
  operacionDeListado,
  recursoDe,
  type Operacion,
  type Superficie,
} from "@/lib/superficie";

function op(parcial: Partial<Operacion>): Operacion {
  return {
    metodo: "GET",
    ruta: "/api/v1/tenants",
    resumen: "",
    etiquetas: ["tenants"],
    solo_plataforma: false,
    permiso: null,
    administracion: true,
    servicio: "tenancy",
    ...parcial,
  };
}

function superficie(operaciones: Operacion[]): Superficie {
  return {
    consultado_at: "2026-09-21T00:00:00Z",
    servicios: ["tenancy"],
    servicios_sin_contestar: [],
    completa: true,
    total: operaciones.length,
    administracion: operaciones.filter((o) => o.administracion).length,
    operaciones,
  };
}

describe("áreas de administración", () => {
  it("solo entra lo marcado como administración", () => {
    const areas = areasDeAdministracion(
      superficie([
        op({}),
        op({ ruta: "/api/v1/accounts", etiquetas: ["cuentas"], administracion: false }),
      ]),
    );
    expect(areas.map((a) => a.recurso)).toEqual(["tenants"]);
  });

  it("agrupa por recurso y no por etiqueta", () => {
    // Dos servicios que rotulan parecido acabarían en el mismo menú apuntando a
    // sitios distintos, y el usuario no vería la diferencia hasta pulsar.
    const areas = areasDeAdministracion(
      superficie([
        op({ ruta: "/api/v1/ajustes", etiquetas: ["configuración"] }),
        op({ ruta: "/api/v1/flags", etiquetas: ["configuración"], servicio: "tenancy" }),
      ]),
    );
    expect(areas.map((a) => a.recurso).sort()).toEqual(["ajustes", "flags"]);
  });

  it("el recurso sale del tercer segmento", () => {
    expect(recursoDe("/api/v1/tenants/{tenant_id}/unidades")).toBe("tenants");
    expect(recursoDe("/health")).toBe("");
  });
});

describe("qué se puede pintar de un área", () => {
  it("el listado es el GET SIN parámetros en la ruta", () => {
    // Con uno parametrizado habría que pedirle al usuario que invente un
    // identificador para ver una tabla.
    const [area] = areasDeAdministracion(
      superficie([
        op({ ruta: "/api/v1/tenants/{tenant_id}" }),
        op({ ruta: "/api/v1/tenants" }),
      ]),
    );
    expect(operacionDeListado(area!)?.ruta).toBe("/api/v1/tenants");
  });

  it("un área sin listado no inventa uno", () => {
    const [area] = areasDeAdministracion(superficie([op({ ruta: "/api/v1/tenants/{tenant_id}" })]));
    expect(operacionDeListado(area!)).toBeUndefined();
  });

  it("las acciones son lo que cambia algo", () => {
    const [area] = areasDeAdministracion(
      superficie([
        op({}),
        op({ metodo: "POST", ruta: "/api/v1/tenants" }),
        op({ metodo: "DELETE", ruta: "/api/v1/tenants/{tenant_id}" }),
      ]),
    );
    expect(acciones(area!).map((o) => o.metodo).sort()).toEqual(["DELETE", "POST"]);
  });
});
