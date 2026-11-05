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
