/**
 * La misma lista, vista como hace falta verla (CRM-07.04.01.09).
 *
 * Una tabla lo enseña todo y no destaca nada: catorce columnas de texto del
 * mismo tamaño, y quien la mira tiene que leerlas todas para encontrar el dato
 * por el que ha entrado. Para revisar cien filas es lo correcto; para trabajar
 * el día a día —¿cuánto hay en cada etapa?, ¿cuál es grande?, ¿de quién es?—
 * no lo es, y era la única vista que había.
 *
 * Se añaden dos, y las dos salen **de los propios datos**, no de una
 * configuración por recurso: una configuración por recurso significa que los
 * veinte que nadie configure se queden con la tabla para siempre.
 *
 *   * **Tarjetas**: un registro por tarjeta, con su nombre grande y sus cuatro
 *     datos debajo. Es lo que convierte una lista en algo que se ojea.
 *   * **Agrupado**: columnas por el campo que separa el trabajo —estado, etapa,
 *     prioridad—, con cuántos hay en cada una y cuánto suman. Es la pregunta
 *     que se hace de verdad delante de una lista de oportunidades o de casos.
 *
 * La vista elegida **se recuerda por recurso**: quien trabaja el embudo en
 * columnas no quiere volver a la tabla cada mañana.
 */

import { useMemo } from "react";
import { Link } from "react-router-dom";

import { Icono } from "@/componentes/Icono";
import { Celda } from "@/componentes/Tabla";
import { inicialesDe, nombreDe, usePersonas, type Persona } from "@/lib/personas";
import {
  CAMPOS_DE_CIFRA,
  CAMPOS_DE_ESTADO,
  clasesDeTono,
  retrasoDe,
  tonoDe,
} from "@/lib/semaforo";
import { escalar, esIdentificadorTecnico, humanizar, nombreDelRegistro, tieneDato } from "@/lib/formato";
import { cn } from "@/lib/utiles";

export type Vista = "tabla" | "tarjetas" | "agrupado";

const CLAVE = "contecrm.vista";

/** Campos por los que agrupar tiene sentido, en orden de preferencia. */
const AGRUPABLES = [
  "etapa",
  "estado",
  "prioridad",
  "tipo",
  "categoria",
  "severidad",
  "nivel",
  "canal",
  "audiencia",
  "objeto",
];

/** Campos cuya suma dice algo. Sumar «probabilidad» no dice nada. */
const SUMABLES = /^(importe|total|importe_ponderado|presupuesto|asignado|coste|cantidad)/;

export function leerVista(recuerdaComo: string): Vista {
  try {
    const guardado = JSON.parse(localStorage.getItem(CLAVE) ?? "{}") as Record<string, Vista>;
    const vista = guardado[recuerdaComo];
    return vista === "tarjetas" || vista === "agrupado" ? vista : "tabla";
  } catch {
    // Puede fallar en navegación privada o con el almacenamiento bloqueado: se
    // vuelve a la tabla, que es lo que había antes de que esto existiera.
    return "tabla";
  }
}

function recordarVista(recuerdaComo: string, vista: Vista): void {
  try {
    const guardado = JSON.parse(localStorage.getItem(CLAVE) ?? "{}") as Record<string, Vista>;
    localStorage.setItem(CLAVE, JSON.stringify({ ...guardado, [recuerdaComo]: vista }));
  } catch {
    // Que no se recuerde no impide trabajar.
  }
}

/** Por qué campo agrupar estas filas, o cadena vacía si por ninguno. */
export function campoDeAgrupacion(filas: Record<string, unknown>[]): string {
  if (filas.length === 0) return "";
  const claves = new Set<string>();
  for (const fila of filas) for (const c of Object.keys(fila)) claves.add(c);
  for (const candidato of AGRUPABLES) {
    if (!claves.has(candidato)) continue;
    const valores = new Set(filas.map((f) => String(f[candidato] ?? "")));
    // Con un solo valor no hay nada que separar, y con tantos como filas
    // tampoco: serían columnas de una fila cada una.
    if (valores.size > 1 && valores.size <= Math.max(2, filas.length / 2)) return candidato;
  }
  return "";
}

export function SelectorVista({
  vista,
  alCambiar,
  recuerdaComo,
  puedeAgrupar,
}: {
  vista: Vista;
  alCambiar: (v: Vista) => void;
  recuerdaComo: string;
  puedeAgrupar: boolean;
}) {
  const opciones: { clave: Vista; icono: string; titulo: string }[] = [
    { clave: "tabla", icono: "table_rows", titulo: "Tabla" },
    { clave: "tarjetas", icono: "grid_view", titulo: "Tarjetas" },
    ...(puedeAgrupar
      ? [{ clave: "agrupado" as Vista, icono: "view_kanban", titulo: "Por columnas" }]
      : []),
  ];
  return (
    <div className="flex items-center gap-0.5 rounded-xl border border-line p-0.5" role="group">
      {opciones.map((o) => (
        <button
          key={o.clave}
          type="button"
          title={o.titulo}
          aria-label={o.titulo}
          aria-pressed={vista === o.clave}
          onClick={() => {
            alCambiar(o.clave);
            recordarVista(recuerdaComo, o.clave);
          }}
          className={cn(
            "rounded-lg px-2 py-1 text-xs",
            vista === o.clave ? "bg-paper-light text-ink" : "text-ink-muted hover:bg-paper-light",
          )}
        >
          <Icono nombre={o.icono} />
        </button>
      ))}
    </div>
  );
}

