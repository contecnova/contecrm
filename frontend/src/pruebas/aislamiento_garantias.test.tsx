/**
 * Qué impide que una empresa vea a otra, PINTADO con lo que el servidor mide
 * (CRM-00.01.02.01 a .05, .07, CRM-00.01.01.09, .10).
 *
 * El caso que justifica la pantalla —y esta prueba— es real y se midió el
 * 28-10-2026 contra un despliegue vivo: las 623 tablas con `tenant_id` tenían
 * RLS, FORCE y política, y el servicio conectaba con un rol SUPERUSER, que se
 * salta las políticas aunque estén en FORCE. Contar tablas protegidas daba
 * verde sobre una red desarmada.
 *
 * Por eso lo que se exige aquí no es que pinte una lista: es que **con la capa
 * del rol en rojo, el veredicto NO salga en verde**. Una pantalla de garantías
 * que tranquiliza cuando la garantía no está es peor que no tenerla.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Seguridad } from "@/paginas/Seguridad";

let garantias: unknown = {};

// Las diez rutas que esta pantalla pide, con la FORMA que mandan. Devolver
// `{}` a las otras nueve tumba el render entero —alguna les pide `.length`—, y
// entonces la prueba de esta parte falla por una razón que no es la suya.
const RESPUESTAS: Record<string, unknown> = {
  // Los nombres son los del servidor, no los que uno diría: `usuarios_sin_factor`
  // y `canales_debiles_activos`. Con otros, la pantalla les pide `.length` sobre
  // `undefined` y se cae entera — que es el mismo fallo que ya cazó la prueba
  // del desvío de entorno, una capa más allá.
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
};

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => {
    if (ruta.includes("/aislamiento/garantias")) return { datos: garantias };
    for (const [trozo, datos] of Object.entries(RESPUESTAS)) {
      if (ruta.includes(trozo)) return { datos };
    }
    return { datos: {} };
  }),
  salvoCancelacion: (f: (e: unknown) => void) => f,
  ErrorApi: class extends Error {},
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

/** Lo que devuelve `GET /api/v1/aislamiento/garantias` con la red desarmada:
 * el caso medido, no uno inventado. */
const CON_EL_ROL_MAL = {
  esquema: "tenancy",
  rol: "postgres",
  rol_se_salta_la_red: true,
  tablas_con_tenant: 44,
  todo_puesto: false,
  que_significa:
    "Alguna de las capas que el producto promete NO está haciendo su trabajo aquí.",
  capas: [
    {
      clave: "motor",
      titulo: "Row-Level Security en el motor de datos",
      ok: false,
      cuantas: 44,
      detalle: "44 tablas con `tenant_id` en el esquema «tenancy»; 0 sin RLS.",
      porque: "La política se aplica con FORCE.",
    },
    {
      clave: "rol",
      titulo: "El rol de conexión no se salta la red",
      ok: false,
      cuantas: null,
      detalle: "Conecta como «postgres» — SUPERUSER, así que las políticas NO filtran nada.",
      porque: "Es la línea que decide si las de arriba sirven.",
    },
    {
      clave: "fuzzing",
      titulo: "Suite que intenta entrar en lo ajeno",
      ok: true,
      cuantas: null,
      medible_aqui: false,
      detalle: "Corre en el gate de pre-push.",
      porque: "Una prueba de RLS como superusuario pasa siempre y no demuestra nada.",
    },
  ],
};

describe("las garantías de aislamiento", () => {
  beforeEach(() => {
    garantias = CON_EL_ROL_MAL;
  });

  it("no tranquiliza cuando el rol se salta la red", async () => {
    render(<Seguridad sesion={null} />);
    const veredicto = await screen.findByTestId("aislamiento-veredicto");
    expect(veredicto.className).toContain("text-warning");
    expect(veredicto.className).not.toContain("text-success");
  });

  it("dice CUÁL de las capas falla, no sólo que algo falla", async () => {
    render(<Seguridad sesion={null} />);
    expect(
      await screen.findByText(/El rol de conexión no se salta la red/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Conecta como «postgres»/)).toBeInTheDocument();
  });

  it("cada capa dice de dónde sale su número", async () => {
    render(<Seguridad sesion={null} />);
    expect(
      await screen.findByText(/44 tablas con `tenant_id` en el esquema/),
    ).toBeInTheDocument();
  });

  it("lo que no se mide aquí lo dice en vez de darlo por bueno", async () => {
    render(<Seguridad sesion={null} />);
    expect(await screen.findByText("seguridad.noSeMideAqui")).toBeInTheDocument();
  });

  it("con las capas puestas sí sale en verde", async () => {
    garantias = {
      ...CON_EL_ROL_MAL,
      rol: "crm_app",
      rol_se_salta_la_red: false,
      todo_puesto: true,
      que_significa: "Las capas que el producto promete están puestas.",
      capas: CON_EL_ROL_MAL.capas.map((c) => ({ ...c, ok: true })),
    };
    render(<Seguridad sesion={null} />);
    const veredicto = await screen.findByTestId("aislamiento-veredicto");
    expect(veredicto.className).toContain("text-success");
  });
});
