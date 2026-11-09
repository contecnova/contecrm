/**
 * Transcribir una llamada o reunión, resumirla y convertir sus compromisos en
 * tareas, desde la ficha de la actividad (CRM-01.02.01.05, CRM-01.02.01.06).
 *
 * `POST /transcripciones` recibía el texto ya transcrito y no resumía ni
 * guardaba. Aquí se sube el audio (queda como adjunto de la actividad), se da
 * el enlace a la grabación o se pega el texto; el proveedor de transcripción
 * es una conexión de Integraciones (plantilla instalable), el resumen y los
 * compromisos los saca el modelo de la casa, y todo queda guardado en la
 * actividad. Cada compromiso es una propuesta: se corrige, se confirma —y
 * entonces se crea la tarea con tu usuario— o se descarta.
 *
 * Lo que importa de la pantalla es poder no fiarse: la confianza del
 * proveedor, la cita de cada compromiso y si esa cita está de verdad en lo
 * transcrito.
 */

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { llamar, subir } from "@/lib/api";
import { cifra, fechaHora, localizacion } from "@/lib/formato";
import { useSuperficie } from "@/lib/permisos";

interface Plantilla {
  clave: string;
  nombre: string;
  envio: string;
}

interface Proveedor {
  configurado: boolean;
  envio: string;
  max_mb: number;
  plantillas: Plantilla[];
  porque: string;
}

export interface Compromiso {
  n: number;
  tipo: string;
  texto: string;
  quien: string;
  cuando?: string | null;
  cita?: string | null;
  cita_literal: boolean;
  se_hace_tarea: boolean;
  estado: "propuesta" | "confirmada" | "descartada";
  tarea_id?: string | null;
}

export interface Transcripcion {
  id: string;
  origen: string;
  texto: string;
  confianza: number | null;
  fiable: boolean;
  minutos: number | null;
  resumen: string;
  compromisos: Compromiso[];
  descartados: { elemento: string; porque: string }[];
  estado: string;
  aviso: string;
  que_no_es: string;
  created_at: string | null;
}

const BASES = [
  "consentimiento_de_todos",
  "aviso_y_no_oposicion",
  "obligacion_legal",
] as const;

type Fuente = "audio" | "enlace" | "texto";

