/**
 * Segmentación y campañas (CRM-07.04.03.09, CRM-07.04.03.10).
 *
 * Dos decisiones:
 *
 * **El recuento de un segmento se pide al servidor y se dice de cuándo es.** Un
 * número sin fecha se lee como el de ahora, y un segmento que se recalcula solo
 * al abrirlo puede llevar semanas sin mirarse. Quien va a mandar un correo a
 * 14.000 personas merece saber si ese 14.000 es de hoy.
 *
 * **Una campaña enseña su estado antes que sus cifras.** Las cifras de una
 * campaña en borrador son cero y se leen como un fracaso; las de una pausada son
 * las de cuando se paró y se leen como las de hoy.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { ErrorApi } from "@/lib/api";
import { listar } from "@/lib/listados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { fecha } from "@/lib/formato";

interface Segmento {
  id: string;
  nombre: string;
  /** Dinámico se recalcula al preguntar; estático es una foto congelada. */
  dinamico: boolean;
  tamano: number | null;
  tamano_at: string | null;
}

interface Campana {
  id: string;
  nombre: string;
  estado: string;
  canal: string;
  /** Agregado sobre los miembros de la campaña, no una columna suya. */
  miembros: number | null;
}

export function Marketing() {
  const { t } = useTranslation();
  const [segmentos, setSegmentos] = useState<Segmento[] | null>(null);
  const [campanas, setCampanas] = useState<Campana[] | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    Promise.all([
      // Por `listar()` y no por `llamar` + `filas`: unos extremos devuelven el
      // array pelado y otros una página `{items}`, y acertar de memoria en cada
      // pantalla es cómo se llega a `map is not a function`. Y con la ruta y la
      // forma juntas, el guardián de contratos las ve: separadas no las veía, y
      // por ahí entraron los seis campos que esta pantalla se inventaba.
      listar<Segmento>("/api/v1/segmentos", { signal: control.signal }),
      listar<Campana>("/api/v1/campanas", { signal: control.signal }),
    ])
      .then(([s, c]) => {
        setSegmentos(s);
        setCampanas(c);
      })
      .catch((e: unknown) => {
        if (e instanceof ErrorApi) setFallo(e);
      });
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!segmentos || !campanas) return <Cargando />;

  return (
    <div className="flex flex-col gap-6">
      <CabeceraPagina
        titulo={t("marketing.titulo")}
        entradilla={t("marketing.entradilla")}
        icono="campaign"
      />

      <section>
        <h2 className="text-sm font-medium text-ink">
          {t("marketing.segmentos")}
        </h2>
        {segmentos.length === 0 ? (
          <Vacio titulo={t("marketing.sinSegmentos")} detalle="" />
        ) : (
          <ul className="lista-acotada mt-2 flex flex-col gap-2 pr-1">
            {segmentos.map((s) => (
              <li
                key={s.id}
                className="flex flex-wrap items-baseline gap-2 rounded-lg border border-ink-dim/40 bg-paper-light p-3"
              >
                <span className="flex-1 text-sm text-ink">{s.nombre}</span>
                <span className="text-2xs text-ink-muted">
                  {t(s.dinamico ? "marketing.dinamico" : "marketing.congelado")}
                </span>
                <span className="font-mono text-2xs text-ink">
                  {s.tamano === null ? t("marketing.sinCalcular") : s.tamano}
                </span>
                {/* La fecha del recuento va SIEMPRE: un número sin fecha se lee
                    como el de ahora, y quien va a mandar un correo a 14.000
                    personas merece saber si ese 14.000 es de hoy. */}
                <span className="text-3xs text-ink-faint">
                  {s.tamano_at
                    ? t("marketing.calculado", {
                        fecha: fecha(s.tamano_at),
                      })
                    : t("marketing.nuncaCalculado")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="text-sm font-medium text-ink">
          {t("marketing.campanas")}
        </h2>
        {campanas.length === 0 ? (
          <Vacio titulo={t("marketing.sinCampanas")} detalle="" />
        ) : (
          <ul className="lista-acotada mt-2 flex flex-col gap-2 pr-1">
            {campanas.map((c) => (
              <li
                key={c.id}
                className="rounded-lg border border-ink-dim/40 bg-paper-light p-3"
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  {/* El estado va primero: las cifras de una campaña en borrador
                      son cero y se leen como un fracaso. */}
                  <span className="rounded bg-paper px-1.5 py-0.5 text-3xs uppercase text-ink-muted">
                    {c.estado}
                  </span>
                  <span className="flex-1 text-sm text-ink">{c.nombre}</span>
                  <span className="text-2xs text-ink-muted">{c.canal}</span>
                </div>
                {/* Sólo los miembros, que es lo que el listado sabe de
                    verdad. Enviados y respuestas se cuentan sobre los envíos y
                    salen del embudo de la campaña: pedirlos por fila sería una
                    consulta por campaña, y pintarlos sin tenerlos es lo que
                    hacía esta pantalla —los tres salían vacíos—. */}
                {c.estado !== "borrador" ? (
                  <p className="mt-1 font-mono text-2xs text-ink-faint">
                    {c.miembros === null
                      ? t("marketing.sinMiembros")
                      : t("marketing.miembros", { miembros: c.miembros })}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
