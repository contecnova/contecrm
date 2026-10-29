/**
 * Por qué este lead tiene esta puntuación
 * (CRM-02.01.02.03, CRM-02.01.02.04, CRM-02.01.02.05, CRM-02.01.02.06).
 *
 * «Este lead tiene 87» no le sirve a nadie. Lo que hace que un comercial llame
 * es saber que descargó el comparativo de precios y entró dos veces en la
 * página de contratación. Sin el porqué, el número es un adorno.
 *
 * **Los dos ejes van separados y nunca sumados.** El encaje dice si es el
 * cliente que buscamos y el interés dice cuánto caso nos está haciendo, y
 * sumarlos borra la diferencia que decide a quién se llama: un director de
 * compras de una empresa objetivo que lleva dos meses callado y un estudiante
 * muy activo pueden dar el mismo total, y no se hace lo mismo con los dos.
 *
 * **El decaimiento se enseña aparte.** Sin él, quien mira no entiende por qué
 * un lead que hizo muchas cosas tiene poco interés y concluye que el scoring
 * está roto. Sólo decae el interés: el encaje sale de quién es, no de lo que
 * hace.
 *
 * **Y los umbrales, al lado del número.** Se guardaban en el modelo y no los
 * devolvía ninguna ruta, así que «es MQL» no se podía contrastar con nada y
 * «qué le falta para SQL» no se podía contestar. Lo que le falta de interés se
 * gana con actividad; lo que le falta de encaje, no — y eso cambia qué se hace
 * con el lead.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";

interface Factor {
  eje: string;
  regla: string;
  puntos: number;
}

interface Umbral {
  interes: number | null;
  encaje: number | null;
}

interface LeFalta {
  hasta: string;
  alcanzable: boolean;
  interes?: number;
  encaje?: number;
  que_significa: string;
}

interface Explicacion {
  lead_id: string;
  modelo: string;
  interes: number;
  encaje: number;
  grado: string | null;
  calificacion: string;
  por_interes: Factor[];
  por_encaje: Factor[];
  /** Puntos de interés perdidos por inactividad. Nunca de encaje. */
  perdido_por_inactividad: number;
  ultima_actividad_at: string | null;
  calculado_at: string;
  umbrales: { mql: Umbral; sql: Umbral } | null;
  grados: { desde?: number; grado?: string }[];
  decaimiento?: {
    puntos: number;
    cada_dias: number;
    interes_minimo: number;
    solo_afecta_a: string;
  };
  le_falta: LeFalta | null;
  porque_no_se_sabe?: string;
  aviso: string;
}

