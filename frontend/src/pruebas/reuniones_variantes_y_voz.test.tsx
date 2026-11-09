/**
 * Transcripción y resumen de una reunión con sus compromisos, variantes de
 * copy con revisión y el modo voz del asistente (CRM-01.02.01.05,
 * CRM-01.02.01.06, CRM-02.04.01.04, CRM-04.02.01.08).
 *
 * Lo que fijan:
 *
 *   · el texto pegado viaja con la base para grabar y el aviso; sin aviso no
 *     se puede mandar;
 *   · un compromiso NO crea la tarea al transcribir: se ve, se corrige y sólo
 *     confirmar la pide —con el asunto corregido—; la cita que no está en lo
 *     transcrito se avisa;
 *   · las variantes se piden con la base y el objetivo, y aprobar manda el
 *     texto reescrito;
 *   · en modo voz, lo dictado se pregunta y la respuesta se lee en voz alta.
 *
 * Los rótulos se comprueban por su clave de traducción, como en el resto.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

type Doble = (
  ruta: string,
  opciones?: { metodo?: string; cuerpo?: unknown },
) => unknown;

const pedidas: { ruta: string; metodo: string; cuerpo?: unknown }[] = [];
const subidas: { ruta: string; campos: Record<string, string> }[] = [];

async function con(doble: Doble) {
  vi.resetModules();
  pedidas.length = 0;
  subidas.length = 0;
  vi.doMock("@/lib/api", async () => {
    const real = await vi.importActual<Record<string, unknown>>("@/lib/api");
    return {
      ...real,
      llamar: async (
        ruta: string,
        opciones?: { metodo?: string; cuerpo?: unknown },
      ) => {
        pedidas.push({
          ruta,
          metodo: (opciones?.metodo ?? "GET").toUpperCase(),
          cuerpo: opciones?.cuerpo,
        });
        return { datos: doble(ruta, opciones) };
      },
      subir: async (
        ruta: string,
        _f: unknown,
        campos: Record<string, string>,
      ) => {
        subidas.push({ ruta, campos });
        return doble(ruta, { metodo: "POST", cuerpo: campos });
      },
    };
  });
  vi.doMock("@/lib/permisos", async () => {
    const real =
      await vi.importActual<Record<string, unknown>>("@/lib/permisos");
    return {
      ...real,
      useSuperficie: () => ({ superficie: null, tiene: () => true }),
    };
  });
}

const TRANSCRIPCION = {
  id: "tr1",
  origen: "texto",
  texto: "Te mando la oferta el jueves.",
  confianza: null,
  fiable: true,
  minutos: null,
  resumen: "Se manda la oferta el jueves.",
  compromisos: [
    {
      n: 0,
      tipo: "compromiso",
      texto: "Mandar la oferta",
      quien: "Comercial",
      cuando: "2026-11-12",
      cita: "te la paso el jueves",
      cita_literal: false,
      se_hace_tarea: true,
      estado: "propuesta",
    },
  ],
  descartados: [],
  estado: "resumida",
  aviso: "",
  que_no_es: "Esto no es un acta.",
  created_at: "2026-11-09T10:00:00Z",
};

describe("transcripción de la reunión", () => {
  it("resume, propone y sólo confirmar crea la tarea con el asunto corregido", async () => {
    await con((ruta, opciones) => {
      if (ruta === "/api/v1/transcripciones/proveedor")
        return {
          configurado: false,
          envio: "enlace",
          max_mb: 25,
          plantillas: [],
          porque: "Sin proveedor.",
        };
      if (ruta.startsWith("/api/v1/transcripciones/reuniones?"))
        return { items: [] };
      if (ruta === "/api/v1/transcripciones/reuniones/transcribir")
        return TRANSCRIPCION;
      if (ruta.includes("/compromisos/0"))
        return {
          ...TRANSCRIPCION,
          compromisos: [
            {
              ...TRANSCRIPCION.compromisos[0],
              estado: "confirmada",
              tarea_id: "t9",
              asunto: (opciones?.cuerpo as { asunto: string }).asunto,
            },
          ],
        };
      return {};
    });
    const { TranscripcionDeReunion } =
      await import("@/componentes/TranscripcionDeReunion");
    render(
      <MemoryRouter>
        <TranscripcionDeReunion actividadId="a1" />
      </MemoryRouter>,
    );
    const u = userEvent.setup();
    expect(await screen.findByText("Sin proveedor.")).toBeTruthy();
    await u.selectOptions(
      screen.getByLabelText("transcripcionReunion.fuente"),
      "texto",
    );
    await u.type(
      screen.getByLabelText("transcripcionReunion.texto"),
      "Te mando la oferta el jueves, seguro.",
    );
    const boton = screen.getByRole("button", {
      name: /transcripcionReunion.transcribir/,
    });
    // Sin avisar a los participantes no se puede mandar.
    expect((boton as HTMLButtonElement).disabled).toBe(true);
    await u.click(screen.getByLabelText("transcripcionReunion.avisados"));
    await u.click(boton);
    expect(
      await screen.findByText("Se manda la oferta el jueves."),
    ).toBeTruthy();
    expect(subidas[0]).toMatchObject({
      ruta: "/api/v1/transcripciones/reuniones/transcribir",
      campos: {
        objeto: "actividad",
        objeto_id: "a1",
        base_para_grabar: "consentimiento_de_todos",
        participantes_avisados: "true",
        texto: "Te mando la oferta el jueves, seguro.",
      },
    });
    expect(screen.getByText("transcripcionReunion.citaNoLiteral")).toBeTruthy();
    // Nada creado todavía.
    expect(pedidas.some((p) => p.ruta.includes("/compromisos/"))).toBe(false);

    const asunto = screen.getByDisplayValue("Mandar la oferta");
    await u.clear(asunto);
    await u.type(asunto, "Mandar oferta v2");
    await u.click(
      screen.getByRole("button", { name: /transcripcionReunion.crearTarea/ }),
    );
    await waitFor(() =>
      expect(pedidas.at(-1)).toMatchObject({
        ruta: "/api/v1/transcripciones/reuniones/tr1/compromisos/0",
        metodo: "POST",
        cuerpo: { confirmar: true, asunto: "Mandar oferta v2" },
      }),
    );
    expect(
      await screen.findByText("transcripcionReunion.abrirTarea"),
    ).toBeTruthy();
  });
});

describe("variantes de copy", () => {
  it("genera con la base y el objetivo, y aprobar manda el texto reescrito", async () => {
    await con((ruta) => {
      if (ruta.startsWith("/api/v1/variantes/generadas?")) return { items: [] };
      if (ruta === "/api/v1/variantes/generar")
        return {
          aviso: "",
          variantes: [
            {
              id: "v1",
              lote_id: "l1",
              texto_propuesto: "Ahorra un 40 %",
              texto_final: null,
              estado: "propuesta",
              ganadora: false,
              afirmaciones: [{ texto: "40 %", es: "un porcentaje concreto" }],
              hubo_reescritura: false,
              motivo: "",
            },
          ],
        };
      if (ruta.endsWith("/decidir"))
        return {
          id: "v1",
          lote_id: "l1",
          texto_propuesto: "Ahorra un 40 %",
          texto_final: "Ahorra este mes",
          estado: "aprobada",
          ganadora: false,
          afirmaciones: [],
          hubo_reescritura: true,
          motivo: "",
        };
      return {};
    });
    const { VariantesDeCopy } = await import("@/componentes/VariantesDeCopy");
    render(
      <VariantesDeCopy
        objeto="plantilla_correo"
        objetoRef="bienvenida"
        textoBase="Bienvenido"
      />,
    );
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("variantesCopy.objetivo"), "Que abran");
    await u.click(
      screen.getByRole("button", { name: /variantesCopy.generar/ }),
    );
    expect(await screen.findByText(/porcentaje concreto/)).toBeTruthy();
    expect(pedidas.at(-1)).toMatchObject({
      ruta: "/api/v1/variantes/generar",
      cuerpo: {
        base: "Bienvenido",
        objetivo: "Que abran",
        objeto: "plantilla_correo",
        objeto_ref: "bienvenida",
      },
    });
    const caja = screen.getByDisplayValue("Ahorra un 40 %");
    await u.clear(caja);
    await u.type(caja, "Ahorra este mes");
    await u.click(
      screen.getByRole("button", { name: /variantesCopy.aprobar/ }),
    );
    await waitFor(() =>
      expect(pedidas.at(-1)).toMatchObject({
        ruta: "/api/v1/variantes/generadas/v1/decidir",
        cuerpo: { aprobar: true, texto_final: "Ahorra este mes" },
      }),
    );
    expect(await screen.findByText("variantesCopy.reescrita")).toBeTruthy();
  });
});

describe("modo voz del asistente", () => {
  it("lo dictado se pregunta y la respuesta se lee en voz alta", async () => {
    const leidas: string[] = [];
    class Reconocedor {
      lang = "";
      interimResults = false;
      continuous = false;
      onresult: ((e: unknown) => void) | null = null;
      onerror: ((e: unknown) => void) | null = null;
      onend: (() => void) | null = null;
      start() {
        this.onresult?.({
          results: [[{ transcript: "¿Cuándo vence el contrato?" }]],
        });
        this.onend?.();
      }
      stop() {}
    }
    vi.stubGlobal("webkitSpeechRecognition", Reconocedor);
    vi.stubGlobal(
      "SpeechSynthesisUtterance",
      class {
        lang = "";
        onend: (() => void) | null = null;
        constructor(public text: string) {}
      },
    );
    vi.stubGlobal("speechSynthesis", {
      cancel: () => undefined,
      speak: (f: { text: string }) => leidas.push(f.text),
    });
    await con((ruta) =>
      ruta.endsWith("/conversar")
        ? {
            texto: "Vence en marzo [1].",
            respondida: true,
            fuentes: [],
            porque: "",
            accion_propuesta: null,
          }
        : {},
    );
    const { Asistente } = await import("@/paginas/Asistente");
    render(
      <MemoryRouter>
        <Asistente />
      </MemoryRouter>,
    );
    const u = userEvent.setup();
    await u.click(screen.getByLabelText("asistente.voz.modo"));
    expect(screen.getByText("asistente.voz.via.navegador")).toBeTruthy();
    await u.click(screen.getByRole("button", { name: /asistente.voz.hablar/ }));
    await waitFor(() =>
      expect(pedidas.at(-1)).toMatchObject({
        ruta: "/api/v1/ia/asistencia/conversar",
        cuerpo: { pregunta: "¿Cuándo vence el contrato?" },
      }),
    );
    // Se lee sin los números de cita.
    await waitFor(() => expect(leidas).toEqual(["Vence en marzo ."]));
    vi.unstubAllGlobals();
  });
});
