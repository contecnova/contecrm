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
}: {
  opciones: OpcionDeMenu[];
  /** Cómo se llama el menú para quien no lo ve. */
  etiqueta?: string;
  /** Lo que va delante del menú, en la misma fila: las acciones del día. */
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  const caja = useRef<HTMLDivElement>(null);
  const disparador = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!abierto) return;
    function fuera(e: MouseEvent) {
      if (caja.current && !caja.current.contains(e.target as Node)) setAbierto(false);
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
            className="btn-secondary inline-flex items-center gap-1"
            aria-haspopup="menu"
            aria-expanded={abierto}
            aria-label={etiqueta ?? t("acciones.mas")}
            onClick={() => setAbierto((v) => !v)}
          >
            {t("acciones.mas")}
            <Icono nombre={abierto ? "expand_less" : "expand_more"} tamano="sm" />
          </button>
          {abierto ? (
            <div
              role="menu"
              aria-label={etiqueta ?? t("acciones.mas")}
              className="absolute left-0 z-20 mt-1 min-w-56 rounded-lg border border-ink-dim/40 bg-paper p-1 shadow-lg"
            >
              {normales.map((o) => (
                <button
                  key={o.clave}
                  type="button"
                  role="menuitem"
                  className="block w-full rounded px-3 py-1.5 text-left text-xs text-ink hover:bg-paper-light"
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
                  className="block w-full rounded px-3 py-1.5 text-left text-xs text-danger hover:bg-danger/10"
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
