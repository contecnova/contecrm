/**
 * Dar de alta y quitar las passkeys propias (CRM-00.05.01.23).
 *
 * El servidor tenía las cuatro rutas —empezar el alta, guardarla, listar y
 * quitar— y el front solo contaba cuántas había: «2 passkeys registradas» sin
 * forma de añadir una tercera ni de quitar la del portátil que se perdió. Una
 * llave que no se puede revocar desde la propia cuenta es una llave que sigue
 * abriendo hasta que alguien de soporte la borre a mano.
 *
 * **Reverificarse no se hace aquí.** Desde el 13-11-2026 (SEC-4) el alta exige
 * haberse verificado hace poco si la cuenta ya tiene un factor fuerte: con una
 * sesión robada se colgaba una llave propia en la cuenta de otro. El servidor
 * contesta `stepup.requerido` y `llamar` abre el diálogo del marco, pide el
 * código y repite la llamada; esta pantalla solo se entera si la persona lo
 * cancela, y entonces dice por qué no se ha podido.
 *
 * Quitar no pide reverificarse —el servidor no lo exige— pero sí confirmación:
 * se borra de verdad y no hay papelera de la que recuperarla.
 */

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmarBorrado } from "@/componentes/Edicion";
import { Error as Fallo } from "@/componentes/Estados";
import { ErrorApi, llamar } from "@/lib/api";
import { fecha, fechaHora } from "@/lib/formato";
import { admitePasskeys, crearPasskey } from "@/lib/webauthn";

/** `GET /auth/passkeys`, fila a fila. */
export interface Passkey {
  id: string;
  nombre?: string;
  creada_at?: string;
  ultimo_uso_at?: string | null;
}

/** Lo que se le dice a la persona cuando no es un error del servidor. */
type Aviso =
  | { tipo: "hecho"; texto: string }
  | { tipo: "nota"; texto: string }
  | { tipo: "fallo"; error: unknown };

