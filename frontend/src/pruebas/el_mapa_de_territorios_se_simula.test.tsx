/**
 * El mapa de territorios: qué pasaría si se publicara.
 *
 * Lo que se hace con un mapa de territorios no es mirarlo: es cambiarlo sin
 * romper el año de nadie. Publicar y ver qué pasa significa que cientos de
 * cuentas cambian de dueño el lunes, y deshacerlo no devuelve las
 * conversaciones que ya se tuvieron.
 *
 * Lo que se afirma aquí es lo que de verdad decide: **no** cuántas cambian,
 * sino las que se quedan sin territorio, los solapes y el veredicto de si se
 * puede publicar. Y las excepciones, que se declaraban y no se podían listar.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pedidas: string[] = [];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      pedidas.push(ruta);
      let datos: unknown = {};
      if (ruta.startsWith("/api/v1/territorios/excepciones"))
        datos = {
          excepciones: [
            {
              id: "e-1",
              cuenta_id: "aaaaaaaa-1111-2222-3333-444444444444",
              territorio_id: "t-2",
              motivo: "La lleva el director desde antes de la reorganización",
              hasta: "2026-11-15",
              permanente: false,
              dias_para_vencer: 17,
            },
          ],
          cuantas: 1,
          vencen_pronto: 1,
          que_significa:
            "1 excepciones vencen en 30 días o menos. Cuando venzan, esas cuentas vuelven a su territorio de origen sin avisar a nadie.",
        };
      else if (ruta.startsWith("/api/v1/territorios/simular"))
        datos = {
          cuentas: 40,
          cambian: [{ cuenta: "Acme", de: "norte", a: "sur" }],
          se_quedan: 37,
          sin_territorio: [{ cuenta: "Beta" }],
          solapes: [
            {
              cuenta: "Gamma",
              territorios: ["norte", "este"],
              por_que: "los dos con prioridad 100",
            },
          ],
          seguro_publicar: false,
        };
      else if (ruta.startsWith("/api/v1/territorios"))
        datos = {
          items: [
            {
              id: "t-1",
              clave: "norte",
              nombre: "Norte",
              prioridad: 100,
              responsable_id: null,
              padre_id: null,
              criterios: [{ campo: "provincia" }],
            },
            {
              id: "t-2",
              clave: "este",
              nombre: "Este",
              prioridad: 100,
              responsable_id: null,
              padre_id: null,
              criterios: [{ campo: "provincia" }],
            },
          ],
        };
      else if (ruta.startsWith("/api/v1/cuotas/consecucion"))
        datos = {
          cuotas: [
            {
              sujeto: "bbbbbbbb-1111-2222-3333-444444444444",
              tipo: "usuario",
              metrica: "importe",
              objetivo: "40000.00",
              objetivo_sin_prorratear: "120000.00",
              prorrateado: true,
              logrado: "15000.00",
              pct: 37.5,
              falta: "25000.00",
            },
          ],
          medible: true,
          aviso: "",
        };
      else if (ruta.startsWith("/api/v1/accounts")) datos = { items: [{ id: "a-1" }] };
      return { datos, version: null, retenidos: [], enmascarados: [] };
    }),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, args?: Record<string, unknown>) =>
      args ? `${clave}:${JSON.stringify(args)}` : clave,
  }),
}));

async function montar() {
  const { Territorios } = await import("@/paginas/Territorios");
  return render(
    <MemoryRouter>
      <Territorios />
    </MemoryRouter>,
  );
}

describe("el mapa de territorios se simula antes de publicarlo", () => {
  beforeEach(() => {
    pedidas.length = 0;
  });

  it("señala las prioridades repetidas, que son de donde salen los solapes", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("Norte")).toBeTruthy());
    // Dos territorios con la misma prioridad: la asignación acabaría
    // dependiendo del orden alfabético, y nadie lo busca hasta que dos
    // comerciales discuten.
    expect(screen.getByText(/territorios.prioridadRepetida/)).toBeTruthy();
  });

  it("simula con las cuentas de verdad y dice que NO conviene publicar", async () => {
    await montar();
    const boton = await waitFor(() => screen.getByText("territorios.simular"));
    await userEvent.click(boton);

    // Las cuentas las manda la pantalla: el servicio de territorios no lee la
    // tabla de cuentas, que vive en otro servicio.
    await waitFor(() =>
      expect(pedidas.some((r) => r.startsWith("/api/v1/accounts"))).toBe(true),
    );
    await waitFor(() =>
      expect(screen.getByText("territorios.noSeguro")).toBeTruthy(),
    );
    // Y lo que lo hace inseguro, dicho: sin territorio y solapes.
    expect(screen.getByText(/territorios.sinTerritorio.*"cuantas":1/)).toBeTruthy();
    expect(screen.getByText(/territorios.solapes.*"cuantos":1/)).toBeTruthy();
  });

  it("lista las excepciones y avisa de las que están a punto de vencer", async () => {
    await montar();
    await waitFor(() =>
      expect(
        screen.getByText("La lleva el director desde antes de la reorganización"),
      ).toBeTruthy(),
    );
    // Una excepción que caduca devuelve la cuenta a su territorio de origen
    // sin avisar: quien la llevaba se entera por el pipeline.
    expect(screen.getByText(/territorios.vence.*"dias":17/)).toBeTruthy();
    expect(
      screen.getByText(/vuelven a su territorio de origen sin avisar/),
    ).toBeTruthy();
  });

  it("dice que una cuota está prorrateada y cuál era la del plan", async () => {
    await montar();
    // Quien entra el día 20 no tiene la cuota entera, y medirle contra ella es
    // garantizarle que no la cumple. Sin el número del plan al lado, el
    // objetivo efectivo parece un error.
    await waitFor(() =>
      expect(screen.getByText(/territorios.prorrateada.*120000/)).toBeTruthy(),
    );
    expect(screen.getByText(/territorios.logradoDe.*40000/)).toBeTruthy();
  });
});
