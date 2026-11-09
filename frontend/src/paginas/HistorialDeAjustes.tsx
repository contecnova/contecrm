/**
 * Historial de la configuración: qué cambió, quién, cuándo, y volver atrás
 * (CRM-00.01.04.02).
 *
 * Cada ajuste que se fija guarda su valor de antes y el de después desde
 * septiembre, y no había pantalla que lo enseñara: medido el 09-11-2026, el
 * historial, el diff y la vuelta atrás sólo se alcanzaban desde una prueba.
 * Aquí se elige un ajuste —los que tienen cambios, sin saberse la clave—, se
 * ve su historial, se comparan dos versiones entrada a entrada, se pregunta qué
 * cambió entre dos fechas y se vuelve al valor de antes de un cambio. Volver es
 * un cambio más: queda en el historial como vuelta atrás y en la auditoría.
 *
 * Comprobado el 09-11-2026 por HTTP contra el servicio: dos cambios de
 * «idioma», historial con antes y después, diff entre fechas, comparación de
 * dos versiones y vuelta atrás que deja UN apunte «vuelta_atras» y la auditoría
 * `ajuste.vuelta_atras`; la versión de otra empresa da 404.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { cn } from "@/lib/utiles";

interface Version {
  id: string;
  clave: string;
  ambito: string;
  ambito_id: string;
  antes: unknown;
  despues: unknown;
  tipo: "cambio" | "vuelta_atras";
  por: string | null;
  motivo: string;
  cuando: string;
}

interface ClaveConHistorial {
  clave: string;
  cambios: number;
  ultimo: string;
}

interface Comparacion {
  clave: string;
  desde: Version;
  hasta: Version;
  cambios: { ruta: string; tipo: string; antes: unknown; despues: unknown }[];
}

interface CambioEnRango {
  clave: string;
  ambito: string;
  antes: unknown;
  despues: unknown;
  cambios: number;
  quien: string[];
}

/** Un valor de ajuste, legible: los estructurados en JSON compacto. */
export function valorLegible(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v === "" ? "«»" : v;
  return JSON.stringify(v);
}

