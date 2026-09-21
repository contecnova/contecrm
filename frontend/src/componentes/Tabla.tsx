/**
 * Una tabla que se pinta de datos que no se conocen de antemano.
 *
 * La consola se construye leyendo el contrato, así que las columnas salen de lo
 * que devuelve la API y no de una lista escrita a mano. Dos decisiones:
 *
 * **Las columnas salen de la unión de las claves de todas las filas**, no de la
 * primera. Con la primera, un registro que trae un campo opcional lo pierde y
 * el usuario nunca sabe que existe.
 *
 * **Los objetos y las listas se enseñan como JSON, no como `[object Object]`.**
 * Es feo y es honesto: un valor compuesto que se pinta mal parece un valor
 * vacío.
 *
 * **En pantalla estrecha se desplaza en horizontal, no se encoge**
 * (CRM-07.04.01.08). Una tabla de doce columnas apretada en 360 px no se lee;
 * una que se desplaza, sí, y el usuario decide qué mira.
 */

export interface Props {
  filas: Record<string, unknown>[];
  /** Columnas en orden. Si no se pasan, salen de las filas. */
  columnas?: string[];
  titulo?: string;
}

export function Tabla({ filas, columnas, titulo }: Props) {
  const cabeceras = columnas ?? columnasDe(filas);
  return (
    <div className="overflow-x-auto rounded-xl border border-ink-dim/60 bg-paper">
      <table className="w-full text-left text-xs">
        {titulo ? <caption className="sr-only">{titulo}</caption> : null}
        <thead className="border-b border-ink-dim/30 bg-paper-light">
          <tr>
            {cabeceras.map((c) => (
              <th key={c} scope="col" className="px-3 py-2 font-medium text-ink-muted">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filas.map((fila, i) => (
            <tr key={clave(fila, i)} className="border-b border-ink-dim/30 last:border-0">
              {cabeceras.map((c) => (
                <td key={c} className="px-3 py-2 align-top text-ink">
                  {celda(fila[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function columnasDe(filas: Record<string, unknown>[]): string[] {
  const vistas = new Set<string>();
  for (const fila of filas) for (const clave of Object.keys(fila)) vistas.add(clave);
  return [...vistas];
}

function clave(fila: Record<string, unknown>, i: number): string {
  const id = fila.id ?? fila.codigo ?? fila.clave ?? fila.nombre;
  return typeof id === "string" || typeof id === "number" ? String(id) : String(i);
}

function celda(valor: unknown): string {
  if (valor === null || valor === undefined) return "—";
  if (typeof valor === "boolean") return valor ? "sí" : "no";
  if (typeof valor === "object") return JSON.stringify(valor);
  return String(valor);
}
