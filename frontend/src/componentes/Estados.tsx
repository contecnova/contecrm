/**
 * Los tres estados que toda pantalla tiene, resueltos en un sitio
 * (CRM-07.04.01.07).
 *
 * Cargando, vacío y error. Si cada pantalla los resuelve a su manera, la
 * aplicación se siente hecha por cinco personas distintas — y, peor, el error
 * de una pantalla dice algo útil y el de otra dice «Error».
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Icono } from "@/componentes/Icono";

import { ErrorApi } from "@/lib/api";
import type { Directorio } from "@/lib/personas";

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
 * Los problemas que el servidor manda en `detalle.problemas`, como frases.
 *
 * Cada uno puede ser un texto o un objeto con `motivo` y, si los hay, los
 * elementos a los que se refiere (`producto`, `otro`, `campo`): se ponen
 * delante para que se sepa de qué habla cada motivo.
 */
export function problemasDe(detalle: unknown): string[] {
  const lista = (detalle as { problemas?: unknown } | null)?.problemas;
  if (!Array.isArray(lista)) return [];
  return lista
    .map((p) => {
      if (typeof p === "string") return p;
      if (!p || typeof p !== "object") return "";
      const o = p as Record<string, unknown>;
      const motivo = typeof o.motivo === "string" ? o.motivo : "";
      const quien = ["producto", "otro", "campo"]
        .map((k) => o[k])
        .filter((v): v is string => typeof v === "string" && v !== "");
      return quien.length ? `${quien.join(" · ")}: ${motivo}` : motivo;
    })
    .filter(Boolean);
}

/**
 * La frase que explica un error, la misma en la pantalla entera
 * (`<Error>`) y en el aviso compacto de un panel (`<FalloCompacto>`).
 *
 * Sacada de `<Error>` para que las dos digan lo mismo del mismo fallo: si el
 * panel dijera «Error» y la pantalla «No se ha podido contactar con el
 * servidor», parecerían dos problemas.
 */
