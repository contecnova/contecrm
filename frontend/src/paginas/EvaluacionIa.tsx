/**
 * Evaluación de la IA contra el modelo real (CRM-05.02.01.07).
 *
 * Hasta el 09-11-2026 de la IA generativa sólo se sabía que funcionaba alguna
 * vez: no había ningún banco de casos y ninguna cifra. Aquí está el acierto
 * por función de la última evaluación, su tendencia, cada caso que falla con
 * su porqué —y si lo decidió un modelo juez, dicho al lado— y el botón que
 * pasa el banco ahora. La evaluación corre en el servidor por tandas, así que
 * la pantalla sólo pregunta cómo va.
 */
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Cargando,
  Error as Fallo,
  FalloCompacto,
  Vacio,
} from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { useCargasSecundarias } from "@/lib/cargaSecundaria";
import { cifra, fechaHora } from "@/lib/formato";
import { cn } from "@/lib/utiles";

const Grafica = lazy(() =>
  import("@/componentes/graficas/Grafica").then((m) => ({
    default: m.Grafica,
  })),
);

interface PorFuncion {
  funcion: string;
  nombre: string;
  casos: number;
  aciertos: number;
  acierto: number | null;
  acierto_anterior: number | null;
  coste: number;
  latencia_media_ms: number;
  casos_con_juez: number;
  version_prompt: string;
}

interface Ejecucion {
  id: string;
  estado: string;
  origen: string;
  empezada_at: string | null;
  terminada_at: string | null;
  modelos: Record<string, string>;
  previstos: number;
  casos: number;
  aciertos: number;
  acierto: number | null;
  coste: number;
  latencia_media_ms: number;
  aviso: string;
  /** Sólo en la que está en curso: cuántos casos lleva. */
  hechos?: number;
}

interface Criterio {
  tipo: string;
  ok: boolean;
  porque: string;
  juez: boolean;
}

interface Fallido {
  caso_clave: string;
  caso_nombre: string;
  funcion: string;
  porque: string;
  criterios: Criterio[];
  modelo: string;
  latencia_ms: number;
}

interface Panel {
  umbral: number;
  cada_horas: number;
  proxima_at: string | null;
  ultima: Ejecucion | null;
  en_curso: Ejecucion | null;
  funciones: PorFuncion[];
  tendencia: Array<Record<string, number | string | null>>;
  fallos: Fallido[];
  banco: number | null;
}

interface Caso {
  clave: string;
  funcion: string;
  funcion_nombre: string;
  nombre: string;
  activo: boolean;
  origen: string;
  con_juez: boolean;
}

interface Detalle {
  hechos: number;
}

const pct = (v: number | null | undefined) =>
  v == null ? "—" : `${Math.round(v * 100)} %`;

