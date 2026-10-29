/**
 * Un periodo de previsión: el número, quién lo tocó y por qué se movió
 * (CRM-03.02.01.03, CRM-03.02.01.04, CRM-03.02.01.05, CRM-03.02.01.08).
 *
 * El módulo listaba los periodos y ahí se acababa. Y un periodo de previsión
 * es justo lo contrario de una fila: es **un número que alguien defiende en un
 * comité**, y lo que hace falta para defenderlo —quién lo ajustó y con qué
 * motivo, si esos ajustes acercaron o alejaron del real, qué se movió desde la
 * última foto— no se alcanzaba desde ninguna pantalla.
 *
 * Se abre por **clave** y no por identificador, como el objeto del modelo y
 * por lo mismo: sus rutas hijas se dirigen por la clave del periodo, y pasarles
 * el identificador las deja en 404.
 *
 * **Lo que no se ha podido convertir sale aparte y no cuenta como cero.** Un
 * total al que le faltan importes en silencio es peor que uno que avisa,
 * porque nadie lo cuestiona. El servidor lo dice y aquí se pinta pegado al
 * número, no en una esquina.
 *
 * **Y el acierto de los ajustes es el panel incómodo a propósito.** Un
 * responsable que ajusta siempre hacia arriba y acierta menos que el número
 * bruto está empeorando la previsión, y sin esta comparación nadie se entera
 * nunca — porque al cerrar el trimestre se mira el real contra el objetivo, no
 * contra lo que se habría previsto sin tocar.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { importe as comoImporte } from "@/lib/formato";

interface Prevision {
  periodo: string;
  moneda: string;
  total: string;
  ponderado: string;
  compromiso: string;
  oportunidades: number;
  por_categoria: Record<
    string,
    { importe: string; ponderado: string; oportunidades: number }
  >;
  sin_tipo_de_cambio: unknown[];
  aviso: string;
}

interface Ajuste {
  id: string;
  ambito: string;
  categoria: string | null;
  bruto: string;
  ajustado: string;
  delta: string;
  motivo: string;
  por: string | null;
}

interface Acierto {
  medible: boolean;
  motivo?: string;
  real?: string;
  bruto?: string;
  ajustado?: string;
  error_sin_ajuste?: string;
  error_con_ajuste?: string;
}

interface Instantanea {
  id: string;
  etiqueta: string;
  tomada_at: string;
  moneda: string;
  totales: Record<string, string>;
}

interface Deslizamiento {
  periodo: string;
  oportunidades_con_cambio_de_fecha: number;
  empujadas: number;
  dias_empujados: number;
  empujadas_mas_de_una_vez: number;
  detalle: { nombre?: string; dias_netos: number; veces: number }[];
}

interface Desglose {
  por: string;
  moneda: string;
  grupos: Record<string, { importe: string; ponderado: string; lineas: number }>;
  grupos_sin_tipo_de_cambio: string[];
}

export function PeriodoDePrevision() {
  const { t } = useTranslation();
  const { clave = "" } = useParams();
  const [prevision, setPrevision] = useState<Prevision | null>(null);
  const [ajustes, setAjustes] = useState<Ajuste[]>([]);
  const [acierto, setAcierto] = useState<Acierto | null>(null);
  const [fotos, setFotos] = useState<Instantanea[]>([]);
  const [deslizamiento, setDeslizamiento] = useState<Deslizamiento | null>(null);
  const [desglose, setDesglose] = useState<Desglose | null>(null);
  const [por, setPor] = useState("familia");
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    // La ruta se escribe ENTERA en cada llamada, no compuesta de una variable.
    // No es repetición por gusto: el gate que exige que toda ruta de la que
    // una pantalla declara la forma esté recorrida por una prueba de servidor
    // lee el código, y de `${base}/ajustes` no puede saber qué ruta es. Un
    // contrato que no se puede leer no se puede vigilar.
    const suya = encodeURIComponent(clave);

    llamar<Prevision>(`/api/v1/forecast/periodos/${suya}`, { signal: control.signal })
      .then((r) => setPrevision(r.datos))
      .catch(salvoCancelacion(setFallo));

    // Cada panel con su fallo: que no haya ajustes no puede dejar sin ver el
    // número, que es a lo que se entra.
    void llamar<Ajuste[]>(`/api/v1/forecast/periodos/${suya}/ajustes`, {
      signal: control.signal,
    })
      .then((r) => setAjustes(r.datos))
      .catch(() => undefined);
    void llamar<Acierto>(`/api/v1/forecast/periodos/${suya}/acierto-ajustes`, {
      signal: control.signal,
    })
      .then((r) => setAcierto(r.datos))
      .catch(() => undefined);
    void llamar<Instantanea[]>(`/api/v1/forecast/periodos/${suya}/instantaneas`, {
      signal: control.signal,
    })
      .then((r) => setFotos(r.datos))
      .catch(() => undefined);
    void llamar<Deslizamiento>(`/api/v1/forecast/periodos/${suya}/deslizamiento`, {
      signal: control.signal,
    })
      .then((r) => setDeslizamiento(r.datos))
      .catch(() => undefined);

    return () => control.abort();
  }, [clave]);

  useEffect(cargar, [cargar]);

  // El desglose se pide aparte porque depende de por qué se agrupa, y cambiar
  // de agrupación no tiene por qué recargar el resto de la pantalla.
  useEffect(() => {
    const control = new AbortController();
    llamar<Desglose>(
      `/api/v1/forecast/periodos/${encodeURIComponent(clave)}/desglose?por=${por}`,
      { signal: control.signal },
    )
      .then((r) => setDesglose(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, [clave, por]);

  if (fallo && !prevision) return <Fallo error={fallo} reintentar={cargar} />;
  if (!prevision) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={prevision.periodo}
        icono="insights"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            <span className="chip-dato">{prevision.moneda}</span>
            <span className="text-2xs text-ink-muted">
              {t("prevision.cuantas", { cuantas: prevision.oportunidades })}
            </span>
          </span>
        }
      />

      <section className="card mb-4 p-4">
        <p className="text-sm font-medium text-ink">
          {t("prevision.total", {
            total: comoImporte(prevision.total, prevision.moneda),
            ponderado: comoImporte(prevision.ponderado, prevision.moneda),
          })}
        </p>
        <p className="mt-1 text-2xs text-ink-muted">
          {t("prevision.compromiso", {
            valor: comoImporte(prevision.compromiso, prevision.moneda),
          })}
        </p>
        {/* El aviso va PEGADO al número, no en una esquina: un total al que le
            faltan importes en silencio es peor que uno que avisa, porque nadie
            lo cuestiona. */}
        {prevision.aviso ? (
          <p className="mt-2 text-2xs text-warning">{prevision.aviso}</p>
        ) : null}

        <ul className="mt-3 divide-y divide-ink-dim/30">
          {Object.entries(prevision.por_categoria).map(([categoria, v]) => (
            <li key={categoria} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
              <span className="text-2xs font-medium text-ink">{categoria}</span>
              <span className="text-2xs text-ink-muted">
                {comoImporte(v.importe, prevision.moneda)}
              </span>
              <span className="text-3xs text-ink-faint">
                {t("prevision.ponderadoCorto", {
                  valor: comoImporte(v.ponderado, prevision.moneda),
                })}
              </span>
              <span className="text-3xs text-ink-faint">
                {t("prevision.cuantas", { cuantas: v.oportunidades })}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <LosAjustes ajustes={ajustes} acierto={acierto} moneda={prevision.moneda} />
        <ElDesglose desglose={desglose} por={por} alCambiar={setPor} />
        <LasFotos fotos={fotos} />
        <LoQueSeHaDeslizado deslizamiento={deslizamiento} />
      </div>
    </>
  );
}

/**
 * Los ajustes del responsable, y si acertaron (CRM-03.02.01.03).
 *
 * El ajuste solo no dice nada: lo que importa es si acercó al real. Un
 * responsable que ajusta siempre hacia arriba y acierta menos que el número
 * bruto está empeorando la previsión, y nadie se entera porque al cerrar se
 * compara el real con el objetivo, no con lo que se habría previsto sin tocar.
 */
function LosAjustes({
  ajustes,
  acierto,
  moneda,
}: {
  ajustes: Ajuste[];
  acierto: Acierto | null;
  moneda: string;
}) {
  const { t } = useTranslation();
  const mejoro =
    acierto?.medible &&
    Number(acierto.error_con_ajuste) < Number(acierto.error_sin_ajuste);

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("prevision.ajustes")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">{t("prevision.ajustesAyuda")}</p>
      {ajustes.length === 0 ? (
        <Vacio titulo={t("prevision.sinAjustes")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {ajustes.map((a) => (
            <li key={a.id} className="py-1.5">
              <div className="flex flex-wrap items-baseline gap-x-3 text-2xs">
                <span className="font-medium text-ink">
                  {comoImporte(a.bruto, moneda)} → {comoImporte(a.ajustado, moneda)}
                </span>
                <span className={Number(a.delta) >= 0 ? "chip-dato" : "chip-dato chip-dato--no"}>
                  {a.delta}
                </span>
                <span className="text-3xs text-ink-faint">{a.ambito}</span>
                {a.categoria ? <span className="chip-dato">{a.categoria}</span> : null}
              </div>
              {/* El motivo es la mitad del ajuste: sin él no se puede juzgar. */}
              <p className="text-3xs text-ink-muted">{a.motivo}</p>
            </li>
          ))}
        </ul>
      )}

      {acierto ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-2">
          <h3 className="text-2xs font-medium text-ink">{t("prevision.acierto")}</h3>
          {!acierto.medible ? (
            <p className="text-3xs text-ink-faint">{acierto.motivo}</p>
          ) : (
            <>
              <p className="mt-1 text-2xs text-ink-muted">
                {t("prevision.contraReal", {
                  real: comoImporte(acierto.real ?? "0", moneda),
                  bruto: comoImporte(acierto.bruto ?? "0", moneda),
                  ajustado: comoImporte(acierto.ajustado ?? "0", moneda),
                })}
              </p>
              <p className={mejoro ? "mt-1 text-2xs text-success" : "mt-1 text-2xs text-danger"}>
                {mejoro
                  ? t("prevision.ajustarAcerco", { error: acierto.error_con_ajuste })
                  : t("prevision.ajustarAlejo", {
                      conAjuste: acierto.error_con_ajuste,
                      sinAjuste: acierto.error_sin_ajuste,
                    })}
              </p>
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}

/**
 * Por producto, por familia o por tipo de ingreso (CRM-03.02.01.08).
 *
 * Lo que no se ha podido convertir se dice **por grupo**: un desglose en el
 * que falta una familia entera por un tipo de cambio que no estaba se lee como
 * «esa familia no vendió nada».
 */
function ElDesglose({
  desglose,
  por,
  alCambiar,
}: {
  desglose: Desglose | null;
  por: string;
  alCambiar: (v: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("prevision.desglose")}</h2>
      <label htmlFor="desglose-por" className="text-2xs text-ink-muted">
        {t("prevision.agruparPor")}
        <select
          id="desglose-por"
          value={por}
          onChange={(e) => alCambiar(e.target.value)}
          className="input-sm ml-2 inline-block w-auto"
        >
          <option value="familia">{t("prevision.porFamilia")}</option>
          <option value="producto">{t("prevision.porProducto")}</option>
          <option value="tipo_ingreso">{t("prevision.porTipo")}</option>
        </select>
      </label>
      {!desglose || Object.keys(desglose.grupos).length === 0 ? (
        <div className="mt-2">
          <Vacio titulo={t("prevision.sinDesglose")} compacto />
        </div>
      ) : (
        <ul className="mt-2 divide-y divide-ink-dim/30">
          {Object.entries(desglose.grupos).map(([grupo, v]) => (
            <li key={grupo} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
              <span className="text-2xs font-medium text-ink">{grupo}</span>
              <span className="text-2xs text-ink-muted">
                {comoImporte(v.importe, desglose.moneda)}
              </span>
              <span className="text-3xs text-ink-faint">
                {t("prevision.lineas", { cuantas: v.lineas })}
              </span>
            </li>
          ))}
        </ul>
      )}
      {desglose && desglose.grupos_sin_tipo_de_cambio.length > 0 ? (
        <p className="mt-2 text-3xs text-warning">
          {t("prevision.gruposSinCambio", {
            grupos: desglose.grupos_sin_tipo_de_cambio.join(", "),
          })}
        </p>
      ) : null}
    </section>
  );
}

/**
 * Las fotos del periodo (CRM-03.02.01.04).
 *
 * Una previsión sin fotos no se puede comparar consigo misma, y «¿cómo
 * íbamos hace tres semanas?» es la pregunta de todos los lunes. Cada foto va
 * con **cuándo se tomó**: una etiqueta sin fecha no sirve para ordenar nada.
 */
function LasFotos({ fotos }: { fotos: Instantanea[] }) {
  const { t } = useTranslation();
  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("prevision.fotos")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">{t("prevision.fotosAyuda")}</p>
      {fotos.length === 0 ? (
        <Vacio titulo={t("prevision.sinFotos")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {fotos.map((f) => {
            const total = Object.entries(f.totales ?? {})
              .filter(([k]) => !k.startsWith("_"))
              .reduce((n, [, v]) => n + Number(v), 0);
            return (
              <li key={f.id} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
                <span className="text-2xs font-medium text-ink">{f.etiqueta}</span>
                <time className="text-3xs text-ink-faint" dateTime={f.tomada_at}>
                  {f.tomada_at.slice(0, 10)}
                </time>
                <span className="text-2xs text-ink-muted">
                  {comoImporte(String(total), f.moneda)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/**
 * Cuánto se ha movido el periodo (CRM-03.02.01.05).
 *
 * **Lo que importa no es cuántas se movieron: es cuántas se han movido MÁS DE
 * UNA VEZ.** Una fecha que se empuja dos trimestres seguidos no es un retraso,
 * es una venta que no existe, y en el total de «oportunidades con cambio de
 * fecha» se confunde con la que se movió una semana.
 */
function LoQueSeHaDeslizado({
  deslizamiento,
}: {
  deslizamiento: Deslizamiento | null;
}) {
  const { t } = useTranslation();
  if (!deslizamiento) return null;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("prevision.deslizamiento")}</h2>
      {deslizamiento.oportunidades_con_cambio_de_fecha === 0 ? (
        <Vacio titulo={t("prevision.sinDeslizamiento")} compacto />
      ) : (
        <>
          <p className="text-2xs text-ink">
            {t("prevision.empujadas", {
              cuantas: deslizamiento.empujadas,
              dias: deslizamiento.dias_empujados,
            })}
          </p>
          {deslizamiento.empujadas_mas_de_una_vez > 0 ? (
            <p className="mt-1 text-2xs text-danger">
              {t("prevision.masDeUnaVez", {
                cuantas: deslizamiento.empujadas_mas_de_una_vez,
              })}
            </p>
          ) : null}
          <ul className="mt-2 divide-y divide-ink-dim/30">
            {deslizamiento.detalle.slice(0, 10).map((d, i) => (
              <li
                key={`${d.nombre ?? ""}-${i}`}
                className="flex flex-wrap items-baseline gap-x-3 py-1.5"
              >
                <span className="text-2xs text-ink">{d.nombre ?? "—"}</span>
                <span className="chip-dato chip-dato--no">
                  {t("prevision.dias", { dias: d.dias_netos })}
                </span>
                {d.veces > 1 ? (
                  <span className="chip-dato chip-dato--no">
                    {t("prevision.veces", { veces: d.veces })}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
