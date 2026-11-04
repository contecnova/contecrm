/**
 * Elegir una aplicación en el lanzador te lleva a esa aplicación.
 *
 * Lo dijo quien lo usa, el 04-11-2026: «cuando vas aquí y seleccionas
 * cualquier opción entre analítica, ventas, servicio y marketing, a veces
 * funciona y a veces no funciona, ni idea de por qué».
 *
 * No era aleatorio ni era el navegador. El marco decide en qué aplicación
 * estás con `aplicacion = delCamino ?? elegida`: **manda el camino**, y la
 * elección sólo se mira cuando el camino no es de ninguna aplicación —la
 * portada, el chat, las menciones—. O sea que elegir «Analítica» estando en
 * una pantalla de Ventas no hacía absolutamente nada, y un efecto más tarde
 * un `useEffect` devolvía la elección al valor del camino.
 *
 * Que el camino mande está bien y no se toca: una portada que cambia de
 * aplicación según desde dónde llegues no deja saber nunca en cuál estás. Lo
 * que faltaba es lo que un lanzador hace: **llevarte**.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...real,
    llamar: vi.fn(async () => ({
      datos: {},
      version: null,
      retenidos: [],
      enmascarados: [],
    })),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

// La barra de aplicación mide sus pestañas para saber cuáles caben, y jsdom no
// trae `ResizeObserver`. Sin esto, el marco revienta al montar y la prueba no
// llega a mirar nada.
class _Observador {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver =
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver ?? _Observador;

const SESION = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "quien@ejemplo.com",
  nombre: "Quien Usa",
  roles: ["admin"],
  permisos: ["*:*"],
  es_admin_plataforma: false,
} as unknown as import("@/lib/sesion").Sesion;

/** Enseña el camino en el que está, para poder afirmarlo sin mirar el DOM. */
function Donde() {
  const { pathname } = useLocation();
  return <span data-testid="camino">{pathname}</span>;
}

async function montar(desde: string) {
  const { Marco } = await import("@/componentes/Marco");
  return render(
    <MemoryRouter initialEntries={[desde]}>
      <Routes>
        <Route
          path="*"
          element={
            <Marco sesion={SESION}>
              <Donde />
            </Marco>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

async function elegir(nombreDeLaApp: string) {
  // Se abre por donde lo abre una persona: el nombre de la aplicación, que es
  // lo que hace Salesforce y lo que dice el comentario de la barra.
  // El que ABRE el diálogo, no «cualquier botón cuyo rótulo empiece por
  // app.»: hay varios en el marco y el primero no es éste.
  // El del LANZADOR, que no es el único con `aria-haspopup="dialog"` en el
  // marco: el panel de avisos tiene otro y está antes en el DOM. Se distingue
  // porque su rótulo es el nombre de la aplicación en la que estás.
  const abrir = [
    ...document.querySelectorAll<HTMLButtonElement>('button[aria-haspopup="dialog"]'),
  ].find((b) => /app\.[a-z]/.test(b.textContent ?? ""));
  expect(abrir, "no está el botón que abre el lanzador").toBeDefined();
  await userEvent.click(abrir as HTMLButtonElement);
  const dialogo = await screen.findByRole("dialog");
  const cartas = await within(dialogo).findAllByRole("button");
  const carta = cartas.find((b) => b.textContent?.includes(nombreDeLaApp));
  expect(carta, `no se encuentra la carta de «${nombreDeLaApp}»`).toBeDefined();
  await userEvent.click(carta as HTMLElement);
}


describe("el lanzador de aplicaciones", () => {
  it("desde una pantalla de otra aplicación, te lleva", async () => {
    // Éste es el caso que no funcionaba: el camino es de Ventas, así que la
    // elección quedaba ignorada y no pasaba nada.
    await montar("/m/oportunidades");
    expect(screen.getByTestId("camino").textContent).toBe("/m/oportunidades");

    await elegir("app.analitica");

    await waitFor(() =>
      expect(screen.getByTestId("camino").textContent).not.toBe("/m/oportunidades"),
    );
  });

  it("y desde una pantalla que no es de ninguna, también", async () => {
    // Éste SÍ funcionaba —a medias: cambiaba el menú y no el sitio—, y es la
    // mitad que hacía que el fallo pareciera aleatorio.
    await montar("/chat");
    await elegir("app.servicio");
    await waitFor(() => expect(screen.getByTestId("camino").textContent).not.toBe("/chat"));
  });
});
