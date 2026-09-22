/**
 * Segmentación y campañas (CRM-07.04.03.09, CRM-07.04.03.10).
 *
 * Dos decisiones:
 *
 * **El recuento de un segmento se pide al servidor y se dice de cuándo es.** Un
 * número sin fecha se lee como el de ahora, y un segmento que se recalcula solo
 * al abrirlo puede llevar semanas sin mirarse. Quien va a mandar un correo a
 * 14.000 personas merece saber si ese 14.000 es de hoy.
 *
 * **Una campaña enseña su estado antes que sus cifras.** Las cifras de una
 * campaña en borrador son cero y se leen como un fracaso; las de una pausada son
 * las de cuando se paró y se leen como las de hoy.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { ErrorApi, llamar } from "@/lib/api";

interface Segmento {
  id: string;
  nombre: string;
  tipo: string;
  miembros: number | null;
  calculado_at: string | null;
}

interface Campana {
  id: string;
  nombre: string;
  estado: string;
  canal: string;
  miembros: number;
  enviados: number;
  respuestas: number;
}

export function Marketing() {
  const { t } = useTranslation();
  const [segmentos, setSegmentos] = useState<Segmento[] | null>(null);
  const [campanas, setCampanas] = useState<Campana[] | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    Promise.all([
      llamar<Segmento[]>("/api/v1/segmentos", { signal: control.signal }),
      llamar<Campana[]>("/api/v1/campanas", { signal: control.signal }),
    ])
      .then(([s, c]) => {
        setSegmentos(s.datos);
        setCampanas(c.datos);
      })
      .catch((e: unknown) => {
        if (e instanceof ErrorApi) setFallo(e);
      });
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!segmentos || !campanas) return <Cargando />;

  return (
    <div className="flex flex-col gap-6 p-4">
      <header>
        <h1 className="text-lg font-medium text-ink">{t("marketing.titulo")}</h1>
        <p className="mt-1 max-w-prose text-2xs text-ink-muted">{t("marketing.entradilla")}</p>
      </header>

      <section>
        <h2 className="text-sm font-medium text-ink">{t("marketing.segmentos")}</h2>
        {segmentos.length === 0 ? (
          <Vacio titulo={t("marketing.sinSegmentos")} detalle="" />
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {segmentos.map((s) => (
              <li
                key={s.id}
                className="flex flex-wrap items-baseline gap-2 rounded-lg border border-ink-dim/40 bg-paper-light p-3"
              >
                <span className="flex-1 text-sm text-ink">{s.nombre}</span>
                <span className="text-2xs text-ink-muted">{s.tipo}</span>
                <span className="font-mono text-2xs text-ink">
                  {s.miembros === null ? t("marketing.sinCalcular") : s.miembros}
                </span>
                {/* La fecha del recuento va SIEMPRE: un número sin fecha se lee
                    como el de ahora, y quien va a mandar un correo a 14.000
                    personas merece saber si ese 14.000 es de hoy. */}
                <span className="text-3xs text-ink-faint">
                  {s.calculado_at
                    ? t("marketing.calculado", {
                        fecha: new Date(s.calculado_at).toLocaleDateString(),
                      })
                    : t("marketing.nuncaCalculado")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="text-sm font-medium text-ink">{t("marketing.campanas")}</h2>
        {campanas.length === 0 ? (
          <Vacio titulo={t("marketing.sinCampanas")} detalle="" />
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {campanas.map((c) => (
              <li
                key={c.id}
                className="rounded-lg border border-ink-dim/40 bg-paper-light p-3"
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  {/* El estado va primero: las cifras de una campaña en borrador
                      son cero y se leen como un fracaso. */}
                  <span className="rounded bg-paper px-1.5 py-0.5 text-3xs uppercase text-ink-muted">
                    {c.estado}
                  </span>
                  <span className="flex-1 text-sm text-ink">{c.nombre}</span>
                  <span className="text-2xs text-ink-muted">{c.canal}</span>
                </div>
                {c.estado !== "borrador" ? (
                  <p className="mt-1 font-mono text-2xs text-ink-faint">
                    {t("marketing.cifras", {
                      miembros: c.miembros,
                      enviados: c.enviados,
                      respuestas: c.respuestas,
                    })}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
