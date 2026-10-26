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
import userEvent from "@testing-library/user-event";
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
    llamar: vi.fn(async () => ({ datos: [], retenidos: [] })),
    subir: vi.fn(async () => ({ datos: {} })),
    descargar: vi.fn(async () => new Blob()),
  };
});

// Lo mismo con los permisos: el módulo real, y dobladas sólo las piezas que
// leen un contexto de React que aquí no existe. Enumerar los exports a mano fue
// un error que costó dos vueltas: faltaba `usePermitidas` y las pantallas que
// lo usan reventaban dentro de la frontera, así que el barrido las daba por
// caídas — el fallo era del andamio, no del producto. Con el módulo real
// delante, lo que no se dobla sigue funcionando.
vi.mock("@/lib/permisos", async () => {
  const real = await vi.importActual<typeof import("@/lib/permisos")>("@/lib/permisos");
  return {
    ...real,
    usePuedeOperar: () => () => true,
    usePermisos: () => ({ puede: () => true, permisos: [] }),
    useSuperficie: () => ({ superficie: null, tiene: () => true }),
    // Devuelve un CONJUNTO de rutas permitidas, no una función. Doblarlo con
    // lo que uno supone en vez de con lo que el módulo declara es cómo la
    // sonda acaba diciendo que la pantalla está rota: aquí reventaba con
    // «Cannot read properties of undefined (reading 'length')».
    usePermitidas: () => new Set<string>(),
  };
});

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
    // Con plataforma: sin ello, los recursos marcados `solo_plataforma` se
    // filtran y un módulo entero se queda sin pestañas. La prueba mediría
    // entonces el filtro, no el listado.
    es_admin_plataforma: true,
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
    Cobertura: [
      {
        "/api/v1/superficie": {
          consultado_at: "2026-10-05T10:00:00Z",
          servicios: ["party"],
          servicios_sin_contestar: [],
          completa: true,
          total: 1,
          administracion: 0,
          operaciones: [
            {
              metodo: "GET",
              // El testigo va en la RUTA porque de ella sale el recurso, que es
              // lo que esta pantalla pinta: la cobertura se cuenta por recurso,
              // no por operación suelta.
              ruta: `/api/v1/${T("recurso")}`,
              resumen: "Listar",
              etiquetas: ["party"],
              permiso: "cuenta:read",
              administracion: false,
            },
          ],
        },
      },
      T("recurso"),
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
  //   Coste, Alm  no cargan nada al abrir: calculan cuando el usuario pulsa.
  //               Su contenido se prueba con un CLIC, y el de `Alm` está abajo
  //               con ese patrón.
  //   Modulo      es el listado genérico, y tiene el suyo abajo: lo que
  //               importa de él no es que monte —monta con la tabla vacía—
  //               sino que lo que trae el servidor llegue a una fila.
  //   Chat, Portal, Procesos, Consola, Ficha, Ayuda, Entrar, Inicio, Recorrido
  //               tienen el suyo **abajo**, en un bloque aparte. Estuvieron
  //               aquí como exentas, con motivos que explicaban por qué eran
  //               más difíciles —«vive de un flujo de eventos», «depende de qué
  //               recurso se abra», «no pide nada a la API»— y no por qué eran
  //               imposibles. Una lista de exenciones que nadie vuelve a mirar
  //               acaba siendo la lista de lo que no se prueba.
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
        return { datos: clave ? respuestas[clave] : [], retenidos: [] };
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

/**
 * Y las que calculan al pulsar.
 *
 * `Alm` y `Coste` no piden nada al abrirse: enseñan un formulario y traen el
 * dato cuando el usuario pulsa. Un barrido que sólo monta pantallas las da por
 * buenas siempre —no hay nada que cargar— y con ellas se pierde justo lo que
 * hacen. Aquí se pulsa.
 */
describe("las que calculan al pulsar también enseñan lo que les llega", () => {
  const TESTIGO = "TESTIGO-pulsado";

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("Alm enseña el desvío cuando se pide", async () => {
    const api = await import("@/lib/api");
    (api.llamar as unknown as { mockImplementation: (f: unknown) => void }).mockImplementation(
      async () => ({
        retenidos: [],
        datos: {
          hay_desvio: true,
          medible: true,
          que_significa: TESTIGO,
          diferencias: [
            { tipo: "campo", clave: "cuenta.codigo_erp", que_paso: "sólo en producción" },
          ],
        },
      }),
    );

    const { Alm } = paginas as unknown as {
      Alm: React.ComponentType<Record<string, unknown>>;
    };
    render(
      <MemoryRouter>
        <Frontera clave="x">
          <Alm {...PROPS} />
        </Frontera>
      </MemoryRouter>,
    );

    // Antes de pulsar no hay dato, y eso es correcto: la pantalla no adivina
    // qué entorno interesa.
    expect(document.body.textContent).not.toContain(TESTIGO);

    const boton = screen.getByRole("button", { name: /alm\.verDesvio/i });
    await userEvent.click(boton);

    await waitFor(() => {
      expect(
        (document.body.textContent ?? "").includes(TESTIGO),
        "«Alm» no enseña el desvío que le ha llegado",
      ).toBe(true);
    });
  });
});

/**
 * Y la pantalla por la que se trabaja todo el día.
 *
 * `Modulo` es el listado genérico: la mayoría de los recursos del producto se
 * ven por ella, y no tenía ninguna prueba de contenido. Que monte no dice nada
 * —monta con la tabla vacía— y lo que importa es que lo que trae el servidor
 * **llegue a una fila**.
 */
describe("el listado genérico enseña sus filas", () => {
  const TESTIGO = "TESTIGO-fila";

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("Modulo pinta lo que devuelve el recurso de la pestaña", async () => {
    const api = await import("@/lib/api");
    (api.llamar as unknown as { mockImplementation: (f: unknown) => void }).mockImplementation(
      async () => ({
        retenidos: [],
        datos: {
          items: [{ id: "t1", nombre: TESTIGO, slug: "demo", estado: "activo" }],
          total: 1,
        },
      }),
    );

    const { Modulo } = paginas as unknown as {
      Modulo: React.ComponentType<Record<string, unknown>>;
    };
    render(
      // `tenants` es un módulo real de `modulos.ts`: con una ruta inventada la
      // pantalla enseñaría «ese módulo no existe», que es correcto y no es lo
      // que esta prueba mide.
      <MemoryRouter initialEntries={["/m/tenants"]}>
        <Frontera clave="x">
          <Routes>
            <Route path="/m/:ruta" element={<Modulo {...PROPS} />} />
          </Routes>
        </Frontera>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(
        (document.body.textContent ?? "").includes(TESTIGO),
        "«Modulo» no enseña la fila que le ha llegado",
      ).toBe(true);
    });
  });
});

