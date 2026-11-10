/**
 * Las recepciones de captura se ven al entrar en Candidatos, con su nombre.
 *
 * Sólo se llegaba a ellas por el desplegable de objetos del módulo, y lo que
 * vive ahí cuenta, para quien usa la herramienta, como si no existiera. El menú
 * de Ventas ya tiene sus diez entradas, así que van como pestaña de primer
 * nivel (`fija`): un botón con su nombre en la cabecera, sin abrir nada.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CabeceraDeLista } from "@/componentes/CabeceraDeLista";
import { recursosDe } from "@/lib/recursos";

describe("las recepciones de captura", () => {
  it("se ven en la cabecera de Candidatos sin abrir el desplegable", async () => {
    const recursos = recursosDe("leads");
    const indice = recursos.findIndex((r) => r.nombre === "Recepciones");
    expect(indice).toBeGreaterThanOrEqual(0);
    const alElegir = vi.fn();

    render(
      <CabeceraDeLista
        icono="person_add"
        modulo="Candidatos"
        recursos={recursos}
        activo={recursos.findIndex((r) => r.principal)}
        alElegir={alElegir}
      />,
    );

    // Un botón con su NOMBRE, no un icono: se lee sin pasar el ratón.
    const boton = screen.getByRole("button", { name: "Recepciones" });
    expect(boton.textContent).toBe("Recepciones");
    await userEvent.click(boton);
    expect(alElegir).toHaveBeenCalledWith(indice);

    // Y no se repite dentro del desplegable de objetos.
    await userEvent.click(screen.getByRole("button", { name: /objeto/i }));
    expect(
      screen.queryByRole("option", { name: "Recepciones" }),
    ).not.toBeInTheDocument();
  });
});
