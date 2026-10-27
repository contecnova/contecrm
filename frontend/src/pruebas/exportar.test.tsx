/**
 * El botón de exportar: que exista, que mande lo que se está mirando y que
 * explique lo que el servidor conteste.
 *
 * Lo que se vigila es lo que haría que pareciera funcionar sin hacerlo:
 *
 *   · **que no salga donde el servidor no lo publica.** Un botón que da 404 es
 *     peor que no tenerlo: quien lo pulsa cree que el sistema está roto;
 *   · **que viajen los filtros puestos.** Exportar «todo» cuando en pantalla
 *     hay un recorte es la forma de que alguien mande un fichero con mucho más
 *     de lo que creía, y no se nota hasta que ya está fuera;
 *   · y **que el paso de verificación se explique**. El servidor pide el
 *     segundo factor otra vez para una exportación masiva; pintado como «no
 *     autorizado» se lee como que falta un permiso, que es otra cosa y lleva a
 *     pedirle a un administrador algo que no va a arreglar nada.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Operacion } from "@/lib/superficie";

const EXPORTAR: Operacion = {
  metodo: "GET",
  ruta: "/api/v1/cuentas/exportar",
  resumen: "Exportar cuentas",
  etiquetas: [],
  permiso: "cuenta:read",
  administracion: false,
  solo_plataforma: false,
  servicio: "party",
};

let operaciones: Operacion[] = [EXPORTAR];

vi.mock("@/lib/permisos", () => ({
  useSuperficie: () => ({ superficie: { operaciones }, tiene: () => true }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    // La CLAVE, no una traducción inventada: así falla si alguien pinta una
    // clave que no existe, en vez de enseñar una cadena vacía.
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

vi.mock("@/lib/config", () => ({ config: () => ({ apiBase: "" }) }));

const { Exportar } = await import("@/componentes/Exportar");

function pintar(consulta = "") {
  return render(<Exportar listar="/api/v1/cuentas" nombre="Cuentas" consulta={consulta} />);
}

beforeEach(() => {
  operaciones = [EXPORTAR];
  // `createObjectURL` no existe en jsdom y el componente lo usa para la
  // descarga: sin esto, la prueba fallaría por el entorno y no por el código.
  Object.assign(URL, {
    createObjectURL: vi.fn(() => "blob:x"),
    revokeObjectURL: vi.fn(),
  });
});

afterEach(() => vi.unstubAllGlobals());

describe("cuándo se ofrece", () => {
  it("si el servidor publica la ruta", () => {
    pintar();
    expect(screen.getByRole("button", { name: /exportar\.deQue/ })).toBeInTheDocument();
  });

  it("y no si no la publica", () => {
    operaciones = [];
    pintar();
    expect(screen.queryByRole("button", { name: /exportar\.deQue/ })).not.toBeInTheDocument();
  });

  it("ni mientras la superficie no ha llegado", () => {
    // Enseñarlo y quitarlo un segundo después mueve los botones bajo el cursor.
    operaciones = [];
    pintar();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("qué manda", () => {
  it("los filtros que hay puestos, y en CSV", async () => {
    const fetchMock = vi.fn(async () => new Response("a,b\n1,2", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    pintar("estado=abierta&importe__mayor=50000");

    await userEvent.click(screen.getByRole("button", { name: /exportar\.deQue/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [primera] = fetchMock.mock.calls as unknown as [[string]];
    const url = String(primera[0]);
    expect(url).toContain("/api/v1/cuentas/exportar?");
    expect(url).toContain("estado=abierta");
    expect(url).toContain("importe__mayor=50000");
    expect(url).toContain("formato=csv");
  });

  it("y dice que ha terminado, en voz alta", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("a,b\n1,2", { status: 200 })));
    pintar();
    await userEvent.click(screen.getByRole("button", { name: /exportar\.deQue/ }));
    // El fichero aparece en la carpeta de descargas sin que la pantalla cambie:
    // sin anunciarlo, quien usa lector de pantalla no se entera de nada.
    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent("exportar.listo");
  });
});

describe("cuando el servidor pide volver a verificarse", () => {
  it("lo explica, en vez de decir «no autorizado»", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error_code: "stepup.requerido",
              detalle: { tiene_factor: true, validez_minutos: 15 },
            }),
            { status: 401 },
          ),
      ),
    );
    pintar();
    await userEvent.click(screen.getByRole("button", { name: /exportar\.deQue/ }));
    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent("exportar.vuelveAVerificarte");
  });

  it("y distingue «verifícate otra vez» de «no tienes segundo factor»", async () => {
    // Son dos cosas muy distintas para quien está delante: una se resuelve en
    // diez segundos y la otra exige configurar algo.
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ error_code: "stepup.requerido", detalle: { tiene_factor: false } }),
            { status: 401 },
          ),
      ),
    );
    pintar();
    await userEvent.click(screen.getByRole("button", { name: /exportar\.deQue/ }));
    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent("exportar.sinSegundoFactor");
  });

  it("y un error que no es ese no se disfraza de reverificación", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ error_code: "otro" }), { status: 500 })),
    );
    pintar();
    await userEvent.click(screen.getByRole("button", { name: /exportar\.deQue/ }));
    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent("exportar.noSePudo");
  });
});

describe("cuando el fichero sale cortado", () => {
  it("lo dice, con cuántas filas lleva", async () => {
    // El aviso llega en una cabecera porque en una hoja de cálculo no cabe
    // decirlo sin ensuciarla, y quien lo pide puede leerla antes de abrir el
    // fichero — que es cuando todavía sirve de algo.
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("a,b\n1,2", {
            status: 200,
            headers: { "X-Exportacion-Truncada": "1", "X-Exportacion-Filas": "5000" },
          }),
      ),
    );
    pintar();
    await userEvent.click(screen.getByRole("button", { name: /exportar\.deQue/ }));
    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent("exportar.cortado");
    expect(aviso).toHaveTextContent("5000");
  });

  it("y no lo dice cuando no se ha cortado", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("a,b\n1,2", {
            status: 200,
            headers: { "X-Exportacion-Truncada": "0", "X-Exportacion-Filas": "2" },
          }),
      ),
    );
    pintar();
    await userEvent.click(screen.getByRole("button", { name: /exportar\.deQue/ }));
    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent("exportar.listo");
  });
});
