/**
 * El componente que se incrusta en una web ajena.
 *
 * Lo que se mide aquí no es cómo pinta: es **con qué identidad habla** y qué
 * no se lleva a la página de otro.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { COMPONENTES } from "@/embebido";

describe("el componente embebible", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("se registra una sola vez aunque el script se cargue dos veces", () => {
    // Una página que incrusta dos componentes carga el script dos veces, y
    // `customElements.define` con un nombre repetido LANZA: sin la
    // comprobación, el segundo componente de la página no se pinta nunca.
    expect(customElements.get("contecrm-componente")).toBeTruthy();
  });

  it("ninguna ruta lleva un identificador", () => {
    /**
     * Ahí está todo el acotamiento: el identificador va DENTRO del token, así
     * que un token de la cuenta A no puede pedir la cuenta B — no hay
     * parámetro que cambiar en las herramientas del navegador.
     */
    for (const [nombre, decl] of Object.entries(COMPONENTES)) {
      expect(decl.ruta, nombre).not.toMatch(/\{|\$\{|:id|\?/);
      expect(decl.ruta, nombre).toMatch(/^\/embebido\//);
    }
  });

  it("no manda cookies", async () => {
    // Vive en otra web: la sesión del CRM no tiene nada que hacer ahí. Es la
    // otra mitad de la misma decisión que el token acotado.
    let opciones: RequestInit | undefined;
    vi.stubGlobal("fetch", (_u: string, o?: RequestInit) => {
      opciones = o;
      return Promise.resolve(
        new Response(JSON.stringify({ nombre: "Acme" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    const el = document.createElement("contecrm-componente");
    el.setAttribute("componente", "ficha-cuenta");
    el.setAttribute("api", "https://crm.example/api/v1");
    el.setAttribute("token", "tok");
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 0));

    expect(opciones?.credentials).toBe("omit");
    expect((opciones?.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    el.remove();
  });

  it("dice qué falta en vez de llamar y enseñar un 401", async () => {
    // Una llamada sin token contesta «no autenticado», y ese mensaje manda a
    // mirar al sitio equivocado a quien está integrando el componente.
    let llamado = false;
    vi.stubGlobal("fetch", () => {
      llamado = true;
      return Promise.resolve(new Response("{}", { status: 200 }));
    });

    const el = document.createElement("contecrm-componente");
    el.setAttribute("componente", "ficha-cuenta");
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 0));

    expect(llamado).toBe(false);
    expect(el.shadowRoot?.textContent).toMatch(/api.*token/i);
    el.remove();
  });

  it("vive dentro de su propio árbol", async () => {
    // Shadow DOM: los estilos del anfitrión no entran y los nuestros no salen.
    // Sin él, una hoja de estilos cualquiera de la página puede dejarlo
    // ilegible —o nosotros romperle la maquetación—, y lo descubre el cliente
    // en su web, no nosotros.
    const el = document.createElement("contecrm-componente");
    document.body.appendChild(el);
    expect(el.shadowRoot).toBeTruthy();
    el.remove();
  });

  it("un componente desconocido se dice, no se calla", async () => {
    const el = document.createElement("contecrm-componente");
    el.setAttribute("componente", "inventado");
    el.setAttribute("api", "https://crm.example/api/v1");
    el.setAttribute("token", "tok");
    document.body.appendChild(el);
    await new Promise((r) => setTimeout(r, 0));
    expect(el.shadowRoot?.textContent).toMatch(/inventado/);
    el.remove();
  });
});
