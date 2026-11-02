/**
 * Una liquidación de comisión, euro a euro (CRM-03.02.03.02, CRM-03.02.03.03).
 *
 * El listado enseñaba el total y el estado. Y delante de una liquidación la
 * pregunta no es cuánto: es **por qué ese número y no otro**. Un comercial que
 * no puede desglosar su comisión no se la cree, y la discusión acaba en una
 * hoja de cálculo paralela que nadie concilia.
 *
 * Por eso el panel que manda es el de las líneas **con su explicación**: cada
 * euro dice de dónde sale, sobre qué base y a qué porcentaje. El servidor lo
 * guarda así desde el primer día y no lo enseñaba nadie.
 *
 * **Lo recortado por el tope va arriba y en color.** Una liquidación con tope
 * aplicado parece simplemente más baja, y quien la cobra no tiene forma de
 * saber que le han quitado algo: es la diferencia entre «he vendido menos» y
 * «he llegado al techo del plan», que son dos conversaciones distintas.
 *
 * **Y las reversiones se marcan.** Una línea negativa sin decir de qué
 * liquidación viene se lee como un error de cálculo.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { DatosClave } from "@/componentes/DatosClave";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";
import { llamar, salvoCancelacion } from "@/lib/api";
import { importe as comoImporte } from "@/lib/formato";

interface Linea {
  id: string;
  origen: string;
  origen_id: string | null;
  concepto: string;
  base: string;
  porcentaje: string;
  importe: string;
  /** De dónde sale este euro. Es lo que hace la comisión discutible. */
  explicacion: string;
  reversion_de: string | null;
}

interface Disputa {
  id: string;
  estado: string;
  motivo: string;
  resolucion: string | null;
  importe_reclamado: string | null;
}

interface Detalle {
  id: string;
  estado: string;
  desde: string;
  hasta: string;
  total: string;
  moneda: string;
  recortado_por_tope: string;
  plan_aplicado: Record<string, unknown> | null;
  pago_referencia: string | null;
  pagada_at: string | null;
  lineas: Linea[];
  disputas: Disputa[];
}

export function Liquidacion() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const modulo = moduloDe("canal");
  const recurso = modulo ? recursoDe(modulo, "liquidacion") : undefined;
  const [detalle, setDetalle] = useState<Detalle | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Detalle>(`/api/v1/liquidaciones/${id}`, { signal: control.signal })
      .then((r) => setDetalle(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  if (fallo && !detalle) return <Fallo error={fallo} reintentar={cargar} />;
  if (!detalle) return <Cargando />;

  const recortado = Number(detalle.recortado_por_tope) > 0;

  return (
    <>
      <DatosClave
        // Con su recurso: la liquidación SÍ está en el catálogo, así que el
        // panel saca de ahí sus datos clave —estado, periodo, referencia de
        // pago— igual que el listado saca sus columnas.
        recurso={recurso}
        tipo="liquidacion"
        nombre={comoImporte(detalle.total, detalle.moneda)}
        fila={detalle as unknown as Record<string, unknown>}
        volverA={{ a: "/m/canal", titulo: modulo?.titulo ?? "", id }}
      />

      {/* Lo recortado por el tope, arriba. Sin esto, una liquidación con techo
          aplicado parece simplemente más baja, y quien la cobra no sabe que le
          han quitado algo. */}
      {recortado ? (
        <p className="card mb-4 border-warning/40 p-3 text-dato text-warning">
          {t("liquidacion.recortado", {
            cuanto: comoImporte(detalle.recortado_por_tope, detalle.moneda),
          })}
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <LasLineas lineas={detalle.lineas} moneda={detalle.moneda} />
        <LasDisputas disputas={detalle.disputas} moneda={detalle.moneda} />
      </div>
    </>
  );
}

/** Cada euro con su porqué. */
function LasLineas({ lineas, moneda }: { lineas: Linea[]; moneda: string }) {
  const { t } = useTranslation();
  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("liquidacion.lineas")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("liquidacion.lineasAyuda")}
      </p>
      {lineas.length === 0 ? (
        <Vacio titulo={t("liquidacion.sinLineas")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {lineas.map((l) => (
            <li key={l.id} className="py-1.5">
              <div className="flex flex-wrap items-baseline gap-x-3 text-dato">
                <span className="font-medium text-ink">{l.concepto}</span>
                <span className="text-ink-muted">
                  {comoImporte(l.importe, moneda)}
                </span>
                <span className="text-rotulo text-ink-faint">
                  {t("liquidacion.baseYPct", {
                    base: comoImporte(l.base, moneda),
                    pct: l.porcentaje,
                  })}
                </span>
                <span className="chip-dato">{l.origen}</span>
                {/* Una línea negativa sin decir de qué liquidación viene se lee
                    como un error de cálculo. */}
                {l.reversion_de ? (
                  <span className="chip-dato chip-dato--no">
                    {t("liquidacion.reversion")}
                  </span>
                ) : null}
              </div>
              <p className="text-rotulo text-ink-muted">{l.explicacion}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Las disputas, con su resolución.
 *
 * Una disputa abierta y una resuelta se ven igual si sólo sale el motivo, y la
 * resolución es lo que cierra la conversación: sin ella, la misma reclamación
 * vuelve el trimestre siguiente.
 */
function LasDisputas({
  disputas,
  moneda,
}: {
  disputas: Disputa[];
  moneda: string;
}) {
  const { t } = useTranslation();
  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("liquidacion.disputas")}</h2>
      {disputas.length === 0 ? (
        <Vacio titulo={t("liquidacion.sinDisputas")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {disputas.map((d) => (
            <li key={d.id} className="py-1.5">
              <div className="flex flex-wrap items-baseline gap-x-3 text-dato">
                <span className="chip-dato">{d.estado}</span>
                {d.importe_reclamado ? (
                  <span className="text-ink-muted">
                    {comoImporte(d.importe_reclamado, moneda)}
                  </span>
                ) : null}
              </div>
              <p className="text-rotulo text-ink">{d.motivo}</p>
              {d.resolucion ? (
                <p className="text-rotulo text-ink-muted">{d.resolucion}</p>
              ) : (
                <p className="text-rotulo text-warning">
                  {t("liquidacion.sinResolver")}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
