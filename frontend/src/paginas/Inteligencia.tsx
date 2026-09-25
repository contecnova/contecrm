/**
 * Lo que la IA sabe de una cuenta, y por qué (CRM-07.04.03.23).
 *
 * **Antes esta pantalla pedía un JSON a mano.** Un área de texto con
 * `{"presupuestos_abiertos":0.42,…}` dentro y un botón para explicarlo. Eso no
 * es una pantalla: es una calculadora en la que el usuario tiene que ser el
 * modelo. Quien la abría no sabía qué escribir ni qué iba a sacar, y con razón.
 *
 * Ahora se elige una CUENTA de verdad y se enseña su salud con los factores que
 * la suben y los que la bajan. La regla que no se salta: **el número va con sus
 * factores**. Una puntuación sin explicación se mira una vez, no coincide con lo
 * que el comercial sabe de su cliente, y a partir de ahí no se mira más — y hace
 * bien, porque él estuvo en la reunión y el modelo no.
 *
 * Y cuando no hay medida **se dice, con el motivo y con qué hacer**. Es lo que
 * contesta el servidor y es la respuesta correcta: «no se ha medido» no es «va
 * bien», y un cero ahí sería mentira. Hoy es lo que sale casi siempre, porque el
 * cálculo existe y las señales con las que se alimenta no las produce nada
 * todavía: eso está dicho en la propia pantalla en vez de escondido.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { ErrorApi, llamar } from "@/lib/api";

interface Cuenta {
  id: string;
  nombre: string;
}

interface Factor {
  senal?: string;
  factor?: string;
  aporta?: number;
  empuja?: number;
}

interface Salud {
  hay: boolean;
  porque?: string;
  que_hacer?: string;
  puntuacion?: number;
  nivel?: string;
  fiable?: boolean;
  detalle?: Factor[];
  medida_at?: string | null;
}

function nombreDe(f: Factor): string {
  return String(f.senal ?? f.factor ?? "");
}

function pesoDe(f: Factor): number {
  return Number(f.aporta ?? f.empuja ?? 0);
}

export function Inteligencia() {
  const { t } = useTranslation();
  const [cuentas, setCuentas] = useState<Cuenta[] | null>(null);
  const [elegida, setElegida] = useState("");
  const [salud, setSalud] = useState<Salud | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    llamar<Cuenta[]>("/api/v1/accounts?limite=200")
      .then((r) => setCuentas(r.datos))
      .catch((e: unknown) => setFallo(e));
  }, []);

  useEffect(() => {
    if (!elegida) {
      setSalud(null);
      return;
    }
    setFallo(null);
    llamar<Salud>(`/api/v1/calidad-dato/salud/${elegida}`)
      .then((r) => setSalud(r.datos))
      .catch((e: unknown) => {
        setSalud(null);
        if (e instanceof ErrorApi) setFallo(e);
      });
  }, [elegida]);

  const suman = (salud?.detalle ?? []).filter((f) => pesoDe(f) > 0);
  const restan = (salud?.detalle ?? []).filter((f) => pesoDe(f) < 0);

  return (
    <>
      <CabeceraPagina titulo={t("ia.titulo")} entradilla={t("ia.intro")} icono="neurology" />

      <div className="mt-4 max-w-md">
        <label className="label-base" htmlFor="ia-cuenta">
          {t("ia.cuenta")}
        </label>
        <select
          id="ia-cuenta"
          className="input-base"
          value={elegida}
          onChange={(e) => setElegida(e.target.value)}
        >
          <option value="">{cuentas === null ? t("ia.cargando") : t("ia.eligeCuenta")}</option>
          {(cuentas ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.nombre}
            </option>
          ))}
        </select>
      </div>

      {fallo ? <Fallo error={fallo} /> : null}

      {salud && !salud.hay ? (
        /* No se pinta un cero: «no medido» y «va mal» son cosas distintas, y
           confundirlas hace que alguien llame a un cliente que está bien. El
           servidor dice el motivo y qué haría falta; se enseñan los dos. */
        <section className="mt-6 max-w-2xl rounded-xl border border-warning/40 bg-warning/5 p-4">
          <h2 className="flex items-center gap-1.5 text-sm font-medium text-warning">
            <Icono nombre="info" tamano="sm" />
            {t("ia.sinMedir")}
          </h2>
          {salud.porque ? <p className="mt-2 text-2xs text-ink-muted">{salud.porque}</p> : null}
          {salud.que_hacer ? (
            <p className="mt-2 text-2xs text-ink">
              <span className="font-medium">{t("ia.queHacer")}</span> {salud.que_hacer}
            </p>
          ) : null}
        </section>
      ) : null}

      {salud?.hay ? (
        <div className="mt-6 flex max-w-3xl flex-col gap-4">
          <section className="rounded-xl border border-ink-dim/60 bg-paper p-4">
            <p className="text-3xl font-bold tracking-tight text-ink">
              {salud.puntuacion ?? "—"}
            </p>
            <p className="mt-1 text-2xs text-ink-muted">
              {salud.nivel}
              {salud.fiable === false ? ` · ${t("ia.pocoFiable")}` : ""}
            </p>
          </section>

          <div className="grid gap-4 sm:grid-cols-2">
            <section className="rounded-xl border border-ink-dim/60 bg-paper p-4">
              <h2 className="text-xs font-medium text-success">{t("ia.suman")}</h2>
              {suman.length === 0 ? (
                <p className="mt-2 text-2xs text-ink-faint">{t("ia.nadaSuma")}</p>
              ) : (
                <ul className="mt-2 space-y-1">
                  {suman.map((f) => (
                    <li key={nombreDe(f)} className="flex justify-between text-2xs">
                      <span className="text-ink">{nombreDe(f)}</span>
                      <span className="text-success">+{pesoDe(f)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            {/* Los que restan, igual de grandes: sin ellos, una puntuación baja
                parece falta de datos cuando puede ser algo que se arregla. */}
            <section className="rounded-xl border border-ink-dim/60 bg-paper p-4">
              <h2 className="text-xs font-medium text-warning">{t("ia.restan")}</h2>
              {restan.length === 0 ? (
                <p className="mt-2 text-2xs text-ink-faint">{t("ia.nadaResta")}</p>
              ) : (
                <ul className="mt-2 space-y-1">
                  {restan.map((f) => (
                    <li key={nombreDe(f)} className="flex justify-between text-2xs">
                      <span className="text-ink">{nombreDe(f)}</span>
                      <span className="text-warning">{pesoDe(f)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </div>
      ) : null}
    </>
  );
}
