/**
 * La pantalla de explotación (CRM-05.01.04.03).
 *
 * Aquí se pregunta y se ven las respuestas **sin salir del CRM**. La consulta la
 * resuelve contecintelligence (RT-4): esta pantalla no calcula nada, no agrega
 * nada y no interpreta los datos. Pide, enseña y guarda la pregunta.
 *
 * Dos decisiones que se ven al usarla:
 *
 * **Cuando la explotación no está disponible, se dice qué SÍ funciona.** Un
 * «servicio no disponible» a secas deja a quien lo lee creyendo que su CRM se ha
 * caído. No se ha caído: lo que no funciona es preguntar. El diagnóstico llega
 * del servidor —no se deduce aquí— porque la lista de motivos depende de
 * configuración que el navegador no ve.
 *
 * **Las preguntas guardadas se separan en «mías» y «publicadas».** Sin esa
 * distinción, una pregunta a medio afinar aparece en la lista de todos y se usa
 * como si estuviera bien.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { ErrorApi, llamar } from "@/lib/api";

interface Diagnostico {
  puede_preguntar: boolean;
  problemas: string[];
  sigue_funcionando: string[];
  no_funciona: string[];
}

interface Pregunta {
  id: string;
  clave: string;
  titulo: string;
  pregunta: string;
  publicada: boolean;
  propia: boolean;
  informe_id: string | null;
  veces_usada: number;
}

export function Explotacion() {
  const { t } = useTranslation();
  const [diagnostico, setDiagnostico] = useState<Diagnostico | null>(null);
  const [preguntas, setPreguntas] = useState<Pregunta[] | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    Promise.all([
      llamar<Diagnostico>("/api/v1/explotacion/diagnostico", { signal: control.signal }),
      llamar<Pregunta[]>("/api/v1/explotacion/preguntas", { signal: control.signal }),
    ])
      .then(([d, p]) => {
        setDiagnostico(d.datos);
        setPreguntas(p.datos);
      })
      .catch((e: unknown) => {
        if (e instanceof ErrorApi) setFallo(e);
      });
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!diagnostico || !preguntas) return <Cargando />;

  const mias = preguntas.filter((p) => p.propia && !p.publicada);
  const publicadas = preguntas.filter((p) => p.publicada);

  return (
    <div className="flex flex-col gap-6 p-4">
      <header>
        <h1 className="text-lg font-medium text-ink">{t("explotacion.titulo")}</h1>
        <p className="mt-1 max-w-prose text-2xs text-ink-muted">
          {t("explotacion.entradilla")}
        </p>
      </header>

      {!diagnostico.puede_preguntar ? (
        <section
          className="rounded-lg border border-warning/40 bg-warning/5 p-4"
          role="status"
          aria-live="polite"
        >
          <h2 className="text-sm font-medium text-warning">
            {t("explotacion.noDisponible")}
          </h2>
          <ul className="mt-2 list-disc pl-5 text-2xs text-ink-muted">
            {diagnostico.problemas.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
          {/* Lo que sigue funcionando va en la MISMA tarjeta y no en otra: quien
              lee un aviso en rojo cierra la pantalla, y si la tranquilidad está
              más abajo no la lee nadie. */}
          <h3 className="mt-3 text-2xs font-medium text-ink">
            {t("explotacion.sigueFuncionando")}
          </h3>
          <ul className="mt-1 list-disc pl-5 text-2xs text-ink-muted">
            {diagnostico.sigue_funcionando.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section>
        <h2 className="text-sm font-medium text-ink">{t("explotacion.publicadas")}</h2>
        {publicadas.length === 0 ? (
          <Vacio titulo={t("explotacion.sinPublicadas")} detalle={t("explotacion.sinPublicadasDetalle")} />
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {publicadas.map((p) => (
              <Tarjeta key={p.id} pregunta={p} />
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="text-sm font-medium text-ink">{t("explotacion.mias")}</h2>
        {mias.length === 0 ? (
          <Vacio titulo={t("explotacion.sinMias")} detalle={t("explotacion.sinMiasDetalle")} />
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {mias.map((p) => (
              <Tarjeta key={p.id} pregunta={p} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Tarjeta({ pregunta }: { pregunta: Pregunta }) {
  const { t } = useTranslation();
  return (
    <li className="rounded-lg border border-ink-dim/40 bg-paper-light p-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-sm text-ink">{pregunta.titulo}</span>
        {pregunta.informe_id ? (
          <span className="rounded bg-success/10 px-1.5 py-0.5 text-3xs uppercase text-success">
            {t("explotacion.esInforme")}
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-2xs text-ink-muted">{pregunta.pregunta}</p>
      <p className="mt-1 text-3xs text-ink-faint">
        {t("explotacion.vecesUsada", { veces: pregunta.veces_usada })}
      </p>
    </li>
  );
}
