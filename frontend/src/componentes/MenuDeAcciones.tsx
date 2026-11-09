/**
 * El menú de «lo demás que se puede hacer» con un registro.
 *
 * **Por qué existe.** Medido en el navegador sobre ocho fichas: en las ocho
 * «Eliminar» era el **segundo botón**, delante de todas las acciones útiles; y
 * la de una cuenta apilaba siete botones del mismo peso en dos filas, cinco de
 * ellos de más de dieciocho caracteres y el más largo de cuarenta y uno:
 *
 *     [Editar] [Eliminar] [Añadir una dirección]
 *     [Colgar la cuenta de otra en una jerarquía] [Fusionar esta cuenta con otra]
 *     [Relacionar esta cuenta con otra] [Sumar a alguien al equipo de la cuenta]
 *
 * Siete cosas igual de destacadas no destacan ninguna, y la que estaba en el
 * sitio más fácil de pulsar era la única que no se deshace.
 *
 * **La regla no lleva ningún número.** No es «las tres primeras fuera y el
 * resto dentro», porque ese tres habría que justificarlo y revisarlo. Es: lo
 * que se usa a diario se queda fuera y **todo lo demás —y siempre lo
 * destructivo— entra aquí**. Quien decide qué es qué es quien pinta la barra,
 * no este componente.
 *
 * Teclado: se abre con Intro o Espacio, se cierra con Escape devolviendo el
 * foco al botón, y se cierra al pulsar fuera. Sin eso es un menú que sólo
 * existe para quien usa ratón.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Icono } from "@/componentes/Icono";
import { cn } from "@/lib/utiles";

export interface OpcionDeMenu {
  clave: string;
  nombre: string;
  alElegir: () => void;
  /** Se pinta en rojo y se separa del resto: no se deshace. */
  destructiva?: boolean;
}

export function MenuDeAcciones({
  opciones,
  etiqueta,
  children,
  clase,
  soloIcono = false,
  haciaLaIzquierda = false,
}: {
  opciones: OpcionDeMenu[];
  /** Cómo se llama el menú para quien no lo ve. */
  etiqueta?: string;
  /**
   * Con qué aspecto se pinta el botón que lo abre.
   *
   * Por defecto es un botón secundario, que es lo que pide una ficha. En la
   * barra de aplicación tiene que parecer **una pestaña más**: un botón con
   * borde entre las pestañas se lee como otra cosa y rompe la fila.
   */
  clase?: string;
  /**
   * Sólo el chevrón, sin la palabra «Más».
   *
   * Para el menú del final de una fila: ahí Lightning no pone texto, y
   * ponerlo ensancha la columna en todas las filas para repetir cincuenta
   * veces la misma palabra. El nombre accesible lo da `etiqueta`.
   */
  soloIcono?: boolean;
  /**
   * El panel se abre hacia la IZQUIERDA.
   *
   * Hace falta cuando el botón vive pegado al borde derecho —el menú de una
   * fila—: con la apertura por defecto, el panel sale fuera de la pantalla y
   * las opciones aparecen cortadas a «Abri…» y «Edit…». Medido abriéndolo.
   */
  haciaLaIzquierda?: boolean;
  /** Lo que va delante del menú, en la misma fila: las acciones del día. */
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  // Hacia dónde abre, decidido al abrir: si desde el botón no cabe hacia la
  // derecha, hacia la izquierda. Dejarlo a que cada sitio lo pida hacía que el
  // «Más» de la ficha, pegado al borde derecho, se cortara (09-11-2026).
  const [noCabe, setNoCabe] = useState(false);
  const caja = useRef<HTMLDivElement>(null);
  const disparador = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!abierto) return;
    function fuera(e: MouseEvent) {
      if (caja.current && !caja.current.contains(e.target as Node))
        setAbierto(false);
    }
    function escape(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      setAbierto(false);
      // El foco vuelve al botón: cerrar un menú y dejar el foco en el cuerpo
      // obliga a tabular desde el principio de la página.
      disparador.current?.focus();
    }
    document.addEventListener("mousedown", fuera);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", fuera);
      document.removeEventListener("keydown", escape);
    };
  }, [abierto]);

  // Las que no se deshacen van al final y separadas, para que no se pulsen de
  // paso al bajar por la lista.
  const normales = opciones.filter((o) => !o.destructiva);
  const destructivas = opciones.filter((o) => o.destructiva);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {children}
      {opciones.length > 0 ? (
        <div className="relative" ref={caja}>
          <button
            ref={disparador}
            type="button"
            className={clase ?? "btn-secondary inline-flex items-center gap-1"}
            aria-haspopup="menu"
            aria-expanded={abierto}
            aria-label={etiqueta ?? t("acciones.mas")}
            onClick={() => {
              const caja = disparador.current?.getBoundingClientRect();
              // 20rem es el ancho máximo del menú (abajo, `max-w-[min(20rem…`).
              const ancho =
                20 *
                parseFloat(
                  getComputedStyle(document.documentElement).fontSize || "16",
                );
              setNoCabe(
                Boolean(caja && caja.left + ancho > window.innerWidth - 8),
              );
              setAbierto((v) => !v);
            }}
          >
            {soloIcono ? null : t("acciones.mas")}
            <Icono
              nombre={abierto ? "expand_less" : "expand_more"}
              tamano="sm"
            />
          </button>
          {abierto ? (
            <div
              role="menu"
              aria-label={etiqueta ?? t("acciones.mas")}
              className={cn(
                // El tope de ancho no es cosmética: abrir hacia un lado
                // resuelve el borde de ese lado y deja el contrario. Un
                // «Aprobar documentos pendientes de firma» en una ventana
                // estrecha se saldría por la izquierda exactamente igual que
                // antes se salía por la derecha. Con tope, el nombre largo
                // parte en dos líneas y el panel sigue dentro.
                "absolute z-popover mt-1 min-w-56 max-w-[min(20rem,calc(100vw-2rem))]",
                "rounded-xl border border-ink-dim/60 bg-paper p-1 shadow-elevation-3",
                haciaLaIzquierda || noCabe ? "right-0" : "left-0",
              )}
            >
              {normales.map((o) => (
                <button
                  key={o.clave}
                  type="button"
                  role="menuitem"
                  className="block w-full rounded px-3 py-1.5 text-left text-titulin text-ink hover:bg-paper-light"
                  onClick={() => {
                    setAbierto(false);
                    o.alElegir();
                  }}
                >
                  {o.nombre}
                </button>
              ))}
              {destructivas.length > 0 && normales.length > 0 ? (
                <hr className="my-1 border-ink-dim/40" />
              ) : null}
              {destructivas.map((o) => (
                <button
                  key={o.clave}
                  type="button"
                  role="menuitem"
                  className="block w-full rounded px-3 py-1.5 text-left text-titulin text-danger hover:bg-danger/10"
                  onClick={() => {
                    setAbierto(false);
                    o.alElegir();
                  }}
                >
                  {o.nombre}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
