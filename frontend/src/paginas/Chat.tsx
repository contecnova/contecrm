/**
 * Chat interno (CRM-06.02.02.01, CRM-06.02.02.03, CRM-06.02.02.04,
 * CRM-06.02.02.05, CRM-06.02.02.06, CRM-06.02.02.07, CRM-06.02.02.08).
 *
 * Media conversación de un CRM ocurre fuera de él: se habla de una oportunidad
 * en otra herramienta, se decide algo, y lo que queda dentro es una etapa
 * cambiada sin el porqué. Seis meses después nadie sabe por qué se bajó aquel
 * precio.
 *
 * **Lo que lo distingue de poner un enlace a Teams** es que una conversación
 * puede colgar de un registro: la de *esta* oportunidad se abre desde su ficha,
 * con el importe y la etapa al lado. Un chat genérico obliga a copiar el enlace
 * y a que quien lo recibe cambie de aplicación, y ahí es donde se pierde el
 * contexto.
 *
 * Dos decisiones de cómo se pinta:
 *
 * **Lo nuevo llega solo, por SSE.** Un chat que hay que recargar no es un chat:
 * la conversación se sigue mirando la pantalla, no pulsando un botón.
 *
 * **El hilo se abre al lado y no sustituye a la conversación.** Entrar en un
 * hilo y perder de vista lo demás obliga a salir y volver para seguir el resto,
 * que es exactamente lo que un hilo existe para no tener que hacer.
 *
 * **Y cuatro cosas que el servidor servía y aquí no se alcanzaban.** Estaban
 * construidas, probadas de punta a punta y sin puerta:
 *
 * - **buscar**, sólo en las conversaciones a las que se pertenece. Un chat sin
 *   búsqueda obliga a recordar en qué canal se dijo algo, que es justo lo que
 *   no se recuerda a los seis meses;
 * - **quién está**, con «visto por última vez». La pregunta no es social: es
 *   si esperar respuesta o levantar el teléfono;
 * - **qué decía antes** un mensaje editado. Lo corregido se ve corregido, no
 *   reescrito: una conversación donde se puede cambiar lo dicho sin rastro no
 *   sirve para explicar una decisión;
 * - **quién está en esta conversación**. Antes de escribir algo delicado hay
 *   que poder saber quién lo va a leer.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { listar } from "@/lib/listados";
import { cn } from "@/lib/utiles";
import type { Sesion } from "@/lib/sesion";
import { localizacion } from "@/lib/formato";

/** Las reacciones que admite el servicio. Lista corta y cerrada a propósito. */
const REACCIONES = ["👍", "👎", "✅", "❓", "🎉", "👀"];

interface Conversacion {
  id: string;
  tipo: string;
  clave: string | null;
  nombre: string;
  proposito: string;
  objeto_tipo: string | null;
  objeto_id: string | null;
  ultimo_mensaje_at: string | null;
  sin_leer: number;
}

interface Presencia {
  usuario_id: string;
  estado: string;
  mensaje: string;
  /** Desde cuándo no se le ve. Es lo que contesta «¿espero o llamo?». */
  visto_at: string | null;
}

interface Miembro {
  usuario_id: string;
  rol: string;
  silenciada: boolean;
}

interface Version {
  cuerpo: string;
  editado_at?: string;
}

interface Mensaje {
  id: string;
  conversacion_id: string;
  autor_id: string;
  cuerpo: string;
  responde_a_id: string | null;
  menciones: string[];
  editado_at: string | null;
  ediciones: number;
  reacciones: Record<string, string[]>;
  created_at: string;
  /**
   * Está en la papelera (CRM-06.02.02.09).
   *
   * Sigue en el hilo y sin cuerpo: un mensaje que se esfuma deja las respuestas
   * colgando de nada, y quien lee la conversación una semana después no
   * entiende el hilo ni sabe que falta algo.
   */
  borrado?: boolean;
}

interface Usuario {
  id: string;
  nombre: string;
  email: string;
}

function titulo(c: Conversacion): string {
  if (c.clave) return `#${c.clave}`;
  return c.nombre || "Conversación";
}

