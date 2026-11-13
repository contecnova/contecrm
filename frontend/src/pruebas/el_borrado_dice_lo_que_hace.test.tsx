/**
 * El botón de borrar dice lo que hace la operación, no «Eliminar».
 *
 * De 124 operaciones DELETE publicadas, muchas no borran: «Enviar una cuenta a
 * la papelera», «Revocar una clave», «Cerrar una sesión», «Dar de baja a un
 * usuario del tenant». Todas salían como «Eliminar» con «Sí, eliminar»
 * debajo: quien manda una cuenta a la papelera no sabía que se recupera, y
 * quien daba de baja a alguien creía que lo estaba borrando.
 *
 * Y en la ficha de un usuario había dos botones para lo mismo —«Dar de baja a
 * un usuario», que pregunta a quién pasan sus registros, y «Eliminar», que
 * desactiva igual sin preguntar—. El recurso puede callar su DELETE, pero
 * sólo diciendo por qué. Visto en la pantalla el 05-11-2026.
 *
 * Validada plantando el caso malo: con `t("ficha.eliminar")` fijo en el menú
 * falla la primera; sin mirar `borrado_oculto_porque`, la segunda.
 */

import { fireEvent, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BotonesDeRegistro, ConfirmarBorrado, useEdicion } from "@/componentes/Edicion";
import type { Recurso } from "@/lib/modulos";

const SUPERFICIE = {
  operaciones: [
    {
      metodo: "DELETE",
      ruta: "/api/v1/accounts/{cuenta_id}",
      permiso: null,
      resumen: "Enviar una cuenta a la papelera",
    },
    {
      metodo: "DELETE",
      ruta: "/api/v1/usuarios/{usuario_id}",
      permiso: null,
      resumen: "Dar de baja a un usuario del tenant",
    },
  ],
};

vi.mock("@/lib/permisos", () => ({
  usePuedeOperar: () => () => true,
  useSuperficie: () => ({ superficie: SUPERFICIE, tiene: () => true }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

const CUENTAS = { nombre: "Cuentas", listar: "/api/v1/accounts", servicio: "party" } as Recurso;

describe("el borrado dice lo que hace", () => {
  it("el rótulo sale del contrato, y el menú y la confirmación lo usan", () => {
    const { result } = renderHook(() => useEdicion(CUENTAS, "c-1"));
    expect(result.current.borrado).toBe("Enviar una cuenta a la papelera");

    render(
      <BotonesDeRegistro
        puedeEditar={false}
        puedeBorrar
        borrado={result.current.borrado}
        alEditar={() => {}}
        alBorrar={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("Enviar una cuenta a la papelera")).toBeTruthy();
    expect(screen.queryByText("ficha.eliminar")).toBeNull();

    render(
      <ConfirmarBorrado
        enviando={false}
        borrado={result.current.borrado}
        alBorrar={() => {}}
        alCancelar={() => {}}
      />,
    );
    const dialogo = screen.getByRole("alertdialog");
    expect(dialogo.getAttribute("aria-label")).toBe("Enviar una cuenta a la papelera");
    expect(screen.queryByText("ficha.eliminarDeVerdad")).toBeNull();
  });

  it("lo que no es un registro dice lo suyo, y el foco entra en «Cancelar» y vuelve", () => {
    // Una regla o un vínculo no tienen «adjuntos, comentarios, documentos»: el
    // aviso propio manda. Y un `alertdialog` sin foco no lo anuncia nadie.
    const origen = document.createElement("button");
    document.body.appendChild(origen);
    origen.focus();
    const { unmount } = render(
      <ConfirmarBorrado
        enviando={false}
        borrado="Quitar el vínculo"
        aviso="Lo vinculado sigue en su origen."
        alBorrar={() => {}}
        alCancelar={() => {}}
      />,
    );
    expect(screen.getByText("Lo vinculado sigue en su origen.")).toBeTruthy();
    expect(screen.queryByText(/ficha.confirmarOperacion/)).toBeNull();
    expect(document.activeElement?.textContent).toBe("modulo.cancelar");
    unmount();
    expect(document.activeElement).toBe(origen);
    origen.remove();
  });

  it("un recurso que calla su DELETE no lo ofrece, y tiene que decir por qué", () => {
    const usuarios = {
      nombre: "Usuarios",
      listar: "/api/v1/usuarios",
      servicio: "identity",
      borrado_oculto_porque: "lo cubre «Dar de baja a un usuario»",
    } as Recurso;
    const { result } = renderHook(() => useEdicion(usuarios, "u-1"));
    expect(result.current.puedeBorrar).toBe(false);
    expect(result.current.borrado).toBe("");
  });
});
