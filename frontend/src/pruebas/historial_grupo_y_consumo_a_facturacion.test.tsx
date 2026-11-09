/**
 * Historial de la configuración, grupo de empresas y consumo para facturación
 * (CRM-00.01.04.02, CRM-00.01.03.07, CRM-00.01.06.07).
 *
 * Las tres pantallas se pintan con la FORMA que manda el servidor (la que fijan
 * sus pruebas de `tests/unit/test_versionado_jerarquia_y_consumo_a_facturacion.py`)
 * y llaman a la ruta que toca al pulsar.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { ConsumoAFacturacion } from "@/paginas/ConsumoAFacturacion";
import { GrupoDeEmpresas } from "@/paginas/GrupoDeEmpresas";
import { HistorialDeAjustes, valorLegible } from "@/paginas/HistorialDeAjustes";
import type { Sesion } from "@/lib/sesion";

const llamadas: { ruta: string; metodo: string; cuerpo?: unknown }[] = [];
let respuestas: Record<string, unknown> = {};

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(
    async (ruta: string, op?: { metodo?: string; cuerpo?: unknown }) => {
      llamadas.push({ ruta, metodo: op?.metodo ?? "GET", cuerpo: op?.cuerpo });
      const clave = Object.keys(respuestas)
        .sort((a, b) => b.length - a.length)
        .find((k) => ruta.includes(k));
      return { datos: clave ? respuestas[clave] : {} };
    },
  ),
  salvoCancelacion: (f: (e: unknown) => void) => f,
  ErrorApi: class extends Error {},
}));

vi.mock("@/lib/listados", () => ({
  listar: vi.fn(async () => [
    { id: "t-matriz", nombre: "Matriz" },
    { id: "t-hija", nombre: "Hija" },
  ]),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

beforeEach(() => {
  llamadas.length = 0;
  respuestas = {};
});

const VERSION = {
  id: "v2",
  clave: "idioma",
  ambito: "tenant",
  ambito_id: "t",
  antes: "es",
  despues: "fr",
  tipo: "cambio",
  por: null,
  motivo: "",
  cuando: "2026-11-09T10:00:00+00:00",
};

describe("Historial de la configuración", () => {
  it("pinta antes y después y vuelve atrás por su ruta", async () => {
    respuestas = {
      "/ajustes/versiones": {
        claves: [{ clave: "idioma", cambios: 2, ultimo: VERSION.cuando }],
        versiones: [
          VERSION,
          { ...VERSION, id: "v1", antes: null, despues: "es" },
        ],
      },
    };
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <MemoryRouter>
        <HistorialDeAjustes />
      </MemoryRouter>,
    );
    expect(await screen.findByText("fr")).toBeTruthy();
    fireEvent.click(
      screen.getAllByRole("button", { name: /historialAjustes.volver/ })[0]!,
    );
    await waitFor(() =>
      expect(
        llamadas.some(
          (l) =>
            l.ruta === "/api/v1/ajustes/versiones/v2/volver" &&
            l.metodo === "POST",
        ),
      ).toBe(true),
    );
  });

  it("compara dos versiones elegidas", async () => {
    respuestas = {
      "/ajustes/versiones": {
        claves: [],
        versiones: [VERSION, { ...VERSION, id: "v1" }],
      },
      "/ajustes/versiones/comparar": {
        clave: "idioma",
        desde: VERSION,
        hasta: VERSION,
        cambios: [{ ruta: "", tipo: "cambiado", antes: "es", despues: "fr" }],
      },
    };
    render(
      <MemoryRouter>
        <HistorialDeAjustes />
      </MemoryRouter>,
    );
    const casillas = await screen.findAllByRole("checkbox");
    fireEvent.click(casillas[0]!);
    fireEvent.click(casillas[1]!);
    fireEvent.click(
      screen.getByRole("button", { name: /historialAjustes.comparar/ }),
    );
    expect(
      await screen.findByText("historialAjustes.valorEntero"),
    ).toBeTruthy();
    expect(
      llamadas.some(
        (l) =>
          l.ruta.includes("comparar?a=v2&b=v1") ||
          l.ruta.includes("comparar?a=v1&b=v2"),
      ),
    ).toBe(true);
  });

  it("un valor estructurado se lee entero y el vacío no es un hueco", () => {
    expect(valorLegible({ a: 1 })).toBe('{"a":1}');
    expect(valorLegible(null)).toBe("—");
    expect(valorLegible("")).toBe("«»");
  });
});

const SESION: Sesion = {
  usuario_id: "u",
  nombre: "Ana",
  email: "a@x",
  tenant_id: "t-hija",
  roles: [],
  permisos: [],
  es_admin_plataforma: false,
  suplantado_por: null,
};

describe("Grupo de empresas", () => {
  it("dice lo no compartido como tal y guarda lo que comparte la hija", async () => {
    respuestas = {
      "/jerarquia": {
        tenant_id: "t-hija",
        relaciones: ["matriz_filial", "franquicia", "holding"],
        nodos: [
          {
            id: "t-matriz",
            slug: "m",
            nombre: "Matriz",
            estado: "activo",
            padre_id: null,
            relacion: null,
            comparte: [],
            nivel: 0,
          },
          {
            id: "t-hija",
            slug: "h",
            nombre: "Hija",
            estado: "activo",
            padre_id: "t-matriz",
            relacion: "franquicia",
            comparte: [],
            nivel: 1,
          },
        ],
      },
      "/jerarquia/agregado": {
        tenant_id: "t-hija",
        hijas: [
          {
            id: "n",
            nombre: "Nieta",
            relacion: "holding",
            comparte: [],
            consumo: null,
            indicadores: null,
          },
        ],
        totales: { consumo: [], indicadores: [] },
        no_comparten: ["Nieta"],
      },
    };
    render(
      <MemoryRouter>
        <GrupoDeEmpresas sesion={SESION} />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Matriz")).toBeTruthy();
    expect(screen.getAllByText("grupoEmpresas.noCompartido")).toHaveLength(2);
    fireEvent.click(screen.getByLabelText("grupoEmpresas.compartible.consumo"));
    fireEvent.click(
      screen.getByRole("button", { name: "grupoEmpresas.guardarComparticion" }),
    );
    await waitFor(() => {
      const put = llamadas.find((l) => l.metodo === "PUT");
      expect(put?.ruta).toBe("/api/v1/tenants/t-hija/jerarquia/comparticion");
      expect(put?.cuerpo).toEqual({ comparte: ["consumo"] });
    });
    // Sin ser plataforma no se ofrece colgar empresas.
    expect(screen.queryByText("grupoEmpresas.colgar")).toBeNull();
  });
});

describe("Consumo para facturación", () => {
  it("enseña el estado del envío y lo incompleto, y toma un corte", async () => {
    respuestas = {
      "/facturacion/destino": {
        configurado: false,
        maquina: "",
        formato: "json",
        periodica: false,
        max_intentos: 5,
        columnas: [
          "periodo",
          "tenant",
          "modulo",
          "metrica",
          "cantidad",
          "unidad",
          "tope",
        ],
      },
      "/facturacion/cortes": {
        cortes: [
          {
            id: "c1",
            periodo: "2026-11",
            origen: "manual",
            filas: 3,
            completo: false,
            no_leidos: ["marketing"],
            estado_envio: "fallido",
            intentos: 2,
            ultimo_error: "HTTP 422: rechazado",
            respuesta_codigo: 422,
            enviado_at: null,
            tomado_at: "2026-11-09T10:00:00+00:00",
          },
        ],
      },
    };
    render(
      <MemoryRouter>
        <ConsumoAFacturacion />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText("consumoFacturacion.estados.fallido"),
    ).toBeTruthy();
    expect(screen.getByText("HTTP 422: rechazado")).toBeTruthy();
    expect(screen.getByText("consumoFacturacion.incompleto")).toBeTruthy();
    expect(screen.getByText("consumoFacturacion.sinDestino")).toBeTruthy();
    respuestas["/facturacion/cortes"] = {
      ...(respuestas["/facturacion/cortes"] as object),
    };
    fireEvent.click(
      screen.getByRole("button", { name: /consumoFacturacion.tomarYEnviar/ }),
    );
    await waitFor(() => {
      const post = llamadas.find((l) => l.metodo === "POST");
      expect(post?.ruta).toBe("/api/v1/facturacion/cortes");
      expect(post?.cuerpo).toEqual({ enviar: true });
    });
  });
});
