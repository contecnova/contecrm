/**
 * Coste y capacidad: el margen de la oferta y qué se puede comprometer
 * (CRM-07.04.03.32).
 *
 * Esta pantalla enseña la mitad de la oferta que casi ningún CRM enseña: **lo que
 * cuesta**. Aprobar por porcentaje de descuento es aprobar a ciegas, y esto
 * existe para que la conversación sea sobre el margen.
 *
 * Tres decisiones de cómo se pinta:
 *
 * **Un margen desconocido no se pinta como cero.** Si faltan costes, se dice
 * cuántas líneas no se pueden medir en vez de enseñar una media que parece el
 * margen de la oferta — que es la forma elegante de mentir en una hoja de
 * aprobación.
 *
 * **Lo que está en pérdidas se ve a la primera.** No en una columna al final: en
 * rojo y arriba.
 *
 * **Y la capacidad enseña lo que hay en ofertas abiertas**, que todavía no está
 * comprometido pero tampoco cabría si se ganaran todas.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { llamar } from "@/lib/api";
import { CabeceraPagina } from "@/componentes/Pagina";

interface Margen {
  completo: boolean;
  lineas_sin_coste: string[];
  venta_total: string;
  coste: string;
  margen: string;
  margen_pct: string;
  necesita_aprobacion: boolean;
  porque: string;
  aviso: string;
}

interface Capacidad {
  contratada: string;
  comprometida: string;
  libre: string;
  en_ofertas_abiertas: string;
  libre_si_se_ganan_todas: string;
  sobrevendida: boolean;
  aviso: string;
}

export function Coste() {
  const { t } = useTranslation();
  const [lineas, setLineas] = useState(
    '[{"referencia":"L1","precio_venta":1000,"coste":700,"cantidad":1}]',
  );
  const [margen, setMargen] = useState<Margen | null>(null);
  const [capacidad, setCapacidad] = useState<Capacidad | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const calcular = async () => {
    setFallo(null);
    try {
      const r = await llamar<Margen>("/api/v1/coste/margen", {
        metodo: "POST",
        cuerpo: { lineas: JSON.parse(lineas) },
      });
      setMargen(r.datos);
    } catch (e) {
      setFallo(e);
    }
  };

  const mirarCapacidad = async () => {
    setFallo(null);
    try {
      const r = await llamar<Capacidad>(
        "/api/v1/coste/capacidad?contratada=1000&comprometida=800&en_ofertas=300",
      );
      setCapacidad(r.datos);
    } catch (e) {
      setFallo(e);
    }
  };

  return (
    <>
      <CabeceraPagina
        titulo={t("coste.titulo")}
        entradilla={t("coste.intro")}
        icono="payments"
      />

      <label className="mt-4 block text-2xs text-ink-muted" htmlFor="coste-lineas">
        {t("coste.lineas")}
      </label>
      <textarea
        id="coste-lineas"
        rows={4}
        className="mt-1 w-full rounded-lg border border-ink-dim/60 bg-paper px-3 py-2 font-mono text-2xs text-ink"
        value={lineas}
        onChange={(e) => setLineas(e.target.value)}
      />
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          onClick={calcular}
          className="rounded-lg bg-accent px-3 py-1.5 text-2xs text-paper"
        >
          {t("coste.calcular")}
        </button>
        <button
          type="button"
          onClick={mirarCapacidad}
          className="rounded-lg border border-ink-dim/60 px-3 py-1.5 text-2xs text-ink"
        >
          {t("coste.verCapacidad")}
        </button>
      </div>

      {fallo ? <Fallo error={fallo} /> : null}

      {margen ? (
        <section className="mt-6 rounded-xl border border-ink-dim/60 bg-paper p-4" role="status">
          <h2 className="text-xs font-medium text-ink">{t("coste.margen")}</h2>
          <p
            className={`mt-2 text-lg ${Number(margen.margen) < 0 ? "text-danger" : "text-ink"}`}
          >
            {margen.margen} ({margen.margen_pct} %)
          </p>
          <p className="mt-1 text-2xs text-ink-muted">{margen.porque}</p>
          {margen.necesita_aprobacion ? (
            <p className="mt-2 text-2xs text-warning">{t("coste.necesitaAprobacion")}</p>
          ) : null}
          {/* Un margen incompleto no se presenta como el margen: se dice qué
              falta por medir. */}
          {!margen.completo ? (
            <p className="mt-2 text-2xs text-warning">{margen.aviso}</p>
          ) : null}
        </section>
      ) : null}

      {capacidad ? (
        <section className="mt-4 rounded-xl border border-ink-dim/60 bg-paper p-4">
          <h2 className="text-xs font-medium text-ink">{t("coste.capacidad")}</h2>
          <dl className="mt-2 grid grid-cols-2 gap-y-1 text-2xs">
            <dt className="text-ink-muted">{t("coste.libre")}</dt>
            <dd className="text-ink">{capacidad.libre}</dd>
            <dt className="text-ink-muted">{t("coste.enOfertas")}</dt>
            <dd className="text-ink">{capacidad.en_ofertas_abiertas}</dd>
            <dt className="text-ink-muted">{t("coste.siSeGananTodas")}</dt>
            <dd className={Number(capacidad.libre_si_se_ganan_todas) < 0 ? "text-warning" : "text-ink"}>
              {capacidad.libre_si_se_ganan_todas}
            </dd>
          </dl>
          {capacidad.aviso ? (
            <p
              className={`mt-2 text-2xs ${capacidad.sobrevendida ? "text-danger" : "text-warning"}`}
            >
              {capacidad.aviso}
            </p>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
