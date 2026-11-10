/**
 * Análisis sobre los datos del CRM (CRM-05.01.03.04, CRM-05.01.03.05,
 * CRM-05.01.03.06, CRM-05.01.01.05, CRM-05.01.03.07).
 *
 * Medido el 09-11-2026: los cinco constaban hechos y ninguno se podía usar.
 * Las cohortes, el embudo y la actividad calculaban sobre lo que se tecleara
 * en el cuerpo de la petición; las instantáneas de un informe sólo se tomaban
 * a mano; y la consulta al lake del cliente devolvía un plan que no ejecutaba
 * nadie. Aquí:
 *
 * - **Embudo** de un embudo de ventas real, con su conversión y la mediana de
 *   días entre etapas, leído del historial de etapas de cada oportunidad.
 * - **Cohortes** de cuentas por mes de alta, con su retención; lo inmaduro y
 *   lo poco significativo no da porcentaje y se dice por qué.
 * - **Actividad frente a resultados** por comercial, con el coeficiente sólo
 *   si hay sujetos de sobra y el aviso de que correlación no es causa.
 * - **Instantáneas programadas** de un informe y su tendencia.
 * - **Consulta federada**: se ejecuta contra la fuente declarada, en lectura
 *   y con su tope de filas, y no se guarda nada.
 *
 * Cada análisis dice **de dónde salió cada dato** —almacén o API, cuántos se
 * leyeron y si se recortó—: un número que no dice de dónde sale no se puede
 * discutir.
 */
import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { listar } from "@/lib/listados";
import { cn } from "@/lib/utiles";

const Grafica = lazy(() =>
  import("@/componentes/graficas/Grafica").then((m) => ({
    default: m.Grafica,
  })),
);

interface Procedencia {
  fuente: "api" | "almacen";
  tabla?: string;
  ruta?: string;
  leidos: number;
  recortado: boolean;
  sin_permiso?: boolean;
  no_leido?: boolean;
  estado_http?: number;
  datos_de?: string | null;
}

interface EtapaEmbudo {
  etapa: string;
  llegaron: number;
  abiertos_aqui: number;
  conversion_desde_anterior: number | null;
  caidos: number;
  dias_mediana: number | null;
}

interface Embudo {
  etapas: EtapaEmbudo[];
  embudos: { id: string; nombre: string }[];
  pipeline: { id: string; nombre: string } | null;
  recorridos?: number;
  abiertos?: number;
  mayor_caida?: { etapa: string; conversion: number; caidos: number } | null;
  desde?: string;
  aviso?: string;
  procedencia: Record<string, Procedencia>;
}

interface Celda {
  periodo: number;
  activos: number;
  pct: number | null;
  inmaduro: boolean;
  poco_significativo: boolean;
}

interface Cohortes {
  cohortes: {
    cohorte: string;
    sujetos: number;
    significativa: boolean;
    celdas: Celda[];
  }[];
  periodos: number;
  minimo_significativo: number;
  aviso: string;
  procedencia: Record<string, Procedencia>;
}

interface Actividad {
  medible: boolean;
  sujetos: number;
  minimo?: number;
  porque?: string;
  coeficiente?: number;
  fuerza?: string;
  aviso?: string;
  por_persona: {
    id: string;
    actividades: number;
    ganadas: number;
    importe: number;
  }[];
  desde: string;
  hasta: string;
  procedencia: Record<string, Procedencia>;
}

interface Usuario {
  id: string;
  nombre: string;
  email: string;
}

export function AnalisisCrm() {
  const { t } = useTranslation();
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  useEffect(() => {
    void listar<Usuario>("/api/v1/usuarios?limite=200")
      .then(setUsuarios)
      .catch(() => setUsuarios([]));
  }, []);
  const nombre = (id: string) => {
    const u = usuarios.find((x) => x.id === id);
    return u ? u.nombre || u.email : `${id.slice(0, 8)}…`;
  };

  return (
    <>
      <CabeceraPagina
        icono="monitoring"
        titulo={t("analisisCrm.titulo")}
        entradilla={t("analisisCrm.entradilla")}
      />
      <SeccionEmbudo />
      <div className="grid gap-4 xl:grid-cols-2">
        <SeccionCohortes />
        <SeccionActividad nombre={nombre} />
      </div>
      <SeccionInstantaneas />
      <SeccionFederada />
    </>
  );
}