export function MisPasskeys({
  passkeys,
  tieneApp,
  alCambiar,
}: {
  passkeys: Passkey[];
  /** Si la cuenta tiene la app de códigos: con ella, quitar la última llave
   * no la deja sin factor fuerte. `undefined` mientras no se sabe. */
  tieneApp?: boolean;
  /** Para volver a leer la lista y lo que depende de ella. */
  alCambiar: () => void;
}) {
  const { t } = useTranslation();
  const [nombre, setNombre] = useState("");
  const [creando, setCreando] = useState(false);
  const [quitando, setQuitando] = useState(false);
  const [aQuitar, setAQuitar] = useState<Passkey | null>(null);
  const [aviso, setAviso] = useState<Aviso | null>(null);
  const navegadorSabe = admitePasskeys();
  const zonaDelAviso = useRef<HTMLDivElement>(null);

  // El resultado se anuncia y recibe el foco: el diálogo del sistema se lo
  // lleva mientras se toca la llave, y al volver no queda nada enfocado.
  useEffect(() => {
    if (aviso) zonaDelAviso.current?.focus();
  }, [aviso]);

  function nombreDe(p: Passkey): string {
    return p.nombre?.trim() || t("seguridad.passkeys.sinNombre");
  }

  async function anadir(evento: FormEvent) {
    evento.preventDefault();
    setAviso(null);
    setCreando(true);
    try {
      // Sin cola sin conexión: un alta de llave a medias no se puede reanudar
      // más tarde, el reto caduca en minutos.
      const opciones = await llamar<Record<string, unknown>>(
        "/api/v1/auth/passkeys",
        { metodo: "POST", encolable: false },
      );
      const respuesta = await crearPasskey(opciones.datos as never);
      const guardada = await llamar<{ id: string; nombre: string }>(
        "/api/v1/auth/passkeys/confirmar",
        {
          metodo: "POST",
          cuerpo: { respuesta, nombre: nombre.trim() },
          encolable: false,
        },
      );
      setNombre("");
      setAviso({
        tipo: "hecho",
        texto: t("seguridad.passkeys.anadida", {
          nombre:
            guardada.datos?.nombre?.trim() ||
            t("seguridad.passkeys.sinNombre"),
        }),
      });
      alCambiar();
    } catch (error) {
      setAviso(avisoDelAlta(error));
    } finally {
      setCreando(false);
    }
  }

  function avisoDelAlta(error: unknown): Aviso {
    // Cancelar el diálogo del sistema, o dejar que se agote, no es un fallo:
    // se dice qué ha pasado sin pintarlo en rojo.
    if (error instanceof DOMException && error.name === "NotAllowedError")
      return { tipo: "nota", texto: t("seguridad.passkeys.cancelada") };
    // El navegador lo dice cuando este dispositivo ya está entre las llaves
    // que mandó el servidor para no registrarlo dos veces.
    const yaEsta = t("seguridad.passkeys.yaEnEsteDispositivo");
    if (error instanceof DOMException && error.name === "InvalidStateError")
      return { tipo: "nota", texto: yaEsta };
    if (error instanceof ErrorApi && error.codigo === "passkey.ya_registrada")
      return { tipo: "nota", texto: yaEsta };
    // El diálogo de reverificación del marco se canceló, o no había con qué:
    // sin la app, el único camino es volver a entrar con la passkey.
    if (error instanceof ErrorApi && error.codigo === "stepup.requerido")
      return {
        tipo: "nota",
        texto:
          tieneApp === false
            ? t("seguridad.passkeys.faltaVerificarteSinApp")
            : t("seguridad.passkeys.faltaVerificarte"),
      };
    return { tipo: "fallo", error };
  }

  async function quitar(llave: Passkey) {
    setAviso(null);
    setQuitando(true);
    try {
      await llamar(
        `/api/v1/auth/passkeys/${encodeURIComponent(llave.id)}`,
        { metodo: "DELETE", encolable: false },
      );
      setAQuitar(null);
      setAviso({
        tipo: "hecho",
        texto: t("seguridad.passkeys.quitada", { nombre: nombreDe(llave) }),
      });
      alCambiar();
    } catch (error) {
      setAQuitar(null);
      // Ya no estaba —la quitó otra pestaña—: lo que hay que hacer es lo
      // mismo que si se hubiera quitado ahora, leer la lista otra vez.
      if (
        error instanceof ErrorApi &&
        error.codigo === "passkey.no_encontrada"
      ) {
        setAviso({ tipo: "nota", texto: t("seguridad.passkeys.yaNoEstaba") });
        alCambiar();
      } else setAviso({ tipo: "fallo", error });
    } finally {
      setQuitando(false);
    }
  }

  // La última llave de una cuenta sin la app: quitarla deja la cuenta sin
  // factor fuerte, y lo que se haya exigido por rol dejará de cumplirse.
  const esLaUltimaFuerte = passkeys.length === 1 && tieneApp === false;

  return (
    <div
      className="card mt-1 flex flex-col gap-3 p-4"
      aria-labelledby="mis-passkeys-titulo"
      role="group"
    >
      <div>
        <h3 id="mis-passkeys-titulo" className="section-label">
          {t("seguridad.passkeys.titulo")}
        </h3>
        <p className="mt-1 text-rotulo text-ink-faint">
          {t("seguridad.passkeys.ayuda")}
        </p>
      </div>

      {passkeys.length === 0 ? (
        <p className="text-dato text-ink-muted">
          {t("seguridad.passkeys.ninguna")}
        </p>
      ) : (
        <ul className="divide-y divide-ink-dim/30 overflow-hidden rounded-lg border border-ink-dim/40">
          {passkeys.map((p) => (
            <li key={p.id} className="flex flex-col gap-2 px-3 py-2">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-dato text-ink">{nombreDe(p)}</p>
                  {/* Cuándo se dio de alta y cuándo se usó: sin eso, revocar
                      una de tres es elegir a ciegas. */}
                  <p className="text-rotulo text-ink-faint">
                    {p.creada_at
                      ? t("seguridad.passkeys.creada", {
                          fecha: fecha(p.creada_at),
                        })
                      : null}
                    {p.creada_at ? " · " : null}
                    {p.ultimo_uso_at
                      ? t("seguridad.passkeys.ultimoUso", {
                          fecha: fechaHora(p.ultimo_uso_at),
                        })
                      : t("seguridad.passkeys.sinUsar")}
                  </p>
                </div>
                <button
                  type="button"
                  className="btn-secondary"
                  aria-label={t("seguridad.passkeys.quitarLa", {
                    nombre: nombreDe(p),
                  })}
                  disabled={quitando || creando}
                  onClick={() => {
                    setAviso(null);
                    setAQuitar(p);
                  }}
                >
                  {t("seguridad.passkeys.quitar")}
                </button>
              </div>
              {aQuitar?.id === p.id ? (
                <ConfirmarBorrado
                  enviando={quitando}
                  borrado={t("seguridad.passkeys.quitarLa", {
                    nombre: nombreDe(p),
                  })}
                  aviso={
                    esLaUltimaFuerte
                      ? `${t("seguridad.passkeys.avisoQuitar")} ${t("seguridad.passkeys.avisoUltima")}`
                      : t("seguridad.passkeys.avisoQuitar")
                  }
                  alBorrar={() => void quitar(p)}
                  alCancelar={() => setAQuitar(null)}
                />
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {navegadorSabe ? (
        <form
          onSubmit={(e) => void anadir(e)}
          className="flex flex-wrap items-end gap-2"
        >
          <div className="flex min-w-[14rem] flex-1 flex-col gap-1">
            <label
              htmlFor="passkey-nombre"
              className="text-rotulo text-ink-muted"
            >
              {t("seguridad.passkeys.nombre")}
            </label>
            <input
              id="passkey-nombre"
              className="input-base"
              value={nombre}
              maxLength={120}
              autoComplete="off"
              aria-describedby="passkey-nombre-ayuda"
              onChange={(e) => setNombre(e.target.value)}
            />
            <p id="passkey-nombre-ayuda" className="text-rotulo text-ink-faint">
              {t("seguridad.passkeys.nombreAyuda")}
            </p>
          </div>
          <button
            type="submit"
            className="btn-primary"
            disabled={creando || quitando}
            aria-busy={creando}
          >
            {creando
              ? t("seguridad.passkeys.creando")
              : t("seguridad.passkeys.anadir")}
          </button>
        </form>
      ) : (
        <p className="text-dato text-ink-muted">
          {t("seguridad.passkeys.navegadorNoSabe")}
        </p>
      )}

      {/* La zona existe siempre, vacía o no: una región viva que aparece con
          el texto ya dentro no la anuncia ningún lector. */}
      <div
        ref={zonaDelAviso}
        tabIndex={-1}
        aria-live="polite"
        className="outline-none"
      >
        {aviso?.tipo === "hecho" ? (
          <p className="text-dato text-success">{aviso.texto}</p>
        ) : aviso?.tipo === "nota" ? (
          <p className="text-dato text-warning">{aviso.texto}</p>
        ) : aviso?.tipo === "fallo" ? (
          <Fallo error={aviso.error} />
        ) : null}
      </div>
    </div>
  );
}
