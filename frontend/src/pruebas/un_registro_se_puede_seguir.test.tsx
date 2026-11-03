/**
 * Seguir un registro, y que la vuelta exista.
 *
 * **Lo que había, medido el 03-11-2026.** `/api/v1/seguimientos` es lo que
 * decide a quién avisa el motor de notificaciones, y en el front no había **ni
 * un solo botón** para seguir ni para dejar de seguir: se veía lo que uno
 * seguía en una pestaña de administración —«cuenta · propietario · sí», sin el
 * nombre del registro y sin forma de abrirlo— y nada más. Escrito y sin
 * enchufar.
 *
 * Tres cosas se vigilan aquí, y las tres se pueden romper sin que se note:
 *
 *  · **El botón está en TODAS las fichas.** Por eso vive dentro del panel de
 *    datos clave y no en cada pantalla: hay catorce con ese panel y ponerlo a
 *    mano son catorce ocasiones de olvidarlo. Una ficha sin botón de seguir se
 *    ve exactamente igual que una ficha.
 *
 *  · **Se vuelve a preguntar después de pulsar**, no se supone el estado. Al
 *    propietario el servidor le SILENCIA en vez de desuscribirle, así que dar
 *    por hecho «ya no sigo» mentiría justo en el caso que importa.
 *
 *  · **Mientras no se sabe, no se ofrece.** Si la consulta falla, un botón que
 *    dijera «Seguir» haría que el primer clic contestara que ya lo seguía.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

let seguidos: { id: string; objeto_tipo: string; objeto_id: string; motivo: string; silenciado: boolean }[] = [];
let llamadas: { ruta: string; metodo: string }[] = [];
let falla = false;

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string, opciones?: { metodo?: string }) => {
      llamadas.push({ ruta, metodo: opciones?.metodo ?? "GET" });
      if (falla) throw new Error("no contesta");
      if ((opciones?.metodo ?? "GET") === "GET") return { datos: { items: seguidos } };
      return { datos: {} };
    }),
  };
});

const { Seguir } = await import("@/componentes/Seguir");

const SEGUIDO = {
  id: "s-1",
  objeto_tipo: "cuenta",
  objeto_id: "c-1",
  motivo: "manual",
  silenciado: false,
};

beforeEach(() => {
  seguidos = [];
  llamadas = [];
  falla = false;
  vi.clearAllMocks();
});

describe("el botón de seguir", () => {
  it("dice «Seguir» cuando no se sigue, y lo pide al pulsarlo", async () => {
    render(<Seguir objetoTipo="cuenta" objetoId="c-1" />);
    await screen.findByRole("button", { name: /seguir\.seguir/ });

    await userEvent.click(screen.getByRole("button"));
    const alta = llamadas.find((l) => l.metodo === "POST");
    expect(alta?.ruta).toBe("/api/v1/seguimientos");
  });

  it("dice «Siguiendo» cuando ya se sigue, y al pulsarlo lo quita", async () => {
    seguidos = [SEGUIDO];
    render(<Seguir objetoTipo="cuenta" objetoId="c-1" />);
    await screen.findByRole("button", { name: /seguir\.siguiendo/ });

    await userEvent.click(screen.getByRole("button"));
    const baja = llamadas.find((l) => l.metodo === "DELETE");
    expect(baja?.ruta).toBe("/api/v1/seguimientos/cuenta/c-1");
  });

  it("no confunde el seguimiento de OTRO registro con el de éste", async () => {
    // El extremo filtra por tipo y no por identificador, así que lo que
    // vuelve son todas las cuentas que sigue esta persona. Quedarse con la
    // primera diría «Siguiendo» en una cuenta que no sigue.
    seguidos = [{ ...SEGUIDO, objeto_id: "otra" }];
    render(<Seguir objetoTipo="cuenta" objetoId="c-1" />);
    expect(
      await screen.findByRole("button", { name: /seguir\.seguir/ }),
    ).toBeInTheDocument();
  });

  it("un seguimiento silenciado no cuenta como seguir", async () => {
    // Al propietario se le silencia en vez de desuscribirle: la fila sigue
    // ahí. Si contara, el botón diría «Siguiendo» mientras no llega un aviso.
    seguidos = [{ ...SEGUIDO, motivo: "propietario", silenciado: true }];
    render(<Seguir objetoTipo="cuenta" objetoId="c-1" />);
    expect(
      await screen.findByRole("button", { name: /seguir\.seguir/ }),
    ).toBeInTheDocument();
  });

  it("vuelve a preguntar en vez de suponer el estado nuevo", async () => {
    seguidos = [{ ...SEGUIDO, motivo: "propietario" }];
    render(<Seguir objetoTipo="cuenta" objetoId="c-1" />);
    await screen.findByRole("button", { name: /seguir\.siguiendo/ });
    llamadas = [];

    await userEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(llamadas.filter((l) => l.metodo === "GET")).toHaveLength(1));
  });

  it("si no se ha podido preguntar, no se ofrece", async () => {
    falla = true;
    const { container } = render(<Seguir objetoTipo="cuenta" objetoId="c-1" />);
    await waitFor(() => expect(llamadas).toHaveLength(1));
    expect(container.querySelector("button")).toBeNull();
  });
});

describe("todas las fichas lo llevan", () => {
  it("porque vive en el panel de datos clave, no en cada pantalla", () => {
    const panel = readFileSync(
      resolve(process.cwd(), "src", "componentes", "DatosClave.tsx"),
      "utf-8",
    );
    expect(panel).toContain("<Seguir");

    // Y ninguna ficha se lo pinta por su cuenta: dos sitios acabarían
    // enseñando dos botones, o uno enseñándolo y el otro no.
    const dir = resolve(process.cwd(), "src", "paginas");
    const conPanel = readdirSync(dir).filter((f) => {
      if (!f.endsWith(".tsx")) return false;
      return readFileSync(join(dir, f), "utf-8").includes("<DatosClave");
    });
    // Cuántas se han recorrido: si el filtro dejara de casar, esto daría
    // verde sin haber mirado ninguna.
    expect(conPanel.length).toBeGreaterThan(10);

    const apagadas: string[] = [];
    for (const f of conPanel) {
      const fuente = readFileSync(join(dir, f), "utf-8");
      expect(fuente, `${f} se pinta su propio botón de seguir`).not.toContain("<Seguir");
      if (/seguible=\{false\}/.test(fuente)) apagadas.push(f);
    }
    // Las que lo apagan son las que no son un registro de negocio, y son
    // exactamente dos. Escrito como número y no como lista: lo que importa
    // es que apagarlo sea una decisión y no una costumbre.
    expect(apagadas.sort()).toEqual(["InstanciaDeProceso.tsx", "ObjetoDelModelo.tsx"]);
  });
});
