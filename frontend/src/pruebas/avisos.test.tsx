/**
 * La bandeja de avisos: que se vea, que lleve y que no borre sola.
 *
 * El servidor guardaba las notificaciones desde hacía meses y en el producto
 * no había forma de verlas. Un aviso que sólo existe en la base de datos no ha
 * avisado a nadie.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Notificaciones } from "@/componentes/Notificaciones";

const AVISOS = [
  {
    id: "11111111-1111-4111-8111-111111111111",
    tipo: "oportunidad.cambiada",
    titulo: "La oportunidad «Obra norte» ha cambiado de etapa",
    cuerpo: "De negociación a propuesta",
    objeto_tipo: "oportunidad",
    objeto_id: "22222222-2222-4222-8222-222222222222",
    prioridad: "normal",
    leida_at: null,
    created_at: "2026-10-27T09:30:00+00:00",
  },
  {
    id: "33333333-3333-4333-8333-333333333333",
    tipo: "sistema.aviso",
    titulo: "Se ha terminado la importación",
    cuerpo: null,
    objeto_tipo: null,
    objeto_id: null,
    prioridad: "baja",
    leida_at: "2026-10-26T09:00:00+00:00",
    created_at: "2026-10-26T08:00:00+00:00",
  },
];

function doblar(respuesta: unknown = { items: AVISOS }) {
  const llamadas: string[] = [];
  vi.stubGlobal("fetch", (url: string, opciones?: RequestInit) => {
    llamadas.push(`${opciones?.method ?? "GET"} ${url}`);
    return Promise.resolve(
      new Response(JSON.stringify(opciones?.method === "POST" ? { marcadas: 1 } : respuesta), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  return llamadas;
}

describe("la bandeja de avisos", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("no pide nada hasta que se abre", async () => {
    const llamadas = doblar();
    render(
      <MemoryRouter>
        <Notificaciones />
      </MemoryRouter>,
    );
    // Un sondeo en bucle multiplica las peticiones por pestañas abiertas y por
    // personas, para enterarse un minuto antes de algo que no corre prisa.
    expect(llamadas.filter((l) => l.includes("notificaciones"))).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: /avisos\.abrir/ }));
    await waitFor(() =>
      expect(llamadas.filter((l) => l.includes("notificaciones")).length).toBeGreaterThan(0),
    );
  });

  it("el aviso de un registro lleva a ese registro, y el que no lo tiene no finge", async () => {
    doblar();
    render(
      <MemoryRouter>
        <Notificaciones />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: /avisos\.abrir/ }));

    const enlace = await screen.findByRole("link", { name: /Obra norte/ });
    expect(enlace).toHaveAttribute(
      "href",
      "/m/oportunidades/oportunidad/22222222-2222-4222-8222-222222222222",
    );
    // El de sistema no es un enlace: un enlace que no lleva a nada se pulsa
    // una vez y se desconfía de todos los demás.
    expect(screen.queryByRole("link", { name: /importación/ })).toBeNull();
    expect(await screen.findByText(/Se ha terminado la importación/)).toBeTruthy();
  });

  it("abrir el panel NO marca como leído", async () => {
    const llamadas = doblar();
    render(
      <MemoryRouter>
        <Notificaciones />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: /avisos\.abrir/ }));
    await screen.findByRole("link", { name: /Obra norte/ });

    // Marcar al abrir haría desaparecer lo que no ha dado tiempo a leer, que
    // es la forma más rápida de perder un aviso para siempre.
    expect(llamadas.filter((l) => l.startsWith("POST"))).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: /avisos\.marcarTodas/ }));
    await waitFor(() =>
      expect(llamadas.filter((l) => l.startsWith("POST") && l.includes("leidas"))).toHaveLength(1),
    );
  });

  it("un fallo del servidor no se lleva la barra por delante", async () => {
    vi.stubGlobal("fetch", () =>
      Promise.resolve(
        new Response(JSON.stringify({ detail: "se cayó" }), {
          status: 500,
          headers: { "Content-Type": "application/problem+json" },
        }),
      ),
    );
    render(
      <MemoryRouter>
        <Notificaciones />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: /avisos\.abrir/ }));
    // Se dice dentro del panel y el botón sigue ahí: la barra es el marco, y
    // si se cae la barra no queda ni forma de navegar.
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy());
    expect(screen.getByRole("button", { name: /avisos\.abrir/ })).toBeTruthy();
  });
});
