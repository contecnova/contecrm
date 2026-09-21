/**
 * Un recorrido guiado por la solución (CRM-07.04.05.04).
 *
 * Construido **desde el catálogo de módulos**, no escrito a mano: un guion de
 * demostración escrito aparte se queda viejo a la tercera pantalla que alguien
 * añade, y el día que se enseña el producto lo que se cuenta ya no es lo que
 * hay. Aquí cada paso sale de un módulo real y lleva a la pantalla real.
 *
 * Y dice **lo que hay hoy**, con el identificador del catálogo delante. Enseñar
 * lo que va a haber es la forma más rápida de que una demostración se convierta
 * en una promesa que alguien apunta.
 */

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { MODULOS, porGrupo } from "@/lib/modulos";

export function Recorrido() {
  const { t } = useTranslation();
  const grupos = [...porGrupo()];

  return (
    <>
      <h1 className="text-sm font-medium text-ink">{t("recorrido.titulo")}</h1>
      <p className="mt-1 max-w-2xl text-2xs text-ink-faint">{t("recorrido.intro")}</p>
      <p className="mt-3 text-3xs text-ink-faint">
        {t("recorrido.cuantos", { modulos: MODULOS.length, grupos: grupos.length })}
      </p>

      <ol className="mt-6 flex flex-col gap-6">
        {grupos.map(([grupo, modulos], i) => (
          <li key={grupo}>
            <h2 className="text-2xs font-medium uppercase tracking-wide text-ink-faint">
              {i + 1}. {grupo}
            </h2>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {modulos.map((m) => (
                <Link
                  key={m.ruta}
                  to={`/m/${m.ruta}`}
                  className="rounded-xl border border-ink-dim/60 bg-paper p-3 hover:bg-paper-light"
                >
                  <p className="text-xs text-ink">{m.titulo}</p>
                  <p className="mt-1 font-mono text-3xs text-ink-faint">{m.capacidad}</p>
                  <p className="mt-1 text-3xs text-ink-faint">
                    {m.recursos.map((r) => r.nombre).join(" · ")}
                  </p>
                </Link>
              ))}
            </div>
          </li>
        ))}
      </ol>

      <p className="mt-8 text-2xs text-ink-faint">{t("recorrido.cierre")}</p>
    </>
  );
}
