/**
 * La ficha emergente al entrar una llamada (CRM-04.02.01.05).
 *
 * Cuando suena el teléfono la ficha ya tiene que estar delante: quién llama
 * —o los candidatos, si el número lo comparten varias fichas, sin abrir la
 * primera «porque suele ser esa»—, lo que tecleó en el IVR para no volver a
 * preguntárselo y lo último que le pasó. Desde aquí se abre su ficha y se
 * transfiere con el resumen dentro.
 *
 * Pregunta primero si el tenant tiene telefonía conectada: sin ella no sondea,
 * para no hacer una petición cada pocos segundos que no puede traer nada.
 */
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Icono } from "@/componentes/Icono";
import { llamar } from "@/lib/api";

interface Candidato {
  id: string;
  nombre: string | null;
}

interface Llamada {
  id: string;
  numero: string;
  estado: string;
  contacto_id: string | null;
  cuenta_id: string | null;
  identificacion: {
    identificado?: boolean;
    nombre?: string;
    que_hacer?: string;
    candidatos?: Candidato[];
  };
  ivr: Record<string, unknown>;
  contexto: {
    ultimo_caso?: { id: string; asunto: string; estado: string };
    ultima_interaccion?: { id: string; tipo: string; asunto: string };
  };
}

export function LlamadaEntrante() {
  const { t } = useTranslation();
  const [sondeo, setSondeo] = useState<number | null>(null);
  const [llamadas, setLlamadas] = useState<Llamada[]>([]);
  const [cerradas, setCerradas] = useState<string[]>([]);
  const [pasando, setPasando] = useState<string | null>(null);
  const [destino, setDestino] = useState("");
  const [resumen, setResumen] = useState("");
  const [aviso, setAviso] = useState("");

  useEffect(() => {
    const control = new AbortController();
    llamar<{ conectado: boolean; sondeo_s?: number }>(
      "/api/v1/telefonia/perfil",
      { signal: control.signal },
    )
      .then((r) => {
        if (r.datos.conectado) setSondeo(Math.max(2, r.datos.sondeo_s ?? 5));
      })
      .catch(() => setSondeo(null));
    return () => control.abort();
  }, []);

  useEffect(() => {
    if (!sondeo) return undefined;
    let vivo = true;
    const preguntar = () =>
      llamar<{ llamadas: Llamada[] }>("/api/v1/telefonia/sonando")
        .then((r) => {
          if (vivo) setLlamadas(r.datos.llamadas ?? []);
        })
        .catch(() => undefined);
    void preguntar();
    const reloj = window.setInterval(() => void preguntar(), sondeo * 1000);
    return () => {
      vivo = false;
      window.clearInterval(reloj);
    };
  }, [sondeo]);

  const l = llamadas.find((x) => !cerradas.includes(x.id));
  if (!l) return null;
  const llamadaId = l.id;
  const ident = l.identificacion ?? {};
  const ivr = Object.entries(l.ivr ?? {});
  const ficha = l.contacto_id
    ? `/abrir/contacto/${l.contacto_id}`
    : l.cuenta_id
      ? `/abrir/cuenta/${l.cuenta_id}`
      : null;

  async function transferir(e: FormEvent) {
    e.preventDefault();
    setAviso("");
    try {
      await llamar(`/api/v1/telefonia/llamadas/${llamadaId}/transferir`, {
        metodo: "POST",
        cuerpo: { a: destino, resumen },
      });
      setAviso(t("llamadaEntrante.transferida", { a: destino }));
      setPasando(null);
      setDestino("");
      setResumen("");
    } catch (err) {
      setAviso(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <aside
      role="status"
      aria-live="polite"
      className="card fixed bottom-4 right-4 z-50 w-96 max-w-[calc(100vw-2rem)] p-4 shadow-lg"
    >
      <div className="flex items-start justify-between gap-2">
        <h2 className="section-label flex items-center gap-2">
          <Icono nombre="ring_volume" tamano="sm" />
          {t("llamadaEntrante.titulo")}
        </h2>
        <button
          type="button"
          className="btn-secondary"
          aria-label={t("llamadaEntrante.cerrar")}
          onClick={() => setCerradas((c) => [...c, l.id])}
        >
          <Icono nombre="close" tamano="sm" />
        </button>
      </div>
      <p className="mt-1 text-titulo font-medium text-ink">
        {ident.identificado ? ident.nombre : l.numero}
      </p>
      {ident.identificado ? (
        <p className="text-rotulo text-ink-muted">{l.numero}</p>
      ) : (
        <p className="text-rotulo text-ink-muted">{ident.que_hacer}</p>
      )}
      {ident.candidatos && ident.candidatos.length > 0 ? (
        <ul className="mt-2 flex flex-wrap gap-1">
          {ident.candidatos.map((c) => (
            <li key={c.id}>
              <Link className="chip-dato" to={`/abrir/contacto/${c.id}`}>
                {c.nombre ?? c.id.slice(0, 8)}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
      {ivr.length > 0 ? (
        <div className="mt-2">
          <p className="text-rotulo text-ink-muted">
            {t("llamadaEntrante.ivr")}
          </p>
          <ul className="flex flex-wrap gap-1">
            {ivr.map(([k, v]) => (
              <li key={k} className="chip-dato">
                {k}: {String(v)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {l.contexto?.ultimo_caso ? (
        <p className="mt-2 text-rotulo text-ink-muted">
          {t("llamadaEntrante.ultimoCaso", {
            asunto: l.contexto.ultimo_caso.asunto,
            estado: l.contexto.ultimo_caso.estado,
          })}
        </p>
      ) : null}
      {l.contexto?.ultima_interaccion ? (
        <p className="text-rotulo text-ink-muted">
          {t("llamadaEntrante.ultimaInteraccion", {
            asunto: l.contexto.ultima_interaccion.asunto,
          })}
        </p>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {ficha ? (
          <Link className="btn-primary" to={ficha}>
            {t("llamadaEntrante.abrirFicha")}
          </Link>
        ) : null}
        <button
          type="button"
          className="btn-secondary"
          onClick={() => setPasando(pasando ? null : l.id)}
        >
          {t("llamadaEntrante.transferir")}
        </button>
      </div>
      {pasando === l.id ? (
        <form className="mt-3 grid gap-2" onSubmit={transferir}>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("llamadaEntrante.a")}
            <input
              className="input-base"
              required
              value={destino}
              onChange={(e) => setDestino(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("llamadaEntrante.resumen")}
            <textarea
              className="input-base"
              rows={2}
              required
              value={resumen}
              onChange={(e) => setResumen(e.target.value)}
            />
          </label>
          <button type="submit" className="btn-primary">
            {t("llamadaEntrante.pasar")}
          </button>
        </form>
      ) : null}
      {aviso ? <p className="mt-2 text-rotulo text-ink">{aviso}</p> : null}
    </aside>
  );
}
