/**
 * La cabecera de un listado, con la forma que tiene en Salesforce.
 *
 * Lo que había era un título de pantalla y, debajo, una tira de hasta trece
 * pestañas —«Cuentas · Planes de cuenta · Estado financiero · Cambios de
 * empresa · Contactos · Calidad del dato · Visitas · Mapa de personas ·
 * Derechos del interesado»— que en Explotación caía en dos filas. Trece
 * pestañas no son una navegación: son una lista puesta en horizontal, y hay
 * que leerlas todas para encontrar la que se usa.
 *
 * Lightning resuelve esto con **el objeto arriba en pequeño y la vista debajo
 * en grande, con un desplegable**: «Leads / Todos los leads abiertos ▾». Se
 * copia tal cual, porque la pregunta que contesta es la misma —¿qué estoy
 * mirando y qué más puedo mirar aquí?— y así ocupa una línea en vez de dos
 * filas.
 *
 * Tres cosas deliberadas:
 *
 * - **El desplegable dice cuántas hay.** Con la tira, el número de pestañas se
 *   veía; escondiéndolas habría que adivinarlo.
 * - **La papelera se queda fuera del desplegable**, a la derecha y con su
 *   icono: no es un sitio donde se trabaja, es donde se mira cuando algo
 *   falta, y mezclada entre las demás obliga a leerlas todas.
 * - **Con una sola pestaña no hay desplegable**: un control que sólo ofrece lo
 *   que ya estás viendo es ruido.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Icono } from "@/componentes/Icono";
import type { Recurso } from "@/lib/modulos";
import { cn } from "@/lib/utiles";

export function CabeceraDeLista({
  icono,
  color,
  modulo,
  recursos,
  activo,
  alElegir,
  acciones,
  trazabilidad,
  pegada = false,
}: {
  /** Símbolo de Material del grupo al que pertenece el módulo. */
  icono: string;
  /** El color del objeto, el de Salesforce. Sin él, el azul del acento. */
  color?: string | null;
  /** El módulo: va encima y en pequeño, como el objeto en Lightning. */
  modulo: string;
  /** Las pestañas del módulo, en su orden. */
  recursos: Recurso[];
  /** Índice de la que se está mirando. */
  activo: number;
  alElegir: (i: number) => void;
  /** Lo que se puede hacer aquí: dar de alta, exportar. */
  acciones?: ReactNode;
  /** El desplegable de trazabilidad, que va donde nadie lo pise. */
  trazabilidad?: ReactNode;
  /**
   * Pegada a lo que va debajo: sin margen, sin esquinas abajo y sin borde
   * inferior, para que la cabecera, la barra de herramientas y la tabla sean
   * **una sola tarjeta** y no tres flotando.
   *
   * Es como se ve una lista en Lightning, y la diferencia no es estética: tres
   * recuadros con dos huecos entre ellos se leen como tres cosas distintas, y
   * son la misma.
   */
  pegada?: boolean;
}) {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  const caja = useRef<HTMLDivElement>(null);
  const disparador = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!abierto) return;
    function alTeclear(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      setAbierto(false);
      // El foco vuelve al botón: si se queda en el aire, quien navega con
      // teclado tiene que recorrer la página entera para volver aquí.
      disparador.current?.focus();
    }
    function alPulsar(e: MouseEvent) {
      if (!caja.current?.contains(e.target as Node)) setAbierto(false);
    }
    document.addEventListener("keydown", alTeclear);
    document.addEventListener("mousedown", alPulsar);
    return () => {
      document.removeEventListener("keydown", alTeclear);
      document.removeEventListener("mousedown", alPulsar);
    };
  }, [abierto]);

  // La papelera y demás pestañas con icono viven fuera del desplegable.
  const normales = recursos.map((r, i) => ({ r, i })).filter(({ r }) => !r.icono);
  const conIcono = recursos.map((r, i) => ({ r, i })).filter(({ r }) => r.icono);
  const actual = recursos[activo];
  const hayQueElegir = normales.length > 1;

  return (
    <header className={cn("card px-4 py-3", pegada ? "mb-0 rounded-b-none border-b-0" : "mb-3")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          {/* El cuadrado con el color del objeto, relleno y con el símbolo en
              blanco: es como se ven en Lightning, y es lo que hace que una
              pestaña de Cuentas no se confunda con una de Casos. */}
          <span
            className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded text-white"
            style={{ backgroundColor: color ?? "rgb(var(--accent))" }}
          >
            <Icono nombre={icono} />
          </span>
          <div className="min-w-0" ref={caja}>
            {/* El nombre del módulo encima, **salvo cuando es el mismo que el
                de la vista**: «CUENTAS / Cuentas» es la misma palabra dos
                veces en dos tamaños, y lo que parece es un fallo. Pasa justo
                en los módulos que ya llevan el nombre de su objeto, que son
                los que más se abren. */}
            {modulo.toLowerCase() !== (actual?.nombre ?? "").toLowerCase() ? (
              <p className="truncate text-3xs font-semibold uppercase tracking-[0.055em] text-ink-faint">
                {modulo}
              </p>
            ) : null}
            {hayQueElegir ? (
              <div className="relative">
                <button
                  ref={disparador}
                  type="button"
                  aria-haspopup="listbox"
                  aria-expanded={abierto}
                  onClick={() => setAbierto((v) => !v)}
                  className="flex min-w-0 items-center gap-1 text-xl-em font-bold tracking-[-0.01em] text-ink hover:text-accent"
                >
                  <span className="truncate">{actual?.nombre ?? modulo}</span>
                  <Icono nombre={abierto ? "expand_less" : "expand_more"} tamano="sm" />
                </button>
                {abierto ? (
                  <ul
                    role="listbox"
                    aria-label={modulo}
                    className="absolute left-0 z-popover mt-1 max-h-80 min-w-64 overflow-y-auto rounded-xl border border-ink-dim/60 bg-paper p-1 shadow-elevation-3"
                  >
                    {normales.map(({ r, i }) => (
                      <li key={r.nombre}>
                        <button
                          type="button"
                          role="option"
                          aria-selected={i === activo}
                          onClick={() => {
                            alElegir(i);
                            setAbierto(false);
                          }}
                          className={cn(
                            "block w-full truncate rounded px-3 py-1.5 text-left text-xs",
                            i === activo
                              ? "bg-accent/10 font-semibold text-accent"
                              : "text-ink hover:bg-paper-light",
                          )}
                        >
                          {r.nombre}
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : (
              <h1 className="min-w-0 truncate text-xl-em font-bold tracking-[-0.01em] text-ink">
                {actual?.nombre ?? modulo}
              </h1>
            )}
            {/* Con desplegable el `<h1>` no puede ser el botón —un encabezado
                no se pulsa—, así que el título accesible va aparte y oculto.
                Sin esto la pantalla se queda sin encabezado de primer nivel y
                quien navega por encabezados no sabe dónde ha entrado. */}
            {hayQueElegir ? (
              <h1 className="sr-only">{`${modulo} — ${actual?.nombre ?? ""}`}</h1>
            ) : null}
            {hayQueElegir ? (
              <p className="mt-0.5 text-3xs text-ink-faint">
                {t("modulo.cuantasPestanas", { count: normales.length })}
              </p>
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {acciones}
          {conIcono.map(({ r, i }) => (
            <button
              key={r.nombre}
              type="button"
              onClick={() => alElegir(i)}
              aria-current={i === activo ? "page" : undefined}
              title={r.nombre}
              aria-label={r.nombre}
              className={cn(
                "btn-icon",
                i === activo ? "bg-accent/10 text-accent" : "text-ink-muted hover:bg-paper-light",
              )}
            >
              <Icono nombre={r.icono!} />
            </button>
          ))}
          {trazabilidad}
        </div>
      </div>
    </header>
  );
}
