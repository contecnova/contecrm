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
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { cifra, esIdentificadorTecnico, humanizar } from "@/lib/formato";

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
  return (
    <>
      <CabeceraPagina
        icono="support_agent"
        titulo={t("asistente.titulo")}
        entradilla={t("asistente.entradilla")}
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <Conocimiento />
        <Datos />
      </div>
    </>
  );
}

function Conocimiento() {
  const { t } = useTranslation();
  const [pregunta, setPregunta] = useState("");
  const [r, setR] = useState<Conversacion | null>(null);
  const [accion, setAccion] = useState<Accion | null>(null);
  const [args, setArgs] = useState<Record<string, string>>({});
  const [fallo, setFallo] = useState<unknown>(null);
  const [trabajando, setTrabajando] = useState(false);

  async function preguntar() {
    setTrabajando(true);
    setFallo(null);
    setR(null);
    setAccion(null);
    try {
      const x = await llamar<Conversacion>("/api/v1/ia/asistencia/conversar", {
        metodo: "POST",
        cuerpo: { pregunta },
      });
      setR(x.datos);
      setAccion(x.datos.accion_propuesta);
      setArgs({ ...(x.datos.accion_propuesta?.argumentos ?? {}) });
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
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
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
    }
  }

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("asistente.conocimiento")}</h2>
      <p className="mb-3 text-rotulo text-ink-faint">
        {t("asistente.conocimientoAyuda")}
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
          placeholder={t("asistente.ejemploConocimiento")}
          onChange={(e) => setPregunta(e.target.value)}
        />
        <div>
          <button
            type="submit"
            className="btn-primary"
            disabled={trabajando || pregunta.trim().length < 3}
          >
            <Icono nombre="send" tamano="sm" />
            {trabajando ? t("asistente.pensando") : t("asistente.preguntar")}
          </button>
        </div>
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