/** De dónde salió cada objeto: almacén o API, cuántos y si se recortó. */
function DeDonde({
  procedencia,
}: {
  procedencia: Record<string, Procedencia>;
}) {
  const { t } = useTranslation();
  const filas = Object.entries(procedencia);
  if (!filas.length) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-2 text-rotulo text-ink-faint">
      {filas.map(([objeto, p]) => (
        <li
          key={objeto}
          className={cn(
            "chip-dato",
            (p.recortado || p.sin_permiso || p.no_leido) && "chip-dato--aviso",
          )}
        >
          {t(`analisisCrm.objetos.${objeto}`, { defaultValue: objeto })}
          {": "}
          {p.sin_permiso
            ? t("analisisCrm.sinPermiso")
            : p.no_leido
              ? t("analisisCrm.noLeido", { codigo: p.estado_http ?? "" })
              : t(
                  p.fuente === "almacen"
                    ? "analisisCrm.delAlmacen"
                    : "analisisCrm.deLaApi",
                  { n: p.leidos },
                )}
          {p.recortado ? ` · ${t("analisisCrm.recortado")}` : ""}
        </li>
      ))}
    </ul>
  );
}

function SeccionEmbudo() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Embudo | null>(null);
  const [pipeline, setPipeline] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    setCargando(true);
    const q = new URLSearchParams(pipeline ? { pipeline_id: pipeline } : {});
    llamar<Embudo>(`/api/v1/analisis/crm/embudo?${q}`)
      .then((r) => {
        setDatos(r.datos);
        setFallo(null);
      })
      .catch(setFallo)
      .finally(() => setCargando(false));
  }, [pipeline]);

  return (
    <section className="card mb-4 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="section-label mb-1">{t("analisisCrm.embudo")}</h2>
          <p className="text-rotulo text-ink-faint">
            {t("analisisCrm.embudoAyuda")}
          </p>
        </div>
        {datos?.embudos.length ? (
          <select
            className="input-base w-auto"
            aria-label={t("analisisCrm.elegirEmbudo")}
            value={pipeline || datos.pipeline?.id || ""}
            onChange={(e) => setPipeline(e.target.value)}
          >
            {datos.embudos.map((p) => (
              <option key={p.id} value={p.id}>
                {p.nombre}
              </option>
            ))}
          </select>
        ) : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      {cargando && !datos ? <Cargando /> : null}
      {datos && !datos.etapas.length ? (
        <Vacio titulo={datos.aviso || t("analisisCrm.sinEmbudo")} compacto />
      ) : null}
      {datos && datos.etapas.length ? (
        <>
          <div role="status" className="mb-2 text-dato text-ink-muted">
            {t("analisisCrm.embudoResumen", {
              n: datos.recorridos ?? 0,
              abiertos: datos.abiertos ?? 0,
              desde: datos.desde ?? "",
            })}
            {datos.mayor_caida
              ? ` ${t("analisisCrm.mayorCaida", {
                  etapa: datos.mayor_caida.etapa,
                  pct: datos.mayor_caida.conversion,
                })}`
              : ""}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Suspense fallback={<Cargando />}>
              <Grafica
                forma="embudo"
                titulo={t("analisisCrm.embudo")}
                datos={{
                  filas: datos.etapas.map((e) => ({
                    etapa: e.etapa,
                    llegaron: e.llegaron,
                  })),
                  ejeX: "etapa",
                  rotuloX: t("analisisCrm.etapa"),
                  series: [
                    { clave: "llegaron", rotulo: t("analisisCrm.llegaron") },
                  ],
                }}
              />
            </Suspense>
            <Rejilla
              titulo={t("analisisCrm.embudo")}
              cabeceras={[
                t("analisisCrm.etapa"),
                t("analisisCrm.llegaron"),
                t("analisisCrm.conversion"),
                t("analisisCrm.caidos"),
                t("analisisCrm.diasMediana"),
              ]}
            >
              {datos.etapas.map((e) => (
                <tr
                  key={e.etapa}
                  className="border-b border-ink-dim/30 last:border-0"
                >
                  <Casilla>{e.etapa}</Casilla>
                  <Casilla className="text-right">{e.llegaron}</Casilla>
                  <Casilla className="text-right">
                    {e.conversion_desde_anterior == null
                      ? "—"
                      : `${e.conversion_desde_anterior} %`}
                  </Casilla>
                  <Casilla className="text-right">{e.caidos}</Casilla>
                  <Casilla className="text-right">
                    {e.dias_mediana == null ? "—" : e.dias_mediana}
                  </Casilla>
                </tr>
              ))}
            </Rejilla>
          </div>
          <DeDonde procedencia={datos.procedencia} />
        </>
      ) : null}
    </section>
  );
}

