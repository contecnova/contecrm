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
    // Las medidas son las del `PageHeader` de contecflow, una a una: 28px por
    // debajo, 20px hasta la línea, y línea. La línea es la que faltaba aquí —
    // sin ella el título y la primera tabla se tocan y la cabecera no termina
    // en ningún sitio.
    <header className="mb-7 flex items-start justify-between gap-4 border-b border-ink-dim/60 pb-5">
      <div className="min-w-0">
        <div className="flex items-center gap-2.5">
          {/* El icono va en su propia caja, no suelto al lado del texto: suelto
              se lee como parte del título y hereda su tamaño, y el título de
              cada pantalla acaba midiendo distinto según lleve icono o no. */}
          {icono ? (
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-accent/25 bg-accent/10 text-accent">
              <Icono nombre={icono} />
            </span>
          ) : null}
          <h1 className="min-w-0 truncate text-xl-em font-bold tracking-[-0.01em] text-ink">
            {titulo}
          </h1>
        </div>
        {entradilla ? (
          <p className={`mt-2 max-w-3xl text-xs text-ink-muted${icono ? " pl-[2.875rem]" : ""}`}>
            {entradilla}
          </p>
        ) : null}
      </div>
      {acciones ? <div className="flex shrink-0 items-center gap-2">{acciones}</div> : null}
    </header>
  );
}
