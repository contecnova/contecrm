/**
 * El informe de vuelta: qué hace el CRM que ninguna pantalla enseña.
 *
 * Es el que nadie hace y el que decide si la solución se puede presentar
 * entera: una capacidad que solo existe por API es una capacidad que quien mira
 * el producto concluye que no está.
 */

import { describe, expect, it } from "vitest";

import { calcular } from "@/paginas/Cobertura";
import type { Operacion, Superficie } from "@/lib/superficie";

function op(ruta: string, extra: Partial<Operacion> = {}): Operacion {
  return {
    metodo: "GET",
    ruta,
    resumen: "",
    etiquetas: [],
    permiso: null,
    solo_plataforma: false,
    administracion: false,
    servicio: "party",
    ...extra,
  };
}

function superficie(operaciones: Operacion[]): Superficie {
  return {
    consultado_at: "2026-09-21T00:00:00Z",
    servicios: ["party"],
    servicios_sin_contestar: [],
    completa: true,
    total: operaciones.length,
    administracion: operaciones.filter((o) => o.administracion).length,
    operaciones,
  };
}

describe("cobertura de la interfaz", () => {
  it("un recurso que un módulo enseña no sale como escondido", () => {
    // `/api/v1/accounts` lo enseña el módulo de cuentas.
    const informe = calcular(superficie([op("/api/v1/accounts")]));
    expect(informe.sinPantalla).toEqual([]);
  });

  it("un recurso que nadie enseña sale, con su servicio y cuántas operaciones", () => {
    const informe = calcular(
      superficie([
        op("/api/v1/inventado"),
        op("/api/v1/inventado/{id}", { metodo: "PATCH" }),
      ]),
    );
    expect(informe.sinPantalla).toEqual([
      { recurso: "inventado", servicios: ["party"], operaciones: 2 },
    ]);
  });

  it("lo que la consola enseña por ser de administración cuenta como enseñado", () => {
    // La consola se construye de la propia superficie, así que todo lo marcado
    // como administración ya tiene pantalla por construcción.
    const informe = calcular(superficie([op("/api/v1/loquesea", { administracion: true })]));
    expect(informe.sinPantalla).toEqual([]);
  });

  it("los recursos escondidos salen ordenados por cuánto esconden", () => {
    // Quien lee esta lista quiere empezar por donde hay más que enseñar.
    const informe = calcular(
      superficie([
        op("/api/v1/poco"),
        op("/api/v1/mucho"),
        op("/api/v1/mucho/{id}"),
        op("/api/v1/mucho/{id}/algo"),
      ]),
    );
    expect(informe.sinPantalla.map((r) => r.recurso)).toEqual(["mucho", "poco"]);
  });
});
