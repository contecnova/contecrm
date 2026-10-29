/**
 * La puerta a lo que se construye en contecintelligence
 * (CRM-05.01.01.01 a .04, CRM-05.01.02.04, CRM-05.01.02.05).
 *
 * El catálogo declara esas seis **«delegado, no se reimplementa»** desde el
 * principio: el constructor de informes, los tipos, los filtros, los campos
 * calculados, los cuadros con el dato de quien los abre y sus suscripciones
 * viven en contecintelligence. Y desde el CRM no se llegaba a ninguna.
 *
 * Un enlace parece poca cosa y aquí es la diferencia entre **delegar y
 * abandonar**: sin él, quien busca «hacer un informe» en el CRM no encuentra
 * nada y concluye que no se puede.
 *
 * Lo que se exige: que el enlace **no aparezca cuando no hay a dónde ir**. Un
 * botón que lleva a ninguna parte es peor que no tenerlo, porque el que lo
 * pulsa deja de creerse el resto de la pantalla.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Explotacion } from "@/paginas/Explotacion";

let diagnostico: unknown;

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => {
    if (ruta.includes("/explotacion/diagnostico")) return { datos: diagnostico };
    if (ruta.includes("/explotacion/preguntas")) return { datos: [] };
    return { datos: {} };
  }),
  salvoCancelacion: (f: (e: unknown) => void) => f,
  ErrorApi: class extends Error {},
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

describe("dónde se construyen los informes", () => {
  beforeEach(() => {
    diagnostico = {
      puede_preguntar: true,
      problemas: [],
      sigue_funcionando: [],
      no_funciona: [],
      url_publica: "https://ci.cliente.test/",
      fuente_id: "f-1",
    };
  });

  it("lleva al constructor, que es donde viven", async () => {
    render(<Explotacion />);
    const caja = await screen.findByTestId("explotacion-donde-se-construyen");
    const enlace = caja.querySelector("a")!;
    expect(enlace.getAttribute("href")).toBe("https://ci.cliente.test");
    // En otra pestaña: quien está preguntando no quiere perder lo que escribió.
    expect(enlace.getAttribute("target")).toBe("_blank");
    // Y sin dejarle la ventana de origen al destino.
    expect(enlace.getAttribute("rel")).toContain("noopener");
  });

  it("dice que se entra con la identidad de uno", async () => {
    render(<Explotacion />);
    const caja = await screen.findByTestId("explotacion-donde-se-construyen");
    expect(caja.textContent).toContain("explotacion.dondeSeConstruyenPorque");
  });

  it("sin dirección no pinta un botón que no lleva a ninguna parte", async () => {
    diagnostico = {
      puede_preguntar: false,
      problemas: ["No hay CI_BASE_URL configurado."],
      sigue_funcionando: ["Los informes del propio CRM."],
      no_funciona: [],
      url_publica: "",
      fuente_id: "",
    };
    render(<Explotacion />);
    await screen.findByText("explotacion.noDisponible");
    expect(screen.queryByTestId("explotacion-donde-se-construyen")).toBeNull();
  });
});
