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

import { useCallback, useMemo, useRef, useState } from "react";
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
import {
  campoDelNombre,
  escalar,
  esIdentificadorTecnico,
  humanizar,
  nombreDelRegistro,
  tieneDato,
} from "@/lib/formato";
import { ErrorApi } from "@/lib/api";
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

/**
 * La vista que este usuario eligió para este recurso, o `null` si nunca eligió.
 *
 * Devuelve `null` y no «tabla» a propósito: hay que poder distinguir «quiso
 * tabla» de «no ha dicho nada», porque lo segundo lo decide `vistaPorDefecto`.
 * Mientras devolvía «tabla» para las dos cosas, el valor por defecto no se
 * podía cambiar sin pisar la elección de quien sí había elegido.
 */
export function vistaRecordada(recuerdaComo: string): Vista | null {
  try {
    const guardado = JSON.parse(localStorage.getItem(CLAVE) ?? "{}") as Record<string, Vista>;
    const vista = guardado[recuerdaComo];
    return vista === "tabla" || vista === "tarjetas" || vista === "agrupado" ? vista : null;
  } catch {
    // Puede fallar en navegación privada o con el almacenamiento bloqueado.
    return null;
  }
}

/**
 * Con qué vista se abre un listado que nadie ha configurado: **tarjetas**.
 *
 * Una tabla enseña catorce columnas del mismo tamaño y no destaca ninguna:
 * quien entra tiene que leerlas todas para encontrar el dato por el que ha
 * venido. Una tarjeta lleva delante el nombre del registro y debajo sus cuatro
 * datos, y eso es lo que convierte una lista en algo que se ojea. Por eso las
 * tarjetas son la vista por defecto en todas partes.
 *
 * La excepción, y sale de los datos y no de una lista escrita a mano —una
 * lista de los recursos que SÍ pueden se queda corta el día que se añade el
 * número veintiséis—: **si el registro no tiene nada que poner de titular**, la
 * tarjeta queda siendo una caja con un identificador dentro, que se lee peor
 * que una fila. Pasa con lo que es puro registro técnico: apuntes de auditoría,
 * eventos, consumos. Ahí se abre en tabla.
 */
