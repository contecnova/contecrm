/**
 * Ninguna pantalla deja al usuario sin nada que ver.
 *
 * Medido el 05-10-2026: de veintisiete pantallas, **cuatro** tenían prueba de
 * contenido. Las otras veintitrés pasaban el tipado, el linter, el gate de
 * accesibilidad —que lee el TEXTO de los ficheros, no lo que se pinta—, las
 * reglas de color y el barrido de Playwright, que comprueba que montan con el
 * servidor contestando bien. Ninguna de esas cosas dice qué pasa cuando no.
 *
 * Lo que este fichero vigila es eso: **la respuesta con una forma que la
 * pantalla no esperaba**. Es el caso real —una versión de la API por delante
 * del front, un campo que se renombró, un despliegue a medias— y hasta el
 * 04-10-2026 dejaba el `<body>` vacío: sin mensaje, sin menú y sin nada que el
 * usuario pueda contarle a soporte.
 *
 * La `Frontera` se puso para eso. Esto comprueba que **sigue puesta y que
 * basta**: que con una respuesta deforme cada pantalla o se pinta igual, o se
 * cae dentro de la frontera y enseña un error — pero nunca se lleva por delante
 * el marco.
 *
 * Lo que esto NO es:
 *
 *   * no ve alineación, ni color, ni si algo queda feo: para eso hace falta una
 *     persona delante;
 *   * **no sustituye a una prueba por pantalla** que compruebe lo que esa
 *     pantalla concreta tiene que decir con datos de verdad. Cuatro la tienen
 *     —`aprobaciones`, `cuadros`, `suite`, `ficha_documentos`— y veintitrés no.
 *     Esto es el suelo común, no el techo.
 */

import type React from "react";

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Frontera } from "@/componentes/Frontera";

import * as paginas from "./_todas_las_pantallas";

// La respuesta DEFORME: una lista vacía donde media pantalla espera un objeto y
// al revés. Es lo que llega el día que la API va por delante del front, y es
// justo el caso que nadie prueba porque «la API devuelve lo que devuelve».
// Se dobla SOLO lo que sale a la red. Todo lo demás del módulo es el de verdad
// —`filas`, que saca la lista de una respuesta con tres formas distintas, y
// `ErrorApi`—: doblarlo haría que esta prueba midiera mi versión del producto y
// no el producto. Costó verlo: con `filas` doblada por un `undefined`, tres
// pantallas se quedaban en «cargando» para siempre porque el `.then` reventaba
// en silencio, y el barrido daba por rotas tres pantallas que estaban bien.
vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async () => ({ datos: [] })),
    subir: vi.fn(async () => ({ datos: {} })),
    descargar: vi.fn(async () => new Blob()),
  };
});

vi.mock("@/lib/permisos", () => ({
  usePuedeOperar: () => () => true,
  usePermisos: () => ({ puede: () => true, permisos: [] }),
  // `useSuperficie` lee un contexto que aquí no existe. Sin doblarlo, las
  // pantallas que lo usan reventaban dentro de la frontera y el barrido las
  // daba por caídas: el fallo era del andamio, no del producto.
  useSuperficie: () => ({ superficie: null, tiene: () => true }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string) => clave,
    i18n: { language: "es", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: unknown }) => children ?? null,
  initReactI18next: { type: "3rdParty", init: () => undefined },
}));

// Se le pasa TODO a todas: la que no espera `sesion` la ignora. Una lista de
// props por pantalla se queda vieja en cuanto alguien cambia una firma, y
// entonces el barrido deja de montar media docena sin decirlo.
const PROPS = {
  sesion: {
    usuario_id: "u1",
    nombre: "Quien prueba",
    email: "quien@cliente.com",
    tenant_id: "t1",
    permisos: ["*"],
    roles: ["admin"],
    modulos: [],
  },
  alEntrar: () => undefined,
  alSalir: () => undefined,
  documentoId: "d1",
};

const COMPONENTES = Object.entries(paginas).filter(
  ([, valor]) => typeof valor === "function",
) as unknown as [string, React.ComponentType<Record<string, unknown>>][];

/** El marco: lo que tiene que seguir en pie pase lo que pase en la pantalla. */
const MARCO = "menú de la aplicación";

