/**
 * El lanzador: qué aplicaciones hay y qué hay dentro de cada una.
 *
 * Es la otra mitad de la barra de aplicación. Si arriba sólo están las
 * pestañas de una, tiene que haber un sitio donde se vean **todas**, o lo que
 * se ha hecho no es ordenar sino esconder.
 *
 * **No lleva buscador, a propósito.** La paleta de `⌘K` ya contesta «llévame a
 * X, sé cómo se llama». Esto contesta otra pregunta —«¿qué hay?»— y es la que
 * no tenía respuesta: con un menú de 59 entradas la única forma de saber qué
 * existe era leerlo entero. Dos buscadores idénticos en dos sitios distintos
 * sólo garantizan que uno de los dos se quede sin mantener, así que aquí se
 * nombra el atajo y no se repite la caja.
 */

import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Icono } from "@/componentes/Icono";
import { APLICACIONES, pestanasDe, type Aplicacion } from "@/lib/aplicaciones";
import type { AreaPintada } from "@/lib/navegacion";
import { cn } from "@/lib/utiles";

export function LanzadorDeAplicaciones({
  menu,
  actual,
  alElegirAplicacion,
  alCerrar,
}: {
  menu: AreaPintada[];
  actual: Aplicacion;
  alElegirAplicacion: (app: Aplicacion) => void;
  alCerrar: () => void;
}) {
  const { t } = useTranslation();
  const panel = useRef<HTMLDivElement>(null);
  const primero = useRef<HTMLButtonElement>(null);

  // Escape cierra y el foco entra en el panel: sin esto, quien navega con
  // teclado abre el lanzador y sigue tabulando por la página de detrás, que es
  // como no haberlo abierto.
  // Y pulsar fuera también cierra. Va escuchando en el documento y no con un
  // `onMouseDown` en el velo: un `div` con manejador de ratón y sin teclado es
  // un control que sólo existe para quien usa ratón, y el linter tiene razón
  // al no dejarlo pasar. Es el mismo patrón que `MenuDeAcciones`.
  useEffect(() => {
    primero.current?.focus();
    function alTeclear(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        alCerrar();
      }
    }
    function alPulsar(e: MouseEvent) {
      if (!panel.current?.contains(e.target as Node)) alCerrar();
    }
    document.addEventListener("keydown", alTeclear, true);
    document.addEventListener("mousedown", alPulsar);
    return () => {
      document.removeEventListener("keydown", alTeclear, true);
      document.removeEventListener("mousedown", alPulsar);
    };
  }, [alCerrar]);

  return (
    <div className="fixed inset-0 z-popover bg-ink/20">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={t("app.lanzador")}
        className="mx-auto mt-16 max-h-[78vh] w-[min(56rem,calc(100vw-2rem))] overflow-y-auto rounded-xl border border-ink-dim/60 bg-paper p-5 shadow-elevation-4"
      >
        <div className="mb-4 flex items-baseline justify-between gap-4">
          <h2 className="text-grande font-bold text-ink">
            {t("app.lanzador")}
          </h2>
          <p className="text-dato text-ink-faint">{t("app.lanzadorAtajo")}</p>
        </div>

        {/* Las aplicaciones, como rejilla: son cuatro y se eligen de un
            vistazo. Una lista vertical de cuatro cosas gasta la pantalla y no
            se lee más rápido. */}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {APLICACIONES.map((app, i) => (
            <button
              key={app.id}
              ref={i === 0 ? primero : undefined}
              type="button"
              onClick={() => alElegirAplicacion(app)}
              aria-current={app.id === actual.id ? "true" : undefined}
              className={cn(
                "flex flex-col items-start gap-2 rounded-lg border p-3 text-left transition-colors",
                app.id === actual.id
                  ? "border-accent bg-accent/5"
                  : "border-ink-dim/60 hover:border-ink-dim hover:bg-paper-light",
              )}
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-md bg-accent/10 text-accent">
                <Icono nombre={app.icono} />
              </span>
              <span className="text-titulo font-semibold text-ink">
                {t(app.clave)}
              </span>
              <span className="text-dato text-ink-faint">
                {t("app.cuantasPestanas", {
                  count: pestanasDe(app, menu).length,
                })}
              </span>
            </button>
          ))}
        </div>

        {/* Y lo que hay dentro, para poder ir directo sin pasar por la
            aplicación. Es lo que hacía el menú lateral entero, pero aquí está
            agrupado por aplicación y sólo cuando se pide. */}
        <h3 className="mb-2 mt-6 text-rotulo font-semibold uppercase tracking-wide text-ink-faint">
          {t("app.todoLoQueHay")}
        </h3>
        <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">
          {APLICACIONES.map((app) => (
            <div key={app.id}>
              <p className="mb-1.5 text-dato font-semibold text-ink-muted">
                {t(app.clave)}
              </p>
              <ul className="flex flex-col">
                {pestanasDe(app, menu).map((e) => (
                  <li key={e.a}>
                    <Link
                      to={e.a}
                      onClick={alCerrar}
                      className="block truncate rounded px-1.5 py-1 text-titulin text-ink-muted hover:bg-paper-light hover:text-ink"
                      title={t(e.clave)}
                    >
                      {t(e.clave)}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
