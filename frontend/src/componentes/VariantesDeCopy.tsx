/**
 * Variantes de copy generadas por el modelo y revisadas por una persona, en la
 * ficha de una plantilla de correo (CRM-02.04.01.04).
 *
 * `POST /variantes` recibía los textos ya escritos. Aquí se parte de un texto
 * —el asunto de la plantilla, o lo que se escriba— y un objetivo, el modelo de
 * la casa propone N variantes, se guardan como propuesta colgadas de la
 * plantilla, y se aprueban (se pueden reescribir antes) o se rechazan de una
 * en una. Gana una aprobada. Las cifras, garantías y superlativos se marcan
 * para que nadie los apruebe leyendo por encima.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { llamar } from "@/lib/api";
import { useSuperficie } from "@/lib/permisos";

export interface Variante {
  id: string;
  lote_id: string;
  texto_propuesto: string;
  texto_final: string | null;
  estado: "propuesta" | "aprobada" | "rechazada";
  ganadora: boolean;
  afirmaciones: { texto: string; es: string }[];
  hubo_reescritura: boolean;
  motivo: string;
}

const CANALES = ["asunto", "email", "sms", "push", "anuncio", "web", "redes"];

export function VariantesDeCopy({
  objeto,
  objetoRef,
  textoBase,
}: {
  objeto: string;
  objetoRef: string;
  textoBase: string;
}) {
  const { t } = useTranslation();
  const { tiene } = useSuperficie();
  const [base, setBase] = useState(textoBase);
  const [objetivo, setObjetivo] = useState("");
  const [canal, setCanal] = useState("asunto");
  const [cuantas, setCuantas] = useState(3);
  const [lista, setLista] = useState<Variante[]>([]);
  const [aviso, setAviso] = useState("");
  const [trabajando, setTrabajando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    llamar<{ items: Variante[] }>(
      `/api/v1/variantes/generadas?objeto=${encodeURIComponent(objeto)}&objeto_ref=${encodeURIComponent(objetoRef)}`,
    )
      .then((r) => setLista(r.datos.items))
      .catch((e) => setFallo(e));
  }, [objeto, objetoRef]);

  useEffect(() => {
    cargar();
  }, [cargar]);

  async function generar() {
    setTrabajando(true);
    setFallo(null);
    setAviso("");
    try {
      const r = await llamar<{ variantes: Variante[]; aviso: string }>(
        "/api/v1/variantes/generar",
        {
          metodo: "POST",
          cuerpo: {
            base,
            objetivo,
            canal,
            cuantas,
            objeto,
            objeto_ref: objetoRef,
          },
        },
      );
      setLista((l) => [...r.datos.variantes, ...l]);
      setAviso(r.datos.aviso);
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
    }
  }

  if (!tiene("ia:usar")) return null;

  const reemplazar = (nueva: Variante) =>
    setLista((l) =>
      l.map((v) =>
        v.id === nueva.id
          ? nueva
          : nueva.ganadora && v.lote_id === nueva.lote_id
            ? { ...v, ganadora: false }
            : v,
      ),
    );

  return (
    <section className="card mb-4 p-4" aria-labelledby="variantes-titulo">
      <h2 id="variantes-titulo" className="section-label mb-1">
        {t("variantesCopy.titulo")}
      </h2>
      <p className="mb-3 text-rotulo text-ink-faint">
        {t("variantesCopy.ayuda")}
      </p>
      <div className="grid gap-2 md:grid-cols-4">
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-4">
          {t("variantesCopy.base")}
          <textarea
            className="input-base min-h-16"
            value={base}
            onChange={(e) => setBase(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-2">
          {t("variantesCopy.objetivo")}
          <input
            className="input-base"
            value={objetivo}
            placeholder={t("variantesCopy.ejemploObjetivo")}
            onChange={(e) => setObjetivo(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("variantesCopy.canal")}
          <select
            className="input-base"
            value={canal}
            onChange={(e) => setCanal(e.target.value)}
          >
            {CANALES.map((c) => (
              <option key={c} value={c}>
                {t(`variantesCopy.canales.${c}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("variantesCopy.cuantas")}
          <input
            className="input-base"
            type="number"
            min={1}
            max={20}
            value={cuantas}
            onChange={(e) => setCuantas(Number(e.target.value) || 1)}
          />
        </label>
        <div className="md:col-span-4">
          <button
            type="button"
            className="btn-primary"
            disabled={trabajando || !base.trim()}
            onClick={() => void generar()}
          >
            <Icono nombre="auto_awesome" tamano="sm" />
            {trabajando
              ? t("variantesCopy.generando")
              : t("variantesCopy.generar")}
          </button>
        </div>
      </div>
      <div role="status" className="mt-2">
        {aviso ? <p className="text-rotulo text-warning">{aviso}</p> : null}
        {fallo ? <Fallo error={fallo} /> : null}
      </div>
      <ul className="mt-3 flex flex-col gap-2">
        {lista.map((v) => (
          <li key={v.id}>
            <UnaVariante variante={v} alCambiar={reemplazar} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function UnaVariante({
  variante: v,
  alCambiar,
}: {
  variante: Variante;
  alCambiar: (v: Variante) => void;
}) {
  const { t } = useTranslation();
  const [texto, setTexto] = useState(v.texto_final ?? v.texto_propuesto);
  const [motivo, setMotivo] = useState("");
  const [trabajando, setTrabajando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  async function enviar(ruta: string, cuerpo?: Record<string, unknown>) {
    setTrabajando(true);
    setFallo(null);
    try {
      const r = await llamar<Variante>(ruta, { metodo: "POST", cuerpo });
      alCambiar(r.datos);
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
    }
  }

  const ruta = `/api/v1/variantes/generadas/${v.id}`;
  return (
    <div
      className={
        v.ganadora
          ? "rounded-lg border border-accent bg-accent/5 p-3"
          : "rounded-lg border border-ink-dim/30 p-3"
      }
    >
      <p className="mb-1 text-rotulo text-ink-faint">
        <span className="chip-dato mr-2">
          {t(`variantesCopy.estados.${v.estado}`)}
        </span>
        {v.ganadora ? (
          <span className="chip-dato mr-2">{t("variantesCopy.ganadora")}</span>
        ) : null}
        {v.hubo_reescritura ? t("variantesCopy.reescrita") : null}
      </p>
      {v.estado === "propuesta" ? (
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("variantesCopy.texto")}
          <textarea
            className="input-base min-h-12"
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
          />
        </label>
      ) : (
        <p className="text-dato text-ink">
          {v.texto_final ?? v.texto_propuesto}
        </p>
      )}
      {v.afirmaciones.length ? (
        <p className="mt-1 text-rotulo text-warning">
          {t("variantesCopy.afirmaciones")}{" "}
          {v.afirmaciones.map((a) => `«${a.texto}» (${a.es})`).join(", ")}
        </p>
      ) : null}
      {v.motivo ? (
        <p className="mt-1 text-rotulo text-ink-faint">{v.motivo}</p>
      ) : null}
      <div className="mt-2 flex flex-wrap items-end gap-2">
        {v.estado === "propuesta" ? (
          <>
            <button
              type="button"
              className="btn-primary"
              disabled={trabajando || !texto.trim()}
              onClick={() =>
                void enviar(`${ruta}/decidir`, {
                  aprobar: true,
                  texto_final: texto.trim(),
                })
              }
            >
              <Icono nombre="check" tamano="sm" />
              {t("variantesCopy.aprobar")}
            </button>
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("variantesCopy.motivo")}
              <input
                className="input-base"
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
              />
            </label>
            <button
              type="button"
              className="btn-secondary"
              disabled={trabajando}
              onClick={() =>
                void enviar(`${ruta}/decidir`, { aprobar: false, motivo })
              }
            >
              {t("variantesCopy.rechazar")}
            </button>
          </>
        ) : v.estado === "aprobada" && !v.ganadora ? (
          <button
            type="button"
            className="btn-secondary"
            disabled={trabajando}
            onClick={() => void enviar(`${ruta}/ganadora`)}
          >
            <Icono nombre="emoji_events" tamano="sm" />
            {t("variantesCopy.elegir")}
          </button>
        ) : null}
      </div>
      {fallo ? (
        <div className="mt-2">
          <Fallo error={fallo} />
        </div>
      ) : null}
    </div>
  );
}
