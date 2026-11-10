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
 *
 * **Los datos los pone quien pregunta, y la pantalla no trae ninguno.** Es una
 * calculadora: el servidor no guarda ni la oferta ni la capacidad que mide.
 * Hasta el 05-11-2026 «Ver capacidad» preguntaba SIEMPRE con 1.000, 800 y 300
 * escritos en el código, y las líneas venían rellenas con un ejemplo: pulsar
 * sin tocar nada daba un margen y una capacidad de nadie, con aspecto de
 * respuesta.
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

interface FechaPrometible {
  se_puede_prometer: boolean;
  fecha?: string;
  dias_del_proveedor?: number;
  dias_propios?: number;
  porque: string;
  que_hacer?: string;
}

export function Coste() {
  const { t } = useTranslation();
  const [lineas, setLineas] = useState("");
  const [contratada, setContratada] = useState("");
  const [comprometida, setComprometida] = useState("");
  const [enOfertas, setEnOfertas] = useState("");
  const [margen, setMargen] = useState<Margen | null>(null);
  const [capacidad, setCapacidad] = useState<Capacidad | null>(null);
  const [plazo, setPlazo] = useState("");
  const [diasPropios, setDiasPropios] = useState("");
  const [fecha, setFecha] = useState<FechaPrometible | null>(null);
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
      const consulta = new URLSearchParams({
        contratada,
        comprometida,
        en_ofertas: enOfertas || "0",
      });
      const r = await llamar<Capacidad>(`/api/v1/coste/capacidad?${consulta}`);
      setCapacidad(r.datos);
    } catch (e) {
      setFallo(e);
    }
  };

  // La fecha que se le puede dar al cliente. Sin plazo del
  // proveedor se pregunta igual: la respuesta es «no se puede prometer», que
  // es justo lo que hay que saber antes de mandar la oferta. Los días propios
  // vacíos no se mandan: el servidor dice cuántos ha contado.
  const mirarFecha = async () => {
    setFallo(null);
    try {
      const consulta = new URLSearchParams();
      if (plazo.trim()) consulta.set("plazo_proveedor_dias", plazo.trim());
      if (diasPropios.trim()) consulta.set("dias_propios", diasPropios.trim());
      const r = await llamar<FechaPrometible>(
        `/api/v1/coste/fecha-prometible?${consulta}`,
      );
      setFecha(r.datos);
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

      <label
        className="mt-4 block text-dato text-ink-muted"
        htmlFor="coste-lineas"
      >
        {t("coste.lineas")}
      </label>
      <textarea
        id="coste-lineas"
        rows={4}
        className="mt-1 w-full rounded-lg border border-ink-dim/60 bg-paper px-3 py-2 font-mono text-dato text-ink"
        value={lineas}
        placeholder='[{"referencia":"L1","precio_venta":1000,"coste":700,"cantidad":1}]'
        onChange={(e) => setLineas(e.target.value)}
      />
      <div className="mt-2">
        <button
          type="button"
          onClick={calcular}
          disabled={!lineas.trim()}
          className="btn-primary"
        >
          {t("coste.calcular")}
        </button>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        {(
          [
            ["contratada", contratada, setContratada],
            ["comprometida", comprometida, setComprometida],
            ["enOfertasDato", enOfertas, setEnOfertas],
          ] as const
        ).map(([clave, valor, poner]) => (
          <label key={clave} className="block text-dato text-ink-muted">
            {t(`coste.${clave}`)}
            <input
              type="number"
              min={0}
              value={valor}
              onChange={(e) => poner(e.target.value)}
              className="mt-1 w-full rounded-lg border border-ink-dim/60 bg-paper px-3 py-1.5 text-dato text-ink"
            />
          </label>
        ))}
      </div>
      <div className="mt-2">
        <button
          type="button"
          onClick={mirarCapacidad}
          disabled={!contratada || !comprometida}
          className="btn-secondary"
        >
          {t("coste.verCapacidad")}
        </button>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        <label className="block text-dato text-ink-muted">
          {t("coste.plazoProveedor")}
          <input
            type="number"
            min={0}
            value={plazo}
            onChange={(e) => setPlazo(e.target.value)}
            className="mt-1 w-full rounded-lg border border-ink-dim/60 bg-paper px-3 py-1.5 text-dato text-ink"
          />
        </label>
        <label className="block text-dato text-ink-muted">
          {t("coste.diasPropios")}
          <input
            type="number"
            min={0}
            value={diasPropios}
            onChange={(e) => setDiasPropios(e.target.value)}
            className="mt-1 w-full rounded-lg border border-ink-dim/60 bg-paper px-3 py-1.5 text-dato text-ink"
          />
        </label>
      </div>
      <div className="mt-2">
        <button type="button" onClick={mirarFecha} className="btn-secondary">
          {t("coste.verFecha")}
        </button>
      </div>

      {fallo ? <Fallo error={fallo} /> : null}

      {fecha ? (
        <section
          className="mt-4 rounded-xl border border-ink-dim/60 bg-paper p-4"
          role="status"
        >
          <h2 className="text-titulin font-medium text-ink">
            {t("coste.fechaPrometible")}
          </h2>
          {fecha.se_puede_prometer && fecha.fecha ? (
            <p className="mt-2 text-grande text-ink">{fecha.fecha}</p>
          ) : (
            <p className="mt-2 text-dato text-warning">
              {t("coste.noSePuedePrometer")}
            </p>
          )}
          <p className="mt-1 text-dato text-ink-muted">{fecha.porque}</p>
          {fecha.que_hacer ? (
            <p className="mt-1 text-dato text-ink">{fecha.que_hacer}</p>
          ) : null}
        </section>
      ) : null}

      {margen ? (
        <section
          className="mt-6 rounded-xl border border-ink-dim/60 bg-paper p-4"
          role="status"
        >
          <h2 className="text-titulin font-medium text-ink">
            {t("coste.margen")}
          </h2>
          <p
            className={`mt-2 text-grande ${Number(margen.margen) < 0 ? "text-danger" : "text-ink"}`}
          >
            {margen.margen} ({margen.margen_pct} %)
          </p>
          <p className="mt-1 text-dato text-ink-muted">{margen.porque}</p>
          {margen.necesita_aprobacion ? (
            <p className="mt-2 text-dato text-warning">
              {t("coste.necesitaAprobacion")}
            </p>
          ) : null}
          {/* Un margen incompleto no se presenta como el margen: se dice qué
              falta por medir. */}
          {!margen.completo ? (
            <p className="mt-2 text-dato text-warning">{margen.aviso}</p>
          ) : null}
        </section>
      ) : null}

      {capacidad ? (
        <section className="mt-4 rounded-xl border border-ink-dim/60 bg-paper p-4">
          <h2 className="text-titulin font-medium text-ink">
            {t("coste.capacidad")}
          </h2>
          <dl className="mt-2 grid grid-cols-2 gap-y-1 text-dato">
            <dt className="text-ink-muted">{t("coste.libre")}</dt>
            <dd className="text-ink">{capacidad.libre}</dd>
            <dt className="text-ink-muted">{t("coste.enOfertas")}</dt>
            <dd className="text-ink">{capacidad.en_ofertas_abiertas}</dd>
            <dt className="text-ink-muted">{t("coste.siSeGananTodas")}</dt>
            <dd
              className={
                Number(capacidad.libre_si_se_ganan_todas) < 0
                  ? "text-warning"
                  : "text-ink"
              }
            >
              {capacidad.libre_si_se_ganan_todas}
            </dd>
          </dl>
          {capacidad.aviso ? (
            <p
              className={`mt-2 text-dato ${capacidad.sobrevendida ? "text-danger" : "text-warning"}`}
            >
              {capacidad.aviso}
            </p>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
