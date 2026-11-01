/**
 * Lo que se enseña a una persona está escrito en castellano.
 *
 * Un nombre de columna no admite tildes ni eñes: la columna se llama
 * `direccion`, `telefono`, `tamano`. Hasta el 01-11-2026 eso salía tal cual a
 * la pantalla. Medido en la ficha de una cuenta a 1440×900, en el recuadro de
 * calidad del dato: «Direccion · Email · Identificador fiscal · Owner id ·
 * Sector codigo · Tamano · Telefono · Web», y en las métricas «Dias medios de
 * pago, Facturacion 12m». En la lista, la columna «Sector codigo».
 *
 * `humanizar` la llaman veinte sitios —cabeceras de lista, selector de
 * columnas, filtros, rótulos de formulario, avisos de calidad, títulos de
 * agrupación— y además se usa sobre los **valores** (`esperando_cliente` →
 * «Esperando cliente»). Por eso se arregla aquí y no en veinte pantallas.
 *
 * Lo que esta prueba protege es el reparto: **lo regular en una regla y sólo
 * lo irregular en la tabla**. Una tabla que repite lo que una regla ya
 * resuelve se queda corta a la primera palabra nueva, y nadie se entera.
 */

import { describe, expect, it } from "vitest";

import { humanizar } from "@/lib/formato";

describe("lo regular sale de una regla, no de la tabla", () => {
  it("-ción y -sión, también en palabras que nadie ha escrito todavía", () => {
    expect(humanizar("direccion")).toBe("Dirección");
    expect(humanizar("facturacion_12m")).toBe("Facturación 12m");
    expect(humanizar("conversion")).toBe("Conversión");
    // La que importa: ésta no está en ninguna tabla y tiene que salir bien.
    expect(humanizar("retrocesion")).toBe("Retrocesión");
    expect(humanizar("condiciones")).toBe("Condiciones");
    expect(humanizar("devoluciones")).toBe("Devoluciones");
  });
});

describe("lo irregular sale de la tabla", () => {
  it("las que se vieron en pantalla", () => {
    expect(humanizar("sector_codigo")).toBe("Sector código");
    expect(humanizar("tamano")).toBe("Tamaño");
    expect(humanizar("telefono")).toBe("Teléfono");
    expect(humanizar("dias_medios_de_pago")).toBe("Días medios de pago");
  });

  it("y el inglés que se coló en un nombre de columna", () => {
    expect(humanizar("owner_id")).toBe("Responsable ID");
  });
});

describe("una sigla no se escribe «Nps»", () => {
  it("va entera en mayúsculas, esté donde esté", () => {
    expect(humanizar("nps")).toBe("NPS");
    expect(humanizar("tenant_id")).toBe("Tenant ID");
    expect(humanizar("iva_incluido")).toBe("IVA incluido");
  });
});

describe("de dónde viene el texto", () => {
  it("del nombre crudo del campo", () => {
    expect(humanizar("ultima_actividad")).toBe("Última actividad");
  });

  it("del `title` del contrato, que Pydantic genera en inglés-Title-Case", () => {
    // Llega con espacios y no con guiones bajos. Partiendo sólo por guion,
    // esto entraba entero como una palabra y no se arreglaba nada.
    expect(humanizar("Desde Moneda")).toBe("Desde moneda");
    expect(humanizar("Tenant Id")).toBe("Tenant ID");
  });

  it("y de un VALOR, que es el mismo problema", () => {
    // Un estado que la API manda como `esperando_cliente` es un identificador
    // enseñado a una persona, igual que un nombre de columna.
    expect(humanizar("esperando_cliente")).toBe("Esperando cliente");
    expect(humanizar("en_negociacion")).toBe("En negociación");
  });
});

describe("lo que no hay que tocar", () => {
  it("una palabra que ya está bien se queda como está", () => {
    expect(humanizar("nombre")).toBe("Nombre");
    expect(humanizar("importe_total")).toBe("Importe total");
    expect(humanizar("fecha_de_cierre")).toBe("Fecha de cierre");
  });

  it("y el prefijo técnico sigue cayéndose", () => {
    // `quota_registros` se lee «Registros»: la columna ya se llama «Cuotas».
    expect(humanizar("quota_registros")).toBe("Registros");
  });
});
