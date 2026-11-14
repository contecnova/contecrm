/**
 * La página de estado dice qué panel no ha llegado, y deja reintentarlo.
 *
 * Es la pantalla que se mira cuando algo va mal, y era la que más tragaba:
 * ocho paneles pedidos aparte y cada fallo en `.catch(() => undefined)`. Con
 * el objetivo de servicio caído, su sitio salía vacío y se leía como «no hay
 * objetivo», que no es lo mismo que «no se ha podido preguntar».
 *
 * Aquí: el estado principal llega, el del objetivo de servicio no, y la página
 * lo dice en su sitio, sigue en pie y al reintentar pide SÓLO esa ruta.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ErrorApi } from "@/lib/api";
import { Estado } from "@/paginas/Estado";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, o?: Record<string, unknown>) =>
      o ? `${clave} ${JSON.stringify(o)}` : clave,
  }),
}));

const SLO = "/api/v1/estado/slo";
let sloCaido = true;
const llamar = vi.fn(async (ruta: string) => {
  if (ruta === "/api/v1/estado")
    return {
      datos: {
        estado: "ok",
        componentes: [
          { servicio: "party", componente: "base", estado: "ok", detalle: "" },
        ],
      },
    };
  if (ruta === SLO) {
    if (sloCaido) throw new ErrorApi(0, "red", "", null);
    return {
      datos: {
        servicios: [{ servicio: "party", objetivo_pct: 99.9, presupuesto_minutos: 43 }],
        que_significa: "se puede desplegar",
      },
    };
  }
  // Los demás paneles, cancelados: no son fallo ni pintan nada, y así aquí
  // sólo se mira el del objetivo.
  throw new DOMException("cancelada", "AbortError");
});
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  llamar: (ruta: string) => llamar(ruta),
}));

describe("la página de estado con un panel caído", () => {
  it("lo dice en su sitio, sigue en pie y reintenta sólo ese", async () => {
    render(<Estado />);

    const aviso = await screen.findByRole("alert");
    expect(aviso.textContent).toContain("estado.slo");
    expect(aviso.textContent).toContain("errores.sinRed");
    // Lo urgente sigue a la vista.
    expect(screen.getByText("party")).toBeTruthy();

    const antes = llamar.mock.calls.length;
    sloCaido = false;
    await userEvent.click(screen.getByRole("button", { name: /app.reintentar/ }));

    expect(await screen.findByText("se puede desplegar")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(llamar.mock.calls.slice(antes).map((c) => c[0])).toEqual([SLO]);
  });
});
