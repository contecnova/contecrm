/**
 * El embudo como tablero: la pantalla que define un CRM.
 *
 * Enseña CRM-03.01.01.01 (la oportunidad con su importe, su fecha de cierre y
 * su etapa), CRM-03.01.01.02 (varios pipelines, uno por línea de negocio) y
 * CRM-03.01.01.03 (las etapas configurables, que son las columnas).
 *
 * Esto faltaba, y es lo primero que echa en falta cualquiera que venga de una
 * herramienta del mercado. Pipedrive, Salesforce, HubSpot y Dynamics enseñan
 * las oportunidades como **columnas por etapa con tarjetas que se arrastran**,
 * y no por gusto estético: en una tabla, «¿cómo va el trimestre?» exige leer
 * cien filas y sumar de cabeza; en el tablero se ve de un vistazo dónde está
 * atascado el dinero. Y mover una oportunidad de etapa —el gesto más repetido
 * de un comercial— pasa de abrir la ficha, buscar el desplegable y guardar, a
 * arrastrar la tarjeta.
 *
 * **Se arrastra, y también se mueve sin arrastrar.** Cada tarjeta lleva un
 * selector de etapa: arrastrar no funciona con teclado ni con lector de
 * pantalla, y dejar el gesto como única forma de mover deja fuera a quien no
 * usa ratón.
 *
 * **La columna dice su total y su cuenta.** Un tablero que solo enseña tarjetas
 * obliga a contar a ojo, y contar a ojo es cómo se llega a una previsión que no
 * cuadra con el sistema.
 *
 * **El cambio se manda al servidor y, si lo rechaza, la tarjeta vuelve.** Las
 * etapas tienen criterios de salida: el servidor puede decir que no. Dejar la
 * tarjeta donde el usuario la soltó enseñaría un embudo que no existe.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { listar } from "@/lib/listados";
import { escalar, importe } from "@/lib/formato";
import { inicialesDe, nombreDe, usePersonas } from "@/lib/personas";
import { puede, type Sesion } from "@/lib/sesion";
import { cn } from "@/lib/utiles";

interface Etapa {
  id: string;
  clave: string;
  nombre: string;
  orden: number;
  probabilidad: number;
  terminal: boolean;
  ganada: boolean;
}

interface PipelineApi {
  id: string;
  nombre: string;
  por_defecto: boolean;
  etapas: Etapa[];
}

interface Oportunidad {
  id: string;
  nombre: string;
  codigo: string | null;
  importe: string | number;
  moneda: string;
  probabilidad: number;
  etapa_id: string;
  estado: string;
  fecha_cierre: string | null;
  cuenta_id: string | null;
  owner_id: string | null;
}

/** Si la fecha de cierre ya pasó y la oportunidad sigue abierta. */
function vencida(o: Oportunidad): boolean {
  if (!o.fecha_cierre || o.estado !== "abierta") return false;
  const cierre = Date.parse(o.fecha_cierre);
  return !Number.isNaN(cierre) && cierre < Date.now();
}

/** Ver `hayCola`: por debajo de esto no hay nada que acotar. */
const COLUMNA_LARGA = 12;

