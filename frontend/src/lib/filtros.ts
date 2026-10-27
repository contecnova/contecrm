/**
 * Filtros de un listado: qué se puede preguntar y cómo viaja en la URL.
 *
 * La pantalla de módulo pinta casi todo el producto y **no tenía filtros**. Se
 * podía buscar por texto en los recursos que declaran búsqueda, y nada más: no
 * había forma de pedir «las oportunidades de más de 50.000 que cierran este
 * mes», ni «los casos que siguen abiertos», ni «lo de esta semana». Con listas
 * de más de cien filas eso convierte cualquier pregunta en leer y sumar de
 * cabeza.
 *
 * El servidor ya entiende la gramática —`?importe__mayor=50000`— y es la misma
 * que usa el motor de permisos. Aquí no se inventa nada: se ofrece lo que esa
 * gramática admite, acotado por el tipo del campo.
 *
 * **Los filtros viven en la URL**, no en un estado interno. Es lo que hace que
 * una lista filtrada se pueda guardar en marcadores, pegar en un chat y
 * recargar sin perderla. Un filtro que sólo existe en memoria obliga a
 * reconstruirlo cada vez que alguien vuelve.
 */

/** Tipo aparente de una columna, deducido de lo que devuelve la API. */
export type TipoCampo = "fecha" | "numero" | "booleano" | "texto";

export interface Operador {
  /** Sufijo en la URL. Vacío = igualdad, que no lleva sufijo. */
  sufijo: string;
  /** Clave de traducción del rótulo. */
  clave: string;
  /** `false` para los que no llevan valor (`vacio`, `no_vacio`). */
  conValor: boolean;
}

/**
 * Los operadores de cada tipo, **en el orden en que se usan**.
 *
 * No se ofrecen todos para todo: «mayor que» sobre un booleano no significa
 * nada, y un desplegable con ocho opciones de las que cinco no aplican es un
 * desplegable que se lee entero cada vez.
 */
const POR_TIPO: Record<TipoCampo, Operador[]> = {
  fecha: [
    { sufijo: "desde", clave: "filtros.desde", conValor: true },
    { sufijo: "hasta", clave: "filtros.hasta", conValor: true },
    { sufijo: "", clave: "filtros.esIgual", conValor: true },
    { sufijo: "vacio", clave: "filtros.sinValor", conValor: false },
    { sufijo: "no_vacio", clave: "filtros.conValor", conValor: false },
  ],
  numero: [
    { sufijo: "mayor", clave: "filtros.mayorQue", conValor: true },
    { sufijo: "menor", clave: "filtros.menorQue", conValor: true },
    { sufijo: "desde", clave: "filtros.desdeNumero", conValor: true },
    { sufijo: "hasta", clave: "filtros.hastaNumero", conValor: true },
    { sufijo: "", clave: "filtros.esIgual", conValor: true },
    { sufijo: "vacio", clave: "filtros.sinValor", conValor: false },
  ],
  booleano: [
    { sufijo: "", clave: "filtros.esIgual", conValor: true },
    { sufijo: "vacio", clave: "filtros.sinValor", conValor: false },
  ],
  texto: [
    { sufijo: "", clave: "filtros.esIgual", conValor: true },
    { sufijo: "distinto", clave: "filtros.distintoDe", conValor: true },
    { sufijo: "en", clave: "filtros.esAlgunoDe", conValor: true },
    { sufijo: "vacio", clave: "filtros.sinValor", conValor: false },
    { sufijo: "no_vacio", clave: "filtros.conValor", conValor: false },
  ],
};

export function operadoresDe(tipo: TipoCampo): Operador[] {
  return POR_TIPO[tipo];
}

/**
 * El tipo de una columna, deducido de los valores que han llegado.
 *
 * Se mira la primera fila con valor y **no la primera fila**: en una columna
 * mayoritariamente vacía, la primera suele serlo, y entonces todo parecería
 * texto y se ofrecerían los operadores equivocados.
 *
 * Las fechas se reconocen por la forma ISO, que es la que manda la API. No se
 * intenta adivinar con `Date.parse`, que acepta cosas como «5» y convertiría
 * cualquier número en una fecha.
 */
const ISO = /^\d{4}-\d{2}-\d{2}([T ]|$)/;

export function tipoDe(filas: Array<Record<string, unknown>>, campo: string): TipoCampo {
  for (const fila of filas) {
    const v = fila[campo];
    if (v === null || v === undefined || v === "") continue;
    if (typeof v === "boolean") return "booleano";
    if (typeof v === "number") return "numero";
    if (typeof v === "string") {
      if (ISO.test(v)) return "fecha";
      // Un número que viaja como texto —un importe decimal— sigue siendo un
      // número para quien filtra. La API los manda así a propósito, para no
      // perder precisión en coma flotante.
      if (v.trim() !== "" && !Number.isNaN(Number(v))) return "numero";
    }
    return "texto";
  }
  return "texto";
}

export interface Filtro {
  campo: string;
  sufijo: string;
  valor: string;
}

/** El nombre del parámetro: `campo` o `campo__sufijo`. */
export function parametroDe(filtro: Filtro): string {
  return filtro.sufijo ? `${filtro.campo}__${filtro.sufijo}` : filtro.campo;
}

/**
 * Qué parámetros de la URL son filtros y cuáles gobiernan la pantalla.
 *
 * La lista es de los que NO lo son, y es corta y cerrada a propósito: con una
 * lista de los que sí, cada campo nuevo de cada módulo habría que añadirlo
 * aquí, y el que se olvide deja de poderse filtrar sin que nadie lo note.
 *
 * **`r` y `nuevo` faltaban, y los escribe la propia pantalla de módulo**: `r`
 * es la pestaña abierta y `nuevo=1` abre el formulario de alta. Al leerlos de
 * vuelta se mandaban al servidor como si fueran campos, y la respuesta era un
 * 422 «No se puede filtrar por «r»» con la lista de columnas del objeto
 * debajo. Lo veía cualquiera que pulsara «crear» desde una pestaña: la
 * pantalla entera en rojo en vez del formulario.
 *
 * Son de la pantalla, no del dato: ningún objeto del catálogo tiene un campo
 * que se llame `r` ni `nuevo`, así que excluirlos no quita ningún filtro real.
 */
const NO_SON_FILTROS = new Set([
  "cursor",
  "limite",
  "orden",
  "campos",
  "total",
  "formato",
  "vista",
  // Las dos de la pantalla de módulo: qué pestaña y si se abre el alta.
  "r",
  "nuevo",
]);

export function leerFiltros(params: URLSearchParams, buscar?: string): Filtro[] {
  const salida: Filtro[] = [];
  for (const [nombre, valor] of params.entries()) {
    if (NO_SON_FILTROS.has(nombre) || nombre === buscar) continue;
    const corte = nombre.indexOf("__");
    salida.push(
      corte === -1
        ? { campo: nombre, sufijo: "", valor }
        : { campo: nombre.slice(0, corte), sufijo: nombre.slice(corte + 2), valor },
    );
  }
  return salida;
}

/** Los filtros como trozo de query, listo para pegar a la ruta del listado. */
export function comoQuery(filtros: Filtro[]): string {
  return filtros
    .map((f) => `${encodeURIComponent(parametroDe(f))}=${encodeURIComponent(f.valor)}`)
    .join("&");
}
