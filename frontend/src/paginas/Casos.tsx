/**
 * Casos: bandeja, SLA con reloj y escalado (CRM-07.04.03.17).
 *
 * Dos decisiones que se ven al usarla:
 *
 * **El reloj del SLA se pinta aquí y se calcula en el servidor.** La pantalla
 * recibe el vencimiento y lo cuenta; no decide cuándo vence. Si lo decidiera,
 * dos navegadores con la hora mal darían dos incumplimientos distintos del mismo
 * caso, y el que manda es el del servidor.
 *
 * **Lo que va a incumplir se separa de lo que ya incumplió.** Son dos trabajos
 * distintos: lo primero se puede salvar y lo segundo hay que explicarlo. Una
 * bandeja que los mezcla hace que se atienda por orden de llegada, que es el
 * único orden que garantiza incumplir los dos.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { ErrorApi, llamar } from "@/lib/api";

interface Caso {
  id: string;
  numero: string;
  asunto: string;
  estado: string;
  prioridad: string;
  vence_at: string | null;
  cuenta_id: string | null;
  cola: string | null;
  escalado: boolean;
}

export function Casos() {
  const { t } = useTranslation();
  const [casos, setCasos] = useState<Caso[] | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<Caso[]>("/api/v1/casos", { signal: control.signal })
      .then((r) => setCasos(r.datos))
      .catch((e: unknown) => {
        if (e instanceof ErrorApi) setFallo(e);
      });
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!casos) return <Cargando />;

  const ahora = Date.now();
  const vencidos = casos.filter((c) => c.vence_at && Date.parse(c.vence_at) < ahora);
  const enRiesgo = casos.filter(
    (c) =>
      c.vence_at &&
      Date.parse(c.vence_at) >= ahora &&
      Date.parse(c.vence_at) - ahora < 4 * 3600_000,
  );
  const resto = casos.filter((c) => !vencidos.includes(c) && !enRiesgo.includes(c));

  return (
    <div className="flex flex-col gap-6 p-4">
      <header>
        <h1 className="text-lg font-medium text-ink">{t("casos.titulo")}</h1>
        <p className="mt-1 max-w-prose text-2xs text-ink-muted">{t("casos.entradilla")}</p>
      </header>

      <Bloque titulo={t("casos.incumplidos")} casos={vencidos} tono="danger" />
      <Bloque titulo={t("casos.enRiesgo")} casos={enRiesgo} tono="warning" />
      <Bloque titulo={t("casos.resto")} casos={resto} tono="normal" />
    </div>
  );
}

function Bloque({
  titulo,
  casos,
  tono,
}: {
  titulo: string;
  casos: Caso[];
  tono: "danger" | "warning" | "normal";
}) {
  const { t } = useTranslation();
  const color =
    tono === "danger" ? "text-danger" : tono === "warning" ? "text-warning" : "text-ink";
  return (
    <section>
      <h2 className={`text-sm font-medium ${color}`}>
        {titulo} <span className="text-ink-faint">({casos.length})</span>
      </h2>
      {casos.length === 0 ? (
        <Vacio titulo={t("casos.ninguno")} detalle="" />
      ) : (
        <ul className="mt-2 flex flex-col gap-2">
          {casos.map((c) => (
            <li
              key={c.id}
              className="flex flex-wrap items-baseline gap-2 rounded-lg border border-ink-dim/40 bg-paper-light p-3"
            >
              <span className="font-mono text-2xs text-ink-faint">{c.numero}</span>
              <span className="flex-1 text-sm text-ink">{c.asunto}</span>
              <span className="text-2xs text-ink-muted">{c.estado}</span>
              {c.escalado ? (
                <span className="rounded bg-warning/10 px-1.5 py-0.5 text-3xs uppercase text-warning">
                  {t("casos.escalado")}
                </span>
              ) : null}
              <Reloj vence={c.vence_at} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * El reloj del SLA.
 *
 * Cuenta desde el vencimiento que da el servidor. **No lo calcula**: si lo
 * calculara, dos navegadores con la hora mal darían dos incumplimientos
 * distintos del mismo caso.
 */
function Reloj({ vence }: { vence: string | null }) {
  const { t } = useTranslation();
  const [ahora, setAhora] = useState(() => Date.now());

  useEffect(() => {
    const reloj = window.setInterval(() => setAhora(Date.now()), 30_000);
    return () => window.clearInterval(reloj);
  }, []);

  if (!vence) return <span className="text-2xs text-ink-faint">{t("casos.sinSla")}</span>;
  const restan = Date.parse(vence) - ahora;
  const horas = Math.floor(Math.abs(restan) / 3600_000);
  const minutos = Math.floor((Math.abs(restan) % 3600_000) / 60_000);
  const texto = `${horas}h ${minutos}m`;
  return (
    <span className={`font-mono text-2xs ${restan < 0 ? "text-danger" : "text-ink-muted"}`}>
      {restan < 0 ? t("casos.vencidoHace", { tiempo: texto }) : t("casos.vence", { tiempo: texto })}
    </span>
  );
}
