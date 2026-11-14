/**
 * El asistente con conocimiento y acciones, y las preguntas a los datos que se
 * ejecutan (CRM-04.03.02.02, CRM-05.02.02.04).
 *
 * Al lado de Nexus y no dentro: Nexus planifica pasos con un agente y sus
 * herramientas; esto contesta con lo que la casa SABE —artículos, casos
 * resueltos, lecciones— citando, propone una acción de una lista cerrada que
 * no se hace hasta que la confirmas, y contesta preguntas sobre los datos
 * ejecutándolas contra los listados del CRM con tus permisos.
 *
 * Lo que importa de la pantalla es poder no fiarse:
 * - cada afirmación lleva su número y la fuente al lado;
 * - la acción se enseña con sus datos, editables, y su ruta, antes de hacerla;
 * - la respuesta sobre los datos va con la consulta que se hizo, tal cual, y
 *   dice si es parcial o si el listado filtraba algo por su cuenta.
 *
 * Verificado en el navegador el 09-11-2026 con el modelo de verdad.
 *
 * Y el modo voz (CRM-04.02.01.08): dictar la pregunta —reconocimiento del
 * navegador o, si no lo tiene, grabación mandada al proveedor de transcripción
 * de la empresa— y oír la respuesta con la síntesis del navegador.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Cargando, Error as Fallo, FalloCompacto } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar, salvoCancelacion, subir } from "@/lib/api";
import {
  cifra,
  esIdentificadorTecnico,
  fechaHora,
  humanizar,
  idiomaDeVoz,
  localizacion,
} from "@/lib/formato";

interface Fuente {
  n: number;
  fuente: string;
  id: string;
  titulo: string;
}

interface Accion {
  id: string;
  accion: string;
  nombre: string;
  argumentos: Record<string, string>;
  campos: Record<
    string,
    { tipo: string; obligatorio?: boolean; opciones?: string[] }
  >;
  ruta: string;
  porque: string;
  estado: string;
  faltan: string[];
  codigo_respuesta: number | null;
  resultado: { id?: string; detalle?: string };
}

interface Conversacion {
  texto: string;
  respondida: boolean;
  fuentes: Fuente[];
  porque: string;
  accion_propuesta: Accion | null;
}

interface RespuestaDatos {
  interpretacion: string;
  ejecutado: boolean;
  respuesta?: string;
  problemas?: string[];
  agregados?: { grupo: string | null; valor: number | null; filas: number }[];
  total?: number | null;
  leidas?: number;
  parcial?: boolean;
  filas?: Record<string, unknown>[];
  plan?: { campos?: string[] } | null;
  consulta?: {
    metodo: string;
    ruta: string;
    parametros: Record<string, unknown>;
    por_defecto_del_listado?: Record<string, unknown>;
  };
  aviso?: string;
}

/** Dónde se abre cada fuente del conocimiento. */
const ENLACE: Record<string, (id: string) => string> = {
  leccion: (id) => `/m/lecciones/leccion/${id}`,
  articulo: (id) => `/m/conocimiento/articulo/${id}`,
  caso_resuelto: (id) => `/m/casos/caso/${id}`,
};

export function Asistente() {
  const { t } = useTranslation();
  // Sube cada vez que el panel de conocimiento propone o decide algo, para que
  // la lista de propuestas de abajo no enseñe la foto de antes.
  const [vuelta, setVuelta] = useState(0);
  const otraVuelta = useCallback(() => setVuelta((v) => v + 1), []);
  return (
    <>
      <CabeceraPagina
        icono="support_agent"
        titulo={t("asistente.titulo")}
        entradilla={t("asistente.entradilla")}
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <Conocimiento alCambiar={otraVuelta} />
        <Datos />
      </div>
      <MisAcciones vuelta={vuelta} />
    </>
  );
}

/** `GET /ia/indice`: cuántos fragmentos hay indexados de cada fuente. */
interface EstadoIndice {
  por_fuente: { fuente: string; modelo: string; fragmentos: number }[];
  total: number;
}

