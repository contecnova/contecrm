/**
 * Lo que el servidor deja hacer con una fila se alcanza aunque no tenga ficha.
 *
 * Una ficha es algo que se lee, y sin `GET /coleccion/{id}` no la hay. Todo lo
 * que la ficha ofrece se quedaba entonces sin sitio: medido el 05-11-2026,
 * dieciséis pestañas tenían operaciones sobre sus filas y ninguna puerta. No
 * se podía revocar una clave de API, cerrar una sesión, quitar un dispositivo
 * de confianza ni editar un ajuste desde ninguna pantalla.
 *
 * Validada plantando el caso malo: sin la rama del `PUT` falla la de ajustes;
 * sin el filtro de permiso, la de permisos; sin codificar el valor, la de la
 * clave con espacio.
 */

import { describe, expect, it } from "vitest";

import { comoAccionDeFila, operacionesDeRegistro } from "@/lib/acciones";
import type { Superficie } from "@/lib/superficie";

const op = (metodo: string, ruta: string, resumen: string, permiso: string | null = null) => ({
  metodo,
  ruta,
  resumen,
  permiso,
});

const SUPERFICIE = {
  operaciones: [
    op("GET", "/api/v1/claves-api", "Claves"),
    op("DELETE", "/api/v1/claves-api/{clave_id}", "Revocar una clave"),
    op("PUT", "/api/v1/ajustes/{clave}", "Fijar un ajuste"),
    op("POST", "/api/v1/conectores/{clave}/actualizar", "Actualizar un conector", "integracion:write"),
    op("DELETE", "/api/v1/conectores/{clave}", "Desinstalar un conector", "integracion:admin"),
    // Un hijo de dos parámetros no es del registro: no entra.
    op("DELETE", "/api/v1/conectores/{clave}/claves/{otra}", "Quitar una clave del conector"),
  ],
} as unknown as Superficie;

const todo = () => true;

describe("una fila sin ficha tiene su menú", () => {
  it("quitar sale con el nombre que le da el contrato", () => {
    const r = operacionesDeRegistro(SUPERFICIE, "/api/v1/claves-api?revocada_at__vacio=true", todo);
    expect(r?.campo).toBe("id");
    expect(r?.quitar?.resumen).toBe("Revocar una clave");
    const accion = comoAccionDeFila(r!.quitar!, "k-1");
    expect(accion).toMatchObject({ ruta: "/api/v1/claves-api/k-1", metodo: "DELETE", nombre: "Revocar una clave" });
  });

  it("lo que sólo se escribe entero por clave se edita con PUT y por esa columna", () => {
    const r = operacionesDeRegistro(SUPERFICIE, "/api/v1/ajustes", todo);
    expect(r?.editar?.metodo).toBe("PUT");
    expect(r?.campo).toBe("clave");
    expect(comoAccionDeFila(r!.editar!, "zona horaria").ruta).toBe("/api/v1/ajustes/zona%20horaria");
  });

  it("sólo lo que el permiso deja, y nada de los hijos", () => {
    const r = operacionesDeRegistro(SUPERFICIE, "/api/v1/conectores", (p) => p === "integracion:write");
    expect(r?.acciones.map((a) => a.resumen)).toEqual(["Actualizar un conector"]);
    expect(r?.quitar).toBeNull();
  });

  it("sin nada que hacer, no hay menú", () => {
    expect(operacionesDeRegistro(SUPERFICIE, "/api/v1/nada", todo)).toBeNull();
  });
});

// La ficha de un proveedor es la de su cuenta, y pedía sólo las acciones de
// `/accounts`: homologar, la evaluación medida y la baja con lo comprometido no
// salían en ninguna parte (05-11-2026).
describe("la ficha de un proveedor", () => {
  const SUP = {
    operaciones: [
      op("POST", "/api/v1/accounts/{cuenta_id}/fusionar", "Fusionar esta cuenta con otra"),
      op("POST", "/api/v1/proveedores/{cuenta_id}/evaluacion-medida", "Cómo va este proveedor"),
      op("POST", "/api/v1/proveedores/{cuenta_id}/puede-darse-de-baja", "La calculadora de antes"),
    ],
  } as unknown as Superficie;

  it("lleva las de proveedor cuando lo es, sin las que se ocultan", async () => {
    const { accionesDeLaCuenta } = await import("@/lib/acciones");
    const nombres = accionesDeLaCuenta(SUP, "c-1", todo, {
      esProveedor: true,
      ocultas: ["/api/v1/proveedores/{cuenta_id}/puede-darse-de-baja"],
    }).map((a) => a.nombre);
    expect(nombres).toContain("Fusionar esta cuenta con otra");
    expect(nombres).toContain("Cómo va este proveedor");
    expect(nombres).not.toContain("La calculadora de antes");
  });

  it("y un cliente no las lleva", async () => {
    const { accionesDeLaCuenta } = await import("@/lib/acciones");
    const nombres = accionesDeLaCuenta(SUP, "c-1", todo, { esProveedor: false, ocultas: [] }).map(
      (a) => a.nombre,
    );
    expect(nombres).toEqual(["Fusionar esta cuenta con otra"]);
  });
});