const PERIODOS = ["semana", "mes", "trimestre"] as const;

function SeccionCohortes() {
  const { t } = useTranslation();
  const [periodo, setPeriodo] = useState<string>("mes");
  const [datos, setDatos] = useState<Cohortes | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    setDatos(null);
    llamar<Cohortes>(
      `/api/v1/analisis/crm/cohortes?periodo=${periodo}&periodos=6`,
    )
      .then((r) => {
        setDatos(r.datos);
        setFallo(null);
      })
      .catch(setFallo);
  }, [periodo]);

  // Las más recientes delante: son las que se están mirando.
  const filas = (datos?.cohortes ?? []).slice(-12).reverse();
  return (
    <section className="card mb-4 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="section-label mb-1">{t("analisisCrm.cohortes")}</h2>
          <p className="text-rotulo text-ink-faint">
            {t("analisisCrm.cohortesAyuda")}
          </p>
        </div>
        <select
          className="input-base w-auto"
          aria-label={t("analisisCrm.periodo")}
          value={periodo}
          onChange={(e) => setPeriodo(e.target.value)}
        >
          {PERIODOS.map((p) => (
            <option key={p} value={p}>
              {t(`analisisCrm.periodos.${p}`)}
            </option>
          ))}
        </select>
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      {!datos && !fallo ? <Cargando /> : null}
      {datos && !filas.length ? (
        <Vacio titulo={t("analisisCrm.sinCohortes")} compacto />
      ) : null}
      {datos && filas.length ? (
        <>
          <Rejilla
            titulo={t("analisisCrm.cohortes")}
            cabeceras={[
              t("analisisCrm.cohorte"),
              t("analisisCrm.cuentas"),
              ...Array.from({ length: datos.periodos }, (_, i) =>
                t("analisisCrm.periodoN", { n: i }),
              ),
            ]}
          >
            {filas.map((c) => (
              <tr
                key={c.cohorte}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla>{c.cohorte}</Casilla>
                <Casilla className="text-right">{c.sujetos}</Casilla>
                {c.celdas.map((x) => (
                  <Casilla key={x.periodo} className="text-right">
                    <span
                      title={
                        x.inmaduro
                          ? t("analisisCrm.inmaduro")
                          : x.poco_significativo
                            ? t("analisisCrm.pocoSignificativo", {
                                n: datos.minimo_significativo,
                              })
                            : undefined
                      }
                      className={x.pct == null ? "text-ink-faint" : ""}
                    >
                      {x.pct != null
                        ? `${x.pct} %`
                        : x.inmaduro
                          ? "…"
                          : x.activos}
                    </span>
                  </Casilla>
                ))}
              </tr>
            ))}
          </Rejilla>
          <p className="mt-2 text-rotulo text-ink-faint">
            {t("analisisCrm.cohortesLeyenda", {
              n: datos.minimo_significativo,
            })}
          </p>
          {datos.aviso ? (
            <p className="text-rotulo text-ink-faint">{datos.aviso}</p>
          ) : null}
          <DeDonde procedencia={datos.procedencia} />
        </>
      ) : null}
    </section>
  );
}