export function TranscripcionDeReunion({
  actividadId,
}: {
  actividadId: string;
}) {
  const { t } = useTranslation();
  const { tiene } = useSuperficie();
  const [proveedor, setProveedor] = useState<Proveedor | null>(null);
  const [lista, setLista] = useState<Transcripcion[]>([]);
  const [fuente, setFuente] = useState<Fuente>("audio");
  const [fichero, setFichero] = useState<File | null>(null);
  const [enlace, setEnlace] = useState("");
  const [texto, setTexto] = useState("");
  const [base, setBase] = useState<string>(BASES[0]);
  const [avisados, setAvisados] = useState(false);
  const [idioma, setIdioma] = useState(
    () => localizacion().split("-")[0] ?? "es",
  );
  const [plantilla, setPlantilla] = useState("");
  const [urlBase, setUrlBase] = useState("");
  const [trabajando, setTrabajando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    llamar<Proveedor>("/api/v1/transcripciones/proveedor")
      .then((r) => setProveedor(r.datos))
      .catch(() => setProveedor(null));
    llamar<{ items: Transcripcion[] }>(
      `/api/v1/transcripciones/reuniones?objeto=actividad&objeto_id=${actividadId}`,
    )
      .then((r) => setLista(r.datos.items))
      .catch((e) => setFallo(e));
  }, [actividadId]);

  useEffect(() => {
    cargar();
  }, [cargar]);

  async function instalar() {
    setTrabajando(true);
    setFallo(null);
    try {
      const r = await llamar<Proveedor>("/api/v1/transcripciones/proveedor", {
        metodo: "POST",
        cuerpo: { plantilla, url_base: urlBase.trim() },
      });
      setProveedor(r.datos);
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
    }
  }

  async function transcribir(evento: FormEvent) {
    evento.preventDefault();
    setTrabajando(true);
    setFallo(null);
    try {
      const nueva = await subir<Transcripcion>(
        "/api/v1/transcripciones/reuniones/transcribir",
        fuente === "audio" ? fichero : null,
        {
          objeto: "actividad",
          objeto_id: actividadId,
          base_para_grabar: base,
          participantes_avisados: String(avisados),
          idioma: idioma.trim() || "es",
          ...(fuente === "enlace" ? { enlace: enlace.trim() } : {}),
          ...(fuente === "texto" ? { texto } : {}),
        },
      );
      setLista((l) => [nueva, ...l]);
      setFichero(null);
      setEnlace("");
      setTexto("");
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
    }
  }

  const listo =
    avisados &&
    (fuente === "audio"
      ? Boolean(fichero) && Boolean(proveedor?.configurado)
      : fuente === "enlace"
        ? /^https?:\/\//.test(enlace.trim()) && Boolean(proveedor?.configurado)
        : texto.trim().length > 20);

  if (!tiene("ia:usar")) return null;

  return (
    <section className="card mb-4 p-4" aria-labelledby="transcripcion-titulo">
      <h2 id="transcripcion-titulo" className="section-label mb-1">
        {t("transcripcionReunion.titulo")}
      </h2>
      <p className="mb-3 text-rotulo text-ink-faint">
        {t("transcripcionReunion.ayuda")}
      </p>

      <div role="status" className="mb-3 text-rotulo">
        {proveedor ? (
          proveedor.configurado ? (
            <span className="text-ink-faint">
              {t("transcripcionReunion.conProveedor", {
                envio: t(`transcripcionReunion.envios.${proveedor.envio}`, {
                  defaultValue: proveedor.envio,
                }),
                mb: proveedor.max_mb,
              })}
            </span>
          ) : (
            <span className="text-warning">{proveedor.porque}</span>
          )
        ) : null}
      </div>

      {proveedor && !proveedor.configurado && tiene("ia:administrar") ? (
        <div className="mb-4 grid gap-2 rounded-lg border border-ink-dim/30 p-3 md:grid-cols-3">
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("transcripcionReunion.plantilla")}
            <select
              className="input-base"
              value={plantilla}
              onChange={(e) => setPlantilla(e.target.value)}
            >
              <option value="">—</option>
              {proveedor.plantillas.map((p) => (
                <option key={p.clave} value={p.clave}>
                  {p.nombre}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("transcripcionReunion.urlBase")}
            <input
              className="input-base"
              value={urlBase}
              placeholder="https://"
              onChange={(e) => setUrlBase(e.target.value)}
            />
          </label>
          <div className="flex items-end">
            <button
              type="button"
              className="btn-secondary"
              disabled={!plantilla || trabajando}
              onClick={() => void instalar()}
            >
              <Icono nombre="cable" tamano="sm" />
              {t("transcripcionReunion.instalar")}
            </button>
          </div>
          <p className="text-rotulo text-ink-faint md:col-span-3">
            {t("transcripcionReunion.instalarAyuda")}
          </p>
        </div>
      ) : null}

      <form
        className="grid gap-2 md:grid-cols-2"
        onSubmit={(e) => void transcribir(e)}
      >
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("transcripcionReunion.fuente")}
          <select
            className="input-base"
            value={fuente}
            onChange={(e) => setFuente(e.target.value as Fuente)}
          >
            {(["audio", "enlace", "texto"] as const).map((f) => (
              <option key={f} value={f}>
                {t(`transcripcionReunion.fuentes.${f}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("transcripcionReunion.base")}
          <select
            className="input-base"
            value={base}
            onChange={(e) => setBase(e.target.value)}
          >
            {BASES.map((b) => (
              <option key={b} value={b}>
                {t(`transcripcionReunion.bases.${b}`)}
              </option>
            ))}
          </select>
        </label>
        {fuente === "audio" ? (
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-2">
            {t("transcripcionReunion.fichero")}
            <input
              className="input-base"
              type="file"
              accept="audio/*,video/*"
              onChange={(e) => setFichero(e.target.files?.[0] ?? null)}
            />
          </label>
        ) : fuente === "enlace" ? (
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-2">
            {t("transcripcionReunion.enlace")}
            <input
              className="input-base"
              type="url"
              value={enlace}
              placeholder="https://"
              onChange={(e) => setEnlace(e.target.value)}
            />
          </label>
        ) : (
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-2">
            {t("transcripcionReunion.texto")}
            <textarea
              className="input-base min-h-24"
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
            />
          </label>
        )}
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("transcripcionReunion.idioma")}
          <input
            className="input-base"
            value={idioma}
            maxLength={10}
            onChange={(e) => setIdioma(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-2 text-rotulo text-ink-muted">
          <input
            type="checkbox"
            checked={avisados}
            onChange={(e) => setAvisados(e.target.checked)}
          />
          {t("transcripcionReunion.avisados")}
        </label>
        <div className="md:col-span-2">
          <button
            type="submit"
            className="btn-primary"
            disabled={!listo || trabajando}
          >
            <Icono nombre="graphic_eq" tamano="sm" />
            {trabajando
              ? t("transcripcionReunion.trabajando")
              : t("transcripcionReunion.transcribir")}
          </button>
        </div>
      </form>

      {fallo ? (
        <div className="mt-3">
          <Fallo error={fallo} />
        </div>
      ) : null}

      <ol className="mt-4 flex flex-col gap-4">
        {lista.map((tr) => (
          <li key={tr.id}>
            <UnaTranscripcion
              transcripcion={tr}
              alCambiar={(nueva) =>
                setLista((l) => l.map((x) => (x.id === nueva.id ? nueva : x)))
              }
            />
          </li>
        ))}
      </ol>
    </section>
  );
}

function UnaTranscripcion({
  transcripcion: tr,
  alCambiar,
}: {
  transcripcion: Transcripcion;
  alCambiar: (t: Transcripcion) => void;
}) {
  const { t } = useTranslation();
  return (
    <article className="rounded-lg border border-ink-dim/30 p-3">
      <p className="text-rotulo text-ink-faint">
        {fechaHora(tr.created_at)} ·{" "}
        {t(`transcripcionReunion.fuentes.${tr.origen}`, {
          defaultValue: tr.origen,
        })}
        {tr.minutos
          ? ` · ${t("transcripcionReunion.minutos", { n: tr.minutos })}`
          : ""}
        {" · "}
        <span className={tr.fiable ? "chip-dato" : "chip-dato text-warning"}>
          {tr.confianza === null
            ? t("transcripcionReunion.sinConfianza")
            : t("transcripcionReunion.confianza", {
                pct: cifra(Math.round(tr.confianza * 100)),
              })}
        </span>
      </p>
      {tr.resumen ? (
        <p className="mt-2 whitespace-pre-line text-dato text-ink">
          {tr.resumen}
        </p>
      ) : null}
      {tr.aviso ? (
        <p className="mt-1 text-rotulo text-warning">{tr.aviso}</p>
      ) : null}
      <p className="mt-1 text-rotulo text-ink-faint">{tr.que_no_es}</p>

      {tr.compromisos.length ? (
        <>
          <h3 className="section-label mt-3 mb-1">
            {t("transcripcionReunion.compromisos")}
          </h3>
          <ul className="flex flex-col gap-2">
            {tr.compromisos.map((c) => (
              <li key={c.n}>
                <UnCompromiso
                  transcripcionId={tr.id}
                  compromiso={c}
                  alCambiar={alCambiar}
                />
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {tr.descartados.length ? (
        <details className="mt-2 text-rotulo text-ink-muted">
          <summary>
            {t("transcripcionReunion.descartados", {
              n: tr.descartados.length,
            })}
          </summary>
          <ul className="mt-1 list-disc pl-5">
            {tr.descartados.map((d, i) => (
              <li key={i}>
                {d.elemento} — {d.porque}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <details className="mt-2 text-rotulo text-ink-muted">
        <summary>{t("transcripcionReunion.verTexto")}</summary>
        <p className="mt-1 whitespace-pre-line text-dato text-ink">
          {tr.texto}
        </p>
      </details>
    </article>
  );
}

function UnCompromiso({
  transcripcionId,
  compromiso: c,
  alCambiar,
}: {
  transcripcionId: string;
  compromiso: Compromiso;
  alCambiar: (t: Transcripcion) => void;
}) {
  const { t } = useTranslation();
  const [asunto, setAsunto] = useState(c.texto);
  const [vence, setVence] = useState(
    c.cuando && /^\d{4}-\d{2}-\d{2}/.test(c.cuando)
      ? `${c.cuando.slice(0, 10)}T09:00`
      : "",
  );
  const [trabajando, setTrabajando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  async function decidir(confirmar: boolean) {
    setTrabajando(true);
    setFallo(null);
    try {
      const r = await llamar<Transcripcion>(
        `/api/v1/transcripciones/reuniones/${transcripcionId}/compromisos/${c.n}`,
        {
          metodo: "POST",
          cuerpo: {
            confirmar,
            asunto: asunto.trim(),
            vence_at: vence ? new Date(vence).toISOString() : "",
          },
        },
      );
      alCambiar(r.datos);
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
    }
  }

  return (
    <div className="rounded-lg border border-accent/30 bg-accent/5 p-3">
      <p className="text-dato text-ink">
        <span className="chip-dato mr-2">
          {t(`transcripcionReunion.tipos.${c.tipo}`, { defaultValue: c.tipo })}
        </span>
        {c.texto}{" "}
        <span className="text-rotulo text-ink-muted">
          — {c.quien}
          {c.cuando ? ` · ${c.cuando}` : ""}
        </span>
      </p>
      {c.cita ? (
        <p className="mt-1 text-rotulo text-ink-faint">
          «{c.cita}»{" "}
          {c.cita_literal ? null : (
            <span className="text-warning">
              {t("transcripcionReunion.citaNoLiteral")}
            </span>
          )}
        </p>
      ) : null}
      {c.estado === "propuesta" ? (
        <div className="mt-2 grid gap-2 md:grid-cols-[1fr_auto_auto_auto] md:items-end">
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("transcripcionReunion.asuntoTarea")}
            <input
              className="input-base"
              value={asunto}
              maxLength={300}
              onChange={(e) => setAsunto(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("transcripcionReunion.vence")}
            <input
              className="input-base"
              type="datetime-local"
              value={vence}
              onChange={(e) => setVence(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="btn-primary"
            disabled={trabajando || !asunto.trim()}
            onClick={() => void decidir(true)}
          >
            <Icono nombre="check" tamano="sm" />
            {c.se_hace_tarea
              ? t("transcripcionReunion.crearTarea")
              : t("transcripcionReunion.confirmar")}
          </button>
          <button
            type="button"
            className="btn-secondary"
            disabled={trabajando}
            onClick={() => void decidir(false)}
          >
            {t("transcripcionReunion.descartar")}
          </button>
        </div>
      ) : (
        <p role="status" className="mt-1 text-rotulo text-ink-muted">
          {c.estado === "descartada" ? (
            t("transcripcionReunion.descartada")
          ) : c.tarea_id ? (
            <>
              {t("transcripcionReunion.tareaCreada")}{" "}
              <Link
                className="text-accent hover:underline"
                to={`/m/actividades/actividad/${c.tarea_id}`}
              >
                {t("transcripcionReunion.abrirTarea")}
              </Link>
            </>
          ) : (
            t("transcripcionReunion.confirmada")
          )}
        </p>
      )}
      {fallo ? (
        <div className="mt-2">
          <Fallo error={fallo} />
        </div>
      ) : null}
    </div>
  );
}
