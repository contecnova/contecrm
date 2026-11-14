/**
 * Las metodologías de venta y los playbooks de cada etapa (CRM-03.01.02).
 *
 * Pedido el 09-11-2026, decidido por formulario: preguntas por etapa con
 * puntuación —MEDDIC, BANT, SPIN, Challenger o propias—, pasos y playbook
 * por etapa, y una metodología por embudo. Las de serie traen sus criterios
 * y se editan; cada criterio puede pedirse sólo desde una etapa.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { AvisoDeRecorte, Cargando, Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { listarPagina, MAXIMO_POR_PAGINA } from "@/lib/listados";
import { cn } from "@/lib/utiles";

interface Criterio {
  clave: string;
  etiqueta: string;
  peso: number;
  desde_etapa?: string | null;
}

interface Metodologia {
  id: string;
  clave: string;
  nombre: string;
  familia: string;
  pipeline: string | null;
  activa: boolean;
  criterios: Criterio[];
}

interface Etapa {
  clave: string;
  nombre: string;
  terminal: boolean;
}

interface Embudo {
  id: string;
  clave: string;
  nombre: string;
  etapas: Etapa[];
}

interface Playbook {
  id: string;
  clave: string;
  titulo: string;
  etapa: string | null;
  pasos: string[];
  activo: boolean;
}

const FAMILIAS = ["meddic", "bant", "spin", "challenger", "custom"];

function aClave(texto: string): string {
  return (
    texto
      .toLowerCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 60) || "criterio"
  );
}

export function Metodologias() {
  const { t } = useTranslation();
  const [metodologias, setMetodologias] = useState<Metodologia[] | null>(null);
  const [embudos, setEmbudos] = useState<Embudo[]>([]);
  // Si el servidor dijo que había más de lo que cabe en una página. Lo que
  // no cabía no salía en la lista ni en el desplegable, y nada lo decía: se
  // leía como que no existía.
  const [hayMasMetodologias, setHayMasMetodologias] = useState(false);
  const [hayMasEmbudos, setHayMasEmbudos] = useState(false);
  const [elegida, setElegida] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  const [nueva, setNueva] = useState({
    nombre: "",
    familia: "meddic",
    pipeline: "",
  });

  const cargar = useCallback(() => {
    listarPagina<Metodologia>("/api/v1/metodologias?limite=100")
      .then(({ filas, siguiente }) => {
        setMetodologias(filas);
        setHayMasMetodologias(siguiente !== "");
        setElegida((e) => e || filas[0]?.id || "");
      })
      .catch((e) => setFallo(e));
  }, []);
  useEffect(cargar, [cargar]);
  useEffect(() => {
    void listarPagina<Embudo>("/api/v1/pipelines?limite=50")
      .then(({ filas, siguiente }) => {
        setEmbudos(filas);
        setHayMasEmbudos(siguiente !== "");
      })
      .catch(() => setEmbudos([]));
  }, []);

  async function crear() {
    try {
      const r = await llamar<{ id: string }>("/api/v1/metodologias", {
        metodo: "POST",
        cuerpo: {
          clave: aClave(nueva.nombre),
          nombre: nueva.nombre,
          familia: nueva.familia,
          pipeline: nueva.pipeline || null,
        },
      });
      setNueva({ nombre: "", familia: "meddic", pipeline: "" });
      setElegida(r.datos.id);
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  if (fallo && !metodologias) return <Fallo error={fallo} />;
  if (!metodologias) return <Cargando />;
  const actual = metodologias.find((m) => m.id === elegida);

  return (
    <>
      <CabeceraPagina
        icono="checklist"
        titulo={t("metodologias.titulo")}
        entradilla={t("metodologias.entradilla")}
      />
      <div className="grid gap-4 lg:grid-cols-[14rem_minmax(0,1fr)]">
        <div className="card p-2">
          <ul className="lista-acotada" aria-label={t("metodologias.lista")}>
            {metodologias.map((m) => (
              <li key={m.id}>
                <button
                  type="button"
                  onClick={() => setElegida(m.id)}
                  aria-current={m.id === elegida}
                  className={cn(
                    "block w-full rounded px-3 py-1.5 text-left text-titulin",
                    m.id === elegida
                      ? "bg-accent/10 font-semibold text-accent"
                      : "text-ink hover:bg-paper-light",
                    !m.activa && "opacity-60",
                  )}
                >
                  {m.nombre}
                </button>
              </li>
            ))}
          </ul>
          {hayMasMetodologias ? (
            <AvisoDeRecorte cuantas={metodologias.length} />
          ) : null}
          <div className="mt-2 space-y-2 border-t border-ink-dim/30 p-2">
            <input
              className="input-base"
              value={nueva.nombre}
              placeholder={t("metodologias.nombreNueva")}
              aria-label={t("metodologias.nombreNueva")}
              onChange={(e) => setNueva({ ...nueva, nombre: e.target.value })}
            />
            <select
              className="input-base"
              value={nueva.familia}
              aria-label={t("metodologias.familia")}
              onChange={(e) => setNueva({ ...nueva, familia: e.target.value })}
            >
              {FAMILIAS.map((f) => (
                <option key={f} value={f}>
                  {t(`metodologias.familias.${f}`)}
                </option>
              ))}
            </select>
            <select
              className="input-base"
              value={nueva.pipeline}
              aria-label={t("metodologias.embudo")}
              onChange={(e) => setNueva({ ...nueva, pipeline: e.target.value })}
            >
              <option value="">{t("metodologias.todos")}</option>
              {embudos.map((e) => (
                <option key={e.clave} value={e.clave}>
                  {e.nombre}
                </option>
              ))}
            </select>
            {hayMasEmbudos ? <AvisoDeRecorte cuantas={embudos.length} /> : null}
            <button
              type="button"
              className="btn-secondary w-full"
              disabled={!nueva.nombre.trim()}
              onClick={() => void crear()}
            >
              <Icono nombre="add" tamano="sm" />
              {t("metodologias.crear")}
            </button>
          </div>
        </div>
        <div className="space-y-4">
          {actual ? (
            <EditorDeMetodologia
              key={actual.id}
              metodologia={actual}
              embudos={embudos}
              alCambiar={cargar}
            />
          ) : null}
          <Playbooks embudos={embudos} />
        </div>
      </div>
    </>
  );
}

function EditorDeMetodologia({
  metodologia,
  embudos,
  alCambiar,
}: {
  metodologia: Metodologia;
  embudos: Embudo[];
  alCambiar: () => void;
}) {
  const { t } = useTranslation();
  // Los criterios se han escrito de dos formas —`etiqueta`/`peso`, o
  // `pregunta`/`nombre` sin peso—; se editan en una sola, como los lee el motor.
  const [m, setM] = useState<Metodologia>(() => {
    const crudos = metodologia.criterios as (Criterio & {
      pregunta?: string;
      nombre?: string;
    })[];
    const sinPeso = !crudos.some((c) => c.peso);
    const reparto = crudos.length ? Math.round(100 / crudos.length) : 0;
    return {
      ...metodologia,
      criterios: crudos.map((c) => ({
        clave: c.clave,
        etiqueta: c.etiqueta || c.pregunta || c.nombre || c.clave,
        peso: sinPeso ? reparto : Number(c.peso) || 0,
        desde_etapa: c.desde_etapa ?? null,
      })),
    };
  });
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");
  const etapas =
    (embudos.find((e) => e.clave === m.pipeline) ?? embudos[0])?.etapas ?? [];
  const total = m.criterios.reduce((s, c) => s + (Number(c.peso) || 0), 0);

  function criterio(i: number, cambio: Partial<Criterio>) {
    setM((x) => ({
      ...x,
      criterios: x.criterios.map((c, j) => (j === i ? { ...c, ...cambio } : c)),
    }));
  }

  async function guardar() {
    setAviso("");
    try {
      await llamar(`/api/v1/metodologias/${m.id}`, {
        metodo: "PATCH",
        cuerpo: {
          nombre: m.nombre,
          pipeline: m.pipeline || null,
          activa: m.activa,
          criterios: m.criterios.map((c) => ({
            ...c,
            clave: c.clave || aClave(c.etiqueta),
            peso: Number(c.peso) || 0,
            desde_etapa: c.desde_etapa || null,
          })),
        },
      });
      setFallo(null);
      setAviso(t("metodologias.guardada"));
      alCambiar();
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <section className="card p-4">
      <div className="mb-3 grid gap-3 md:grid-cols-3">
        <label className="text-rotulo text-ink-muted">
          {t("metodologias.nombre")}
          <input
            className="input-base mt-1"
            value={m.nombre}
            onChange={(e) => setM({ ...m, nombre: e.target.value })}
          />
        </label>
        <label className="text-rotulo text-ink-muted">
          {t("metodologias.embudo")}
          <select
            className="input-base mt-1"
            value={m.pipeline ?? ""}
            onChange={(e) => setM({ ...m, pipeline: e.target.value || null })}
          >
            <option value="">{t("metodologias.todos")}</option>
            {embudos.map((e) => (
              <option key={e.clave} value={e.clave}>
                {e.nombre}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 self-end text-dato text-ink">
          <input
            type="checkbox"
            checked={m.activa}
            onChange={(e) => setM({ ...m, activa: e.target.checked })}
            className="h-4 w-4 accent-accent"
          />
          {t("metodologias.activa")}
        </label>
      </div>
      <h2 className="section-label mb-1">{t("metodologias.criterios")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("metodologias.pesoTotal", { total })}
      </p>
      <Rejilla
        titulo={t("metodologias.criterios")}
        acotada={false}
        cabeceras={[
          t("metodologias.pregunta"),
          t("metodologias.peso"),
          t("metodologias.desdeEtapa"),
          "",
        ]}
      >
        {m.criterios.map((c, i) => (
          <tr key={i} className="border-b border-ink-dim/30 last:border-0">
            <Casilla className="min-w-[18rem]">
              <input
                className="input-base"
                value={c.etiqueta}
                aria-label={t("metodologias.pregunta")}
                onChange={(e) => criterio(i, { etiqueta: e.target.value })}
              />
            </Casilla>
            <Casilla>
              <input
                type="number"
                min={0}
                className="input-base !w-20"
                value={c.peso}
                aria-label={t("metodologias.peso")}
                onChange={(e) => criterio(i, { peso: Number(e.target.value) })}
              />
            </Casilla>
            <Casilla>
              <select
                className="input-base"
                value={c.desde_etapa ?? ""}
                aria-label={t("metodologias.desdeEtapa")}
                onChange={(e) =>
                  criterio(i, { desde_etapa: e.target.value || null })
                }
              >
                <option value="">{t("metodologias.desdeElPrincipio")}</option>
                {etapas
                  .filter((e) => !e.terminal)
                  .map((e) => (
                    <option key={e.clave} value={e.clave}>
                      {e.nombre}
                    </option>
                  ))}
              </select>
            </Casilla>
            <Casilla>
              <button
                type="button"
                className="btn-link text-danger"
                aria-label={t("metodologias.quitarCriterio")}
                onClick={() =>
                  setM({
                    ...m,
                    criterios: m.criterios.filter((_, j) => j !== i),
                  })
                }
              >
                <Icono nombre="delete" tamano="sm" />
              </button>
            </Casilla>
          </tr>
        ))}
      </Rejilla>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-secondary"
          onClick={() =>
            setM({
              ...m,
              criterios: [
                ...m.criterios,
                { clave: "", etiqueta: "", peso: 10 },
              ],
            })
          }
        >
          <Icono nombre="add" tamano="sm" />
          {t("metodologias.anadirCriterio")}
        </button>
        <button
          type="button"
          className="btn-primary"
          onClick={() => void guardar()}
        >
          {t("metodologias.guardar")}
        </button>
      </div>
      <div role="status" className="mt-2">
        {fallo ? <Fallo error={fallo} /> : null}
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>
    </section>
  );
}

function Playbooks({ embudos }: { embudos: Embudo[] }) {
  const { t } = useTranslation();
  const [embudo, setEmbudo] = useState("");
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  // Con más playbooks de los que caben en una página, una etapa cuyo
  // playbook no llegó se enseñaba vacía, y escribir en ella crearía otro.
  const [hayMasPlaybooks, setHayMasPlaybooks] = useState(false);
  const [borradores, setBorradores] = useState<Record<string, string>>({});
  const [aviso, setAviso] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    void listarPagina<Playbook>(`/api/v1/playbooks?limite=${MAXIMO_POR_PAGINA}`)
      .then(({ filas, siguiente }) => {
        setPlaybooks(filas);
        setHayMasPlaybooks(siguiente !== "");
      })
      .catch(() => setPlaybooks([]));
  }, []);
  useEffect(cargar, [cargar]);

  const elegido = embudos.find((e) => e.clave === embudo) ?? embudos[0];
  const etapas = (elegido?.etapas ?? []).filter((e) => !e.terminal);
  const de = (etapa: string) =>
    playbooks.find((p) => p.etapa === etapa && p.activo);

  async function guardar(etapa: Etapa) {
    const texto =
      borradores[etapa.clave] ?? (de(etapa.clave)?.pasos ?? []).join("\n");
    const pasos = texto
      .split("\n")
      .map((p) => p.trim())
      .filter(Boolean);
    const actual = de(etapa.clave);
    setAviso("");
    try {
      if (actual) {
        await llamar(`/api/v1/playbooks/${actual.id}`, {
          metodo: "PATCH",
          cuerpo: { pasos },
        });
      } else {
        await llamar("/api/v1/playbooks", {
          metodo: "POST",
          cuerpo: {
            clave: aClave(`${elegido?.clave ?? ""}_${etapa.clave}`),
            titulo: t("metodologias.playbookDe", { etapa: etapa.nombre }),
            etapa: etapa.clave,
            pasos,
          },
        });
      }
      setFallo(null);
      setAviso(t("metodologias.playbookGuardado", { etapa: etapa.nombre }));
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <section className="card p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="section-label">{t("metodologias.playbooks")}</h2>
        {hayMasPlaybooks ? (
          <AvisoDeRecorte cuantas={playbooks.length} />
        ) : null}
        <select
          className="input-base w-auto"
          value={elegido?.clave ?? ""}
          aria-label={t("metodologias.embudo")}
          onChange={(e) => setEmbudo(e.target.value)}
        >
          {embudos.map((e) => (
            <option key={e.clave} value={e.clave}>
              {e.nombre}
            </option>
          ))}
        </select>
      </div>
      <p className="mb-3 text-rotulo text-ink-faint">
        {t("metodologias.playbooksAyuda")}
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        {etapas.map((etapa) => (
          <div
            key={etapa.clave}
            className="rounded border border-ink-dim/50 p-3"
          >
            <p className="mb-1 text-dato font-medium text-ink">
              {etapa.nombre}
            </p>
            <textarea
              className="input-base"
              rows={4}
              aria-label={t("metodologias.pasosDe", { etapa: etapa.nombre })}
              placeholder={t("metodologias.pasosEjemplo")}
              value={
                borradores[etapa.clave] ??
                (de(etapa.clave)?.pasos ?? []).join("\n")
              }
              onChange={(e) =>
                setBorradores({ ...borradores, [etapa.clave]: e.target.value })
              }
            />
            <button
              type="button"
              className="btn-secondary mt-2"
              onClick={() => void guardar(etapa)}
            >
              {t("metodologias.guardarPasos")}
            </button>
          </div>
        ))}
      </div>
      <div role="status" className="mt-2">
        {fallo ? <Fallo error={fallo} /> : null}
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>
    </section>
  );
}