function SeccionActividad({ nombre }: { nombre: (id: string) => string }) {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Actividad | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    llamar<Actividad>("/api/v1/analisis/crm/actividad")
      .then((r) => setDatos(r.datos))
      .catch(setFallo);
  }, []);

  const personas = (datos?.por_persona ?? []).slice(0, 12);
  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">{t("analisisCrm.actividad")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("analisisCrm.actividadAyuda")}
      </p>
      {fallo ? <Fallo error={fallo} /> : null}
      {!datos && !fallo ? <Cargando /> : null}
      {datos ? (
        <>
          <div role="status" className="mb-2 text-dato">
            {datos.medible ? (
              <span>
                {t("analisisCrm.coeficiente", {
                  r: datos.coeficiente,
                  fuerza: datos.fuerza,
                  n: datos.sujetos,
                })}
              </span>
            ) : (
              <span className="text-ink-muted">{datos.porque}</span>
            )}
          </div>
          {datos.aviso ? (
            <p className="mb-2 text-rotulo text-ink-faint">{datos.aviso}</p>
          ) : null}
          {personas.length ? (
            <>
              <Suspense fallback={<Cargando />}>
                <Grafica
                  forma="barras"
                  titulo={t("analisisCrm.actividad")}
                  datos={{
                    filas: personas.map((p) => ({
                      persona: nombre(p.id),
                      actividades: p.actividades,
                      ganadas: p.ganadas,
                    })),
                    ejeX: "persona",
                    rotuloX: t("analisisCrm.persona"),
                    series: [
                      {
                        clave: "actividades",
                        rotulo: t("analisisCrm.actividades"),
                      },
                      { clave: "ganadas", rotulo: t("analisisCrm.ganadas") },
                    ],
                  }}
                />
              </Suspense>
              <p className="mt-1 text-rotulo text-ink-faint">
                {t("analisisCrm.ventana", {
                  desde: datos.desde,
                  hasta: datos.hasta,
                })}
              </p>
            </>
          ) : (
            <Vacio titulo={t("analisisCrm.sinPersonas")} compacto />
          )}
          <DeDonde procedencia={datos.procedencia} />
        </>
      ) : null}
    </section>
  );
}

interface Informe {
  id: string;
  nombre: string;
}

interface Programacion {
  id: string;
  informe_id: string;
  periodicidad: string;
  hora: number;
  accion: string;
  activa: boolean;
  proxima_at: string | null;
  ultima_at: string | null;
  ultimo_error: string | null;
}

interface Tendencia {
  puntos: { dia: string; filas: number }[];
  cuantos: number;
  hay_tendencia: boolean;
  aviso: string;
}

const PERIODICIDADES = ["diaria", "semanal", "mensual"] as const;

