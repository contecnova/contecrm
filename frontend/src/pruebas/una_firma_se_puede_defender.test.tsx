/**
 * Un sobre de firma: no si está firmado, sino **si esa firma se sostiene**.
 *
 * El listado enseñaba el estado y la referencia, y la ficha genérica no podía
 * enseñar la evidencia: devuelve un objeto, y esa ficha sólo descubre paneles
 * que devuelven listas, así que habría salido siempre «nada todavía».
 *
 * Lo que se afirma aquí es lo que decide el día que alguien discuta la firma:
 * que una firma sin los dos hashes **no se puede verificar** aunque el estado
 * ponga «firmado», que un firmante sin identificación es una casilla marcada
 * por quien tuviera acceso al correo, y que un dato de la prueba que falta se
 * dice en vez de dejar el hueco.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const EVIDENCIA = {
  referencia: "SOB-2026-77",
  proveedor: "firmaproveedor",
  nivel: "avanzada",
  estado: "firmado",
  documento_id: "d-1",
  documento_firmado_id: null,
  certificado_id: "c-1",
  sello_tiempo: "2026-10-20T10:00:00Z",
  hash_enviado: "abc123",
  hash_firmado: null,
  verificable: false,
  firmantes: [
    {
      nombre: "Ana Quintana",
      email: "ana@x.test",
      papel: "firmante",
      identificacion: "DNI + SMS",
      estado: "firmado",
      firmado_at: "2026-10-20T09:00:00Z",
      motivo_rechazo: null,
    },
    {
      nombre: "",
      email: "luis@x.test",
      papel: "testigo",
      identificacion: null,
      estado: "pendiente",
      firmado_at: null,
      motivo_rechazo: null,
    },
  ],
  eventos: [{ tipo: "enviado", descripcion: "Al correo de Ana", firmante: "ana@x.test" }],
};

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async () => ({
      datos: EVIDENCIA,
      version: null,
      retenidos: [],
      enmascarados: [],
    })),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, args?: Record<string, unknown>) =>
      args ? `${clave}:${JSON.stringify(args)}` : clave,
  }),
}));

async function montar() {
  const { SobreDeFirma } = await import("@/paginas/SobreDeFirma");
  return render(
    <MemoryRouter initialEntries={["/m/operacion/sobre_firma/s-1"]}>
      <Routes>
        <Route path="/m/operacion/sobre_firma/:id" element={<SobreDeFirma />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("una firma se puede defender, o no", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("dice que NO se puede verificar aunque el estado ponga firmado", async () => {
    await montar();
    // Es la diferencia entre un documento firmado y uno que PARECE firmado, y
    // no se nota mirando el estado: pone «firmado» igual.
    await waitFor(() => expect(screen.getByText("sobre.noVerificable")).toBeTruthy());
    // «firmado» sale dos veces —el estado del sobre y el del primer firmante—
    // y lo que se afirma es que el AVISO convive con ese estado: el sobre dice
    // que está firmado y aun así no se puede verificar.
    expect(screen.getAllByText("firmado").length).toBeGreaterThanOrEqual(2);
  });

  it("enseña el nivel eIDAS, que no es lo mismo ante un juez", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("avanzada")).toBeTruthy());
  });

  it("marca al firmante sin identificación", async () => {
    await montar();
    await waitFor(() =>
      expect(screen.getByText(/sobre.identificado.*DNI \+ SMS/)).toBeTruthy(),
    );
    // Una firma sin identificación es una casilla marcada por alguien con
    // acceso al correo, y en una lista se ve igual que una con DNI.
    expect(screen.getByText("sobre.sinIdentificar")).toBeTruthy();
  });

  it("dice qué dato de la prueba falta en vez de dejar el hueco", async () => {
    await montar();
    await waitFor(() => expect(screen.getByText("abc123")).toBeTruthy());
    // El hash de lo firmado y el documento firmado no están: se dicen, porque
    // un hueco en blanco se lee como «no aplica».
    expect(screen.getAllByText("sobre.falta").length).toBe(2);
  });
});
