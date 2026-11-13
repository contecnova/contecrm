/**
 * Un enlace a la ficha de un registro lleva a una ruta que existe.
 *
 * Calidad del dato enlazaba a `/contactos/{id}` y `/cuentas/{id}`, que no son
 * rutas: el usuario caía en «no existe». La ficha vive en
 * `/m/<módulo>/<tipo>/<id>`, y el módulo sale de la tabla de visibilidad, no de
 * una cadena escrita a mano en cada pantalla. Validada plantando el caso malo:
 * con `/contactos/${id}` en `fichaDeObjeto` falla la primera.
 */

import { describe, expect, it } from "vitest";

import { fichaDeObjeto } from "@/lib/modulos";

describe("un enlace a ficha lleva a una ruta", () => {
  it("contacto, cuenta y lead van a la ficha de su módulo", () => {
    expect(fichaDeObjeto("contacto", "c-1")).toBe("/m/cuentas/contacto/c-1");
    expect(fichaDeObjeto("cuenta", "a-1")).toBe("/m/cuentas/cuenta/a-1");
    expect(fichaDeObjeto("lead", "l-1")).toBe("/m/leads/lead/l-1");
  });

  it("un tipo sin pantalla va a `/abrir/…`, que lo dice", () => {
    expect(fichaDeObjeto("no_existe", "x-1")).toBe("/abrir/no_existe/x-1");
  });
});
