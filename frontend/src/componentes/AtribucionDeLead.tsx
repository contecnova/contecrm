/**
 * A qué campañas se atribuye la venta de este lead (CRM-02.02.01.06).
 *
 * `GET /atribucion/leads/{id}` era real y no tenía pantalla. Aquí, en la ficha
 * del lead: el importe sale **de su oportunidad** —si se convirtió— y se puede
 * cambiar para ver el reparto de otra cifra; el modelo se elige, y el basado en
 * datos (cadena de Markov con efecto de eliminación sobre los caminos reales
 * del tenant) dice sobre cuántos caminos y conversiones se calculó.
 *
 * Verificado pulsando el 09-11-2026: con un lead sin toques en la ventana el
 * panel lo dice en vez de repartir a la campaña más reciente.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";

const MODELOS = [
  "data_driven",
  "primer_toque",
  "ultimo_toque",
  "lineal",
  "en_u",
  "en_w",
  "decaimiento",
] as const;

interface Reparto {
  campana: string;
  peso: number;
  importe: string;
}

interface Atribucion {
  toques: number;
  sin_toques: boolean;
  aviso: string;
  modelos: Record<string, Reparto[]>;
  data_driven: {
    medible: boolean;
    caminos?: number;
    convertidos?: number;
    aviso: string;
  } | null;
}

export function AtribucionDeLead({
  leadId,
  lead,
}: {
  leadId: string;
  lead: Record<string, unknown> | null;
}) {
  const { t } = useTranslation();
  const [modelo, setModelo] = useState<string>("data_driven");
  const [importe, setImporte] = useState("");
  const [deOportunidad, setDeOportunidad] = useState(false);
  const [datos, setDatos] = useState<Atribucion | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  // El importe de su oportunidad, si se convirtió.
  const oportunidad = lead?.oportunidad_id;
  useEffect(() => {
    if (typeof oportunidad !== "string" || !oportunidad) return;
    llamar<{ importe?: string | number | null }>(
      `/api/v1/opportunities/${oportunidad}`,
    )
      .then((r) => {
        if (r.datos?.importe != null) {
          setImporte(String(r.datos.importe));
          setDeOportunidad(true);
        }
      })
      .catch(() => setDeOportunidad(false));
  }, [oportunidad]);

  useEffect(() => {
    const cifra = importe.trim() || "0";
    const control = new AbortController();
    llamar<Atribucion>(
      `/api/v1/atribucion/leads/${leadId}?importe=${encodeURIComponent(cifra)}&modelo=${modelo}`,
      { signal: control.signal },
    )
      .then((r) => {
        setDatos(r.datos);
        setFallo(null);
      })
      .catch((e) => {
        if (!control.signal.aborted) setFallo(e);
      });
    return () => control.abort();
  }, [leadId, modelo, importe]);

  const reparto = Array.isArray(datos?.modelos?.[modelo])
    ? datos!.modelos[modelo]!
    : [];
  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">{t("mk.atribucion.titulo")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("mk.atribucion.ayuda")}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-dato text-ink-muted" htmlFor="mk-modelo">
          {t("mk.atribucion.modelo")}
        </label>
        <select
          id="mk-modelo"
          className="input-base w-auto"
          value={modelo}
          onChange={(e) => setModelo(e.target.value)}
        >
          {MODELOS.map((m) => (
            <option key={m} value={m}>
              {t(`mk.atribucion.modelos.${m}`)}
            </option>
          ))}
        </select>
        <label className="text-dato text-ink-muted" htmlFor="mk-importe">
          {t("mk.atribucion.importe")}
        </label>
        <input
          id="mk-importe"
          className="input-base w-32"
          inputMode="decimal"
          value={importe}
          onChange={(e) => {
            setImporte(e.target.value);
            setDeOportunidad(false);
          }}
        />
        <span className="text-rotulo text-ink-faint">
          {deOportunidad
            ? t("mk.atribucion.deSuOportunidad")
            : t("mk.atribucion.tecleado")}
        </span>
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      <div role="status" className="mt-2">
        {datos ? (
          <p className="text-dato text-ink-muted">
            {t("mk.atribucion.toques", { cuantos: datos.toques })}{" "}
            {datos.sin_toques ? datos.aviso : null}
          </p>
        ) : null}
        {modelo === "data_driven" && datos?.data_driven ? (
          <p className="text-rotulo text-ink-faint">
            {datos.data_driven.caminos != null
              ? t("mk.atribucion.sobreCaminos", {
                  caminos: datos.data_driven.caminos,
                  convertidos: datos.data_driven.convertidos ?? 0,
                })
              : null}{" "}
            {datos.data_driven.aviso}
          </p>
        ) : null}
      </div>
      {reparto.length > 0 ? (
        <Rejilla
          titulo={t("mk.atribucion.titulo")}
          compacta
          cabeceras={[
            t("mk.atribucion.campana"),
            t("mk.atribucion.peso"),
            t("mk.atribucion.importe"),
          ]}
        >
          {reparto.map((r) => (
            <tr
              key={r.campana}
              className="border-b border-ink-dim/30 last:border-0"
            >
              <Casilla>{r.campana}</Casilla>
              <Casilla className="font-mono">
                {(r.peso * 100).toFixed(1)} %
              </Casilla>
              <Casilla className="font-mono">{r.importe}</Casilla>
            </tr>
          ))}
        </Rejilla>
      ) : null}
    </section>
  );
}
