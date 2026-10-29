/**
 * Nexus: el plan antes que el resultado.
 *
 * Esta pantalla es la única puerta del agente autónomo, y lo que la hace
 * aceptable no es que conteste: es que **se puede no fiarse de ella**. Lo que
 * estas pruebas fijan es justo eso, y en el orden en que duele si se rompe:
 *
 *   · preguntar NO ejecuta nada: devuelve un plan y el plan se ve;
 *   · el riesgo de cada paso está en pantalla ANTES de que haya nada que
 *     aprobar, no en la letra pequeña de después;
 *   · un paso que espera a una persona **para** el avance: la pantalla no
 *     sigue pidiendo vueltas por su cuenta;
 *   · una vuelta que sólo piensa se cuenta como tal. Si no, el botón parece
 *     roto cuando lo que ha hecho es decidir el paso siguiente;
 *   · y lo que no se deshace se dice antes de ofrecer el botón de deshacer.
 *
 * Los rótulos se comprueban por su CLAVE de traducción, como el resto de las
 * pruebas de pantalla: aquí no se inicia i18n, y afirmar sobre el castellano
 * convertiría cualquier retoque de redacción en una prueba roja.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pedidas: { ruta: string; metodo: string }[] = [];
let agentes: unknown[] = [];
let vueltas: unknown[] = [];
let actuacion: unknown = null;

function unPaso(orden: number, extra: Record<string, unknown> = {}) {
  return {
    id: `p${orden}`,
    orden,
    herramienta: "get_accounts",
    riesgo: "lectura",
    porque: `vuelta ${orden}`,
    estado: "planificado",
    reversible: true,
    ...extra,
  };
}

async function montar() {
  vi.resetModules();
  pedidas.length = 0;
  vi.doMock("@/lib/api", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/api");
    return {
      ...real,
      llamar: async (ruta: string, opciones?: { metodo?: string }) => {
        pedidas.push({ ruta, metodo: (opciones?.metodo ?? "GET").toUpperCase() });
        if (ruta.includes("/avanzar")) {
          return { datos: vueltas.shift() ?? { avanzado: false, terminada: true } };
        }
        if (ruta.includes("/lanzar")) return { datos: { ejecucion_id: "e1" } };
        if (ruta.includes("/ejecuciones/")) return { datos: actuacion };
        if (ruta.includes("/pasos/")) return { datos: {} };
        return { datos: agentes };
      },
    };
  });
  const { Preguntar } = await import("@/paginas/Preguntar");
  return render(<Preguntar />);
}

async function preguntar() {
  const usuario = userEvent.setup();
  await montar();
  const caja = await screen.findByLabelText("preguntar.quePides");
  // Con varios agentes hay que elegir; con uno solo no hay desplegable que
  // tocar, y es lo que comprueba su propia prueba más abajo.
  const selector = screen.queryByLabelText("preguntar.quienResponde");
  if (selector) await usuario.selectOptions(selector, "analista");
  await usuario.type(caja, "qué cuentas están en riesgo");
  await usuario.click(screen.getByRole("button", { name: "preguntar.planificar" }));
  return usuario;
}

describe("nexus", () => {
  beforeEach(() => {
    agentes = [{ id: "a1", clave: "analista", tipo: "calificacion_leads", activo: true }];
    vueltas = [];
    actuacion = null;
  });

  it("preguntar devuelve un plan y no ejecuta nada", async () => {
    actuacion = {
      ejecucion_id: "e1",
      objetivo: "qué cuentas están en riesgo",
      estado: "ejecutando",
      tokens: 150,
      pasos: [unPaso(1), unPaso(2, { riesgo: "escritura" })],
      reversible_del_todo: true,
      no_reversibles: [],
    };
    await preguntar();

    await screen.findByText(/vuelta 1/);
    // Lo que se ha llamado es lanzar y leer. Avanzar, no.
    expect(pedidas.some((p) => p.ruta.includes("/lanzar"))).toBe(true);
    expect(pedidas.some((p) => p.ruta.includes("/avanzar"))).toBe(false);
    // Y el riesgo de cada paso se lee ya, antes de aprobar nada.
    expect(screen.getByText("escritura")).toBeInTheDocument();
  });

  it("un paso que espera a una persona para el avance", async () => {
    actuacion = {
      ejecucion_id: "e1",
      objetivo: "borra los duplicados",
      estado: "esperando_aprobacion",
      tokens: 10,
      pasos: [unPaso(1, { riesgo: "destructivo", estado: "esperando_aprobacion" })],
      reversible_del_todo: true,
      no_reversibles: [],
    };
    await preguntar();

    await screen.findByText("preguntar.esperaAPersona");
    // El botón de seguir existe pero no se puede pulsar: la pantalla no
    // puede saltarse el control humano por comodidad.
    expect(screen.getByRole("button", { name: "preguntar.seguir" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "preguntar.autorizar" })).toBeEnabled();
  });

  it("una vuelta que sólo piensa se cuenta como tal", async () => {
    actuacion = {
      ejecucion_id: "e1",
      objetivo: "mira y luego decide",
      estado: "ejecutando",
      tokens: 10,
      pasos: [unPaso(1, { estado: "hecho" })],
      reversible_del_todo: true,
      no_reversibles: [],
    };
    vueltas = [
      {
        avanzado: false,
        paso_decidido: {
          orden: 2,
          herramienta: "get_invoices",
          riesgo: "lectura",
          porque: "mirar la facturación de las que han salido",
        },
      },
      { avanzado: true, estado: "hecho" },
      { avanzado: false, terminada: true, conclusion: "Tres cuentas en riesgo" },
    ];
    const usuario = await preguntar();
    await screen.findByText(/vuelta 1/);
    await usuario.click(screen.getByRole("button", { name: "preguntar.seguir" }));

    // Lo que ha hecho el botón se dice: sin esto parece que no ha pasado nada.
    await screen.findByText("Tres cuentas en riesgo");
    // Tres vueltas pedidas: pensar, ejecutar, terminar. Ni una más — seguir
    // llamando a una ejecución cerrada sería gastar presupuesto del agente.
    expect(pedidas.filter((p) => p.ruta.includes("/avanzar")).length).toBe(3);
  });

  it("lo que no se deshace se dice antes de ofrecer deshacer", async () => {
    actuacion = {
      ejecucion_id: "e1",
      objetivo: "avisa a los clientes",
      estado: "terminada",
      motivo_fin: "Objetivo cumplido",
      tokens: 10,
      pasos: [unPaso(1, { estado: "hecho", reversible: false, herramienta: "post_emails" })],
      reversible_del_todo: false,
      no_reversibles: [{ orden: 1, herramienta: "post_emails" }],
    };
    await preguntar();

    await screen.findByText(/preguntar.noTodoSeDeshace/);
    expect(screen.getByRole("button", { name: "preguntar.deshacer" })).toBeInTheDocument();
    // Y por qué paró, que no es lo mismo que «ya no quedan pasos».
    expect(screen.getByText(/Objetivo cumplido/)).toBeInTheDocument();
  });

  it("con un solo agente no se pregunta cuál, pero se dice quién responde", async () => {
    // Elegir de una lista de uno no es una decisión: es un paso obligatorio
    // para llegar al que sí lo es, con el botón bloqueado hasta darlo. Lo que
    // sobra es el desplegable; el dato no, porque saber qué agente contesta es
    // parte de poder no fiarse de la respuesta.
    await montar();
    await screen.findByLabelText("preguntar.quePides");
    expect(screen.queryByLabelText("preguntar.quienResponde")).toBeNull();
    expect(screen.queryByText("preguntar.elige")).toBeNull();
    expect(screen.getByText("analista")).toBeInTheDocument();

    // Y el botón se desbloquea sólo con escribir lo que se pide.
    const usuario = userEvent.setup();
    expect(screen.getByRole("button", { name: "preguntar.planificar" })).toBeDisabled();
    await usuario.type(screen.getByLabelText("preguntar.quePides"), "qué cuentas peligran");
    expect(screen.getByRole("button", { name: "preguntar.planificar" })).toBeEnabled();
  });

  it("con dos agentes sí se pregunta cuál", async () => {
    agentes = [
      { id: "a1", clave: "analista", tipo: "calificacion_leads", activo: true },
      { id: "a2", clave: "soporte", tipo: "respuesta_soporte", activo: true },
    ];
    await montar();
    await screen.findByLabelText("preguntar.quienResponde");
    expect(screen.getByText("preguntar.elige")).toBeInTheDocument();
  });

  it("un agente apagado no cuenta para decidir si hace falta elegir", async () => {
    // Dos filas pero una inactiva siguen siendo una opción de verdad: si se
    // contaran las dos, volvería el desplegable de un solo elemento usable.
    agentes = [
      { id: "a1", clave: "analista", tipo: "calificacion_leads", activo: true },
      { id: "a2", clave: "apagado", tipo: "respuesta_soporte", activo: false },
    ];
    await montar();
    await screen.findByLabelText("preguntar.quePides");
    expect(screen.queryByLabelText("preguntar.quienResponde")).toBeNull();
    expect(screen.getByText("analista")).toBeInTheDocument();
  });

  it("sin agentes declarados se dice qué falta, no sólo que no hay", async () => {
    agentes = [];
    await montar();
    await screen.findByText("preguntar.sinAgentes");
    expect(screen.getByText("preguntar.sinAgentesDetalle")).toBeInTheDocument();
  });
});