export function Pipeline({ sesion }: { sesion: Sesion | null }) {
  const personas = usePersonas();
  const { t } = useTranslation();
  const [pipelines, setPipelines] = useState<PipelineApi[] | null>(null);
  const [abierto, setAbierto] = useState("");
  const [oportunidades, setOportunidades] = useState<Oportunidad[] | null>(
    null,
  );
  const [fallo, setFallo] = useState<unknown>(null);
  const [arrastrando, setArrastrando] = useState<string | null>(null);
  const [sobre, setSobre] = useState<string | null>(null);
  const [moviendo, setMoviendo] = useState<string | null>(null);

  useEffect(() => {
    const control = new AbortController();
    listar<PipelineApi>("/api/v1/pipelines", { signal: control.signal })
      .then((lista) => {
        setPipelines(lista);
        setAbierto(lista.find((p) => p.por_defecto)?.id ?? lista[0]?.id ?? "");
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  const cargar = useCallback((signal?: AbortSignal) => {
    // Se piden muchas porque el tablero es una vista de conjunto: paginarlo
    // haría que una columna enseñara media verdad y el total, otra.
    listar<Oportunidad>("/api/v1/opportunities?limite=200", { signal })
      .then(setOportunidades)
      .catch(salvoCancelacion(setFallo));
  }, []);

  useEffect(() => {
    const control = new AbortController();
    cargar(control.signal);
    return () => control.abort();
  }, [cargar]);

  const pipeline = pipelines?.find((p) => p.id === abierto) ?? pipelines?.[0];
  const etapas = useMemo(
    () => [...(pipeline?.etapas ?? [])].sort((a, b) => a.orden - b.orden),
    [pipeline],
  );

  /**
   * A partir de cuántas oportunidades se acota el tablero a una pantalla.
   *
   * Con pocas, fijar el alto deja un recuadro vacío de pantalla entera; con
   * muchas, no fijarlo estira el tablero y deja las demás columnas en blanco
   * durante miles de píxeles. Mismo umbral y mismo motivo que en la ficha de
   * cliente.
   */
  const hayCola = (oportunidades ?? []).length >= COLUMNA_LARGA;

  const porEtapa = useMemo(() => {
    const mapa = new Map<string, Oportunidad[]>();
    for (const o of oportunidades ?? []) {
      if (pipeline && !etapas.some((e) => e.id === o.etapa_id)) continue;
      mapa.set(o.etapa_id, [...(mapa.get(o.etapa_id) ?? []), o]);
    }
    return mapa;
  }, [oportunidades, etapas, pipeline]);

  const puedeMover = puede(sesion, "opportunity:write");

  async function mover(oportunidadId: string, etapaId: string) {
    const previas = oportunidades;
    setMoviendo(oportunidadId);
    // Se mueve en pantalla al instante y se deshace si el servidor dice que no:
    // esperar a la respuesta para pintar hace que arrastrar se sienta roto.
    setOportunidades((o) =>
      (o ?? []).map((x) =>
        x.id === oportunidadId ? { ...x, etapa_id: etapaId } : x,
      ),
    );
    try {
      await llamar(`/api/v1/opportunities/${oportunidadId}/etapa`, {
        metodo: "POST",
        cuerpo: { etapa_id: etapaId },
      });
      setFallo(null);
    } catch (error) {
      // Las etapas tienen criterios de salida y el servidor puede rechazar el
      // movimiento. La tarjeta vuelve a su sitio: dejarla donde se soltó
      // enseñaría un embudo que no existe.
      setOportunidades(previas);
      setFallo(error);
    } finally {
      setMoviendo(null);
      setArrastrando(null);
      setSobre(null);
    }
  }

  if (fallo && !oportunidades)
    return <Fallo error={fallo} reintentar={() => cargar()} />;
  if (!pipelines || !oportunidades) return <Cargando />;
  if (etapas.length === 0) {
    return (
      <>
        <CabeceraPagina titulo={t("pipeline.titulo")} icono="view_kanban" />
        <Vacio
          icono="view_kanban"
          titulo={t("pipeline.sinPipeline")}
          detalle={t("pipeline.sinPipelineDetalle")}
          accion={{
            texto: t("pipeline.irAConfigurar"),
            a: "/m/oportunidades?r=Pipelines&nuevo=1",
          }}
        />
      </>
    );
  }

  return (
    <>
      <CabeceraPagina
        titulo={t("pipeline.titulo")}
        entradilla={t("pipeline.entradilla")}
        icono="view_kanban"
        acciones={
          pipelines.length > 1 ? (
            <>
              <label htmlFor="pipeline-elegir" className="sr-only">
                {t("pipeline.elegir")}
              </label>
              <select
                id="pipeline-elegir"
                className="input-sm"
                value={abierto}
                onChange={(e) => setAbierto(e.target.value)}
              >
                {pipelines.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.nombre}
                  </option>
                ))}
              </select>
            </>
          ) : null
        }
      />

      {fallo ? (
        <div className="mb-4">
          <Fallo error={fallo} />
        </div>
      ) : null}

      {/* El tablero se queda en una pantalla y **cada columna recorre la
          suya**. Sin esto, una etapa con cincuenta oportunidades estiraba el
          tablero entero: las demás columnas quedaban vacías durante miles de
          píxeles y para volver a la cabecera había que subir la página.

          El alto se fija sólo cuando hay de qué (`COLUMNA_LARGA`): con un
          tablero recién abierto, o con tres oportunidades, fijarlo deja un
          recuadro vacío de pantalla entera. Y tiene que ser un alto DEFINIDO y
          no un máximo: con un máximo, los hijos no se comprimen y el contenido
          se sale por abajo.

          Es la misma regla que la ficha de cliente, y a propósito: dos
          pantallas que enseñan muchas filas en cajas de al lado se comportan
          igual. */}
      <div
        className={cn(
          "-mx-1 flex gap-3 overflow-x-auto pb-4",
          hayCola && "lg:h-[calc(100vh-18rem)]",
        )}
      >
        {etapas.map((etapa) => {
          const dentro = porEtapa.get(etapa.id) ?? [];
          const total = dentro.reduce(
            (suma, o) => suma + Number(o.importe || 0),
            0,
          );

          return (
            <section
              key={etapa.id}
              aria-label={etapa.nombre}
              onDragOver={(e) => {
                if (!arrastrando || !puedeMover) return;
                e.preventDefault();
                setSobre(etapa.id);
              }}
              onDragLeave={() => setSobre((s) => (s === etapa.id ? null : s))}
              onDrop={(e) => {
                e.preventDefault();
                if (arrastrando && puedeMover)
                  void mover(arrastrando, etapa.id);
              }}
              className={`flex w-72 shrink-0 flex-col overflow-hidden rounded-xl border p-2 transition-colors ${
                sobre === etapa.id
                  ? "border-accent bg-accent/5"
                  : "border-ink-dim/60 bg-paper-dark"
              }`}
            >
              <header className="shrink-0 px-1.5 pb-2 pt-1">
                <div className="flex items-baseline justify-between gap-2">
                  <h2 className="truncate text-xs font-semibold text-ink">
                    {etapa.nombre}
                  </h2>
                  <span className="shrink-0 text-3xs text-ink-faint">
                    {dentro.length}
                  </span>
                </div>
                {/* El total de la columna: sin él hay que contar a ojo, y contar
                    a ojo es cómo se llega a una previsión que no cuadra. */}
                <p className="mt-0.5 text-2xs text-ink-muted">
                  {importe(total)}
                  {etapa.terminal ? null : ` · ${etapa.probabilidad} %`}
                </p>
              </header>

              <div className="flex min-h-24 flex-col gap-2 overflow-y-auto lg:min-h-0 lg:flex-1">
                {dentro.length === 0 ? (
                  <p className="px-1.5 py-6 text-center text-3xs text-ink-faint">
                    {t("pipeline.columnaVacia")}
                  </p>
                ) : (
                  dentro.map((o) => (
                    <article
                      key={o.id}
                      draggable={puedeMover}
                      onDragStart={() => setArrastrando(o.id)}
                      onDragEnd={() => {
                        setArrastrando(null);
                        setSobre(null);
                      }}
                      className={`card p-2.5 ${puedeMover ? "cursor-grab active:cursor-grabbing" : ""} ${
                        moviendo === o.id ? "opacity-50" : ""
                      }`}
                    >
                      <Link
                        to={`/m/oportunidades/oportunidad/${o.id}`}
                        className="block truncate text-xs font-medium text-ink hover:underline"
                        title={o.nombre}
                      >
                        {o.nombre}
                      </Link>
                      {/* El importe, grande. Un número del mismo tamaño que
                          todo lo demás no distingue una oportunidad de doce mil
                          euros de una de doce millones, que es lo primero que
                          se mira en un tablero. */}
                      <p className="mt-1 text-sm font-semibold leading-none text-ink">
                        {importe(o.importe, o.moneda)}
                      </p>

                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        {o.fecha_cierre ? (
                          /* En rojo si ya pasó y sigue abierta: una fecha de
                             cierre vencida es la señal más barata de que el
                             embudo no está al día, y en gris se pierde. */
                          <span
                            className={`inline-flex items-center gap-1 text-3xs ${
                              vencida(o)
                                ? "font-medium text-danger"
                                : "text-ink-faint"
                            }`}
                          >
                            <Icono nombre="event" tamano="sm" />
                            {escalar(o.fecha_cierre)}
                          </span>
                        ) : null}
                        <span className="rounded-lg border border-ink-dim/60 px-1.5 py-0.5 text-3xs text-ink-muted">
                          {o.probabilidad} %
                        </span>
                        {o.owner_id ? (
                          <span
                            className="ml-auto inline-flex items-center gap-1 text-3xs text-ink-muted"
                            title={nombreDe(personas, o.owner_id)}
                          >
                            <span
                              aria-hidden
                              className="grid h-5 w-5 place-items-center rounded-full bg-paper-sunk text-[0.6rem] font-medium"
                            >
                              {inicialesDe(nombreDe(personas, o.owner_id))}
                            </span>
                          </span>
                        ) : null}
                      </div>

                      {/* Mover sin arrastrar. Arrastrar no funciona con teclado
                          ni con lector de pantalla, y dejarlo como única forma
                          deja fuera a quien no usa ratón. */}
                      {puedeMover ? (
                        <>
                          <label htmlFor={`etapa-${o.id}`} className="sr-only">
                            {t("pipeline.moverA", { oportunidad: o.nombre })}
                          </label>
                          {/* Escondido hasta que recibe el foco. Con el
                              selector siempre visible, cada tarjeta repetía el
                              nombre de su propia columna y el tablero se leía
                              como un formulario. Con el ratón se arrastra; con
                              teclado se tabula hasta aquí y aparece. */}
                          <select
                            id={`etapa-${o.id}`}
                            value={o.etapa_id}
                            onChange={(e) => void mover(o.id, e.target.value)}
                            className="input-sm mt-2 text-3xs sr-only focus:not-sr-only focus:relative"
                          >
                            {etapas.map((e) => (
                              <option key={e.id} value={e.id}>
                                {e.nombre}
                              </option>
                            ))}
                          </select>
                        </>
                      ) : null}
                    </article>
                  ))
                )}
              </div>
            </section>
          );
        })}
      </div>
    </>
  );
}
