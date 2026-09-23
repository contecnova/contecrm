/**
 * Una tabla que se pinta de datos que no se conocen de antemano.
 *
 * La consola se construye leyendo el contrato, así que las columnas salen de lo
 * que devuelve la API y no de una lista escrita a mano. Las decisiones:
 *
 * **Las columnas salen de la unión de las claves de todas las filas**, no de la
 * primera. Con la primera, un registro que trae un campo opcional lo pierde y
 * el usuario nunca sabe que existe.
 *
 * **El rótulo de la columna se escribe como se lee.** La API devuelve
 * `sector_codigo` y `facturacion_anual`, y eso es el nombre del campo, no el de
 * la columna. Se transforma con una regla —guiones bajos a espacios y la
 * primera en mayúscula— y no con una lista de traducciones por campo: una lista
 * así se queda corta en cuanto se añade un campo, y entonces conviven columnas
 * bonitas con columnas en crudo, que es peor que tenerlas todas en crudo.
 *
 * **Se eligen las columnas.** Un listado de clientes con las veinte columnas
 * del modelo no se lee: hay que desplazarse en horizontal para llegar al
 * teléfono. Quien mira elige cuáles quiere y se le recuerdan — es lo que hacen
 * las vistas de lista de Salesforce y el «editar columnas» de HubSpot, y por el
 * mismo motivo: las columnas útiles dependen de para qué se mire la lista.
 *
 * **Una columna vacía en TODAS las filas no se pinta, y se dice cuántas se han
 * escondido.** Esconderlas en silencio sería ocultar que el campo existe; no
 * esconderlas deja una tabla de veinte columnas con guiones donde hay tres con
 * datos, y ahí no se lee nada.
 *
 * **Los objetos y las listas se enseñan como JSON, no como `[object Object]`.**
 * Es feo y es honesto: un valor compuesto que se pinta mal parece un valor
 * vacío.
 *
 * **Las celdas no parten la línea.** Un identificador partido en cuatro líneas
 * estira la fila entera y hace ilegible el resto. En pantalla estrecha la tabla
 * se desplaza en horizontal (CRM-07.04.01.08): una tabla de doce columnas
 * apretada en 360 px no se lee; una que se desplaza, sí, y quien mira decide
 * qué mira.
 */

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Icono } from "@/componentes/Icono";

import {
  escalar,
  esIdentificadorTecnico,
  humanizar,
  tieneDato,
  trozos,
  UUID,
} from "@/lib/formato";

export interface Props {
  /**
   * Las filas tal y como llegan de la API. Pueden no ser objetos: hay extremos
   * que devuelven una lista de textos —los motivos de pérdida admitidos, por
   * ejemplo— y eso también es un listado legítimo.
   */
  filas: unknown[];
  /** Columnas en orden. Si no se pasan, salen de las filas. */
  columnas?: string[];
  titulo?: string;
  /** Si se pasa, la primera celda de cada fila enlaza a su ficha. */
  enlace?: (fila: Record<string, unknown>) => string | null;
  /**
   * Cuántas columnas se enseñan de entrada cuando el recurso no declara cuáles.
   *
   * Seis, no todas: un listado que nace con veinte columnas obliga a desplazarse
   * en horizontal antes de leer nada, y quien llega no sabe que puede quitarlas.
   */
  porDefecto?: number;
  /**
   * Con qué nombre se recuerda la elección de columnas. Sin él no se recuerda:
   * dos tablas distintas no pueden compartir preferencia.
   */
  recuerdaComo?: string;
}

const CLAVE_COLUMNAS = "contecrm.columnas";

function leerElegidas(recuerdaComo?: string): string[] | null {
  if (!recuerdaComo) return null;
  try {
    const crudo = localStorage.getItem(`${CLAVE_COLUMNAS}.${recuerdaComo}`);
    const lista = crudo ? (JSON.parse(crudo) as unknown) : null;
    return Array.isArray(lista) ? lista.map(String) : null;
  } catch {
    return null;
  }
}

