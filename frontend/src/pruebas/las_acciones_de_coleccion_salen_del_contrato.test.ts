/**
 * Las acciones sobre la colección entera, deducidas en vez de escritas.
 *
 * Se declaraban a mano y el comentario que las declaraba decía que no se
 * podían deducir. Medido el 29-10-2026: **102 `POST` colgando de una colección
 * sin ningún parámetro en la ruta, y la lista a mano tenía cuatro**. Trece de
 * esas 102 no piden cuerpo —«genera las recurrentes que tocan», «he perdido el
 * portátil», «busca duplicados en todo el maestro»— y **ninguna tenía botón en
 * ninguna pantalla**: existían en la API y no había forma de llamarlas.
 *
 * Es el caso de libro de «una lista de los que SÍ siempre se queda corta»: no
 * falla, no avisa, y lo que falta no se nota porque nadie echa de menos un
 * botón que nunca ha visto.
 *
 * Lo que se fija aquí son las cuatro reglas que hacen que el botón no mienta:
 * que no se ofrezca lo que pide cuerpo (contestaría 422), ni lo que actúa
 * sobre un registro (su sitio es la ficha), ni lo que no toca por permiso, ni
 * el alta de la propia colección, que ya tiene su botón.
 */

import { describe, expect, it } from "vitest";

import { accionesDeColeccion } from "@/lib/acciones";
import type { Superficie } from "@/lib/superficie";

const SUPERFICIE = {
  servicio: "party",
  operaciones: [
    // La que SÍ: un tramo más, sin parámetros, sin cuerpo obligatorio.
    {
      metodo: "POST",
      ruta: "/api/v1/recurrencias/generar",
      resumen: "Crear las recurrentes que tocan",
      permiso: "activity:write",
      exige_cuerpo: false,
    },
    // Pide cuerpo: llamarla vacía da 422, así que un botón suyo sería un
    // botón que no funciona nunca. Es un formulario, no una acción.
    {
      metodo: "POST",
      ruta: "/api/v1/recurrencias/declarar",
      resumen: "Declarar una recurrencia",
      permiso: "activity:write",
      exige_cuerpo: true,
    },
    // Actúa sobre un registro: su sitio es la ficha, no la cabecera del
    // listado, donde además no habría identificador que ponerle.
    {
      metodo: "POST",
      ruta: "/api/v1/recurrencias/{id}/pausar",
      resumen: "Pausar",
      permiso: "activity:write",
      exige_cuerpo: false,
    },
    // El alta de la colección: ya tiene su botón.
    {
      metodo: "POST",
      ruta: "/api/v1/recurrencias",
      resumen: "Crear",
      permiso: "activity:write",
      exige_cuerpo: true,
    },
    // De otra colección.
    {
      metodo: "POST",
      ruta: "/api/v1/visitas/check-in",
      resumen: "Registrar la llegada",
      permiso: "activity:write",
      exige_cuerpo: false,
    },
    // No es POST.
    {
      metodo: "GET",
      ruta: "/api/v1/recurrencias/pendientes",
      resumen: "Las que quedan",
      permiso: "activity:read",
      exige_cuerpo: false,
    },
  ],
} as unknown as Superficie;

const TODO = () => true;

describe("las acciones de colección se deducen del contrato", () => {
  it("ofrece la que no pide cuerpo y nada más", () => {
    const acciones = accionesDeColeccion(SUPERFICIE, "/api/v1/recurrencias", TODO);
    expect(acciones.map((a) => a.ruta)).toEqual(["/api/v1/recurrencias/generar"]);
    // El rótulo lo escribe el servicio dueño: dice lo que hace mejor que el
    // último tramo de la ruta.
    expect(acciones[0]?.nombre).toBe("Crear las recurrentes que tocan");
  });

  it("no ofrece lo que esta persona no puede hacer", () => {
    const acciones = accionesDeColeccion(
      SUPERFICIE,
      "/api/v1/recurrencias",
      (permiso) => permiso !== "activity:write",
    );
    expect(acciones).toEqual([]);
  });

  it("sin superficie no inventa nada", () => {
    // Mientras la superficie no ha llegado no se pintan botones a medias: uno
    // que aparece y desaparece se lee como un fallo.
    expect(accionesDeColeccion(null, "/api/v1/recurrencias", TODO)).toEqual([]);
  });

  it("no confunde una colección con otra que empieza igual", () => {
    const acciones = accionesDeColeccion(SUPERFICIE, "/api/v1/visitas", TODO);
    expect(acciones.map((a) => a.ruta)).toEqual(["/api/v1/visitas/check-in"]);
  });
});
