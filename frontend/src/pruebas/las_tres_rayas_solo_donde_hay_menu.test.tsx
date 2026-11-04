/**
 * El botón de las tres rayas sólo está donde hay algo que plegar.
 *
 * Lo preguntó quien lo usa el 04-11-2026: «mira las tres rayitas de la esquina
 * izquierda superior, ¿tienen sentido?».
 *
 * No lo tenían. El panel lateral —el árbol de ajustes— **se pinta sólo en
 * configuración**: trabajando, la navegación son las pestañas de arriba y no
 * hay ningún `aside`. El botón, en cambio, se pintaba siempre, y encima en la
 * esquina de arriba a la izquierda, que es donde se busca la navegación
 * principal.
 *
 * Medido pulsándolo antes de tocar nada: en una pantalla de trabajo, `aside`
 * 0→0 y el ancho del contenido 1440→1440 px — no pasaba nada, y quien lo pulsa
 * se queda dudando de si ha hecho clic bien. En configuración sí: 1440→1218.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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

// La barra de aplicación mide sus pestañas; jsdom no trae `ResizeObserver`.
class _Observador {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver =
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver ?? _Observador;

// Y el árbol pregunta si está en móvil. Tampoco lo trae jsdom; en un navegador
// de verdad existe siempre. Se contesta «no es móvil», que es el caso que
// pinta el árbol.
if (!window.matchMedia) {
  window.matchMedia = ((consulta: string) => ({
    matches: false,
    media: consulta,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

const SESION = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "quien@ejemplo.com",
  nombre: "Quien Usa",
  roles: ["admin"],
  permisos: ["*:*"],
  es_admin_plataforma: false,
} as unknown as import("@/lib/sesion").Sesion;

async function montar(desde: string) {
  const { Marco } = await import("@/componentes/Marco");
  return render(
    <MemoryRouter initialEntries={[desde]}>
      <Routes>
        <Route
          path="*"
          element={
            <Marco sesion={SESION}>
              <span>contenido</span>
            </Marco>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

/** El de las tres rayas, por su nombre accesible; no «el primer botón». */
function rayas() {
  return screen.queryByRole("button", { name: "nav.alternarPanel" });
}

describe("el botón de las tres rayas", () => {
  it("no sale trabajando, porque ahí no hay panel que plegar", async () => {
    await montar("/m/oportunidades");
    await waitFor(() => expect(screen.getByText("contenido")).toBeInTheDocument());
    expect(rayas()).toBeNull();
  });

  it("y sí sale en configuración, que es donde pliega el árbol", async () => {
    // La otra mitad: quitarlo de todas partes cumpliría lo de arriba y dejaría
    // sin forma de ganar ancho justo donde el árbol ocupa 222 px.
    await montar("/m/acceso");
    await waitFor(() => expect(rayas()).not.toBeNull());
  });
});
