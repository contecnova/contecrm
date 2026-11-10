/**
 * La puntuación de marketing, en la ficha del lead (CRM-02.01.02.01 a .05).
 *
 * **Medido el 10-11-2026:** el modelo de puntuación existía, la pantalla de
 * «por qué este lead tiene esta puntuación» también, y **no la enlazaba nada**:
 * desde la ficha del lead no había forma de puntuarlo ni de ver su nota. Aquí
 * van las dos cosas, con la calificación —MQL, SQL— delante, que es lo que
 * decide si lo llama ventas.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Error as Fallo } from "@/componentes/Estados";
import { ErrorApi, llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";

interface Nota {
  modelo: string;
  interes: number;
  encaje: number;
  grado: string | null;
  calificacion: string;
  perdido_por_inactividad: number;
  calculado_at: string;
}

export function PuntuacionDelLead({
  leadId,
  alCambiar,
}: {
  leadId: string;
  /** Al puntuar puede cambiar el lead en ventas: el estado y la puntuación. */
  alCambiar?: () => void;
}) {
  const { t } = useTranslation();
  const [nota, setNota] = useState<Nota | null>(null);
  const [sinNota, setSinNota] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const [puntuando, setPuntuando] = useState(false);

  const cargar = useCallback(
    (signal?: AbortSignal) =>
      llamar<Nota>(`/api/v1/puntuacion/leads/${leadId}`, { signal })
        .then((r) => {
          setNota(r.datos);
          setSinNota(false);
        })
        .catch((e: unknown) => {
          if (signal?.aborted) return;
          // Sin puntuar todavía es una respuesta, no un error de la pantalla.
          if (e instanceof ErrorApi && e.estado === 404) setSinNota(true);
          else setFallo(e);
        }),
    [leadId],
  );

  useEffect(() => {
    const control = new AbortController();
    void cargar(control.signal);
    return () => control.abort();
  }, [cargar]);

  async function puntuar() {
    setPuntuando(true);
    setFallo(null);
    try {
      await llamar(`/api/v1/puntuacion/leads/${leadId}`, { metodo: "POST" });
      await cargar();
      alCambiar?.();
    } catch (e) {
      setFallo(e);
    } finally {
      setPuntuando(false);
    }
  }

  return (
    <section
      className="card mb-4 p-4"
      aria-label={t("mk.puntuacionFicha.titulo")}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="section-label flex-1">
          {t("mk.puntuacionFicha.titulo")}
        </h2>
        <button
          type="button"
          className="btn-secondary"
          disabled={puntuando}
          onClick={() => void puntuar()}
        >
          {puntuando
            ? t("mk.puntuacionFicha.puntuando")
            : t("mk.puntuacionFicha.puntuar")}
        </button>
        {nota ? (
          <Link
            className="btn-ghost"
            to={`/m/segmentos/lead/${leadId}/puntuacion`}
          >
            {t("mk.puntuacionFicha.porQue")}
          </Link>
        ) : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      <div role="status" aria-live="polite" className="mt-2">
        {sinNota && !nota ? (
          <p className="text-dato text-ink-faint">
            {t("mk.puntuacionFicha.sinNota")}
          </p>
        ) : null}
        {nota ? (
          <>
            <p className="flex flex-wrap items-baseline gap-3 text-dato text-ink">
              <span className="badge badge-muted uppercase">
                {t(`mk.puntuacionFicha.calificacion.${nota.calificacion}`, {
                  defaultValue: nota.calificacion,
                })}
              </span>
              <span>
                {t("mk.puntuacionFicha.interes")}{" "}
                <span className="font-mono">{nota.interes}</span>
              </span>
              <span>
                {t("mk.puntuacionFicha.encaje")}{" "}
                <span className="font-mono">{nota.encaje}</span>
              </span>
              {nota.grado ? (
                <span>
                  {t("mk.puntuacionFicha.grado")}{" "}
                  <span className="font-mono">{nota.grado}</span>
                </span>
              ) : null}
            </p>
            <p className="mt-1 text-rotulo text-ink-faint">
              {t("mk.puntuacionFicha.pie", {
                modelo: nota.modelo,
                fecha: fechaHora(nota.calculado_at),
                perdidos: nota.perdido_por_inactividad,
              })}
            </p>
          </>
        ) : null}
      </div>
    </section>
  );
}
