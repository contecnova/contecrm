/**
 * La pantalla de una instancia de proceso: dónde va, qué pasó y cómo se saca.
 *
 * Las cuatro cosas que enseña estaban publicadas en la API y no se alcanzaban
 * desde ninguna pantalla: el listado de instancias abría la ficha genérica,
 * que enseña columnas —`estado`, `paso_actual`, un identificador— y ninguna de
 * ésas es la pregunta que se hace delante de un proceso parado.
 *
 * Lo que se afirma aquí es **el dato que sólo puede venir de la respuesta de
 * su ruta**, no que el identificador de la capacidad aparezca en el fichero:
 * eso lo cumple igual un comentario. Validado plantando: quitar cualquiera de
 * los paneles del montaje pone en rojo su prueba y sólo la suya.
 *
 * Y la que más importa de las cuatro: que saltar **sólo ofrezca los destinos
 * que el propio paso declara**. Un desplegable con todos los pasos convertiría
 * el rescate en un «ejecuta lo que quieras» sobre un proceso en marcha.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pedidas: string[] = [];

const GRAFICO = {
  instancia_id: "i-1",
  proceso: "pedido_grande",
  version: 1,
  estado: "esperando",
  paso_actual: "pedir_visto_bueno",
  error: null,
  arrancada_at: null,
  finalizada_at: null,
  nodos: [
    { paso: "pedir_visto_bueno", tipo: "humano", estado: "actual", veces: 1, intentos: 1, duracion_ms: 0, error: null, tarea_pendiente: null },
    { paso: "enviar", tipo: "servicio", estado: "pendiente", veces: 0, intentos: 0, duracion_ms: 0, error: null, tarea_pendiente: null },
    { paso: "fin_no", tipo: "fin", estado: "no_recorrido", veces: 0, intentos: 0, duracion_ms: 0, error: null, tarea_pendiente: null },
  ],
  recorrido: [{ paso: "pedir_visto_bueno", resultado: "en_curso", intento: 2 }],
};

const DEFINICIONES = [
  {
    id: "d-1",
    clave: "pedido_grande",
    version: 1,
    nombre: "Pedido grande",
    estado: "publicada",
    definicion: {
      inicio: "pedir_visto_bueno",
      pasos: {
        pedir_visto_bueno: {
          tipo: "humano",
          rutas: { aprobar: "enviar", rechazar: "fin_no" },
        },
        enviar: { tipo: "servicio", siguiente: "fin_si" },
        fin_si: { tipo: "fin" },
        fin_no: { tipo: "fin" },
      },
    },
  },
  // Otra versión, para comprobar que NO se coge: pintar sobre el gráfico nuevo
  // señalaría pasos que esta instancia no tiene.
  {
    id: "d-2",
    clave: "pedido_grande",
    version: 2,
    nombre: "Pedido grande",
    estado: "publicada",
    definicion: {
      inicio: "paso_de_otra_version",
      pasos: { paso_de_otra_version: { tipo: "fin" } },
    },
  },
];

const ANALITICA = {
  proceso: "pedido_grande",
  instancias: 4,
  terminadas: 2,
  falladas: 1,
  concluyente: false,
  aviso: "Con 4 ejecuciones el dato no es concluyente.",
  ciclo_horas_medio: 31.5,
  ciclo_horas_mediana: 12,
  cuello_de_botella: "pedir_visto_bueno",
  pasos: [
    {
      paso: "pedir_visto_bueno",
      tipo: "humano",
      veces: 4,
      fallos: 1,
      con_reintento: 0,
      motor_ms_medio: 3,
      espera_horas_media: 29,
      espera_horas_mediana: 10,
      pendientes_ahora: 2,
    },
  ],
};

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      pedidas.push(ruta);
      const datos = ruta.includes("/grafico")
        ? GRAFICO
        : ruta.startsWith("/api/v1/procesos/definiciones")
          ? DEFINICIONES
          : ruta.startsWith("/api/v1/analitica-procesos/")
            ? ANALITICA
            : {};
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
  const { InstanciaDeProceso } = await import("@/paginas/InstanciaDeProceso");
  return render(
    <MemoryRouter initialEntries={["/m/procesos/instancia/i-1"]}>
      <Routes>
        <Route path="/m/procesos/instancia/:id" element={<InstanciaDeProceso />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("una instancia parada se ve y se desatasca", () => {
  beforeEach(() => {
    pedidas.length = 0;
  });

  it("pinta el gráfico sobre la definición de SU versión", async () => {
    await montar();
    // Dentro del propio lienzo: el nombre del paso sale también en el camino
    // y en la analítica, y buscarlo suelto no diría si se ha pintado el
    // diagrama o sólo las listas de al lado.
    const lienzo = await waitFor(() => screen.getByRole("img"));
    const cajas = Array.from(lienzo.querySelectorAll("text")).map(
      (n) => n.textContent,
    );
    expect(cajas).toContain("pedir_visto_bueno");
    expect(cajas).toContain("enviar");
    // El paso de la versión 2 no puede aparecer: esta instancia no lo tiene.
    expect(cajas).not.toContain("paso_de_otra_version");
    // Y el estado va ESCRITO, no sólo en el color del borde.
    expect(cajas).toContain("instancia.estado.actual");
  });

  it("enseña qué pasó en orden, con el intento", async () => {
    await montar();
    await waitFor(() =>
      expect(screen.getByText(/instancia.intento.*"n":2/)).toBeTruthy(),
    );
  });

  it("sólo deja saltar a los destinos que el paso declara", async () => {
    await montar();
    await waitFor(() => expect(screen.getByLabelText(/instancia.saltarA/)).toBeTruthy());
    const opciones = Array.from(
      screen.getByLabelText(/instancia.saltarA/).querySelectorAll("option"),
    ).map((o) => o.getAttribute("value"));
    // Las dos rutas de la tarea humana, y NADA más: `fin_si` sólo se alcanza
    // pasando por `enviar`, así que ofrecerlo sería saltarse el envío.
    expect(opciones).toEqual(["", "enviar", "fin_no"]);
  });

  it("dice dónde se atasca el proceso y que el dato no es concluyente", async () => {
    await montar();
    await waitFor(() =>
      expect(screen.getByText(/instancia.cuello.*pedir_visto_bueno/)).toBeTruthy(),
    );
    // El aviso del servidor, tal cual: un cuello de botella deducido de cuatro
    // ejecuciones lleva a rediseñar un flujo que funcionaba.
    expect(screen.getByText(ANALITICA.aviso)).toBeTruthy();
    // La mediana al lado de la media.
    expect(screen.getByText(/instancia.ciclo.*"mediana":12/)).toBeTruthy();
  });
});
