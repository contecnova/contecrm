/**
 * Lo que me toca revisar de mi gente, en mi bandeja (CRM-07.03.02.15).
 *
 * Va dentro de la bandeja de aprobaciones porque es lo mismo: algo que espera
 * una decisión mía. Cada acceso se confirma o se retira; **retirar lo quita en
 * el momento** —el rol sale de la membresía y se cierran sus sesiones— y por eso
 * pide motivo. Si no hay nada que revisar, no ocupa sitio.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";
import { cn } from "@/lib/utiles";

interface Revision {
  id: string;
  usuario: string;
  tipo: string;
  valor: string;
  decision: string;
  vencida: boolean;
}

interface Campana {
  campana_id: string;
  nombre: string;
  plazo_at: string;
  fuera_de_plazo: boolean;
  revisiones: Revision[];
}

export function MiRevisionDeAccesos() {
  const { t } = useTranslation();
  const [campanas, setCampanas] = useState<Campana[]>([]);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<Campana[]>("/api/v1/recertificacion/mias", {
      signal: control.signal,
    })
      .then((r) => setCampanas(Array.isArray(r.datos) ? r.datos : []))
      .catch(salvoCancelacion(() => setCampanas([])));
    return () => control.abort();
  }, []);
  useEffect(cargar, [cargar]);

  if (campanas.length === 0) return null;

  return (
    <section className="card mt-4 p-4" aria-label={t("miRevision.titulo")}>
      <h2 className="section-label mb-1">{t("miRevision.titulo")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">{t("miRevision.ayuda")}</p>
      {fallo ? <Fallo error={fallo} /> : null}
      <div className="flex flex-col gap-4">
        {campanas.map((c) => (
          <div key={c.campana_id}>
            <p className="mb-1 text-dato font-medium text-ink">
              {c.nombre}{" "}
              <span
                className={cn(
                  "chip-dato",
                  c.fuera_de_plazo ? "chip-dato--mal" : "chip-dato--aviso",
                )}
              >
                {t(
                  c.fuera_de_plazo ? "miRevision.vencio" : "miRevision.hasta",
                  { fecha: c.plazo_at },
                )}
              </span>
            </p>
            <ul className="lista-acotada divide-y divide-ink-dim/30">
              {c.revisiones.map((r) => (
                <FilaRevision
                  key={r.id}
                  revision={r}
                  alDecidir={cargar}
                  alFallar={setFallo}
                />
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

function FilaRevision({
  revision: r,
  alDecidir,
  alFallar,
}: {
  revision: Revision;
  alDecidir: () => void;
  alFallar: (e: unknown) => void;
}) {
  const { t } = useTranslation();
  const [retirando, setRetirando] = useState(false);
  const [motivo, setMotivo] = useState("");

  async function decidir(decision: "confirmado" | "retirado") {
    try {
      await llamar(`/api/v1/recertificacion/revisiones/${r.id}/decision`, {
        metodo: "POST",
        cuerpo: { decision, comentario: motivo },
      });
      alFallar(null);
      alDecidir();
    } catch (e) {
      alFallar(e);
    }
  }

  return (
    <li className="py-2 text-dato">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-medium text-ink">{r.usuario}</span>
          <span className="chip-dato">
            {t(`miRevision.tipos.${r.tipo}`)}: {r.valor}
          </span>
          {r.vencida ? (
            <span className="chip-dato chip-dato--mal">
              {t("miRevision.fueraDePlazo")}
            </span>
          ) : null}
        </div>
        {r.decision === "pendiente" ? (
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-secondary"
              onClick={() => void decidir("confirmado")}
            >
              {t("miRevision.confirmar")}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setRetirando(!retirando)}
            >
              {t("miRevision.retirar")}
            </button>
          </div>
        ) : (
          <span
            className={cn(
              "chip-dato",
              r.decision === "retirado" ? "chip-dato--mal" : "chip-dato--si",
            )}
          >
            {t(`miRevision.decisiones.${r.decision}`)}
          </span>
        )}
      </div>
      {retirando && r.decision === "pendiente" ? (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <label className="flex flex-1 flex-col gap-1 text-rotulo text-ink-muted">
            {t("miRevision.motivo")}
            <input
              className="input-base"
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="btn-primary"
            disabled={!motivo.trim()}
            onClick={() => void decidir("retirado")}
          >
            {t("miRevision.retirarYa")}
          </button>
        </div>
      ) : null}
    </li>
  );
}
