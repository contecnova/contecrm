/**
 * Dónde me han mencionado.
 *
 * Lo que se afirma aquí:
 *
 *  · que un servicio que **no contesta** se diga. «No tienes menciones» y «no
 *    se ha podido preguntar» se leen igual y significan lo contrario, y con
 *    los comentarios repartidos por servicio esto pasa de verdad;
 *  · que una mención **interna** vaya marcada: es la que no ve el cliente, y
 *    mezclada se contesta al que no toca;
 *  · y que desde cada una se **llegue al registro**, que es la mitad del
 *    trabajo que la pantalla ahorra.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

let respuesta: Record<string, unknown>;

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...real, llamar: vi.fn(async () => ({ datos: respuesta })) };
});

const { Menciones } = await import("@/paginas/Menciones");

function montar() {
  return render(
    <MemoryRouter>
      <Menciones />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  respuesta = {
    menciones: [
      {
        id: "m-1",
        objeto_tipo: "caso",
        objeto_id: "k-1",
        cuerpo: "@ana mira esto antes de cerrarlo",
        autor_id: "u-2",
        interno: true,
        hilo_id: null,
        cuando: "2026-10-30T08:00:00Z",
        servicio: "service",
      },
      {
        id: "m-2",
        objeto_tipo: "cuenta",
        objeto_id: "c-1",
        cuerpo: "@ana el cliente pregunta por la renovación",
        autor_id: "u-3",
        interno: false,
        hilo_id: null,
        cuando: "2026-10-29T08:00:00Z",
        servicio: "party",
      },
    ],
    cuantas: 2,
    sin_respuesta: [],
    aviso: "",
  };
  vi.clearAllMocks();
});

describe("las menciones", () => {
  it("salen las de todos los servicios", async () => {
    montar();
    await screen.findByText("@ana mira esto antes de cerrarlo");
    expect(
      screen.getByText("@ana el cliente pregunta por la renovación"),
    ).toBeInTheDocument();
  });

  it("una interna va marcada, porque no la ve el cliente", async () => {
    montar();
    await screen.findByText("menciones.interno");
    // Y sólo una: la otra no es interna.
    expect(screen.getAllByText("menciones.interno")).toHaveLength(1);
  });

  it("desde cada una se llega al registro", async () => {
    montar();
    const enlaces = await screen.findAllByText("menciones.abrir");
    expect(enlaces.length).toBeGreaterThan(0);
  });
});

describe("cuando un servicio no contesta", () => {
  it("se avisa, en vez de enseñar una lista corta como si fuera todo", async () => {
    respuesta = {
      ...respuesta,
      sin_respuesta: ["sales"],
      aviso: "1 servicio(s) no contestan: puede haber menciones que no salen aquí.",
    };
    montar();
    expect(
      await screen.findByText(/puede haber menciones que no salen/),
    ).toBeInTheDocument();
  });

  it("y sin menciones Y con un servicio mudo, no se dice que no hay ninguna", async () => {
    respuesta = {
      menciones: [],
      cuantas: 0,
      sin_respuesta: ["sales"],
      aviso: "1 servicio(s) no contestan: puede haber menciones que no salen aquí.",
    };
    montar();
    await screen.findByText("menciones.ninguna");
    expect(screen.getByText("menciones.ningunaPeroMudos")).toBeInTheDocument();
    expect(screen.queryByText("menciones.ningunaDeVerdad")).not.toBeInTheDocument();
  });

  it("sin menciones y con todos contestando, sí se dice que no hay ninguna", async () => {
    respuesta = { menciones: [], cuantas: 0, sin_respuesta: [], aviso: "" };
    montar();
    await screen.findByText("menciones.ninguna");
    expect(screen.getByText("menciones.ningunaDeVerdad")).toBeInTheDocument();
  });
});
