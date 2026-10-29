/**
 * Una instancia de proceso: por dónde va, qué pasó y qué se puede hacer
 * (CRM-00.03.05.14, CRM-00.03.03.07, CRM-00.03.02.12, CRM-00.03.05.16).
 *
 * **Las cuatro estaban publicadas y sin puerta.** El listado de instancias
 * abría la ficha genérica, que enseña columnas: `estado`, `paso_actual`, un
 * identificador. Y la pregunta que se hace delante de un proceso parado no es
 * ninguna de ésas — es «¿dónde está, qué pasó y cómo lo desatasco?».
 *
 * Por qué una pantalla a medida y no la ficha genérica: el gráfico necesita la
 * DEFINICIÓN con la que arrancó esta instancia, no la publicada. Enseñarla
 * sobre el gráfico nuevo señalaría nodos que esta instancia no tiene, que es
 * peor que no pintar nada. Se pide la versión exacta y se pinta sobre ella.
 *
 * **Las herramientas de rescate son tres y van juntas**, porque elegir entre
 * ellas es el trabajo: reintentar vuelve a ejecutar lo mismo —sirve si el
 * fallo fue pasajero—, corregir las variables arregla el dato, y saltar el
 * paso es para cuando ese paso no se va a poder completar nunca. Separarlas en
 * tres sitios obligaría a saber cuál se necesita antes de poder compararlas.
 *
 * Y saltar sólo ofrece **los destinos que el propio paso declara**: la lista
 * sale de la misma definición que mira el servidor, así que la pantalla no
 * puede ofrecer un salto que el servidor vaya a rechazar.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import {
  ALTO,
  ANCHO,
  aristas,
  colocar,
  type Definicion,
} from "@/lib/grafo";

interface NodoDeInstancia {
  paso: string;
  tipo: string;
  estado: string;
  veces: number;
  intentos: number;
  duracion_ms: number;
  error: string | null;
  tarea_pendiente: {
    id: string;
    titulo: string;
    estado: string;
    vence_at: string | null;
  } | null;
}

interface Grafico {
  instancia_id: string;
  proceso: string;
  version: number;
  estado: string;
  paso_actual: string | null;
  error: string | null;
  arrancada_at: string | null;
  finalizada_at: string | null;
  nodos: NodoDeInstancia[];
  recorrido: Record<string, unknown>[];
}

interface DefinicionPublicada {
  id: string;
  clave: string;
  version: number;
  nombre: string;
  estado: string;
  definicion: Definicion;
}

interface Analitica {
  proceso: string;
  instancias: number;
  concluyente?: boolean;
  aviso?: string;
  terminadas?: number;
  falladas?: number;
  ciclo_horas_medio: number | null;
  ciclo_horas_mediana: number | null;
  cuello_de_botella: string | null;
  pasos: {
    paso: string;
    tipo: string;
    veces: number;
    fallos: number;
    con_reintento: number;
    motor_ms_medio: number;
    espera_horas_media: number | null;
    espera_horas_mediana: number | null;
    pendientes_ahora: number;
  }[];
}

/** El color de cada estado de nodo. Del front, como dice la propia ruta. */
const TRAZO: Record<string, string> = {
  actual: "rgb(var(--accent))",
  fallido: "rgb(var(--danger))",
  compensado: "rgb(var(--warning))",
  recorrido: "rgb(var(--success))",
  pendiente: "rgb(var(--ink-dim))",
  no_recorrido: "rgb(var(--ink-dim))",
};

export function InstanciaDeProceso() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [grafico, setGrafico] = useState<Grafico | null>(null);
  const [definicion, setDefinicion] = useState<Definicion | null>(null);
  const [analitica, setAnalitica] = useState<Analitica | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Grafico>(`/api/v1/analitica-procesos/instancias/${id}/grafico`, {
      signal: control.signal,
    })
      .then(({ datos }) => {
        setGrafico(datos);
        // La definición de SU versión, no la publicada. Pintar sobre la nueva
        // señalaría nodos que esta instancia no tiene.
        void llamar<DefinicionPublicada[]>("/api/v1/procesos/definiciones", {
          signal: control.signal,
        })
          .then((r) =>
            setDefinicion(
              r.datos.find(
                (d) => d.clave === datos.proceso && d.version === datos.version,
              )?.definicion ?? null,
            ),
          )
          .catch(() => undefined);
        void llamar<Analitica>(
          `/api/v1/analitica-procesos/${encodeURIComponent(datos.proceso)}`,
          { signal: control.signal },
        )
          .then((r) => setAnalitica(r.datos))
          .catch(() => undefined);
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  if (fallo && !grafico) return <Fallo error={fallo} reintentar={cargar} />;
  if (!grafico) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={grafico.proceso}
        icono="account_tree"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            <span className="chip-dato">{grafico.estado}</span>
            {/* La versión SIEMPRE: sin ella no se sabe si se está viendo el
                proceso que se ejecutó o el que se publicó después. */}
            <span className="badge badge-muted">
              {t("instancia.version", { version: grafico.version })}
            </span>
            {grafico.paso_actual ? (
              <span className="text-2xs text-ink-muted">
                {t("instancia.paradaEn", { paso: grafico.paso_actual })}
              </span>
            ) : null}
          </span>
        }
      />

      {grafico.error ? (
        <p className="card mb-4 border-danger/40 p-3 text-2xs text-danger">
          {grafico.error}
        </p>
      ) : null}

      <ElGrafico grafico={grafico} definicion={definicion} />

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <ElCaminoEnOrden grafico={grafico} />
        <Rescate
          grafico={grafico}
          definicion={definicion}
          alHacer={(texto) => {
            setAviso(texto);
            cargar();
          }}
        />
      </div>

      <DondeSeAtasca analitica={analitica} />

      {/* Lo que ha pasado al pulsar, anunciado: sin esto, quien no ve la
          pantalla no se entera de que el rescate ha hecho algo. */}
      <p role="status" aria-live="polite" className="mt-3 text-2xs text-ink-muted">
        {aviso}
      </p>
    </>
  );
}

