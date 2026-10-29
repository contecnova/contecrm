/**
 * Cuatro preguntas por registro que la API contestaba y no alcanzaba nadie.
 *
 * El módulo de calidad del dato enseña la cola y los agregados —qué hay que
 * tocar hoy, si la cola crece—. Delante de un cliente concreto la pregunta es
 * otra: **por qué su teléfono dice eso y no lo que dice el ERP**.
 *
 * De los cuatro paneles, los dos que cambian una decisión tienen prueba
 * propia: que se diga **cuál fuente gana** —sin eso, una lista de valores
 * distintos no dice cuál se está usando— y que la salud diga **si sirve para
 * actuar** antes de enseñar la puntuación.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

// `react-i18next` simulado para que `t()` devuelva la clave CON sus valores.
// Las pruebas no arrancan i18next —el diccionario no se carga— así que sin
// esto `t("x", { dias: 400 })` sale como «x» a secas, y entonces no se puede
// afirmar sobre el 400, que es justo el dato que importa.

const CUENTA = {
  cuenta: {
    id: "c1",
    nombre: "Componentes Delta",
    // El sector va con su forma real: la ficha lo lee como objeto, y un doble
    // a medias tumba la pantalla por un motivo que no es el que se prueba.
    sector: { codigo: "industria" },
    estado: "activa",
    roles: [],
    calidad: { puntuacion: 80, faltan: [] },
  },
  contactos: [],
  identificadores: [],
  metricas: { metricas: [], sin_dato: [] },
  timeline: [],
};

async function montar() {
  vi.resetModules();
  vi.doMock("@/lib/api", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/api");
    return {
      ...real,
      llamar: async (ruta: string) => {
        if (ruta.includes("/360")) return { datos: CUENTA };
        if (ruta.includes("/calidad-dato/linaje/"))
          return {
            datos: {
              campos: {
                telefono: [
                  {
                    fuente: "erp",
                    valor: "+34 600 000 000",
                    gana: true,
                    cambio_el_valor: "2026-09-01T00:00:00Z",
                    ultimo_mensaje: "2026-10-01T00:00:00Z",
                    confianza: 90,
                  },
                  {
                    fuente: "formulario_web",
                    valor: "+34 911 111 111",
                    gana: false,
                    cambio_el_valor: null,
                    ultimo_mensaje: "2026-08-01T00:00:00Z",
                    confianza: 40,
                  },
                ],
              },
              medible: true,
              que_significa: "",
            },
          };
        if (ruta.includes("/calidad-dato/obsoletos/"))
          return {
            datos: {
              obsoletos: [
                { campo: "telefono", fuente: "erp", dias_sin_confirmar: 400, tope: 365 },
              ],
              campos_con_linaje: ["telefono"],
              aviso: "",
            },
          };
        if (ruta.includes("/jerarquia"))
          return {
            datos: {
              id: "c1",
              nombre: "Componentes Delta",
              jerarquia: "legal",
              hijos: [
                { id: "c2", nombre: "Delta Portugal", rol: "filial", hijos: [] },
              ],
            },
          };
        if (ruta.includes("/calidad-dato/salud/"))
          return {
            datos: {
              hay: true,
              puntuacion: 72,
              nivel: "en riesgo",
              fiable: true,
              vigente: false,
              medida_hace_dias: 95,
              motivo: "Bajada de uso en los últimos dos meses",
              sirve_para_actuar: false,
              aviso: "La medida tiene 95 días.",
            },
          };
        return { datos: [] };
      },
    };
  });
  vi.doMock("@/lib/permisos", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/permisos");
    return { ...real, useSuperficie: () => ({ superficie: null, tiene: () => true }) };
  });
  vi.doMock("react-i18next", () => ({
    useTranslation: () => ({
      t: (clave: string, args?: Record<string, unknown>) =>
        args ? `${clave}:${JSON.stringify(args)}` : clave,
    }),
  }));
  vi.doMock("react-router-dom", async () => {
    const real = await vi.importActual<Record<string, unknown>>("react-router-dom");
    return { ...real, useParams: () => ({ id: "c1" }) };
  });
  const { Cuenta } = await import("@/paginas/Cuenta");
  return render(
    <MemoryRouter>
      <Cuenta />
    </MemoryRouter>,
  );
}

describe("de dónde sale cada dato de este cliente", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("dice qué fuente GANA, no sólo qué fuentes hay", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("+34 600 000 000")).toBeTruthy());
    // Las dos fuentes están; lo que decide es cuál manda. Sin el «gana», una
    // lista de valores distintos no dice cuál se está usando, que es justo la
    // pregunta: «¿por qué pone esto si el ERP dice otra cosa?».
    expect(screen.getByText("+34 911 111 111")).toBeTruthy();
    // «erp» sale dos veces —como fuente que gana y como fuente del dato
    // obsoleto—, así que se busca por la MARCA y no por el texto: la que
    // manda es la única con el distintivo de ganadora.
    const ganadoras = screen
      .getAllByText(/erp|formulario_web/)
      .filter((n) => n.className.includes("chip-dato--si"));
    expect(ganadoras).toHaveLength(1);
    expect(ganadoras[0]?.textContent).toBe("erp");
  });

  it("dice que la salud NO sirve para actuar antes de enseñar el número", async () => {
    await montar();
    // Una puntuación que no está vigente no puede mover una decisión, y
    // pintarla igual que una buena es lo que hace que nadie se crea ninguna.
    await waitFor(() => expect(screen.getByText("cuenta.saludNoSirve")).toBeTruthy());
    expect(screen.getByText(/cuenta.saludPuntuacion.*72/)).toBeTruthy();
    expect(screen.getByText(/cuenta.saludMedida.*95/)).toBeTruthy();
  });

  it("dice los días sin confirmar Y el tope", async () => {
    await montar();
    // «Lleva 400 días» no dice nada sin el tope: es lo que lo convierte en
    // «se ha pasado». Un dato viejo no se distingue de uno bueno mirándolo.
    await waitFor(() =>
      expect(screen.getByText(/cuenta.sinConfirmar.*400.*365/)).toBeTruthy(),
    );
  });

  it("enseña de qué grupo forma parte, y en qué jerarquía", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("Delta Portugal")).toBeTruthy());
    expect(screen.getByText("filial")).toBeTruthy();
    // La jerarquía concreta: la legal no es la comercial ni la de facturación.
    expect(screen.getByText(/cuenta.jerarquiaAyuda.*legal/)).toBeTruthy();
  });
});
