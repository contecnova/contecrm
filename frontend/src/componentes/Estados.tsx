/**
 * Los tres estados que toda pantalla tiene, resueltos en un sitio
 * (CRM-07.04.01.07).
 *
 * Cargando, vacío y error. Si cada pantalla los resuelve a su manera, la
 * aplicación se siente hecha por cinco personas distintas — y, peor, el error
 * de una pantalla dice algo útil y el de otra dice «Error».
 */

import { useTranslation } from "react-i18next";

import { ErrorApi } from "@/lib/api";

export function Cargando({ texto }: { texto?: string }) {
  const { t } = useTranslation();
  return (
    <div
      className="flex items-center gap-3 p-8 text-ink-muted"
      role="status"
      aria-live="polite"
    >
      <span className="h-4 w-4 animate-pulse-slow rounded-full bg-accent" aria-hidden="true" />
      {texto ?? t("app.cargando")}
    </div>
  );
}

export function Vacio({ titulo, detalle }: { titulo?: string; detalle?: string }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-xl border border-ink-dim/60 bg-paper p-10 text-center">
      <p className="text-ink">{titulo ?? t("vacio.titulo")}</p>
      <p className="mt-1 text-2xs text-ink-faint">{detalle ?? t("vacio.detalle")}</p>
    </div>
  );
}

/**
 * Un error, traducido a algo que se pueda leer y con qué hacer.
 *
 * El detalle técnico se enseña aparte y plegado: quien puede usarlo lo
 * necesita entero, y a quien no, esconderlo del todo le deja sin nada que
 * pegar en un ticket.
 */
export function Error({ error, reintentar }: { error: unknown; reintentar?: () => void }) {
  const { t } = useTranslation();
  const api = error instanceof ErrorApi ? error : null;

  let mensaje = t("errores.generico");
  if (!api) mensaje = t("errores.sinRed");
  else if (api.esPoliticaDeAcceso) mensaje = t("errores.politica");
  else if (api.estado === 403) mensaje = t("errores.sinPermiso");
  else if (api.estado === 404) mensaje = t("errores.noEncontrado");
  else if (api.esConflictoDeVersion) mensaje = t("errores.conflicto");
  else if (api.titulo) mensaje = api.titulo;

  return (
    <div className="rounded-xl border border-danger/40 bg-danger/5 p-6" role="alert">
      <p className="text-danger">{mensaje}</p>
      {api?.detalle ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-2xs text-ink-faint">Detalle técnico</summary>
          <pre className="mt-2 overflow-x-auto rounded-lg bg-paper-light p-3 font-mono text-2xs text-ink-muted">
            {JSON.stringify(api.detalle, null, 2)}
          </pre>
        </details>
      ) : null}
      {reintentar ? (
        <button
          type="button"
          onClick={reintentar}
          className="mt-4 rounded-lg bg-accent px-3 py-1.5 text-2xs text-paper hover:bg-accent-soft"
        >
          {t("app.reintentar")}
        </button>
      ) : null}
    </div>
  );
}

/**
 * Aviso de los campos que el servidor ha retenido por permisos.
 *
 * Sin él, el usuario no distingue «este campo está vacío» de «este campo no te
 * lo doy», y esa diferencia cambia lo que hace: rellenarlo o pedir acceso.
 */
export function Retenidos({ campos }: { campos: string[] }) {
  const { t } = useTranslation();
  if (campos.length === 0) return null;
  return (
    <p className="mt-2 text-2xs text-warning" role="note">
      {t("retenidos", { count: campos.length, campos: campos.join(", ") })}
    </p>
  );
}