describe("ninguna pantalla deja al usuario sin nada que ver", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // React avisa por consola de cada error que recoge una frontera. Aquí es lo
    // esperado, y dejarlo escupiendo esconde los avisos que sí importan.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("se han encontrado todas las pantallas", () => {
    // Sin esto, un barrido que no encuentra nada pasa en verde y parece que
    // veintisiete pantallas están comprobadas. Es el fallo que este fichero
    // persigue, aplicado a sí mismo.
    expect(COMPONENTES.length).toBeGreaterThanOrEqual(25);
  });

  it.each(COMPONENTES)(
    "%s no se lleva por delante el marco",
    async (nombre, Pantalla) => {
      render(
        <MemoryRouter initialEntries={["/x/id-de-prueba"]}>
          <div>
            <nav>{MARCO}</nav>
            <Frontera clave="x">
              <Routes>
                <Route path="/x/:id" element={<Pantalla {...PROPS} />} />
              </Routes>
            </Frontera>
          </div>
        </MemoryRouter>,
      );

      // Lo que se exige: el marco sigue ahí. Que la pantalla se haya caído
      // dentro de la frontera es aceptable —enseña un error y se puede ir a
      // otro sitio—; que se lleve el marco, no: eso es el `<body>` vacío.
      await waitFor(() => {
        expect(
          screen.queryByText(MARCO),
          `«${nombre}» ha dejado la aplicación en blanco`,
        ).not.toBeNull();
      });

      // Y algo tiene que haberse pintado dentro: una frontera que recoge el
      // error y no dice nada es el mismo hueco con otro nombre.
      const cuerpo = (document.body.textContent ?? "").replace(MARCO, "").trim();
      expect(cuerpo.length, `«${nombre}» no pinta ni una palabra`).toBeGreaterThan(0);
    },
  );
});

/**
 * Y la otra mitad: con datos, cada pantalla **los enseña**.
 *
 * Lo de arriba comprueba que ninguna deja al usuario sin nada. Esto comprueba
 * lo contrario y es lo que de verdad echaba en falta: que lo que llega del
 * servidor **llega a la pantalla**. Una pantalla que pinta su cabecera, su
 * tabla vacía y su pie pasa todos los gates y no enseña ni un dato, y eso no se
 * nota mirando el código: se nota cuando alguien abre la pantalla.
 *
 * Cada escenario es una tabla endpoint → respuesta con un **testigo**, una
 * cadena que no aparece en ninguna otra parte. Si el testigo sale en el texto
 * pintado, el dato ha recorrido el camino entero: petición, estado, render.
 */
