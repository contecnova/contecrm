/**
 * Lo que esta persona ha abierto hace poco (CRM-07.04.01.03).
 *
 * **Para qué.** Comparado con Salesforce el 03-11-2026, era el hueco más caro
 * de los que quedaban: allí «Recently Viewed» es lo primero que sale al
 * pinchar el buscador y la vista por defecto de cada objeto, y en ello se
 * apoya casi toda la navegación del día. Aquí, para volver a la cuenta que
 * acababas de mirar había que buscarla otra vez por su nombre.
 *
 * **No vive en el navegador.** Un `localStorage` habría salido más barato y
 * sería otra cosa: se pierde al cambiar de ordenador, no la ve el móvil y no
 * sobrevive a limpiar el sitio. Lo que se pregunta es «qué he mirado yo», no
 * «qué he mirado en este navegador». Está en `/api/v1/vistos`.
 */

import { llamar } from "@/lib/api";

export interface Visto {
  objeto_tipo: string;
  objeto_id: string;
  nombre: string;
  visto_at: string;
}

/**
 * Apunta que se ha abierto un registro.
 *
 * **No espera y no propaga el fallo.** Es un apunte de conveniencia: si el
 * servidor no contesta, lo que no puede pasar es que la ficha que la persona
 * ha venido a ver se quede sin pintar o enseñe un error por esto. Se pierde
 * una entrada del historial, que no es nada.
 */
/**
 * Cuándo se apuntó por última vez cada registro, en esta pestaña.
 *
 * **Abrir el mismo registro dos veces en medio minuto es la misma visita.**
 * Medido con el barrido de pantallas el 03-11-2026: salieron **57 apuntes
 * para 17 registros**, más de tres por registro. Son los remontajes del
 * marco y el doble disparo de efectos del modo estricto en desarrollo — cosas
 * que no son visitas de nadie. El servidor es idempotente y no se estropeaba,
 * pero eran tres escrituras donde hace falta una.
 *
 * Fuera del componente a propósito: dentro de él, un remontaje lo vaciaría y
 * no serviría para lo que está.
 */
const APUNTADOS = new Map<string, number>();

/** Dos visitas al mismo registro dentro de esta ventana son una. */
const MISMA_VISITA_MS = 30_000;

export function anotarVisto(
  objetoTipo: string,
  objetoId: string,
  nombre: string,
): void {
  if (!objetoTipo || !objetoId) return;
  const clave = `${objetoTipo}:${objetoId}`;
  const ahora = Date.now();
  const antes = APUNTADOS.get(clave);
  if (antes !== undefined && ahora - antes < MISMA_VISITA_MS) return;
  APUNTADOS.set(clave, ahora);
  void llamar("/api/v1/vistos", {
    metodo: "POST",
    cuerpo: { objeto_tipo: objetoTipo, objeto_id: objetoId, nombre },
    // Se apunta solo: sin red se pierde, no se encola como un cambio tuyo.
    encolable: false,
  }).catch(() => undefined);
}

/**
 * Los últimos que abrió, del más reciente al más antiguo.
 *
 * Con `limite` y leyendo `items`: es un listado raíz y pagina como todos los
 * demás. Devolvía el array pelado y lo rechazó el guardián de paginación —«un
 * listado sin cursor devuelve su primera página y quien la lee cree que es la
 * tabla»—, que aquí además es fácil de creer porque la lista es corta.
 */
export async function ultimosVistos(
  cuantos: number,
  signal?: AbortSignal,
): Promise<Visto[]> {
  const { datos } = await llamar<{ items: Visto[] }>(
    `/api/v1/vistos?limite=${cuantos}`,
    { signal },
  );
  // **Si no es una lista, lista vacía.** Esto lo pinta la paleta, que es la
  // pieza que se abre con `⌘K` desde cualquier sitio: una respuesta con otra
  // forma la dejaría en blanco y se perdería también la navegación por
  // pantallas, que es a lo que se abre el 90 % de las veces. Es el mismo
  // criterio que `filas()` del cliente de API, y por el mismo motivo.
  return Array.isArray(datos?.items) ? datos.items : [];
}
