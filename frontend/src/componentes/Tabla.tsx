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
                  {rotular(c)}
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
                  const { texto, largo, monoespaciado } = pintar(fila[c]);
                  return (
                    <td
                      key={c}
                      className={`whitespace-nowrap px-3 py-2 align-top text-ink ${
                        monoespaciado ? "font-mono text-3xs text-ink-muted" : ""
                      }`}
                      // El valor entero en el atributo: se recorta lo que se ve,
                      // no lo que se tiene. Sin esto, recortar sería perderlo.
                      title={largo}
                    >
                      {destino ? (
                        // Enlace de contenido, no de acción: `btn-link` es un
                        // micro-enlace monoespaciado en mayúsculas, y el nombre
                        // de una cuenta puesto ahí deja de parecer un nombre.
                        <Link to={destino} className="text-accent-text hover:underline">
                          {texto}
                        </Link>
                      ) : (
                        texto
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

/** El nombre del campo, escrito como se lee. */
export function rotular(campo: string): string {
  const limpio = campo.replace(/_/g, " ").trim();
  return limpio.charAt(0).toUpperCase() + limpio.slice(1);
}

/** ¿Hay algo que enseñar aquí? Una lista vacía y un objeto vacío no lo son. */
function tieneDato(valor: unknown): boolean {
  if (valor === null || valor === undefined || valor === "") return false;
  if (Array.isArray(valor)) return valor.length > 0;
  if (typeof valor === "object") return Object.keys(valor as object).length > 0;
  return true;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Cómo se pinta un valor: lo que se ve, lo que se conserva y si va en monoespaciado.
 *
 * Un identificador se recorta a sus primeros ocho caracteres. No es para que
 * quepa: es que treinta y seis caracteres de hexadecimal no se leen, no se
 * recuerdan y no se comparan de un vistazo, mientras que ocho sí bastan para
 * distinguir dos filas. El valor completo sigue estando en el atributo `title`.
 */
function pintar(valor: unknown): { texto: string; largo: string; monoespaciado: boolean } {
  if (!tieneDato(valor)) {
    const vacio = Array.isArray(valor) || (typeof valor === "object" && valor !== null);
    return {
      texto: "—",
      // Se distingue «no hay dato» de «la lista está vacía». Parece lo mismo y
      // no lo es: lo primero puede ser un fallo de carga y lo segundo es un
      // hecho sobre el registro.
      largo: vacio ? "Lista vacía" : "Sin dato",
      monoespaciado: false,
    };
  }
  if (typeof valor === "boolean") return { texto: valor ? "sí" : "no", largo: String(valor), monoespaciado: false };
  if (typeof valor === "object") {
    const json = JSON.stringify(valor);
    return { texto: json.length > 40 ? `${json.slice(0, 40)}…` : json, largo: json, monoespaciado: true };
  }
  const texto = String(valor);
  if (UUID.test(texto)) return { texto: `${texto.slice(0, 8)}…`, largo: texto, monoespaciado: true };
  return {
    texto: texto.length > 60 ? `${texto.slice(0, 60)}…` : texto,
    largo: texto,
    monoespaciado: false,
  };
}

function clave(fila: Record<string, unknown>, i: number): string {
  const id = fila.id ?? fila.codigo ?? fila.clave ?? fila.nombre;
  return typeof id === "string" || typeof id === "number" ? String(id) : String(i);
}
