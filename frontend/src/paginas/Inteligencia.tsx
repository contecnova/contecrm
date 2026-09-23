/**
 * Lo que propone la IA, siempre con el porqué (CRM-07.04.03.23).
 *
 * Esta pantalla enseña puntuaciones, resúmenes y sugerencias con una regla que no
 * se salta nunca: **el número va con sus factores**. Una puntuación sin
 * explicación se mira una vez, no coincide con lo que el comercial sabe de su
 * cliente, y a partir de ahí no se mira más — y hace bien, porque él estuvo en la
 * reunión y el modelo no.
 *
 * Y dos cosas que se pintan a propósito y que casi ningún producto enseña:
 *
 * **Los factores que restan.** Un panel que solo cuenta lo que suma hace pensar
 * que la puntuación es baja por falta de datos, cuando puede ser por algo
 * concreto que se puede arreglar.
 *
 * **Y «no se puede medir» en vez de un cero.** Sin datos suficientes no se pinta
 * un número: se dice que no se sabe, que es distinto de que vaya mal.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo, Vacio } from "@/componentes/Estados";
import { llamar } from "@/lib/api";

interface Factor {
  factor: string;
  empuja: number;
}

interface Factores {
  suman: Factor[];
  restan: Factor[];
  medible: boolean;
  porque: string;
}

export function Inteligencia() {
  const { t } = useTranslation();
  const [contribuciones, setContribuciones] = useState(
    '{"presupuestos_abiertos":0.42,"dias_sin_contestar":-0.31,"visitas_web":0.12}',
  );
  const [datos, setDatos] = useState<Factores | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const explicar = async () => {
    setFallo(null);
    try {
      const r = await llamar<Factores>("/api/v1/modelos/factores", {
        metodo: "POST",
        cuerpo: { contribuciones: JSON.parse(contribuciones) },
      });
      setDatos(r.datos);
    } catch (e) {
      setFallo(e);
    }
  };

  return (
    <>
      <h1 className="text-sm font-medium text-ink">{t("ia.titulo")}</h1>
      <p className="mt-1 text-2xs text-ink-faint">{t("ia.intro")}</p>

      <label className="mt-4 block text-2xs text-ink-muted" htmlFor="ia-contrib">
        {t("ia.contribuciones")}
      </label>
      <textarea
        id="ia-contrib"
        rows={3}
        className="mt-1 w-full rounded-lg border border-ink-dim/60 bg-paper px-3 py-2 font-mono text-2xs text-ink"
        value={contribuciones}
        onChange={(e) => setContribuciones(e.target.value)}
      />
      <button
        type="button"
        onClick={explicar}
        className="mt-2 rounded-lg bg-accent px-3 py-1.5 text-2xs text-paper"
      >
        {t("ia.explicar")}
      </button>

      {fallo ? <Fallo error={fallo} /> : null}

      {datos && !datos.medible ? (
        /* Sin contribuciones no se pinta un número: una puntuación que no se
           puede explicar no se usa. */
        <Vacio titulo={t("ia.noMedible")} detalle={datos.porque} />
      ) : null}

      {datos && datos.medible ? (
        <div className="mt-6 grid gap-4 sm:grid-cols-2" role="status">
          <section className="rounded-xl border border-ink-dim/60 bg-paper p-4">
            <h2 className="text-xs font-medium text-success">{t("ia.suman")}</h2>
            <ul className="mt-2 space-y-1">
              {datos.suman.map((f) => (
                <li key={f.factor} className="flex justify-between text-2xs">
                  <span className="text-ink">{f.factor}</span>
                  <span className="text-success">+{f.empuja}</span>
                </li>
              ))}
            </ul>
          </section>
          {/* Los que restan se enseñan igual de grandes: sin ellos, la
              puntuación baja parece falta de datos. */}
          <section className="rounded-xl border border-ink-dim/60 bg-paper p-4">
            <h2 className="text-xs font-medium text-warning">{t("ia.restan")}</h2>
            {datos.restan.length === 0 ? (
              <p className="mt-2 text-2xs text-ink-faint">{t("ia.nadaResta")}</p>
            ) : (
              <ul className="mt-2 space-y-1">
                {datos.restan.map((f) => (
                  <li key={f.factor} className="flex justify-between text-2xs">
                    <span className="text-ink">{f.factor}</span>
                    <span className="text-warning">{f.empuja}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      ) : null}

      {datos?.porque ? <p className="mt-4 text-3xs text-ink-faint">{datos.porque}</p> : null}
    </>
  );
}
