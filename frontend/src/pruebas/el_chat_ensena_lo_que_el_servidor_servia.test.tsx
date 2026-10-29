/**
 * Cuatro cosas que el chat servía y ninguna pantalla alcanzaba.
 *
 * Estaban construidas y probadas de punta a punta en el servidor —dieciocho
 * pruebas— y sin puerta: buscar, quién está, qué decía antes un mensaje
 * editado y quién hay en la conversación. Una capacidad que sólo se alcanza
 * con `curl` no la tiene el cliente que la compró.
 *
 * Lo que se afirma aquí es **el dato que sólo puede venir de la respuesta de
 * su ruta**, no que el identificador aparezca en el fichero: eso lo cumple
 * igual un comentario. Validado plantando: quitar cada pieza pone en rojo su
 * prueba y sólo la suya.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pedidas: string[] = [];

const CONVERSACION = {
  id: "c-1",
  tipo: "canal",
  clave: "ventas",
  nombre: "Ventas",
  proposito: "",
  privada: false,
  objeto_tipo: null,
  objeto_id: null,
  ultimo_mensaje_at: null,
  sin_leer: 0,
};

const MENSAJE = {
  id: "m-1",
  conversacion_id: "c-1",
  autor_id: "u-2",
  cuerpo: "el precio se bajó por el volumen",
  borrado: false,
  borrado_at: null,
  responde_a_id: null,
  menciones: [],
  adjuntos: [],
  editado_at: "2026-10-29T10:00:00+00:00",
  ediciones: 1,
  reacciones: {},
  created_at: "2026-10-29T10:00:00+00:00",
};

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      pedidas.push(ruta);
      let datos: unknown = {};
      if (ruta.startsWith("/api/v1/chat/conversaciones/c-1/mensajes")) datos = [MENSAJE];
      else if (ruta === "/api/v1/chat/conversaciones/c-1")
        datos = { ...CONVERSACION, miembros: [{ usuario_id: "u-2", rol: "admin", silenciada: false }] };
      else if (ruta.startsWith("/api/v1/chat/conversaciones")) datos = [CONVERSACION];
      else if (ruta === "/api/v1/chat/presencia")
        datos = [
          {
            usuario_id: "u-2",
            estado: "ausente",
            mensaje: "en una visita",
            visto_at: "2026-10-29T09:00:00+00:00",
          },
        ];
      else if (ruta.startsWith("/api/v1/chat/buscar")) datos = [MENSAJE];
      else if (ruta.endsWith("/versiones")) datos = [{ cuerpo: "el precio se bajó porque sí" }];
      else if (ruta.startsWith("/api/v1/usuarios"))
        datos = { items: [{ id: "u-2", nombre: "Luis", email: "luis@x.com" }] };
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
  const { Chat } = await import("@/paginas/Chat");
  return render(
    <MemoryRouter initialEntries={["/chat?c=c-1"]}>
      <Chat sesion={{ usuario_id: "u-1" } as never} />
    </MemoryRouter>,
  );
}

describe("el chat enseña lo que el servidor ya servía", () => {
  beforeEach(() => {
    pedidas.length = 0;
  });

  it("busca, y sólo en lo mío: lo acota el servidor", async () => {
    await montar();
    const campo = await waitFor(() => screen.getByLabelText("chat.buscar"));
    await userEvent.type(campo, "precio{Enter}");
    await waitFor(() =>
      expect(pedidas.some((r) => r.startsWith("/api/v1/chat/buscar"))).toBe(true),
    );
    // El resultado se pinta, que es lo que no pasaba.
    await waitFor(() =>
      expect(screen.getByText(/chat.hallazgos.*"cuantos":1/)).toBeTruthy(),
    );
  });

  it("dice quién está y desde cuándo no se le ve", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("chat.quienEsta")).toBeTruthy());
    // El estado, el mensaje escrito y el «visto»: sin el último, la pregunta
    // de verdad —«¿espero o llamo?»— se queda sin contestar.
    expect(screen.getByText("ausente")).toBeTruthy();
    expect(screen.getByText("en una visita")).toBeTruthy();
    expect(screen.getByText(/chat.vistoA/)).toBeTruthy();
  });

  it("enseña quién va a leer lo que se escriba", async () => {
    await montar();
    await waitFor(() =>
      expect(screen.getByText(/chat.miembros.*"cuantos":1/)).toBeTruthy(),
    );
  });

  it("abre qué decía antes un mensaje editado", async () => {
    await montar();
    const editado = await waitFor(() => screen.getByText(/chat.editado$/));
    await userEvent.click(editado);
    await waitFor(() =>
      expect(screen.getByText("el precio se bajó porque sí")).toBeTruthy(),
    );
    // Y el mensaje vigente sigue ahí: lo corregido se ve corregido, no
    // sustituido por su versión vieja.
    expect(screen.getByText("el precio se bajó por el volumen")).toBeTruthy();
  });
});
