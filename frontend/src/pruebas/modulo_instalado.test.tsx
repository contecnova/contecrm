/**
 * La ficha de un módulo vertical instalado (CRM-00.04.04.01, .03, .04, .05,
 * .07, .08, .10).
 *
 * Todo esto lo contestaba el servidor y no se alcanzaba desde el producto: el
 * manifiesto estaba guardado entero y la ficha devolvía cuatro campos, y la
 * integridad y la telemetría sólo se podían pedir sabiéndose la clave de
 * memoria.
 *
 * Lo que se exige aquí es lo que distingue esta pantalla de un volcado: que
 * **diga que no sabe cuando no sabe**. Una integridad en verde calculada
 * contra un catálogo que ya no tiene esa versión es peor que un «no se puede
 * comparar», y una conclusión de «esto sobra» sacada a los dos días de
 * instalarlo es una conclusión sobre nada.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { llamar } from "@/lib/api";
import { ModuloInstalado } from "@/paginas/ModuloInstalado";

let modulo: unknown;
let ensayo: unknown;
let integridad: unknown;
let telemetria: unknown;

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => {
    if (ruta.endsWith("/desinstalar")) return { datos: ensayo };
    if (ruta.endsWith("/integridad")) return { datos: integridad };
    if (ruta.endsWith("/telemetria")) return { datos: telemetria };
    if (ruta.endsWith("/superficie"))
      return {
        datos: {
          modulos: [],
          pantallas: [
            {
              modulo: "homologaciones",
              clave: "homologaciones.lista",
              titulo: "Homologaciones",
            },
          ],
        },
      };
    return { datos: modulo };
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

function abrir() {
  render(
    <MemoryRouter initialEntries={["/m/modelo/modulo/homologaciones"]}>
      <Routes>
        <Route path="/m/modelo/modulo/:clave" element={<ModuloInstalado />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("la ficha de un módulo instalado", () => {
  beforeEach(() => {
    vi.mocked(llamar).mockClear();
    ensayo = {
      quitaria: 3,
      registros_por_objeto: { homologacion_mercado: 120 },
      no_se_han_podido_contar: ["certificado_mercado"],
      modificados_por_el_cliente: ["campos.norma"],
      modulos_que_dependen: [],
      se_puede_desinstalar: true,
      que_pasa_con_los_datos:
        "Los registros se CONSERVAN y quedarán sin pantalla que los enseñe.",
    };
    modulo = {
      clave: "homologaciones",
      nombre: "Homologaciones por mercado",
      version: "1.0.0",
      autor: "contecnova",
      estado: "instalado",
      instalado_at: "2026-10-28T14:57:20+01:00",
      objetos: ["homologacion_mercado"],
      campos: 3,
      espacio_de_nombres: "homo",
      depende_de: { calidad: ">=2.0" },
      nucleo_minimo: "1.4",
      huella: "9f3c1ab0d4e5f6a7b8c9",
    };
    integridad = {
      modulo: "homologaciones",
      medible: true,
      integro: false,
      tocados_a_mano: ["campos.norma"],
      desaparecidos: ["campos.vence_at"],
    };
    telemetria = {
      modulo: "homologaciones",
      version: "1.0.0",
      instalado_hace_dias: 0,
      elementos: 3,
      usados: 0,
      sin_usar: ["homologacion_mercado"],
      modificados_por_el_cliente: [],
      mas_usados: [],
      concluyente: false,
      aviso:
        "Lleva 0 días instalado: todavía es pronto para concluir qué sobra.",
    };
  });

  it("enseña qué declara el módulo y bajo qué espacio de nombres vive", async () => {
    abrir();
    const caja = await screen.findByTestId("modulo-manifiesto");
    expect(caja.textContent).toContain("homologacion_mercado");
    expect(screen.getByText(/modulo\.espacioDeNombres/)).toBeInTheDocument();
  });

  it("enseña de qué depende y contra qué núcleo", async () => {
    abrir();
    expect(await screen.findByText(/calidad >=2.0/)).toBeInTheDocument();
  });

  it("sin huella lo dice, en vez de dejar el hueco", async () => {
    modulo = { ...(modulo as Record<string, unknown>), huella: "" };
    abrir();
    expect(await screen.findByText("modulo.sinHuella")).toBeInTheDocument();
  });

  it("lo desaparecido se pinta igual que lo tocado a mano", async () => {
    abrir();
    const caja = await screen.findByTestId("modulo-integridad");
    expect(caja.textContent).toContain("campos.norma");
    expect(caja.textContent).toContain("campos.vence_at");
  });

  it("cuando no se puede comparar, lo dice y no da el visto bueno", async () => {
    integridad = {
      modulo: "homologaciones",
      medible: false,
      motivo:
        "La versión 1.0.0 ya no está en el catálogo: no se puede comparar.",
    };
    abrir();
    const caja = await screen.findByTestId("modulo-integridad");
    expect(caja.textContent).toContain("ya no está en el catálogo");
    expect(caja.textContent).not.toContain("modulo.integro");
  });

  it("avisa de que es pronto ANTES de enseñar lo que no se usa", async () => {
    abrir();
    const caja = await screen.findByTestId("modulo-telemetria");
    expect(caja.textContent).toContain("todavía es pronto");
    const aviso = caja.textContent?.indexOf("todavía es pronto") ?? -1;
    const lista = caja.textContent?.indexOf("modulo.sinUsar") ?? -1;
    expect(aviso).toBeGreaterThan(-1);
    expect(lista).toBeGreaterThan(aviso);
  });

  it("lo que no se usa sale por su nombre, no como [object Object]", async () => {
    // Así lo devuelve el servidor (medido el 09-11-2026): cada elemento con su
    // sección, su clave con prefijo y su nombre sin él.
    telemetria = {
      ...(telemetria as Record<string, unknown>),
      sin_usar: [
        {
          seccion: "conectores",
          clave: "zzaudhijo__zzaud_taller",
          nombre: "zzaud_taller",
        },
      ],
    };
    abrir();
    const caja = await screen.findByTestId("modulo-telemetria");
    expect(caja.textContent).toContain("zzaud_taller");
    expect(caja.textContent).not.toContain("[object Object]");
  });

  it("enseña las pantallas que el módulo declara", async () => {
    abrir();
    expect(
      (await screen.findByTestId("modulo-pantallas")).textContent,
    ).toContain("Homologaciones");
  });

  // Quitarlo, con el ensayo delante (CRM-00.04.04.02, CRM-00.04.04.09). La
  // ruta existía y la pantalla prometía «lo que se borra y lo que se queda,
  // antes de tocar el botón» sin tener ni lo uno ni el botón.
  it("antes de quitarlo dice qué pasaría, y el ensayo no quita nada", async () => {
    abrir();
    fireEvent.click(await screen.findByText("modulo.verQuePasaria"));
    const caja = await screen.findByTestId("modulo-quitar");
    expect(
      await screen.findByText(/homologacion_mercado 120/),
    ).toBeInTheDocument();
    expect(caja.textContent).toContain("certificado_mercado");
    expect(caja.textContent).toContain("campos.norma");
    expect(caja.textContent).toContain("se CONSERVAN");
    const ensayos = vi
      .mocked(llamar)
      .mock.calls.filter(([r]) => String(r).endsWith("/desinstalar"));
    expect(ensayos).toHaveLength(1);
    expect(ensayos[0]?.[1]).toMatchObject({
      cuerpo: { aplicar: false, borrar_datos: false },
    });
  });

  it("si otro módulo depende de este, no ofrece quitarlo y dice cuál", async () => {
    ensayo = {
      ...(ensayo as Record<string, unknown>),
      modulos_que_dependen: ["calidad"],
      se_puede_desinstalar: false,
    };
    abrir();
    fireEvent.click(await screen.findByText("modulo.verQuePasaria"));
    expect(
      await screen.findByText(/modulo\.dependen.*calidad/),
    ).toBeInTheDocument();
    expect(screen.queryByText("modulo.quitarDeVerdad")).toBeNull();
  });

  it("quitarlo de verdad manda aplicar con lo elegido sobre los datos", async () => {
    abrir();
    fireEvent.click(await screen.findByText("modulo.verQuePasaria"));
    fireEvent.click(await screen.findByLabelText("modulo.borrarDatos"));
    fireEvent.click(await screen.findByText("modulo.quitarDeVerdad"));
    await vi.waitFor(() => {
      const ultima = vi
        .mocked(llamar)
        .mock.calls.filter(([r]) => String(r).endsWith("/desinstalar"))
        .at(-1);
      expect(ultima?.[1]).toMatchObject({
        cuerpo: { aplicar: true, borrar_datos: true },
      });
    });
  });
});
