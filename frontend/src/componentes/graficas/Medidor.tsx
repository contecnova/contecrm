/**
 * Un medidor: una cifra contra su objetivo.
 *
 * Es la pieza que faltaba. Un componente de cuadro de tipo `gauge` —«una
 * métrica contra su objetivo»— se dibujaba como un KPI normal, o sea **como la
 * cifra sola**. Y el propio catálogo del servidor lo dice: «un gauge sin
 * objetivo es un KPI con una aguja; la aguja sólo significa algo contra una
 * meta». Perdiendo la meta, el gauge dejaba de ser un gauge.
 *
 * **Barra y no aguja.** Una aguja sobre un arco obliga a estimar un ángulo, y
 * estimar ángulos es justo lo que no se hace bien a ojo: dos agujas parecidas
 * sólo se distinguen leyendo los números, y si hay que leerlos la aguja no
 * aportaba nada. Una barra contra su pista se lee de un vistazo y además se
 * puede comparar con la de al lado, que es lo que se hace en un cuadro.
 *
 * **El objetivo se marca, no se da por hecho.** La pista llega hasta el mayor
 * de los dos —lo conseguido o la meta—, así que pasarse se ve: la barra sigue
 * más allá de la marca. Un medidor que recorta en el 100 % esconde que se
 * superó la meta, que es exactamente la noticia buena.
 */

import { useTranslation } from "react-i18next";

import { exacto } from "@/componentes/graficas/escalas";

export function Medidor({
  titulo,
  valor,
  objetivo,
  unidad,
}: {
  titulo: string;
  valor: number;
  objetivo: number;
  unidad?: string | null;
}) {
  const { t } = useTranslation();

  // Sin objetivo no hay medidor. Se dice en vez de pintar una barra contra
  // nada, que es lo que hacía antes con otra forma.
  if (!Number.isFinite(objetivo) || objetivo <= 0) {
    return (
      <figure className="card p-3">
        <figcaption className="text-xs font-medium text-ink">{titulo}</figcaption>
        <p className="mt-2 text-2xl font-bold tracking-tight text-ink">
          {exacto(valor, unidad)}
        </p>
        <p className="mt-1 text-3xs text-ink-faint">{t("medidor.sinObjetivo")}</p>
      </figure>
    );
  }

  const pct = (valor / objetivo) * 100;
  // La pista llega al mayor de los dos: así pasarse se ve.
  const techo = Math.max(valor, objetivo);
  const anchoValor = Math.max(0, Math.min(100, (valor / techo) * 100));
  const posObjetivo = (objetivo / techo) * 100;
  const cumplido = valor >= objetivo;

  return (
    <figure className="card p-3">
      <figcaption className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-ink">{titulo}</span>
        {/* El porcentaje en tinta y no en el color de la barra: el texto de
            color se lee peor y duplica una señal que la barra ya da. */}
        <span className="font-mono text-2xs text-ink-muted">
          {Math.round(pct)}%
        </span>
      </figcaption>

      <p className="mt-1 text-2xl font-bold tracking-tight text-ink">
        {exacto(valor, unidad)}
      </p>

      <div
        className="relative mt-2 h-2 w-full overflow-hidden rounded-full bg-paper-sunk"
        role="meter"
        aria-valuenow={valor}
        aria-valuemin={0}
        aria-valuemax={techo}
        aria-label={titulo}
      >
        <span
          className={`block h-full rounded-full ${cumplido ? "bg-success" : "bg-accent"}`}
          style={{ width: `${anchoValor}%` }}
        />
        {/* La marca del objetivo, encima de la barra. Va aquí y no como una
            segunda barra: son dos cosas distintas —lo conseguido y la meta— y
            dos barras del mismo grosor se leen como dos series. */}
        <span
          aria-hidden
          className="absolute top-0 h-full w-0.5 bg-ink"
          style={{ left: `calc(${posObjetivo}% - 1px)` }}
        />
      </div>

      <p className="mt-1 text-3xs text-ink-muted">
        {t(cumplido ? "medidor.cumplido" : "medidor.faltan", {
          objetivo: exacto(objetivo, unidad),
          falta: exacto(Math.max(0, objetivo - valor), unidad),
        })}
      </p>
    </figure>
  );
}
