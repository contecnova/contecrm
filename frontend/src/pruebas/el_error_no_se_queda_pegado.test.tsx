/**
 * Un error en una pantalla no se queda puesto en las demás.
 *
 * Lo reportó el usuario: «cuando vas a inteligencia aparece esto, pero cuando
 * te mueves a cualquier otra opción sigue entonces apareciendo esto». Y seguía
 * hasta recargar a mano.
 *
 * La frontera de error sí sabía olvidarse al cambiar de ruta —compara su
 * `clave`—, pero quien la montaba le pasaba `window.location.pathname`. Eso no
 * es reactivo: la raíz no se suscribe a la navegación, no se vuelve a pintar y
 * la clave se queda congelada en la pantalla rota. Y se realimenta solo:
 * mientras la frontera enseña el error, las rutas de dentro están desmontadas,
 * así que tampoco queda nadie escuchando.
 *
 * Validada plantando el caso malo: con `clave={window.location.pathname}` en
 * vez de `useLocation`, la primera prueba de aquí falla.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { FronteraDeRuta } from "@/componentes/Frontera";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

function Pantalla() {
  const { pathname } = useLocation();
  // Una pantalla cuyo servicio no contesta: es el caso de «Inteligencia» con
  // su motor apagado, que es donde apareció.
  if (pathname === "/rota") throw new Error("el servicio no contesta");
  return <p>contenido de {pathname}</p>;
}

function Aplicacion({ desde }: { desde: string }) {
  return (
    <MemoryRouter initialEntries={[desde]}>
      {/* El menú va FUERA de la frontera, como el marco de verdad: es lo que
          permite irse a otro sitio cuando la pantalla se ha caído. */}
      <Link to="/sana">ir a otra</Link>
      <FronteraDeRuta>
        <Routes>
          <Route path="*" element={<Pantalla />} />
        </Routes>
      </FronteraDeRuta>
    </MemoryRouter>
  );
}

describe("la frontera de error y la navegación", () => {
  it("al irse a otra pantalla, el error se olvida", async () => {
    // React escupe el error por consola aunque lo recoja una frontera. Se
    // silencia sólo aquí para que el fallo de verdad se lea.
    const silencio = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      render(<Aplicacion desde="/rota" />);
      expect(screen.getByRole("alert")).toBeTruthy();

      await userEvent.click(screen.getByText("ir a otra"));

      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.getByText("contenido de /sana")).toBeTruthy();
    } finally {
      silencio.mockRestore();
    }
  });

  it("una pantalla que va bien se pinta sin más", () => {
    render(<Aplicacion desde="/sana" />);
    expect(screen.getByText("contenido de /sana")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