export function HistorialDeAjustes() {
  const { t } = useTranslation();
  const [claves, setClaves] = useState<ClaveConHistorial[] | null>(null);
  const [clave, setClave] = useState("");
  const [versiones, setVersiones] = useState<Version[]>([]);
  const [elegidas, setElegidas] = useState<string[]>([]);
  const [comparacion, setComparacion] = useState<Comparacion | null>(null);
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const [enRango, setEnRango] = useState<CambioEnRango[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");

  const cargar = useCallback(() => {
    const q = clave ? `?clave=${encodeURIComponent(clave)}` : "";
    llamar<{ claves: ClaveConHistorial[]; versiones: Version[] }>(
      `/api/v1/ajustes/versiones${q}`,
    )
      .then((r) => {
        setClaves(r.datos.claves ?? []);
        setVersiones(r.datos.versiones ?? []);
        setFallo(null);
      })
      .catch((e) => setFallo(e));
  }, [clave]);
  useEffect(cargar, [cargar]);

  function alternar(id: string) {
    setComparacion(null);
    setElegidas((xs) =>
      xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id].slice(-2),
    );
  }

  async function comparar() {
    const [a, b] = elegidas;
    if (!a || !b) return;
    try {
      const r = await llamar<Comparacion>(
        `/api/v1/ajustes/versiones/comparar?a=${a}&b=${b}`,
      );
      setComparacion(r.datos);
      setFallo(null);
    } catch (e) {
      setFallo(e);
    }
  }

  async function volver(v: Version) {
    if (
      !window.confirm(
        t("historialAjustes.confirmarVolver", {
          clave: v.clave,
          valor: valorLegible(v.antes),
        }),
      )
    )
      return;
    try {
      await llamar(`/api/v1/ajustes/versiones/${v.id}/volver`, {
        metodo: "POST",
      });
      setAviso(
        t("historialAjustes.vuelto", {
          clave: v.clave,
          valor: valorLegible(v.antes),
        }),
      );
      setElegidas([]);
      setComparacion(null);
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function verRango() {
    if (!desde) return;
    // `desde` escrito en la ruta, no montado aparte: es obligatorio, y así
    // se ve —también el guardián que comprueba que se manda— que va siempre.
    const hastaQ = hasta
      ? `&hasta=${encodeURIComponent(new Date(hasta).toISOString())}`
      : "";
    try {
      const r = await llamar<{ cambios: CambioEnRango[] }>(
        `/api/v1/ajustes/versiones/diferencias?desde=${encodeURIComponent(new Date(desde).toISOString())}${hastaQ}`,
      );
      setEnRango(r.datos.cambios ?? []);
      setFallo(null);
    } catch (e) {
      setFallo(e);
    }
  }

  if (fallo && !claves) return <Fallo error={fallo} />;
  if (!claves) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        icono="history"
        titulo={t("historialAjustes.titulo")}
        entradilla={t("historialAjustes.entradilla")}
      />
      <div role="status" className="mb-3">
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-2">
          {t("historialAjustes.historial")}
        </h2>
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("historialAjustes.ajuste")}
            <select
              className="input-base min-w-[18rem]"
              value={clave}
              onChange={(e) => {
                setClave(e.target.value);
                setElegidas([]);
                setComparacion(null);
              }}
            >
              <option value="">{t("historialAjustes.todos")}</option>
              {claves.map((c) => (
                <option key={c.clave} value={c.clave}>
                  {t("historialAjustes.opcionClave", {
                    clave: c.clave,
                    count: c.cambios,
                  })}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn-secondary"
            disabled={elegidas.length !== 2}
            onClick={() => void comparar()}
          >
            <Icono nombre="difference" tamano="sm" />
            {t("historialAjustes.comparar")}
          </button>
          <p className="text-rotulo text-ink-faint">
            {t("historialAjustes.compararAyuda")}
          </p>
        </div>
        {versiones.length === 0 ? (
          <Vacio titulo={t("historialAjustes.sinCambios")} compacto />
        ) : (
          <Rejilla
            titulo={t("historialAjustes.historial")}
            cabeceras={[
              "",
              t("historialAjustes.cuando"),
              t("historialAjustes.ajuste"),
              t("historialAjustes.ambito"),
              t("historialAjustes.antes"),
              t("historialAjustes.despues"),
              t("historialAjustes.tipo"),
              "",
            ]}
          >
            {versiones.map((v) => (
              <tr
                key={v.id}
                className={cn(
                  "border-b border-ink-dim/30 last:border-0",
                  elegidas.includes(v.id) && "bg-paper-light/40",
                )}
              >
                <Casilla>
                  <input
                    type="checkbox"
                    aria-label={t("historialAjustes.elegir")}
                    checked={elegidas.includes(v.id)}
                    onChange={() => alternar(v.id)}
                  />
                </Casilla>
                <Casilla enUnaLinea>{fechaHora(v.cuando)}</Casilla>
                <Casilla className="font-medium text-ink">{v.clave}</Casilla>
                <Casilla className="text-ink-muted">
                  {t(`historialAjustes.ambitos.${v.ambito}`, {
                    defaultValue: v.ambito,
                  })}
                </Casilla>
                <Casilla className="max-w-[16rem] break-all text-ink-muted">
                  {valorLegible(v.antes)}
                </Casilla>
                <Casilla className="max-w-[16rem] break-all">
                  {valorLegible(v.despues)}
                </Casilla>
                <Casilla>
                  <span
                    className={cn(
                      "chip-dato",
                      v.tipo === "vuelta_atras" && "chip-dato--aviso",
                    )}
                    title={v.motivo || undefined}
                  >
                    {t(`historialAjustes.tipos.${v.tipo}`)}
                  </span>
                </Casilla>
                <Casilla>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => void volver(v)}
                  >
                    <Icono nombre="undo" tamano="sm" />
                    {t("historialAjustes.volver")}
                  </button>
                </Casilla>
              </tr>
            ))}
          </Rejilla>
        )}
      </section>

      {comparacion ? (
        <section className="card mb-4 p-4">
          <h2 className="section-label mb-1">
            {t("historialAjustes.diferencias", { clave: comparacion.clave })}
          </h2>
          <p className="mb-2 text-rotulo text-ink-faint">
            {t("historialAjustes.entre", {
              desde: fechaHora(comparacion.desde.cuando),
              hasta: fechaHora(comparacion.hasta.cuando),
            })}
          </p>
          {comparacion.cambios.length === 0 ? (
            <Vacio titulo={t("historialAjustes.iguales")} compacto />
          ) : (
            <Rejilla
              titulo={t("historialAjustes.diferencias", {
                clave: comparacion.clave,
              })}
              cabeceras={[
                t("historialAjustes.entrada"),
                t("historialAjustes.tipo"),
                t("historialAjustes.antes"),
                t("historialAjustes.despues"),
              ]}
            >
              {comparacion.cambios.map((c) => (
                <tr
                  key={c.ruta || "valor"}
                  className="border-b border-ink-dim/30 last:border-0"
                >
                  <Casilla className="font-medium text-ink">
                    {c.ruta || t("historialAjustes.valorEntero")}
                  </Casilla>
                  <Casilla>{t(`historialAjustes.cambios.${c.tipo}`)}</Casilla>
                  <Casilla className="break-all text-ink-muted">
                    {valorLegible(c.antes)}
                  </Casilla>
                  <Casilla className="break-all">
                    {valorLegible(c.despues)}
                  </Casilla>
                </tr>
              ))}
            </Rejilla>
          )}
        </section>
      ) : null}

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("historialAjustes.rango")}</h2>
        <p className="mb-2 text-rotulo text-ink-faint">
          {t("historialAjustes.rangoAyuda")}
        </p>
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("historialAjustes.desde")}
            <input
              type="datetime-local"
              className="input-base"
              value={desde}
              onChange={(e) => setDesde(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("historialAjustes.hasta")}
            <input
              type="datetime-local"
              className="input-base"
              value={hasta}
              onChange={(e) => setHasta(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="btn-primary"
            disabled={!desde}
            onClick={() => void verRango()}
          >
            {t("historialAjustes.verRango")}
          </button>
        </div>
        {enRango === null ? null : enRango.length === 0 ? (
          <Vacio titulo={t("historialAjustes.nadaEnRango")} compacto />
        ) : (
          <Rejilla
            titulo={t("historialAjustes.rango")}
            cabeceras={[
              t("historialAjustes.ajuste"),
              t("historialAjustes.ambito"),
              t("historialAjustes.antes"),
              t("historialAjustes.despues"),
              t("historialAjustes.nCambios"),
            ]}
          >
            {enRango.map((c) => (
              <tr
                key={`${c.clave}-${c.ambito}`}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla className="font-medium text-ink">{c.clave}</Casilla>
                <Casilla className="text-ink-muted">
                  {t(`historialAjustes.ambitos.${c.ambito}`, {
                    defaultValue: c.ambito,
                  })}
                </Casilla>
                <Casilla className="break-all text-ink-muted">
                  {valorLegible(c.antes)}
                </Casilla>
                <Casilla className="break-all">
                  {valorLegible(c.despues)}
                </Casilla>
                <Casilla enUnaLinea>{c.cambios}</Casilla>
              </tr>
            ))}
          </Rejilla>
        )}
      </section>
    </>
  );
}