/**
 * El título de una tarjeta.
 *
 * Una fila de un solo campo —los motivos de pérdida son una lista de textos—
 * es su propio título: pintarla como «Valor: sin_presupuesto» añade una
 * etiqueta que no dice nada y esconde lo único que importa.
 */
function tituloDe(fila: Record<string, unknown>): string {
  const claves = Object.keys(fila);
  if (claves.length === 1) return humanizar(String(fila[claves[0] as string] ?? ""));
  return nombreDelRegistro(fila);
}

/** Los campos que se enseñan en una tarjeta: los útiles, sin el título. */
function camposDeTarjeta(
  filas: Record<string, unknown>[],
  columnas: string[] | undefined,
  titulo: string,
): string[] {
  const claves =
    columnas ??
    [...new Set(filas.flatMap((f) => Object.keys(f)))].filter((c) => !esIdentificadorTecnico(c));
  return claves.filter((c) => c !== titulo && filas.some((f) => tieneDato(f[c]))).slice(0, 5);
}

/**
 * Un listado de un solo campo no son registros: es un vocabulario.
 *
 * «Motivos de pérdida admitidos» son nueve palabras. Pintarlas como tabla da
 * nueve filas de una columna; como tarjetas, nueve recuadros con una palabra
 * dentro. Las dos cosas ocupan la pantalla entera para decir nueve palabras.
 * Como etiquetas se leen de un vistazo, que es para lo que se abre esa
 * pantalla.
 */
export function esVocabulario(filas: Record<string, unknown>[]): boolean {
  return filas.length > 0 && filas.every((f) => Object.keys(f).length === 1);
}

export function Etiquetas({ filas }: { filas: Record<string, unknown>[] }) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {filas.map((fila, i) => (
        <li
          key={i}
          className="rounded-lg border border-line bg-paper-sunk px-2.5 py-1 text-xs text-ink"
        >
          {tituloDe(fila)}
        </li>
      ))}
    </ul>
  );
}

/**
 * Una tarjeta que se lee de un vistazo.
 *
 * Una tabla lo enseña todo con el mismo peso: catorce columnas de texto del
 * mismo tamaño donde hay que leerlas todas para encontrar el dato por el que se
 * ha entrado. Una tarjeta decide qué manda, y en un CRM eso es siempre lo
 * mismo: **cuánto, de quién, en qué estado y si va con retraso.**
 *
 * Todo sale de los datos, no de una configuración por recurso: configurarlo
 * recurso a recurso significa que los veinte que nadie configure se queden con
 * la tarjeta sosa para siempre.
 *
 *   * **La cifra va grande** y arriba. Un importe perdido entre catorce campos
 *     del mismo tamaño no distingue una oportunidad de doce mil euros de una de
 *     doce millones, que es lo primero que se mira.
 *   * **El estado va en color**, y el color significa lo mismo en todas las
 *     pantallas (`lib/semaforo.ts`). Con un color por valor sacado de un hash,
 *     «perdida» sale verde aquí y morada allá, y el color deja de leerse.
 *   * **El retraso se canta.** Es lo que más urge y lo que una tabla esconde
 *     entre columnas: aquí va arriba y en rojo.
 *   * **El responsable, con su cara.** Un `owner_id` en UUID no dice de quién
 *     es nada, y «de quién es esto» es la segunda pregunta de cualquier lista.
 */
