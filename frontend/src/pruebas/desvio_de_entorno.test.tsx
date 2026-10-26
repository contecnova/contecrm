/**
 * El desvío de un entorno, PINTADO con lo que el servidor manda de verdad
 * (CRM-07.04.03.27).
 *
 * La pantalla leía `hay_desvio` y `diferencias`. El servidor manda `limpio`,
 * `tocado_a_mano` y `desaparecido`, y no ha mandado nunca los otros dos:
 *
 *   · `hay_desvio` llegaba `undefined`, así que el aviso salía **siempre en
 *     verde** — incluso con el texto de al lado diciendo que había
 *     configuración tocada a mano;
 *   · y a `diferencias` se le pedía `.length`, que sobre `undefined` **tumba
 *     la pantalla entera**.
 *
 * Nada de esto se ve en el servidor ni en el tipo de TypeScript: la respuesta
 * llega como `unknown` y el tipo es una promesa, no una comprobación. Se ve
 * pintándola con la respuesta real, que es lo que se hace aquí.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Alm } from "@/paginas/Alm";

let respuesta: unknown = {};
let puesto: unknown = { hay: false, porque: "Aquí no consta nada puesto." };

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => ({
    datos: ruta.endsWith("/desplegado") ? puesto : respuesta,
  })),
  ErrorApi: class extends Error {},
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

/** Lo que devuelve `GET /api/v1/entornos/{entorno}/drift`, copiado de la
 * prueba de servidor que lo recorre. */
const CON_DESVIO = {
  entorno: "produccion",
  paquete: "base",
  version: 1,
  medible: true,
  tocado_a_mano: [{ elemento: "campos.nif", que_paso: "cambiado a mano", campos: ["tipo"] }],
  desaparecido: ["campos.web"],
  limpio: false,
  comparado: ["campos"],
  no_comparado: ["objetos", "vistas"],
  que_significa: "Hay configuración tocada fuera del pipeline.",
};

async function mirar() {
  render(<Alm />);
  await userEvent.click(screen.getByRole("button", { name: "alm.verDesvio" }));
}

describe("el desvío de un entorno", () => {
  beforeEach(() => {
    respuesta = {};
    puesto = { hay: false, porque: "Aquí no consta nada puesto." };
  });

  it("pinta lo tocado a mano con el campo que cambió", async () => {
    respuesta = CON_DESVIO;
    await mirar();
    expect(await screen.findByText("nif")).toBeInTheDocument();
    // Dos filas, las dos del tipo «campos»: lo tocado y lo desaparecido.
    expect(screen.getAllByText("campos")).toHaveLength(2);
    expect(screen.getByText(/cambiado a mano: tipo/)).toBeInTheDocument();
  });

  it("pinta lo que desapareció igual que lo que se tocó", async () => {
    // Es el caso que más se esconde: alguien borró algo en producción y un
    // panel que solo enseña lo añadido lo deja fuera.
    respuesta = CON_DESVIO;
    await mirar();
    expect(await screen.findByText("web")).toBeInTheDocument();
    expect(screen.getByText(/ya no está/)).toBeInTheDocument();
  });

  it("no pinta en verde un entorno con desvío", async () => {
    // **El fallo.** `hay_desvio` no existe: llegaba `undefined` y el aviso
    // salía en verde con el texto diciendo lo contrario.
    respuesta = CON_DESVIO;
    await mirar();
    const aviso = await screen.findByRole("status");
    expect(aviso.className).toContain("text-warning");
    expect(aviso.className).not.toContain("text-success");
  });

  it("dice qué no se ha comparado", async () => {
    // Un «limpio» que tapa seis tipos sin mirar es peor que no medir.
    respuesta = { ...CON_DESVIO, limpio: true, tocado_a_mano: [], desaparecido: [] };
    await mirar();
    expect(await screen.findByText(/alm\.noComparado/)).toBeInTheDocument();
  });

  it("sin paquete desplegado dice por qué, no un hueco", async () => {
    // La pantalla leía `que_significa`, que en esta rama no viene: el motivo
    // es `porque`, y el recuadro salía con el título y nada debajo.
    respuesta = {
      entorno: "produccion",
      medible: false,
      porque: "No consta ningún paquete desplegado en este entorno.",
    };
    await mirar();
    expect(
      await screen.findByText(/No consta ningún paquete desplegado/),
    ).toBeInTheDocument();
  });

  it("dice qué hay puesto y de qué commit sale", async () => {
    // El agujero de CRM-07.02.01.04: `referencia_git` se escribía al empaquetar
    // y no la devolvía ninguna ruta, así que «¿de qué versión del repositorio
    // sale lo que hay en producción?» no se podía contestar desde el producto.
    respuesta = CON_DESVIO;
    puesto = {
      hay: true,
      paquete: "base",
      version: 3,
      referencia_git: "refs/tags/v2.4.0@9f3c1ab",
    };
    await mirar();
    const linea = await screen.findByTestId("alm-desplegado");
    expect(linea.textContent).toContain("base");
    expect(linea.textContent).toContain("9f3c1ab");
  });

  it("un paquete montado desde la consola lo dice, no deja el hueco", async () => {
    // No hay commit al que volver, sólo el paquete anterior. Un hueco se lee
    // como «todavía está cargando».
    respuesta = CON_DESVIO;
    puesto = { hay: true, paquete: "base", version: 3, referencia_git: "" };
    await mirar();
    const linea = await screen.findByTestId("alm-desplegado");
    expect(linea.textContent).toContain("alm.sinGit");
  });
});
