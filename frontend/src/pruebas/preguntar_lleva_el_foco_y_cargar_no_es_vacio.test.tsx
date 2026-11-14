/**
 * Lo que arregla la auditoría del 13-11-2026 en estados y foco, fijado para
 * que no vuelva:
 *
 *   · UX-7: una pregunta en línea (`role="alertdialog"`) lleva el foco al
 *     botón seguro al abrirse y lo devuelve al cerrarse. Sin eso, con teclado
 *     o lector no se sabe que se está preguntando nada;
 *   · UX-10: «todavía no ha llegado» no se pinta como «no hay nada»;
 *   · COB-3: una versión de modelo se activa —o se vuelve a una anterior—
 *     desde la pantalla, preguntando antes y con la ruta del servidor.
 *
 * Los rótulos se comprueban por su clave de traducción, como en el resto.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useRef, useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { useFocoDeConfirmacion } from "@/lib/foco";

type Doble = (
  ruta: string,
  opciones?: { metodo?: string; cuerpo?: unknown },
) => unknown;

const pedidas: { ruta: string; metodo: string }[] = [];

async function con(doble: Doble, { puede = true } = {}) {
  vi.resetModules();
  pedidas.length = 0;
  vi.doMock("@/lib/api", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/api");
    return {
      ...real,
      llamar: async (
        ruta: string,
        opciones?: { metodo?: string; cuerpo?: unknown },
      ) => {
        pedidas.push({ ruta, metodo: (opciones?.metodo ?? "GET").toUpperCase() });
        return { datos: await doble(ruta, opciones) };
      },
    };
  });
  vi.doMock("@/lib/permisos", async () => {
    const real =
      await vi.importActual<Record<string, unknown>>("@/lib/permisos");
    return { ...real, usePuedeOperar: () => () => puede };
  });
}

/** Una pregunta mínima con el mismo hook que usan las pantallas. */
function Pregunta({ tomaElFoco }: { tomaElFoco: boolean }) {
  const [abierta, setAbierta] = useState(false);
  const [hecho, setHecho] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setAbierta(true)}>
        abrir
      </button>
      {abierta ? (
        <Dialogo
          alCancelar={() => setAbierta(false)}
          alAceptar={() => {
            setAbierta(false);
            setHecho(true);
          }}
        />
      ) : null}
      {hecho && tomaElFoco ? <Siguiente /> : null}
    </>
  );
}

function Dialogo({
  alCancelar,
  alAceptar,
}: {
  alCancelar: () => void;
  alAceptar: () => void;
}) {
  const seguro = useRef<HTMLButtonElement>(null);
  useFocoDeConfirmacion(seguro);
  return (
    <div role="alertdialog" aria-label="pregunta">
      <button type="button" onClick={alAceptar}>
        sí
      </button>
      <button ref={seguro} type="button" onClick={alCancelar}>
        no
      </button>
    </div>
  );
}

/** Lo que sale después y coge el foco por su cuenta. */
function Siguiente() {
  const ref = useRef<HTMLButtonElement>(null);
  // Como el botón de ejecutar de `Acciones` tras «Lo entiendo».
  useEffect(() => ref.current?.focus(), []);
  return (
    <button ref={ref} type="button">
      ejecutar
    </button>
  );
}

describe("UX-7: el foco de una pregunta en línea", () => {
  it("entra en el botón seguro y vuelve al que la abrió", async () => {
    const u = userEvent.setup();
    render(<Pregunta tomaElFoco={false} />);
    await u.click(screen.getByRole("button", { name: "abrir" }));
    expect(screen.getByRole("button", { name: "no" })).toHaveFocus();
    await u.keyboard("{Enter}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("button", { name: "abrir" })).toHaveFocus();
  });

  it("no le quita el foco a lo que sale después y lo ha cogido", async () => {
    const u = userEvent.setup();
    render(<Pregunta tomaElFoco />);
    await u.click(screen.getByRole("button", { name: "abrir" }));
    await u.click(screen.getByRole("button", { name: "sí" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "ejecutar" })).toHaveFocus(),
    );
  });

  it("en duplicados: «Mejor no» al abrir y «Fusionar» al cancelar", async () => {
    await con(() => [
      {
        id: "d1",
        a_id: "cuenta-a",
        b_id: "cuenta-b",
        a_nombre: "Plásticos Ebro, S.A.U.",
        b_nombre: "Plásticos Ebro Valencia, S.L.U.",
        probabilidad: 90,
        senales: ["dominio"],
        concluyente: true,
        decision: "",
        decidido_at: null,
        nota: "",
      },
    ]);
    const { Duplicados } = await import("@/paginas/Duplicados");
    const u = userEvent.setup();
    render(
      <MemoryRouter>
        <Duplicados />
      </MemoryRouter>,
    );
    await screen.findByText("Plásticos Ebro, S.A.U.");
    await u.click(screen.getAllByRole("radio")[0]!);
    await u.click(screen.getByRole("button", { name: "duplicados.fusionar" }));

    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "duplicados.mejorNo" }),
    ).toHaveFocus();

    await u.click(screen.getByRole("button", { name: "duplicados.mejorNo" }));
    // «Fusionar» es OTRO nodo —se ha vuelto a pintar—, y aun así recibe el
    // foco: se devuelve por referencia, no a «donde estaba».
    expect(
      screen.getByRole("button", { name: "duplicados.fusionar" }),
    ).toHaveFocus();
  });
});

