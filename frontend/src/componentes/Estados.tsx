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
      <span
        className="h-4 w-4 animate-pulse-slow rounded-full bg-accent"
        aria-hidden="true"
      />
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
      <Link
        to={accion.a}
        className="btn-primary mt-4 inline-flex items-center gap-1.5"
      >
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
      // Marcado para poder CONTARLO: el barrido comprueba que ninguna
      // pantalla pinte dos vacíos de caja grande, y sin esta marca habría que
      // adivinarlo por la altura y el texto, que es como se cuentan de más.
      <div data-vacio="seccion" className="py-4">
        <p className="flex items-center gap-2 text-dato text-ink-faint">
          <Icono nombre={icono} tamano="sm" />
          {titulo ?? t("vacio.titulo")}
        </p>
        {/* **El porqué también en compacto.** Lo tiraba: cuatro pantallas le
            pasaban una explicación —por qué no hay rastro, por qué no hay
            conexiones, si el registro no se ha tocado o si este servicio no
            lleva ese histórico— y ninguna llegaba a quien la miraba. Medido el
            29-10-2026. Un vacío sin porqué se lee como «no hay nada», que es
            justo lo que estas pantallas estaban intentando no decir. */}
        {detalle ? (
          <p className="mt-1 text-rotulo text-ink-faint">{detalle}</p>
        ) : null}
      </div>
    );
  }

  return (
    <div
      data-vacio="pantalla"
      className="card flex flex-col items-center px-6 py-12 text-center"
    >
      <Icono nombre={icono} tamano="xl" className="text-ink-dim" />
      <p className="mt-3 text-titulo font-medium text-ink">
        {titulo ?? t("vacio.titulo")}
      </p>
      <p className="mt-1 max-w-md text-dato text-ink-faint">
        {detalle ?? t("vacio.detalle")}
      </p>
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
export function Error({
  error,
  reintentar,
}: {
  error: unknown;
  reintentar?: () => void;
}) {
  const { t } = useTranslation();
  const api = error instanceof ErrorApi ? error : null;

  let mensaje = t("errores.generico");
  // **«No hay red» sólo cuando de verdad no hay red.** Antes era el mensaje de
  // todo lo que no fuera un `ErrorApi`, y eso incluye los fallos al pintar: la
  // ficha de una oportunidad llevaba rota quién sabe cuánto enseñando «No se
  // ha podido contactar con el servidor», y lo que pasaba es que el front
  // pintaba un objeto donde esperaba un texto. El servidor contestaba 200.
  //
  // Ahora `llamar` marca los fallos de red con estado 0, así que aquí se
  // pueden distinguir, y lo que no es ninguno de los dos se dice como lo que
  // es —algo ha fallado en esta pantalla— con su mensaje debajo.
  if (api?.estado === 0) mensaje = t("errores.sinRed");
  else if (!api) mensaje = t("errores.pantalla");
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
    <div
      className="rounded-xl border border-danger/40 bg-danger/5 p-6"
      role="alert"
    >
      <p className="flex items-center gap-2 text-danger">
        <Icono nombre="error" tamano="sm" />
        {mensaje}
      </p>
      {/* Y el mensaje de verdad, siempre a mano. Un fallo al pintar sin su
          texto obliga a abrir la consola del navegador para saber qué pasó, y
          eso no lo hace quien está usando el producto: lo cuenta como «no
          funciona» y nadie puede arreglarlo. */}
      {!api && error instanceof globalThis.Error ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-dato text-ink-faint">
            {t("errores.detalleTecnico")}
          </summary>
          <pre className="mt-2 overflow-x-auto rounded bg-paper-light p-3 font-mono text-dato text-ink-muted">
            {error.message}
          </pre>
        </details>
      ) : null}
      {api?.detalle ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-dato text-ink-faint">
            {t("errores.detalleTecnico")}
          </summary>
          <pre className="mt-2 overflow-x-auto rounded-lg bg-paper-light p-3 font-mono text-dato text-ink-muted">
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
export function Retenidos({
  campos,
  enmascarados = [],
}: {
  campos: string[];
  /**
   * Los que vienen TAPADOS. Van aparte de los retenidos a propósito: un campo
   * retenido no viene y se ve el hueco; uno enmascarado viene y tiene la forma
   * del dato, así que sin decirlo nadie nota que lo que lee no es el valor.
   * Alguien copia «··············tora» creyendo que es el nombre.
   */
  enmascarados?: string[];
}) {
  const { t } = useTranslation();
  if (campos.length === 0 && enmascarados.length === 0) return null;
  return (
    <>
      {campos.length > 0 ? (
        <p className="mt-2 text-dato text-warning" role="note">
          {t("retenidos", { count: campos.length, campos: campos.join(", ") })}
        </p>
      ) : null}
      {enmascarados.length > 0 ? (
        <p className="mt-2 text-dato text-warning" role="note">
          {t("enmascarados", {
            count: enmascarados.length,
            campos: enmascarados.join(", "),
          })}
        </p>
      ) : null}
    </>
  );
}
