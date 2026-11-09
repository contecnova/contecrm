/**
 * La gráfica, dibujada de verdad.
 *
 * Lo de arriba comprueba las cuentas; esto comprueba lo que sale en pantalla,
 * que es donde viven los fallos que importan: una leyenda que falta, un trazo
 * que cruza un hueco inventando una tendencia, y la tabla que tiene que estar
 * siempre porque es lo único que funciona con un lector de pantalla.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Grafica, type DatosGrafica } from "@/componentes/graficas/Grafica";

const MESES: DatosGrafica = {
  filas: [
    { mes: "ene", ventas: 120, soporte: 40 },
    { mes: "feb", ventas: null, soporte: 55 },
    { mes: "mar", ventas: 180, soporte: 30 },
  ],
  ejeX: "mes",
  rotuloX: "Mes",
  series: [
    { clave: "ventas", rotulo: "Ventas" },
    { clave: "soporte", rotulo: "Soporte" },
  ],
  unidad: "€",
};

function unaSerie(): DatosGrafica {
  return { ...MESES, series: [{ clave: "ventas", rotulo: "Ventas" }] };
}

describe("lo que se pinta", () => {
  it("con dos series hay leyenda, y con una no", () => {
    // La leyenda es obligatoria con dos o más por una razón medida: magenta y
    // teal se separan ΔE 6,6 bajo deuteranopía, en la banda que sólo es legal
    // con codificación secundaria. Con una serie sobra: el título ya la nombra
    // y una leyenda de un elemento es una fila de ruido.
    // Se busca DENTRO de la leyenda: desde el 09-11-2026 el detalle de abajo
    // sale siempre (con la primera categoría) y también nombra las series.
    const { unmount } = render(
      <Grafica forma="lineas" datos={MESES} titulo="Por mes" />,
    );
    const leyenda = screen.getByRole("list", { name: /leyenda/i });
    expect(within(leyenda).getByText("Ventas")).toBeInTheDocument();
    expect(within(leyenda).getByText("Soporte")).toBeInTheDocument();
    unmount();

    render(<Grafica forma="lineas" datos={unaSerie()} titulo="Por mes" />);
    expect(
      screen.queryByRole("list", { name: /leyenda/i }),
    ).not.toBeInTheDocument();
  });

  it("el trazo se parte en el hueco y no lo cruza", () => {
    // Febrero no tiene dato. Una línea recta de enero a marzo dibuja una
    // tendencia que nadie midió, y es el error más caro de una serie temporal.
    const { container } = render(
      <Grafica forma="lineas" datos={unaSerie()} titulo="Por mes" />,
    );
    const trazos = container.querySelectorAll("path[stroke]");
    expect(trazos.length).toBe(2);
    for (const t of trazos) {
      expect(t.getAttribute("d")).not.toContain("feb");
    }
  });

  it("sin huecos el trazo es uno solo", () => {
    const seguidos: DatosGrafica = {
      ...MESES,
      filas: [
        { mes: "ene", ventas: 120 },
        { mes: "feb", ventas: 140 },
        { mes: "mar", ventas: 180 },
      ],
      series: [{ clave: "ventas", rotulo: "Ventas" }],
    };
    const { container } = render(
      <Grafica forma="lineas" datos={seguidos} titulo="Por mes" />,
    );
    expect(container.querySelectorAll("path[stroke]").length).toBe(1);
  });

  it("el área se rellena con una serie y NO con tres", () => {
    // Se descubrió mirando el dibujo, que es lo que ningún validador de color
    // caza: con tres series los rellenos se superponen y se mezclan en un
    // barro del que no se saca ninguna de las tres. Se degrada a líneas.
    const { container: sola } = render(
      <Grafica forma="area" datos={unaSerie()} titulo="Una" />,
    );
    expect(sola.querySelectorAll("path[fill-opacity]").length).toBeGreaterThan(
      0,
    );

    const { container: tres } = render(
      <Grafica forma="area" datos={MESES} titulo="Tres" />,
    );
    expect(tres.querySelectorAll("path[fill-opacity]")).toHaveLength(0);
    // Pero las tres líneas siguen ahí: se degrada, no se deja de dibujar.
    expect(tres.querySelectorAll("path[stroke]").length).toBeGreaterThanOrEqual(
      3,
    );
  });

  it("el embudo no lleva eje de valor ni rótulos abajo", () => {
    // También de mirarlo: tenía marcas de 0 a 1,5 k al lado —una escala que no
    // mide nada de lo que se ve— y los nombres de etapa en el eje de abajo,
    // donde «Contactado» caía debajo de la barra de «Ganada» y el último se
    // cortaba a «Ganad».
    const embudo: DatosGrafica = {
      filas: [
        { etapa: "Contactado", n: 1240 },
        { etapa: "Calificado", n: 720 },
        { etapa: "Ganada", n: 62 },
      ],
      ejeX: "etapa",
      series: [{ clave: "n", rotulo: "Oportunidades" }],
    };
    const { container } = render(
      <Grafica forma="embudo" datos={embudo} titulo="Embudo" />,
    );
    // Ni una línea de rejilla.
    expect(container.querySelectorAll("line")).toHaveLength(0);
    // El nombre de cada etapa está, y alineado a la derecha contra su barra.
    const rotulos = [
      ...container.querySelectorAll('text[text-anchor="end"]'),
    ].map((e) => e.textContent);
    expect(rotulos).toContain("Contactado");
    expect(rotulos).toContain("Ganada");
    // Y el peso de cada etapa SOBRE EL TOTAL: 1.200 + 720 + 62 = 1.982, así
    // que 61 %, 36 % y 3 %.
    //
    // Antes era la caída desde la primera etapa —1.200 → 62 es un 5 %—, y
    // para un embudo que decrece es la pregunta buena. El problema es que **no
    // todos decrecen**: la portada suma IMPORTES por etapa, y ahí la segunda
    // puede valer más que la primera. Medido el 01-11-2026 en la portada de un
    // comercial: «495,3 k · 1764 %» y «555,5 k · 1979 %». Un porcentaje de mil
    // novecientos en la primera pantalla del producto no es un matiz: es un
    // número que no significa nada y que hace dudar de los de al lado.
    //
    // Sobre el total es cierto en los dos casos, y en un embudo que decrece
    // sigue contando la misma historia.
    expect(container.textContent).toContain("61%");
    expect(container.textContent).toContain("3%");
  });

  it("el nombre de una etapa larga se lee entero, no cortado", () => {
    // **Medido en el navegador el 03-11-2026**, en la portada: el embudo de
    // ventas enseñaba «Oferta presenta…» y «Pendiente de ad…» mientras a su
    // derecha sobraban 1.284 px de pantalla vacía. El sitio del rótulo era un
    // 92 fijo y el corte, 16 caracteres: dos de las siete etapas del producto
    // no se podían leer, en la primera pantalla que ve nadie.
    //
    // Son los nombres de etapa de verdad, los que trae el producto.
    const largas: DatosGrafica = {
      filas: [
        { etapa: "Oferta presentada", n: 10 },
        { etapa: "Pendiente de adjudicación", n: 4 },
        { etapa: "Ganada", n: 2 },
      ],
      ejeX: "etapa",
      series: [{ clave: "n", rotulo: "Oportunidades" }],
    };
    const { container } = render(
      <Grafica forma="embudo" datos={largas} titulo="Embudo" />,
    );
    const rotulos = [
      ...container.querySelectorAll('text[text-anchor="end"]'),
    ].map((e) => e.textContent ?? "");
    // Que se han mirado los tres: una lista vacía daría verde sin cortar nada.
    expect(rotulos).toHaveLength(3);
    expect(rotulos.filter((r) => r.includes("\u2026"))).toEqual([]);
    expect(rotulos).toContain("Pendiente de adjudicación");
  });

  it("siempre se puede ver como tabla, con el valor exacto", async () => {
    render(<Grafica forma="barras" datos={MESES} titulo="Por mes" />);
    await userEvent.click(screen.getByRole("button", { name: /tabla/i }));

    const tabla = screen.getByRole("table");
    expect(within(tabla).getByText("Mes")).toBeInTheDocument();
    // El valor exacto con su unidad, no el abreviado del eje.
    expect(within(tabla).getByText("120 €")).toBeInTheDocument();
    // Y el hueco se dice, no se rellena con un cero.
    expect(within(tabla).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("sin datos lo dice, y no pinta un marco vacío", () => {
    // Se comprueba por estructura y no por el texto: en pruebas, i18n
    // devuelve la clave, y una aserción sobre la copia se rompe el día que
    // alguien mejore la frase sin tocar el comportamiento.
    const { container } = render(
      <Grafica
        forma="barras"
        datos={{ ...MESES, filas: [] }}
        titulo="Por mes"
      />,
    );
    // Ni dibujo ni ejes: un marco vacío con la rejilla puesta parece una
    // gráfica cargando para siempre.
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(container.querySelectorAll("svg")).toHaveLength(0);
    // Pero sí se dice algo, que es lo contrario de no pintar nada.
    expect(container.querySelector("figure p")?.textContent).toBeTruthy();
  });

  it("la gráfica se anuncia con su título a quien no la ve", () => {
    render(<Grafica forma="barras" datos={MESES} titulo="Ventas por mes" />);
    expect(
      screen.getByRole("img", { name: "Ventas por mes" }),
    ).toBeInTheDocument();
  });

  it("a partir de la sexta serie se pliega la cola, no se inventan colores", () => {
    const muchas: DatosGrafica = {
      filas: [{ x: "a", s1: 1, s2: 2, s3: 3, s4: 4, s5: 5, s6: 6, s7: 7 }],
      ejeX: "x",
      series: [1, 2, 3, 4, 5, 6, 7].map((n) => ({
        clave: `s${n}`,
        rotulo: `S${n}`,
      })),
    };
    const { container } = render(
      <Grafica forma="barras" datos={muchas} titulo="Muchas" />,
    );
    // En la leyenda: el detalle de abajo sale siempre y nombra también las series.
    const leyenda = screen.getByRole("list", { name: /leyenda/i });
    expect(within(leyenda).getByText("S5")).toBeInTheDocument();
    // S6 y S7 ya no tienen rótulo propio: van sumadas en una sola entrada.
    expect(screen.queryByText("S6")).not.toBeInTheDocument();
    expect(screen.queryByText("S7")).not.toBeInTheDocument();
    // Seis entradas de leyenda para siete series: cinco con color y la cola.
    expect(within(leyenda).getAllByRole("listitem")).toHaveLength(6);
    // Y los colores usados son exactamente los cinco declarados más «otros»:
    // ni uno generado.
    const usados = new Set(
      [...container.querySelectorAll('rect[fill^="rgb(var(--viz"]')].map((r) =>
        r.getAttribute("fill"),
      ),
    );
    expect(usados.size).toBeLessThanOrEqual(6);
    expect(
      [...usados].every((c) => /--viz-([1-5]|otros)\)/.test(c ?? "")),
    ).toBe(true);
  });
});
