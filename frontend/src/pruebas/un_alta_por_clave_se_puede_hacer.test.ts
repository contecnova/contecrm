/**
 * Hay colecciones que se crean con `PUT /coleccion/{codigo}`, y no se podían crear.
 *
 * **Medido el 04-11-2026** recorriendo las pantallas de administrar: en
 * «Riesgos y controles» no hay botón de «Nuevo». Un módulo de gobierno en el
 * que no se puede dar de alta un riesgo.
 *
 * Y no es que la API no lo admita: lo hace con `PUT /grc/riesgos/{codigo}`,
 * que es un alta-o-actualización. El descubrimiento del front sólo miraba el
 * `POST` de la colección, así que esas pestañas salían sin alta. Son cuatro,
 * medidas contra los contratos de los trece servicios: riesgos, controles,
 * reglas de segregación y políticas de acceso.
 *
 * La cuarta era peor: declaraba su alta a mano —`crear:
 * "…/politicas-acceso/{nombre}"`— así que **sí** tenía botón, y al pulsarlo
 * abría un formulario **vacío**, porque los campos se sacaban de un `POST`
 * que no existe.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { altaPorClave, altaPorPost, type Documento } from "@/lib/contrato";

const DOC = {
  paths: {
    "/api/v1/grc/riesgos": { get: {} },
    "/api/v1/grc/riesgos/{codigo}": { get: {}, put: {} },
    "/api/v1/cuentas": { get: {}, post: {} },
    "/api/v1/cuentas/{id}": { get: {}, patch: {} },
    "/api/v1/informes/{id}/ejecutar": { post: {} },
  },
} as unknown as Documento;

describe("el alta por clave", () => {
  it("se encuentra cuando la colección se escribe con PUT", () => {
    expect(altaPorClave(DOC, "/api/v1/grc/riesgos")).toEqual({
      plantilla: "/api/v1/grc/riesgos/{codigo}",
      clave: "codigo",
    });
  });

  it("no se inventa donde no la hay", () => {
    // `/cuentas/{id}` existe pero con `PATCH`: eso es editar, no dar de alta.
    // Confundirlos pondría un «Nuevo» que contesta 405.
    expect(altaPorClave(DOC, "/api/v1/cuentas")).toBeNull();
    expect(altaPorClave(DOC, "/api/v1/loquesea")).toBeNull();
  });

  it("no confunde una acción de un registro con el alta de la colección", () => {
    // `/informes/{id}/ejecutar` cuelga de un registro y tiene dos tramos
    // detrás: no es la plantilla de la colección.
    expect(altaPorClave(DOC, "/api/v1/informes")).toBeNull();
  });

  it("aguanta la ruta con parámetros de consulta y con barra final", () => {
    // El `listar` de un recurso puede traer su filtro puesto; la plantilla es
    // la misma. Sin esto, la pestaña que acota su listado se quedaba sin alta.
    expect(altaPorClave(DOC, "/api/v1/grc/riesgos?estado=abierto")?.clave).toBe(
      "codigo",
    );
    expect(altaPorClave(DOC, "/api/v1/grc/riesgos/")?.clave).toBe("codigo");
  });
});

describe("la pantalla de módulo", () => {
  it("descubre el alta por clave y la manda como PUT", () => {
    // Por el código, que es donde se decide: montar la pantalla entera pediría
    // un contrato de mentira por cada uno de los trece servicios.
    const fuente = readFileSync(
      resolve(process.cwd(), "src", "paginas", "Modulo.tsx"),
      "utf-8",
    );
    expect(fuente).toContain("altaPorClave(");
    // El método, y que la clave se sustituya en la URL en vez de viajar
    // dentro de unas llaves literales — que es lo que pasaba con la que se
    // declaraba a mano: `POST /api/v1/politicas-acceso/{nombre}`.
    expect(fuente).toContain('metodo: "PUT"');
    expect(fuente).toMatch(/replace\(\s*`\{\$\{claveDeAlta\}\}`/);
  });

  it("y no pinta dos campos con el mismo nombre", () => {
    // `PUT /politicas-acceso/{nombre}` tiene además un `nombre` en el cuerpo.
    // Añadir la clave sin mirar dejaba dos `#campo-nombre` en el DOM: la
    // etiqueta apunta a uno, el `aria-describedby` al otro, y el segundo no
    // se alcanza con teclado. Cazado dando de alta una política.
    const fuente = readFileSync(
      resolve(process.cwd(), "src", "paginas", "Modulo.tsx"),
      "utf-8",
    );
    expect(fuente).toContain("camposConLaClave(");
    expect(fuente).toMatch(/delCuerpo\.find\(\(c\) => c\.nombre === clave\)/);
  });
});

describe("el alta por POST", () => {
  // Medido el 09-11-2026: «Claves de API» lista con filtro y el alta iba a la
  // misma ruta CON el filtro, que el servidor rechaza con 422.
  it("va a la colección sin el filtro de la lista", () => {
    expect(altaPorPost(DOC, "/api/v1/cuentas?revocada_at__vacio=true")).toBe(
      "/api/v1/cuentas",
    );
    expect(altaPorPost(DOC, "/api/v1/cuentas")).toBe("/api/v1/cuentas");
  });

  it("y no la hay donde la colección no admite POST", () => {
    expect(altaPorPost(DOC, "/api/v1/grc/riesgos?x=1")).toBeNull();
  });
});
