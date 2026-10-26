/**
 * La respuesta de contecintelligence, pintada (CRM-05.01.04.03).
 *
 * El contrato de allí devuelve un `payload` con `type`, `data` y, para las
 * gráficas, sus ejes y series. Aquí se convierte en algo que se lee:
 *
 *   kpi_card                     → el número, grande
 *   bar/column                   → barras
 *   line/timeseries/combo        → líneas
 *   area                         → área
 *   pie/donut/stacked            → barra APILADA, no tarta (ver `Grafica`)
 *   funnel                       → embudo
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

import { FORMA_DE_TIPO, Grafica, type Forma } from "@/componentes/graficas/Grafica";

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

/* Qué tipo se dibuja de qué forma sale de `FORMA_DE_TIPO`, en las gráficas.
   Aquí había una lista propia —`DE_BARRAS`— que metía los siete tipos en el
   mismo saco y los pintaba todos como barras: una serie temporal, un embudo y
   un reparto salían iguales. Lo que no esté en el mapa sigue cayendo a TABLA,
   que siempre se entiende, y nunca a un volcado de JSON. */

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
      ) : FORMA_DE_TIPO[payload.type] ? (
        <Dibujo payload={payload} columnas={columnas} />
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

/**
 * El puente entre el contrato de la respuesta y la gráfica.
 *
 * Vive aquí y no dentro de `Grafica` para que la gráfica no sepa nada del
 * contrato de contecintelligence: lo que se dibuja son series y categorías, y
 * la próxima fuente que haya traerá las suyas con otros nombres.
 */
function Dibujo({ payload, columnas }: { payload: Payload; columnas: string[] }) {
  const filas = payload.data || [];
  const ejeX =
    payload.xAxis?.key && columnas.includes(payload.xAxis.key) ? payload.xAxis.key : columnas[0];
  // Las series declaradas que existen de verdad en los datos. Si no declara
  // ninguna, se toman las columnas numéricas que no sean el eje: un informe
  // que se dejó el `series` sin poner se sigue dibujando.
  const declaradas = (payload.series || []).filter((s) => columnas.includes(s.key));
  const series =
    declaradas.length > 0
      ? declaradas.map((s) => ({ clave: s.key, rotulo: s.label || s.key }))
      : columnas
          .filter((c) => c !== ejeX && filas.some((f) => typeof f[c] === "number"))
          .map((c) => ({ clave: c, rotulo: c }));

  if (!ejeX || series.length === 0) return <Tabla columnas={columnas} filas={filas} />;

  return (
    <div className="mt-3">
      <Grafica
        forma={FORMA_DE_TIPO[payload.type] as Forma}
        titulo={payload.title || ""}
        datos={{
          filas,
          ejeX,
          rotuloX: payload.xAxis?.label,
          series,
          unidad: payload.unit,
        }}
      />
    </div>
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
