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

import { Link } from "react-router-dom";

import { escalar, humanizar, tieneDato, trozos, UUID } from "@/lib/formato";

export interface Props {
  filas: Record<string, unknown>[];
  /** Columnas en orden. Si no se pasan, salen de las filas. */
  columnas?: string[];
  titulo?: string;
  /** Si se pasa, la primera celda de cada fila enlaza a su ficha. */
  enlace?: (fila: Record<string, unknown>) => string | null;
}

export function Tabla({ filas, columnas, titulo, enlace }: Props) {
  const pedidas = columnas ?? columnasDe(filas);
  const cabeceras = pedidas.filter((c) => filas.some((fila) => tieneDato(fila[c])));
  const escondidas = pedidas.length - cabeceras.length;

  return (
    <div>
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
          {escondidas === 1
            ? "Hay 1 columna más, sin ningún dato en estas filas."
            : `Hay ${escondidas} columnas más, sin ningún dato en estas filas.`}
        </p>
      ) : null}
    </div>
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
