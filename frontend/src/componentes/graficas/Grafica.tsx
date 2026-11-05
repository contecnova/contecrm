/**
 * Las gráficas del producto (CRM-05.01.04.03, CRM-07.04.01.02).
 *
 * **Hasta hoy no había ninguna.** Medido el 26-10-2026: cero librerías de
 * gráficas, dos `<svg>` en toda la aplicación y ninguno era una gráfica. Un
 * `line_chart`, un `pie_chart` y un `funnel_chart` se dibujaban los tres como
 * barras horizontales con el número al lado. El backend sí devolvía series y
 * agregados; lo que faltaba era dibujarlos.
 *
 * Tres decisiones que no son de gusto y conviene que estén escritas:
 *
 * **Secuencial es el defecto, no categórico.** Una serie sola de magnitudes se
 * pinta en un tono y se ordena; el color categórico es para cuando las series
 * SON el asunto. Pintar seis barras de seis colores cuando lo que importa es
 * cuál es más alta entierra la respuesta debajo de un arcoíris.
 *
 * **Parte de un todo es una barra apilada, no una tarta.** Comparar ángulos es
 * medir mal: dos porciones parecidas sólo se distinguen leyendo los números, y
 * si hay que leer los números la tarta no estaba aportando nada. Cuando el
 * informe pide `pie_chart` se dibuja apilada horizontal, que es lo mismo mejor
 * leído.
 *
 * **Nunca dos ejes verticales.** Dos magnitudes de escalas distintas van en dos
 * gráficas o indexadas a una base común. Un eje doble deja que quien lo dibuja
 * elija dónde se cruzan las líneas, y entonces la gráfica dice lo que quiera.
 *
 * Y la salida de emergencia de siempre: **toda gráfica trae su tabla**. Es lo
 * que la hace legible con un lector de pantalla, lo que permite copiar un
 * número y lo único que funciona cuando alguien no distingue dos colores.
 */

import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  MAXIMO_ETIQUETA_DIRECTA,
  SERIES_CON_COLOR,
  aNumero,
  colorDeSerie,
  corto,
  exacto,
  marcas,
  techo,
  type Dato,
} from "@/componentes/graficas/escalas";

export type Forma = "barras" | "lineas" | "area" | "apilada" | "embudo";

export interface Serie {
  clave: string;
  rotulo: string;
}

export interface DatosGrafica {
  /** Cada fila: la categoría del eje y un valor por serie. */
  filas: Array<Record<string, unknown>>;
  /** Qué columna es el eje horizontal. */
  ejeX: string;
  rotuloX?: string | null;
  series: Serie[];
  unidad?: string | null;
}

/**
 * De qué tipo del contrato sale cada forma.
 *
 * El mapa está aquí y no repartido por las pantallas: el tipo lo elige quien
 * escribe el informe, y dos pantallas que lo tradujeran por su cuenta acabarían
 * dibujando el mismo informe de dos maneras.
 */
export const FORMA_DE_TIPO: Record<string, Forma> = {
  bar_chart: "barras",
  column_chart: "barras",
  line_chart: "lineas",
  timeseries_line: "lineas",
  area_chart: "area",
  // A propósito: lo que se pide como tarta se dibuja apilado. Ver arriba.
  pie_chart: "apilada",
  donut_chart: "apilada",
  stacked_bar: "apilada",
  funnel_chart: "embudo",
  // Una combinada son dos magnitudes distintas en el mismo dibujo, que es el
  // eje doble con otro nombre. Se dibujan como líneas, que al menos comparten
  // escala y no mienten sobre dónde se cruzan.
  combo_chart: "lineas",
};

const ALTO = 220;
const MARGEN = { arriba: 12, derecha: 12, abajo: 28, izquierda: 48 };

/**
 * Los tamaños de letra de un SVG, en la escala del sistema.
 *
 * Un `<text>` de SVG no admite una clase de Tailwind con el tamaño, así que
 * va el número — y por eso se escapó: **medido el 02-11-2026**, las etiquetas
 * de los ejes y de los nodos estaban en 9 px, por debajo de lo que se lee en
 * un escritorio, en la portada y en el diagrama de procesos. Van al mínimo
 * del sistema, que son 12.
 */
const LETRA_GRAFICA = 12;

