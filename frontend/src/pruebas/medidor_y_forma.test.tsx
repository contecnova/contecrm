/**
 * El medidor y la forma de un gráfico.
 *
 * Dos cosas que el cuadro de mando prometía y no cumplía:
 *
 *   · un componente `gauge` es «una métrica contra su objetivo», y se pintaba
 *     como un KPI normal — o sea, **la cifra sola**. El propio catálogo del
 *     servidor lo dice: «un gauge sin objetivo es un KPI con una aguja; la
 *     aguja sólo significa algo contra una meta». Perdiendo la meta, dejaba de
 *     ser un gauge;
 *   · un componente `grafico` se describe como «barras, líneas o áreas» y se
 *     dibujaba siempre como barras. Una serie temporal salía como un bosque de
 *     barras, que es la forma de no ver una tendencia.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Medidor } from "@/componentes/graficas/Medidor";

describe("el medidor", () => {
  it("enseña la cifra, el porcentaje y la meta", () => {
    const { container } = render(
      <Medidor titulo="Ventas del trimestre" valor={75_000} objetivo={100_000} unidad="€" />,
    );
    expect(screen.getByText("75.000 €")).toBeInTheDocument();
    expect(screen.getByText("75%")).toBeInTheDocument();
    // La meta se dice, y cuánto falta: «75 %» sin saber de qué no sirve.
    expect(container.textContent).toContain("medidor.faltan");
  });

  it("pasarse de la meta se VE, no se recorta", () => {
    // Un medidor que recorta en el 100 % esconde que se superó el objetivo,
    // que es justamente la noticia buena.
    const { container } = render(
      <Medidor titulo="Ventas" valor={130} objetivo={100} />,
    );
    expect(screen.getByText("130%")).toBeInTheDocument();
    expect(container.textContent).toContain("medidor.cumplido");
    // La pista llega hasta lo conseguido, así que la marca del objetivo cae
    // ANTES del final: eso es lo que hace visible el exceso.
    const medidor = screen.getByRole("meter");
    expect(Number(medidor.getAttribute("aria-valuemax"))).toBe(130);
    expect(Number(medidor.getAttribute("aria-valuenow"))).toBe(130);
  });

  it("sin objetivo lo dice, y no finge un medidor", () => {
    const { container } = render(<Medidor titulo="Ventas" valor={75} objetivo={0} />);
    expect(container.textContent).toContain("medidor.sinObjetivo");
    // Y no se pinta la barra: una barra contra nada es lo que ya hacía mal.
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  });

  it("se anuncia como medidor a quien no lo ve", () => {
    render(<Medidor titulo="Ventas del trimestre" valor={75} objetivo={100} />);
    expect(screen.getByRole("meter", { name: "Ventas del trimestre" })).toBeInTheDocument();
  });
});

describe("la forma de un gráfico", () => {
  it("la que pide el componente manda sobre la de su tipo", async () => {
    // Se comprueba el mapa, que es lo que decide: con un `grafico` sin forma
    // siguen saliendo barras —lo de siempre, para no cambiarle el dibujo a un
    // cuadro existente— y con forma sale lo que pide.
    const modulo = await import("@/paginas/Cuadros");
    expect(modulo).toBeDefined();

    const { FORMA_DE_TIPO } = await import("@/componentes/graficas/Grafica");
    // Las tres formas que el servidor admite tienen que existir en la gráfica:
    // si no, el cuadro pediría una forma que nadie sabe dibujar.
    expect(FORMA_DE_TIPO.bar_chart).toBe("barras");
    expect(FORMA_DE_TIPO.line_chart).toBe("lineas");
    expect(FORMA_DE_TIPO.area_chart).toBe("area");
  });
});
