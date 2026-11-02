/**
 * En qué pestaña se aterriza al abrir una ficha.
 *
 * Salesforce reparte la ficha en **Relacionado** y **Detalles**, y entra por
 * «Relacionado»: al abrir un registro lo que se busca casi siempre es lo que
 * cuelga de él —sus contactos, sus adjuntos—, no releer sus campos. Aquí la
 * ficha entraba por «Datos» con TODO dentro, una cosa debajo de otra.
 *
 * Con una diferencia respecto a Lightning, que es lo que prueba este fichero:
 * **se aterriza en «Relacionado» sólo si hay algo que enseñar**. En este
 * producto hay objetos que no tienen nada colgando, y aterrizar en una pestaña
 * vacía es peor primera impresión que empezar por los campos.
 *
 * Y mientras la superficie no ha llegado no se sabe si hay algo, así que se
 * entra por «Detalles», que siempre tiene algo. La regla para **enseñar** una
 * pestaña es la contraria —mientras no se sabe se da por buena, para no mover
 * los botones bajo el cursor—, y mezclar las dos hacía que un enlace directo
 * a un registro aterrizara siempre en una pestaña que podía estar vacía.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

let conAdjuntos = true;
let superficieLlegada = true;

vi.mock("@/lib/permisos", () => ({
  useSuperficie: () => ({
    superficie: superficieLlegada
      ? {
          operaciones: [],
          objetos: {
            adjuntos: conAdjuntos ? ["cuenta"] : [],
            comentarios: [],
            documentos: [],
            actividades: [],
          },
        }
      : null,
    tiene: () => true,
  }),
  usePuedeOperar: () => () => true,
  useVisibilidad: () => ({
    rutas: new Set<string>(),
    cargada: false,
    sinContestar: new Set<string>(),
  }),
}));

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    // El doble contesta según la ruta. Con una sola respuesta, el panel de
    // adjuntos recibía el registro donde espera una lista y reventaba: eso
    // dice «la pantalla está rota» cuando lo que faltaba era el doble.
    llamar: vi.fn(async (ruta: string) => ({
      datos: /\/(adjuntos|documentos)\//.test(ruta)
        ? []
        : { id: "r-1", nombre: "Lo que sea" },
      version: null,
      retenidos: [],
      enmascarados: [],
    })),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

async function abrir() {
  const { Ficha } = await import("@/paginas/Ficha");
  return render(
    <MemoryRouter initialEntries={["/m/cuentas/cuenta/r-1"]}>
      <Routes>
        <Route path="/m/:ruta/:tipo/:id" element={<Ficha />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** Cuál está marcada: la que lleva `aria-current`, como el resto de la casa. */
function pestanaActiva(): string | null {
  const marcada = screen
    .getAllByRole("button")
    .find((b) => b.getAttribute("aria-current") === "page");
  return marcada?.textContent ?? null;
}

describe("la ficha abre por Relacionado", () => {
  beforeEach(() => {
    conAdjuntos = true;
    superficieLlegada = true;
  });

  it("entra por Relacionado cuando hay algo que enseñar", async () => {
    await abrir();
    await waitFor(() => expect(pestanaActiva()).toBe("ficha.relacionado"));
    // Y los campos NO están: están en la otra pestaña, no todos juntos.
    expect(screen.queryByText("ficha.identificadores")).toBeNull();
  });

  it("entra por Detalles cuando no cuelga nada del registro", async () => {
    conAdjuntos = false;
    await abrir();
    await waitFor(() => expect(pestanaActiva()).toBe("ficha.detalles"));
    await waitFor(() =>
      expect(screen.getByText("ficha.identificadores")).toBeInTheDocument(),
    );
  });

  it("entra por Detalles mientras no se sabe si hay algo", async () => {
    // El caso que lo destapó: el enlace directo a un registro. La superficie
    // todavía no ha llegado y la regla optimista decía «sí hay», así que se
    // aterrizaba en una pestaña que en la mitad de los objetos está vacía.
    superficieLlegada = false;
    await abrir();
    await waitFor(() => expect(pestanaActiva()).toBe("ficha.detalles"));
  });
});
