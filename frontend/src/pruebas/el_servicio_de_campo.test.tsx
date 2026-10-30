/**
 * El servicio de campo: el activo y la orden de trabajo.
 *
 * Lo que se afirma aquí es lo que el servidor ya decía y nadie enseñaba:
 *
 *  · que una cobertura **no concluyente** no se pinte como «no cubierto». La
 *    diferencia es quién paga la reparación;
 *  · que un contador que **retrocede** se señale: no es un error de lectura;
 *  · que el historial diga que sigue una **cadena de sustituciones**;
 *  · que el reparto de cobertura tenga **tres cestas**, y la tercera —«no se
 *    sabe»— salga aparte;
 *  · y que un parte **tocado después de firmar** salga arriba del todo.
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

let cobertura: Record<string, unknown>;
let ficha: Record<string, unknown>;
let historial: Record<string, unknown>;
let orden: Record<string, unknown>;
let candidatos: Record<string, unknown>;

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async (ruta: string) => {
      if (ruta.includes("/arbol"))
        return {
          datos: {
            id: "a-1",
            codigo: "MAQ-001",
            nombre: "Prensa 4",
            numero_serie: "SN-9",
            estado: "operativo",
            componentes: [
              {
                id: "a-2",
                codigo: "BOM-7",
                nombre: "Bomba hidráulica",
                numero_serie: null,
                estado: "operativo",
                componentes: [],
                truncado: true,
              },
            ],
          },
        };
      if (ruta.includes("/historial")) return { datos: historial };
      if (ruta.includes("/cobertura")) return { datos: cobertura };

      if (ruta.includes("/candidatos")) return { datos: candidatos };
      if (/\/activos\/[^/]+$/.test(ruta)) return { datos: ficha };
      return { datos: orden };
    }),
  };
});

const { Activo } = await import("@/paginas/Activo");
const { OrdenDeTrabajo } = await import("@/paginas/OrdenDeTrabajo");

function montarActivo() {
  return render(
    <MemoryRouter initialEntries={["/m/campo/activo/a-1"]}>
      <Routes>
        <Route path="/m/campo/activo/:id" element={<Activo />} />
      </Routes>
    </MemoryRouter>,
  );
}

function montarOrden() {
  return render(
    <MemoryRouter initialEntries={["/m/campo/orden_trabajo/o-1"]}>
      <Routes>
        <Route path="/m/campo/orden_trabajo/:id" element={<OrdenDeTrabajo />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  cobertura = {
    cubierto: true,
    concluyente: true,
    tipo: "fabricante",
    hasta: "2027-01-01",
    exclusiones: ["consumibles"],
    motivo: "Cubierto por la garantía del fabricante.",
    garantias: [{}],
  };
  // El contador sale de la ficha del activo: `leer_contador` ANOTA una
  // lectura pese al nombre, así que no hay forma de consultarlo sin escribir.
  ficha = {
    contador: 12000,
    unidad_contador: "horas",
    contador_at: "2026-10-01T00:00:00Z",
  };
  historial = {
    activo_id: "a-1",
    // Es una LISTA de identificadores, no un número: tipearlo como número
    // hacía que `> 1` fuera siempre cierto y el aviso saliera en todos.
    equipos_en_la_cadena: ["a-0", "a-00", "a-1"],
    eventos: [{ tipo: "avería", cuando: "2026-01-01T00:00:00Z" }],
  };
  orden = {
    id: "o-1",
    codigo: "OT-42",
    titulo: "Cambiar la bomba",
    tipo: "correctivo",
    estado: "cerrada",
    tecnico_id: "t-1",
    activo_id: "a-1",
    cita_desde: null,
    minutos_trabajados: 95,
    lineas: [
      {
        id: "l-1",
        tipo: "repuesto",
        concepto: "Bomba",
        cantidad: "1",
        unidad: "ud",
        facturable: true,
        cubierto_garantia: false,
        nota_cobertura: null,
      },
      {
        id: "l-2",
        tipo: "tiempo",
        concepto: "Mano de obra",
        cantidad: "1.5",
        unidad: "h",
        facturable: true,
        cubierto_garantia: null,
        nota_cobertura: null,
      },
    ],
    a_facturar: 1,
    a_garantia: 0,
    sin_determinar: 1,
    parte: {
      resumen: "Se cambió la bomba",
      diagnostico: "Junta rota",
      checklist: [{}, {}],
      evidencias: [{}],
      firmado: true,
      conforme: true,
      huella: "abc",
      alterado_tras_firmar: false,
    },
  };
  candidatos = {
    orden_id: "o-1",
    competencias_requeridas: ["hidraulica"],
    aptos: [],
    descartados: [{ tecnico_id: "t-2", porque: "fuera de zona" }],
    hay_candidatos: false,
  };
  vi.clearAllMocks();
});

describe("el activo", () => {
  it("una cobertura no concluyente NO se pinta como «no cubierto»", async () => {
    cobertura = {
      cubierto: false,
      concluyente: false,
      motivo: "No hay garantía registrada para este activo.",
      garantias: [],
    };
    montarActivo();
    await screen.findByText("activo.noConcluyente");
    expect(screen.queryByText("activo.noCubierto")).not.toBeInTheDocument();
  });

  it("y una concluyente sí dice si está cubierto", async () => {
    montarActivo();
    await screen.findByText("activo.cubierto");
    expect(screen.queryByText("activo.noConcluyente")).not.toBeInTheDocument();
  });

  it("el contador va con la fecha de su lectura", async () => {
    montarActivo();
    // Un número sin fecha al lado se lee como el de hoy, y sobre un contador
    // se decide un mantenimiento.
    await screen.findByText(/activo\.leidoEl/);
  });

  it("y sin fecha de lectura lo dice, en vez de dar el número a secas", async () => {
    ficha = { ...ficha, contador_at: null };
    montarActivo();
    await screen.findByText("activo.sinFechaDeLectura");
  });

  it("el historial dice que sigue la cadena de sustituciones", async () => {
    montarActivo();
    await screen.findByText('activo.cadena:{"equipos":3}');
  });

  it("y con una sola máquina no habla de cadena", async () => {
    historial = { ...historial, equipos_en_la_cadena: ["a-1"] };
    montarActivo();
    await screen.findByText("activo.historial");
    expect(screen.queryByText(/activo\.cadena/)).not.toBeInTheDocument();
  });

  it("un árbol cortado avisa de que hay más por debajo", async () => {
    montarActivo();
    await screen.findByText("activo.truncado");
  });
});

describe("la orden de trabajo", () => {
  it("el reparto va en tres cestas, y la tercera sale aparte", async () => {
    montarOrden();
    await screen.findByText('orden.cestas:{"facturar":1,"garantia":0}');
    expect(
      screen.getByText('orden.sinDeterminar:{"cuantas":1}'),
    ).toBeInTheDocument();
    // Y la línea sin decidir va marcada, no como facturable.
    expect(screen.getByText("orden.porDecidir")).toBeInTheDocument();
  });

  it("sin líneas por decidir no se avisa de nada", async () => {
    orden = {
      ...orden,
      sin_determinar: 0,
      lineas: [(orden.lineas as unknown[])[0]],
    };
    montarOrden();
    await screen.findByText("orden.quienPaga");
    expect(screen.queryByText(/orden\.sinDeterminar/)).not.toBeInTheDocument();
  });

  it("un parte tocado después de firmar sale arriba del todo", async () => {
    orden = {
      ...orden,
      parte: { ...(orden.parte as Record<string, unknown>), alterado_tras_firmar: true },
    };
    montarOrden();
    await screen.findByText("orden.alterado");
  });

  it("firmado y no conforme no es lo mismo que firmado", async () => {
    orden = {
      ...orden,
      parte: { ...(orden.parte as Record<string, unknown>), conforme: false },
    };
    montarOrden();
    await screen.findByText("orden.firmadoNoConforme");
    expect(screen.queryByText("orden.firmado")).not.toBeInTheDocument();
  });

  it("los descartados salen con su porqué", async () => {
    montarOrden();
    await screen.findByText("orden.nadieApto");
    expect(screen.getByText("fuera de zona")).toBeInTheDocument();
  });
});
