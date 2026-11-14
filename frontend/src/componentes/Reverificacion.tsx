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
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { ErrorApi, llamar, registrarReverificacion } from "@/lib/api";

export function Reverificacion() {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  const [codigo, setCodigo] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState("");
  const [sinApp, setSinApp] = useState(false);
  const resolver = useRef<((ok: boolean) => void) | null>(null);
  const campo = useRef<HTMLInputElement>(null);

  const cerrar = useCallback((ok: boolean) => {
    setAbierto(false);
    setCodigo("");
    setFallo("");
    setSinApp(false);
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
          // Quien no tiene la app no puede escribir el código: se le dice
          // de entrada, en vez de pedírselo y contestar después que no vale.
          void llamar<{ tiene_app?: boolean }>("/api/v1/factores/nivel", {
            sinReverificar: true,
          })
            .then((r) => {
              if (r.datos.tiene_app === false) setSinApp(true);
            })
            // Es sólo una pista para el diálogo: sin ella se pide el código
            // igual, que es lo que se hacía antes de tenerla, y un error aquí
            // taparía el diálogo que hay que contestar.
            .catch(() => undefined);
        }),
    );
    return () => registrarReverificacion(null);
  }, []);

  useEffect(() => {
    if (abierto) campo.current?.focus();
  }, [abierto]);

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
        setSinApp(true);
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
          {sinApp ? null : ` ${t("reverificar.pideCodigo")}`}
        </p>
        {sinApp ? (
          <div className="mt-4" role="status">
            <p className="text-dato text-ink">{t("reverificar.sinApp")}</p>
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
          <form
            className="mt-4"
            onSubmit={(e) => {
              e.preventDefault();
              void confirmar();
            }}
          >
            <label htmlFor="reverificar-codigo" className="section-label">
              {t("reverificar.codigo")}
            </label>
            <input
              id="reverificar-codigo"
              ref={campo}
              value={codigo}
              onChange={(e) => setCodigo(e.target.value.replace(/\D/g, ""))}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              className="input mt-1 w-full font-mono tracking-widest"
            />
            {fallo ? (
              <p className="mt-2 text-dato text-danger" role="alert">
                {fallo}
              </p>
            ) : null}
            <div className="mt-4 flex gap-2">
              <button
                type="submit"
                className="btn-primary"
                disabled={enviando || codigo.trim().length !== 6}
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
        )}
      </div>
    </div>
  );
}