function Tarjeta({
  fila,
  campos,
  personas,
  compacta = false,
}: {
  fila: Record<string, unknown>;
  campos: string[];
  personas: Record<string, Persona>;
  compacta?: boolean;
}) {
  const retraso = retrasoDe(fila);
  const cifra = campos.find((c) => CAMPOS_DE_CIFRA.test(c) && tieneDato(fila[c]));
  const estados = campos.filter((c) => CAMPOS_DE_ESTADO.includes(c) && tieneDato(fila[c]));
  const responsable = ["owner_id", "asignado_a", "responsable_id", "autor_id", "propietario_id"]
    .filter((c) => tieneDato(fila[c]))
    .at(0);
  // Lo que queda: ni la cifra, ni los estados, ni el responsable, ni el título.
  const resto = campos.filter(
    (c) => c !== cifra && c !== responsable && !estados.includes(c) && !esIdentificadorTecnico(c),
  );

  return (
    <>
      {retraso ? (
        <p className="mb-1 flex items-center gap-1 text-3xs font-medium text-danger">
          <Icono nombre="schedule" /> {humanizar(retraso)}
        </p>
      ) : null}

      <p className={cn("font-medium text-ink", compacta ? "text-xs" : "text-sm")}>
        {tituloDe(fila)}
      </p>

      {cifra ? (
        <p className="mt-1 text-lg font-semibold leading-none text-ink">
          {escalar(fila[cifra], cifra)}
        </p>
      ) : null}

      {estados.length > 0 ? (
        <ul className="mt-2 flex flex-wrap gap-1">
          {estados.map((c) => (
            <li
              key={c}
              title={humanizar(c)}
              className={cn(
                "rounded-lg border px-1.5 py-0.5 text-3xs",
                clasesDeTono(tonoDe(fila[c])),
              )}
            >
              {humanizar(String(fila[c]))}
            </li>
          ))}
        </ul>
      ) : null}

      {resto.length > 0 ? (
        <dl className="mt-2 space-y-0.5">
          {resto.slice(0, compacta ? 2 : 4).map((c) => (
            <div key={c} className="flex items-baseline justify-between gap-3">
              <dt className="text-3xs text-ink-faint">{humanizar(c)}</dt>
              <dd className="min-w-0 text-right text-3xs text-ink-muted">
                <Celda valor={fila[c]} campo={c} />
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      {responsable ? (
        <p className="mt-2 flex items-center gap-1.5 text-3xs text-ink-muted">
          <span
            aria-hidden
            className="grid h-5 w-5 place-items-center rounded-full bg-paper-sunk text-[0.6rem] font-medium text-ink-muted"
          >
            {inicialesDe(nombreDe(personas, fila[responsable]))}
          </span>
          {nombreDe(personas, fila[responsable])}
        </p>
      ) : null}
    </>
  );
}

export function Tarjetas({
  filas,
  columnas,
  enlace,
}: {
  filas: Record<string, unknown>[];
  columnas?: string[];
  enlace?: (fila: Record<string, unknown>) => string | null;
}) {
  const campos = useMemo(() => camposDeTarjeta(filas, columnas, "nombre"), [filas, columnas]);
  const personas = usePersonas();
  return (
    <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {filas.map((fila, i) => {
        const a = enlace?.(fila) ?? null;
        const cuerpo = <Tarjeta fila={fila} campos={campos} personas={personas} />;
        return (
          <li key={String(fila.id ?? i)}>
            {a ? (
              <Link
                to={a}
                className="block rounded-xl border border-line bg-paper p-3 hover:border-accent"
              >
                {cuerpo}
              </Link>
            ) : (
              <div className="rounded-xl border border-line bg-paper p-3">{cuerpo}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function Agrupado({
  filas,
  campo,
  columnas,
  enlace,
}: {
  filas: Record<string, unknown>[];
  campo: string;
  columnas?: string[];
  enlace?: (fila: Record<string, unknown>) => string | null;
}) {
  const campos = useMemo(() => camposDeTarjeta(filas, columnas, "nombre"), [filas, columnas]);
  const personas = usePersonas();
  const sumable = useMemo(
    () => campos.find((c) => SUMABLES.test(c) && filas.some((f) => Number(f[c]) > 0)) ?? "",
    [campos, filas],
  );

  const grupos = useMemo(() => {
    const mapa = new Map<string, Record<string, unknown>[]>();
    for (const fila of filas) {
      const clave = String(fila[campo] ?? "—");
      mapa.set(clave, [...(mapa.get(clave) ?? []), fila]);
    }
    return [...mapa.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [filas, campo]);

  const mayor = Math.max(...grupos.map(([, f]) => f.length), 1);

  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
      {grupos.map(([clave, suyas]) => {
        const suma = sumable ? suyas.reduce((t, f) => t + (Number(f[sumable]) || 0), 0) : 0;
        return (
          <section key={clave} className="w-72 shrink-0">
            <header className="mb-2">
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="truncate text-xs font-medium text-ink">{humanizar(clave)}</h3>
                <span className="text-3xs text-ink-faint">{suyas.length}</span>
              </div>
              {/* La barra dice de un vistazo dónde se acumula el trabajo, que es
                  lo que un número solo no enseña hasta que se comparan todos. */}
              <div className="mt-1 h-1 rounded-full bg-paper-sunk">
                <div
                  className="h-1 rounded-full bg-accent"
                  style={{ width: `${Math.round((suyas.length / mayor) * 100)}%` }}
                />
              </div>
              {sumable ? (
                <p className="mt-1 text-3xs text-ink-faint">
                  {humanizar(sumable)}: {escalar(suma, sumable)}
                </p>
              ) : null}
            </header>
            <ul className="space-y-2">
              {suyas.map((fila, i) => {
                const a = enlace?.(fila) ?? null;
                const cuerpo = (
                  <Tarjeta
                    fila={fila}
                    // Sin la columna por la que se agrupa: repetir «Cualificación»
                    // en las doce tarjetas de la columna «Cualificación» no dice
                    // nada y ocupa la línea que sí diría algo.
                    campos={campos.filter((c) => c !== campo)}
                    personas={personas}
                    compacta
                  />
                );
                return (
                  <li key={String(fila.id ?? i)}>
                    {a ? (
                      <Link
                        to={a}
                        className="block rounded-xl border border-line bg-paper p-2.5 hover:border-accent"
                      >
                        {cuerpo}
                      </Link>
                    ) : (
                      <div className="rounded-xl border border-line bg-paper p-2.5">{cuerpo}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

export { recordarVista };
