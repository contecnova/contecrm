/**
 * Qué hay desplegado en cada entorno, y qué se ha tocado a mano.
 *
 * Lo que se afirma aquí:
 *
 *  · que un entorno **sin medir el drift no salga limpio**. Las dos cosas se
 *    ven igual de bien y significan lo contrario;
 *  · que lo **tocado a mano** y lo **desaparecido** se digan por separado: lo
 *    primero lo pisa el siguiente despliegue, lo segundo ya no está;
 *  · que **lo no comparado** se declare, porque un «limpio» calculado sobre la
 *    mitad no es un limpio;
 *  · y que si **no se puede volver atrás** se diga antes de pulsar.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

let porEntorno: Record<string, { desplegado: unknown; drift: unknown }>;

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      const entorno = ruta.split("/")[4] ?? "";
      const datos = porEntorno[entorno];
      if (!datos) throw new Error("sin datos");
      return { datos: ruta.endsWith("/drift") ? datos.drift : datos.desplegado };
    }),
  };
});

const { Entornos } = await import("@/paginas/Entornos");

const VACIO = { desplegado: { entorno: "x", hay: false, porque: "Nunca se desplegó" }, drift: { entorno: "x", medible: false, porque: "Sin paquete que comparar" } };

beforeEach(() => {
  porEntorno = {
    desarrollo: { ...VACIO },
    pruebas: { ...VACIO },
    preproduccion: { ...VACIO },
    produccion: {
      desplegado: {
        entorno: "produccion",
        hay: true,
        paquete: "base",
        version: 7,
        huella: "abcdef0123456789",
        referencia_git: "a1b2c3d",
        origen_entorno: "preproduccion",
        desplegado_at: "2026-10-28T10:00:00Z",
        desplegado_por: "ana",
        motivo: "Campos nuevos de servicio",
        se_puede_volver_atras: true,
        que_significa: "",
      },
      drift: {
        entorno: "produccion",
        medible: true,
        paquete: "base",
        version: 7,
        tocado_a_mano: [{ elemento: "campo", clave: "caso.prioridad" }],
        desaparecido: [{ elemento: "layout", clave: "caso.ficha" }],
        limpio: false,
        comparado: 40,
        no_comparado: 3,
        que_significa: "",
      },
    },
  };
  vi.clearAllMocks();
});

describe("el drift", () => {
  it("un entorno sin medir NO sale limpio", async () => {
    render(<Entornos />);
    // Tres entornos sin paquete: los tres lo dicen, ninguno sale limpio.
    expect(await screen.findAllByText("Sin paquete que comparar")).toHaveLength(3);
    // Y en concreto no dice que esté limpio, que es lo contrario.
    expect(screen.queryByText(/entornos\.limpio/)).not.toBeInTheDocument();
  });

  it("separa lo tocado a mano de lo desaparecido", async () => {
    render(<Entornos />);
    expect(
      await screen.findByText('entornos.tocadoAMano:{"cuantos":1}'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('entornos.desaparecido:{"cuantos":1}'),
    ).toBeInTheDocument();
  });

  it("declara lo que no ha podido comparar", async () => {
    render(<Entornos />);
    expect(
      await screen.findByText('entornos.noComparado:{"cuantos":3}'),
    ).toBeInTheDocument();
  });

  it("un entorno limpio de verdad dice cuántos comparó", async () => {
    porEntorno.produccion!.drift = {
      entorno: "produccion",
      medible: true,
      limpio: true,
      comparado: 40,
      no_comparado: 0,
      tocado_a_mano: [],
      desaparecido: [],
    };
    render(<Entornos />);
    expect(
      await screen.findByText('entornos.limpio:{"comparado":40}'),
    ).toBeInTheDocument();
  });
});

describe("lo desplegado", () => {
  it("dice el paquete, la huella y el commit", async () => {
    render(<Entornos />);
    await screen.findByText(
      'entornos.puesto:{"paquete":"base","version":7,"desde":"preproduccion"}',
    );
    expect(
      screen.getByText('entornos.huella:{"huella":"abcdef012345","git":"a1b2c3d"}'),
    ).toBeInTheDocument();
  });

  it("si no se puede volver atrás, lo dice antes de pulsar nada", async () => {
    porEntorno.produccion!.desplegado = {
      ...(porEntorno.produccion!.desplegado as Record<string, unknown>),
      se_puede_volver_atras: false,
    };
    render(<Entornos />);
    expect(await screen.findByText("entornos.noSePuedeVolver")).toBeInTheDocument();
  });

  it("un entorno sin nada desplegado dice por qué", async () => {
    render(<Entornos />);
    expect(await screen.findAllByText("Nunca se desplegó")).toHaveLength(3);
  });

  it("producción va señalada", async () => {
    render(<Entornos />);
    expect(await screen.findByText("entornos.esProduccion")).toBeInTheDocument();
  });
});