/**
 * Qué sabe el asistente: los fragmentos indexados por fuente.
 *
 * Es la otra mitad de «sin respuesta comprobable»: si el índice tiene tres
 * artículos, la culpa de que no conteste no es de la pregunta.
 */
function LoQueSabe() {
  const { t } = useTranslation();
  // `undefined` mientras se pregunta; `null` si llegó a medias. Antes las dos
  // cosas —y el fallo— eran `null` y la línea no salía: no se distinguía
  // «todavía no lo sé» de «no lo he podido mirar» (auditoría 13-11-2026,
  // UX-11).
  const [estado, setEstado] = useState<EstadoIndice | null | undefined>(
    undefined,
  );
  const [fallo, setFallo] = useState<unknown>(null);
  const [intento, setIntento] = useState(0);
  useEffect(() => {
    const control = new AbortController();
    llamar<EstadoIndice>("/api/v1/ia/indice", { signal: control.signal })
      // Sólo si trae su desglose: un estado a medias no se pinta como «vacío».
      .then((r) =>
        setEstado(Array.isArray(r.datos?.por_fuente) ? r.datos : null),
      )
      .catch(
        salvoCancelacion((e) => {
          setFallo(e);
          setEstado(null);
        }),
      );
    return () => control.abort();
  }, [intento]);
  if (fallo)
    return (
      <div className="mb-3">
        <FalloCompacto
          error={fallo}
          que={t("asistente.indice")}
          reintentar={() => {
            setFallo(null);
            setEstado(undefined);
            setIntento((n) => n + 1);
          }}
        />
      </div>
    );
  if (estado === undefined)
    return (
      <p className="mb-3 text-rotulo text-ink-faint" role="status">
        {t("asistente.mirandoIndice")}
      </p>
    );
  if (!estado) return null;
  if (estado.total === 0)
    return (
      <p className="mb-3 text-rotulo text-warning">
        {t("asistente.indiceVacio")}
      </p>
    );
  const porFuente = new Map<string, number>();
  for (const f of estado.por_fuente)
    porFuente.set(f.fuente, (porFuente.get(f.fuente) ?? 0) + f.fragmentos);
  const modelos = [...new Set(estado.por_fuente.map((f) => f.modelo))];
  return (
    <p className="mb-3 text-rotulo text-ink-muted">
      {t("asistente.sabeDe", {
        fuentes: [...porFuente]
          .map(
            ([fuente, n]) =>
              `${t(`asistente.fuentes.${fuente}`, { defaultValue: fuente })}: ${cifra(n)}`,
          )
          .join(" · "),
        modelos: modelos.join(", "),
      })}
    </p>
  );
}