function SeccionInstantaneas() {
  const { t } = useTranslation();
  const [informes, setInformes] = useState<Informe[] | null>(null);
  const [informe, setInforme] = useState("");
  const [programaciones, setProgramaciones] = useState<Programacion[]>([]);
  const [tendencia, setTendencia] = useState<Tendencia | null>(null);
  const [periodicidad, setPeriodicidad] = useState<string>("semanal");
  const [hora, setHora] = useState(7);
  // La zona en la que se lee la hora: la del tenant, que da el servidor.
  const [zona, setZona] = useState("");
  const [aviso, setAviso] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    llamar<Informe[]>("/api/v1/informes")
      .then((r) => {
        const lista = Array.isArray(r.datos) ? r.datos : [];
        setInformes(lista);
        const primero = lista[0];
        if (primero) setInforme((x) => x || primero.id);
      })
      .catch(setFallo);
  }, []);

  const cargar = useCallback(() => {
    if (!informe) return;
    llamar<{ programaciones: Programacion[]; zona?: string }>(
      "/api/v1/informes/programaciones",
    )
      .then((r) => {
        setZona(r.datos?.zona ?? "");
        setProgramaciones(
          (r.datos?.programaciones ?? []).filter(
            (p) => p.informe_id === informe && p.accion === "instantanea",
          ),
        );
      })
      .catch(setFallo);
    llamar<Tendencia>(`/api/v1/informes/${informe}/tendencia`)
      .then((r) => setTendencia(r.datos))
      .catch(setFallo);
  }, [informe]);
  useEffect(cargar, [cargar]);

  async function programar() {
    try {
      await llamar(`/api/v1/informes/${informe}/programar`, {
        metodo: "POST",
        cuerpo: { periodicidad, hora, accion: "instantanea" },
      });
      setAviso(t("analisisCrm.programada"));
      setFallo(null);
      cargar();
    } catch (e) {
      setAviso("");
      setFallo(e);
    }
  }

  async function tomarAhora() {
    try {
      await llamar(`/api/v1/informes/${informe}/instantanea`, {
        metodo: "POST",
      });
      setAviso(t("analisisCrm.tomada"));
      setFallo(null);
      cargar();
    } catch (e) {
      setAviso("");
      setFallo(e);
    }
  }

  async function quitar(id: string) {
    try {
      await llamar(`/api/v1/informes/programaciones/${id}`, {
        metodo: "DELETE",
      });
      setAviso(t("analisisCrm.quitada"));
      cargar();
    } catch (e) {
      setAviso("");
      setFallo(e);
    }
  }

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">{t("analisisCrm.instantaneas")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("analisisCrm.instantaneasAyuda")}
      </p>
      {informes === null && !fallo ? <Cargando /> : null}
      {informes === null && fallo ? <Fallo error={fallo} /> : null}
      {informes === null ? null : !informes.length ? (
        <Vacio titulo={t("analisisCrm.sinInformes")} compacto />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-3">
            <label className="block text-rotulo text-ink-muted">
              {t("analisisCrm.informe")}
              <select
                className="input-base mt-1"
                value={informe}
                onChange={(e) => setInforme(e.target.value)}
              >
                {informes.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.nombre}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col text-rotulo text-ink-muted">
                {t("analisisCrm.cada")}
                <select
                  className="input-base mt-1 w-auto"
                  value={periodicidad}
                  onChange={(e) => setPeriodicidad(e.target.value)}
                >
                  {PERIODICIDADES.map((p) => (
                    <option key={p} value={p}>
                      {t(`analisisCrm.periodicidades.${p}`)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col text-rotulo text-ink-muted">
                {zona
                  ? t("analisisCrm.horaEnZona", { zona })
                  : t("analisisCrm.hora")}
                <input
                  type="number"
                  min={0}
                  max={23}
                  className="input-base mt-1 w-20"
                  value={hora}
                  onChange={(e) => setHora(Number(e.target.value))}
                />
              </label>
              <button
                type="button"
                className="btn-primary"
                onClick={() => void programar()}
              >
                <Icono nombre="schedule" tamano="sm" />
                {t("analisisCrm.programar")}
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => void tomarAhora()}
              >
                <Icono nombre="photo_camera" tamano="sm" />
                {t("analisisCrm.tomarAhora")}
              </button>
            </div>
            <div role="status">
              {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
            </div>
            {fallo ? <Fallo error={fallo} /> : null}
            {programaciones.length ? (
              <ul className="divide-y divide-ink-dim/30">
                {programaciones.map((p) => (
                  <li
                    key={p.id}
                    className="flex items-start justify-between gap-2 py-2 text-dato"
                  >
                    <div>
                      <span className="font-medium text-ink">
                        {t(`analisisCrm.periodicidades.${p.periodicidad}`, {
                          defaultValue: p.periodicidad,
                        })}
                        {" · "}
                        {zona
                          ? t("analisisCrm.aLasEnZona", { h: p.hora, zona })
                          : t("analisisCrm.aLas", { h: p.hora })}
                      </span>
                      <p className="text-rotulo text-ink-faint">
                        {t("analisisCrm.proxima", {
                          cuando: p.proxima_at ? fechaHora(p.proxima_at) : "—",
                        })}
                      </p>
                      {p.ultimo_error ? (
                        <p className="text-rotulo text-danger">
                          {p.ultimo_error}
                        </p>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      className="btn-link shrink-0"
                      onClick={() => void quitar(p.id)}
                    >
                      {t("analisisCrm.quitar")}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-dato text-ink-muted">
                {t("analisisCrm.sinProgramar")}
              </p>
            )}
          </div>
          <div>
            {tendencia && tendencia.puntos.length ? (
              <Suspense fallback={<Cargando />}>
                <Grafica
                  forma="lineas"
                  titulo={t("analisisCrm.tendencia")}
                  datos={{
                    filas: tendencia.puntos.map((p) => ({
                      dia: p.dia,
                      filas: p.filas,
                    })),
                    ejeX: "dia",
                    rotuloX: t("analisisCrm.dia"),
                    series: [
                      { clave: "filas", rotulo: t("analisisCrm.filas") },
                    ],
                  }}
                />
              </Suspense>
            ) : null}
            <p className="mt-1 text-rotulo text-ink-faint">
              {tendencia?.hay_tendencia
                ? t("analisisCrm.puntos", { n: tendencia.cuantos })
                : tendencia?.cuantos
                  ? tendencia.aviso
                  : t("analisisCrm.sinInstantaneas")}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}

interface Fuente {
  id: string;
  clave: string;
  nombre: string;
  objetos: string[];
  tope_filas: number;
  config: Record<string, unknown>;
}

interface ResultadoFederado {
  filas: Record<string, unknown>[];
  columnas: string[];
  cuantas: number;
  limite: number;
  recortado: boolean;
  consultado_at: string;
  duracion_ms: number;
  aviso: string;
}

function SeccionFederada() {
  const { t } = useTranslation();
  const [fuentes, setFuentes] = useState<Fuente[]>([]);
  const [fuente, setFuente] = useState("");
  const [objeto, setObjeto] = useState("");
  const [campos, setCampos] = useState("");
  const [limite, setLimite] = useState(100);
  const [resultado, setResultado] = useState<ResultadoFederado | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [consultando, setConsultando] = useState(false);

  useEffect(() => {
    void listar<Fuente>("/api/v1/almacen/federadas?limite=200")
      .then((lista) => {
        setFuentes(lista);
        const primera = lista[0];
        if (primera) {
          setFuente(primera.clave);
          setObjeto(String(primera.objetos?.[0] ?? ""));
        }
      })
      .catch(setFallo);
  }, []);

  const elegida = fuentes.find((f) => f.clave === fuente);

  async function consultar() {
    setConsultando(true);
    try {
      const r = await llamar<ResultadoFederado>(
        `/api/v1/almacen/federadas/${encodeURIComponent(fuente)}/consultar`,
        {
          metodo: "POST",
          cuerpo: {
            objeto,
            campos: campos
              .split(",")
              .map((c) => c.trim())
              .filter(Boolean),
            limite,
          },
        },
      );
      setResultado(r.datos);
      setFallo(null);
    } catch (e) {
      setResultado(null);
      setFallo(e);
    } finally {
      setConsultando(false);
    }
  }

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">{t("analisisCrm.federada")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("analisisCrm.federadaAyuda")}
      </p>
      {!fuentes.length ? (
        <Vacio titulo={t("analisisCrm.sinFuentes")} compacto />
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <label className="flex flex-col text-rotulo text-ink-muted">
              {t("analisisCrm.fuente")}
              <select
                className="input-base mt-1 w-auto"
                value={fuente}
                onChange={(e) => {
                  setFuente(e.target.value);
                  const f = fuentes.find((x) => x.clave === e.target.value);
                  setObjeto(String(f?.objetos?.[0] ?? ""));
                }}
              >
                {fuentes.map((f) => (
                  <option key={f.clave} value={f.clave}>
                    {f.nombre || f.clave}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col text-rotulo text-ink-muted">
              {t("analisisCrm.objeto")}
              <select
                className="input-base mt-1 w-auto"
                value={objeto}
                onChange={(e) => setObjeto(e.target.value)}
              >
                {(elegida?.objetos ?? []).map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col text-rotulo text-ink-muted">
              {t("analisisCrm.campos")}
              <input
                className="input-base mt-1 w-56"
                value={campos}
                placeholder={t("analisisCrm.camposAyuda")}
                onChange={(e) => setCampos(e.target.value)}
              />
            </label>
            <label className="flex flex-col text-rotulo text-ink-muted">
              {t("analisisCrm.limite", { tope: elegida?.tope_filas ?? "" })}
              <input
                type="number"
                min={1}
                className="input-base mt-1 w-28"
                value={limite}
                onChange={(e) => setLimite(Number(e.target.value))}
              />
            </label>
            <button
              type="button"
              className="btn-primary"
              disabled={!fuente || !objeto || consultando}
              onClick={() => void consultar()}
            >
              <Icono nombre="travel_explore" tamano="sm" />
              {t("analisisCrm.consultar")}
            </button>
          </div>
          {fallo ? <Fallo error={fallo} /> : null}
          <div role="status">
            {resultado ? (
              <p className="mb-2 text-dato text-ink-muted">
                {t("analisisCrm.resultadoFederado", {
                  n: resultado.cuantas,
                  ms: resultado.duracion_ms,
                  cuando: fechaHora(resultado.consultado_at),
                })}
                {resultado.recortado
                  ? ` ${t("analisisCrm.recortadoA", { n: resultado.limite })}`
                  : ""}
              </p>
            ) : null}
          </div>
          {resultado && resultado.filas.length ? (
            <Rejilla
              titulo={t("analisisCrm.federada")}
              cabeceras={resultado.columnas}
            >
              {resultado.filas.map((f, i) => (
                <tr
                  key={i}
                  className="border-b border-ink-dim/30 last:border-0"
                >
                  {resultado.columnas.map((c) => (
                    <Casilla key={c}>{String(f[c] ?? "")}</Casilla>
                  ))}
                </tr>
              ))}
            </Rejilla>
          ) : null}
          {resultado ? (
            <p className="mt-2 text-rotulo text-ink-faint">{resultado.aviso}</p>
          ) : null}
        </>
      )}
    </section>
  );
}
