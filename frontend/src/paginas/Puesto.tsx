/**
 * El puesto de trabajo: correo y calendario conectados (CRM-07.04.03.24).
 *
 * Lo que enseña esta pantalla no es «está conectado»: es **si está entrando algo
 * y desde cuándo no**. Es la diferencia entre un panel que tranquiliza y uno que
 * sirve.
 *
 * Tres decisiones:
 *
 * **Lo que no se ha medido no cuenta como verde.** Una conexión sin última
 * sincronización no es una conexión sana, es una de la que no se sabe nada.
 *
 * **Lo que va por sondeo se dice.** Sus cambios entran con retraso en vez de al
 * instante, y el usuario tiene derecho a saber por qué su cita tarda diez
 * minutos en aparecer.
 *
 * **Y el consentimiento es suyo.** Desde aquí se ve qué autorizó cada persona,
 * recurso a recurso, y se puede revocar — pero nadie puede autorizar por otro.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";
import { CabeceraPagina } from "@/componentes/Pagina";

interface Parada {
  conexion: string;
  horas_sin_sincronizar: number;
  estado: string;
  porque: string;
}

interface Salud {
  total: number;
  paradas: Parada[];
  sin_medir: string[];
  en_sondeo: string[];
  todo_bien: boolean;
  medible: boolean;
  que_significa: string;
  los_en_sondeo: string;
}

/**
 * El segundo factor de TU cuenta: ponerlo y quitarlo.
 *
 * La API sabía activarlo desde el primer día y **ninguna pantalla lo llamaba**,
 * así que nadie podía darlo de alta: lo preguntó quien lo usa el 04-11-2026
 * —«en ningún momento se ha dado de alta el doble factor, por lo menos ¿cómo lo
 * doy de alta?»—. Y quitarlo no existía en ninguna parte: `mfa_activo` se ponía
 * a cierto en un sitio y no volvía nunca, de modo que perder el autenticador
 * dejaba la cuenta inalcanzable. Las dos mitades se cierran aquí.
 *
 * Va en el puesto de trabajo y no en «Seguridad»: aquélla es la vista de quien
 * administra —quién tiene MFA en la empresa, si es obligatoria—, y ésta es tu
 * cuenta. Son dos preguntas distintas y mezclarlas haría que quien busca la
 * suya acabe mirando la de los demás.
 *
 * **El secreto y los códigos de recuperación se enseñan una sola vez**, que es
 * como los devuelve el servidor. Guardarlos para volver a enseñarlos sería
 * tener la llave escrita en la pantalla de todo el que entre después.
 */