export function vistaPorDefecto(filas: Record<string, unknown>[]): Vista {
  if (filas.length === 0) return "tarjetas";
  const conTitular = filas.filter((f) => nombreDelRegistro(f).trim()).length;
  // La mayoría, no todas: en un listado de contactos puede haber uno sin
  // nombre, y eso no convierte al resto en una tabla.
  return conTitular * 2 >= filas.length ? "tarjetas" : "tabla";
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
    <div className="flex items-center gap-0.5 rounded-xl border border-ink-dim/60 p-0.5" role="group">
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

/**
 * Los campos que se enseñan en una tarjeta: los útiles, **sin el título**.
 *
 * Cuál es el título no es un nombre escrito aquí: lo dice `campoDelNombre`,
 * que es quien lo eligió. Antes esta función recibía la cadena `"nombre"` a
 * mano desde sus dos llamadas, así que sólo se excluía ese campo: la tarjeta
 * de un caso —que se titula por `asunto`— repetía su propio título debajo y
 * recortado, y lo mismo con `titulo`, `razon_social`, `clave`, `codigo`,
 * `email`, `slug` y `nombre_completo`.
 *
 * Se mira fila a fila porque un listado puede mezclar: en una lista de
 * contactos unos traen `nombre_completo` y otros sólo `email`.
 */
function camposDeTarjeta(
  filas: Record<string, unknown>[],
  columnas: string[] | undefined,
): string[] {
  const titulares = new Set(filas.map((f) => campoDelNombre(f)).filter(Boolean));
  const claves =
    columnas ??
    [...new Set(filas.flatMap((f) => Object.keys(f)))].filter((c) => !esIdentificadorTecnico(c));
  return claves.filter((c) => !titulares.has(c) && filas.some((f) => tieneDato(f[c]))).slice(0, 5);
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
          className="rounded-lg border border-ink-dim/60 bg-paper-sunk px-2.5 py-1 text-xs text-ink"
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

      {/* Abajo del todo: con `mt-auto` el responsable se pega al borde
          inferior, así que en una fila de tarjetas los avatares quedan
          alineados entre sí en vez de a distinta altura cada uno. En la
          variante compacta, que no es flex, `mt-auto` no hace nada. */}
      {responsable ? (
        <p className="mt-auto flex items-center gap-1.5 pt-2 text-3xs text-ink-muted">
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
  const campos = useMemo(() => camposDeTarjeta(filas, columnas), [filas, columnas]);
  const personas = usePersonas();
  return (
    // Todas las tarjetas del mismo alto, y el de la mayor **de la rejilla
    // entera**, no el de su fila. Hacen falta las tres cosas y por separado:
    //
    //   · `auto-rows-fr` reparte el alto entre TODAS las filas por igual, así
    //     que una fila sin responsables no sale más baja que la de debajo;
    //   · `items-stretch` estira cada celda al alto de su fila;
    //   · y `h-full` hasta la propia tarjeta, porque si no se estira la celda
    //     y la tarjeta de dentro se queda con su alto.
    //
    // Con sólo las dos últimas quedaban iguales por fila y distintas entre
    // filas, que es como se vio la segunda vez. No es estética: un borde que
    // no cuadra con el de al lado se lee como que a esa ficha le falta algo, y
    // lo que le falta es un dato que puede estar vacío a propósito.
    <ul className="grid auto-rows-fr items-stretch gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {filas.map((fila, i) => {
        const a = enlace?.(fila) ?? null;
        const cuerpo = <Tarjeta fila={fila} campos={campos} personas={personas} />;
        return (
          <li key={String(fila.id ?? i)} className="h-full">
            {a ? (
              <Link
                to={a}
                className="flex h-full flex-col rounded-xl border border-ink-dim/60 bg-paper p-3 hover:border-accent"
              >
                {cuerpo}
              </Link>
            ) : (
              <div className="flex h-full flex-col rounded-xl border border-ink-dim/60 bg-paper p-3">
                {cuerpo}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Las columnas, con el registro moviéndose de una a otra.
 *
 * Un tablero en el que no se puede mover nada es una tabla girada: obliga a
 * abrir la ficha, buscar el campo y guardarlo para hacer lo que la propia
 * forma del tablero está prometiendo con sólo existir. Arrastrar **es** la
 * acción, y por eso va aquí y no en una pantalla concreta: donde haya columnas
 * se arrastra, sin que nadie tenga que acordarse de enchufarlo.
 *
 * **Sólo si se puede guardar.** `mover` llega desde fuera y sólo llega cuando
 * el contrato admite cambiar ese campo de ese registro. Sin él no se marca
 * nada como arrastrable: un tablero que deja coger una tarjeta y la devuelve a
 * su sitio sin decir por qué se lee como que la aplicación falla.
 *
 * **Y con teclado.** Arrastrar con el ratón no es una forma de hacer algo: es
 * una de las formas. Con la tarjeta enfocada, `Ctrl`/`Cmd` + flecha la mueve a
 * la columna de al lado, y el resultado se canta en una región viva — sin eso,
 * quien no ve la pantalla no se entera de que ha pasado nada.
 */
/**
 * La columna de los que no tienen valor no es un valor.
 *
 * Soltar ahí escribiría el guion como si fuera el estado del registro, y
 * entonces «—» pasaría a existir de verdad en los datos. Vaciar un campo es
 * una decisión que se toma en la ficha, con su campo delante.
 */
const SIN_COLUMNA = "Esa columna agrupa lo que no tiene valor: no se puede mover ahí";

/**
 * Por qué no se movió, con la frase del servidor.
 *
 * «Algo ha ido mal» hace que se intente otra vez igual. «Una oportunidad
 * perdida no vuelve a negociación» dice qué hacer.
 */
function porQueNoSeMovio(error: unknown): string {
  if (error instanceof ErrorApi) return error.explicacion || error.titulo;
  return error instanceof Error ? error.message : String(error);
}

export function Agrupado({
  filas,
  campo,
  columnas,
  enlace,
  mover,
}: {
  filas: Record<string, unknown>[];
  campo: string;
  columnas?: string[];
  enlace?: (fila: Record<string, unknown>) => string | null;
  /** Guarda el nuevo valor del campo de agrupación. Ausente: no se arrastra. */
  mover?: (fila: Record<string, unknown>, valor: string) => Promise<void>;
}) {
  const campos = useMemo(() => camposDeTarjeta(filas, columnas), [filas, columnas]);
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
  const claves = useMemo(() => grupos.map(([c]) => c), [grupos]);

  // Lo que se está arrastrando, por su identificador. En una `ref` y no en el
  // estado: cambiarlo redibuja el tablero entero a mitad del arrastre y el
  // navegador cancela el gesto.
  const arrastrando = useRef<Record<string, unknown> | null>(null);
  const [encima, setEncima] = useState<string | null>(null);
  // Lo que se canta. Una tarjeta que cambia de sitio sin decirlo deja a quien
  // no mira la pantalla sin saber si se ha movido, si ha fallado o si no pasó
  // nada.
  const [dicho, setDicho] = useState("");

  const llevar = useCallback(
    async (fila: Record<string, unknown> | null, destino: string) => {
      if (!mover || !fila || String(fila[campo] ?? "—") === destino) return;
      // «—» es la columna de los que no tienen valor, no un valor: soltar ahí
      // escribiría el guion como si fuera el estado del registro.
      if (destino === "—") {
        setDicho(SIN_COLUMNA);
        return;
      }
      try {
        await mover(fila, destino);
        setDicho(`${nombreDelRegistro(fila)} → ${humanizar(destino)}`);
      } catch (error) {
        // El motivo del servidor, no «algo ha ido mal»: una transición que el
        // negocio no admite es la respuesta útil, y esconderla hace que se
        // intente otra vez igual.
        setDicho(`${nombreDelRegistro(fila)}: ${porQueNoSeMovio(error)}`);
      }
    },
    [mover, campo],
  );

  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
      {/* La región viva va fuera de las columnas y siempre montada: si
          apareciera al mover, el lector no la estaría observando todavía. */}
      <p role="status" aria-live="polite" className="sr-only">
        {dicho}
      </p>
      {grupos.map(([clave, suyas]) => {
        const suma = sumable ? suyas.reduce((t, f) => t + (Number(f[sumable]) || 0), 0) : 0;
        return (
          <section
            key={clave}
            className={`w-72 shrink-0 rounded-xl transition-colors ${
              encima === clave ? "bg-accent/10 ring-1 ring-accent" : ""
            }`}
            // `preventDefault` en `dragOver` es lo que hace que una zona
            // ACEPTE lo que se suelta: sin él, el navegador rechaza el gesto y
            // la tarjeta vuelve a su sitio sin que falle nada visible.
            onDragOver={
              mover
                ? (e) => {
                    e.preventDefault();
                    setEncima(clave);
                  }
                : undefined
            }
            onDragLeave={mover ? () => setEncima((c) => (c === clave ? null : c)) : undefined}
            onDrop={
              mover
                ? (e) => {
                    e.preventDefault();
                    setEncima(null);
                    void llevar(arrastrando.current, clave);
                    arrastrando.current = null;
                  }
                : undefined
            }
          >
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
                const propiedadesDeArrastre = mover
                  ? {
                      draggable: true,
                      onDragStart: () => {
                        arrastrando.current = fila;
                      },
                      onDragEnd: () => {
                        arrastrando.current = null;
                        setEncima(null);
                      },
                    }
                  : {};
                const id = String(fila.id ?? i);
                // El mismo selector que el embudo, y a propósito: dos pantallas
                // que hacen lo mismo lo hacen igual. Escondido hasta que recibe
                // el foco —con el ratón se arrastra; con teclado se tabula
                // hasta aquí y aparece—, porque siempre visible cada tarjeta
                // repetiría el nombre de su propia columna y el tablero se
                // leería como un formulario.
                const selector = mover ? (
                  <>
                    <label htmlFor={`mover-${id}`} className="sr-only">
                      {`Mover ${nombreDelRegistro(fila)} a otra columna`}
                    </label>
                    <select
                      id={`mover-${id}`}
                      value={clave}
                      onChange={(e) => void llevar(fila, e.target.value)}
                      className="input-sm mt-2 text-3xs sr-only focus:not-sr-only focus:relative"
                    >
                      {claves.map((c) => (
                        <option key={c} value={c}>
                          {humanizar(c)}
                        </option>
                      ))}
                    </select>
                  </>
                ) : null;
                return (
                  <li key={id}>
                    {a ? (
                      // El selector va FUERA del enlace: dentro de un `<a>` no
                      // se puede usar —el navegador se lleva la pulsación al
                      // enlace— y la única forma de mover con teclado dejaría
                      // de funcionar justo en el caso normal.
                      <div
                        className={`rounded-xl border border-ink-dim/60 bg-paper p-2.5 hover:border-accent ${
                          mover ? "cursor-grab active:cursor-grabbing" : ""
                        }`}
                        {...propiedadesDeArrastre}
                      >
                        <Link to={a} className="block">
                          {cuerpo}
                        </Link>
                        {selector}
                      </div>
                    ) : (
                      <div
                        className={`rounded-xl border border-ink-dim/60 bg-paper p-2.5 ${
                          mover ? "cursor-grab active:cursor-grabbing" : ""
                        }`}
                        {...propiedadesDeArrastre}
                      >
                        {cuerpo}
                        {selector}
                      </div>
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