export function Chat({ sesion }: { sesion: Sesion | null }) {
  const { t } = useTranslation();
  const [parametros, setParametros] = useSearchParams();
  const [conversaciones, setConversaciones] = useState<Conversacion[] | null>(null);
  const [mensajes, setMensajes] = useState<Mensaje[]>([]);
  const [usuarios, setUsuarios] = useState<Record<string, Usuario>>({});
  /** Lo que se busca, y lo encontrado. Sólo en mis conversaciones. */
  const [termino, setTermino] = useState("");
  const [hallazgos, setHallazgos] = useState<Mensaje[] | null>(null);
  /** Quién está, para saber si esperar respuesta o llamar. */
  const [presencia, setPresencia] = useState<Presencia[]>([]);
  /** Las versiones de un mensaje editado, cuando alguien las abre. */
  const [versiones, setVersiones] = useState<{ de: string; lista: Version[] } | null>(null);
  /** Quién está en la conversación abierta. */
  const [miembros, setMiembros] = useState<Miembro[]>([]);
  const [fallo, setFallo] = useState<unknown>(null);
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [hilo, setHilo] = useState<string | null>(null);
  const [abriendo, setAbriendo] = useState(false);
  const abajo = useRef<HTMLDivElement | null>(null);

  const activa = parametros.get("c") ?? "";

  const cargarConversaciones = useCallback(async (signal?: AbortSignal) => {
    setConversaciones(await listar<Conversacion>("/api/v1/chat/conversaciones", { signal }));
  }, []);

  useEffect(() => {
    const control = new AbortController();
    void cargarConversaciones(control.signal).catch(salvoCancelacion(setFallo));
    listar<Usuario>("/api/v1/usuarios?limite=200", { signal: control.signal })
      .then((us) =>
        setUsuarios(
          Object.fromEntries(us.map((u) => [u.id, u])),
        ),
      )
      .catch(salvoCancelacion(() => undefined));
    return () => control.abort();
  }, [cargarConversaciones]);

  // Los mensajes de la conversación abierta.
  useEffect(() => {
    if (!activa) {
      setMensajes([]);
      return;
    }
    const control = new AbortController();
    listar<Mensaje>(`/api/v1/chat/conversaciones/${activa}/mensajes?limite=200`, {
      signal: control.signal,
    })
      .then(setMensajes)
      .catch(salvoCancelacion(setFallo));
    void llamar(`/api/v1/chat/conversaciones/${activa}/leido`, { metodo: "POST", cuerpo: {} }).catch(
      () => undefined,
    );
    return () => control.abort();
  }, [activa]);

  /**
   * Lo nuevo, en vivo.
   *
   * `EventSource` y no un sondeo desde aquí: se reconecta solo tras un corte
   * —que en un portátil es cada vez que se cierra la tapa— y eso escrito a mano
   * es un temporizador que alguien acaba dejando en dos segundos para siempre.
   */
  useEffect(() => {
    const fuente = new EventSource("/api/v1/chat/eventos", { withCredentials: true });
    fuente.addEventListener("mensaje", (evento) => {
      try {
        const mensaje = JSON.parse((evento as MessageEvent).data) as Mensaje;
        setConversaciones((previas) =>
          (previas ?? []).map((c) =>
            c.id === mensaje.conversacion_id && c.id !== activa
              ? { ...c, sin_leer: c.sin_leer + 1 }
              : c,
          ),
        );
        if (mensaje.conversacion_id !== activa) return;
        setMensajes((previos) =>
          previos.some((m) => m.id === mensaje.id) ? previos : [...previos, mensaje],
        );
      } catch {
        // Un evento que no se entiende no tira la pantalla: se ignora y el
        // siguiente llega igual.
      }
    });
    return () => fuente.close();
  }, [activa]);

  useEffect(() => {
    abajo.current?.scrollIntoView({ behavior: "smooth" });
  }, [mensajes.length]);

  // Quién está en esta conversación. Se pide al cambiar de una a otra y no
  // con la lista: la lista de canales no puede costar traerse los miembros de
  // todos para enseñar los de uno.
  useEffect(() => {
    if (!activa) {
      setMiembros([]);
      return;
    }
    const control = new AbortController();
    llamar<{ miembros: Miembro[] }>(`/api/v1/chat/conversaciones/${activa}`, {
      signal: control.signal,
    })
      .then(({ datos }) => setMiembros(datos.miembros ?? []))
      .catch(() => undefined);
    return () => control.abort();
  }, [activa]);

  const { raiz, respuestas } = useMemo(() => {
    const porPadre = new Map<string, Mensaje[]>();
    const sueltos: Mensaje[] = [];
    for (const m of mensajes) {
      if (m.responde_a_id) {
        porPadre.set(m.responde_a_id, [...(porPadre.get(m.responde_a_id) ?? []), m]);
      } else {
        sueltos.push(m);
      }
    }
    return { raiz: sueltos, respuestas: porPadre };
  }, [mensajes]);

  /**
   * Quién está, y desde cuándo no se le ve.
   *
   * Se pide una vez al abrir y no en bucle: un sondeo cada pocos segundos por
   * un dato que cambia cada media hora es tráfico constante para nada.
   */
  useEffect(() => {
    const control = new AbortController();
    llamar<Presencia[]>("/api/v1/chat/presencia", { signal: control.signal })
      .then(({ datos }) => setPresencia(datos))
      .catch(() => undefined);
    return () => control.abort();
  }, []);

  /** Buscar, sólo en mis conversaciones. Lo acota el servidor, no la pantalla. */
  async function buscar() {
    const limpio = termino.trim();
    if (limpio.length < 2) {
      setHallazgos(null);
      return;
    }
    try {
      const { datos } = await llamar<Mensaje[]>(
        `/api/v1/chat/buscar?texto=${encodeURIComponent(limpio)}`,
      );
      setHallazgos(datos);
    } catch (error) {
      setFallo(error);
    }
  }

  /** Qué decía antes este mensaje. */
  async function verVersiones(mensajeId: string) {
    try {
      const { datos } = await llamar<Version[]>(`/api/v1/chat/mensajes/${mensajeId}/versiones`);
      setVersiones({ de: mensajeId, lista: datos });
    } catch (error) {
      setFallo(error);
    }
  }

  async function enviar() {
    if (!texto.trim() || !activa) return;
    setEnviando(true);
    try {
      // Las menciones salen del propio texto: `@correo`. Se resuelven contra la
      // lista de usuarios en vez de pedir que se elijan en un desplegable, que
      // es lo que hace que nadie mencione a nadie.
      const menciones = Object.values(usuarios)
        .filter((u) => texto.includes(`@${u.email}`) || texto.includes(`@${u.nombre}`))
        .map((u) => u.id);
      const r = await llamar<Mensaje>(`/api/v1/chat/conversaciones/${activa}/mensajes`, {
        metodo: "POST",
        cuerpo: { cuerpo: texto, responde_a_id: hilo, menciones },
      });
      setMensajes((previos) => [...previos, r.datos]);
      setTexto("");
      setHilo(null);
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  async function reaccionar(mensajeId: string, emoji: string) {
    try {
      await llamar(`/api/v1/chat/mensajes/${mensajeId}/reacciones`, {
        metodo: "POST",
        cuerpo: { emoji },
      });
      await recargarMensajes();
    } catch (error) {
      setFallo(error);
    }
  }

  /** Recarga los mensajes de la conversación abierta. */
  async function recargarMensajes() {
    setMensajes(await listar<Mensaje>(`/api/v1/chat/conversaciones/${activa}/mensajes?limite=200`));
  }

  /**
   * Manda un mensaje a la papelera, o lo saca de ella (CRM-06.02.02.09).
   *
   * La ruta existía en el servidor y **no tenía botón**: se podía borrar con
   * `curl` y desde la pantalla no. Un endpoint sin botón es una capacidad que
   * nadie usa.
   */
  async function papelera(mensajeId: string, borrado: boolean) {
    try {
      await llamar(
        borrado
          ? `/api/v1/chat/mensajes/${mensajeId}/recuperar`
          : `/api/v1/chat/mensajes/${mensajeId}`,
        { metodo: borrado ? "POST" : "DELETE" },
      );
      await recargarMensajes();
    } catch (error) {
      setFallo(error);
    }
  }

  /**
   * Abre una conversación nueva: un canal o un directo con alguien.
   *
   * Antes esto era un `window.prompt` pidiendo una clave, y solo sabía hacer
   * canales. Así que **no había forma de escribirle a una persona**, que es
   * para lo que se abre un chat la mayoría de las veces, y el diálogo del
   * navegador no decía ni qué era una clave ni que hubiera otra opción.
   *
   * Un directo con alguien con quien ya se habló devuelve el que hay: el
   * servidor lo resuelve, porque abrir uno nuevo al lado del que tiene el
   * histórico es como se acaban teniendo tres conversaciones con la misma
   * persona.
   */
  async function abrirConversacion(cuerpo: Record<string, unknown>) {
    try {
      const r = await llamar<Conversacion>("/api/v1/chat/conversaciones", {
        metodo: "POST",
        cuerpo,
      });
      setAbriendo(false);
      await cargarConversaciones();
      setParametros({ c: r.datos.id });
    } catch (error) {
      setFallo(error);
    }
  }

  function Burbuja({ mensaje, dentro = false }: { mensaje: Mensaje; dentro?: boolean }) {
    const mio = mensaje.autor_id === sesion?.usuario_id;
    const autor = usuarios[mensaje.autor_id];
    const hijas = respuestas.get(mensaje.id) ?? [];
    return (
      <li className={cn("group", dentro && "ml-6 border-l border-ink-dim/60 pl-3")}>
        <div className={cn("rounded-xl px-3 py-2", mio ? "bg-accent/10" : "bg-paper-sunk")}>
          <p className="flex items-baseline gap-2 text-3xs text-ink-faint">
            <span className="font-medium text-ink-muted">
              {autor?.nombre || autor?.email || t("chat.alguien")}
            </span>
            <time dateTime={mensaje.created_at}>
              {new Date(mensaje.created_at).toLocaleString(localizacion(), {
                day: "2-digit",
                month: "short",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </time>
            {/* «Editado» no es una etiqueta: es la puerta a QUÉ DECÍA ANTES.
                Una conversación donde se puede cambiar lo dicho sin que se
                pueda mirar lo anterior no sirve para explicar una decisión, y
                el servidor lo guardaba sin que nadie pudiera verlo. */}
            {mensaje.ediciones > 0 ? (
              <button
                type="button"
                onClick={() => void verVersiones(mensaje.id)}
                title={t("chat.editadoVeces", { veces: mensaje.ediciones })}
                className="underline decoration-dotted hover:text-ink"
              >
                · {t("chat.editado")}
              </button>
            ) : null}
          </p>
          {mensaje.borrado ? (
            <p className="mt-1 text-xs italic text-ink-faint">{t("chat.borrado")}</p>
          ) : (
            <p className="mt-1 whitespace-pre-wrap text-xs text-ink">{mensaje.cuerpo}</p>
          )}

          <div className="mt-1 flex flex-wrap items-center gap-1">
            {Object.entries(mensaje.reacciones).map(([emoji, quienes]) => (
              <button
                key={emoji}
                type="button"
                onClick={() => void reaccionar(mensaje.id, emoji)}
                className="rounded-lg border border-ink-dim/60 px-1.5 py-0.5 text-3xs text-ink-muted hover:bg-paper"
              >
                {emoji} {quienes.length}
              </button>
            ))}
            {/* Las reacciones aparecen al pasar por encima: siempre visibles,
                seis emojis por mensaje ocupan más que el propio mensaje. */}
            <span className="hidden gap-0.5 group-hover:flex">
              {REACCIONES.filter((e) => !(e in mensaje.reacciones)).map((emoji) => (
                <button
                  key={emoji}
                  type="button"
                  title={t("chat.reaccionar")}
                  onClick={() => void reaccionar(mensaje.id, emoji)}
                  className="rounded-lg px-1 py-0.5 text-3xs opacity-60 hover:opacity-100"
                >
                  {emoji}
                </button>
              ))}
            </span>
            {!dentro && !mensaje.borrado ? (
              <button
                type="button"
                onClick={() => setHilo(mensaje.id)}
                className="ml-1 hidden rounded-lg px-1.5 py-0.5 text-3xs text-ink-muted hover:bg-paper group-hover:block"
              >
                {t("chat.responder")}
              </button>
            ) : null}
            {/* Solo sobre lo propio: el servidor deja además a quien administra
                la conversación, y esta pantalla no sabe todavía quién lo es. */}
            {mio ? (
              <button
                type="button"
                onClick={() => void papelera(mensaje.id, Boolean(mensaje.borrado))}
                className="ml-1 hidden rounded-lg px-1.5 py-0.5 text-3xs text-ink-muted hover:bg-paper group-hover:block"
              >
                {mensaje.borrado ? t("chat.recuperar") : t("chat.borrar")}
              </button>
            ) : null}
          </div>
        </div>
        {hijas.length > 0 ? (
          <ul className="mt-1 space-y-1">
            {hijas.map((h) => (
              <Burbuja key={h.id} mensaje={h} dentro />
            ))}
          </ul>
        ) : null}
      </li>
    );
  }

  const abierta = (conversaciones ?? []).find((c) => c.id === activa);

  return (
    <>
      <CabeceraPagina titulo={t("chat.titulo")} entradilla={t("chat.intro")} icono="forum" />
      {fallo ? <Fallo error={fallo} /> : null}

      <div className="mt-4 grid gap-3 lg:grid-cols-[16rem_1fr]">
        <aside className="rounded-xl border border-ink-dim/60 bg-paper p-2">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-2xs font-medium uppercase tracking-wide text-ink-faint">
              {t("chat.conversaciones")}
            </h2>
            <button
              type="button"
              onClick={() => setAbriendo((v) => !v)}
              aria-expanded={abriendo}
              title={t("chat.nueva")}
              className="rounded-lg px-1.5 py-0.5 text-ink-muted hover:bg-paper-sunk hover:text-ink"
            >
              <Icono nombre={abriendo ? "close" : "add"} />
            </button>
          </div>
          {abriendo ? (
            <NuevaConversacion
              usuarios={usuarios}
              yo={sesion?.usuario_id ?? ""}
              alAbrir={abrirConversacion}
            />
          ) : null}
          {conversaciones === null ? (
            <Cargando />
          ) : conversaciones.length === 0 ? (
            <p className="px-2 py-3 text-3xs text-ink-faint">{t("chat.sinConversaciones")}</p>
          ) : (
            <ul className="space-y-0.5">
              {conversaciones.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => setParametros({ c: c.id })}
                    className={cn(
                      "flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-xs",
                      c.id === activa
                        ? "bg-paper-light text-ink"
                        : "text-ink-muted hover:bg-paper-light",
                    )}
                  >
                    <span className="truncate">{titulo(c)}</span>
                    {c.sin_leer > 0 ? (
                      <span className="ml-2 rounded-full bg-accent px-1.5 text-3xs text-white">
                        {c.sin_leer}
                      </span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}

          {/* ── Buscar, sólo en lo mío ──────────────────────────────────
              A los seis meses nadie recuerda en qué canal se dijo algo, que
              es justo lo que hace falta encontrar. Lo acota el SERVIDOR a las
              conversaciones de quien pregunta: buscar en todas devolvería
              texto de canales en los que no se está. */}
          <form
            className="mt-3 border-t border-ink-dim/60 pt-2"
            onSubmit={(e) => {
              e.preventDefault();
              void buscar();
            }}
          >
            <label htmlFor="buscar-chat" className="sr-only">
              {t("chat.buscar")}
            </label>
            <input
              id="buscar-chat"
              value={termino}
              onChange={(e) => setTermino(e.target.value)}
              placeholder={t("chat.buscar")}
              className="input-sm w-full"
            />
            {hallazgos ? (
              <div className="mt-2">
                <p className="text-3xs text-ink-faint" role="status">
                  {t("chat.hallazgos", { cuantos: hallazgos.length })}
                </p>
                <ul className="lista-acotada mt-1 space-y-1">
                  {hallazgos.map((m) => (
                    <li key={m.id}>
                      <button
                        type="button"
                        onClick={() => setParametros({ c: m.conversacion_id })}
                        className="w-full rounded-lg px-2 py-1 text-left text-3xs text-ink-muted hover:bg-paper-light"
                      >
                        {m.cuerpo.slice(0, 90)}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </form>

          {/* ── Quién está ──────────────────────────────────────────────
              No es un adorno social: contesta «¿espero respuesta o llamo?».
              Por eso va el «visto por última vez» y no sólo un punto verde. */}
          {presencia.length > 0 ? (
            <div className="mt-3 border-t border-ink-dim/60 pt-2">
              <h2 className="text-3xs font-medium uppercase tracking-wide text-ink-faint">
                {t("chat.quienEsta")}
              </h2>
              <ul className="mt-1 space-y-0.5">
                {presencia.map((pr) => (
                  <li key={pr.usuario_id} className="flex items-baseline gap-2 text-3xs">
                    <span className="text-ink-muted">
                      {usuarios[pr.usuario_id]?.nombre ?? t("chat.alguien")}
                    </span>
                    <span className="chip-dato">{pr.estado}</span>
                    {pr.mensaje ? (
                      <span className="text-ink-faint">{pr.mensaje}</span>
                    ) : null}
                    {pr.visto_at ? (
                      <time className="text-ink-faint" dateTime={pr.visto_at}>
                        {t("chat.vistoA", {
                          cuando: new Date(pr.visto_at).toLocaleString(localizacion(), {
                            day: "2-digit",
                            month: "short",
                            hour: "2-digit",
                            minute: "2-digit",
                          }),
                        })}
                      </time>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </aside>

        <section className="flex min-h-[28rem] flex-col rounded-xl border border-ink-dim/60 bg-paper">
          {!abierta ? (
            <Vacio
              icono="forum"
              titulo={t("chat.eligeUna")}
              detalle={t("chat.eligeUnaDetalle")}
            />
          ) : (
            <>
              <header className="border-b border-ink-dim/60 px-3 py-2">
                <h2 className="text-xs font-medium text-ink">{titulo(abierta)}</h2>
                {abierta.proposito ? (
                  <p className="text-3xs text-ink-faint">{abierta.proposito}</p>
                ) : null}
                {abierta.objeto_tipo ? (
                  /* Lo que hace que esto no sea un chat cualquiera: se ve de qué
                     registro se está hablando sin salir de aquí. */
                  <p className="mt-0.5 text-3xs text-accent">
                    <Icono nombre="link" /> {t("chat.sobreEl", { objeto: abierta.objeto_tipo })}
                  </p>
                ) : null}
                {/* QUIÉN LO VA A LEER. Antes de escribir algo delicado en un
                    canal hay que poder saberlo, y el servidor lo devolvía sin
                    que ninguna pantalla lo enseñara. */}
                {miembros.length > 0 ? (
                  <p className="mt-0.5 flex flex-wrap items-baseline gap-1 text-3xs text-ink-faint">
                    <span>{t("chat.miembros", { cuantos: miembros.length })}</span>
                    {miembros.map((m) => (
                      <span key={m.usuario_id} className="chip-dato">
                        {usuarios[m.usuario_id]?.nombre ?? t("chat.alguien")}
                        {m.rol === "admin" ? ` · ${t("chat.admin")}` : ""}
                      </span>
                    ))}
                  </p>
                ) : null}
              </header>

              {/* En un chat esto no es un requisito que se cumple: es la
                  función. Quien no ve la pantalla tiene que enterarse de que
                  ha llegado algo y de quién, que es justo lo que un lector de
                  pantalla no puede deducir de una lista que crece sola. */}
              <p className="sr-only" role="status" aria-live="polite">
                {mensajes.length > 0
                  ? t("chat.ultimoDe", {
                      quien:
                        usuarios[mensajes[mensajes.length - 1]!.autor_id]?.nombre ??
                        t("chat.alguien"),
                      texto: mensajes[mensajes.length - 1]!.cuerpo.slice(0, 120),
                    })
                  : ""}
              </p>
              {/* ── Qué decía antes ───────────────────────────────────
                  Lo corregido se ve corregido, no reescrito. Se abre desde el
                  «editado» del propio mensaje y se cierra: no vive abierto,
                  porque es una consulta puntual y no parte de la
                  conversación. */}
              {versiones ? (
                <div className="border-b border-ink-dim/60 bg-paper-sunk px-3 py-2">
                  <div className="flex items-baseline justify-between">
                    <h3 className="text-3xs font-medium uppercase tracking-wide text-ink-faint">
                      {t("chat.queDeciaAntes")}
                    </h3>
                    <button
                      type="button"
                      onClick={() => setVersiones(null)}
                      aria-label={t("chat.cerrar")}
                      className="text-ink-muted hover:text-ink"
                    >
                      <Icono nombre="close" />
                    </button>
                  </div>
                  {versiones.lista.length === 0 ? (
                    <p className="text-3xs text-ink-faint">{t("chat.sinVersiones")}</p>
                  ) : (
                    <ol className="mt-1 space-y-1">
                      {versiones.lista.map((v, i) => (
                        <li
                          key={i}
                          className="rounded-lg bg-paper px-2 py-1 text-3xs text-ink-muted"
                        >
                          {v.cuerpo}
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              ) : null}

              <ul className="flex-1 space-y-2 overflow-y-auto p-3">
                {raiz.map((m) => (
                  <Burbuja key={m.id} mensaje={m} />
                ))}
                <div ref={abajo} />
              </ul>

              <div className="border-t border-ink-dim/60 p-2">
                {hilo ? (
                  <p className="mb-1 flex items-center gap-2 text-3xs text-ink-faint">
                    {t("chat.respondiendo")}
                    <button
                      type="button"
                      onClick={() => setHilo(null)}
                      className="text-ink-muted hover:text-ink"
                    >
                      <Icono nombre="close" />
                    </button>
                  </p>
                ) : null}
                <form
                  className="flex gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void enviar();
                  }}
                >
                  <input
                    value={texto}
                    onChange={(e) => setTexto(e.target.value)}
                    placeholder={t("chat.escribe")}
                    aria-label={t("chat.escribe")}
                    className="input-base flex-1"
                  />
                  <button
                    type="submit"
                    disabled={enviando || !texto.trim()}
                    className="rounded-xl bg-accent px-3 py-1.5 text-xs text-white disabled:opacity-50"
                  >
                    {t("chat.enviar")}
                  </button>
                </form>
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}

/**
 * Abrir una conversación: un canal, o un directo con alguien.
 *
 * Las dos cosas en el mismo sitio y con las personas a la vista, porque
 * escribirle a alguien es lo que más se hace y era justo lo que no se podía:
 * el botón solo sabía crear canales, y pedía «la clave» en un diálogo del
 * navegador sin decir qué era eso.
 */
function NuevaConversacion({
  usuarios,
  yo,
  alAbrir,
}: {
  usuarios: Record<string, Usuario>;
  yo: string;
  alAbrir: (cuerpo: Record<string, unknown>) => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const [modo, setModo] = useState<"directo" | "canal">("directo");
  const [nombre, setNombre] = useState("");
  const [busca, setBusca] = useState("");

  // Uno mismo fuera: un directo con uno mismo no es una conversación, y
  // ofrecerlo es ofrecer algo que al pulsarlo no hace nada útil.
  const gente = Object.values(usuarios)
    .filter((u) => u.id !== yo)
    .filter((u) => {
      const q = busca.trim().toLowerCase();
      return !q || `${u.nombre} ${u.email}`.toLowerCase().includes(q);
    })
    .slice(0, 12);

  return (
    <div className="mb-2 rounded-lg border border-ink-dim/60 bg-paper-sunk p-2">
      <div className="mb-2 flex gap-1" role="tablist">
        {(["directo", "canal"] as const).map((x) => (
          <button
            key={x}
            type="button"
            role="tab"
            aria-selected={modo === x}
            onClick={() => setModo(x)}
            className={cn(
              "rounded-lg px-2 py-1 text-3xs",
              modo === x ? "bg-accent/15 text-accent" : "text-ink-muted hover:bg-paper",
            )}
          >
            {t(x === "directo" ? "chat.conAlguien" : "chat.unCanal")}
          </button>
        ))}
      </div>

      {modo === "directo" ? (
        <>
          <input
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            placeholder={t("chat.buscarPersona")}
            aria-label={t("chat.buscarPersona")}
            className="input-base mb-1"
          />
          {gente.length === 0 ? (
            <p className="px-1 py-2 text-3xs text-ink-faint">{t("chat.nadieAsi")}</p>
          ) : (
            <ul className="space-y-0.5">
              {gente.map((u) => (
                <li key={u.id}>
                  <button
                    type="button"
                    onClick={() => void alAbrir({ tipo: "directo", miembros: [u.id] })}
                    className="w-full truncate rounded-lg px-2 py-1 text-left text-2xs text-ink hover:bg-paper"
                  >
                    {u.nombre || u.email}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const clave = nombre.trim();
            if (!clave) return;
            void alAbrir({ tipo: "canal", clave, nombre: clave });
          }}
        >
          <input
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            placeholder={t("chat.comoSeLlama")}
            aria-label={t("chat.comoSeLlama")}
            className="input-base mb-1"
          />
          <button type="submit" disabled={!nombre.trim()} className="btn-primary w-full">
            {t("chat.crearCanal")}
          </button>
        </form>
      )}
    </div>
  );
}
