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
 * Lightning reparte eso en **dos niveles, y cada uno contesta una pregunta
 * distinta**:
 *
 * - Arriba, pequeño: **qué objeto** estoy mirando. Aquí es el recurso del
 *   módulo —Cuentas, Contactos, Visitas—, y se elige en un desplegable
 *   discreto porque se cambia de tarde en tarde.
 * - Debajo, grande: **qué vista** de ese objeto. Es el recorte con nombre que
 *   se abre cada día, y por eso es lo que manda en la pantalla.
 *
 * Sin vistas guardadas, la grande dice «Todo», que es exactamente lo que
 * había antes: el listado completo, sin tener que elegir nada.
 *
 * Tres cosas deliberadas:
 *
 * - **El desplegable del objeto dice cuántos hay.** Con la tira, el número se
 *   veía; escondiéndolos habría que adivinarlo.
 * - **La papelera se queda fuera**, a la derecha y con su icono: no es un
 *   sitio donde se trabaja, es donde se mira cuando algo falta, y mezclada
 *   entre las demás obliga a leerlas todas.
 * - **Con un solo objeto no hay desplegable de objeto**: un control que sólo
 *   ofrece lo que ya estás viendo es ruido.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Icono } from "@/componentes/Icono";
import type { Recurso } from "@/lib/modulos";
import { cn } from "@/lib/utiles";
import type { VistaDeLista } from "@/lib/vistasDeLista";

/**
 * Un desplegable con su cierre: Escape, pulsar fuera, y el foco de vuelta.
 *
 * Está aquí dentro y no en un componente del sistema porque la cabecera tiene
 * DOS y son el mismo control con distinto tamaño. Dos copias del mismo
 * comportamiento de cierre se separan a la primera corrección.
 */
function Desplegable({
  etiqueta,
  rotulo,
  grande,
  children,
}: {
  etiqueta: string;
  rotulo: ReactNode;
  grande?: boolean;
  /** Recibe el cierre, para poder llamarlo al elegir. */
  children: (cerrar: () => void) => ReactNode;
}) {
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

  return (
    <div className="relative min-w-0" ref={caja}>
      <button
        ref={disparador}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={abierto}
        aria-label={etiqueta}
        onClick={() => setAbierto((v) => !v)}
        className={cn(
          "flex min-w-0 items-center gap-1",
          grande
            ? "text-pagina font-bold tracking-[-0.01em] text-ink hover:text-accent"
            : "text-rotulo font-semibold uppercase tracking-[0.055em] text-ink-faint hover:text-ink",
        )}
      >
        <span className="truncate">{rotulo}</span>
        <Icono nombre={abierto ? "expand_less" : "expand_more"} tamano="sm" />
      </button>
      {abierto ? (
        <ul
          role="listbox"
          aria-label={etiqueta}
          className="absolute left-0 z-popover mt-1 max-h-80 min-w-64 overflow-y-auto rounded-xl border border-ink-dim/60 bg-paper p-1 shadow-elevation-3"
        >
          {children(() => setAbierto(false))}
        </ul>
      ) : null}
    </div>
  );
}

