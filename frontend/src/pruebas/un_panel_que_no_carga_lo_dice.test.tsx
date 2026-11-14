/**
 * Un panel que no se ha podido consultar lo dice; no desaparece.
 *
 * Antes cada carga secundaria acababa en `.catch(() => undefined)` y el panel
 * simplemente no salía: «no se pudo consultar» y «no hay nada» se veían igual.
 * Aquí se prueba la pieza común (`useCargasSecundarias` + `<FalloCompacto>`)
 * con lo que la hace valer: el fallo se ve, se reintenta solo esa carga, la
 * cancelación no es un fallo y un 403 no se anuncia.
 *
 * Validada plantando el caso malo: con `seguir` tragándose el error (sin
 * guardar `error`), la primera prueba falla.
 */

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { FalloCompacto } from "@/componentes/Estados";
import { ErrorApi } from "@/lib/api";
import { useCargasSecundarias } from "@/lib/cargaSecundaria";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, o?: Record<string, unknown>) =>
      o ? `${clave} ${JSON.stringify(o)}` : clave,
  }),
}));

function errorApi(estado: number): ErrorApi {
  return new ErrorApi(estado, "x", "x", null);
}

/** Una pantalla con un panel secundario que pide `pedir`. */
function Pantalla({ pedir }: { pedir: () => Promise<string> }) {
  const secundarias = useCargasSecundarias();
  const [dato, setDato] = useState<string | null>(null);
  useEffect(() => {
    secundarias.seguir("panel", () => pedir().then(setDato));
    // `seguir` es estable: se pide una vez, como en las pantallas.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const estado = secundarias.estado("panel");
  return (
    <div>
      <p>principal</p>
      {dato ? <p>dato: {dato}</p> : null}
      {estado.cargando ? <p>cargando panel</p> : null}
      {estado.sinPermiso ? <p>sin permiso</p> : null}
      <FalloCompacto {...estado} que="Panel" />
    </div>
  );
}

describe("las cargas secundarias", () => {
  it("si falla, se dice cuál y se puede reintentar sólo esa", async () => {
    const pedir = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(errorApi(0))
      .mockResolvedValueOnce("llegó");
    render(<Pantalla pedir={pedir} />);

    const aviso = await screen.findByRole("alert");
    // El nombre del panel y la frase del fallo, la misma que en `<Error>`.
    expect(aviso.textContent).toContain("Panel");
    expect(aviso.textContent).toContain("errores.sinRed");
    // Y la pantalla sigue en pie.
    expect(screen.getByText("principal")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: /app.reintentar/ }));

    expect(await screen.findByText("dato: llegó")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(pedir).toHaveBeenCalledTimes(2);
  });

  it("mientras llega, está cargando; cuando llega, ni carga ni fallo", async () => {
    let resolver: (v: string) => void = () => undefined;
    const pedir = () => new Promise<string>((r) => (resolver = r));
    render(<Pantalla pedir={pedir} />);
    expect(screen.getByText("cargando panel")).toBeTruthy();

    await act(async () => resolver("ya"));

    expect(screen.getByText("dato: ya")).toBeTruthy();
    expect(screen.queryByText("cargando panel")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("una cancelación no es un fallo", async () => {
    const cancelada = new DOMException("abortada", "AbortError");
    render(<Pantalla pedir={() => Promise.reject(cancelada)} />);
    await act(async () => undefined);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("cargando panel")).toBeNull();
  });

  it("un 403 no se anuncia como fallo, pero se sabe", async () => {
    render(<Pantalla pedir={() => Promise.reject(errorApi(403))} />);
    expect(await screen.findByText("sin permiso")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("sin error, el aviso compacto no pinta nada", () => {
    const { container } = render(<FalloCompacto error={null} que="Panel" />);
    expect(container.innerHTML).toBe("");
  });
});