/**
 * Por dónde va, sobre su propio gráfico (CRM-00.03.05.14).
 *
 * El mismo lienzo que el editor de procesos, a propósito: si el proceso se
 * dibuja de una forma al escribirlo y de otra al seguirlo, hay que volver a
 * entender el diagrama cada vez que se cambia de pantalla.
 *
 * Lo único que cambia es el color del trazo, que dice el estado de cada paso.
 * Y el color nunca va solo: cada caja lleva su estado escrito debajo, porque
 * un diagrama que sólo se entiende viendo los colores no lo lee quien no los
 * distingue.
 */
function ElGrafico({
  grafico,
  definicion,
}: {
  grafico: Grafico;
  definicion: Definicion | null;
}) {
  const { t } = useTranslation();
  const nodos = useMemo(
    () => (definicion ? colocar(definicion) : []),
    [definicion],
  );
  const enlaces = useMemo(
    () => (definicion ? aristas(definicion) : []),
    [definicion],
  );
  const estados = useMemo(
    () => new Map(grafico.nodos.map((n) => [n.paso, n])),
    [grafico.nodos],
  );

  if (!definicion || nodos.length === 0) {
    return (
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("instancia.grafico")}</h2>
        <Vacio titulo={t("instancia.sinDefinicion")} compacto />
      </section>
    );
  }

  const porNombre = new Map(nodos.map((n) => [n.nombre, n]));
  const ancho = Math.max(400, ...nodos.map((n) => n.x + ANCHO));
  const alto = Math.max(280, ...nodos.map((n) => n.y + ALTO));

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("instancia.grafico")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">{t("instancia.graficoAyuda")}</p>
      <div className="overflow-auto rounded-xl border border-ink-dim/60 bg-paper">
        <svg width={ancho} height={alto} role="img" aria-label={t("instancia.grafico")}>
          {enlaces.map((a, i) => {
            const desde = porNombre.get(a.desde);
            const hasta = porNombre.get(a.hasta);
            if (!desde || !hasta) return null;
            return (
              <line
                key={`${a.desde}-${a.hasta}-${i}`}
                x1={desde.x + 140}
                y1={desde.y + 18}
                x2={hasta.x}
                y2={hasta.y + 18}
                stroke="rgb(var(--ink-dim))"
                strokeWidth={1.5}
              />
            );
          })}
          {nodos.map((n) => {
            const estado = estados.get(n.nombre)?.estado ?? "pendiente";
            return (
              <g key={n.nombre}>
                <rect
                  x={n.x}
                  y={n.y}
                  width={140}
                  height={44}
                  rx={8}
                  fill="rgb(var(--paper-light))"
                  stroke={TRAZO[estado] ?? "rgb(var(--ink-dim))"}
                  strokeWidth={estado === "actual" ? 2.5 : 1.5}
                />
                <text x={n.x + 10} y={n.y + 15} fill="rgb(var(--ink))" fontSize={11}>
                  {n.nombre}
                </text>
                {/* El estado ESCRITO, no sólo en el color del borde. */}
                <text x={n.x + 10} y={n.y + 28} fill="rgb(var(--ink-faint))" fontSize={9}>
                  {t(`instancia.estado.${estado}`)}
                </text>
                <text x={n.x + 10} y={n.y + 39} fill="rgb(var(--ink-faint))" fontSize={9}>
                  {n.tipo}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </section>
  );
}

/**
 * El camino en orden: el depurador (CRM-00.03.03.07).
 *
 * El estado por nodo dice dónde está; **no dice en qué orden pasó**, y con un
 * bucle por medio eso es la mitad de la historia: un paso puede estar en
 * «recorrido» por la tercera vuelta y lo que importa es qué decidió en cada
 * una. Esta lista es el log de decisiones de este registro concreto.
 */
function ElCaminoEnOrden({ grafico }: { grafico: Grafico }) {
  const { t } = useTranslation();
  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("instancia.camino")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">{t("instancia.caminoAyuda")}</p>
      {grafico.recorrido.length === 0 ? (
        <Vacio titulo={t("instancia.sinRecorrido")} compacto />
      ) : (
        <ol className="lista-acotada flex flex-col gap-1 pr-1">
          {grafico.recorrido.map((paso, i) => (
            <li
              key={`${String(paso.paso)}-${i}`}
              className="rounded-lg border border-ink-dim/30 bg-paper px-3 py-1.5 text-2xs"
            >
              <span className="font-medium text-ink">{String(paso.paso)}</span>{" "}
              <span className="text-ink-faint">{String(paso.resultado ?? "")}</span>
              {paso.error ? (
                <span className="ml-2 text-danger">{String(paso.error)}</span>
              ) : null}
              {typeof paso.intento === "number" && paso.intento > 1 ? (
                <span className="ml-2 chip-dato">
                  {t("instancia.intento", { n: paso.intento })}
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/**
 * Las tres herramientas de rescate (CRM-00.03.02.12).
 *
 * Juntas porque elegir entre ellas es el trabajo. Y las tres piden **motivo**
 * donde el servidor lo pide: cambiar el curso de un proceso en marcha sin
 * dejar escrito por qué es una decisión que nadie podrá revisar después.
 */
function Rescate({
  grafico,
  definicion,
  alHacer,
}: {
  grafico: Grafico;
  definicion: Definicion | null;
  alHacer: (aviso: string) => void;
}) {
  const { t } = useTranslation();
  const [motivo, setMotivo] = useState("");
  const [destino, setDestino] = useState("");
  const [variables, setVariables] = useState("{}");
  const [fallo, setFallo] = useState<unknown>(null);

  // Los destinos salen de la MISMA definición que mira el servidor, así que la
  // pantalla no puede ofrecer un salto que el servidor vaya a rechazar.
  const destinos = useMemo(() => {
    const paso = definicion?.pasos?.[grafico.paso_actual ?? ""];
    if (!paso) return [];
    const salidas: string[] = [];
    for (const clave of ["siguiente", "si_no", "al_fallar"] as const) {
      const valor = (paso as Record<string, unknown>)[clave];
      if (typeof valor === "string" && valor) salidas.push(valor);
    }
    const rutas = (paso as { rutas?: Record<string, string> }).rutas ?? {};
    salidas.push(...Object.values(rutas));
    const condiciones =
      (paso as { condiciones?: { entonces?: string }[] }).condiciones ?? [];
    for (const c of condiciones) if (c.entonces) salidas.push(c.entonces);
    return [...new Set(salidas)];
  }, [definicion, grafico.paso_actual]);

  async function pedir(ruta: string, cuerpo: Record<string, unknown>, aviso: string) {
    setFallo(null);
    try {
      await llamar(`/api/v1/instancias/${grafico.instancia_id}${ruta}`, {
        metodo: ruta === "/variables" ? "PATCH" : "POST",
        cuerpo,
      });
      alHacer(aviso);
    } catch (error) {
      setFallo(error);
    }
  }

  const motivoCorto = motivo.trim().length < 10;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("instancia.rescate")}</h2>
      <p className="mb-3 text-3xs text-ink-faint">{t("instancia.rescateAyuda")}</p>

      <label htmlFor="motivo-rescate" className="text-2xs text-ink-muted">
        {t("instancia.motivo")}
        <input
          id="motivo-rescate"
          value={motivo}
          onChange={(e) => setMotivo(e.target.value)}
          className="input-sm mt-1 w-full"
        />
      </label>
      {motivoCorto ? (
        <p className="mt-1 text-3xs text-ink-faint">{t("instancia.motivoCorto")}</p>
      ) : null}

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <button
          type="button"
          className="btn btn-secundario"
          onClick={() => void pedir("/reintentar", {}, t("instancia.hechoReintento"))}
        >
          {t("instancia.reintentar")}
        </button>
      </div>
      <p className="mt-1 text-3xs text-ink-faint">{t("instancia.reintentarAyuda")}</p>

      <div className="mt-3 border-t border-ink-dim/30 pt-3">
        <label htmlFor="destino-salto" className="text-2xs text-ink-muted">
          {t("instancia.saltarA")}
          <select
            id="destino-salto"
            value={destino}
            onChange={(e) => setDestino(e.target.value)}
            className="input-sm mt-1 w-full"
          >
            <option value="">{t("instancia.eligeDestino")}</option>
            {destinos.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <p className="mt-1 text-3xs text-ink-faint">{t("instancia.saltarAyuda")}</p>
        <button
          type="button"
          className="btn btn-secundario mt-2"
          disabled={!destino || motivoCorto}
          onClick={() =>
            void pedir("/saltar-paso", { destino, motivo }, t("instancia.hechoSalto"))
          }
        >
          {t("instancia.saltar")}
        </button>
      </div>

      <div className="mt-3 border-t border-ink-dim/30 pt-3">
        <label htmlFor="variables-rescate" className="text-2xs text-ink-muted">
          {t("instancia.variables")}
          <textarea
            id="variables-rescate"
            value={variables}
            onChange={(e) => setVariables(e.target.value)}
            rows={3}
            spellCheck={false}
            className="mt-1 w-full rounded-xl border border-ink-dim/60 bg-paper p-2 font-mono text-3xs text-ink"
          />
        </label>
        <p className="mt-1 text-3xs text-ink-faint">{t("instancia.variablesAyuda")}</p>
        <button
          type="button"
          className="btn btn-secundario mt-2"
          disabled={motivoCorto}
          onClick={() => {
            let valores: Record<string, unknown>;
            try {
              valores = JSON.parse(variables) as Record<string, unknown>;
            } catch {
              setFallo(new Error(t("instancia.variablesMal")));
              return;
            }
            void pedir(
              "/variables",
              { variables: valores, motivo },
              t("instancia.hechoVariables"),
            );
          }}
        >
          {t("instancia.corregir")}
        </button>
      </div>

      {fallo ? (
        <div className="mt-3">
          <Fallo error={fallo} />
        </div>
      ) : null}
    </section>
  );
}

/**
 * Dónde se atasca este proceso, no esta instancia (CRM-00.03.05.16).
 *
 * Va aquí y no en una pantalla aparte porque es la pregunta siguiente: se mira
 * una instancia parada y lo próximo que se quiere saber es si es ésta o es que
 * ese paso para siempre.
 *
 * **Con el «no es concluyente» delante.** Un cuello de botella deducido de
 * tres ejecuciones lleva a rediseñar un flujo que funcionaba.
 */
function DondeSeAtasca({ analitica }: { analitica: Analitica | null }) {
  const { t } = useTranslation();
  if (!analitica) return null;

  return (
    <section className="card mt-4 p-4">
      <h2 className="section-label mb-1">{t("instancia.atasco")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">{t("instancia.atascoAyuda")}</p>
      {analitica.instancias === 0 ? (
        <p className="text-2xs text-ink-muted">{analitica.aviso}</p>
      ) : (
        <>
          <p className="text-2xs text-ink">
            {t("instancia.ejecuciones", {
              cuantas: analitica.instancias,
              terminadas: analitica.terminadas ?? 0,
              falladas: analitica.falladas ?? 0,
            })}
          </p>
          {analitica.concluyente === false ? (
            <p className="mt-1 text-2xs text-warning">{analitica.aviso}</p>
          ) : null}
          {analitica.cuello_de_botella ? (
            <p className="mt-1 text-2xs text-ink">
              {t("instancia.cuello", { paso: analitica.cuello_de_botella })}
            </p>
          ) : null}
          {/* La mediana AL LADO de la media: con una espera de tres días en una
              de veinte, la media dice que todo va bien. */}
          {analitica.ciclo_horas_medio !== null ? (
            <p className="mt-1 text-3xs text-ink-muted">
              {t("instancia.ciclo", {
                media: analitica.ciclo_horas_medio,
                mediana: analitica.ciclo_horas_mediana ?? 0,
              })}
            </p>
          ) : null}
          <ul className="mt-2 divide-y divide-ink-dim/30">
            {analitica.pasos.map((p) => (
              <li key={p.paso} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
                <span className="text-2xs font-medium text-ink">{p.paso}</span>
                <span className="chip-dato">{p.tipo}</span>
                <span className="text-3xs text-ink-muted">
                  {t("instancia.veces", { veces: p.veces })}
                </span>
                {p.espera_horas_media !== null ? (
                  <span className="text-3xs text-ink-muted">
                    {t("instancia.espera", {
                      media: p.espera_horas_media,
                      mediana: p.espera_horas_mediana ?? 0,
                    })}
                  </span>
                ) : null}
                {p.fallos > 0 ? (
                  <span className="text-3xs text-danger">
                    {t("instancia.fallos", { cuantos: p.fallos })}
                  </span>
                ) : null}
                {p.pendientes_ahora > 0 ? (
                  <span className="text-3xs text-warning">
                    {t("instancia.pendientesAhora", { cuantas: p.pendientes_ahora })}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