function Opcion({
  activa,
  onClick,
  children,
  tono,
}: {
  activa?: boolean;
  onClick: () => void;
  children: ReactNode;
  tono?: "accion";
}) {
  return (
    <li>
      <button
        type="button"
        role="option"
        aria-selected={Boolean(activa)}
        onClick={onClick}
        className={cn(
          "block w-full truncate rounded px-3 py-1.5 text-left text-titulin",
          activa
            ? "bg-accent/10 font-semibold text-accent"
            : tono === "accion"
              ? "text-accent hover:bg-paper-light"
              : "text-ink hover:bg-paper-light",
        )}
      >
        {children}
      </button>
    </li>
  );
}

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
  vistas = [],
  vistaActiva = null,
  alElegirVista,
  alGuardarVista,
  alBorrarVista,
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
   */
  pegada?: boolean;
  /** Las vistas guardadas de este listado. Sin ellas, sólo sale «Todo». */
  vistas?: VistaDeLista[];
  vistaActiva?: VistaDeLista | null;
  alElegirVista?: (vista: VistaDeLista | null) => void;
  /** Guardar lo que hay en pantalla como una vista nueva. */
  alGuardarVista?: () => void;
  alBorrarVista?: (vista: VistaDeLista) => void;
}) {
  const { t } = useTranslation();

  // La papelera y demás pestañas con icono viven fuera del desplegable, y las
  // de primer nivel (`fija`) también, con su nombre.
  const normales = recursos
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => !r.icono && !r.fija);
  const fijas = recursos
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => r.fija && !r.icono);
  const conIcono = recursos
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => r.icono);
  const actual = recursos[activo];
  const hayQueElegirObjeto = normales.length > 1;
  const hayVistas = Boolean(alElegirVista);
  const nombreDeLaVista = vistaActiva?.nombre ?? t("vistas.todo");

  // El rótulo pequeño: el objeto. Cuando el módulo se llama igual que su
  // recurso —«Cuentas y contactos» / «Cuentas»— se dice una sola vez: la misma
  // palabra dos veces en dos tamaños parece un fallo.
  const mismoNombre =
    modulo.toLowerCase() === (actual?.nombre ?? "").toLowerCase();
  const rotuloDelObjeto = mismoNombre
    ? modulo
    : `${modulo} · ${actual?.nombre ?? ""}`;

  return (
    <header
      className={cn(
        "card px-4 py-3",
        pegada ? "mb-0 rounded-b-none border-b-0" : "mb-3",
      )}
    >
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
          <div className="min-w-0">
            {/* Arriba, QUÉ OBJETO. Desplegable sólo si hay más de uno. */}
            {hayQueElegirObjeto ? (
              <Desplegable
                etiqueta={t("vistas.queObjeto")}
                rotulo={rotuloDelObjeto}
              >
                {(cerrar) => (
                  <>
                    {normales.map(({ r, i }) => (
                      <Opcion
                        key={r.nombre}
                        activa={i === activo}
                        onClick={() => {
                          alElegir(i);
                          cerrar();
                        }}
                      >
                        {r.nombre}
                      </Opcion>
                    ))}
                  </>
                )}
              </Desplegable>
            ) : (
              <p className="truncate text-rotulo font-semibold uppercase tracking-[0.055em] text-ink-faint">
                {rotuloDelObjeto}
              </p>
            )}

            {/* Debajo, QUÉ VISTA. Es lo grande porque es lo que se cambia
                cada día. Sin vistas guardadas dice «Todo», que es el listado
                completo: lo que había antes de que esto existiera. */}
            {hayVistas ? (
              <Desplegable
                etiqueta={t("vistas.queVista")}
                rotulo={nombreDeLaVista}
                grande
              >
                {(cerrar) => (
                  <>
                    <Opcion
                      activa={!vistaActiva}
                      onClick={() => {
                        alElegirVista?.(null);
                        cerrar();
                      }}
                    >
                      {t("vistas.todo")}
                    </Opcion>
                    {vistas.map((v) => (
                      <Opcion
                        key={v.id}
                        activa={v.id === vistaActiva?.id}
                        onClick={() => {
                          alElegirVista?.(v);
                          cerrar();
                        }}
                      >
                        {v.nombre}
                        {/* Quién la ve. Sin esto, borrar una compartida
                            creyéndola propia deja a todo el equipo sin su
                            listado de cada día. */}
                        {v.compartida ? (
                          <span className="ml-2 text-rotulo text-ink-faint">
                            {t("vistas.deTodos")}
                          </span>
                        ) : null}
                      </Opcion>
                    ))}
                    <li>
                      <hr className="my-1 border-ink-dim/40" />
                    </li>
                    <Opcion
                      tono="accion"
                      onClick={() => {
                        alGuardarVista?.();
                        cerrar();
                      }}
                    >
                      {t("vistas.guardarComo")}
                    </Opcion>
                    {vistaActiva && alBorrarVista ? (
                      <Opcion
                        tono="accion"
                        onClick={() => {
                          alBorrarVista(vistaActiva);
                          cerrar();
                        }}
                      >
                        {t("vistas.borrarEsta", { nombre: vistaActiva.nombre })}
                      </Opcion>
                    ) : null}
                  </>
                )}
              </Desplegable>
            ) : (
              <h1 className="min-w-0 truncate text-pagina font-bold tracking-[-0.01em] text-ink">
                {actual?.nombre ?? modulo}
              </h1>
            )}

            {/* Con desplegable el `<h1>` no puede ser el botón —un encabezado
                no se pulsa—, así que el título accesible va aparte y oculto.
                Sin esto la pantalla se queda sin encabezado de primer nivel y
                quien navega por encabezados no sabe dónde ha entrado. */}
            {hayVistas ? (
              <h1 className="sr-only">{`${rotuloDelObjeto} — ${nombreDeLaVista}`}</h1>
            ) : null}
            {hayQueElegirObjeto ? (
              <p className="mt-0.5 text-rotulo text-ink-faint">
                {t("modulo.cuantasPestanas", { count: normales.length })}
              </p>
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {acciones}
          {fijas.map(({ r, i }) => (
            <button
              key={r.nombre}
              type="button"
              onClick={() => alElegir(i)}
              aria-current={i === activo ? "page" : undefined}
              className={cn(
                "btn-ghost",
                i === activo ? "bg-accent/10 text-accent" : undefined,
              )}
            >
              {r.nombre}
            </button>
          ))}
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
                i === activo
                  ? "bg-accent/10 text-accent"
                  : "text-ink-muted hover:bg-paper-light",
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
