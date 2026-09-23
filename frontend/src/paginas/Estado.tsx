/**
 * La página de estado del tenant (CRM-00.06.01.06).

 * Enseña también los compromisos de servicio del tenant —RPO, RTO,
 * disponibilidad— junto a lo medido (CRM-07.04.03.30): un compromiso escrito en
 * un contrato que nadie compara con la realidad no lo comprueba nadie.
 *
 * La compone el gateway juntando lo que publica cada servicio sobre sus propios
 * componentes. Aquí solo se pinta: si esta pantalla dedujera el estado general
 * a partir de los componentes, habría dos definiciones de «va bien» y se
 * separarían.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";
import { CabeceraPagina } from "@/componentes/Pagina";

interface Componente {
  servicio: string;
  componente: string;
  estado: string;
  detalle?: string;
}

interface Respuesta {
  estado: string;
  consultado_at: string;
  componentes: Componente[];
}

const COLOR: Record<string, string> = {
  ok: "text-success",
  degradado: "text-warning",
  caido: "text-danger",
};

// El estado global va como insignia y no como texto de color: un párrafo en
// rojo bajo el título se lee como un aviso cualquiera, y una insignia con
// relleno se ve antes que el propio título — que es lo que hace falta cuando
// algo está caído. El color solo, además, no basta: la palabra va dentro.
const INSIGNIA: Record<string, string> = {
  ok: "badge-success",
  degradado: "badge-warning",
  caido: "badge-danger",
};

interface Compromiso {
  metrica: string;
  que_es: string;
  comprometido: number;
  unidad: string;
  medido: number | null;
  como_se_mide: string;
}

interface Compromisos {
  tier: string;
  compromisos: Compromiso[];
}

export function Estado() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Respuesta | null>(null);
  const [compromisos, setCompromisos] = useState<Compromisos | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<Respuesta>("/api/v1/estado", { signal: control.signal })
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    // Los compromisos se piden aparte y su fallo NO tumba la página: el estado
    // de los componentes es lo urgente cuando algo va mal, y perderlo porque no
    // se pudo leer un número de contrato sería el peor momento para perderlo.
    llamar<Compromisos>("/api/v1/compromisos", { signal: control.signal })
      .then((r) => setCompromisos(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, []);

  if (fallo) return <Fallo error={fallo} />;
  if (!datos) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={t("estado.titulo")}
        icono="monitor_heart"
        acciones={
          <span className={`badge ${INSIGNIA[datos.estado] ?? "badge-muted"}`}>{datos.estado}</span>
        }
      />
      <div className="mt-4 overflow-x-auto rounded-xl border border-ink-dim/60 bg-paper">
        <table className="w-full text-left text-xs">
          <thead className="border-b border-ink-dim/30 bg-paper-light">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium text-ink-muted">
                {t("estado.servicio")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium text-ink-muted">
                {t("estado.componente")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium text-ink-muted">
                {t("estado.situacion")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium text-ink-muted">
                {t("estado.detalle")}
              </th>
            </tr>
          </thead>
          <tbody>
            {datos.componentes.map((c) => (
              <tr key={`${c.servicio}:${c.componente}`} className="border-b border-ink-dim/30 last:border-0">
                <td className="px-3 py-2 text-ink-muted">{c.servicio}</td>
                <td className="px-3 py-2 text-ink">{c.componente}</td>
                <td className={`px-3 py-2 ${COLOR[c.estado] ?? "text-ink-muted"}`}>{c.estado}</td>
                <td className="px-3 py-2 text-2xs text-ink-faint">{c.detalle ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {compromisos ? (
        <>
          <h2 className="mt-8 text-sm font-medium text-ink">
            {t("estado.compromisos")} · {compromisos.tier}
          </h2>
          <p className="mt-1 text-2xs text-ink-faint">{t("estado.compromisosIntro")}</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {compromisos.compromisos.map((c) => (
              <div key={c.metrica} className="rounded-xl border border-ink-dim/60 bg-paper p-4">
                <p className="text-xs text-ink">{c.metrica}</p>
                <p className="mt-1 text-3xs text-ink-faint">{c.que_es}</p>
                <p className="mt-3 text-2xs text-ink-muted">
                  {t("estado.comprometido")}:{" "}
                  <span className="text-ink">
                    {c.comprometido} {c.unidad}
                  </span>
                </p>
                <p className="text-2xs text-ink-muted">
                  {t("estado.medido")}:{" "}
                  {/* Lo que no se puede medir se dice. Un cero aquí se leería
                      como «se cumple», que es la lectura contraria a la real. */}
                  {c.medido === null ? (
                    <span className="text-warning">{t("estado.noSeMide")}</span>
                  ) : (
                    <span className={c.medido > c.comprometido ? "text-danger" : "text-success"}>
                      {c.medido} {c.unidad}
                    </span>
                  )}
                </p>
                <p className="mt-2 text-3xs text-ink-faint">{c.como_se_mide}</p>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </>
  );
}
