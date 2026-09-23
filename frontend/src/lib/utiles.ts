/** Utilidades mínimas compartidas por los componentes del armazón. */

/** Junta clases y descarta las que no aplican. Igual que en contecmind. */
export function cn(...clases: (string | false | null | undefined)[]): string {
  return clases.filter(Boolean).join(" ");
}

/**
 * Cómo se llama la tecla del atajo en esta máquina.
 *
 * Escribir «Ctrl K» en un Mac no es un detalle estético: es una instrucción
 * falsa. Quien la sigue pulsa Ctrl+K, no pasa nada, y concluye que la paleta
 * no funciona.
 */
export function teclaAtajo(tecla = "K"): string {
  const esMac =
    typeof navigator !== "undefined" && /mac|iphone|ipad/i.test(navigator.platform || "");
  return esMac ? `⌘${tecla}` : `Ctrl ${tecla}`;
}
