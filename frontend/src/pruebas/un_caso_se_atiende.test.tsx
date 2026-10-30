/**
 * La ficha de un caso: con qué tiene que ver, cómo va el reloj y cómo acabó.
 *
 * La bandeja dice qué atender primero; abrir un caso es otra cosa. La ficha
 * genérica enseñaba seis UUID sueltos y un array, y la propia ruta de detalle
 * **no devolvía ni las relaciones ni el cierre**: el dato llegaba a la bandeja
 * y no al detalle, así que abrir el caso perdía de qué cliente era.
 *
 * Los tres avisos que se afirman son los que cambian cómo se atiende: los dos
 * incumplimientos por separado, el reloj parado, y que un caso pendiente de
 * que el cliente lo dé por bueno NO está cerrado.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const CASO = {
  id: "k-1",
  codigo: "CAS-2026-00042",
  asunto: "No arranca la máquina 4",
  descripcion: "Desde el martes",
  estado: "cerrado",
  prioridad: "alta",
  severidad: "grave",
  clasificacion: "Hardware / Motor",
  relacionado_con: {
    cuenta_id: "aaaaaaaa-0000-0000-0000-000000000001",
    contacto_id: null,
    producto_id: null,
    activo_id: "bbbbbbbb-0000-0000-0000-000000000002",
    contrato_id: null,
    pedido_id: null,
  },
  cierre: {
    motivo: "resuelto",
    resolucion: "Se cambió el relé",
    validacion_cliente: "pendiente",
    reaperturas: 2,
    cerrado_at: "2026-10-20T10:00:00Z",
    resuelto_at: "2026-10-20T09:00:00Z",
  },
  sla: {
    clave: "oro",
    version: 3,
    vence_primera_respuesta_at: "2026-10-18T10:00:00Z",
    vence_resolucion_at: "2026-10-25T10:00:00Z",
    primera_respuesta_at: null,
    pausa_acumulada_s: 54000,
    incumplio_primera_respuesta: true,
    incumplio_resolucion: false,
  },
  relaciones: {
    caso: "k-1",
    padre: null,
    hijos: [{ id: "k-2", asunto: "Pieza de repuesto", estado: "abierto" }],
    colgados_del_maestro: [],
    duplicado_de: "k-0",
  },
  historial: [
    { tipo: "reabierto", detalle: { por_que: "volvió a fallar" }, at: "2026-10-22T08:00:00Z" },
  ],
};

const ASIGNACIONES = [
  {
    at: "2026-10-18T09:00:00Z",
    regla: "Máquinas en garantía",
    asignado_a: null,
    cola: "campo-norte",
    estrategia: "menos_carga",
    motivo: "El activo está en zona norte",
    evaluadas: 4,
  },
];

const SALDO = {
  entitlement: "Soporte oro 2026",
  al_agotar: "se factura por horas",
  horas: {
    incluidas: "200.00",
    consumidas: "200.00",
    restantes: "0.00",
    sin_limite: false,
    agotado: true,
  },
  casos: { incluidos: null, consumidos: 12, restantes: null, sin_limite: true, agotado: false },
  vigente_hasta: "2026-12-31",
};

const enviado: { ruta: string; cuerpo: unknown }[] = [];

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(
      async (ruta: string, opciones?: { metodo?: string; cuerpo?: unknown }) => {
        if ((opciones?.metodo ?? "GET") !== "GET") {
          enviado.push({ ruta, cuerpo: opciones?.cuerpo });
          return { datos: { id: "art-1", clave: "caso-k-1" }, version: null };
        }
        let datos: unknown = CASO;
        if (ruta.startsWith("/api/v1/colas/explicar/")) datos = ASIGNACIONES;
        else if (ruta.startsWith("/api/v1/entitlements/aplicable"))
          datos = { entitlement_id: "e-1" };
        else if (ruta.startsWith("/api/v1/entitlements/e-1/saldo")) datos = SALDO;
        return { datos, version: null, retenidos: [], enmascarados: [] };
      },
    ),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, args?: Record<string, unknown>) =>
      args ? `${clave}:${JSON.stringify(args)}` : clave,
  }),
}));

async function montar() {
  const { Caso } = await import("@/paginas/Caso");
  return render(
    <MemoryRouter initialEntries={["/m/casos/caso/k-1"]}>
      <Routes>
        <Route path="/m/casos/caso/:id" element={<Caso />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("un caso se atiende", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("dice de qué cliente es y sobre qué activo, no seis UUID sueltos", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("caso.rel.cuenta_id")).toBeTruthy());
    expect(screen.getByText("caso.rel.activo_id")).toBeTruthy();
    // Lo que NO está puesto no se pinta: una lista con cuatro «—» hace creer
    // que faltan datos cuando lo que pasa es que ese caso no es de un pedido.
    expect(screen.queryByText("caso.rel.pedido_id")).toBeNull();
  });

  it("separa los dos incumplimientos y dice que el reloj está parado", async () => {
    await montar();
    // Incumplir la primera respuesta y incumplir la resolución son dos
    // conversaciones distintas; sumarlas esconde la que todavía se salva.
    await waitFor(() =>
      expect(screen.getByText("caso.incumplioPrimera")).toBeTruthy(),
    );
    expect(screen.queryByText("caso.incumplioResolucion")).toBeNull();
    // 54.000 s = 15 h esperando al cliente. No es tiempo sin atender.
    expect(screen.getByText(/caso.enPausa.*15/)).toBeTruthy();
  });

  it("avisa de que un caso pendiente del cliente NO está cerrado", async () => {
    await montar();
    await waitFor(() =>
      expect(screen.getByText(/caso.pendienteDelCliente.*pendiente/)).toBeTruthy(),
    );
    // Y las reaperturas con el cierre: cerrado tres veces no es resuelto.
    expect(screen.getByText(/caso.reaperturas.*"cuantas":2/)).toBeTruthy();
  });

  it("enseña de qué cuelga, qué cuelga de él y de cuál es duplicado", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("caso.duplicadoDe")).toBeTruthy());
    expect(screen.getByText("Pieza de repuesto")).toBeTruthy();
  });

  it("enseña el historial, que es la trazabilidad de la reapertura", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("reabierto")).toBeTruthy());
    expect(screen.getByText(/volvió a fallar/)).toBeTruthy();
  });

  it("dice por qué está en esta cola, y cuántas reglas se miraron", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("campo-norte")).toBeTruthy());
    expect(screen.getByText("El activo está en zona norte")).toBeTruthy();
    // Sin ese número, «ninguna coincidió y cayó a la cola por defecto» y
    // «coincidió la primera» se cuentan igual, y significan lo contrario.
    expect(screen.getByText(/caso.reglasMiradas.*"cuantas":4/)).toBeTruthy();
  });

  it("enseña LAS DOS bolsas del derecho, aunque sólo una esté limitada", async () => {
    await montar();
    // Enseñar sólo la limitada hace que quien mira no sepa si la otra no se
    // cuenta o es que nadie ha gastado, y son cosas distintas delante de un
    // cliente que pregunta.
    await waitFor(() =>
      expect(screen.getByText(/caso.horasRestantes.*"restantes":"0.00"/)).toBeTruthy(),
    );
    expect(screen.getByText(/caso.casosSinLimite.*12/)).toBeTruthy();
    // Y qué pasa al agotarse, que es lo que hay que poder decirle al cliente.
    expect(screen.getByText(/caso.alAgotar.*factura por horas/)).toBeTruthy();
  });
});

// ── El artículo se escribe aquí y ahora (CRM-04.03.01.05) ────────────────
//
// El momento ES la capacidad: se escribe cuando se resuelve, con el problema
// fresco y por quien lo resolvió. Pedirlo después, en una sesión dedicada, es
// como no pedirlo — y es por lo que las bases de conocimiento se quedan
// vacías teniendo el procedimiento escrito en el servidor.

describe("escribir el artículo desde el caso resuelto", () => {
  beforeEach(() => {
    enviado.length = 0;
  });

  it("el aviso de datos del cliente va ANTES de escribir, no después", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    await montar();
    await screen.findByText("caso.cierre");

    await userEvent.click(screen.getByText("caso.escribirArticulo"));

    // Lo que hay que quitar del texto se quita mientras se escribe: después de
    // guardar ya está escrito, y el artículo ya lleva el nombre del cliente.
    expect(screen.getByText("caso.avisoResolucion")).toBeInTheDocument();
  });

  it("viene relleno con la resolución, y se puede cambiar antes de guardar", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    await montar();
    await screen.findByText("caso.cierre");
    await userEvent.click(screen.getByText("caso.escribirArticulo"));

    const cuerpo = screen.getByLabelText("caso.cuerpoArticulo");
    expect(cuerpo).toHaveValue("Se cambió el relé");

    await userEvent.clear(cuerpo);
    await userEvent.type(cuerpo, "Se cambia el rele del motor");
    await userEvent.type(screen.getByLabelText("caso.tituloArticulo"), "Rele del motor");
    await userEvent.click(screen.getByText("caso.guardarArticulo"));

    await waitFor(() => expect(enviado).toHaveLength(1));
    const peticion = enviado[0]!;
    expect(peticion.ruta).toBe("/api/v1/conocimiento/desde-caso/k-1");
    expect(peticion.cuerpo).toMatchObject({
      titulo: "Rele del motor",
      cuerpo: "Se cambia el rele del motor",
    });
  });

  it("sin título no deja guardar: un artículo sin nombre no lo encuentra nadie", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    await montar();
    await screen.findByText("caso.cierre");
    await userEvent.click(screen.getByText("caso.escribirArticulo"));

    expect(screen.getByText("caso.guardarArticulo")).toBeDisabled();
    expect(enviado).toHaveLength(0);
  });

  it("al crearlo dice que nace en borrador e interno", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    await montar();
    await screen.findByText("caso.cierre");
    await userEvent.click(screen.getByText("caso.escribirArticulo"));
    await userEvent.type(screen.getByLabelText("caso.tituloArticulo"), "Rele");
    await userEvent.click(screen.getByText("caso.guardarArticulo"));

    expect(
      await screen.findByText('caso.articuloCreado:{"clave":"caso-k-1"}'),
    ).toBeInTheDocument();
  });
});
