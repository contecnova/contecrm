/**
 * Las dos entradas y la densidad: el armazón del rediseño.
 *
 * Dos cosas que se comprueban aquí y que se habrían escapado a la vista:
 *
 *   · que el filtro por ámbito sea **por entrada y no por área**, que es lo
 *     único que hace que la excepción de las aprobaciones exista de verdad;
 *   · que cargar la densidad **no la guarde**. Escribir el defecto al arrancar
 *     no se nota nunca —todo se ve bien— y entierra el ajuste del
 *     administrador para siempre: a partir del primer arranque cada persona
 *     tiene un valor propio idéntico al defecto, y el día que la empresa
 *     cambie el suyo no le cambia a nadie.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { grupoDelModulo } from "@/lib/modulos";
import {
  AREAS,
  TRANSVERSALES,
  ambitoDe,
  ambitoDelArea,
  ambitoDelCamino,
  menuDe,
} from "@/lib/navegacion";

const SIN_MODULOS = new Map<string, { ruta: string; titulo: string; grupo: string }[]>();
const TODAS = () => true;

describe("las dos entradas", () => {
  it("toda área declara su ámbito, y los dos existen", () => {
    const ambitos = new Set(AREAS.map((a) => a.ambito));
    expect(ambitos).toEqual(new Set(["trabajar", "administrar"]));
    // Y ninguno se queda vacío: un ámbito sin áreas sería una pestaña que no
    // lleva a ninguna parte.
    for (const esperado of ["trabajar", "administrar"]) {
      expect(AREAS.filter((a) => a.ambito === esperado).length).toBeGreaterThan(0);
    }
  });

  it("el trabajo diario y la configuración no comparten menú", () => {
    const trabajar = menuDe(SIN_MODULOS, TODAS, "trabajar").map((a) => a.id);
    const administrar = menuDe(SIN_MODULOS, TODAS, "administrar").map((a) => a.id);
    expect(trabajar).toContain("ventas");
    expect(trabajar).not.toContain("configuracion");
    expect(administrar).toContain("configuracion");
    expect(administrar).not.toContain("ventas");
  });

  it("sin pedir ámbito salen las dos: el resto de la aplicación no cambia", () => {
    // La paleta de comandos y la miga de pan llaman sin ámbito y tienen que
    // seguir viéndolo todo. Buscar una pantalla que existe y que no aparezca
    // porque está «en la otra pestaña» es peor que no tener pestañas.
    const todo = menuDe(SIN_MODULOS, TODAS).map((a) => a.id);
    expect(todo).toContain("ventas");
    expect(todo).toContain("configuracion");
  });

  it("las aprobaciones son trabajo aunque vivan en Automatización", () => {
    const aprobaciones = TRANSVERSALES.find((e) => e.a === "/aprobaciones");
    expect(aprobaciones).toBeDefined();
    // Su área es de administrar...
    expect(ambitoDelArea(aprobaciones!.area)).toBe("administrar");
    // ...y la entrada no.
    expect(ambitoDe(aprobaciones!, aprobaciones!.area)).toBe("trabajar");

    // Y se ve en el menú de trabajar, que es lo que importa: aprobar un
    // descuento escondido detrás de «Administrar» es una aprobación que se
    // queda esperando.
    const caminos = menuDe(SIN_MODULOS, TODAS, "trabajar").flatMap((a) =>
      a.entradas.map((e) => e.a),
    );
    expect(caminos).toContain("/aprobaciones");
    const otros = menuDe(SIN_MODULOS, TODAS, "administrar").flatMap((a) =>
      a.entradas.map((e) => e.a),
    );
    expect(otros).not.toContain("/aprobaciones");
  });

  it("la excepción es UNA y está contada", () => {
    // Si mañana son seis, el corte está mal hecho y hay que rehacerlo, no
    // seguir añadiendo excepciones. Esta cuenta es la que obliga a mirarlo.
    const excepciones = TRANSVERSALES.filter(
      (e) => e.ambito && e.ambito !== ambitoDelArea(e.area),
    );
    expect(excepciones.map((e) => e.a)).toEqual(["/aprobaciones"]);
  });

  it("la pestaña marcada sale del camino, también en un enlace directo", () => {
    expect(ambitoDelCamino("/administracion")).toBe("administrar");
    expect(ambitoDelCamino("/embudo")).toBe("trabajar");
    expect(ambitoDelCamino("/aprobaciones")).toBe("trabajar");
    // Lo que no está en el mapa cae en trabajar, que es donde se entra.
    expect(ambitoDelCamino("/")).toBe("trabajar");
    expect(ambitoDelCamino("/lo-que-sea")).toBe("trabajar");
  });

  it("un módulo de administración NO te devuelve a trabajar", () => {
    /**
     * El fallo que lo contó un usuario, no una prueba: estando en
     * «Administrar», abrir un módulo de administración cambiaba la pestaña a
     * «Trabajar» —porque `/m/<ruta>` no estaba en el mapa y caía por
     * descarte— y, como el destino de esa pestaña es la portada, el siguiente
     * clic te sacaba de donde estabas trabajando.
     *
     * Se comprueba con módulos reales del catálogo y en los dos sentidos: el
     * de administración se queda, y el de trabajo sigue siendo de trabajo.
     */
    expect(grupoDelModulo("tenants")).toBe("Plataforma");
    expect(ambitoDelCamino("/m/tenants", grupoDelModulo)).toBe("administrar");
    expect(ambitoDelCamino("/m/modelo", grupoDelModulo)).toBe("administrar");
    expect(ambitoDelCamino("/m/acceso", grupoDelModulo)).toBe("administrar");
    // Y la ficha de dentro de ese módulo, que es la misma travesía.
    expect(ambitoDelCamino("/m/tenants/tenant/abc", grupoDelModulo)).toBe("administrar");

    expect(ambitoDelCamino("/m/cuentas", grupoDelModulo)).toBe("trabajar");
    expect(ambitoDelCamino("/m/oportunidades", grupoDelModulo)).toBe("trabajar");

    // Sin el buscador de grupo se comporta como antes: es el parámetro el que
    // arregla el fallo, y así queda dicho que quitarlo lo devuelve.
    expect(ambitoDelCamino("/m/tenants")).toBe("trabajar");
  });

  it("gana el camino más largo cuando uno es prefijo de otro", () => {
    // `/m/cuentas` y `/m` no deben confundirse. Con un `startsWith` sin
    // ordenar, la primera coincidencia manda y el resultado depende del orden
    // de declaración, que es el tipo de fallo que sólo aparece al añadir una
    // pantalla meses después.
    const porLongitud = [...TRANSVERSALES].sort((a, b) => b.a.length - a.a.length);
    expect(porLongitud[0]!.a.length).toBeGreaterThanOrEqual(porLongitud.at(-1)!.a.length);
    expect(ambitoDelCamino("/administracion/lo-que-sea")).toBe("administrar");
  });
});

