/**
 * Listados: la ruta y la forma de lo que devuelve, juntas.
 *
 * **Van en su propio módulo y no dentro de `api.ts` a propósito.** Una prueba
 * que sustituye `@/lib/api` para servir su propio JSON sustituye el módulo
 * para quien lo importa; una función que vive DENTRO de `api.ts` sigue
 * llamando a la `llamar` de verdad, que en una prueba sale a la red y no
 * contesta. Desde aquí, `llamar` es un import como el de cualquier pantalla y
 * el doble de la prueba vale igual. Medido: 41 pruebas rojas con las dos
 * funciones dentro, y ninguna fuera.
 */

import { filas, llamar, siguientePagina } from "@/lib/api";
import type { Opciones } from "@/lib/api";

/**
 * Un listado, con su ruta y su forma en el mismo sitio.
 *
 * Es `llamar` + `filas` en una llamada, y existe por lo que pasaba al
 * separarlos: la pantalla escribía `llamar<unknown>(ruta)` y le ponía la forma
 * después, con `filas<Algo>(r.datos)`. Eso **no es un atajo, es un hueco**: el
 * guardián que comprueba los contratos sólo mira las llamadas tipadas, así que
 * veintiuna rutas de diez pantallas declaraban una forma que nadie revisaba.
 *
 * Medido el 29-10-2026: por ahí pasaban cuatro pantallas leyendo campos que el
 * servidor no manda —el listado de segmentos, el de campañas, el de territorios
 * y el de conocimiento, que además se caía entera al escribir en el buscador
 * porque filtraba por un título que era `undefined`—.
 */
export async function listar<T>(ruta: string, opciones: Opciones = {}): Promise<T[]> {
  const respuesta = await llamar<unknown>(ruta, opciones);
  return filas<T>(respuesta.datos);
}

/**
 * Un listado del que además hace falta saber si hay más páginas.
 *
 * Igual que `listar`, y existe por lo mismo: sin él, la pantalla que necesita
 * el cursor tenía que volver a `llamar<unknown>` + `filas<T>` y se salía otra
 * vez del alcance del guardián de contratos.
 */
export async function listarPagina<T>(
  ruta: string,
  opciones: Opciones = {},
): Promise<{ filas: T[]; siguiente: string }> {
  const respuesta = await llamar<unknown>(ruta, opciones);
  return { filas: filas<T>(respuesta.datos), siguiente: siguientePagina(respuesta.datos) };
}
