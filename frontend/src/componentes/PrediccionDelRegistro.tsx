/**
 * Lo que dicen los modelos entrenados con el histórico sobre ESTE registro
 * (CRM-02.01.02.02, CRM-05.02.01.02, CRM-05.02.01.03).
 *
 * El número va siempre con lo que lo sube y lo que lo baja: una puntuación sin
 * porqué se mira una vez, no coincide con lo que el comercial sabe de su
 * cliente y ya no se mira más. Y cuando no hay modelo publicado se dice por
 * qué —no hay bastantes datos, o no superó el mínimo— en vez de enseñar un
 * 50 % que parece un empate y es «no lo sé».
 *
 * El registro se lee en el servidor con los permisos de quien mira, por su id:
 * aquí no se teclea ningún rasgo.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { llamar, salvoCancelacion } from "@/lib/api";
import { cifra, fecha, importe } from "@/lib/formato";
import { cn } from "@/lib/utiles";

interface Factor {
  variable: string;
  etiqueta: string;
  valor: string | number;
  aporta: number;
}

interface Recomendacion {
  producto: string;
  nombre: string;
  porque: string;
}

export interface Prediccion {
  tipo: string;
  hay: boolean;
  porque?: string;
  valor?: number;
  minimo?: number | null;
  maximo?: number | null;
  factores?: Factor[];
  modelo?: {
    version: number;
    metricas: Record<string, number | null>;
    entrenado_at?: string | null;
  };
  declarado?: number;
  moneda?: string;
  fecha_prevista?: string;
  pasada_de_lo_habitual?: boolean;
  declarada?: string | null;
  recomendaciones?: Recomendacion[];
}

interface Respuesta {
  predicciones: Prediccion[];
  porque?: string;
}

const pct = (v: number | undefined) => `${Math.round((v ?? 0) * 100)} %`;

function Valor({ p }: { p: Prediccion }) {
  const { t } = useTranslation();
  if (p.tipo === "importe") {
    return (
      <>
        <span className="text-titulo font-medium text-ink">
          {importe(p.valor, p.moneda || "EUR")}
        </span>
        {p.minimo != null && p.maximo != null ? (
          <span className="text-rotulo text-ink-faint">
            {t("prediccion.entre", {
              min: importe(p.minimo, p.moneda || "EUR"),
              max: importe(p.maximo, p.moneda || "EUR"),
            })}
          </span>
        ) : null}
        {p.declarado != null ? (
          <span className="text-rotulo text-ink-muted">
            {t("prediccion.declarado", {
              valor: importe(p.declarado, p.moneda || "EUR"),
            })}
          </span>
        ) : null}
      </>
    );
  }
  if (p.tipo === "fecha_cierre") {
    return (
      <>
        <span className="text-titulo font-medium text-ink">
          {fecha(p.fecha_prevista)}
        </span>
        <span className="text-rotulo text-ink-faint">
          {t("prediccion.dias", { n: cifra(Math.round(p.valor ?? 0)) })}
        </span>
        {p.declarada ? (
          <span className="text-rotulo text-ink-muted">
            {t("prediccion.declarada", { fecha: fecha(p.declarada) })}
          </span>
        ) : null}
        {p.pasada_de_lo_habitual ? (
          <span className="chip-dato chip-dato--aviso">
            {t("prediccion.pasada")}
          </span>
        ) : null}
      </>
    );
  }
  return (
    <span className="text-titulo font-medium text-ink">{pct(p.valor)}</span>
  );
}

function Factores({ factores }: { factores: Factor[] }) {
  const { t } = useTranslation();
  const suman = factores.filter((f) => f.aporta > 0);
  const restan = factores.filter((f) => f.aporta < 0);
  if (factores.length === 0) return null;
  return (
    <div className="mt-1 flex flex-col gap-1">
      {[
        ["suman", suman],
        ["restan", restan],
      ].map(([clave, lista]) =>
        (lista as Factor[]).length ? (
          <div key={clave as string}>
            <p className="text-rotulo text-ink-faint">
              {t(`prediccion.${clave as string}`)}
            </p>
            <ul className="flex flex-wrap gap-1">
              {(lista as Factor[]).map((f) => (
                <li
                  key={f.variable}
                  className={cn(
                    "chip-dato",
                    f.aporta > 0 ? "chip-dato--si" : "chip-dato--mal",
                  )}
                  title={t("prediccion.aporta", { n: f.aporta.toFixed(2) })}
                >
                  {f.etiqueta}:{" "}
                  {typeof f.valor === "number" ? cifra(f.valor) : f.valor}
                </li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
    </div>
  );
}

function Metrica({ p }: { p: Prediccion }) {
  const { t } = useTranslation();
  const m = p.modelo?.metricas ?? {};
  const medida =
    m.auc != null
      ? t("prediccion.auc", { n: cifra(Number(m.auc)) })
      : m.mae != null
        ? t("prediccion.mae", { n: cifra(m.mae) })
        : m.acierto_top != null
          ? t("prediccion.aciertoTop", { n: pct(Number(m.acierto_top)) })
          : "";
  return (
    <p className="text-rotulo text-ink-faint">
      {t("prediccion.modelo", {
        version: p.modelo?.version,
        medida,
        muestras: m.muestras ?? 0,
      })}
    </p>
  );
}

export function PrediccionDelRegistro({
  objeto,
  id,
}: {
  objeto: "lead" | "oportunidad" | "cuenta";
  id: string;
}) {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Respuesta | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [cargando, setCargando] = useState(false);

  const cargar = useCallback(
    (recalcular: boolean, signal?: AbortSignal) => {
      setCargando(true);
      llamar<Respuesta>(
        `/api/v1/ia/predictivo/${objeto}/${id}${recalcular ? "?recalcular=true" : ""}`,
        { signal },
      )
        .then((r) => {
          setDatos(r.datos);
          setFallo(null);
        })
        .catch(salvoCancelacion(setFallo))
        .finally(() => setCargando(false));
    },
    [objeto, id],
  );

  useEffect(() => {
    const control = new AbortController();
    cargar(false, control.signal);
    return () => control.abort();
  }, [cargar]);

  return (
    <section className="card mb-4 p-4" aria-label={t("prediccion.titulo")}>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2 className="section-label flex items-center gap-1">
          <Icono nombre="model_training" tamano="sm" className="text-accent" />
          {t("prediccion.titulo")}
        </h2>
        <button
          type="button"
          className="btn-link"
          disabled={cargando}
          onClick={() => cargar(true)}
        >
          {t("prediccion.recalcular")}
        </button>
      </div>
      <div role="status" className="flex flex-col gap-3">
        {fallo ? <Fallo error={fallo} /> : null}
        {!datos && !fallo ? (
          <p className="text-dato text-ink-faint">{t("prediccion.cargando")}</p>
        ) : null}
        {datos?.porque ? (
          <p className="text-dato text-ink-muted">{datos.porque}</p>
        ) : null}
        {(Array.isArray(datos?.predicciones) ? datos.predicciones : []).map(
          (p) => (
            <div key={p.tipo} className="flex flex-col gap-1">
              <p className="text-rotulo uppercase text-ink-muted">
                {t(`prediccion.tipos.${p.tipo}`, { defaultValue: p.tipo })}
              </p>
              {!p.hay ? (
                <p className="text-dato text-ink-faint">{p.porque}</p>
              ) : p.tipo === "siguiente_oferta" ? (
                <ul className="flex flex-col gap-1">
                  {(p.recomendaciones ?? []).map((r) => (
                    <li key={r.producto} className="text-dato">
                      <span className="font-medium text-ink">{r.nombre}</span>{" "}
                      <span className="text-ink-faint">{r.porque}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <>
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <Valor p={p} />
                  </div>
                  <Factores factores={p.factores ?? []} />
                  <Metrica p={p} />
                </>
              )}
            </div>
          ),
        )}
      </div>
    </section>
  );
}
