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

import { StrictMode } from "react";
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
  // **Con `StrictMode`, como la aplicación de verdad.** En desarrollo monta,
  // desmonta y vuelve a montar, y eso es lo que destapó que la pantalla se
  // quedaba muerta después del primer clic: sin esto, la prueba montaba una
  // sola vez y no reproducía nada.
  return render(
    <StrictMode>
      <Preguntar />
    </StrictMode>,
  );
}

async function preguntar() {
  const usuario = userEvent.setup();
  await montar();
  const caja = await screen.findByLabelText("preguntar.quePides");
  // Aquí nunca se elige agente: contesta siempre el asistente.
  await usuario.type(caja, "qué cuentas están en riesgo");
  await usuario.click(screen.getByRole("button", { name: "preguntar.planificar" }));
  return usuario;
}

describe("nexus", () => {
  beforeEach(() => {
    // `tipo` decide quién contesta en Nexus, así que el doble tiene que
    // declararlo: con un tipo cualquiera, estas pruebas pasarían midiendo otra
    // pantalla.
    agentes = [
      { id: "a1", clave: "analista", tipo: "asistente_conversacional", activo: true },
    ];
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

  it("la pantalla sigue viva después del doble montaje de desarrollo", async () => {
    // `StrictMode` monta, desmonta y vuelve a montar. La bandera de «sigo
    // vivo» se ponía a `false` en la limpieza y no volvía a `true` al montar,
    // así que el segundo montaje arrancaba muerto: la pantalla pedía el plan,
    // lo recibía y **no lo pintaba**, y el botón se apagaba y no volvía. Una
    // pantalla que acepta la pregunta y no hace nada, sin un solo error.
    const usuario = userEvent.setup();
    actuacion = {
      ejecucion_id: "e1",
      objetivo: "qué cuentas están en riesgo",
      estado: "ejecutando",
      tokens: 10,
      pasos: [unPaso(1)],
      reversible_del_todo: true,
      no_reversibles: [],
    };
    await montar();
    await usuario.type(
      await screen.findByLabelText("preguntar.quePides"),
      "qué cuentas están en riesgo",
    );
    await usuario.click(screen.getByRole("button", { name: "preguntar.planificar" }));

    // El plan se PINTA: si la bandera estuviera muerta, la respuesta llegaría
    // y se descartaría.
    await screen.findByText(/vuelta 1/);
    // Y el botón vuelve: si no, no se puede preguntar nunca más.
    expect(screen.getByRole("button", { name: "preguntar.planificar" })).toBeEnabled();
  });

  it("no se elige agente: se dice quién responde y se escribe", async () => {
    // Elegir agente es, en realidad, elegir con qué permisos y con qué
    // herramientas se contesta. Eso no es una pregunta para quien escribe
    // «qué cuentas están en riesgo». Lo que sobra es el desplegable; el dato
    // no, porque saber qué asistente contesta es parte de poder no fiarse de
    // la respuesta.
    await montar();
    await screen.findByLabelText("preguntar.quePides");
    expect(screen.queryByLabelText("preguntar.quienResponde")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.getByText("analista")).toBeInTheDocument();

    // Y el botón se desbloquea sólo con escribir lo que se pide.
    const usuario = userEvent.setup();
    expect(screen.getByRole("button", { name: "preguntar.planificar" })).toBeDisabled();
    await usuario.type(screen.getByLabelText("preguntar.quePides"), "qué cuentas peligran");
    expect(screen.getByRole("button", { name: "preguntar.planificar" })).toBeEnabled();
  });

  it("los agentes de tarea no contestan aquí", async () => {
    // Proponer la respuesta de un caso o calificar un lead son trabajos con un
    // registro delante: su sitio es la pantalla de ese trabajo. Ofrecerlos en
    // la caja de «pregúntale al sistema» era dar a elegir entre cosas que no
    // contestan la misma pregunta.
    agentes = [
      { id: "a1", clave: "primera-respuesta", tipo: "respuesta_soporte", activo: true },
      { id: "a2", clave: "califica", tipo: "calificacion_leads", activo: true },
    ];
    await montar();
    await screen.findByText("preguntar.sinAgentes");
    expect(screen.queryByText("primera-respuesta")).toBeNull();
    expect(screen.queryByText("califica")).toBeNull();
  });

  it("con varios asistentes contesta siempre el mismo", async () => {
    // El orden en que los devuelva el servidor no es una decisión de producto:
    // que la respuesta dependa de él sería imposible de explicar.
    agentes = [
      { id: "a2", clave: "zeta", tipo: "asistente_conversacional", activo: true },
      { id: "a1", clave: "alfa", tipo: "asistente_conversacional", activo: true },
    ];
    await montar();
    await screen.findByLabelText("preguntar.quePides");
    expect(screen.getByText("alfa")).toBeInTheDocument();
    expect(screen.queryByText("zeta")).toBeNull();
  });

  it("un asistente apagado no contesta", async () => {
    agentes = [
      { id: "a1", clave: "analista", tipo: "asistente_conversacional", activo: true },
      { id: "a2", clave: "apagado", tipo: "asistente_conversacional", activo: false },
    ];
    await montar();
    await screen.findByLabelText("preguntar.quePides");
    expect(screen.getByText("analista")).toBeInTheDocument();
    expect(screen.queryByText("apagado")).toBeNull();
  });

  it("sin agentes declarados se dice qué falta, no sólo que no hay", async () => {
    agentes = [];
    await montar();
    await screen.findByText("preguntar.sinAgentes");
    expect(screen.getByText("preguntar.sinAgentesDetalle")).toBeInTheDocument();
  });
});
