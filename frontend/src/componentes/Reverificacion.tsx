/**
 * Volver a verificarse sin salir (CRM-00.05.01.18).
 *
 * Las operaciones sensibles —crear una clave de API, exportar media base,
 * borrar en bloque, restaurar— exigen un factor fuerte reciente. Hasta el
 * 10-11-2026 no había forma de dárselo con la sesión abierta: el servidor no
 * tenía ruta para comprobar el código de la app, y cada pantalla enseñaba el
 * rechazo como un error. Había que salir y volver a entrar.
 *
 * Se monta una vez en el marco y se registra en `llamar`: cuando una llamada
 * contesta `stepup.requerido`, se abre, pide el código, lo comprueba en
 * `POST /auth/mfa/reverificar` (la pasarela cambia la cookie por el token
 * elevado) y la llamada se repite. Si se cancela, la pantalla recibe el error
 * de siempre.
 *
 * **Y con la passkey** (auditoría 13-11-2026, UX-28). Sólo había código de
 * app: quien tenía únicamente passkeys —el factor más fuerte de los que hay—
 * leía «no tienes con qué verificarte» y tenía que salir y volver a entrar con
 * la llave. Ahora firma aquí mismo (`POST /auth/passkeys/reverificar` y
 * `…/confirmar`), y la pasarela cambia la cookie igual que con el código.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { ErrorApi, llamar, registrarReverificacion } from "@/lib/api";
import { admitePasskeys, firmarConPasskey } from "@/lib/webauthn";

/**
 * Con qué puede verificarse quien está dentro, según `/factores/nivel`.
 * `null` es «no se sabe» —la pista no llegó—, y entonces se ofrece todo: es
 * lo que se hacía antes de tenerla, y el servidor dice si algo no vale.
 */
interface Medios {
  app: boolean | null;
  passkey: boolean | null;
}

const SIN_SABER: Medios = { app: null, passkey: null };

