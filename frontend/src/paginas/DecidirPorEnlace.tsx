/**
 * Decidir una aprobación desde el correo, sin entrar al CRM (CRM-00.03.05.12).
 *
 * Quien abre esto viene de un correo y no tiene por qué haber entrado: por eso
 * va fuera del marco —sin menú, sin paleta— y pide a la API **sin cookie**. Con
 * la cookie de una sesión caducada en el navegador, el gateway contestaría
 * «tu sesión ha caducado» a alguien que no necesita ninguna.
 *
 * Abrir la página NO decide nada ni gasta el enlace: los escáneres de correo
 * abren los enlaces para revisarlos, y una página que decidiera al cargarse
 * aprobaría por ellos. Se decide pulsando, con comentario si se quiere.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { config } from "@/lib/config";
import { fechaHora } from "@/lib/formato";

interface Vista {
  titulo: string;
  objeto: string;
  etapa: string;
  datos: Record<string, string | number | boolean | null>;
  caduca_at: string;
  decisiones: string[];
}

type Decision = "aprobar" | "rechazar" | "pedir_cambios";

class EnlaceInvalido extends Error {}

async function pedir<T>(ruta: string, cuerpo: unknown): Promise<T> {
  const respuesta = await fetch(`${config().apiBase}${ruta}`, {
    method: "POST",
    credentials: "omit",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo),
  });
  const texto = await respuesta.text();
  const datos = texto ? (JSON.parse(texto) as unknown) : null;
  if (respuesta.status === 401 || respuesta.status === 422) {
    throw new EnlaceInvalido();
  }
  if (!respuesta.ok) {
    const d = datos as { detail?: string; title?: string } | null;
    throw new Error(d?.detail || d?.title || String(respuesta.status));
  }
  return datos as T;
}

export function DecidirPorEnlace() {
  const { t } = useTranslation();
  const token = new URLSearchParams(window.location.search).get("t") ?? "";
  const [vista, setVista] = useState<Vista | null>(null);
  const [invalido, setInvalido] = useState(!token);
  const [fallo, setFallo] = useState("");
  const [comentario, setComentario] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [hecho, setHecho] = useState<{
    decision: Decision;
    estado: string;
  } | null>(null);

  useEffect(() => {
    if (!token) return;
    pedir<Vista>("/api/v1/enlace-de-aprobacion/ver", { token })
      .then(setVista)
      .catch((e) => {
        if (e instanceof EnlaceInvalido) setInvalido(true);
        else setFallo(e instanceof Error ? e.message : String(e));
      });
  }, [token]);

  async function decidir(decision: Decision) {
    setEnviando(true);
    setFallo("");
    try {
      const r = await pedir<{ decision: Decision; estado: string }>(
        "/api/v1/enlace-de-aprobacion/decidir",
        { token, decision, comentario },
      );
      setHecho(r);
    } catch (e) {
      if (e instanceof EnlaceInvalido) setInvalido(true);
      else setFallo(e instanceof Error ? e.message : String(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <main className="min-h-screen bg-paper-sunk px-4 py-10">
      <div className="mx-auto max-w-xl">
        <p className="mb-4 text-rotulo font-semibold uppercase tracking-[0.055em] text-ink-muted">
          {config().nombre}
        </p>
        <h1 className="mb-1 text-pagina font-bold text-ink">
          {t("decidirPorEnlace.titulo")}
        </h1>
        <p className="mb-6 text-dato text-ink-muted">
          {t("decidirPorEnlace.entradilla")}
        </p>

        <div role="status">
          {invalido ? (
            <section className="card p-4">
              <p className="flex items-center gap-2 font-medium text-ink">
                <Icono nombre="link_off" tamano="sm" />
                {t("decidirPorEnlace.invalido")}
              </p>
              <p className="mt-1 text-dato text-ink-muted">
                {t("decidirPorEnlace.invalidoDetalle")}
              </p>
            </section>
          ) : hecho ? (
            <section className="card p-4">
              <p className="flex items-center gap-2 font-medium text-ink">
                <Icono nombre="task_alt" tamano="sm" />
                {t(`decidirPorEnlace.hecho.${hecho.decision}`)}
              </p>
              <p className="mt-1 text-dato text-ink-muted">
                {t("decidirPorEnlace.estadoAhora", {
                  estado: t(`decidirPorEnlace.estados.${hecho.estado}`, {
                    defaultValue: hecho.estado,
                  }),
                })}
              </p>
            </section>
          ) : null}
          {fallo ? <p className="mt-3 text-dato text-danger">{fallo}</p> : null}
        </div>

        {!invalido && !hecho && !vista && !fallo ? <Cargando /> : null}

        {vista && !hecho && !invalido ? (
          <>
            <section className="card mb-4 p-4">
              <h2 className="section-label mb-2">
                {t("decidirPorEnlace.queSeDecide")}
              </h2>
              <p className="text-titulin font-semibold text-ink">
                {vista.titulo}
              </p>
              <p className="text-dato text-ink-muted">
                {t("decidirPorEnlace.etapa", { etapa: vista.etapa })}
              </p>
              {Object.keys(vista.datos).length > 0 ? (
                <dl className="mt-3 grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-1 text-dato">
                  {Object.entries(vista.datos).map(([clave, valor]) => (
                    <div key={clave} className="contents">
                      <dt className="text-ink-muted">
                        {clave.replace(/_/g, " ")}
                      </dt>
                      <dd className="text-ink">{String(valor ?? "—")}</dd>
                    </div>
                  ))}
                </dl>
              ) : null}
              <p className="mt-3 text-rotulo text-ink-faint">
                {t("decidirPorEnlace.caduca", {
                  fecha: fechaHora(vista.caduca_at),
                })}
              </p>
            </section>

            <section className="card p-4">
              <h2 className="section-label mb-2">
                {t("decidirPorEnlace.tuDecision")}
              </h2>
              <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
                {t("decidirPorEnlace.comentario")}
                <textarea
                  className="input-base min-h-[5rem]"
                  value={comentario}
                  maxLength={2000}
                  onChange={(e) => setComentario(e.target.value)}
                />
              </label>
              <p className="mt-1 text-rotulo text-ink-faint">
                {t("decidirPorEnlace.comentarioAyuda")}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  className="btn-primary"
                  disabled={enviando}
                  onClick={() => void decidir("aprobar")}
                >
                  <Icono nombre="check" tamano="sm" />
                  {t("decidirPorEnlace.aprobar")}
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={enviando || !comentario.trim()}
                  title={
                    comentario.trim()
                      ? undefined
                      : t("decidirPorEnlace.pideComentario")
                  }
                  onClick={() => void decidir("pedir_cambios")}
                >
                  <Icono nombre="edit_note" tamano="sm" />
                  {t("decidirPorEnlace.pedirCambios")}
                </button>
                <button
                  type="button"
                  className="btn-secondary text-danger"
                  disabled={enviando}
                  onClick={() => void decidir("rechazar")}
                >
                  <Icono nombre="close" tamano="sm" />
                  {t("decidirPorEnlace.rechazar")}
                </button>
              </div>
              <p className="mt-3 text-rotulo text-ink-faint">
                {t("decidirPorEnlace.unSoloUso")}
              </p>
            </section>
          </>
        ) : null}
      </div>
    </main>
  );
}