function Conocimiento({ alCambiar }: { alCambiar: () => void }) {
  const { t } = useTranslation();
  const [pregunta, setPregunta] = useState("");
  const [r, setR] = useState<Conversacion | null>(null);
  const [accion, setAccion] = useState<Accion | null>(null);
  const [args, setArgs] = useState<Record<string, string>>({});
  const [fallo, setFallo] = useState<unknown>(null);
  const [trabajando, setTrabajando] = useState(false);

  const voz = useVoz();

  async function preguntar(dicha?: string) {
    const texto = (dicha ?? pregunta).trim();
    setTrabajando(true);
    setFallo(null);
    setR(null);
    setAccion(null);
    try {
      const x = await llamar<Conversacion>("/api/v1/ia/asistencia/conversar", {
        metodo: "POST",
        cuerpo: { pregunta: texto },
      });
      setR(x.datos);
      setAccion(x.datos.accion_propuesta);
      if (x.datos.accion_propuesta) alCambiar();
      setArgs({ ...(x.datos.accion_propuesta?.argumentos ?? {}) });
      // En modo voz se lee la respuesta (y lo que propone hacer, que se
      // confirma igual: a mano, viendo sus datos).
      if (voz.activo) {
        const propuesta = x.datos.accion_propuesta
          ? " " +
            t("asistente.propone", { accion: x.datos.accion_propuesta.nombre })
          : "";
        voz.leer(
          (x.datos.respondida
            ? x.datos.texto
            : t("asistente.sinRespuesta")
          ).replace(/\[\d+\]/g, "") + propuesta,
        );
      }
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
    }
  }

  async function dictar() {
    setFallo(null);
    try {
      const texto = await voz.escuchar();
      if (texto) {
        setPregunta(texto);
        await preguntar(texto);
      }
    } catch (e) {
      setFallo(e);
    }
  }

  async function decidir(confirmar: boolean) {
    if (!accion) return;
    setTrabajando(true);
    setFallo(null);
    try {
      const x = await llamar<Accion>(
        `/api/v1/ia/asistente/acciones/${accion.id}`,
        {
          metodo: "POST",
          cuerpo: { confirmar, argumentos: args },
        },
      );
      setAccion(x.datos);
      alCambiar();
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
    }
  }

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("asistente.conocimiento")}</h2>
      <p className="mb-1 text-rotulo text-ink-faint">
        {t("asistente.conocimientoAyuda")}
      </p>
      <LoQueSabe />
      <form
        className="flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void preguntar();
        }}
      >
        <textarea
          className="input-base min-h-20"
          value={pregunta}
          aria-label={t("asistente.pregunta")}
          placeholder={t("asistente.ejemploConocimiento")}
          onChange={(e) => setPregunta(e.target.value)}
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="submit"
            className="btn-primary"
            disabled={trabajando || pregunta.trim().length < 3}
          >
            <Icono nombre="send" tamano="sm" />
            {trabajando ? t("asistente.pensando") : t("asistente.preguntar")}
          </button>
          <label className="flex items-center gap-2 text-rotulo text-ink-muted">
            <input
              type="checkbox"
              checked={voz.activo}
              onChange={(e) => voz.setActivo(e.target.checked)}
            />
            {t("asistente.voz.modo")}
          </label>
          {voz.activo ? (
            <>
              <button
                type="button"
                className="btn-secondary"
                disabled={trabajando || voz.escuchando}
                onClick={() => void dictar()}
              >
                <Icono nombre="mic" tamano="sm" />
                {voz.escuchando
                  ? t("asistente.voz.escuchando")
                  : t("asistente.voz.hablar")}
              </button>
              {voz.escuchando && voz.via === "grabacion" ? (
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => voz.terminar()}
                >
                  <Icono nombre="stop" tamano="sm" />
                  {t("asistente.voz.terminar")}
                </button>
              ) : null}
              {voz.leyendo ? (
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => voz.callar()}
                >
                  <Icono nombre="volume_off" tamano="sm" />
                  {t("asistente.voz.callar")}
                </button>
              ) : null}
            </>
          ) : null}
        </div>
        {voz.activo ? (
          <p className="text-rotulo text-ink-faint">
            {t(`asistente.voz.via.${voz.via}`)}
          </p>
        ) : null}
      </form>
      <div role="status" className="mt-3 flex flex-col gap-3 text-dato">
        {fallo ? <Fallo error={fallo} /> : null}
        {r ? (
          r.respondida ? (
            <div>
              <p className="whitespace-pre-line text-ink">{r.texto}</p>
              <ol className="mt-2 flex flex-col gap-1">
                {r.fuentes.map((f) => (
                  <li key={f.n} className="text-rotulo text-ink-muted">
                    <span className="chip-dato mr-2">[{f.n}]</span>
                    {t(`asistente.fuentes.${f.fuente}`, {
                      defaultValue: f.fuente,
                    })}
                    {": "}
                    {ENLACE[f.fuente] ? (
                      <Link
                        className="text-accent hover:underline"
                        to={ENLACE[f.fuente]!(f.id)}
                      >
                        {f.titulo || f.id}
                      </Link>
                    ) : (
                      f.titulo || f.id
                    )}
                  </li>
                ))}
              </ol>
            </div>
          ) : (
            <p className="text-ink-muted">
              {t("asistente.sinRespuesta")} {r.porque}
            </p>
          )
        ) : null}
        {accion ? (
          <div className="rounded-lg border border-accent/30 bg-accent/5 p-3">
            <p className="font-medium text-ink">
              {t("asistente.propone", { accion: accion.nombre })}
            </p>
            {accion.porque ? (
              <p className="text-rotulo text-ink-muted">{accion.porque}</p>
            ) : null}
            <p className="font-mono text-rotulo text-ink-faint">
              {accion.ruta}
            </p>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {Object.entries(accion.campos).map(([campo, def]) => (
                <label
                  key={campo}
                  className="flex flex-col gap-1 text-rotulo text-ink-muted"
                >
                  {t(`asistente.campos.${campo}`, { defaultValue: campo })}
                  {def.obligatorio ? " *" : ""}
                  {def.opciones ? (
                    <select
                      className="input-base"
                      value={args[campo] ?? ""}
                      aria-label={t(`asistente.campos.${campo}`, {
                        defaultValue: campo,
                      })}
                      disabled={accion.estado !== "propuesta"}
                      onChange={(e) =>
                        setArgs({ ...args, [campo]: e.target.value })
                      }
                    >
                      <option value="">—</option>
                      {def.opciones.map((o) => (
                        <option key={o} value={o}>
                          {o}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      className="input-base"
                      value={args[campo] ?? ""}
                      aria-label={t(`asistente.campos.${campo}`, {
                        defaultValue: campo,
                      })}
                      disabled={accion.estado !== "propuesta"}
                      onChange={(e) =>
                        setArgs({ ...args, [campo]: e.target.value })
                      }
                    />
                  )}
                </label>
              ))}
            </div>
            {accion.estado === "propuesta" ? (
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  className="btn-primary"
                  disabled={trabajando}
                  onClick={() => void decidir(true)}
                >
                  <Icono nombre="check" tamano="sm" />
                  {t("asistente.confirmar")}
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={trabajando}
                  onClick={() => void decidir(false)}
                >
                  {t("asistente.descartar")}
                </button>
                <span className="text-rotulo text-ink-faint">
                  {t("asistente.conTusPermisos")}
                </span>
              </div>
            ) : (
              <p
                className={
                  accion.estado === "ejecutada"
                    ? "mt-2 text-success"
                    : "mt-2 text-ink-muted"
                }
              >
                {t(`asistente.estados.${accion.estado}`, {
                  codigo: accion.codigo_respuesta,
                  id: accion.resultado?.id ?? "",
                  detalle: accion.resultado?.detalle ?? "",
                })}
              </p>
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
}

/**
 * Lo que el asistente te ha propuesto hacer, y qué pasó con cada cosa.
 *
 * La propuesta vive en la respuesta: si sales de la pantalla antes de
 * confirmarla, sin esto se pierde aunque siga vigente. Aquí se retoma —con los
 * datos que propuso: para corregirlos, se vuelve a preguntar— y se ve qué se
 * hizo de verdad, con la respuesta que dio el CRM. Y qué le puedes pedir TÚ:
 * las acciones que no permite tu rol no se le ofrecen al modelo.
 */
function MisAcciones({ vuelta }: { vuelta: number }) {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<{
    acciones: (Accion & { caduca_at: string | null })[];
    disponibles: { clave: string; nombre: string }[];
  } | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [trabajando, setTrabajando] = useState("");
  // Si el servidor ha contestado ya alguna vez. Sin esto, mientras llegaba la
  // lista la sección no existía y la pantalla parecía no tener propuestas
  // (auditoría 13-11-2026, UX-11).
  const [contestada, setContestada] = useState(false);

  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<NonNullable<typeof datos>>("/api/v1/ia/asistente/acciones", {
      signal: control.signal,
    })
      .then((r) =>
        setDatos(
          Array.isArray(r.datos?.acciones)
            ? {
                acciones: r.datos.acciones,
                disponibles: Array.isArray(r.datos.disponibles)
                  ? r.datos.disponibles
                  : [],
              }
            : null,
        ),
      )
      .catch(salvoCancelacion(setFallo))
      .finally(() => {
        if (!control.signal.aborted) setContestada(true);
      });
    return () => control.abort();
  }, []);
  useEffect(cargar, [cargar, vuelta]);

  async function decidir(accion: Accion, confirmar: boolean) {
    setTrabajando(accion.id);
    setFallo(null);
    try {
      await llamar(`/api/v1/ia/asistente/acciones/${accion.id}`, {
        metodo: "POST",
        cuerpo: { confirmar, argumentos: accion.argumentos },
      });
      cargar();
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando("");
    }
  }

  if (!contestada)
    return (
      <section className="card mt-4 p-4">
        <h2 className="section-label mb-1">{t("asistente.misAcciones")}</h2>
        <Cargando />
      </section>
    );
  if (!datos && !fallo) return null;
  const ahora = Date.now();
  return (
    <section className="card mt-4 p-4">
      <h2 className="section-label mb-1">{t("asistente.misAcciones")}</h2>
      {datos ? (
        <p className="mb-2 text-rotulo text-ink-faint">
          {datos.disponibles.length
            ? t("asistente.puedesPedir", {
                acciones: datos.disponibles.map((d) => d.nombre).join(" · "),
              })
            : t("asistente.nadaQuePedir")}
        </p>
      ) : null}
      {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}
      {datos && datos.acciones.length === 0 ? (
        <p className="text-dato text-ink-muted">
          {t("asistente.sinPropuestas")}
        </p>
      ) : null}
      {datos && datos.acciones.length > 0 ? (
        <ul className="lista-acotada divide-y divide-ink-dim/30 pr-1">
          {datos.acciones.map((a) => {
            const caducada =
              a.estado === "propuesta" &&
              !!a.caduca_at &&
              Date.parse(a.caduca_at) < ahora;
            const estado = caducada ? "caducada" : a.estado;
            return (
              <li key={a.id} className="py-2">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-medium text-ink">{a.nombre}</span>
                  <span
                    className={`chip-dato ${
                      estado === "ejecutada"
                        ? "chip-dato--si"
                        : estado === "fallida"
                          ? "chip-dato--mal"
                          : estado === "propuesta"
                            ? "chip-dato--aviso"
                            : "chip-dato--no"
                    }`}
                  >
                    {t(`asistente.estadoCorto.${estado}`, {
                      defaultValue: estado,
                    })}
                  </span>
                  {estado === "propuesta" && a.caduca_at ? (
                    <span className="text-rotulo text-ink-faint">
                      {t("asistente.caduca", {
                        cuando: fechaHora(a.caduca_at),
                      })}
                    </span>
                  ) : null}
                </div>
                {a.porque ? (
                  <p className="text-rotulo text-ink-muted">{a.porque}</p>
                ) : null}
                <p className="text-rotulo text-ink-faint">
                  {Object.entries(a.argumentos)
                    .map(
                      ([campo, valor]) =>
                        `${t(`asistente.campos.${campo}`, { defaultValue: campo })}: ${valor}`,
                    )
                    .join(" · ")}
                </p>
                {estado === "ejecutada" || estado === "fallida" ? (
                  <p className="text-rotulo text-ink-muted">
                    {t(`asistente.estados.${estado}`, {
                      codigo: a.codigo_respuesta,
                      id: a.resultado?.id ?? "",
                      detalle: a.resultado?.detalle ?? "",
                    })}
                  </p>
                ) : null}
                {estado === "propuesta" ? (
                  <div className="mt-1 flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="btn-primary"
                      disabled={trabajando === a.id || a.faltan.length > 0}
                      title={
                        a.faltan.length
                          ? t("asistente.faltan", {
                              campos: a.faltan
                                .map((c) =>
                                  t(`asistente.campos.${c}`, {
                                    defaultValue: c,
                                  }),
                                )
                                .join(", "),
                            })
                          : undefined
                      }
                      onClick={() => void decidir(a, true)}
                    >
                      <Icono nombre="check" tamano="sm" />
                      {t("asistente.confirmar")}
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={trabajando === a.id}
                      onClick={() => void decidir(a, false)}
                    >
                      {t("asistente.descartar")}
                    </button>
                    {a.faltan.length ? (
                      <span className="text-rotulo text-warning">
                        {t("asistente.faltan", {
                          campos: a.faltan
                            .map((c) =>
                              t(`asistente.campos.${c}`, { defaultValue: c }),
                            )
                            .join(", "),
                        })}
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

function Datos() {
  const { t } = useTranslation();
  const [pregunta, setPregunta] = useState("");
  const [r, setR] = useState<RespuestaDatos | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [trabajando, setTrabajando] = useState(false);

  async function preguntar() {
    setTrabajando(true);
    setFallo(null);
    setR(null);
    try {
      const x = await llamar<RespuestaDatos>("/api/v1/ia/preguntar-datos", {
        metodo: "POST",
        cuerpo: { pregunta },
      });
      setR(x.datos);
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
    }
  }

  const columnas =
    r?.plan?.campos && r.plan.campos.length
      ? r.plan.campos
      : // Sin campos pedidos, los que se leen: fuera los identificadores
        // técnicos, que ocupan media tabla y no contestan nada.
        Object.keys(r?.filas?.[0] ?? {})
          .filter((c) => !esIdentificadorTecnico(c))
          .slice(0, 6);
  const parametros = Object.entries(r?.consulta?.parametros ?? {})
    .map(([k, v]) => `${k}=${String(v)}`)
    .join("&");

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("asistente.datos")}</h2>
      <p className="mb-3 text-rotulo text-ink-faint">
        {t("asistente.datosAyuda")}
      </p>
      <form
        className="flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void preguntar();
        }}
      >
        <textarea
          className="input-base min-h-20"
          value={pregunta}
          aria-label={t("asistente.pregunta")}
          placeholder={t("asistente.ejemploDatos")}
          onChange={(e) => setPregunta(e.target.value)}
        />
        <div>
          <button
            type="submit"
            className="btn-primary"
            disabled={trabajando || pregunta.trim().length < 3}
          >
            <Icono nombre="query_stats" tamano="sm" />
            {trabajando ? t("asistente.pensando") : t("asistente.preguntar")}
          </button>
        </div>
      </form>
      <div role="status" className="mt-3 flex flex-col gap-2 text-dato">
        {fallo ? <Fallo error={fallo} /> : null}
        {r ? (
          <>
            {r.interpretacion ? (
              <p className="text-ink-muted">
                {t("asistente.entendido")} {r.interpretacion}
              </p>
            ) : null}
            {r.ejecutado ? (
              <p className="text-titulo font-medium text-ink">{r.respuesta}</p>
            ) : (
              <ul className="text-warning">
                {(r.problemas ?? []).map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            )}
            {r.parcial ? (
              <p className="chip-dato chip-dato--aviso self-start">
                {t("asistente.parcial", { leidas: r.leidas, total: r.total })}
              </p>
            ) : null}
            {r.aviso ? <p className="text-warning">{r.aviso}</p> : null}
            {r.consulta ? (
              <div>
                <p className="text-rotulo text-ink-faint">
                  {t("asistente.consultaHecha")}
                </p>
                <code className="block break-all rounded bg-ink-dim/10 p-2 font-mono text-rotulo text-ink">
                  {r.consulta.metodo} {r.consulta.ruta}
                  {parametros ? `?${parametros}` : ""}
                </code>
              </div>
            ) : null}
            {r.agregados && r.agregados.length > 1 ? (
              <Rejilla
                titulo={t("asistente.agregados")}
                compacta
                cabeceras={[
                  t("asistente.grupo"),
                  t("asistente.valor"),
                  t("asistente.filas"),
                ]}
              >
                {r.agregados.map((g) => (
                  <tr
                    key={String(g.grupo)}
                    className="border-b border-ink-dim/30 last:border-0"
                  >
                    <Casilla>{g.grupo ?? "—"}</Casilla>
                    <Casilla className="text-right">{cifra(g.valor)}</Casilla>
                    <Casilla className="text-right">{cifra(g.filas)}</Casilla>
                  </tr>
                ))}
              </Rejilla>
            ) : null}
            {r.filas && r.filas.length && columnas.length ? (
              <Rejilla
                titulo={t("asistente.filasDeEjemplo")}
                compacta
                cabeceras={columnas.map(humanizar)}
              >
                {r.filas.map((f, i) => (
                  <tr
                    key={i}
                    className="border-b border-ink-dim/30 last:border-0"
                  >
                    {columnas.map((c) => (
                      <Casilla key={c}>{String(f[c] ?? "")}</Casilla>
                    ))}
                  </tr>
                ))}
              </Rejilla>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  );
}

// ── Modo voz (CRM-04.02.01.08) ────────────────────────────────────────────

interface Reconocedor {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult:
    | ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void)
    | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

/** El reconocimiento del navegador, si lo tiene (Chrome, Edge, Safari). */
function reconocedorDelNavegador(): Reconocedor | null {
  const w = window as unknown as Record<string, unknown>;
  const Clase = (w.SpeechRecognition ?? w.webkitSpeechRecognition) as
    (new () => Reconocedor) | undefined;
  return Clase ? new Clase() : null;
}

type ViaDeVoz = "navegador" | "grabacion" | "ninguna";


/**
 * Dictar y leer en voz alta.
 *
 * Dictado: el reconocimiento del navegador cuando existe —no sale nada hacia
 * nuestro servidor hasta que se pregunta—; si no, se graba con el micrófono y
 * se manda al proveedor de transcripción de la empresa (`POST /voz/dictado`,
 * que no guarda la voz). Lectura: `speechSynthesis`, del propio navegador.
 */
function useVoz() {
  const { i18n } = useTranslation();
  const voz = idiomaDeVoz(
    i18n.resolvedLanguage ?? i18n.language ?? "es",
    localizacion(),
  );
  const [activo, setActivo] = useState(false);
  const [escuchando, setEscuchando] = useState(false);
  const [leyendo, setLeyendo] = useState(false);
  const grabadora = useRef<MediaRecorder | null>(null);
  const via: ViaDeVoz =
    typeof window !== "undefined" && reconocedorDelNavegador()
      ? "navegador"
      : typeof window !== "undefined" &&
          typeof MediaRecorder !== "undefined" &&
          Boolean(navigator.mediaDevices?.getUserMedia)
        ? "grabacion"
        : "ninguna";

  function escuchar(): Promise<string> {
    const rec = reconocedorDelNavegador();
    if (rec) {
      return new Promise((resolver, rechazar) => {
        let dicho = "";
        rec.lang = voz;
        rec.interimResults = false;
        rec.continuous = false;
        rec.onresult = (e) => {
          dicho = Array.from(e.results)
            .map((r) => r[0]?.transcript ?? "")
            .join(" ")
            .trim();
        };
        rec.onerror = (e) => {
          setEscuchando(false);
          rechazar(new Error(e.error));
        };
        rec.onend = () => {
          setEscuchando(false);
          resolver(dicho);
        };
        setEscuchando(true);
        rec.start();
      });
    }
    if (via !== "grabacion") return Promise.resolve("");
    return navigator.mediaDevices.getUserMedia({ audio: true }).then(
      (flujo) =>
        new Promise<string>((resolver, rechazar) => {
          const trozos: Blob[] = [];
          const g = new MediaRecorder(flujo);
          grabadora.current = g;
          g.ondataavailable = (e) => trozos.push(e.data);
          g.onstop = () => {
            flujo.getTracks().forEach((p) => p.stop());
            setEscuchando(false);
            const tipo = g.mimeType || "audio/webm";
            const fichero = new File(trozos, "dictado.webm", { type: tipo });
            subir<{ texto: string }>("/api/v1/voz/dictado", fichero, {
              idioma: voz.split("-")[0] ?? "es",
            })
              .then((r) => resolver(r.texto))
              .catch(rechazar);
          };
          setEscuchando(true);
          g.start();
        }),
    );
  }

  function terminar() {
    grabadora.current?.stop();
  }

  function leer(texto: string) {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const frase = new SpeechSynthesisUtterance(texto);
    frase.lang = voz;
    frase.onend = () => setLeyendo(false);
    setLeyendo(true);
    window.speechSynthesis.speak(frase);
  }

  function callar() {
    window.speechSynthesis?.cancel();
    setLeyendo(false);
  }

  return {
    activo,
    setActivo,
    escuchando,
    leyendo,
    via,
    escuchar,
    terminar,
    leer,
    callar,
  };
}
