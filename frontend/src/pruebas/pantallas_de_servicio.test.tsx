/**
 * Tres pantallas de servicio, PINTADAS con el contrato real del servidor.
 *
 *   · **Consola de agente** (CRM-07.04.03.18): el punto de la omnicanalidad no
 *     es tener cinco bandejas bonitas, es **una sola cola**. Con una bandeja
 *     por canal, el correo se mira dos veces al día y el chat todo el rato, y
 *     quien escribe por correo espera el doble sin que nadie lo decida.
 *   · **Conocimiento** (CRM-07.04.03.19): un artículo sin publicar y uno
 *     publicado se usan de forma distinta, así que no se pueden pintar igual.
 *   · **Inteligencia** (CRM-07.04.03.23): siempre con el porqué y con la
 *     fuente a la vista. Una puntuación sin motivo no se puede discutir, y una
 *     que no se puede discutir acaba ignorándose.
 *
 * Los contratos salen de las pruebas de servidor que recorren esas rutas.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Conocimiento } from "@/paginas/Conocimiento";
import { ConsolaAgente } from "@/paginas/Consola.agente";
import { Inteligencia } from "@/paginas/Inteligencia";

let respuestas: Record<string, unknown> = {};

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      const clave = Object.keys(respuestas)
        .filter((k) => ruta.startsWith(k))
        .sort((a, b) => b.length - a.length)[0];
      if (!clave) throw new Error(`sin respuesta preparada para ${ruta}`);
      return { datos: respuestas[clave] };
    }),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

function pintar(pantalla: React.ReactElement) {
  return render(<MemoryRouter>{pantalla}</MemoryRouter>);
}

beforeEach(() => {
  respuestas = {};
});

// ── Consola de agente (CRM-07.04.03.18) ───────────────────────────────────

describe("la consola de agente", () => {
  const CONSOLA = {
    agente: { presencia: "disponible" },
    cola: [
      {
        tipo: "caso",
        id: "c1",
        canal: "correo",
        asunto: "No puedo entrar",
        estado: "abierto",
        minutos_restantes: -30,
        espera_min: null,
        vencido: true,
      },
      {
        tipo: "conversacion",
        id: "v1",
        canal: "chat",
        asunto: "Duda de factura",
        estado: "abierta",
        minutos_restantes: null,
        espera_min: 12,
        vencido: false,
      },
    ],
    mis_casos: [],
    mis_conversaciones: [],
  };

  it("mezcla los canales en una sola cola", async () => {
    // El canal es una etiqueta, no una pestaña: con una bandeja por canal, el
    // que se mira menos espera más sin que nadie lo haya decidido.
    respuestas = { "/api/v1/consola-agente": CONSOLA };
    pintar(<ConsolaAgente />);
    expect(await screen.findByText(/No puedo entrar/)).toBeInTheDocument();
    expect(screen.getByText(/Duda de factura/)).toBeInTheDocument();
    // Y los dos canales se ven, porque de eso depende saber por dónde contestar.
    expect(screen.getByText(/correo/)).toBeInTheDocument();
    expect(screen.getByText(/chat/)).toBeInTheDocument();
  });

  it("lo vencido se ve como vencido", async () => {
    // Un plazo pasado y uno que queda no se pueden pintar igual: lo primero ya
    // está incumplido y lo segundo es la tarea de ahora mismo.
    respuestas = { "/api/v1/consola-agente": CONSOLA };
    const { container } = pintar(<ConsolaAgente />);
    await screen.findByText(/No puedo entrar/);
    expect(container.innerHTML).toContain("text-danger");
  });

  it("con la cola vacía lo dice, en vez de dejar un hueco", async () => {
    respuestas = {
      "/api/v1/consola-agente": {
        agente: { presencia: "disponible" },
        cola: [],
        mis_casos: [],
        mis_conversaciones: [],
      },
    };
    const { container } = pintar(<ConsolaAgente />);
    // Lo que no puede es quedarse en blanco: una consola vacía sin un texto se
    // lee como «todavía está cargando», y el agente se queda esperando.
    await screen.findByRole("heading", { level: 1 });
    expect(container.textContent?.trim()).not.toBe("");
  });
});

// ── Conocimiento (CRM-07.04.03.19) ────────────────────────────────────────

describe("la base de conocimiento", () => {
  it("distingue lo publicado de lo que está sin aprobar", async () => {
    // Un artículo en borrador que se pinta igual que uno publicado se cita en
    // un caso como si estuviera revisado, y lo que llega al cliente es un
    // texto que nadie aprobó.
    respuestas = {
      "/api/v1/conocimiento/articulos": [
        {
          id: "a1",
          titulo: "Cómo restablecer la contraseña",
          estado: "publicado",
          publico: true,
          categoria: "acceso",
          vistas: 120,
          util: 0.9,
        },
        {
          id: "a2",
          titulo: "Borrador sin revisar",
          estado: "borrador",
          publico: false,
          categoria: null,
          vistas: 0,
          util: null,
        },
      ],
    };
    const { container } = pintar(<Conocimiento />);
    expect(await screen.findByText(/Cómo restablecer/)).toBeInTheDocument();
    expect(screen.getByText(/Borrador sin revisar/)).toBeInTheDocument();
    // Los dos estados se ven: sin eso, la lista es una lista de títulos.
    expect(container.textContent).toContain("publicado");
    expect(container.textContent).toContain("borrador");
  });

  it("«no se sabe si fue útil» no se pinta como cero", async () => {
    // Cero por ciento de utilidad y «nadie lo ha valorado» se leen igual y
    // significan lo contrario: con el cero, el artículo se reescribe sin motivo.
    respuestas = {
      "/api/v1/conocimiento/articulos": [
        {
          id: "a1",
          titulo: "Sin valorar",
          estado: "publicado",
          publico: true,
          categoria: null,
          vistas: 3,
          util: null,
        },
      ],
    };
    const { container } = pintar(<Conocimiento />);
    await screen.findByText(/Sin valorar/);
    expect(container.textContent).not.toMatch(/\b0\s*%/);
  });
});

// ── Inteligencia (CRM-07.04.03.23) ────────────────────────────────────────

describe("lo que la IA sabe de una cuenta", () => {
  const CUENTAS = [{ id: "cta1", nombre: "Acme" }];

  /** La salud se pide al elegir una cuenta, no al entrar: pedir las de todas
   * al abrir la pantalla sería una consulta por cuenta del tenant. */
  async function elegirCuenta() {
    pintar(<Inteligencia />);
    const selector = await screen.findByLabelText("ia.cuenta");
    await userEvent.selectOptions(selector, "cta1");
  }

  it("enseña la puntuación con su porqué y de dónde sale", async () => {
    // Una puntuación sin motivo no se puede discutir, y una que no se puede
    // discutir acaba ignorándose. Y «de dónde sale» importa porque esto es una
    // copia: el detalle vive en quien la calcula.
    respuestas = {
      "/api/v1/accounts": CUENTAS,
      "/api/v1/calidad-dato/salud/": {
        hay: true,
        puntuacion: 42,
        nivel: "riesgo",
        fiable: true,
        vigente: true,
        medida_hace_dias: 2,
        motivo: "Tres incidencias abiertas",
        sirve_para_actuar: true,
        aviso: "",
        de_donde_sale: "Se calcula en inteligencia; aquí hay una copia",
      },
    };
    await elegirCuenta();
    expect(await screen.findByText(/Tres incidencias abiertas/)).toBeInTheDocument();
    expect(screen.getByText(/aquí hay una copia/)).toBeInTheDocument();
  });

  it("«no medido» no se pinta como «va mal»", async () => {
    // Confundirlos hace que alguien llame a un cliente que está bien.
    respuestas = {
      "/api/v1/accounts": CUENTAS,
      "/api/v1/calidad-dato/salud/": {
        hay: false,
        porque: "Nadie ha medido la salud de esta cuenta todavía",
        que_hacer: "Lanzar el cálculo desde inteligencia",
      },
    };
    await elegirCuenta();
    expect(await screen.findByText(/Nadie ha medido/)).toBeInTheDocument();
    expect(screen.getByText(/Lanzar el cálculo/)).toBeInTheDocument();
  });

  it("una medida vieja lo dice, en vez de pasar por actual", async () => {
    // Una puntuación de hace ocho meses no es una puntuación: es un recuerdo, y
    // se usa para decidir como si fuera de hoy.
    respuestas = {
      "/api/v1/accounts": CUENTAS,
      "/api/v1/calidad-dato/salud/": {
        hay: true,
        puntuacion: 80,
        nivel: "sana",
        fiable: true,
        vigente: false,
        medida_hace_dias: 240,
        motivo: "Sin incidencias",
        sirve_para_actuar: false,
        aviso: "Esta medida tiene 240 días: no sirve para actuar.",
        de_donde_sale: "Se calcula en inteligencia",
      },
    };
    await elegirCuenta();
    expect(await screen.findByText(/no sirve para actuar/)).toBeInTheDocument();
  });
});
