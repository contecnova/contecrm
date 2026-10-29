/**
 * Qué sabe hacer cada suite declarada, y qué se puede preguntarle.
 *
 * Diez capacidades de esta familia estaban **servidas y sin pantalla**: el
 * perfil se declaraba, los alcances se concedían, el incremento funcionaba y la
 * política decidía qué entra — y lo único que se veía de todo eso era si un
 * buzón estaba parado. Un perfil que no se puede mirar no se puede revisar, y
 * es donde se cuela que una integración lea la agenda personal de alguien.
 *
 * Lo que fijan estas pruebas es que la pantalla enseña **lo que manda el
 * servidor** y no una versión suya: el sentido de cada recurso, el incremento,
 * el aviso de datos de terceros y lo que nunca entra. Si mañana el servidor
 * deja de mandar uno, la pantalla se queda sin la parte que la hacía revisable
 * y no da ningún error.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const respuestas: Record<string, unknown> = {};

/** Qué se mira antes. La de capacidades contiene la de perfiles. */
const ORDEN = [
  "/capacidades",
  "/suites/consentimiento",
  "/suites/reglas",
  "/suites/perfiles",
];
let fallaAntesDeSincronizar = false;

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      if (ruta.includes("antes-de-sincronizar") && fallaAntesDeSincronizar) {
        // Con la firma que declara el módulo —estado, código, título,
        // detalle y la FRASE del servidor—, no con un objeto suelto: esa
        // frase es lo que la pantalla enseña, y doblarlo de otra forma
        // probaría otra cosa.
        throw new real.ErrorApi(
          403,
          "suite.sin_consentimiento",
          "Sin permiso",
          null,
          "Nadie ha autorizado leer «correo» de esta persona.",
        );
      }
      // **En orden explícito, no por azar.** La ruta de capacidades es
      // `/suites/perfiles/…/capacidades`, así que contiene también
      // `/suites/perfiles`: casando por «la primera que encaje» —o por la más
      // larga— le llegaba la carga de los perfiles, `detalle` venía indefinido
      // y la sección reventaba. Un doble que casa por casualidad mide otra
      // cosa.
      const clave = ORDEN.find((k) => ruta.includes(k));
      return {
        datos: clave ? respuestas[clave] : {},
        version: null,
        retenidos: [],
        enmascarados: [],
      };
    }),
  };
});

vi.mock("@/lib/permisos", () => ({
  usePuedeOperar: () => () => true,
  useSuperficie: () => ({ superficie: null, tiene: () => true }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

async function montar() {
  // Sólo la sección nueva: montar el gobierno entero traería ocho llamadas
  // que no son lo que se está probando.
  const { QueSabeHacerCadaSuite } = await import("@/paginas/Suite");
  return render(<QueSabeHacerCadaSuite />);
}

describe("qué sabe hacer cada suite", () => {
  beforeEach(() => {
    fallaAntesDeSincronizar = false;
    respuestas["/suites/perfiles"] = {
      items: [{ id: "p1", nombre: "M365 del cliente", sistema: "m365" }],
    };
    respuestas["/capacidades"] = {
      recursos: ["calendario"],
      detalle: [
        {
          recurso: "calendario",
          sentidos: ["leer", "escribir"],
          incremento: "token_delta",
          trae_dato_de_terceros: true,
          aviso: "Trae datos de gente que no es ni usuaria ni cliente.",
        },
      ],
    };
    respuestas["/suites/reglas"] = {
      criterio: "con_contacto_del_crm",
      nunca_entra: ["marcado_privado", "borrador"],
      recursos_pedidos_que_no_permite_el_tenant: [],
      porque: "La preferencia personal estrecha la política; nunca la abre.",
    };
    respuestas["/suites/consentimiento"] = {
      items: [
        {
          id: "c1",
          usuario_id: "u1",
          perfil: "M365 del cliente",
          recurso: "correo",
          sentido: "leer",
          alcances: ["Mail.Read"],
          tiene_refresco: true,
        },
      ],
    };
  });

  it("enseña en qué sentido va cada recurso y con qué incremento", async () => {
    await montar();
    expect(await screen.findByText("calendario")).toBeInTheDocument();
    // «leer» y «leer y escribir» sobre el calendario de alguien no son lo
    // mismo, y es la línea que hay que poder revisar.
    expect(screen.getByText("leer")).toBeInTheDocument();
    expect(screen.getByText("escribir")).toBeInTheDocument();
    // Sin el incremento nadie sabe si una sincronización que tarda está
    // avanzando o repitiéndose.
    expect(screen.getByText("token_delta")).toBeInTheDocument();
  });

  it("el aviso de datos de terceros lo escribe el servidor, no la pantalla", async () => {
    await montar();
    expect(
      await screen.findByText(/no es ni usuaria ni cliente/),
    ).toBeInTheDocument();
  });

  it("dice qué entra y, sobre todo, qué no entra nunca", async () => {
    // Un recuadro que diga qué entra y calle qué no deja fuera justo la mitad
    // que alguien revisa.
    await montar();
    expect(await screen.findByText(/con_contacto_del_crm/)).toBeInTheDocument();
    expect(screen.getByText(/marcado_privado/)).toBeInTheDocument();
  });

  it("«¿se puede ya?» se pregunta desde el consentimiento, no a mano", async () => {
    // El servidor exige usuario, perfil y recurso, y los tres están en esa
    // fila. Un formulario suelto los pedía a mano y contestaba 422.
    const { llamar } = await import("@/lib/api");
    await montar();
    await userEvent.click(await screen.findByText("suite.sePuedeSincronizar"));
    const llamadas = vi.mocked(llamar).mock.calls;
    const pregunta = llamadas.find(([r]) =>
      String(r).includes("antes-de-sincronizar"),
    );
    expect(pregunta?.[1]).toMatchObject({
      cuerpo: { usuario_id: "u1", perfil: "M365 del cliente", recurso: "correo" },
    });
  });

  it("un 403 enseña lo que dijo el servidor, no un hueco", async () => {
    // El «no» llega como 403 y con el porqué en palabras. Tratarlo como un
    // error de la pantalla la deja en blanco y esconde la única frase que dice
    // qué hacer.
    fallaAntesDeSincronizar = true;
    await montar();
    await userEvent.click(await screen.findByText("suite.sePuedeSincronizar"));
    expect(
      await screen.findByText(/Nadie ha autorizado leer/),
    ).toBeInTheDocument();
  });
});
