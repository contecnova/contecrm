/**
 * Controles del GRC: de dónde sale cada uno, qué prueba y a qué está enlazado
 * (CRM-07.03.02.12, CRM-07.03.02.13, CRM-07.03.02.14, CRM-07.03.02.15).
 *
 * Pedido el 09-11-2026: «que todo lo que hay en la aplicación esté controlado
 * por el GRC». Medido ese día: 0 de 781 capacidades hechas con control. Aquí
 * se instalan los controles de serie —uno por familia del catálogo, uno por
 * regla de segregación, uno por requisito TCSEC y el de la revisión de
 * accesos—, se evalúan con la evidencia que pone el sistema y se ajustan o se
 * desactivan uno a uno.
 *
 * **Anclado no es comprobado**, y la cabecera lo enseña separado: la
 * cobertura anclada sube al cien por cien el día que se instala; la
 * verificada sólo cuenta lo que una evaluación en plazo dio por bueno.
 *
 * Enlazado en los dos sentidos: cada control lleva a su regla, su requisito o
 * su campaña, y esas pantallas vuelven aquí con `?control=`.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { usePuedeOperar } from "@/lib/permisos";
import { cn } from "@/lib/utiles";

interface Ultima {
  fecha: string;
  resultado: string;
  proxima_at: string | null;
}

interface Control {
  codigo: string;
  nombre: string;
  descripcion: string;
  tipo: string;
  frecuencia: string;
  activo: boolean;
  automatico: boolean;
  capacidades: { id: string; titulo: string }[];
  riesgos: string[];
  marcos: { marco: string; referencia: string }[];
  fuente_evidencia: string;
  origen: string;
  referencia: string;
  ajustado: boolean;
  ultima_evaluacion: Ultima | null;
}

interface Hallazgo {
  codigo: string;
  control: string;
  titulo: string;
  riesgo: string;
  estado: string;
  motivo_cierre: string;
  detectado_at: string;
}

interface Evidencia {
  referencia: string;
  descripcion: string;
  caduca_at: string | null;
  vigente: boolean;
}

interface Detalle extends Control {
  evaluaciones: {
    fecha: string;
    resultado: string;
    evidencia: Record<string, unknown>;
    plan_accion: string;
    proxima_at: string | null;
  }[];
  hallazgos: Hallazgo[];
}

interface Cobertura {
  medible: boolean;
  capacidades?: number;
  con_control?: number;
  verificadas?: number;
  pct?: number;
  pct_verificado?: number;
}

interface DeSerie {
  esperados: number;
  instalados: number;
}

const ORIGENES = [
  "familia",
  "segregacion",
  "tcsec",
  "recertificacion",
  "manual",
] as const;

const TONO: Record<string, string> = {
  efectivo: "chip-dato--si",
  parcial: "chip-dato--aviso",
  inefectivo: "chip-dato--mal",
};

/** A qué pantalla lleva el origen del control: el otro sentido del enlace. */
export function enlaceDeOrigen(c: {
  origen: string;
  referencia: string;
}): string | null {
  const ref = encodeURIComponent(c.referencia);
  if (c.origen === "segregacion") return `/segregacion?regla=${ref}`;
  if (c.origen === "tcsec") return `/tcsec?requisito=${ref}`;
  if (c.origen === "recertificacion") return "/revision-accesos";
  if (c.origen === "familia") return "/cumplimiento";
  return null;
}

