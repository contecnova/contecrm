/**
 * «Esto antes no decía esto»: el historial campo a campo del registro.
 *
 * Cada edición anotaba el campo, el valor anterior, el nuevo, quién lo hizo y
 * **desde dónde**, y no lo devolvía ninguna ruta ni lo enseñaba ninguna
 * pantalla. Se escribía y no lo leía nadie.
 *
 * Lo que fijan estas pruebas, por orden de lo que duele:
 *
 *   · que NO se pida al abrir la ficha —es trazabilidad, no contenido, y una
 *     llamada por registro abierto que casi nadie mira se paga en cada ficha—;
 *   · que el **origen** salga al lado del cambio, porque es lo que distingue
 *     «lo cambió alguien» de «lo pisó una sincronización»;
 *   · y que un historial vacío diga CUÁL de las dos cosas es, en vez de «no
 *     hay nada».
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pedidas: string[] = [];
let respuesta: unknown = null;

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      pedidas.push(ruta);
      return { datos: respuesta, version: null, retenidos: [], enmascarados: [] };
    }),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

async function montar() {
  const { HistorialDeCampos } = await import("@/paginas/Ficha");
  return render(
    <HistorialDeCampos servicio="sales" objeto="oportunidad" objetoId="op-1" />,
  );
}

describe("qué ha cambiado en este registro", () => {
  beforeEach(() => {
    pedidas.length = 0;
    respuesta = {
      cambios: [
        {
          campo: "importe",
          valor_anterior: "1000",
          valor_nuevo: "2500",
          origen: "sincronizacion",
        },
      ],
      cuantos: 1,
      que_significa: "Cada línea dice qué cambió, quién y desde dónde.",
    };
  });

  it("no se pide hasta que alguien lo abre", async () => {
    await montar();
    expect(pedidas).toEqual([]);

    await userEvent.click(screen.getByText("ficha.queHaCambiado"));
    // Con espera: el `onToggle` cambia el estado y la llamada la hace el
    // efecto de la vuelta siguiente. Afirmar justo después del clic pasaba en
    // una máquina descargada y fallaba en el preflight completo, con la
    // máquina a 7 de carga. Una prueba que depende de la prisa no mide nada.
    await waitFor(() =>
      expect(pedidas).toEqual(["/api/v1/sales/rastro/campos/oportunidad/op-1"]),
    );
  });

  it("el origen sale al lado del cambio", async () => {
    await montar();
    await userEvent.click(screen.getByText("ficha.queHaCambiado"));

    expect(await screen.findByText("importe")).toBeInTheDocument();
    expect(screen.getByText("1000")).toBeInTheDocument();
    expect(screen.getByText("2500")).toBeInTheDocument();
    // Lo que zanja la discusión: no es lo mismo que lo cambiara una persona a
    // que lo pisara una sincronización todas las noches.
    expect(screen.getByText("sincronizacion")).toBeInTheDocument();
  });

  it("vacío dice cuál de las dos cosas es, no «no hay nada»", async () => {
    respuesta = {
      cambios: [],
      cuantos: 0,
      que_significa:
        "Este servicio no ha anotado ningún cambio de campo de ningún registro.",
    };
    await montar();
    await userEvent.click(screen.getByText("ficha.queHaCambiado"));

    expect(
      await screen.findByText(/no ha anotado ningún cambio de campo/),
    ).toBeInTheDocument();
  });

  it("abrirlo dos veces no lo pide dos veces", async () => {
    await montar();
    const resumen = screen.getByText("ficha.queHaCambiado");
    await userEvent.click(resumen);
    await screen.findByText("importe");
    await userEvent.click(resumen);
    await userEvent.click(resumen);
    await waitFor(() => expect(pedidas).toHaveLength(1));
  });
});
