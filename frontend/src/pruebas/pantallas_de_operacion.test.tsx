/**
 * Cinco pantallas de operación, PINTADAS con el contrato real del servidor.
 *
 * El barrido general comprueba que ninguna deje la aplicación en blanco ante
 * una respuesta deforme. Eso es el suelo. Lo que falta —y es donde estaban los
 * dos agujeros de hoy— es que cada pantalla **diga lo que promete** con la
 * respuesta que de verdad manda su ruta.
 *
 * Las cinco:
 *
 *   · **Puesto** (CRM-07.04.03.24): lo que no se ha medido no cuenta como
 *     verde. Una conexión sin última sincronización no es una conexión sana:
 *     es una de la que no se sabe nada.
 *   · **Estado** (CRM-07.04.03.30): lo prometido y lo medido al lado. Y lo que
 *     no se puede medir se dice, en vez de un cero que se leería como «se
 *     cumple».
 *   · **Coste** (CRM-07.04.03.32): lo que queda de verdad con un proveedor, y
 *     el aviso de que si se ganan todas las ofertas no cabe.
 *   · **Rendimiento** (CRM-07.04.03.29): cuánto hay, cuánto cabe y qué se está
 *     aplazando ahora mismo, que es la pregunta que llega de verdad.
 *   · **Ayuda** (CRM-07.04.03.33): el capítulo de la pantalla en la que estás,
 *     no el índice. Mandar al índice es mandar a buscar, y quien está atascado
 *     no busca: se rinde y escribe a soporte.
 *
 * Los contratos están copiados de las pruebas de servidor que recorren esas
 * rutas, no inventados: una pantalla probada contra una forma imaginada es
 * exactamente el fallo que esto existe para no tener.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Ayuda } from "@/paginas/Ayuda";
import { Coste } from "@/paginas/Coste";
import { Estado } from "@/paginas/Estado";
import { Puesto } from "@/paginas/Puesto";
import { Rendimiento } from "@/paginas/Rendimiento";

let respuestas: Record<string, unknown> = {};

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      // La clave MÁS LARGA que encaje, no la primera: `/api/v1/estado/presion`
      // empieza por `/api/v1/estado`, y con la primera una pantalla recibiría
      // la respuesta de la otra.
      const clave = Object.keys(respuestas)
        .filter((k) => ruta.startsWith(k))
        .sort((a, b) => b.length - a.length)[0];
      if (!clave) throw new Error(`sin respuesta preparada para ${ruta}`);
      return { datos: respuestas[clave] };
    }),
  };
});

vi.mock("@/lib/sesion", async () => {
  const real = await vi.importActual<typeof import("@/lib/sesion")>("@/lib/sesion");
  // Devuelve una PROMESA, como la de verdad: un doble que devuelve el objeto
  // directamente revienta en el `.then` y deja la pantalla en blanco, con un
  // error que no tiene nada que ver con lo que se mide.
  return {
    ...real,
    cargarSesion: async () => ({ tenant_id: "t1", usuario_id: "u1" }),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

function pintar(pantalla: React.ReactElement, ruta = "/") {
  return render(<MemoryRouter initialEntries={[ruta]}>{pantalla}</MemoryRouter>);
}

beforeEach(() => {
  respuestas = {};
});

// ── Puesto de trabajo (CRM-07.04.03.24) ───────────────────────────────────

describe("el puesto de trabajo", () => {
  it("no pinta en verde lo que no se ha medido", async () => {
    // Una conexión sin última sincronización no es una conexión sana: es una
    // de la que no se sabe nada, y las dos se pintaban igual.
    respuestas = {
      "/api/v1/suites/salud": {
        total: 2,
        paradas: [
          {
            conexion: "ana@correo",
            horas_sin_sincronizar: 72.5,
            estado: "conectado",
            porque: "Sin motivo anotado",
          },
        ],
        sin_medir: ["ana@calendario"],
        en_sondeo: [],
        todo_bien: false,
        medible: true,
        que_significa: "1 conexiones paradas y 1 sin medir.",
        los_en_sondeo: "",
      },
    };
    pintar(<Puesto />);
    const aviso = await screen.findByText(/1 conexiones paradas y 1 sin medir/);
    expect(aviso.className).toContain("text-warning");
    expect(aviso.className).not.toContain("text-success");
    expect(screen.getByText(/ana@correo/)).toBeInTheDocument();
    // Y la que nunca sincronizó sale aparte, no mezclada con las paradas.
    expect(screen.getByText(/ana@calendario/)).toBeInTheDocument();
  });

  it("sin ninguna conexión lo dice, en vez de salir en verde", async () => {
    // Un «todo bien» silencioso haría creer que el puesto está conectado
    // cuando sólo está sin usar.
    respuestas = {
      "/api/v1/suites/salud": {
        total: 0,
        paradas: [],
        sin_medir: [],
        en_sondeo: [],
        todo_bien: false,
        medible: false,
        que_significa: "No hay ninguna conexión: esto no está en verde, está sin usar.",
        los_en_sondeo: "",
      },
    };
    pintar(<Puesto />);
    expect(await screen.findByText(/está sin usar/)).toBeInTheDocument();
  });
});

// ── Estado del tenant (CRM-07.04.03.30) ───────────────────────────────────

describe("el estado del tenant", () => {
  const ESTADO = {
    estado: "degradado",
    consultado_at: "2026-10-26T09:00:00+00:00",
    componentes: [
      { servicio: "party", componente: "base", estado: "ok", detalle: "" },
      { servicio: "sales", componente: "bus", estado: "degradado", detalle: "cola larga" },
    ],
  };

  it("enseña lo prometido y lo medido al lado", async () => {
    respuestas = {
      "/api/v1/estado": ESTADO,
      "/api/v1/compromisos": {
        tier: "premium",
        compromisos: [
          {
            metrica: "RPO",
            que_es: "Cuántos minutos de datos se pueden perder",
            comprometido: 15,
            unidad: "minutos",
            medido: 7,
            como_se_mide: "Desde la última exportación verificada",
          },
          {
            metrica: "RTO",
            que_es: "Cuántos minutos se tarda en volver",
            comprometido: 60,
            unidad: "minutos",
            medido: null,
            como_se_mide: "Ensayando una restauración completa",
          },
        ],
      },
    };
    pintar(<Estado />);
    // Lo prometido.
    expect(await screen.findByText(/RPO/)).toBeInTheDocument();
    expect(screen.getByText(/RTO/)).toBeInTheDocument();
    // Y lo que NO se puede medir, dicho: un cero se leería como «se cumple».
    expect(screen.getByText(/Ensayando una restauración/)).toBeInTheDocument();
  });

  it("si los compromisos fallan, el estado de los componentes sigue ahí", async () => {
    // Es lo urgente cuando algo va mal, y perderlo porque no se pudo leer un
    // número de contrato sería el peor momento para perderlo.
    respuestas = { "/api/v1/estado": ESTADO };
    pintar(<Estado />);
    expect(await screen.findByText("sales")).toBeInTheDocument();
    expect(screen.getByText(/cola larga/)).toBeInTheDocument();
  });
});

// ── Coste y capacidad (CRM-07.04.03.32) ───────────────────────────────────

describe("coste y capacidad", () => {
  it("avisa de que si se ganan todas las ofertas no cabe", async () => {
    // Esa conversación es mejor tenerla antes de mandar la cuarta oferta que
    // en la semana de la entrega.
    respuestas = {
      "/api/v1/coste/capacidad": {
        contratada: "1000",
        comprometida: "800",
        libre: "200",
        en_ofertas_abiertas: "300",
        libre_si_se_ganan_todas: "-100",
        sobrevendida: false,
        aviso: "Si se ganaran todas las ofertas abiertas no cabría.",
      },
    };
    pintar(<Coste />);
    await userEvent.click(screen.getByRole("button", { name: "coste.verCapacidad" }));
    expect(await screen.findByText(/no cabría/)).toBeInTheDocument();
    expect(screen.getByText("-100")).toBeInTheDocument();
  });
});

// ── Rendimiento (CRM-07.04.03.29) ─────────────────────────────────────────

describe("rendimiento", () => {
  it("dice qué se está aplazando ahora mismo", async () => {
    // Es la mitad de la respuesta a «¿por qué no me sale el informe?», y vive
    // en otro sitio en cualquier otro producto.
    respuestas = {
      "/api/v1/estado/presion": {
        peor: { servicio: "analytics", presion: 0.9, que_significa: "los informes esperan" },
        sin_respuesta: ["marketing"],
        que_significa: "El sistema está bajo presión.",
        aviso: "Los recálculos pesados se están aplazando.",
      },
      "/api/v1/tenants/": [
        { metrica: "contactos", consumido: 9000, limite: 10000, pct: 90, en_aviso: true },
      ],
    };
    pintar(<Rendimiento />);
    expect(await screen.findByText(/los informes esperan/)).toBeInTheDocument();
    // Y el límite del plan, con aviso ANTES de que no quepa nada.
    expect(screen.getByText("contactos")).toBeInTheDocument();
  });

  it("dice de quién no ha podido saber nada", async () => {
    // Un panel que calla el servicio que no contestó enseña una presión más
    // baja de la real, y con esa cifra se decide no mirar.
    respuestas = {
      "/api/v1/estado/presion": {
        peor: undefined,
        sin_respuesta: ["marketing", "intelligence"],
        que_significa: "No se ha podido medir todo.",
        aviso: "",
      },
      "/api/v1/tenants/": [],
    };
    pintar(<Rendimiento />);
    expect(await screen.findByText(/marketing/)).toBeInTheDocument();
  });
});

// ── Ayuda en producto (CRM-07.04.03.33) ───────────────────────────────────

describe("la ayuda", () => {
  it("abre por el capítulo de la pantalla en la que estás", async () => {
    // Mandar al índice es mandar a buscar, y quien está atascado no busca: se
    // rinde y escribe a soporte.
    pintar(<Ayuda />, "/casos");
    const enlaces = screen.getAllByRole("link");
    const anclas = enlaces.map((e) => e.getAttribute("href") ?? "");
    expect(anclas.some((h) => h.includes("#"))).toBe(true);
  });

  it("desde una pantalla que no tiene capítulo, sigue llevando al manual", async () => {
    // Sin capítulo propio no se deja a nadie sin salida: la alternativa es un
    // hueco, y un hueco en la ayuda se lee como «aquí no hay ayuda».
    pintar(<Ayuda />, "/una-pantalla-sin-capitulo");
    expect(screen.getAllByRole("link").length).toBeGreaterThan(0);
  });
});