export function Reverificacion() {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  const [codigo, setCodigo] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState("");
  const [medios, setMedios] = useState<Medios>(SIN_SABER);
  const [firmando, setFirmando] = useState(false);
  const resolver = useRef<((ok: boolean) => void) | null>(null);
  const campo = useRef<HTMLInputElement>(null);
  const conLlave = useRef<HTMLButtonElement>(null);

  const cerrar = useCallback((ok: boolean) => {
    setAbierto(false);
    setCodigo("");
    setFallo("");
    setMedios(SIN_SABER);
    resolver.current?.(ok);
    resolver.current = null;
  }, []);

  useEffect(() => {
    registrarReverificacion(
      () =>
        new Promise<boolean>((resolve) => {
          // Si ya hay uno abierto, el anterior se da por cancelado: dos
          // diálogos a la vez pidiendo el mismo código no los entiende nadie.
          resolver.current?.(false);
          resolver.current = resolve;
          setAbierto(true);
          // Quien no tiene la app no puede escribir el código, y quien no
          // tiene passkey no puede firmar: se le ofrece sólo lo que tiene,
          // en vez de pedírselo y contestar después que no vale.
          void llamar<{ tiene_app?: boolean; tiene_passkey?: boolean }>(
            "/api/v1/factores/nivel",
            { sinReverificar: true },
          )
            .then((r) =>
              setMedios({
                app: typeof r.datos.tiene_app === "boolean" ? r.datos.tiene_app : null,
                passkey:
                  typeof r.datos.tiene_passkey === "boolean"
                    ? r.datos.tiene_passkey
                    : null,
              }),
            )
            // Es sólo una pista para el diálogo: sin ella se pide el código
            // igual, que es lo que se hacía antes de tenerla, y un error aquí
            // taparía el diálogo que hay que contestar.
            .catch(() => undefined);
        }),
    );
    return () => registrarReverificacion(null);
  }, []);

  // Lo que se ofrece. La passkey sólo si el navegador sabe firmar: ofrecer
  // un botón que no puede hacer nada es peor que no ofrecerlo.
  const ofreceLlave = medios.passkey !== false && admitePasskeys();
  const ofreceCodigo = medios.app !== false;
  const sinNada = !ofreceLlave && !ofreceCodigo;

  // El foco, a lo primero que se puede hacer: la llave si la hay —un toque—,
  // y si no, la caja del código.
  useEffect(() => {
    if (!abierto) return;
    if (ofreceLlave) conLlave.current?.focus();
    else campo.current?.focus();
  }, [abierto, ofreceLlave]);

  async function firmar() {
    setFirmando(true);
    setFallo("");
    try {
      const reto = await llamar<Record<string, unknown>>(
        "/api/v1/auth/passkeys/reverificar",
        { metodo: "POST", sinReverificar: true, encolable: false },
      );
      const firmada = await firmarConPasskey(reto.datos as never);
      await llamar("/api/v1/auth/passkeys/reverificar/confirmar", {
        metodo: "POST",
        cuerpo: { respuesta: firmada },
        sinReverificar: true,
        encolable: false,
      });
      cerrar(true);
    } catch (error) {
      // Cancelar el diálogo del sistema no es un fallo: no se dice nada y se
      // puede volver a intentar o usar el código.
      if (error instanceof DOMException && error.name === "NotAllowedError")
        return;
      if (error instanceof ErrorApi && error.codigo === "auth.sin_passkey") {
        setMedios((m) => ({ ...m, passkey: false }));
      } else {
        setFallo(
          error instanceof ErrorApi
            ? error.explicacion || error.titulo
            : String(error),
        );
      }
    } finally {
      setFirmando(false);
    }
  }

  async function confirmar() {
    setEnviando(true);
    setFallo("");
    try {
      await llamar("/api/v1/auth/mfa/reverificar", {
        metodo: "POST",
        cuerpo: { codigo: codigo.trim() },
        sinReverificar: true,
        encolable: false,
      });
      cerrar(true);
    } catch (error) {
      if (error instanceof ErrorApi && error.codigo === "auth.mfa_no_activa") {
        setMedios((m) => ({ ...m, app: false }));
      } else {
        setFallo(
          error instanceof ErrorApi
            ? error.explicacion || error.titulo
            : String(error),
        );
      }
    } finally {
      setEnviando(false);
    }
  }

  if (!abierto) return null;
  return (
    <div className="fixed inset-0 z-command flex items-start justify-center p-4 pt-24">
      <button
        type="button"
        onClick={() => cerrar(false)}
        aria-label={t("reverificar.cancelar")}
        className="fixed inset-0 cursor-default bg-ink/50"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="reverificar-titulo"
        className="card relative w-full max-w-md animate-fade-in p-4 shadow-elevation-3"
      >
        <h2
          id="reverificar-titulo"
          className="text-titulo font-semibold text-ink"
        >
          {t("reverificar.titulo")}
        </h2>
        <p className="mt-2 text-dato text-ink-muted">
          {t("reverificar.porQue")}
        </p>
        {sinNada ? (
          <div className="mt-4" role="status">
            <p className="text-dato text-ink">
              {t(
                medios.passkey ? "reverificar.sinNavegador" : "reverificar.sinFactor",
              )}
            </p>
            <div className="mt-3 flex gap-2">
              <Link
                to="/puesto"
                className="btn-primary"
                onClick={() => cerrar(false)}
              >
                {t("reverificar.irAlPuesto")}
              </Link>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => cerrar(false)}
              >
                {t("reverificar.cancelar")}
              </button>
            </div>
          </div>
        ) : (
          <>
            {ofreceLlave ? (
              <div className="mt-4">
                <p className="text-dato text-ink">
                  {t("reverificar.pideLlave")}
                </p>
                <button
                  ref={conLlave}
                  type="button"
                  className="btn-primary mt-2"
                  disabled={firmando || enviando}
                  aria-busy={firmando}
                  onClick={() => void firmar()}
                >
                  {firmando
                    ? t("reverificar.firmando")
                    : t("reverificar.conLlave")}
                </button>
              </div>
            ) : null}
            {ofreceCodigo ? (
              <form
                className="mt-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  void confirmar();
                }}
              >
                <p className="mb-2 text-dato text-ink-muted">
                  {t(
                    ofreceLlave
                      ? "reverificar.oCodigo"
                      : "reverificar.pideCodigo",
                  )}
                </p>
                <label htmlFor="reverificar-codigo" className="section-label">
                  {t("reverificar.codigo")}
                </label>
                <input
                  id="reverificar-codigo"
                  ref={campo}
                  value={codigo}
                  onChange={(e) =>
                    setCodigo(e.target.value.replace(/\D/g, ""))
                  }
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  className="input mt-1 w-full font-mono tracking-widest"
                />
                <div className="mt-4 flex gap-2">
                  <button
                    type="submit"
                    className={ofreceLlave ? "btn-secondary" : "btn-primary"}
                    disabled={
                      enviando || firmando || codigo.trim().length !== 6
                    }
                  >
                    {t("reverificar.confirmar")}
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => cerrar(false)}
                  >
                    {t("reverificar.cancelar")}
                  </button>
                </div>
              </form>
            ) : (
              <div className="mt-4 flex gap-2">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => cerrar(false)}
                >
                  {t("reverificar.cancelar")}
                </button>
              </div>
            )}
            {fallo ? (
              <p className="mt-2 text-dato text-danger" role="alert">
                {fallo}
              </p>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
