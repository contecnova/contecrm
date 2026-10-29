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