export function Tabla({
  filas: filasCrudas,
  columnas,
  titulo,
  enlace,
  porDefecto = 6,
  recuerdaComo,
}: Props) {
  const { t } = useTranslation();
  const filas = useMemo(() => normalizar(filasCrudas), [filasCrudas]);
  const pedidas = columnas ?? columnasDe(filas);
  // Con dato en alguna fila. Una columna vacía en todas es ruido.
  const disponibles = pedidas.filter((c) => filas.some((fila) => tieneDato(fila[c])));

  const [elegidas, setElegidas] = useState<string[] | null>(() => leerElegidas(recuerdaComo));
  const [eligiendo, setEligiendo] = useState(false);

  // De entrada, las que el recurso declara como preferidas —o las primeras—,
  // no todas: `columnas` llega con las preferidas delante.
  const visibles = useMemo(() => {
    const guardadas = elegidas?.filter((c) => disponibles.includes(c));
    if (guardadas && guardadas.length > 0) return guardadas;
    // Los identificadores técnicos no entran de entrada: una columna de UUID
    // ocupa el ancho de tres columnas útiles y no dice nada. Siguen estando en
    // el selector para quien los necesite.
    const utiles = disponibles.filter((c) => !esIdentificadorTecnico(c));
    return (utiles.length > 0 ? utiles : disponibles).slice(0, Math.max(1, porDefecto));
  }, [elegidas, disponibles, porDefecto]);

  function alternarColumna(columna: string) {
    const siguientes = visibles.includes(columna)
      ? visibles.filter((c) => c !== columna)
      : [...disponibles.filter((c) => visibles.includes(c) || c === columna)];
    setElegidas(siguientes);
    if (!recuerdaComo) return;
    try {
      localStorage.setItem(`${CLAVE_COLUMNAS}.${recuerdaComo}`, JSON.stringify(siguientes));
    } catch {
      /* sin almacenamiento: la elección vale para esta sesión */
    }
  }

  const cabeceras = visibles;
  const escondidas = disponibles.length - cabeceras.length;

  return (
    <div>
      {disponibles.length > cabeceras.length || elegidas ? (
        <div className="mb-2 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => setEligiendo((v) => !v)}
            aria-expanded={eligiendo}
            className="btn-secondary inline-flex items-center gap-1.5"
          >
            <Icono nombre="view_column" tamano="sm" />
            {t("tabla.columnas", { visibles: cabeceras.length, total: disponibles.length })}
          </button>
        </div>
      ) : null}

      {eligiendo ? (
        <fieldset className="card mb-2 p-3">
          <legend className="sr-only">{t("tabla.elegirColumnas")}</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {disponibles.map((c) => (
              <label key={c} className="inline-flex items-center gap-1.5 text-2xs text-ink">
                <input
                  type="checkbox"
                  checked={cabeceras.includes(c)}
                  onChange={() => alternarColumna(c)}
                  className="h-3.5 w-3.5 rounded border-ink-dim accent-accent"
                />
                {humanizar(c)}
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}

      <div className="overflow-x-auto rounded-xl border border-ink-dim/60 bg-paper">
        <table className="w-full text-left text-xs">
          {titulo ? <caption className="sr-only">{titulo}</caption> : null}
          <thead className="border-b border-ink-dim/30 bg-paper-light">
            <tr>
              {cabeceras.map((c) => (
                <th
                  key={c}
                  scope="col"
                  className="whitespace-nowrap px-3 py-2 font-medium text-ink-muted"
                  title={c}
                >
                  {humanizar(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filas.map((fila, i) => (
              <tr
                key={clave(fila, i)}
                className="border-b border-ink-dim/30 last:border-0 hover:bg-paper-light"
              >
                {cabeceras.map((c, columna) => {
                  const destino = columna === 0 && enlace ? enlace(fila) : null;
                  return (
                    <td key={c} className="whitespace-nowrap px-3 py-2 align-top text-ink">
                      {destino ? (
                        // Enlace de contenido, no de acción: `btn-link` es un
                        // micro-enlace monoespaciado en mayúsculas, y el nombre
                        // de una cuenta puesto ahí deja de parecer un nombre.
                        <Link to={destino} className="text-accent hover:underline">
                          <Celda valor={fila[c]} campo={c} />
                        </Link>
                      ) : (
                        <Celda valor={fila[c]} campo={c} />
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {escondidas > 0 ? (
        <p className="mt-1.5 text-3xs text-ink-faint">
          {t("tabla.masColumnas", { count: escondidas })}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Deja cada fila como un objeto, venga como venga.
 *
 * Una lista de textos —`["competencia", "sin_presupuesto", …]`— es una
 * respuesta perfectamente normal, y aquí llegaba a `Object.keys("competencia")`,
 * que devuelve `["0","1","2",…]`. El resultado era una tabla con una columna
 * **por cada letra** y una letra en cada celda: la pantalla de motivos de
 * pérdida se leía en vertical, carácter a carácter. Información verdadera y
 * completamente inutilizable, que es la peor forma de estar mal.
 */
export function normalizar(filas: unknown[]): Record<string, unknown>[] {
  return filas.map((fila) =>
    fila !== null && typeof fila === "object" && !Array.isArray(fila)
      ? (fila as Record<string, unknown>)
      : { valor: fila },
  );
}

export function columnasDe(filas: Record<string, unknown>[]): string[] {
  const vistas = new Set<string>();
  for (const fila of filas) for (const clave of Object.keys(fila)) vistas.add(clave);
  return [...vistas];
}

/**
 * Lo que se pinta en una celda.
 *
 * Devuelve nodos y no texto: un objeto de interruptores se lee como etiquetas
 * —qué está encendido y qué no—, no como `{"procesos":true,"webhooks":true,…`
 * recortado a la mitad. Eso último es información verdadera e inutilizable:
 * nadie lee un JSON de un vistazo, y recortado ni siquiera entero.
 */
function Celda({ valor, campo }: { valor: unknown; campo: string }) {
  if (!tieneDato(valor)) {
    const vacio = Array.isArray(valor) || (typeof valor === "object" && valor !== null);
    // Se distingue «no hay dato» de «la lista está vacía»: parece lo mismo y no
    // lo es —lo primero puede ser un fallo de carga y lo segundo es un hecho—.
    return (
      <span className="text-ink-faint" title={vacio ? "Lista vacía" : "Sin dato"}>
        —
      </span>
    );
  }

  const compuesto = Array.isArray(valor) || (valor !== null && typeof valor === "object");
  if (compuesto) {
    const piezas = trozos(valor, campo);
    const visibles = piezas.slice(0, 3);
    return (
      <span className="inline-flex flex-wrap items-center gap-1">
        {visibles.map((t, i) => (
          <span
            key={i}
            className={`chip-dato ${t.apagado ? "chip-dato--no" : "chip-dato--si"}`}
          >
            {t.texto}
          </span>
        ))}
        {piezas.length > visibles.length ? (
          <span
            className="text-3xs text-ink-faint"
            title={piezas.map((t) => t.texto).join(" · ")}
          >
            +{piezas.length - visibles.length}
          </span>
        ) : null}
      </span>
    );
  }

  const texto = escalar(valor, campo);
  if (typeof valor === "string" && UUID.test(valor)) {
    // Ocho caracteres bastan para distinguir dos filas; treinta y seis de
    // hexadecimal no se leen, no se recuerdan y no se comparan de un vistazo.
    return (
      <span className="font-mono text-3xs text-ink-muted" title={valor}>
        {valor.slice(0, 8)}…
      </span>
    );
  }
  return (
    <span title={texto.length > 60 ? texto : undefined}>
      {texto.length > 60 ? `${texto.slice(0, 60)}…` : texto}
    </span>
  );
}

function clave(fila: Record<string, unknown>, i: number): string {
  const id = fila.id ?? fila.codigo ?? fila.clave ?? fila.nombre;
  return typeof id === "string" || typeof id === "number" ? String(id) : String(i);
}
