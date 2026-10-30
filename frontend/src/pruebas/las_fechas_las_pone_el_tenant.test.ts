/**
 * Ninguna pantalla escribe una fecha ni un importe por su cuenta.
 *
 * Visto en la ficha de un presupuesto, con la interfaz en castellano:
 *
 *     Válido hasta el 11/26/2026
 *     1531.00 EUR
 *
 * El 26 de noviembre escrito al revés, y el importe en crudo: decimal con
 * punto, sin separador de miles y con el código ISO detrás en vez del símbolo.
 *
 * `lib/formato.ts` lleva desde hace tiempo los formateadores con la
 * localización que **resuelve el servidor** —jerarquía global → tier → tenant
 * → unidad → usuario, `GET /api/v1/localizacion`—. Lo que fallaba es que diez
 * pantallas llamaban a `new Date(x).toLocaleDateString()` sin localización, y
 * entonces manda la del navegador: la misma pantalla sale distinta según quién
 * la abra, y ninguna de las dos es la del tenant.
 *
 * Esta prueba es de código, no de pintado: recorre las pantallas y no deja que
 * vuelva a aparecer la llamada. Validada plantando el caso malo: devolviendo
 * una sola de las diez, falla nombrando el fichero y la línea.
 */

import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { fecha, fechaHora, fijarLocalizacion, importe, localizacion } from "@/lib/formato";

const SRC = path.resolve(__dirname, "..");

function ficheros(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return e.name === "pruebas" ? [] : ficheros(p);
    return /\.tsx?$/.test(e.name) ? [p] : [];
  });
}

describe("las fechas y los importes los pone el tenant", () => {
  it("ninguna pantalla llama a toLocale*String sin localización", () => {
    const todos = ficheros(SRC);
    // Cuántos ha mirado: un recorrido vacío parece limpio.
    expect(todos.length).toBeGreaterThan(80);

    const malos: string[] = [];
    for (const f of todos) {
      if (f.endsWith(path.join("lib", "formato.ts"))) continue; // es quien los crea
      fs.readFileSync(f, "utf8")
        .split("\n")
        .forEach((linea, i) => {
          // Sin argumentos es lo que coge la del navegador. Con ellos, alguien
          // la ha elegido a propósito y eso se lee en la revisión.
          if (/\.toLocale(Date|Time)?String\(\s*\)/.test(linea)) {
            malos.push(`${path.relative(SRC, f)}:${i + 1}  ${linea.trim()}`);
          }
        });
    }
    expect(malos).toEqual([]);
  });

  it("los ayudantes formatean con la localización del servidor, no con la del navegador", () => {
    const antes = localizacion();
    try {
      fijarLocalizacion("es-ES");
      expect(fecha("2026-11-26")).toBe("26/11/26");
      expect(importe("1531.00", "EUR")).toContain("1531");
      expect(importe("1531.00", "EUR")).toContain("€");
      // El mismo dato, otro tenant: cambia sin tocar ninguna pantalla.
      fijarLocalizacion("en-US");
      expect(fecha("2026-11-26")).toBe("11/26/26");
      expect(importe("1531.00", "USD")).toContain("$");
    } finally {
      fijarLocalizacion(antes);
    }
  });

  it("un valor que falta es una raya, no «Invalid Date»", () => {
    for (const malo of [null, undefined, "", "no-es-una-fecha", {}]) {
      expect(fecha(malo)).toBe("—");
      expect(fechaHora(malo)).toBe("—");
    }
  });

  it("el idioma del documento sigue a la localización del tenant", () => {
    const antes = localizacion();
    try {
      fijarLocalizacion("pt-PT");
      expect(document.documentElement.lang).toBe("pt-PT");
      fijarLocalizacion("es-ES");
      expect(document.documentElement.lang).toBe("es-ES");
    } finally {
      fijarLocalizacion(antes);
    }
  });
});
