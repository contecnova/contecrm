/**
 * Segundo factor con el proveedor de la empresa (CRM-00.05.01.22).
 *
 * Se elige una plantilla en el desplegable y el formulario sale relleno con
 * ella —variables, cuerpo, dónde contesta—; al guardar va el secreto tecleado
 * y la API nunca lo devuelve; «Probar» manda la persona y el código y enseña
 * lo que contestó el proveedor.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string) => clave,
    i18n: { language: "es", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: unknown }) => children ?? null,
  initReactI18next: { type: "3rdParty", init: () => undefined },
}));

const llamadas: { ruta: string; metodo: string; cuerpo?: unknown }[] = [];
const guardado = {
  id: "p1",
  nombre: "Twilio Verify",
  plantilla: "twilio_verify",
  activo: true,
  url: "https://verify.example/v2/Services/{{var.service_sid}}/VerificationCheck",
  metodo: "POST",
  formato: "form",
  autenticacion: { tipo: "basica", usuario: "{{var.account_sid}}" },
  tiene_secreto: true,
  cabeceras: {},
  cuerpo: { To: "{{persona.telefono}}", Code: "{{codigo}}" },
  variables: { service_sid: "VA1", account_sid: "AC1" },
  campos_persona: ["telefono"],
  respuesta: { campo: "status", validos: ["approved"] },
};

vi.mock("@/lib/listados", () => ({
  listar: vi.fn(async () => [
    { id: "u1", nombre: "Ana", email: "ana@ejemplo.com" },
  ]),
}));

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(
      async (
        ruta: string,
        opciones?: { metodo?: string; cuerpo?: unknown },
      ) => {
        const metodo = opciones?.metodo ?? "GET";
        llamadas.push({ ruta, metodo, cuerpo: opciones?.cuerpo });
        if (ruta.endsWith("/plantillas"))
          return {
            datos: {
              twilio_verify: {
                ...guardado,
                id: undefined,
                tiene_secreto: undefined,
                activo: undefined,
                nota: "El secreto es el Auth Token.",
              },
            },
          };
        if (ruta.endsWith("/perfiles") && metodo === "GET")
          return {
            datos: {
              items: llamadas.some((l) => l.metodo === "POST")
                ? [guardado]
                : [],
            },
          };
        if (ruta.endsWith("/perfiles") && metodo === "POST")
          return { datos: guardado };
        if (ruta.endsWith("/personas")) return { datos: { items: [] } };
        if (ruta.endsWith("/probar"))
          return {
            datos: {
              valido: true,
              estado_http: 200,
              motivo: "«status» vale «approved»",
              peticion: { url: "…", cuerpo: { Code: "••••" } },
            },
          };
        return { datos: {} };
      },
    ),
  };
});

describe("segundo factor con el proveedor de la empresa", () => {
  beforeEach(() => {
    llamadas.length = 0;
  });

  it("rellena desde la plantilla, guarda con el secreto y prueba un código", async () => {
    const { SegundoFactorPorProveedor } =
      await import("@/componentes/SegundoFactorPorProveedor");
    render(<SegundoFactorPorProveedor puedeCambiar />);

    const plantilla = await screen.findByLabelText(
      "seguridad.proveedor.desdePlantilla",
    );
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: "Twilio Verify" }),
      ).toBeTruthy(),
    );
    await userEvent.selectOptions(plantilla, "twilio_verify");

    // El formulario sale con lo de la plantilla: la nota, la variable y dónde contesta.
    expect(
      await screen.findByText("El secreto es el Auth Token."),
    ).toBeTruthy();
    expect(screen.getByDisplayValue("status")).toBeTruthy();
    expect(screen.getByDisplayValue("VA1")).toBeTruthy();

    const secreto = screen.getByLabelText("seguridad.proveedor.secreto");
    await userEvent.type(secreto, "token-secreto");
    await userEvent.click(screen.getByText("seguridad.proveedor.guardar"));

    await waitFor(() =>
      expect(llamadas.some((l) => l.metodo === "POST")).toBe(true),
    );
    const alta = llamadas.find((l) => l.metodo === "POST")?.cuerpo as Record<
      string,
      unknown
    >;
    expect(alta.secreto).toBe("token-secreto");
    expect(alta.plantilla).toBe("twilio_verify");
    expect(alta.campos_persona).toEqual(["telefono"]);
    expect(alta.respuesta).toEqual({ campo: "status", validos: ["approved"] });

    // Guardado: ya tiene id, así que salen la persona y «Probar».
    expect(
      await screen.findByText("seguridad.proveedor.guardado"),
    ).toBeTruthy();
    const personas = await screen.findAllByLabelText(
      "seguridad.proveedor.persona",
    );
    const elegirEnProbar = personas[personas.length - 1] as HTMLSelectElement;
    await userEvent.selectOptions(elegirEnProbar, "u1");
    await userEvent.type(
      screen.getByLabelText("seguridad.proveedor.codigo"),
      "246810",
    );
    const botones = screen.getAllByText("seguridad.proveedor.probar");
    await userEvent.click(botones[botones.length - 1] as Element);

    expect(
      await screen.findByText("seguridad.proveedor.resultadoVale", {
        exact: false,
      }),
    ).toBeTruthy();
    const prueba = llamadas.find((l) => l.ruta.endsWith("/probar"));
    expect(prueba?.cuerpo).toEqual({ usuario_id: "u1", codigo: "246810" });
  });
});