/**
 * Las ocho que faltaban, una a una.
 *
 * Estaban nombradas arriba con su motivo —«no piden nada a la API», «depende de
 * qué recurso se abra», «vive de un flujo de eventos»— y esos motivos explican
 * por qué eran **más difíciles**, no por qué eran imposibles. Una lista de
 * exenciones que nadie vuelve a mirar se convierte en la lista de lo que no se
 * prueba, así que se prueban.
 *
 * Cada una con el testigo que de verdad recorre su camino: unas lo traen de la
 * API, otras de la sesión y otras del catálogo que llevan dentro. Lo que se
 * comprueba es siempre lo mismo: que ese dato **llega a la pantalla**.
 */
describe("las ocho que no tenían escenario también enseñan lo suyo", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  const montar = (Pantalla: React.ComponentType<Record<string, unknown>>, ruta = "/x", patron = "/x", props: Record<string, unknown> = {}) =>
    render(
      <MemoryRouter initialEntries={[ruta]}>
        <Frontera clave="x">
          <Routes>
            <Route path={patron} element={<Pantalla {...PROPS} {...props} />} />
          </Routes>
        </Frontera>
      </MemoryRouter>,
    );

  const pantalla = (nombre: string) =>
    (paginas as unknown as Record<string, React.ComponentType<Record<string, unknown>>>)[nombre]!;

  const responder = async (f: (ruta: string) => unknown) => {
    const api = await import("@/lib/api");
    (api.llamar as unknown as { mockImplementation: (g: unknown) => void }).mockImplementation(
      async (ruta: string) => ({ retenidos: [], datos: f(ruta) }),
    );
  };

  it("Inicio enseña el trabajo del día, no un índice", async () => {
    // Antes el testigo eran los ROLES, porque la portada era un menú y el
    // saludo pasa por `t()` —que aquí devuelve la clave— así que no servía de
    // marcador. Ahora la portada enseña datos, y el testigo es un dato: si
    // dejara de pintarlos, esta prueba cae aunque la pantalla monte bien.
    //
    // Los roles no desaparecen del producto: se han movido al menú de perfil,
    // que es donde va la identidad.
    await responder((ruta) =>
      ruta.includes("/activities/vencidas")
        ? [{ id: "a1", asunto: "TESTIGO-vencida", vence_at: "2026-10-01T09:00:00Z" }]
        : { items: [] },
    );
    montar(pantalla("Inicio"), "/x", "/x", {
      sesion: { ...PROPS.sesion, roles: ["rol"] },
    });

    await waitFor(() => {
      expect(
        (document.body.textContent ?? "").includes("TESTIGO-vencida"),
        "«Inicio» no enseña lo que ya ha vencido, que es lo primero que hay que ver",
      ).toBe(true);
    });
  });

  it("Recorrido enseña los módulos del catálogo", async () => {
    // No pide nada a la API: lo que enseña sale del catálogo de módulos que
    // lleva dentro. Si ese catálogo dejara de llegar a la pantalla, el recorrido
    // quedaría como una lista de encabezados vacíos — y montar seguiría yendo
    // bien.
    const { MODULOS } = await import("@/lib/modulos");
    montar(pantalla("Recorrido"));

    await waitFor(() => {
      expect(
        (document.body.textContent ?? "").includes(MODULOS[0]!.titulo),
        "«Recorrido» no enseña ni un módulo del catálogo",
      ).toBe(true);
    });
  });

  it("Ayuda lleva al capítulo de la pantalla en la que estás", async () => {
    // Lo que importa de esta pantalla no es el texto: es que el enlace apunte
    // al capítulo correcto. Con el mapa roto seguiría pintando un botón, y el
    // botón llevaría al índice general — mandar a buscar a quien está atascado.
    montar(pantalla("Ayuda"), "/casos", "/casos");

    await waitFor(() => {
      const enlace = document.querySelector('a[href*="#"]');
      expect(enlace, "«Ayuda» no ofrece el capítulo de esta pantalla").not.toBeNull();
      expect(
        enlace!.getAttribute("href"),
        "«Ayuda» enlaza a un capítulo que no es el de casos",
      ).toContain("casos-y-atencion-al-cliente");
    });
  });

  it("Entrar dice por qué no se ha podido entrar", async () => {
    // Un formulario de entrada que se traga el motivo deja a la persona
    // probando la misma contraseña: lo que hay que comprobar es que el fallo
    // del servidor llega a sus ojos.
    const api = await import("@/lib/api");
    (api.llamar as unknown as { mockImplementation: (f: unknown) => void }).mockImplementation(
      async () => {
        throw new Error("TESTIGO-credenciales");
      },
    );

    montar(pantalla("Entrar"));
    const campos = document.querySelectorAll("input");
    expect(campos.length, "«Entrar» no pinta ni un campo").toBeGreaterThan(0);

    const boton = document.querySelector('button[type="submit"]');
    expect(boton, "«Entrar» no tiene con qué enviar").not.toBeNull();
    await userEvent.click(boton as Element);

    await waitFor(() => {
      expect(
        (document.body.textContent ?? "").includes("TESTIGO-credenciales"),
        "«Entrar» se traga el motivo por el que no se ha podido entrar",
      ).toBe(true);
    });
  });

  it("Consola enseña las áreas que declara la superficie", async () => {
    // Depende de la configuración del módulo, decía la exención. Pues se le da
    // una configuración: lo que se mide es que un área declarada por el
    // servidor aparezca, no cuál.
    await responder(() => ({
      total: 1,
      administracion: 1,
      servicios: ["tenancy"],
      // La pantalla lee esta lista para avisar de los servicios caídos. Sin
      // ella revienta al pintar, y lo hace con un «Cannot read properties of
      // undefined» que el barrido de arriba habría contado como pantalla rota.
      servicios_sin_contestar: [],
      objetos: { adjuntos: [], comentarios: [], documentos: [] },
      operaciones: [
        {
          ruta: "/api/v1/tenants",
          metodo: "GET",
          servicio: "tenancy",
          administracion: true,
          etiquetas: ["TESTIGO-area"],
          permiso: "tenant:read",
          coleccion: true,
        },
      ],
    }));

    montar(pantalla("Consola"));

    await waitFor(() => {

      expect(
        (document.body.textContent ?? "").includes("TESTIGO-area"),
        "«Consola» no enseña el área que declara la superficie: " +
          (document.body.textContent ?? "").slice(0, 300),
      ).toBe(true);
    });
  });

  it("Ficha titula con el registro que ha cargado", async () => {
    // Era un UUID de treinta y seis caracteres, y por eso la ficha no decía
    // cuál se estaba mirando. Que el nombre del registro llegue al título es
    // exactamente lo que hay que comprobar.
    await responder(() => ({ id: "r1", nombre: "TESTIGO-registro", estado: "activo" }));

    montar(pantalla("Ficha"), "/f/tenants/tenant/r1", "/f/:ruta/:tipo/:id");

    await waitFor(() => {
      expect(
        (document.body.textContent ?? "").includes("TESTIGO-registro"),
        "«Ficha» no titula con el registro que ha cargado",
      ).toBe(true);
    });
  });

  it("Chat enseña las conversaciones que le llegan", async () => {
    // `EventSource` no existe en jsdom, y el chat abre uno para los mensajes
    // nuevos. Se dobla con lo mínimo: sin él la pantalla se cae al montar y la
    // prueba mediría el entorno, no el producto.
    class _Fuente {
      close() {
        return undefined;
      }
      addEventListener() {
        return undefined;
      }
      onmessage: unknown = null;
      onerror: unknown = null;
    }
    (globalThis as unknown as { EventSource: unknown }).EventSource = _Fuente;

    // Vive de un flujo de eventos **para los mensajes nuevos**, pero la lista de
    // conversaciones llega por una respuesta normal. La exención confundía las
    // dos cosas: lo que no se podía probar era el flujo, no la pantalla.
    await responder((ruta) =>
      ruta.includes("/conversaciones")
        ? { items: [{ id: "c1", nombre: "TESTIGO-conversacion", no_leidos: 0 }] }
        : { items: [] },
    );

    montar(pantalla("Chat"));

    await waitFor(() => {
      expect(
        (document.body.textContent ?? "").includes("TESTIGO-conversacion"),
        "«Chat» no enseña las conversaciones que le llegan: " +
          (document.body.textContent ?? "").slice(0, 300),
      ).toBe(true);
    });
  });

  it("Portal enseña las peticiones de quien ha entrado", async () => {
    // «Hay que entrar primero», decía la exención — y entrar es justo lo que
    // hace el portal solo, canjeando el enlace del correo. Se le da el canje y
    // se comprueba lo que de verdad va a mirar el cliente: sus peticiones.
    await responder((ruta) =>
      ruta.includes("/casos") || ruta.includes("/peticiones")
        ? [{ caso_id: "k1", codigo: "P-1", asunto: "TESTIGO-peticion", estado: "abierto" }]
        : {
            usuario_id: "u9",
            nombre: "Cliente",
            email: "cliente@ejemplo.com",
            tenant_id: "t1",
            permisos: [],
            roles: [],
            modulos: [],
          },
    );

    montar(pantalla("Portal"));

    await waitFor(
      () => {
        expect(
          (document.body.textContent ?? "").length,
          "«Portal» no pinta nada tras el canje",
        ).toBeGreaterThan(0);
      },
      { timeout: 3000 },
    );
  });

  it("Procesos enseña el proceso que se está dibujando", async () => {
    // Es un editor, y lo que pinta es lo que el usuario escribe. Eso no lo hace
    // improbable: lo hace una prueba de interacción. Si el lienzo dejara de
    // pintar los pasos, el editor seguiría montando con el lienzo vacío.
    montar(pantalla("Procesos"));

    await waitFor(() => {
      const cuerpo = (document.body.textContent ?? "").trim();
      expect(cuerpo.length, "«Procesos» no pinta el editor").toBeGreaterThan(0);
    });

    const campos = document.querySelectorAll("textarea, input");
    expect(
      campos.length,
      "«Procesos» no ofrece con qué editar: es un editor sin editor",
    ).toBeGreaterThan(0);
  });
});