export function EvaluacionIa() {
  const { t } = useTranslation();
  const [panel, setPanel] = useState<Panel | null>(null);
  const [casos, setCasos] = useState<Caso[]>([]);
  const [hechos, setHechos] = useState<number | null>(null);
  const [lanzando, setLanzando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  // El banco de casos se pide aparte del panel. Si no llega se dice: vaciarlo
  // en silencio lo pintaba como «el banco está vacío» e invitaba a llenarlo
  // otra vez.
  const { seguir, estado } = useCargasSecundarias();

  const cargar = useCallback(() => {
    llamar<Panel>("/api/v1/ia/evaluacion")
      .then((r) => setPanel(r.datos))
      .catch(setFallo);
    seguir("banco", () =>
      llamar<{ casos: Caso[] }>("/api/v1/ia/evaluacion/casos").then((r) =>
        setCasos(r.datos.casos),
      ),
    );
  }, [seguir]);
  const cargaDelBanco = estado("banco");
  useEffect(cargar, [cargar]);

  // Mientras hay una en curso se pregunta cómo va; al terminar, se recarga.
  const enCurso = panel?.en_curso?.id ?? "";
  useEffect(() => {
    if (!enCurso) return;
    const reloj = window.setInterval(() => {
      llamar<Detalle & { estado: string }>(
        `/api/v1/ia/evaluacion/ejecuciones/${enCurso}`,
      )
        .then((r) => {
          setHechos(r.datos.hechos);
          if (r.datos.estado !== "en_curso") cargar();
        })
        // Es un sondeo: si una vuelta falla, la siguiente vuelve a preguntar
        // dentro de cinco segundos y el avance sigue a la vista. Avisar de
        // cada vuelta perdida sería ruido sobre algo que se arregla solo.
        .catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(reloj);
  }, [enCurso, cargar]);

  async function evaluar() {
    setLanzando(true);
    try {
      await llamar("/api/v1/ia/evaluacion/ejecutar", {
        metodo: "POST",
        cuerpo: { funciones: [] },
      });
      setFallo(null);
      setHechos(0);
      cargar();
    } catch (e) {
      setFallo(e);
    } finally {
      setLanzando(false);
    }
  }

  async function activar(clave: string, activo: boolean) {
    try {
      await llamar(`/api/v1/ia/evaluacion/casos/${encodeURIComponent(clave)}`, {
        metodo: "PATCH",
        cuerpo: { activo },
      });
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  if (fallo && !panel) return <Fallo error={fallo} reintentar={cargar} />;
  if (!panel) return <Cargando />;

  const ultima = panel.ultima;
  const tono = (v: number | null) =>
    v == null
      ? ""
      : v >= panel.umbral
        ? "chip-dato--si"
        : v >= panel.umbral - 0.15
          ? "chip-dato--aviso"
          : "chip-dato--mal";

  return (
    <>
      <CabeceraPagina
        icono="fact_check"
        titulo={t("evaluacionIa.titulo")}
        entradilla={t("evaluacionIa.entradilla")}
        acciones={
          <button
            type="button"
            className="btn-primary"
            disabled={lanzando || Boolean(panel.en_curso)}
            onClick={() => void evaluar()}
          >
            <Icono nombre="play_arrow" tamano="sm" />
            {panel.en_curso
              ? t("evaluacionIa.evaluando", {
                  hechos: hechos ?? panel.en_curso.hechos ?? 0,
                  total: panel.en_curso.previstos,
                })
              : t("evaluacionIa.evaluarAhora")}
          </button>
        }
      />
      {fallo ? <Fallo error={fallo} /> : null}

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("evaluacionIa.ultima")}</h2>
        {ultima ? (
          <div role="status" className="flex flex-col gap-1 text-dato">
            <p className="text-ink">
              <span className={cn("chip-dato mr-2", tono(ultima.acierto))}>
                {pct(ultima.acierto)}
              </span>
              {t("evaluacionIa.resumen", {
                aciertos: ultima.aciertos,
                casos: ultima.casos,
                cuando: fechaHora(ultima.empezada_at),
                origen: t(`evaluacionIa.origenes.${ultima.origen}`, {
                  defaultValue: ultima.origen,
                }),
              })}
            </p>
            <p className="text-rotulo text-ink-muted">
              {t("evaluacionIa.modelo", {
                modelos: Array.from(
                  new Set(Object.values(ultima.modelos)),
                ).join(", "),
                coste: cifra(ultima.coste),
                latencia: cifra(ultima.latencia_media_ms),
              })}
            </p>
            {ultima.aviso ? (
              <p className="mt-1 rounded-lg border border-warning/40 bg-warning/5 p-2 text-rotulo text-ink">
                <Icono nombre="warning" tamano="sm" /> {ultima.aviso}
              </p>
            ) : null}
          </div>
        ) : (
          <Vacio
            titulo={t("evaluacionIa.nunca", { casos: panel.banco ?? 0 })}
            compacto
          />
        )}
        <p className="mt-2 text-rotulo text-ink-faint">
          {panel.cada_horas > 0
            ? t("evaluacionIa.programada", {
                horas: panel.cada_horas,
                umbral: pct(panel.umbral),
                proxima: panel.proxima_at
                  ? fechaHora(panel.proxima_at)
                  : t("evaluacionIa.trasLaPrimera"),
              })
            : t("evaluacionIa.sinProgramar", { umbral: pct(panel.umbral) })}
        </p>
      </section>

      <h2 className="section-label mb-1">{t("evaluacionIa.porFuncion")}</h2>
      <div className="mb-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {panel.funciones.map((f) => (
          <section key={f.funcion} className="card p-4">
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <h3 className="text-dato font-medium text-ink">{f.nombre}</h3>
              <span className={cn("chip-dato", tono(f.acierto))}>
                {pct(f.acierto)}
              </span>
            </div>
            {f.casos ? (
              <p className="text-rotulo text-ink-muted">
                {t("evaluacionIa.casosDe", {
                  aciertos: f.aciertos,
                  casos: f.casos,
                })}
                {f.acierto_anterior != null && f.acierto != null
                  ? ` · ${t("evaluacionIa.antes", { antes: pct(f.acierto_anterior) })}`
                  : ""}
                {` · ${t("evaluacionIa.latencia", { ms: cifra(f.latencia_media_ms) })}`}
              </p>
            ) : (
              <p className="text-rotulo text-ink-faint">
                {t("evaluacionIa.sinEvaluar")}
              </p>
            )}
            {f.casos_con_juez ? (
              <p className="mt-1 text-rotulo text-ink-faint">
                {t("evaluacionIa.conJuez", { n: f.casos_con_juez })}
              </p>
            ) : null}
            {f.version_prompt ? (
              <p className="mt-1 text-rotulo text-ink-faint">
                {t("evaluacionIa.version", { version: f.version_prompt })}
              </p>
            ) : null}
          </section>
        ))}
      </div>

      {panel.tendencia.length > 1 ? (
        <section className="card mb-4 p-4">
          <h2 className="section-label mb-1">{t("evaluacionIa.tendencia")}</h2>
          <Suspense fallback={<Cargando />}>
            <Grafica
              forma="lineas"
              titulo={t("evaluacionIa.tendencia")}
              datos={{
                filas: panel.tendencia.map((e) => ({
                  fecha: fechaHora(e.fecha),
                  acierto:
                    e.acierto == null
                      ? null
                      : Math.round(Number(e.acierto) * 100),
                })),
                ejeX: "fecha",
                rotuloX: t("evaluacionIa.fecha"),
                series: [
                  { clave: "acierto", rotulo: t("evaluacionIa.acierto") },
                ],
                unidad: "%",
              }}
            />
          </Suspense>
        </section>
      ) : null}

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("evaluacionIa.fallan")}</h2>
        {!ultima ? null : panel.fallos.length === 0 ? (
          <Vacio titulo={t("evaluacionIa.ningunFallo")} compacto />
        ) : (
          <ul className="flex flex-col gap-3">
            {panel.fallos.map((f) => (
              <li
                key={f.caso_clave}
                className="border-b border-ink-dim/30 pb-2 last:border-0"
              >
                <p className="text-dato text-ink">
                  <span className="chip-dato mr-2">
                    {panel.funciones.find((x) => x.funcion === f.funcion)
                      ?.nombre ?? f.funcion}
                  </span>
                  {f.caso_nombre}
                </p>
                <ul className="mt-1 flex flex-col gap-0.5">
                  {(f.criterios.length
                    ? f.criterios.filter((c) => !c.ok)
                    : [{ tipo: "", ok: false, porque: f.porque, juez: false }]
                  ).map((c, i) => (
                    <li key={i} className="text-rotulo text-ink-muted">
                      {c.juez ? (
                        <span className="chip-dato chip-dato--aviso mr-1">
                          {t("evaluacionIa.juez")}
                        </span>
                      ) : null}
                      {c.porque}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card p-4">
        <h2 className="section-label mb-1">{t("evaluacionIa.banco")}</h2>
        <p className="mb-2 text-rotulo text-ink-faint">
          {t("evaluacionIa.bancoAyuda")}
        </p>
        {cargaDelBanco.error ? (
          <FalloCompacto {...cargaDelBanco} />
        ) : casos.length === 0 ? (
          <Vacio titulo={t("evaluacionIa.bancoVacio")} compacto />
        ) : (
          <Rejilla
            titulo={t("evaluacionIa.banco")}
            cabeceras={[
              t("evaluacionIa.col.funcion"),
              t("evaluacionIa.col.caso"),
              t("evaluacionIa.col.origen"),
              t("evaluacionIa.col.juez"),
              t("evaluacionIa.col.activo"),
            ]}
          >
            {casos.map((c) => (
              <tr
                key={c.clave}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla>{c.funcion_nombre}</Casilla>
                <Casilla>{c.nombre}</Casilla>
                <Casilla>
                  {t(`evaluacionIa.origenesCaso.${c.origen}`, {
                    defaultValue: c.origen,
                  })}
                </Casilla>
                <Casilla>{c.con_juez ? t("evaluacionIa.juez") : ""}</Casilla>
                <Casilla>
                  <input
                    type="checkbox"
                    aria-label={t("evaluacionIa.activar", { caso: c.nombre })}
                    checked={c.activo}
                    onChange={(e) => void activar(c.clave, e.target.checked)}
                  />
                </Casilla>
              </tr>
            ))}
          </Rejilla>
        )}
      </section>
    </>
  );
}
