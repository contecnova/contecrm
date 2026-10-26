/**
 * La papelera del chat, PINTADA (CRM-06.02.02.09).
 *
 * La capacidad estaba declarada hecha y no existía: el modelo del mensaje
 * llevaba las columnas de borrado desde el principio y no había ruta que
 * borrara, ni que recuperara, ni retención que purgara. Al construirla, lo que
 * no puede volver a pasar es que la ruta exista y **no tenga botón**: un
 * endpoint sin botón es una capacidad que nadie usa.
 *
 * Y la decisión que se ve aquí: un mensaje borrado **deja su hueco en el hilo**,
 * sin cuerpo. Si desapareciera, su respuesta se quedaría sin padre y esta
 * pantalla la subiría al nivel de arriba en silencio — una conversación que se
 * lee mal y no dice que falta nada.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Chat } from "@/paginas/Chat";

const YO = "11111111-1111-4111-8111-111111111111";

const CONVERSACION = {
  id: "c1",
  tipo: "canal",
  clave: "ventas",
  nombre: "Ventas",
  proposito: "",
  objeto_tipo: null,
  objeto_id: null,
  ultimo_mensaje_at: null,
  sin_leer: 0,
};

function mensaje(extra: Record<string, unknown> = {}) {
  return {
    id: "m1",
    conversacion_id: "c1",
    autor_id: YO,
    cuerpo: "Una credencial que no debía estar aquí",
    responde_a_id: null,
    menciones: [],
    editado_at: null,
    ediciones: 0,
    reacciones: {},
    created_at: "2026-10-26T09:00:00+00:00",
    borrado: false,
    ...extra,
  };
}

let mensajes: unknown[] = [];
const llamadas: { ruta: string; metodo?: string }[] = [];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string, opciones?: { metodo?: string }) => {
      llamadas.push({ ruta, metodo: opciones?.metodo });
      if (ruta.includes("/mensajes")) return { datos: mensajes };
      if (ruta.includes("/chat/conversaciones")) return { datos: [CONVERSACION] };
      return { datos: [] };
    }),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

async function abrir() {
  render(
    <MemoryRouter initialEntries={["/chat?c=c1"]}>
      <Chat sesion={{ usuario_id: YO } as never} />
    </MemoryRouter>,
  );
  // El rótulo de un canal es `#clave`, no su nombre: es como se nombra un canal
  // en cualquier chat y es lo que esta pantalla pinta.
  await screen.findAllByText("#ventas");
}

describe("la papelera del chat", () => {
  beforeEach(() => {
    llamadas.length = 0;
    mensajes = [mensaje()];
  });

  it("lo mío se puede mandar a la papelera desde la pantalla", async () => {
    await abrir();
    await userEvent.click(await screen.findByRole("button", { name: "chat.borrar" }));
    await waitFor(() =>
      expect(
        llamadas.some((l) => l.metodo === "DELETE" && l.ruta.endsWith("/chat/mensajes/m1")),
      ).toBe(true),
    );
  });

  it("un mensaje borrado deja su hueco, sin cuerpo", async () => {
    mensajes = [mensaje({ borrado: true, cuerpo: "", borrado_at: "2026-10-26T10:00:00+00:00" })];
    await abrir();
    expect(await screen.findByText("chat.borrado")).toBeInTheDocument();
    expect(screen.queryByText(/credencial/)).not.toBeInTheDocument();
  });

  it("y se puede recuperar, que es lo que lo distingue de un borrado", async () => {
    mensajes = [mensaje({ borrado: true, cuerpo: "" })];
    await abrir();
    await userEvent.click(await screen.findByRole("button", { name: "chat.recuperar" }));
    await waitFor(() =>
      expect(llamadas.some((l) => l.ruta.endsWith("/chat/mensajes/m1/recuperar"))).toBe(true),
    );
  });

  it("a un mensaje borrado no se le ofrece responder", async () => {
    // Responder a un hueco no tiene sentido, y además dejaría una respuesta
    // colgando de algo que ya no se puede leer.
    mensajes = [mensaje({ borrado: true, cuerpo: "" })];
    await abrir();
    expect(screen.queryByRole("button", { name: "chat.responder" })).not.toBeInTheDocument();
  });

  it("el mensaje de otro no lleva botón de borrar", async () => {
    // El servidor deja además a quien administra la conversación, y esta
    // pantalla todavía no sabe quién lo es: ofrecer el botón a todos daría un
    // 403 al pulsarlo, que es peor que no ofrecerlo.
    mensajes = [mensaje({ autor_id: "22222222-2222-4222-8222-222222222222" })];
    await abrir();
    expect(screen.queryByRole("button", { name: "chat.borrar" })).not.toBeInTheDocument();
  });
});
