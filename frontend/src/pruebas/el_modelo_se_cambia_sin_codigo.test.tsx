/**
 * Lo que una empresa cambia sin escribir código, visto desde la pantalla.
 *
 * Seis cosas estaban publicadas en la API y **sin puerta**: el formulario que
 * le toca a cada rol, lo que la IA entiende de un objeto, qué campos ya
 * justifican una columna real, la máquina de estados, cuándo se puede retirar
 * un campo renombrado y cómo se lleva la configuración a otro entorno.
 *
 * Esta prueba existe por un motivo concreto: el gate de «cada capacidad tiene
 * pantalla» cuenta identificadores que aparecen en un fichero de pantalla, y
 * eso lo cumple igual un comentario. Lo que no cumple un comentario es
 * **pintar el dato que devuelve la ruta**, y es lo único que se afirma aquí:
 * de cada panel, el número o el texto que sólo puede venir de su respuesta.
 *
 * Se valida plantando el caso malo: quitar cualquiera de los cinco paneles
 * del montaje pone en rojo su `it` y sólo el suyo.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const pedidas: string[] = [];

/** Lo que contesta cada ruta, con la forma real de su servicio. */
const RESPUESTAS: Record<string, unknown> = {
  "/api/v1/metadata/objetos/obj-1": {
    id: "obj-1",
    nombre: "cuenta",
    etiqueta: "Cliente",
    etiqueta_plural: "Clientes",
    descripcion: "",
    origen: "producto",
    icono: "account",
    activo: true,
    // La máquina de estados: un estado con salidas y otro final.
    estados: { prospecto: ["cliente", "descartado"], descartado: [] },
  },
  "/api/v1/metadata/objetos/cuenta/describe": {
    objeto: { nombre: "cuenta" },
    campos: [
      {
        id: "c1",
        nombre: "margen",
        etiqueta: "Margen",
        tipo: "formula",
        obligatorio: false,
        unico: false,
        solo_lectura: true,
        sensibilidad: "normal",
        deprecado: false,
      },
    ],
    reglas: [],
    layouts: [],
  },
  "/api/v1/metadata/objetos/cuenta/trazabilidad": {
    objeto: "cuenta",
    campos: [
      {
        campo: "codigo_viejo",
        tipo: "texto",
        creado_at: null,
        deprecado: true,
        escrituras: 0,
        ultima_escritura_at: null,
        materializado: false,
        se_puede_retirar: true,
      },
    ],
    sin_usar: [],
    publicaciones: [],
  },
  "/api/v1/metadata/objetos/cuenta/diseno": {
    objeto: "cuenta",
    hay_diseno: true,
    nombre: "Ficha comercial",
    secciones: [{}, {}, {}],
    porque: "Hay un layout para el rol «comercial».",
  },
  "/api/v1/metadata/objetos/cuenta/semantica": {
    objeto: "cuenta",
    campos: [],
    fuera_por_sensibles: ["nif"],
    fuera_por_internos: [],
    sin_describir: ["cmp_2"],
    completo: false,
    aviso: "",
    cobertura: {
      medible: true,
      campos: 4,
      descritos: 1,
      explotables: 1,
      pct: 25,
      que_significa: "Se puede explotar el 25 % de los campos personalizados.",
      los_que_faltan: ["cmp_2"],
    },
  },
  "/api/v1/metadata/objetos/cuenta/candidatos-columna": {
    objeto: "cuenta",
    umbral: 1000,
    candidatos: [{ campo: "segmento", escrituras: 4821 }],
    como_se_hace: "",
    por_que_no_siempre:
      "Un ALTER TABLE en una tabla compartida los bloquea a todos.",
  },
  "/api/v1/analitica/modelo-semantico?objeto=cuenta": {
    tenant: "t",
    objetos: [{ nombre: "cuenta", campos: [{}, {}] }],
    excluidos_por_sensibilidad: ["nif"],
    motivo_exclusion: "",
    contiene_datos: false,
  },
};

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      pedidas.push(ruta);
      if (!(ruta in RESPUESTAS)) {
        // Un 404 de verdad: así los paneles que no son de esta prueba se
        // comportan como en producción cuando su ruta no contesta.
        throw new Error(`sin doble para ${ruta}`);
      }
      return {
        datos: RESPUESTAS[ruta],
        version: null,
        retenidos: [],
        enmascarados: [],
      };
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
  const { ObjetoDelModelo } = await import("@/paginas/ObjetoDelModelo");
  return render(
    <MemoryRouter initialEntries={["/m/modelo/objeto/obj-1"]}>
      <Routes>
        <Route path="/m/modelo/objeto/:id" element={<ObjetoDelModelo />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("el modelo de datos se cambia sin escribir código", () => {
  beforeEach(() => {
    pedidas.length = 0;
  });

  it("dice qué formulario te toca y por qué ése", async () => {
    await montar();
    // El «por qué» viene de la ruta: con dos diseños por rol es la única
    // respuesta a «¿por qué yo veo otra pantalla?».
    await waitFor(() =>
      expect(
        screen.getByText("Hay un layout para el rol «comercial»."),
      ).toBeTruthy(),
    );
    expect(screen.getByText(/modeloDatos.secciones.*3/)).toBeTruthy();
  });

  it("enseña la cobertura semántica con su número y los campos que faltan", async () => {
    await montar();
    await waitFor(() =>
      expect(screen.getByText(/modeloDatos.iaCobertura.*25/)).toBeTruthy(),
    );
    // Los que faltan, por su nombre: un porcentaje dice cuánto queda, una
    // lista dice qué hacer esta tarde.
    expect(screen.getByText(/modeloDatos.iaSinDescribir.*cmp_2/)).toBeTruthy();
    // Y lo que se ha dejado fuera, que callado hace creer que el dato no está.
    expect(screen.getByText(/modeloDatos.iaFuera.*"sensibles":1/)).toBeTruthy();
  });

  it("y cuántos campos salen en informes, que lo dice otro servicio", async () => {
    await montar();
    await waitFor(() =>
      expect(
        screen.getByText(/modeloDatos.enInformesCuantos.*"cuantos":2/),
      ).toBeTruthy(),
    );
    expect(
      pedidas.some((r) => r.startsWith("/api/v1/analitica/modelo-semantico")),
    ).toBe(true);
  });

  it("dice qué campo ya justifica una columna, con su medida", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("segmento")).toBeTruthy());
    // Con el número delante: sin él, cada cliente que note su lista lenta
    // pediría columna.
    expect(
      screen.getByText(/modeloDatos.columnaEscrituras.*4821/),
    ).toBeTruthy();
  });

  it("pinta la máquina de estados, y marca cuál es final", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("prospecto")).toBeTruthy());
    expect(screen.getByText("cliente")).toBeTruthy();
    // Un estado sin salidas es final: en una lista de transiciones, callarlo
    // se lee como un hueco.
    expect(screen.getByText("modeloDatos.estadoFinal")).toBeTruthy();
  });

  it("dice cuántos campos renombrados ya se pueden retirar", async () => {
    await montar();
    await waitFor(() =>
      expect(
        screen.getByText(/modeloDatos.sePuedeRetirar.*"cuantos":1/),
      ).toBeTruthy(),
    );
    expect(screen.getByText("modeloDatos.paqueteDescargar")).toBeTruthy();
  });

  it("marca los campos que se calculan", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("margen")).toBeTruthy());
    // Un campo de fórmula no se teclea. Sin la marca, alguien busca por qué
    // «no se puede rellenar».
    expect(screen.getByText("modeloDatos.calculado")).toBeTruthy();
  });
});
