/**
 * La ficha de una oportunidad: lo que hace falta para cerrarla.
 *
 * Antes era la ficha genérica, un volcado de campos. Con eso delante no se
 * contesta «¿cómo vamos con esta venta?», que es para lo que se abre.
 *
 * Y tres de sus paneles enseñan cosas que **se guardaban y no leía nadie**: el
 * reparto entre comerciales y las oportunidades relacionadas vivían en su
 * tabla, consultadas sólo por su propio escritor para reemplazar filas.
 *
 * Se afirma el dato que sólo puede venir de la respuesta de su ruta. Validado
 * plantando: quitar cada panel pone en rojo su prueba y sólo la suya.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pedidas: string[] = [];

const OP = {
  id: "o-1",
  codigo: "OPP-7",
  nombre: "Renovación Acme",
  cuenta_id: "a-1",
  pipeline: "Nuevo negocio",
  etapa: "Propuesta",
  importe: "120000",
  moneda: "EUR",
  probabilidad: 60,
  importe_ponderado: "72000",
  fecha_cierre: "2026-12-31",
  estado: "abierta",
  categoria_forecast: "probable",
  etapa_desde: null,
  bloqueada: false,
};

let EVALUACION: Record<string, unknown> = {
  puntuacion: 62,
  criterios: 6,
  cubiertos: 4,
  lo_que_falta: ["No hay criterio de decisión declarado", "Falta el campeón"],
  siguiente_paso: "Pregunta quién firma",
  cualificada: false,
};

let PLAYBOOK: Record<string, unknown> | null = {
  clave: "negociacion",
  titulo: "Qué hacer en negociación",
  pasos: ["Confirma el presupuesto", "Pide la fecha de firma"],
  por_que: "Elegido por la etapa «negociacion» y el segmento por defecto.",
};

let PLANES: unknown[] = [
  { id: "pc-1", oportunidad_id: "o-1", fecha_objetivo: "2026-12-01" },
];

let PLAN: Record<string, unknown> | null = {
  pasos: 8,
  hechos: 3,
  retrasados_nuestros: [{ paso: "Mandar la propuesta técnica" }],
  retrasados_del_cliente: [{ paso: "Validar con legal" }, { paso: "Confirmar aforo" }],
  retrasados_conjuntos: [],
  compartido: true,
  visto_por_el_cliente: "2026-10-20T10:00:00Z",
  la_fecha_es_creible: false,
  que_significa: "",
  aviso: "",
};

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      pedidas.push(ruta);
      let datos: unknown = {};
      if (ruta === "/api/v1/opportunities/o-1") datos = OP;
      else if (ruta === "/api/v1/opportunities/o-1/lineas")
        datos = {
          items: [
            {
              id: "l-1",
              descripcion: "Suscripción anual",
              cantidad: "10",
              precio_unitario: "1000",
              descuento_pct: "0",
              total: "10000",
              tipo: "recurrente",
            },
          ],
        };
      else if (ruta === "/api/v1/ingresos/metricas")
        datos = {
          arr: "10000.00",
          mrr: "833.33",
          tcv: "12000.00",
          acv: "12000.00",
          puntual: "2000.00",
          hay_recurrente: true,
          porque: "El ARR sale solo de lo recurrente.",
          lo_que_no_cuenta_como_arr: ["implantacion"],
        };
      else if (ruta === "/api/v1/ingresos/de/o-1")
        datos = {
          reparto: [
            { usuario_id: "u-1", papel: "credito", porcentaje: "60.00", motivo: "lo cerró" },
          ],
          credito_total: "60.00",
          credito_cuadra: false,
          porque_el_overlay_no_suma: "El overlay es apoyo que no resta al titular.",
          relacionadas: [{ tipo: "renovacion", sentido: "sale_de_aqui", otra_id: "o-2" }],
        };
      else if (ruta === "/api/v1/ingresos/grupo-compra/o-1")
        datos = {
          roles: { economico: [{ contacto_id: "c-1", postura: 0, motivo: "", hablado: false }] },
          faltan_por_identificar: ["tecnico"],
          clave_sin_hablar: ["c-1"],
          en_contra: 0,
          completo: false,
          que_mirar: "Falta el técnico y al económico no se le ha visto.",
        };
      else if (ruta.includes("historial-prevision"))
        datos = [
          {
            campo: "fecha_cierre",
            anterior: "2026-09-30",
            nuevo: "2026-12-31",
            dias_deslizados: 92,
            delta_importe: null,
            motivo: null,
            at: "2026-10-01T10:00:00+00:00",
          },
        ];
      else if (ruta.startsWith("/api/v1/metodologias?activa=true"))
        datos = [{ id: "me-1", clave: "meddic", nombre: "MEDDIC", activa: true }];
      else if (ruta === "/api/v1/metodologias/me-1/oportunidad/o-1") datos = EVALUACION;
      else if (ruta.startsWith("/api/v1/metodologias/playbook")) datos = PLAYBOOK;
      else if (ruta.startsWith("/api/v1/planes-conjuntos?oportunidad_id="))
        datos = PLANES;
      else if (ruta === "/api/v1/planes-conjuntos/pc-1/estado") datos = PLAN;
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
  const { Oportunidad } = await import("@/paginas/Oportunidad");
  return render(
    <MemoryRouter initialEntries={["/m/oportunidades/oportunidad/o-1"]}>
      <Routes>
        <Route path="/m/oportunidades/oportunidad/:id" element={<Oportunidad />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("la ficha de una venta", () => {
  beforeEach(() => {
    pedidas.length = 0;
  });

  it("enseña las líneas y pide el ARR al servicio que sabe calcularlo", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("Suscripción anual")).toBeTruthy());
    // El ARR NO se calcula aquí: se manda a quien sabe qué es recurrente.
    // Calcularlo en la pantalla mete la implantación dentro y deja dos sitios
    // donde se calcula, que acaban diciendo cosas distintas.
    expect(pedidas).toContain("/api/v1/ingresos/metricas");
    // `/^ARR/` y no `/ARR/`: el aviso de lo que no cuenta también lo nombra, y
    // buscar suelto encuentra dos y no dice si se ha pintado la métrica.
    await waitFor(() => expect(screen.getByText(/^ARR /)).toBeTruthy());
    // Y lo que NO cuenta como ARR, dicho: sin eso el número se cita en un
    // comité como si fuera todo lo que entra.
    expect(screen.getByText(/oportunidad.noCuentaComoArr.*implantacion/)).toBeTruthy();
  });

  it("dice quién decide y, sobre todo, quién falta", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("economico")).toBeTruthy());
    expect(screen.getByText("oportunidad.sinHablar")).toBeTruthy();
    // Lo que falta es la mitad que hace útil el panel.
    expect(
      screen.getByText("Falta el técnico y al económico no se le ha visto."),
    ).toBeTruthy();
  });

  it("enseña el reparto y AVISA de que no cuadra", async () => {
    await montar();
    await waitFor(() =>
      expect(screen.getByText(/oportunidad.creditoTotal.*60.00/)).toBeTruthy(),
    );
    // Un 60 % solo tiene que verse como lo que es. Con repartos al 60/60 las
    // comisiones cuadran hacia arriba y el descuadre lo encuentra finanzas
    // tres meses después.
    expect(screen.getByText(/oportunidad.noCuadra/)).toBeTruthy();
    // Y de qué lado está ésta en la relación.
    expect(screen.getByText(/oportunidad.sentido.sale_de_aqui/)).toBeTruthy();
  });

  it("enseña lo que se ha movido, y que se movió sin motivo", async () => {
    await montar();
    await waitFor(() =>
      expect(screen.getByText(/oportunidad.deslizada.*92/)).toBeTruthy(),
    );
    // Un movimiento sin motivo es el que no se puede discutir; decirlo es lo
    // que hace que la próxima vez se escriba.
    expect(screen.getByText("oportunidad.sinMotivo")).toBeTruthy();
  });
});

// ── Qué falta para cerrar, y el plan con el cliente ─────────────────────
//
// Tres cosas que el servidor ya daba y no enseñaba nadie, y las tres se
// afirman por lo mismo: un número sin su porqué al lado no cambia lo que
// alguien hace.

// Los dobles se reponen entre pruebas: dos de abajo los cambian, y un doble
// mutado se lo encuentra la siguiente prueba sin saberlo — que es como una
// suite empieza a depender del orden.
const EVALUACION_BASE = { ...EVALUACION };
const PLAYBOOK_BASE = { ...(PLAYBOOK as Record<string, unknown>) };
const PLANES_BASE = [...PLANES];
const PLAN_BASE = { ...(PLAN as Record<string, unknown>) };

beforeEach(() => {
  EVALUACION = { ...EVALUACION_BASE };
  PLAYBOOK = { ...PLAYBOOK_BASE };
  PLANES = [...PLANES_BASE];
  PLAN = { ...PLAN_BASE };
});

describe("qué falta para poder cerrar", () => {
  it("la puntuación va con lo que falta, no sola", async () => {
    await montar();
    await screen.findByText(
      'oportunidad.cubiertos:{"cubiertos":4,"criterios":6,"puntuacion":62}',
    );
    // Y lo que falta, enumerado: la nota sola no dice qué hacer.
    expect(
      screen.getByText("No hay criterio de decisión declarado"),
    ).toBeInTheDocument();
    expect(screen.getByText("Falta el campeón")).toBeInTheDocument();
    expect(
      screen.getByText('oportunidad.siguientePaso:{"paso":"Pregunta quién firma"}'),
    ).toBeInTheDocument();
  });

  it("y dice si está cualificada o no", async () => {
    await montar();
    await screen.findByText("oportunidad.noCualificada");
    expect(screen.queryByText("oportunidad.cualificada")).not.toBeInTheDocument();
  });

  it("el playbook viene con el porqué se eligió ése", async () => {
    await montar();
    await screen.findByText("Qué hacer en negociación");
    expect(
      screen.getByText(/Elegido por la etapa «negociacion»/),
    ).toBeInTheDocument();
    expect(screen.getByText("Confirma el presupuesto")).toBeInTheDocument();
  });
});

describe("el plan con el cliente", () => {
  it("separa lo retrasado nuestro de lo retrasado del cliente", async () => {
    await montar();
    // Son dos conversaciones distintas: una dentro de casa y otra con él.
    expect(
      await screen.findByText('oportunidad.retrasoNuestro:{"cuantos":1}'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('oportunidad.retrasoDelCliente:{"cuantos":2}'),
    ).toBeInTheDocument();
    // Y no se pinta la categoría vacía.
    expect(screen.queryByText(/oportunidad\.retrasoConjunto/)).not.toBeInTheDocument();
  });

  it("dice si la fecha objetivo ya no se sostiene", async () => {
    await montar();
    expect(await screen.findByText("oportunidad.fechaNoCreible")).toBeInTheDocument();
  });

  it("un plan que el cliente no ha visto se señala", async () => {
    PLAN = { ...(PLAN as Record<string, unknown>), compartido: false };
    await montar();
    expect(await screen.findByText("oportunidad.planSinCompartir")).toBeInTheDocument();
  });

  it("sin plan lo dice, y dice qué significa no tenerlo", async () => {
    PLANES = [];
    await montar();
    expect(await screen.findByText("oportunidad.sinPlan")).toBeInTheDocument();
  });
});