describe("UX-10: cargando no es vacío", () => {
  it("los canales dicen que cargan mientras cargan, y que no hay cuando no hay", async () => {
    let soltar: (v: unknown) => void = () => undefined;
    const llegada = new Promise((r) => {
      soltar = r;
    });
    await con((ruta) =>
      ruta.startsWith("/api/v1/canales-marketing") ? llegada : {},
    );
    const { Canales } = await import("@/paginas/Canales");
    render(
      <MemoryRouter>
        <Canales />
      </MemoryRouter>,
    );
    await screen.findByText("canalesmk.declarados");
    expect(screen.getByText("app.cargando")).toBeInTheDocument();
    expect(screen.queryByText("canalesmk.sinCanales")).toBeNull();

    soltar([]);
    expect(await screen.findByText("canalesmk.sinCanales")).toBeInTheDocument();
    expect(screen.queryByText("app.cargando")).toBeNull();
  });
});

describe("COB-3: activar una versión de modelo", () => {
  const VERSIONES = {
    entrenables: { cierre: "oportunidad" },
    versiones: [
      {
        id: "m2",
        tipo: "cierre",
        version: 2,
        estado: "activa",
        origen: "historico",
        metricas: { auc: 0.62, muestras: 114 },
        ejemplos: 458,
        ventana: "",
        entrenado_at: null,
        notas: "",
      },
      {
        id: "m1",
        tipo: "cierre",
        version: 1,
        estado: "retirada",
        origen: "historico",
        metricas: { auc: 0.71, muestras: 98 },
        ejemplos: 400,
        ventana: "",
        entrenado_at: null,
        notas: "",
      },
    ],
  };

  function doble(ruta: string) {
    if (ruta.endsWith("/predictivo/versiones")) return VERSIONES;
    if (ruta.endsWith("/programaciones")) return [];
    if (ruta.endsWith("/activar"))
      return {
        tipo: "cierre",
        version: 1,
        comparacion: {
          habia_anterior: true,
          metrica: "auc",
          anterior: 0.62,
          nueva: 0.71,
          mejora: true,
          aviso: "",
        },
      };
    return {};
  }

  it("se vuelve a una anterior preguntando antes, con la ruta del servidor", async () => {
    await con(doble);
    const { ModelosPredictivos } = await import("@/paginas/ModelosPredictivos");
    const u = userEvent.setup();
    render(
      <MemoryRouter>
        <ModelosPredictivos />
      </MemoryRouter>,
    );
    // La v1 es anterior a la que puntúa: se ofrece como «volver», no como
    // «activar». Y la que puntúa no ofrece nada.
    const volver = await screen.findByRole("button", {
      name: "modelosPredictivos.volverAVersion",
    });
    expect(
      screen.queryByRole("button", { name: "modelosPredictivos.activarVersion" }),
    ).toBeNull();

    await u.click(volver);
    // Antes de mandar nada, se pregunta, con el foco en «Cancelar».
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "modulo.cancelar" })).toHaveFocus();
    expect(pedidas.some((p) => p.ruta.endsWith("/activar"))).toBe(false);

    await u.click(
      screen.getByRole("button", { name: "modelosPredictivos.siActivar" }),
    );
    expect(
      await screen.findByText("modelosPredictivos.activada"),
    ).toBeInTheDocument();
    const activar = pedidas.find((p) => p.ruta.endsWith("/activar"));
    expect(activar).toEqual({
      ruta: "/api/v1/ia/modelos/cierre/versiones/1/activar",
      metodo: "POST",
    });
    // Y se vuelve a pedir la lista, para que diga cuál puntúa ahora.
    expect(
      pedidas.filter((p) => p.ruta.endsWith("/predictivo/versiones")).length,
    ).toBe(2);
  });

  it("cancelar no manda nada", async () => {
    await con(doble);
    const { ModelosPredictivos } = await import("@/paginas/ModelosPredictivos");
    const u = userEvent.setup();
    render(
      <MemoryRouter>
        <ModelosPredictivos />
      </MemoryRouter>,
    );
    await u.click(
      await screen.findByRole("button", {
        name: "modelosPredictivos.volverAVersion",
      }),
    );
    await u.click(screen.getByRole("button", { name: "modulo.cancelar" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(pedidas.some((p) => p.ruta.endsWith("/activar"))).toBe(false);
  });

  it("sin permiso no se ofrece", async () => {
    await con(doble, { puede: false });
    const { ModelosPredictivos } = await import("@/paginas/ModelosPredictivos");
    render(
      <MemoryRouter>
        <ModelosPredictivos />
      </MemoryRouter>,
    );
    await screen.findByText("modelosPredictivos.versiones", {
      selector: "h2",
    });
    expect(
      screen.queryByRole("button", { name: /modelosPredictivos\.(activar|volverA)/ }),
    ).toBeNull();
    expect(screen.queryByText("modelosPredictivos.col.accion")).toBeNull();
  });
});
