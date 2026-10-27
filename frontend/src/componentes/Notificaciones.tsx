/**
 * La bandeja de avisos, donde se mira: en la barra (CRM-06.02.01.02).
 *
 * **Estaba todo construido menos la puerta.** El servidor guarda las
 * notificaciones, las agrupa, respeta el horario de silencio y las entrega por
 * los canales que cada uno elige — y en el producto no había forma de verlas.
 * Un aviso que sólo existe en la base de datos no ha avisado a nadie.
 *
 * Tres decisiones, y las tres salen del mismo sitio: esto se mira de reojo,
 * quince veces al día.
 *
 * **El número sin leer se pide al abrir, no se consulta en bucle.** Un sondeo
 * cada pocos segundos multiplica las peticiones por el número de pestañas
 * abiertas y por el número de personas, para enterarse un minuto antes de algo
 * que no corre prisa. Se refresca al abrir el panel y al marcar como leído,
 * que es cuando el número cambia de verdad.
 *
 * **Cada aviso lleva a su registro.** Un aviso que dice «la oportunidad X ha
 * cambiado» y no deja ir a la oportunidad obliga a buscarla a mano, y entonces
 * se dejan de leer.
 *
 * **Marcar como leído es explícito.** Marcar al abrir el panel haría
 * desaparecer lo que no ha dado tiempo a leer, que es la forma más rápida de
 * perder un aviso para siempre.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Icono } from "@/componentes/Icono";
import { ErrorApi, filas, llamar } from "@/lib/api";

interface Aviso {
  id: string;
  tipo: string;
  titulo: string;
  cuerpo: string | null;
  objeto_tipo: string | null;
  objeto_id: string | null;
  prioridad: string;
  leida_at: string | null;
  created_at: string;
}

/** A qué módulo pertenece cada tipo de objeto que puede avisar. */
const MODULO_DE: Record<string, string> = {
  cuenta: "cuentas",
  contacto: "cuentas",
  oportunidad: "oportunidades",
  lead: "leads",
  caso: "casos",
  actividad: "actividades",
};

export function Notificaciones() {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  const [avisos, setAvisos] = useState<Aviso[] | null>(null);
  const [fallo, setFallo] = useState<string>("");
  const panel = useRef<HTMLDivElement>(null);

  const cargar = useCallback(() => {
    llamar<unknown>("/api/v1/notificaciones?limite=30")
      .then((r) => setAvisos(filas<Aviso>(r.datos)))
      .catch((e: unknown) => {
        // Un fallo aquí no puede llevarse la barra por delante: se dice en el
        // panel y el resto de la aplicación sigue funcionando.
        setFallo(e instanceof ErrorApi ? e.message : String(e));
        setAvisos([]);
      });
  }, []);

  useEffect(() => {
    if (abierto) cargar();
  }, [abierto, cargar]);

  // Se cierra al pulsar fuera y con Escape, como el menú de usuario.
  useEffect(() => {
    if (!abierto) return;
    const fuera = (e: MouseEvent) => {
      if (panel.current && !panel.current.contains(e.target as Node)) setAbierto(false);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setAbierto(false);
    };
    document.addEventListener("mousedown", fuera);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", fuera);
      document.removeEventListener("keydown", escape);
    };
  }, [abierto]);

  const sinLeer = (avisos ?? []).filter((a) => a.leida_at === null).length;

  async function marcarTodas() {
    try {
      await llamar("/api/v1/notificaciones/leidas", { metodo: "POST", cuerpo: {} });
      cargar();
    } catch (e: unknown) {
      setFallo(e instanceof ErrorApi ? e.message : String(e));
    }
  }

  return (
    <div className="relative" ref={panel}>
      <button
        type="button"
        onClick={() => setAbierto((v) => !v)}
        className="btn-icon relative text-ink-muted hover:bg-paper-light hover:text-ink"
        aria-label={t("avisos.abrir")}
        aria-haspopup="dialog"
        aria-expanded={abierto}
        title={t("avisos.abrir")}
      >
        <Icono nombre="notifications" />
        {sinLeer > 0 ? (
          <span className="absolute right-0 top-0 min-w-4 rounded-full bg-danger px-1 text-center text-3xs font-bold leading-4 text-paper">
            {sinLeer > 9 ? "9+" : sinLeer}
          </span>
        ) : null}
      </button>

      {abierto ? (
        <div
          role="dialog"
          aria-label={t("avisos.titulo")}
          className="absolute right-0 z-popover mt-2 w-80 animate-fade-in rounded-xl border border-ink-dim/60 bg-paper shadow-elevation-3"
        >
          <div className="flex items-center justify-between border-b border-ink-dim/30 px-3 py-2">
            <p className="text-xs font-semibold text-ink">{t("avisos.titulo")}</p>
            {sinLeer > 0 ? (
              <button type="button" className="btn-link text-3xs" onClick={() => void marcarTodas()}>
                {t("avisos.marcarTodas")}
              </button>
            ) : null}
          </div>

          {/* Lo que pasa al marcar se anuncia: quien no ve la pantalla pulsa y
              no se entera de que el número ya está a cero. */}
          <div role="status" aria-live="polite" className="sr-only">
            {t("avisos.sinLeer", { count: sinLeer })}
          </div>

          {fallo ? (
            <p className="px-3 py-4 text-2xs text-danger">{fallo}</p>
          ) : avisos === null ? (
            <p className="px-3 py-4 text-2xs text-ink-faint">{t("avisos.cargando")}</p>
          ) : avisos.length === 0 ? (
            <p className="px-3 py-6 text-center text-2xs text-ink-faint">{t("avisos.vacio")}</p>
          ) : (
            <ul className="max-h-96 divide-y divide-ink-dim/20 overflow-y-auto">
              {avisos.map((a) => {
                const modulo = a.objeto_tipo ? MODULO_DE[a.objeto_tipo] : undefined;
                const contenido = (
                  <>
                    <div className="flex items-baseline gap-2">
                      {a.leida_at === null ? (
                        <span
                          className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
                          aria-hidden="true"
                        />
                      ) : null}
                      <span className="min-w-0 flex-1 text-2xs text-ink">{a.titulo}</span>
                      <span className="shrink-0 font-mono text-3xs text-ink-faint">
                        {a.created_at.slice(5, 16).replace("T", " ")}
                      </span>
                    </div>
                    {a.cuerpo ? (
                      <p className="mt-0.5 truncate pl-3.5 text-3xs text-ink-muted">
                        {a.cuerpo}
                      </p>
                    ) : null}
                  </>
                );
                return (
                  <li key={a.id}>
                    {modulo && a.objeto_id ? (
                      <Link
                        to={`/m/${modulo}/${a.objeto_tipo}/${a.objeto_id}`}
                        onClick={() => setAbierto(false)}
                        className="block px-3 py-2 hover:bg-paper-light"
                      >
                        {contenido}
                      </Link>
                    ) : (
                      // Sin registro al que ir, el aviso se lee y no finge ser
                      // un enlace: un enlace que no lleva a nada se pulsa una
                      // vez y se desconfía de todos los demás.
                      <div className="px-3 py-2">{contenido}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
