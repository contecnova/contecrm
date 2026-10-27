/**
 * El portal enseña las secciones que el acceso concede, y sólo ésas.
 *
 * El servidor ya dice cuáles en `secciones`, y lo dice justo para que el
 * portal **no pinte botones que luego dan 403**. Hasta el 27-10-2026 esta
 * pantalla enseñaba dos —peticiones y conversación— y las otras seis estaban
 * publicadas y servidas sin que el cliente pudiera verlas: lo que su empresa
 * tiene instalado, sus contratos, sus pedidos, los artículos que puede leer,
 * la comunidad y quién más de su empresa tiene acceso.
 *
 * Las tres cosas que esto fija, que son las que se rompen sin ruido:
 *
 *   · se piden las rutas de las secciones concedidas, y no las demás;
 *   · una sección que el servidor concede y este portal no sabe pintar no se
 *     inventa: no se enseña. Un recuadro con su rótulo y nada dentro se lee
 *     como «no tienes nada»;
 *   · lo que no se puede leer **se dice**. Callarlo deja al cliente creyendo
 *     que no tiene contratos cuando lo que pasa es que el acceso está mal dado.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pedidas: string[] = [];
let respuestas: Record<string, unknown> = {};
let fallan: Set<string> = new Set();

vi.stubGlobal(
  "fetch",
  vi.fn(async (url: string) => {
    const ruta = String(url);
    pedidas.push(ruta);
    const clave = Object.keys(respuestas).find((k) => ruta.includes(k));
    if ([...fallan].some((f) => ruta.includes(f))) {
      return {
        ok: false,
        status: 403,
        json: async () => ({ detail: "Esa sección no es tuya" }),
        text: async () => JSON.stringify({ detail: "Esa sección no es tuya" }),
      } as unknown as Response;
    }
    // `text()` y no sólo `json()`: el portal lee el cuerpo con `.text()` y lo
    // parsea él. Con el texto vacío todo llegaba `null` y las secciones salían
    // vacías sin que fallara nada — justo el fallo que esta prueba persigue.
    const cuerpo = clave ? respuestas[clave] : [];
    return {
      ok: true,
      status: 200,
      json: async () => cuerpo,
      text: async () => JSON.stringify(cuerpo),
    } as unknown as Response;
  }),
);

const { Portal } = await import("@/paginas/Portal");

function entrar(secciones: string[]) {
  // La sesión nace del canje del enlace que llega por correo, con el token en
  // la dirección: es exactamente lo que hace el cliente, así que es lo que se
  // monta aquí en vez de inyectarle una sesión por dentro.
  window.history.replaceState({}, "", "/portal?t=enlace-del-correo");
  respuestas = {
    "/portal/sesion": { token: "t", nivel: "cuenta", secciones },
    ...respuestas,
  };
}

describe("el portal pinta lo que el acceso concede", () => {
  beforeEach(() => {
    pedidas.length = 0;
    respuestas = {};
    fallan = new Set();
  });

  it("pide las secciones concedidas y ninguna más", async () => {
    entrar(["casos", "contratos", "activos"]);
    respuestas["/portal/mi/contratos"] = [{ id: "c1", nombre: "TESTIGO-contrato" }];
    respuestas["/portal/mi/activos"] = [{ id: "a1", nombre: "TESTIGO-activo" }];
    render(<Portal />);

    await waitFor(() => {
      expect(pedidas.some((r) => r.includes("/portal/mi/contratos"))).toBe(true);
    });
    expect(pedidas.some((r) => r.includes("/portal/mi/activos"))).toBe(true);
    // Las que el acceso NO concede no se piden: una petición que va a dar 403
    // no es una comprobación, es ruido en el registro del servidor.
    expect(pedidas.some((r) => r.includes("/portal/mi/comunidad"))).toBe(false);
    expect(pedidas.some((r) => r.includes("/portal/mi/pedidos"))).toBe(false);
  });

  it("enseña lo que llega de cada sección", async () => {
    entrar(["casos", "contratos"]);
    respuestas["/portal/mi/contratos"] = [
      { id: "c1", nombre: "TESTIGO-contrato", estado: "vigente" },
    ];
    render(<Portal />);
    expect(await screen.findByText("TESTIGO-contrato")).toBeInTheDocument();
    expect(screen.getByText("vigente")).toBeInTheDocument();
  });

  it("una sección que este portal no sabe pintar no se inventa", async () => {
    entrar(["casos", "seccion_del_futuro"]);
    render(<Portal />);
    await waitFor(() => expect(pedidas.length).toBeGreaterThan(0));
    // Ni se pide ni se pinta un recuadro vacío con su rótulo, que se leería
    // como que no hay datos.
    expect(pedidas.some((r) => r.includes("seccion_del_futuro"))).toBe(false);
    expect(screen.queryByText(/seccion_del_futuro/i)).toBeNull();
  });

  it("lo que no se puede leer se dice, no se calla", async () => {
    entrar(["casos", "pedidos"]);
    fallan.add("/portal/mi/pedidos");
    render(<Portal />);
    // Callarlo deja al cliente creyendo que no tiene pedidos cuando lo que
    // pasa es que su acceso está mal dado.
    await waitFor(() => {
      const avisos = screen.getAllByRole("alert").map((n) => n.textContent ?? "");
      expect(avisos.join(" ")).toMatch(/sección|secci/i);
    });
  });
});
