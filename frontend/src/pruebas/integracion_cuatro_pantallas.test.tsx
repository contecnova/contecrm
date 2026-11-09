/**
 * Las tres pantallas de integración que estaban sin botón, PINTADAS.
 *
 * · CRM-00.01.04.08 — la credencial de una conexión: pide los campos que dice
 *   su tipo, enseña cuándo y quién, y **nunca** el valor.
 * · CRM-06.01.02.11 — el sobre ofrece sólo lo que su estado admite, y lo que
 *   contesta el servidor se dice.
 * · CRM-06.01.03.10 — «Crear reunión en línea»: sin suite, deshabilitado y
 *   con el motivo; con suite, crea y enseña el enlace.
 *
 * El portal de encargos (CRM-00.04.05.06) va en su propio fichero porque el
 * portal habla con `fetch` y no con `llamar`.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

let respuestas: Record<string, unknown> = {};
const llamadas: { ruta: string; metodo?: string; cuerpo?: unknown }[] = [];

vi.mock("@/lib/api", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...real,
    llamar: vi.fn(
      async (
        ruta: string,
        opciones?: { metodo?: string; cuerpo?: unknown },
      ) => {
        llamadas.push({
          ruta,
          metodo: opciones?.metodo,
          cuerpo: opciones?.cuerpo,
        });
        const clave = Object.keys(respuestas)
          .filter((k) => ruta.startsWith(k))
          .sort((a, b) => b.length - a.length)[0];
        if (!clave) throw new Error(`sin respuesta preparada para ${ruta}`);
        return {
          datos: respuestas[clave],
          version: null,
          retenidos: [],
          enmascarados: [],
        };
      },
    ),
    salvoCancelacion: (fn: (e: unknown) => void) => fn,
  };
});

vi.mock("@/lib/permisos", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/permisos")>()),
  useSuperficie: () => ({ superficie: null, tiene: () => true }),
  usePuedeOperar: () => () => true,
}));

vi.mock("@/lib/personas", () => ({
  usePersonas: () => ({
    "u-1": { id: "u-1", nombre: "Marta Ruiz", email: "" },
  }),
  nombreDe: (p: Record<string, { nombre: string }>, id: string) =>
    p[id]?.nombre ?? id,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

const { CredencialesDeConexion } =
  await import("@/componentes/CredencialesDeConexion");
const { ReunionEnLinea } = await import("@/componentes/ReunionEnLinea");

beforeEach(() => {
  respuestas = {};
  llamadas.length = 0;
});

// ── Credenciales ─────────────────────────────────────────────────────────

const ESTADO_OAUTH = {
  auth_tipo: "oauth2_client_credentials",
  campos: [
    { clave: "client_id", secreto: false },
    { clave: "client_secret", secreto: true },
  ],
  actual: {
    version: 2,
    activa: true,
    fijada_at: "2026-11-01T10:00:00Z",
    fijada_por: "u-1",
    rotada_at: null,
    caduca_at: null,
    claves: ["client_id", "client_secret"],
  },
  anteriores: [],
  se_puede_probar: true,
  prueba: { probada_at: null, ok: null, detalle: null },
};

describe("credenciales de una conexión", () => {
  it("dice cuándo y quién la fijó, y pide los campos de su tipo", async () => {
    respuestas["/api/v1/integraciones/conexiones/c-1/credenciales"] =
      ESTADO_OAUTH;
    render(<CredencialesDeConexion conexionId="c-1" />);
    expect(
      await screen.findByText(/credenciales\.actual.*Marta Ruiz/),
    ).toBeInTheDocument();
    // Probar está porque la conexión tiene operaciones.
    expect(screen.getByText("credenciales.probar")).toBeInTheDocument();

    await userEvent.click(screen.getByText("credenciales.rotar"));
    const secreto = screen.getByLabelText(
      /credenciales\.campos\.client_secret/,
    );
    // El secreto se escribe sin verse, y el identificador a la vista.
    expect(secreto).toHaveAttribute("type", "password");
    expect(
      screen.getByLabelText(/credenciales\.campos\.client_id/),
    ).toHaveAttribute("type", "text");
  });

  it("manda lo tecleado con PUT y lo olvida al guardar", async () => {
    respuestas["/api/v1/integraciones/conexiones/c-1/credenciales"] =
      ESTADO_OAUTH;
    render(<CredencialesDeConexion conexionId="c-1" />);
    await userEvent.click(await screen.findByText("credenciales.rotar"));
    const guardar = screen.getByText("credenciales.guardar");
    // Incompleta no se puede mandar.
    expect(guardar).toBeDisabled();
    await userEvent.type(
      screen.getByLabelText(/credenciales\.campos\.client_id/),
      "app",
    );
    await userEvent.type(
      screen.getByLabelText(/credenciales\.campos\.client_secret/),
      "TESTIGO-secreto",
    );
    respuestas["/api/v1/integraciones/conexiones/c-1/credenciales"] = {
      ...ESTADO_OAUTH,
      version: 3,
      rotada: true,
    };
    await userEvent.click(guardar);
    await waitFor(() =>
      expect(llamadas.some((l) => l.metodo === "PUT")).toBe(true),
    );
    const put = llamadas.find((l) => l.metodo === "PUT");
    expect(put?.cuerpo).toMatchObject({
      valores: { client_id: "app", client_secret: "TESTIGO-secreto" },
    });
    // Y el secreto no se queda pintado en ningún sitio.
    await waitFor(() =>
      expect(screen.queryByDisplayValue("TESTIGO-secreto")).toBeNull(),
    );
    expect(document.body.textContent).not.toContain("TESTIGO-secreto");
  });

  it("si nunca se fijó, lo dice", async () => {
    respuestas["/api/v1/integraciones/conexiones/c-1/credenciales"] = {
      ...ESTADO_OAUTH,
      actual: null,
      se_puede_probar: false,
    };
    render(<CredencialesDeConexion conexionId="c-1" />);
    expect(await screen.findByText("credenciales.ninguna")).toBeInTheDocument();
    expect(screen.getByText("credenciales.fijar")).toBeInTheDocument();
    expect(screen.queryByText("credenciales.probar")).toBeNull();
  });
});

// ── Reunión en línea ─────────────────────────────────────────────────────

describe("reunión en línea", () => {
  it("sin suite conectada, el botón sale deshabilitado y con el motivo", async () => {
    respuestas["/api/v1/suites/reuniones/proveedor"] = {
      disponible: false,
      motivo: "TESTIGO-sin-suite",
    };
    render(
      <ReunionEnLinea objeto="cuenta" objetoId="a-1" alCrear={() => {}} />,
    );
    expect(await screen.findByText(/TESTIGO-sin-suite/)).toBeInTheDocument();
    expect(
      screen.getByText("reunionEnLinea.crear").closest("button"),
    ).toBeDisabled();
  });

  it("desde una actividad crea la sala y enseña el enlace", async () => {
    respuestas["/api/v1/suites/reuniones/proveedor"] = {
      disponible: true,
      perfil: "m365",
      sistema: "microsoft",
    };
    respuestas["/api/v1/suites/reuniones"] = {
      enlace: "https://reuniones.example/join/1",
      perfil: "m365",
      sistema: "microsoft",
      creada_at: "2026-11-09T10:00:00Z",
      guardada: true,
    };
    const alCrear = vi.fn();
    render(
      <ReunionEnLinea
        actividadId="act-1"
        actividad={{
          tipo: "reunion",
          inicio_at: "2026-11-20T10:00:00Z",
          fin_at: "2026-11-20T11:00:00Z",
          detalles: {},
        }}
        alCrear={alCrear}
      />,
    );
    const crear = await screen.findByText("reunionEnLinea.crear");
    await waitFor(() => expect(crear.closest("button")).toBeEnabled());
    await userEvent.click(crear);
    // Con hora en la actividad no se vuelve a pedir.
    expect(screen.queryByLabelText("reunionEnLinea.inicio")).toBeNull();
    await userEvent.click(screen.getByText("reunionEnLinea.confirmar"));
    const enlace = await screen.findByText("reunionEnLinea.entrar");
    expect(enlace).toHaveAttribute("href", "https://reuniones.example/join/1");
    const post = llamadas.find((l) => l.metodo === "POST");
    expect(post?.cuerpo).toMatchObject({
      actividad_id: "act-1",
      confirmada: true,
    });
    expect(alCrear).toHaveBeenCalled();
  });

  it("una actividad que ya tiene sala enseña su enlace y no ofrece otra", async () => {
    respuestas["/api/v1/suites/reuniones/proveedor"] = { disponible: true };
    render(
      <ReunionEnLinea
        actividadId="act-2"
        actividad={{
          tipo: "reunion",
          detalles: {
            reunion: { enlace: "https://ya.example/1", perfil: "google" },
          },
        }}
        alCrear={() => {}}
      />,
    );
    expect(await screen.findByText("reunionEnLinea.entrar")).toHaveAttribute(
      "href",
      "https://ya.example/1",
    );
    expect(screen.queryByText("reunionEnLinea.crear")).toBeNull();
  });
});

// ── Acciones del sobre ───────────────────────────────────────────────────

const { SobreDeFirma } = await import("@/paginas/SobreDeFirma");

function evidencia(estado: string) {
  return {
    referencia: "S-1",
    proveedor: "doble",
    nivel: "simple",
    estado,
    documento_id: "doc-1",
    documento_firmado_id: null,
    certificado_id: null,
    sello_tiempo: null,
    hash_enviado: null,
    hash_firmado: null,
    verificable: false,
    firmantes: [],
    eventos: [],
  };
}

function pintarSobre() {
  render(
    <MemoryRouter initialEntries={["/m/operacion/sobre_firma/s-1"]}>
      <Routes>
        <Route path="/m/operacion/sobre_firma/:id" element={<SobreDeFirma />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("acciones del sobre según su estado", () => {
  it("en borrador ofrece enviar, pide confirmar y dice lo que contestó", async () => {
    respuestas["/api/v1/firma/sobres/s-1/evidencia"] = evidencia("borrador");
    respuestas["/api/v1/firma/sobres/s-1/enviar"] = {
      sobre_id: "s-1",
      estado: "enviado",
      caduca_at: "2026-12-01T00:00:00Z",
    };
    pintarSobre();
    await userEvent.click(await screen.findByText("sobre.acciones.enviar"));
    // No sale hasta confirmar: le llega un correo al cliente.
    expect(llamadas.some((l) => l.ruta.endsWith("/enviar"))).toBe(false);
    await userEvent.click(screen.getByText("sobre.acciones.siEnviar"));
    expect(
      await screen.findByText(/sobre\.acciones\.enviado.*enviado/),
    ).toBeInTheDocument();
    expect(screen.queryByText("sobre.acciones.recordar")).toBeNull();
  });

  it("en curso ofrece recordar y cancelar, no enviar", async () => {
    respuestas["/api/v1/firma/sobres/s-1/evidencia"] = evidencia("en_curso");
    respuestas["/api/v1/firma/sobres/s-1/recordar"] = {
      recordados: ["ana@example.com"],
      medible: true,
    };
    pintarSobre();
    await userEvent.click(await screen.findByText("sobre.acciones.recordar"));
    expect(
      await screen.findByText(/sobre\.acciones\.recordado.*ana@example\.com/),
    ).toBeInTheDocument();
    expect(screen.getByText("sobre.acciones.cancelar")).toBeInTheDocument();
    expect(screen.queryByText("sobre.acciones.enviar")).toBeNull();
  });

  it("cancelar exige motivo", async () => {
    respuestas["/api/v1/firma/sobres/s-1/evidencia"] = evidencia("enviado");
    respuestas["/api/v1/firma/sobres/s-1/cancelar"] = { estado: "cancelado" };
    pintarSobre();
    await userEvent.click(await screen.findByText("sobre.acciones.cancelar"));
    const confirmar = screen.getAllByText(
      "sobre.acciones.siCancelar",
    )[0] as HTMLElement;
    expect(confirmar).toBeDisabled();
    await userEvent.type(
      screen.getByLabelText("sobre.acciones.motivo"),
      "Precio cambiado",
    );
    await userEvent.click(confirmar);
    await waitFor(() =>
      expect(
        llamadas.find((l) => l.ruta.endsWith("/cancelar"))?.cuerpo,
      ).toEqual({ motivo: "Precio cambiado" }),
    );
  });

  it("un sobre terminado no ofrece nada", async () => {
    respuestas["/api/v1/firma/sobres/s-1/evidencia"] = evidencia("cancelado");
    pintarSobre();
    await screen.findByText("sobre.firmantes");
    expect(screen.queryByText("sobre.acciones.titulo")).toBeNull();
  });
});
