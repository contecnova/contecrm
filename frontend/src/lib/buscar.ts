/**
 * Buscar en un listado **en el servidor** (`?buscar=`), no en lo cargado.
 *
 * El buscador de cada lista y el selector de un campo que apunta a otro
 * registro filtraban las filas que ya estaban en el navegador —las doscientas
 * primeras—. Con más clientes, el que se buscaba no salía y la pantalla decía
 * «nada con eso» de algo que existe. Medido el 10-11-2026.
 *
 * Lo comparten las dos pantallas para que digan lo mismo y caigan igual cuando
 * un listado no sabe buscar.
 */

/**
 * Cuánto se espera tras la última tecla antes de preguntar: una petición por
 * palabra, no por letra. La misma pausa que la paleta de arriba.
 */
export const PAUSA_AL_TECLEAR_MS = 200;

/**
 * Lo que contesta un listado que no sabe buscar por texto: no tiene campos de
 * nombre (`listado.sin_busqueda`) o es una ruta escrita a mano que no admite el
 * parámetro. No es un fallo: se busca en lo cargado y se dice.
 */
export const NO_SABE_BUSCAR: ReadonlySet<string> = new Set([
  "listado.sin_busqueda",
  "peticion.parametro_desconocido",
]);

/** La ruta del listado con el texto que se busca y cuántos traer. */
export function rutaConBusqueda(
  listar: string,
  texto: string,
  limite: number,
): string {
  const separador = listar.includes("?") ? "&" : "?";
  return `${listar}${separador}buscar=${encodeURIComponent(texto)}&limite=${limite}`;
}
