/**
 * Un segmento: a cuánta gente le llega, y a cuánta le llega dos veces.
 *
 * Lo que se afirma aquí es lo que de verdad decide antes de un envío:
 *
 *  · que el número que se enseña sea el de los **alcanzables**, y que el hueco
 *    hasta el bruto se NOMBRE. Planificar un envío a diez mil y que salga a
 *    siete mil sin saber por qué faltan tres mil es el caso que esto evita;
 *  · que una **foto congelada** no se enseñe igual que un dinámico: los dos
 *    dan un número con la misma cara, y sobre el segundo se manda un correo
 *    creyendo que es la gente de hoy;
 *  · que el solapamiento salga con el **porcentaje sobre cada uno de los dos**,
 *    porque mil comunes es mucho si el segmento tiene mil doscientos y poco si
 *    tiene cien mil.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

// El doble de i18next devuelve la CLAVE **con sus valores interpolados**. Sin
// los valores, afirmar `segmento.deLosCuales` no comprueba nada de lo que la
// pantalla pinta dentro: los dos números que explican el hueco podrían ser
// constantes y la prueba seguiría verde.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

let dinamico = true;
let esFoto = false;
const pedidas: string[] = [];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      pedidas.push(ruta);
      if (ruta.startsWith("/api/v1/segmentos/solapamiento"))
        return {
          datos: {
            a: "activos",
            b: "renovaciones",
            tamano_a: 1200,
            tamano_b: 100000,
            comunes: 1000,
            pct_de_a: 83.3,
            pct_de_b: 1,
            solo_a: 200,
            solo_b: 99000,
          },
        };
      if (ruta.endsWith("/tamano"))
        return {
          datos: {
            segmento: "activos",
            bruto: 10000,
            alcanzables: 7000,
            suprimidos: 3000,
            calculado_at: "2026-10-29T08:00:00Z",
            dinamico,
            es_foto_congelada: esFoto,
          },
        };
      if (ruta.endsWith("/congelar")) return { datos: { segmento: "activos", miembros: 7000 } };
      if (ruta === "/api/v1/segmentos")
        return {
          datos: [
            { id: "s-1", nombre: "Clientes activos" },
            { id: "s-2", nombre: "Renovaciones Q4" },
          ],
        };
      return {
        datos: {
          id: "s-1",
          clave: "activos",
          nombre: "Clientes activos",
          descripcion: "Los que compraron este año",
          objeto: "contacto",
          dinamico,
          definicion: {
            op: "y",
            hijos: [
              { campo: "estado", operador: "=", valor: "activo" },
              {
                op: "o",
                hijos: [
                  { campo: "sector", operador: "=", valor: "obra" },
                  { campo: "sector", operador: "=", valor: "industria" },
                ],
              },
            ],
          },
          excluye: ["s-9"],
          tamano: 7000,
          tamano_at: "2026-10-29T08:00:00Z",
        },
      };
    }),
  };
});

const { Segmento } = await import("@/paginas/Segmento");

function montar() {
  return render(
    <MemoryRouter initialEntries={["/m/segmentos/segmento/s-1"]}>
      <Routes>
        <Route path="/m/segmentos/segmento/:id" element={<Segmento />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  dinamico = true;
  esFoto = false;
  pedidas.length = 0;
  vi.clearAllMocks();
});

describe("el tamaño de un segmento", () => {
  it("enseña los alcanzables y NOMBRA lo que se cae por supresión", async () => {
    montar();
    expect(await screen.findByText("7000")).toBeInTheDocument();
    // El hueco, con sus dos números: sin él, 7000 se lee como «todos».
    expect(
      screen.getByText('segmento.deLosCuales:{"bruto":10000,"suprimidos":3000}'),
    ).toBeInTheDocument();
  });

  it("avisa cuando el número es una foto y no el estado de ahora", async () => {
    dinamico = false;
    esFoto = true;
    montar();
    expect(await screen.findByText("segmento.esFoto")).toBeInTheDocument();
    expect(screen.getByText("segmento.congeladoEtiqueta")).toBeInTheDocument();
    // Y no se ofrece congelar lo que ya está congelado.
    expect(screen.queryByText("segmento.congelar")).not.toBeInTheDocument();
  });

  it("deja congelar un dinámico, y dice cuántos quedan dentro", async () => {
    montar();
    await screen.findByText("7000");

    await userEvent.click(screen.getByText("segmento.congelar"));

    expect(
      await screen.findByText('segmento.congelado:{"cuantos":7000}'),
    ).toBeInTheDocument();
    expect(pedidas.some((r) => r.endsWith("/congelar"))).toBe(true);
  });
});

describe("el solapamiento", () => {
  it("se mide contra otro segmento y da el porcentaje sobre cada uno", async () => {
    montar();
    await screen.findByText("7000");

    await userEvent.selectOptions(screen.getByLabelText("segmento.contra"), "s-2");
    await userEvent.click(screen.getByText("segmento.medir"));

    expect(await screen.findByText("1000")).toBeInTheDocument();
    // Los dos porcentajes: 1000 comunes es el 83 % de uno y el 1 % del otro, y
    // con un solo porcentaje la decisión sale al revés.
    expect(
      screen.getByText('segmento.pctDeCada:{"a":83.3,"b":1}'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('segmento.solos:{"a":200,"b":99000}'),
    ).toBeInTheDocument();
  });

  it("no mide nada mientras no se elija contra quién", async () => {
    montar();
    await screen.findByText("7000");
    expect(screen.getByText("segmento.medir")).toBeDisabled();
  });
});

describe("la definición", () => {
  it("enseña las condiciones anidadas, no el JSON crudo", async () => {
    montar();
    await screen.findByText("7000");

    // Un «y» con un «o» dentro: si se aplanara, «(A o B) y no C» se leería
    // como otra cosa — que es justo lo que el árbol anidado existe para poder
    // expresar.
    expect(screen.getByText("segmento.y")).toBeInTheDocument();
    expect(screen.getByText("segmento.o")).toBeInTheDocument();
    expect(screen.getByText("estado")).toBeInTheDocument();
    expect(screen.getAllByText("sector")).toHaveLength(2);
  });

  it("dice que resta otro segmento, que no es lo mismo que una condición negada", async () => {
    montar();
    await screen.findByText("7000");
    expect(screen.getByText('segmento.excluye:{"cuantos":1}')).toBeInTheDocument();
  });
});
