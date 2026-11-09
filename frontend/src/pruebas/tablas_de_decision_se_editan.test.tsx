/**
 * El editor de tablas de decisión, PINTADO y usado (CRM-00.03.02.10).
 *
 * Constaba hecho con sólo la API: la pantalla era la ficha genérica, que
 * pintaba las reglas como texto y editaba con PATCH una tabla que se guarda
 * entera con PUT. Aquí se comprueba que la rejilla sale con una fila por regla
 * y una casilla por condición, que lo que se teclea llega a la API con el TIPO
 * de su columna —un «50000» de texto comparado con un número da falso sin
 * avisar— y que validar, probar y guardar llaman a lo que tienen que llamar.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aTablaApi, TablaDeDecision } from "@/paginas/TablaDeDecision";

const llamadas: { ruta: string; metodo?: string; cuerpo?: unknown }[] = [];
let respuestas: Record<string, unknown> = {};

vi.mock("@/lib/api", () => ({
  ErrorApi: class extends Error {},
  llamar: vi.fn(
    async (ruta: string, op: { metodo?: string; cuerpo?: unknown } = {}) => {
      llamadas.push({ ruta, metodo: op.metodo, cuerpo: op.cuerpo });
      const clave = Object.keys(respuestas)
        .filter((k) => ruta.startsWith(k))
        .sort((a, b) => b.length - a.length)[0];
      if (!clave) throw new Error(`sin respuesta preparada para ${ruta}`);
      return { datos: respuestas[clave] };
    },
  ),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

const TABLA = {
  clave: "quien_aprueba",
  nombre: "Quién aprueba el descuento",
  politica: "primera",
  activa: true,
  entradas: [
    {
      clave: "importe",
      etiqueta: "Importe",
      expresion: "@oportunidad.importe",
      tipo: "numero",
    },
  ],
  salidas: [{ clave: "aprobador", etiqueta: "Aprobador", tipo: "texto" }],
  reglas: [
    {
      nombre: "grande",
      condiciones: [{ entrada: "importe", op: ">=", valor: 50000 }],
      salidas: { aprobador: "director" },
    },
    { nombre: "resto", condiciones: [], salidas: { aprobador: "jefe" } },
  ],
};

function abrir(ruta = "/m/procesos/tablas-decision/quien_aprueba") {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <Routes>
        <Route
          path="/m/procesos/tablas-decision/:clave"
          element={<TablaDeDecision />}
        />
        <Route path="/tablas-decision/nueva" element={<TablaDeDecision />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("el editor de tablas de decisión", () => {
  beforeEach(() => {
    llamadas.length = 0;
    respuestas = { "/api/v1/tablas-decision/quien_aprueba": TABLA };
  });

  it("convierte lo tecleado al tipo de su columna", () => {
    const api = aTablaApi(
      { nombre: "t", politica: "prioridad", activa: true },
      [
        { clave: "importe", expresion: "@importe", tipo: "numero" },
        { clave: "pais", expresion: "@pais", tipo: "texto" },
        { clave: "vip", expresion: "@vip", tipo: "booleano" },
      ],
      [{ clave: "nivel", tipo: "numero" }, { clave: "nota" }],
      [
        {
          id: "a",
          nombre: "r1",
          prioridad: "5",
          condiciones: {
            importe: [
              { op: ">=", valor: "1000,5" },
              { op: "<", valor: "@limite" },
            ],
            pais: [{ op: "en", valor: "ES, PT" }],
            vip: [{ op: "no_vacio", valor: "x" }],
          },
          salidas: { nivel: "2", nota: "" },
        },
      ],
    );
    const regla = api.reglas[0]!;
    expect(regla.condiciones).toEqual([
      { entrada: "importe", op: ">=", valor: 1000.5 },
      { entrada: "importe", op: "<", valor: "@limite" },
      { entrada: "pais", op: "en", valor: ["ES", "PT"] },
      { entrada: "vip", op: "no_vacio", valor: null },
    ]);
    // La salida vacía no se manda: una regla «sin salida» es un error claro, y
    // un "" mandado como valor sería una respuesta inventada.
    expect(regla.salidas).toEqual({ nivel: 2 });
    expect(regla.prioridad).toBe(5);
  });

  it("pinta una fila por regla y una casilla por condición", async () => {
    abrir();
    const filas = await screen.findAllByRole("row", {
      name: /tablasDecision\.reglaN:/,
    });
    expect(filas).toHaveLength(2);
    expect(within(filas[0]!).getByDisplayValue("50000")).toBeInTheDocument();
    expect(within(filas[0]!).getByDisplayValue("director")).toBeInTheDocument();
    // La regla sin condiciones dice «cualquiera», no una casilla vacía.
    expect(
      within(filas[1]!).getByText("tablasDecision.cualquiera"),
    ).toBeInTheDocument();
  });

  it("añadir, ordenar y quitar reglas", async () => {
    const usuario = userEvent.setup();
    abrir();
    await screen.findAllByRole("row", { name: /tablasDecision\.reglaN:/ });
    await usuario.click(
      screen.getByRole("button", { name: "tablasDecision.anadirRegla" }),
    );
    expect(
      screen.getAllByRole("row", { name: /tablasDecision\.reglaN:/ }),
    ).toHaveLength(3);
    // Subir la segunda la pone primera.
    await usuario.click(
      screen.getAllByRole("button", { name: "tablasDecision.subir" })[1]!,
    );
    const primera = screen.getAllByRole("row", {
      name: /tablasDecision\.reglaN:/,
    })[0]!;
    expect(within(primera).getByDisplayValue("resto")).toBeInTheDocument();
    await usuario.click(
      screen.getByRole("button", {
        name: 'tablasDecision.quitarRegla:{"n":3}',
      }),
    );
    expect(
      screen.getAllByRole("row", { name: /tablasDecision\.reglaN:/ }),
    ).toHaveLength(2);
  });

  it("probar manda la tabla de la pantalla y los datos donde los lee la expresión", async () => {
    const usuario = userEvent.setup();
    respuestas["/api/v1/tablas-decision/probar"] = {
      salidas: { aprobador: "director" },
      entradas: { importe: 60000 },
      por_defecto: false,
      reglas: [
        {
          indice: 0,
          nombre: "grande",
          caso: true,
          salidas: { aprobador: "director" },
        },
        {
          indice: 1,
          nombre: "resto",
          caso: true,
          salidas: { aprobador: "jefe" },
        },
      ],
    };
    abrir();
    await screen.findAllByRole("row", { name: /tablasDecision\.reglaN:/ });
    await usuario.type(screen.getByLabelText("Importe"), "60000");
    await usuario.click(
      screen.getByRole("button", { name: "tablasDecision.probarBoton" }),
    );
    await waitFor(() =>
      expect(
        llamadas.some((l) => l.ruta === "/api/v1/tablas-decision/probar"),
      ).toBe(true),
    );
    const prueba = llamadas.find(
      (l) => l.ruta === "/api/v1/tablas-decision/probar",
    )!;
    const cuerpo = prueba.cuerpo as {
      tabla: { reglas: unknown[] };
      variables: unknown;
    };
    expect(cuerpo.variables).toEqual({ oportunidad: { importe: 60000 } });
    expect(cuerpo.tabla.reglas).toHaveLength(2);
    expect(await screen.findByText("director")).toBeInTheDocument();
  });

  it("validar enseña los huecos, y guardar va por PUT a su clave", async () => {
    const usuario = userEvent.setup();
    respuestas["/api/v1/tablas-decision/validar"] = {
      valida: true,
      problemas: [],
      analisis: {
        solapes: [],
        inalcanzables: [],
        huecos: [{ entrada: "importe", desde: null, hasta: 0 }],
        sin_red_de_seguridad: false,
        indecidibles: [],
      },
    };
    abrir();
    await screen.findAllByRole("row", { name: /tablasDecision\.reglaN:/ });
    await usuario.click(
      screen.getByRole("button", { name: "tablasDecision.validar" }),
    );
    expect(
      await screen.findByText(/tablasDecision\.huecos/),
    ).toBeInTheDocument();

    respuestas["/api/v1/tablas-decision/quien_aprueba"] = {
      clave: "quien_aprueba",
      analisis: {
        solapes: [],
        inalcanzables: [],
        huecos: [],
        sin_red_de_seguridad: false,
        indecidibles: [],
      },
    };
    await usuario.click(
      screen.getByRole("button", { name: "tablasDecision.guardar" }),
    );
    await waitFor(() =>
      expect(llamadas.some((l) => l.metodo === "PUT")).toBe(true),
    );
    const put = llamadas.find((l) => l.metodo === "PUT")!;
    expect(put.ruta).toBe("/api/v1/tablas-decision/quien_aprueba");
    expect((put.cuerpo as { politica: string }).politica).toBe("primera");
  });

  it("una tabla nueva saca la clave del nombre", async () => {
    const usuario = userEvent.setup();
    abrir("/tablas-decision/nueva");
    await usuario.type(
      screen.getByLabelText("tablasDecision.nombre"),
      "Tipo de IVA",
    );
    expect(screen.getByLabelText(/tablasDecision\.clave/)).toHaveValue(
      "tipo_de_iva",
    );
  });
});
