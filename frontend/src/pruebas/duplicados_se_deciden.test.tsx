/**
 * Los duplicados se DECIDEN, no se miran.
 *
 * El barrido encontraba las parejas, el listado genérico las pintaba y ahí se
 * acababa: dieciocho tarjetas con dos nombres y una probabilidad. El servidor
 * sabía fusionar —eligiendo cuál se queda—, recordar que dos fichas no son la
 * misma y dejarlo para luego, y no había un solo botón. Circuito abierto.
 *
 * Lo que fijan estas pruebas es lo que convierte la lista en una herramienta,
 * y lo que más caro sale si se rompe:
 *
 *   · fusionar **pide elegir** cuál se queda, y no se puede pulsar sin ello:
 *     la que sobrevive conserva el identificador que usan los sistemas de
 *     fuera, y eso no lo sabe un algoritmo;
 *   · y **se confirma**, con los dos nombres puestos. Mezclar el histórico de
 *     dos clientes es difícil de deshacer;
 *   · «no son la misma» viaja como tal, que es lo que hace que el siguiente
 *     barrido no vuelva a proponerla. Si se mandara como «descartar», la cola
 *     reaparecería entera y se dejaría de mirar;
 *   · y lo que ha coincidido se ve al lado de cuánto: con un «90 %» a secas
 *     hay que abrir las dos fichas para saber qué se compara.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const enviado: { ruta: string; cuerpo: unknown }[] = [];
let cola: unknown[] = [];

async function montar() {
  vi.resetModules();
  enviado.length = 0;
  vi.doMock("@/lib/api", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/api");
    return {
      ...real,
      llamar: async (
        ruta: string,
        opciones?: { metodo?: string; cuerpo?: unknown },
      ) => {
        if ((opciones?.metodo ?? "GET") !== "GET") {
          enviado.push({ ruta, cuerpo: opciones?.cuerpo });
          return { datos: { revisadas: 120, propuestas: 3 } };
        }
        return { datos: cola };
      },
    };
  });
  const { Duplicados } = await import("@/paginas/Duplicados");
  return render(
    <MemoryRouter>
      <Duplicados />
    </MemoryRouter>,
  );
}

const PAREJA = {
  id: "d1",
  a_id: "cuenta-a",
  b_id: "cuenta-b",
  a_nombre: "Plásticos Ebro, S.A.U.",
  b_nombre: "Plásticos Ebro Valencia, S.L.U.",
  probabilidad: 90,
  senales: ["forma_juridica_distinta", "dominio"],
  concluyente: true,
  decision: "",
  decidido_at: null,
  nota: "",
};

describe("la cola de duplicados", () => {
  beforeEach(() => {
    cola = [PAREJA];
  });

  it("no se puede fusionar sin decir cuál de las dos se queda", async () => {
    const usuario = userEvent.setup();
    await montar();
    await screen.findByText("Plásticos Ebro, S.A.U.");

    expect(
      screen.getByRole("button", { name: "duplicados.fusionar" }),
    ).toBeDisabled();
    expect(screen.getByText("duplicados.eligeCual")).toBeInTheDocument();

    await usuario.click(screen.getAllByRole("radio")[0]!);
    expect(
      screen.getByRole("button", { name: "duplicados.fusionar" }),
    ).toBeEnabled();
  });

  it("fusionar se confirma y manda la que se queda", async () => {
    const usuario = userEvent.setup();
    await montar();
    await screen.findByText("Plásticos Ebro, S.A.U.");

    await usuario.click(screen.getAllByRole("radio")[0]!);
    await usuario.click(
      screen.getByRole("button", { name: "duplicados.fusionar" }),
    );

    // Primero avisa de lo que va a pasar, y todavía no ha mandado nada.
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(enviado).toHaveLength(0);

    await usuario.click(
      screen.getByRole("button", { name: "duplicados.siFusiona" }),
    );
    expect(enviado).toHaveLength(1);
    expect(enviado[0]!.ruta).toContain("/duplicates/cola/d1");
    expect(enviado[0]!.cuerpo).toMatchObject({
      decision: "fusionar",
      superviviente_id: "cuenta-a",
    });
  });

  it("«no son la misma» no es «dejarlo para luego»", async () => {
    const usuario = userEvent.setup();
    await montar();
    await screen.findByText("Plásticos Ebro, S.A.U.");

    await usuario.click(
      screen.getByRole("button", { name: "duplicados.noSonLaMisma" }),
    );
    // Es la decisión que el servidor RECUERDA: mandarla como «descartar»
    // haría que el siguiente barrido volviera a proponer la misma pareja, y
    // una cola que reaparece entera se deja de mirar.
    expect(enviado[0]!.cuerpo).toMatchObject({ decision: "no_es_duplicado" });

    enviado.length = 0;
    await usuario.click(
      screen.getByRole("button", { name: "duplicados.paraLuego" }),
    );
    expect(enviado[0]!.cuerpo).toMatchObject({ decision: "descartar" });
  });

  it("se ve en qué se parecen, no sólo cuánto", async () => {
    await montar();
    await screen.findByText("Plásticos Ebro, S.A.U.");
    expect(screen.getByText(/duplicados.probabilidad/)).toBeInTheDocument();
    expect(screen.getByText("Forma juridica distinta")).toBeInTheDocument();
    expect(screen.getByText("Dominio")).toBeInTheDocument();
    // Y se puede abrir cada ficha: si son dos empresas distintas que se
    // parecen, lo que hace falta es cambiar algo en una.
    const fichas = screen.getAllByText("duplicados.abrirFicha");
    expect(fichas).toHaveLength(2);
    expect(fichas[0]!.getAttribute("href")).toBe("/m/cuentas/cuenta/cuenta-a");
  });

  it("una pareja ya decidida se enseña decidida y sin botones", async () => {
    cola = [
      {
        ...PAREJA,
        decision: "no_es_duplicado",
        decidido_at: "2026-10-28T06:00:00Z",
      },
    ];
    await montar();
    await screen.findByText("Plásticos Ebro, S.A.U.");
    expect(
      screen.queryByRole("button", { name: "duplicados.fusionar" }),
    ).toBeNull();
    // El rótulo sale de `duplicados.decision.<la decisión>`, con la propia
    // decisión como respaldo: una decisión nueva en el servidor se enseña por
    // su nombre en vez de dejar la insignia en blanco.
    expect(
      screen.getByText(/no_es_duplicado|No son la misma/),
    ).toBeInTheDocument();
  });

  it("el barrido dice cuántas fichas ha mirado", async () => {
    const usuario = userEvent.setup();
    await montar();
    await screen.findByText("Plásticos Ebro, S.A.U.");
    await usuario.click(
      screen.getByRole("button", { name: /duplicados.buscar/ }),
    );
    // «Hecho» a secas no dice si ha mirado tres fichas o tres mil.
    expect(screen.getByText(/duplicados.resultadoBarrido/)).toBeInTheDocument();
  });
});
