/**
 * La paleta encuentra registros, no sólo pantallas.
 *
 * El manual prometía desde el primer día que la búsqueda mira a la vez en
 * cuentas, contactos, oportunidades, casos y documentos. `GET /api/v1/buscar`
 * lo hacía y **nadie la llamaba**: quien escribía «Acme» aquí encontraba la
 * pantalla de cuentas y luego tenía que buscar Acme dentro.
 *
 * Lo que fija esta prueba:
 *
 *   · se pide al servidor, con lo escrito;
 *   · los registros van **debajo** de las pantallas. La paleta se abre casi
 *     siempre para ir a un sitio, y ponerlos delante cambiaría lo que hace el
 *     `Intro` de quien ya la tiene en los dedos;
 *   · un resultado de un tipo que no vive en ningún módulo **no se enlaza**:
 *     una fila que lleva a una pantalla que no existe es peor que una de menos;
 *   · y un fallo de la búsqueda no rompe la paleta, que es lo que se vino a
 *     usar en el noventa por ciento de los casos.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

const pedidas: string[] = [];
let resultados: unknown[] = [];
let vistos: unknown[] = [];
let falla = false;

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => {
    pedidas.push(ruta);
    if (falla) throw new Error("no se ha podido buscar");
    // «Visto hace poco» se pide al abrir y devuelve una LISTA, no la forma de
    // la búsqueda. Contestarle con lo mismo que a `/buscar` no es un detalle
    // del doble: la paleta se quedaba en blanco entera, y con ella la
    // navegación por pantallas. Ahora la función se defiende y aquí se
    // contesta lo que contesta el servidor.
    if (ruta.startsWith("/api/v1/vistos")) {
      // **Con tope, para no alimentar un bucle.** Si la paleta volviera a
      // pedirlo en cada render —y ya pasó: `t` en las dependencias del
      // efecto— cada respuesta provoca otro render y otra petición.
      //
      // Dicho con honestidad: el tope **no convierte el caso malo en un
      // rojo**. Se probó plantándolo y el fichero sigue sin terminar en 240 s,
      // así que lo que delata ese fallo es que la pasada no acaba, no un
      // assert. El tope sí evita que además se coma la memoria de la pasada
      // entera, que es como se descubrió: 4 GB y «JavaScript heap out of
      // memory» en la suite completa.
      if (pedidas.filter((r) => r.startsWith("/api/v1/vistos")).length > 4) {
        return new Promise(() => undefined);
      }
      return { datos: { items: vistos } };
    }
    return { datos: { resultados, servicios_sin_responder: [] } };
  }),
}));

vi.mock("@/lib/permisos", () => ({
  useVisibilidad: () => ({
    rutas: new Set<string>(),
    cargada: false,
    sinContestar: new Set<string>(),
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

const { Paleta } = await import("@/componentes/Paleta");

function abrir() {
  return render(
    <MemoryRouter>
      <Paleta abierta sesion={null} alCerrar={() => undefined} />
    </MemoryRouter>,
  );
}

describe("la paleta busca registros", () => {
  beforeEach(() => {
    pedidas.length = 0;
    resultados = [];
    vistos = [];
    falla = false;
  });

  it("pide al servidor lo que se escribe", async () => {
    resultados = [
      { objeto: "cuenta", registro_id: "c1", titulo: "Acme Ibérica", subtitulo: "Cliente" },
    ];
    abrir();
    await userEvent.type(screen.getByRole("textbox"), "acme");
    await waitFor(() =>
      expect(pedidas.some((r) => r.includes("/api/v1/buscar?q=acme"))).toBe(true),
    );
    expect(await screen.findByText("Acme Ibérica")).toBeInTheDocument();
  });

  it("los registros van debajo de las pantallas", async () => {
    resultados = [
      { objeto: "cuenta", registro_id: "c1", titulo: "Acme Ibérica", subtitulo: "" },
    ];
    abrir();
    // «cuentas» casa con la pantalla de cuentas Y con el registro.
    await userEvent.type(screen.getByRole("textbox"), "cuentas");
    await screen.findByText("Acme Ibérica");
    const filas = [...document.querySelectorAll("li")].map((n) => n.textContent ?? "");
    // La paleta se abre para ir a un sitio: poner los registros delante
    // cambiaría lo que hace el Intro de quien ya la tiene en los dedos.
    expect(filas.findIndex((f) => f.includes("Acme Ibérica"))).toBeGreaterThan(0);
  });

  it("«visto hace poco» sale con la caja vacía, delante de las pantallas", async () => {
    vistos = [
      {
        objeto_tipo: "cuenta",
        objeto_id: "c1",
        nombre: "Ibérica Levante",
        visto_at: "2026-11-03T10:00:00Z",
      },
    ];
    abrir();
    expect(await screen.findByText("Ibérica Levante")).toBeInTheDocument();
    const filas = [...document.querySelectorAll("li")].map((n) => n.textContent ?? "");
    // La PRIMERA. Es a donde va quien abre la paleta sin saber todavía qué va
    // a escribir, y es lo que hace Salesforce al pinchar el buscador.
    expect(filas[0]).toContain("Ibérica Levante");
  });

  it("y se pide UNA vez, no una por tecla", async () => {
    // **Medido el 03-11-2026.** La primera versión metía `t` en las
    // dependencias del efecto, y `useTranslation` devuelve una función nueva
    // en cada render: con la paleta abierta, cada pulsación relanzaba el
    // efecto —una petición y un `AbortController` vivo por tecla—. En la
    // suite entera llevó el proceso a 4 GB y reventó con «JavaScript heap out
    // of memory»; en el navegador habría sido una ráfaga de peticiones al
    // escribir.
    vistos = [
      {
        objeto_tipo: "cuenta",
        objeto_id: "c1",
        nombre: "Ibérica Levante",
        visto_at: "2026-11-03T10:00:00Z",
      },
    ];
    abrir();
    await screen.findByText("Ibérica Levante");
    await userEvent.type(screen.getByRole("textbox"), "cuentas");
    await new Promise((r) => setTimeout(r, 300));
    const cuantas = pedidas.filter((r) => r.startsWith("/api/v1/vistos")).length;
    expect(cuantas, `se ha pedido ${cuantas} veces`).toBe(1);
  });

  it("una respuesta con otra forma deja la paleta en pie", async () => {
    // El servidor devuelve una lista. Si devolviera otra cosa, la paleta no
    // puede quedarse en blanco: con ella se pierde también la navegación por
    // pantallas, que es a lo que se abre el 90 % de las veces.
    vistos = "ni una lista" as unknown as unknown[];
    abrir();
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
    expect(screen.getByText("nav.inicio")).toBeInTheDocument();
  });

  it("con una sola letra no se pregunta: sería una consulta por pulsación", async () => {
    abrir();
    await userEvent.type(screen.getByRole("textbox"), "a");
    await new Promise((r) => setTimeout(r, 300));
    expect(pedidas.some((r) => r.includes("/api/v1/buscar"))).toBe(false);
  });

  it("un tipo que no vive en ningún módulo no se enlaza", async () => {
    resultados = [
      { objeto: "cuenta", registro_id: "c1", titulo: "Acme Ibérica", subtitulo: "" },
      { objeto: "cosa_inventada", registro_id: "x1", titulo: "TESTIGO-sin-modulo", subtitulo: "" },
    ];
    abrir();
    await userEvent.type(screen.getByRole("textbox"), "acme");
    expect(await screen.findByText("Acme Ibérica")).toBeInTheDocument();
    // Llevaría a una pantalla que no existe.
    expect(screen.queryByText("TESTIGO-sin-modulo")).toBeNull();
  });

  it("si la búsqueda falla, las pantallas siguen estando", async () => {
    falla = true;
    abrir();
    await userEvent.type(screen.getByRole("textbox"), "cuentas");
    await waitFor(() => expect(pedidas.length).toBeGreaterThan(0));
    // Lo que se vino a hacer en el noventa por ciento de los casos: la lista
    // de pantallas sigue ahí, filtrada por lo escrito.
    expect(document.querySelectorAll("li").length).toBeGreaterThan(0);
  });
});
