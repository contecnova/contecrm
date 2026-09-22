/**
 * Consola de agente: varios canales en una sola cola (CRM-07.04.03.18).
 *
 * El punto de la omnicanalidad no es tener cinco bandejas bonitas: es **una sola
 * cola**. Con una bandeja por canal, lo que pasa es que el correo se mira dos
 * veces al día y el chat todo el rato, y quien escribe por correo espera el
 * doble sin que nadie lo haya decidido.
 *
 * Por eso aquí el canal es una etiqueta, no una pestaña.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { ErrorApi, llamar } from "@/lib/api";

interface Conversacion {
  conversacion_id: string;
  canal: string;
  asunto: string | null;
  estado: string;
  ultimo_mensaje_at: string | null;
}

interface Caso {
  caso_id: string;
  codigo: string;
  asunto: string;
  prioridad: string;
  estado: string;
  minutos_restantes: number | null;
}

interface Consola {
  agente: { presencia: string };
  mis_casos: Caso[];
  mis_conversaciones: Conversacion[];
}

export function ConsolaAgente() {
  const { t } = useTranslation();
  const [consola, setConsola] = useState<Consola | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);

  // Una sola llamada y no dos: la propia API lo resuelve así a propósito, porque
  // una consola que abre seis peticiones tarda lo que tarde la más lenta y el
  // agente lo ve como un producto lento aunque cinco vayan rápido.
  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<Consola>("/api/v1/consola-agente", { signal: control.signal })
      .then((r) => setConsola(r.datos))
      .catch((e: unknown) => {
        if (e instanceof ErrorApi) setFallo(e);
      });
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!consola) return <Cargando />;

  // Casos y conversaciones en UNA cola. El punto de la omnicanalidad no es tener
  // dos listas: es que lo que lleva más esperando se atienda antes, venga por
  // donde venga.
  const cola: Array<{
    clave: string;
    canal: string;
    asunto: string;
    estado: string;
    urgencia: number;
    nota: string | null;
  }> = [
    ...consola.mis_casos.map((c) => ({
      clave: c.caso_id,
      canal: "caso",
      asunto: `${c.codigo} · ${c.asunto}`,
      estado: c.estado,
      urgencia: c.minutos_restantes ?? Number.MAX_SAFE_INTEGER,
      nota: c.minutos_restantes === null ? null : `${c.minutos_restantes} min`,
    })),
    ...consola.mis_conversaciones.map((c) => ({
      clave: c.conversacion_id,
      canal: c.canal,
      asunto: c.asunto ?? "",
      estado: c.estado,
      urgencia: Number.MAX_SAFE_INTEGER - 1,
      nota: c.ultimo_mensaje_at ? new Date(c.ultimo_mensaje_at).toLocaleString() : null,
    })),
  ].sort((a, b) => a.urgencia - b.urgencia);

  return (
    <div className="flex flex-col gap-4 p-4">
      <header>
        <h1 className="text-lg font-medium text-ink">{t("consolaAgente.titulo")}</h1>
        <p className="mt-1 max-w-prose text-2xs text-ink-muted">
          {t("consolaAgente.entradilla")}
        </p>
      </header>

      {cola.length === 0 ? (
        <Vacio titulo={t("consolaAgente.vacia")} detalle={t("consolaAgente.vaciaDetalle")} />
      ) : (
        <ul className="flex flex-col gap-2">
          {cola.map((c) => (
            <li
              key={c.clave}
              className="flex flex-wrap items-baseline gap-2 rounded-lg border border-ink-dim/40 bg-paper-light p-3"
            >
              {/* El canal es una etiqueta y no una pestaña: con una bandeja por
                  canal, el correo se mira dos veces al día y el chat todo el
                  rato, y quien escribe por correo espera el doble. */}
              <span className="rounded bg-accent/10 px-1.5 py-0.5 text-3xs uppercase text-accent">
                {c.canal}
              </span>
              <span className="flex-1 text-sm text-ink">
                {c.asunto || t("consolaAgente.sinAsunto")}
              </span>
              <span className="text-2xs text-ink-muted">{c.estado}</span>
              {/* Lo que ordena la cola es la urgencia, no la hora de llegada. */}
              {c.nota ? (
                <span className="font-mono text-2xs text-ink-muted">{c.nota}</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