function SegundoFactor() {
  const { t } = useTranslation();
  const [activo, setActivo] = useState<boolean | null>(null);
  const [alta, setAlta] = useState<{
    secreto: string;
    uri_otpauth: string;
    codigos_recuperacion: string[];
  } | null>(null);
  const [codigo, setCodigo] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  const mirar = useCallback(() => {
    llamar<{ usuario?: { mfa_activo?: boolean } }>("/api/v1/auth/me")
      .then((r) => setActivo(Boolean(r.datos?.usuario?.mfa_activo)))
      .catch(() => setActivo(null));
  }, []);

  useEffect(mirar, [mirar]);

  async function empezar() {
    setEnviando(true);
    setFallo(null);
    try {
      const r = await llamar<{
        secreto: string;
        uri_otpauth: string;
        codigos_recuperacion: string[];
      }>("/api/v1/auth/mfa/iniciar", { metodo: "POST" });
      setAlta(r.datos);
    } catch (e) {
      setFallo(e);
    } finally {
      setEnviando(false);
    }
  }

  async function confirmar() {
    setEnviando(true);
    setFallo(null);
    try {
      await llamar("/api/v1/auth/mfa/activar", {
        metodo: "POST",
        cuerpo: { codigo: codigo.trim() },
      });
      setAlta(null);
      setCodigo("");
      mirar();
    } catch (e) {
      setFallo(e);
    } finally {
      setEnviando(false);
    }
  }

  async function quitar() {
    setEnviando(true);
    setFallo(null);
    try {
      await llamar("/api/v1/auth/mfa/desactivar", { metodo: "POST" });
      mirar();
    } catch (e) {
      setFallo(e);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="card mt-6 p-4">
      <h2 className="text-titulin font-medium text-ink">
        {t("puesto.factor.titulo")}
      </h2>
      <p className="mt-1 text-dato text-ink-muted">
        {activo === null
          ? t("puesto.factor.sinSaber")
          : activo
            ? t("puesto.factor.puesto")
            : t("puesto.factor.sinPoner")}
      </p>

      {alta ? (
        <div className="mt-3 space-y-3">
          <p className="text-dato text-ink">{t("puesto.factor.comoSeApunta")}</p>
          {/* El secreto, para teclearlo en el autenticador; y el enlace, que en
              un móvil lo abre directamente. Sin imagen de QR: traer una
              biblioteca para dibujarla pesaría más en la apertura de toda la
              aplicación que lo que ahorra en los dos minutos del alta. */}
          <p className="break-all rounded-md bg-paper-light p-2 font-mono text-dato text-ink">
            {alta.secreto}
          </p>
          <a
            href={alta.uri_otpauth}
            className="btn-link inline-block text-dato"
            rel="noreferrer"
          >
            {t("puesto.factor.abrirEnElAutenticador")}
          </a>
          <div>
            <p className="text-rotulo text-ink-faint">
              {t("puesto.factor.recuperacion")}
            </p>
            <ul className="mt-1 grid grid-cols-2 gap-1 font-mono text-dato text-ink">
              {alta.codigos_recuperacion.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </div>
          <div className="flex items-end gap-2">
            <label className="flex-1">
              <span className="block text-rotulo text-ink-faint">
                {t("puesto.factor.elCodigo")}
              </span>
              <input
                className="input-base mt-1 w-40 font-mono"
                value={codigo}
                inputMode="numeric"
                autoComplete="one-time-code"
                onChange={(e) => setCodigo(e.target.value)}
              />
            </label>
            <button
              type="button"
              className="btn-primary"
              disabled={enviando || codigo.trim().length < 6}
              onClick={() => void confirmar()}
            >
              {t("puesto.factor.confirmar")}
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-3">
          {activo ? (
            <button
              type="button"
              className="btn-secondary"
              disabled={enviando}
              onClick={() => void quitar()}
            >
              {t("puesto.factor.quitar")}
            </button>
          ) : (
            <button
              type="button"
              className="btn-primary"
              disabled={enviando}
              onClick={() => void empezar()}
            >
              {t("puesto.factor.activar")}
            </button>
          )}
        </div>
      )}

      {fallo ? (
        <div className="mt-3">
          <Fallo error={fallo} />
        </div>
      ) : null}
    </section>
  );
}

export function Puesto() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Salud | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<Salud>("/api/v1/suites/salud", { signal: control.signal })
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  if (fallo) return <Fallo error={fallo} />;
  if (!datos) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={t("puesto.titulo")}
        entradilla={t("puesto.intro")}
        icono="desk"
      />

      {!datos.medible ? (
        <Vacio
          titulo={t("puesto.sinConexiones")}
          detalle={datos.que_significa}
        />
      ) : (
        <>
          <p
            className={`mt-4 text-titulin ${datos.todo_bien ? "text-success" : "text-warning"}`}
            role="status"
          >
            {datos.que_significa}
          </p>

          {datos.paradas.length > 0 ? (
            <section className="mt-4">
              <h2 className="text-titulin font-medium text-danger">
                {t("puesto.paradas")}
              </h2>
              <ul className="mt-2 space-y-1">
                {datos.paradas.map((p) => (
                  <li key={p.conexion} className="text-dato text-ink">
                    {p.conexion} ·{" "}
                    {t("puesto.horas", { horas: p.horas_sin_sincronizar })} ·{" "}
                    <span className="text-ink-muted">{p.porque}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {/* Lo que no se ha medido no se pinta en verde: es una conexión de la
              que no se sabe nada.

              Y se dicen CUÁLES, no sólo cuántas. Las paradas salen con su
              nombre porque hay que ir a mirarlas; las que no se han medido
              también, y hasta el 26-10-2026 sólo salía el recuento: quien leía
              «1 conexión sin medir» no sabía cuál, que es lo primero que hace
              falta para arreglarlo. */}
          {datos.sin_medir.length > 0 ? (
            <>
              <p className="mt-4 text-dato text-warning">
                {t("puesto.sinMedir", { cuantas: datos.sin_medir.length })}
              </p>
              <ul className="mt-1 space-y-0.5">
                {datos.sin_medir.map((c) => (
                  <li key={c} className="text-dato text-ink-muted">
                    {c}
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          {datos.los_en_sondeo ? (
            <p className="mt-2 text-dato text-ink-muted">
              {datos.los_en_sondeo}
            </p>
          ) : null}
        </>
      )}

      {/* Siempre, tengas o no conexiones: tu segundo factor no depende de que
          el correo esté enchufado. */}
      <SegundoFactor />
    </>
  );
}
