/**
 * La cabecera de una pantalla, igual en todas (CRM-07.04.01.02).
 *
 * Existe para que el título, la entradilla y las acciones tengan la misma
 * presencia en toda la aplicación. Cuando cada pantalla se pinta su propio
 * encabezado, el tamaño, el margen y el sitio de los botones varían un poco en
 * cada una, y esa variación es exactamente lo que hace que un producto parezca
 * cosido de trozos.
 *
 * Pone el `<h1>` de la pantalla. Es el único de la página a propósito: quien
 * navega con lector salta por encabezados, y dos de primer nivel dejan de
 * indicar dónde está uno.
 */

import type { ReactNode } from "react";

import { Icono } from "@/componentes/Icono";

export function CabeceraPagina({
  titulo,
  entradilla,
  acciones,
  icono,
}: {
  titulo: ReactNode;
  entradilla?: ReactNode;
  /** Botones de la derecha. */
  acciones?: ReactNode;
  /** Nombre del símbolo de Material que acompaña al título. */
  icono?: string;
}) {
  return (
    <header className="mb-6 flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="inline-flex items-center gap-2 text-xl font-semibold text-ink">
          {icono ? <Icono nombre={icono} className="text-ink-muted" /> : null}
          <span className="truncate">{titulo}</span>
        </h1>
        {entradilla ? <p className="mt-1 max-w-3xl text-sm text-ink-muted">{entradilla}</p> : null}
      </div>
      {acciones ? <div className="flex shrink-0 items-center gap-2">{acciones}</div> : null}
    </header>
  );
}
