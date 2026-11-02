/**
 * La tarjeta de una lista relacionada: su nombre, cuántos hay y lo que lleva
 * dentro.
 *
 * Es la forma que tiene Salesforce de enseñar lo que cuelga de un registro, y
 * lo que la hace legible no es la caja sino **el rótulo con el recuento**:
 * «Contactos (3)», «Adjuntos (0)». Se sabe qué es sin abrirlo y se sabe si hay
 * algo sin mirarlo.
 *
 * Aquí los paneles del contrato ya lo tenían y los tres transversales
 * —adjuntos, comentarios y documentos— no: salían como una tarjeta sin título
 * con «Aquí no hay nada todavía» dentro. Visto en la pantalla: la pestaña de
 * un candidato eran dos cajas idénticas y anónimas, y no había forma de saber
 * cuál era cuál. Mismo registro, misma pregunta, dos formas de enseñarlo.
 *
 * El abierto/cerrado **lo lleva quien lo usa** y no esta pieza: los paneles
 * del contrato piden sus datos al abrirse —una ficha con ocho haría ocho
 * llamadas antes de que nadie mire ninguna— y necesitan saberlo.
 */

import type { ReactNode } from "react";

import { Icono } from "@/componentes/Icono";

export function PanelRelacionado({
  nombre,
  cuantos,
  abierto,
  alAlternar,
  acciones,
  children,
}: {
  nombre: string;
  /** Cuántos elementos hay. Sin valor cuando todavía no se sabe. */
  cuantos?: number;
  abierto: boolean;
  alAlternar: () => void;
  /** Lo que se puede hacer sobre la lista entera: subir un fichero, enlazar. */
  acciones?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card">
      <div className="flex items-center justify-between gap-2 pr-4">
        <button
          type="button"
          onClick={alAlternar}
          aria-expanded={abierto}
          className="flex min-w-0 flex-1 items-center gap-1.5 px-4 py-3 text-left text-titulin font-medium text-ink"
        >
          <Icono
            nombre="keyboard_arrow_down"
            tamano="sm"
            className={abierto ? "" : "-rotate-90"}
          />
          <span className="truncate">{nombre}</span>
          {/* El recuento va entre paréntesis y PEGADO al nombre, como en
              Lightning. Suelto al otro extremo de la tarjeta es un número sin
              dueño: así estaban los paneles del contrato. */}
          {cuantos !== undefined ? (
            <span className="shrink-0 font-normal text-ink-faint">
              ({cuantos})
            </span>
          ) : null}
        </button>
        {acciones ? <div className="shrink-0">{acciones}</div> : null}
      </div>

      {abierto ? (
        <div className="border-t border-ink-dim/30 px-4 py-3">{children}</div>
      ) : null}
    </section>
  );
}
