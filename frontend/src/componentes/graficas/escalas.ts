/**
 * Las cuentas de una gráfica: escalas, marcas de eje y formato.
 *
 * Aparte del dibujo a propósito. Son la parte que se puede equivocar en
 * silencio —un eje que no empieza en cero, una marca cada 7 unidades, un
 * número con dos decimales donde todos son enteros— y es la parte que se puede
 * probar sin montar un SVG.
 */

/** Un valor del eje, ya resuelto a número. `null` es «no hay dato». */
export type Dato = number | null;

/**
 * El tope del eje y sus marcas, en pasos que una persona lee.
 *
 * Los pasos son 1, 2, 2.5, 5 y 10 por década: son los que producen 0, 20, 40…
 * en vez de 0, 17, 34… Un eje con marcas en 17 obliga a hacer la cuenta para
 * saber dónde cae un punto, que es justo lo que la gráfica venía a evitar.
 */
export function marcas(maximo: number, cuantas = 4): number[] {
  if (!Number.isFinite(maximo) || maximo <= 0) return [0];
  const bruto = maximo / cuantas;
  const decada = Math.pow(10, Math.floor(Math.log10(bruto)));
  const paso =
    [1, 2, 2.5, 5, 10].map((m) => m * decada).find((p) => p >= bruto) ?? 10 * decada;
  const salida: number[] = [];
  for (let v = 0; v <= maximo + paso * 0.001; v += paso) salida.push(Number(v.toFixed(10)));
  return salida;
}

/**
 * El techo del eje: la marca siguiente por encima del dato mayor.
 *
 * Nunca el dato mayor exacto. Si el techo fuera el máximo, la barra más alta
 * tocaría el borde y parecería cortada, y el punto más alto de una línea se
 * quedaría pegado al marco.
 */
export function techo(valores: Dato[]): number {
  const maximo = Math.max(0, ...valores.filter((v): v is number => v !== null));
  if (maximo <= 0) return 1;
  const ms = marcas(maximo);
  const ultima = ms[ms.length - 1] ?? maximo;
  return ultima >= maximo ? ultima : ultima + (ms[1] ?? maximo);
}

/**
 * Formato de un número para que se lea de un vistazo.
 *
 * Abrevia por encima del millar porque un eje con «1.250.000» en cada marca es
 * un eje que no se lee: se cuentan las cifras. El valor exacto vive en el
 * emergente, que es donde alguien va a buscarlo.
 */
export function corto(valor: number): string {
  const abs = Math.abs(valor);
  if (abs >= 1_000_000) return `${(valor / 1_000_000).toLocaleString("es-ES", { maximumFractionDigits: 1 })} M`;
  if (abs >= 1_000) return `${(valor / 1_000).toLocaleString("es-ES", { maximumFractionDigits: 1 })} k`;
  return valor.toLocaleString("es-ES", { maximumFractionDigits: 2 });
}

/** El valor entero, con separador de miles y su unidad si la tiene. */
export function exacto(valor: Dato, unidad?: string | null): string {
  if (valor === null) return "—";
  const texto = Number.isInteger(valor)
    ? valor.toLocaleString("es-ES")
    : valor.toLocaleString("es-ES", { maximumFractionDigits: 2 });
  return unidad ? `${texto} ${unidad}` : texto;
}

/**
 * Lo que venga, convertido a número, o `null`.
 *
 * `null` y no `0`: son dos cosas distintas y llevan a decisiones distintas.
 * Un mes sin medir pintado como cero es una caída a cero que nadie tuvo, y es
 * el error más caro de una serie temporal.
 */
export function aNumero(valor: unknown): Dato {
  if (typeof valor === "number") return Number.isFinite(valor) ? valor : null;
  if (typeof valor === "string" && valor.trim() !== "") {
    const n = Number(valor.replace(",", "."));
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * El color de la serie `i`, **por su posición y nunca ciclado**.
 *
 * A partir de la sexta no se inventa un tono: se pliega en «otros». Un sexto
 * color generado es indistinguible de otro bajo daltonismo y rompe todas las
 * comprobaciones de la paleta.
 */
export function colorDeSerie(i: number): string {
  return i < 5 ? `rgb(var(--viz-${i + 1}))` : "rgb(var(--viz-otros))";
}

/** Cuántas series se pintan con color propio antes de plegar la cola. */
export const SERIES_CON_COLOR = 5;

/**
 * Hasta cuántas series se etiquetan directamente sobre el dibujo.
 *
 * Con cuatro o menos, la etiqueta al lado del trazo evita el viaje de ida y
 * vuelta a la leyenda. Con más, las etiquetas se pisan y estorban más de lo
 * que ayudan — y entonces manda la leyenda, que siempre está.
 */
export const MAXIMO_ETIQUETA_DIRECTA = 4;
