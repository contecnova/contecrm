/**
 * Un artículo de conocimiento: a quién llega, en qué idiomas y si sirve.
 *
 * Lo que se afirma aquí:
 *
 *  · que una traducción atrasada diga **cuántas versiones** va por detrás. Una
 *    es una errata y seis son otro artículo, y «desincronizada» a secas no
 *    distingue las dos;
 *  · que un artículo **dañino** se señale distinto de uno **huérfano**. Los dos
 *    se ven igual en una lista por vistas y se arreglan al revés: uno se
 *    corrige porque alguien lo está siguiendo, el otro puede que sobre;
 *  · que la deflexión salga **con su aviso de que es aproximada**: es el número
 *    con el que se justifica no contratar a nadie más en soporte.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

let articulo: Record<string, unknown>;
let traducciones: Record<string, unknown> | null;
let eficacia: Record<string, unknown> | null;

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      if (ruta.includes("/traducciones")) {
        if (traducciones === null) throw new Error("sin traducciones");
        return { datos: traducciones };
      }
      if (ruta.includes("/eficacia")) {
        if (eficacia === null) throw new Error("sin eficacia");
        return { datos: eficacia };
      }
      return { datos: articulo };
    }),
  };
});

const { Articulo } = await import("@/paginas/Articulo");

function montar() {
  return render(
    <MemoryRouter initialEntries={["/m/conocimiento/articulo/a-1"]}>
      <Routes>
        <Route path="/m/conocimiento/articulo/:id" element={<Articulo />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  articulo = {
    articulo_id: "a-1",
    clave: "reiniciar",
    idioma: "es",
    estado: "publicado",
    titulo: "Cómo reiniciar el equipo",
    cuerpo: "Pulsa el botón",
    version: 3,
    utiles: 40,
    inutiles: 2,
    obsoleto: false,
    pendiente_de_revision: false,
    aviso: "",
  };
  traducciones = {
    articulo: "a-1",
    idioma_original: "es",
    version_publicada: 3,
    traducciones: [
      {
        idioma: "fr",
        articulo_id: "a-2",
        estado: "publicado",
        traducido_de_version: 1,
        sincronizada: false,
        versiones_por_detras: 2,
      },
      {
        idioma: "en",
        articulo_id: "a-3",
        estado: "publicado",
        traducido_de_version: 3,
        sincronizada: true,
        versiones_por_detras: 0,
      },
    ],
    desincronizadas: ["fr"],
  };
  eficacia = {
    articulos: 120,
    publicados: 80,
    dañinos: [],
    huerfanos: [],
    caducados: [],
    vistas: 9000,
    usos_en_caso: 300,
    deflexion_aproximada_pct: 22.5,
    aviso_deflexion: "Es una estimación: no se sabe quién habría abierto un caso.",
  };
  vi.clearAllMocks();
});

describe("las traducciones", () => {
  it("dicen cuántas versiones por detrás, no sólo que están atrasadas", async () => {
    montar();
    await screen.findByText("articulo.idiomas");
    expect(
      screen.getByText('articulo.porDetras:{"cuantas":2}'),
    ).toBeInTheDocument();
    expect(screen.getByText("articulo.alDia")).toBeInTheDocument();
  });

  it("y resumen cuántas se han quedado atrás", async () => {
    montar();
    await screen.findByText('articulo.desincronizadas:{"cuantas":1}');
  });

  it("sin traducciones lo dice en vez de dejar el hueco", async () => {
    traducciones = {
      articulo: "a-1",
      idioma_original: "es",
      version_publicada: 3,
      traducciones: [],
      desincronizadas: [],
    };
    montar();
    await screen.findByText("articulo.sinTraducciones");
    expect(screen.queryByText(/articulo\.desincronizadas/)).not.toBeInTheDocument();
  });
});

describe("si el artículo sirve", () => {
  it("un dañino se señala como lo que es: alguien lo está siguiendo", async () => {
    eficacia = {
      ...eficacia,
      dañinos: [
        { clave: "reiniciar", idioma: "es", vistas: 900, utiles: 2, inutiles: 120 },
      ],
    };
    montar();
    await screen.findByText("articulo.daniño");
    expect(screen.queryByText("articulo.huerfano")).not.toBeInTheDocument();
  });

  it("un huérfano se señala distinto, porque se arregla al revés", async () => {
    eficacia = { ...eficacia, huerfanos: [{ clave: "reiniciar", idioma: "es" }] };
    montar();
    await screen.findByText("articulo.huerfano");
    expect(screen.queryByText("articulo.daniño")).not.toBeInTheDocument();
  });

  it("uno que no está en ninguna de las dos listas no se señala", async () => {
    montar();
    await screen.findByText("articulo.eficacia");
    expect(screen.queryByText("articulo.daniño")).not.toBeInTheDocument();
    expect(screen.queryByText("articulo.huerfano")).not.toBeInTheDocument();
  });

  it("la deflexión va con su aviso de que es aproximada", async () => {
    montar();
    await screen.findByText('articulo.deflexion:{"pct":22.5}');
    expect(
      screen.getByText(/no se sabe quién habría abierto un caso/),
    ).toBeInTheDocument();
  });

  it("y si no se puede estimar, lo dice en vez de poner un cero", async () => {
    eficacia = { ...eficacia, deflexion_aproximada_pct: null, aviso_deflexion: "" };
    montar();
    await screen.findByText("articulo.sinDeflexion");
    expect(screen.queryByText(/articulo\.deflexion:/)).not.toBeInTheDocument();
  });
});

describe("quién lo ve", () => {
  it("un publicado avisa de que puede estar en el portal", async () => {
    montar();
    await screen.findByText("articulo.audiencia.publicado");
  });

  it("un borrador dice que no llega a nadie, pase lo que pase", async () => {
    articulo = { ...articulo, estado: "borrador" };
    montar();
    await screen.findByText("articulo.audiencia.borrador");
  });

  it("lo pendiente de revisión se avisa sin ocultar el artículo", async () => {
    articulo = { ...articulo, pendiente_de_revision: true };
    montar();
    await screen.findByText("articulo.toca_revisar");
    // Y el artículo sigue ahí: ocultarlo deja al cliente sin respuesta.
    expect(screen.getByText("Cómo reiniciar el equipo")).toBeInTheDocument();
  });
});