describe("con datos, la pantalla los enseña", () => {
  const T = (que: string) => `TESTIGO-${que}`;

  // endpoint → lo que contesta. La clave que gana es la MÁS LARGA que encaje:
  // `/api/v1/informes/i1/ejecutar` empieza por `/api/v1/informes`, y con la
  // primera que coincida se devuelve la lista donde tocaba el resultado — la
  // pantalla se queda cargando y la sonda da por rota una que está bien.
  const ESCENARIOS: Record<string, [Record<string, unknown>, string]> = {
    Casos: [
      {
        "/api/v1/casos": [
          {
            id: "c1",
            numero: "C-1",
            asunto: T("caso"),
            estado: "abierto",
            prioridad: "alta",
            vence_at: null,
            cuenta_id: null,
            cola: null,
            escalado: false,
          },
        ],
      },
      T("caso"),
    ],
    Conocimiento: [
      {
        "/api/v1/conocimiento/articulos": {
          items: [{ id: "a1", clave: T("articulo"), titulo: T("articulo"), estado: "publicado" }],
        },
      },
      T("articulo"),
    ],
    Cuadros: [
      {
        "/api/v1/cuadros-mando": [
          { id: "q1", clave: "ventas", nombre: T("cuadro"), componentes: [] },
        ],
        "/api/v1/informes": [],
      },
      T("cuadro"),
    ],
    Marketing: [
      {
        "/api/v1/segmentos": { items: [{ id: "s1", nombre: T("segmento") }] },
        "/api/v1/campanas": { items: [] },
      },
      T("segmento"),
    ],
    Pipeline: [
      {
        "/api/v1/pipelines": {
          items: [
            {
              id: "p1",
              nombre: "Ventas",
              por_defecto: true,
              // El testigo va en la ETAPA y no en el nombre del embudo: el
              // nombre sale dentro de un `<option>` del selector, que solo se
              // pinta cuando hay más de uno. La etapa es lo que el usuario ve
              // siempre, y es lo que esta pantalla existe para enseñar.
              etapas: [
                {
                  id: "e1",
                  clave: "prospecto",
                  nombre: T("etapa"),
                  orden: 1,
                  probabilidad: 10,
                  terminal: false,
                  ganada: false,
                },
              ],
            },
          ],
        },
        "/api/v1/opportunities": { items: [] },
      },
      T("etapa"),
    ],
    Inteligencia: [
      {
        "/api/v1/accounts": [{ id: "a1", nombre: T("cuenta") }],
      },
      T("cuenta"),
    ],
    ConsolaAgente: [
      {
        "/api/v1/consola-agente": {
          agente: { presencia: "disponible" },
          mis_casos: [
            {
              caso_id: "k1",
              codigo: T("caso-agente"),
              asunto: "Algo pasa",
              prioridad: "alta",
              estado: "abierto",
              minutos_restantes: 30,
            },
          ],
          mis_conversaciones: [],
        },
      },
      T("caso-agente"),
    ],
    Estado: [
      {
        "/api/v1/estado": {
          estado: "ok",
          consultado_at: "2026-10-05T10:00:00Z",
          componentes: [{ servicio: T("servicio"), componente: "base", estado: "ok" }],
        },
        "/api/v1/compromisos": {
          tier: "estándar",
          compromisos: [
            {
              metrica: "disponibilidad",
              que_es: "cuánto tiempo responde",
              comprometido: 99.5,
              unidad: "%",
              medido: 99.9,
              como_se_mide: "sondas",
            },
          ],
        },
      },
      T("servicio"),
    ],
    Puesto: [
      {
        "/api/v1/suites/salud": {
          total: 1,
          paradas: [
            {
              conexion: T("conexion"),
              horas_sin_sincronizar: 30,
              estado: "parada",
              porque: "sin credencial",
            },
          ],
          sin_medir: [],
          en_sondeo: [],
          todo_bien: false,
          medible: true,
          que_significa: "hay una parada",
          los_en_sondeo: "",
        },
      },
      T("conexion"),
    ],
    Rendimiento: [
      {
        "/api/v1/estado/presion": {
          sin_respuesta: [],
          que_significa: T("presion"),
          aviso: "",
        },
      },
      T("presion"),
    ],
    Explotacion: [
      {
        "/api/v1/explotacion/diagnostico": {
          puede_preguntar: true,
          problemas: [],
          sigue_funcionando: [],
          no_funciona: [],
          url_publica: "https://inteligencia.cliente.com",
          fuente_id: "f1",
        },
        "/api/v1/explotacion/preguntas": [
          {
            id: "p1",
            clave: "ventas-mes",
            titulo: T("pregunta"),
            pregunta: "¿Cuánto hemos vendido?",
            publicada: true,
            propia: true,
            informe_id: null,
          },
        ],
      },
      T("pregunta"),
    ],
    Cuenta: [
      {
        "/api/v1/accounts": {
          cuenta: {
            id: "a1",
            nombre: T("ficha"),
            estado: "activa",
            roles: ["cliente"],
            sector: { esquema: null, codigo: null },
            calidad: { puntuacion: 90, faltan: [] },
            owner_id: null,
          },
          identificadores: [],
          direcciones: [],
          contactos: [],
          timeline: [],
          metricas: {},
        },
        "/api/v1/opportunities": { items: [] },
        "/api/v1/casos": { items: [] },
      },
      T("ficha"),
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  // Las que NO tienen escenario aquí, y por qué. Se escribe en vez de dejarlas
  // fuera en silencio: una lista incompleta sin explicación se lee como una
  // lista completa.
  //
  //   Coste       no carga nada al abrir: calcula cuando el usuario pulsa. Su
  //               contenido se prueba con un clic, no con un render.
  //   Chat        vive de un flujo de eventos abierto, no de una respuesta.
  //   Portal      hay que entrar primero: lo que enseña depende del canje de
  //               un enlace, que es otro escenario.
  //   Procesos    es un editor; lo que pinta es lo que el usuario escribe.
  //   Alm, Ayuda, Cobertura, Consola, Ficha, Inicio, Modulo, Recorrido
  //               no piden nada a la API: componen otras piezas o pintan lo
  //               que les llega por props.
  //
  // Todas ellas sí pasan por el barrido de arriba, que es el que garantiza que
  // ninguna deja al usuario sin nada que ver.
  it.each(Object.keys(ESCENARIOS))("%s enseña lo que le llega", async (nombre) => {
    const [respuestas, testigo] = ESCENARIOS[nombre]!;
    const api = await import("@/lib/api");
    (api.llamar as unknown as { mockImplementation: (f: unknown) => void }).mockImplementation(
      async (ruta: string) => {
        const clave = Object.keys(respuestas)
          .filter((k) => ruta.startsWith(k))
          .sort((a, b) => b.length - a.length)[0];
        return { datos: clave ? respuestas[clave] : [] };
      },
    );

    const Pantalla = (
      paginas as unknown as Record<string, React.ComponentType<Record<string, unknown>>>
    )[nombre]!;
    render(
      <MemoryRouter initialEntries={["/x/id-de-prueba"]}>
        <Frontera clave="x">
          <Routes>
            <Route path="/x/:id" element={<Pantalla {...PROPS} />} />
          </Routes>
        </Frontera>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(
        (document.body.textContent ?? "").includes(testigo),
        `«${nombre}» no enseña el dato que le ha llegado`,
      ).toBe(true);
    });
  });
});