export function ControlesGrc() {
  const { t } = useTranslation();
  const puede = usePuedeOperar();
  const [params, setParams] = useSearchParams();
  const elegido = params.get("control") ?? "";
  const [controles, setControles] = useState<Control[] | null>(null);
  const [cobertura, setCobertura] = useState<Cobertura | null>(null);
  const [serie, setSerie] = useState<DeSerie | null>(null);
  const [hallazgos, setHallazgos] = useState<Hallazgo[]>([]);
  const [origen, setOrigen] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => {
    llamar<Control[]>("/api/v1/grc/controles")
      .then((r) => setControles(Array.isArray(r.datos) ? r.datos : []))
      .catch((e) => setFallo(e));
    llamar<Cobertura>("/api/v1/grc/cobertura?solo_hechas=true")
      .then((r) => setCobertura(r.datos))
      .catch(() => setCobertura(null));
    llamar<DeSerie>("/api/v1/grc/de-serie")
      .then((r) => setSerie(r.datos))
      .catch(() => setSerie(null));
    llamar<Hallazgo[]>("/api/v1/grc/hallazgos")
      .then((r) => setHallazgos(Array.isArray(r.datos) ? r.datos : []))
      .catch(() => setHallazgos([]));
  }, []);
  useEffect(cargar, [cargar]);

  async function accion(
    ruta: string,
    texto: (d: Record<string, unknown>) => string,
  ) {
    setOcupado(true);
    setAviso("");
    try {
      const r = await llamar<Record<string, unknown>>(ruta, {
        metodo: "POST",
      });
      setAviso(texto(r.datos));
      setFallo(null);
      cargar();
    } catch (e) {
      setFallo(e);
    } finally {
      setOcupado(false);
    }
  }

  const visibles = useMemo(
    () =>
      (controles ?? []).filter((c) =>
        !origen ? true : (c.origen || "manual") === origen,
      ),
    [controles, origen],
  );

  if (fallo && !controles) return <Fallo error={fallo} reintentar={cargar} />;
  if (!controles) return <Cargando />;

  const escribir = puede("POST", "/api/v1/grc/de-serie");

  return (
    <>
      <CabeceraPagina
        icono="fact_check"
        titulo={t("controlesGrc.titulo")}
        entradilla={t("controlesGrc.entradilla")}
        acciones={
          escribir ? (
            <>
              <button
                type="button"
                className="btn-secondary"
                disabled={ocupado}
                onClick={() =>
                  void accion("/api/v1/grc/de-serie", (d) => {
                    const c = (d.controles ?? {}) as Record<
                      string,
                      { creado: number; actualizado: number }
                    >;
                    const n = Object.values(c).reduce(
                      (s, x) => s + x.creado + x.actualizado,
                      0,
                    );
                    return t("controlesGrc.instalados", { n });
                  })
                }
              >
                <Icono nombre="library_add" tamano="sm" />
                {t("controlesGrc.instalar")}
              </button>
              <button
                type="button"
                className="btn-secondary"
                disabled={ocupado}
                onClick={() =>
                  void accion("/api/v1/grc/segregacion/sincronizar", (d) =>
                    t("controlesGrc.sincronizada", {
                      reglas: d.reglas,
                      abiertos: d.hallazgos_abiertos,
                      evidencias: d.evidencias,
                    }),
                  )
                }
              >
                <Icono nombre="sync" tamano="sm" />
                {t("controlesGrc.sincronizar")}
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={ocupado}
                onClick={() =>
                  void accion(
                    "/api/v1/grc/controles/evaluar-automaticos",
                    (d) =>
                      t("controlesGrc.evaluados", {
                        n: d.controles,
                        detalle: Object.entries(
                          (d.por_resultado ?? {}) as Record<string, number>,
                        )
                          .map(
                            ([k, v]) =>
                              `${t(`controlesGrc.resultados.${k}`)}: ${v}`,
                          )
                          .join(" · "),
                      }),
                  )
                }
              >
                <Icono nombre="play_arrow" tamano="sm" />
                {ocupado
                  ? t("controlesGrc.trabajando")
                  : t("controlesGrc.evaluar")}
              </button>
            </>
          ) : null
        }
      />
      <div role="status" className="mb-3">
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
        {fallo ? <Fallo error={fallo} /> : null}
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="card p-4">
          <p className="section-label">{t("controlesGrc.anclada")}</p>
          <p className="text-grande tabular-nums text-ink">
            {cobertura?.medible
              ? t("controlesGrc.deTotal", {
                  n: cobertura.con_control,
                  total: cobertura.capacidades,
                  pct: cobertura.pct,
                })
              : t("controlesGrc.sinMedir")}
          </p>
          <p className="text-rotulo text-ink-faint">
            {t("controlesGrc.ancladaAyuda")}
          </p>
        </div>
        <div className="card p-4">
          <p className="section-label">{t("controlesGrc.verificada")}</p>
          <p className="text-grande tabular-nums text-ink">
            {cobertura?.medible
              ? t("controlesGrc.deTotal", {
                  n: cobertura.verificadas,
                  total: cobertura.capacidades,
                  pct: cobertura.pct_verificado,
                })
              : t("controlesGrc.sinMedir")}
          </p>
          <p className="text-rotulo text-ink-faint">
            {t("controlesGrc.verificadaAyuda")}
          </p>
        </div>
        <div className="card p-4">
          <p className="section-label">{t("controlesGrc.hallazgos")}</p>
          <p className="text-grande tabular-nums text-ink">
            {hallazgos.length}
          </p>
          <p className="text-rotulo text-ink-faint">
            {t("controlesGrc.hallazgosAyuda")}
          </p>
        </div>
        <div className="card p-4">
          <p className="section-label">{t("controlesGrc.deSerie")}</p>
          <p className="text-grande tabular-nums text-ink">
            {serie
              ? t("controlesGrc.instaladosDe", {
                  n: serie.instalados,
                  total: serie.esperados,
                })
              : "—"}
          </p>
          <p className="text-rotulo text-ink-faint">
            {t("controlesGrc.deSerieAyuda")}
          </p>
        </div>
      </div>

      {elegido ? (
        <DetalleControl
          key={elegido}
          codigo={elegido}
          escribir={escribir}
          alCerrar={() => setParams({})}
          alCambiar={cargar}
        />
      ) : null}

      <section className="card mb-4 p-4">
        <div className="mb-2 flex flex-wrap items-end justify-between gap-3">
          <h2 className="section-label">{t("controlesGrc.controles")}</h2>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("controlesGrc.origen")}
            <select
              className="input-base w-auto"
              value={origen}
              onChange={(e) => setOrigen(e.target.value)}
            >
              <option value="">{t("controlesGrc.todos")}</option>
              {ORIGENES.map((o) => (
                <option key={o} value={o}>
                  {t(`controlesGrc.origenes.${o}`)}
                </option>
              ))}
            </select>
          </label>
        </div>
        {visibles.length === 0 ? (
          <Vacio compacto titulo={t("controlesGrc.sinControles")} />
        ) : (
          <Rejilla
            titulo={t("controlesGrc.controles")}
            cabeceras={[
              t("controlesGrc.control"),
              t("controlesGrc.origen"),
              t("controlesGrc.ultima"),
              t("controlesGrc.capacidades"),
              t("controlesGrc.activo"),
            ]}
          >
            {visibles.map((c) => (
              <FilaControl
                key={c.codigo}
                control={c}
                escribir={escribir}
                alElegir={() => setParams({ control: c.codigo })}
                alCambiar={cargar}
              />
            ))}
          </Rejilla>
        )}
      </section>

      <section className="card p-4">
        <h2 className="section-label mb-1">
          {t("controlesGrc.hallazgosAbiertos")}
        </h2>
        {hallazgos.length === 0 ? (
          <p className="text-dato text-ink-muted">
            {t("controlesGrc.sinHallazgos")}
          </p>
        ) : (
          <ul className="lista-acotada divide-y divide-ink-dim/30">
            {hallazgos.map((h) => (
              <li key={h.codigo} className="py-2 text-dato">
                <p className="text-ink">{h.titulo}</p>
                <p className="text-rotulo text-ink-faint">
                  <button
                    type="button"
                    className="btn-link"
                    onClick={() => setParams({ control: h.control })}
                  >
                    {h.control}
                  </button>{" "}
                  {t("controlesGrc.riesgoDesde", {
                    riesgo: h.riesgo || "—",
                    fecha: h.detectado_at.slice(0, 10),
                  })}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function FilaControl({
  control: c,
  escribir,
  alElegir,
  alCambiar,
}: {
  control: Control;
  escribir: boolean;
  alElegir: () => void;
  alCambiar: () => void;
}) {
  const { t } = useTranslation();
  const [fallo, setFallo] = useState<unknown>(null);
  const destino = enlaceDeOrigen(c);

  async function activar(activo: boolean) {
    try {
      await llamar(
        `/api/v1/grc/controles/${encodeURIComponent(c.codigo)}/activo`,
        { metodo: "POST", cuerpo: { activo } },
      );
      setFallo(null);
      alCambiar();
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <tr className="border-b border-ink-dim/30 last:border-0">
      <Casilla className="min-w-[16rem]">
        <button
          type="button"
          className="text-left text-ink hover:text-accent hover:underline"
          onClick={alElegir}
        >
          <span className="font-mono text-rotulo text-ink-muted">
            {c.codigo}
          </span>{" "}
          {c.nombre}
        </button>
        {c.ajustado ? (
          <span className="chip-dato ml-2">{t("controlesGrc.ajustado")}</span>
        ) : null}
        {fallo ? <Fallo error={fallo} /> : null}
      </Casilla>
      <Casilla>
        <span className="chip-dato">
          {t(`controlesGrc.origenes.${c.origen || "manual"}`)}
        </span>
        {destino ? (
          <Link to={destino} className="btn-link ml-2">
            {c.referencia || t("controlesGrc.ver")}
          </Link>
        ) : null}
      </Casilla>
      <Casilla>
        {c.ultima_evaluacion ? (
          <span
            className={cn(
              "chip-dato",
              TONO[c.ultima_evaluacion.resultado] ?? "",
            )}
            title={c.ultima_evaluacion.fecha}
          >
            {t(`controlesGrc.resultados.${c.ultima_evaluacion.resultado}`)}
          </span>
        ) : (
          <span className="text-rotulo text-ink-faint">
            {t("controlesGrc.nuncaEvaluado")}
          </span>
        )}
      </Casilla>
      <Casilla className="text-right tabular-nums">
        {c.capacidades.length}
      </Casilla>
      <Casilla className="text-center">
        <input
          type="checkbox"
          checked={c.activo}
          disabled={!escribir}
          aria-label={t("controlesGrc.activarControl", { codigo: c.codigo })}
          onChange={(e) => void activar(e.target.checked)}
        />
      </Casilla>
    </tr>
  );
}

function DetalleControl({
  codigo,
  escribir,
  alCerrar,
  alCambiar,
}: {
  codigo: string;
  escribir: boolean;
  alCerrar: () => void;
  alCambiar: () => void;
}) {
  const { t } = useTranslation();
  const [d, setD] = useState<Detalle | null>(null);
  const [evidencias, setEvidencias] = useState<Evidencia[]>([]);
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");

  const cargar = useCallback(() => {
    const c = encodeURIComponent(codigo);
    llamar<Detalle>(`/api/v1/grc/controles/${c}`)
      .then((r) => setD(r.datos))
      .catch((e) => setFallo(e));
    llamar<Evidencia[]>(`/api/v1/grc/evidencias?control=${c}`)
      .then((r) => setEvidencias(Array.isArray(r.datos) ? r.datos : []))
      .catch(() => setEvidencias([]));
  }, [codigo]);
  useEffect(cargar, [cargar]);

  async function evaluar() {
    try {
      const r = await llamar<{
        evaluado: boolean;
        resultado?: string;
        motivo?: string;
      }>(
        `/api/v1/grc/controles/${encodeURIComponent(codigo)}/evaluar-automatico`,
        { metodo: "POST" },
      );
      setAviso(
        r.datos.evaluado
          ? t("controlesGrc.evaluadoComo", {
              resultado: t(`controlesGrc.resultados.${r.datos.resultado}`),
            })
          : t("controlesGrc.noEvaluado", { motivo: r.datos.motivo }),
      );
      setFallo(null);
      cargar();
      alCambiar();
    } catch (e) {
      setFallo(e);
    }
  }

  if (fallo && !d) return <Fallo error={fallo} />;
  if (!d) return <Cargando />;
  const destino = enlaceDeOrigen(d);
  const ultima = d.evaluaciones[0];

  return (
    <section className="card mb-4 p-4" aria-label={d.nombre}>
      <div className="mb-2 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="section-label">{d.codigo}</h2>
          <p className="text-titulin text-ink">{d.nombre}</p>
          <p className="text-rotulo text-ink-muted">{d.descripcion}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {destino ? (
            <Link to={destino} className="btn-secondary">
              <Icono nombre="link" tamano="sm" />
              {t(`controlesGrc.irA.${d.origen}`)}
            </Link>
          ) : null}
          {escribir && d.fuente_evidencia ? (
            <button
              type="button"
              className="btn-primary"
              onClick={() => void evaluar()}
            >
              <Icono nombre="play_arrow" tamano="sm" />
              {t("controlesGrc.evaluarEste")}
            </button>
          ) : null}
          <button type="button" className="btn-secondary" onClick={alCerrar}>
            {t("controlesGrc.cerrar")}
          </button>
        </div>
      </div>
      <div role="status">
        {aviso ? <p className="mb-2 text-dato text-success">{aviso}</p> : null}
        {fallo ? <Fallo error={fallo} /> : null}
      </div>
      <dl className="mb-3 grid gap-x-4 gap-y-1 text-dato sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-rotulo text-ink-faint">
            {t("controlesGrc.fuente")}
          </dt>
          <dd className="text-ink">
            {d.fuente_evidencia || t("controlesGrc.aMano")}
          </dd>
        </div>
        <div>
          <dt className="text-rotulo text-ink-faint">
            {t("controlesGrc.frecuencia")}
          </dt>
          <dd className="text-ink">{d.frecuencia}</dd>
        </div>
        <div>
          <dt className="text-rotulo text-ink-faint">
            {t("controlesGrc.capacidades")}
          </dt>
          <dd className="text-ink">{d.capacidades.length}</dd>
        </div>
        <div>
          <dt className="text-rotulo text-ink-faint">
            {t("controlesGrc.marcos")}
          </dt>
          <dd className="text-ink">
            {d.marcos.map((m) => `${m.marco} ${m.referencia}`).join(", ") ||
              "—"}
          </dd>
        </div>
      </dl>

      <h3 className="section-label mb-1">{t("controlesGrc.ultimaEval")}</h3>
      {ultima ? (
        <div className="mb-3">
          <p className="text-dato">
            <span
              className={cn("chip-dato mr-2", TONO[ultima.resultado] ?? "")}
            >
              {t(`controlesGrc.resultados.${ultima.resultado}`)}
            </span>
            {t("controlesGrc.elDia", {
              fecha: ultima.fecha,
              proxima: ultima.proxima_at ?? "—",
            })}
          </p>
          {ultima.plan_accion ? (
            <p className="mt-1 text-dato text-warning">{ultima.plan_accion}</p>
          ) : null}
          <details className="mt-1">
            <summary className="cursor-pointer text-rotulo text-ink-muted">
              {t("controlesGrc.verEvidencia")}
            </summary>
            <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-all rounded bg-paper-light p-2 font-mono text-rotulo text-ink-muted">
              {JSON.stringify(ultima.evidencia, null, 2)}
            </pre>
          </details>
        </div>
      ) : (
        <p className="mb-3 text-dato text-ink-muted">
          {t("controlesGrc.nuncaEvaluado")}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="section-label mb-1">{t("controlesGrc.hallazgos")}</h3>
          {d.hallazgos.length === 0 ? (
            <p className="text-dato text-ink-muted">
              {t("controlesGrc.sinHallazgos")}
            </p>
          ) : (
            <ul className="lista-acotada divide-y divide-ink-dim/30">
              {d.hallazgos.map((h) => (
                <li key={h.codigo} className="py-1.5 text-dato">
                  <span
                    className={cn(
                      "chip-dato mr-2",
                      h.estado === "abierto" ? "chip-dato--mal" : "",
                    )}
                  >
                    {h.estado === "abierto"
                      ? t("controlesGrc.abierto")
                      : t(
                          `controlesGrc.cierres.${h.motivo_cierre || "resuelto"}`,
                        )}
                  </span>
                  {h.titulo}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className="section-label mb-1">{t("controlesGrc.evidencias")}</h3>
          {evidencias.length === 0 ? (
            <p className="text-dato text-ink-muted">
              {t("controlesGrc.sinEvidencias")}
            </p>
          ) : (
            <ul className="lista-acotada divide-y divide-ink-dim/30">
              {evidencias.map((e) => (
                <li key={e.referencia} className="py-1.5 text-dato">
                  <span
                    className={cn(
                      "chip-dato mr-2",
                      e.vigente ? "chip-dato--si" : "",
                    )}
                  >
                    {e.vigente
                      ? t("controlesGrc.hasta", { fecha: e.caduca_at ?? "—" })
                      : t("controlesGrc.caducada", { fecha: e.caduca_at })}
                  </span>
                  {e.descripcion}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
