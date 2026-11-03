/**
 * La biblioteca de archivos, y lo que la separa de un volcado de la tabla.
 *
 * **El hueco:** los documentos se veían desde el registro del que cuelgan y
 * **sólo** desde ahí, así que para encontrar uno había que acordarse antes de
 * a qué cuenta pertenece — que es justo lo que no se recuerda.
 *
 * Tres cosas se vigilan, y las tres se pueden romper sin que se note porque
 * la pantalla sigue enseñando filas:
 *
 *  · **De qué registro cuelga cada uno, por su nombre.** «pliego.txt» no dice
 *    nada; «pliego.txt de Talleres Ibéricos» sí. Es el motivo de la pantalla.
 *  · **Sin nombre no se enlaza, y se dice por qué.** «Ya no existe» sólo de lo
 *    que se ha podido mirar: decirlo de algo que sigue ahí es afirmar que se
 *    ha borrado el registro de alguien.
 *  · **Un servicio mudo no se calla.** Los documentos los guarda cada servicio
 *    en el suyo; una lista corta y una lista incompleta se leen igual.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

let biblioteca: Record<string, unknown>;
/** Qué contesta cada listado al resolver nombres. `null` = no contesta. */
let listados: Record<string, Record<string, unknown>[] | null>;
let pedidas: string[];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      pedidas.push(ruta);
      if (ruta.startsWith("/api/v1/adjuntos")) return { datos: biblioteca };
      const base = ruta.split("?")[0] ?? "";
      const items = listados[base];
      if (items === null || items === undefined) throw new Error("no contesta");
      return { datos: { items } };
    }),
  };
});

const { Archivos } = await import("@/paginas/Archivos");

const DOC = {
  id: "d-1",
  objeto_tipo: "cuenta",
  objeto_id: "c-1",
  nombre: "pliego-tecnico.txt",
  extension: "txt",
  tamano: 37,
  version: 1,
  analisis: "limpio",
  descripcion: "",
  externo_sistema: "",
  created_at: "2026-10-27T20:08:07Z",
  servicio: "party",
};

function respuesta(documentos: unknown[], extra: Record<string, unknown> = {}) {
  return {
    documentos,
    cuantos: documentos.length,
    sin_respuesta: [],
    hay_mas: false,
    aviso: "",
    ...extra,
  };
}

function pintar() {
  return render(
    <MemoryRouter>
      <Archivos />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  pedidas = [];
  biblioteca = respuesta([DOC]);
  listados = { "/api/v1/accounts": [{ id: "c-1", nombre: "Talleres Ibéricos, S.A." }] };
  vi.clearAllMocks();
});

describe("la biblioteca de archivos", () => {
  it("dice de qué registro cuelga cada documento, por su nombre", async () => {
    pintar();
    expect(await screen.findByText("pliego-tecnico.txt")).toBeInTheDocument();
    // Lo que convierte un nombre de fichero en algo que sirve.
    const cuelga = await screen.findByText("Talleres Ibéricos, S.A.");
    expect(cuelga.closest("a")).toHaveAttribute("href", "/m/cuentas/cuenta/c-1");

    // **Un listado por TIPO, no uno por documento.** Con uno por documento,
    // una biblioteca de cien ficheros son cien llamadas.
    const deNombres = pedidas.filter((r) => r.startsWith("/api/v1/accounts"));
    expect(deNombres).toHaveLength(1);
    expect(deNombres[0]).toContain("id__en=c-1");
  });

  it("un registro que se ha mirado y no está lo dice, y no se enlaza", async () => {
    // El listado contesta, y el registro no viene: se ha borrado.
    listados["/api/v1/accounts"] = [];
    pintar();
    await screen.findByText("pliego-tecnico.txt");
    await waitFor(() =>
      expect(screen.getByText(/archivos\.registroBorrado/)).toBeInTheDocument(),
    );
    // Sin enlace: llevaría a una ficha que contesta 404.
    expect(screen.queryByText("Talleres Ibéricos, S.A.")).toBeNull();
    expect(document.querySelector('a[href^="/m/cuentas"]')).toBeNull();
  });

  it("y si no se ha podido mirar, NO dice que se haya borrado", async () => {
    // Es la diferencia que importa: afirmar que el registro de alguien ya no
    // existe cuando sigue ahí es la peor de las dos equivocaciones.
    listados["/api/v1/accounts"] = null;
    pintar();
    await screen.findByText("pliego-tecnico.txt");
    await waitFor(() =>
      expect(screen.getByText(/archivos\.registroSinMirar/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/archivos\.registroBorrado/)).toBeNull();
  });

  it("un servicio que no contesta sale avisado, no callado", async () => {
    biblioteca = respuesta([DOC], {
      sin_respuesta: ["sales"],
      aviso: "1 servicio(s) no contestan",
    });
    pintar();
    // Por el TEXTO del aviso y no por «el primer status»: el indicador de
    // carga también es un `status`, así que esperar por el rol resolvía antes
    // de que llegara la respuesta y lo que se comprobaba era el «cargando».
    expect(await screen.findByText("1 servicio(s) no contestan")).toBeInTheDocument();
  });

  it("un fichero infectado no se ofrece para abrir", async () => {
    // El servidor ya se niega a entregarlo: ofrecer el enlace es ofrecer algo
    // que contesta un error, y además lo pinta como si fuera normal.
    biblioteca = respuesta([{ ...DOC, analisis: "infectado" }]);
    pintar();
    const nombre = await screen.findByText("pliego-tecnico.txt");
    expect(nombre.closest("a")).toBeNull();
  });

  it("sin documentos lo dice, y distinto si es que la búsqueda no encuentra", async () => {
    biblioteca = respuesta([]);
    pintar();
    expect(await screen.findByText("archivos.ninguno")).toBeInTheDocument();
    expect(screen.getByText("archivos.ningunoPorque")).toBeInTheDocument();
  });
});