function Eje({
  titulo,
  valor,
  umbral,
  factores,
}: {
  titulo: string;
  valor: number;
  umbral: number | null;
  factores: Factor[];
}) {
  const { t } = useTranslation();
  return (
    <section className="card p-4">
      <h2 className="text-sm font-medium text-ink">{titulo}</h2>
      <p className="mt-1 font-mono text-lg text-ink">{valor}</p>
      {/* El umbral pegado al número: sin él, «62» no dice si falta mucho. */}
      <p className="mt-1 text-2xs text-ink-muted">
        {umbral === null
          ? t("puntuacion.sinUmbral")
          : t("puntuacion.umbralEs", { umbral })}
      </p>
      {factores.length === 0 ? (
        <Vacio titulo={t("puntuacion.sinFactores")} detalle="" />
      ) : (
        <ul className="mt-3 flex flex-col gap-1">
          {factores.map((f, i) => (
            <li key={`${f.regla}-${i}`} className="flex items-baseline gap-2">
              <span className="flex-1 text-2xs text-ink">{f.regla}</span>
              <span className="font-mono text-2xs text-ink-muted">
                {f.puntos > 0 ? `+${f.puntos}` : f.puntos}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function PuntuacionDeLead() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [explicacion, setExplicacion] = useState<Explicacion | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Explicacion>(`/api/v1/puntuacion/leads/${id}`, { signal: control.signal })
      .then((r) => setExplicacion(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  if (fallo && !explicacion) return <Fallo error={fallo} reintentar={cargar} />;
  if (!explicacion) return <Cargando />;

  const e = explicacion;
  const grados = e.grados ?? [];
  const tramo = grados.find((g) => g.grado === e.grado);

  return (
    <>
      <CabeceraPagina
        titulo={t("puntuacion.titulo")}
        icono="target"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            <span className="chip-dato">{e.calificacion}</span>
            {/* El grado va con su tramo: una letra sola no dice desde qué
                encaje se gana, y entonces no se puede discutir. */}
            {e.grado ? (
              <span className="badge badge-muted">
                {tramo?.desde !== undefined
                  ? t("puntuacion.gradoDesde", { grado: e.grado, desde: tramo.desde })
                  : e.grado}
              </span>
            ) : null}
            <span className="text-2xs text-ink-muted">{e.modelo}</span>
          </span>
        }
      />

      {e.aviso ? (
        <p className="card mb-3 border-warning/40 p-3 text-2xs text-warning">{e.aviso}</p>
      ) : null}
      {e.porque_no_se_sabe ? (
        <p className="card mb-3 p-3 text-2xs text-ink-muted">{e.porque_no_se_sabe}</p>
      ) : null}

      {/* Qué le falta para el siguiente escalón: es la única pregunta que se
          acciona. «87» no se acciona; «le faltan 7 de interés» sí. */}
      {e.le_falta ? (
        <p
          className={
            e.le_falta.alcanzable
              ? "card mb-4 p-3 text-2xs text-ink"
              : "card mb-4 border-warning/40 p-3 text-2xs text-warning"
          }
        >
          {e.le_falta.que_significa}
        </p>
      ) : (
        <p className="card mb-4 p-3 text-2xs text-ink-muted">{t("puntuacion.yaEsSql")}</p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Eje
          titulo={t("puntuacion.interes")}
          valor={e.interes}
          umbral={e.umbrales?.[e.calificacion === "sql" ? "sql" : "mql"].interes ?? null}
          factores={e.por_interes ?? []}
        />
        <Eje
          titulo={t("puntuacion.encaje")}
          valor={e.encaje}
          umbral={e.umbrales?.[e.calificacion === "sql" ? "sql" : "mql"].encaje ?? null}
          factores={e.por_encaje ?? []}
        />

        <section className="card p-4 lg:col-span-2">
          <h2 className="text-sm font-medium text-ink">{t("puntuacion.inactividad")}</h2>
          {/* Aparte y con su nombre: sin esto, un lead que hizo muchas cosas y
              tiene poco interés parece un scoring roto. */}
          {e.perdido_por_inactividad > 0 ? (
            <p className="mt-2 text-2xs text-ink">
              {t("puntuacion.perdidos", { puntos: e.perdido_por_inactividad })}
            </p>
          ) : (
            <p className="mt-2 text-2xs text-ink-muted">{t("puntuacion.sinDecaer")}</p>
          )}
          {e.decaimiento ? (
            <p className="mt-1 text-3xs text-ink-faint">
              {t("puntuacion.reglaDecaimiento", {
                puntos: e.decaimiento.puntos,
                dias: e.decaimiento.cada_dias,
                minimo: e.decaimiento.interes_minimo,
              })}
            </p>
          ) : null}
          <p className="mt-1 text-3xs text-ink-faint">
            {e.ultima_actividad_at
              ? t("puntuacion.ultimaActividad", {
                  fecha: new Date(e.ultima_actividad_at).toLocaleDateString(),
                })
              : t("puntuacion.sinActividad")}
          </p>
        </section>

        {grados.length > 0 ? (
          <section className="card p-4 lg:col-span-2">
            <h2 className="text-sm font-medium text-ink">{t("puntuacion.tramos")}</h2>
            <p className="mt-1 text-3xs text-ink-faint">{t("puntuacion.porqueTramos")}</p>
            <ul className="mt-2 flex flex-wrap gap-2">
              {grados.map((g, i) => (
                <li
                  key={`${g.grado}-${i}`}
                  className={
                    g.grado === e.grado
                      ? "badge badge-muted font-mono"
                      : "chip-dato font-mono"
                  }
                >
                  {t("puntuacion.tramo", { grado: g.grado ?? "—", desde: g.desde ?? 0 })}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </>
  );
}
