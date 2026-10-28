/**
 * Quién ve qué, y por qué (CRM-00.05.02.02, .03, .05, .08, .18, .20, .21).
 *
 * Dos cosas que faltaban y que son la misma: poder **ver la decisión por
 * capas** y poder **leer las excepciones de campo**.
 *
 * La primera importa porque un «no podría» a secas manda a cambiar el rol
 * cuando lo que corta es una política de atributos, y al revés. La segunda,
 * porque la ruta que crea esas excepciones justifica escribirlas con que «una
 * excepción que vive en la cabeza de quien la pidió es la que nadie revisa al
 * año siguiente» — y hasta hoy no había forma de leerlas, así que vivía igual
 * de escondida, sólo que en una tabla.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Seguridad } from "@/paginas/Seguridad";

let simulacion: unknown = null;
let campos: unknown = { campos: [], cuantas: 0, que_significa: "No hay ninguna excepción." };

const SALUD = {
  "/factores/adopcion": {
    total_usuarios: 0,
    con_factor: 0,
    sin_factor: 0,
    adopcion_pct: null,
    medible: false,
    mfa_obligatoria: false,
    usuarios_sin_factor: [],
    canales_debiles_activos: [],
    aviso: "",
  },
  "/sso-gobierno/certificados": { certificados: [] },
  "/segregacion/violaciones": { violaciones: [], reglas: 0 },
  "/factores/nivel": { nivel: "contrasena", factores: [], que_falta: [] },
  "/factores/operaciones-sensibles": { operaciones: [] },
  "/factores/plan-de-inscripcion": { pasos: [] },
  "/factores/cambio-de-dispositivo": { caminos: [] },
  "/auth/passkeys": [],
  "/segregacion/excepciones": [],
  "/sso-gobierno/descubrir": { tiene_proveedor: false, entrada: "contrasena" },
  "/aislamiento/garantias": {
    esquema: "identity",
    rol: "crm_app",
    rol_se_salta_la_red: false,
    tablas_con_tenant: 10,
    todo_puesto: true,
    que_significa: "Puestas.",
    capas: [],
  },
};

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => {
    if (ruta.includes("/politicas-acceso/simular")) return { datos: simulacion };
    if (ruta.includes("/politicas-acceso/campos")) return { datos: campos };
    if (ruta.includes("/roles/explicar")) return { datos: { ok: true } };
    for (const [trozo, datos] of Object.entries(SALUD)) {
      if (ruta.includes(trozo)) return { datos };
    }
    return { datos: {} };
  }),
  salvoCancelacion: (f: (e: unknown) => void) => f,
  ErrorApi: class extends Error {},
}));

vi.mock("@/lib/sesion", async (original) => ({
  ...(await original<Record<string, unknown>>()),
  puede: () => true,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

async function preguntarPor(sesion: null = null) {
  render(<Seguridad sesion={sesion} />);
  const usuario = await screen.findByLabelText(/seguridad\.explicador\.usuario/);
  await userEvent.type(usuario, "u-1");
  await userEvent.type(
    screen.getByLabelText(/seguridad\.explicador\.objeto/),
    "cuenta",
  );
  await userEvent.click(
    screen.getByRole("button", { name: /seguridad\.explicador\.preguntar/ }),
  );
}

describe("quién ve qué", () => {
  beforeEach(() => {
    simulacion = {
      permitido: false,
      origen: "3 políticas activas del tenant",
      rbac: { concede: true, permiso: "cuenta:read" },
      abac: { permitido: false, explicacion: "Fuera del horario declarado" },
      ambito: {
        usuario: { roles: ["comercial"], business_unit_id: "iberia" },
        contexto: { hora: 23, dia_semana: 6 },
      },
    };
    campos = { campos: [], cuantas: 0, que_significa: "No hay ninguna excepción." };
  });

  it("dice CUÁL de las dos capas niega, no sólo que niega", async () => {
    await preguntarPor();
    const caja = await screen.findByTestId("simulacion-acceso");
    // El rol concede y los atributos niegan: sin separarlo, alguien va a
    // cambiar el rol y no va a servir de nada.
    expect(caja.textContent).toContain("seguridad.simulador.rbac");
    expect(caja.textContent).toContain("Fuera del horario declarado");
  });

  it("enseña el contexto con el que se evaluó, que es lo que permite repetirlo", async () => {
    await preguntarPor();
    const caja = await screen.findByTestId("simulacion-acceso");
    expect(caja.textContent).toContain("comercial");
    expect(caja.textContent).toContain("iberia");
  });

  it("un «no podría» no se pinta como si fuera un sí", async () => {
    await preguntarPor();
    const caja = await screen.findByTestId("simulacion-acceso");
    expect(caja.textContent).toContain("seguridad.simulador.denegado");
  });

  it("lista las excepciones de campo, que antes no se podían leer", async () => {
    campos = {
      cuantas: 2,
      que_significa: "Cada línea es un campo que NO se comporta como dice su clasificación.",
      campos: [
        { objeto: "oportunidad", campo: "margen", rol: "*", nivel: "oculto", para_todos: true },
        { objeto: "contacto", campo: "movil", rol: "soporte", nivel: "claro", para_todos: false },
      ],
    };
    render(<Seguridad sesion={null} />);
    const lista = await screen.findByTestId("excepciones-de-campo");
    expect(lista.textContent).toContain("oportunidad.margen");
    expect(lista.textContent).toContain("contacto.movil");
    // El rol tal cual: `*` se dice, no se esconde.
    expect(lista.textContent).toContain("soporte");
  });

  it("sin excepciones dice qué significa, no deja el hueco", async () => {
    render(<Seguridad sesion={null} />);
    expect(await screen.findByText("No hay ninguna excepción.")).toBeInTheDocument();
  });
});
