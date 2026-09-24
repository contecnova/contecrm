/**
 * La respuesta de contecintelligence, pintada (CRM-05.01.04.03).
 *
 * El contrato de allí devuelve un `payload` con `type`, `data` y, para las
 * gráficas, sus ejes y series. Aquí se convierte en algo que se lee:
 *
 *   kpi_card                     → el número, grande
 *   bar/line/area/pie/funnel…    → barras, con su valor al lado
 *   table y todo lo demás        → tabla
 *
 * **Nunca se enseña el JSON.** Es la regla que ordena este fichero: un objeto
 * crudo en pantalla es pedirle a quien pregunta «¿cuánto vendimos?» que lea una
 * estructura de datos. Un tipo de gráfica que aún no se dibuja cae a TABLA, que
 * siempre se entiende, y no a un volcado.
 *
 * El SQL y las comprobaciones van en un desplegable cerrado: quien quiera
 * auditar la respuesta tiene que poder, y quien solo quiera el número no tiene
 * que verlo.
 */

import { useMemo } from "react";
import { useTranslation } from "react-i18next";

export interface Payload {
  type: string;
  title: string;
  data: Array<Record<string, unknown>>;
  series?: Array<{ key: string; label?: string | null }>;
  xAxis?: { key?: string; label?: string | null } | null;
  unit?: string | null;
  sql?: string | null;
  meta?: { verification?: Array<{ title: string; status: string; detail?: string }> } | null;
}

/** Los tipos que se dibujan como barras. El resto cae a tabla, a propósito. */
const DE_BARRAS = new Set([
  "bar_chart",
  "line_chart",
  "timeseries_line",
  "area_chart",
  "pie_chart",
  "funnel_chart",
  "combo_chart",
]);

function formatear(valor: unknown, unidad?: string | null): string {
  if (valor === null || valor === undefined) return "—";
  if (typeof valor === "number") {
    // Sin decimales cuando es entero: «3» se lee mejor que «3,00», y con miles
    // separados, que es la diferencia entre leer un número y contar sus cifras.
    const texto = Number.isInteger(valor)
      ? valor.toLocaleString("es-ES")
      : valor.toLocaleString("es-ES", { maximumFractionDigits: 2 });
    return unidad ? `${texto} ${unidad}` : texto;
  }
  if (typeof valor === "boolean") return valor ? "sí" : "no";
  if (typeof valor === "object") return JSON.stringify(valor);
  return String(valor);
}

export function RespuestaAnalitica({ payload, texto }: { payload: Payload; texto?: string }) {
  const { t } = useTranslation();
  const columnas = useMemo(() => {
    const vistas = new Set<string>();
    for (const fila of payload.data || []) for (const k of Object.keys(fila)) vistas.add(k);
    return [...vistas];
  }, [payload.data]);

  const titulo = payload.title || texto || "";

  return (
    <div className="rounded-xl border border-ink-dim/60 bg-paper p-4">
      {titulo ? <h3 className="text-sm font-semibold text-ink">{titulo}</h3> : null}

      {payload.type === "kpi_card" ? (
        <Numero payload={payload} columnas={columnas} />
      ) : DE_BARRAS.has(payload.type) ? (
        <Barras payload={payload} columnas={columnas} />
      ) : (
        <Tabla columnas={columnas} filas={payload.data || []} />
      )}

      {payload.sql ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-3xs text-ink-faint hover:text-ink-muted">
            {t("explotacion.comoSeCalculo")}
          </summary>
          <pre className="mt-2 overflow-x-auto rounded-md bg-paper-sunk p-2 font-mono text-3xs text-ink-muted">
            {payload.sql}
          </pre>
          {payload.meta?.verification?.length ? (
            <ul className="mt-2 flex flex-col gap-1">
              {payload.meta.verification.map((v) => (
                <li key={v.title} className="text-3xs text-ink-faint">
                  <span className="font-medium text-ink-muted">{v.title}:</span> {v.detail || v.status}
                </li>
              ))}
            </ul>
          ) : null}
        </details>
      ) : null}
    </div>
  );
}

function Numero({ payload, columnas }: { payload: Payload; columnas: string[] }) {
  const fila = (payload.data || [])[0] || {};
  const clave = payload.series?.[0]?.key && clave_en(fila, payload.series[0].key) ? payload.series[0].key : columnas[0];
  return (
    <p className="mt-2 text-3xl font-bold tracking-tight text-ink">
      {formatear(clave ? fila[clave] : undefined, payload.unit)}
    </p>
  );
}

function clave_en(fila: Record<string, unknown>, clave: string): boolean {
  return Object.prototype.hasOwnProperty.call(fila, clave);
}

function Barras({ payload, columnas }: { payload: Payload; columnas: string[] }) {
  const filas = payload.data || [];
  const etiquetaClave = payload.xAxis?.key && columnas.includes(payload.xAxis.key) ? payload.xAxis.key : columnas[0];
  const valorClave =
    payload.series?.find((s) => columnas.includes(s.key))?.key ??
    columnas.find((c) => c !== etiquetaClave && filas.some((f) => typeof f[c] === "number")) ??
    columnas[1];

  if (!valorClave || !etiquetaClave) return <Tabla columnas={columnas} filas={filas} />;
  const clave = valorClave;
  const maximo = Math.max(
    ...filas.map((f) => (typeof f[clave] === "number" ? (f[clave] as number) : 0)),
    0,
  );
  if (maximo <= 0) return <Tabla columnas={columnas} filas={filas} />;

  return (
    <ul className="mt-3 flex flex-col gap-1.5">
      {filas.map((f, i) => {
        const valor = typeof f[clave] === "number" ? (f[clave] as number) : 0;
        return (
          <li key={i} className="flex items-center gap-2">
            <span className="w-40 shrink-0 truncate text-2xs text-ink-muted" title={String(f[etiquetaClave] ?? "")}>
              {formatear(f[etiquetaClave])}
            </span>
            {/* La barra lleva su valor al lado y no dentro: dentro, una barra
                corta esconde su propio número. */}
            <span className="h-3 flex-1 overflow-hidden rounded-sm bg-paper-sunk" aria-hidden>
              <span
                className="block h-full rounded-sm bg-accent"
                style={{ width: `${Math.max(2, (valor / maximo) * 100)}%` }}
              />
            </span>
            <span className="w-28 shrink-0 text-right text-2xs tabular-nums text-ink">
              {formatear(valor, payload.unit)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function Tabla({ columnas, filas }: { columnas: string[]; filas: Array<Record<string, unknown>> }) {
  if (filas.length === 0) {
    return <p className="mt-2 text-2xs text-ink-muted">Sin resultados.</p>;
  }
  return (
    <div className="mt-3 overflow-x-auto rounded-lg border border-ink-dim/30">
      <table className="w-full text-2xs">
        <thead className="bg-paper-sunk text-ink-muted">
          <tr>
            {columnas.map((c) => (
              <th key={c} className="px-2 py-1.5 text-left font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filas.map((f, i) => (
            <tr key={i} className="border-t border-ink-dim/30">
              {columnas.map((c) => (
                <td key={c} className="px-2 py-1.5 text-ink">
                  {formatear(f[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
