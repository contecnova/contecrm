/**
 * Las filas de una respuesta de listado, sea cual sea su forma.
 *
 * Vivía dentro de la página de la consola y la importaba el listado de cada
 * módulo: con ello el trozo de `Modulo` arrastraba la consola entera y se pasó
 * del tope por pantalla (05-11-2026). Una función que usan dos pantallas es de
 * las dos, no de una de ellas.
 */
import { normalizar } from "@/componentes/Tabla";

/**
 * Convierte lo que devuelve un listado en filas.
 *
 * La API pagina por cursor y devuelve `{items, siguiente}` en unos sitios y una
 * lista a secas en otros. Se admiten las dos formas en vez de exigir una: la
 * alternativa era que media consola no enseñara nada y pareciera que esos
 * recursos están vacíos.
 */
export function comoFilas(
  datos: unknown,
  claveDeLista?: string,
): Record<string, unknown>[] {
  if (Array.isArray(datos)) return normalizar(datos);
  if (datos && typeof datos === "object") {
    const objeto = datos as Record<string, unknown>;
    // Cuando la pantalla dice cuál es su lista, no hay nada que adivinar.
    //
    // Lo dice sólo donde hace falta: respuestas con MÁS DE UNA lista dentro.
    // Sin esto, el camino era el `return [objeto]` de abajo —una fila con el
    // objeto entero— y eso no es un listado: es el JSON crudo repartido en
    // celdas. **Medido el 04-11-2026 llamando a las 204 pestañas declaradas:
    // le pasaba a una**, «Entradas sin atribuir», que devuelve `interacciones`
    // e `interlocutores_frecuentes`. En pantalla salía UNA fila con tres
    // columnas —«Interacciones», «Interlocutores frecuentes», «Cuantas»— y las
    // cuatro interacciones apelotonadas dentro de la primera celda.
    if (claveDeLista) {
      const elegida = objeto[claveDeLista];
      return Array.isArray(elegida) ? normalizar(elegida) : [];
    }
    for (const clave of ["items", "resultados", "datos"]) {
      if (Array.isArray(objeto[clave])) return normalizar(objeto[clave]);
    }
    // Y la tercera forma: la lista bajo su propio nombre —`{partners: […]}`,
    // `{ordenes: […]}`—. Se coge cuando hay una sola propiedad que sea un
    // array; con dos no se adivina cuál es la lista.
    const arrays = Object.values(objeto).filter(Array.isArray) as unknown[][];
    if (arrays.length === 1 && arrays[0]) return normalizar(arrays[0]);
    // Y la cuarta: un **diccionario de registros** —`{oidc_cache_ttl_s: {valor,
    // origen, tipo…}, …}`—, la lista indexada por su clave. Se reconoce porque
    // son dos o más valores, todos registros y todos con la misma forma; un
    // resumen —`{total, este_mes, por_canal: {…}}`— mezcla formas y sigue
    // siendo una fila. La clave pasa a la columna `clave`, que es por la que
    // se edita (`PUT /ajustes/{clave}`).
    //
    // Medido el 05-11-2026 sobre las pestañas declaradas: le pasaba a una, y
    // era «Ajustes» — los 91 umbrales que Administración tiene que poder
    // cambiar salían como UNA fila de 91 columnas, sin forma de editar
    // ninguno salvo teclear su clave exacta en «Nuevo».
    const valores = Object.values(objeto);
    const esRegistro = (v: unknown): v is Record<string, unknown> =>
      Boolean(v) && typeof v === "object" && !Array.isArray(v);
    const forma = (v: Record<string, unknown>) => Object.keys(v).sort().join("|");
    const primero = valores[0];
    if (
      valores.length >= 2 &&
      esRegistro(primero) &&
      valores.every((v) => esRegistro(v) && forma(v) === forma(primero))
    ) {
      return normalizar(
        Object.entries(objeto).map(([clave, v]) => ({
          clave,
          ...(v as Record<string, unknown>),
        })),
      );
    }
    return [objeto];
  }
  return [];
}
