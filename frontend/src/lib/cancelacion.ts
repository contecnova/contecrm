/**
 * Si un error es una cancelación del `AbortController` y no un fallo.
 *
 * La usa `salvoCancelacion` y la usan las cargas secundarias
 * (`useCargasSecundarias`), que necesitan la misma pregunta sin el
 * envoltorio: una cancelación termina la carga pero no es un fallo que pintar.
 *
 * **En su propio módulo y no en `api.ts`, a propósito**, por lo mismo que
 * `listados.ts`: las pruebas que sustituyen `@/lib/api` con un doble escrito a
 * mano no la traen, y entonces cualquier pantalla con cargas secundarias
 * rompía en esas pruebas con «No "esCancelacion" export is defined on the
 * mock». Medido el 14-11-2026: 32 errores en cuatro ficheros de prueba.
 */
export function esCancelacion(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}
