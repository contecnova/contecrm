/**
 * Por qué este lead cayó donde cayó, y por dónde llegó.
 *
 * Las dos preguntas que se hacen delante de un lead y que hasta el 10-11-2026
 * sólo contestaba la API: «¿por qué no me llegó a mí?» —las reglas de reparto
 * evaluadas, con el motivo por el que cada una no encajó— y «¿cómo llegó?»
 * —sus toques en orden, que se leen como una historia—. El primer y el último
 * toque van aparte porque ninguno de los dos se puede reconstruir después.
 *
 * Cerrado de entrada: son dos llamadas y la mayoría de las veces se mira la
 * ficha por otra cosa.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";
import { nombreDe, usePersonas } from "@/lib/personas";

interface Evaluada {
  regla: string;
  resultado: string;
  motivo?: string;
}

interface Decision {
  cuando: string | null;
  regla: string | null;
  asignado_a: string | null;
  cola: string | null;
  estrategia: string | null;
  evaluadas: Evaluada[] | null;
}

interface Toque {
  canal: string | null;
  fuente: string | null;
  medio: string | null;
  campana: string | null;
  cuando: string | null;
}

interface Recorrido {
  toques: Toque[];
  primer_toque: Record<string, unknown> | null;
  ultimo_toque: Record<string, unknown> | null;
  total: number;
}

function describir(toque: Record<string, unknown> | null | undefined): string {
  if (!toque) return "—";
  return (
    ["canal", "fuente", "medio", "campana"]
      .map((c) => toque[c])
      .filter((v) => typeof v === "string" && v.trim())
      .join(" · ") || "—"
  );
}

export function RepartoYOrigenDelLead({ leadId }: { leadId: string }) {
  const { t } = useTranslation();
  const personas = usePersonas();
  const [abierto, setAbierto] = useState(false);
  const [decisiones, setDecisiones] = useState<Decision[] | null>(null);
  const [recorrido, setRecorrido] = useState<Recorrido | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    if (!abierto) return;
    const control = new AbortController();
    setFallo(null);
    llamar<Decision[]>(`/api/v1/lead-routing/leads/${leadId}/explicacion`, {
      signal: control.signal,
    })
      .then((r) => setDecisiones(r.datos ?? []))
      .catch(salvoCancelacion(setFallo));
    llamar<Recorrido>(`/api/v1/origen/leads/${leadId}/recorrido`, {
      signal: control.signal,
    })
      .then((r) => setRecorrido(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [abierto, leadId]);

  return (
    <section className="card mb-4 p-4">
      <button
        type="button"
        className="flex w-full items-center justify-between text-left"
        aria-expanded={abierto}
        onClick={() => setAbierto((v) => !v)}
      >
        <h2 className="section-label">{t("repartoLead.titulo")}</h2>
        <span className="text-dato text-ink-muted">
          {abierto ? t("repartoLead.cerrar") : t("repartoLead.abrir")}
        </span>
      </button>
      {abierto ? (
        <div className="mt-2 grid gap-4 lg:grid-cols-2">
          {fallo ? <Fallo error={fallo} /> : null}
          <div>
            <h3 className="mb-1 text-titulin font-medium text-ink">
              {t("repartoLead.porQue")}
            </h3>
            {decisiones === null && !fallo ? <Cargando /> : null}
            {decisiones !== null && decisiones.length === 0 ? (
              <p className="text-dato text-ink-faint">
                {t("repartoLead.sinReparto")}
              </p>
            ) : null}
            <ul className="lista-acotada flex flex-col gap-2 pr-1">
              {(decisiones ?? []).map((d, i) => (
                <li key={`${d.cuando ?? ""}-${i}`} className="text-dato">
                  <p className="text-ink">
                    {d.asignado_a
                      ? t("repartoLead.asignadoA", {
                          quien: nombreDe(personas, d.asignado_a),
                        })
                      : t("repartoLead.aLaCola", { cola: d.cola ?? "—" })}
                    {d.regla ? ` · ${d.regla}` : ""}
                  </p>
                  <ul className="mt-1 flex flex-col gap-0.5">
                    {(d.evaluadas ?? []).map((e, j) => (
                      <li key={`${e.regla}-${j}`} className="text-rotulo">
                        <span
                          className={`chip-dato ${e.resultado === "gana" ? "chip-dato--si" : "chip-dato--no"}`}
                        >
                          {t(`repartoLead.resultado.${e.resultado}`, {
                            defaultValue: e.resultado,
                          })}
                        </span>{" "}
                        <span className="text-ink">{e.regla}</span>
                        {e.motivo ? (
                          <span className="text-ink-muted"> — {e.motivo}</span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="mb-1 text-titulin font-medium text-ink">
              {t("repartoLead.comoLlego")}
            </h3>
            {recorrido === null && !fallo ? <Cargando /> : null}
            {recorrido ? (
              <>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-dato">
                  <dt className="text-ink-muted">{t("repartoLead.primero")}</dt>
                  <dd className="text-ink">
                    {describir(recorrido.primer_toque)}
                  </dd>
                  <dt className="text-ink-muted">{t("repartoLead.ultimo")}</dt>
                  <dd className="text-ink">
                    {describir(recorrido.ultimo_toque)}
                  </dd>
                </dl>
                {recorrido.toques.length === 0 ? (
                  <p className="mt-2 text-dato text-ink-faint">
                    {t("repartoLead.sinToques")}
                  </p>
                ) : (
                  <ol className="lista-acotada mt-2 flex flex-col gap-0.5 pr-1">
                    {recorrido.toques.map((toque, i) => (
                      <li
                        key={`${toque.cuando ?? ""}-${i}`}
                        className="flex flex-wrap gap-x-2 text-dato"
                      >
                        <time className="font-mono text-rotulo text-ink-faint">
                          {(toque.cuando ?? "").slice(0, 10)}
                        </time>
                        <span className="text-ink">
                          {describir(
                            toque as unknown as Record<string, unknown>,
                          )}
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
