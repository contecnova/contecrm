/**
 * Un icono de Material Symbols (CRM-07.04.01.02).
 *
 * La misma fuente y el mismo juego que contecmind. Va envuelto en un componente
 * y no suelto por las pantallas para que el `aria-hidden` no dependa de que
 * alguien se acuerde: **un icono nunca se anuncia**. El nombre del símbolo es
 * una ligadura —el texto literal `search` se dibuja como una lupa—, así que un
 * lector de pantalla que lo leyera diría «search» en medio de una frase en
 * castellano.
 *
 * Cuando el icono va solo, sin texto al lado, el nombre accesible lo pone el
 * control que lo contiene con su `aria-label`. Por eso este componente nunca lo
 * pone: si lo pusiera, el botón se anunciaría dos veces.
 */

import { cn } from "@/lib/utiles";

export type Tamano = "sm" | "md" | "lg" | "xl";

const CLASE_TAMANO: Record<Tamano, string> = {
  sm: "material-symbol--sm",
  md: "",
  lg: "material-symbol--lg",
  xl: "material-symbol--xl",
};

export function Icono({
  nombre,
  tamano = "md",
  relleno = false,
  className,
}: {
  nombre: string;
  tamano?: Tamano;
  /** Variante rellena, para el elemento activo. */
  relleno?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "material-symbol",
        CLASE_TAMANO[tamano],
        relleno && "material-symbol--filled",
        className,
      )}
    >
      {nombre}
    </span>
  );
}
