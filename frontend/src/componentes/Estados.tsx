/**
 * Los tres estados que toda pantalla tiene, resueltos en un sitio
 * (CRM-07.04.01.07).
 *
 * Cargando, vacío y error. Si cada pantalla los resuelve a su manera, la
 * aplicación se siente hecha por cinco personas distintas — y, peor, el error
 * de una pantalla dice algo útil y el de otra dice «Error».
 */

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Icono } from "@/componentes/Icono";

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

/**
 * Nada que enseñar, dicho con un icono y —cuando la hay— con la acción que lo
 * llena.
 *
 * Un recuadro que solo dice «no hay nada» deja a quien mira en el mismo sitio
 * en el que estaba: sabe que está vacío y no sabe qué hacer. Y una pantalla
 * vacía sin explicación se confunde con una averiada, que es peor: lleva a
 * llamar a soporte por algo que funciona.
 */
export function Vacio({
  titulo,
  detalle,
  icono = "inbox",
  accion,
  compacto = false,
}: {
  titulo?: string;
  detalle?: string;
  icono?: string;
  /** Lo que se puede hacer para que deje de estar vacío. */
  accion?: { texto: string; a?: string; alPulsar?: () => void };
  compacto?: boolean;
}) {
  const { t } = useTranslation();
  const boton = accion ? (
    accion.a ? (
      <Link to={accion.a} className="btn-primary mt-4 inline-flex items-center gap-1.5">
        <Icono nombre="add" tamano="sm" />
        {accion.texto}
      </Link>
    ) : (
      <button
        type="button"
        onClick={accion.alPulsar}
        className="btn-primary mt-4 inline-flex items-center gap-1.5"
      >
        <Icono nombre="add" tamano="sm" />
        {accion.texto}
      </button>
    )
  ) : null;

  if (compacto) {
    return (
      <p className="flex items-center gap-2 py-4 text-2xs text-ink-faint">
        <Icono nombre={icono} tamano="sm" />
        {titulo ?? t("vacio.titulo")}
      </p>
    );
  }

  return (
    <div className="card flex flex-col items-center px-6 py-12 text-center">
      <Icono nombre={icono} tamano="xl" className="text-ink-dim" />
      <p className="mt-3 text-sm font-medium text-ink">{titulo ?? t("vacio.titulo")}</p>
      <p className="mt-1 max-w-md text-2xs text-ink-faint">{detalle ?? t("vacio.detalle")}</p>
      {boton}
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
  // La frase del servidor antes que el título. El título es del TIPO de error
  // —«Conflicto con el estado actual»— y la frase es de ESTE error: «El motor
  // analítico no pudo resolver el informe: …». La primera no dice nada que se
  // pueda hacer; la segunda dice dónde mirar.
  else if (api.explicacion) mensaje = api.explicacion;
  else if (api.titulo) mensaje = api.titulo;

  return (
    <div className="rounded-xl border border-danger/40 bg-danger/5 p-6" role="alert">
      <p className="flex items-center gap-2 text-danger">
        <Icono nombre="error" tamano="sm" />
        {mensaje}
      </p>
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
          className="btn-secondary mt-4"
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