export function mensajeDeError(
  error: unknown,
  t: (clave: string) => string,
): string {
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
  // Guardado en el dispositivo sin red (CRM-06.02.01.04): no es un fallo, es
  // un cambio pendiente de subir, y se dice así.
  if (api?.codigo === "encolada_sin_conexion")
    mensaje = t("errores.encoladaSinConexion");
  else if (api?.estado === 0) mensaje = t("errores.sinRed");
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
  return mensaje;
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
  const mensaje = mensajeDeError(error, t);

  // Guardado sin red: es un aviso, no un fallo, y no se pinta en rojo.
  if (api?.codigo === "encolada_sin_conexion")
    return (
      <div
        className="rounded-xl border border-warning/40 bg-warning/5 p-4"
        role="status"
      >
        <p className="flex items-center gap-2 text-warning">
          <Icono nombre="cloud_off" tamano="sm" />
          {mensaje}
        </p>
      </div>
    );

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
      {/* Los motivos concretos, a la vista. «Esa combinación de productos no
          se puede vender junta» sin decir cuáles obliga a abrir el detalle
          técnico y leer JSON; la lista `problemas` del servidor ya dice qué
          choca con qué y por qué (CRM-03.03.02.02, medido el 09-11-2026). */}
      {problemasDe(api?.detalle).length > 0 ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-dato text-ink">
          {problemasDe(api?.detalle).map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      ) : null}
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
      {api?.requestId ? <IdDePeticion id={api.requestId} /> : null}
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
 * El fallo de UN panel, dicho donde estaría el panel y sin tumbar la pantalla.
 *
 * Es la pareja de `useCargasSecundarias`: lo que se pide aparte de lo
 * principal no puede llevarse la pantalla por delante, pero tampoco puede
 * desaparecer sin más, porque un panel que no está se lee como «no hay
 * nada». Una línea, no un recuadro: con la red caída puede haber ocho a la
 * vez, y ocho recuadros rojos esconderían lo que sí ha cargado.
 *
 * No pinta nada sin error, así que se puede dejar puesto siempre.
 */
export function FalloCompacto({
  error,
  que,
  reintentar,
}: {
  error: unknown;
  /** Qué no se ha podido consultar: el título del panel que falta. */
  que?: string;
  reintentar?: () => void;
}) {
  const { t } = useTranslation();
  if (!error) return null;
  const mensaje = mensajeDeError(error, t);
  const requestId = error instanceof ErrorApi ? error.requestId : null;
  return (
    <div
      data-fallo="seccion"
      role="alert"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-dato"
    >
      <p className="flex items-center gap-2 text-danger">
        <Icono nombre="error" tamano="sm" />
        {que ? t("cargaSecundaria.falloDe", { que, mensaje }) : mensaje}
      </p>
      {/* El identificador va en el título y no a la vista: en una línea no
          cabe, y quien llama a soporte lo encuentra pasando el ratón. */}
      {reintentar ? (
        <button
          type="button"
          onClick={reintentar}
          className="btn-ghost"
          title={requestId ? `${t("errores.peticion")}: ${requestId}` : undefined}
        >
          <Icono nombre="refresh" tamano="sm" />
          {t("app.reintentar")}
        </button>
      ) : null}
    </div>
  );
}

/**
 * Que una lista viene cortada, dicho debajo de ella (y cómo seguir).
 *
 * Una lista recortada que parece completa es peor que una lista larga: con
 * las doscientas primeras oportunidades en el tablero, la doscientas una no
 * existe para quien lo mira. El servidor ya lo dice —devuelve cursor cuando
 * hay más—, así que esto sólo sale cuando lo ha dicho: no se cuenta ni se
 * adivina por el tamaño.
 *
 * Con `alCargarMas`, ofrece seguir con el cursor; sin él, al menos lo avisa.
 */
export function AvisoDeRecorte({
  cuantas,
  alCargarMas,
  cargando = false,
  detalle,
  quiza = false,
}: {
  /** Las que se están enseñando. */
  cuantas: number;
  /**
   * La ruta no da cursor y lo único que se sabe es que la respuesta llenó lo
   * pedido: PUEDE haber más. Se dice así, porque afirmar «hay más» de una
   * lista que justo tenía ese número sería otra forma de mentir.
   */
  quiza?: boolean;
  alCargarMas?: () => void;
  cargando?: boolean;
  /** Dónde buscar lo que no sale, cuando no se puede cargar más aquí. */
  detalle?: string;
}) {
  const { t } = useTranslation();
  return (
    <div
      data-recorte="lista"
      role="note"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-rotulo text-ink-faint"
    >
      <span className="flex items-center gap-1.5">
        <Icono nombre="more_horiz" tamano="sm" />
        {t(quiza ? "listas.quizaRecortada" : "listas.recortada", {
          count: cuantas,
        })}
      </span>
      {detalle ? <span>{detalle}</span> : null}
      {alCargarMas ? (
        <button
          type="button"
          onClick={alCargarMas}
          disabled={cargando}
          className="btn-ghost"
        >
          {cargando ? t("app.cargando") : t("listas.cargarMas")}
        </button>
      ) : null}
    </div>
  );
}

/**
 * Lo que hay que saber de la lista de personas de un desplegable: si no ha
 * llegado entera, por fallo o por tope (`useDirectorio`).
 *
 * Junto en un sitio porque lo ponen seis selectores, y los seis tienen que
 * decirlo igual: «esa persona no está» tiene que poder leerse como «no se ha
 * podido traer» cuando es eso lo que pasa.
 */
export function AvisoDelDirectorio({ directorio }: { directorio: Directorio }) {
  const { t } = useTranslation();
  return (
    <>
      <FalloCompacto
        error={directorio.fallo}
        que={t("listas.personas")}
        reintentar={directorio.reintentar}
      />
      {directorio.recortado ? (
        <AvisoDeRecorte cuantas={directorio.personas?.length ?? 0} />
      ) : null}
    </>
  );
}

/**
 * El identificador de la petición que falló, para copiarlo
 * (CRM-00.02.04.07).
 *
 * A la vista y no dentro del «detalle técnico»: es lo único del error que
 * quien llama a soporte necesita dar, y escondido no lo da nadie. Con él, el
 * audit trail de Plataforma y cumplimiento enseña lo que esa petición
 * escribió.
 */
export function IdDePeticion({ id }: { id: string }) {
  const { t } = useTranslation();
  const [copiado, setCopiado] = useState(false);
  return (
    <p className="mt-3 flex flex-wrap items-center gap-2 text-rotulo text-ink-faint">
      <span>{t("errores.peticion")}:</span>
      <code className="font-mono text-ink-muted">{id}</code>
      <button
        type="button"
        className="btn-ghost"
        onClick={() => {
          // Sin portapapeles (contexto inseguro, permiso denegado) el
          // identificador sigue a la vista y se puede seleccionar a mano.
          void navigator.clipboard
            ?.writeText(id)
            .then(() => setCopiado(true))
            .catch(() => undefined);
        }}
      >
        <Icono nombre={copiado ? "check" : "content_copy"} tamano="sm" />
        {copiado ? t("errores.copiado") : t("errores.copiar")}
      </button>
      <span className="w-full">{t("errores.peticionAyuda")}</span>
    </p>
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
