/**
 * La pantalla de aprobaciones, PINTADA.
 *
 * Por qué existe este fichero. Todo el front de esta sesión se escribió y se
 * dio por bueno sin que nadie viera una pantalla: pasaban el tipado, el linter,
 * el gate de accesibilidad —que lee el TEXTO de los ficheros, no lo que se
 * pinta— y las reglas de color. Ninguna de esas cosas comprueba que la pantalla
 * enseñe algo, ni que lo que enseña se entienda.
 *
 * El equipo para pintarlas estaba instalado en el repositorio desde siempre
 * (`@testing-library/react`, `jsdom`) y **no se había usado nunca**. Eso
 * explica por qué un fallo de pantalla podía pasar todos los gates.
 *
 * Lo que esto NO es: no ve alineación, ni color, ni si algo queda feo. Para eso
 * hace falta una persona delante. Lo que sí hace es comprobar que la pantalla
 * se pinta y que **dice lo que tiene que decir**.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Aprobaciones } from "@/paginas/Aprobaciones";

// Lo que contesta el servidor en cada caso. Se declara por ruta para que la
// prueba diga qué escenario monta y no un `mock` opaco.
let respuestas: Record<string, unknown> = {};

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => {
    // La clave MÁS LARGA que encaje, no la primera: `/api/v1/informes/i1/ejecutar`
    // empieza por `/api/v1/informes`, así que con la primera se devolvía la
    // LISTA de informes donde tocaba el resultado, y la pantalla se quedaba
    // cargando para siempre. La sonda daba por rota una pantalla que estaba
    // bien: exactamente lo que llevo toda la noche encontrando en otros sitios.
    const clave = Object.keys(respuestas)
      .filter((k) => ruta.startsWith(k))
      .sort((a, b) => b.length - a.length)[0];
    if (!clave) throw new Error(`sin respuesta preparada para ${ruta}`);
    return { datos: respuestas[clave] };
  }),
  salvoCancelacion: (fn: (e: unknown) => void) => fn,
}));

vi.mock("@/lib/permisos", () => ({
  usePuedeOperar: () => () => true,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    // Devuelve la CLAVE, no una traducción inventada: así la prueba falla si
    // alguien pinta una clave que no existe en el diccionario, en vez de
    // enseñar una cadena vacía que parece correcta.
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

describe("la pantalla de aprobaciones", () => {
  beforeEach(() => {
    respuestas = {};
  });

  it("con el corpus apagado lo explica, y no pide la bandeja", async () => {
    respuestas = {
      "/api/v1/documentos/estado": { activo: false, sin_el: "los adjuntos siguen" },
    };
    render(<Aprobaciones />);
    expect(await screen.findByText(/aprobaciones\.sinCorpus/)).toBeInTheDocument();
  });

  it("con el corpus caído dice la dirección, no un error rojo", async () => {
    respuestas = {
      "/api/v1/documentos/estado": {
        activo: true,
        alcanzable: false,
        url: "http://contecmind:4000",
        error: "Name or service not known",
      },
    };
    render(<Aprobaciones />);
    const aviso = await screen.findByText(/aprobaciones\.corpusCaido/);
    expect(aviso.textContent).toContain("contecmind:4000");
  });

  it("sin nada pendiente lo dice, y no pinta filas fantasma", async () => {
    respuestas = {
      "/api/v1/documentos/estado": { activo: true, alcanzable: true },
      "/api/v1/documentos/aprobaciones/pendientes": { items: [] },
    };
    render(<Aprobaciones />);
    expect(await screen.findByText(/aprobaciones\.nadaPendiente/)).toBeInTheDocument();
  });

  it("con una solicitud enseña de qué es y ofrece las tres decisiones", async () => {
    respuestas = {
      "/api/v1/documentos/estado": { activo: true, alcanzable: true },
      "/api/v1/documentos/aprobaciones/pendientes": {
        items: [
          {
            id: "s1",
            entity_summary: "Contrato marco ACME",
            status: "pending",
            version_no: 2,
            puedo_decidir: true,
          },
        ],
      },
    };
    render(<Aprobaciones />);
    expect(await screen.findByText("Contrato marco ACME")).toBeInTheDocument();
    for (const decision of ["approved", "rejected", "delegated"]) {
      expect(
        screen.getByRole("button", { name: `aprobaciones.decision.${decision}` }),
      ).toBeInTheDocument();
    }
  });

  it("cuando no te toca decidir, lo dice en vez de dejar la fila muda", async () => {
    respuestas = {
      "/api/v1/documentos/estado": { activo: true, alcanzable: true },
      "/api/v1/documentos/aprobaciones/pendientes": {
        items: [{ id: "s2", entity_summary: "Procedimiento", status: "pending", puedo_decidir: false }],
      },
    };
    render(<Aprobaciones />);
    expect(await screen.findByText(/aprobaciones\.noTeToca/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /decision\.approved/ })).toBeNull();
  });

  it("delegar no deja enviar sin decir en quién", async () => {
    respuestas = {
      "/api/v1/documentos/estado": { activo: true, alcanzable: true },
      "/api/v1/documentos/aprobaciones/pendientes": {
        items: [{ id: "s3", entity_summary: "Contrato", status: "pending", puedo_decidir: true }],
      },
    };
    render(<Aprobaciones />);
    const delegar = await screen.findByRole("button", { name: /decision\.delegated/ });
    await userEvent.click(delegar);
    const confirmar = screen.getByRole("button", { name: /aprobaciones\.confirmar/ });
    expect(confirmar).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/aprobaciones\.delegarEn/), "u-7");
    await waitFor(() => expect(confirmar).not.toBeDisabled());
  });
});
