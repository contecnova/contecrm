/**
 * Portada. Por ahora dice qué hay y adónde ir.
 *
 * Los módulos funcionales —cuentas, oportunidades, casos— están catalogados en
 * `CRM-07.04.03.*` y se construyen encima de esto. Se dice aquí en vez de
 * enseñar una portada con tarjetas que no llevan a ningún sitio.
 */

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { config } from "@/lib/config";
import type { Sesion } from "@/lib/sesion";

export function Inicio({ sesion }: { sesion: Sesion | null }) {
  const { t } = useTranslation();
  return (
    <>
      <h1 className="text-lg font-medium text-ink">{config().nombre}</h1>
      {sesion ? (
        <p className="mt-1 text-2xs text-ink-faint">
          {sesion.roles.length > 0 ? sesion.roles.join(", ") : "sin roles asignados"}
        </p>
      ) : null}
      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        <Tarjeta a="/administracion" titulo={t("nav.consola")} detalle={t("consola.intro")} />
        <Tarjeta a="/estado" titulo={t("nav.estado")} detalle={t("estado.titulo")} />
      </div>
    </>
  );
}

function Tarjeta({ a, titulo, detalle }: { a: string; titulo: string; detalle: string }) {
  return (
    <Link
      to={a}
      className="rounded-xl border border-ink-dim/60 bg-paper p-4 hover:bg-paper-light"
    >
      <p className="text-xs text-ink">{titulo}</p>
      <p className="mt-1 text-2xs text-ink-faint">{detalle}</p>
    </Link>
  );
}