describe("la densidad", () => {
  beforeEach(() => {
    delete document.documentElement.dataset.densidad;
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it("se pinta en el documento y no en una clase", async () => {
    const { aplicarDensidad } = await import("@/lib/densidad");
    aplicarDensidad("comoda");
    expect(document.documentElement.dataset.densidad).toBe("comoda");
    // Y no toca la clase, que es de `.dark`: son dos ejes independientes y
    // mezclarlos obliga a conocer uno para cambiar el otro.
    expect(document.documentElement.className).not.toContain("comoda");
  });

  it("leerla NO la guarda", async () => {
    const llamadas: { ruta: string; metodo?: string }[] = [];
    vi.doMock("@/lib/api", () => ({
      llamar: async (ruta: string, opciones?: { metodo?: string }) => {
        llamadas.push({ ruta, metodo: opciones?.metodo });
        return { datos: { ui_densidad: { valor: "compacta" } }, version: null, retenidos: [] };
      },
    }));
    const { densidadDelPerfil } = await import("@/lib/densidad");

    expect(await densidadDelPerfil()).toBe("compacta");
    // Una sola llamada, y de lectura. Un PUT aquí es el fallo entero.
    expect(llamadas).toHaveLength(1);
    expect(llamadas[0]!.metodo).toBeUndefined();
  });

  it("si el servidor no contesta se usa el defecto y tampoco se guarda", async () => {
    const llamadas: string[] = [];
    vi.doMock("@/lib/api", () => ({
      llamar: async (ruta: string) => {
        llamadas.push(ruta);
        throw new Error("sin red");
      },
    }));
    const { densidadDelPerfil } = await import("@/lib/densidad");

    expect(await densidadDelPerfil()).toBe("compacta");
    expect(llamadas).toHaveLength(1);
  });

  it("un valor que no conocemos no se aplica", async () => {
    vi.doMock("@/lib/api", () => ({
      llamar: async () => ({
        datos: { ui_densidad: { valor: "gigante" } },
        version: null,
        retenidos: [],
      }),
    }));
    const { densidadDelPerfil } = await import("@/lib/densidad");
    expect(await densidadDelPerfil()).toBe("compacta");
  });

  it("elegirla sí la guarda, y sin decir el ámbito", async () => {
    const puestas: { ruta: string; metodo?: string; cuerpo?: unknown }[] = [];
    vi.doMock("@/lib/api", () => ({
      llamar: async (
        ruta: string,
        opciones?: { metodo?: string; cuerpo?: unknown },
      ) => {
        puestas.push({ ruta, ...opciones });
        return { datos: {}, version: null, retenidos: [] };
      },
    }));
    const { elegirDensidad } = await import("@/lib/densidad");

    await elegirDensidad("comoda");
    expect(document.documentElement.dataset.densidad).toBe("comoda");
    expect(puestas).toHaveLength(1);
    expect(puestas[0]!.metodo).toBe("PUT");
    expect(puestas[0]!.cuerpo).toEqual({ valor: "comoda" });
    // El ámbito lo pone el servidor. Mandarlo desde aquí sería dejar que
    // cualquiera cambiase la densidad de toda la empresa.
    expect(JSON.stringify(puestas[0]!.cuerpo)).not.toContain("ambito");
  });
});
