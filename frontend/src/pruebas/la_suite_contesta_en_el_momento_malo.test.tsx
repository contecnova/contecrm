/**
 * Las dos preguntas que se hacen cuando la suite falla.
 *
 * El servidor las contestaba desde el primer día y no había dónde hacerlas:
 *
 *   · «esto no conecta, ¿qué falta exactamente?» — porque «error de
 *     autenticación» es lo que atasca una implantación una semana y termina
 *     con alguien pidiendo permisos de administrador global «para descartar»;
 *   · «si lo desconecto, ¿qué me llevo y qué se queda?» — porque nadie
 *     desconecta sin saberlo, y entonces queda vivo el acceso de quien ya no
 *     está.
 *
 * Lo que estas pruebas fijan es lo que las hace útiles y no decorativas: que
 * los alcances se escriban **como los lista el proveedor** —separados por
 * comas, no en JSON—, que el veredicto se **anuncie** porque aparece lejos del
 * botón, y que el plan de baja enseñe **las dos mitades**, que es donde está
 * todo el valor: enseñar sólo lo que se borra asusta, y enseñar sólo lo que se
 * queda engaña.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const enviado: { ruta: string; cuerpo?: unknown }[] = [];

const PLAN = {
  motivo: "revocacion",
  se_queda: [
    {
      que: "Las actividades registradas",
      porque: "Es el histórico de la empresa",
    },
  ],
  se_borra: [
    {
      que: "El token y el refresco",
      porque: "Un token vivo es un acceso sin vigilar",
    },
  ],
};

async function montar() {
  vi.resetModules();
  enviado.length = 0;
  vi.doMock("@/lib/api", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/api");
    return {
      ...real,
      llamar: async (
        ruta: string,
        opciones?: { metodo?: string; cuerpo?: unknown },
      ) => {
        enviado.push({ ruta, cuerpo: opciones?.cuerpo });
        if (ruta.includes("/suites/baja/")) return { datos: PLAN };
        if (ruta.includes("/suites/diagnostico")) {
          return {
            datos: {
              ok: false,
              que_pasa: "Faltan permisos concretos",
              faltan_alcances: ["Calendars.ReadWrite"],
              que_hacer: "Pedir exactamente estos alcances",
            },
          };
        }
        return { datos: { lista: [] } };
      },
    };
  });
  // Los dos paneles por separado, no la pantalla entera: lo que se prueba es
  // lo que contestan, y montar el resto obligaría a doblar media docena de
  // rutas que no tienen nada que ver.
  const { CuandoNoConecta, AntesDeDesconectar } =
    await import("@/paginas/Suite");
  return render(
    <>
      <CuandoNoConecta />
      <AntesDeDesconectar />
    </>,
  );
}

describe("la suite en el momento malo", () => {
  beforeEach(() => {
    enviado.length = 0;
  });

  it("los alcances se escriben como los lista el proveedor, no en JSON", async () => {
    const usuario = userEvent.setup();
    await montar();
    await screen.findByText("suite.noConecta");

    await usuario.type(screen.getByLabelText("suite.codigoHttp"), "403");
    await usuario.type(
      screen.getByLabelText("suite.alcancesConcedidos"),
      "Mail.Read, Calendars.Read",
    );
    await usuario.type(
      screen.getByLabelText("suite.alcancesNecesarios"),
      "Mail.Read Calendars.ReadWrite",
    );
    await usuario.click(screen.getByRole("button", { name: "suite.queFalla" }));

    const peticion = enviado.find((p) =>
      p.ruta.includes("/suites/diagnostico"),
    );
    expect(peticion, "no se ha preguntado al servidor").toBeDefined();
    // Separados por comas O por espacios: lo que el consultor tiene delante es
    // la pantalla de consentimiento del proveedor, no un editor de JSON.
    expect(peticion!.cuerpo).toMatchObject({
      codigo: 403,
      alcances_concedidos: ["Mail.Read", "Calendars.Read"],
      alcances_necesarios: ["Mail.Read", "Calendars.ReadWrite"],
    });

    // Y el veredicto se ve, con el alcance que falta por su nombre: sin él,
    // «faltan permisos» obliga a adivinar cuál.
    await screen.findByText("Faltan permisos concretos");
    expect(screen.getByText("Calendars.ReadWrite")).toBeInTheDocument();
  });

  it("el código vacío no se manda como cero", async () => {
    const usuario = userEvent.setup();
    await montar();
    await screen.findByText("suite.noConecta");
    await usuario.click(screen.getByRole("button", { name: "suite.queFalla" }));

    // `Number("")` es 0, y un 0 se leería como un código HTTP que no existe.
    // Sin esto, preguntar sin código daría un veredicto sobre nada.
    const peticion = enviado.find((p) =>
      p.ruta.includes("/suites/diagnostico"),
    );
    expect((peticion!.cuerpo as { codigo: unknown }).codigo).toBeNull();
  });

  it("el plan de baja enseña las dos mitades, no sólo lo que se borra", async () => {
    await montar();
    await screen.findByText("suite.antesDeDesconectar");

    // Enseñar sólo lo que desaparece asusta y nadie desconecta; enseñar sólo
    // lo que se queda engaña. Las dos, o no sirve.
    await screen.findByText("Las actividades registradas");
    expect(screen.getByText("El token y el refresco")).toBeInTheDocument();
    // Y cada una con su porqué: sin él es una norma que alguien discutirá.
    expect(
      screen.getByText("Es el histórico de la empresa"),
    ).toBeInTheDocument();
  });

  it("cambiar el motivo vuelve a preguntar: la respuesta no es la misma", async () => {
    const usuario = userEvent.setup();
    await montar();
    await screen.findByText("suite.antesDeDesconectar");
    enviado.length = 0;

    await usuario.selectOptions(
      screen.getByLabelText("suite.porQueSeDesconecta"),
      "fin_del_contrato",
    );
    expect(
      enviado.some((p) => p.ruta.includes("/suites/baja/fin_del_contrato")),
      "no se ha vuelto a preguntar con el motivo nuevo",
    ).toBe(true);
  });
});
