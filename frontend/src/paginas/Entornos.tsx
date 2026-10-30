/**
 * Qué hay desplegado en cada entorno, y qué se ha tocado a mano
 * (CRM-07.02.01.01, CRM-07.02.01.03, CRM-07.02.01.04, CRM-07.02.01.06,
 * CRM-07.02.01.07).
 *
 * La configuración se promociona por paquetes: desarrollo → pruebas →
 * preproducción → producción. Todo eso existía por API y no se veía en ningún
 * sitio, así que la pregunta que nadie podía contestar era la primera que se
 * hace delante de una incidencia: **«¿qué hay puesto ahí ahora mismo?»**.
 *
 * **El drift es lo que decide.** Un entorno «limpio» y un entorno que no se ha
 * podido comparar se ven igual de bien, y significan lo contrario: por eso el
 * servidor manda `medible` y aquí un entorno sin medir no sale verde. Y
 * dentro, lo tocado a mano va separado de lo desaparecido: lo primero es un
 * cambio que el siguiente despliegue va a pisar sin avisar, lo segundo es
 * algo que estaba declarado y ya no está.
 *
 * **La huella y la referencia de Git van con el despliegue.** Sin ellas, «está
 * desplegado el paquete v7» no se puede contrastar con nada: la huella dice si
 * lo que hay es exactamente lo que se empaquetó, y la referencia dice qué
 * commit lo generó.
 *
 * **Y volver atrás se dice si se puede o no**, antes de pulsar. Un botón de
 * rollback que a veces no funciona es peor que no tenerlo, porque se cuenta
 * con él justo el día que hace falta.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";

const ENTORNOS = ["desarrollo", "pruebas", "preproduccion", "produccion"] as const;

interface Desplegado {
  entorno: string;
  hay: boolean;
  porque?: string;
  paquete?: string;
  version?: number;
  /** Dice si lo que hay es exactamente lo que se empaquetó. */
  huella?: string;
  referencia_git?: string | null;
  origen_entorno?: string | null;
  desplegado_at?: string;
  desplegado_por?: string | null;
  motivo?: string;
  se_puede_volver_atras?: boolean;
  que_significa?: string;
}

interface Drift {
  entorno: string;
  /** Un entorno «limpio» y uno sin medir se ven igual y son lo contrario. */
  medible: boolean;
  porque?: string;
  paquete?: string;
  version?: number;
  /** Cambiado a mano: el siguiente despliegue lo pisa sin avisar. */
  tocado_a_mano?: { elemento?: string; clave?: string }[];
  /** Estaba declarado y ya no está. */
  desaparecido?: { elemento?: string; clave?: string }[];
  limpio?: boolean;
  comparado?: number;
  no_comparado?: number;
  que_significa?: string;
}

export function Entornos() {
  const { t } = useTranslation();
  const [desplegado, setDesplegado] = useState<Record<string, Desplegado>>({});
  const [drift, setDrift] = useState<Record<string, Drift>>({});
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    const { signal } = control;
    setFallo(null);
    for (const entorno of ENTORNOS) {
      llamar<Desplegado>(`/api/v1/entornos/${entorno}/desplegado`, { signal })
        .then((r) => setDesplegado((x) => ({ ...x, [entorno]: r.datos })))
        .catch(salvoCancelacion(setFallo));
      llamar<Drift>(`/api/v1/entornos/${entorno}/drift`, { signal })
        .then((r) => setDrift((x) => ({ ...x, [entorno]: r.datos })))
        .catch(salvoCancelacion(() => undefined));
    }
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo && Object.keys(desplegado).length === 0) {
    return <Fallo error={fallo} reintentar={cargar} />;
  }

  return (
    <>
      <CabeceraPagina
        titulo={t("entornos.titulo")}
        icono="layers"
        entradilla={t("entornos.entradilla")}
      />

      <ul className="flex flex-col gap-3">
        {ENTORNOS.map((entorno) => {
          const d = desplegado[entorno];
          const g = drift[entorno];
          const tocado = g?.tocado_a_mano ?? [];
          const ido = g?.desaparecido ?? [];

          return (
            <li key={entorno} className="card p-4">
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="flex-1 text-sm text-ink">{entorno}</span>
                {entorno === "produccion" ? (
                  <span className="badge badge-aviso">{t("entornos.esProduccion")}</span>
                ) : null}
              </div>

              {!d ? (
                <p className="mt-2 text-2xs text-ink-muted">{t("entornos.cargando")}</p>
              ) : !d.hay ? (
                <Vacio titulo={d.porque || t("entornos.sinDesplegar")} detalle="" />
              ) : (
                <>
                  <p className="mt-2 font-mono text-2xs text-ink">
                    {t("entornos.puesto", {
                      paquete: d.paquete,
                      version: d.version,
                      desde: d.origen_entorno ?? t("entornos.sinOrigen"),
                    })}
                  </p>
                  {/* La huella y el commit: sin ellos «está el v7» no se
                      contrasta con nada. */}
                  <p className="mt-1 font-mono text-3xs text-ink-muted">
                    {t("entornos.huella", {
                      huella: (d.huella ?? "").slice(0, 12) || "—",
                      git: d.referencia_git || t("entornos.sinGit"),
                    })}
                  </p>
                  {d.motivo ? (
                    <p className="mt-1 text-3xs text-ink-faint">{d.motivo}</p>
                  ) : null}
                  {/* Si se puede volver atrás se dice ANTES de pulsar: un
                      rollback que a veces no funciona es peor que ninguno. */}
                  <p className="mt-1 text-3xs text-ink-faint">
                    {d.se_puede_volver_atras
                      ? t("entornos.sePuedeVolver")
                      : t("entornos.noSePuedeVolver")}
                  </p>
                </>
              )}

              {/* El drift, con su `medible` delante. */}
              {g ? (
                !g.medible ? (
                  <p className="mt-2 text-2xs text-warning">
                    {g.porque || t("entornos.sinMedirDrift")}
                  </p>
                ) : g.limpio ? (
                  <p className="mt-2 text-2xs text-ink-muted">
                    {t("entornos.limpio", { comparado: g.comparado ?? 0 })}
                  </p>
                ) : (
                  <div className="mt-2">
                    {tocado.length > 0 ? (
                      <p className="text-2xs text-warning">
                        {t("entornos.tocadoAMano", { cuantos: tocado.length })}
                      </p>
                    ) : null}
                    {ido.length > 0 ? (
                      <p className="mt-1 text-2xs text-danger">
                        {t("entornos.desaparecido", { cuantos: ido.length })}
                      </p>
                    ) : null}
                    {/* Lo que no se ha podido comparar se dice: un «limpio»
                        calculado sobre la mitad no es un limpio. */}
                    {(g.no_comparado ?? 0) > 0 ? (
                      <p className="mt-1 text-3xs text-ink-faint">
                        {t("entornos.noComparado", { cuantos: g.no_comparado })}
                      </p>
                    ) : null}
                  </div>
                )
              ) : null}
            </li>
          );
        })}
      </ul>
    </>
  );
}
