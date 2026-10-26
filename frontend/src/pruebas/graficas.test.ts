/**
 * Las gráficas: las cuentas, el reparto de formas y la paleta.
 *
 * Lo que se vigila aquí es lo que se rompe sin que se note:
 *
 *   · un hueco en una serie pintado como cero —una caída a cero que nadie
 *     tuvo— en vez de como un hueco;
 *   · un sexto color generado, que bajo daltonismo es indistinguible de otro y
 *     rompe la paleta entera;
 *   · un tono de estado reutilizado como serie: en un CRM, una serie en rojo
 *     se lee como un problema aunque sea «Cataluña»;
 *   · y el contraste de las marcas contra su superficie, que es la medida que
 *     decide si una barra se ve o no se ve.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { FORMA_DE_TIPO } from "@/componentes/graficas/Grafica";
import {
  SERIES_CON_COLOR,
  aNumero,
  colorDeSerie,
  corto,
  exacto,
  marcas,
  techo,
} from "@/componentes/graficas/escalas";

describe("las cuentas del eje", () => {
  it("las marcas caen en pasos que una persona lee", () => {
    // 0, 20, 40… y nunca 0, 17, 34…: con marcas en 17 hay que hacer la cuenta
    // para saber dónde cae un punto, que es lo que la gráfica venía a evitar.
    for (const maximo of [8, 37, 94, 480, 1_234, 87_000]) {
      const ms = marcas(maximo);
      const paso = (ms[1] ?? 0) - (ms[0] ?? 0);
      const mantisa = paso / Math.pow(10, Math.floor(Math.log10(paso)));
      expect([1, 2, 2.5, 5, 10]).toContain(Number(mantisa.toFixed(10)));
    }
  });

  it("el techo deja aire por encima del dato mayor", () => {
    // Si el techo fuera el máximo, la barra más alta tocaría el borde y
    // parecería cortada.
    for (const valores of [[37], [94, 12], [1_234, 980]]) {
      expect(techo(valores)).toBeGreaterThanOrEqual(Math.max(...valores));
    }
    // Y nunca cero, que dividiría por cero al escalar.
    expect(techo([])).toBeGreaterThan(0);
    expect(techo([null, null])).toBeGreaterThan(0);
  });

  it("un hueco es un hueco y no un cero", () => {
    // **El error más caro de una serie temporal.** Un mes sin medir pintado
    // como cero es una caída a cero que nadie tuvo.
    expect(aNumero(null)).toBeNull();
    expect(aNumero(undefined)).toBeNull();
    expect(aNumero("")).toBeNull();
    expect(aNumero("   ")).toBeNull();
    expect(aNumero({})).toBeNull();
    expect(aNumero(Number.NaN)).toBeNull();
    // Y un cero de verdad sí es cero.
    expect(aNumero(0)).toBe(0);
    expect(aNumero("0")).toBe(0);
  });

  it("el eje abrevia y el emergente no", () => {
    // Son dos sitios con dos trabajos: el eje se lee de un vistazo, el
    // emergente es donde alguien viene a buscar el número de verdad.
    expect(corto(1_250_000)).toContain("M");
    expect(corto(4_200)).toContain("k");
    expect(exacto(1_250_000)).toBe("1.250.000");
    expect(exacto(1_250_000, "€")).toBe("1.250.000 €");
    expect(exacto(null)).toBe("—");
  });
});

describe("la paleta", () => {
  const css = readFileSync(resolve(__dirname, "../index.css"), "utf8");

  function tokens(tema: "claro" | "oscuro"): string[] {
    // El claro vive en `:root` y el oscuro dentro de `.dark`.
    const desde = tema === "claro" ? 0 : css.indexOf(".dark {");
    const hasta = tema === "claro" ? css.indexOf(".dark {") : css.length;
    const trozo = css.slice(desde, hasta);
    return [1, 2, 3, 4, 5].map((i) => {
      const m = trozo.match(new RegExp(`--viz-${i}:\\s*([0-9]+ [0-9]+ [0-9]+)`));
      if (!m) throw new Error(`falta --viz-${i} en ${tema}`);
      return m[1]!;
    });
  }

  function luminancia(rgb: string): number {
    const [r, g, b] = rgb.split(" ").map((n) => {
      const c = Number(n) / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    }) as [number, number, number];
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  function contraste(a: string, b: string): number {
    const [x, y] = [luminancia(a), luminancia(b)].sort((p, q) => q - p) as [number, number];
    return (x + 0.05) / (y + 0.05);
  }

  it("hay cinco series declaradas en los dos temas", () => {
    expect(tokens("claro")).toHaveLength(5);
    expect(tokens("oscuro")).toHaveLength(5);
  });

  it("el oscuro tiene pasos PROPIOS, no el claro volteado", () => {
    // Medido al elegirla: con los valores del claro, el magenta se quedaba en
    // 2,88:1 contra el panel oscuro. Un volteo automático no es una paleta.
    expect(tokens("oscuro")).not.toEqual(tokens("claro"));
  });

  it("toda marca se ve contra su superficie", () => {
    // 3:1 es el mínimo para un elemento no textual. Por debajo, una barra
    // existe en el DOM y no en la pantalla.
    const SUPERFICIE = { claro: "255 255 255", oscuro: "28 29 38" };
    for (const tema of ["claro", "oscuro"] as const) {
      for (const [i, color] of tokens(tema).entries()) {
        const medido = contraste(color, SUPERFICIE[tema]);
        expect(
          medido,
          `--viz-${i + 1} en ${tema} mide ${medido.toFixed(2)}:1 contra el panel`,
        ).toBeGreaterThanOrEqual(3);
      }
    }
  });

  it("ningún tono de estado se reutiliza como serie", () => {
    // Verde, ámbar y rojo están reservados para ganada, en riesgo y perdida.
    // En un CRM eso no es un matiz: una serie en rojo se lee como un problema.
    const ESTADO = ["30 142 62", "249 171 0", "217 48 37", "66 133 244"].filter(
      // El azul del acento SÍ es la serie 1 a propósito: es el color del
      // producto y no lleva carga de estado. Se excluye de la comprobación.
      (c) => c !== "66 133 244",
    );
    for (const tema of ["claro", "oscuro"] as const) {
      for (const color of tokens(tema)) {
        expect(ESTADO, `${color} es un color de estado`).not.toContain(color);
      }
    }
  });

  it("a partir de la sexta serie no se inventa un color", () => {
    // Un sexto tono generado es indistinguible de otro bajo daltonismo y
    // rompe todas las comprobaciones. Lo que sobra se pliega en «otros».
    const colores = Array.from({ length: 5 }, (_, i) => colorDeSerie(i));
    expect(new Set(colores).size).toBe(5);
    for (const i of [5, 6, 12, 99]) {
      expect(colorDeSerie(i)).toBe("rgb(var(--viz-otros))");
    }
    expect(SERIES_CON_COLOR).toBe(5);
  });

  it("el color sigue a la entidad, no a su puesto en el ranking", () => {
    // La serie 3 es la serie 3 aunque un filtro deje de enseñar la 1. Si el
    // color saliera del orden de llegada, filtrar repintaría lo que queda.
    expect(colorDeSerie(2)).toBe("rgb(var(--viz-3))");
    expect(colorDeSerie(0)).toBe("rgb(var(--viz-1))");
  });
});

describe("qué forma toca", () => {
  it("una serie temporal es una línea, no barras", () => {
    // Era el fallo medido: los siete tipos caían en el mismo saco y salían
    // todos como barras horizontales.
    expect(FORMA_DE_TIPO.line_chart).toBe("lineas");
    expect(FORMA_DE_TIPO.timeseries_line).toBe("lineas");
    expect(FORMA_DE_TIPO.area_chart).toBe("area");
    expect(FORMA_DE_TIPO.funnel_chart).toBe("embudo");
    expect(FORMA_DE_TIPO.bar_chart).toBe("barras");
  });

  it("lo que se pide como tarta se dibuja apilado", () => {
    // Comparar ángulos es medir mal: dos porciones parecidas sólo se
    // distinguen leyendo los números, y si hay que leerlos la tarta no estaba
    // aportando nada.
    expect(FORMA_DE_TIPO.pie_chart).toBe("apilada");
    expect(FORMA_DE_TIPO.donut_chart).toBe("apilada");
  });

  it("no existe ninguna forma de dos ejes", () => {
    // Un eje doble deja que quien lo dibuja elija dónde se cruzan las líneas,
    // y entonces la gráfica dice lo que quiera.
    expect(Object.values(FORMA_DE_TIPO)).not.toContain("combinada");
    expect(FORMA_DE_TIPO.combo_chart).toBe("lineas");
  });

  it("un tipo que no conocemos no se dibuja: cae a tabla", () => {
    // Y nunca a un volcado de JSON, que es pedirle a quien pregunta «¿cuánto
    // vendimos?» que lea una estructura de datos.
    expect(FORMA_DE_TIPO.sankey_chart).toBeUndefined();
    expect(FORMA_DE_TIPO.treemap).toBeUndefined();
  });
});