export function Grafica({
  forma,
  datos,
  titulo,
}: {
  forma: Forma;
  datos: DatosGrafica;
  titulo: string;
}) {
  const { t } = useTranslation();
  const [verTabla, setVerTabla] = useState(false);
  const [encima, setEncima] = useState<number | null>(null);
  const idTitulo = useId();

  const categorias = useMemo(
    () => datos.filas.map((f) => String(f[datos.ejeX] ?? "")),
    [datos],
  );

  // Las series que se pintan: hasta cinco con color propio, el resto sumado en
  // «otros». Nunca se genera un sexto tono.
  const series = useMemo(() => {
    const visibles = datos.series.slice(0, SERIES_CON_COLOR);
    const cola = datos.series.slice(SERIES_CON_COLOR);
    const lista = visibles.map((s, i) => ({
      ...s,
      color: colorDeSerie(i),
      valores: datos.filas.map((f) => aNumero(f[s.clave])),
    }));
    if (cola.length > 0) {
      lista.push({
        clave: "__otros__",
        rotulo: t("grafica.otras", { count: cola.length }),
        color: colorDeSerie(SERIES_CON_COLOR),
        valores: datos.filas.map((f) => {
          const suma = cola
            .map((s) => aNumero(f[s.clave]))
            .filter((v): v is number => v !== null);
          return suma.length > 0 ? suma.reduce((a, b) => a + b, 0) : null;
        }),
      });
    }
    return lista;
  }, [datos, t]);

  const apilada = forma === "apilada";
  const esEmbudo = forma === "embudo";
  // **Área sólo con una serie.** Con tres, los rellenos se superponen y se
  // mezclan en un barro del que no se saca ninguna de las tres. Se vio al
  // mirar el dibujo —no lo caza ningún validador de color— y se degrada a
  // líneas, que es la misma información legible.
  const conRelleno = forma === "area" && series.length === 1;
  const totales = useMemo(
    () =>
      datos.filas.map((_, i) =>
        series
          .map((s) => s.valores[i])
          .filter((v): v is number => v !== null)
          .reduce((a, b) => a + b, 0),
      ),
    [datos.filas, series],
  );
  const maximo = techo(apilada ? totales : series.flatMap((s) => s.valores));
  const lineasEje = marcas(maximo);

  const ancho = 640;
  const anchoUtil = ancho - MARGEN.izquierda - MARGEN.derecha;
  const altoUtil = ALTO - MARGEN.arriba - MARGEN.abajo;
  const x = (i: number) =>
    MARGEN.izquierda +
    (categorias.length <= 1
      ? anchoUtil / 2
      : (anchoUtil * i) / (categorias.length - 1));
  const y = (v: number) => MARGEN.arriba + altoUtil - (altoUtil * v) / maximo;

  const sinDatos = categorias.length === 0 || series.length === 0;

  return (
    <figure className="card p-3" aria-labelledby={idTitulo}>
      <figcaption className="mb-2 flex items-start justify-between gap-2">
        <span id={idTitulo} className="text-titulin font-medium text-ink">
          {titulo}
        </span>
        {/* La tabla no es un extra: es lo que hace esto legible con un lector
            de pantalla y lo único que funciona si alguien no distingue dos
            colores. Por eso el botón está siempre, no escondido en un menú. */}
        <button
          type="button"
          onClick={() => setVerTabla((v) => !v)}
          className="btn-link shrink-0"
          aria-pressed={verTabla}
        >
          {t(verTabla ? "grafica.verDibujo" : "grafica.verTabla")}
        </button>
      </figcaption>

      {sinDatos ? (
        <p className="py-6 text-center text-dato text-ink-faint">
          {t("grafica.sinDatos")}
        </p>
      ) : verTabla ? (
        <Tabla datos={datos} series={series} categorias={categorias} />
      ) : (
        <>
          <svg
            viewBox={`0 0 ${ancho} ${ALTO}`}
            className="w-full"
            role="img"
            aria-label={titulo}
            onMouseLeave={() => setEncima(null)}
          >
            {/* Rejilla recesiva: orienta y no compite. Sólo horizontales —las
                verticales doblan las líneas en pantalla y no añaden nada que el
                rótulo del eje no diga ya. */}
            {/* El embudo no lleva eje de valor ni rejilla: sus etapas no son
                una magnitud sobre un eje vertical, y pintarle marcas de 0 a
                1,5 k al lado es una escala que no mide nada de lo que se ve.
                Cada etapa lleva su número al lado, que es lo que se lee. */}
            {esEmbudo
              ? null
              : lineasEje.map((v) => (
                  <g key={v}>
                    <line
                      x1={MARGEN.izquierda}
                      x2={ancho - MARGEN.derecha}
                      y1={y(v)}
                      y2={y(v)}
                      stroke="rgb(var(--viz-grid))"
                      strokeWidth={1}
                    />
                    <text
                      x={MARGEN.izquierda - 6}
                      y={y(v) + 3}
                      textAnchor="end"
                      className="fill-ink-faint"
                      style={{ fontSize: LETRA_GRAFICA }}
                    >
                      {corto(v)}
                    </text>
                  </g>
                ))}

            {forma === "embudo" ? (
              <Embudo
                series={series}
                categorias={categorias}
                maximo={maximo}
                ancho={ancho}
              />
            ) : apilada ? (
              <Apiladas
                series={series}
                categorias={categorias}
                maximo={maximo}
                x={x}
                y={y}
                anchoUtil={anchoUtil}
                altoUtil={altoUtil}
                margen={MARGEN}
                encima={encima}
                alEntrar={setEncima}
              />
            ) : forma === "barras" ? (
              <Barras
                series={series}
                categorias={categorias}
                y={y}
                anchoUtil={anchoUtil}
                margen={MARGEN}
                base={MARGEN.arriba + altoUtil}
                encima={encima}
                alEntrar={setEncima}
              />
            ) : (
              <Trazos
                series={series}
                conRelleno={conRelleno}
                x={x}
                y={y}
                base={MARGEN.arriba + altoUtil}
                encima={encima}
              />
            )}

            {/* Las categorías del eje. Se saltan las que no caben en vez de
                encogerlas: una etiqueta de 6px no la lee nadie, y girarlas 45°
                hace ilegible la gráfica entera en cuanto hay doce. */}
            {esEmbudo
              ? null
              : categorias.map((c, i) =>
                  i % Math.ceil(categorias.length / 8) === 0 ? (
                    <text
                      key={`${c}-${i}`}
                      x={
                        forma === "barras" || apilada
                          ? bandaX(
                              i,
                              categorias.length,
                              MARGEN.izquierda,
                              anchoUtil,
                            )
                          : x(i)
                      }
                      y={ALTO - 8}
                      textAnchor="middle"
                      className="fill-ink-faint"
                      style={{ fontSize: LETRA_GRAFICA }}
                    >
                      {/* Igual que en el embudo: cortado, pero legible. */}
                      {c.length > 12 ? <title>{c}</title> : null}
                      {c.length > 12 ? `${c.slice(0, 11)}…` : c}
                    </text>
                  ) : null,
                )}

            {/* La cruz de posición, sólo en líneas y área: es donde hace falta
                para leer un punto concreto de una serie continua. */}
            {encima !== null && (forma === "lineas" || forma === "area") ? (
              <line
                x1={x(encima)}
                x2={x(encima)}
                y1={MARGEN.arriba}
                y2={MARGEN.arriba + altoUtil}
                stroke="rgb(var(--ink-muted))"
                strokeWidth={1}
                strokeDasharray="3 3"
              />
            ) : null}

            {/* Las zonas de puntería, más anchas que la marca: acertarle a una
                línea de 2px con el ratón no lo consigue nadie. */}
            {categorias.map((_, i) => (
              <rect
                key={i}
                x={MARGEN.izquierda + (anchoUtil * i) / categorias.length}
                y={MARGEN.arriba}
                width={anchoUtil / categorias.length}
                height={altoUtil}
                fill="transparent"
                onMouseEnter={() => setEncima(i)}
              />
            ))}
          </svg>

          {encima !== null ? (
            <Emergente
              categoria={categorias[encima] ?? ""}
              series={series}
              indice={encima}
              unidad={datos.unidad}
            />
          ) : null}

          {/* La leyenda SIEMPRE con dos o más series. Nunca con una: el título
              ya la nombra, y una leyenda de un elemento es una fila de ruido.

              Y es obligatoria aquí por una razón medida: magenta y teal se
              separan ΔE 6,6 bajo deuteranopía, dentro de la banda que el
              método admite sólo con codificación secundaria. Sin leyenda, esta
              paleta deja de ser válida. */}
          {series.length > 1 ? (
            <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
              {series.map((s) => (
                <li key={s.clave} className="inline-flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="h-2 w-2 shrink-0 rounded-sm"
                    style={{ background: s.color }}
                  />
                  {/* El rótulo va en tinta, no en el color de la serie: el
                      texto de color se lee peor y encima duplica la señal que
                      ya da la muestra de al lado. */}
                  <span className="text-rotulo text-ink-muted">{s.rotulo}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </figure>
  );
}

/** El centro de la banda `i` cuando las marcas ocupan ancho (barras, apiladas). */
function bandaX(
  i: number,
  cuantas: number,
  izquierda: number,
  anchoUtil: number,
): number {
  return izquierda + (anchoUtil * (i + 0.5)) / cuantas;
}

type SeriePintada = Serie & { color: string; valores: Dato[] };

function Trazos({
  series,
  conRelleno,
  x,
  y,
  base,
  encima,
}: {
  series: SeriePintada[];
  conRelleno: boolean;
  x: (i: number) => number;
  y: (v: number) => number;
  base: number;
  encima: number | null;
}) {
  return (
    <>
      {series.map((s) => {
        // Los huecos parten el trazo en vez de unirse: una línea recta sobre
        // un mes sin medir inventa una tendencia que nadie midió.
        const tramos: Array<Array<[number, number]>> = [];
        let actual: Array<[number, number]> = [];
        s.valores.forEach((v, i) => {
          if (v === null) {
            if (actual.length > 0) tramos.push(actual);
            actual = [];
          } else {
            actual.push([x(i), y(v)]);
          }
        });
        if (actual.length > 0) tramos.push(actual);

        return (
          <g key={s.clave}>
            {conRelleno
              ? tramos.map((tramo, n) => (
                  <path
                    key={n}
                    d={`M ${tramo[0]![0]} ${base} ${tramo
                      .map(([px, py]) => `L ${px} ${py}`)
                      .join(" ")} L ${tramo[tramo.length - 1]![0]} ${base} Z`}
                    fill={s.color}
                    fillOpacity={0.14}
                  />
                ))
              : null}
            {tramos.map((tramo, n) => (
              <path
                key={n}
                d={tramo
                  .map(([px, py], i) => `${i === 0 ? "M" : "L"} ${px} ${py}`)
                  .join(" ")}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ))}
            {/* El punto sólo donde se está mirando. Un marcador en cada punto
                de una serie de cincuenta convierte la línea en un collar. */}
            {encima !== null &&
            s.valores[encima] !== null &&
            s.valores[encima] !== undefined ? (
              <circle
                cx={x(encima)}
                cy={y(s.valores[encima] as number)}
                r={4}
                fill={s.color}
                stroke="rgb(var(--paper))"
                strokeWidth={2}
              />
            ) : null}
          </g>
        );
      })}
    </>
  );
}

function Barras({
  series,
  categorias,
  y,
  anchoUtil,
  margen,
  base,
  encima,
  alEntrar,
}: {
  series: SeriePintada[];
  categorias: string[];
  y: (v: number) => number;
  anchoUtil: number;
  margen: typeof MARGEN;
  base: number;
  encima: number | null;
  alEntrar: (i: number) => void;
}) {
  const banda = anchoUtil / categorias.length;
  // 2px de superficie entre barras vecinas: sin el hueco, dos series contiguas
  // se leen como una sola barra bicolor.
  const anchoBarra = Math.max(2, (banda * 0.7) / series.length - 2);
  return (
    <>
      {series.map((s, si) =>
        s.valores.map((v, i) =>
          v === null ? null : (
            <rect
              key={`${s.clave}-${i}`}
              x={
                margen.izquierda +
                banda * i +
                banda * 0.15 +
                si * (anchoBarra + 2)
              }
              y={y(v)}
              width={anchoBarra}
              height={Math.max(0, base - y(v))}
              rx={2}
              fill={s.color}
              fillOpacity={encima === null || encima === i ? 1 : 0.45}
              onMouseEnter={() => alEntrar(i)}
            />
          ),
        ),
      )}
    </>
  );
}

function Apiladas({
  series,
  categorias,
  maximo,
  y,
  anchoUtil,
  margen,
  altoUtil,
  encima,
  alEntrar,
}: {
  series: SeriePintada[];
  categorias: string[];
  maximo: number;
  x: (i: number) => number;
  y: (v: number) => number;
  anchoUtil: number;
  altoUtil: number;
  margen: typeof MARGEN;
  encima: number | null;
  alEntrar: (i: number) => void;
}) {
  const banda = anchoUtil / categorias.length;
  const ancho = Math.max(4, banda * 0.6);
  return (
    <>
      {categorias.map((_, i) => {
        let acumulado = 0;
        return series.map((s) => {
          const v = s.valores[i];
          if (v === null || v === undefined) return null;
          const desde = acumulado;
          acumulado += v;
          const alto = (altoUtil * v) / maximo;
          return (
            <rect
              key={`${s.clave}-${i}`}
              x={margen.izquierda + banda * i + (banda - ancho) / 2}
              // 2px de superficie entre tramos: sin el hueco, dos tramos
              // contiguos de tono parecido se leen como uno solo, y eso es
              // justo lo que la banda 6–8 de daltonismo no perdona.
              y={y(desde + v)}
              width={ancho}
              height={Math.max(0, alto - 2)}
              rx={2}
              fill={s.color}
              fillOpacity={encima === null || encima === i ? 1 : 0.45}
              onMouseEnter={() => alEntrar(i)}
            />
          );
        });
      })}
    </>
  );
}

function Embudo({
  series,
  categorias,
  maximo,
  ancho,
}: {
  series: SeriePintada[];
  categorias: string[];
  maximo: number;
  ancho: number;
}) {
  // Un embudo es UNA serie por etapas: se dibuja con la primera y las demás se
  // ignoran a propósito. Un embudo de dos series no es un embudo, son dos
  // embudos superpuestos y no se puede leer ninguno.
  const serie = series[0];
  if (!serie) return null;

  // Las etapas son FILAS, así que su nombre va a la izquierda de su barra y no
  // en un eje horizontal abajo. Se vio al mirar el dibujo: con los nombres
  // abajo, «Contactado» quedaba debajo de la barra de «Ganada» y el último se
  // cortaba a «Ganad».
  // **El ancho del rótulo lo marcan los rótulos, no un número fijo.** Con 92
  // de ancho y el corte a los 16 caracteres, la portada enseñaba «Oferta
  // presenta…» y «Pendiente de ad…» mientras al lado del embudo sobraban
  // 1.284 px de pantalla vacía: dos de las siete etapas del embudo de ventas
  // no se podían leer. Medido en el navegador el 03-11-2026.
  //
  // 6,3 por carácter es el ancho medio de la letra de la casa a 12 px; no
  // hace falta afinar más porque sólo decide cuánto sitio reservar. El tope
  // del 30 % está para que un nombre de etapa larguísimo no se coma la barra,
  // que es lo que de verdad se viene a mirar.
  const LARGO = Math.max(...categorias.map((c) => c.length), 8);
  const ROTULO = Math.min(ancho * 0.3, Math.max(92, LARGO * 6.3 + 4));
  const izquierda = ROTULO + 8;
  // Cuántos caracteres caben de verdad en ese ancho: cortar a 16 fijos con un
  // rótulo que ahora mide el doble dejaría el corte donde estaba.
  const CABEN = Math.max(8, Math.floor((ROTULO - 4) / 6.3));
  const util = ancho - izquierda - 56;
  const altoEtapa =
    (ALTO - MARGEN.arriba - MARGEN.abajo) / Math.max(1, categorias.length);
  // El porcentaje va contra el TOTAL, no contra la primera etapa.
  //
  // Contra la primera sólo tiene sentido si el embudo decrece, que es verdad
  // cuando se cuentan registros —de cien contactados quedan veinte— y es falso
  // cuando se suman IMPORTES, que es lo que enseña la portada: ahí la segunda
  // etapa puede valer más que la primera. Medido el 01-11-2026 en la portada
  // de un comercial: «495,3 k · 1764 %» y «555,5 k · 1979 %». Un porcentaje de
  // mil setecientos sesenta y cuatro en la primera pantalla del producto no es
  // un matiz: es un número que no significa nada y que hace dudar de los que
  // están al lado.
  //
  // Contra el total sí significa algo en los dos casos: «Negociación es el
  // 43 % de mi embudo» se entiende cuente lo que cuente.
  const total = serie.valores.reduce((a: number, v) => a + (v ?? 0), 0);

  return (
    <>
      {categorias.map((c, i) => {
        const v = serie.valores[i];
        if (v === null || v === undefined) return null;
        const anchoTramo = Math.max(2, (util * v) / maximo);
        const y = MARGEN.arriba + altoEtapa * i;
        const medio = y + altoEtapa / 2 + 3;
        return (
          <g key={`${c}-${i}`}>
            <text
              x={ROTULO}
              y={medio}
              textAnchor="end"
              className="fill-ink-muted"
              style={{ fontSize: LETRA_GRAFICA }}
            >
              {/* El nombre entero, para cuando no cabe. En SVG el tooltip es
                  un `<title>` dentro del propio elemento, y además lo lee
                  quien no ve la gráfica. Sin esto, «Pendiente de
                  adjudicación» salía como «Pendiente d…» y no había forma de
                  saber de qué etapa hablaba. */}
              {c.length > CABEN ? <title>{c}</title> : null}
              {c.length > CABEN ? `${c.slice(0, CABEN - 1)}…` : c}
            </text>
            <rect
              x={izquierda}
              y={y + 2}
              width={anchoTramo}
              height={Math.max(2, altoEtapa - 5)}
              rx={2}
              fill={serie.color}
              // Un solo tono que se aclara al bajar: las etapas son una
              // secuencia, no cinco cosas distintas, y cinco colores aquí
              // dirían que lo son.
              fillOpacity={1 - i * 0.13}
            />
            {/* El valor SIEMPRE al lado: la caída entre etapas es el dato, y
                estimarla comparando la longitud de dos rectángulos es
                exactamente lo que no se puede hacer a ojo. Y el peso de la
                etapa sobre el total, que se entiende cuente lo que cuente. */}
            <text
              x={izquierda + anchoTramo + 6}
              y={medio}
              className="fill-ink"
              style={{ fontSize: LETRA_GRAFICA }}
            >
              {corto(v)}
              {total > 0 ? (
                <tspan className="fill-ink-faint">
                  {" "}
                  · {Math.round((v / total) * 100)}%
                </tspan>
              ) : null}
            </text>
          </g>
        );
      })}
    </>
  );
}

function Emergente({
  categoria,
  series,
  indice,
  unidad,
}: {
  categoria: string;
  series: SeriePintada[];
  indice: number;
  unidad?: string | null;
}) {
  const conValor = series.filter((s) => s.valores[indice] !== null);
  return (
    <div className="mt-1 rounded-lg border border-ink-dim/60 bg-paper-light px-2 py-1.5">
      <p className="text-rotulo font-medium text-ink">{categoria}</p>
      <ul className="mt-0.5 space-y-0.5">
        {conValor.map((s) => (
          <li key={s.clave} className="flex items-center justify-between gap-3">
            <span className="inline-flex items-center gap-1.5">
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-sm"
                style={{ background: s.color }}
              />
              <span className="text-rotulo text-ink-muted">{s.rotulo}</span>
            </span>
            {/* Aquí el valor EXACTO, no el abreviado del eje: el emergente es
                donde alguien viene a buscar el número de verdad. */}
            <span className="font-mono text-rotulo text-ink">
              {exacto(s.valores[indice] as Dato, unidad)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Tabla({
  datos,
  series,
  categorias,
}: {
  datos: DatosGrafica;
  series: SeriePintada[];
  categorias: string[];
}) {
  // El armazón de la casa, como el resto de las tablas: esta vista es la
  // alternativa de quien no puede leer el dibujo, y salía con otra cabecera
  // —texto normal en gris— y otro espaciado que las demás. Medido el
  // 03-11-2026, al barrer las tablas escritas a mano que quedaban.
  //
  // Sin acotar: va dentro de la tarjeta de la gráfica, que ya mide lo suyo.
  return (
    <Rejilla
      acotada={false}
      pegada
      cabeceras={[datos.rotuloX || datos.ejeX, ...series.map((s) => s.rotulo)]}
    >
      {categorias.map((c, i) => (
        <tr
          key={`${c}-${i}`}
          className="border-b border-ink-dim/30 last:border-0"
        >
          <th scope="row" className="celda-rejilla font-normal text-ink">
            {c}
          </th>
          {series.map((s) => (
            <Casilla key={s.clave} className="text-right font-mono text-ink">
              {exacto(s.valores[i] as Dato, datos.unidad)}
            </Casilla>
          ))}
        </tr>
      ))}
    </Rejilla>
  );
}

export { MAXIMO_ETIQUETA_DIRECTA };
