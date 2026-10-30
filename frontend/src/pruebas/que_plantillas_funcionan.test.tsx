/**
 * Qué plantillas funcionan, y a quién le toca la próxima reunión.
 *
 * Lo que se afirma aquí:
 *
 *  · que una plantilla **no concluyente** salga aparte y no compitiendo con
 *    las demás. Con nueve envíos un 33 % es ruido, y ordenadas juntas la mejor
 *    sería siempre la que menos se ha usado;
 *  · que la tasa venga **con su denominador**;
 *  · que pedir el turno **se diga que lo consume**, porque pulsar tres veces
 *    para «ver» se salta a dos del equipo;
 *  · y que un equipo sin nadie disponible lo diga, en vez de repartir en
 *    silencio entre cero personas.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

let rendimiento: Record<string, unknown>;
let turno: Record<string, unknown> | null;

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      if (ruta.includes("/agenda/turno")) {
        if (turno === null) {
          // El constructor de verdad: (estado, código, título, detalle,
          // explicación). La frase que se enseña es la explicación.
          throw new real.ErrorApi(
            404,
            "agenda.equipo_sin_disponibilidad",
            "No encontrado",
            { equipo: "norte" },
            "Nadie del equipo «norte» tiene disponibilidad declarada y activa.",
          );
        }
        return { datos: turno };
      }
      return { datos: rendimiento };
    }),
  };
});

const { Prospeccion } = await import("@/paginas/Prospeccion");

beforeEach(() => {
  rendimiento = {
    medible: true,
    plantillas: [
      {
        clave: "frio-1",
        nombre: "Primer contacto",
        enviados: 400,
        respondidos: 48,
        reuniones: 12,
        tasa_respuesta: 12,
        tasa_reunion: 3,
        abiertos: 180,
        aviso_apertura: "La apertura depende de un píxel que media industria bloquea.",
        concluyente: true,
        aviso: "",
      },
      {
        clave: "nueva",
        nombre: "Plantilla nueva",
        enviados: 9,
        respondidos: 3,
        reuniones: 0,
        tasa_respuesta: 33,
        tasa_reunion: 0,
        abiertos: 4,
        aviso_apertura: "",
        concluyente: false,
        aviso: "Con 9 envíos no se puede concluir nada.",
      },
    ],
  };
  turno = {
    usuario_id: "u-1",
    equipo: "norte",
    turno_consumido: true,
    huecos: [{ desde: "2026-11-02T09:00:00Z", hasta: "2026-11-02T10:00:00Z" }],
  };
  vi.clearAllMocks();
});

describe("las plantillas", () => {
  it("la que no es concluyente sale aparte, no compitiendo", async () => {
    render(<Prospeccion />);
    await screen.findByText("Primer contacto");
    expect(
      screen.getByText('prospeccion.pocasVeces:{"cuantas":1}'),
    ).toBeInTheDocument();
    // Y no se le pinta la tasa al lado de las buenas: un 33 % de nueve
    // envíos arriba del todo es exactamente el error.
    expect(
      screen.queryByText('prospeccion.tasas:{"respuesta":33,"reunion":0}'),
    ).not.toBeInTheDocument();
  });

  it("la concluyente viene con su denominador", async () => {
    render(<Prospeccion />);
    await screen.findByText('prospeccion.tasas:{"respuesta":12,"reunion":3}');
    expect(
      screen.getByText(
        'prospeccion.sobre:{"enviados":400,"respondidos":48,"reuniones":12}',
      ),
    ).toBeInTheDocument();
  });

  it("y la apertura va con su advertencia", async () => {
    render(<Prospeccion />);
    await screen.findByText(/media industria bloquea/);
  });

  it("sin nada medible lo dice, en vez de enseñar ceros", async () => {
    rendimiento = { medible: false, plantillas: [] };
    render(<Prospeccion />);
    expect(await screen.findByText("prospeccion.sinMedir")).toBeInTheDocument();
  });
});

describe("el turno", () => {
  it("no se pide al abrir: avanzaría el round-robin solo", async () => {
    render(<Prospeccion />);
    await screen.findByText("prospeccion.aQuienLeToca");
    expect(screen.queryByText(/prospeccion\.leToca/)).not.toBeInTheDocument();
  });

  it("al pedirlo dice a quién le toca Y que el turno se ha consumido", async () => {
    render(<Prospeccion />);
    await screen.findByText("prospeccion.aQuienLeToca");
    await userEvent.type(screen.getByLabelText("prospeccion.equipo"), "norte");
    await userEvent.click(screen.getByText("prospeccion.pedirTurno"));

    expect(
      await screen.findByText('prospeccion.leToca:{"usuario":"u-1"}'),
    ).toBeInTheDocument();
    expect(screen.getByText("prospeccion.turnoConsumido")).toBeInTheDocument();
  });

  it("un equipo sin nadie disponible lo dice, no reparte en silencio", async () => {
    turno = null;
    render(<Prospeccion />);
    await screen.findByText("prospeccion.aQuienLeToca");
    await userEvent.type(screen.getByLabelText("prospeccion.equipo"), "norte");
    await userEvent.click(screen.getByText("prospeccion.pedirTurno"));

    expect(await screen.findByText(/disponibilidad declarada/)).toBeInTheDocument();
  });

  it("no se puede pedir sin equipo", async () => {
    render(<Prospeccion />);
    await screen.findByText("prospeccion.aQuienLeToca");
    expect(screen.getByText("prospeccion.pedirTurno")).toBeDisabled();
  });
});
